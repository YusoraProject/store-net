"""同店换区只切换计时段，不结账、不扣权益。"""
import json
import math
import time
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from .models import User, Consumption
from .access_models import (ConsumptionArea, ConsumptionSegment, MemberOccupancy,
    SwitchReceipt, PasscodeRequest, LockCredential)
from .billing import segments, day_kind, quote_cents
from .access_credentials import valid_client, secret_box
from .access_journal import process


def guard_pending(db, user_id):
    occupied = db.get(MemberOccupancy, user_id)
    if occupied and occupied.pending_request_id:
        raise HTTPException(409, "换区密码还在确认中，仍按原区域计费，请先核对或联系店长取消申请")


def change_segment(db, row, area_id, prices, when):
    link = db.get(ConsumptionArea, row.id)
    current = db.scalar(select(ConsumptionSegment).where(
        ConsumptionSegment.active_consumption_id == row.id).with_for_update())
    if current is None:
        if not link or not link.pricing_json:
            raise HTTPException(409, "原区域价格快照缺失，请联系店长处理")
        current = ConsumptionSegment(consumption_id=row.id, area_id=link.area_id,
            started_at=row.started_at, pricing_json=link.pricing_json)
        db.add(current)
    if when < current.started_at:
        raise HTTPException(409, "当前消费开始时间晚于服务器时间，不能换区")
    current.ended_at = when
    current.active_consumption_id = None
    db.flush()
    db.add(ConsumptionSegment(consumption_id=row.id, area_id=area_id, started_at=when,
        pricing_json=prices, active_consumption_id=row.id))
    link.area_id, link.pricing_json = area_id, prices
    occupied = db.get(MemberOccupancy, row.user_id)
    occupied.area_id = area_id
    row.updated_at = when


def finalize_switch(db, request):
    db.execute(update(User).where(User.id == request.recipient_id).values(id=request.recipient_id))
    row = db.scalar(select(Consumption).where(Consumption.id == request.target_consumption_id)
                    .with_for_update().execution_options(populate_existing=True))
    occupied = db.get(MemberOccupancy, request.recipient_id)
    if (not row or row.status != "open" or row.user_id != request.recipient_id
            or row.store_id != request.store_id or not occupied
            or occupied.pending_request_id != request.id):
        raise HTTPException(409, "换区消费状态已变化，请联系店长核对")
    if int(request.end_ms) <= int(time.time() * 1000):
        raise HTTPException(409, "新区域密码已经过期，继续按原区域计费")
    # 远端确认之前的时间全部留在原区；只有本地事务成功才切到新区。
    change_segment(db, row, request.area_id, request.pricing_json, datetime.utcnow())
    occupied.pending_request_id = None
    occupied.request_id = request.id
    return row.id


