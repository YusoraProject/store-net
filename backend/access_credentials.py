"""门店授权管理。日志不得记录令牌、账号密码或开门密码。"""
import json
import os
import time
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select, update, inspect
from backend.access_models import LockCredential, PasscodeRequest, CredentialRefresh
from backend.ttlock_client import TTLockClient, SecretBox, LockError


def secret_box():
    return SecretBox(os.getenv("TTLOCK_MASTER_KEY", ""))


def client(region, client_id):
    return TTLockClient(region, client_id,
        real_enabled=os.getenv("TTLOCK_REAL_ENABLED", "false").lower() == "true")


def secure_request(request):
    # 本地开发也不例外：真实凭证不能通过明文连接提交。
    if request.url.scheme != "https":
        raise HTTPException(403, "请先配置 HTTPS，再录入门锁授权或查看密码")


def credential(db, store_id):
    row = db.get(LockCredential, store_id)
    if not row:
        raise HTTPException(409, "请先配置该门店的通通锁授权")
    bundle = json.loads(secret_box().decrypt(row.encrypted_bundle, f"store:{store_id}:credential"))
    return row, bundle


def valid_client(db, store_id):
    row, bundle = credential(db, store_id)
    if inspect(db.get_bind()).has_table("access_credential_refresh"):
        state = db.get(CredentialRefresh, store_id)
        if state and state.credential_version == row.version:
            if state.status == "refreshing":
                raise HTTPException(409, "通通锁授权正在自动续期，请稍后重试")
            if state.status in {"unknown", "reauthorize"}:
                raise HTTPException(409, state.safe_error or "请重新配置通通锁授权")
    if bundle["expires_at"] <= int(time.time()) + 60:
        raise HTTPException(409, "通通锁授权已到续期时间，请稍后重试或在管理端检查授权续期")
    return client(row.region, bundle["client_id"]), bundle["access_token"], row.version


def save_authorization(db, store_id, actor_id, region, client_id, secret, username, password):
    if not inspect(db.get_bind()).has_table("access_credential_refresh"):
        raise HTTPException(503, "门锁数据表尚未初始化，请检查数据库配置并重新启动后端")
    state = db.get(CredentialRefresh, store_id)
    if state and state.status == "refreshing" and state.lease_until and state.lease_until > datetime.utcnow():
        raise HTTPException(409, "授权正在续期，请完成后再重新授权")
    pending = db.scalar(select(PasscodeRequest.id).where(PasscodeRequest.store_id == store_id,
        PasscodeRequest.status.in_(["pending", "issuing", "unknown", "review"])).limit(1))
    if pending:
        # 先拒绝，再请求远端；不要为了返回一个错误就轮换了仍需核对的账号令牌。
        raise HTTPException(409, "存在待确认的发码请求，请先核对或由店长确认风险后取消申请")
    # 先结束数据库事务，再请求通通锁，避免网络等待占用数据库锁。
    db.rollback()
    box = secret_box()
    adapter = client(region, client_id)
    tokens = adapter.authorize(secret, username, password)
    adapter.locks(tokens.access_token)
    bundle = {"client_id": client_id, "client_secret": secret,
              "access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
              "expires_at": tokens.expires_at}
    encrypted = box.encrypt(json.dumps(bundle), f"store:{store_id}:credential")
    row = db.get(LockCredential, store_id)
    if row:
        # 先取得写锁再检查待处理请求，防止换授权和发码同时发生。
        db.execute(update(LockCredential).where(LockCredential.store_id == store_id)
                   .values(updated_at=datetime.utcnow()))
        db.refresh(row)
        state = db.scalar(select(CredentialRefresh).where(CredentialRefresh.store_id == store_id)
            .with_for_update().execution_options(populate_existing=True))
        if state and state.status == "refreshing" and state.lease_until and state.lease_until > datetime.utcnow():
            db.rollback()
            raise HTTPException(409, "授权正在续期，请完成后再重新授权")
        pending = db.scalar(select(PasscodeRequest.id).where(
            PasscodeRequest.store_id == store_id,
            PasscodeRequest.status.in_(["pending", "issuing", "unknown", "review"])).limit(1))
        if pending:
            db.rollback()
            raise HTTPException(409, "存在待确认的发码请求，暂不能更换门店授权")
        row.version += 1
    else:
        row = LockCredential(store_id=store_id, version=1)
        db.add(row)
    row.region = region
    row.encrypted_bundle = encrypted
    row.tested_at = datetime.utcnow()
    row.updated_by = actor_id
    row.updated_at = datetime.utcnow()
    state = db.get(CredentialRefresh, store_id)
    if state is None:
        state = CredentialRefresh(store_id=store_id)
        db.add(state)
    state.credential_version, state.status, state.safe_error = row.version, "ready", None
    state.lease_token = state.lease_until = None
    state.last_attempt_at = state.last_success_at = None
    db.commit()
