"""House archive API - 一房一码房屋数字档案."""
from fastapi import APIRouter, HTTPException
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
async def list_houses():
    """List all houses (summary)."""
    return {"houses": get_all_houses()}

@router.get("/{house_id}")
async def get_house(house_id: str):
    """Get full house digital archive."""
    house = get_house_by_id(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    return house

@router.get("/qr/{qr_code}")
async def get_house_by_qr_code(qr_code: str):
    """Get house by QR code."""
    house = get_house_by_qr(qr_code)
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    return house

@router.get("/{house_id}/components")
async def get_components(house_id: str, category: str = None):
    """Get house components, optionally filtered by category."""
    components = get_house_components(house_id, category)
    if components is None:
        raise HTTPException(status_code=404, detail="House not found")
    return {"house_id": house_id, "components": components}

@router.get("/{house_id}/pipeline")
async def get_pipeline(house_id: str):
    """Get pipeline layout."""
    pipeline = get_house_pipeline_layout(house_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="House not found")
    return {"house_id": house_id, "pipeline_layout": pipeline}

@router.get("/{house_id}/history")
async def get_history(house_id: str):
    """Get maintenance history."""
    history = get_maintenance_history(house_id)
    return {"house_id": house_id, "records": history}
