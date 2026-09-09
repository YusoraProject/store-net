import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from fastapi import HTTPException

from backend.tests import test_pricing
from backend.models import (Role, User, StoreMember, MemberBenefit, BenefitLedger, VenueBooking,
                            BookingDetails, BookingInvitation, BookingSession, Consumption)
from backend.access_models import BillingArea, MemberOccupancy
from backend.booking_config import BEIJING


class MemberBookingTests(unittest.TestCase):
    def setUp(self):
        test_pricing.PricingApiTests.setUp(self)
        with self.sessions() as db:
            db.add(Role(id=2, name="member", permissions_json="[]"))
            for uid in (2, 3, 4):
                db.add(User(id=uid, username=f"member{uid}", name=f"会员{uid}", email=f"{uid}@example.com", role_id=2, password_hash="unused"))
                db.add(StoreMember(store_id=1, user_id=uid))
            for uid in (1, 2, 3, 4):
                db.add(MemberBenefit(store_id=1, user_id=uid, paid_cents=100000, bonus_cents=5000, times_count=5))
            db.commit()
        self.config = {"slots": [{"id": "all-day", "name": "全天包场", "area_id": 1, "start": "00:00", "end": "00:00", "price": 100.01, "enabled": True}]}
        self.assertEqual(self.client.put("/api/v1/stores/1/booking-slots", json=self.config).status_code, 200)
        self.assertEqual(self.client.put("/api/v1/stores/1/booking-config", json={"deposit_percent": 33}).status_code, 200)

    tearDown = test_pricing.PricingApiTests.tearDown

    def as_user(self, uid):
        with self.sessions() as db:
            self.user = db.get(User, uid)

    def create(self, key="member-booking"):
        result = self.client.post("/api/v1/me/stores/1/bookings", json={"booking_date": datetime.now(BEIJING).date().isoformat(), "slot_id": "all-day", "request_key": key})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def post(self, row, action, body=None, manager=False):
        prefix = "" if manager else "/me"
        return self.client.post(f"/api/v1{prefix}/stores/1/bookings/{row['id']}/{action}", json=body or {})

    def prepare_guest(self):
        row = self.create()
        self.assertEqual(self.post(row, "deposit").status_code, 200)
        self.assertEqual(self.post(row, "invite", {"user_ids": [2]}).status_code, 200)
        self.as_user(2)
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 200)
        return row

    def test_server_price_percent_snapshot_and_idempotent_balance_payment(self):
        row = self.create()
        self.assertEqual(row["deposit"], 33.01)
        self.config["slots"][0]["price"] = 900
        self.client.put("/api/v1/stores/1/booking-slots", json=self.config)
        self.client.put("/api/v1/stores/1/booking-config", json={"deposit_percent": 80})
        self.assertEqual(self.create()["id"], row["id"])
        for _ in range(2):
            paid = self.post(row, "deposit")
            self.assertEqual(paid.status_code, 200, paid.text)
            self.assertEqual(paid.json()["paid"], 33.01)
            self.assertTrue(paid.json()["deposit_paid"])
        with self.sessions() as db:
            wallet = db.scalar(select(MemberBenefit).where(MemberBenefit.user_id == 1))
            self.assertEqual((wallet.paid_cents, wallet.bonus_cents, wallet.times_count), (96699, 5000, 5))
            self.assertEqual(len(db.scalars(select(BenefitLedger)).all()), 1)
        tampered = self.client.post("/api/v1/me/stores/1/bookings", json={"booking_date": datetime.now(BEIJING).date().isoformat(), "slot_id": "all-day", "request_key": "tampered", "amount": 0.01})
        self.assertEqual(tampered.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/stores/1/reports").json()["revenue"], 33.01)

    def test_unpaid_pending_declined_outsiders_and_accepted_admission(self):
        row = self.create()
        self.assertEqual(self.post(row, "invite", {"user_ids": [2]}).status_code, 409)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["blocked"])
        self.post(row, "deposit")
        self.post(row, "invite", {"user_ids": [2]})
        self.post(row, "invite", {"user_ids": [2]})
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(BookingInvitation)).all()), 2)
        self.as_user(3)
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 403)
        self.assertEqual(self.post(row, "deposit").status_code, 403)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["blocked"])
        self.as_user(2)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["blocked"])
        self.assertEqual(self.post(row, "respond", {"accept": False}).status_code, 200)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["blocked"])
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 200)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["free"])

    def test_free_session_never_charges_balance_bonus_or_times_card(self):
        row = self.prepare_guest()
        result = self.client.post("/api/v1/me/consumption/start", json={"store_id": 1, "area_id": 1, "idempotency_key": "guest-free-start"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["booking_id"], row["id"])
        quote = self.client.post("/api/v1/me/consumption/quote", json={})
        self.assertEqual(quote.json()["amount_due"], 0)
        for _ in range(2):
            result = self.client.post("/api/v1/me/consumption/checkout", json={"payment_method": "auto", "idempotency_key": "guest-free-finish"})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["payment_method"], "booking")
            self.assertEqual(result.json()["amount_paid"], 0)
        with self.sessions() as db:
            wallet = db.scalar(select(MemberBenefit).where(MemberBenefit.user_id == 2))
            self.assertEqual((wallet.paid_cents, wallet.bonus_cents, wallet.times_count), (100000, 5000, 5))
            self.assertIsNone(db.get(MemberOccupancy, 2))
            self.assertEqual(len(db.scalars(select(BenefitLedger).where(BenefitLedger.user_id == 2)).all()), 0)

    def test_expiry_and_declining_end_free_sessions(self):
        row = self.prepare_guest()
        from backend.area_billing import begin
        with self.sessions() as db:
            started, _ = begin(db, store_id=1, user_id=2, operator_id=2, area_id=1, key="free-expire", started_at=None, secure=False)
            started.started_at = datetime.utcnow() - timedelta(minutes=20)
            free = db.get(BookingSession, started.id)
            free.ends_at = datetime.utcnow() - timedelta(minutes=1)
            cid = started.id
            db.commit()
        self.assertIsNone(self.client.get("/api/v1/me/consumption/current").json())
        with self.sessions() as db:
            session = db.get(Consumption, cid)
            self.assertEqual((session.status, session.paid_cents, session.payment_method), ("paid", 0, "booking"))
            self.assertIsNone(db.get(MemberOccupancy, 2))
            started, _ = begin(db, store_id=1, user_id=2, operator_id=2, area_id=1, key="free-decline", started_at=None, secure=False)
            cid = started.id
        self.assertEqual(self.post(row, "respond", {"accept": False}).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.get(Consumption, cid).status, "paid")
            self.assertIsNone(db.get(MemberOccupancy, 2))

    def test_balance_and_offline_refund_are_separate_and_atomic(self):
        row = self.create(); self.post(row, "deposit")
        self.assertEqual(self.post(row, "pay", manager=True).status_code, 200)
        self.assertEqual(self.post(row, "cancel", manager=True).status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(MemberBenefit.paid_cents).where(MemberBenefit.user_id == 1)), 96699)
        for _ in range(2):
            result = self.post(row, "cancel", {"refund_confirmed": True}, manager=True)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["refunded"], 100.01)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(MemberBenefit.paid_cents).where(MemberBenefit.user_id == 1)), 100000)
            self.assertEqual(len(db.scalars(select(BenefitLedger)).all()), 2)
        self.assertEqual(self.client.get("/api/v1/stores/1/reports").json()["revenue"], 0)

    def test_unpaid_hold_expires_and_insufficient_balance_is_atomic(self):
        with self.sessions() as db:
            wallet = db.scalar(select(MemberBenefit).where(MemberBenefit.user_id == 1)); wallet.paid_cents = 0; db.commit()
        row = self.create()
        self.assertEqual(self.post(row, "deposit").status_code, 402)
        with self.sessions() as db:
            self.assertEqual(db.get(VenueBooking, row["id"]).paid_cents, 0)
            self.assertIsNone(db.get(BookingDetails, row["id"]).deposit_paid_at)
            db.get(BookingDetails, row["id"]).hold_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
        self.assertEqual(self.post(row, "deposit").status_code, 409)
        replacement = self.create("replacement")
        self.assertNotEqual(replacement["id"], row["id"])
        self.assertEqual(len(self.client.get("/api/v1/me/stores/1/bookings").json()), 2)

    def test_manual_selected_host_and_guests_require_deposit_and_consent(self):
        result = self.client.post("/api/v1/stores/1/bookings", json={"slot_id": "all-day", "booking_date": datetime.now(BEIJING).date().isoformat(), "customer_name": "手动包场", "host_user_id": 4, "user_ids": [2], "request_key": "manual-selected"})
        self.assertEqual(result.status_code, 200, result.text)
        row = result.json()
        self.as_user(2)
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 409)
        self.as_user(4)
        self.assertEqual(self.post(row, "deposit").status_code, 200)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["free"])
        self.as_user(2)
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 200)
        self.assertTrue(self.client.get("/api/v1/me/stores/1/areas").json()[0]["booking"]["free"])

    def test_free_session_cannot_switch_outside_booking(self):
        row = self.prepare_guest()
        from backend.area_billing import begin
        from backend.area_switching import switch
        with self.sessions() as db:
            prices = db.get(BillingArea, 1).pricing_json
            db.add(BillingArea(id=2, store_id=1, name="普通区", pricing_json=prices)); db.commit()
            started, _ = begin(db, store_id=1, user_id=2, operator_id=2, area_id=1, key="free-switch", started_at=None, secure=False)
            with self.assertRaisesRegex(HTTPException, "结束包场免费上机"):
                switch(db, consumption_id=started.id, user_id=2, operator_id=2, area_id=2, key="outside", secure=False)
            db.rollback()

    def test_async_passcode_finalization_keeps_free_admission_binding(self):
        row = self.prepare_guest()
        from backend.area_billing import finalize
        from backend.bookings import admission_pricing
        with self.sessions() as db:
            booking = db.get(VenueBooking, row["id"])
            request = SimpleNamespace(source="automatic", store_id=1, area_id=1, recipient_id=2, operator_id=2,
                pricing_json=admission_pricing(db.get(BillingArea, 1).pricing_json, booking), end_ms=str(int(time.time() * 1000) + 3600000))
            cid = finalize(db, request); db.flush()
            self.assertEqual(db.get(BookingSession, cid).booking_id, row["id"])
            db.rollback()
            booking = db.get(VenueBooking, row["id"]); booking.status = "cancelled"; db.commit()
            with self.assertRaisesRegex(HTTPException, "包场资格已变化"):
                finalize(db, request)

    def test_timezone_is_locked_and_cross_midnight_booking_uses_beijing(self):
        config = test_pricing.rules(); config["timezone_offset_minutes"] = -300
        self.assertEqual(self.client.put("/api/v1/stores/1/pricing", json=config).json()["timezone_offset_minutes"], 480)
        self.config["slots"][0].update(start="22:00", end="02:00")
        self.client.put("/api/v1/stores/1/booking-slots", json=self.config)
        day = datetime.now(BEIJING).date() + timedelta(days=1)
        result = self.client.post("/api/v1/me/stores/1/bookings", json={"booking_date": day.isoformat(), "slot_id": "all-day", "request_key": "overnight"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["started_at"], day.isoformat() + "T14:00:00Z")
        self.assertEqual(result.json()["ended_at"], day.isoformat() + "T18:00:00Z")

    def test_configuration_and_membership_permissions(self):
        self.assertEqual(self.client.put("/api/v1/stores/1/booking-config", json={"deposit_percent": 0}).status_code, 422)
        self.as_user(2)
        self.assertEqual(self.client.put("/api/v1/stores/1/booking-config", json={"deposit_percent": 50}).status_code, 403)
        self.assertEqual(self.client.put("/api/v1/stores/1/booking-slots", json=self.config).status_code, 403)
        self.as_user(1)
        row = self.create(); self.post(row, "deposit"); self.post(row, "invite", {"user_ids": [2]})
        with self.sessions() as db:
            member = db.scalar(select(StoreMember).where(StoreMember.user_id == 2)); member.is_active = False; db.commit()
        self.as_user(2)
        self.assertEqual(self.post(row, "respond", {"accept": True}).status_code, 403)

    def test_parallel_reservations_payments_and_refunds(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from fastapi.testclient import TestClient
        original_sessions = self.sessions
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "booking-concurrency.db"
            source = self.engine.raw_connection()
            target = sqlite3.connect(path)
            source.driver_connection.backup(target)
            target.close(); source.close()
            engine = create_engine("sqlite:///" + path.as_posix(), connect_args={"check_same_thread": False, "timeout": 15})
            self.sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
            def together(callback):
                barrier = Barrier(2)
                # 不进入TestClient上下文，避免真实startup/后台任务；每个请求用独立连接。
                def run(index):
                    client = TestClient(self.app)
                    try:
                        barrier.wait(timeout=10)
                        return callback(client, index)
                    finally:
                        client.close()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    return list(pool.map(run, (0, 1)))
            try:
                results = together(lambda client, i: client.post("/api/v1/me/stores/1/bookings", json={
                    "booking_date": datetime.now(BEIJING).date().isoformat(), "slot_id": "all-day", "request_key": f"parallel-{i}"}))
                self.assertEqual(sorted(r.status_code for r in results), [200, 409])
                bid = next(r.json()["id"] for r in results if r.status_code == 200)
                paid = together(lambda client, _: client.post(f"/api/v1/me/stores/1/bookings/{bid}/deposit"))
                self.assertEqual([r.status_code for r in paid], [200, 200])
                with self.sessions() as db:
                    self.assertEqual(db.scalar(select(MemberBenefit.paid_cents).where(MemberBenefit.user_id == 1)), 96699)
                    self.assertEqual(len(db.scalars(select(BenefitLedger)).all()), 1)
                refunds = together(lambda client, _: client.post(f"/api/v1/stores/1/bookings/{bid}/cancel", json={}))
                self.assertEqual([r.status_code for r in refunds], [200, 200])
                with self.sessions() as db:
                    self.assertEqual(db.scalar(select(MemberBenefit.paid_cents).where(MemberBenefit.user_id == 1)), 100000)
                    self.assertEqual(len(db.scalars(select(BenefitLedger)).all()), 2)
            finally:
                self.sessions = original_sessions
                engine.dispose()


if __name__ == "__main__": unittest.main()
