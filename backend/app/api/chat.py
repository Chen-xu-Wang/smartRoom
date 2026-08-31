"""报修对话接口 —— AI 对话 + 持久化到 MySQL.

数据落库设计（对应数据库设计文档的 8 张表）：
    1. 用户发起报修  → repair_order 建一条 DRAFT（草稿）工单
    2. 每轮对话      → repair_message 存一条消息（用户消息 / AI追问 / AI总结）
    3. AI 生成工单   → 更新 repair_order 的 AI 分析字段，
                       同时把完整结构化结果以 JSON 存一条 AI_SUMMARY 消息
                       （置信度、建议工种等扩展信息就存在这条消息里）
    4. 用户确认提交  → 工单状态 DRAFT → PENDING_REVIEW，等待物业审核
    5. 每次状态变化  → repair_record 记一条操作流水（审计用）

会话说明：
    AI Agent 是有状态的（状态机 + 已收集信息），当前会话存内存，
    对话消息已全部持久化到 repair_message，重启后不丢聊天记录。
    未来可将 Agent 状态序列化后存 Redis 实现跨实例持久化。
"""
import json
import os
import uuid
import mimetypes
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..services.agent import MaintenanceAgent
from ..services.archive import get_house_by_id
from ..config import BACKEND_DIR, LLM_API_KEY, LLM_BASE_URL
from ..database import query_one, execute, execute_return_id

# 附件上传目录：backend/uploads/（已在 .gitignore 忽略，不会进仓库）
UPLOAD_DIR = os.path.join(BACKEND_DIR, "uploads")

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 内存会话表（生产环境可替换为 Redis）
sessions = {}


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------
_default_reporter_cache = None


def _resolve_reporter_id(requested: int | None) -> int:
    """解析报修人 ID：优先使用前端传入的登录用户 ID，否则回退到初始住户.

    前端登录后会在 init 时传入 reporter_id（来自 /api/auth/login 返回的 id），
    确保工单真实关联到当前登录人，支持审计与「我的工单」按人过滤。
    未登录或旧客户端未传参时，为兼容仍回退到 resident1。
    """
    if requested:
        row = query_one("SELECT id FROM `user` WHERE id = %s", (requested,))
        if row:
            return row["id"]
    global _default_reporter_cache
    if _default_reporter_cache is None:
        row = query_one("SELECT id FROM `user` WHERE username = 'resident1'")
        _default_reporter_cache = row["id"] if row else 1
    return _default_reporter_cache


def get_default_reporter_id() -> int:
    """兼容旧调用：回退到初始住户."""
    return _resolve_reporter_id(None)


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
    reporter_id: int | None = None  # 真实报修人 user.id（前端登录后传入）


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
    reporter_id = _resolve_reporter_id(req.reporter_id)
    order_no = f"WO-{req.house_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    order_db_id = execute_return_id(
        "INSERT INTO repair_order (order_no, reporter_id, house_id,"
        " original_description, priority, info_status, status)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            order_no,
            reporter_id,
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
    """发送消息给 AI Agent，并把对话内容存库。信息齐全时自动提交工单。"""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent: MaintenanceAgent = session["agent"]
    response = agent.process(req.message)

    # 1. 存用户消息（sender 取工单的 reporter_id，保证真实归属）
    order_row = query_one("SELECT reporter_id, status FROM repair_order WHERE id = %s", (session["order_db_id"],))
    sender_id = order_row["reporter_id"] if order_row else get_default_reporter_id()
    _save_message(session["order_db_id"], "USER", "TEXT",
                  req.message, sender_id=sender_id)

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
        # 4. 自动提交：信息齐全后不再等待用户手动确认，直接进入待审核
        #     避免用户多轮对话后仍需点确认，AI 先给方案并自动建单
        order = response.get("work_order") or agent.generated_order
        if order and order_row and order_row["status"] in ("DRAFT", "AI_PROCESSING"):
            confidence = order.get("confidence", 0)
            new_info_status = "COMPLETE" if confidence >= 70 else "MANUAL_CONFIRM"
            execute(
                "UPDATE repair_order SET status = 'PENDING_REVIEW', info_status = %s WHERE id = %s",
                (new_info_status, session["order_db_id"]),
            )
            _save_record(
                session["order_db_id"], "USER", "CREATE", "AI_PROCESSING",
                "PENDING_REVIEW",
                f"AI 自动提交工单并进入待审核（{session['order_no']}，置信度 {confidence}%）",
            )
            agent.state = "complete"
            response["agent_state"] = "complete"
            response["auto_submitted"] = True
            response["work_order_id"] = session["order_no"]
            # 在内容末尾追加自动提交提示（若 Agent 模板未包含）
            if "已自动提交工单" not in response.get("content", ""):
                response["content"] += f"\n\n✅ 已自动提交工单 `{session['order_no']}`，等待物业审核。"
        else:
            # 已提交过的会话保持完成态
            if agent.state == "complete":
                response["auto_submitted"] = True
                response["work_order_id"] = session["order_no"]

    return response


