"""楼栋拓扑、一房一码设备与画像分配（任务 1.2）。

产出两份文件：

* ``sim_building.json``（公开）：108 户的户型、批次、供水分区、给水/排水拓扑、电气回路、
  传感器与设备清单。相当于"扩展后的一房一码档案"，检测算法可以读取。
* ``_truth/household_personas.json``（真值）：每户的家庭画像与成员构成。检测算法不可读取；
  公开文件只保留物业可以合理掌握的 ``registered_residents`` 与 ``care_registered``。

1302、805、503 三户以现有档案为准：户型、面积、批次日期、已登记设备的编码/型号/安装日期
全部沿用档案，档案未登记的部件按同一编码规则补充，并标注 ``in_archive: false``。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import rng
from .params import Params
from .paths import ARCHIVE_HOUSES_FILE, ARCHIVE_PROFILES_FILE

ARCHIVE_HOUSE_IDS = ("1302", "805", "503")

# ---------------------------------------------------------------------------
# 户型模板
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AirConditioner:
    circuit: str
    name: str
    model: str
    room: str


@dataclass(frozen=True)
class LayoutTemplate:
    layout_id: str
    name: str
    area_m2: float
    rooms: tuple[str, ...]
    kitchen_hot_water: bool
    washer_area: str  # "Y" 阳台 / "B" 卫生间
    heater_volume_param: str
    kitchen_sockets: int
    air_conditioners: tuple[AirConditioner, ...]
    archive_template: str  # 型号参照的档案住户
    specs: dict = field(default_factory=dict)


TEMPLATES: dict[str, LayoutTemplate] = {
    "T89": LayoutTemplate(
        layout_id="T89", name="三室两厅一卫", area_m2=89.5,
        rooms=("BEDROOM_MAIN", "BEDROOM_2", "BEDROOM_3", "LIVING", "KITCHEN", "BATHROOM", "BALCONY"),
        kitchen_hot_water=True, washer_area="Y",
        heater_volume_param="water.hot_water.heater_t89_volume_l", kitchen_sockets=2,
        air_conditioners=(
            AirConditioner("AC1", "卧室空调", "KFR-35GW", "BEDROOM_MAIN"),
            AirConditioner("AC2", "客厅空调", "KFR-50GW", "LIVING"),
        ),
        archive_template="1302",
        specs={"K_SINK": "XX-203", "K_ANGLE_VALVE": "AF-105", "K_HOSE": "SH-300", "B_TOILET": "MT-500",
               "B_SHOWER": "HS-200"},
    ),
    "T75": LayoutTemplate(
        layout_id="T75", name="两室两厅一卫", area_m2=75.0,
        rooms=("BEDROOM_MAIN", "BEDROOM_2", "LIVING", "KITCHEN", "BATHROOM", "BALCONY"),
        kitchen_hot_water=False, washer_area="Y",
        heater_volume_param="water.hot_water.heater_small_volume_l", kitchen_sockets=2,
        air_conditioners=(
            AirConditioner("AC1", "客厅空调", "KFR-35GW", "LIVING"),
            AirConditioner("AC2", "卧室空调", "KFR-26GW", "BEDROOM_MAIN"),
        ),
        archive_template="503",
        specs={"K_SINK": "XX-200", "K_ANGLE_VALVE": "AF-102", "K_HOSE": "SH-300", "B_TOILET": "MT-300",
               "B_SHOWER": "HS-180"},
    ),
    "T65": LayoutTemplate(
        layout_id="T65", name="两室一厅一卫", area_m2=65.0,
        rooms=("BEDROOM_MAIN", "BEDROOM_2", "LIVING", "KITCHEN", "BATHROOM"),
        kitchen_hot_water=False, washer_area="B",
        heater_volume_param="water.hot_water.heater_small_volume_l", kitchen_sockets=1,
        air_conditioners=(
            AirConditioner("AC1", "卧室空调", "KFR-26GW", "BEDROOM_MAIN"),
            AirConditioner("AC2", "客厅空调", "KFR-35GW", "LIVING"),
        ),
        archive_template="805",
        specs={"K_SINK": "XX-180", "K_ANGLE_VALVE": "AF-102", "K_HOSE": "SH-300", "B_TOILET": "MT-300",
               "B_SHOWER": "HS-180"},
    ),
}

# ---------------------------------------------------------------------------
# 设备角色：编码前缀、区域、名称、安装日期偏移（相对交付日）、关联拓扑
# 每个 (前缀, 区域) 内按列表顺序编号，顺序与档案 1302 的编号习惯一致。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceRole:
    role: str
    prefix: str
    area: str
    name: str
    category: str
    install_offset_days: int
    segment: str | None = None  # 拓扑后缀，如 "K-AV"；None 表示不关联给排水拓扑
    circuit: str | None = None
    applies: str = "ALL"  # ALL / KITCHEN_HOT / WASHER_Y / WASHER_B / PRV / T89 / AC1 / AC2


DEVICE_ROLES: tuple[DeviceRole, ...] = (
    # 厨房
    DeviceRole("K_SINK", "EQ", "K", "水槽", "plumbing", 0, segment="K-FC"),
    DeviceRole("K_ANGLE_VALVE", "EQ", "K", "角阀", "plumbing", -2, segment="K-AV"),
    DeviceRole("K_HOSE", "EQ", "K", "连接软管", "plumbing", 0, segment="K-HS"),
    DeviceRole("K_ANGLE_VALVE_HOT", "EQ", "K", "热水角阀", "plumbing", -2, segment="K-AVH", applies="KITCHEN_HOT"),
    DeviceRole("K_HOSE_HOT", "EQ", "K", "热水连接软管", "plumbing", 0, segment="K-HSH", applies="KITCHEN_HOT"),
    DeviceRole("K_COLD_PIPE", "PL", "K", "冷水管", "plumbing", -2, segment="K-C"),
    DeviceRole("K_HOT_PIPE", "PL", "K", "热水管", "plumbing", -2, segment="K-H", applies="KITCHEN_HOT"),
    DeviceRole("K_DRAIN_PIPE", "PL", "K", "排水管", "plumbing", -3, segment="WD:K-BR"),
    DeviceRole("K_SOCKET_1", "EL", "K", "厨房插座-1", "electrical", -5, circuit="KT"),
    DeviceRole("K_SOCKET_2", "EL", "K", "厨房插座-2", "electrical", -5, circuit="KT", applies="KITCHEN_SOCKET_2"),
    # 卫生间
    DeviceRole("B_TOILET", "EQ", "B", "马桶", "bathroom", -1, segment="B-WC"),
    DeviceRole("B_SHOWER", "EQ", "B", "花洒", "bathroom", -1, segment="B-SH"),
    DeviceRole("B_BASIN", "EQ", "B", "洗脸盆", "bathroom", -1, segment="B-BS"),
    DeviceRole("B_MIXER", "EQ", "B", "淋浴混水阀", "bathroom", -1, segment="B-MV"),
    DeviceRole("B_HEATER", "EQ", "B", "电热水器", "bathroom", 0, segment="WH", circuit="WH"),
    DeviceRole("B_WASHER_TAP", "EQ", "B", "洗衣机龙头", "bathroom", -1, segment="B-WT", applies="WASHER_B"),
    DeviceRole("B_DRAIN_PIPE", "PL", "B", "排水管", "bathroom", -3, segment="WD:B-BR"),
    DeviceRole("B_FLOOR_DRAIN", "PL", "B", "地漏", "bathroom", -3, segment="WD:B-FD"),
    DeviceRole("B_COLD_PIPE", "PL", "B", "冷水管", "bathroom", -2, segment="B-C"),
    # 档案中仅 1302（T89）登记了热水管；T75/T65 热水器就近安装，出水短管不作为档案设备
    DeviceRole("B_HOT_PIPE", "PL", "B", "热水管", "bathroom", -2, segment="B-H", applies="KITCHEN_HOT"),
    DeviceRole("B_SOCKET", "EL", "B", "卫生间插座", "electrical", -5, circuit="BT"),
    # 阳台
    DeviceRole("Y_WASHER_TAP", "EQ", "Y", "洗衣机龙头", "plumbing", -1, segment="Y-WT", applies="WASHER_Y"),
    DeviceRole("Y_FLOOR_DRAIN", "PL", "Y", "洗衣机地漏", "plumbing", -3, segment="WD:Y-FD", applies="WASHER_Y"),
    # 入户
    DeviceRole("E_METER", "EQ", "E", "智能水表", "plumbing", -2, segment="IN-MT"),
    DeviceRole("E_VALVE", "EQ", "E", "电动总阀", "plumbing", -2, segment="IN-MV"),
    DeviceRole("E_FILTER", "EQ", "E", "前置过滤器", "plumbing", -2, segment="IN-FLT"),
    DeviceRole("E_PRV", "EQ", "E", "支管减压阀", "plumbing", -2, segment="IN-PRV", applies="PRV"),
    # 起居与卧室
    DeviceRole("L_AC1", "EQ", "L", "", "hvac", 2, circuit="AC1", applies="AC1"),
    DeviceRole("L_AC2", "EQ", "L", "", "hvac", 2, circuit="AC2", applies="AC2"),
    DeviceRole("L_LIGHT", "EL", "L", "客厅灯", "electrical", -4, circuit="LT"),
)

ROLE_LOCATIONS = {
    "K_SINK": "厨房操作台下方", "K_ANGLE_VALVE": "厨房水槽下方左侧", "K_HOSE": "厨房水槽下方",
    "K_ANGLE_VALVE_HOT": "厨房水槽下方右侧", "K_HOSE_HOT": "厨房水槽下方", "K_COLD_PIPE": "厨房墙体",
    "K_HOT_PIPE": "厨房墙体", "K_DRAIN_PIPE": "厨房地面下方", "K_SOCKET_1": "厨房操作台上方",
    "K_SOCKET_2": "厨房冰箱位", "B_TOILET": "卫生间", "B_SHOWER": "卫生间淋浴区", "B_BASIN": "卫生间",
    "B_MIXER": "卫生间淋浴区", "B_HEATER": "卫生间吊顶内", "B_WASHER_TAP": "卫生间洗衣机位",
    "B_DRAIN_PIPE": "卫生间地面下方", "B_FLOOR_DRAIN": "卫生间地面", "B_COLD_PIPE": "卫生间墙体",
    "B_HOT_PIPE": "卫生间墙体", "B_SOCKET": "卫生间洗手台旁", "Y_WASHER_TAP": "阳台洗衣机位",
    "Y_FLOOR_DRAIN": "阳台地面", "E_METER": "入户管井", "E_VALVE": "入户管井", "E_FILTER": "入户管井",
    "E_PRV": "入户管井", "L_LIGHT": "客厅天花板",
}

ROOM_NAMES = {
    "BEDROOM_MAIN": "主卧室", "BEDROOM_2": "次卧室", "BEDROOM_3": "书房", "LIVING": "客厅",
    "KITCHEN": "厨房", "BATHROOM": "卫生间", "BALCONY": "阳台",
}

# 档案设备名称 → 角色（按区域字母区分同名设备）
ARCHIVE_NAME_TO_ROLE = {
    ("K", "水槽"): "K_SINK", ("K", "角阀"): "K_ANGLE_VALVE", ("K", "连接软管"): "K_HOSE",
    ("K", "冷水管"): "K_COLD_PIPE", ("K", "热水管"): "K_HOT_PIPE",
    ("K", "厨房插座-1"): "K_SOCKET_1", ("K", "厨房插座"): "K_SOCKET_1", ("K", "厨房插座-2"): "K_SOCKET_2",
    ("B", "马桶"): "B_TOILET", ("B", "花洒"): "B_SHOWER", ("B", "排水管"): "B_DRAIN_PIPE",
    ("B", "地漏"): "B_FLOOR_DRAIN", ("L", "客厅灯"): "L_LIGHT",
}

GENERIC_MANUFACTURER = "模拟品牌"

# 批次部件批号：供应商使用代号，缺陷为虚构，与任何真实品牌无关
COMPONENT_LOTS = {
    "A": {"马桶进水阀": ("配件供应商甲", "FV-2511-A"), "角阀": ("配件供应商丙", "AV-2511-A"),
          "连接软管": ("配件供应商丙", "HS-2511-A"), "地漏": ("配件供应商丁", "FD-2511-A"),
          "断路器": ("电气供应商甲", "MCB-2511-A"), "插座": ("电气供应商乙", "SK-2511-A")},
    "B": {"马桶进水阀": ("配件供应商乙", "FV-2512-B"), "角阀": ("配件供应商丙", "AV-2512-B"),
          "连接软管": ("配件供应商丙", "HS-2512-B"), "地漏": ("配件供应商丁", "FD-2512-B"),
          "断路器": ("电气供应商甲", "MCB-2512-B"), "插座": ("电气供应商乙", "SK-2512-B")},
    "C": {"马桶进水阀": ("配件供应商甲", "FV-2601-C"), "角阀": ("配件供应商丙", "AV-2601-C"),
          "连接软管": ("配件供应商丙", "HS-2601-C"), "地漏": ("配件供应商丁", "FD-2601-C"),
          "断路器": ("电气供应商甲", "MCB-2601-C"), "插座": ("电气供应商乙", "SK-2601-C")},
}

DEVICE_CODE_RE = re.compile(r"^((EQ|PL|EL|DW)-\d{3,4}-[A-Z]-\d{2}|DW-\d{3,4}-\d{2})$")
SEGMENT_CODE_RE = re.compile(r"^((WS|WD|CB|ST)-[A-Z0-9]+(-[A-Z0-9]+)*|ST0[1-6](-F\d{1,2}){0,2})$")


# ---------------------------------------------------------------------------
# 基础计算
# ---------------------------------------------------------------------------


def house_ids(params: Params) -> list[str]:
    floors = params["building.floors"]
    positions = params["building.positions_per_floor"]
    return [f"{f}0{p}" for f in range(1, floors + 1) for p in range(1, positions + 1)]


def split_house_id(house_id: str) -> tuple[int, str]:
    return int(house_id[:-2]), house_id[-2:]


def batch_of_floor(params: Params, floor: int) -> str:
    for batch_id, spec in params["building.batches"].items():
        low, high = spec["floors"]
        if low <= floor <= high:
            return batch_id
    raise ValueError(f"楼层 {floor} 不属于任何批次")


def entry_pressure(params: Params, floor: int) -> dict:
    """入户静压（MPa）与是否加装减压阀。"""
    height = entry_height_m(params, floor)
    per_m = params["water.supply.pressure_per_m_mpa"]
    zone_id, zone = zone_of_floor(params, floor)
    if zone["source"] == "MUNICIPAL":
        source_mpa = params["water.supply.municipal_ground_pressure_mpa"]
    else:
        source_mpa = zone["outlet_mpa"]
    raw = source_mpa - per_m * height
    has_prv = raw > params["water.supply.entry_pressure_max_mpa"]
    return {"supply_zone": zone_id, "raw_static_mpa": round(raw, 4), "has_prv": bool(has_prv)}


def entry_height_m(params: Params, floor: int) -> float:
    return (floor - 1) * params["building.floor_height_m"] + params["building.entry_height_above_floor_m"]


def zone_of_floor(params: Params, floor: int) -> tuple[str, dict]:
    for zone_id, zone in params["water.supply.zones"].items():
        low, high = zone["floors"]
        if low <= floor <= high:
            return zone_id, zone
    raise ValueError(f"楼层 {floor} 不属于任何供水分区")


def _date(text: str) -> date:
    return date.fromisoformat(text)


# ---------------------------------------------------------------------------
# 拓扑
# ---------------------------------------------------------------------------


def supply_network(house_id: str, t: LayoutTemplate, has_prv: bool) -> list[dict]:
    """给水拓扑（有向无环图）：parents 为上游节点，混水器具有冷、热两个上游。"""
    h = house_id

    def seg(suffix, name, kind, parents, side="COLD", area=None, fixture=None, loss=None):
        return {
            "segment_code": f"WS-{h}-{suffix}", "name": name, "kind": kind,
            "parents": [f"WS-{h}-{p}" for p in parents], "side": side,
            "area": area or suffix.split("-")[0], "fixture": fixture, "loss_param": loss,
        }

    loss = "water.pipes."
    nodes = [
        seg("IN-MT", "智能水表", "METER", [], area="IN", loss=loss + "loss_meter_mpa_at_0p30lps"),
        seg("IN-MV", "电动总阀", "VALVE", ["IN-MT"], area="IN"),
    ]
    upstream = "IN-MV"
    if has_prv:
        nodes.append(seg("IN-PRV", "支管减压阀", "PRV", ["IN-MV"], area="IN"))
        upstream = "IN-PRV"
    nodes += [
        seg("IN-FLT", "前置过滤器", "FILTER", [upstream], area="IN", loss=loss + "loss_entry_filter_mpa_at_0p30lps"),
        seg("IN-MAIN", "户内主管", "PIPE", ["IN-FLT"], area="IN", loss=loss + "loss_main_mpa_at_0p30lps"),
        # 厨房冷水
        seg("K-C", "厨房冷水支路", "PIPE", ["IN-MAIN"], loss=loss + "loss_branch_mpa_at_0p20lps"),
        seg("K-AV", "厨房冷水角阀", "ANGLE_VALVE", ["K-C"], loss=loss + "loss_angle_valve_hose_mpa_at_0p15lps"),
        seg("K-HS", "厨房冷水连接软管", "HOSE", ["K-AV"]),
        # 卫生间冷水
        seg("B-C", "卫生间冷水支路", "PIPE", ["IN-MAIN"], loss=loss + "loss_branch_mpa_at_0p20lps"),
        seg("B-AVT", "马桶角阀", "ANGLE_VALVE", ["B-C"], loss=loss + "loss_angle_valve_hose_mpa_at_0p15lps"),
        seg("B-WC", "马桶进水阀", "FIXTURE", ["B-AVT"], fixture="TOILET"),
        seg("B-AVB", "洗脸盆冷水角阀", "ANGLE_VALVE", ["B-C"], loss=loss + "loss_angle_valve_hose_mpa_at_0p15lps"),
        # 热水器
        seg("WH-FLT", "热水器进水滤网", "HEATER_FILTER", ["IN-MAIN"], area="WH"),
        seg("WH", "电热水器", "HEATER", ["WH-FLT"], side="HOT", area="WH", loss=loss + "loss_heater_mpa_at_0p15lps"),
        seg("B-H", "卫生间热水支路", "PIPE", ["WH"], side="HOT", loss=loss + "loss_branch_mpa_at_0p20lps"),
        seg("B-AVBH", "洗脸盆热水角阀", "ANGLE_VALVE", ["B-H"], side="HOT",
            loss=loss + "loss_angle_valve_hose_mpa_at_0p15lps"),
        seg("B-BS", "洗脸盆龙头", "FIXTURE", ["B-AVB", "B-AVBH"], side="MIXED", fixture="BASIN"),
        seg("B-MV", "淋浴混水阀", "MIXER", ["B-C", "B-H"], side="MIXED", loss=loss + "loss_mixer_mpa_at_0p15lps"),
        seg("B-SH", "花洒头", "FIXTURE", ["B-MV"], side="MIXED", fixture="SHOWER"),
    ]
    if t.kitchen_hot_water:
        nodes += [
            seg("K-H", "厨房热水支路", "PIPE", ["WH"], side="HOT", loss=loss + "loss_branch_mpa_at_0p20lps"),
            seg("K-AVH", "厨房热水角阀", "ANGLE_VALVE", ["K-H"], side="HOT",
                loss=loss + "loss_angle_valve_hose_mpa_at_0p15lps"),
            seg("K-HSH", "厨房热水连接软管", "HOSE", ["K-AVH"], side="HOT"),
            seg("K-FC", "厨房龙头", "FIXTURE", ["K-HS", "K-HSH"], side="MIXED", fixture="KITCHEN_FAUCET"),
        ]
    else:
        nodes.append(seg("K-FC", "厨房龙头", "FIXTURE", ["K-HS"], fixture="KITCHEN_FAUCET"))
    if t.washer_area == "Y":
        nodes += [
            seg("Y-C", "阳台冷水支路", "PIPE", ["IN-MAIN"], loss=loss + "loss_branch_mpa_at_0p20lps"),
            seg("Y-WT", "洗衣机龙头", "FIXTURE", ["Y-C"], fixture="WASHER"),
        ]
    else:
        nodes.append(seg("B-WT", "洗衣机龙头", "FIXTURE", ["B-C"], fixture="WASHER"))
    return nodes


def drain_network(house_id: str, t: LayoutTemplate, stack_id: str, floor: int) -> list[dict]:
    """排水拓扑：排水点 → 横支管 → 立管接入点。receives 为汇入该排水点的器具。"""
    h = house_id

    def seg(suffix, name, kind, downstream, receives=(), tau_param=None):
        return {
            "segment_code": f"WD-{h}-{suffix}", "name": name, "kind": kind,
            "downstream": downstream, "receives": list(receives), "area": suffix.split("-")[0],
            "tau_param": tau_param,
        }

    stack_joint = f"{stack_id}-F{floor}"
    bath_fd_receives = ["SHOWER"] + (["WASHER"] if t.washer_area == "B" else [])
    nodes = [
        seg("B-FD", "卫生间地漏", "FLOOR_DRAIN", f"WD-{h}-B-BR", bath_fd_receives, "water.drain.tau_floor_drain_s"),
        seg("B-BS", "洗脸盆存水弯", "TRAP", f"WD-{h}-B-BR", ["BASIN"], "water.drain.tau_basin_trap_s"),
        seg("B-WC", "马桶排水口", "TOILET_OUTLET", f"WD-{h}-B-BR", ["TOILET"]),
        seg("B-BR", "卫生间排水横支管", "BRANCH", stack_joint),
        seg("K-SK", "厨房水槽存水弯", "TRAP", f"WD-{h}-K-BR", ["KITCHEN_FAUCET"], "water.drain.tau_kitchen_trap_s"),
        seg("K-BR", "厨房排水横支管", "BRANCH", stack_joint),
    ]
    if t.washer_area == "Y":
        nodes += [
            seg("Y-FD", "洗衣机地漏", "FLOOR_DRAIN", f"WD-{h}-Y-BR", ["WASHER"], "water.drain.tau_balcony_drain_s"),
            seg("Y-BR", "阳台排水横支管", "BRANCH", stack_joint),
        ]
    return nodes


def circuits(house_id: str, t: LayoutTemplate, params: Params) -> list[dict]:
    ratings = params["power.breakers.ratings_a"]
    rcd = params["power.breakers.rcd_trip_ma"]
    base = [
        ("LT", "照明回路", "LT", list(t.rooms)),
        ("SK", "普通插座回路", "SK", [r for r in t.rooms if r not in ("KITCHEN", "BATHROOM")]),
        ("KT", "厨房插座回路", "KT", ["KITCHEN"]),
        ("BT", "卫生间插座回路", "BT", ["BATHROOM"]),
        ("WH", "热水器回路", "WH", ["BATHROOM"]),
    ]
    out = [
        {"circuit_code": f"CB-{house_id}-{code}", "name": name, "rating_a": ratings[kind],
         "rcd_trip_ma": rcd[kind], "rooms": rooms, "has_terminal_temp": True, "has_residual_current": True}
        for code, name, kind, rooms in base
    ]
    for ac in t.air_conditioners:
        out.append({
            "circuit_code": f"CB-{house_id}-{ac.circuit}", "name": f"{ac.name}回路", "rating_a": ratings["AC"],
            "rcd_trip_ma": rcd["AC"], "rooms": [ac.room], "has_terminal_temp": True, "has_residual_current": True,
        })
    return out


def sensors(house_id: str, t: LayoutTemplate, care_registered: bool, has_prv: bool) -> list[dict]:
    h = house_id

    def sn(code, kind, target, room=None):
        return {"sensor_code": code, "type": kind, "target": target, "room": room}

    out = [
        sn(f"SN-{h}-IN-FL01", "FL", f"WS-{h}-IN-MT"),
        sn(f"SN-{h}-IN-PR01", "PR", f"WS-{h}-{'IN-PRV' if has_prv else 'IN-MV'}"),
        sn(f"SN-{h}-IN-PR02", "PR", f"WS-{h}-IN-MAIN"),
        sn(f"SN-{h}-K-FL01", "FL", f"WS-{h}-K-C"),
        sn(f"SN-{h}-B-FL01", "FL", f"WS-{h}-B-C"),
        sn(f"SN-{h}-B-FL02", "FL", f"WS-{h}-B-H"),
        sn(f"SN-{h}-K-PR01", "PR", f"WS-{h}-K-HS"),
        sn(f"SN-{h}-B-PR01", "PR", f"WS-{h}-B-MV"),
        sn(f"SN-{h}-WH-TP01", "TP", f"WS-{h}-WH-FLT"),
        sn(f"SN-{h}-WH-TP02", "TP", f"WS-{h}-WH"),
        sn(f"SN-{h}-B-LV01", "LV", f"WD-{h}-B-FD"),
        sn(f"SN-{h}-B-LV02", "LV", f"WD-{h}-B-BS"),
        sn(f"SN-{h}-K-LV01", "LV", f"WD-{h}-K-SK"),
        sn(f"SN-{h}-K-WL01", "WL", f"WS-{h}-K-HS", "KITCHEN"),
        sn(f"SN-{h}-B-WL01", "WL", f"WD-{h}-B-FD", "BATHROOM"),
        sn(f"SN-{h}-WH-WL01", "WL", f"WS-{h}-WH", "BATHROOM"),
        sn(f"SN-{h}-L-PS01", "PS", None, "LIVING"),
        sn(f"SN-{h}-B-PS01", "PS", None, "BATHROOM"),
    ]
    if t.kitchen_hot_water:
        out.append(sn(f"SN-{h}-K-FL02", "FL", f"WS-{h}-K-H"))
    if t.washer_area == "Y":
        out += [sn(f"SN-{h}-Y-FL01", "FL", f"WS-{h}-Y-C"), sn(f"SN-{h}-Y-LV01", "LV", f"WD-{h}-Y-FD")]
    for i, ac in enumerate(t.air_conditioners, start=1):
        out.append(sn(f"SN-{h}-L-TH{i:02d}", "TH", f"CB-{h}-{ac.circuit}", ac.room))
    if care_registered:
        # 关怀服务住户经授权加装卧室雷达与智能音箱
        out.append(sn(f"SN-{h}-L-PS02", "PS", None, "BEDROOM_MAIN"))
        out.append({"sensor_code": f"SPK-{h}-L-01", "type": "SPEAKER", "target": None, "room": "LIVING"})
    return sorted(out, key=lambda s: s["sensor_code"])


# ---------------------------------------------------------------------------
# 设备（扩展档案）
# ---------------------------------------------------------------------------


def _role_applies(role: DeviceRole, t: LayoutTemplate, has_prv: bool) -> bool:
    return {
        "ALL": True,
        "KITCHEN_HOT": t.kitchen_hot_water,
        "KITCHEN_SOCKET_2": t.kitchen_sockets >= 2,
        "WASHER_Y": t.washer_area == "Y",
        "WASHER_B": t.washer_area == "B",
        "PRV": has_prv,
        "AC1": len(t.air_conditioners) >= 1,
        "AC2": len(t.air_conditioners) >= 2,
    }[role.applies]


def _archive_role(area: str, name: str, t: LayoutTemplate) -> str | None:
    if area == "L" and name.endswith("空调"):
        room = "LIVING" if name.startswith("客厅") else "BEDROOM_MAIN"
        for ac in t.air_conditioners:
            if ac.room == room:
                return f"L_{ac.circuit}"
        return None
    return ARCHIVE_NAME_TO_ROLE.get((area, name))


def devices(house_id: str, t: LayoutTemplate, has_prv: bool, delivery: date,
            archive_components: list[dict] | None) -> list[dict]:
    """生成设备清单。档案住户先放入档案设备，再按角色补齐缺失部件。"""
    h = house_id
    out: list[dict] = []
    used_numbers: dict[tuple[str, str], set[int]] = defaultdict(set)
    filled_roles: set[str] = set()

    for comp in archive_components or []:
        parts = comp["id"].split("-")
        if parts[0] == "DW":  # 档案门窗编码无区域段：DW-1302-01
            role = None
        else:
            prefix, _, area, number = parts
            role = _archive_role(area, comp["name"], t)
            used_numbers[(prefix, area)].add(int(number))
        role_def = next((r for r in DEVICE_ROLES if r.role == role), None)
        out.append({
            "device_code": comp["id"], "name": comp["name"], "role": role or "OTHER",
            "category": role_def.category if role_def else "doors_windows",
            "spec": comp.get("spec"), "location": comp.get("location"),
            "install_date": comp.get("installDate"), "manufacturer": comp.get("manufacturer"),
            "in_archive": True,
            "segment_code": _segment_of(role_def, h),
            "circuit_code": f"CB-{h}-{role_def.circuit}" if role_def and role_def.circuit else None,
        })
        if role:
            filled_roles.add(role)

    for role_def in DEVICE_ROLES:
        if role_def.role in filled_roles or not _role_applies(role_def, t, has_prv):
            continue
        key = (role_def.prefix, role_def.area)
        number = 1
        while number in used_numbers[key]:
            number += 1
        used_numbers[key].add(number)
        name, spec, location = role_def.name, t.specs.get(role_def.role), ROLE_LOCATIONS.get(role_def.role)
        if role_def.role in ("L_AC1", "L_AC2"):
            ac = t.air_conditioners[int(role_def.role[-1]) - 1]
            name, spec, location = ac.name, ac.model, ROOM_NAMES[ac.room]
        out.append({
            "device_code": f"{role_def.prefix}-{h}-{role_def.area}-{number:02d}", "name": name,
            "role": role_def.role, "category": role_def.category, "spec": spec, "location": location,
            "install_date": (delivery + timedelta(days=role_def.install_offset_days)).isoformat(),
            "manufacturer": GENERIC_MANUFACTURER, "in_archive": False,
            "segment_code": _segment_of(role_def, h),
            "circuit_code": f"CB-{h}-{role_def.circuit}" if role_def.circuit else None,
        })
    return sorted(out, key=lambda d: d["device_code"])


def _segment_of(role_def: DeviceRole | None, house_id: str) -> str | None:
    if role_def is None or role_def.segment is None:
        return None
    if role_def.segment.startswith("WD:"):
        return f"WD-{house_id}-{role_def.segment[3:]}"
    return f"WS-{house_id}-{role_def.segment}"


# ---------------------------------------------------------------------------
# 画像分配
# ---------------------------------------------------------------------------


def allocate_personas(params: Params, layout_of: dict[str, str]) -> dict[str, str]:
    """按户型分配画像；1302/805/503 固定，其余按种子随机洗牌。"""
    allocation = params["behavior.persona_allocation"]
    fixed = params["behavior.fixed_personas"]
    seed = params["seeds.building"]
    result: dict[str, str] = dict(fixed)
    for layout_id, counts in allocation.items():
        pool: list[str] = []
        remaining = Counter(counts)
        for house_id, persona in fixed.items():
            if layout_of[house_id] == layout_id:
                if remaining[persona] <= 0:
                    raise ValueError(f"固定画像 {house_id}={persona} 超出户型 {layout_id} 的名额")
                remaining[persona] -= 1
        for persona, n in sorted(remaining.items()):
            pool += [persona] * n
        houses = sorted(h for h, lay in layout_of.items() if lay == layout_id and h not in fixed)
        if len(pool) != len(houses):
            raise ValueError(f"户型 {layout_id} 画像名额 {len(pool)} 与住户数 {len(houses)} 不一致")
        order = rng.stream(seed, "persona", layout_id).permutation(len(pool))
        for house_id, idx in zip(houses, order):
            result[house_id] = pool[idx]
    return result


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------


def archive_components(archive: dict | None) -> list[dict] | None:
    """档案 components 按类别分组，这里展开为列表。"""
    if archive is None:
        return None
    return [comp for group in archive["components"].values() for comp in group]


def load_archive() -> tuple[dict, dict]:
    with open(ARCHIVE_HOUSES_FILE, encoding="utf-8") as f:
        houses = {h["houseId"]: h for h in json.load(f)}
    with open(ARCHIVE_PROFILES_FILE, encoding="utf-8") as f:
        profiles = json.load(f)
    return houses, profiles


def build(params: Params) -> tuple[dict, dict]:
    """返回 (公开楼栋数据, 画像真值)。"""
    archive_houses, archive_profiles = load_archive()
    layout_by_position = params["building.layout_by_position"]
    phase_by_position = params["building.phase_by_position"]
    batches = params["building.batches"]
    personas_spec = params["behavior.personas"]

    ids = house_ids(params)
    layout_of = {h: layout_by_position[split_house_id(h)[1]] for h in ids}
    personas = allocate_personas(params, layout_of)

    houses = []
    for h in ids:
        floor, position = split_house_id(h)
        t = TEMPLATES[layout_of[h]]
        batch_id = batch_of_floor(params, floor)
        delivery = _date(batches[batch_id]["delivery_date"])
        pressure = entry_pressure(params, floor)
        persona = personas[h]
        members = personas_spec[persona]["members"]
        care = bool(personas_spec[persona].get("care_registered", False))
        stack_id = f"ST{position}"
        archive = archive_houses.get(h)
        entry_static = params["water.supply.prv_setpoint_mpa"] if pressure["has_prv"] else pressure["raw_static_mpa"]
        houses.append({
            "house_id": h,
            "room_no": f"{h}室",
            "floor": floor,
            "floor_label": f"{floor}层",
            "position": position,
            "layout_id": t.layout_id,
            "layout": t.name,
            "area_m2": t.area_m2,
            "rooms": list(t.rooms),
            "batch_id": batch_id,
            "mic_module_id": archive["micModuleId"] if archive else f"MIC-1F-{floor}-{h}",
            "production_date": batches[batch_id]["production_date"],
            "delivery_date": archive["deliveryDate"] if archive else batches[batch_id]["delivery_date"],
            "in_archive": archive is not None,
            "registered_residents": len(members),
            "care_registered": care,
            "supply_zone": pressure["supply_zone"],
            "has_prv": pressure["has_prv"],
            "raw_static_pressure_mpa": pressure["raw_static_mpa"],
            "entry_static_pressure_mpa": round(entry_static, 4),
            "drain_stack": stack_id,
            "phase": phase_by_position[position],
            "heater_volume_l": params[t.heater_volume_param],
            "pipeline_layout": archive_profiles[h]["pipelineLayout"] if h in archive_profiles else None,
            "supply_network": supply_network(h, t, pressure["has_prv"]),
            "drain_network": drain_network(h, t, stack_id, floor),
            "circuits": circuits(h, t, params),
            "electric_meter": f"CB-{h}-MAIN",
            "sensors": sensors(h, t, care, pressure["has_prv"]),
            "devices": devices(h, t, pressure["has_prv"], delivery, archive_components(archive)),
        })

    floors = params["building.floors"]
    stacks = []
    for position in sorted(layout_by_position):
        stack_id = f"ST{position}"
        stacks.append({
            "stack_id": stack_id,
            "position": position,
            "houses": [f"{f}0{int(position)}" for f in range(1, floors + 1)],
            "segments": [f"{stack_id}-F{f - 1}-F{f}" for f in range(1, floors + 1)],
            "note": "ST0n-F{a}-F{b} 为第 a 层与第 b 层接入点之间的立管段；F0 表示首层以下至室外排出管",
        })

    building = {
        "meta": {
            "schema": "sim_building v1.0",
            "generator": "data/scripts/build_building.py",
            "building_seed": params["seeds.building"],
            "params_version": params.raw["meta"]["version"],
            "data_source": "SIMULATED",
            "note": "扩展的一房一码档案。1302/805/503 沿用现有档案；其余 105 户仅存在于模拟数据中。缺陷与画像真值不在本文件中。",
        },
        "building": {
            "building": "1栋", "unit": "1单元", "floors": floors,
            "positions_per_floor": params["building.positions_per_floor"],
            "floor_height_m": params["building.floor_height_m"],
            "location_hint": params["building.location_hint"],
        },
        "batches": [
            {"batch_id": b, "floors": spec["floors"], "production_date": spec["production_date"],
             "delivery_date": spec["delivery_date"],
             "component_lots": [{"component": c, "supplier": s, "lot": lot} for c, (s, lot) in COMPONENT_LOTS[b].items()]}
            for b, spec in batches.items()
        ],
        "supply_zones": [
            {"zone_id": zone_id, "floors": zone["floors"], "source": zone["source"],
             "source_pressure_mpa": zone.get("outlet_mpa", params["water.supply.municipal_ground_pressure_mpa"]),
             "pump": f"WS-BLDG-PUMP-{zone_id}" if zone["source"] == "BOOSTER" else None,
             "prv_setpoint_mpa": params["water.supply.prv_setpoint_mpa"],
             "building_meter": f"WS-BLDG-{zone_id}-MT"}
            for zone_id, zone in params["water.supply.zones"].items()
        ],
        "stacks": stacks,
        "building_points": [
            {"code": "WS-BLDG-LOW-MT", "name": "低区总水表"},
            {"code": "WS-BLDG-MID-MT", "name": "中区总水表"},
            {"code": "WS-BLDG-HIGH-MT", "name": "高区总水表"},
            {"code": "WS-BLDG-PUMP-MID", "name": "中区二次供水变频泵"},
            {"code": "WS-BLDG-PUMP-HIGH", "name": "高区二次供水变频泵"},
            {"code": "CB-BLDG-PUB", "name": "公区用电（照明、电梯、水泵）"},
            {"code": "SN-BLDG-OUT-TH01", "name": "室外温湿度"},
        ],
        "layouts": [
            {"layout_id": t.layout_id, "name": t.name, "area_m2": t.area_m2, "rooms": list(t.rooms),
             "kitchen_hot_water": t.kitchen_hot_water, "washer_area": t.washer_area,
             "air_conditioners": [ac.__dict__ for ac in t.air_conditioners], "archive_template": t.archive_template}
            for t in TEMPLATES.values()
        ],
        "houses": houses,
    }

    truth = {
        "meta": {
            "schema": "household_personas v1.0",
            "generator": "data/scripts/build_building.py",
            "building_seed": params["seeds.building"],
            "visibility": "TRUTH_ONLY：检测算法、处理链路与百炼均不得读取",
        },
        "households": {
            h: {"persona": personas[h], "persona_label": personas_spec[personas[h]]["label"],
                "members": personas_spec[personas[h]]["members"]}
            for h in ids
        },
    }
    return building, truth


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------


def check(building: dict, truth: dict, params: Params) -> list[tuple[str, bool, str]]:
    """返回 [(检查项, 是否通过, 说明)]。"""
    results: list[tuple[str, bool, str]] = []
    add = lambda name, ok, detail="": results.append((name, bool(ok), detail))  # noqa: E731
    houses = {h["house_id"]: h for h in building["houses"]}
    archive_houses, _ = load_archive()

    add("住户总数为 108", len(houses) == 108, f"{len(houses)} 户")

    for hid, arch in archive_houses.items():
        h = houses[hid]
        dev = {d["device_code"]: d for d in h["devices"]}
        comps = archive_components(arch)
        missing = [c["id"] for c in comps if c["id"] not in dev]
        mismatched = [c["id"] for c in comps if c["id"] in dev and (
            dev[c["id"]]["spec"] != c.get("spec") or dev[c["id"]]["install_date"] != c.get("installDate"))]
        ok = (h["layout"] == arch["layout"] and h["area_m2"] == arch["area"] and h["floor_label"] == arch["floor"]
              and h["delivery_date"] == arch["deliveryDate"] and h["mic_module_id"] == arch["micModuleId"]
              and not missing and not mismatched)
        add(f"{hid} 与档案一致（户型/面积/楼层/交付日/模块号/设备）", ok,
            f"缺失 {missing} 不一致 {mismatched}" if not ok else f"{len(comps)} 件档案设备全部保留")
        add(f"{hid} 批次交付日期与档案一致",
            next(b for b in building["batches"] if b["batch_id"] == h["batch_id"])["delivery_date"] == arch["deliveryDate"],
            h["batch_id"])

    fixed = params["behavior.fixed_personas"]
    add("固定画像与契约样例一致", all(truth["households"][h]["persona"] == p for h, p in fixed.items()), str(fixed))
    add("503 为关怀登记住户（契约样例 05）", houses["503"]["care_registered"], "")
    add("1302 登记人数为 3（契约样例月报）", houses["1302"]["registered_residents"] == 3, "")

    persona_counts = Counter(v["persona"] for v in truth["households"].values())
    expected = Counter()
    for counts in params["behavior.persona_allocation"].values():
        expected.update(counts)
    add("画像数量符合分配表", persona_counts == expected, dict(sorted(persona_counts.items())).__repr__())

    by_layout = defaultdict(Counter)
    for hid, v in truth["households"].items():
        by_layout[houses[hid]["layout_id"]][v["persona"]] += 1
    add("各户型画像名额符合分配表",
        all(by_layout[lay] == Counter(c) for lay, c in params["behavior.persona_allocation"].items()),
        {k: dict(v) for k, v in by_layout.items()}.__repr__())

    add("批次各 36 户", Counter(h["batch_id"] for h in houses.values()) == Counter({"A": 36, "B": 36, "C": 36}), "")
    add("相别均衡（每相 36 户）", Counter(h["phase"] for h in houses.values()) == Counter({"L1": 36, "L2": 36, "L3": 36}), "")
    add("户型各 36 户", Counter(h["layout_id"] for h in houses.values()) == Counter({"T89": 36, "T75": 36, "T65": 36}), "")

    max_entry = params["water.supply.entry_pressure_max_mpa"]
    pressures = [h["entry_static_pressure_mpa"] for h in houses.values()]
    add("入户静压均 ≤ 0.35 MPa 且 ≥ 0.15 MPa", all(0.15 <= p <= max_entry + 1e-9 for p in pressures),
        f"范围 {min(pressures):.3f}–{max(pressures):.3f} MPa")
    prv_floors = sorted({h["floor"] for h in houses.values() if h["has_prv"]})
    expected_prv = sorted({h["floor"] for h in houses.values() if h["raw_static_pressure_mpa"] > max_entry})
    add("减压阀恰好装在未减压静压 > 0.35 MPa 的楼层", prv_floors == expected_prv and len(prv_floors) > 0,
        f"加装减压阀楼层 {prv_floors}")

    zone_limit = params["water.supply.zone_static_pressure_max_mpa"]
    zone_max = {z: max(h["raw_static_pressure_mpa"] for h in houses.values() if h["supply_zone"] == z)
                for z in params["water.supply.zones"]}
    add("各分区最低用水点静压 ≤ 0.45 MPa", all(v <= zone_limit for v in zone_max.values()),
        ", ".join(f"{z} {v:.3f}" for z, v in zone_max.items()))
    zones_by_batch = {b: sorted({h["supply_zone"] for h in houses.values() if h["batch_id"] == b}) for b in "ABC"}
    add("批次与供水分区不完全重合（批次对比可按分区分层，避免与水压混杂）",
        sum(len(z) > 1 for z in zones_by_batch.values()) >= 2, str(zones_by_batch))

    all_device_codes = [d["device_code"] for h in houses.values() for d in h["devices"]]
    add("设备编码全局唯一", len(all_device_codes) == len(set(all_device_codes)), f"{len(all_device_codes)} 件")
    add("设备编码符合契约正则", all(DEVICE_CODE_RE.match(c) for c in all_device_codes), "")

    segments = [s["segment_code"] for h in houses.values() for s in h["supply_network"] + h["drain_network"]]
    segments += [c["circuit_code"] for h in houses.values() for c in h["circuits"]]
    segments += [seg for st in building["stacks"] for seg in st["segments"]]
    add("拓扑编码全局唯一", len(segments) == len(set(segments)), f"{len(segments)} 个")
    add("拓扑编码符合契约 segmentCode 正则（2.1）", all(SEGMENT_CODE_RE.match(s) for s in segments), "")

    contract_codes = {"WS-1302-B-SH", "WS-1302-B-MV", "WS-805-K-HS", "WS-805-K-AV", "WS-805-IN-MV", "CB-1302-KT"}
    present = set(segments)
    add("契约样例引用的拓扑编码均存在", contract_codes <= present, f"缺失 {sorted(contract_codes - present)}")
    sample_devices = {"EQ-1302-B-02", "EQ-805-K-02"}
    add("契约样例引用的设备编码均存在", sample_devices <= set(all_device_codes), "")
    sample_sensors = {"SN-805-K-WL01", "SPK-503-L-01"}
    all_sensors = {s["sensor_code"] for h in houses.values() for s in h["sensors"]}
    add("契约样例引用的传感器编码均存在", sample_sensors <= all_sensors, "")

    dangling = []
    for h in houses.values():
        codes = {s["segment_code"] for s in h["supply_network"]}
        for s in h["supply_network"]:
            dangling += [p for p in s["parents"] if p not in codes]
        drain_codes = {s["segment_code"] for s in h["drain_network"]}
        for s in h["drain_network"]:
            if s["downstream"].startswith("WD-") and s["downstream"] not in drain_codes:
                dangling.append(s["downstream"])
        dangling += [s["target"] for s in h["sensors"] if s["target"] and s["target"] not in codes | drain_codes
                     and not s["target"].startswith("CB-")]
    add("拓扑引用无悬空节点", not dangling, f"{dangling[:5]}")

    fixtures_ok = all(
        {s["fixture"] for s in h["supply_network"] if s["fixture"]}
        == {r for s in h["drain_network"] for r in s["receives"]}
        for h in houses.values()
    )
    add("每个用水器具都有对应排水点（水量平衡前提）", fixtures_ok, "")

    care_sensors = all(
        any(s["sensor_code"].startswith(f"SPK-{h['house_id']}") for s in h["sensors"]) == h["care_registered"]
        for h in houses.values()
    )
    add("卧室雷达与音箱仅安装于关怀登记住户", care_sensors, f"{sum(h['care_registered'] for h in houses.values())} 户")
    add("公开楼栋文件不含画像字段", "persona" not in json.dumps(building, ensure_ascii=False), "")
    return results
