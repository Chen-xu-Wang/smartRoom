"""房屋数字档案服务 —— 「一房一码」档案的读取入口.

数据来源分两部分（v1 设计）：
    1. MySQL 数据库（业务数据，会不断变化）
       - house        房屋基础档案
       - house_device 房屋设备清单
       - repair_order 维修历史（已完成工单即维修记录）
    2. 本地 JSON（静态描述性档案，基本不变）
       - house_profiles.json：户型、楼层、MiC 模块号、管线布局等

为什么这样拆：
    房屋/设备/工单是要持续读写、多方共享的业务数据，放数据库；
    管线布局这类「出厂即固定」的描述信息放文件即可，没必要建表。
    （后续若需要，也可以在 MySQL 加表，本模块改几个查询就行。）
"""
import json
from ..config import HOUSE_PROFILES_FILE
from ..database import query_one, query_all, parse_json_field

# ------------------------------------------------------------------
# 本地静态档案（进程内缓存，避免每次请求都读文件）
# ------------------------------------------------------------------
_profiles_cache = None


def _load_profiles() -> dict:
    """读取静态档案补充信息（含户型、管线布局等）."""
    global _profiles_cache
    if _profiles_cache is None:
        try:
            with open(HOUSE_PROFILES_FILE, "r", encoding="utf-8") as f:
                _profiles_cache = json.load(f)
        except FileNotFoundError:
            # 文件不存在时返回空字典（比如还没跑过 init_database.py）
            _profiles_cache = {}
    return _profiles_cache


# ------------------------------------------------------------------
# 内部工具：按房屋编号（house_code，如 "1302"）查 house 表
# ------------------------------------------------------------------
def _find_house_row(house_code: str):
    """按房屋编号查询 house 表原始行；查不到返回 None."""
    return query_one("SELECT * FROM house WHERE house_code = %s", (house_code,))


def _build_house_dict(row: dict) -> dict:
    """把 house 表的一行 + 静态档案组装成前端/Agent 习惯的字典结构.

    兼容说明：字典里同时保留了旧字段名（houseId/building/room/qrCode）
    和新字段名（house_code/building_no/room_no/qr_token），
    这样 agent.py 和前端页面都不用改。
    """
    code = row["house_code"]
    profile = _load_profiles().get(code, {})
    return {
        # ---------- 来自 MySQL house 表 ----------
        "id": row["id"],                    # 数据库自增主键（数字）
        "houseId": code,                    # 旧字段名兼容：房屋编号
        "house_code": code,                 # 新字段名：房屋编号
        "building": row["building_no"],     # 旧字段名兼容：楼栋
        "building_no": row["building_no"],
        "unit": row.get("unit_no"),
        "room": row["room_no"],             # 旧字段名兼容：房号
        "room_no": row["room_no"],
        "qrCode": row["qr_token"],          # 旧字段名兼容：一房一码
        "qr_token": row["qr_token"],
        "area": row.get("area"),
        "status": row.get("status"),
        # ---------- 来自静态档案 JSON ----------
        "floor": profile.get("floor"),
        "layout": profile.get("layout"),
        "micModuleId": profile.get("micModuleId"),
        "productionDate": profile.get("productionDate"),
        "deliveryDate": profile.get("deliveryDate"),
        "digitalId": profile.get("digitalId"),
        "warranty": profile.get("warranty"),
        "pipelineLayout": profile.get("pipelineLayout", {}),
    }


# ------------------------------------------------------------------
# 对外查询接口（houses API 和 AI Agent 都调用这些函数）
# ------------------------------------------------------------------
def get_all_houses() -> list:
    """房屋列表（首页展示用）."""
    rows = query_all("SELECT * FROM house WHERE status = 1 ORDER BY id")
    return [_build_house_dict(r) for r in rows]


def get_house_by_id(house_code: str):
    """按房屋编号获取完整数字档案（含静态档案信息）."""
    row = _find_house_row(house_code)
    return _build_house_dict(row) if row else None


def get_house_by_qr(qr_code: str):
    """按一房一码（二维码标识）查房屋 —— 扫码进入的入口."""
    row = query_one("SELECT * FROM house WHERE qr_token = %s", (qr_code,))
    return _build_house_dict(row) if row else None


# 设备类型中文名映射（数据库存英文分类，展示时转中文）
DEVICE_TYPE_NAMES = {
    "plumbing": "给排水",
    "electrical": "电气",
    "hvac": "暖通空调",
    "bathroom": "卫浴",
    "doors_windows": "门窗",
}


