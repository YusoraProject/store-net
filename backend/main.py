import io
import json
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from PIL import Image, ImageOps
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import PERMISSIONS, current_user, permissions_for, require
from .billing import cents_to_money, money_to_cents, quote_cents
from .config import *
from .database import Base, SessionLocal, engine, get_db
from .models import *
from .schemas import *
from .security import create_token, hash_password, verify_password
from . import area_billing, area_switching
from .access_models import BillingArea, ConsumptionArea, ConsumptionSegment, MemberOccupancy, PasscodeRequest, AccessAudit
from .access_credentials import secure_request, secret_box
from .access_journal import release_consumption
from .ttlock_client import LockError

app = FastAPI(title="StoreNet API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    labels = {"username": "用户名", "email": "邮箱", "password": "密码", "name": "名称",
              "identifier": "账号", "qq": "QQ号", "store_id": "门店", "user_id": "用户",
              "remark": "备注", "idempotency_key": "结账请求标识"}
    messages = []
    for error in exc.errors():
        field = labels.get(str(error["loc"][-1]), "提交内容")
        kind = error["type"]
        context = error.get("ctx", {})
        if kind == "missing": message = f"{field}不能为空"
        elif kind == "string_too_short": message = f"{field}至少需要{context.get('min_length')}个字符"
        elif kind == "string_too_long": message = f"{field}不能超过{context.get('max_length')}个字符"
        else: message = f"{field}格式或数值不正确，请检查后重试"
        messages.append(message)
    return JSONResponse(status_code=422, content={"detail": "；".join(messages)})


@app.get("/api/v1/admin/stats")
def registration_stats(db: Session = Depends(get_db), user: User = Depends(require("users.manage"))):
    # 统计在数据库内完成，不为画趋势图传输完整用户列表。
    now = datetime.utcnow()
    months = []
    for offset in range(5, -1, -1):
        absolute = now.year * 12 + now.month - 1 - offset
        year, month = divmod(absolute, 12)
        start = datetime(year, month + 1, 1)
        end = datetime(year + 1, 1, 1) if month == 11 else datetime(year, month + 2, 1)
        count = db.scalar(select(func.count(User.id)).where(User.created_at >= start, User.created_at < end)) or 0
        months.append({"month": start.strftime("%Y-%m"), "count": count})
    return {"total_users": db.scalar(select(func.count(User.id))) or 0,
            "new_this_month": months[-1]["count"], "months": months}

_limits = defaultdict(deque)
_limit_lock = threading.Lock()


def limited(request: Request, scope: str, limit: int = 10):
    key = f"{scope}:{request.client.host if request.client else 'unknown'}"
    now = time.monotonic()
    with _limit_lock:
        events = _limits[key]
        while events and events[0] < now - 60:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(429, "操作过于频繁，请稍后重试", headers={"Retry-After": "60"})
        events.append(now)


def role_out(row: Role) -> RoleOut:
    return RoleOut(id=row.id, name=row.name, description=row.description, permissions=json.loads(row.permissions_json), is_system=row.is_system)


def user_out(db: Session, row: User) -> UserOut:
    role = db.get(Role, row.role_id)
    return UserOut(id=row.id, username=row.username, email=row.email, name=row.name, avatar=row.avatar, qq=row.qq,
                   role_id=row.role_id, role_name=role.name if role else "", is_active=row.is_active, created_at=row.created_at)


def store_out(row: Store) -> StoreOut:
    return StoreOut(id=row.id, name=row.name, address=row.address, remark=row.remark, is_active=row.is_active,
                    created_at=row.created_at, updated_at=row.updated_at)


def benefit(db: Session, store_id: int, user_id: int) -> MemberBenefit:
    row = db.execute(select(MemberBenefit).where(MemberBenefit.store_id == store_id, MemberBenefit.user_id == user_id)).scalar_one_or_none()
    if not row:
        row = MemberBenefit(store_id=store_id, user_id=user_id)
        db.add(row); db.flush()
    return row


def membership(db: Session, store_id: int, user_id: int, active=True) -> StoreMember:
    query = select(StoreMember).where(StoreMember.store_id == store_id, StoreMember.user_id == user_id)
    if active:
        query = query.where(StoreMember.is_active == True)  # noqa: E712
    row = db.execute(query).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "未找到有效的门店会员关系")
    return row


