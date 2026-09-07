"""区域上机与门锁发码的业务衔接，仅供StoreNet使用。"""
import json
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, update, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .models import Store, StoreMember, User, Consumption, StorePricing
from .access_models import BillingArea, ConsumptionArea, MemberOccupancy, PasscodeRequest, StartReceipt
from .access_credentials import valid_client, secret_box
from .access_journal import reserve, process
from .ttlock_client import LockError


def required_schema(db):
    if not inspect(db.get_bind()).has_table("access_consumption_segments"):
        raise HTTPException(503, "计费数据表尚未初始化，请检查数据库配置并重新启动后端")


def active_member(db, store_id, user_id):
    store = db.get(Store, store_id)
    user = db.get(User, user_id)
    member = db.scalar(select(StoreMember).where(StoreMember.store_id == store_id,
        StoreMember.user_id == user_id, StoreMember.is_active.is_(True)))
    if not store or not store.is_active or not user or not user.is_active or not member:
        raise HTTPException(403, "门店、账号或会员关系已停用，不能开始计时")


def default_area(db, store_id):
    """新店首次读取时补默认区，不改动已有区域。调用方负责提交。"""
    rows = db.scalars(select(BillingArea).where(BillingArea.store_id == store_id).order_by(BillingArea.id)).all()
    if rows:
        return rows
    price = db.scalar(select(StorePricing).where(StorePricing.store_id == store_id))
    values = {f"{d}_{p}_{r}_cents": getattr(price, f"{d}_{p}_{r}_cents",
        800 if r == "hourly" else 4000) for d in ("workday","weekend","holiday")
        for p in ("day","night") for r in ("hourly","cap")}
    row = BillingArea(store_id=store_id, name="默认区域", enabled=True, auto_issue=False,
                      pricing_json=json.dumps(values))
    db.add(row)
    db.flush()
    return [row]


def resolve_area(db, store_id, area_id):
    rows = [r for r in default_area(db, store_id) if r.enabled]
    if area_id is None:
        if len(rows) != 1:
            raise HTTPException(422, "请选择要进入的计费区域")
        return rows[0]
    row = next((r for r in rows if r.id == area_id), None)
    if not row:
        raise HTTPException(404, "区域不存在或已停用")
    return row


def snapshot_pricing(db, consumption, fallback):
    link = db.get(ConsumptionArea, consumption.id)
    if link and link.pricing_json:
        return SimpleNamespace(**json.loads(link.pricing_json))
    # 兼容尚无关联的历史记录，绝不将其套用其他区域的价格。
    return fallback


def finalize(db, request):
    if request.source == "switch":
        from .area_switching import finalize_switch
        return finalize_switch(db, request)
    active_member(db, request.store_id, request.recipient_id)
    if db.scalar(select(Consumption.id).where(Consumption.user_id == request.recipient_id,
                                              Consumption.status == "open")):
        raise HTTPException(409, "会员已有进行中的消费")
    if int(request.end_ms) <= int(time.time()*1000):
        raise HTTPException(409, "密码已过期，不能启动计费，请联系店长处理")
    if not request.pricing_json:
        raise HTTPException(409, "发码申请缺少区域价格，请联系店长核对")
    now = datetime.utcnow()
    row = Consumption(store_id=request.store_id, user_id=request.recipient_id,
        started_at=now, ended_at=now, operator_id=request.operator_id)
    db.add(row)
    db.flush()
    return row.id


def resume(db, request_id):
    row = db.get(PasscodeRequest, request_id)
    if not row:
        raise HTTPException(404, "发码申请不存在")
    if row.status in {"ready","failed","cancelled"}:
        return
    adapter, token, version = valid_client(db, row.store_id)
    if version != row.credential_version:
        raise HTTPException(409, "授权已变化，请联系店长核对原请求")
    sessions = sessionmaker(db.get_bind())
    db.rollback()
    process(sessions, request_id, client=adapter, token=token, box=secret_box(), finalize=finalize)
    db.expire_all()


