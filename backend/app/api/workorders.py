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

from ..database import query_one, query_all, execute, execute_return_id, parse_json_field
from ..services.archive import get_house_by_id

router = APIRouter(prefix="/api/workorders", tags=["workorders"])

# 优先级：数据库（英文）←→ 前端显示（中文）
PRIORITY_EN2CN = {"URGENT": "紧急", "HIGH": "高", "NORMAL": "中", "LOW": "低"}
PRIORITY_CN2EN = {v: k for k, v in PRIORITY_EN2CN.items()}

# 工单状态：数据库（设计文档定义）←→ 前端（原型期习惯）
# 【阶段5.4拆分说明】
#   原设计把 PENDING_ASSIGN 和 PROCESSING 都映射为 approved（前端视为「已批准」），
#   导致前端无法区分「待派单/已派单待开始」和「维修中」。
#   现拆分为 pending_assign / processing 两个独立状态。
STATUS_EN2CN = {
    "DRAFT": "draft",                # 草稿/信息收集中
    "AI_PROCESSING": "draft",        # AI 分析中
    "PENDING_REVIEW": "pending_review",  # 待物业审核
    "PENDING_ASSIGN": "pending_assign",  # 审核通过待派单 / 已派单待开始维修（与 PROCESSING 拆分）
    "PROCESSING": "processing",      # 维修处理中（与 PENDING_ASSIGN 拆分）
    "COMPLETED": "completed",        # 已完成
    "CANCELLED": "cancelled",        # 已取消
}
# 前端状态参数 → 数据库状态（一个前端状态可能对应多个数据库状态）
# 【阶段5.4说明】approved 仅保留为「旧前端筛选入参」的兼容别名
# （= 待处理 = 已派单 + 维修中），后端输出不再使用它。
STATUS_CN2EN = {
    "draft": ("DRAFT", "AI_PROCESSING"),
    "pending_review": ("PENDING_REVIEW",),
    "pending_assign": ("PENDING_ASSIGN",),
    "processing": ("PROCESSING",),
    "completed": ("COMPLETED",),
    "cancelled": ("CANCELLED",),
    # 兼容别名：旧页面仍传 approved 作「待处理」筛选，语义=已派单+维修中
    "approved": ("PENDING_ASSIGN", "PROCESSING"),
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
    """按姓名查找用户 id；找不到时自动创建（仅限少量演示场景）.

    【阶段5.6/5.9后的使用范围（已收窄到只剩审核人）】
        - review 的审核人（reviewed_by → role="PROPERTY"）
        （派单 assign / 开始维修 start / 完成维修 complete 均已改用
         只读的 _find_user_id，禁止输入一个名字就自动建号）
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


def _find_user_id(name: str, role: str = "REPAIRER") -> int | None:
    """只读查找用户 id，找不到（或角色不匹配）返回 None（绝不自动创建）.

    【与 _resolve_user_id 的区别】
        - _resolve_user_id：找不到就 INSERT 一个新账号
        - _find_user_id：只 SELECT，不写库

    【阶段5.6起的使用范围】
        - 派单（assign / review 带 assigned_to）：校验维修人必须是在册 REPAIRER
        - 开始维修（start）：校验发起人 = 派单维修人
        一律不允许「输入一个名字就自动建号」。

    【Java 类比】
        相当于 Repository 层的 findByRealNameAndRole 只读查询，
        调用方决定查不到时怎么处理（抛 400 或拒绝）。
    """
    if not name:
        return None
    row = query_one(
        "SELECT id FROM `user` WHERE real_name = %s AND role = %s"
        " ORDER BY id LIMIT 1",
        (name, role),
    )
    return row["id"] if row else None


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
# 维修结果解析（阶段5.9：B1 维修结果无法显示）
# ------------------------------------------------------------------
def _parse_complete_description(description: str) -> dict:
    """把一条 COMPLETE_REPAIR 流水的 description（中文键 JSON）解析成前端字段.

    【JSON 键来源】complete_workorder 写入时用的是中文键：
        {"实际故障": ..., "处理措施": ..., "使用配件": ..., "维修人": ..., "结果": ...}
    这里统一翻译成前端模板用的命名字段
    （actual_fault / actual_action / used_parts / result / repair_person），
    RepairTasks 已完成卡片和 WorkOrderDetail 详情页直接读取。

    【解析失败 / 空内容】返回空 dict，调用方按「无维修结果」处理（前端 v-if 不显示）。

    【Java 类比】相当于把流水里的 JSON 反序列化成 DTO 的 ObjectMapper.readValue。
    """
    data = parse_json_field(description, {})
    if not data:
        return {}
    return {
        "actual_fault": data.get("实际故障", ""),
        "actual_action": data.get("处理措施", ""),
        "used_parts": data.get("使用配件", ""),
        "result": data.get("结果", ""),
        "repair_person": data.get("维修人", ""),
    }


def _get_complete_results(order_db_ids: list) -> dict:
    """批量获取工单的维修结果（从 COMPLETE_REPAIR 流水解析）.

    【为什么批量】列表接口一次可能返回多张工单，如果每张工单单独
    查一次 repair_record 就是 N+1 查询（Java 里同理要避免）。
    这里一次 IN 查询取出全部相关流水，在内存里按 repair_order_id 分组。

    【同一工单多条 COMPLETE_REPAIR】只保留最后一条（id 大的覆盖小的）：
    演示数据/历史数据可能存在重复完成记录，业务上以最近一次为准。

    【Java 类比】相当于 Repository 层按 orderIds IN 批量查询完工记录，
    再 Map<orderId, result> 内存聚合，避免循环查库。

    【返回】{ repair_order_id(int): {actual_fault, actual_action,
            used_parts, result, repair_person}, ... }
    """
    if not order_db_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(order_db_ids))
    rows = query_all(
        f"SELECT repair_order_id, description FROM repair_record"
        f" WHERE action_type = 'COMPLETE_REPAIR'"
        f" AND repair_order_id IN ({placeholders}) ORDER BY id ASC",
        tuple(order_db_ids),
    )
    results = {}
    for r in rows:
        data = _parse_complete_description(r["description"])
        if data:
            results[r["repair_order_id"]] = data
    return results


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


class AssignRequest(BaseModel):
    """独立派单请求.

    【设计说明】
        派单和审核是两个独立的业务动作：
        - 审核通过后，工单进入 PENDING_ASSIGN 状态，此时不一定立刻派单；
        - 物业可以在后续任意时间点调用本接口，指定维修人员。
        - 派单后状态不变（仍为 PENDING_ASSIGN），仅 assigned_to 字段被填充，
          语义为「已派单、待开始维修」。

    【Java 类比】
        相当于 Spring Boot 中单独拆出一个 AssignController，
        而不是把 assign 逻辑塞在 ApproveController 里。
    """
    assigned_to: str                 # 维修人员姓名（必须是在册 REPAIRER，否则 400）
    assigned_by: str = None          # 操作人姓名（记流水用，可选）


class StartRepairRequest(BaseModel):
    """开始维修请求.

    【设计说明】
        开始维修是维修师傅在接到派单后发起的动作：
        - 工单必须先派单（assigned_to 非空），否则不能开始维修；
        - repair_person 可选：传了则校验「发起人 = 派单维修人」，
          防止工单派给 A 却由 B 开始维修；
        - 本接口只做只读校验，绝不自动创建维修人账号
          （与派单/审核一样，统一使用只读的 _find_user_id）。

    【Java 类比】
        相当于 Service 层校验 @NotNull(assigned_to) + 身份比对，
        不引入额外依赖。
    """
    repair_person: str = None        # 可选：发起开始维修的维修人姓名（只校验，不建号）


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
    # 【阶段5.11：B2 已驳回筛选查不到数据】
    # rejected 不是一个数据库状态，而是「组合条件」：
    #   当前状态为 DRAFT（被退回后仍未重新提交） 且
    #   该工单在 repair_record 里存在 REJECT 流水（确实被物业退回过）。
    # 这样既能把「被物业退回的工单」查出来，又不会把普通未提交草稿
    # （同样可能是 DRAFT，但从未被 REJECT）误判成已驳回。
    # 命中后仅在前端输出层把 status 翻译为 "rejected"，数据库状态保持 DRAFT 不变。
    #
    # 【Java 类比】相当于 Service 层对特殊筛选做单独分支：
    #   WHERE o.status='DRAFT' AND o.id IN (SELECT repair_order_id
    #        FROM repair_record WHERE action_type='REJECT')
    # 类似 JPA 的关联子查询 existsRejectRecord()，而不是简单状态枚举映射。
    is_rejected_filter = False
    if status:
        if status == "rejected":
            is_rejected_filter = True
            where.append(
                "o.status = 'DRAFT' AND o.id IN ("
                " SELECT DISTINCT repair_order_id FROM repair_record"
                " WHERE action_type = 'REJECT')"
            )
        else:
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

    # 批量取 AI 扩展信息 + 维修结果并组装响应
    # 【阶段5.9】维修结果从 COMPLETE_REPAIR 流水一次 IN 批量解析，
    # 不逐条查库（避免 N+1），completed 工单卡片可直接展示。
    extras = _get_ai_extras([r["id"] for r in rows])
    results = _get_complete_results([r["id"] for r in rows])
    orders = []
    for r in rows:
        o = _order_row_to_dict(r, extras.get(r["id"], {}))
        o.update(results.get(r["id"], {}))
        # 阶段5.11：rejected 筛选命中后，输出层把 status 翻译为 "rejected"
        # （数据库状态仍是 DRAFT，仅前端展示为「已驳回」，
        #   与 PropertyDashboard/WorkOrderCard 已预置的 rejected 标签对齐）
        if is_rejected_filter:
            o["status"] = "rejected"
        orders.append(o)
    return {"orders": orders, "page": page, "page_size": page_size}


@router.get("/repairers")
async def list_repairers():
    """维修人员列表（派单下拉用）.

    【数据来源】user 表 role = 'REPAIRER' 的在册用户，只读查询，绝不创建。
    【用途】前端派单时从本接口拉取可选维修人员，禁止自由文本自动建号。
    【返回字段】
        - id        ：user.id，派单时写入 repair_order.assigned_to
        - username  ：登录名（备用，后续登录体系用）
        - real_name ：姓名，下拉展示与后端校验用

    【路由顺序说明】本接口必须声明在 GET /{order_id} 之前，
    否则 "repairers" 会被当作工单号 order_no 匹配（FastAPI 按声明顺序匹配）。

    【Java 类比】相当于 RepairerController.list()，一个只读的字典查询接口。
    """
    rows = query_all(
        "SELECT id, username, real_name FROM `user`"
        " WHERE role = 'REPAIRER' ORDER BY id"
    )
    return {"repairers": rows}


@router.get("/{order_id}")
async def get_workorder(order_id: str):
    """工单详情（order_id 为工单号 order_no）."""
    row = query_one(_BASE_SELECT + " WHERE o.order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")
    extras = _get_ai_extras([row["id"]]).get(row["id"], {})
    order = _order_row_to_dict(row, extras)
    # 阶段5.9：把 COMPLETE_REPAIR 流水里的维修结果解析出来
    # （actual_fault / actual_action / used_parts / result / repair_person），
    # 详情页的「维修结果」区块依赖这些字段。
    order.update(_get_complete_results([row["id"]]).get(row["id"], {}))

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
    """物业审核：通过（可同时改优先级/工种/派单）或退回（要求补充信息）.

    【状态前置校验】只有 PENDING_REVIEW（待物业审核）的工单允许审核。
    防止已审核过 / 已派单 / 已完成的工单被重复审核，
    导致 reviewer_id、reviewed_at 等审核信息被反复覆盖。
    """
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    # ---- 状态前置校验：只有待审核状态才能审核（通过/退回共用此校验）----
    # 【Java 类比】Service 层入口的状态机校验 if-check，
    # 或 Spring StateMachine 的 transition guard
    if row["status"] != "PENDING_REVIEW":
        raise HTTPException(
            status_code=400,
            detail=f"当前工单状态为 {row['status']}，只有 PENDING_REVIEW"
                   f"（待物业审核）状态才能执行审核操作",
        )

    reviewer_id = _resolve_user_id(req.reviewed_by, role="PROPERTY")
    now = datetime.now()

    if req.status == "approved":
        # ---------- 审核通过 ----------
        # 指派了维修人 → PENDING_ASSIGN（待接单）；没指派 → 也进 PENDING_ASSIGN
        new_status = "PENDING_ASSIGN"
        # 【阶段5.6】审核时带的维修人也必须是在册 REPAIRER（与 /assign 同一套校验），
        # 不允许审核时输入一个不存在的名字自动建号
        assigned_id = None
        if req.assigned_to:
            assigned_id = _find_user_id(req.assigned_to, role="REPAIRER")
            if assigned_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"维修人员「{req.assigned_to}」不存在于维修人员名单中，"
                           f"无法在审核时派单（请先通过审核，"
                           f"再调用独立派单接口指定维修人员）",
                )

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


@router.put("/{order_id}/assign")
async def assign_workorder(order_id: str, req: AssignRequest):
    """独立派单：为已审核通过但尚未派单的工单指定维修人员.

    【业务规则】
        1. 只有 PENDING_ASSIGN 状态的工单允许派单
           （审核已通过，还没指定维修人，或者需要改派维修人）
        2. 派单后工单状态不变，仍为 PENDING_ASSIGN
           语义：「已派单、待开始维修」
           （后续阶段5.2+ 会引入「开始维修」动作，届时状态才推进到 PROCESSING）
        3. 允许改派：如果工单已有 assigned_to，再次调用会覆盖
        4. 【阶段5.6】维修人员必须是 user 表 role='REPAIRER' 的在册用户，
           不允许自由输入不存在的名字（禁止自动建号），查不到返回 400

    【为什么不在 review 接口里做】
        审核和派单是两个独立的业务决策：
        - 审核是「物业确认这个报修合理，同意维修」
        - 派单是「物业决定派哪个师傅去修」
        实际工作中这两个动作可能间隔几小时甚至几天，
        放在一个接口里会导致审核信息被反复覆盖。

    【Java 类比】
        相当于把 ApproveServiceImpl 里的 assign 逻辑
        拆成一个独立的 AssignServiceImpl，各司其职。
    """
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    # ---- 状态前置校验 ----
    # 只有 PENDING_ASSIGN 允许派单，其他状态拒绝
    # （对应 Java 中 @PreAuthorize 或 service 层 if-check）
    if row["status"] != "PENDING_ASSIGN":
        raise HTTPException(
            status_code=400,
            detail=f"当前工单状态为 {row['status']}，只有 PENDING_ASSIGN（已审核通过待派单）"
                   f"状态才能派单",
        )

    # ---- 校验维修人员：必须是 user 表中在册的 REPAIRER ----
    # 【阶段5.6】不再自动建号：找不到 → 400，提示从维修人员列表中选择
    assigned_id = _find_user_id(req.assigned_to, role="REPAIRER")
    if assigned_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"维修人员「{req.assigned_to}」不存在于维修人员名单中，"
                   f"无法派单（请调用 GET /api/workorders/repairers 获取可选维修人员）",
        )

    # ---- 更新工单 assigned_to 字段（状态不变）----
    execute(
        "UPDATE repair_order SET assigned_to = %s WHERE id = %s",
        (assigned_id, row["id"]),
    )

    # ---- 记操作流水 ----
    desc_parts = [f"独立派单：维修人 → {req.assigned_to}"]
    if req.assigned_by:
        desc_parts.append(f"操作人：{req.assigned_by}")
    if row.get("assigned_to"):
        desc_parts.append(f"（原维修人已改派）")
    _add_record(
        row["id"], "PROPERTY", "ASSIGN",
        row["status"], row["status"],  # 状态没变，before = after
        "；".join(desc_parts),
    )

    return {
        "success": True,
        "order_id": order_id,
        "assigned_to": req.assigned_to,
        "message": "派单成功，工单等待开始维修",
    }


@router.put("/{order_id}/start")
async def start_workorder(order_id: str, req: StartRepairRequest):
    """开始维修：维修师傅接到派单后开工，状态 PENDING_ASSIGN → PROCESSING.

    【业务规则】
        1. 只有 PENDING_ASSIGN（已审核通过待派单/待开始维修）状态允许开始维修
        2. 工单必须已经派单（assigned_to 非空），未派单不能开工
        3. 请求体可传 repair_person 做身份校验：
           只读查询 user 表，校验该姓名就是本工单指派的维修人
           （查不到或不是指派人都拒绝，且绝不自动建号）
        4. 通过后状态推进到 PROCESSING，并写一条 START_REPAIR 流水

    【action_type 命名说明】
        采用 START_REPAIR，与现有 COMPLETE_REPAIR 形成动词对
        （START ↔ COMPLETE）。数据库 action_type 为 varchar(30)
        无 ENUM/CHECK 约束，可直接新增，不需要改表结构。

    【Java 类比】
        相当于 RepairService.startRepair()：
        先校验工单状态（@AssertTrue），再校验维修人身份，
        最后 update status + insert 操作日志（一个事务）。
    """
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    # ---- 规则1：状态前置校验 ----
    if row["status"] != "PENDING_ASSIGN":
        raise HTTPException(
            status_code=400,
            detail=f"当前工单状态为 {row['status']}，只有 PENDING_ASSIGN"
                   f"（已派单待开始维修）状态才能开始维修",
        )

    # ---- 规则2：必须已派单 ----
    if not row.get("assigned_to"):
        raise HTTPException(
            status_code=400,
            detail="该工单尚未派单（assigned_to 为空），请先完成派单再开始维修",
        )

    # ---- 规则3：维修人身份校验（可选，只读不建号）----
    assigned_name = None
    if req.repair_person:
        person_id = _find_user_id(req.repair_person)
        if person_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"维修人「{req.repair_person}」不存在于维修人员名单中，"
                       f"无法开始维修（请确认姓名与派单人一致）",
            )
        if person_id != row["assigned_to"]:
            raise HTTPException(
                status_code=400,
                detail=f"该工单已指派给其他维修人，不能由「{req.repair_person}」开始维修",
            )
        assigned_name = req.repair_person
    else:
        # 未传姓名 → 取派单人姓名用于流水展示（联表查一次）
        u = query_one("SELECT real_name FROM `user` WHERE id = %s", (row["assigned_to"],))
        assigned_name = u["real_name"] if u else str(row["assigned_to"])

    # ---- 规则4：状态流转 PENDING_ASSIGN → PROCESSING ----
    execute(
        "UPDATE repair_order SET status = 'PROCESSING' WHERE id = %s",
        (row["id"],),
    )

    # ---- 写操作流水 ----
    _add_record(
        row["id"], "REPAIRER", "START_REPAIR",
        "PENDING_ASSIGN", "PROCESSING",
        f"开始维修（维修人：{assigned_name}）",
    )

    return {
        "success": True,
        "order_id": order_id,
        "status": "PROCESSING",
        "message": "已开始维修，工单状态更新为维修中",
    }


@router.put("/{order_id}/complete")
async def complete_workorder(order_id: str, req: CompleteRequest):
    """维修完成：更新工单状态 + 记录实际维修详情.

    【数据回写说明】旧版本维修完成后要把记录回写到 houses.json；
    现在维修历史直接查 repair_order 表，「回写」自动完成——
    这就是数字档案随业务数据持续增长的设计。

    【状态前置校验】只有 PROCESSING（维修中）的工单允许完成维修。
    即完整链路必须是：审核通过 → 派单 → 开始维修 → 完成维修，
    不允许跳过派单/开工环节直接完成。
    """
    row = query_one("SELECT * FROM repair_order WHERE order_no = %s", (order_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")

    # ---- 状态前置校验：只有维修中的工单才能完成 ----
    # PENDING_ASSIGN（还没开工）/ PENDING_REVIEW（还没审核）/
    # COMPLETED（已完成）等状态一律拒绝
    if row["status"] != "PROCESSING":
        raise HTTPException(
            status_code=400,
            detail=f"当前工单状态为 {row['status']}，只有 PROCESSING（维修中）"
                   f"状态才能完成维修，请先派单并开始维修",
        )

    # ---- 维修人校验（阶段5.9收口：只读校验，禁止自动建号）----
    # 1) 必须是 user 表 role='REPAIRER' 的在册维修人员：查不到 → 400，绝不 INSERT。
    #    （改前这里用 _resolve_user_id，输入任意姓名会自动创建一个新账号）
    repairer_id = _find_user_id(req.repair_person, role="REPAIRER")
    if repairer_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"维修人员「{req.repair_person}」不存在于维修人员名单中，"
                   f"无法完成维修（请确认姓名与派单人一致）",
        )
    # 2) 优先校验：完成人必须就是本工单已指派的维修人。
    #    （PROCESSING 状态必然已派单，assigned_to 非空；
    #      空值分支仅作防御，防止状态机未来变化时漏校验）
    if row["assigned_to"] and repairer_id != row["assigned_to"]:
        raise HTTPException(
            status_code=400,
            detail=f"该工单已指派给其他维修人，不能由「{req.repair_person}」完成维修",
        )

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
