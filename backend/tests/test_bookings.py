import json
import unittest
from datetime import datetime, timedelta, timezone

from backend.tests import test_pricing


class BookingTests(unittest.TestCase):
    setUp = test_pricing.PricingApiTests.setUp
    tearDown = test_pricing.PricingApiTests.tearDown

    def payload(self, **kwargs):
        now = datetime.now(timezone.utc)
        return dict(area_id=1, customer_name="活动客户", started_at=(now - timedelta(minutes=1)).isoformat(),
                    ended_at=(now + timedelta(hours=2)).isoformat(), amount=299.99, request_key="booking-test", **kwargs)

    def create(self, data=None):
        result = self.client.post("/api/v1/stores/1/bookings", json=data or self.payload())
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_overlap_adjacent_areas_whole_store_and_idempotency(self):
        data = self.payload()
        first = self.create(data)
        self.assertEqual(self.create(data)["id"], first["id"])
        other = dict(data, request_key="second")
        self.assertEqual(self.client.post("/api/v1/stores/1/bookings", json=other).status_code, 409)
        other.update(area_id=None)
        self.assertEqual(self.client.post("/api/v1/stores/1/bookings", json=other).status_code, 409)
        other.update(area_id=1, started_at=data["ended_at"], ended_at=(datetime.fromisoformat(data["ended_at"]) + timedelta(hours=1)).isoformat())
        self.create(other)
        from backend.access_models import BillingArea
        with self.sessions() as db:
            db.add(BillingArea(id=2, store_id=1, name="另一区", pricing_json="{}")); db.commit()
        self.create(dict(data, area_id=2, request_key="another-area"))
        self.assertEqual(self.client.post("/api/v1/stores/1/bookings", json=dict(data, amount=1)).status_code, 409)

    def test_receipts_refunds_reports_and_duplicate_requests(self):
        row = self.create()
        base = f"/api/v1/stores/1/bookings/{row['id']}"
        for _ in range(2):
            result = self.client.post(base + "/pay")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["paid"], 299.99)
        self.assertEqual(self.client.get("/api/v1/stores/1/reports").json()["revenue"], 299.99)
        self.assertEqual(self.client.post(base + "/cancel", json={}).status_code, 409)
        for _ in range(2):
            result = self.client.post(base + "/cancel", json={"refund_confirmed": True})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["refunded"], 299.99)
        self.assertEqual(self.client.get("/api/v1/stores/1/reports").json()["revenue"], 0)
        self.assertEqual(self.client.post(base + "/pay").status_code, 409)
        self.create(dict(self.payload(), request_key="replacement"))

    def test_entry_switch_and_async_finalization_blocked_until_cancel(self):
        from fastapi import HTTPException
        from backend.area_billing import begin, finalize
        from backend.area_switching import switch
        from backend.models import Consumption
        from backend.access_models import BillingArea, ConsumptionArea, MemberOccupancy
        from types import SimpleNamespace
        import time
        row = self.create()
        with self.sessions() as db:
            with self.assertRaises(HTTPException) as error:
                begin(db, store_id=1, user_id=1, operator_id=1, area_id=1, key="normal", started_at=None, secure=False)
            self.assertEqual(error.exception.status_code, 409); db.rollback()
            request = SimpleNamespace(source="automatic", store_id=1, area_id=1, recipient_id=1, end_ms=str(int(time.time()*1000)+3600000), pricing_json="{}")
            with self.assertRaisesRegex(HTTPException, "已包场"):
                finalize(db, request)
            db.rollback()
            prices = db.get(BillingArea, 1).pricing_json
            db.add(BillingArea(id=2, store_id=1, name="另一区", pricing_json=prices))
            now = datetime.utcnow()
            db.add(Consumption(id=1, store_id=1, user_id=1, operator_id=1, started_at=now, ended_at=now))
            db.add(ConsumptionArea(consumption_id=1, area_id=2, pricing_json=prices))
            db.add(MemberOccupancy(user_id=1, area_id=2, consumption_id=1)); db.commit()
            with self.assertRaisesRegex(HTTPException, "已包场"):
                switch(db, consumption_id=1, user_id=1, operator_id=1, area_id=1, key="switch", secure=False)
            db.rollback()
        self.client.post(f"/api/v1/stores/1/bookings/{row['id']}/cancel", json={})
        with self.sessions() as db:
            result, _ = switch(db, consumption_id=1, user_id=1, operator_id=1, area_id=1, key="switch", secure=False)
            self.assertEqual(result.id, 1)

    def test_open_session_blocks_booking(self):
        from backend.area_billing import begin
        with self.sessions() as db:
            begin(db, store_id=1, user_id=1, operator_id=1, area_id=1, key="normal", started_at=None, secure=False)
        result = self.client.post("/api/v1/stores/1/bookings", json=self.payload())
        self.assertEqual(result.status_code, 409, result.text)

    def test_future_reservation_warns_of_sessions_and_whole_store_blocks_new_area(self):
        from backend.area_billing import begin
        from backend.access_models import BillingArea
        from backend.bookings import guard_entry
        from backend.models import VenueBooking
        from fastapi import HTTPException
        data = self.payload(); data.update(area_id=None, started_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        row = self.create(data)
        with self.sessions() as db:
            begin(db, store_id=1, user_id=1, operator_id=1, area_id=1, key="normal", started_at=None, secure=False)
        self.assertEqual(self.client.get("/api/v1/stores/1/bookings").json()["items"][0]["occupancy_count"], 1)
        with self.sessions() as db:
            db.add(BillingArea(id=2, store_id=1, name="新区域", pricing_json="{}"))
            db.get(VenueBooking, row["id"]).started_at = datetime.utcnow() - timedelta(minutes=1); db.commit()
            with self.assertRaises(HTTPException): guard_entry(db, 1, 2)

    def test_time_price_and_scope_validation(self):
        data = self.payload()
        for invalid in (dict(data, amount=0.001), dict(data, started_at="2026-09-08T10:00:00"),
                        dict(data, ended_at=data["started_at"]), dict(data, customer_name="   "), dict(data, area_id=99)):
            self.assertIn(self.client.post("/api/v1/stores/1/bookings", json=invalid).status_code, (404, 422))
        row = self.create()
        from backend.models import Role, Store
        with self.sessions() as db:
            db.add(Store(id=2, name="其他门店", created_by=1)); db.commit()
        self.assertEqual(self.client.post(f"/api/v1/stores/2/bookings/{row['id']}/pay").status_code, 404)
        with self.sessions() as db:
            role = db.get(Role, 1); role.name = "manager"; role.permissions_json = json.dumps(["store.consumptions.manage"]); db.commit()
        self.assertEqual(self.client.get("/api/v1/stores/2/bookings").status_code, 403)
        with self.sessions() as db:
            role = db.get(Role, 1); role.permissions_json = "[]"; db.commit()
        self.assertEqual(self.client.get("/api/v1/stores/1/bookings").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/stores/1/bookings", json=data).status_code, 403)


class BookingSchemaTests(unittest.TestCase):
    def test_additive_schema_preserves_data_and_rejects_unknown_damage(self):
        from sqlalchemy import create_engine, inspect, text
        from backend.initialize import current_metadata, prepare_schema
        engine = create_engine("sqlite://")
        metadata = current_metadata()
        metadata.create_all(engine, tables=[t for t in metadata.sorted_tables if t.name != "venue_bookings"])
        with engine.begin() as db:
            db.execute(text("INSERT INTO roles (id, name, permissions_json, is_system) VALUES (1, 'kept', '[]', 1)"))
        prepare_schema(engine); prepare_schema(engine)
        self.assertIn("venue_bookings", inspect(engine).get_table_names())
        with engine.connect() as db:
            self.assertEqual(db.scalar(text("SELECT name FROM roles WHERE id = 1")), "kept")
        with engine.begin() as db:
            db.execute(text("DROP TABLE venue_bookings")); db.execute(text("ALTER TABLE roles ADD COLUMN unexpected INTEGER"))
        with self.assertRaises(RuntimeError): prepare_schema(engine)
        self.assertNotIn("venue_bookings", inspect(engine).get_table_names())
        engine.dispose()


if __name__ == "__main__": unittest.main()
