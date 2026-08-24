"""报修对话接口 —— AI 对话 + 持久化到 MySQL.

数据落库设计（对应数据库设计文档的 8 张表）：
    1. 用户发起报修  → repair_order 建一条 DRAFT（草稿）工单
    2. 每轮对话      → repair_message 存一条消息（用户消息 / AI追问 / AI总结）
    3. AI 生成工单   → 更新 repair_order 的 AI 分析字段，
                       同时把完整结构化结果以 JSON 存一条 AI_SUMMARY 消息
                       （置信度、建议工种等扩展信息就存在这条消息里）
    4. 用户确认提交  → 工单状态 DRAFT → PENDING_REVIEW，等待物业审核
    5. 每次状态变化  → repair_record 记一条操作流水（审计用）

为什么 session 里 Agent 还是放在内存里：
    AI Agent 是有状态的（状态机 + 已收集信息），演示版本存内存即可。
    生产环境建议把 Agent 状态序列化后存 Redis（重启不丢失），
    本版本对话消息已全部持久化到 repair_message，重启后至少不丢聊天记录。
"""
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.agent import MaintenanceAgent
from ..services.archive import get_house_by_id
from ..database import query_one, execute, execute_return_id

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 内存会话表（演示用；生产环境换 Redis）
sessions = {}


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------
_default_reporter_cache = None


def get_default_reporter_id() -> int:
    """获取默认报修人（演示账号 resident1 / 张三）.

    【说明】当前系统还没有登录功能，所有报修先记在这个演示住户名下；
    后续接入登录后，这里改成从登录态（token）里取当前用户 id。
    """
    global _default_reporter_cache
    if _default_reporter_cache is None:
        row = query_one("SELECT id FROM `user` WHERE username = 'resident1'")
        _default_reporter_cache = row["id"] if row else 1
    return _default_reporter_cache


# 优先级中文 ↔ 英文对照（数据库存英文，界面显示中文）
PRIORITY_MAP_CN2EN = {"紧急": "URGENT", "高": "HIGH", "中": "NORMAL", "低": "LOW"}
PRIORITY_MAP_EN2CN = {v: k for k, v in PRIORITY_MAP_CN2EN.items()}


def _save_message(order_db_id: int, sender_type: str, message_type: str,
                  content: str, sender_id: int = None):
    """把一条对话消息存入 repair_message 表."""
    execute(
        "INSERT INTO repair_message (repair_order_id, sender_id, sender_type,"
        " message_type, content) VALUES (%s, %s, %s, %s, %s)",
        (order_db_id, sender_id, sender_type, message_type, content),
    )


def _save_record(order_db_id: int, operator_type: str, action_type: str,
                 before_status: str, after_status: str, description: str):
    """把一条操作流水存入 repair_record 表（审计记录）."""
    execute(
        "INSERT INTO repair_record (repair_order_id, operator_id, operator_type,"
        " action_type, before_status, after_status, description)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (order_db_id, None, operator_type, action_type, before_status,
         after_status, description),
    )


def _update_order_with_ai_result(session: dict, response: dict):
    """AI 生成结构化工单后，把分析结果写回 repair_order 表."""
    agent: MaintenanceAgent = session["agent"]
    order = response.get("work_order") or agent.generated_order
    if not order:
        return
    info = agent.extracted_info

    # 设备匹配：AI 找到的关联设备取第一个存 device_id；没有则存文字描述
    device_id = None
    device_description = None
    related = order.get("related_equipment") or []
    if related:
        try:
            device_id = int(related[0])
        except (ValueError, TypeError):
            device_id = None
    if device_id is None:
        device_description = info.get("device") or info.get("location") or ""

    # 置信度 >= 70 视为信息完整，否则标记「待人工确认」
    confidence = order.get("confidence", 0)
    info_status = "COMPLETE" if confidence >= 70 else "MANUAL_CONFIRM"

    execute(
        "UPDATE repair_order SET original_description = %s, ai_summary = %s,"
        " repair_category = %s, location = %s, priority = %s,"
        " info_status = %s, device_id = %s, device_description = %s,"
        " status = 'AI_PROCESSING' WHERE id = %s",
        (
            info.get("raw_description", ""),
            order.get("ai_analysis", ""),
            order.get("fault_type", ""),
            order.get("location", ""),
            PRIORITY_MAP_CN2EN.get(order.get("urgency", "中"), "NORMAL"),
            info_status,
            device_id,
            device_description,
            session["order_db_id"],
        ),
    )

    # 完整结构化结果存为一条 AI_SUMMARY 消息（含置信度、建议工种等扩展字段）
    ai_payload = {
        "confidence": confidence,
        "suggested_trade": order.get("suggested_trade", ""),
        "urgency": order.get("urgency", ""),
        "possible_causes": order.get("possible_causes", []),
        "fault_type": order.get("fault_type", ""),
        "related_equipment": order.get("related_equipment", []),
    }
    _save_message(
        session["order_db_id"], "AI", "AI_SUMMARY",
        json.dumps(ai_payload, ensure_ascii=False),
    )
    # 记一条「AI 生成」操作流水
    _save_record(
        session["order_db_id"], "AI", "AI_GENERATE", "DRAFT", "AI_PROCESSING",
        f"AI 生成结构化工单（置信度 {confidence}%，建议工种：{order.get('suggested_trade', '')}）",
    )


