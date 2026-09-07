"""提前续期门锁授权；网络等待期间不占用数据库事务。"""
import json
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update, inspect
from fastapi import HTTPException

from .access_models import LockCredential, CredentialRefresh, AccessAudit
from .access_credentials import client, secret_box
from .ttlock_client import LockError, ReauthorizationRequired


def schema_ready(db):
    return inspect(db.get_bind()).has_table("access_credential_refresh")


def refresh_store(sessions, store_id):
    """只在临近到期时续期。未知结果不重放旧刷新令牌，交由管理员重新授权。"""
    now = datetime.utcnow()
    with sessions() as db:
        if not schema_ready(db):
            raise HTTPException(503, "授权续期数据表尚未初始化，请检查数据库配置并重新启动后端")
        locked = db.execute(update(LockCredential).where(LockCredential.store_id == store_id)
            .values(updated_at=LockCredential.updated_at))
        if not locked.rowcount:
            raise HTTPException(409, "请先配置该门店的通通锁授权")
        row = db.get(LockCredential, store_id)
        state = db.get(CredentialRefresh, store_id)
        if state is None:
            state = CredentialRefresh(store_id=store_id, credential_version=row.version, status="ready")
            db.add(state)
        if state.credential_version != row.version:
            state.credential_version = row.version
            state.status, state.safe_error = "ready", None
            state.lease_token = state.lease_until = None
        if state.status == "refreshing":
            if not state.lease_until or state.lease_until <= now:
                # 旧进程可能已拿到新令牌。租约过期不是再次刷新旧令牌的依据。
                state.status = "unknown"
                state.safe_error = "上次授权续期未完成，结果无法确认，请重新授权"
                state.lease_token = state.lease_until = None
            db.commit()
            return state.status
        if state.status in {"unknown", "reauthorize"}:
            return state.status
        box = secret_box()
        bundle = json.loads(box.decrypt(row.encrypted_bundle, f"store:{store_id}:credential"))
        if int(bundle["expires_at"]) > int(time.time()) + 300:
            db.commit()
            return "ready"
        adapter = client(row.region, bundle["client_id"])
        lease = str(uuid.uuid4())
        version = row.version
        state.status, state.safe_error = "refreshing", None
        state.lease_token, state.lease_until = lease, now + timedelta(seconds=60)
        state.last_attempt_at = now
        db.commit()
    try:
        tokens = adapter.refresh(bundle["client_secret"], bundle["refresh_token"])
        if tokens.expires_at <= int(time.time()) + 60:
            raise ReauthorizationRequired("授权有效期过短，请重新授权")
        bundle.update(access_token=tokens.access_token, refresh_token=tokens.refresh_token,
                      expires_at=tokens.expires_at)
        encrypted = box.encrypt(json.dumps(bundle), f"store:{store_id}:credential")
        with sessions() as db:
            # 令牌轮换不改变账号授权版本，待确认的发码申请仍能核对原账号。
            locked = db.execute(update(LockCredential).where(LockCredential.store_id == store_id,
                LockCredential.version == version).values(updated_at=LockCredential.updated_at))
            if not locked.rowcount:
                db.rollback()
                return "superseded"
            state = db.get(CredentialRefresh, store_id)
            if not state or state.status != "refreshing" or state.lease_token != lease:
                db.rollback()
                return "superseded"
            db.get(LockCredential, store_id).encrypted_bundle = encrypted
            state.status, state.safe_error = "ready", None
            state.lease_token = state.lease_until = None
            state.last_success_at = datetime.utcnow()
            db.add(AccessAudit(store_id=store_id, actor_id=db.get(LockCredential, store_id).updated_by,
                               action="credential_refreshed"))
            db.commit()
        return "ready"
    except Exception as exc:
        # 不保存异常正文，上游内容可能包含应用密钥或令牌。
        status = "reauthorize" if isinstance(exc, ReauthorizationRequired) else "unknown"
        message = ("授权续期被拒绝，请重新授权" if status == "reauthorize"
                   else "授权续期结果无法确认，请重新授权；请勿重复使用旧刷新令牌")
        with sessions() as db:
            db.execute(update(CredentialRefresh).where(CredentialRefresh.store_id == store_id,
                CredentialRefresh.credential_version == version, CredentialRefresh.lease_token == lease,
                CredentialRefresh.status == "refreshing").values(status=status, safe_error=message,
                    lease_token=None, lease_until=None))
            db.commit()
        return status


def refresh_due(sessions):
    with sessions() as db:
        if not schema_ready(db):
            return
        ids = db.scalars(select(LockCredential.store_id).order_by(LockCredential.store_id)).all()
    for store_id in ids:
        try:
            refresh_store(sessions, store_id)
        except (LockError, HTTPException, ValueError, KeyError):
            # 某家门店配置损坏不影响其他门店；管理页负责提示配置问题。
            continue