def assert_store_scope(db: Session, user: User, store_id: int, permission: str) -> Store:
    # 非管理员除了有管理权限，还必须是本店的有效店长。
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "门店不存在")
    perms = permissions_for(db, user)
    role = db.get(Role, user.role_id)
    if permission not in perms:
        raise HTTPException(403, "没有操作权限")
    if not role or role.name != "admin":
        member = db.execute(select(StoreMember).where(StoreMember.store_id == store_id, StoreMember.user_id == user.id,
                                                       StoreMember.store_role == "manager", StoreMember.is_active == True)).scalar_one_or_none()  # noqa: E712
        if not member:
            raise HTTPException(403, "无权访问该门店")
    return store


def member_out(db: Session, row: StoreMember) -> MemberOut:
    target = db.get(User, row.user_id); b = benefit(db, row.store_id, row.user_id)
    return MemberOut(id=row.id, store_id=row.store_id, user_id=row.user_id, username=target.username, name=target.name,
                     store_role=row.store_role, is_active=row.is_active, paid=cents_to_money(b.paid_cents),
                     bonus=cents_to_money(b.bonus_cents), times_count=b.times_count)


def consumption_out(row: Consumption) -> ConsumptionOut:
    from sqlalchemy.orm import object_session
    db = object_session(row)
    link = db.get(ConsumptionArea, row.id) if db else None
    area = db.get(BillingArea, link.area_id) if link else None
    visits = db.scalars(select(ConsumptionSegment).where(ConsumptionSegment.consumption_id == row.id)
                       .order_by(ConsumptionSegment.started_at, ConsumptionSegment.id)).all() if db else []
    history = [{"area_id": v.area_id, "area_name": db.get(BillingArea, v.area_id).name,
                "started_at": v.started_at, "ended_at": v.ended_at} for v in visits]
    return ConsumptionOut(id=row.id, area_id=link.area_id if link else None, area_name=area.name if area else None,
                          segments=history,
                          store_id=row.store_id, user_id=row.user_id, started_at=row.started_at,
                          ended_at=row.ended_at, duration_minutes=row.duration_minutes,
                          amount_due=cents_to_money(row.amount_due_cents), amount_paid=cents_to_money(row.paid_cents),
                          payment_method=row.payment_method, status=row.status, remark=row.remark)


def get_pricing(db: Session, store_id: int) -> StorePricing:
    row = db.execute(select(StorePricing).where(StorePricing.store_id == store_id)).scalar_one_or_none()
    if not row:
        row = StorePricing(store_id=store_id); db.add(row); db.flush()
    return row


def pricing_dict(row: StorePricing):
    return pricing_payload(row)


PRICE_NAMES = [
    "workday_day_hourly", "workday_day_cap", "workday_night_hourly", "workday_night_cap",
    "weekend_day_hourly", "weekend_day_cap", "weekend_night_hourly", "weekend_night_cap",
    "holiday_day_hourly", "holiday_day_cap", "holiday_night_hourly", "holiday_night_cap",
]


def pricing_payload(row: StorePricing) -> dict:
    return {name: cents_to_money(getattr(row, name + "_cents")) for name in PRICE_NAMES}


def initialize():
    from .initialize import initialize_database
    initialize_database(engine, SessionLocal)


@app.on_event("startup")
def startup():
    initialize()


@app.get("/api/v1/health/live")
def live(): return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready():
    try:
        with engine.connect() as conn: conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "数据库暂时不可用") from exc
    return {"status": "ready"}


@app.post("/api/v1/auth/register", response_model=TokenOut)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    limited(request, "register", 5)
    if db.execute(select(User).where(or_(User.username == payload.username.strip(), User.email == payload.email.lower()))).scalar_one_or_none():
        raise HTTPException(409, "用户名或邮箱已存在")
    if not any(x.isalpha() for x in payload.password) or not any(x.isdigit() for x in payload.password):
        raise HTTPException(400, "密码必须同时包含字母和数字")
    role = db.execute(select(Role).where(Role.name == "member")).scalar_one()
    user = User(username=payload.username.strip(), email=payload.email.lower(), password_hash=hash_password(payload.password),
                name=(payload.name or payload.username).strip(), role_id=role.id)
    db.add(user); db.commit(); db.refresh(user)
    return TokenOut(token=create_token(user.id, TOKEN_SECRET, TOKEN_TTL_MINUTES))


