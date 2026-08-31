"""可解释的维修工单调度算法。

这个模块只处理纯数据，不访问数据库，方便单元测试和后续替换策略。
大模型负责理解故障并给出建议工种；本模块负责执行不可被模型绕过的
安全约束（在岗、技能、并发容量、每日容量）并给出可追溯的排序理由。
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from statistics import pstdev
from typing import Any


PRIORITY_LOAD = {"URGENT": 1.6, "HIGH": 1.3, "NORMAL": 1.0, "LOW": 0.8}
SLA_TARGET_HOURS = {"URGENT": 1, "HIGH": 4, "NORMAL": 24, "LOW": 48}

_TRADE_ALIASES = {
    "给排水故障": "水电维修",
    "给排水": "水电维修",
    "管道疏通": "水电维修",
    "水暖维修": "水电维修",
    "电气故障": "电工维修",
    "电工": "电工维修",
    "空调故障": "空调维修",
    "暖通维修": "空调维修",
    "门窗故障": "门窗维修",
    "墙面裂缝": "油漆维修",
    "墙面维修": "油漆维修",
    "其他故障": "综合维修",
}


def parse_skills(value: Any) -> list[str]:
    """把 JSON、逗号分隔字符串或列表统一成去重后的技能列表。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ["综合维修"]
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = text.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple, set)):
        value = [value] if value else []
    result = []
    for item in value:
        skill = str(item).strip()
        if skill and skill not in result:
            result.append(skill)
    return result or ["综合维修"]


def canonical_trade(value: str | None) -> str:
    value = (value or "").strip()
    return _TRADE_ALIASES.get(value, value or "综合维修")


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def calculate_fatigue(candidate: dict, now: datetime | None = None) -> dict:
    """根据在途负载、今日完工量与最小休息间隔计算疲劳指数。

    指数不是医学判断，而是调度保护信号。容量上限同时作为硬约束，
    因此即便其它评分很高，也不会把新工单继续派给已满负荷人员。
    """
    now = now or datetime.now()
    active_orders = int(candidate.get("active_orders") or 0)
    active_load = float(candidate.get("active_load") or active_orders)
    completed_today = int(candidate.get("completed_today") or 0)
    max_active = max(1, int(candidate.get("max_active_orders") or 3))
    daily_capacity = max(1, int(candidate.get("daily_capacity") or 5))

    active_ratio = active_load / max_active
    daily_ratio = completed_today / daily_capacity
    rest_penalty = 0.0
    last_completed = _as_datetime(candidate.get("last_completed_at"))
    if last_completed:
        hours_since_rest = max(0.0, (now - last_completed).total_seconds() / 3600)
        if hours_since_rest < 2:
            rest_penalty = 15 * (1 - hours_since_rest / 2)

    fatigue_index = round(min(100, active_ratio * 55 + daily_ratio * 30 + rest_penalty))
    if fatigue_index >= 75:
        level = "high"
    elif fatigue_index >= 45:
        level = "medium"
    else:
        level = "low"

    blockers = []
    if not bool(candidate.get("on_duty", True)):
        blockers.append("当前不在岗")
    if active_orders >= max_active:
        blockers.append(f"在途工单已达上限（{active_orders}/{max_active}）")
    if completed_today >= daily_capacity:
        blockers.append(f"今日完工量已达保护上限（{completed_today}/{daily_capacity}）")
    if fatigue_index >= 75:
        blockers.append("疲劳指数偏高，已触发休息保护")

    return {
        "fatigue_index": fatigue_index,
        "fatigue_level": level,
        "active_orders": active_orders,
        "active_load": round(active_load, 1),
        "completed_today": completed_today,
        "max_active_orders": max_active,
        "daily_capacity": daily_capacity,
        "capacity_remaining": max(0, max_active - active_orders),
        "workload_blockers": blockers,
    }


