from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import make_url
from pathlib import Path

from .config import DATABASE_URL, ROOT

def database_url(value):
    """SQLite 相对路径固定以项目根目录为准，避免从不同目录启动时连错库。"""
    url = make_url(value)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            url = url.set(database=str((ROOT / path).resolve()))
    return url


kwargs = {"pool_pre_ping": True}
url = database_url(DATABASE_URL)
if url.get_backend_name() == "sqlite":
    kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}

engine = create_engine(url, **kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    # 每个请求单独使用会话；异常退出时也必须关闭，不能让连接一直占着。
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
