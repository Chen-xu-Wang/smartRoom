"""认证接口 —— 真实校验 MySQL user 表.

前端 resident / admin 登录均走本接口，后端用 SHA256 校验密码，
返回用户信息（id / username / real_name / role，住户另含名下房屋 house_ids）和访问令牌 token。
之后的所有接口都要带 Authorization: Bearer <token>，身份以令牌为准（见 app/security.py）。
"""
import hashlib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..database import query_one
from ..security import CurrentUser, create_token, current_user
from ..services.user_house import list_bindings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    username = (req.username or "").strip()
    password = req.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    row = query_one(
        "SELECT id, username, real_name, role, status, password FROM `user` WHERE username = %s",
        (username,),
    )
    if not row:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # status = 0 视为禁用
    if row.get("status") == 0:
        raise HTTPException(status_code=403, detail="账号已禁用，请联系管理员")

    stored = row.get("password") or ""
    # 兼容两种存储：SHA256 哈希或历史明文
    # 历史自动创建的账号密码为空：不允许登录（否则任意密码都能拿到令牌），需由管理员重置密码
    if not stored or (stored != _hash(password) and stored != password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token, expires_at = create_token(row["id"], row["role"])
    return {**_profile(row), "token": token, "expires_at": expires_at}


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user)):
    """当前登录用户（按令牌重新查库，房屋绑定变更后前端可据此刷新）."""
    return _profile({"id": user.id, "username": user.username, "real_name": user.real_name, "role": user.role})


def _profile(row: dict) -> dict:
    # 住户返回名下房屋（user_house 表），前端据此限定可访问的住户；其他角色为空列表
    houses = list_bindings(row["id"]) if row["role"] == "RESIDENT" else []
    return {
        "id": row["id"],
        "username": row["username"],
        "real_name": row["real_name"],
        "role": row["role"],
        "houses": houses,
        "house_ids": [h["house_code"] for h in houses],
    }
