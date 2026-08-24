"""工单管理接口 —— 对接 MySQL repair_order 表.

【字段映射说明】
    数据库用的是设计文档里的字段名（如 repair_category、priority），
    前端页面用的是原型期的字段名（如 fault_type、urgency）。
    本模块在「返回响应」时做了一层翻译，前端代码完全不用改。
    对照表：
        数据库 repair_category  ←→  前端 fault_type     （故障类别）
        数据库 priority         ←→  前端 urgency        （优先级，库中存英文）
        数据库 original_description ←→ 前端 user_description（用户原始描述）
        数据库 ai_summary       ←→  前端 ai_analysis    （AI 分析结果）
        数据库 order_no         ←→  前端 id             （工单号当主键用）

【扩展信息的存放】
    AI 置信度（confidence）和建议工种（suggested_trade）在数据库
    设计中没有独立字段，按设计约定存在 repair_message 表的
    AI_SUMMARY 消息里（JSON 格式），本模块负责解析合并。
"""
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import query_one, query_all, execute, parse_json_field
from ..services.archive import get_house_by_id

router = APIRouter(prefix="/api/workorders", tags=["workorders"])

# 优先级：数据库（英文）←→ 前端显示（中文）
PRIORITY_EN2CN = {"URGENT": "紧急", "HIGH": "高", "NORMAL": "中", "LOW": "低"}
PRIORITY_CN2EN = {v: k for k, v in PRIORITY_EN2CN.items()}

# 工单状态：数据库（设计文档定义）←→ 前端（原型期习惯）
STATUS_EN2CN = {
    "DRAFT": "draft",                # 草稿/信息收集中
    "AI_PROCESSING": "draft",        # AI 分析中
    "PENDING_REVIEW": "pending_review",  # 待物业审核
    "PENDING_ASSIGN": "approved",    # 审核通过待派单 → 前端视为「已批准」
    "PROCESSING": "approved",        # 维修处理中 → 前端视为「已批准」
    "COMPLETED": "completed",        # 已完成
    "CANCELLED": "cancelled",        # 已取消
}
# 前端状态参数 → 数据库状态（一个前端状态可能对应多个数据库状态）
STATUS_CN2EN = {
    "draft": ("DRAFT", "AI_PROCESSING"),
    "pending_review": ("PENDING_REVIEW",),
    "approved": ("PENDING_ASSIGN", "PROCESSING"),
    "completed": ("COMPLETED",),
    "cancelled": ("CANCELLED",),
    # 同时兼容直接传数据库原始状态（大写）
    "DRAFT": ("DRAFT",), "AI_PROCESSING": ("AI_PROCESSING",),
    "PENDING_REVIEW": ("PENDING_REVIEW",),
    "PENDING_ASSIGN": ("PENDING_ASSIGN",), "PROCESSING": ("PROCESSING",),
    "COMPLETED": ("COMPLETED",), "CANCELLED": ("CANCELLED",),
}


# ------------------------------------------------------------------
# 内部工具函数
# ------------------------------------------------------------------
def _resolve_user_id(name: str, role: str = "REPAIRER") -> int | None:
    """按姓名查找用户 id；找不到时自动创建（简化演示流程）.

    前端派单输入的是维修师傅姓名（自由文本），数据库需要存用户 id。
    【说明】自动建账号只是演示阶段的简化处理；
    正式版本应做成「从维修人员列表中选择」。
    """
    if not name:
        return None
    row = query_one(
        "SELECT id FROM `user` WHERE real_name = %s ORDER BY id LIMIT 1", (name,)
    )
    if row:
        return row["id"]
    # 没找到 → 自动创建一个该角色的账号（用户名 = 姓名拼音随机后缀）
    username = f"{role.lower()}_{name}_{datetime.now().strftime('%H%M%S')}"
    return execute_return_id(
        "INSERT INTO `user` (username, password, real_name, role, status)"
        " VALUES (%s, %s, %s, %s, 1)",
        (username, "", name, role),
    )


