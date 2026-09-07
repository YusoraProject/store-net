import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # 系统环境变量优先，文件只补齐未设置的项。
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
# 当前按首次本地运行准备，不默认连接旧测试库或正式数据库。
APP_ENV = os.getenv("APP_ENV", "development").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/store-net.db")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "store-net-development-secret-change-me")
TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "1440"))
_upload_path = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR = (_upload_path if _upload_path.is_absolute() else ROOT / _upload_path).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "2097152"))
MAX_UPLOAD_PIXELS = int(os.getenv("MAX_UPLOAD_PIXELS", "16000000"))
CORS_ORIGINS = [x.strip().rstrip("/") for x in os.getenv("CORS_ORIGINS", "http://localhost:8081").split(",") if x.strip()]
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123@StoreNet")

if APP_ENV in {"production", "prod"}:
    if len(TOKEN_SECRET) < 32 or ADMIN_PASSWORD == "admin123@StoreNet" or CORS_ORIGINS == ["*"]:
        raise RuntimeError("生产环境需要足够长度的令牌密钥、非默认管理员密码和明确的跨域来源")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