@app.post("/api/v1/auth/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    limited(request, "login")
    user = db.execute(select(User).where(or_(User.username == payload.identifier, User.email == payload.identifier.lower()))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(401, "账号或密码错误")
    if not user.is_active: raise HTTPException(403, "账号已被停用")
    return TokenOut(token=create_token(user.id, TOKEN_SECRET, TOKEN_TTL_MINUTES))


@app.get("/api/v1/users/me", response_model=UserOut)
def me(db: Session = Depends(get_db), user: User = Depends(current_user)): return user_out(db, user)


@app.put("/api/v1/users/me", response_model=UserOut)
def update_me(payload: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if payload.name is not None: user.name = payload.name.strip()
    if payload.qq is not None:
        qq = payload.qq.strip()
        if qq and not qq.isdigit(): raise HTTPException(400, "QQ号只能包含数字")
        user.qq = qq or None
    if payload.avatar is not None: user.avatar = payload.avatar
    db.commit(); db.refresh(user); return user_out(db, user)


@app.get("/api/v1/users/me/permissions")
def my_permissions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"permissions": sorted(permissions_for(db, user))}


@app.post("/api/v1/users/me/avatar")
async def avatar(request: Request, file: UploadFile = File(...), user: User = Depends(current_user)):
    limited(request, "avatar", 5); content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES: raise HTTPException(400, "文件过大，请选择较小的图片")
    try:
        Image.MAX_IMAGE_PIXELS = MAX_UPLOAD_PIXELS
        with Image.open(io.BytesIO(content)) as source: source.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source); image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            output = io.BytesIO(); image.convert("RGB").save(output, "JPEG", quality=88, optimize=True)
    except Exception as exc: raise HTTPException(400, "图片无效或不符合安全要求") from exc
    filename = f"avatar-{user.id}-{uuid.uuid4().hex}.jpg"; (UPLOAD_DIR / filename).write_bytes(output.getvalue())
    user.avatar = f"/api/v1/uploads/{filename}"
    with SessionLocal() as db:
        target = db.get(User, user.id); target.avatar = user.avatar; db.commit()
    return {"url": user.avatar}


@app.get("/api/v1/uploads/{filename}", include_in_schema=False)
def uploaded(filename: str):
    if filename != Path(filename).name or not filename.startswith("avatar-"): raise HTTPException(404, "请求的资源不存在")
    target = (UPLOAD_DIR / filename).resolve()
    if target.parent != UPLOAD_DIR or not target.is_file(): raise HTTPException(404, "请求的资源不存在")
    return FileResponse(target, headers={"X-Content-Type-Options": "nosniff"})


@app.get("/api/v1/admin/roles", response_model=list[RoleOut])
def roles(db: Session = Depends(get_db), _: User = Depends(require("roles.manage"))):
    return [role_out(x) for x in db.execute(select(Role).order_by(Role.name)).scalars()]


@app.post("/api/v1/admin/roles", response_model=RoleOut)
def create_role(payload: RoleIn, db: Session = Depends(get_db), _: User = Depends(require("roles.manage"))):
    unknown = set(payload.permissions) - PERMISSIONS
    if unknown: raise HTTPException(400, f"未知的权限：{sorted(unknown)}")
    row = Role(name=payload.name.strip(), description=payload.description, permissions_json=json.dumps(sorted(set(payload.permissions))))
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "角色已存在")
    db.refresh(row); return role_out(row)


