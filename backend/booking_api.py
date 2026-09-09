"""包场配置、订金支付、邀请与管理接口。"""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, or_

from .models import (User, StoreMember, MemberBenefit, BenefitLedger, VenueBooking,
                     BookingDetails, BookingInvitation)
from .access_models import BillingArea
from .area_billing import active_member, default_area
from .booking_config import (BEIJING, SlotsIn, DepositIn, settings, config_out, save_slots, slot_schedule)
from .bookings import lock_store, out, utc, check_available, net_revenue, expire_sessions


class BookingIn(BaseModel):
    area_id: int | None = Field(default=None, gt=0)
    customer_name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default="", max_length=120)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    amount: Decimal | None = Field(default=None, ge=0, le=1000000, decimal_places=2)
    booking_date: date | None = None
    slot_id: str | None = None
    host_user_id: int | None = Field(default=None, gt=0)
    user_ids: list[int] = Field(default_factory=list, max_length=100)
    remark: str = Field(default="", max_length=500)
    request_key: str = Field(min_length=1, max_length=80)


class MemberBookingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_date: date
    slot_id: str = Field(min_length=1, max_length=64)
    customer_name: str = Field(default="我的包场", min_length=1, max_length=120)
    request_key: str = Field(min_length=1, max_length=80)


class CancelIn(BaseModel):
    refund_confirmed: bool = False


class InviteIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=100)


class RespondIn(BaseModel):
    accept: bool


def add_people(db, row, actor_id, user_ids, *, host_id=None):
    for uid in set(user_ids) | ({host_id} if host_id else set()):
        active_member(db, row.store_id, uid)
        invite = db.scalar(select(BookingInvitation).where(BookingInvitation.booking_id == row.id,
                                                          BookingInvitation.user_id == uid))
        if invite is None:
            db.add(BookingInvitation(booking_id=row.id, user_id=uid, invited_by=actor_id,
                status="accepted" if uid == host_id else "pending",
                responded_at=datetime.utcnow() if uid == host_id else None))
        elif invite.status == "declined":
            invite.status, invite.responded_at, invite.invited_by = "pending", None, actor_id


def add_details(db, row, host_id, source, slot=None, user_ids=()):
    percent = config_out(db, row.store_id)["deposit_percent"]
    detail = BookingDetails(booking_id=row.id, host_user_id=host_id, source=source,
        slot_id=slot["id"] if slot else None, slot_name=slot["name"] if slot else None,
        deposit_percent=percent, deposit_cents=(row.amount_cents * percent + 99) // 100,
        hold_until=min(datetime.utcnow() + timedelta(minutes=15), row.ended_at) if source == "member" else None)
    db.add(detail)
    add_people(db, row, row.operator_id, user_ids, host_id=host_id)
    return detail


def wallet_delta(db, row, host_id, delta, actor_id, action):
    db.execute(update(User).where(User.id == host_id).values(id=host_id))
    wallet = db.scalar(select(MemberBenefit).where(MemberBenefit.store_id == row.store_id,
        MemberBenefit.user_id == host_id).with_for_update().execution_options(populate_existing=True))
    if wallet is None:
        if delta < 0:
            raise HTTPException(402, "充值余额不足，请先联系店长充值")
        wallet = MemberBenefit(store_id=row.store_id, user_id=host_id, paid_cents=0, bonus_cents=0, times_count=0)
        db.add(wallet)
    if wallet.paid_cents + delta < 0:
        raise HTTPException(402, "充值余额不足；包场订金不使用赠送余额或次卡")
    before = {"paid": wallet.paid_cents, "bonus": wallet.bonus_cents, "times": wallet.times_count}
    wallet.paid_cents += delta
    wallet.updated_at = datetime.utcnow()
    after = {**before, "paid": wallet.paid_cents}
    if delta:
        db.add(BenefitLedger(store_id=row.store_id, user_id=host_id, action=action,
            paid_delta_cents=delta, before_json=json.dumps(before), after_json=json.dumps(after),
            remark=f"包场 #{row.id} " + ("订金" if delta < 0 else "退款"), operator_id=actor_id))


def payable(row, detail):
    now = datetime.utcnow()
    if row.status == "cancelled":
        raise HTTPException(409, "包场已取消，不能收款")
    if row.status == "pending" and (not detail or detail.hold_until <= now or row.ended_at <= now):
        raise HTTPException(409, "订金支付期限已过，请重新选择包场时段")


