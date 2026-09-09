import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.pricing import validate_pricing, public_pricing, LEGACY_KEYS
from backend.billing import quote_cents


def rules():
    return {"version": 2, "timezone_offset_minutes": 480, "weekend_enabled": True, "holiday_enabled": True,
            "periods": [{"id": "all", "name": "全天", "start": "00:00", "end": "00:00",
                         "rates": {"workday": {"hourly": 6, "cap": 0}, "weekend": {"hourly": 12, "cap": 0},
                                   "holiday": {"hourly": 18, "cap": 0}}}], "date_rules": []}


def quote(config, start, end):
    def instant(value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return quote_cents(validate_pricing(config), instant(start), instant(end))


class PricingTests(unittest.TestCase):
    def test_custom_period_boundaries(self):
        config = rules()
        config["periods"] = []
        for pid, start, end, hourly in (("early", "00:00", "08:00", 6), ("mid", "08:00", "10:00", 12), ("late", "10:00", "00:00", 18)):
            config["periods"].append({"id": pid, "name": pid, "start": start, "end": end,
                                      "rates": {k: {"hourly": hourly, "cap": 0} for k in ("workday", "weekend", "holiday")}})
        self.assertEqual(quote(config, "2026-09-07T07:30", "2026-09-07T10:30"), (180, 3600))

    def test_beijing_clock_and_holiday_midnight(self):
        config = rules(); config["timezone_offset_minutes"] = 480
        config["date_rules"] = [{"id": "national", "name": "国庆", "start_date": "2026-10-01", "end_date": "2026-10-07", "kind": "holiday"}]
        self.assertEqual(quote(config, "2026-09-30T15:30+00:00", "2026-09-30T16:30+00:00"), (60, 1200))
        self.assertEqual(quote(config, "2026-10-07T15:00+00:00", "2026-10-07T17:00+00:00"), (120, 2400))

    def test_special_holiday_and_switches(self):
        config = rules()
        config["date_rules"] = [{"id": "event", "name": "活动", "start_date": "2026-09-12", "end_date": "2026-09-13", "kind": "special", "rates": {"all": {"hourly": 30, "cap": 25}}}]
        self.assertEqual(quote(config, "2026-09-12T10:00", "2026-09-12T11:00"), (60, 2500))
        config["holiday_enabled"] = False
        self.assertEqual(quote(config, "2026-09-12T10:00", "2026-09-12T11:00"), (60, 1200))
        config["weekend_enabled"] = False
        self.assertEqual(quote(config, "2026-09-12T10:00", "2026-09-12T11:00"), (60, 600))

    def test_makeup_workday_overrides_weekend(self):
        config = rules(); config["holiday_enabled"] = False
        config["date_rules"] = [{"id": "work", "name": "调休", "start_date": "2026-09-12", "end_date": "2026-09-12", "kind": "workday"}]
        self.assertEqual(quote(config, "2026-09-12T10:00", "2026-09-12T11:00"), (60, 600))

    def test_midnight_caps_and_zero_cap(self):
        config = rules()
        config["periods"][0]["rates"]["workday"]["cap"] = 5
        self.assertEqual(quote(config, "2026-09-07T23:00", "2026-09-08T01:00"), (120, 1000))
        config["periods"][0]["rates"]["workday"]["cap"] = 0
        self.assertEqual(quote(config, "2026-09-07T23:00", "2026-09-08T01:00"), (120, 1200))

    def test_cross_midnight_period_shares_same_day_cap(self):
        config = public_pricing({key + "_cents": 600 if key.endswith("hourly") else 500 for key in LEGACY_KEYS})
        self.assertEqual(quote(config, "2026-09-07T00:00", "2026-09-08T00:00"), (1440, 1000))

    def test_rounding_to_minutes_and_cents(self):
        config = rules(); config["periods"][0]["rates"]["workday"]["hourly"] = 0.61
        self.assertEqual(quote(config, "2026-09-07T10:00:00", "2026-09-07T10:00:01"), (1, 2))
        with self.assertRaises(ValueError): quote(config, "2026-09-07T10:00", "2026-09-07T10:00")

    def test_full_day_period_has_no_extra_boundary_at_its_display_time(self):
        config = rules()
        config["periods"][0].update(start="08:00", end="08:00")
        self.assertEqual(quote(config, "2026-09-07T07:59:30", "2026-09-07T08:00:30"), (1, 10))

    def test_legacy_snapshots_keep_original_clock(self):
        old = {key + "_cents": 800 if key.endswith("hourly") else 4000 for key in LEGACY_KEYS}
        old["workday_day_hourly_cents"] = 1200
        start, end = datetime(2026, 9, 7, 7, 30), datetime(2026, 9, 7, 8, 30)
        self.assertEqual(quote_cents(SimpleNamespace(**old), start, end), (60, 1000))
        converted = public_pricing(old, current=False)
        self.assertEqual(converted["timezone_offset_minutes"], 0)
        self.assertEqual(quote_cents(validate_pricing(converted, preserve_clock=True), start, end), (60, 1000))

    def test_validation_rejects_gaps_overlap_duplicate_ids_and_bad_prices(self):
        for change, message in [
            (lambda r: r["periods"][0].update(end="23:00"), "空档"),
            (lambda r: r["periods"].append(dict(copy.deepcopy(r["periods"][0]), id="two", name="另一段")), "重叠"),
            (lambda r: r["periods"].append(copy.deepcopy(r["periods"][0])), "重复"),
            (lambda r: r["periods"][0].update(start="24:00"), "HH:MM"),
            (lambda r: r["periods"][0]["rates"]["workday"].update(hourly=0.001), "价格"),
            (lambda r: r["periods"][0]["rates"]["workday"].update(hourly=float("nan")), "价格"),
            (lambda r: r["periods"][0]["rates"]["workday"].update(hourly=True), "价格"),
        ]:
            with self.subTest(message=message):
                config = rules(); change(config)
                with self.assertRaisesRegex(ValueError, message): validate_pricing(config)

    def test_date_validation_and_roundtrip(self):
        config = rules()
        config["date_rules"] = [{"id": "special", "name": "春节", "start_date": "2026-02-16", "end_date": "2026-02-20", "kind": "special", "rates": {"all": {"hourly": 23.45, "cap": 88.88}}}]
        self.assertEqual(public_pricing(validate_pricing(config)), config)
        config["date_rules"].append(dict(config["date_rules"][0], id="overlap"))
        with self.assertRaisesRegex(ValueError, "重叠"): validate_pricing(config)
        config["date_rules"] = [dict(config["date_rules"][0], start_date="2026-02-30")]
        with self.assertRaisesRegex(ValueError, "日期"): validate_pricing(config)


class PricingApiTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from fastapi.testclient import TestClient
        from backend.main import app, get_db, current_user
        from backend.initialize import current_metadata
        from backend.models import Role, User, Store, StoreMember, StorePricing
        from backend.access_models import BillingArea
        from backend.auth import PERMISSIONS
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        current_metadata().create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.config = rules()
        with self.sessions() as db:
            db.add(Role(id=1, name="admin", permissions_json=json.dumps(sorted(PERMISSIONS))))
            db.add(User(id=1, username="testadmin", email="test@example.com", name="测试", role_id=1, password_hash="unused"))
            db.add(Store(id=1, name="测试店", created_by=1))
            db.add(StoreMember(store_id=1, user_id=1, store_role="manager"))
            db.add(StorePricing(store_id=1))
            db.add(BillingArea(id=1, store_id=1, name="测试区", pricing_json=json.dumps(validate_pricing(self.config)), enabled=True, auto_issue=False))
            db.commit()
            self.user = db.get(User, 1)
        def get_test_db():
            with self.sessions() as db: yield db
        self.app = app
        self.previous = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[current_user] = lambda: self.user
        # 不进入应用startup，避免启动真实数据库及门锁后台线程。
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()
        self.app.dependency_overrides.update(self.previous)
        self.engine.dispose()

    def test_both_editors_share_rules_and_invalid_updates_are_atomic(self):
        base = "/api/v1/access/stores/1/areas/1"
        config = rules(); config["weekend_enabled"] = False
        response = self.client.put(base, json={"name": "测试区", "pricing": config})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/v1/stores/1/pricing").json(), config)
        invalid = copy.deepcopy(config); invalid["periods"][0]["end"] = "20:00"
        rejected = self.client.put("/api/v1/stores/1/pricing", json=invalid)
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(self.client.get("/api/v1/stores/1/pricing").json(), config)
        config["periods"][0]["rates"]["workday"]["hourly"] = 10.25
        self.assertEqual(self.client.put("/api/v1/stores/1/pricing", json=config).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/access/stores/1/areas").json()[0]["pricing"], config)

    def test_started_consumption_keeps_snapshot_after_price_update(self):
        start = self.client.post("/api/v1/stores/1/consumptions/start", json={"store_id": 1, "user_id": 1, "area_id": 1, "started_at": "2026-09-07T10:00:00"})
        self.assertEqual(start.status_code, 200, start.text)
        config = rules(); config["periods"][0]["rates"]["workday"]["hourly"] = 99
        self.assertEqual(self.client.put("/api/v1/stores/1/pricing", json=config).status_code, 200)
        result = self.client.post(f"/api/v1/stores/1/consumptions/{start.json()['id']}/checkout", json={"ended_at": "2026-09-07T11:00:00", "payment_method": "cash", "cash_amount": 6, "idempotency_key": "snapshot-checkout"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["amount_due"], 6)

    def test_returning_to_area_shares_cap_and_new_snapshot_gets_own_cap(self):
        from backend.area_switching import quote_accumulated
        from backend.models import Consumption
        from backend.access_models import ConsumptionSegment
        config = rules(); config["periods"][0]["rates"]["workday"]["cap"] = 10
        stored = json.dumps(validate_pricing(config))
        with self.sessions() as db:
            row = Consumption(id=1, store_id=1, user_id=1, operator_id=1, started_at=datetime(2026,9,7,8), ended_at=datetime(2026,9,7,8))
            db.add(row)
            for area, hour in ((1,8), (2,9), (1,10)):
                db.add(ConsumptionSegment(consumption_id=1, area_id=area, started_at=datetime(2026,9,7,hour), ended_at=datetime(2026,9,7,hour+1), pricing_json=stored))
            db.commit()
            self.assertEqual(quote_accumulated(db,row,None,datetime(2026,9,7,11)), (180,1600))
            final = db.query(ConsumptionSegment).order_by(ConsumptionSegment.id.desc()).first()
            changed = copy.deepcopy(config); changed["periods"][0]["rates"]["workday"]["hourly"] = 7
            final.pricing_json = json.dumps(validate_pricing(changed)); db.commit()
            self.assertEqual(quote_accumulated(db,row,None,datetime(2026,9,7,11)), (180,1900))

    def test_format_upgrade_does_not_reset_legacy_cap(self):
        from backend.area_switching import quote_accumulated
        from backend.models import Consumption
        from backend.access_models import ConsumptionSegment
        old = {key + "_cents": 600 if key.endswith("hourly") else 1000 for key in LEGACY_KEYS}
        new = validate_pricing(public_pricing(old, current=False), preserve_clock=True)
        with self.sessions() as db:
            row = Consumption(id=1, store_id=1, user_id=1, operator_id=1, started_at=datetime(2026,9,7,8), ended_at=datetime(2026,9,7,8))
            db.add(row)
            for hour, price in ((8, old), (9, new)):
                db.add(ConsumptionSegment(consumption_id=1, area_id=1, started_at=datetime(2026,9,7,hour), ended_at=datetime(2026,9,7,hour+1), pricing_json=json.dumps(price)))
            db.commit()
            self.assertEqual(quote_accumulated(db,row,None,datetime(2026,9,7,10)), (120,1000))

    def test_multi_area_store_cannot_overwrite_default_pricing(self):
        result = self.client.post("/api/v1/access/stores/1/areas", json={"name":"另一区域","pricing":rules()})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get("/api/v1/stores/1/pricing").status_code,409)
        self.assertEqual(self.client.put("/api/v1/stores/1/pricing",json=rules()).status_code,409)

    def test_members_cannot_update_prices(self):
        from backend.models import Role
        with self.sessions() as db:
            row = db.get(Role, 1); row.name = "member"; row.permissions_json = "[]"; db.commit()
        result = self.client.put("/api/v1/stores/1/pricing", json=rules())
        self.assertEqual(result.status_code, 403)
        result = self.client.put("/api/v1/access/stores/1/areas/1", json={"name":"测试区","pricing":rules()})
        self.assertEqual(result.status_code, 403)


if __name__ == "__main__": unittest.main()
