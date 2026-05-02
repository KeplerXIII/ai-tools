import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,64}$")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        u = v.strip().lower()
        if not _USERNAME_RE.match(u):
            raise ValueError("username: 3–64 символа, латиница, цифры, подчёркивание")
        return u

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v


class UserPublic(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr | None = None
    is_active: bool
    is_admin: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenWithUser(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip().lower()