@router.post("/action")
async def chat_action(req: ChatActionRequest):
    """用户对 AI 生成的工单做确认或修改."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent: MaintenanceAgent = session["agent"]

    if req.action == "confirm_order":
        # ---------- 确认提交：已自动提交的工单直接返回成功（幂等）----------
        row = query_one("SELECT status FROM repair_order WHERE id = %s", (session["order_db_id"],))
        if row and row["status"] in ("PENDING_REVIEW", "PENDING_ASSIGN", "PROCESSING", "COMPLETED"):
            agent.state = "complete"
            return {
                "success": True,
                "message": "工单已自动提交，等待物业审核",
                "work_order_id": session["order_no"],
                "work_order": agent.generated_order,
            }
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


# ------------------------------------------------------------------
# 图片 / 附件上传（A 端职责：文档第 2/9 节点名「当前后端没有任何代码实现」）
# ------------------------------------------------------------------
@router.post("/attachment")
async def upload_attachment(
    repair_order_id: str = Form(...),   # 关联工单号（order_no）
    uploader_id: int = Form(None),     # 上传人 user.id（可选）
    file: UploadFile = File(...),      # 任意文件（图片/视频/文档/音频等均支持）
    attachment_type: str = Form("photo"),  # photo / video / audio / doc / file（自动推断也可）
    ai_description: str = Form(""),    # 多模态模型对文件的理解（可选）
):
    """上传报修附件（支持任意文件类型），落库到 repair_attachment 表.

    【设计说明】
        - 文件保存在 backend/uploads/ 目录，URL 形如 /uploads/xxx.jpg
        - 关联 repair_order（用 order_no 反查 repair_order.id）
        - ai_description 字段预留给多模态模型（图片识别），当前不依赖外部模型，
          由前端/调用方按需写入「现场可见：水槽下方积水」这类辅助描述
        - repair_attachment 表已由 B 端建好（含 ai_description 字段），本接口补齐写入能力

    【联调注意】本接口为 A 端补齐，文档第 8 节「图片附件」项依赖它；
        若联调不需要附件能力，可暂不调用，不影响核心报修流程。
    """
    # 1. 保存文件（防止文件名冲突 + 路径穿越，统一加时间戳前缀）
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{int(datetime.now().timestamp())}_{os.path.basename(file.filename or 'file')}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    file_url = f"/uploads/{safe_name}"

    # 2. 关联工单（order_no → repair_order.id）
    order = query_one(
        "SELECT id FROM repair_order WHERE order_no = %s", (repair_order_id,)
    )
    order_db_id = order["id"] if order else None

    # 3. 写入 repair_attachment 表
    aid = execute_return_id(
        "INSERT INTO repair_attachment (repair_order_id, uploader_id, file_name,"
        " file_url, file_type, attachment_type, ai_description)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            order_db_id,
            uploader_id,
            file.filename or safe_name,
            file_url,
            file.content_type or "",
            attachment_type,
            ai_description,
        ),
    )

    return {
        "success": True,
        "attachment_id": aid,
        "repair_order_id": repair_order_id,
        "file_url": file_url,
        "file_name": file.filename,
        "file_type": file.content_type,
        "attachment_type": attachment_type,
        "ai_description": ai_description,
    }


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """语音转文字（多模态输入）.

    前端优先使用浏览器 Web Speech API（零后端成本）；本接口作为兜底，
    接受任意音频文件（webm/mp3/wav/m4a），保存到 uploads 并尝试调用
    OpenAI 兼容的 /audio/transcriptions。若未配置 LLM 或转写失败，
    返回 422 让前端 fallback 到浏览器识别或提示手动输入。
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"voice_{int(datetime.now().timestamp())}_{os.path.basename(file.filename or 'audio.webm')}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # 尝试远端转写（OpenAI 兼容）
    if LLM_API_KEY and LLM_BASE_URL:
        try:
            import urllib.request
            import urllib.parse
            import json as _json
            # 构造 multipart/form-data
            boundary = "----SmartRoomBoundary" + uuid.uuid4().hex[:8]
            body_parts = []
            # file field
            body_parts.append(f"--{boundary}".encode())
            body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{safe_name}"'.encode())
            ctype = file.content_type or mimetypes.guess_type(save_path)[0] or "audio/webm"
            body_parts.append(f"Content-Type: {ctype}".encode())
            body_parts.append(b"")
            body_parts.append(content)
            # model field
            body_parts.append(f"--{boundary}".encode())
            body_parts.append(b'Content-Disposition: form-data; name="model"')
            body_parts.append(b"")
            # 优先使用 whisper 模型，若未配置则用通用语音模型
            body_parts.append(b"whisper-1")
            body_parts.append(f"--{boundary}--".encode())
            body = b"\r\n".join(body_parts)
            url = LLM_BASE_URL.rstrip("/") + "/audio/transcriptions"
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            req.add_header("Authorization", f"Bearer {LLM_API_KEY}")
            with urllib.request.urlopen(req, timeout=30) as resp:
                obj = _json.loads(resp.read().decode("utf-8"))
                text = obj.get("text") or obj.get("data", {}).get("text") or ""
                if text:
                    return {"success": True, "text": text.strip(), "file_url": f"/uploads/{safe_name}"}
        except Exception as e:
            # 转写失败不抛 500，回退到前端
            return {"success": False, "error": f"远端转写失败: {e}", "file_url": f"/uploads/{safe_name}"}

    # 未配置或失败：返回文件已保存，前端可提示手动输入或用浏览器识别
    return {"success": False, "error": "未配置语音转写服务，请使用浏览器语音或手动输入", "file_url": f"/uploads/{safe_name}"}


@router.get("/state/{session_id}")
async def get_state(session_id: str):
    """查询当前 Agent 状态（调试用）."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session["agent"].get_state()
