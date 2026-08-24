"""Work order API - 工单管理接口."""
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from ..database import get_db
from ..services.archive import add_maintenance_record, get_house_by_id

router = APIRouter(prefix="/api/workorders", tags=["workorders"])

class ReviewRequest(BaseModel):
    reviewed_by: str
    urgency: str = None
    suggested_trade: str = None
    assigned_to: str = None
    review_notes: str = None
    status: str = "approved"  # approved or rejected

class CompleteRequest(BaseModel):
    repair_person: str
    actual_fault: str
    actual_action: str
    used_parts: str = ""
    result: str = "完成"

@router.get("")
async def list_workorders(
    status: str = Query(None),
    house_id: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List work orders with optional filters."""
    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM work_orders WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if house_id:
        query += " AND house_id = ?"
        params.append(house_id)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    orders = []
    for row in rows:
        order = dict(row)
        if order.get("related_equipment"):
            order["related_equipment"] = order["related_equipment"].split(",")
        orders.append(order)
    conn.close()
    return {"orders": orders, "page": page, "page_size": page_size}

@router.get("/{order_id}")
async def get_workorder(order_id: str):
    """Get a specific work order."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Work order not found")
    order = dict(row)
    if order.get("related_equipment"):
        order["related_equipment"] = order["related_equipment"].split(",")
    return order

@router.put("/{order_id}/review")
async def review_workorder(order_id: str, req: ReviewRequest):
    """Property management reviews and approves/modifies a work order."""
    conn = get_db()
    cursor = conn.cursor()

    # Check order exists
    cursor.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Work order not found")

    updates = []
    params = []
    if req.urgency:
        updates.append("urgency = ?")
        params.append(req.urgency)
    if req.suggested_trade:
        updates.append("suggested_trade = ?")
        params.append(req.suggested_trade)
    if req.assigned_to:
        updates.append("assigned_to = ?")
        params.append(req.assigned_to)
    updates.append("reviewed_by = ?")
    params.append(req.reviewed_by)
    updates.append("reviewed_at = ?")
    params.append(datetime.now().isoformat())
    updates.append("review_notes = ?")
    params.append(req.review_notes)
    updates.append("status = ?")
    params.append(req.status if req.status == "approved" else "rejected")

    params.append(order_id)
    query = f"UPDATE work_orders SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    return {"success": True, "order_id": order_id, "status": req.status}

@router.put("/{order_id}/complete")
async def complete_workorder(order_id: str, req: CompleteRequest):
    """Repair person completes a work order."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Work order not found")

    order = dict(row)
    cursor.execute(
        """UPDATE work_orders SET
        status = 'completed', completed_at = ?, actual_fault = ?,
        actual_action = ?, used_parts = ?, repair_person = ?, result = ?
        WHERE id = ?""",
        (
            datetime.now().isoformat(), req.actual_fault, req.actual_action,
            req.used_parts, req.repair_person, req.result, order_id,
        ),
    )
    conn.commit()
    conn.close()

    # Write back to house digital archive
    record = {
        "id": f"MR-{order['house_id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "workOrderId": order_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "location": order.get("location", ""),
        "fault": order.get("fault_type", ""),
        "cause": req.actual_fault,
        "action": req.actual_action,
        "repairPerson": req.repair_person,
        "result": req.result,
    }
    add_maintenance_record(order["house_id"], record)

    return {
        "success": True,
        "order_id": order_id,
        "message": "维修完成，数据已回写至一房一码数字档案",
        "maintenance_record": record,
    }

@router.get("/stats/summary")
async def get_stats():
    """Get work order statistics."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT status, COUNT(*) as count FROM work_orders GROUP BY status")
    status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

    cursor.execute("SELECT urgency, COUNT(*) as count FROM work_orders GROUP BY urgency")
    urgency_counts = {row["urgency"]: row["count"] for row in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) as total FROM work_orders")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT AVG(confidence) as avg_confidence FROM work_orders")
    avg_conf = cursor.fetchone()["avg_confidence"] or 0

    conn.close()
    return {
        "total": total,
        "by_status": status_counts,
        "by_urgency": urgency_counts,
        "avg_confidence": round(avg_conf, 1),
    }
