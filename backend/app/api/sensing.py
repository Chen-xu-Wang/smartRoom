"""主动感知接口：检测事件、住户提醒、一键报修、复查与建单。

业务逻辑全部在 ``services/sensing_service.py``，这里只做参数接收、权限与数据范围、错误翻译。
数据范围：物业/管理员全部；维修人员只看自己工单触发的事件；
住户只看与名下房屋相关的事件与提醒，邻居事件只返回影响提示（见 services/event_access.py）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..database import query_all, query_one
from ..security import CurrentUser, current_user, require_roles, require_staff
from ..services import event_access
from ..services import sensing_service as svc

router = APIRouter(prefix="/api/sensing", tags=["sensing"])


class RunRequest(BaseModel):
    house_id: str = "1302"
    scenario: str = "fault"


class DetectRequest(BaseModel):
    house_id: str = "1302"
    detector: str = "supply_blockage"   # supply_blockage / water_leak / power_safety
    scenario: str


class RepairRequest(BaseModel):
    reporter_id: int | None = None      # 旧客户端兼容字段，已忽略：报修人取登录账号


class OperatorRequest(BaseModel):
    operator: str | None = None         # 旧客户端兼容字段，已忽略：操作人取登录账号


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.SensingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": message})


def _placeholders(items) -> str:
    return ", ".join(["%s"] * len(items))


def _resident_event_ids(codes: list[str]) -> set[str]:
    """与住户名下房屋相关的事件：发生在本户、提醒对象含本户、楼栋级事件波及本户."""
    if not codes:
        return set()
    ph = _placeholders(codes)
    ids = {r["event_id"] for r in query_all(
        f"SELECT DISTINCT event_id FROM resident_notice WHERE house_code IN ({ph})"
        f" AND audience IN ({_placeholders(event_access.RESIDENT_AUDIENCES)})",
        (*codes, *event_access.RESIDENT_AUDIENCES),
    )}
    ids |= {r["event_id"] for r in query_all(f"SELECT event_id FROM device_event WHERE house_code IN ({ph})", tuple(codes))}
    for code in codes:
        ids |= {r["event_id"] for r in query_all(
            "SELECT event_id FROM device_event WHERE JSON_CONTAINS(JSON_EXTRACT(payload, '$.related_houses'), JSON_QUOTE(%s))",
            (code,),
        )}
    return ids


def _repairer_event_ids(user_id: int) -> set[str]:
    rows = query_all(
        "SELECT trigger_event_id AS event_id FROM repair_order WHERE assigned_to = %s AND trigger_event_id IS NOT NULL"
        " UNION SELECT e.event_id FROM device_event e JOIN repair_order o ON e.repair_order_id = o.id WHERE o.assigned_to = %s",
        (user_id, user_id),
    )
    return {r["event_id"] for r in rows}


def _neighbor_event_ids(event_ids: set[str], codes: list[str]) -> set[str]:
    """这些事件里哪些不是发生在住户名下房屋（邻居事件或楼栋级事件）."""
    if not event_ids:
        return set()
    rows = query_all(f"SELECT event_id, house_code FROM device_event WHERE event_id IN ({_placeholders(event_ids)})",
                     tuple(event_ids))
    return {r["event_id"] for r in rows if r["house_code"] not in codes}


def _sanitize_resident_notices(notices: list[dict], user: CurrentUser) -> list[dict]:
    """邻居事件的提醒：事件号换成别名（事件号含发生户房号），不返回对方房屋的工单号."""
    neighbor = _neighbor_event_ids({n["event_id"] for n in notices}, user.house_codes)
    for n in notices:
        if n["event_id"] in neighbor:
            n.update(event_id=event_access.neighbor_event_id(n["event_id"]), work_order_id=None, work_order_status=None)
    return notices


def _resolve_resident_event_id(event_id: str, user: CurrentUser) -> str:
    """住户用别名访问邻居事件时换回真实事件号；别名不在其可见范围内视为不存在."""
    if not event_id.startswith("EVT-NB-"):
        return event_id
    for real in _resident_event_ids(user.house_codes):
        if event_access.neighbor_event_id(real) == event_id:
            return real
    raise HTTPException(status_code=404, detail={"code": "EVENT_NOT_FOUND", "message": "事件不存在"})


def _own_notice_titles(codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = query_all(
        f"SELECT event_id, title FROM resident_notice WHERE house_code IN ({_placeholders(codes)}) ORDER BY id",
        tuple(codes),
    )
    out = {}
    for r in rows:
        out.setdefault(r["event_id"], r["title"])
    return out


@router.get("/samples", dependencies=[Depends(require_staff)])
async def list_samples(house_id: str = Query("1302")):
    """可回放的模拟样例数据（检测器、场景名、时段）。"""
    return {"house_id": house_id, "detectors": {k: v["label"] for k, v in svc.DETECTORS.items()},
            "samples": _call(svc.list_samples, house_id)}


@router.post("/run", dependencies=[Depends(require_staff)])
async def run_detection(req: DetectRequest):
    """对样例数据运行指定检测器；可能产生多个事件，每个事件生成规则决策、提醒，必要时立即建单（按数据来源幂等）。"""
    return _call(svc.run_detection, req.house_id, req.detector, req.scenario)


@router.post("/water-blockage/run", dependencies=[Depends(require_staff)])
async def run_water_blockage(req: RunRequest):
    """对样例数据运行进水堵塞检测；有事件则生成规则决策、住户提醒（按数据来源幂等）。"""
    return _call(svc.run_supply_blockage, req.house_id, req.scenario)


@router.post("/demo/reset", dependencies=[Depends(require_staff)])
async def reset_demo(house_id: str = Query("1302")):
    """演示用：清掉尚未建单的样例事件与提醒。"""
    return _call(svc.reset_sample_events, house_id)


@router.get("/events")
async def list_events(house_id: str = Query(None), status: str = Query(None), limit: int = Query(50, ge=1, le=200),
                      user: CurrentUser = Depends(current_user)):
    if user.is_staff:
        return {"events": _call(svc.list_events, house_id, status, limit)}
    if user.is_resident:
        if house_id and house_id not in user.house_codes:
            raise _forbidden("该房屋不属于您")
        allowed = _resident_event_ids(user.house_codes)
    else:
        allowed = _repairer_event_ids(user.id)
    events = [e for e in _call(svc.list_events, house_id, status, 200) if e["event_id"] in allowed][:limit]
    if user.is_resident:
        titles = _own_notice_titles(user.house_codes)
        for e in events:
            e["source_ref"] = None
            if e["house_id"] not in user.house_codes:
                # 邻居事件：只留影响提示
                e.update(event_id=event_access.neighbor_event_id(e["event_id"]),
                         house_id=None, top_candidate=None, evidence_text="", control_actions_taken=[],
                         fault_summary=titles.get(e["event_id"]) or "附近住户或公共管线的问题可能影响您家",
                         work_order_id=None, work_order_status=None, neighbor=True)
    return {"events": events}


@router.get("/events/{event_id}")
async def get_event(event_id: str, user: CurrentUser = Depends(current_user)):
    if user.is_resident:
        event_id = _resolve_resident_event_id(event_id, user)
    detail = _call(svc.get_event, event_id)
    if user.is_staff:
        return detail
    if user.is_repairer:
        if event_id not in _repairer_event_ids(user.id):
            raise _forbidden("该问题不在您的工单范围内")
        detail["notices"] = event_access.repairer_notices(detail.get("notices"))
        return detail
    if not event_access.resident_can_see(detail["event"], detail["decision"], user.house_codes, detail.get("notices")):
        raise _forbidden("只能查看与您家相关的问题")
    event, decision, notices, neighbor = event_access.redact_for_resident(
        detail["event"], detail["decision"], detail.get("notices"), user.house_codes)
    detail.update(event=event, decision=decision, notices=notices, source_ref=None)
    if neighbor:
        detail.update(event_id=event["event_id"], house_id=None, diagnostics={}, fault_summary=decision["fault_summary"],
                      work_order_id=None, work_order_status=None, neighbor=True)
    return detail


@router.post("/events/{event_id}/recheck", dependencies=[Depends(require_staff)])
async def recheck_event(event_id: str):
    """复查：仍未恢复则自动建单，已恢复则解除事件。"""
    return _call(svc.recheck_event, event_id)


@router.post("/events/{event_id}/workorder")
async def create_workorder(event_id: str, req: OperatorRequest, user: CurrentUser = Depends(require_staff)):
    """物业直接为事件建单（不等复查）。"""
    return _call(svc.create_workorder_for_event, event_id, user.real_name)


@router.get("/notices")
async def list_notices(house_id: str = Query(None), status: str = Query(None),
                       audience: str = Query("RESIDENT,NEIGHBOR,FAMILY", description="逗号分隔；PROPERTY 为物业提醒"),
                       user: CurrentUser = Depends(require_roles("RESIDENT", "PROPERTY", "ADMIN"))):
    audiences = tuple(a.strip().upper() for a in audience.split(",") if a.strip()) or None
    if user.is_staff:
        return {"notices": _call(svc.list_notices, house_id, status, None, audiences)}
    # 住户：只能看名下房屋、给住户的提醒
    if house_id and house_id not in user.house_codes:
        raise _forbidden("该房屋不属于您")
    audiences = tuple(a for a in (audiences or event_access.RESIDENT_AUDIENCES) if a in event_access.RESIDENT_AUDIENCES)
    if not audiences:
        return {"notices": []}
    notices = []
    for code in ([house_id] if house_id else user.house_codes):
        notices += _call(svc.list_notices, code, status, None, audiences)
    notices.sort(key=lambda n: n["id"], reverse=True)
    return {"notices": _sanitize_resident_notices(notices, user)}


def _ensure_own_notice(notice_id: int, user: CurrentUser) -> None:
    row = query_one("SELECT house_code, audience FROM resident_notice WHERE id = %s", (notice_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOTICE_NOT_FOUND", "message": f"提醒 {notice_id} 不存在"})
    if row["house_code"] not in user.house_codes or row["audience"] not in event_access.RESIDENT_AUDIENCES:
        raise _forbidden("该提醒不属于您")


@router.post("/notices/{notice_id}/read")
async def read_notice(notice_id: int, user: CurrentUser = Depends(require_roles("RESIDENT"))):
    _ensure_own_notice(notice_id, user)
    return _sanitize_resident_notices([_call(svc.mark_notice_read, notice_id)], user)[0]


@router.post("/notices/{notice_id}/repair")
async def repair_from_notice(notice_id: int, req: RepairRequest, user: CurrentUser = Depends(require_roles("RESIDENT"))):
    """住户一键报修：按工单草稿生成待审核工单。"""
    _ensure_own_notice(notice_id, user)
    result = _call(svc.request_repair, notice_id, user.id)
    notice = _sanitize_resident_notices([result["notice"]], user)[0]
    if notice["work_order_id"] is None:
        # 邻居事件：工单建在发生户，不把对方房屋的工单号返回给本户
        return {"notice": notice, "created": result.get("created"), "work_order_id": None, "work_order_status": None,
                "message": "已通知物业处理"}
    return {**result, "notice": notice}


@router.post("/notices/{notice_id}/dismiss")
async def dismiss_notice(notice_id: int, user: CurrentUser = Depends(require_roles("RESIDENT"))):
    """住户已自行处理或确认是自己调小了阀门。"""
    _ensure_own_notice(notice_id, user)
    return _sanitize_resident_notices([_call(svc.dismiss_notice, notice_id)], user)[0]
