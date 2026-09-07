import tempfile
import base64
import time
from unittest.mock import patch, Mock
import unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.access_models import AccessBase, PasscodeRequest
from backend.access_api import make_router
from backend.ttlock_client import Tokens, Passcode


class ManagementTests(unittest.TestCase):
    def setUp(self):
        from backend.access_api import _limits
        _limits.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + (Path(self.tmp.name)/"api.db").as_posix(),
                                    connect_args={"check_same_thread":False})
        AccessBase.metadata.create_all(self.engine)
        self.sessions=sessionmaker(self.engine)
        self.user=SimpleNamespace(id=1)
        def get_db():
            with self.sessions() as db:
                yield db
        def user():
            return self.user
        def scope(db,user,store_id):
            if user.id != 99 and store_id != 1:
                raise HTTPException(403,"无权管理该门店")
        app=FastAPI()
        app.include_router(make_router(user_dependency=user,db_dependency=get_db,scope=scope,cents=True))
        self.client=TestClient(app)
        self.app=app
        self.payload={"name":"区域一","pricing":{f"{d}_{p}_{r}":8 for d in
            ("workday","weekend","holiday") for p in ("day","night") for r in ("hourly","cap")}}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_store_scope_and_superadmin(self):
        self.assertEqual(self.client.get("/access/stores/2/status").status_code,403)
        self.user=SimpleNamespace(id=99)
        self.assertEqual(self.client.get("/access/stores/2/status").status_code,200)

    def test_area_edit_and_cross_store_id_rejected(self):
        result=self.client.post("/access/stores/1/areas",json=self.payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["pricing"]["workday_day_hourly"],8)
        self.user=SimpleNamespace(id=99)
        self.assertEqual(self.client.put("/access/stores/2/areas/"+str(result.json()["id"]),
                                        json=self.payload).status_code,404)

    def test_duplicate_and_invalid_prices(self):
        self.client.post("/access/stores/1/areas",json=self.payload)
        self.assertEqual(self.client.post("/access/stores/1/areas",json=self.payload).status_code,409)
        self.payload["pricing"]["workday_day_hourly"]=-1
        self.assertEqual(self.client.post("/access/stores/1/areas",json=self.payload).status_code,422)

    def test_automatic_issuing_is_fail_closed(self):
        self.payload["auto_issue"]=True
        self.assertEqual(self.client.post("/access/stores/1/areas",json=self.payload).status_code,403)

    def test_credentials_reject_plain_http(self):
        response=self.client.post("/access/stores/1/authorization",json={
            "region":"cn","client_id":"app","client_secret":"secret","username":"user","password":"secret"})
        self.assertEqual(response.status_code,403)
        self.assertNotIn("secret",response.text)

    def test_refresh_requires_https_scope_and_does_not_cache_errors(self):
        path="/access/stores/1/authorization/refresh"
        result=self.client.post(path)
        self.assertEqual(result.status_code,403)
        self.assertEqual(result.headers["cache-control"],"no-store")
        with TestClient(self.app,base_url="https://testserver") as client, patch(
                "backend.access_refresh.refresh_store",return_value="ready") as refresh:
            self.assertEqual(client.post("/access/stores/2/authorization/refresh").status_code,403)
            refresh.assert_not_called()
            allowed=client.post(path)
            self.assertEqual(allowed.status_code,200,allowed.text)
            self.assertEqual(allowed.json()["status"],"ready")
            self.assertEqual(allowed.headers["cache-control"],"no-store")

    def test_refresh_status_never_returns_credentials(self):
        from backend.access_models import LockCredential, CredentialRefresh
        with self.sessions() as db:
            db.add(LockCredential(store_id=1,region="cn",version=1,updated_by=1,encrypted_bundle="SECRET-CIPHER"))
            db.add(CredentialRefresh(store_id=1,credential_version=1,status="refreshing",lease_token="SECRET-LEASE"))
            db.commit()
        with patch("backend.access_api.credential",return_value=(None,{
                "expires_at":int(time.time())+3600,"access_token":"SECRET-ACCESS","refresh_token":"SECRET-REFRESH"})):
            result=self.client.get("/access/stores/1/status")
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["refresh_status"],"refreshing")
        self.assertNotIn("SECRET",result.text)
        self.assertEqual(result.headers["cache-control"],"no-store")

    def test_manual_issue_end_to_end_mock_and_no_duplicate(self):
        adapter=Mock()
        adapter.authorize.return_value=Tokens("token","refresh",int(time.time())+3600)
        adapter.locks.return_value=[{"lock_id":123,"name":"测试门锁","password_version":4}]
        adapter.one_time.return_value=Passcode("remote","87654321",int(time.time()*1000),int(time.time()*1000)+3600000)
        with patch.dict("os.environ",{"TTLOCK_MASTER_KEY":base64.b64encode(b"x"*32).decode()}), patch(
                "backend.access_credentials.client",return_value=adapter), TestClient(self.app,base_url="https://testserver") as client:
            result=client.post("/access/stores/1/authorization",json={
                "region":"cn","client_id":"app","client_secret":"secret","username":"user","password":"secret"})
            self.assertEqual(result.status_code,200,result.text)
            area=client.post("/access/stores/1/areas",json=self.payload).json()["id"]
            self.assertEqual(client.put(f"/access/stores/1/areas/{area}/lock",json={"lock_id":"123"}).status_code,200)
            first=client.post(f"/access/stores/1/areas/{area}/issue",json={"idempotency_key":"request-one"})
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(first.json()["status"],"ready")
            second=client.post(f"/access/stores/1/areas/{area}/issue",json={"idempotency_key":"request-one"})
            self.assertEqual(second.json()["id"],first.json()["id"])
            self.assertEqual(adapter.one_time.call_count,1)
            self.assertNotIn("87654321",client.get("/access/stores/1/records").text)
            revealed=client.post("/access/stores/1/records/"+first.json()["id"]+"/reveal")
            self.assertEqual(revealed.json()["password"],"87654321")
            self.assertEqual(revealed.headers["cache-control"],"no-store")

    def test_records_never_contain_password_or_remote_secrets(self):
        with self.sessions() as db:
            db.add(PasscodeRequest(id="test",store_id=1,area_id=1,operator_id=1,
                recipient_id=2,idempotency_key="key",remote_name="SECRET-REMOTE-NAME",source="manual",
                lock_id="1",credential_version=1,password_version=4,start_ms="0",end_ms="0",
                encrypted_password="SECRET-CIPHER"))
            db.commit()
        response=self.client.get("/access/stores/1/records")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertNotIn("SECRET",response.text)
        self.assertEqual(response.json()["total"],1)
        self.assertEqual(self.client.get("/access/stores/1/records?page_size=1000").status_code,422)
