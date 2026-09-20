"""House archive API - 一房一码房屋数字档案.

数据范围：物业/管理员可看全部；住户只能看名下房屋；维修人员只能看工单涉及的房屋（见 app/security.py）。
"""
from fastapi import APIRouter, Depends, HTTPException
from ..security import CurrentUser, current_user, ensure_house_access, visible_house_codes
from ..services.archive import (
    get_all_houses,
    get_house_by_id,
    get_house_by_qr,
    get_house_components,
    get_house_pipeline_layout,
    get_maintenance_history,
)

router = APIRouter(prefix="/api/houses", tags=["houses"])

@router.get("")
async def list_houses(user: CurrentUser = Depends(current_user)):
    """List all houses (summary)."""
    houses = get_all_houses()
    scope = visible_house_codes(user)
    if scope is not None:
        houses = [h for h in houses if h["houseId"] in scope]
    return {"houses": houses}

@router.get("/{house_id}")
async def get_house(house_id: str, user: CurrentUser = Depends(current_user)):
    """Get full house digital archive."""
    ensure_house_access(user, house_id)
    house = get_house_by_id(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    return house

@router.get("/qr/{qr_code}")
async def get_house_by_qr_code(qr_code: str, user: CurrentUser = Depends(current_user)):
    """Get house by QR code."""
    house = get_house_by_qr(qr_code)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    # 扫到别人家的码：提示不属于您，不返回档案
    ensure_house_access(user, house["houseId"])
    return house

@router.get("/{house_id}/components")
async def get_components(house_id: str, category: str = None, user: CurrentUser = Depends(current_user)):
    """Get house components, optionally filtered by category."""
    ensure_house_access(user, house_id)
    components = get_house_components(house_id, category)
    if components is None:
        raise HTTPException(status_code=404, detail="House not found")
    return {"house_id": house_id, "components": components}

@router.get("/{house_id}/pipeline")
async def get_pipeline(house_id: str, user: CurrentUser = Depends(current_user)):
    """Get pipeline layout."""
    ensure_house_access(user, house_id)
    pipeline = get_house_pipeline_layout(house_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="House not found")
    return {"house_id": house_id, "pipeline_layout": pipeline}

@router.get("/{house_id}/history")
async def get_history(house_id: str, user: CurrentUser = Depends(current_user)):
    """Get maintenance history."""
    ensure_house_access(user, house_id)
    history = get_maintenance_history(house_id)
    return {"house_id": house_id, "records": history}
