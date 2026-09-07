"""门锁管理接口。两项目独立运行，不互相导入代码。

自动发码必须先绑定门锁并验证授权，会员上机与管理端代上机共用业务流程。
"""
import json
import os
import time
import threading
from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import sessionmaker
from backend.access_credentials import secure_request, save_authorization, valid_client, secret_box, credential
from backend.access_journal import reserve, process, reveal
from backend.ttlock_client import LockError
from sqlalchemy import select, func, inspect, update
from sqlalchemy.exc import IntegrityError

from backend.access_models import BillingArea, LockCredential, CredentialRefresh, PasscodeRequest, AccessAudit, MemberOccupancy


class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                response = await original(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "提交内容格式不正确，请检查必填项和数值"},
                                    headers={"Cache-Control": "no-store"})
            except LockError as exc:
                return JSONResponse(status_code=409, content={"detail": str(exc)}, headers={"Cache-Control": "no-store"})
            except IntegrityError:
                return JSONResponse(status_code=409, content={"detail": "配置被其他操作更新，请刷新后重试"},
                                    headers={"Cache-Control": "no-store"})
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                                    headers={**(exc.headers or {}), "Cache-Control": "no-store"})
        return handler


_limits = defaultdict(deque)
_limits_lock = threading.Lock()


def limited(user_id, action):
    now = time.monotonic()
    with _limits_lock:
        queue = _limits[(user_id, action)]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= 5:
            raise HTTPException(429, "操作过于频繁，请稍后重试", headers={"Retry-After": "60"})
        queue.append(now)


class AuthorizationInput(BaseModel):
    region: str = Field(pattern="^(cn|eu)$")
    client_id: str = Field(min_length=1, max_length=200)
    client_secret: SecretStr
    username: str = Field(min_length=1, max_length=200)
    password: SecretStr


class BindingInput(BaseModel):
    lock_id: str = Field(pattern="^[0-9]{1,20}$")


class IssueInput(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80)


class CancelInput(BaseModel):
    acknowledged: bool = False
    reason: str = Field(min_length=2, max_length=200)


class AreaInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    pricing: dict[str, float]
    auto_issue: bool = False


def validate_prices(values, cents):
    keys = {f"{day}_{period}_{kind}" for day in ("workday", "weekend", "holiday")
            for period in ("day", "night") for kind in ("hourly", "cap")}
    if set(values) != keys:
        raise HTTPException(422, "请完整填写工作日、周末、节假日的日间及夜间价格")
    result = {}
    for key, value in values.items():
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0 or amount > 100000:
                raise ValueError()
            if amount.quantize(Decimal("0.01")) != amount:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise HTTPException(422, "价格必须为0至100000之间、最多两位小数的金额") from None
        result[key + ("_cents" if cents else "")] = int(amount * 100) if cents else float(amount)
    return result


def public_area(row, cents):
    prices = json.loads(row.pricing_json)
    if cents:
        prices = {key.removesuffix("_cents"): value / 100 for key, value in prices.items()}
    return dict(id=row.id, store_id=row.store_id, name=row.name, enabled=row.enabled,
                pricing=prices, lock_id=row.lock_id, lock_name=row.lock_name,
                auto_issue=row.auto_issue)


