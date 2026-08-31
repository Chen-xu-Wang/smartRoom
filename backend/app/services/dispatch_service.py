"""智能派单数据库服务。

负责读取工单与维修人员负载、调用纯调度算法，并以事务方式写入派单结果。
所有自动/人工派单入口共用 MySQL 命名锁，避免并发请求突破人员容量上限。
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime

from ..database import get_conn, query_all, query_one
from .dispatcher import (
    build_dispatch_plan,
    calculate_fatigue,
    calculate_sla_risk,
    parse_skills,
    workload_balance_score,
)


class DispatchError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "DISPATCH_ERROR"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@contextmanager
def _dispatch_lock(timeout_seconds: int = 5):
    """使用 MySQL GET_LOCK 串行化容量检查与派单决策。"""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT GET_LOCK('smartroom_ai_dispatch', %s) AS acquired",
                (timeout_seconds,),
            )
            row = cursor.fetchone()
            if not row or row.get("acquired") != 1:
                raise DispatchError("调度服务繁忙，请稍后重试", 409, "DISPATCH_BUSY")
            try:
                yield
            finally:
                cursor.execute("SELECT RELEASE_LOCK('smartroom_ai_dispatch')")


def _latest_ai_summary(order_db_id: int) -> dict:
    row = query_one(
        "SELECT content FROM repair_message"
        " WHERE repair_order_id = %s AND message_type = 'AI_SUMMARY'"
        " ORDER BY id DESC LIMIT 1",
        (order_db_id,),
    )
    if not row or not row.get("content"):
        return {}
    try:
        value = json.loads(row["content"])
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _load_order(order_no: str) -> dict | None:
    row = query_one(
        "SELECT o.*, h.house_code, h.building_no, h.room_no"
        " FROM repair_order o JOIN house h ON o.house_id = h.id"
        " WHERE o.order_no = %s",
        (order_no,),
    )
    if not row:
        return None
    extra = _latest_ai_summary(row["id"])
    row["suggested_trade"] = extra.get("suggested_trade") or row.get("repair_category")
    return row


def _load_candidate_metrics(order: dict | None = None) -> list[dict]:
    category = order.get("repair_category") if order else None
    building = order.get("building_no") if order else None
    rows = query_all(
        "SELECT u.id, u.username, u.real_name,"
        " COALESCE(p.skills, '[\"综合维修\"]') AS skills,"
        " COALESCE(p.max_active_orders, 3) AS max_active_orders,"
        " COALESCE(p.daily_capacity, 5) AS daily_capacity,"
        " COALESCE(p.on_duty, 1) AS on_duty,"
        " p.last_assigned_at,"
        " SUM(CASE WHEN o.status IN ('PENDING_ASSIGN', 'PROCESSING')"
        "               AND o.assigned_to IS NOT NULL THEN 1 ELSE 0 END) AS active_orders,"
        " SUM(CASE WHEN o.status IN ('PENDING_ASSIGN', 'PROCESSING')"
        "               AND o.assigned_to IS NOT NULL"
        "          THEN CASE o.priority WHEN 'URGENT' THEN 1.6 WHEN 'HIGH' THEN 1.3"
        "               WHEN 'LOW' THEN 0.8 ELSE 1.0 END ELSE 0 END) AS active_load,"
        " SUM(CASE WHEN o.status = 'PROCESSING' THEN 1 ELSE 0 END) AS processing_orders,"
        " SUM(CASE WHEN o.status = 'COMPLETED' AND o.completed_at >= CURDATE()"
        "          THEN 1 ELSE 0 END) AS completed_today,"
        " MAX(o.completed_at) AS last_completed_at,"
        " SUM(CASE WHEN o.status = 'COMPLETED'"
        "               AND o.completed_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)"
        "               AND o.repair_category = %s THEN 1 ELSE 0 END) AS similar_jobs_90d,"
        " SUM(CASE WHEN o.status = 'COMPLETED'"
        "               AND o.completed_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)"
        "               AND h.building_no = %s THEN 1 ELSE 0 END) AS same_building_jobs_90d"
        " FROM `user` u"
        " LEFT JOIN repairer_profile p ON p.user_id = u.id"
        " LEFT JOIN repair_order o ON o.assigned_to = u.id"
        " LEFT JOIN house h ON h.id = o.house_id"
        " WHERE u.role = 'REPAIRER' AND u.status = 1"
        " GROUP BY u.id, u.username, u.real_name, p.skills, p.max_active_orders,"
        "          p.daily_capacity, p.on_duty, p.last_assigned_at"
        " ORDER BY u.id",
        (category, building),
    )
    for row in rows:
        row["skills"] = parse_skills(row.get("skills"))
        row["on_duty"] = bool(row.get("on_duty"))
    return rows


def get_dispatch_plan(order_no: str, allow_assigned: bool = False) -> dict:
    order = _load_order(order_no)
    if not order:
        raise DispatchError("Work order not found", 404, "ORDER_NOT_FOUND")
    if order["status"] != "PENDING_ASSIGN":
        raise DispatchError(
            f"当前工单状态为 {order['status']}，只有待派单工单可以生成调度方案",
            400,
            "INVALID_ORDER_STATUS",
        )
    if order.get("assigned_to") and not allow_assigned:
        raise DispatchError("该工单已经完成派单，无需重复自动派单", 409, "ALREADY_ASSIGNED")

    plan = build_dispatch_plan(order, _load_candidate_metrics(order))
    plan.update(
        {
            "order": {
                "order_no": order["order_no"],
                "house_code": order.get("house_code"),
                "building_no": order.get("building_no"),
                "location": order.get("location"),
                "repair_category": order.get("repair_category"),
                "suggested_trade": order.get("suggested_trade"),
                "priority": order.get("priority"),
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return plan


def _write_assignment(
    order: dict,
    candidate: dict,
    mode: str,
    assigned_by: str | None,
    require_unassigned: bool,
    override_reason: str | None = None,
) -> None:
    """在一个事务内更新工单、写审计流水并更新时间轮转字段。"""
    decision = {
        "派单方式": mode,
        "维修人": candidate["name"],
        "维修人ID": candidate["user_id"],
        "匹配分": candidate.get("score"),
        "疲劳指数": candidate.get("fatigue_index"),
        "接单后预计疲劳指数": candidate.get("projected_fatigue_index"),
        "推荐理由": candidate.get("reasons", []),
        "操作人": assigned_by or "系统",
        "人工越权原因": override_reason or "",
        "算法版本": "dispatch-v1",
    }
    with get_conn() as conn:
        try:
            conn.begin()
            with conn.cursor() as cursor:
                sql = (
                    "UPDATE repair_order SET assigned_to = %s"
                    " WHERE id = %s AND status = 'PENDING_ASSIGN'"
                )
                params = [candidate["user_id"], order["id"]]
                if require_unassigned:
                    sql += " AND assigned_to IS NULL"
                affected = cursor.execute(sql, tuple(params))
                if affected != 1:
                    raise DispatchError(
                        "工单状态或派单结果已变化，请刷新后重试",
                        409,
                        "ORDER_CHANGED",
                    )
                cursor.execute(
                    "INSERT INTO repair_record"
                    " (repair_order_id, operator_id, operator_type, action_type,"
                    "  before_status, after_status, description)"
                    " VALUES (%s, NULL, 'PROPERTY', %s, 'PENDING_ASSIGN',"
                    "         'PENDING_ASSIGN', %s)",
                    (
                        order["id"],
                        "AI_ASSIGN" if mode == "AI" else "MANUAL_ASSIGN",
                        json.dumps(decision, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    "UPDATE repairer_profile SET last_assigned_at = NOW() WHERE user_id = %s",
                    (candidate["user_id"],),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def auto_assign(order_no: str, assigned_by: str | None = None) -> dict:
    with _dispatch_lock():
        plan = get_dispatch_plan(order_no)
        candidate = plan.get("recommended")
        if not candidate:
            raise DispatchError(
                "当前没有满足技能与疲劳保护要求的维修人员，工单已保留待人工处理",
                409,
                "NO_SAFE_CANDIDATE",
            )
        order = _load_order(order_no)
        _write_assignment(order, candidate, "AI", assigned_by, require_unassigned=True)
        return {
            "success": True,
            "order_id": order_no,
            "assigned_to": candidate["name"],
            "assignment": candidate,
            "message": f"AI 已安全派单给「{candidate['name']}」",
        }


def manual_assign(
    order_no: str,
    repairer_name: str,
    assigned_by: str | None = None,
    force: bool = False,
    override_reason: str | None = None,
) -> dict:
    with _dispatch_lock():
        plan = get_dispatch_plan(order_no, allow_assigned=True)
        candidate = next(
            (item for item in plan["candidates"] if item["name"] == repairer_name),
            None,
        )
        if not candidate:
            raise DispatchError(
                f"维修人员「{repairer_name}」不存在或账号已停用",
                400,
                "REPAIRER_NOT_FOUND",
            )
        if not candidate["available"] and not force:
            raise DispatchError(
                f"疲劳保护已阻止派单：{'；'.join(candidate['blockers'])}",
                409,
                "FATIGUE_GUARD",
            )
        if force and not (override_reason or "").strip():
            raise DispatchError("强制派单必须填写越权原因", 400, "OVERRIDE_REASON_REQUIRED")
        order = _load_order(order_no)
        _write_assignment(
            order,
            candidate,
            "MANUAL_OVERRIDE" if force else "MANUAL",
            assigned_by,
            require_unassigned=False,
            override_reason=override_reason,
        )
        return {
            "success": True,
            "order_id": order_no,
            "assigned_to": candidate["name"],
            "assignment": candidate,
            "message": "派单成功，工单等待开始维修",
        }


def _auto_approve_for_batch(pending_rows: list[dict], assigned_by: str | None, remaining_limit: int) -> tuple[list[str], list[dict]]:
    """批量自动审核 PENDING_REVIEW 为 PENDING_ASSIGN（仅高置信度）.

    返回 (approved_order_nos, skipped_records)。高置信度阈值与 chat 自动提交一致：>=70 视为 COMPLETE。
    低置信度跳过，保留人工审核，避免完全绕过人类决策。
    """
    if not pending_rows:
        return [], []
    # 批量取置信度
    order_ids = [r["id"] for r in pending_rows]
    placeholders = ", ".join(["%s"] * len(order_ids))
    ai_rows = query_all(
        f"SELECT repair_order_id, content FROM repair_message WHERE message_type='AI_SUMMARY' AND repair_order_id IN ({placeholders}) ORDER BY id DESC",
        tuple(order_ids),
    )
    # 取最新一条
    latest = {}
    for r in ai_rows:
        if r["repair_order_id"] not in latest:
            try:
                latest[r["repair_order_id"]] = json.loads(r["content"]).get("confidence", 0)
            except:
                latest[r["repair_order_id"]] = 0
    # 系统审核人（PROPERTY 角色的首位）
    reviewer = query_one("SELECT id FROM `user` WHERE role IN ('PROPERTY','ADMIN') ORDER BY id LIMIT 1")
    reviewer_id = reviewer["id"] if reviewer else None
    approved, skipped = [], []
    for row in pending_rows:
        if len(approved) >= remaining_limit:
            break
        conf = int(latest.get(row["id"], 0) or 0)
        if conf < 70:
            skipped.append({"order_id": row["order_no"], "reason": "NEEDS_MANUAL_REVIEW", "confidence": conf})
            continue
        # 事务内更新为待派单
        with get_conn() as conn:
            try:
                conn.begin()
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE repair_order SET status='PENDING_ASSIGN', reviewer_id=%s, reviewed_at=NOW(), info_status='COMPLETE' WHERE id=%s AND status='PENDING_REVIEW'",
                        (reviewer_id, row["id"]),
                    )
                    if cursor.rowcount != 1:
                        skipped.append({"order_id": row["order_no"], "reason": "ORDER_CHANGED"})
                        conn.rollback()
                        continue
                    cursor.execute(
                        "INSERT INTO repair_record (repair_order_id, operator_id, operator_type, action_type, before_status, after_status, description) VALUES (%s, NULL, 'PROPERTY', 'APPROVE', 'PENDING_REVIEW', 'PENDING_ASSIGN', %s)",
                        (row["id"], json.dumps({"auto_approved": True, "confidence": conf, "by": assigned_by or "系统批量"}, ensure_ascii=False)),
                    )
                conn.commit()
                approved.append(row["order_no"])
            except Exception as e:
                try: conn.rollback()
                except: pass
                skipped.append({"order_id": row["order_no"], "reason": "APPROVE_FAILED"})
    return approved, skipped


def auto_assign_batch(assigned_by: str | None = None, limit: int = 50) -> dict:
    """按优先级逐单重算团队负载，支持一键覆盖待审核→待派单→派单全链路。

    1) 先对 PENDING_REVIEW 中高置信度（>=70）自动审核为 PENDING_ASSIGN
    2) 再对 PENDING_ASSIGN 未派单的按优先级与疲劳保护派单
    两阶段共享 limit，避免一批压垮。
    """
    limit = max(1, min(int(limit), 100))
    with _dispatch_lock():
        # 1) 自动审核阶段
        pending_review_rows = query_all(
            "SELECT id, order_no, priority, created_at FROM repair_order WHERE status='PENDING_REVIEW' ORDER BY CASE priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END, created_at ASC LIMIT %s",
            (limit,),
        )
        auto_approved, auto_skipped = _auto_approve_for_batch(pending_review_rows, assigned_by, limit)
        remaining = limit - len(auto_approved)
        # 2) 派单阶段（包含刚自动审核的）
        rows = query_all(
            "SELECT order_no FROM repair_order"
            " WHERE status = 'PENDING_ASSIGN' AND assigned_to IS NULL"
            " ORDER BY CASE priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2"
            "                        WHEN 'NORMAL' THEN 3 ELSE 4 END, created_at ASC"
            " LIMIT %s",
            (limit,),
        )
        assigned, skipped = [], []
        # 将自动审核阶段的低置信度跳过合并
        skipped.extend(auto_skipped)
        for row in rows:
            order_no = row["order_no"]
            # 避免重复处理刚审核的已在 rows 中（已通过后续派单覆盖）
            try:
                plan = get_dispatch_plan(order_no)
                candidate = plan.get("recommended")
                if not candidate:
                    skipped.append({"order_id": order_no, "reason": "NO_SAFE_CANDIDATE"})
                    continue
                order = _load_order(order_no)
                _write_assignment(order, candidate, "AI", assigned_by, require_unassigned=True)
                assigned.append(
                    {
                        "order_id": order_no,
                        "assigned_to": candidate["name"],
                        "score": candidate["score"],
                        "fatigue_index": candidate["fatigue_index"],
                    }
                )
            except DispatchError as exc:
                skipped.append({"order_id": order_no, "reason": exc.code})
        return {
            "success": True,
            "auto_approved_count": len(auto_approved),
            "auto_approved": auto_approved,
            "assigned_count": len(assigned),
            "skipped_count": len(skipped),
            "assigned": assigned,
            "skipped": skipped,
        }


def get_dispatch_overview() -> dict:
    candidates = _load_candidate_metrics()
    repairers = []
    for candidate in candidates:
        fatigue = calculate_fatigue(candidate)
        repairers.append(
            {
                "id": candidate["id"],
                "username": candidate["username"],
                "real_name": candidate["real_name"],
                "skills": candidate["skills"],
                "on_duty": candidate["on_duty"],
                "processing_orders": int(candidate.get("processing_orders") or 0),
                **fatigue,
            }
        )

    pending_review_rows = query_all(
        "SELECT o.order_no, o.priority, o.created_at, o.location, o.repair_category, h.house_code"
        " FROM repair_order o JOIN house h ON h.id = o.house_id"
        " WHERE o.status = 'PENDING_REVIEW' ORDER BY CASE o.priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END, o.created_at ASC"
    )
    unassigned_rows = query_all(
        "SELECT o.order_no, o.priority, o.created_at, o.location, o.repair_category,"
        "       h.house_code"
        " FROM repair_order o JOIN house h ON h.id = o.house_id"
        " WHERE o.status = 'PENDING_ASSIGN' AND o.assigned_to IS NULL"
        " ORDER BY CASE o.priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2"
        "                         WHEN 'NORMAL' THEN 3 ELSE 4 END, o.created_at ASC"
    )
    open_rows = query_all(
        "SELECT o.order_no, o.status, o.priority, o.created_at, o.location,"
        "       o.assigned_to, h.house_code"
        " FROM repair_order o JOIN house h ON h.id = o.house_id"
        " WHERE o.status IN ('PENDING_REVIEW', 'PENDING_ASSIGN', 'PROCESSING')"
        " ORDER BY o.created_at ASC LIMIT 200"
    )
    sla_risks = []
    for row in open_rows:
        risk = calculate_sla_risk(row)
        if risk["is_at_risk"]:
            sla_risks.append(
                {
                    "order_no": row["order_no"],
                    "house_code": row["house_code"],
                    "location": row.get("location"),
                    "priority": row["priority"],
                    "status": row["status"],
                    "unassigned": not bool(row.get("assigned_to")),
                    **risk,
                }
            )
    risk_rank = {"overdue": 0, "high": 1, "medium": 2, "low": 3}
    sla_risks.sort(key=lambda item: (risk_rank[item["risk_level"]], item["remaining_hours"]))

    overload_repairers = [
        item
        for item in repairers
        if item["workload_blockers"] or item["fatigue_level"] == "high"
    ]
    available_repairers = [
        item for item in repairers if item["on_duty"] and not item["workload_blockers"]
    ]
    return {
        "summary": {
            "pending_review_orders": len(pending_review_rows),
            "unassigned_orders": len(unassigned_rows),
            "total_dispatchable": len(pending_review_rows) + len(unassigned_rows),
            "available_repairers": len(available_repairers),
            "overload_repairers": len(overload_repairers),
            "sla_risk_orders": len(sla_risks),
            "today_completed": sum(item["completed_today"] for item in repairers),
            "balance_score": workload_balance_score(repairers),
        },
        "repairers": repairers,
        "pending_review_orders": pending_review_rows,
        "unassigned_orders": unassigned_rows,
        "sla_risks": sla_risks,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
