"""登录鉴权与数据范围 —— 所有接口的权限入口.

1. 令牌：登录成功后签发 JWT（HS256，标准库实现，不引入额外依赖），前端放在
   ``Authorization: Bearer <token>`` 请求头里。密钥 JWT_SECRET、有效期 JWT_EXPIRE_HOURS 见 .env。
2. 身份：每次请求按令牌里的用户 id 重新查库，账号被禁用、角色变更、房屋改绑都立即生效。
3. 数据范围（与 3D/src/data/access.js 保持一致）：
     物业 / 管理员：全部
     住户：名下房屋（user_house），工单也按房屋判断（系统自动建单的报修人字段不可靠，不按报修人放行）
     维修人员：派给自己的工单，以及这些工单涉及的住户
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from .config import JWT_EXPIRE_HOURS, JWT_SECRET
from .database import query_all, query_one

STAFF_ROLES = ("PROPERTY", "ADMIN")

if JWT_SECRET:
    _SECRET = JWT_SECRET.encode("utf-8")
else:
    # 未配置时每次启动随机生成：可以用，但重启后所有人需要重新登录
    _SECRET = secrets.token_bytes(32)
    print("[安全提示] 未配置 JWT_SECRET，已临时生成随机密钥；后端重启后需重新登录。请在 backend/.env 中设置 JWT_SECRET")


# ------------------------------------------------------------------
# JWT（HS256）
# ------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(user_id: int, role: str, *, now: float | None = None, ttl_hours: float | None = None) -> tuple[str, int]:
    """返回 (令牌, 过期时间戳秒)."""
    now = int(now if now is not None else time.time())
    exp = now + int((ttl_hours if ttl_hours is not None else JWT_EXPIRE_HOURS) * 3600)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": str(user_id), "role": role, "iat": now, "exp": exp}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64(hmac.new(_SECRET, signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}", exp


def decode_token(token: str, *, now: float | None = None) -> dict:
    """校验签名与有效期，失败抛 ValueError."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64(header_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("令牌格式不正确") from exc
    if header.get("alg") != "HS256":
        raise ValueError("不支持的签名算法")
    expected = hmac.new(_SECRET, f"{header_b64}.{payload_b64}".encode("ascii"), hashlib.sha256).digest()
    try:
        signature = _unb64(signature_b64)
    except ValueError as exc:
        raise ValueError("令牌签名不正确") from exc
    if not hmac.compare_digest(expected, signature):
        raise ValueError("令牌签名不正确")
    payload = json.loads(_unb64(payload_b64))
    if int(payload.get("exp", 0)) <= int(now if now is not None else time.time()):
        raise ValueError("登录已过期")
    return payload


def opaque_id(kind: str, value: str) -> str:
    """对不该暴露的编号（如含邻居户号的事件号）生成稳定的不透明别名."""
    digest = hmac.new(_SECRET, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{kind.upper()}-{digest}"


# ------------------------------------------------------------------
# 当前用户
# ------------------------------------------------------------------
@dataclass
class CurrentUser:
    id: int
    username: str
    real_name: str
    role: str
    house_codes: list[str] = field(default_factory=list)  # 住户名下房屋

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_resident(self) -> bool:
        return self.role == "RESIDENT"

    @property
    def is_repairer(self) -> bool:
        return self.role == "REPAIRER"


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def load_user(user_id: int) -> CurrentUser | None:
    row = query_one("SELECT id, username, real_name, role, status FROM `user` WHERE id = %s", (user_id,))
    if not row or row.get("status") == 0:
        return None
    from .services.user_house import house_codes_of  # 避免循环导入
    return CurrentUser(
        id=row["id"], username=row["username"], real_name=row["real_name"] or row["username"], role=row["role"],
        house_codes=house_codes_of(row["id"]) if row["role"] == "RESIDENT" else [],
    )


def current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("请先登录")
    try:
        payload = decode_token(token.strip())
    except ValueError as exc:
        raise _unauthorized(str(exc)) from exc
    user = load_user(int(payload["sub"]))
    if not user:
        raise _unauthorized("账号不存在或已被禁用")
    request.state.user = user
    return user


def require_roles(*roles: str):
    """路由依赖：限定角色，如 ``Depends(require_roles("PROPERTY", "ADMIN"))``."""
    def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="当前账号无权执行该操作")
        return user
    return checker


require_staff = require_roles(*STAFF_ROLES)


# ------------------------------------------------------------------
# 数据范围
# ------------------------------------------------------------------
def repairer_house_codes(user_id: int) -> list[str]:
    rows = query_all(
        "SELECT DISTINCT h.house_code FROM repair_order o JOIN house h ON o.house_id = h.id WHERE o.assigned_to = %s",
        (user_id,),
    )
    return [r["house_code"] for r in rows]


def visible_house_codes(user: CurrentUser) -> list[str] | None:
    """可访问的房号；None 表示不限."""
    if user.is_staff:
        return None
    if user.is_resident:
        return list(user.house_codes)
    if user.is_repairer:
        return repairer_house_codes(user.id)
    return []


def ensure_house_access(user: CurrentUser, house_code: str) -> None:
    scope = visible_house_codes(user)
    if scope is None or str(house_code) in scope:
        return
    if user.is_resident:
        raise HTTPException(status_code=403, detail="该房屋不属于您")
    raise HTTPException(status_code=403, detail="只能查看您工单涉及的住户")


def can_access_order(user: CurrentUser, order_row: dict) -> bool:
    """order_row 需含 reporter_id、assigned_to、house_code."""
    if user.is_staff:
        return True
    if user.is_repairer:
        return order_row.get("assigned_to") == user.id
    if user.is_resident:
        return order_row.get("house_code") in user.house_codes
    return False


def ensure_order_access(user: CurrentUser, order_no: str) -> dict:
    row = query_one(
        "SELECT o.id, o.order_no, o.reporter_id, o.assigned_to, o.status, h.house_code"
        " FROM repair_order o LEFT JOIN house h ON o.house_id = h.id WHERE o.order_no = %s",
        (order_no,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")
    if not can_access_order(user, row):
        raise HTTPException(status_code=403, detail="无权查看该工单")
    return row
