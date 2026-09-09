"""包场占用、已同意参与者的免费上机与会话到期处理。"""
import json
import math
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update, or_, func, and_

from .models import (Store, User, Consumption, VenueBooking, BookingDetails,
                     BookingInvitation, BookingSession)
from .access_models import BillingArea, ConsumptionArea, PasscodeRequest


def lock_store(db, store_id):
    db.execute(update(Store).where(Store.id == store_id).values(id=store_id))


def live_clause(now=None):
    now = now or datetime.utcnow()
    return or_(VenueBooking.status == "reserved", and_(VenueBooking.status == "pending",
               VenueBooking.id.in_(select(BookingDetails.booking_id).where(BookingDetails.hold_until > now))))


def has_access(db, booking, user_id, *, lock=False):
    query = select(BookingDetails).where(BookingDetails.booking_id == booking.id)
    detail = db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
    if booking.status != "reserved" or not detail or detail.deposit_paid_at is None or user_id is None:
        return False
    query = select(BookingInvitation.id).where(BookingInvitation.booking_id == booking.id,
                     BookingInvitation.user_id == user_id, BookingInvitation.status == "accepted")
    return db.scalar(query.with_for_update() if lock else query) is not None


def guard_entry(db, store_id, area_id, started_at=None, user_id=None):
    now = datetime.utcnow()
    when = utc(started_at) if started_at and started_at.tzinfo else started_at
    start, end = min(when or now, now), max(when or now, now)
    rows = db.scalars(select(VenueBooking).where(VenueBooking.store_id == store_id, live_clause(now),
        or_(VenueBooking.area_id.is_(None), VenueBooking.area_id == area_id),
        VenueBooking.started_at <= end, VenueBooking.ended_at > start).with_for_update()).all()
    admitted = None
    for booking in rows:
        if (booking.started_at <= now < booking.ended_at and start >= booking.started_at
                and end < booking.ended_at and has_access(db, booking, user_id, lock=True)):
            admitted = booking
        else:
            raise HTTPException(409, "当前区域已包场，仅已支付订金的发起人及已同意邀请的会员可免费上机")
    return admitted


def entry_status(db, store_id, area_id, user_id):
    now = datetime.utcnow()
    row = db.scalar(select(VenueBooking).where(VenueBooking.store_id == store_id, live_clause(now),
        or_(VenueBooking.area_id.is_(None), VenueBooking.area_id == area_id),
        VenueBooking.started_at <= now, VenueBooking.ended_at > now))
    if not row:
        return {"blocked": False, "free": False, "message": ""}
    allowed = has_access(db, row, user_id)
    return {"blocked": not allowed, "free": allowed, "booking_id": row.id,
            "ends_at": row.ended_at.isoformat() + "Z",
            "message": "当前为包场时段，你已获准免费上机。" if allowed else "当前区域正在包场，暂不允许上机；已同意邀请的参与者除外。"}


def admission_pricing(raw, booking):
    from .pricing import current_snapshot
    values = json.loads(current_snapshot(raw))
    if booking:
        values["_booking_id"] = booking.id
    return json.dumps(values)


def check_reserved_admission(request, booking):
    expected = json.loads(request.pricing_json or "{}").get("_booking_id")
    if expected != (booking.id if booking else None):
        raise HTTPException(409, "包场资格已变化，不能开始本次上机，请联系店长核对门锁申请")


def attach_session(db, consumption_id, booking):
    if booking:
        db.add(BookingSession(consumption_id=consumption_id, booking_id=booking.id, ends_at=booking.ended_at))


def guard_session_switch(db, consumption, booking):
    session = db.get(BookingSession, consumption.id)
    if session and (not booking or booking.id != session.booking_id or session.ends_at <= datetime.utcnow()):
        raise HTTPException(409, "请先结束包场免费上机，再开始其他区域的普通计费")
    if booking and not session:
        raise HTTPException(409, "请先结清当前普通消费，再进入包场免费上机")


def free_quote(row, session, ended):
    if ended.tzinfo:
        ended = utc(ended)
    ended = min(ended, session.ends_at)
    if ended < row.started_at:
        raise HTTPException(422, "结束时间不能早于上机时间")
    return ended, max(0, math.ceil((ended - row.started_at).total_seconds() / 60)), 0


def finish_free(db, row, session, *, ended=None, key=None, operator_id=None):
    from .area_switching import close_segment
    from .access_journal import release_consumption
    ended, minutes, _ = free_quote(row, session, ended or datetime.utcnow())
    row.ended_at, row.duration_minutes = ended, minutes
    row.amount_due_cents = row.paid_cents = 0
    row.payment_method, row.status = "booking", "paid"
    row.checkout_key = key or f"booking-end-{uuid.uuid4()}"
    row.operator_id = operator_id or row.operator_id
    row.updated_at = datetime.utcnow()
    close_segment(db, row, ended)
    release_consumption(db, row.user_id, row.id)


