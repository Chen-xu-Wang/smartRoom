"""主动感知业务服务：检测 → 规则决策 → 落库 → 住户提醒 → 工单闭环。

数据流（去掉百炼后的最小闭环）：
    模拟传感器数据流 ──检测器──▶ 契约① 事件 ──event_rules──▶ 契约② 决策
        ├─ notices   → resident_notice（住户/相关住户/物业提醒）
        └─ workorders
             ├─ IMMEDIATE：立即写 repair_order（PENDING_REVIEW, source=AUTO_SENSOR）
             └─ DEFERRED ：住户点"一键报修"，或物业"复查"时仍未恢复，再写 repair_order
    之后的审核、智能派单、疲劳保护、SLA、档案回写全部复用现有工单体系。

检测器（``DETECTORS``）与样例目录一一对应：
    supply_blockage  data/processed/samples/supply_blockage_{户号}/   进水堵塞
    water_leak       data/processed/samples/water_leak_{户号}/        暗漏、爆管自动关阀
    power_safety     data/processed/samples/power_{户号}/             漏电、电压是否在电器安全范围内
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from functools import lru_cache

from ..config import SENSING_SAMPLE_DIR, SIM_BUILDING_FILE
from ..database import execute, execute_return_id, parse_json_field, query_all, query_one
from . import event_rules, power_safety, water_blockage, water_leak

PRIORITY_EN2CN = {"URGENT": "紧急", "HIGH": "高", "NORMAL": "中", "LOW": "低"}
RESIDENT_AUDIENCES = ("RESIDENT", "NEIGHBOR", "FAMILY")
_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_HOUSE_RE = re.compile(r"^\d{3,4}$")
_SOURCE_RE = re.compile(r"^sample:([a-z_]+?)_(\d{3,4})/([a-z0-9_]+)$")


class SensingError(Exception):
    """带 HTTP 状态码的业务错误，由 API 层翻译成响应。"""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


# ---------------------------------------------------------------------------
# 模拟档案与样例数据
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _sim_building() -> dict:
    if not os.path.exists(SIM_BUILDING_FILE):
        raise SensingError(503, "SIM_BUILDING_MISSING", f"未找到扩展档案 {SIM_BUILDING_FILE}，请先运行 data/scripts/build_building.py")
    with open(SIM_BUILDING_FILE, encoding="utf-8") as f:
        return json.load(f)


def _sim_house(house_code: str) -> dict:
    house = next((h for h in _sim_building()["houses"] if h["house_id"] == house_code), None)
    if house is None:
        raise SensingError(404, "HOUSE_NOT_IN_SIM", f"模拟楼栋中没有 {house_code}")
    return house


# 检测器注册表：样例目录前缀、生成脚本、展示名
DETECTORS = {
    "supply_blockage": {"prefix": "supply_blockage", "label": "进水堵塞", "domain": "WATER",
                        "script": "run_sample_blockage.py"},
    "water_leak": {"prefix": "water_leak", "label": "漏水（暗漏 / 爆管）", "domain": "WATER",
                   "script": "run_sample_water_leak.py"},
    "power_safety": {"prefix": "power", "label": "用电安全（漏电 / 电压）", "domain": "POWER",
                     "script": "run_sample_power.py"},
}
_PREFIX_TO_DETECTOR = {v["prefix"]: k for k, v in DETECTORS.items()}


def _sample_dir(detector: str, house_code: str) -> str:
    return os.path.join(SENSING_SAMPLE_DIR, f"{DETECTORS[detector]['prefix']}_{house_code}")


def list_samples(house_code: str) -> list[dict]:
    out = []
    for detector, spec in DETECTORS.items():
        base = _sample_dir(detector, house_code)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not _NAME_RE.match(name) or not os.path.exists(os.path.join(base, name, "sensor_stream.csv.gz")):
                continue
            with open(os.path.join(base, name, "manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            out.append({"detector": detector, "detector_label": spec["label"], "domain": spec["domain"],
                        "scenario": name, "window": manifest["window"], "data_source": manifest["data_source"]})
    return out


def list_blockage_samples(house_code: str) -> list[dict]:
    """兼容旧接口：只返回进水堵塞样例。"""
    return [s for s in list_samples(house_code) if s["detector"] == "supply_blockage"]


def _scenario_dir(detector: str, house_code: str, scenario: str) -> str:
    if detector not in DETECTORS:
        raise SensingError(400, "BAD_DETECTOR", f"未知检测器 {detector}")
    if not _HOUSE_RE.match(house_code or "") or not _NAME_RE.match(scenario or ""):
        raise SensingError(400, "BAD_SAMPLE", "户号或场景名不合法")
    path = os.path.join(_sample_dir(detector, house_code), scenario)
    if not os.path.exists(os.path.join(path, "sensor_stream.csv.gz")):
        raise SensingError(404, "SAMPLE_NOT_FOUND", f"未找到样例数据 {house_code}/{scenario}，"
                                                     f"请先运行 python data/scripts/{DETECTORS[detector]['script']}")
    return path


def _stream_path(house_code: str, scenario: str) -> str:
    """兼容旧调用：进水堵塞样例的传感器文件路径。"""
    return os.path.join(_scenario_dir("supply_blockage", house_code, scenario), "sensor_stream.csv.gz")


# ---------------------------------------------------------------------------
# 图表（给前端统一画图的最小结构）
# ---------------------------------------------------------------------------
def _chart(title: str, unit: str, x: list, series: list[dict], *, flags: list[bool] | None = None,
           thresholds: list[dict] | None = None, marker: dict | None = None, value_format: str = "number",
           x_label: str = "日期") -> dict:
    return {"title": title, "unit": unit, "x": x, "x_label": x_label, "series": series, "flags": flags or [False] * len(x),
            "thresholds": thresholds or [], "marker": marker, "value_format": value_format}


def _blockage_chart(diag: dict, event: dict | None) -> dict:
    daily = diag.get("daily", [])
    thr = -(diag.get("config", {}).get("drop_threshold", 0.30))
    return _chart("淋浴出水能力（相对入住初期）", "", [p["date"] for p in daily],
                  [{"key": "change", "label": "出水能力变化", "values": [p["change_ratio"] for p in daily]}],
                  flags=[p["flagged"] for p in daily], thresholds=[{"value": thr, "label": "报警线"}],
                  marker={"x": event["detected_at"][:10], "label": "检测日"} if event else None, value_format="percent")


def _hidden_leak_chart(diag: dict, event: dict | None) -> dict:
    nights = [p for p in diag.get("nightly", []) if p["meter_lpm"] is not None]
    limit = diag.get("config", {}).get("min_leak_lpm", 0.05)
    return _chart("凌晨 2–5 点最小流量", "L/min", [p["date"] for p in nights],
                  [{"key": "meter", "label": "总表最小流量", "values": [p["meter_lpm"] for p in nights]}],
                  flags=[p["flagged"] for p in nights], thresholds=[{"value": limit, "label": "漏水判定线"}],
                  marker={"x": event["detected_at"][:10], "label": "检测日"} if event else None, x_label="夜间")


def _burst_chart(diag: dict, event: dict) -> dict:
    trace = diag.get("trace", [])
    closed = next((a["executed_at"][11:16] for a in event["control_actions_taken"] if a["action"] == "CLOSE_MAIN_VALVE"), None)
    # 模拟数据不回灌关阀动作，关阀之后的流量不代表真实情况，因此只画到关阀时刻
    def cut(key):
        return [None if closed and p["time"] > closed else p[key] for p in trace]
    return _chart("爆管前后每分钟最大流量（关阀后不再绘制）", "L/min", [p["time"] for p in trace],
                  [{"key": "branch", "label": "出事支路", "values": cut("branch_lpm")},
                   {"key": "meter", "label": "入户总表", "values": cut("meter_lpm")}],
                  marker={"x": closed, "label": "自动关阀"} if closed else None, x_label="时刻")


def _leakage_chart(diag: dict, event: dict | None, circuit_code: str, circuit_name: str | None = None) -> dict:
    daily = diag.get("circuits", {}).get(circuit_code, {}).get("daily", [])
    rows = [p for p in daily if p["p95_ma"] is not None or p["trips"]]
    rated = event["evidence"]["trip_threshold_ma"] if event else 30
    return _chart(f"{circuit_name or circuit_code}漏电流（每日 95% 分位）", "mA", [p["date"] for p in rows],
                  [{"key": "p95", "label": "漏电流", "values": [p["p95_ma"] for p in rows]}],
                  flags=[p["flagged"] or p["trips"] > 0 for p in rows],
                  thresholds=[{"value": rated / 2, "label": "接近动作值"}, {"value": rated, "label": "保护动作值"}],
                  marker={"x": event["detected_at"][:10], "label": "检测日"} if event else None)


def _voltage_chart(diag: dict, event: dict | None) -> dict:
    daily = diag.get("daily", [])
    lo, hi = diag.get("limits_v", [198.0, 235.4])
    # 每条线只标出自己越限的日子（过电压标在最高电压线上，欠电压标在最低电压线上）
    return _chart("每日最低 / 最高电压", "V", [p["date"] for p in daily],
                  [{"key": "vmax", "label": "最高电压", "values": [p["vmax"] for p in daily],
                    "flags": [p["vmax"] > hi for p in daily]},
                   {"key": "vmin", "label": "最低电压", "values": [p["vmin"] for p in daily],
                    "flags": [p["vmin"] < lo for p in daily]}],
                  flags=[p["flagged"] for p in daily],
                  thresholds=[{"value": hi, "label": f"国标上限 {hi} V"}, {"value": lo, "label": f"国标下限 {lo} V"}],
                  marker={"x": event["detected_at"][:10], "label": "检测日"} if event else None)


# ---------------------------------------------------------------------------
# 检测器实现：返回 (事件列表 [(事件, 图表)], 无事件时的图表)
# ---------------------------------------------------------------------------
def _run_blockage(house_code: str, path: str):
    house, building = _sim_house(house_code), _sim_building()
    stream = water_blockage.read_stream_csv(os.path.join(path, "sensor_stream.csv.gz"))
    r = water_blockage.detect_supply_blockage(stream, house, building["building"],
                                              recent_repairs_180d=_recent_plumbing_repairs(house_code))
    chart = _blockage_chart(r["diagnostics"], r["event"])
    return ([(r["event"], chart)] if r["event"] else []), [chart], r["diagnostics"]["status"]


def _run_water_leak(house_code: str, path: str):
    house, building = _sim_house(house_code), _sim_building()
    stream = water_blockage.read_stream_csv(os.path.join(path, "sensor_stream.csv.gz"))
    burst = water_leak.detect_pipe_burst(stream, house, building["building"], event_seq=1)
    hidden = water_leak.detect_hidden_leak(stream, house, building["building"], event_seq=2 if burst["event"] else 1)
    events = []
    if burst["event"]:
        events.append((burst["event"], _burst_chart(burst["diagnostics"], burst["event"])))
    hidden_chart = _hidden_leak_chart(hidden["diagnostics"], hidden["event"])
    if hidden["event"]:
        events.append((hidden["event"], hidden_chart))
    status = "EVENT" if events else hidden["diagnostics"]["status"]
    return events, [hidden_chart], status


def _run_power(house_code: str, path: str):
    house, building = _sim_house(house_code), _sim_building()
    stream = water_blockage.read_stream_csv(os.path.join(path, "sensor_stream.csv.gz"))
    neighbors = water_blockage.read_stream_csv(os.path.join(path, "neighbors.csv.gz"))
    leak = power_safety.detect_leakage(stream, house, building["building"])
    volt = power_safety.detect_voltage(stream, neighbors, house, building, event_seq=len(leak["events"]) + 1)
    names = {c["circuit_code"]: c["name"] for c in house["circuits"]}
    events = [(e, _leakage_chart(leak["diagnostics"], e, e["evidence"]["circuit_code"], names.get(e["evidence"]["circuit_code"])))
              for e in leak["events"]]
    volt_chart = _voltage_chart(volt["diagnostics"], volt["event"])
    if volt["event"]:
        events.append((volt["event"], volt_chart))
    # 无事件时展示最容易受潮的卫生间插座回路（没有则取第一条有剩余电流保护的回路）与电压
    circuits = leak["diagnostics"]["circuits"]
    shown = next((c for c in circuits if c.endswith("-BT")), next(iter(circuits), None))
    charts = ([_leakage_chart(leak["diagnostics"], None, shown, names.get(shown))] if shown else []) + [volt_chart]
    return events, charts, "EVENT" if events else "NO_EVENT"


_RUNNERS = {"supply_blockage": _run_blockage, "water_leak": _run_water_leak, "power_safety": _run_power}


# ---------------------------------------------------------------------------
# 检测入口
# ---------------------------------------------------------------------------
def run_detection(house_code: str, detector: str, scenario: str) -> dict:
    """对样例数据运行检测器；每个事件按规则决策并落库（按数据来源 + 事件类型幂等）。"""
    path = _scenario_dir(detector, house_code, scenario)
    source_ref = f"sample:{DETECTORS[detector]['prefix']}_{house_code}/{scenario}"
    found, charts, status = _RUNNERS[detector](house_code, path)
    results = []
    for event, chart in found:
        # 同一份数据重复运行得到同一事件：已存在就直接返回，不重复提醒（需要重演时先重置演示）
        existing = query_one("SELECT event_id FROM device_event WHERE source_ref = %s AND event_type = %s"
                             " AND status <> 'ARCHIVED'", (source_ref, event["event_type"]))
        if existing:
            results.append({"created": False, **get_event(existing["event_id"])})
            continue
        event["event_id"] = _next_event_id(event["event_id"])
        decision = event_rules.decide(event)
        _persist_event(event, decision, {"chart": chart}, source_ref)
        results.append({"created": True, **get_event(event["event_id"])})
    return {"detector": detector, "scenario": scenario, "detection_status": status, "events": results,
            "charts": charts if not results else [r["diagnostics"].get("chart") for r in results]}


def run_supply_blockage(house_code: str, scenario: str) -> dict:
    """兼容旧接口 /water-blockage/run：返回单个事件的平铺结构。"""
    r = run_detection(house_code, "supply_blockage", scenario)
    if not r["events"]:
        return {"detection_status": r["detection_status"], "created": False, "event": None,
                "diagnostics": {"status": r["detection_status"], "chart": r["charts"][0] if r["charts"] else None}}
    return {"detection_status": "EVENT", **r["events"][0]}


def _next_event_id(candidate: str) -> str:
    """同一范围键同一天已有其它事件时顺延序号。"""
    prefix = candidate.rsplit("-", 1)[0]
    rows = query_all("SELECT event_id FROM device_event WHERE event_id LIKE %s", (prefix + "-%",))
    used = {int(r["event_id"].rsplit("-", 1)[1]) for r in rows}
    seq = 1
    while seq in used:
        seq += 1
    return f"{prefix}-{seq:04d}"


def _recent_plumbing_repairs(house_code: str) -> int:
    row = query_one(
        "SELECT COUNT(*) AS c FROM repair_order o JOIN house h ON o.house_id = h.id"
        " WHERE h.house_code = %s AND o.repair_category = '给排水故障'"
        " AND o.created_at >= DATE_SUB(NOW(), INTERVAL 180 DAY) AND o.status <> 'CANCELLED'",
        (house_code,),
    )
    return int(row["c"]) if row else 0


def _persist_event(event: dict, decision: dict, diagnostics: dict, source_ref: str) -> None:
    house_code = event["house_id"]
    house_row = query_one("SELECT id FROM house WHERE house_code = %s", (house_code,)) if house_code else None
    detected = datetime.fromisoformat(event["detected_at"]).replace(tzinfo=None)
    deferred = [w for w in decision["workorders"] if w["create_mode"] == "DEFERRED"]
    recheck_due = (detected.date() + timedelta(days=deferred[0]["recheck_after_days"])) if deferred else None
    execute(
        "INSERT INTO device_event (event_id, house_id, house_code, scope, domain, event_type, severity, priority,"
        " detected_at, fault_summary, payload, decision, diagnostics, generated_by, source_ref, status, recheck_due)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            event["event_id"], house_row["id"] if house_row else None, house_code, event["scope"], event["domain"],
            event["event_type"], event["severity"], decision["priority"], detected, decision["fault_summary"],
            json.dumps(event, ensure_ascii=False), json.dumps(decision, ensure_ascii=False),
            json.dumps(diagnostics, ensure_ascii=False), event_rules.GENERATED_BY, source_ref, "NOTIFIED", recheck_due,
        ),
    )
    for notice in decision["notices"]:
        for hid in notice["house_ids"]:
            execute(
                "INSERT IGNORE INTO resident_notice (event_id, house_code, audience, title, content,"
                " self_check_steps, show_repair_button) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (event["event_id"], hid, notice["audience"], notice["title"], notice["content"],
                 json.dumps(notice["self_check_steps"], ensure_ascii=False), int(notice["show_repair_button"])),
            )
    if any(w["create_mode"] == "IMMEDIATE" for w in decision["workorders"]):
        _create_workorder(event["event_id"], operator_type="SYSTEM", reason="规则要求立即建单")


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def _event_row_to_dict(row: dict) -> dict:
    order = None
    if row.get("repair_order_id"):
        order = query_one("SELECT order_no, status FROM repair_order WHERE id = %s", (row["repair_order_id"],))
    return {
        "event_id": row["event_id"],
        "house_id": row["house_code"],
        "scope": row["scope"],
        "domain": row["domain"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "priority": row["priority"],
        "urgency": PRIORITY_EN2CN.get(row["priority"], "中"),
        "detected_at": row["detected_at"].strftime("%Y-%m-%dT%H:%M:%S+08:00") if row.get("detected_at") else None,
        "fault_summary": row["fault_summary"],
        "status": row["status"],
        "recheck_due": row["recheck_due"].isoformat() if row.get("recheck_due") else None,
        "generated_by": row["generated_by"],
        "source_ref": row["source_ref"],
        "work_order_id": order["order_no"] if order else None,
        "work_order_status": order["status"] if order else None,
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


def list_events(house_code: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    where, params = ["1=1"], []
    if house_code:
        # 本户事件 + 波及本户的楼栋级事件（如同相供电电压异常）
        where.append("(house_code = %s OR (house_code IS NULL AND"
                     " JSON_CONTAINS(JSON_EXTRACT(payload, '$.related_houses'), JSON_QUOTE(%s))))")
        params += [house_code, house_code]
    if status:
        where.append("status = %s")
        params.append(status)
    else:
        where.append("status <> 'ARCHIVED'")  # 归档事件默认不显示，需要时按 status=ARCHIVED 查询
    rows = query_all(
        f"SELECT * FROM device_event WHERE {' AND '.join(where)} ORDER BY detected_at DESC, id DESC LIMIT %s",
        tuple(params + [limit]),
    )
    out = []
    for r in rows:
        item = _event_row_to_dict(r)
        payload = parse_json_field(r["payload"], {})
        item["top_candidate"] = (payload.get("location_candidates") or [None])[0]
        item["evidence_text"] = payload.get("evidence_text", "")
        item["control_actions_taken"] = payload.get("control_actions_taken", [])
        out.append(item)
    return out


def get_event(event_id: str) -> dict:
    row = query_one("SELECT * FROM device_event WHERE event_id = %s", (event_id,))
    if not row:
        raise SensingError(404, "EVENT_NOT_FOUND", f"事件 {event_id} 不存在")
    diagnostics = parse_json_field(row["diagnostics"], {})
    event = parse_json_field(row["payload"], {})
    if "chart" not in diagnostics and event.get("event_type") == "SUPPLY_BLOCKAGE":
        diagnostics["chart"] = _blockage_chart(diagnostics, event)  # 兼容早期只存逐日数据的事件
    return {
        **_event_row_to_dict(row),
        "event": event,
        "decision": parse_json_field(row["decision"], {}),
        "diagnostics": diagnostics,
        "notices": list_notices(event_id=event_id, audiences=None),
    }


def _notice_row_to_dict(row: dict) -> dict:
    order = None
    if row.get("repair_order_id"):
        order = query_one("SELECT order_no, status FROM repair_order WHERE id = %s", (row["repair_order_id"],))
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "house_id": row["house_code"],
        "audience": row["audience"],
        "title": row["title"],
        "content": row["content"],
        "self_check_steps": parse_json_field(row["self_check_steps"], []),
        "show_repair_button": bool(row["show_repair_button"]),
        "status": row["status"],
        "work_order_id": order["order_no"] if order else None,
        "work_order_status": order["status"] if order else None,
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


def list_notices(house_code: str | None = None, status: str | None = None, event_id: str | None = None,
                 audiences: tuple[str, ...] | None = RESIDENT_AUDIENCES) -> list[dict]:
    """``audiences`` 默认是住户能看到的提醒（本户、相关住户、家属）；传 None 表示全部。"""
    where, params = ["1=1"], []
    if audiences:
        where.append(f"audience IN ({', '.join(['%s'] * len(audiences))})")
        params += list(audiences)
    if house_code:
        where.append("house_code = %s")
        params.append(house_code)
    if status:
        where.append("status = %s")
        params.append(status)
    elif not event_id:
        where.append("status <> 'ARCHIVED'")
    if event_id:
        where.append("event_id = %s")
        params.append(event_id)
    rows = query_all(f"SELECT * FROM resident_notice WHERE {' AND '.join(where)} ORDER BY id DESC", tuple(params))
    return [_notice_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 住户与物业动作
# ---------------------------------------------------------------------------
def _notice_row(notice_id: int) -> dict:
    row = query_one("SELECT * FROM resident_notice WHERE id = %s", (notice_id,))
    if not row:
        raise SensingError(404, "NOTICE_NOT_FOUND", f"提醒 {notice_id} 不存在")
    return row


def mark_notice_read(notice_id: int) -> dict:
    row = _notice_row(notice_id)
    if row["status"] == "UNREAD":
        execute("UPDATE resident_notice SET status = 'READ' WHERE id = %s", (notice_id,))
    return _notice_row_to_dict(_notice_row(notice_id))


def dismiss_notice(notice_id: int) -> dict:
    """住户确认已自行处理或属于自己调小阀门：提醒关闭；本户事件未建单时标记为已解除。"""
    row = _notice_row(notice_id)
    if row["status"] == "REPAIR_REQUESTED":
        raise SensingError(409, "ALREADY_REQUESTED", "已发起报修，不能再忽略")
    execute("UPDATE resident_notice SET status = 'DISMISSED' WHERE id = %s", (notice_id,))
    if row["audience"] == "RESIDENT":
        execute("UPDATE device_event SET status = 'RESOLVED' WHERE event_id = %s AND status = 'NOTIFIED'", (row["event_id"],))
    return _notice_row_to_dict(_notice_row(notice_id))


def request_repair(notice_id: int, reporter_id: int | None = None) -> dict:
    """住户点"一键报修"：按决策中的工单草稿生成工单，重复点击返回同一张工单。"""
    row = _notice_row(notice_id)
    if row["status"] == "DISMISSED":
        raise SensingError(409, "NOTICE_DISMISSED", "提醒已被忽略，请重新检测后再报修")
    order = _create_workorder(row["event_id"], operator_type="USER", reason="住户一键报修", reporter_id=reporter_id)
    execute("UPDATE resident_notice SET status = 'REPAIR_REQUESTED', repair_order_id = %s WHERE id = %s",
            (order["order_db_id"], notice_id))
    return {"notice": _notice_row_to_dict(_notice_row(notice_id)), **order}


def create_workorder_for_event(event_id: str, operator: str | None = None) -> dict:
    """物业不等复查，直接为事件建单。"""
    return _create_workorder(event_id, operator_type="PROPERTY", reason=f"物业直接建单（{operator or '物业'}）")


def recheck_event(event_id: str) -> dict:
    """复查：用复查日的数据重新评估。仍异常则建单，已恢复则解除事件。

    模拟数据是离线样例，这里用"检测日 + 复查天数"（不超过数据末日）作为复查日。
    目前支持 DEFERRED 类事件：进水堵塞（出水能力是否仍越线）、暗漏（复查日夜间是否仍有持续流量）。
    """
    row = query_one("SELECT * FROM device_event WHERE event_id = %s", (event_id,))
    if not row:
        raise SensingError(404, "EVENT_NOT_FOUND", f"事件 {event_id} 不存在")
    if row["status"] != "NOTIFIED":
        return {"rechecked": False, "reason": f"事件状态为 {row['status']}，无需复查", **get_event(event_id)}
    match = _SOURCE_RE.match((row["source_ref"] or "").split("#")[0])
    if not match or row["event_type"] not in ("SUPPLY_BLOCKAGE", "HIDDEN_LEAK"):
        raise SensingError(400, "RECHECK_UNSUPPORTED", "该事件类型或来源暂不支持复查")
    prefix, house_code, scenario = match.groups()
    detector = _PREFIX_TO_DETECTOR.get(prefix)
    path = _scenario_dir(detector, house_code, scenario)
    stream = water_blockage.read_stream_csv(os.path.join(path, "sensor_stream.csv.gz"))
    recheck_day = min(row["recheck_due"] or row["detected_at"].date(), stream.ts[-1].date())
    house = _sim_house(house_code)

    if row["event_type"] == "SUPPLY_BLOCKAGE":
        result = water_blockage.detect_supply_blockage(stream, house, _sim_building()["building"], as_of=recheck_day)
        last = next((p for p in reversed(result["diagnostics"]["daily"]) if p["change_ratio"] is not None), None)
        still_abnormal = bool(last and last["flagged"])
        detail = f"出水能力变化 {last['change_ratio']:+.0%}" if last else "数据不足"
    else:
        last = water_leak.leak_still_present(stream, house, recheck_day)
        still_abnormal = bool(last and last["flagged"])
        detail = f"凌晨最小流量 {last['meter_lpm']} L/min" if last else "数据不足"

    if still_abnormal:
        order = _create_workorder(event_id, operator_type="SYSTEM", reason=f"{recheck_day} 复查仍未恢复（{detail}）")
        return {"rechecked": True, "recheck_day": recheck_day.isoformat(), "still_abnormal": True, "detail": detail,
                "latest": last, **order, **get_event(event_id)}
    execute("UPDATE device_event SET status = 'RESOLVED' WHERE event_id = %s", (event_id,))
    execute("UPDATE resident_notice SET status = 'DISMISSED' WHERE event_id = %s AND status IN ('UNREAD', 'READ')",
            (event_id,))
    return {"rechecked": True, "recheck_day": recheck_day.isoformat(), "still_abnormal": False, "detail": detail,
            "latest": last, **get_event(event_id)}


CLOSED_ORDER_STATUSES = ("COMPLETED", "CANCELLED")


def on_workorder_completed(order_db_id: int) -> None:
    """工单完成后闭环：由该工单触发的感知事件标记为已解决。"""
    execute("UPDATE device_event SET status = 'RESOLVED' WHERE repair_order_id = %s AND status = 'ORDER_CREATED'",
            (order_db_id,))


def reset_sample_events(house_code: str) -> dict:
    """演示用：让某户的样例数据可以重新演示（覆盖该户全部检测器，含波及该户的楼栋级事件）。

    - 未建单的事件：连同提醒直接删除；
    - 工单已完成或已取消的事件：归档（保留事件与工单历史，但不再出现在演示列表中，
      也不再占用"同一样例只产生一次事件"的幂等位，重新检测会生成新事件）；
    - 工单仍在处理中的事件：保留，避免演示重置打断正在进行的维修流程。
    """
    if not _HOUSE_RE.match(house_code or ""):
        raise SensingError(400, "BAD_HOUSE", "户号不合法")
    rows = query_all(
        "SELECT e.id, e.event_id, e.source_ref, e.repair_order_id, o.order_no, o.status AS order_status"
        " FROM device_event e LEFT JOIN repair_order o ON o.id = e.repair_order_id"
        " WHERE e.source_ref LIKE 'sample:%%' AND e.status <> 'ARCHIVED'",
    )
    deleted, archived, kept = [], [], []
    for r in rows:
        match = _SOURCE_RE.match(r["source_ref"] or "")
        if not match or match.group(2) != house_code:
            continue
        if r["repair_order_id"] is None or r["order_no"] is None:
            execute("DELETE FROM resident_notice WHERE event_id = %s", (r["event_id"],))
            execute("DELETE FROM device_event WHERE id = %s", (r["id"],))
            deleted.append(r["event_id"])
        elif r["order_status"] in CLOSED_ORDER_STATUSES:
            execute("UPDATE device_event SET status = 'ARCHIVED', source_ref = %s WHERE id = %s",
                    (f"{r['source_ref']}#archived-{r['id']}"[:160], r["id"]))
            execute("UPDATE resident_notice SET status = 'ARCHIVED' WHERE event_id = %s", (r["event_id"],))
            archived.append({"event_id": r["event_id"], "work_order_id": r["order_no"]})
        else:
            kept.append({"event_id": r["event_id"], "work_order_id": r["order_no"], "work_order_status": r["order_status"]})
    return {"deleted_events": deleted, "archived_events": archived, "kept_open_events": kept}


def _create_workorder(event_id: str, *, operator_type: str, reason: str, reporter_id: int | None = None) -> dict:
    row = query_one("SELECT * FROM device_event WHERE event_id = %s", (event_id,))
    if not row:
        raise SensingError(404, "EVENT_NOT_FOUND", f"事件 {event_id} 不存在")
    if row["repair_order_id"]:
        existing = query_one("SELECT id, order_no, status FROM repair_order WHERE id = %s", (row["repair_order_id"],))
        if existing:
            return {"created": False, "work_order_id": existing["order_no"], "order_db_id": existing["id"],
                    "work_order_status": existing["status"]}
    if row["status"] == "RESOLVED":
        raise SensingError(409, "EVENT_RESOLVED", "事件已解除，不能建单")

    event = parse_json_field(row["payload"], {})
    decision = parse_json_field(row["decision"], {})
    drafts = decision.get("workorders") or []
    if not drafts:
        raise SensingError(409, "NO_WORKORDER_DRAFT", "该事件的决策不需要工单")
    draft = drafts[0]
    # 本户事件挂在本户；楼栋级事件（如供电电压异常）挂在发现异常的住户（样例来源户）上，
    # 该户不在档案库时再取受影响住户中第一个已建档的房屋；位置写公共部位
    source = _SOURCE_RE.match((row["source_ref"] or "").split("#")[0])
    observer = [source.group(2)] if source else []
    candidates_houses = [row["house_code"]] if row["house_code"] else observer + [h for h in draft.get("house_ids") or [] if h not in observer]
    house = None
    for code in candidates_houses:
        house = query_one("SELECT id, house_code FROM house WHERE house_code = %s", (code,))
        if house:
            break
    if not house:
        raise SensingError(409, "HOUSE_NOT_IN_ARCHIVE", f"{'、'.join(candidates_houses[:3])} 不在一房一码档案库中，无法建单")
    if reporter_id is None:
        resident = query_one("SELECT id FROM `user` WHERE username = 'resident1'")
        reporter_id = resident["id"] if resident else None

    device = None
    if draft.get("device_code"):
        device = query_one("SELECT id, device_name FROM house_device WHERE house_id = %s AND device_code = %s",
                           (house["id"], draft["device_code"]))
    candidates = event.get("location_candidates") or []
    confidence = round((candidates[0]["confidence"] if candidates else 0.8) * 100)
    scope_note = "【楼栋公共部位】" if event.get("scope") == "BUILDING" else ""

    order_no = f"WO-{house['house_code']}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    suffix = 1
    while query_one("SELECT id FROM repair_order WHERE order_no = %s", (order_no,)):
        suffix += 1
        order_no = f"WO-{house['house_code']}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{suffix}"

    order_db_id = execute_return_id(
        "INSERT INTO repair_order (order_no, reporter_id, house_id, original_description, ai_summary,"
        " repair_category, location, priority, info_status, status, device_id, device_description,"
        " source, trigger_event_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETE', 'PENDING_REVIEW', %s, %s, 'AUTO_SENSOR', %s)",
        (
            order_no, reporter_id, house["id"], f"【系统主动感知】{scope_note}{event.get('evidence_text', '')}",
            draft["ai_summary"], draft["fault_type"], draft["location"], decision.get("priority", "NORMAL"),
            device["id"] if device else None, device["device_name"] if device else draft["location"], event_id,
        ),
    )
    ai_payload = {
        "confidence": confidence,
        "suggested_trade": draft["suggested_trade"],
        "urgency": PRIORITY_EN2CN.get(decision.get("priority"), "中"),
        "fault_type": draft["fault_type"],
        "possible_causes": [f"{c['segment_name']}（{round(c['confidence'] * 100)}%）" for c in candidates],
        # 与报修对话一致：存 house_device 主键，工单详情页据此展示关联设备
        "related_equipment": [device["id"]] if device else [],
        "materials": draft.get("materials", []),
        "worker_safety_notice": draft.get("worker_safety_notice", []),
        "control_actions_taken": event.get("control_actions_taken", []),
        "source": "AUTO_SENSOR",
        "event_id": event_id,
        "generated_by": row["generated_by"],
    }
    execute(
        "INSERT INTO repair_message (repair_order_id, sender_id, sender_type, message_type, content)"
        " VALUES (%s, NULL, 'AI', 'AI_SUMMARY', %s)",
        (order_db_id, json.dumps(ai_payload, ensure_ascii=False)),
    )
    execute(
        "INSERT INTO repair_record (repair_order_id, operator_id, operator_type, action_type, before_status,"
        " after_status, description) VALUES (%s, %s, %s, 'CREATE', NULL, 'PENDING_REVIEW', %s)",
        (order_db_id, reporter_id if operator_type == "USER" else None, operator_type,
         f"主动感知事件 {event_id} 生成工单：{reason}；{decision.get('fault_summary', '')}"),
    )
    execute("UPDATE device_event SET status = 'ORDER_CREATED', repair_order_id = %s WHERE event_id = %s",
            (order_db_id, event_id))
    execute("UPDATE resident_notice SET repair_order_id = %s WHERE event_id = %s", (order_db_id, event_id))
    return {"created": True, "work_order_id": order_no, "order_db_id": order_db_id, "work_order_status": "PENDING_REVIEW"}
