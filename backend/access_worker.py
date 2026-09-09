"""恢复未确认的发码请求；数据库租约保证多进程不会重复处理。"""
import os
import threading
from datetime import datetime, timedelta
from sqlalchemy import select, inspect
from .database import SessionLocal
from .access_models import PasscodeRequest
from .area_billing import resume
from .access_refresh import refresh_due


def recover_once():
    if os.getenv("TTLOCK_REAL_ENABLED", "false").lower() != "true":
        return
    with SessionLocal() as db:
        if not inspect(db.get_bind()).has_table("access_consumption_segments"):
            return
        now = datetime.utcnow()
        ids = db.scalars(select(PasscodeRequest.id).where(
            PasscodeRequest.source.in_(["automatic", "switch"]),
            PasscodeRequest.status.in_(["pending", "issuing", "unknown", "review"]),
            PasscodeRequest.updated_at < now - timedelta(seconds=60),
            PasscodeRequest.created_at > now - timedelta(minutes=5),
        ).order_by(PasscodeRequest.created_at).limit(100)).all()
    for request_id in ids:
        with SessionLocal() as db:
            try:
                resume(db, request_id)
            except Exception:
                # 保留原申请及占用，管理端可继续核对。不输出可能带凭证的异常正文。
                db.rollback()


def start_worker():
    stop = threading.Event()
    def run():
        while not stop.is_set():
            try:
                from .bookings import expire_sessions
                with SessionLocal() as db:
                    if expire_sessions(db):
                        db.commit()
                if os.getenv("TTLOCK_REAL_ENABLED", "false").lower() == "true":
                    refresh_due(SessionLocal)
                recover_once()
            except Exception:
                pass
            if stop.wait(30):
                break
    thread = threading.Thread(target=run, name="门锁结果核对", daemon=True)
    thread.start()
    return stop, thread