def make_router(*, user_dependency, db_dependency, scope, cents):
    router = APIRouter(prefix="/access", tags=["门锁与计费区域"], route_class=SafeRoute)

    def ready(db):
        if not inspect(db.get_bind()).has_table("access_areas"):
            raise HTTPException(503, "门锁数据表尚未初始化，请检查数据库配置并重新启动后端")

    def authorize(db, user, store_id):
        scope(db, user, store_id)
        ready(db)

    @router.get("/stores/{store_id}/status")
    def status(store_id: int, response: Response,
               db=Depends(db_dependency), user=Depends(user_dependency)):
        scope(db, user, store_id)
        response.headers["Cache-Control"] = "no-store"
        installed = inspect(db.get_bind()).has_table("access_credentials")
        saved = db.get(LockCredential, store_id) if installed else None
        renewal_ready = inspect(db.get_bind()).has_table("access_credential_refresh")
        state = db.get(CredentialRefresh, store_id) if renewal_ready else None
        expires_at, renewal_error = None, state.safe_error if state else None
        if saved:
            try:
                _, bundle = credential(db, store_id)
                expires_at = int(bundle["expires_at"])
            except (LockError, ValueError, KeyError, TypeError):
                renewal_error = "授权配置无法读取，请检查服务器加密主密钥"
        renewal_status = state.status if state else ("ready" if renewal_ready else "initialization_required")
        if renewal_status == "ready" and saved and expires_at and expires_at <= int(time.time()) + 300:
            renewal_status = "due"
        return {"initialized": installed, "credential_configured": bool(saved),
                "region": saved.region if saved else None,
                "tested_at": saved.tested_at if saved else None,
                "expires_at": expires_at,
                "refresh_status": renewal_status,
                "refresh_error": renewal_error,
                "last_refresh_at": state.last_success_at if state else None,
                "automatic_available": True,
                "message": "区域价格用于新上机；进行中的消费保持上机时价格。自动发码成功后才开始计费。"}

    @router.post("/stores/{store_id}/authorization/refresh")
    def refresh_authorization(store_id: int, request: Request,
                              db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        limited(user.id, "authorization-refresh")
        from .access_refresh import refresh_store
        sessions = sessionmaker(db.get_bind())
        db.rollback()
        result = refresh_store(sessions, store_id)
        messages = {"ready": "授权可用，临近到期时会自动续期", "refreshing": "授权正在续期，请稍后刷新状态",
                    "unknown": "上次续期结果无法确认，请重新授权", "reauthorize": "授权续期被拒绝，请重新授权",
                    "superseded": "授权状态已变化，请刷新查看"}
        return {"status": result, "message": messages[result]}

    @router.get("/stores/{store_id}/areas")
    def areas(store_id: int, db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        rows = db.scalars(select(BillingArea).where(BillingArea.store_id == store_id)
                          .order_by(BillingArea.id)).all()
        return [public_area(row, cents) for row in rows]

    def save(db, user, store_id, payload, row=None):
        authorize(db, user, store_id)
        if not payload.name.strip():
            raise HTTPException(422, "区域名称不能为空")
        if payload.auto_issue:
            if not row or not row.lock_id or row.password_version != 4:
                raise HTTPException(409, "请先保存区域并绑定支持第四版密码的门锁")
            valid_client(db, store_id)
        prices = validate_prices(payload.pricing, cents)
        if row is None:
            row = BillingArea(store_id=store_id)
            db.add(row)
        row.name = payload.name.strip()
        row.enabled = payload.enabled
        row.pricing_json = json.dumps(prices)
        row.auto_issue = payload.auto_issue
        db.add(AccessAudit(store_id=store_id, actor_id=user.id, action="area_updated"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该门店已有同名区域") from None
        db.refresh(row)
        return public_area(row, cents)

    @router.post("/stores/{store_id}/areas")
    def create_area(store_id: int, payload: AreaInput, request: Request,
                    db=Depends(db_dependency), user=Depends(user_dependency)):
        if payload.auto_issue: secure_request(request)
        return save(db, user, store_id, payload)

    @router.put("/stores/{store_id}/areas/{area_id}")
    def update_area(store_id: int, area_id: int, payload: AreaInput, request: Request,
                    db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        row = db.get(BillingArea, area_id)
        if not row or row.store_id != store_id:
            raise HTTPException(404, "区域不存在")
        if payload.auto_issue: secure_request(request)
        return save(db, user, store_id, payload, row)

    @router.get("/stores/{store_id}/records")
    def records(store_id: int, response: Response, page: int = Query(1, ge=1),
                page_size: int = Query(20, ge=1, le=100),
                area_id: int | None = None, source: str | None = None,
                status: str | None = None, from_date: datetime | None = None,
                to_date: datetime | None = None,
                db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        response.headers["Cache-Control"] = "no-store"
        filters = [PasscodeRequest.store_id == store_id]
        for column, value in [(PasscodeRequest.area_id, area_id), (PasscodeRequest.source, source),
                              (PasscodeRequest.status, status)]:
            if value is not None:
                filters.append(column == value)
        if from_date:
            filters.append(PasscodeRequest.created_at >= from_date)
        if to_date:
            filters.append(PasscodeRequest.created_at <= to_date)
        rows = db.scalars(select(PasscodeRequest).where(*filters)
            .order_by(PasscodeRequest.created_at.desc(), PasscodeRequest.id.desc())
            .offset((page-1)*page_size).limit(page_size)).all()
        return {"total": db.scalar(select(func.count()).select_from(PasscodeRequest).where(*filters)),
                "items": [dict(id=r.id, store_id=r.store_id, area_id=r.area_id,
                    operator_id=r.operator_id, recipient_id=r.recipient_id, source=r.source,
                    status=r.status, created_at=r.created_at, start_ms=r.start_ms, end_ms=r.end_ms,
                    error=r.safe_error) for r in rows]}


    @router.post("/stores/{store_id}/authorization")
    def authorize_lock(store_id: int, payload: AuthorizationInput, request: Request,
                       db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        limited(user.id, "authorization")
        save_authorization(db, store_id, user.id, payload.region, payload.client_id,
                           payload.client_secret.get_secret_value(), payload.username,
                           payload.password.get_secret_value())
        return {"configured": True, "message": "授权及连接测试成功"}

    @router.get("/stores/{store_id}/locks")
    def locks(store_id: int, request: Request, response: Response,
              page: int = Query(1, ge=1),
              db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        adapter, token, version = valid_client(db, store_id)
        db.rollback()
        response.headers["Cache-Control"] = "no-store"
        return adapter.locks(token, page=page)

    @router.put("/stores/{store_id}/areas/{area_id}/lock")
    def bind_lock(store_id: int, area_id: int, payload: BindingInput, request: Request,
                  db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        row = db.get(BillingArea, area_id)
        if not row or row.store_id != store_id:
            raise HTTPException(404, "区域不存在")
        adapter, token, version = valid_client(db, store_id)
        db.rollback()
        match = None
        for page in range(1, 101):
            found = adapter.locks(token, page=page)
            match = next((lock for lock in found if str(lock["lock_id"]) == payload.lock_id), None)
            if match or len(found) < 100:
                break
        if not match or match["password_version"] != 4:
            raise HTTPException(422, "请选择当前授权账号下支持第四版密码的门锁")
        changed = db.execute(update(LockCredential).where(
            LockCredential.store_id == store_id, LockCredential.version == version
        ).values(updated_at=datetime.utcnow()))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "门店授权已变化，请重新加载门锁列表")
        row = db.get(BillingArea, area_id)
        if not row or row.store_id != store_id:
            raise HTTPException(404, "区域不存在")
        row.lock_id = payload.lock_id
        row.lock_name = match["name"]
        row.password_version = 4
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该门锁已绑定其他区域") from None
        return public_area(row, cents)

    @router.post("/stores/{store_id}/areas/{area_id}/issue")
    def manual_issue(store_id: int, area_id: int, payload: IssueInput, request: Request,
                     response: Response, db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        limited(user.id, "issue")
        row = db.get(BillingArea, area_id)
        if not row or row.store_id != store_id or not row.enabled or not row.lock_id:
            raise HTTPException(409, "区域未启用或尚未绑定门锁")
        adapter, token, version = valid_client(db, store_id)
        values = dict(store_id=store_id, area_id=area_id, operator_id=user.id,
                      recipient_id=None, idempotency_key=payload.idempotency_key,
                      lock_id=row.lock_id, credential_version=version, password_version=row.password_version,
                      start_ms=int(time.time()//3600)*3600000, source="manual")
        bind = db.get_bind()
        db.rollback()
        sessions = sessionmaker(bind)
        request_id = reserve(sessions, **values)
        process(sessions, request_id, client=adapter, token=token, box=secret_box())
        response.headers["Cache-Control"] = "no-store"
        result = db.get(PasscodeRequest, request_id)
        return {"id": request_id, "status": result.status, "message": result.safe_error}

    @router.post("/stores/{store_id}/records/{request_id}/reconcile")
    def reconcile(store_id: int, request_id: str, request: Request,
                  db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        limited(user.id, "reconcile")
        row = db.get(PasscodeRequest, request_id)
        if not row or row.store_id != store_id:
            raise HTTPException(404, "发码记录不存在")
        adapter, token, version = valid_client(db, store_id)
        if version != row.credential_version:
            raise HTTPException(409, "授权版本已变化，请人工核对原账号")
        bind = db.get_bind()
        db.rollback()
        from .area_billing import finalize
        process(sessionmaker(bind), request_id, client=adapter, token=token, box=secret_box(), finalize=finalize)
        return {"message": "核对完成，请刷新记录；结果未确认前不要另行创建"}

    @router.post("/stores/{store_id}/records/{request_id}/reveal")
    def reveal_password(store_id: int, request_id: str, request: Request, response: Response,
                        db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        limited(user.id, "reveal")
        bind = db.get_bind()
        db.rollback()
        password = reveal(sessionmaker(bind), request_id, actor_id=user.id,
                          allowed_store_ids={store_id}, box=secret_box())
        response.headers["Cache-Control"] = "no-store"
        return {"password": password}

    @router.post("/stores/{store_id}/records/{request_id}/cancel")
    def cancel_pending(store_id: int, request_id: str, payload: CancelInput, request: Request,
                       db=Depends(db_dependency), user=Depends(user_dependency)):
        authorize(db, user, store_id)
        secure_request(request)
        if not payload.acknowledged:
            raise HTTPException(422, "必须确认原密码可能仍有效，取消申请不会撤销门锁密码")
        changed = db.execute(update(PasscodeRequest).where(PasscodeRequest.id == request_id,
            PasscodeRequest.store_id == store_id, PasscodeRequest.source.in_(["automatic", "switch"]),
            PasscodeRequest.status.in_(["review", "unknown"]),
            PasscodeRequest.consumption_id.is_(None),
            (PasscodeRequest.lease_until.is_(None)) | (PasscodeRequest.lease_until < datetime.utcnow()),
        ).values(status="cancelled", safe_error="店长取消待确认申请：" + payload.reason,
                 updated_at=datetime.utcnow(), lease_token=None, lease_until=None))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "只能取消无人处理且尚未完成的待确认申请")
        row = db.get(PasscodeRequest, request_id)
        occupancy = db.get(MemberOccupancy, row.recipient_id)
        if occupancy and occupancy.request_id == row.id and occupancy.consumption_id is None:
            db.delete(occupancy)
        if occupancy and occupancy.pending_request_id == row.id:
            occupancy.pending_request_id = None
        db.add(AccessAudit(store_id=store_id, actor_id=user.id, request_id=request_id, action="cancel_unknown"))
        db.commit()
        return {"message": "申请已取消；换区申请仍按原区域计费。此操作未撤销可能已经生成的门锁密码。"}

    return router
