"""感知事件的按账号可见范围与脱敏（联机事件和 3D 演示事件共用）.

规则（与 3D/src/data/access.js 一致）：
  物业 / 管理员：全部原样
  维修人员：只看自己工单触发的事件；提醒只保留给物业的
  住户：
    - 本户事件：完整，但去掉其他住户的户号、提醒和工单草稿
    - 邻居事件（提醒对象包含本户，如楼上漏水）：只留影响提示——
      发给本户的提醒、类型、级别、时间；不含邻居户号、定位候选、证据、控制动作、监测数据
"""
from __future__ import annotations

from ..security import opaque_id

RESIDENT_AUDIENCES = ("RESIDENT", "NEIGHBOR", "FAMILY")


def _notice_houses(notice: dict) -> list[str]:
    if notice.get("house_ids") is not None:
        return [str(h) for h in notice["house_ids"]]
    return [str(notice["house_id"])] if notice.get("house_id") else []


def affected_houses(event: dict, decision: dict | None, notices: list[dict] | None = None) -> set[str]:
    """事件涉及住户：发生户 + 住户可见提醒的对象 + related_houses."""
    out = {str(h) for h in (event.get("related_houses") or [])}
    if event.get("house_id"):
        out.add(str(event["house_id"]))
    for n in list((decision or {}).get("notices") or []) + list(notices or []):
        if n.get("audience") in RESIDENT_AUDIENCES:
            out.update(_notice_houses(n))
    return out


def resident_can_see(event: dict, decision: dict | None, house_codes: list[str], notices: list[dict] | None = None) -> bool:
    return bool(affected_houses(event, decision, notices) & set(house_codes))


def neighbor_event_id(event_id: str) -> str:
    """邻居事件对住户使用别名：事件号里含发生户的房号（如 EVT-20260623-805-0002）."""
    return opaque_id("evt-nb", event_id)


def _own_notices(notices: list[dict], house_codes: set[str]) -> list[dict]:
    out = []
    for n in notices or []:
        if n.get("audience") not in RESIDENT_AUDIENCES:
            continue
        mine = [h for h in _notice_houses(n) if h in house_codes]
        if not mine:
            continue
        n = dict(n)
        if "house_ids" in n:
            n["house_ids"] = mine
        out.append(n)
    return out


def redact_for_resident(event: dict, decision: dict | None, notices: list[dict] | None,
                        house_codes: list[str]) -> tuple[dict, dict, list[dict], bool]:
    """返回 (event, decision, notices, is_neighbor)."""
    codes = {str(h) for h in house_codes}
    decision = decision or {}
    own_decision_notices = _own_notices(decision.get("notices") or [], codes)
    own_notices = _own_notices(notices or [], codes)
    neighbor = str(event.get("house_id") or "") not in codes
    first_title = next((n.get("title") for n in own_decision_notices + own_notices if n.get("title")), "")

    if not neighbor:
        event = {**event, "related_houses": [h for h in (event.get("related_houses") or []) if str(h) in codes]}
        decision = {**decision, "notices": own_decision_notices, "workorders": []}
        return event, decision, own_notices, False

    alias = neighbor_event_id(event.get("event_id") or "")
    for n in own_decision_notices + own_notices:
        if "event_id" in n:
            n["event_id"] = alias
        n.update({k: None for k in ("work_order_id", "work_order_status") if k in n})
    slim_event = {
        "event_id": alias,
        "event_type": event.get("event_type"),
        "domain": event.get("domain"),
        "severity": event.get("severity"),
        "detected_at": event.get("detected_at"),
        "scope": event.get("scope"),
        "house_id": None,
        "related_houses": [h for h in (event.get("related_houses") or []) if str(h) in codes],
        "location_candidates": [],
        "evidence": {},
        "evidence_text": "",
        "control_actions_taken": [],
        "data_source": event.get("data_source"),
    }
    slim_decision = {
        "priority": decision.get("priority"),
        "fault_summary": first_title or "附近住户或公共管线的问题可能影响您家",
        "notices": own_decision_notices,
        "workorders": [],
    }
    return slim_event, slim_decision, own_notices, True


def repairer_notices(notices: list[dict] | None) -> list[dict]:
    return [n for n in notices or [] if n.get("audience") == "PROPERTY"]
