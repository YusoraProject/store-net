"""持久化发码记录，不直接依赖具体计费模型。

接入约定：finalize(db, request) 创建消费并返回整数编号，但不能提交事务。
授权凭证在数据库事务外准备；用户权限和门店范围由接口层校验。
"""
import uuid
import time
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.access_models import (
    PasscodeRequest, MemberOccupancy, AccessAudit, ConsumptionArea, LockCredential,
)
from backend.ttlock_client import LockError, OutcomeUnknown


TERMINAL = {"ready", "failed", "cancelled"}
PENDING = {"pending", "issuing", "unknown", "review"}


def reserve(session_factory, *, store_id, area_id, operator_id, recipient_id,
            idempotency_key, lock_id, credential_version, password_version,
            start_ms, source, pricing_json=None):
    if source not in {"manual", "automatic"}:
        raise LockError("发码来源无效")
    if source == "automatic" and recipient_id is None:
        raise LockError("自动发码必须指定会员")
    if not idempotency_key or len(idempotency_key) > 80:
        raise LockError("发码请求标识无效")
    with session_factory() as db:
        locked = db.execute(update(LockCredential).where(
            LockCredential.store_id == store_id,
            LockCredential.version == credential_version,
        ).values(updated_at=datetime.utcnow()))
        if locked.rowcount != 1:
            db.rollback()
            raise LockError("门锁授权已变化或不存在，请刷新后重试")
        existing = db.scalar(select(PasscodeRequest).where(
            PasscodeRequest.operator_id == operator_id,
            PasscodeRequest.idempotency_key == idempotency_key))
        if existing:
            if (existing.store_id, existing.area_id, existing.recipient_id, existing.source) != (
                    store_id, area_id, recipient_id, source):
                raise LockError("同一请求标识不能用于不同的发码操作")
            return existing.id
        request_id = str(uuid.uuid4())
        row = PasscodeRequest(id=request_id, store_id=store_id, area_id=area_id,
            pricing_json=pricing_json,
            operator_id=operator_id, recipient_id=recipient_id,
            idempotency_key=idempotency_key, remote_name="net-" + uuid.uuid4().hex,
            source=source, status="pending", lock_id=str(lock_id),
            credential_version=credential_version, password_version=password_version,
            start_ms=str(start_ms), end_ms=str(start_ms + 21_600_000))
        db.add(row)
        if source == "automatic":
            db.add(MemberOccupancy(user_id=recipient_id, area_id=area_id, request_id=request_id))
        try:
            db.commit()
            return request_id
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(PasscodeRequest).where(
                PasscodeRequest.operator_id == operator_id,
                PasscodeRequest.idempotency_key == idempotency_key))
            if existing and (existing.store_id, existing.area_id, existing.recipient_id, existing.source) == (
                    store_id, area_id, recipient_id, source):
                return existing.id
            raise LockError("该会员已有进行中或正在确认的上机请求，请先处理原记录") from None


def claim(session_factory, request_id, *, now=None):
    """通过数据库条件更新领取任务，多进程不能只靠内存锁。"""
    now = now or datetime.utcnow()
    token = str(uuid.uuid4())
    with session_factory() as db:
        row = db.get(PasscodeRequest, request_id)
        if not row:
            raise LockError("发码请求不存在")
        status = row.status
        if status in TERMINAL:
            return None
        if row.lease_until and row.lease_until > now:
            return None
        # 原进程可能已经发码；接管超时任务时只能先核对，不能直接重发。
        mode = "issue" if status == "pending" else "reconcile"
        result = db.execute(update(PasscodeRequest).where(
            PasscodeRequest.id == request_id,
            PasscodeRequest.status == status,
            (PasscodeRequest.lease_until.is_(None)) | (PasscodeRequest.lease_until <= now),
        ).values(status="issuing" if mode == "issue" else "unknown",
                 lease_token=token, lease_until=now + timedelta(seconds=60),
                 updated_at=now))
        db.commit()
        return (token, mode) if result.rowcount == 1 else None


