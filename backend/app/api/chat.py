"""Chat API - AI报修对话接口."""
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..services.agent import MaintenanceAgent
from ..database import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory session storage (for demo; use Redis in production)
sessions = {}

class ChatInitRequest(BaseModel):
    house_id: str

class ChatMessageRequest(BaseModel):
    session_id: str
    message: str

class ChatActionRequest(BaseModel):
    session_id: str
    action: str  # "confirm_order" or "modify_order"

@router.post("/init")
async def init_chat(req: ChatInitRequest):
    """Initialize a chat session for a house."""
    session_id = str(uuid.uuid4())[:8]
    agent = MaintenanceAgent()
    agent.init(req.house_id)

    sessions[session_id] = {
        "agent": agent,
        "house_id": req.house_id,
        "created_at": datetime.now().isoformat(),
    }

    # Save to DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO chat_sessions (id, house_id, messages, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, req.house_id, "", datetime.now().isoformat(), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    first_msg = agent.conversation_history[-1]
    return {
        "session_id": session_id,
        "house_id": req.house_id,
        "message": first_msg,
        "agent_state": agent.state,
    }

@router.post("/message")
async def send_message(req: ChatMessageRequest):
    """Send a message to the agent."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = session["agent"]
    response = agent.process(req.message)

    # Update DB
    conn = get_db()
    cursor = conn.cursor()
    import json
    messages_json = json.dumps(agent.conversation_history, ensure_ascii=False, default=str)
    cursor.execute(
        "UPDATE chat_sessions SET messages=?, updated_at=? WHERE id=?",
        (messages_json, datetime.now().isoformat(), req.session_id),
    )
    conn.commit()
    conn.close()

    return response

@router.post("/action")
async def chat_action(req: ChatActionRequest):
    """Handle user actions (confirm/modify order)."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent = session["agent"]

    if req.action == "confirm_order":
        # Confirm the generated order - create it in DB
        if not agent.generated_order:
            raise HTTPException(status_code=400, detail="No order to confirm")

        order = agent.generated_order
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO work_orders
            (id, house_id, location, fault_type, user_description, related_equipment,
             ai_analysis, suggested_trade, urgency, confidence, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order["id"], order["house_id"], order.get("location", ""),
                order.get("fault_type", ""), order.get("user_description", ""),
                ",".join(order.get("related_equipment", [])),
                order.get("ai_analysis", ""), order.get("suggested_trade", ""),
                order.get("urgency", ""), order.get("confidence", 0),
                "pending_review", datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        agent.state = "complete"
        return {
            "success": True,
            "message": "工单已创建，等待物业审核",
            "work_order_id": order["id"],
            "work_order": order,
        }

    elif req.action == "modify_order":
        agent.state = "collecting_info"
        return {
            "success": True,
            "message": "请补充或修改信息",
            "agent_state": agent.state,
        }

    raise HTTPException(status_code=400, detail="Unknown action")

@router.get("/state/{session_id}")
async def get_state(session_id: str):
    """Get current agent state."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session["agent"].get_state()
