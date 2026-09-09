from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from .database import Base


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    permissions_json = Column(Text, default="[]", nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False)
    avatar = Column(String(255))
    qq = Column(String(20), index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    address = Column(String(500))
    remark = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StoreMember(Base):
    __tablename__ = "store_members"
    __table_args__ = (UniqueConstraint("store_id", "user_id", name="uq_store_member"),)
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_role = Column(String(20), default="member", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StorePricing(Base):
    __tablename__ = "store_pricing"
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), unique=True, nullable=False)
    workday_day_hourly_cents = Column(Integer, default=800, nullable=False)
    workday_day_cap_cents = Column(Integer, default=4000, nullable=False)
    workday_night_hourly_cents = Column(Integer, default=800, nullable=False)
    workday_night_cap_cents = Column(Integer, default=4000, nullable=False)
    weekend_day_hourly_cents = Column(Integer, default=800, nullable=False)
    weekend_day_cap_cents = Column(Integer, default=4000, nullable=False)
    weekend_night_hourly_cents = Column(Integer, default=800, nullable=False)
    weekend_night_cap_cents = Column(Integer, default=4000, nullable=False)
    holiday_day_hourly_cents = Column(Integer, default=800, nullable=False)
    holiday_day_cap_cents = Column(Integer, default=4000, nullable=False)
    holiday_night_hourly_cents = Column(Integer, default=800, nullable=False)
    holiday_night_cap_cents = Column(Integer, default=4000, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MemberBenefit(Base):
    __tablename__ = "member_benefits"
    __table_args__ = (UniqueConstraint("store_id", "user_id", name="uq_member_benefit"),)
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    paid_cents = Column(Integer, default=0, nullable=False)
    bonus_cents = Column(Integer, default=0, nullable=False)
    times_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BenefitLedger(Base):
    __tablename__ = "benefit_ledgers"
    __table_args__ = (Index("ix_ledger_store_time", "store_id", "created_at"),)
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(30), nullable=False)
    paid_delta_cents = Column(Integer, default=0, nullable=False)
    bonus_delta_cents = Column(Integer, default=0, nullable=False)
    times_delta = Column(Integer, default=0, nullable=False)
    before_json = Column(Text, nullable=False)
    after_json = Column(Text, nullable=False)
    remark = Column(String(500))
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Consumption(Base):
    __tablename__ = "consumptions"
    __table_args__ = (
        Index("ix_consumption_store_time", "store_id", "started_at"),
        Index("ix_consumption_user_status", "user_id", "status"),
        UniqueConstraint("checkout_key", name="uq_checkout_key"),
    )
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=0, nullable=False)
    amount_due_cents = Column(Integer, default=0, nullable=False)
    paid_cents = Column(Integer, default=0, nullable=False)
    payment_method = Column(String(20), default="pending", nullable=False)
    status = Column(String(20), default="open", nullable=False)
    checkout_key = Column(String(80))
    remark = Column(String(500))
    operator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class VenueBooking(Base):
    __tablename__ = "venue_bookings"
    __table_args__ = (UniqueConstraint("store_id", "request_key", name="uq_booking_request"),)
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    area_id = Column(Integer)  # NULL 表示整店，包含后续新增区域。
    customer_name = Column(String(120), nullable=False)
    contact = Column(String(120), default="", nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    paid_cents = Column(Integer, default=0, nullable=False)
    refunded_cents = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default="reserved", nullable=False)
    remark = Column(String(500), default="", nullable=False)
    request_key = Column(String(80), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    paid_by = Column(Integer, ForeignKey("users.id"))
    cancelled_by = Column(Integer, ForeignKey("users.id"))
    paid_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BookingSettings(Base):
    __tablename__ = "booking_settings"
    store_id = Column(Integer, ForeignKey("stores.id"), primary_key=True)
    deposit_percent = Column(Integer, default=30, nullable=False)
    slots_json = Column(Text, default="[]", nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"))
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BookingDetails(Base):
    __tablename__ = "booking_details"
    booking_id = Column(Integer, ForeignKey("venue_bookings.id"), primary_key=True)
    host_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    source = Column(String(20), default="manual", nullable=False)
    slot_id = Column(String(64))
    slot_name = Column(String(60))
    deposit_percent = Column(Integer, nullable=False)
    deposit_cents = Column(Integer, nullable=False)
    deposit_paid_at = Column(DateTime)
    balance_paid_cents = Column(Integer, default=0, nullable=False)
    hold_until = Column(DateTime)


class BookingInvitation(Base):
    __tablename__ = "booking_invitations"
    __table_args__ = (UniqueConstraint("booking_id", "user_id", name="uq_booking_invitation"),)
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("venue_bookings.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    responded_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BookingSession(Base):
    __tablename__ = "booking_sessions"
    consumption_id = Column(Integer, ForeignKey("consumptions.id"), primary_key=True)
    booking_id = Column(Integer, ForeignKey("venue_bookings.id"), nullable=False, index=True)
    ends_at = Column(DateTime, nullable=False)