def score_candidate(order: dict, candidate: dict, now: datetime | None = None) -> dict:
    """对单个候选维修人员做硬过滤并计算可解释匹配分。"""
    target_trade = canonical_trade(order.get("suggested_trade") or order.get("repair_category"))
    raw_skills = parse_skills(candidate.get("skills"))
    skills = [canonical_trade(item) for item in raw_skills]
    exact_skill = target_trade in skills
    general_skill = "综合维修" in skills

    fatigue = calculate_fatigue(candidate, now)
    projected_candidate = dict(candidate)
    projected_candidate["active_orders"] = fatigue["active_orders"] + 1
    projected_candidate["active_load"] = fatigue["active_load"] + PRIORITY_LOAD.get(
        (order.get("priority") or "NORMAL").upper(), 1.0
    )
    projected = calculate_fatigue(projected_candidate, now)
    blockers = list(fatigue["workload_blockers"])
    if projected["fatigue_index"] >= 75 and fatigue["fatigue_index"] < 75:
        blockers.append(
            f"接单后预计疲劳指数 {projected['fatigue_index']}，将触发休息保护"
        )
    if not exact_skill and not general_skill:
        blockers.append(f"缺少「{target_trade}」技能")

    skill_factor = 1.0 if exact_skill else 0.72 if general_skill else 0.0
    capacity_factor = max(0.0, 1 - projected["fatigue_index"] / 100)
    max_active = fatigue["max_active_orders"]
    fairness_factor = max(0.0, 1 - fatigue["active_orders"] / max_active)
    similar_jobs = int(candidate.get("similar_jobs_90d") or 0)
    same_building_jobs = int(candidate.get("same_building_jobs_90d") or 0)
    experience_factor = min(1.0, similar_jobs / 4)
    locality_factor = min(1.0, same_building_jobs / 5)

    score = round(
        skill_factor * 50
        + capacity_factor * 30
        + experience_factor * 8
        + locality_factor * 4
        + fairness_factor * 8,
        1,
    )
    available = not blockers

    reasons = []
    if exact_skill:
        reasons.append(f"技能与「{target_trade}」精确匹配")
    elif general_skill:
        reasons.append(f"具备综合维修能力，可承接「{target_trade}」")
    if fatigue["active_orders"] == 0:
        reasons.append("当前无在途工单")
    else:
        reasons.append(
            f"当前在途 {fatigue['active_orders']}/{fatigue['max_active_orders']} 单"
        )
    if similar_jobs:
        reasons.append(f"近90天处理过 {similar_jobs} 个同类故障")
    if same_building_jobs:
        reasons.append(f"熟悉该楼栋（近90天 {same_building_jobs} 单）")
    if fatigue["fatigue_level"] == "low":
        reasons.append("疲劳风险低")

    return {
        "user_id": candidate.get("id") or candidate.get("user_id"),
        "username": candidate.get("username", ""),
        "name": candidate.get("real_name") or candidate.get("name") or "未命名维修人员",
        "skills": raw_skills,
        "target_trade": target_trade,
        "skill_match": "exact" if exact_skill else "general" if general_skill else "mismatch",
        "available": available,
        "score": score,
        "reasons": reasons,
        "blockers": blockers,
        "similar_jobs_90d": similar_jobs,
        "same_building_jobs_90d": same_building_jobs,
        "last_assigned_at": candidate.get("last_assigned_at"),
        "projected_fatigue_index": projected["fatigue_index"],
        "projected_fatigue_level": projected["fatigue_level"],
        **fatigue,
    }


def build_dispatch_plan(
    order: dict,
    candidates: list[dict],
    now: datetime | None = None,
) -> dict:
    """生成排序后的候选名单；无人安全可接时明确返回 NO_SAFE_CANDIDATE。"""
    now = now or datetime.now()
    scored = [score_candidate(order, candidate, now) for candidate in candidates]
    scored.sort(
        key=lambda item: (
            not item["available"],
            -item["score"],
            item["fatigue_index"],
            item["active_orders"],
            _as_datetime(item.get("last_assigned_at")) or datetime.min,
            item["user_id"] or math.inf,
        )
    )
    recommended = next((item for item in scored if item["available"]), None)
    return {
        "assignment_available": recommended is not None,
        "recommended": recommended,
        "candidates": scored,
        "no_assignment_reason": None if recommended else "NO_SAFE_CANDIDATE",
        "policy": {
            "version": "dispatch-v1",
            "principle": "安全硬约束优先，再按技能、负载、经验与公平性评分",
            "weights": {
                "skill": 50,
                "safe_capacity": 30,
                "similar_experience": 8,
                "building_familiarity": 4,
                "fairness": 8,
            },
        },
    }


def calculate_sla_risk(order: dict, now: datetime | None = None) -> dict:
    """按优先级和创建时长识别即将超时/已超时的未完成工单。"""
    now = now or datetime.now()
    created_at = _as_datetime(order.get("created_at")) or now
    priority = (order.get("priority") or "NORMAL").upper()
    target_hours = SLA_TARGET_HOURS.get(priority, SLA_TARGET_HOURS["NORMAL"])
    elapsed_hours = max(0.0, (now - created_at).total_seconds() / 3600)
    ratio = elapsed_hours / target_hours

    if ratio >= 1:
        level = "overdue"
    elif ratio >= 0.75:
        level = "high"
    elif ratio >= 0.5:
        level = "medium"
    else:
        level = "low"
    remaining = round(target_hours - elapsed_hours, 1)
    return {
        "risk_level": level,
        "target_hours": target_hours,
        "elapsed_hours": round(elapsed_hours, 1),
        "remaining_hours": remaining,
        "progress": round(min(100, ratio * 100)),
        "is_at_risk": level in {"medium", "high", "overdue"},
        "message": (
            f"已超出响应目标 {abs(remaining):.1f} 小时"
            if remaining < 0
            else f"距响应目标剩余 {remaining:.1f} 小时"
        ),
    }


def workload_balance_score(repairers: list[dict]) -> int:
    """返回 0-100 的团队负载均衡分，越高表示分配越均匀。"""
    if not repairers:
        return 100
    utilizations = []
    for item in repairers:
        max_active = max(1, int(item.get("max_active_orders") or 3))
        utilizations.append(min(1.5, float(item.get("active_orders") or 0) / max_active))
    if len(utilizations) == 1:
        return 100
    return round(max(0, 100 - pstdev(utilizations) * 120))