def _device_row_to_dict(row: dict) -> dict:
    """把 house_device 表的一行转成前端/Agent 习惯的设备字典."""
    return {
        "id": row["id"],                    # 数据库自增主键（数字）
        "device_code": row["device_code"],
        "name": row["device_name"],         # 旧字段名兼容：设备名称
        "device_name": row["device_name"],
        "category": row.get("device_type"),  # 旧字段名兼容：分类
        "device_type": row.get("device_type"),
        "categoryName": DEVICE_TYPE_NAMES.get(row.get("device_type"), "其他"),
        "location": row.get("location"),
        "brand": row.get("brand"),          # 品牌（对应 JSON 里的 manufacturer）
        "manufacturer": row.get("brand"),   # 旧字段名兼容
        "spec": row.get("model"),           # 旧字段名兼容：规格型号
        "model": row.get("model"),
        "installDate": str(row["install_date"]) if row.get("install_date") else None,
        "remark": row.get("remark"),
    }


def _get_house_db_id(house_code: str):
    """房屋编号 → 数据库主键 id；查不到返回 None."""
    row = _find_house_row(house_code)
    return row["id"] if row else None


def get_house_components(house_code: str, category: str = None):
    """获取房屋设备清单，按分类分组.

    返回结构（与旧 JSON 结构一致，前端无需改动）：
        {"plumbing": [设备, ...], "electrical": [...], ...}
    """
    house_id = _get_house_db_id(house_code)
    if house_id is None:
        return None
    rows = query_all(
        "SELECT * FROM house_device WHERE house_id = %s ORDER BY id", (house_id,)
    )
    result = {}
    for r in rows:
        d = _device_row_to_dict(r)
        cat = d["category"] or "other"
        result.setdefault(cat, []).append(d)
    if category:
        return result.get(category, [])
    return result


def get_house_pipeline_layout(house_code: str):
    """获取房屋管线布局（静态档案，来自本地 JSON）."""
    house = get_house_by_id(house_code)
    if not house:
        return None
    return house.get("pipelineLayout", {})


def get_house_equipment_by_location(house_code: str, location_keyword: str) -> list:
    """按区域关键词查设备（供 AI Agent 分析报修时调用）.

    例如 location_keyword = "厨房"，返回所有位置在厨房的设备。
    """
    house_id = _get_house_db_id(house_code)
    if house_id is None:
        return []
    if not location_keyword:
        return []
    # LIKE '%关键词%'：模糊匹配设备的位置或名称字段
    rows = query_all(
        "SELECT * FROM house_device WHERE house_id = %s"
        " AND (location LIKE %s OR device_name LIKE %s) ORDER BY id",
        (house_id, f"%{location_keyword}%", f"%{location_keyword}%"),
    )
    return [_device_row_to_dict(r) for r in rows]


def get_maintenance_history(house_code: str) -> list:
    """获取房屋维修历史（已完成工单 + 维修完成记录）.

    数据来源：repair_order 表中 status=COMPLETED 的工单，
    实际故障原因/处理措施从 repair_record 的 COMPLETE_REPAIR 流水里取。
    """
    house_id = _get_house_db_id(house_code)
    if house_id is None:
        return []
    orders = query_all(
        "SELECT o.id, o.order_no, o.location, o.original_description,"
        "       o.completed_at, u.real_name AS repair_person"
        " FROM repair_order o"
        " LEFT JOIN `user` u ON o.assigned_to = u.id"
        " WHERE o.house_id = %s AND o.status = 'COMPLETED'"
        " ORDER BY o.completed_at DESC",
        (house_id,),
    )
    if not orders:
        return []

    records = []
    for o in orders:
        # 取该工单的「维修完成」流水（里面存了实际故障和措施的 JSON）
        rec = query_one(
            "SELECT description FROM repair_record"
            " WHERE repair_order_id = %s AND action_type = 'COMPLETE_REPAIR'"
            " ORDER BY id DESC LIMIT 1",
            (o["id"],),
        )
        detail = parse_json_field(rec["description"], {}) if rec else {}
        records.append({
            "id": f"MR-{o['order_no']}",                       # 维修记录编号
            "orderId": o["order_no"],                          # 关联工单号
            "date": str(o["completed_at"].date()) if o.get("completed_at") else "",
            "location": o.get("location") or "",
            "fault": o.get("original_description") or "",
            "cause": detail.get("实际故障", ""),
            "action": detail.get("处理措施", ""),
            "repairPerson": detail.get("维修人") or (o.get("repair_person") or ""),
            "result": detail.get("结果", "完成"),
        })
    return records
