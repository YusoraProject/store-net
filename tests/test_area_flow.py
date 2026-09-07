import json
import base64
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.database import Base, get_db
from backend.auth import current_user
from backend.models import Role, User, Store, StoreMember, StorePricing, MemberBenefit, Consumption, BenefitLedger
from backend.access_models import AccessBase, BillingArea, LockCredential, MemberOccupancy, PasscodeRequest, ConsumptionArea, ConsumptionSegment
from backend.ttlock_client import SecretBox, Passcode, OutcomeUnknown, LockError
from backend.area_billing import begin


class AreaFlowTests(unittest.TestCase):
    def setUp(self):
        from backend.main import _limits
        _limits.clear()
        self.tmp=tempfile.TemporaryDirectory()
        self.engine=create_engine("sqlite:///"+(Path(self.tmp.name)/"area.db").as_posix(),
                                  connect_args={"check_same_thread":False,"timeout":15})
        self.sessions=sessionmaker(self.engine,autoflush=False)
        Base.metadata.create_all(self.engine)
        AccessBase.metadata.create_all(self.engine)
        self.box=SecretBox(base64.b64encode(b"x"*32).decode())
        def db_dep():
            with self.sessions() as db: yield db
        def actor(x_user:int=Header(2),db=Depends(get_db)):
            return db.get(User,x_user)
        app.dependency_overrides[get_db]=db_dep
        app.dependency_overrides[current_user]=actor
        self.client=TestClient(app,base_url="https://testserver")
        with self.sessions() as db:
            db.add_all([Role(id=1,name="admin"),Role(id=2,name="member")])
            for uid in (1,2,3):
                db.add(User(id=uid,username="user"+str(uid),email=f"u{uid}@example.com",
                    password_hash="unused",name="用户",role_id=1 if uid==1 else 2))
            for sid in (1,2):
                db.add(Store(id=sid,name=f"门店{sid}",created_by=1))
                db.add(StorePricing(store_id=sid))
                db.add(LockCredential(store_id=sid,region="cn",encrypted_bundle="mock",version=1,updated_by=1))
                for uid in (1,2,3):
                    db.add(StoreMember(store_id=sid,user_id=uid,store_role="manager" if uid==1 else "member"))
                    db.add(MemberBenefit(store_id=sid,user_id=uid,paid_cents=100000,times_count=2))
            for aid,sid,rate in [(1,1,1000),(2,1,2000),(3,2,3000)]:
                prices={f"{d}_{p}_{r}_cents":rate if r=="hourly" else 0
                    for d in ("workday","weekend","holiday") for p in ("day","night") for r in ("hourly","cap")}
                db.add(BillingArea(id=aid,store_id=sid,name=f"区域{aid}",enabled=True,
                                  pricing_json=json.dumps(prices),auto_issue=False))
            db.commit()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.tmp.cleanup()

    def start(self,area=1,key="start-key-001"):
        return self.client.post("/api/v1/me/consumption/start",
                                json={"store_id":1,"area_id":area,"idempotency_key":key})

    def switch_area(self, area=2, key="switch-key-001", when=None):
        with patch("backend.area_switching.datetime", wraps=datetime) as clock:
            clock.utcnow.return_value = when or datetime.utcnow()
            return self.client.post("/api/v1/me/consumption/switch",
                json={"area_id": area, "idempotency_key": key})

    def test_switch_accumulates_without_deduction_and_checkout_once(self):
        cid = self.start().json()["id"]
        start = datetime(2026, 9, 7, 8)
        with self.sessions() as db:
            db.get(Consumption, cid).started_at = start
            db.commit()
        switched = self.switch_area(when=start + timedelta(hours=1))
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual(switched.json()["id"], cid)
        self.assertEqual(switched.json()["area_id"], 2)
        self.assertEqual(len(switched.json()["segments"]), 2)
        self.assertEqual(self.switch_area().status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.query(Consumption).count(), 1)
            self.assertEqual(db.query(ConsumptionSegment).count(), 2)
            self.assertEqual(db.query(BenefitLedger).count(), 0)
            self.assertEqual(db.get(Consumption, cid).status, "open")
        result = self.client.post(f"/api/v1/stores/1/consumptions/{cid}/checkout", headers={"x-user":"1"},
            json={"idempotency_key":"accumulated-checkout", "payment_method":"balance",
                  "ended_at":(start + timedelta(hours=2)).isoformat()})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["amount_due"], 30)
        with self.sessions() as db:
            self.assertEqual(db.query(BenefitLedger).count(), 1)
            self.assertIsNone(db.get(MemberOccupancy, 2))
            self.assertEqual(db.query(ConsumptionSegment).filter(ConsumptionSegment.ended_at.is_(None)).count(), 0)

    def test_return_to_same_area_keeps_cap(self):
        with self.sessions() as db:
            area = db.get(BillingArea, 1)
            values = json.loads(area.pricing_json)
            values["workday_day_cap_cents"] = 1500
            area.pricing_json = json.dumps(values)
            db.commit()
        cid = self.start().json()["id"]
        start = datetime(2026, 9, 7, 8)
        with self.sessions() as db:
            db.get(Consumption, cid).started_at = start
            db.commit()
        self.assertEqual(self.switch_area(when=start+timedelta(hours=1)).status_code, 200)
        self.assertEqual(self.switch_area(1, "return-area-key", start+timedelta(hours=2)).status_code, 200)
        result = self.client.post(f"/api/v1/stores/1/consumptions/{cid}/checkout", headers={"x-user":"1"},
            json={"idempotency_key":"cap-checkout", "payment_method":"cash",
                  "ended_at":(start+timedelta(hours=3)).isoformat()})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["amount_due"], 35)

    def test_switch_rejects_other_store_and_other_users(self):
        cid = self.start().json()["id"]
        self.assertEqual(self.switch_area(3).status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/stores/1/consumptions/{cid}/switch", headers={"x-user":"3"},
            json={"area_id":2,"idempotency_key":"unauthorized-switch"}).status_code,403)
        self.assertEqual(self.client.post("/api/v1/me/consumption/switch",headers={"x-user":"3"},
            json={"area_id":2,"idempotency_key":"another-user-switch"}).status_code,404)

    def test_switch_unknown_keeps_original_until_reconciliation(self):
        cid = self.start().json()["id"]
        with self.sessions() as db:
            area=db.get(BillingArea,2); area.auto_issue=True; area.lock_id="456"; area.password_version=4
            db.commit()
        adapter=Mock(); adapter.one_time.side_effect=OutcomeUnknown("待确认")
        adapter.find_created.return_value=Passcode("remote","87654321",int(time.time()*1000),int(time.time()*1000)+3600000)
        with patch("backend.area_switching.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_billing.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_switching.secret_box",return_value=self.box), patch(
                "backend.area_billing.secret_box",return_value=self.box), patch("backend.main.secret_box",return_value=self.box):
            first=self.switch_area()
            self.assertEqual(first.status_code,202,first.text)
            self.assertEqual(self.switch_area().status_code,202)
            self.assertEqual(adapter.one_time.call_count,1)
            self.assertEqual(self.client.get("/api/v1/me/consumption/current").json()["area_id"],1)
            self.assertEqual(self.client.post("/api/v1/me/consumption/checkout",
                json={"idempotency_key":"pending-checkout"}).status_code,409)
            self.assertEqual(self.switch_area(2,"another-switch-key").status_code,409)
            resumed=self.client.post("/api/v1/me/consumption/access/resume")
            self.assertEqual(resumed.status_code,200,resumed.text)
            self.assertEqual(resumed.json()["status"],"ready")
            current=self.client.get("/api/v1/me/consumption/current").json()
            self.assertEqual(current["id"],cid)
            self.assertEqual(current["area_id"],2)
            self.assertEqual(len(current["segments"]),2)
            self.assertEqual(self.client.post("/api/v1/me/consumption/password").json()["password"],"87654321")
        with self.sessions() as db:
            self.assertEqual(db.query(Consumption).count(),1)
            self.assertEqual(db.query(BenefitLedger).count(),0)

    def test_cancel_unknown_switch_keeps_open_consumption(self):
        cid=self.start().json()["id"]
        with self.sessions() as db:
            area=db.get(BillingArea,2); area.auto_issue=True; area.lock_id="456"; area.password_version=4
            db.commit()
        adapter=Mock(); adapter.one_time.side_effect=OutcomeUnknown("待确认")
        with patch("backend.area_switching.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_switching.secret_box",return_value=self.box):
            request_id=self.switch_area().json()["request_id"]
        response=self.client.post(f"/api/v1/access/stores/1/records/{request_id}/cancel", headers={"x-user":"1"},
            json={"acknowledged":True,"reason":"现场核对后取消换区"})
        self.assertEqual(response.status_code,200,response.text)
        with self.sessions() as db:
            occupied=db.get(MemberOccupancy,2)
            self.assertEqual(occupied.consumption_id,cid)
            self.assertEqual(occupied.area_id,1)
            self.assertIsNone(occupied.pending_request_id)
            self.assertEqual(db.get(Consumption,cid).status,"open")

    def test_concurrent_same_switch_creates_one_segment(self):
        cid = self.start().json()["id"]
        def run(_):
            return self.client.post("/api/v1/me/consumption/switch",
                json={"area_id":2,"idempotency_key":"concurrent-switch"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(run,[0,1])),[200,200])
        with self.sessions() as db:
            self.assertEqual(db.query(ConsumptionSegment).count(),2)
            self.assertEqual(db.query(Consumption).count(),1)
            self.assertEqual(db.get(MemberOccupancy,2).consumption_id,cid)

    def test_multiple_automatic_codes_share_consumption_and_failure_keeps_current_code(self):
        with self.sessions() as db:
            for aid in (1,2):
                area=db.get(BillingArea,aid);area.auto_issue=True;area.lock_id=str(aid);area.password_version=4
            db.commit()
        adapter=Mock()
        now=int(time.time()*1000)
        adapter.one_time.side_effect=[Passcode("r1","11111111",now,now+3600000),
            Passcode("r2","22222222",now,now+3600000),LockError("失败")]
        with patch("backend.area_billing.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_switching.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_billing.secret_box",return_value=self.box), patch(
                "backend.area_switching.secret_box",return_value=self.box), patch("backend.main.secret_box",return_value=self.box):
            start=self.start()
            self.assertEqual(start.status_code,200,start.text)
            cid=start.json()["id"]
            switched=self.switch_area()
            self.assertEqual(switched.status_code,200,switched.text)
            self.assertEqual(switched.json()["id"],cid)
            failed=self.switch_area(1,"failed-switch-key")
            self.assertEqual(failed.status_code,202,failed.text)
            self.assertEqual(failed.json()["status"],"failed")
            self.assertEqual(self.client.get("/api/v1/me/consumption/current").json()["area_id"],2)
            self.assertEqual(self.client.post("/api/v1/me/consumption/password").json()["password"],"22222222")
        with self.sessions() as db:
            self.assertEqual(db.query(Consumption).count(),1)
            self.assertEqual(db.query(PasscodeRequest).filter(PasscodeRequest.consumption_id==cid).count(),2)
            self.assertIsNone(db.get(MemberOccupancy,2).pending_request_id)

    def test_multiple_areas_require_selection_and_snapshot_survives_price_change(self):
        self.assertEqual(self.client.post("/api/v1/me/consumption/start",json={"store_id":1}).status_code,422)
        created=self.start()
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        started=datetime(2026,9,7,8)
        with self.sessions() as db:
            row=db.get(Consumption,cid);row.started_at=started
            area=db.get(BillingArea,1)
            values=json.loads(area.pricing_json);values["workday_day_hourly_cents"]=9999
            area.pricing_json=json.dumps(values)
            db.commit()
        result=self.client.post(f"/api/v1/stores/1/consumptions/{cid}/checkout",
            headers={"x-user":"1"},json={"idempotency_key":"checkout-key-01","payment_method":"cash",
                                        "ended_at":(started+timedelta(hours=1)).isoformat()})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["amount_due"],10)
        with self.sessions() as db:
            self.assertIsNone(db.get(MemberOccupancy,2))
        self.assertEqual(self.start(2,"start-key-002").status_code,200)

    def test_repeated_start_and_cross_area_rejection(self):
        first=self.start()
        self.assertEqual(self.start().json()["id"],first.json()["id"])
        self.assertEqual(self.start(2,"another-key").status_code,409)

    def test_concurrent_checkout_deducts_once(self):
        created=self.start().json()
        def settle(i):
            return self.client.post('/api/v1/me/consumption/checkout', json={
                'payment_method':'times_card','idempotency_key':'checkout-concurrent'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(settle,[0,1]))
        self.assertEqual(result,[200,200])
        with self.sessions() as db:
            b=db.scalar(select(MemberBenefit).where(MemberBenefit.store_id==1,MemberBenefit.user_id==2))
            self.assertEqual(b.times_count,1)
            self.assertEqual(db.query(BenefitLedger).count(),1)
            self.assertIsNone(db.get(MemberOccupancy,2))

    def test_manager_start_uses_selected_area_and_member_cannot_backdate(self):
        requested=(datetime.utcnow()-timedelta(days=10)).isoformat()
        result=self.client.post('/api/v1/me/consumption/start',json={
            'store_id':1,'area_id':1,'started_at':requested,'idempotency_key':'no-backdating'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertGreater(datetime.fromisoformat(result.json()['started_at']),datetime.utcnow()-timedelta(minutes=1))
        manager=self.client.post('/api/v1/stores/1/consumptions/start',headers={'x-user':'1'},json={
            'store_id':1,'user_id':3,'area_id':2,'idempotency_key':'manager-area'})
        self.assertEqual(manager.status_code,200,manager.text)
        self.assertEqual(manager.json()['area_id'],2)

    def test_automatic_requires_https_and_does_not_reserve(self):
        with self.sessions() as db:
            area=db.get(BillingArea,1);area.auto_issue=True;area.lock_id='123';area.password_version=4
            db.commit()
        client=TestClient(app,base_url='http://testserver')
        try:
            response=client.post('/api/v1/me/consumption/start',json={
                'store_id':1,'area_id':1,'idempotency_key':'insecure-start'})
        finally:
            client.close()
        self.assertEqual(response.status_code,403)
        with self.sessions() as db:
            self.assertEqual(db.query(MemberOccupancy).count(),0)

    def test_concurrent_cross_store_only_one_consumption(self):
        def run(i):
            with self.sessions() as db:
                try:
                    begin(db,store_id=1 if i==0 else 2,user_id=2,operator_id=2,
                          area_id=1 if i==0 else 3,key="parallel-"+str(i),started_at=None,secure=True)
                    return True
                except Exception:
                    db.rollback()
                    return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(run,[0,1]))
        self.assertEqual(sum(result),1)
        with self.sessions() as db:
            self.assertEqual(db.query(Consumption).count(),1)

    def test_insufficient_balance_keeps_occupancy_and_assets(self):
        created=self.start().json()
        with self.sessions() as db:
            b=db.scalar(select(MemberBenefit).where(MemberBenefit.store_id==1,MemberBenefit.user_id==2))
            b.paid_cents=0;b.times_count=0
            db.get(Consumption,created["id"]).started_at=datetime.utcnow()-timedelta(hours=1)
            db.commit()
        result=self.client.post("/api/v1/me/consumption/checkout",
            json={"payment_method":"auto","idempotency_key":"no-money-key"})
        self.assertEqual(result.status_code,402)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(MemberOccupancy,2))
            self.assertEqual(db.get(Consumption,created["id"]).status,"open")
            self.assertEqual(db.query(BenefitLedger).count(),0)

    def test_unknown_issue_no_billing_then_reconcile_once(self):
        with self.sessions() as db:
            area=db.get(BillingArea,1);area.auto_issue=True;area.lock_id="123";area.password_version=4
            db.commit()
        adapter=Mock()
        adapter.one_time.side_effect=OutcomeUnknown("待确认")
        adapter.find_created.return_value=Passcode("remote","12345678",int(time.time()*1000),int(time.time()*1000)+3600000)
        with patch("backend.area_billing.valid_client",return_value=(adapter,"token",1)), patch(
                "backend.area_billing.secret_box",return_value=self.box), patch("backend.main.secret_box",return_value=self.box):
            first=self.start()
            self.assertEqual(first.status_code,202,first.text)
            with self.sessions() as db:self.assertEqual(db.query(Consumption).count(),0)
            self.assertEqual(self.start().status_code,202)
            result=self.client.post("/api/v1/me/consumption/access/resume")
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()["status"],"ready")
            self.assertEqual(adapter.one_time.call_count,1)
            password=self.client.post("/api/v1/me/consumption/password")
            self.assertEqual(password.json()["password"],"12345678")
            self.assertEqual(self.client.post("/api/v1/me/consumption/password",headers={"x-user":"3"}).status_code,404)
            with self.sessions() as db:
                self.assertEqual(db.query(Consumption).count(),1)
                row=db.scalar(select(Consumption))
                self.assertLess((datetime.utcnow()-row.started_at).total_seconds(),10)

    def test_manager_can_cancel_unknown_without_billing_or_revoking_password(self):
        with self.sessions() as db:
            area=db.get(BillingArea,1);area.auto_issue=True;area.lock_id='123';area.password_version=4
            db.commit()
        adapter=Mock();adapter.one_time.side_effect=OutcomeUnknown('待确认')
        with patch('backend.area_billing.valid_client',return_value=(adapter,'token',1)), patch(
                'backend.area_billing.secret_box',return_value=self.box):
            pending=self.start().json()['request_id']
        path='/api/v1/access/stores/1/records/'+pending+'/cancel'
        payload={'acknowledged':True,'reason':'现场确认后取消'}
        self.assertEqual(self.client.post(path,json=payload).status_code,403)
        result=self.client.post(path,json=payload,headers={'x-user':'1'})
        self.assertEqual(result.status_code,200,result.text)
        with self.sessions() as db:
            self.assertEqual(db.query(Consumption).count(),0)
            self.assertIsNone(db.get(MemberOccupancy,2))
            self.assertEqual(db.get(PasscodeRequest,pending).status,'cancelled')
