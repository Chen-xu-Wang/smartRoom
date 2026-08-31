"""Maintenance API - 维修记录与预测性维护风险接口."""
from fastapi import APIRouter, HTTPException
from ..services.archive import get_maintenance_history, get_house_by_id
from ..services.predictive_maintenance import get_maintenance_risks

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/risks")
async def get_predictive_maintenance_risks(house_id: str | None = None):
    """聚合设备与位置健康风险；可用 house_id（房屋编号）筛选。"""
    return get_maintenance_risks(house_code=house_id)


@router.get("/history/{house_id}")
async def get_maintenance_history_api(house_id: str):
    """Get maintenance history for a house."""
    house = get_house_by_id(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    history = get_maintenance_history(house_id)

    # Check for repeat maintenance warnings
    location_counts = {}
    for record in history:
        loc = record.get("location", "")
        if loc:
            if loc not in location_counts:
                location_counts[loc] = 0
            location_counts[loc] += 1

    warnings = []
    for loc, count in location_counts.items():
        if count >= 2:
            warnings.append(
                f"{loc}区域近期存在{count}次维修记录，建议进一步排查根本原因，避免简单重复更换部件。"
            )

    return {
        "house_id": house_id,
        "records": history,
        "repeat_warnings": warnings,
        "total_count": len(history),
    }
