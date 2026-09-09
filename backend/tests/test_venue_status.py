import unittest
from datetime import datetime, timedelta

from backend.tests import test_pricing
from backend.models import User, Role, Store, StoreMember, Consumption, VenueBooking, BookingSession, BookingDetails
from backend.access_models import BillingArea, ConsumptionArea, ConsumptionSegment, PasscodeRequest


class VenueStatusTests(unittest.TestCase):
    setUp = test_pricing.PricingApiTests.setUp
    tearDown = test_pricing.PricingApiTests.tearDown

    def get(self, store=1):
        return self.client.get(f"/api/v1/stores/{store}/venue-status")

    def session(self, db, sid, area=1, status="open"):
        now = datetime.utcnow()
        db.add(User(id=sid + 10, username=f"private-login-{sid}", email=f"private-{sid}@example.com",
                    name=f"玩家{sid}", role_id=1, password_hash="private-hash"))
        db.add(Consumption(id=sid, user_id=sid + 10, store_id=1, started_at=now - timedelta(hours=1),
                           ended_at=now, status=status, remark="private-remark"))
        if area is not None:
            db.add(ConsumptionArea(consumption_id=sid, area_id=area, pricing_json="{}"))

    def test_current_area_grouping_switch_and_pending_do_not_duplicate_users(self):
        now = datetime.utcnow()
        with self.sessions() as db:
            db.add(BillingArea(id=2, store_id=1, name="二楼", enabled=True, pricing_json="{}"))
            self.session(db, 1, area=2)
            self.session(db, 2)
            self.session(db, 3, status="paid")
            db.add(ConsumptionSegment(consumption_id=1, area_id=1, started_at=now - timedelta(hours=1),
                                      ended_at=now - timedelta(minutes=10), pricing_json="{}"))
            db.add(ConsumptionSegment(consumption_id=1, area_id=2, started_at=now - timedelta(minutes=10),
                                      active_consumption_id=1, pricing_json="{}"))
            for index, source, status in ((1, "switch", "issuing"), (2, "automatic", "review"),
                                          (3, "manual", "pending"), (4, "automatic", "ready"),
                                          (5, "switch", "failed")):
                db.add(PasscodeRequest(id=str(index), store_id=1, area_id=1, operator_id=1, recipient_id=11,
                    idempotency_key=str(index), remote_name=str(index), source=source, status=status,
                    lock_id="private-lock", credential_version=1, password_version=1,
                    encrypted_password="private-passcode", start_ms="0", end_ms="9999999999999"))
            db.commit()
        result = self.get()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        data = result.json()
        self.assertEqual((data["online_count"], data["pending_count"]), (2, 2))
        first, second = data["areas"]
        self.assertEqual([u["name"] for u in first["users"]], ["玩家2"])
        self.assertEqual([u["name"] for u in second["users"]], ["玩家1"])
        self.assertEqual(first["pending_count"], 2)
        current = second["users"][0]
        self.assertEqual(current["area_entered_at"], (now - timedelta(minutes=10)).isoformat() + "Z")
        self.assertGreaterEqual(current["elapsed_seconds"], 3600)
        self.assertNotIn("private-", result.text)
        self.assertEqual(set(current), {"session_id", "name", "avatar", "is_me", "started_at",
                                      "area_entered_at", "elapsed_seconds", "free", "free_until"})
        # 下机后下一次读取立即更新人数。
        with self.sessions() as db:
            db.get(Consumption, 1).status = "paid"; db.commit()
        self.assertEqual(self.get().json()["online_count"], 1)

    def test_disabled_and_legacy_unassigned_sessions_remain_visible(self):
        with self.sessions() as db:
            db.get(BillingArea, 1).enabled = False
            self.session(db, 1)
            self.session(db, 2, area=None)
            db.commit()
        data = self.get().json()
        self.assertEqual(data["online_count"], 2)
        self.assertFalse(data["areas"][0]["enabled"])
        self.assertEqual(data["areas"][1]["name"], "未分配区域")
        self.assertEqual(len(data["areas"][1]["users"]), 1)

    def test_whole_store_booking_and_free_session_expiry(self):
        now = datetime.utcnow()
        with self.sessions() as db:
            db.add(BillingArea(id=2, store_id=1, name="空闲区", pricing_json="{}"))
            db.add(VenueBooking(id=1, store_id=1, area_id=None, customer_name="private-client", contact="private-contact",
                started_at=now - timedelta(hours=2), ended_at=now + timedelta(hours=1), amount_cents=30000,
                request_key="whole", operator_id=1))
            self.session(db, 1)
            self.session(db, 2)
            db.add(BookingSession(consumption_id=1, booking_id=1, ends_at=now + timedelta(hours=1)))
            db.add(BookingSession(consumption_id=2, booking_id=1, ends_at=now - timedelta(seconds=1)))
            db.commit()
        result = self.get()
        data = result.json()
        self.assertEqual(data["online_count"], 1)
        self.assertTrue(data["areas"][0]["users"][0]["free"])
        self.assertTrue(all(a["booking"] and not a["booking"]["pending_payment"] for a in data["areas"]))
        self.assertEqual(data["areas"][1]["users"], [])
        self.assertNotIn("private-", result.text)
        # 只读场况不依赖后台过期任务，也不会改写消费。
        with self.sessions() as db:
            self.assertEqual(db.get(Consumption, 2).status, "open")

    def test_only_current_unexpired_booking_holds_are_shown(self):
        now = datetime.utcnow()
        with self.sessions() as db:
            for bid, area, status, hold in ((1, 1, "pending", now + timedelta(minutes=5)),
                                          (2, 2, "pending", now - timedelta(seconds=1)),
                                          (3, 3, "cancelled", now + timedelta(minutes=5))):
                if area > 1: db.add(BillingArea(id=area, store_id=1, name=f"区{area}", pricing_json="{}"))
                db.add(VenueBooking(id=bid, store_id=1, area_id=area, customer_name="客户", status=status,
                    started_at=now - timedelta(hours=1), ended_at=now + timedelta(hours=1), amount_cents=10000,
                    request_key=str(bid), operator_id=1))
                db.add(BookingDetails(booking_id=bid, deposit_percent=30, deposit_cents=3000, hold_until=hold))
            db.commit()
        areas = self.get().json()["areas"]
        self.assertTrue(areas[0]["booking"]["pending_payment"])
        self.assertIsNone(areas[1]["booking"])
        self.assertIsNone(areas[2]["booking"])

    def test_membership_scope_inactive_members_and_admin_access(self):
        with self.sessions() as db:
            db.add(Store(id=2, name="其他店", created_by=1))
            db.commit()
        self.assertEqual(self.get(2).status_code, 200)
        self.assertEqual(self.get(999).status_code, 404)
        with self.sessions() as db:
            role = db.get(Role, 1); role.name = "member"; role.permissions_json = "[]"
            db.commit()
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.get(2).status_code, 403)
        with self.sessions() as db:
            db.query(StoreMember).filter_by(store_id=1, user_id=1).one().is_active = False
            db.commit()
        self.assertEqual(self.get().status_code, 403)
        with self.sessions() as db:
            db.query(StoreMember).filter_by(store_id=1, user_id=1).one().is_active = True
            db.get(Store, 1).is_active = False
            db.commit()
        self.assertEqual(self.get().status_code, 403)


if __name__ == "__main__": unittest.main()