@app.put("/api/v1/admin/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: int, payload: RoleIn, db: Session = Depends(get_db), _: User = Depends(require("roles.manage"))):
    row = db.get(Role, role_id)
    if not row: raise HTTPException(404, "请求的资源不存在")
    if row.is_system and row.name == "admin": raise HTTPException(400, "不能修改管理员角色")
    if set(payload.permissions) - PERMISSIONS: raise HTTPException(400, "包含未知权限")
    row.name = payload.name.strip(); row.description = payload.description; row.permissions_json = json.dumps(sorted(set(payload.permissions)))
    db.commit(); db.refresh(row); return role_out(row)


@app.delete("/api/v1/admin/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db), _: User = Depends(require("roles.manage"))):
    row = db.get(Role, role_id)
    if not row: raise HTTPException(404, "请求的资源不存在")
    if row.is_system: raise HTTPException(400, "不能删除系统角色")
    if db.scalar(select(func.count()).select_from(User).where(User.role_id == role_id)):
        raise HTTPException(409, "该角色仍有用户使用，无法删除")
    db.delete(row); db.commit(); return {"message": "deleted"}


@app.get("/api/v1/admin/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _: User = Depends(require("users.manage"))):
    return [user_out(db, x) for x in db.execute(select(User).order_by(User.created_at.desc())).scalars()]


@app.put("/api/v1/admin/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserAdminUpdate, db: Session = Depends(get_db), actor: User = Depends(require("users.manage"))):
    row = db.get(User, user_id)
    if not row: raise HTTPException(404, "请求的资源不存在")
    if row.id == actor.id and payload.is_active is False: raise HTTPException(400, "不能停用自己的账号")
    if payload.role_id is not None and not db.get(Role, payload.role_id): raise HTTPException(404, "角色不存在")
    if payload.role_id is not None: row.role_id = payload.role_id
    if payload.is_active is not None: row.is_active = payload.is_active
    db.commit(); db.refresh(row); return user_out(db, row)


@app.get("/api/v1/stores", response_model=list[StoreOut])
def list_stores(db: Session = Depends(get_db), user: User = Depends(current_user)):
    role = db.get(Role, user.role_id)
    if role and role.name == "admin": rows = db.execute(select(Store).order_by(Store.name)).scalars()
    else:
        rows = db.execute(select(Store).join(StoreMember, StoreMember.store_id == Store.id).where(
            StoreMember.user_id == user.id, StoreMember.is_active == True).order_by(Store.name)).scalars()  # noqa: E712
    return [store_out(x) for x in rows]


@app.post("/api/v1/stores", response_model=StoreOut)
def create_store(payload: StoreIn, db: Session = Depends(get_db), user: User = Depends(require("stores.manage"))):
    row = Store(**payload.dict(), created_by=user.id); db.add(row); db.flush()
    db.add(StorePricing(store_id=row.id)); db.add(StoreMember(store_id=row.id, user_id=user.id, store_role="manager"))
    db.flush()
    area_billing.required_schema(db)
    area_billing.default_area(db, row.id)
    db.commit(); db.refresh(row); return store_out(row)


@app.get("/api/v1/stores/{store_id}", response_model=StoreOut)
def get_store(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(Store, store_id)
    if not row: raise HTTPException(404, "请求的资源不存在")
    membership(db, store_id, user.id); return store_out(row)


@app.put("/api/v1/stores/{store_id}", response_model=StoreOut)
def update_store(store_id: int, payload: StoreIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = assert_store_scope(db, user, store_id, "stores.manage")
    for key, value in payload.dict().items(): setattr(row, key, value)
    row.updated_at = datetime.utcnow(); db.commit(); db.refresh(row); return store_out(row)


@app.get("/api/v1/stores/{store_id}/members", response_model=list[MemberOut])
def members(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.members.manage")
    rows = db.execute(select(StoreMember).where(StoreMember.store_id == store_id).order_by(StoreMember.updated_at.desc())).scalars()
    result = [member_out(db, x) for x in rows]; db.commit(); return result


@app.get("/api/v1/stores/{store_id}/member-candidates", response_model=list[UserOut])
def member_candidates(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.members.manage")
    rows = db.execute(select(User).where(User.is_active == True).order_by(User.name)).scalars()  # noqa: E712
    return [user_out(db, row) for row in rows]


@app.post("/api/v1/stores/{store_id}/members", response_model=MemberOut)
def add_member(store_id: int, payload: MemberIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.members.manage")
    if payload.store_role not in {"member", "manager"}: raise HTTPException(400, "门店身份无效")
    if not db.get(User, payload.user_id): raise HTTPException(404, "用户不存在")
    row = db.execute(select(StoreMember).where(StoreMember.store_id == store_id, StoreMember.user_id == payload.user_id)).scalar_one_or_none()
    if row: row.is_active = True; row.store_role = payload.store_role; row.updated_at = datetime.utcnow()
    else: row = StoreMember(store_id=store_id, user_id=payload.user_id, store_role=payload.store_role); db.add(row)
    benefit(db, store_id, payload.user_id); db.commit(); db.refresh(row); return member_out(db, row)


@app.put("/api/v1/stores/{store_id}/members/{user_id}", response_model=MemberOut)
def change_member(store_id: int, user_id: int, payload: MemberUpdate, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    assert_store_scope(db, actor, store_id, "store.members.manage"); row = membership(db, store_id, user_id, active=False)
    if payload.store_role is not None:
        if payload.store_role not in {"member", "manager"}: raise HTTPException(400, "门店身份无效")
        row.store_role = payload.store_role
    if payload.is_active is not None: row.is_active = payload.is_active
    row.updated_at = datetime.utcnow(); db.commit(); db.refresh(row); return member_out(db, row)


@app.get("/api/v1/stores/{store_id}/pricing", response_model=PricingIn)
def get_store_pricing(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    membership(db, store_id, user.id)
    rows = area_billing.default_area(db, store_id)
    if len(rows) != 1:
        raise HTTPException(409, "门店有多个区域，请到计费区域分别查看价格")
    result = PricingIn(**{k.removesuffix("_cents"): v/100 for k,v in json.loads(rows[0].pricing_json).items()})
    db.commit()
    return result


@app.put("/api/v1/stores/{store_id}/pricing", response_model=PricingIn)
def set_store_pricing(store_id: int, payload: PricingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.pricing.manage"); row = get_pricing(db, store_id)
    areas = area_billing.default_area(db, store_id)
    if len(areas) != 1:
        raise HTTPException(409, "门店有多个区域，请到计费区域分别修改价格")
    for name in PRICE_NAMES:
        value = getattr(payload, name)
        if value < 0: raise HTTPException(400, "价格不能为负数")
        setattr(row, name + "_cents", money_to_cents(value))
    areas[0].pricing_json = json.dumps({name + "_cents": getattr(row, name + "_cents") for name in PRICE_NAMES})
    row.updated_at = datetime.utcnow(); db.commit(); return pricing_payload(row)


@app.post("/api/v1/stores/{store_id}/benefits/{user_id}", response_model=MemberOut)
def change_benefit(store_id: int, user_id: int, payload: BenefitChange, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    assert_store_scope(db, actor, store_id, "store.members.manage"); member = membership(db, store_id, user_id)
    db.execute(update(User).where(User.id == user_id).values(id=user_id))
    row = benefit(db, store_id, user_id); before = {"paid": row.paid_cents, "bonus": row.bonus_cents, "times": row.times_count}
    paid_delta = money_to_cents(payload.paid_delta); bonus_delta = money_to_cents(payload.bonus_delta)
    if row.paid_cents + paid_delta < 0 or row.bonus_cents + bonus_delta < 0 or row.times_count + payload.times_delta < 0:
        raise HTTPException(400, "余额或次卡数量不能小于零")
    row.paid_cents += paid_delta; row.bonus_cents += bonus_delta; row.times_count += payload.times_delta; row.updated_at = datetime.utcnow()
    after = {"paid": row.paid_cents, "bonus": row.bonus_cents, "times": row.times_count}
    db.add(BenefitLedger(store_id=store_id, user_id=user_id, action="adjust", paid_delta_cents=paid_delta,
                         bonus_delta_cents=bonus_delta, times_delta=payload.times_delta, before_json=json.dumps(before),
                         after_json=json.dumps(after), remark=payload.remark, operator_id=actor.id))
    db.commit(); return member_out(db, member)


@app.get("/api/v1/stores/{store_id}/ledgers", response_model=list[LedgerOut])
def ledgers(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.ledgers.view")
    rows = db.execute(select(BenefitLedger).where(BenefitLedger.store_id == store_id).order_by(BenefitLedger.created_at.desc()).limit(500)).scalars()
    return [LedgerOut(id=x.id, store_id=x.store_id, user_id=x.user_id, action=x.action,
                      paid_delta=cents_to_money(x.paid_delta_cents), bonus_delta=cents_to_money(x.bonus_delta_cents),
                      times_delta=x.times_delta, remark=x.remark, operator_id=x.operator_id, created_at=x.created_at) for x in rows]


def open_consumption(db: Session, user_id: int) -> Consumption | None:
    return db.execute(select(Consumption).where(Consumption.user_id == user_id, Consumption.status == "open").order_by(Consumption.id.desc())).scalars().first()


def start_consumption(db, store_id, target_id, started_at, operator, area_id=None, key=None, secure=False):
    try:
        return area_billing.begin(db, store_id=store_id, user_id=target_id, operator_id=operator,
            area_id=area_id, key=key, started_at=started_at, secure=secure)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "已有上机申请或区域正在更新，请刷新后查看原记录") from None


def start_response(db, result):
    row, request_id = result
    if row:
        return consumption_out(row)
    pending = db.get(PasscodeRequest, request_id)
    return JSONResponse(status_code=202, content={"request_id": request_id,
        "status": pending.status, "message": pending.safe_error or (
            "正在确认新区密码，仍按原区域计费" if pending.source == "switch" else "正在确认密码，尚未开始计费")},
        headers={"Cache-Control": "no-store"})


@app.get("/api/v1/me/stores", response_model=list[StoreOut])
def my_stores(db: Session = Depends(get_db), user: User = Depends(current_user)): return list_stores(db, user)


@app.post("/api/v1/me/consumption/start", response_model=ConsumptionOut)
def start_mine(payload: StartIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    limited(request, "start", 10)
    if payload.user_id not in {None, user.id}: raise HTTPException(403, "没有操作权限")
    return start_response(db, start_consumption(db, payload.store_id, user.id, datetime.utcnow(), user.id,
        payload.area_id, payload.idempotency_key, request.url.scheme == "https"))


@app.get("/api/v1/me/consumption/current", response_model=ConsumptionOut | None)
def current_mine(db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = open_consumption(db, user.id); return consumption_out(row) if row else None


def quote_row(db: Session, row: Consumption, payload: QuoteIn) -> tuple[datetime, int, int]:
    # 报价和结账共用计算入口，避免页面预览与最终扣款采用不同规则。
    ended = payload.ended_at or datetime.utcnow()
    try: minutes, due = area_switching.quote_accumulated(db, row, get_pricing(db, row.store_id), ended, payload.day_type)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    return ended, minutes, due


@app.post("/api/v1/me/consumption/quote", response_model=QuoteOut)
def quote_mine(payload: QuoteIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = open_consumption(db, user.id)
    if not row: raise HTTPException(404, "没有正在计时的消费记录")
    payload = payload.model_copy(update={"ended_at": None, "day_type": "auto"})
    ended, minutes, due = quote_row(db, row, payload); return QuoteOut(duration_minutes=minutes, amount_due=cents_to_money(due), ended_at=ended)


def checkout(db: Session, row: Consumption, payload: CheckoutIn, actor: User, self_service=False) -> Consumption:
    # 重复请求先返回原结果；扣权益、写流水和关闭消费必须一起提交。
    db.execute(update(User).where(User.id == row.user_id).values(id=row.user_id))
    row = db.scalar(select(Consumption).where(Consumption.id == row.id).with_for_update()
                    .execution_options(populate_existing=True))
    if row.checkout_key == payload.idempotency_key:
        return row
    existing = db.execute(select(Consumption).where(Consumption.checkout_key == payload.idempotency_key)).scalar_one_or_none()
    if existing:
        if existing.id != row.id: raise HTTPException(409, "结账请求标识已用于其他消费")
        return existing
    if row.status != "open": raise HTTPException(409, "该消费记录已经结账")
    area_switching.guard_pending(db, row.user_id)
    if self_service:
        payload = payload.model_copy(update={"ended_at": None, "day_type": "auto"})
    ended, minutes, due = quote_row(db, row, payload); b = benefit(db, row.store_id, row.user_id)
    b = db.scalar(select(MemberBenefit).where(MemberBenefit.id == b.id).with_for_update()
                  .execution_options(populate_existing=True))
    before = {"paid": b.paid_cents, "bonus": b.bonus_cents, "times": b.times_count}
    method = payload.payment_method
    if method == "auto": method = "times_card" if b.times_count > 0 else "balance"
    paid_delta = bonus_delta = times_delta = 0
    if method == "times_card":
        if b.times_count <= 0: raise HTTPException(402, "没有可用的次卡")
        b.times_count -= 1; times_delta = -1; paid_amount = 0
    elif method == "balance":
        if b.paid_cents + b.bonus_cents < due: raise HTTPException(402, "余额不足，请联系店长结账")
        bonus_used = min(b.bonus_cents, due); paid_used = due - bonus_used
        b.bonus_cents -= bonus_used; b.paid_cents -= paid_used; bonus_delta = -bonus_used; paid_delta = -paid_used; paid_amount = due
    elif method in {"cash", "mixed"} and not self_service:
        cash = due if payload.cash_amount is None else money_to_cents(payload.cash_amount)
        if cash < 0 or cash > due: raise HTTPException(400, "现金金额无效")
        wallet = due - cash
        if b.paid_cents + b.bonus_cents < wallet: raise HTTPException(402, "余额不足")
        bonus_used = min(b.bonus_cents, wallet); paid_used = wallet - bonus_used
        b.bonus_cents -= bonus_used; b.paid_cents -= paid_used; bonus_delta = -bonus_used; paid_delta = -paid_used; paid_amount = due
    else: raise HTTPException(400, "不支持该结账方式")
    row.ended_at = ended; row.duration_minutes = minutes; row.amount_due_cents = due; row.paid_cents = paid_amount
    row.payment_method = method; row.status = "paid"; row.checkout_key = payload.idempotency_key; row.remark = payload.remark
    row.operator_id = actor.id; row.updated_at = datetime.utcnow(); b.updated_at = datetime.utcnow()
    after = {"paid": b.paid_cents, "bonus": b.bonus_cents, "times": b.times_count}
    if paid_delta or bonus_delta or times_delta:
        db.add(BenefitLedger(store_id=row.store_id, user_id=row.user_id, action="consume", paid_delta_cents=paid_delta,
                             bonus_delta_cents=bonus_delta, times_delta=times_delta, before_json=json.dumps(before),
                             after_json=json.dumps(after), remark=payload.remark or f"Consumption #{row.id}", operator_id=actor.id))
    area_switching.close_segment(db, row, ended)
    release_consumption(db, row.user_id, row.id)
    try: db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "结账请求冲突，请刷新消费记录") from None
    db.refresh(row); return row


@app.post("/api/v1/me/consumption/checkout", response_model=ConsumptionOut)
def checkout_mine(payload: CheckoutIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = open_consumption(db, user.id)
    if not row:
        existing = db.execute(select(Consumption).where(Consumption.checkout_key == payload.idempotency_key, Consumption.user_id == user.id)).scalar_one_or_none()
        if existing: return consumption_out(existing)
        raise HTTPException(404, "没有正在计时的消费记录")
    return consumption_out(checkout(db, row, payload, user, True))


@app.get("/api/v1/stores/{store_id}/consumptions", response_model=list[ConsumptionOut])
def consumptions(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.consumptions.manage")
    rows = db.execute(select(Consumption).where(Consumption.store_id == store_id).order_by(Consumption.started_at.desc()).limit(500)).scalars()
    return [consumption_out(x) for x in rows]


@app.post("/api/v1/stores/{store_id}/consumptions/start", response_model=ConsumptionOut)
def manager_start(store_id: int, payload: StartIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    limited(request, "manager-start", 10)
    assert_store_scope(db, user, store_id, "store.consumptions.manage")
    if payload.user_id is None: raise HTTPException(400, "请选择用户")
    return start_response(db, start_consumption(db, store_id, payload.user_id, payload.started_at or datetime.utcnow(), user.id,
        payload.area_id, payload.idempotency_key, request.url.scheme == "https"))


@app.post("/api/v1/stores/{store_id}/consumptions/{consumption_id}/checkout", response_model=ConsumptionOut)
def manager_checkout(store_id: int, consumption_id: int, payload: CheckoutIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.consumptions.manage"); row = db.get(Consumption, consumption_id)
    if not row or row.store_id != store_id: raise HTTPException(404, "请求的资源不存在")
    return consumption_out(checkout(db, row, payload, user, False))


@app.get("/api/v1/stores/{store_id}/reports")
def report(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.reports.view")
    active = db.scalar(select(func.count()).select_from(Consumption).where(Consumption.store_id == store_id, Consumption.status == "open"))
    members_count = db.scalar(select(func.count()).select_from(StoreMember).where(StoreMember.store_id == store_id, StoreMember.is_active == True))  # noqa: E712
    revenue = db.scalar(select(func.coalesce(func.sum(Consumption.paid_cents), 0)).where(Consumption.store_id == store_id, Consumption.status == "paid"))
    return {"active_sessions": active, "members": members_count, "revenue": cents_to_money(revenue)}


from .access_api import make_router as make_access_router


def access_scope(db, user, store_id):
    return assert_store_scope(db, user, store_id, "stores.manage")


app.include_router(make_access_router(user_dependency=current_user, db_dependency=get_db,
                                      scope=access_scope, cents=True), prefix="/api/v1")

@app.exception_handler(LockError)
async def lock_error(request: Request, exc: LockError):
    return JSONResponse(status_code=409, content={"detail": str(exc)}, headers={"Cache-Control": "no-store"})


@app.on_event("startup")
def start_access_worker():
    from .access_worker import start_worker
    app.state.access_worker = start_worker()


@app.on_event("shutdown")
def stop_access_worker():
    worker = getattr(app.state, "access_worker", None)
    if worker:
        worker[0].set()
        worker[1].join(timeout=2)


@app.get("/api/v1/me/stores/{store_id}/areas")
def member_areas(store_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    area_billing.required_schema(db)
    area_billing.active_member(db, store_id, user.id)
    db.execute(update(Store).where(Store.id == store_id).values(id=store_id))
    rows = area_billing.default_area(db, store_id)
    from .access_api import public_area
    result = [public_area(r, True) for r in rows if r.enabled]
    db.commit()
    return result


@app.get("/api/v1/me/consumption/access")
def my_access(db: Session = Depends(get_db), user: User = Depends(current_user)):
    area_billing.required_schema(db)
    return JSONResponse(content=area_billing.pending_out(db, user.id), headers={"Cache-Control": "no-store"})


@app.post("/api/v1/me/consumption/access/resume")
def resume_my_access(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    secure_request(request)
    area_billing.required_schema(db)
    limited(request, "access-resume", 5)
    pending = area_billing.pending_out(db, user.id)
    if pending: area_billing.resume(db, pending["id"])
    return area_billing.pending_out(db, user.id)


@app.post("/api/v1/me/consumption/password")
def my_password(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    secure_request(request)
    area_billing.required_schema(db)
    limited(request, "password", 10)
    row = open_consumption(db, user.id)
    if not row: raise HTTPException(404, "没有进行中的消费")
    occupancy = db.get(MemberOccupancy, user.id)
    code = db.get(PasscodeRequest, occupancy.request_id) if occupancy and occupancy.request_id else None
    if code and (code.consumption_id != row.id or code.recipient_id != user.id or code.status != "ready"):
        code = None
    if not code or int(code.end_ms) <= int(time.time()*1000):
        raise HTTPException(404, "当前没有有效的入场密码")
    password = secret_box().decrypt(code.encrypted_password, f"store:{code.store_id}:request:{code.id}:password")
    db.add(AccessAudit(store_id=code.store_id, actor_id=user.id, request_id=code.id, action="member_reveal"))
    db.commit()
    return JSONResponse(content={"password": password, "start_ms": code.start_ms, "end_ms": code.end_ms},
                        headers={"Cache-Control": "no-store"})


def switch_response(db, row, payload, user, request):
    limited(request, "switch-area", 10)
    try:
        return start_response(db, area_switching.switch(db, consumption_id=row.id,
            user_id=row.user_id, operator_id=user.id, area_id=payload.area_id,
            key=payload.idempotency_key, secure=request.url.scheme == "https"))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "换区操作冲突，请刷新查看当前区域") from None


@app.post("/api/v1/me/consumption/switch", response_model=ConsumptionOut)
def switch_mine(payload: SwitchIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = open_consumption(db, user.id)
    if not row: raise HTTPException(404, "没有进行中的消费")
    return switch_response(db, row, payload, user, request)


@app.post("/api/v1/stores/{store_id}/consumptions/{consumption_id}/switch", response_model=ConsumptionOut)
def manager_switch(store_id: int, consumption_id: int, payload: SwitchIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    assert_store_scope(db, user, store_id, "store.consumptions.manage")
    row = db.get(Consumption, consumption_id)
    if not row or row.store_id != store_id: raise HTTPException(404, "消费记录不存在")
    return switch_response(db, row, payload, user, request)
