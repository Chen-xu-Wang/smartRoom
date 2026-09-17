"""3D 数字孪生数据接口 —— 按登录账号裁剪后下发.

楼栋拓扑与演示事件含全部住户的档案（设备、传感器、管线、登记人数等），
不放在前端 public 目录，由本接口按数据范围返回：
  - /api/twin/building     无权访问的住户只保留户型外壳（户号、楼层、户位、户型），户内档案清空
  - /api/twin/demo-events  演示事件与演示工单，规则同联机事件（services/event_access.py）
数据文件由 3D/scripts/build_twin_data.py 生成到 backend/app/data/twin/。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from fastapi import APIRouter, Depends

from ..config import DATA_DIR
from ..security import CurrentUser, current_user, visible_house_codes
from ..services import event_access

router = APIRouter(prefix="/api/twin", tags=["twin"])

TWIN_DIR = os.path.join(DATA_DIR, "twin")

# 无权访问的住户只保留渲染建筑外壳所需的字段
SHELL_KEEP = ("house_id", "floor", "position", "layout_id", "layout", "area_m2", "rooms")
SHELL_EMPTY = {"supply": [], "drain": [], "circuits": [], "sensors": [], "devices": [], "pipeline_layout": None}


@lru_cache(maxsize=4)
def _load(name: str, mtime: float) -> dict:
    with open(os.path.join(TWIN_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _read(name: str) -> dict:
    return _load(name, os.path.getmtime(os.path.join(TWIN_DIR, name)))


def _demo_orders_of(real_name: str) -> list[dict]:
    return [o for o in _read("demo_events.json").get("work_orders", []) if o.get("repairer") == real_name]


def _allowed_houses(user: CurrentUser) -> set[str] | None:
    scope = visible_house_codes(user)
    if scope is None:
        return None
    allowed = set(scope)
    if user.is_repairer:
        # 演示工单按维修人员姓名派单，涉及的住户也可查看
        allowed |= {str(o["house_id"]) for o in _demo_orders_of(user.real_name)}
    return allowed


@router.get("/building")
async def building(user: CurrentUser = Depends(current_user)):
    data = _read("building.json")
    allowed = _allowed_houses(user)
    if allowed is None:
        return data
    houses = [
        h if h["house_id"] in allowed else {**{k: h.get(k) for k in SHELL_KEEP}, **SHELL_EMPTY}
        for h in data["houses"]
    ]
    return {**data, "houses": houses}


@router.get("/demo-events")
async def demo_events(user: CurrentUser = Depends(current_user)):
    data = _read("demo_events.json")
    if user.is_staff:
        return data
    events, orders = [], []
    if user.is_repairer:
        orders = _demo_orders_of(user.real_name)
        ids = {o["event_id"] for o in orders}
        for item in data["events"]:
            if item["event"]["event_id"] not in ids:
                continue
            decision = {**(item.get("decision") or {})}
            decision["notices"] = event_access.repairer_notices(decision.get("notices"))
            events.append({**item, "decision": decision})
    elif user.is_resident:
        for item in data["events"]:
            if not event_access.resident_can_see(item["event"], item.get("decision"), user.house_codes):
                continue
            event, decision, _, neighbor = event_access.redact_for_resident(
                item["event"], item.get("decision"), None, user.house_codes)
            slim = {**item, "event": event, "decision": decision, "source_ref": None}
            if neighbor:
                slim.update(trend=None, chart=None)
            events.append(slim)
    return {**{k: v for k, v in data.items() if k not in ("events", "work_orders")}, "events": events, "work_orders": orders}
