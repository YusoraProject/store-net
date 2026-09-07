import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_tmp.name) / 'api.db').as_posix()}"
os.environ["ADMIN_PASSWORD"] = "AdminPass123"

from fastapi.testclient import TestClient  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import app, initialize  # noqa: E402
from backend.models import User  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        from backend.access_models import AccessBase
        AccessBase.metadata.create_all(engine)
        initialize()
        cls.client = TestClient(app)
        cls.admin_header = cls.login("admin", "AdminPass123")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        engine.dispose()
        _tmp.cleanup()

    @classmethod
    def login(cls, identifier, password):
        response = cls.client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_registration_duplicate_and_server_permissions(self):
        payload = {"username": "member1", "email": "member1@example.com", "password": "MemberPass123"}
        created = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/register", json=payload).status_code, 409)
        header = {"Authorization": f"Bearer {created.json()['token']}"}
        self.assertEqual(self.client.get("/api/v1/users/me/permissions", headers=header).json()["permissions"], [])
        self.assertEqual(self.client.post("/api/v1/stores", headers=header, json={"name": "Forbidden"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/stats", headers=header).status_code, 403)

    def test_registration_statistics(self):
        self.assertEqual(self.client.get("/api/v1/admin/stats").status_code, 401)
        response = self.client.get("/api/v1/admin/stats", headers=self.admin_header)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        with SessionLocal() as db:
            self.assertEqual(data["total_users"], db.query(User).count())
            month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            self.assertEqual(data["new_this_month"], db.query(User).filter(User.created_at >= month_start).count())
        self.assertEqual(len(data["months"]), 6)
        self.assertEqual(data["months"][-1]["count"], data["new_this_month"])
        self.assertEqual(data["months"][-1]["month"], datetime.utcnow().strftime("%Y-%m"))

    def test_disabled_account_is_rejected(self):
        payload = {"username": "disabled1", "email": "disabled@example.com", "password": "MemberPass123"}
        token = self.client.post("/api/v1/auth/register", json=payload).json()["token"]
        with SessionLocal() as db:
            row = db.query(User).filter(User.username == "disabled1").one(); row.is_active = False; db.commit()
        response = self.client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 403)

    def test_store_benefit_checkout_and_idempotency(self):
        payload = {"username": "billing1", "email": "billing@example.com", "password": "MemberPass123"}
        member_token = self.client.post("/api/v1/auth/register", json=payload).json()["token"]
        member_header = {"Authorization": f"Bearer {member_token}"}
        user_id = self.client.get("/api/v1/users/me", headers=member_header).json()["id"]
        store = self.client.post("/api/v1/stores", headers=self.admin_header, json={"name": "Test Store"}).json()
        store_id = store["id"]
        self.assertEqual(self.client.post(f"/api/v1/stores/{store_id}/members", headers=self.admin_header,
                                          json={"user_id": user_id, "store_role": "member"}).status_code, 200)
        self.client.post(f"/api/v1/stores/{store_id}/benefits/{user_id}", headers=self.admin_header,
                         json={"paid_delta": 50, "bonus_delta": 10, "times_delta": 1, "remark": "test"})
        started = datetime.utcnow() - timedelta(hours=2)
        self.assertEqual(self.client.post("/api/v1/me/consumption/start", headers=member_header,
                                          json={"store_id": store_id, "started_at": started.isoformat()}).status_code, 200)
        body = {"payment_method": "times_card", "idempotency_key": "checkout-test-0001"}
        first = self.client.post("/api/v1/me/consumption/checkout", headers=member_header, json=body)
        second = self.client.post("/api/v1/me/consumption/checkout", headers=member_header, json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        members = self.client.get(f"/api/v1/stores/{store_id}/members", headers=self.admin_header).json()
        target = next(row for row in members if row["user_id"] == user_id)
        self.assertEqual(target["times_count"], 0)


if __name__ == "__main__": unittest.main()
