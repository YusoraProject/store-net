"""门店包场时段与订金配置，所有时段固定按北京时间解释。"""
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import BookingSettings
from .access_models import BillingArea
from .pricing import minute

BEIJING = timezone(timedelta(hours=8))


class SlotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=60)
    area_id: int | None = Field(default=None, gt=0)
    start: str
    end: str
    price: Decimal = Field(gt=0, le=1000000, decimal_places=2)
    enabled: bool = True


class SlotsIn(BaseModel):
    slots: list[SlotIn] = Field(max_length=48)


class DepositIn(BaseModel):
    deposit_percent: int = Field(ge=1, le=100, strict=True)


def settings(db, store_id, *, create=False):
    row = db.get(BookingSettings, store_id)
    if row is None and create:
        row = BookingSettings(store_id=store_id, deposit_percent=30, slots_json="[]")
        db.add(row)
        db.flush()
    return row


def config_out(db, store_id, *, member=False):
    row = settings(db, store_id)
    slots = json.loads(row.slots_json) if row else []
    result = []
    for slot in slots:
        area = db.get(BillingArea, slot["area_id"]) if slot["area_id"] else None
        available = slot["enabled"] and (slot["area_id"] is None or area is not None and area.enabled)
        if member and not available:
            continue
        result.append({**{k: v for k, v in slot.items() if k != "price_cents"},
                       "price": slot["price_cents"] / 100,
                       "area_name": area.name if area else "整店", "available": available})
    return {"deposit_percent": row.deposit_percent if row else 30, "slots": result}


def save_slots(db, store_id, payload):
    ids = set()
    slots = []
    for slot in payload.slots:
        try:
            minute(slot.start); minute(slot.end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if slot.id in ids or not slot.name.strip():
            raise HTTPException(422, "包场时段编号不能重复，名称不能为空")
        ids.add(slot.id)
        if slot.area_id:
            area = db.get(BillingArea, slot.area_id)
            if not area or area.store_id != store_id:
                raise HTTPException(422, "包场时段的区域不存在")
        slots.append({"id": slot.id, "name": slot.name.strip(), "area_id": slot.area_id,
                      "start": slot.start, "end": slot.end, "price_cents": int(slot.price * 100), "enabled": slot.enabled})
    settings(db, store_id, create=True).slots_json = json.dumps(slots, ensure_ascii=False)


def slot_schedule(db, store_id, slot_id, booking_date: date):
    row = settings(db, store_id)
    slot = next((s for s in json.loads(row.slots_json) if s["id"] == slot_id and s["enabled"]), None) if row else None
    if slot is None:
        raise HTTPException(409, "该包场时段已调整或停用，请刷新后选择")
    start = datetime.combine(booking_date, time(), tzinfo=BEIJING) + timedelta(minutes=minute(slot["start"]))
    duration = (minute(slot["end"]) - minute(slot["start"])) % 1440 or 1440
    end = start + timedelta(minutes=duration)
    return slot, start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None)
