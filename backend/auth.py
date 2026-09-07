import json
from typing import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import TOKEN_SECRET
from .database import get_db
from .models import Role, User
from .security import decode_token

PERMISSIONS = {
    "users.manage", "roles.manage", "stores.manage", "store.members.manage",
    "store.pricing.manage", "store.consumptions.manage", "store.ledgers.view", "store.reports.view",
}


def current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    try:
        user = db.get(User, decode_token(authorization[7:], TOKEN_SECRET))
    except TimeoutError:
        raise HTTPException(401, "登录已过期，请重新登录")
    except Exception:
        raise HTTPException(401, "登录凭证无效，请重新登录")
    if not user:
        raise HTTPException(401, "登录凭证无效，请重新登录")
    if not user.is_active:
        raise HTTPException(403, "账号已被停用")
    return user


def permissions_for(db: Session, user: User) -> set[str]:
    # 每次查询数据库中的角色，调整权限后不用等待旧令牌过期。
    role = db.get(Role, user.role_id)
    if role and role.name == "admin":
        return set(PERMISSIONS)
    try:
        values = json.loads(role.permissions_json if role else "[]")
    except Exception:
        values = []
    return {x for x in values if x in PERMISSIONS}


def require(permission: str) -> Callable:
    def dependency(db: Session = Depends(get_db), user: User = Depends(current_user)) -> User:
        if permission not in permissions_for(db, user):
            raise HTTPException(403, "没有操作权限")
        return user
    return dependency
