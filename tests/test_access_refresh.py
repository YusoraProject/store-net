"""授权续期只使用模拟请求，覆盖多进程互斥所依赖的数据库状态。"""
import base64
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.access_models import AccessBase, LockCredential, CredentialRefresh, PasscodeRequest, AccessAudit
from backend.access_credentials import valid_client, save_authorization
from backend.access_refresh import refresh_store, refresh_due
from backend.ttlock_client import SecretBox, Tokens, LockError, ReauthorizationRequired


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + (Path(self.tmp.name) / "refresh.db").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 5})
        self.sessions = sessionmaker(self.engine)
        AccessBase.metadata.create_all(self.engine)
        self.box = SecretBox(base64.b64encode(b"r" * 32).decode())
        self.adapter = Mock()
        self.adapter.refresh.return_value = Tokens("new-access", "new-refresh", int(time.time()) + 3600)
        self.patches = [patch("backend.access_refresh.secret_box", return_value=self.box),
            patch("backend.access_credentials.secret_box", return_value=self.box),
            patch("backend.access_refresh.client", return_value=self.adapter),
            patch("backend.access_credentials.client", return_value=self.adapter)]
        for item in self.patches:
            item.start()
        self.bundle = {"client_id": "app", "client_secret": "secret-never-log",
            "access_token": "old-access", "refresh_token": "old-refresh", "expires_at": int(time.time()) + 90}
        with self.sessions() as db:
            db.add(LockCredential(store_id=1, region="cn", version=3, updated_by=99,
                encrypted_bundle=self.box.encrypt(json.dumps(self.bundle), "store:1:credential")))
            db.commit()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_refresh_replaces_both_tokens_without_changing_account_version(self):
        with self.sessions() as db:
            db.add(PasscodeRequest(id="pending",store_id=1,area_id=1,operator_id=2,recipient_id=2,
                idempotency_key="pending-key",remote_name="pending-name",source="automatic",status="review",
                lock_id="1",credential_version=3,password_version=4,start_ms="0",end_ms="1"))
            db.commit()
        self.assertEqual(refresh_store(self.sessions, 1), "ready")
        self.adapter.refresh.assert_called_once_with("secret-never-log", "old-refresh")
        with self.sessions() as db:
            row = db.get(LockCredential, 1)
            bundle = json.loads(self.box.decrypt(row.encrypted_bundle, "store:1:credential"))
            self.assertEqual(bundle["access_token"], "new-access")
            self.assertEqual(bundle["refresh_token"], "new-refresh")
            self.assertNotIn("new-access", row.encrypted_bundle)
            self.assertEqual(row.version, 3)
            self.assertEqual(db.get(PasscodeRequest, "pending").credential_version, 3)
            self.assertEqual(valid_client(db, 1)[1], "new-access")
            self.assertEqual(db.query(AccessAudit).count(), 1)
        self.assertEqual(refresh_store(self.sessions, 1), "ready")
        self.assertEqual(self.adapter.refresh.call_count, 1)

    def test_concurrent_requests_refresh_once_and_network_does_not_hold_write_lock(self):
        started, release = threading.Event(), threading.Event()
        def remote(*args):
            started.set()
            self.assertTrue(release.wait(5))
            return Tokens("new-access", "new-refresh", int(time.time()) + 3600)
        self.adapter.refresh.side_effect = remote
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(refresh_store, self.sessions, 1)
            try:
                self.assertTrue(started.wait(5))
                self.assertEqual(refresh_store(self.sessions, 1), "refreshing")
                # 另一连接能写库，说明外部请求期间没有保留写事务。
                with self.sessions() as db:
                    db.add(AccessAudit(store_id=2, actor_id=99, action="unrelated_write"))
                    db.commit()
                    with self.assertRaises(HTTPException):
                        valid_client(db, 1)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5), "ready")
        self.assertEqual(self.adapter.refresh.call_count, 1)

    def test_interrupted_refresh_never_replays_old_refresh_token(self):
        with self.sessions() as db:
            db.add(CredentialRefresh(store_id=1, credential_version=3, status="refreshing",
                lease_token="old-process", lease_until=datetime.utcnow() - timedelta(seconds=1)))
            db.commit()
        self.assertEqual(refresh_store(self.sessions, 1), "unknown")
        self.assertEqual(refresh_store(self.sessions, 1), "unknown")
        self.adapter.refresh.assert_not_called()
        with self.sessions() as db:
            with self.assertRaises(HTTPException):
                valid_client(db, 1)

    def test_failure_is_sanitized_and_not_retried(self):
        self.adapter.refresh.side_effect = LockError("secret-never-log old-refresh upstream-body")
        self.assertEqual(refresh_store(self.sessions, 1), "unknown")
        refresh_due(self.sessions)
        self.assertEqual(self.adapter.refresh.call_count, 1)
        with self.sessions() as db:
            state = db.get(CredentialRefresh, 1)
            self.assertNotIn("secret-never-log", state.safe_error)
            self.assertNotIn("old-refresh", state.safe_error)

    def test_rejected_refresh_can_be_reauthorized(self):
        self.adapter.refresh.side_effect = ReauthorizationRequired("不要回显的上游正文")
        self.assertEqual(refresh_store(self.sessions, 1), "reauthorize")
        self.adapter.authorize.return_value = Tokens("replacement-access", "replacement-refresh", int(time.time()) + 3600)
        self.adapter.locks.return_value = []
        with self.sessions() as db:
            save_authorization(db,1,99,"cn","app","new-secret","test-user","test-password")
            self.assertEqual(db.get(CredentialRefresh, 1).status, "ready")
            self.assertEqual(db.get(LockCredential, 1).version, 4)
            self.assertEqual(valid_client(db, 1)[1], "replacement-access")

    def test_active_refresh_blocks_reauthorization_before_external_request(self):
        with self.sessions() as db:
            db.add(CredentialRefresh(store_id=1, credential_version=3, status="refreshing",
                lease_token="working", lease_until=datetime.utcnow() + timedelta(seconds=30)))
            db.commit()
            with self.assertRaises(HTTPException):
                save_authorization(db,1,99,"cn","app","secret","user","password")
        self.adapter.authorize.assert_not_called()

    def test_unresolved_passcode_blocks_reauthorization_before_remote_call(self):
        with self.sessions() as db:
            db.add(PasscodeRequest(id="unresolved",store_id=1,area_id=1,operator_id=2,recipient_id=2,
                idempotency_key="unresolved-key",remote_name="unresolved-name",source="automatic",status="review",
                lock_id="1",credential_version=3,password_version=4,start_ms="0",end_ms="1"))
            db.commit()
            with self.assertRaises(HTTPException):
                save_authorization(db,1,99,"cn","app","secret","user","password")
        self.adapter.authorize.assert_not_called()

    def test_late_result_cannot_overwrite_new_authorization(self):
        def remote(*args):
            with self.sessions() as db:
                row = db.get(LockCredential,1)
                row.version = 4
                fresh = {**self.bundle, "access_token":"different-account", "expires_at":int(time.time())+3600}
                row.encrypted_bundle = self.box.encrypt(json.dumps(fresh), "store:1:credential")
                state = db.get(CredentialRefresh,1)
                state.credential_version, state.status, state.lease_token = 4,"ready",None
                db.commit()
            return Tokens("stale-access", "stale-refresh", int(time.time())+3600)
        self.adapter.refresh.side_effect = remote
        self.assertEqual(refresh_store(self.sessions,1),"superseded")
        with self.sessions() as db:
            self.assertEqual(valid_client(db,1)[1],"different-account")