def switch(db, *, consumption_id, user_id, operator_id, area_id, key, secure):
    from .area_billing import required_schema, active_member, resolve_area, finalize
    required_schema(db)
    db.execute(update(User).where(User.id == user_id).values(id=user_id))
    row = db.scalar(select(Consumption).where(Consumption.id == consumption_id)
        .with_for_update().execution_options(populate_existing=True))
    if not row or row.user_id != user_id:
        raise HTTPException(404, "消费记录不存在")
    receipt = db.scalar(select(SwitchReceipt).where(SwitchReceipt.operator_id == operator_id,
        SwitchReceipt.request_key == key).with_for_update())
    prior = db.scalar(select(PasscodeRequest).where(PasscodeRequest.operator_id == operator_id,
        PasscodeRequest.idempotency_key == key).with_for_update())
    if receipt:
        if receipt.consumption_id != row.id or receipt.area_id != area_id:
            raise HTTPException(409, "该请求标识已用于其他换区操作")
        return row, None
    if prior:
        if prior.source != "switch" or prior.target_consumption_id != row.id or prior.area_id != area_id:
            raise HTTPException(409, "该请求标识已用于其他操作")
        return (row if prior.status == "ready" else None), prior.id
    if row.status != "open":
        raise HTTPException(409, "消费已结账，不能换区")
    active_member(db, row.store_id, user_id)
    guard_pending(db, user_id)
    occupied = db.get(MemberOccupancy, user_id)
    if not occupied or occupied.consumption_id != row.id:
        raise HTTPException(409, "上机占用记录不一致，请联系店长处理")
    area = resolve_area(db, row.store_id, area_id)
    if area.id == occupied.area_id:
        raise HTTPException(409, "已经在该区域，无需重复切换")
    if not area.auto_issue:
        change_segment(db, row, area.id, area.pricing_json, datetime.utcnow())
        occupied.request_id = None
        db.add(SwitchReceipt(operator_id=operator_id, request_key=key,
                            consumption_id=row.id, area_id=area.id))
        db.commit()
        return row, None
    if not secure:
        raise HTTPException(403, "自动发码需要HTTPS连接")
    if not area.lock_id or area.password_version != 4:
        raise HTTPException(409, "区域门锁尚未正确配置")
    adapter, token, version = valid_client(db, row.store_id)
    locked = db.execute(update(LockCredential).where(LockCredential.store_id == row.store_id,
        LockCredential.version == version).values(updated_at=datetime.utcnow()))
    if locked.rowcount != 1:
        raise HTTPException(409, "门锁授权已变化，请刷新后重试")
    request_id = str(uuid.uuid4())
    start_ms = int(time.time() // 3600) * 3600000
    db.add(PasscodeRequest(id=request_id, pricing_json=area.pricing_json, store_id=row.store_id,
        area_id=area.id, operator_id=operator_id, recipient_id=user_id, idempotency_key=key,
        remote_name="net-" + uuid.uuid4().hex, source="switch", status="pending",
        lock_id=area.lock_id, credential_version=version, password_version=area.password_version,
        start_ms=str(start_ms), end_ms=str(start_ms + 21_600_000), target_consumption_id=row.id))
    occupied.pending_request_id = request_id
    sessions = sessionmaker(db.get_bind())
    db.commit()
    # 网络调用在预占落库之后执行，原消费继续计时，不持有数据库锁。
    process(sessions, request_id, client=adapter, token=token, box=secret_box(), finalize=finalize)
    db.expire_all()
    result = db.get(PasscodeRequest, request_id)
    return (db.get(Consumption, consumption_id) if result.status == "ready" else None), request_id


def quote_accumulated(db, row, fallback, ended, forced_day="auto"):
    visits = db.scalars(select(ConsumptionSegment).where(
        ConsumptionSegment.consumption_id == row.id).order_by(ConsumptionSegment.started_at, ConsumptionSegment.id)).all()
    if not visits:
        from .area_billing import snapshot_pricing
        return quote_cents(snapshot_pricing(db, row, fallback), row.started_at, ended, forced_day)
    if ended <= row.started_at or ended < visits[-1].started_at:
        raise ValueError("结束时间不能早于最后一次换区")
    totals, caps = {}, {}
    for visit in visits:
        price = json.loads(visit.pricing_json)
        price_key = json.dumps(price, sort_keys=True)
        for left, right in segments(visit.started_at, min(visit.ended_at or ended, ended)):
            period = "day" if 8 <= left.hour < 18 else "night"
            kind = day_kind(left, forced_day)
            # 重返同区不重置同一天同一时段的封顶；不同价格快照分别计算。
            key = (visit.area_id, price_key, left.date(), period)
            minutes = math.ceil((right - left).total_seconds() / 60)
            totals[key] = totals.get(key, 0) + math.ceil(price[f"{kind}_{period}_hourly_cents"] * minutes / 60)
            caps[key] = price[f"{kind}_{period}_cap_cents"]
    due = sum(min(value, caps[key]) if caps[key] > 0 else value for key, value in totals.items())
    return max(1, math.ceil((ended - row.started_at).total_seconds() / 60)), due


def close_segment(db, row, ended):
    segment = db.scalar(select(ConsumptionSegment).where(ConsumptionSegment.active_consumption_id == row.id))
    if segment:
        segment.ended_at = ended
        segment.active_consumption_id = None
