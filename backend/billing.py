import math
from datetime import date, datetime, time, timedelta, timezone
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


def charge_parts(pricing, started, ended, forced_day="auto"):
    """产出每日每时段的费用；普通计费和换区累计使用同一实现。"""
    from .pricing import minute
    values = pricing if isinstance(pricing, dict) else vars(pricing)
    if values.get("version") != 2:
        for left, right in segments(started, ended):
            period = "day" if 8 <= left.hour < 18 else "night"
            kind = day_kind(left, forced_day)
            hourly, cap = (int(values[f"{kind}_{period}_{key}_cents"]) for key in ("hourly", "cap"))
            minutes = math.ceil((right - left).total_seconds() / 60)
            yield (left.date(), period), (hourly * minutes + 59) // 60, cap
        return
    if forced_day not in {"auto", "workday", "weekend", "holiday"}:
        raise ValueError("日期类型无效")
    zone = timezone(timedelta(minutes=values["timezone_offset_minutes"]))
    def local(value):
        # 数据库时间为无时区UTC；时段、周末和特殊日期按规则里的营业时区判定。
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(zone).replace(tzinfo=None)
    cursor, finish = local(started), local(ended)
    periods = [(p, minute(p["start"]), minute(p["end"])) for p in values["periods"]]
    while cursor < finish:
        point = cursor.hour * 60 + cursor.minute
        period = next(p for p, start, end in periods
                      if start == end or (start <= point < end if start < end else point >= start or point < end))
        boundaries = [datetime.combine(cursor.date() + timedelta(days=1), time())]
        boundaries += [datetime.combine(cursor.date(), time()) + timedelta(minutes=start)
                       for _, start, end in periods if start != end]
        right = min(finish, min(b for b in boundaries if b > cursor))
        kind = "weekend" if cursor.weekday() >= 5 else "workday"
        special = None
        if forced_day != "auto":
            kind = forced_day
        else:
            today = cursor.date().isoformat()
            for rule in values["date_rules"]:
                if rule["start_date"] <= today <= rule["end_date"]:
                    if rule["kind"] in {"holiday", "special"} and not values["holiday_enabled"]:
                        continue
                    if rule["kind"] == "special":
                        special = rule["rates"][period["id"]]
                    else:
                        kind = rule["kind"]
                    break
        if kind == "holiday" and not values["holiday_enabled"]:
            kind = "weekend" if cursor.weekday() >= 5 else "workday"
        if kind == "weekend" and not values["weekend_enabled"]:
            kind = "workday"
        rate = special or period["rates"][kind]
        minutes = math.ceil((right - cursor).total_seconds() / 60)
        yield (cursor.date(), period["id"]), (rate["hourly_cents"] * minutes + 59) // 60, rate["cap_cents"]
        cursor = right


def quote_cents(pricing: StorePricing, started: datetime, ended: datetime, forced_day: str = "auto") -> tuple[int, int]:
    if ended <= started:
        raise ValueError("结束时间必须晚于开始时间")
    minutes = max(1, math.ceil((ended - started).total_seconds() / 60))
    totals, caps = {}, {}
    for key, amount, cap in charge_parts(pricing, started, ended, forced_day):
        totals[key] = totals.get(key, 0) + amount
        caps[key] = cap
    # 跨零点按自然日分别封顶；同一天跨午夜时段的两段共享封顶。
    due = sum(min(value, caps[key]) if caps[key] > 0 else value for key, value in totals.items())
    return minutes, due
