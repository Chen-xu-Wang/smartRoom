"""主动感知接口：检测事件、住户提醒、一键报修、复查与建单。

业务逻辑全部在 ``services/sensing_service.py``，这里只做参数接收与错误翻译。
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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
    reporter_id: int | None = None


class OperatorRequest(BaseModel):
    operator: str | None = None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.SensingError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/samples")
async def list_samples(house_id: str = Query("1302")):
    """可回放的模拟样例数据（检测器、场景名、时段）。"""
    return {"house_id": house_id, "detectors": {k: v["label"] for k, v in svc.DETECTORS.items()},
            "samples": _call(svc.list_samples, house_id)}


@router.post("/run")
async def run_detection(req: DetectRequest):
    """对样例数据运行指定检测器；可能产生多个事件，每个事件生成规则决策、提醒，必要时立即建单（按数据来源幂等）。"""
    return _call(svc.run_detection, req.house_id, req.detector, req.scenario)


@router.post("/water-blockage/run")
async def run_water_blockage(req: RunRequest):
    """对样例数据运行进水堵塞检测；有事件则生成规则决策、住户提醒（按数据来源幂等）。"""
    return _call(svc.run_supply_blockage, req.house_id, req.scenario)


@router.post("/demo/reset")
async def reset_demo(house_id: str = Query("1302")):
    """演示用：清掉尚未建单的样例事件与提醒。"""
    return _call(svc.reset_sample_events, house_id)


@router.get("/events")
async def list_events(house_id: str = Query(None), status: str = Query(None), limit: int = Query(50, ge=1, le=200)):
    return {"events": _call(svc.list_events, house_id, status, limit)}


@router.get("/events/{event_id}")
async def get_event(event_id: str):
    return _call(svc.get_event, event_id)


@router.post("/events/{event_id}/recheck")
async def recheck_event(event_id: str):
    """复查：仍未恢复则自动建单，已恢复则解除事件。"""
    return _call(svc.recheck_event, event_id)


@router.post("/events/{event_id}/workorder")
async def create_workorder(event_id: str, req: OperatorRequest):
    """物业直接为事件建单（不等复查）。"""
    return _call(svc.create_workorder_for_event, event_id, req.operator)


@router.get("/notices")
async def list_notices(house_id: str = Query(None), status: str = Query(None),
                       audience: str = Query("RESIDENT,NEIGHBOR,FAMILY", description="逗号分隔；PROPERTY 为物业提醒")):
    audiences = tuple(a.strip().upper() for a in audience.split(",") if a.strip()) or None
    return {"notices": _call(svc.list_notices, house_id, status, None, audiences)}


@router.post("/notices/{notice_id}/read")
async def read_notice(notice_id: int):
    return _call(svc.mark_notice_read, notice_id)


@router.post("/notices/{notice_id}/repair")
async def repair_from_notice(notice_id: int, req: RepairRequest):
    """住户一键报修：按工单草稿生成待审核工单。"""
    return _call(svc.request_repair, notice_id, req.reporter_id)


@router.post("/notices/{notice_id}/dismiss")
async def dismiss_notice(notice_id: int):
    """住户已自行处理或确认是自己调小了阀门。"""
    return _call(svc.dismiss_notice, notice_id)
