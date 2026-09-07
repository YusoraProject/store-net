"""首次建库和重复启动的检查，只在临时目录运行。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text, UniqueConstraint
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from backend.initialize import current_metadata, initialize_database, prepare_schema
from backend.models import User, Role, Store
from backend.database import database_url
from backend.config import ROOT


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "new" / "store.db"
        self.engine = create_engine("sqlite:///" + self.path.as_posix(), poolclass=NullPool)
        self.sessions = sessionmaker(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_empty_database_creates_all_tables_and_initial_admin_only(self):
        initialize_database(self.engine, self.sessions)
        self.assertTrue(self.path.exists())
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(current_metadata().tables))
        with self.sessions() as db:
            self.assertEqual(db.query(User).count(), 1)
            self.assertEqual(db.query(Role).count(), 2)
            self.assertEqual(db.query(Store).count(), 0)

    def test_repeated_initialization_keeps_password_and_store_data(self):
        initialize_database(self.engine, self.sessions)
        with self.sessions() as db:
            user = db.scalar(select(User))
            user.password_hash = "password-changed-by-user"
            db.add(Store(name="自己的门店", created_by=user.id))
            db.commit()
        initialize_database(self.engine, self.sessions)
        with self.sessions() as db:
            self.assertEqual(db.query(User).count(), 1)
            self.assertEqual(db.scalar(select(User)).password_hash, "password-changed-by-user")
            self.assertEqual(db.scalar(select(Store)).name, "自己的门店")

    def test_old_or_partial_database_is_rejected_without_writes(self):
        self.path.parent.mkdir()
        with self.engine.begin() as db:
            db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, note TEXT)"))
            db.execute(text("INSERT INTO users (id,note) VALUES (1,'保留原数据')"))
        with self.assertRaisesRegex(RuntimeError, "未修改原数据"):
            initialize_database(self.engine, self.sessions)
        self.assertEqual(inspect(self.engine).get_table_names(), ["users"])
        with self.engine.connect() as db:
            self.assertEqual(db.scalar(text("SELECT note FROM users WHERE id=1")), "保留原数据")

    def test_missing_unique_constraint_is_rejected(self):
        self.path.parent.mkdir()
        metadata = current_metadata()
        receipts = metadata.tables["access_switch_receipts"]
        for constraint in list(receipts.constraints):
            if isinstance(constraint, UniqueConstraint):
                receipts.constraints.remove(constraint)
        metadata.create_all(self.engine)
        with self.assertRaises(RuntimeError):
            prepare_schema(self.engine)

    def test_changed_columns_are_rejected(self):
        initialize_database(self.engine, self.sessions)
        with self.engine.begin() as db:
            db.execute(text("ALTER TABLE users ADD COLUMN old_flag INTEGER"))
        with self.assertRaises(RuntimeError):
            prepare_schema(self.engine)
        self.assertIn("old_flag", {row["name"] for row in inspect(self.engine).get_columns("users")})

    def test_relative_sqlite_paths_are_resolved_against_project(self):
        self.assertEqual(Path(database_url("sqlite:///data/example.db").database), ROOT / "data" / "example.db")
        self.assertEqual(database_url("sqlite:///:memory:").database, ":memory:")

    def test_first_app_start_creates_database_without_extra_commands(self):
        # 独立进程验证真实启动钩子，防止测试预先建表掩盖启动问题。
        code = '''
from fastapi.testclient import TestClient
from backend.main import app
with TestClient(app) as client:
    assert client.get('/api/v1/health/ready').status_code == 200
    result = client.post('/api/v1/auth/login', json={'identifier':'admin','password':'LocalTestPass123'})
    assert result.status_code == 200, result.text
    headers = {'Authorization':'Bearer ' + result.json()['token']}
    store = client.post('/api/v1/stores', headers=headers, json={'name':'首次运行门店'})
    assert store.status_code == 200, store.text
    areas = client.get('/api/v1/access/stores/' + str(store.json()['id']) + '/areas', headers=headers)
    assert areas.status_code == 200 and len(areas.json()) == 1, areas.text
'''
        environment = {**os.environ, "DATABASE_URL": "sqlite:///" + self.path.as_posix(),
            "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "LocalTestPass123", "ADMIN_EMAIL": "admin@example.com",
            "APP_ENV": "development", "TTLOCK_REAL_ENABLED": "false", "TTLOCK_MASTER_KEY": "",
            "UPLOAD_DIR": str(Path(self.tmp.name) / "uploads")}
        result = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=ROOT,
            env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(current_metadata().tables))
