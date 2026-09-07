import base64
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from backend.access_models import AccessBase, MemberOccupancy, PasscodeRequest, LockCredential
from backend.access_journal import reserve, process, claim, release_consumption
from backend.ttlock_client import SecretBox, Passcode, OutcomeUnknown, LockError


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + (Path(self.tmp.name) / "journal.db").as_posix(),
                                    connect_args={"check_same_thread": False, "timeout": 10})
        AccessBase.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        with self.sessions() as db:
            for store_id in range(1, 5):
                db.add(LockCredential(store_id=store_id, region="cn", encrypted_bundle="mock",
                                      version=1, updated_by=1))
            db.commit()
        self.box = SecretBox(base64.b64encode(b"x" * 32).decode())
        self.args = dict(store_id=1, area_id=1, operator_id=1, recipient_id=2,
            idempotency_key="one", lock_id="100", credential_version=1,
            password_version=4, start_ms=0, source="automatic")

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_duplicate_request_reuses_reservation(self):
        first = reserve(self.sessions, **self.args)
        self.assertEqual(first, reserve(self.sessions, **self.args))
        with self.sessions() as db:
            self.assertEqual(db.query(MemberOccupancy).count(), 1)
            self.assertEqual(db.query(PasscodeRequest).count(), 1)

    def test_concurrent_cross_store_start_is_exclusive(self):
        def run(i):
            try:
                return reserve(self.sessions, **dict(self.args, store_id=i+1, area_id=i+1,
                                                     idempotency_key=str(i)))
            except LockError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_worker_lease_expiry_only_allows_reconciliation(self):
        key = reserve(self.sessions, **self.args)
        now = datetime.utcnow()
        self.assertEqual(claim(self.sessions, key, now=now)[1], "issue")
        self.assertIsNone(claim(self.sessions, key, now=now))
        self.assertEqual(claim(self.sessions, key, now=now + timedelta(seconds=61))[1], "reconcile")

    def test_remote_success_local_failure_recovers_without_reissue(self):
        key = reserve(self.sessions, **self.args)
        class Client:
            creates = 0
            def one_time(self, *args, **kwargs):
                self.creates += 1
                return Passcode("remote", "123456", 0, 21600000)
            def find_created(self, *args):
                return Passcode("remote", "123456", 0, 21600000)
        client = Client()
        def broken(db, request):
            raise RuntimeError("local database failure")
        process(self.sessions, key, client=client, token="secret", box=self.box, finalize=broken)
        with self.sessions() as db:
            self.assertEqual(db.get(PasscodeRequest, key).status, "review")
            self.assertIsNotNone(db.get(MemberOccupancy, 2))
        process(self.sessions, key, client=client, token="secret", box=self.box,
                finalize=lambda db, request: 42)
        with self.sessions() as db:
            row = db.get(PasscodeRequest, key)
            self.assertEqual(row.status, "ready")
            self.assertNotIn("123456", row.encrypted_password)
            self.assertEqual(db.get(MemberOccupancy, 2).consumption_id, 42)
            release_consumption(db, 2, 42)
            db.commit()
        self.assertEqual(client.creates, 1)

    def test_unknown_holds_occupancy_without_billing(self):
        key = reserve(self.sessions, **self.args)
        class Client:
            def one_time(self, *args, **kwargs):
                raise OutcomeUnknown("unknown")
        process(self.sessions, key, client=Client(), token="secret", box=self.box,
                finalize=lambda *args: self.fail("must not bill"))
        with self.sessions() as db:
            self.assertEqual(db.get(PasscodeRequest, key).status, "review")
            self.assertIsNone(db.get(MemberOccupancy, 2).consumption_id)

    def test_definitive_failure_releases_occupancy(self):
        key = reserve(self.sessions, **self.args)
        class Client:
            def one_time(self, *args, **kwargs):
                raise LockError("rejected")
        process(self.sessions, key, client=Client(), token="secret", box=self.box)
        with self.sessions() as db:
            self.assertEqual(db.get(PasscodeRequest, key).status, "failed")
            self.assertIsNone(db.get(MemberOccupancy, 2))

    def test_different_arguments_cannot_reuse_key(self):
        reserve(self.sessions, **self.args)
        with self.assertRaises(LockError):
            reserve(self.sessions, **dict(self.args, area_id=2))
