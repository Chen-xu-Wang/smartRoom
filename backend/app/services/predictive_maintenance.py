"""预测性维护风险聚合服务。

本模块只读 ``house_device``、``repair_order``、``repair_record`` 三张业务表，
把零散的设备档案和维修事件归并为可解释的健康分。评分函数与数据库访问分离，
这样规则可以在没有 MySQL 的环境中做确定性的单元测试。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping


RECENT_WINDOW_DAYS = 180

# 草稿和 AI 分析中的工单可能是被放弃的会话，不作为“正在发生的故障”；
# 以下三个状态均已进入人工处理流程，才计入待处理风险。
OPEN_ORDER_STATUSES = frozenset({"PENDING_REVIEW", "PENDING_ASSIGN", "PROCESSING"})
HIGH_PRIORITIES = frozenset({"URGENT", "HIGH", "紧急", "高"})
ABNORMAL_DEVICE_STATUSES = frozenset(
    {
        "FAULT",
        "ERROR",
        "OFFLINE",
        "MAINTENANCE",
        "REPAIR",
        "WARNING",
        "ABNORMAL",
        "STOPPED",
        "故障",
        "异常",
        "离线",
        "检修",
    }
)


def _normalise_datetime(value: Any) -> datetime | None:
    """把 MySQL/PyMySQL 和历史字符串日期统一成无时区 UTC datetime。

    历史库中日期可能是 ``None``、``date``、``datetime`` 或 ISO 字符串；
    解析不了时返回 ``None``，单条脏数据不会中断整个风险中心。
    """
    if value is None or value == "":
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            # 兼容少量旧数据中的 ``YYYY/MM/DD`` 日期。
            try:
                parsed = datetime.strptime(text[:10], "%Y/%m/%d")
            except (TypeError, ValueError):
                return None
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _non_negative_int(value: Any) -> int:
    """把聚合信号安全转成非负整数。"""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _status(value: Any) -> str:
    return str(value or "").strip().upper()


def _years_since(install_date: Any, now: datetime) -> float | None:
    installed = _normalise_datetime(install_date)
    if installed is None or installed > now:
        return None
    return max(0.0, (now - installed).days / 365.25)


def calculate_risk_score(
    signals: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    **overrides: Any,
) -> dict:
    """根据已经聚合好的信号计算健康分（纯函数，无 I/O）。

    ``signals`` 可包含：``device_status``、``install_date``、
    ``recent_repair_count``、``open_order_count``、
    ``urgent_open_order_count``、``incomplete_repair_count``、
    ``recent_rejected_count`` 和 ``last_repair_at``。

    返回的 ``risk_score`` 越高风险越大，``health_score = 100-risk_score``。
    规则刻意保持透明，物业能够从 ``risk_factor_details`` 看出每一分的来源。
    """
    data = dict(signals or {})
    data.update(overrides)
    current = _normalise_datetime(now) or datetime.now()
    window_days = max(
        1, _non_negative_int(data.get("recent_window_days") or RECENT_WINDOW_DAYS)
    )

    recent_repairs = _non_negative_int(data.get("recent_repair_count"))
    open_orders = _non_negative_int(data.get("open_order_count"))
    urgent_open = min(open_orders, _non_negative_int(data.get("urgent_open_order_count")))
    incomplete_repairs = min(
        recent_repairs, _non_negative_int(data.get("incomplete_repair_count"))
    )
    recent_rejected = _non_negative_int(data.get("recent_rejected_count"))
    age_years = _years_since(data.get("install_date"), current)

    details: list[dict] = []

    def add_factor(code: str, message: str, weight: int) -> None:
        if weight > 0:
            details.append({"code": code, "message": message, "weight": weight})

    if recent_repairs >= 4:
        add_factor(
            "FREQUENT_REPAIRS",
            f"近{window_days}天已完成{recent_repairs}次维修，存在高频复发迹象",
            45,
        )
    elif recent_repairs == 3:
        add_factor(
            "REPEAT_REPAIRS", f"近{window_days}天已完成3次维修，故障重复发生", 35
        )
    elif recent_repairs == 2:
        add_factor(
            "REPEAT_REPAIRS", f"近{window_days}天已完成2次维修，建议排查根因", 22
        )
    elif recent_repairs == 1:
        add_factor(
            "RECENT_REPAIR", f"近{window_days}天有1次维修记录，需要持续观察", 8
        )

    if open_orders:
        open_weight = 12 if open_orders == 1 else 20 if open_orders == 2 else 28
        add_factor(
            "OPEN_ORDERS",
            f"当前有{open_orders}张待处理或维修中的工单",
            open_weight,
        )

    if urgent_open:
        add_factor(
            "URGENT_OPEN_ORDERS",
            f"其中{urgent_open}张为高优先级工单",
            min(20, urgent_open * 10),
        )

    if incomplete_repairs:
        add_factor(
            "MISSING_REPAIR_RESULT",
            f"{incomplete_repairs}次已完成维修缺少完工流水，无法确认闭环质量",
            min(15, incomplete_repairs * 7),
        )

    if recent_rejected:
        add_factor(
            "REJECTED_ORDERS",
            f"近{window_days}天出现{recent_rejected}次工单退回，信息或方案需复核",
            min(12, recent_rejected * 6),
        )

    raw_device_status = _status(data.get("device_status"))
    if raw_device_status in ABNORMAL_DEVICE_STATUSES:
        add_factor(
            "ABNORMAL_DEVICE_STATUS",
            f"设备档案状态为{data.get('device_status') or '异常'}",
            30,
        )

    if age_years is not None:
        if age_years >= 12:
            add_factor("AGING_DEVICE", f"设备已安装约{age_years:.1f}年，老化风险较高", 24)
        elif age_years >= 8:
            add_factor("AGING_DEVICE", f"设备已安装约{age_years:.1f}年，进入老化期", 16)
        elif age_years >= 5:
            add_factor("AGING_DEVICE", f"设备已安装约{age_years:.1f}年", 8)

    last_repair = _normalise_datetime(data.get("last_repair_at"))
    if last_repair is not None and recent_repairs and 0 <= (current - last_repair).days <= 30:
        add_factor("VERY_RECENT_REPAIR", "最近30天刚发生过维修，建议进行回访复检", 5)

    risk_score = min(100, sum(item["weight"] for item in details))
    health_score = 100 - risk_score
    if risk_score >= 50:
        risk_level, risk_label = "HIGH", "高风险"
    elif risk_score >= 25:
        risk_level, risk_label = "MEDIUM", "中风险"
    else:
        risk_level, risk_label = "LOW", "低风险"

    factor_codes = {item["code"] for item in details}
    if risk_level == "HIGH" and "URGENT_OPEN_ORDERS" in factor_codes:
        action = "立即安排现场安全检查，优先闭环高优先级工单，并复核维修人员负荷。"
    elif risk_level == "HIGH" and (
        "FREQUENT_REPAIRS" in factor_codes or "REPEAT_REPAIRS" in factor_codes
    ):
        action = "48小时内组织专项诊断，排查根因并评估整体更换，避免继续重复派修。"
    elif risk_level == "HIGH":
        action = "48小时内安排专项巡检，确认安全隐患、备件和后续维护计划。"
    elif risk_level == "MEDIUM":
        action = "纳入下一轮预防性巡检，结合历史记录检查易损件并提前准备备件。"
    else:
        action = "保持常规巡检；设备或位置出现新异常时重新评估。"

    return {
        "risk_score": risk_score,
        "health_score": health_score,
        "risk_level": risk_level,
        "risk_level_label": risk_label,
        "risk_factors": [item["message"] for item in details],
        "risk_factor_details": details,
        "recommended_action": action,
        # 兼容“建议动作”这一更直观的 API 命名。
        "suggested_action": action,
    }


def _target_house_fields(row: Mapping[str, Any]) -> dict:
    house_code = str(row.get("house_code") or row.get("house_id") or "")
    name_parts = [row.get("building_no"), row.get("unit_no"), row.get("room_no")]
    house_name = "".join(str(part) for part in name_parts if part not in (None, ""))
    return {
        "house_id": row.get("house_id"),
        "house_code": house_code,
        "house_name": house_name or house_code,
    }


def _location_key(value: Any) -> str:
    text = str(value or "").strip()
    return "".join(text.split()).casefold() or "__unknown__"


def _make_location_target(order: Mapping[str, Any]) -> dict:
    location = str(order.get("location") or "").strip() or "未标注区域"
    house = _target_house_fields(order)
    key = _location_key(location)
    return {
        **house,
        "target_id": f"location:{house['house_id']}:{key}",
        "target_type": "LOCATION",
        "device_id": None,
        "device_code": None,
        "device_name": None,
        "device_type": None,
        "location": location,
        "device_status": None,
        "install_date": None,
        "orders": [],
    }


def _event_at(order: Mapping[str, Any]) -> datetime | None:
    return _normalise_datetime(order.get("completed_at")) or _normalise_datetime(
        order.get("created_at")
    )


def _is_in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    return value is not None and start <= value <= end


def _summary_for(level: str, risks: list[dict]) -> dict:
    selected = [risk for risk in risks if risk["risk_level"] == level]
    label = "高风险" if level == "HIGH" else "中风险"
    return {
        "count": len(selected),
        "average_health_score": (
            round(sum(item["health_score"] for item in selected) / len(selected), 1)
            if selected
            else None
        ),
        "targets": [
            {
                "target_id": item["target_id"],
                "target_type": item["target_type"],
                "house_code": item["house_code"],
                "device_name": item["device_name"],
                "location": item["location"],
                "health_score": item["health_score"],
                "recent_repair_count": item["recent_repair_count"],
            }
            for item in selected
        ],
        "message": f"当前共有{len(selected)}个{label}维护目标",
    }


def build_maintenance_risk_report(
    device_rows: Iterable[Mapping[str, Any]] | None,
    order_rows: Iterable[Mapping[str, Any]] | None,
    record_rows: Iterable[Mapping[str, Any]] | None,
    *,
    now: datetime | None = None,
    recent_window_days: int = RECENT_WINDOW_DAYS,
) -> dict:
    """把三张表的查询结果聚合成风险报告（纯函数，无 I/O）。

    有 ``device_id`` 的工单精确归到设备；旧工单没有设备关联时，按
    ``房屋 + 位置`` 建立 LOCATION 目标，避免历史数据被静默丢弃。
    """
    current = _normalise_datetime(now) or datetime.now()
    window_days = max(1, _non_negative_int(recent_window_days))
    window_start = current - timedelta(days=window_days)

    targets: dict[str, dict] = {}
    device_target_by_id: dict[Any, str] = {}

    for row in device_rows or []:
        device_id = row.get("device_id", row.get("id"))
        if device_id is None:
            continue
        target_id = f"device:{device_id}"
        house = _target_house_fields(row)
        targets[target_id] = {
            **house,
            "target_id": target_id,
            "target_type": "DEVICE",
            "device_id": device_id,
            "device_code": row.get("device_code") or "",
            "device_name": row.get("device_name") or "未命名设备",
            "device_type": row.get("device_type") or "",
            "location": str(row.get("location") or "").strip() or "未标注区域",
            "device_status": row.get("device_status", row.get("status")),
            "install_date": row.get("install_date"),
            "orders": [],
        }
        device_target_by_id[device_id] = target_id

    orders_by_id: dict[Any, Mapping[str, Any]] = {}
    for order in order_rows or []:
        order_id = order.get("order_id", order.get("id"))
        if order_id is not None:
            orders_by_id[order_id] = order

        target_id = device_target_by_id.get(order.get("device_id"))
        if target_id is None:
            location_target = _make_location_target(order)
            target_id = location_target["target_id"]
            targets.setdefault(target_id, location_target)
        targets[target_id]["orders"].append(order)

    complete_record_order_ids: set[Any] = set()
    reject_counts: defaultdict[Any, int] = defaultdict(int)
    for record in record_rows or []:
        order_id = record.get("repair_order_id")
        if order_id not in orders_by_id:
            continue
        action_type = _status(record.get("action_type"))
        if action_type == "COMPLETE_REPAIR":
            complete_record_order_ids.add(order_id)
        elif action_type == "REJECT":
            reject_counts[order_id] += 1

    risks: list[dict] = []
    for target in targets.values():
        completed_orders: list[Mapping[str, Any]] = []
        active_orders: list[Mapping[str, Any]] = []
        recent_rejected_count = 0

        for order in target["orders"]:
            status = _status(order.get("status"))
            event_at = _event_at(order)
            in_window = _is_in_window(event_at, window_start, current)
            if status == "COMPLETED" and in_window:
                completed_orders.append(order)
            if status in OPEN_ORDER_STATUSES:
                active_orders.append(order)
            if in_window:
                recent_rejected_count += reject_counts.get(
                    order.get("order_id", order.get("id")), 0
                )

        incomplete_repair_count = sum(
            1
            for order in completed_orders
            if order.get("order_id", order.get("id")) not in complete_record_order_ids
        )
        urgent_open_count = sum(
            1 for order in active_orders if _status(order.get("priority")) in HIGH_PRIORITIES
        )
        completed_dates = [_event_at(order) for order in completed_orders]
        last_repair = max((value for value in completed_dates if value), default=None)

        score = calculate_risk_score(
            {
                "device_status": target["device_status"],
                "install_date": target["install_date"],
                "recent_repair_count": len(completed_orders),
                "open_order_count": len(active_orders),
                "urgent_open_order_count": urgent_open_count,
                "incomplete_repair_count": incomplete_repair_count,
                "recent_rejected_count": recent_rejected_count,
                "last_repair_at": last_repair,
                "recent_window_days": window_days,
            },
            now=current,
        )
        total_completed = sum(
            1 for order in target["orders"] if _status(order.get("status")) == "COMPLETED"
        )
        public_target = {key: value for key, value in target.items() if key != "orders"}
        risks.append(
            {
                **public_target,
                **score,
                "recent_window_days": window_days,
                "recent_repair_count": len(completed_orders),
                "repair_history_count": total_completed,
                "open_order_count": len(active_orders),
                "urgent_open_order_count": urgent_open_count,
                "last_repair_at": last_repair.isoformat(sep=" ") if last_repair else None,
            }
        )

    level_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    risks.sort(
        key=lambda item: (
            level_order[item["risk_level"]],
            item["health_score"],
            -item["recent_repair_count"],
            item["target_id"],
        )
    )
    high_summary = _summary_for("HIGH", risks)
    medium_summary = _summary_for("MEDIUM", risks)
    low_count = sum(1 for item in risks if item["risk_level"] == "LOW")
    average_health = (
        round(sum(item["health_score"] for item in risks) / len(risks), 1)
        if risks
        else None
    )
    return {
        "generated_at": current.isoformat(sep=" "),
        "recent_window_days": window_days,
        "high_risk_count": high_summary["count"],
        "medium_risk_count": medium_summary["count"],
        "low_risk_count": low_count,
        "summary": {
            "total_targets": len(risks),
            "high_risk_count": high_summary["count"],
            "medium_risk_count": medium_summary["count"],
            "low_risk_count": low_count,
            "average_health_score": average_health,
        },
        "high_risk_summary": high_summary,
        "medium_risk_summary": medium_summary,
        "risks": risks,
    }


def get_maintenance_risks(
    house_code: str | None = None,
    *,
    now: datetime | None = None,
    query_all_fn: Callable[[str, tuple], list] | None = None,
) -> dict:
    """从 MySQL 读取维护数据并返回风险报告。

    ``query_all_fn`` 是测试缝隙；生产环境不传时延迟导入项目数据库助手，
    因而纯评分测试不需要连接 MySQL。
    """
    if query_all_fn is None:
        from ..database import query_all as query_all_fn

    device_sql = (
        "SELECT d.id AS device_id, d.house_id, d.device_code, d.device_name,"
        " d.device_type, d.location, d.install_date, d.status AS device_status,"
        " h.house_code, h.building_no, h.unit_no, h.room_no"
        " FROM house_device d JOIN house h ON d.house_id = h.id"
        " WHERE (h.status = 1 OR h.status IS NULL)"
    )
    order_sql = (
        "SELECT o.id AS order_id, o.house_id, o.device_id, o.location,"
        " o.priority, o.status, o.created_at, o.completed_at,"
        " h.house_code, h.building_no, h.unit_no, h.room_no"
        " FROM repair_order o JOIN house h ON o.house_id = h.id"
        " WHERE (h.status = 1 OR h.status IS NULL)"
    )
    record_sql = (
        "SELECT r.repair_order_id, r.action_type, r.description, r.created_at"
        " FROM repair_record r"
        " JOIN repair_order o ON r.repair_order_id = o.id"
        " JOIN house h ON o.house_id = h.id"
        " WHERE (h.status = 1 OR h.status IS NULL)"
        " AND r.action_type IN ('COMPLETE_REPAIR', 'REJECT')"
    )
    params: tuple = ()
    if house_code:
        device_sql += " AND h.house_code = %s"
        order_sql += " AND h.house_code = %s"
        record_sql += " AND h.house_code = %s"
        params = (house_code,)

    device_sql += " ORDER BY d.id"
    order_sql += " ORDER BY o.id"
    record_sql += " ORDER BY r.id"
    device_rows = query_all_fn(device_sql, params)
    order_rows = query_all_fn(order_sql, params)
    record_rows = query_all_fn(record_sql, params)
    return build_maintenance_risk_report(
        device_rows,
        order_rows,
        record_rows,
        now=now,
        recent_window_days=RECENT_WINDOW_DAYS,
    )