def begin(db, *, store_id, user_id, operator_id, area_id, key, started_at, secure):
    required_schema(db)
    # 写锁统一串行化普通上机和结账；外部请求前必须结束事务。
    db.execute(update(User).where(User.id == user_id).values(id=user_id))
    active_member(db, store_id, user_id)
    receipt = db.scalar(select(StartReceipt).where(StartReceipt.operator_id == operator_id,
                                                   StartReceipt.request_key == key).with_for_update()) if key else None
    if receipt:
        area = db.get(BillingArea, receipt.area_id)
        if receipt.user_id != user_id or area.store_id != store_id or (area_id and area_id != area.id):
            raise HTTPException(409, "该请求标识已用于其他上机操作")
        return db.get(Consumption, receipt.consumption_id), None
    prior = db.scalar(select(PasscodeRequest).where(PasscodeRequest.operator_id == operator_id,
        PasscodeRequest.idempotency_key == key).with_for_update()) if key else None
    if prior:
        if prior.source != "automatic" or prior.recipient_id != user_id or prior.store_id != store_id or (area_id and area_id != prior.area_id):
            raise HTTPException(409, "该请求标识已用于其他操作")
        return db.get(Consumption, prior.consumption_id) if prior.consumption_id else None, prior.id
    occupied = db.scalar(select(MemberOccupancy).where(MemberOccupancy.user_id == user_id).with_for_update())
    opened = db.scalar(select(Consumption).where(Consumption.user_id == user_id, Consumption.status == "open").with_for_update())
    if occupied or opened:
        raise HTTPException(409, "已有进行中或待确认记录；同店请使用换区入口，跨店需先结账")
    area = resolve_area(db, store_id, area_id)
    area_id, prices = area.id, area.pricing_json
    if not area.auto_issue:
        when = started_at or datetime.utcnow()
        row = Consumption(store_id=store_id, user_id=user_id, started_at=when,
                          ended_at=when, operator_id=operator_id)
        db.add(row)
        db.flush()
        db.add(ConsumptionArea(consumption_id=row.id, area_id=area_id, pricing_json=prices))
        db.add(MemberOccupancy(user_id=user_id, area_id=area_id, consumption_id=row.id))
        if key:
            db.add(StartReceipt(operator_id=operator_id, request_key=key, user_id=user_id,
                                area_id=area_id, consumption_id=row.id))
        db.commit()
        db.refresh(row)
        return row, None
    if not secure:
        raise HTTPException(403, "自动发码需要HTTPS连接")
    if not key:
        raise HTTPException(422, "自动发码需要上机请求标识，请刷新页面")
    if not area.lock_id or area.password_version != 4:
        raise HTTPException(409, "区域门锁尚未正确配置")
    lock_id, version = area.lock_id, area.password_version
    adapter, token, credential_version = valid_client(db, store_id)
    sessions = sessionmaker(db.get_bind())
    db.commit()
    try:
        request_id = reserve(sessions, store_id=store_id, area_id=area_id, operator_id=operator_id,
            recipient_id=user_id, idempotency_key=key, lock_id=lock_id,
            credential_version=credential_version, password_version=version,
            start_ms=int(time.time()//3600)*3600000, source="automatic", pricing_json=prices)
        process(sessions, request_id, client=adapter, token=token, box=secret_box(), finalize=finalize)
    except LockError as exc:
        raise HTTPException(409, str(exc)) from None
    result = db.get(PasscodeRequest, request_id)
    return db.get(Consumption, result.consumption_id) if result.consumption_id else None, request_id


def pending_out(db, user_id):
    occupancy = db.get(MemberOccupancy, user_id)
    if not occupancy or not (occupancy.pending_request_id or occupancy.request_id):
        return None
    row = db.get(PasscodeRequest, occupancy.pending_request_id or occupancy.request_id)
    return {"id": row.id, "status": row.status, "area_id": row.area_id, "store_id": row.store_id,
            "source": row.source,
            "message": row.safe_error, "consumption_id": row.consumption_id,
            "start_ms": row.start_ms, "end_ms": row.end_ms}
