"""按当前区域汇总场况，仅展示有效会员可见的在场资料。"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, or_

from .models import User, Role, Store, StoreMember, Consumption, BookingSession, VenueBooking
from .access_models import BillingArea, ConsumptionArea, ConsumptionSegment, PasscodeRequest
from .bookings import live_clause


def snapshot(db, store_id, viewer):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "门店不存在")
    role = db.get(Role, viewer.role_id)
    member = db.scalar(select(StoreMember.id).where(StoreMember.store_id == store_id,
        StoreMember.user_id == viewer.id, StoreMember.is_active.is_(True)))
    if not viewer.is_active or (not (role and role.name == "admin") and (not member or not store.is_active)):
        raise HTTPException(403, "只有本店有效会员可以查看场况")
    now = datetime.utcnow()
    areas = db.scalars(select(BillingArea).where(BillingArea.store_id == store_id).order_by(BillingArea.id)).all()
    groups = {a.id: {"id": a.id, "name": a.name, "enabled": a.enabled, "users": [],
                     "pending_count": 0, "booking": None} for a in areas}
    def group(area_id):
        if area_id in groups:
            return groups[area_id]
        if None not in groups:
            groups[None] = {"id": None, "name": "未分配区域", "enabled": False,
                            "users": [], "pending_count": 0, "booking": None}
        return groups[None]
    sessions = db.execute(select(Consumption, User, ConsumptionArea.area_id,
        ConsumptionSegment.started_at, BookingSession.booking_id, BookingSession.ends_at)
        .join(User, User.id == Consumption.user_id)
        .outerjoin(ConsumptionArea, ConsumptionArea.consumption_id == Consumption.id)
        .outerjoin(ConsumptionSegment, ConsumptionSegment.active_consumption_id == Consumption.id)
        .outerjoin(BookingSession, BookingSession.consumption_id == Consumption.id)
        .where(Consumption.store_id == store_id, Consumption.status == "open",
               or_(BookingSession.consumption_id.is_(None), BookingSession.ends_at > now))
        .order_by(Consumption.started_at, Consumption.id)).all()
    for row, user, area_id, entered, booking_id, free_until in sessions:
        group(area_id)["users"].append({"session_id": row.id, "name": user.name,
            "avatar": user.avatar, "is_me": user.id == viewer.id,
            "started_at": row.started_at.isoformat() + "Z",
            "area_entered_at": (entered or row.started_at).isoformat() + "Z",
            "elapsed_seconds": max(0, int((now - row.started_at).total_seconds())),
            "free": booking_id is not None,
            "free_until": free_until.isoformat() + "Z" if free_until else None})
    pending = db.execute(select(PasscodeRequest.area_id, PasscodeRequest.source).where(
        PasscodeRequest.store_id == store_id, PasscodeRequest.source.in_(["automatic", "switch"]),
        PasscodeRequest.status.in_(["pending", "issuing", "unknown", "review"]))).all()
    for area_id, _ in pending:
        group(area_id)["pending_count"] += 1
    bookings = db.scalars(select(VenueBooking).where(VenueBooking.store_id == store_id,
        live_clause(now), VenueBooking.started_at <= now, VenueBooking.ended_at > now)).all()
    for booking in bookings:
        targets = list(groups.values()) if booking.area_id is None else [group(booking.area_id)]
        for target in targets:
            target["booking"] = {"pending_payment": booking.status == "pending", "ends_at": booking.ended_at.isoformat() + "Z"}
    return {"store_id": store.id, "store_name": store.name, "store_active": store.is_active,
            "updated_at": now.isoformat() + "Z", "online_count": len(sessions),
            "pending_count": len(pending), "areas": list(groups.values())}
