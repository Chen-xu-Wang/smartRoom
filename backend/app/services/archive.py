"""House digital archive service - 一房一码模拟档案."""
import json
from pathlib import Path
from ..config import HOUSES_FILE

_houses_cache = None

def load_houses():
    global _houses_cache
    if _houses_cache is None:
        with open(HOUSES_FILE, "r", encoding="utf-8") as f:
            _houses_cache = json.load(f)
    return _houses_cache

def get_all_houses():
    houses = load_houses()
    return [
        {
            "houseId": h["houseId"],
            "building": h["building"],
            "room": h["room"],
            "floor": h["floor"],
            "qrCode": h["qrCode"],
            "digitalId": h["digitalId"],
            "layout": h["layout"],
            "area": h["area"],
        }
        for h in houses
    ]

def get_house_by_id(house_id: str):
    houses = load_houses()
    for h in houses:
        if h["houseId"] == house_id:
            return h
    return None

def get_house_by_qr(qr_code: str):
    houses = load_houses()
    for h in houses:
        if h["qrCode"] == qr_code:
            return h
    return None

def get_house_components(house_id: str, category: str = None):
    house = get_house_by_id(house_id)
    if not house:
        return None
    components = house.get("components", {})
    if category:
        return components.get(category, [])
    return components

def get_house_pipeline_layout(house_id: str):
    house = get_house_by_id(house_id)
    if not house:
        return None
    return house.get("pipelineLayout", {})

def get_house_equipment_by_location(house_id: str, location_keyword: str):
    """Get equipment related to a location keyword (e.g., '厨房')."""
    house = get_house_by_id(house_id)
    if not house:
        return []
    result = []
    location_map = {
        "厨房": ["plumbing"],
        "卫生间": ["bathroom"],
        "卧室": ["hvac"],
        "客厅": ["hvac"],
        "阳台": ["doors_windows"],
    }
    categories = location_map.get(location_keyword, [])
    # Also search all categories for location matches
    for cat, items in house.get("components", {}).items():
        for item in items:
            if location_keyword in item.get("location", "") or location_keyword in item.get("name", ""):
                result.append(item)
    return result

def get_maintenance_history(house_id: str):
    house = get_house_by_id(house_id)
    if not house:
        return []
    return house.get("maintenanceRecords", [])

def add_maintenance_record(house_id: str, record: dict):
    """Add a maintenance record to the house's archive."""
    global _houses_cache
    houses = load_houses()
    for h in houses:
        if h["houseId"] == house_id:
            if "maintenanceRecords" not in h:
                h["maintenanceRecords"] = []
            h["maintenanceRecords"].append(record)
            # Write back to file
            with open(HOUSES_FILE, "w", encoding="utf-8") as f:
                json.dump(houses, f, ensure_ascii=False, indent=2)
            _houses_cache = houses
            return record
    return None