# ------------------------------------------------------------------
# 请求体定义（Pydantic 模型 ≈ Java 里带校验注解的 DTO）
# ------------------------------------------------------------------
class ChatInitRequest(BaseModel):
    house_id: str  # 房屋编号（house_code，如 "1302"）


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


class ChatActionRequest(BaseModel):
    session_id: str
    action: str  # "confirm_order"（确认提交）或 "modify_order"（返回修改）


# ------------------------------------------------------------------
# 接口
# ------------------------------------------------------------------
@router.post("/init")
async def init_chat(req: ChatInitRequest):
    """初始化报修对话：建草稿工单 + 启动 AI Agent."""
    house = get_house_by_id(req.house_id)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")

    # 1. 创建 AI Agent 并加载房屋档案
    agent = MaintenanceAgent()
    agent.init(req.house_id)

    # 2. 创建草稿工单（状态 DRAFT，信息状态 INCOMPLETE）
    order_no = f"WO-{req.house_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    order_db_id = execute_return_id(
        "INSERT INTO repair_order (order_no, reporter_id, house_id,"
        " original_description, priority, info_status, status)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            order_no,
            get_default_reporter_id(),   # 报修人（演示阶段固定为张三）
            house["id"],                 # 数据库房屋主键
            agent.extracted_info.get("raw_description", ""),
            "NORMAL", "INCOMPLETE", "DRAFT",
        ),
    )

    # 3. 会话存内存（Agent 状态机）；工单号关联数据库记录
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "agent": agent,
        "house_id": req.house_id,
        "order_db_id": order_db_id,
        "order_no": order_no,
        "created_at": datetime.now().isoformat(),
    }

    # 4. 欢迎消息落库 + 记一条「创建工单」流水
    first_msg = agent.conversation_history[-1]
    _save_message(order_db_id, "AI", "TEXT", first_msg["content"])
    _save_record(order_db_id, "USER", "CREATE", None, "DRAFT",
                 f"住户发起报修，创建草稿工单 {order_no}")

    return {
        "session_id": session_id,
        "house_id": req.house_id,
        "order_no": order_no,
        "message": first_msg,
        "agent_state": agent.state,
    }


@router.post("/message")
async def send_message(req: ChatMessageRequest):
    """发送消息给 AI Agent，并把对话内容存库."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent: MaintenanceAgent = session["agent"]
    response = agent.process(req.message)

    # 1. 存用户消息
    _save_message(session["order_db_id"], "USER", "TEXT",
                  req.message, sender_id=get_default_reporter_id())

    # 2. 存 AI 回复（根据内容判断消息类型：追问 / 总结 / 普通文本）
    if response.get("missing_info"):
        msg_type = "AI_QUESTION"     # AI 追问补充信息
    elif response.get("work_order"):
        msg_type = "AI_SUMMARY"     # AI 输出结构化分析（下面还会另存一条 JSON 明细）
    else:
        msg_type = "TEXT"
    _save_message(session["order_db_id"], "AI", msg_type, response["content"])

    # 3. 如果 AI 生成了工单，把结构化结果写回工单表
    if response.get("work_order"):
        _update_order_with_ai_result(session, response)

    return response


@router.post("/action")
async def chat_action(req: ChatActionRequest):
    """用户对 AI 生成的工单做确认或修改."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent: MaintenanceAgent = session["agent"]

    if req.action == "confirm_order":
        # ---------- 确认提交：工单进入「待物业审核」----------
        if not agent.generated_order:
            raise HTTPException(status_code=400, detail="No order to confirm")

        order = agent.generated_order
        confidence = order.get("confidence", 0)
        # 置信度不足的工单标记为「待人工确认」，信息完整的直接进入「待物业审核」
        new_info_status = "COMPLETE" if confidence >= 70 else "MANUAL_CONFIRM"

        execute(
            "UPDATE repair_order SET status = 'PENDING_REVIEW', info_status = %s"
            " WHERE id = %s",
            (new_info_status, session["order_db_id"]),
        )
        _save_record(
            session["order_db_id"], "USER", "CREATE", "AI_PROCESSING",
            "PENDING_REVIEW",
            f"住户确认 AI 工单并提交审核（{session['order_no']}，"
            f"置信度 {confidence}%）",
        )

        agent.state = "complete"
        return {
            "success": True,
            "message": "工单已创建，等待物业审核",
            "work_order_id": session["order_no"],
            "work_order": order,
        }

    elif req.action == "modify_order":
        # ---------- 返回修改：Agent 回到信息收集阶段 ----------
        agent.state = "collecting_info"
        _save_record(
            session["order_db_id"], "USER", "REQUEST_MORE_INFO",
            "AI_PROCESSING", "DRAFT", "住户要求修改 AI 生成的工单信息",
        )
        return {
            "success": True,
            "message": "请补充或修改信息",
            "agent_state": agent.state,
        }

    raise HTTPException(status_code=400, detail="Unknown action")


@router.get("/state/{session_id}")
async def get_state(session_id: str):
    """查询当前 Agent 状态（调试用）."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session["agent"].get_state()