def expire_sessions(db, *, user_id=None, booking_id=None, cancel_at=None):
    now = datetime.utcnow()
    query = select(Consumption.id, Consumption.user_id).join(BookingSession, BookingSession.consumption_id == Consumption.id).where(Consumption.status == "open")
    if user_id is not None:
        query = query.where(Consumption.user_id == user_id)
    if booking_id is not None:
        query = query.where(BookingSession.booking_id == booking_id)
    else:
        query = query.where(BookingSession.ends_at <= now)
    changed = False
    for cid, uid in db.execute(query).all():
        db.execute(update(User).where(User.id == uid).values(id=uid))
        row = db.scalar(select(Consumption).where(Consumption.id == cid).with_for_update().execution_options(populate_existing=True))
        if row.status != "open":
            continue
        session = db.get(BookingSession, cid)
        finish_free(db, row, session, ended=cancel_at or session.ends_at)
        changed = True
    if changed:
        db.flush()
    return changed


def occupancy_count(db, store_id, area_id, *, lock=False):
    opened = select(Consumption.id).outerjoin(ConsumptionArea, ConsumptionArea.consumption_id == Consumption.id).where(
        Consumption.store_id == store_id, Consumption.status == "open")
    if area_id is not None:
        opened = opened.where(or_(ConsumptionArea.area_id == area_id, ConsumptionArea.area_id.is_(None)))
    if lock:
        opened = opened.with_for_update(of=Consumption)
    count = len(db.scalars(opened).all())
    pending = select(PasscodeRequest.id).where(PasscodeRequest.store_id == store_id,
        PasscodeRequest.status.in_(["pending", "issuing", "unknown", "review"]))
    if area_id is not None:
        pending = pending.where(PasscodeRequest.area_id == area_id)
    if lock:
        pending = pending.with_for_update()
    return count + len(db.scalars(pending).all())


def check_available(db, store_id, area_id, start, end):
    if area_id:
        area = db.get(BillingArea, area_id)
        if not area or area.store_id != store_id or not area.enabled:
            raise HTTPException(404, "区域不存在或已停用")
    if end <= datetime.utcnow() or end <= start:
        raise HTTPException(422, "请设置尚未结束的有效包场时段")
    if start <= datetime.utcnow() and occupancy_count(db, store_id, area_id, lock=True):
        raise HTTPException(409, "区域仍有上机或待确认发码，请先清场后再创建当前时段的包场")
    conflict = select(VenueBooking.id).where(VenueBooking.store_id == store_id, live_clause(),
        VenueBooking.started_at < end, VenueBooking.ended_at > start)
    if area_id:
        conflict = conflict.where(or_(VenueBooking.area_id.is_(None), VenueBooking.area_id == area_id))
    if db.scalar(conflict.with_for_update()):
        raise HTTPException(409, "该时段已有包场或待支付预约，请调整区域或时间")


def net_revenue(db, store_id):
    return db.scalar(select(func.coalesce(func.sum(VenueBooking.paid_cents - VenueBooking.refunded_cents), 0))
                     .where(VenueBooking.store_id == store_id))


def out(db, row, *, viewer_id=None):
    now = datetime.utcnow()
    detail = db.get(BookingDetails, row.id)
    area = db.get(BillingArea, row.area_id) if row.area_id else None
    phase = "cancelled" if row.status == "cancelled" else "scheduled" if now < row.started_at else "ended" if now >= row.ended_at else "in_progress"
    if row.status == "pending":
        phase = "awaiting_deposit" if detail and detail.hold_until > now and row.ended_at > now else "expired"
    invitations = db.scalars(select(BookingInvitation).where(BookingInvitation.booking_id == row.id).order_by(BookingInvitation.id)).all()
    own = next((i for i in invitations if i.user_id == viewer_id), None)
    host = db.get(User, detail.host_user_id) if detail and detail.host_user_id else None
    privileged = viewer_id is None or (detail and detail.host_user_id == viewer_id)
    return {"id": row.id, "store_id": row.store_id, "area_id": row.area_id, "area_name": area.name if area else "整店",
            "customer_name": row.customer_name, "contact": row.contact if privileged else "",
            "host_user_id": host.id if host else None, "host_name": host.name if host else None,
            "slot_name": detail.slot_name if detail else None,
            "started_at": row.started_at.isoformat() + "Z", "ended_at": row.ended_at.isoformat() + "Z",
            "amount": row.amount_cents / 100, "paid": row.paid_cents / 100, "refunded": row.refunded_cents / 100,
            "is_paid": row.paid_cents >= row.amount_cents and row.paid_at is not None,
            "deposit": detail.deposit_cents / 100 if detail else row.amount_cents / 100,
            "deposit_percent": detail.deposit_percent if detail else 100,
            "deposit_paid": detail.deposit_paid_at is not None if detail else row.paid_at is not None,
            "balance_paid": detail.balance_paid_cents / 100 if detail else 0,
            "hold_until": detail.hold_until.isoformat() + "Z" if detail and detail.hold_until else None,
            "status": row.status, "phase": phase, "remark": row.remark if privileged else "",
            "my_invitation": own.status if own else None,
            "participants": [{"user_id": i.user_id, "name": db.get(User, i.user_id).name,
                              "status": i.status} for i in invitations] if privileged else [],
            "occupancy_count": occupancy_count(db, row.store_id, row.area_id) if privileged and phase in {"scheduled", "in_progress"} else 0}


def utc(value):
    if value.tzinfo is None:
        raise HTTPException(422, "包场时间必须带时区")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def make_router(**kwargs):
    from .booking_api import make_router as build
    return build(**kwargs)
