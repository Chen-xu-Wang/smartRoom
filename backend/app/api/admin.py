"""管理后台接口 —— 房屋与维修工/用户管理."""
import hashlib
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..config import HOUSE_PROFILES_FILE
from ..database import query_all, query_one, execute, execute_return_id
from ..services.archive import get_all_houses

router = APIRouter(prefix="/api/admin", tags=["admin"])

def _hash(p): return hashlib.sha256(p.encode()).hexdigest()

# ---------- Houses ----------
class HouseCreate(BaseModel):
    house_code: str
    building_no: str
    unit_no: str | None = None
    room_no: str
    qr_token: str | None = None
    area: float | None = None
    floor: str | None = None
    layout: str | None = None
    micModuleId: str | None = None
    digitalId: str | None = None
    deliveryDate: str | None = None

class HouseUpdate(BaseModel):
    building_no: str | None = None
    unit_no: str | None = None
    room_no: str | None = None
    qr_token: str | None = None
    area: float | None = None
    floor: str | None = None
    layout: str | None = None
    micModuleId: str | None = None
    digitalId: str | None = None
    deliveryDate: str | None = None

def _update_profile(house_code, data: dict):
    try:
        with open(HOUSE_PROFILES_FILE, "r", encoding="utf-8") as f:
            profiles = json.load(f)
    except: profiles = {}
    p = profiles.get(house_code, {})
    for k in ["floor","layout","micModuleId","digitalId","deliveryDate"]:
        if data.get(k) is not None: p[k]=data[k]
    profiles[house_code]=p
    with open(HOUSE_PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)

@router.get("/houses")
async def admin_list_houses():
    return {"houses": get_all_houses()}

@router.post("/houses")
async def admin_create_house(req: HouseCreate):
    exists = query_one("SELECT id FROM house WHERE house_code=%s", (req.house_code,))
    if exists: raise HTTPException(400, "房屋编号已存在")
    qr = req.qr_token or f"HOUSE-{req.house_code}"
    hid = execute_return_id(
        "INSERT INTO house (house_code, building_no, unit_no, room_no, qr_token, area, status) VALUES (%s,%s,%s,%s,%s,%s,1)",
        (req.house_code, req.building_no, req.unit_no, req.room_no, qr, req.area))
    _update_profile(req.house_code, req.model_dump())
    return {"success": True, "id": hid, "house_code": req.house_code}

@router.put("/houses/{house_code}")
async def admin_update_house(house_code: str, req: HouseUpdate):
    row = query_one("SELECT id FROM house WHERE house_code=%s", (house_code,))
    if not row: raise HTTPException(404, "房屋不存在")
    fields, params = [], []
    for col, val in [("building_no", req.building_no),("unit_no", req.unit_no),("room_no", req.room_no),("qr_token", req.qr_token),("area", req.area)]:
        if val is not None:
            fields.append(f"{col}=%s"); params.append(val)
    if fields:
        params.append(house_code)
        execute(f"UPDATE house SET {', '.join(fields)} WHERE house_code=%s", tuple(params))
    _update_profile(house_code, req.model_dump(exclude_none=True))
    # 清空 archive 缓存
    from ..services.archive import _profiles_cache
    import app.services.archive as arch
    arch._profiles_cache = None
    return {"success": True}

@router.delete("/houses/{house_code}")
async def admin_delete_house(house_code: str):
    row = query_one("SELECT id FROM house WHERE house_code=%s", (house_code,))
    if not row: raise HTTPException(404, "房屋不存在")
    # 检查是否有未完成工单
    cnt = query_one("SELECT COUNT(*) c FROM repair_order WHERE house_id=%s AND status!='COMPLETED'", (row["id"],))
    if cnt and cnt["c"]>0: raise HTTPException(400, "该房屋存在未完成工单，无法删除")
    execute("DELETE FROM house_device WHERE house_id=%s", (row["id"],))
    execute("DELETE FROM house WHERE id=%s", (row["id"],))
    try:
        with open(HOUSE_PROFILES_FILE,"r",encoding="utf-8") as f: profiles=json.load(f)
        profiles.pop(house_code,None)
        with open(HOUSE_PROFILES_FILE,"w",encoding="utf-8") as f: json.dump(profiles,f,ensure_ascii=False,indent=2)
        import app.services.archive as arch; arch._profiles_cache=None
    except: pass
    return {"success": True}

# ---------- Users / Repairers ----------
class UserCreate(BaseModel):
    username: str
    password: str = "123456"
    real_name: str
    phone: str | None = None
    role: str = "REPAIRER"  # REPAIRER / PROPERTY / RESIDENT / ADMIN
    skills: list[str] | None = None
    max_active_orders: int | None = 3
    daily_capacity: int | None = 5

class UserUpdate(BaseModel):
    real_name: str | None = None
    phone: str | None = None
    role: str | None = None
    status: int | None = None
    password: str | None = None
    skills: list[str] | None = None
    max_active_orders: int | None = None
    daily_capacity: int | None = None
    on_duty: int | None = None