def _finish_error(session_factory, request_id, lease_token, *, uncertain):
    with session_factory() as db:
        changed = db.execute(update(PasscodeRequest).where(
            PasscodeRequest.id == request_id,
            PasscodeRequest.lease_token == lease_token,
            PasscodeRequest.status.in_(["issuing", "unknown"]),
        ).values(updated_at=datetime.utcnow()))
        if changed.rowcount != 1:
            db.rollback()
            return
        row = db.get(PasscodeRequest, request_id)
        row.status = "review" if uncertain else "failed"
        row.safe_error = ("暂不能确认发码结果，可能已有密码产生，请联系店长，勿重复创建"
                          if uncertain else "发码失败，未开始计费，请检查门锁授权")
        row.lease_until = None
        row.lease_token = None
        row.updated_at = datetime.utcnow()
        if not uncertain and row.source == "automatic":
            occupancy = db.get(MemberOccupancy, row.recipient_id)
            if occupancy and occupancy.request_id == row.id and occupancy.consumption_id is None:
                db.delete(occupancy)
        if not uncertain and row.source == "switch":
            row.safe_error = "换区发码失败，仍按原区域计费，请检查门锁授权"
            occupancy = db.get(MemberOccupancy, row.recipient_id)
            if occupancy and occupancy.pending_request_id == row.id:
                occupancy.pending_request_id = None
        db.commit()


def process(session_factory, request_id, *, client, token, box, finalize=None):
    lease = claim(session_factory, request_id)
    if not lease:
        return
    lease_token, mode = lease
    # 取出请求参数后关闭读事务，网络调用不占用数据库事务。
    with session_factory() as db:
        row = db.get(PasscodeRequest, request_id)
        lock_id, version, name, start_ms = (
            row.lock_id, row.password_version, row.remote_name, int(row.start_ms))
    try:
        if mode == "issue":
            result = client.one_time(token, lock_id, version, name, start_ms=start_ms)
        else:
            result = client.find_created(token, lock_id, name)
    except OutcomeUnknown:
        _finish_error(session_factory, request_id, lease_token, uncertain=True)
        return
    except LockError:
        # 核对接口失败并不能说明原密码没有生成。
        _finish_error(session_factory, request_id, lease_token, uncertain=mode != "issue")
        return

    # 远端已成功时，本地失败也必须保留后续核对机会。
    try:
        with session_factory() as db:
            # 条件更新也能在SQLite下取得写锁，不能只依赖FOR UPDATE。
            changed = db.execute(update(PasscodeRequest).where(
                PasscodeRequest.id == request_id,
                PasscodeRequest.lease_token == lease_token,
                PasscodeRequest.status.in_(["issuing", "unknown"]),
            ).values(updated_at=datetime.utcnow()))
            if changed.rowcount != 1:
                db.rollback()
                return
            row = db.get(PasscodeRequest, request_id)
            row.encrypted_password = box.encrypt(result.password,
                f"store:{row.store_id}:request:{row.id}:password")
            row.remote_id = result.remote_id
            row.start_ms, row.end_ms = str(result.start_ms), str(result.end_ms)
            if row.source in {"automatic", "switch"}:
                if finalize is None:
                    raise RuntimeError("缺少同事务创建消费的回调")
                occupancy = db.get(MemberOccupancy, row.recipient_id)
                if not occupancy or (occupancy.pending_request_id if row.source == "switch" else occupancy.request_id) != row.id:
                    raise RuntimeError("会员上机占用记录已丢失")
                consumption_id = finalize(db, row)
                row.consumption_id = consumption_id
                occupancy.consumption_id = consumption_id
                if row.source == "automatic":
                    db.add(ConsumptionArea(consumption_id=consumption_id, area_id=row.area_id,
                                           pricing_json=row.pricing_json))
            row.status = "ready"
            row.safe_error = None
            row.lease_token = None
            row.lease_until = None
            row.updated_at = datetime.utcnow()
            db.add(AccessAudit(store_id=row.store_id, actor_id=row.operator_id,
                               request_id=row.id, action="issued"))
            db.commit()
    except Exception:
        _finish_error(session_factory, request_id, lease_token, uncertain=True)


def release_consumption(db, user_id, consumption_id):
    """仅在成功结账的同一事务中释放占用，不要提前释放。"""
    occupancy = db.get(MemberOccupancy, user_id)
    if occupancy and occupancy.consumption_id == consumption_id:
        db.delete(occupancy)


def reveal(session_factory, request_id, *, actor_id, allowed_store_ids, box):
    """供管理端查看密码使用；会员读取当前会话密码需单独校验。"""
    with session_factory() as db:
        row = db.get(PasscodeRequest, request_id)
        if not row or row.store_id not in allowed_store_ids:
            raise LockError("无权查看该密码")
        if row.status != "ready" or int(row.end_ms) <= int(time.time() * 1000):
            raise LockError("密码尚未生成或已经过期")
        password = box.decrypt(row.encrypted_password,
                               f"store:{row.store_id}:request:{row.id}:password")
        db.add(AccessAudit(store_id=row.store_id, actor_id=actor_id,
                           request_id=row.id, action="reveal"))
        db.commit()
        return password
