import math
from datetime import date, datetime, time, timedelta
from typing import Iterable, Tuple

from .models import StorePricing


def money_to_cents(value: float) -> int:
    return int(round(float(value) * 100))


def cents_to_money(value: int) -> float:
    return round(int(value or 0) / 100, 2)


def segments(started: datetime, ended: datetime) -> Iterable[Tuple[datetime, datetime]]:
    # 按日夜交界和零点拆段，跨天消费不能全部套用开始时的费率。
    cursor = started
    while cursor < ended:
        boundaries = [
            datetime.combine(cursor.date(), time(8)),
            datetime.combine(cursor.date(), time(18)),
            datetime.combine(cursor.date() + timedelta(days=1), time()),
            datetime.combine(cursor.date() + timedelta(days=1), time(8)),
        ]
        boundary = min(x for x in boundaries if x > cursor)
        next_cursor = min(boundary, ended)
        yield cursor, next_cursor
        cursor = next_cursor


def day_kind(value: datetime, forced: str = "auto") -> str:
    if forced != "auto":
        if forced not in {"workday", "weekend", "holiday"}:
            raise ValueError("日期类型无效")
        return forced
    return "weekend" if value.weekday() >= 5 else "workday"


def quote_cents(pricing: StorePricing, started: datetime, ended: datetime, forced_day: str = "auto") -> tuple[int, int]:
    if ended <= started:
        raise ValueError("结束时间必须晚于开始时间")
    minutes = max(1, math.ceil((ended - started).total_seconds() / 60))
    totals: dict[tuple[date, str], int] = {}
    caps: dict[tuple[date, str], int] = {}
    for left, right in segments(started, ended):
        period = "day" if 8 <= left.hour < 18 else "night"
        kind = day_kind(left, forced_day)
        key = (left.date(), period)
        segment_minutes = max(1, math.ceil((right - left).total_seconds() / 60))
        hourly = int(getattr(pricing, f"{kind}_{period}_hourly_cents"))
        cap = int(getattr(pricing, f"{kind}_{period}_cap_cents"))
        totals[key] = totals.get(key, 0) + math.ceil(hourly * segment_minutes / 60)
        caps[key] = cap
    # 封顶按每天的日间、夜间分别计算，封顶价为0时不限制。
    due = sum(min(value, caps[key]) if caps[key] > 0 else value for key, value in totals.items())
    return minutes, due