@router.get("/users")
async def admin_list_users(role: str = Query(None)):
    if role:
        rows = query_all("SELECT id, username, real_name, phone, role, status, created_at FROM `user` WHERE role=%s ORDER BY id", (role.upper(),))
    else:
        rows = query_all("SELECT id, username, real_name, phone, role, status, created_at FROM `user` ORDER BY id")
    # 附带画像
    for r in rows:
        prof = query_one("SELECT skills, max_active_orders, daily_capacity, on_duty FROM repairer_profile WHERE user_id=%s", (r["id"],))
        if prof:
            try: r["skills"]=json.loads(prof["skills"])
            except: r["skills"]=[]
            r["max_active_orders"]=prof["max_active_orders"]; r["daily_capacity"]=prof["daily_capacity"]; r["on_duty"]=prof["on_duty"]
        else:
            r["skills"]=[]; r["max_active_orders"]=3; r["daily_capacity"]=5; r["on_duty"]=1
        r["created_at"]=str(r["created_at"]) if r["created_at"] else None
    return {"users": rows}

@router.post("/users")
async def admin_create_user(req: UserCreate):
    if query_one("SELECT id FROM `user` WHERE username=%s", (req.username,)):
        raise HTTPException(400, "用户名已存在")
    role = req.role.upper()
    if role not in ("RESIDENT","PROPERTY","REPAIRER","ADMIN"): raise HTTPException(400, "角色不合法")
    uid = execute_return_id(
        "INSERT INTO `user` (username,password,real_name,phone,role,status) VALUES (%s,%s,%s,%s,%s,1)",
        (req.username, _hash(req.password), req.real_name, req.phone, role))
    if role=="REPAIRER":
        skills = req.skills or ["综合维修"]
        execute("INSERT INTO repairer_profile (user_id, skills, max_active_orders, daily_capacity, on_duty) VALUES (%s,%s,%s,%s,1)",
                (uid, json.dumps(skills, ensure_ascii=False), req.max_active_orders or 3, req.daily_capacity or 5))
    return {"success": True, "id": uid}

@router.put("/users/{user_id}")
async def admin_update_user(user_id: int, req: UserUpdate):
    row = query_one("SELECT * FROM `user` WHERE id=%s", (user_id,))
    if not row: raise HTTPException(404, "用户不存在")
    if req.real_name is not None: execute("UPDATE `user` SET real_name=%s WHERE id=%s", (req.real_name, user_id))
    if req.phone is not None: execute("UPDATE `user` SET phone=%s WHERE id=%s", (req.phone, user_id))
    if req.role is not None: execute("UPDATE `user` SET role=%s WHERE id=%s", (req.role.upper(), user_id))
    if req.status is not None: execute("UPDATE `user` SET status=%s WHERE id=%s", (req.status, user_id))
    if req.password: execute("UPDATE `user` SET password=%s WHERE id=%s", (_hash(req.password), user_id))
    # 画像
    if any(v is not None for v in [req.skills, req.max_active_orders, req.daily_capacity, req.on_duty]):
        prof = query_one("SELECT user_id FROM repairer_profile WHERE user_id=%s", (user_id,))
        if not prof:
            execute("INSERT INTO repairer_profile (user_id, skills, max_active_orders, daily_capacity, on_duty) VALUES (%s,%s,%s,%s,%s)",
                    (user_id, json.dumps(req.skills or ["综合维修"], ensure_ascii=False), req.max_active_orders or 3, req.daily_capacity or 5, req.on_duty if req.on_duty is not None else 1))
        else:
            if req.skills is not None: execute("UPDATE repairer_profile SET skills=%s WHERE user_id=%s", (json.dumps(req.skills, ensure_ascii=False), user_id))
            if req.max_active_orders is not None: execute("UPDATE repairer_profile SET max_active_orders=%s WHERE user_id=%s", (req.max_active_orders, user_id))
            if req.daily_capacity is not None: execute("UPDATE repairer_profile SET daily_capacity=%s WHERE user_id=%s", (req.daily_capacity, user_id))
            if req.on_duty is not None: execute("UPDATE repairer_profile SET on_duty=%s WHERE user_id=%s", (req.on_duty, user_id))
    return {"success": True}

@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: int):
    row = query_one("SELECT role FROM `user` WHERE id=%s", (user_id,))
    if not row: raise HTTPException(404, "用户不存在")
    # 维修工若有在途工单不允许删
    if row["role"]=="REPAIRER":
        cnt = query_one("SELECT COUNT(*) c FROM repair_order WHERE assigned_to=%s AND status IN ('PENDING_ASSIGN','PROCESSING')", (user_id,))
        if cnt and cnt["c"]>0: raise HTTPException(400, "该维修工存在在途工单，无法删除")
    execute("DELETE FROM repairer_profile WHERE user_id=%s", (user_id,))
    execute("DELETE FROM `user` WHERE id=%s", (user_id,))
    return {"success": True}