def locked_details(db, booking_id):
    return db.scalar(select(BookingDetails).where(BookingDetails.booking_id == booking_id)
                     .with_for_update().execution_options(populate_existing=True))


def record_offline(db, row, actor_id, *, deposit_only=False):
    detail = locked_details(db, row.id)
    payable(row, detail)
    target = detail.deposit_cents if deposit_only and detail else row.amount_cents
    row.paid_cents = max(row.paid_cents, target)
    row.paid_at, row.paid_by, row.status = row.paid_at or datetime.utcnow(), actor_id, "reserved"
    if detail and row.paid_cents >= detail.deposit_cents:
        detail.deposit_paid_at = detail.deposit_paid_at or datetime.utcnow()


def cancel_booking(db, row, actor_id, refund_confirmed):
    if row.status == "cancelled":
        return
    detail = locked_details(db, row.id)
    balance = detail.balance_paid_cents if detail else 0
    offline = row.paid_cents - balance
    if offline > 0 and not refund_confirmed:
        raise HTTPException(409, "请先在线下完成线下实收部分的退款，再确认取消")
    if balance:
        wallet_delta(db, row, detail.host_user_id, balance, actor_id, "booking_refund")
    row.status, row.cancelled_at, row.cancelled_by = "cancelled", datetime.utcnow(), actor_id
    row.refunded_cents = row.paid_cents
    expire_sessions(db, booking_id=row.id, cancel_at=row.cancelled_at)


