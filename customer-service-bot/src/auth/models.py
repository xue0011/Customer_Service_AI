"""认证相关的 Pydantic schema。"""

from __future__ import annotations

from pydantic import BaseModel


class TokenRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    display_name: str = ""
    customer_id: str | None = None


class UserOut(BaseModel):
    id: str
    username: str | None = None
    role: str
    display_name: str = ""
    customer_id: str | None = None
    is_active: bool = True


class CustomerCreate(BaseModel):
    customer_id: str
    name: str = ""