def _get_ai_extras(order_ids: list) -> dict:
    """批量获取工单的 AI 扩展信息（置信度、建议工种）.

    从每张工单最新一条 AI_SUMMARY 消息里解析 JSON。
    一次 IN 查询批量取出，避免逐条查询（N+1 问题，Java 里同理）。
    """
    if not order_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(order_ids))
    rows = query_all(
        f"SELECT repair_order_id, content FROM repair_message"
        f" WHERE message_type = 'AI_SUMMARY' AND repair_order_id IN ({placeholders})"
        f" ORDER BY id ASC",
        tuple(order_ids),
    )
    # 同一张工单可能有多条 AI_SUMMARY（用户修改后重新生成），后面的覆盖前面的
    extras = {}
    for r in rows:
        data = parse_json_field(r["content"], {})
        if data:
            extras[r["repair_order_id"]] = data
    return extras


def _order_row_to_dict(row: dict, extra: dict) -> dict:
    """数据库行 + AI扩展信息 → 前端习惯的工单字典."""
    return {
        # ---- 前端兼容字段（原型期命名）----
        "id": row["order_no"],
        "house_id": row.get("house_code"),
        "house_name": f"{row.get('building_no') or ''}{row.get('room_no') or ''}",
        "location": row.get("location") or "",
        "fault_type": row.get("repair_category") or "",
        "user_description": row.get("original_description") or "",
        "ai_analysis": row.get("ai_summary") or "",
        "suggested_trade": extra.get("suggested_trade", ""),
        "urgency": PRIORITY_EN2CN.get(row.get("priority"), "中"),
        "confidence": extra.get("confidence", 0),
        "status": STATUS_EN2CN.get(row.get("status"), "draft"),
        "assigned_to": row.get("assigned_name") or "",
        "reviewed_by": row.get("reviewer_name") or "",
        "related_equipment": extra.get("related_equipment", []),
        # ---- 数据库原始字段（新页面/后续开发可用）----
        "order_no": row["order_no"],
        "order_db_id": row["id"],
        "priority": row.get("priority"),
        "info_status": row.get("info_status"),
        "raw_status": row.get("status"),
        "device_id": row.get("device_id"),
        "device_description": row.get("device_description"),
        "reviewed_at": str(row["reviewed_at"]) if row.get("reviewed_at") else None,
        "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


# 工单列表基础查询（联表带出房屋编号、维修人姓名、审核人姓名）
_BASE_SELECT = (
    "SELECT o.*, h.house_code, h.building_no, h.room_no,"
    "       ua.real_name AS assigned_name, ur.real_name AS reviewer_name"
    " FROM repair_order o"
    " JOIN house h ON o.house_id = h.id"
    " LEFT JOIN `user` ua ON o.assigned_to = ua.id"
    " LEFT JOIN `user` ur ON o.reviewer_id = ur.id"
)


# ------------------------------------------------------------------
# 请求体定义（≈ Java DTO）
# ------------------------------------------------------------------
class ReviewRequest(BaseModel):
    """物业审核请求."""
    reviewed_by: str                 # 审核人姓名
    urgency: str = None              # 修改后的优先级（中文：紧急/高/中/低）
    suggested_trade: str = None      # 修改后的建议工种
    assigned_to: str = None          # 指派的维修人员姓名
    review_notes: str = None         # 审核备注
    status: str = "approved"         # approved=通过 / rejected=退回


class CompleteRequest(BaseModel):
    """维修完成请求."""
    repair_person: str               # 维修人姓名
    actual_fault: str                # 实际故障原因
    actual_action: str               # 实际处理措施
    used_parts: str = ""             # 使用配件
    result: str = "完成"             # 维修结果


# ------------------------------------------------------------------
# 接口
# ------------------------------------------------------------------
@router.get("")
async def list_workorders(
    status: str = Query(None),
    house_id: str = Query(None),   # 房屋编号（house_code，如 "1302"）
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """工单列表（支持按状态、房屋过滤 + 分页）."""
    where, params = ["1=1"], []
    if status:
        # 前端状态翻译成数据库状态（可能对应多个值，用 IN 查询）
        db_statuses = STATUS_CN2EN.get(status, (status,))
        where.append(f"o.status IN ({', '.join(['%s'] * len(db_statuses))})")
        params.extend(db_statuses)
    if house_id:
        where.append("h.house_code = %s")
        params.append(house_id)

    query = _BASE_SELECT + " WHERE " + " AND ".join(where)
    query += " ORDER BY o.created_at DESC LIMIT %s OFFSET %s"
    params.extend([page_size, (page - 1) * page_size])
    rows = query_all(query, tuple(params))

    # 批量取 AI 扩展信息并组装响应
    extras = _get_ai_extras([r["id"] for r in rows])
    orders = [_order_row_to_dict(r, extras.get(r["id"], {})) for r in rows]
    return {"orders": orders, "page": page, "page_size": page_size}


@router.get("/{order_id}")
async def get_workorder(order_id: str):
    """工单详情（order_id 为工单号 order_no）."""
    row = query_one(_BASE_SELECT + " WHERE o.order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")
    extras = _get_ai_extras([row["id"]]).get(row["id"], {})
    order = _order_row_to_dict(row, extras)

    # 附带对话记录和操作流水，详情页可以展示完整过程
    order["messages"] = query_all(
        "SELECT sender_type, message_type, content, created_at"
        " FROM repair_message WHERE repair_order_id = %s ORDER BY id",
        (row["id"],),
    )
    order["timeline"] = query_all(
        "SELECT operator_type, action_type, before_status, after_status,"
        "       description, created_at"
        " FROM repair_record WHERE repair_order_id = %s ORDER BY id",
        (row["id"],),
    )
    return order


@router.put("/{order_id}/review")
async def review_workorder(order_id: str, req: ReviewRequest):
    """物业审核：通过（可同时改优先级/工种/派单）或退回（要求补充信息）."""
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    reviewer_id = _resolve_user_id(req.reviewed_by, role="PROPERTY")
    now = datetime.now()

    if req.status == "approved":
        # ---------- 审核通过 ----------
        # 指派了维修人 → PENDING_ASSIGN（待接单）；没指派 → 也进 PENDING_ASSIGN
        new_status = "PENDING_ASSIGN"
        assigned_id = _resolve_user_id(req.assigned_to) if req.assigned_to else None

        set_sql = ["status = %s", "reviewer_id = %s", "reviewed_at = %s",
                   "info_status = 'COMPLETE'"]
        set_params = [new_status, reviewer_id, now]
        if req.urgency:
            set_sql.append("priority = %s")
            set_params.append(PRIORITY_CN2EN.get(req.urgency, "NORMAL"))
        if assigned_id:
            set_sql.append("assigned_to = %s")
            set_params.append(assigned_id)
        set_params.append(row["id"])

        execute(
            f"UPDATE repair_order SET {', '.join(set_sql)} WHERE id = %s",
            tuple(set_params),
        )

        # 物业修改了建议工种 → 同步更新 AI_SUMMARY 消息里的 JSON
        if req.suggested_trade:
            _update_ai_summary_field(row["id"], "suggested_trade", req.suggested_trade)

        # 记操作流水
        desc_parts = [f"物业审核通过（审核人：{req.reviewed_by}）"]
        if req.assigned_to:
            desc_parts.append(f"指派维修人：{req.assigned_to}")
        if req.urgency:
            desc_parts.append(f"优先级调整为：{req.urgency}")
        if req.review_notes:
            desc_parts.append(f"备注：{req.review_notes}")
        _add_record(row["id"], "PROPERTY", "APPROVE" if not req.assigned_to else "ASSIGN",
                    row["status"], new_status, "；".join(desc_parts))
    else:
        # ---------- 审核退回：要求用户补充信息 ----------
        execute(
            "UPDATE repair_order SET status = 'DRAFT', info_status = 'INCOMPLETE',"
            " reviewer_id = %s, reviewed_at = %s WHERE id = %s",
            (reviewer_id, now, row["id"]),
        )
        _add_record(
            row["id"], "PROPERTY", "REJECT", row["status"], "DRAFT",
            f"物业退回工单，要求补充信息（审核人：{req.reviewed_by}；"
            f"原因：{req.review_notes or '信息不足'}）",
        )

    return {"success": True, "order_id": order_id, "status": req.status}


@router.put("/{order_id}/complete")
async def complete_workorder(order_id: str, req: CompleteRequest):
    """维修完成：更新工单状态 + 记录实际维修详情.

    【数据回写说明】旧版本维修完成后要把记录回写到 houses.json；
    现在维修历史直接查 repair_order 表，「回写」自动完成——
    这就是数字档案随业务数据持续增长的设计。
    """
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    repairer_id = _resolve_user_id(req.repair_person)
    now = datetime.now()

    execute(
        "UPDATE repair_order SET status = 'COMPLETED', completed_at = %s,"
        " assigned_to = %s WHERE id = %s",
        (now, repairer_id, row["id"]),
    )
    # 实际维修详情存进操作流水（JSON 格式，维修历史查询时会解析它）
    _add_record(
        row["id"], "REPAIRER", "COMPLETE_REPAIR", row["status"], "COMPLETED",
        json.dumps({
            "实际故障": req.actual_fault,
            "处理措施": req.actual_action,
            "使用配件": req.used_parts,
            "维修人": req.repair_person,
            "结果": req.result,
        }, ensure_ascii=False),
    )

    return {
        "success": True,
        "order_id": order_id,
        "message": "维修完成，数据已回写至一房一码数字档案",
    }


@router.get("/stats/summary")
async def get_stats():
    """工单统计（物业看板用）."""
    rows = query_all("SELECT status, priority FROM repair_order")
    by_status, by_urgency = {}, {}
    for r in rows:
        # 数据库状态映射成前端状态后统计
        fe_status = STATUS_EN2CN.get(r["status"], r["status"])
        by_status[fe_status] = by_status.get(fe_status, 0) + 1
        urg = PRIORITY_EN2CN.get(r["priority"], "中")
        by_urgency[urg] = by_urgency.get(urg, 0) + 1

    # 平均置信度：解析所有 AI_SUMMARY 消息求平均
    msg_rows = query_all(
        "SELECT content FROM repair_message WHERE message_type = 'AI_SUMMARY'"
    )
    confidences = []
    for m in msg_rows:
        data = parse_json_field(m["content"], {})
        if isinstance(data.get("confidence"), (int, float)):
            confidences.append(data["confidence"])
    avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0

    return {
        "total": len(rows),
        "by_status": by_status,
        "by_urgency": by_urgency,
        "avg_confidence": avg_conf,
    }


# ------------------------------------------------------------------
# 小工具
# ------------------------------------------------------------------
def _add_record(order_db_id: int, operator_type: str, action_type: str,
                before_status: str, after_status: str, description: str):
    """记一条操作流水到 repair_record."""
    execute(
        "INSERT INTO repair_record (repair_order_id, operator_id, operator_type,"
        " action_type, before_status, after_status, description)"
        " VALUES (%s, NULL, %s, %s, %s, %s, %s)",
        (order_db_id, operator_type, action_type, before_status,
         after_status, description),
    )


def _update_ai_summary_field(order_db_id: int, field: str, value):
    """更新工单最新一条 AI_SUMMARY 消息 JSON 里的某个字段.

    使用场景：物业审核时覆盖 AI 的建议（如修改建议工种），
    修改结果仍然保留在原消息里，方便追溯。
    """
    row = query_one(
        "SELECT id, content FROM repair_message"
        " WHERE repair_order_id = %s AND message_type = 'AI_SUMMARY'"
        " ORDER BY id DESC LIMIT 1",
        (order_db_id,),
    )
    if not row:
        return
    data = parse_json_field(row["content"], {})
    if data:
        data[field] = value
        execute(
            "UPDATE repair_message SET content = %s WHERE id = %s",
            (json.dumps(data, ensure_ascii=False), row["id"]),
        )
