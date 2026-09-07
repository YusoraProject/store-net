from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    identifier: str
    password: str


class TokenOut(BaseModel):
    token: str


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    qq: Optional[str] = Field(default=None, max_length=20)
    avatar: Optional[str] = Field(default=None, max_length=255)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    name: str
    avatar: Optional[str]
    qq: Optional[str]
    role_id: int
    role_name: str
    is_active: bool
    created_at: datetime


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=255)
    permissions: List[str] = []


class RoleOut(RoleIn):
    id: int
    is_system: bool


class UserAdminUpdate(BaseModel):
    role_id: Optional[int] = None
    is_active: Optional[bool] = None


class StoreIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    remark: Optional[str] = None
    is_active: bool = True


class StoreOut(StoreIn):
    id: int
    created_at: datetime
    updated_at: datetime


class MemberIn(BaseModel):
    user_id: int
    store_role: str = "member"


class MemberUpdate(BaseModel):
    store_role: Optional[str] = None
    is_active: Optional[bool] = None


class MemberOut(BaseModel):
    id: int
    store_id: int
    user_id: int
    username: str
    name: str
    store_role: str
    is_active: bool
    paid: float
    bonus: float
    times_count: int


class PricingIn(BaseModel):
    workday_day_hourly: float = 8
    workday_day_cap: float = 40
    workday_night_hourly: float = 8
    workday_night_cap: float = 40
    weekend_day_hourly: float = 8
    weekend_day_cap: float = 40
    weekend_night_hourly: float = 8
    weekend_night_cap: float = 40
    holiday_day_hourly: float = 8
    holiday_day_cap: float = 40
    holiday_night_hourly: float = 8
    holiday_night_cap: float = 40


class BenefitChange(BaseModel):
    paid_delta: float = 0
    bonus_delta: float = 0
    times_delta: int = 0
    remark: str = Field(min_length=1, max_length=500)


class SwitchIn(BaseModel):
    area_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=80)


class StartIn(BaseModel):
    store_id: int
    area_id: Optional[int] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=80)
    user_id: Optional[int] = None
    started_at: Optional[datetime] = None


class QuoteIn(BaseModel):
    ended_at: Optional[datetime] = None
    day_type: str = "auto"


class CheckoutIn(QuoteIn):
    payment_method: str = "auto"
    cash_amount: Optional[float] = None
    idempotency_key: str = Field(min_length=8, max_length=80)
    remark: Optional[str] = Field(default=None, max_length=500)


class ConsumptionOut(BaseModel):
    id: int
    segments: list[dict] = Field(default_factory=list)
    area_id: Optional[int] = None
    area_name: Optional[str] = None
    store_id: int
    user_id: int
    started_at: datetime
    ended_at: datetime
    duration_minutes: int
    amount_due: float
    amount_paid: float
    payment_method: str
    status: str
    remark: Optional[str]


class QuoteOut(BaseModel):
    duration_minutes: int
    amount_due: float
    ended_at: datetime


class LedgerOut(BaseModel):
    id: int
    store_id: int
    user_id: int
    action: str
    paid_delta: float
    bonus_delta: float
    times_delta: int
    remark: Optional[str]
    operator_id: int
    created_at: datetime