def make_router(*, user_dependency, db_dependency, scope, pricing_scope=None):
    from .access_api import SafeRoute
    router = APIRouter(route_class=SafeRoute)
    price_scope = pricing_scope or scope

    def get_locked(db, user, store_id, booking_id, *, member=False):
        if member:
            active_member(db, store_id, user.id)
        else:
            scope(db, user, store_id)
        lock_store(db, store_id)
        row = db.scalar(select(VenueBooking).where(VenueBooking.id == booking_id).with_for_update())
        if not row or row.store_id != store_id:
            raise HTTPException(404, "包场记录不存在")
        return row

    def require_host(db, row, user_id):
        detail = locked_details(db, row.id)
        if not detail or detail.host_user_id != user_id:
            raise HTTPException(403, "只有该包场的发起人可以操作")
        return detail

    def config_with_areas(db, store_id, *, member=False):
        areas = default_area(db, store_id)
        db.commit()
        return {**config_out(db, store_id, member=member), "areas": [{"id": a.id, "name": a.name} for a in areas if a.enabled]}

    @router.get("/stores/{store_id}/booking-slots")
    def slots_config(store_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        price_scope(db, user, store_id)
        return config_with_areas(db, store_id)

    @router.put("/stores/{store_id}/booking-slots")
    def update_slots(store_id: int, payload: SlotsIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        price_scope(db, user, store_id)
        lock_store(db, store_id)
        save_slots(db, store_id, payload)
        row = settings(db, store_id, create=True)
        row.updated_by, row.updated_at = user.id, datetime.utcnow()
        db.commit()
        return config_out(db, store_id)

    @router.put("/stores/{store_id}/booking-config")
    def update_deposit(store_id: int, payload: DepositIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        scope(db, user, store_id)
        lock_store(db, store_id)
        row = settings(db, store_id, create=True)
        row.deposit_percent, row.updated_by, row.updated_at = payload.deposit_percent, user.id, datetime.utcnow()
        db.commit()
        return config_out(db, store_id)

    @router.get("/stores/{store_id}/bookings")
    def listing(store_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        scope(db, user, store_id)
        config = config_with_areas(db, store_id)
        rows = db.scalars(select(VenueBooking).where(VenueBooking.store_id == store_id)
                          .order_by(VenueBooking.started_at.desc(), VenueBooking.id.desc())).all()
        people = db.execute(select(User.id, User.name, User.username).join(StoreMember, StoreMember.user_id == User.id)
                            .where(StoreMember.store_id == store_id, StoreMember.is_active.is_(True), User.is_active.is_(True))).all()
        return {**config, "items": [out(db, row) for row in rows],
                "members": [{"id": p.id, "name": p.name, "username": p.username} for p in people],
                "revenue": net_revenue(db, store_id) / 100}

    @router.post("/stores/{store_id}/bookings")
    def create(store_id: int, payload: BookingIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        store = scope(db, user, store_id)
        if not store.is_active:
            raise HTTPException(409, "门店已停用")
        lock_store(db, store_id)
        slot = None
        if payload.slot_id:
            if not payload.booking_date:
                raise HTTPException(422, "请选择包场日期")
            slot, start, end = slot_schedule(db, store_id, payload.slot_id, payload.booking_date)
            area_id, amount = slot["area_id"], slot["price_cents"]
        else:
            if payload.started_at is None or payload.ended_at is None or payload.amount is None:
                raise HTTPException(422, "请选择时段或填写起止时间和总价")
            start, end = utc(payload.started_at), utc(payload.ended_at)
            area_id, amount = payload.area_id, int(payload.amount * 100)
        name = payload.customer_name.strip()
        if not name or end <= start:
            raise HTTPException(422, "请填写客户名称及有效时间")
        values = dict(area_id=area_id, customer_name=name, contact=payload.contact.strip(),
                      started_at=start, ended_at=end, amount_cents=amount, remark=payload.remark.strip())
        prior = db.scalar(select(VenueBooking).where(VenueBooking.store_id == store_id, VenueBooking.request_key == payload.request_key).with_for_update())
        if prior:
            detail = db.get(BookingDetails, prior.id)
            if (prior.operator_id != user.id or any(getattr(prior, k) != v for k, v in values.items())
                    or (detail.host_user_id if detail else None) != payload.host_user_id):
                raise HTTPException(409, "该请求标识已用于其他包场")
            return out(db, prior)
        check_available(db, store_id, area_id, start, end)
        row = VenueBooking(store_id=store_id, operator_id=user.id, request_key=payload.request_key, **values)
        db.add(row); db.flush()
        add_details(db, row, payload.host_user_id, "manual", slot, payload.user_ids)
        db.commit()
        return out(db, row)

    @router.post("/stores/{store_id}/bookings/{booking_id}/pay")
    def pay(store_id: int, booking_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id)
        record_offline(db, row, user.id)
        db.commit()
        return out(db, row)

    @router.post("/stores/{store_id}/bookings/{booking_id}/deposit")
    def offline_deposit(store_id: int, booking_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id)
        record_offline(db, row, user.id, deposit_only=True)
        db.commit()
        return out(db, row)

    @router.post("/stores/{store_id}/bookings/{booking_id}/cancel")
    def cancel(store_id: int, booking_id: int, payload: CancelIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id)
        cancel_booking(db, row, user.id, payload.refund_confirmed)
        db.commit()
        return out(db, row)

    @router.get("/me/stores/{store_id}/booking-config")
    def my_config(store_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        active_member(db, store_id, user.id)
        result = config_with_areas(db, store_id, member=True)
        wallet = db.scalar(select(MemberBenefit).where(MemberBenefit.store_id == store_id, MemberBenefit.user_id == user.id))
        return {**result, "balance": wallet.paid_cents / 100 if wallet else 0}

    @router.get("/me/stores/{store_id}/bookings")
    def my_bookings(store_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        active_member(db, store_id, user.id)
        ids = select(BookingInvitation.booking_id).where(BookingInvitation.user_id == user.id)
        rows = db.scalars(select(VenueBooking).where(VenueBooking.store_id == store_id,
            or_(VenueBooking.id.in_(ids), VenueBooking.id.in_(select(BookingDetails.booking_id).where(BookingDetails.host_user_id == user.id))))
            .order_by(VenueBooking.started_at.desc(), VenueBooking.id.desc())).all()
        return [out(db, row, viewer_id=user.id) for row in rows]

    @router.post("/me/stores/{store_id}/bookings")
    def create_mine(store_id: int, payload: MemberBookingIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        active_member(db, store_id, user.id)
        lock_store(db, store_id)
        prior = db.scalar(select(VenueBooking).where(VenueBooking.store_id == store_id, VenueBooking.request_key == payload.request_key).with_for_update())
        if prior:
            detail = require_host(db, prior, user.id)
            if detail.slot_id != payload.slot_id or prior.started_at.replace(tzinfo=timezone.utc).astimezone(BEIJING).date() != payload.booking_date:
                raise HTTPException(409, "该请求标识已用于其他包场")
            return out(db, prior, viewer_id=user.id)
        slot, start, end = slot_schedule(db, store_id, payload.slot_id, payload.booking_date)
        check_available(db, store_id, slot["area_id"], start, end)
        if not payload.customer_name.strip():
            raise HTTPException(422, "请填写包场名称")
        row = VenueBooking(store_id=store_id, area_id=slot["area_id"], customer_name=payload.customer_name.strip(),
            started_at=start, ended_at=end, amount_cents=slot["price_cents"], status="pending",
            request_key=payload.request_key, operator_id=user.id)
        db.add(row); db.flush()
        add_details(db, row, user.id, "member", slot)
        db.commit()
        return out(db, row, viewer_id=user.id)

    @router.post("/me/stores/{store_id}/bookings/{booking_id}/deposit")
    def pay_deposit(store_id: int, booking_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id, member=True)
        detail = require_host(db, row, user.id)
        payable(row, detail)
        if detail.deposit_paid_at is None:
            if row.ended_at <= datetime.utcnow():
                raise HTTPException(409, "包场时段已结束")
            due = max(0, detail.deposit_cents - row.paid_cents)
            wallet_delta(db, row, user.id, -due, user.id, "booking_deposit")
            detail.balance_paid_cents += due
            detail.deposit_paid_at = datetime.utcnow()
            row.paid_cents += due
            row.paid_at, row.paid_by, row.status = row.paid_at or datetime.utcnow(), user.id, "reserved"
        db.commit()
        return out(db, row, viewer_id=user.id)

    @router.post("/me/stores/{store_id}/bookings/{booking_id}/cancel")
    def cancel_mine(store_id: int, booking_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id, member=True)
        require_host(db, row, user.id)
        if row.paid_cents > 0:
            raise HTTPException(409, "已付订金的包场请联系店长办理取消和退款")
        cancel_booking(db, row, user.id, False)
        db.commit()
        return out(db, row, viewer_id=user.id)

    @router.get("/me/stores/{store_id}/booking-members")
    def candidates(store_id: int, q: str = Query(min_length=1, max_length=120), db=Depends(db_dependency), user=Depends(user_dependency)):
        active_member(db, store_id, user.id)
        people = db.execute(select(User.id, User.name, User.username).join(StoreMember, StoreMember.user_id == User.id)
            .where(StoreMember.store_id == store_id, StoreMember.is_active.is_(True), User.is_active.is_(True),
                   or_(User.username.contains(q, autoescape=True), User.name.contains(q, autoescape=True))).limit(30)).all()
        return [{"id": p.id, "name": p.name, "username": p.username} for p in people if p.id != user.id]

    @router.post("/me/stores/{store_id}/bookings/{booking_id}/invite")
    def invite(store_id: int, booking_id: int, payload: InviteIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id, member=True)
        detail = require_host(db, row, user.id)
        if row.status != "reserved" or detail.deposit_paid_at is None or row.ended_at <= datetime.utcnow():
            raise HTTPException(409, "需先支付订金，且包场尚未结束，才可邀请其他会员")
        add_people(db, row, user.id, payload.user_ids, host_id=user.id)
        db.commit()
        return out(db, row, viewer_id=user.id)

    @router.post("/me/stores/{store_id}/bookings/{booking_id}/respond")
    def respond(store_id: int, booking_id: int, payload: RespondIn, db=Depends(db_dependency), user=Depends(user_dependency)):
        row = get_locked(db, user, store_id, booking_id, member=True)
        detail = locked_details(db, row.id)
        invite = db.scalar(select(BookingInvitation).where(BookingInvitation.booking_id == row.id,
            BookingInvitation.user_id == user.id).with_for_update())
        if not invite or not detail or detail.host_user_id == user.id:
            raise HTTPException(403, "没有可处理的包场邀请")
        if row.status != "reserved" or detail.deposit_paid_at is None or row.ended_at <= datetime.utcnow():
            raise HTTPException(409, "邀请尚未生效、已取消或包场已结束")
        invite.status = "accepted" if payload.accept else "declined"
        invite.responded_at = datetime.utcnow()
        if not payload.accept:
            expire_sessions(db, user_id=user.id, booking_id=row.id, cancel_at=datetime.utcnow())
        db.commit()
        return out(db, row, viewer_id=user.id)

    return router
