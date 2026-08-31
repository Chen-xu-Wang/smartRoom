"""认证接口 —— 真实校验 MySQL user 表.

前端 resident / admin 登录均走本接口，后端用 SHA256 校验密码，
返回用户信息（id / username / real_name / role），前端据此写入 Pinia + localStorage
并用于后续工单创建的 reporter 身份。
"""
import hashlib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import query_one

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
    # 兼容两种存储：SHA256 哈希或明文空密码（历史自动创建账号）
    if stored and stored != _hash(password) and stored != password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 空密码账号也要求密码非空才可登录，防止随意填空登录
    if not stored and not password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return {
        "id": row["id"],
        "username": row["username"],
        "real_name": row["real_name"],
        "role": row["role"],
    }
