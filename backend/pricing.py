"""可配置时段和日期规则。金额入库为整数分，规则随消费快照保存。"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re

DAY_TYPES = ("workday", "weekend", "holiday")
LEGACY_KEYS = {f"{d}_{p}_{r}" for d in DAY_TYPES for p in ("day", "night") for r in ("hourly", "cap")}


def amount(value, cents):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= 100000 or number != number.quantize(Decimal("0.01")):
            raise ValueError()
        return int(number * 100) if cents else float(number)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("价格必须为0至100000之间、最多两位小数的金额") from None


def minute(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("时段时间请使用 HH:MM 格式，范围为00:00至23:59")
    h, m = map(int, value.split(":"))
    return h * 60 + m


def text(value, label, limit=60):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{label}不能为空，且不能超过{limit}个字符")
    return value.strip()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("规则编号无效，请刷新页面后重试")
    return value


def rate(value, cents):
    if not isinstance(value, dict) or set(value) != {"hourly", "cap"}:
        raise ValueError("请完整填写每小时价格和封顶价格")
    suffix = "_cents" if cents else ""
    return {key + suffix: amount(value[key], cents) for key in ("hourly", "cap")}


def validate_pricing(values, cents=True, *, preserve_clock=False):
    if not isinstance(values, dict):
        raise ValueError("计费规则格式不正确")
    if "periods" not in values and "version" not in values:
        if set(values) != LEGACY_KEYS:
            raise ValueError("请完整填写计费规则")
        return {key + ("_cents" if cents else ""): amount(value, cents) for key, value in values.items()}
    if values.get("version") != 2:
        raise ValueError("不支持的计费规则版本")
    offset = values.get("timezone_offset_minutes", 480)
    if type(offset) is not int or not -720 <= offset <= 840 or offset % 15:
        raise ValueError("计费时区无效")
    result = {"version": 2, "timezone_offset_minutes": offset if preserve_clock else 480}
    for key in ("weekend_enabled", "holiday_enabled"):
        if type(values.get(key)) is not bool:
            raise ValueError("请设置周末和节假日计价开关")
        result[key] = values[key]
    periods = values.get("periods")
    if not isinstance(periods, list) or not 1 <= len(periods) <= 24:
        raise ValueError("请配置1至24个计费时段")
    occupied = [False] * 1440
    ids, names = set(), set()
    result["periods"] = []
    for item in periods:
        if not isinstance(item, dict):
            raise ValueError("时段格式不正确")
        pid, name = identifier(item.get("id")), text(item.get("name"), "时段名称", 30)
        if pid in ids or name in names:
            raise ValueError("时段名称和编号不能重复")
        ids.add(pid); names.add(name)
        start, end = minute(item.get("start")), minute(item.get("end"))
        length = (end - start) % 1440 or 1440
        for point in range(length):
            index = (start + point) % 1440
            if occupied[index]:
                raise ValueError("计费时段有重叠，请调整起止时间")
            occupied[index] = True
        rates = item.get("rates")
        if not isinstance(rates, dict) or set(rates) != set(DAY_TYPES):
            raise ValueError("请完整填写基础、周末和节假日价格")
        result["periods"].append({"id": pid, "name": name, "start": item["start"], "end": item["end"],
                                  "rates": {kind: rate(rates[kind], cents) for kind in DAY_TYPES}})
    if not all(occupied):
        raise ValueError("计费时段必须覆盖完整24小时，不能留有空档")
    result["periods"].sort(key=lambda item: item["start"])
    rules = values.get("date_rules", [])
    if not isinstance(rules, list) or len(rules) > 366:
        raise ValueError("特殊日期规则最多可设置366条")
    result["date_rules"] = []
    rule_ids = set()
    ranges = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("特殊日期规则格式不正确")
        rid, name = identifier(item.get("id")), text(item.get("name"), "日期规则名称")
        if rid in rule_ids:
            raise ValueError("日期规则编号不能重复")
        rule_ids.add(rid)
        try:
            start_date, end_date = date.fromisoformat(item["start_date"]), date.fromisoformat(item["end_date"])
            if item["start_date"] != start_date.isoformat() or item["end_date"] != end_date.isoformat() or start_date > end_date:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError("请填写有效的起止日期，结束日期不能早于开始日期") from None
        if any(start_date <= right and end_date >= left for left, right in ranges):
            raise ValueError("特殊日期范围不能重叠，请合并或调整日期")
        ranges.append((start_date, end_date))
        kind = item.get("kind")
        if kind not in (*DAY_TYPES, "special"):
            raise ValueError("特殊日期的计价方式无效")
        rule = {"id": rid, "name": name, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "kind": kind}
        if kind == "special":
            rates = item.get("rates")
            if not isinstance(rates, dict) or set(rates) != ids:
                raise ValueError("请为特殊节假日填写全部时段的价格")
            rule["rates"] = {pid: rate(rates[pid], cents) for pid in sorted(ids)}
        result["date_rules"].append(rule)
    result["date_rules"].sort(key=lambda item: (item["start_date"], item["id"]))
    return result


def public_pricing(values, cents=True, *, current=True):
    """当前配置固定北京时间；历史快照转换时显式保留原时钟。"""
    if values.get("version") == 2:
        result = deepcopy(values)
        if current:
            result["timezone_offset_minutes"] = 480
        def convert(value):
            return {key: value[key + "_cents"] / 100 for key in ("hourly", "cap")} if cents else value
        for period in result["periods"]:
            period["rates"] = {kind: convert(value) for kind, value in period["rates"].items()}
        for rule in result["date_rules"]:
            if rule["kind"] == "special":
                rule["rates"] = {pid: convert(value) for pid, value in rule["rates"].items()}
        return result
    suffix, divisor = ("_cents", 100) if cents else ("", 1)
    return {"version": 2, "timezone_offset_minutes": 480 if current else 0, "weekend_enabled": True, "holiday_enabled": False,
            "periods": [{"id": period, "name": name, "start": start, "end": end,
                         "rates": {kind: {key: values[f"{kind}_{period}_{key}{suffix}"] / divisor
                                          for key in ("hourly", "cap")} for kind in DAY_TYPES}}
                        for period, name, start, end in (("day", "日间", "08:00", "18:00"), ("night", "夜间", "18:00", "08:00"))],
            "date_rules": []}


def current_snapshot(raw):
    import json
    return json.dumps(validate_pricing(public_pricing(json.loads(raw))))
