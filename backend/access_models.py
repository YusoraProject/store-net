"""门锁、区域和计时占用模型，首次启动时与普通业务表一起创建。"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

AccessBase = declarative_base()


class LockCredential(AccessBase):
    __tablename__ = "access_credentials"
    store_id = Column(Integer, primary_key=True)
    region = Column(String(10), nullable=False)
    encrypted_bundle = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    tested_at = Column(DateTime)
    updated_by = Column(Integer, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CredentialRefresh(AccessBase):
    __tablename__ = "access_credential_refresh"
    store_id = Column(Integer, primary_key=True)
    credential_version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="ready")
    lease_token = Column(String(36))
    lease_until = Column(DateTime)
    last_attempt_at = Column(DateTime)
    last_success_at = Column(DateTime)
    safe_error = Column(String(255))


class BillingArea(AccessBase):
    __tablename__ = "access_areas"
    __table_args__ = (UniqueConstraint("store_id", "name", name="uq_access_area_name"),
                      UniqueConstraint("lock_id", name="uq_access_area_lock"))
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    pricing_json = Column(Text, nullable=False)
    lock_id = Column(String(40))
    lock_name = Column(String(120))
    password_version = Column(Integer)
    auto_issue = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PasscodeRequest(AccessBase):
    __tablename__ = "access_requests"
    __table_args__ = (UniqueConstraint("operator_id", "idempotency_key", name="uq_access_idempotency"),
                      UniqueConstraint("remote_name", name="uq_access_remote_name"))
    id = Column(String(36), primary_key=True)
    pricing_json = Column(Text)
    store_id = Column(Integer, nullable=False, index=True)
    area_id = Column(Integer, nullable=False)
    operator_id = Column(Integer, nullable=False)
    recipient_id = Column(Integer)
    idempotency_key = Column(String(80), nullable=False)
    remote_name = Column(String(64), nullable=False)
    source = Column(String(20), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    lock_id = Column(String(40), nullable=False)
    credential_version = Column(Integer, nullable=False)
    password_version = Column(Integer, nullable=False)
    remote_id = Column(String(40))
    encrypted_password = Column(Text)
    start_ms = Column(String(20), nullable=False)
    end_ms = Column(String(20), nullable=False)
    consumption_id = Column(Integer)
    target_consumption_id = Column(Integer)
    safe_error = Column(String(255))
    lease_token = Column(String(36))
    lease_until = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MemberOccupancy(AccessBase):
    __tablename__ = "access_member_occupancy"
    # 每个用户仅一条占用记录，不因门店、区域或进程不同而重复。
    user_id = Column(Integer, primary_key=True)
    area_id = Column(Integer, nullable=False)
    request_id = Column(String(36), unique=True)
    pending_request_id = Column(String(36), unique=True)
    consumption_id = Column(Integer, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ConsumptionArea(AccessBase):
    __tablename__ = "access_consumption_areas"
    consumption_id = Column(Integer, primary_key=True)
    area_id = Column(Integer, nullable=False, index=True)
    pricing_json = Column(Text)


class StartReceipt(AccessBase):
    __tablename__ = "access_start_receipts"
    __table_args__ = (UniqueConstraint("operator_id", "request_key", name="uq_start_receipt"),)
    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, nullable=False)
    request_key = Column(String(80), nullable=False)
    user_id = Column(Integer, nullable=False)
    area_id = Column(Integer, nullable=False)
    consumption_id = Column(Integer, nullable=False)


class ConsumptionSegment(AccessBase):
    __tablename__ = "access_consumption_segments"
    id = Column(Integer, primary_key=True)
    consumption_id = Column(Integer, nullable=False, index=True)
    area_id = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime)
    pricing_json = Column(Text, nullable=False)
    # 关闭时置空，由数据库保证每笔消费最多只有一段正在计时。
    active_consumption_id = Column(Integer, unique=True)


class SwitchReceipt(AccessBase):
    __tablename__ = "access_switch_receipts"
    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, nullable=False)
    request_key = Column(String(80), nullable=False)
    consumption_id = Column(Integer, nullable=False)
    area_id = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("operator_id", "request_key", name="uq_switch_receipt"),)


class AccessAudit(AccessBase):
    __tablename__ = "access_audits"
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    request_id = Column(String(36))
    action = Column(String(40), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
