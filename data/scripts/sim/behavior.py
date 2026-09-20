"""行为模型（任务 1.4）：住户习惯 → 逐日作息 → 器具与电器使用事件。

分三层，均可复现：

1. **住户习惯**（``draw_profiles``）：按画像的总体分布为每户、每位成员抽取个人参数
   （起床时间均值、淋浴时长、开水龙头的习惯开度、空调开机温度……）。随机流为
   (数据集种子, 户号, "habits")，同一数据集内固定，dev 与 test 相互独立。
2. **外出计划**（``plan_absences``）：暑期出游、出差、周末外出、访客与空置房业主到访。
3. **逐日行为**（``simulate_house``）：每人每天的在家/外出/睡眠区间，以及落在区间内的
   用水、用电、照明事件，空调使用意图与热水器启用时段。

本层只描述"人做了什么"：水流量、功率、室温由物理模型（1.5/1.6）根据这里的开度、
设定温度与意图计算。``estimate_water_l`` 仅用于行为层自检的量级估算。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import rng as rngmod
from .params import Params

# 器具 → (拓扑后缀, 排水点所在区域)；洗衣机位置由户型决定
WATER_DEVICES = ("TOILET", "BASIN", "SHOWER", "KITCHEN_FAUCET", "WASHER")
POWER_DEVICES = ("KETTLE", "MICROWAVE", "RICE_COOKER", "RANGE_HOOD", "TV", "PC", "HAIR_DRYER", "BATH_FAN", "LIGHT")

APPLIANCE_CIRCUIT = {
    "KETTLE": "KT", "MICROWAVE": "KT", "RICE_COOKER": "KT", "RANGE_HOOD": "KT",
    "TV": "SK", "PC": "SK", "HAIR_DRYER": "BT", "BATH_FAN": "BT", "LIGHT": "LT",
}
APPLIANCE_POWER_PARAM = {
    "KETTLE": "power.appliances.kettle_w", "MICROWAVE": "power.appliances.microwave_w",
    "RICE_COOKER": "power.appliances.rice_cooker_avg_w", "RANGE_HOOD": "power.appliances.range_hood_w",
    "TV": "power.appliances.tv_w", "PC": "power.appliances.pc_w", "HAIR_DRYER": "power.appliances.hair_dryer_w",
    "BATH_FAN": "power.appliances.bath_fan_w",
}

AWAY, HOME, SLEEP, NAP = "AWAY", "HOME_AWAKE", "SLEEP", "NAP"
MIN_EVENT_S = 5.0  # 区间求交可能产生毫秒级碎片，短于此值的用电/照明事件丢弃


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Person:
    person_id: str
    role: str
    habits: dict


@dataclass
class HouseholdProfile:
    house_id: str
    persona: str
    layout_id: str
    washer_area: str
    kitchen_hot_water: bool
    bedroom_ac_circuit: str | None
    living_ac_circuit: str | None
    persons: list[Person]
    habits: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "house_id": self.house_id, "persona": self.persona, "layout_id": self.layout_id,
            "habits": self.habits,
            "persons": [{"person_id": p.person_id, "role": p.role, "habits": p.habits} for p in self.persons],
        }


@dataclass
class DayContext:
    day: date
    weekend: bool
    school_day: bool
    vacation: bool
    sunrise_h: float
    sunset_h: float


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _clip(x: float, lo: float, hi: float) -> float:
    return float(min(max(x, lo), hi))


def _norm_pos(g: np.random.Generator, mean: float, sd: float, lo: float = 0.0) -> float:
    return max(lo, float(g.normal(mean, sd)))


def sun_times(day: date, lat_deg: float, lon_deg: float, tz_hours: float = 8.0) -> tuple[float, float]:
    """近似日出、日落时刻（本地小时）。误差约 ±5 分钟，足够用于照明判断。"""
    n = day.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + n) / 365)
    b = 2 * math.pi * (n - 81) / 364
    eot_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    solar_noon = 12 + (tz_hours * 15 - lon_deg) * 4 / 60 - eot_min / 60
    cos_ha = -math.tan(math.radians(lat_deg)) * math.tan(decl)
    half_day = math.degrees(math.acos(_clip(cos_ha, -1, 1))) / 15
    return solar_noon - half_day, solar_noon + half_day


def subtract(intervals: list[tuple[float, float]], cut: tuple[float, float]) -> list[tuple[float, float]]:
    """从区间列表中扣除一个区间。"""
    out = []
    cs, ce = cut
    for s, e in intervals:
        if ce <= s or cs >= e:
            out.append((s, e))
            continue
        if cs > s:
            out.append((s, cs))
        if ce < e:
            out.append((ce, e))
    return [(s, e) for s, e in out if e - s > 1e-6]


def merge(intervals: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if e - s > 1e-6:
                out.append((s, e))
    return merge(out)


def contains(intervals: list[tuple[float, float]], t: float) -> bool:
    return any(s <= t < e for s, e in intervals)


def day_contexts(params: Params, start: date, end: date) -> list[DayContext]:
    holidays = {date.fromisoformat(d) for d in params["calendar.public_holidays"]}
    school_last = date.fromisoformat(params["calendar.school_last_day"])
    lat, lon = params["environment.latitude_deg"], params["environment.longitude_deg"]
    out = []
    d = start
    while d <= end:
        weekend = d.weekday() >= 5 or d in holidays
        sunrise, sunset = sun_times(d, lat, lon)
        out.append(DayContext(d, weekend, (not weekend) and d <= school_last, d > school_last, sunrise, sunset))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# 第一层：住户习惯
# ---------------------------------------------------------------------------


def _person_time(g: np.random.Generator, spec: list[float]) -> list[float]:
    """[总体均值, 户间标准差, 日间标准差] → [个人均值, 日间标准差]。"""
    mean, sd_between, sd_day = spec
    return [round(float(g.normal(mean, sd_between)), 3), sd_day]


def _person_value(g: np.random.Generator, spec: list[float], lo: float = 0.0, hi: float = 1e9) -> float:
    mean, sd_between = spec[0], spec[1]
    return round(_clip(float(g.normal(mean, sd_between)), lo, hi), 3)


def draw_person(g: np.random.Generator, person_id: str, role: str, params: Params) -> Person:
    spec = params["behavior.roles"][role]
    act = params["behavior.activities"]
    h: dict = {}
    for key in ("wake", "sleep"):
        h[key] = {kind: _person_time(g, spec[key][kind]) for kind in ("weekday", "weekend")}
    for key in ("leave", "return", "morning_outing", "nap"):
        if key in spec:
            h[key] = _person_time(g, spec[key])
    for key in ("wfh_prob", "evening_shower_prob", "morning_outing_prob", "afternoon_outing_prob", "nap_prob",
                "vacation_camp_prob"):
        if key in spec:
            h[key] = spec[key]
    h["showers_per_day"] = _person_value(g, spec["showers_per_day"], 0.3, 2.0)
    h["shower_min"] = [_person_value(g, spec["shower_min"][:2], 3.0, 30.0), spec["shower_min"][2]]
    h["hair_dryer_prob"] = _person_value(g, spec["hair_dryer_prob"], 0.0, 1.0)
    for key in ("pc_evening_prob",):
        if key in spec:
            h[key] = round(_clip(float(g.normal(spec[key], 0.2)), 0.0, 1.0), 3)
    for key in ("pc_daytime_hours_vacation", "kettle_per_day", "tv_hours", "morning_outing_min", "nap_min"):
        if key in spec:
            h[key] = _person_value(g, spec[key], 0.0, 12.0) if key not in ("morning_outing_min", "nap_min") else spec[key]
    faucet, shower = act["faucet_open_fraction"], act["shower_open_fraction"]
    mix = params["water.hot_water.shower_mix_temp_c"]
    h["faucet_open_fraction"] = round(_clip(float(g.normal(faucet["mean"], faucet["sd_person"])), 0.3, 1.0), 3)
    h["shower_open_fraction"] = round(_clip(float(g.normal(shower["mean"], shower["sd_person"])), 0.4, 1.0), 3)
    h["shower_mix_temp_c"] = round(float(g.normal(mix["mean"], mix["sd_person"])), 2)
    h["kettle_morning_prob"] = act["kettle_morning_prob"][role]
    h["night_toilet_prob"] = round(_clip(float(g.normal(act["night_toilet_prob"][role], 0.08)), 0.0, 1.0), 3)
    return Person(person_id, role, h)


def draw_profiles(building: dict, personas: dict, params: Params, seed: int) -> dict[str, HouseholdProfile]:
    persona_spec = params["behavior.personas"]
    comfort = params["behavior.comfort"]
    act = params["behavior.activities"]
    layouts = {lay["layout_id"]: lay for lay in building["layouts"]}
    profiles: dict[str, HouseholdProfile] = {}
    for house in building["houses"]:
        hid = house["house_id"]
        persona = personas["households"][hid]["persona"]
        spec = persona_spec[persona]
        layout = layouts[house["layout_id"]]
        g = rngmod.stream(seed, hid, "habits")
        persons = [draw_person(g, f"{hid}-P{i + 1}", role, params) for i, role in enumerate(spec["members"])]
        acs = {ac["room"]: ac["circuit"] for ac in layout["air_conditioners"]}
        habits: dict = {}
        if persona != "VACANT":
            modes = comfort["heater_mode_prob"]
            habits["heater_mode"] = str(g.choice(list(modes), p=list(modes.values())))
            sp = comfort["heater_setpoint_c"]
            habits["heater_setpoint_c"] = int(g.choice(sp["options"], p=sp["probs"]))
            habits["ac_on_threshold_c"] = _person_value(g, comfort["ac_on_threshold_c"][persona], 24, 33)
            habits["ac_setpoint_c"] = min(_person_value(g, comfort["ac_setpoint_c"][persona], 22, 30),
                                          habits["ac_on_threshold_c"] - 0.5)
            habits["night_ac_timer_off_prob"] = round(
                _clip(float(g.normal(comfort["night_ac_timer_off_prob"][persona], 0.15)), 0, 1), 3)
            laundry = spec["laundry_per_week"]
            habits["laundry_per_week"] = round(max(0.5, float(g.normal(laundry["mean"], laundry["sd"]))), 2)
            prefs = act["laundry_start_pref"]
            habits["laundry_pref"] = str(g.choice(list(prefs), p=list(prefs.values())))
            tv = act["tv_evening_prob"].get(persona)
            habits["tv_evening_prob"] = round(_clip(float(g.normal(tv, 0.15)), 0, 1), 3) if tv is not None else None
        else:
            habits["heater_mode"] = "OFF"
        always_on = params["power.appliances.always_on_w"]
        habits["always_on_w"] = round(max(always_on["min"], float(g.normal(always_on["mean"], always_on["sd"]))), 1)
        if persona == "VACANT":
            habits["always_on_w"] = round(habits["always_on_w"] * 0.2, 1)  # 空置房仅保留少量待机
        fridge = params["power.appliances.fridge_daily_kwh"]
        habits["fridge_daily_kwh"] = 0.0 if persona == "VACANT" else round(
            max(0.4, float(g.normal(fridge["mean"], fridge["sd"]))), 3)
        profiles[hid] = HouseholdProfile(
            house_id=hid, persona=persona, layout_id=house["layout_id"], washer_area=layout["washer_area"],
            kitchen_hot_water=layout["kitchen_hot_water"], bedroom_ac_circuit=acs.get("BEDROOM_MAIN"),
            living_ac_circuit=acs.get("LIVING"), persons=persons, habits=habits,
        )
    return profiles


# ---------------------------------------------------------------------------
# 第二层：外出计划
# ---------------------------------------------------------------------------


def plan_absences(profile: HouseholdProfile, days: list[DayContext], params: Params, seed: int) -> dict:
    """返回 {"away_days": {date}, "person_away_days": {pid: {date}}, "outing_days": {date: (s, e)},
    "visitor_days": {date}, "owner_visits": {date: (s, e)}}。"""
    g = rngmod.stream(seed, profile.house_id, "absences")
    spec = params["behavior.personas"][profile.persona]
    plan = {"away_days": set(), "person_away_days": {p.person_id: set() for p in profile.persons},
            "outing_days": {}, "visitor_days": set(), "owner_visits": {}}
    all_days = [d.day for d in days]
    baseline_end = days[0].day + timedelta(days=params["calendar.baseline_learning_days"])

    if profile.persona == "VACANT":
        for month in sorted({d.month for d in all_days}):
            month_days = [d for d in all_days if d.month == month]
            for _ in range(g.poisson(spec["owner_visits_per_month"] * len(month_days) / 30)):
                d = month_days[int(g.integers(len(month_days)))]
                start = float(g.uniform(10, 15))
                plan["owner_visits"][d] = (start, start + float(g.uniform(*spec["owner_visit_hours"])))
        return plan

    if "summer_trip_prob" in spec and g.random() < spec["summer_trip_prob"]:
        # 暑期出游安排在基线学习期之后，避免污染基线
        candidates = [d for d in all_days if d >= max(baseline_end, date(d.year, 7, 5))]
        lo, hi = spec["summer_trip_days"]
        length = int(g.integers(lo, hi + 1))
        if len(candidates) > length:
            start_idx = int(g.integers(0, len(candidates) - length))
            plan["away_days"].update(candidates[start_idx:start_idx + length])

    if profile.persona == "TRAVELER":
        lo, hi = spec["trip_days"]
        i = 0
        while i < len(all_days):
            if all_days[i] not in plan["away_days"] and g.random() < spec["trip_start_prob_per_home_day"]:
                length = int(g.integers(lo, hi + 1))
                for p in profile.persons:
                    plan["person_away_days"][p.person_id].update(all_days[i:i + length])
                i += length + 1  # 出差回来至少在家一天
            else:
                i += 1

    for ctx in days:
        if ctx.day in plan["away_days"]:
            continue
        if ctx.weekend and g.random() < spec.get("weekend_outing_prob", 0.0):
            start = float(g.uniform(9.5, 11.0))
            plan["outing_days"][ctx.day] = (start, start + float(g.uniform(5.0, 8.0)))

    rate = spec.get("visitors_per_month", 0.0) * len(all_days) / 30
    weekend_days = [d.day for d in days if d.weekend and d.day not in plan["away_days"]]
    for _ in range(g.poisson(rate)):
        if weekend_days:
            plan["visitor_days"].add(weekend_days[int(g.integers(len(weekend_days)))])
    return plan


# ---------------------------------------------------------------------------
# 第三层：逐日行为
# ---------------------------------------------------------------------------


class DayBuilder:
    """收集一户一天内的事件、在家区间、空调意图与热水器时段。时间为当日小时数（可 >24）。"""

    def __init__(self, profile: HouseholdProfile, ctx: DayContext, params: Params, g: np.random.Generator):
        self.p = profile
        self.ctx = ctx
        self.params = params
        self.g = g
        self.act = params["behavior.activities"]
        self.events: list[dict] = []
        self.presence: list[dict] = []
        self.ac: list[dict] = []
        self.heater: list[dict] = []
        self.room_use: dict[str, list[tuple[float, float]]] = {}

    # ---- 事件写入 ----
    def water(self, device: str, start: float, duration_s: float, person: Person | None, activity: str,
              open_fraction: float | None = None, mix_temp_c: float | None = None, hot_fraction: float | None = None,
              volume_l: float | None = None) -> None:
        room = {"TOILET": "BATHROOM", "BASIN": "BATHROOM", "SHOWER": "BATHROOM", "KITCHEN_FAUCET": "KITCHEN",
                "WASHER": "BALCONY" if self.p.washer_area == "Y" else "BATHROOM"}[device]
        self.events.append({
            "hour": start, "duration_s": round(float(duration_s), 1), "person_id": person.person_id if person else None,
            "activity": activity, "kind": "WATER", "device": device, "room": room,
            "open_fraction": None if open_fraction is None else round(float(open_fraction), 3),
            "mix_temp_c": None if mix_temp_c is None else round(float(mix_temp_c), 2),
            "hot_fraction": None if hot_fraction is None else round(float(hot_fraction), 3),
            "volume_l": volume_l, "power_w": None,
        })
        if person is not None:
            self.use_room(room, start, start + duration_s / 3600 + 1 / 60)

    def power(self, device: str, start: float, duration_s: float, person: Person | None, activity: str,
              room: str) -> None:
        if duration_s < MIN_EVENT_S:
            return
        self.events.append({
            "hour": start, "duration_s": round(float(duration_s), 1), "person_id": person.person_id if person else None,
            "activity": activity, "kind": "POWER", "device": device, "room": room,
            "open_fraction": None, "mix_temp_c": None, "hot_fraction": None, "volume_l": None,
            "power_w": self.params[APPLIANCE_POWER_PARAM[device]] if device in APPLIANCE_POWER_PARAM else None,
        })

    def use_room(self, room: str, s: float, e: float) -> None:
        self.room_use.setdefault(room, []).append((s, e))

    def open_fraction(self, base: float, sd_key: str = "faucet_open_fraction") -> float:
        if self.g.random() < self.act["full_open_prob"]:
            return 1.0
        return _clip(float(self.g.normal(base, self.act[sd_key]["sd_use"])), 0.15, 1.0)


def _daily_time(g: np.random.Generator, spec: list[float]) -> float:
    return float(g.normal(spec[0], spec[1]))


def person_segments(person: Person, ctx: DayContext, prev_sleep_h: float, wake_h: float, sleep_h: float,
                    next_day_away: bool, plan: dict, g: np.random.Generator, params: Params) -> list[tuple]:
    """当日 [0,24) 内的 (开始, 结束, 状态, 房间)。prev_sleep_h 为前一晚入睡时刻减 24（未跨零点为 0）。"""
    segs: list[tuple] = []
    bedroom = "BEDROOM_2" if person.role == "CHILD" else "BEDROOM_MAIN"
    if prev_sleep_h < 1 / 60:  # 过零点不足 1 分钟即入睡，视为未跨零点，避免产生零长度区间
        prev_sleep_h = 0.0
    if prev_sleep_h > 0:
        segs.append((0.0, prev_sleep_h, HOME, "LIVING"))
    segs.append((prev_sleep_h, wake_h, SLEEP, bedroom))
    awake_end = min(sleep_h, 24.0)
    awake = [(wake_h, awake_end)]
    h = person.habits
    role = person.role

    away_cuts: list[tuple[float, float]] = []
    if role in ("WORKER", "TRAVELER") and not ctx.weekend and g.random() >= h.get("wfh_prob", 0.0):
        leave = max(wake_h + 0.5, _daily_time(g, h["leave"]))
        ret = _daily_time(g, h["return"])
        if role == "WORKER" and plan.get("dinner_out"):
            ret = max(ret, float(g.uniform(20.8, 22.0)))
        away_cuts.append((leave, min(ret, awake_end - 0.3)))
    if role == "CHILD":
        if ctx.school_day:
            away_cuts.append((max(wake_h + 0.4, _daily_time(g, h["leave"])), _daily_time(g, h["return"])))
        elif ctx.vacation and not ctx.weekend and g.random() < h.get("vacation_camp_prob", 0.0):
            away_cuts.append((8.4, 17.0))
    if role == "ELDER":
        if g.random() < h["morning_outing_prob"]:
            s = max(wake_h + 0.3, _daily_time(g, h["morning_outing"]))
            away_cuts.append((s, s + max(0.5, g.normal(*h["morning_outing_min"]) / 60)))
        if g.random() < h["afternoon_outing_prob"]:
            s = float(g.uniform(15.0, 16.5))
            away_cuts.append((s, s + float(g.uniform(0.7, 1.5))))
    if plan.get("outing"):
        away_cuts.append(plan["outing"])

    # 外出区间裁剪到清醒时段内并合并，保证同一人的状态区间互不重叠
    away_cuts = merge([(max(s, wake_h), min(e, awake_end)) for s, e in away_cuts if min(e, awake_end) > max(s, wake_h)])
    for cut in away_cuts:
        awake = subtract(awake, cut)
    nap_cut = None
    if role == "ELDER" and g.random() < h["nap_prob"]:
        s = _daily_time(g, h["nap"])
        e = s + max(0.3, g.normal(*h["nap_min"]) / 60)
        if any(a <= s and e <= b for a, b in awake):
            awake = subtract(awake, (s, e))
            nap_cut = (s, e)

    for s, e in awake:
        segs.append((s, e, HOME, "LIVING"))
    for s, e in away_cuts:
        segs.append((s, e, AWAY, None))
    if nap_cut:
        segs.append((nap_cut[0], nap_cut[1], NAP, bedroom))
    if sleep_h < 24.0:
        segs.append((sleep_h, 24.0, SLEEP, bedroom))
    return sorted(segs)


def simulate_house(profile: HouseholdProfile, house: dict, days: list[DayContext], params: Params,
                   seed: int) -> dict[str, list[dict]]:
    """生成一户在给定日期内的全部行为数据。"""
    plan = plan_absences(profile, days, params, seed)
    out = {"events": [], "presence": [], "ac_intents": [], "heater_schedule": []}
    if profile.persona == "VACANT":
        for ctx in days:
            g = rngmod.stream(seed, profile.house_id, "day", ctx.day.toordinal())
            if ctx.day in plan["owner_visits"]:
                _owner_visit(profile, ctx, plan["owner_visits"][ctx.day], params, g, out)
        return out

    # 预先抽取每人每天的起床、入睡时刻，保证跨零点作息前后一致
    wake: dict[str, list[float]] = {}
    sleep: dict[str, list[float]] = {}
    for person in profile.persons:
        g = rngmod.stream(seed, profile.house_id, "sleep", person.person_id)
        wake[person.person_id], sleep[person.person_id] = [], []
        for ctx in days:
            kind = "weekend" if ctx.weekend else "weekday"
            w = _clip(_daily_time(g, person.habits["wake"][kind]), 4.5, 11.0)
            s = _daily_time(g, person.habits["sleep"][kind])
            s = s + 24 if s < 12 else s
            wake[person.person_id].append(w)
            sleep[person.person_id].append(_clip(s, w + 12.0, 27.0))

    spec = params["behavior.personas"][profile.persona]
    for i, ctx in enumerate(days):
        g = rngmod.stream(seed, profile.house_id, "day", ctx.day.toordinal())
        b = DayBuilder(profile, ctx, params, g)
        house_away = ctx.day in plan["away_days"]
        dinner_out = (profile.persona == "COUPLE" and not ctx.weekend
                      and g.random() < spec.get("dinner_out_weekday_prob", 0.0))
        day_plan = {"outing": plan["outing_days"].get(ctx.day), "dinner_out": dinner_out}
        segments: dict[str, list[tuple]] = {}
        for person in profile.persons:
            pid = person.person_id
            if house_away or ctx.day in plan["person_away_days"][pid]:
                segments[pid] = [(0.0, 24.0, AWAY, None)]
                continue
            prev_sleep = 0.0
            if i > 0 and not (days[i - 1].day in plan["away_days"] or days[i - 1].day in plan["person_away_days"][pid]):
                prev_sleep = max(0.0, sleep[pid][i - 1] - 24.0)
            next_away = i + 1 < len(days) and (days[i + 1].day in plan["away_days"]
                                               or days[i + 1].day in plan["person_away_days"][pid])
            sleep_h = min(sleep[pid][i], 24.0) if next_away else sleep[pid][i]
            segments[pid] = person_segments(person, ctx, prev_sleep, wake[pid][i], sleep_h, next_away, day_plan, g,
                                            params)
            _personal_routines(b, person, segments[pid], sleep_h, wake[pid][i + 1] if i + 1 < len(days) else None,
                               next_away)
        if not house_away:
            home_any = merge([(s, e) for segs in segments.values() for s, e, st, _ in segs if st == HOME])
            _meals(b, profile, segments, home_any, spec, day_plan)
            _laundry(b, profile, home_any)
            _entertainment(b, profile, segments, home_any)
            if ctx.day in plan["visitor_days"]:
                _visitors(b, profile, home_any)
            _lighting(b, segments, home_any)
            _ac_intents(b, profile, segments, home_any)
        _heater_schedule(b, profile, segments)
        _emit(profile, ctx, b, segments, out)
    return out


def _personal_routines(b: DayBuilder, person: Person, segs: list[tuple], sleep_h: float, next_wake: float | None,
                       next_away: bool) -> None:
    g, h, act = b.g, person.habits, b.act
    home = [(s, e) for s, e, st, _ in segs if st == HOME]
    if not home:
        return
    faucet = h["faucet_open_fraction"]
    # 起床与睡前流程（跟在 SLEEP 之后 / 在 SLEEP 之前的在家区间）
    for idx, (s, e, st, _) in enumerate(segs):
        if st != HOME:
            continue
        before = segs[idx - 1][2] if idx > 0 else None
        after = segs[idx + 1][2] if idx + 1 < len(segs) else None
        if before == SLEEP and e - s > 0.2:
            t = s + float(g.uniform(0.02, 0.15))
            if g.random() < act["toilet_at_wake_prob"]:
                b.water("TOILET", t, 60, person, "WAKE_TOILET", volume_l=b.params["water.fixtures.toilet_flush_grade2_l"])
            t += float(g.uniform(0.03, 0.08))
            b.water("BASIN", t, g.uniform(*act["brush_teeth_s"]), person, "BRUSH_TEETH",
                    b.open_fraction(faucet) * act["brush_teeth_flow_factor"], mix_temp_c=None)
            b.water("BASIN", t + 0.04, g.uniform(*act["face_wash_s"]), person, "FACE_WASH", b.open_fraction(faucet),
                    mix_temp_c=float(g.normal(35, 2)))
            kettle_t = t + float(g.uniform(0.1, 0.3))
            if g.random() < h["kettle_morning_prob"] and kettle_t + 0.07 < e:
                b.power("KETTLE", kettle_t, g.uniform(170, 240), person, "MORNING_KETTLE", "KITCHEN")
        if after == SLEEP and e - s > 0.3:
            t = e - float(g.uniform(0.1, 0.3))
            b.water("BASIN", t, g.uniform(*act["brush_teeth_s"]), person, "BRUSH_TEETH",
                    b.open_fraction(faucet) * act["brush_teeth_flow_factor"])
            if g.random() < act["toilet_at_sleep_prob"]:
                b.water("TOILET", t + 0.05, 60, person, "SLEEP_TOILET",
                        volume_l=b.params["water.fixtures.toilet_flush_grade2_l"])
            b.use_room("BEDROOM_2" if person.role == "CHILD" else "BEDROOM_MAIN", e - 0.3, e)

    # 白天随机如厕、洗手
    for s, e in home:
        for _ in range(g.poisson(act["toilet_per_awake_home_hour"] * (e - s))):
            t = float(g.uniform(s, e))
            b.water("TOILET", t, 60, person, "TOILET", volume_l=b.params["water.fixtures.toilet_flush_grade2_l"])
            if g.random() < 0.8:
                b.water("BASIN", t + 0.02, g.uniform(*act["handwash_s"]), person, "HANDWASH", b.open_fraction(faucet))
        for _ in range(g.poisson(act["handwash_per_awake_home_hour"] * (e - s))):
            b.water("BASIN", float(g.uniform(s, e)), g.uniform(*act["handwash_s"]), person, "HANDWASH",
                    b.open_fraction(faucet))

    # 夜间如厕
    if g.random() < h["night_toilet_prob"] and sleep_h < 24 + 3:
        latest = 24.0 if (next_away or next_wake is None) else 24.0 + next_wake - 0.5
        if latest - (sleep_h + 1.0) > 0.5:
            b.water("TOILET", float(g.uniform(sleep_h + 1.0, latest)), 60, person, "NIGHT_TOILET",
                    volume_l=b.params["water.fixtures.toilet_flush_grade2_l"])

    # 淋浴
    expected = h["showers_per_day"]
    n = int(expected) + (1 if g.random() < expected - int(expected) else 0)
    # 候选窗口 (最早开始, 最晚开始, 所在在家区间的结束时刻)
    evening_windows = [(max(s, e - 2.5), e - 0.5, e) for s, e, st, _ in segs if st == HOME and e - s > 1.0
                       and e >= 17.0]
    morning_windows = [(s + 0.15, min(e, s + 0.8), e) for idx, (s, e, st, _) in enumerate(segs)
                       if st == HOME and idx > 0 and segs[idx - 1][2] == SLEEP and e - s > 0.5]
    afternoon_windows = [(max(s, 14.5), min(e, 17.5), e) for s, e, st, _ in segs if st == HOME]
    for k in range(n):
        prefer_evening = g.random() < h["evening_shower_prob"] if k == 0 else True
        windows = [w for w in (evening_windows if prefer_evening else morning_windows) if w[1] > w[0]]
        if not windows and person.role == "ELDER":
            windows = [w for w in afternoon_windows if w[1] - w[0] > 0.3]
        windows = windows or [w for w in evening_windows + morning_windows if w[1] > w[0]]
        if not windows:
            break
        ws, we, seg_end = windows[int(g.integers(len(windows)))]
        minutes = max(3.0, float(g.normal(h["shower_min"][0], h["shower_min"][1])))
        # 洗完澡须在离家或入睡前结束；时间不够就缩短
        latest = min(we, seg_end - minutes / 60 - 0.1)
        if latest < ws:
            minutes = max(3.0, (seg_end - ws - 0.1) * 60)
            latest = ws
        start = float(g.uniform(ws, latest))
        if start + minutes / 60 > seg_end:
            break
        b.water("SHOWER", start, minutes * 60, person, "SHOWER", b.open_fraction(h["shower_open_fraction"],
                                                                                   "shower_open_fraction"),
                mix_temp_c=float(g.normal(h["shower_mix_temp_c"], b.params["water.hot_water.shower_mix_temp_c"]["sd_use"])))
        b.power("BATH_FAN", start, minutes * 60 + 900, person, "SHOWER_FAN", "BATHROOM")
        dry_start, dry_s = start + minutes / 60 + 0.05, float(g.uniform(240, 480))
        if g.random() < h["hair_dryer_prob"] and dry_start + dry_s / 3600 < seg_end:
            b.power("HAIR_DRYER", dry_start, dry_s, person, "HAIR_DRY", "BATHROOM")


def _meals(b: DayBuilder, profile: HouseholdProfile, segments: dict, home_any: list, spec: dict, day_plan: dict) -> None:
    g, act, ctx = b.g, b.act, b.ctx
    kind = "weekend" if ctx.weekend else "weekday"
    probs = spec["meals_at_home"][kind]
    persons = {p.person_id: p for p in profile.persons}
    hot = act["kitchen_hot_fraction_t89"] if profile.kitchen_hot_water else None

    def cook_at(t: float) -> Person | None:
        candidates = [persons[pid] for pid, segs in segments.items()
                      if any(s <= t < e and st == HOME for s, e, st, _ in segs)]
        adults = [p for p in candidates if p.role != "CHILD"]
        return (adults or candidates or [None])[0]

    def home_interval(person: Person, t: float) -> tuple[float, float]:
        return next((s, e) for s, e, st, _ in segments[person.person_id] if st == HOME and s <= t < e)

    wakes = [s for segs in segments.values() for idx, (s, e, st, _) in enumerate(segs)
             if st == HOME and idx > 0 and segs[idx - 1][2] == SLEEP]
    times = {}
    if wakes:
        times["BREAKFAST"] = min(wakes) + float(g.uniform(0.3, 0.6))
    times["LUNCH"] = float(g.normal(12.0, 0.25))
    if profile.persona == "ELDER":
        times["DINNER"] = float(g.normal(17.6, 0.3))
    elif ctx.weekend:
        times["DINNER"] = float(g.normal(18.5, 0.4))
    else:
        returns = [e for segs in segments.values() for s, e, st, _ in segs if st == AWAY and 16 < e < 23]
        times["DINNER"] = (max(returns) if returns else 18.3) + float(g.uniform(0.4, 0.8))

    for meal, t in times.items():
        if meal == "DINNER" and day_plan.get("dinner_out"):
            continue
        if g.random() >= probs[meal.lower()]:
            continue
        cook = cook_at(t - 0.4)
        if cook is None or not contains(home_any, t):
            continue
        # 所有烹饪动作都限制在做饭人本次在家清醒的区间内
        cs, ce = home_interval(cook, t - 0.4)
        meal_t = min(t, ce - 0.05)
        faucet = cook.habits["faucet_open_fraction"]
        size = act["meal_household_size_factor"]
        scale = act["meal_scale"][meal] * min(size["max"], size["base"] + size["per_member"] * len(profile.persons))
        prep_start = max(cs + 0.03, meal_t - float(g.uniform(0.35, 0.6)))
        if meal_t - prep_start < 0.1:
            continue
        n_prep = max(1, round(int(g.integers(act["meal_prep_draws"][0], act["meal_prep_draws"][1] + 1)) * scale))
        for _ in range(n_prep):
            dur = float(g.uniform(*act["meal_prep_draw_s"]))
            b.water("KITCHEN_FAUCET", float(g.uniform(prep_start, meal_t - dur / 3600)), dur, cook,
                    f"{meal}_PREP", b.open_fraction(faucet), hot_fraction=hot)
        b.use_room("KITCHEN", prep_start, meal_t)
        if (meal != "BREAKFAST" or g.random() < 0.3) and meal_t - prep_start > 0.2:
            b.power("RANGE_HOOD", prep_start + 0.1, (meal_t - prep_start - 0.1) * 3600, cook, f"{meal}_HOOD", "KITCHEN")
        if meal == "DINNER" and g.random() < act["rice_cooker_dinner_prob"]:
            b.power("RICE_COOKER", max(cs + 0.02, meal_t - 0.75), 2400, cook, "RICE_COOKER", "KITCHEN")
        if g.random() < act["microwave_per_meal_prob"]:
            b.power("MICROWAVE", meal_t - 0.08, g.uniform(120, 240), cook, f"{meal}_MICROWAVE", "KITCHEN")
        dish_start = meal_t + float(g.uniform(0.35, 0.6))
        washer = cook_at(dish_start)
        if washer is None:
            continue  # 饭后家中无人：碗碟留到下次，不产生洗碗用水
        ws, we = home_interval(washer, dish_start)
        dish_end = min(dish_start + float(g.uniform(0.15, 0.3)), we - 0.02)
        n_dish = max(1, round(int(g.integers(act["dishwash_draws"][0], act["dishwash_draws"][1] + 1)) * scale))
        for _ in range(n_dish if dish_end > dish_start else 0):
            dur = min(float(g.uniform(*act["dishwash_draw_s"])), (we - dish_start) * 3600 - 30)
            if dur < 5:
                break
            b.water("KITCHEN_FAUCET", float(g.uniform(dish_start, max(dish_start, dish_end - dur / 3600))), dur,
                    washer, f"{meal}_DISHWASH", b.open_fraction(washer.habits["faucet_open_fraction"]), hot_fraction=hot)
        b.use_room("KITCHEN", dish_start, max(dish_start, dish_end))


def _laundry(b: DayBuilder, profile: HouseholdProfile, home_any: list) -> None:
    g, ctx = b.g, b.ctx
    lam = profile.habits["laundry_per_week"] / 7
    n = min(2, int(g.poisson(lam)))
    evening_home = [(max(s, 19.0), min(e, 22.0)) for s, e in home_any if min(e, 22.0) - max(s, 19.0) > 0.3]
    for k in range(n):
        pref = profile.habits["laundry_pref"]
        if pref == "WEEKEND_MORNING" and ctx.weekend and contains(home_any, 9.5) and k == 0:
            start = float(g.uniform(9.0, 11.0))
        elif pref == "VALLEY_TIMER" and contains(home_any, 22.2):
            start = float(g.uniform(22.3, 23.3))
        elif evening_home:
            s, e = evening_home[int(g.integers(len(evening_home)))]
            start = float(g.uniform(s, e))
        else:
            continue
        start += 1.2 * k  # 第二桶接着洗
        volume = b.params["water.fixtures.washer_water_per_cycle_l"]
        b.water("WASHER", start, float(g.uniform(62, 75)) * 60, None, "LAUNDRY_CYCLE", open_fraction=1.0,
                volume_l=float(round(g.normal(volume, 4), 1)))
        b.use_room("BALCONY" if profile.washer_area == "Y" else "BATHROOM", start, start + 0.05)


def _entertainment(b: DayBuilder, profile: HouseholdProfile, segments: dict, home_any: list) -> None:
    g, ctx, act = b.g, b.ctx, b.act
    persons = {p.person_id: p for p in profile.persons}
    tv_prob = profile.habits.get("tv_evening_prob")
    if profile.persona == "ELDER":
        elder = profile.persons[0]
        hours = max(0.5, float(g.normal(elder.habits["tv_hours"], 0.7)))
        for (lo, hi), share in (((8.5, 11.0), 0.4), ((19.0, 21.0), 0.6)):
            dur = hours * share
            start = float(g.uniform(lo, max(lo, hi - dur)))
            for s, e in intersect([(start, start + dur)], home_any):
                b.power("TV", s, (e - s) * 3600, elder, "TV", "LIVING")
    elif tv_prob is not None and g.random() < tv_prob:
        start = float(g.uniform(19.5, 20.8))
        dur = max(0.5, float(g.normal(*act["tv_evening_hours"])))
        for s, e in intersect([(start, start + dur)], home_any):
            b.power("TV", s, (e - s) * 3600, None, "TV", "LIVING")

    for pid, segs in segments.items():
        person = persons[pid]
        home = [(s, e) for s, e, st, _ in segs if st == HOME]
        if "pc_evening_prob" in person.habits and g.random() < person.habits["pc_evening_prob"]:
            start = float(g.normal(20.8, 0.5))
            for s, e in intersect([(start, start + float(g.uniform(1.0, 3.0)))], home):
                b.power("PC", s, (e - s) * 3600, person, "PC", "BEDROOM_MAIN")
                b.use_room("BEDROOM_MAIN", s, e)
        if person.role == "CHILD" and ctx.vacation:
            dur = max(0.5, float(g.normal(person.habits["pc_daytime_hours_vacation"], 0.8)))
            start = float(g.uniform(13.5, 16.0))
            for s, e in intersect([(start, start + dur)], home):
                b.power("PC", s, (e - s) * 3600, person, "PC_VACATION", "BEDROOM_2")
                b.use_room("BEDROOM_2", s, e)


def _visitors(b: DayBuilder, profile: HouseholdProfile, home_any: list) -> None:
    """访客：2 人午后到访，只产生如厕、洗手；访客不计入住户成员。"""
    g, act = b.g, b.act
    visit = intersect([(float(g.uniform(11.0, 13.0)), float(g.uniform(18.0, 20.5)))], home_any)
    for s, e in visit:
        for _ in range(2):
            for _ in range(g.poisson(act["toilet_per_awake_home_hour"] * (e - s))):
                t = float(g.uniform(s, e))
                b.water("TOILET", t, 60, None, "GUEST_TOILET", volume_l=b.params["water.fixtures.toilet_flush_grade2_l"])
                b.water("BASIN", t + 0.02, g.uniform(*act["handwash_s"]), None, "GUEST_HANDWASH", 0.6)
        b.use_room("LIVING", s, e)


def _owner_visit(profile: HouseholdProfile, ctx: DayContext, window: tuple[float, float], params: Params,
                 g: np.random.Generator, out: dict) -> None:
    b = DayBuilder(profile, ctx, params, g)
    s, e = window
    b.water("TOILET", float(g.uniform(s, e)), 60, None, "OWNER_TOILET",
            volume_l=params["water.fixtures.toilet_flush_grade2_l"])
    for _ in range(int(g.integers(1, 3))):
        b.water("BASIN", float(g.uniform(s, e)), g.uniform(*b.act["handwash_s"]), None, "OWNER_HANDWASH", 0.6)
    b.water("KITCHEN_FAUCET", float(g.uniform(s, e)), g.uniform(20, 40), None, "OWNER_FLUSH_TAP", 0.8)
    b.presence.append({"person_id": f"{profile.house_id}-OWNER", "role": "OWNER", "hour_start": s, "hour_end": e,
                       "state": HOME, "room": "LIVING"})
    _emit(profile, ctx, b, {}, out)


def _lighting(b: DayBuilder, segments: dict, home_any: list) -> None:
    margin = b.act["room_lighting_dark_margin_min"] / 60
    dark = [(0.0, b.ctx.sunrise_h + margin), (b.ctx.sunset_h - margin, 30.0)]
    rooms = {room: list(v) for room, v in b.room_use.items()}
    rooms.setdefault("LIVING", []).extend(home_any)
    for room, intervals in rooms.items():
        for s, e in intersect(merge(intervals, gap=2 / 60), dark):
            if (e - s) * 3600 < MIN_EVENT_S:
                continue
            b.events.append({
                "hour": s, "duration_s": round((e - s) * 3600, 1), "person_id": None, "activity": "LIGHT",
                "kind": "POWER", "device": "LIGHT", "room": room, "open_fraction": None, "mix_temp_c": None,
                "hot_fraction": None, "volume_l": None,
                "power_w": b.params["power.appliances.lighting_w_by_room"].get(room, 10),
            })


def _ac_intents(b: DayBuilder, profile: HouseholdProfile, segments: dict, home_any: list) -> None:
    g, h = b.g, profile.habits
    base = {"on_threshold_c": h["ac_on_threshold_c"], "setpoint_c": h["ac_setpoint_c"]}
    if profile.living_ac_circuit:
        for s, e in home_any:
            if e - s >= 0.5:
                b.ac.append({"room": "LIVING", "circuit": profile.living_ac_circuit, "hour_start": s, "hour_end": e,
                             "reason": "AWAKE_HOME", **base})
    if profile.bedroom_ac_circuit:
        adults = [p for p in profile.persons if p.role != "CHILD"]
        sleeps = []
        for p in adults:
            sleeps += [(s, e, st) for s, e, st, room in segments[p.person_id] if st in (SLEEP, NAP)]
        timer_off = g.random() < h["night_ac_timer_off_prob"]
        for s, e in merge([(s, e) for s, e, _ in sleeps]):
            start = s - 0.3 if s > 1 else s
            end = min(e, s + 3.0) if (timer_off and s > 18) else e
            b.ac.append({"room": "BEDROOM_MAIN", "circuit": profile.bedroom_ac_circuit, "hour_start": start,
                         "hour_end": end, "reason": "SLEEP", **base})


def _heater_schedule(b: DayBuilder, profile: HouseholdProfile, segments: dict) -> None:
    mode = profile.habits["heater_mode"]
    setpoint = profile.habits.get("heater_setpoint_c")
    if mode == "ALWAYS_ON":
        windows = [(0.0, 24.0)]
    elif mode == "VALLEY_TIMER":
        windows = [(0.0, 8.0), (22.0, 24.0)]
    elif mode == "SMART_PREHEAT":
        showers = [e["hour"] for e in b.events if e["device"] == "SHOWER"]
        windows = merge([(max(0.0, t - 1.5), min(24.0, t + 0.5)) for t in showers])
    else:
        windows = []
    for s, e in windows:
        b.heater.append({"hour_start": s, "hour_end": e, "mode": mode, "setpoint_c": setpoint})


def _emit(profile: HouseholdProfile, ctx: DayContext, b: DayBuilder, segments: dict, out: dict) -> None:
    base = pd.Timestamp(ctx.day)
    hid = profile.house_id

    def ts(hour: float) -> pd.Timestamp:
        return base + pd.Timedelta(seconds=round(hour * 3600))

    for e in b.events:
        row = {"house_id": hid, "plan_date": ctx.day.isoformat(), "start": ts(e["hour"]), **e}
        row.pop("hour")
        out["events"].append(row)
    for pid, segs in segments.items():
        role = next(p.role for p in profile.persons if p.person_id == pid)
        for s, e, st, room in segs:
            if ts(e) <= ts(s):  # 秒级取整后长度为 0 的区间不输出
                continue
            out["presence"].append({"house_id": hid, "person_id": pid, "role": role, "start": ts(s), "end": ts(e),
                                    "state": st, "room": room})
    for p in b.presence:
        out["presence"].append({"house_id": hid, "person_id": p["person_id"], "role": p["role"],
                                "start": ts(p["hour_start"]), "end": ts(p["hour_end"]), "state": p["state"],
                                "room": p["room"]})
    for a in b.ac:
        out["ac_intents"].append({"house_id": hid, "room": a["room"], "circuit": f"CB-{hid}-{a['circuit']}",
                                  "start": ts(a["hour_start"]), "end": ts(a["hour_end"]), "reason": a["reason"],
                                  "on_threshold_c": a["on_threshold_c"], "setpoint_c": a["setpoint_c"]})
    for w in b.heater:
        out["heater_schedule"].append({"house_id": hid, "start": ts(w["hour_start"]), "end": ts(w["hour_end"]),
                                       "mode": w["mode"], "setpoint_c": w["setpoint_c"]})


# ---------------------------------------------------------------------------
# 汇总入口
# ---------------------------------------------------------------------------


def generate(building: dict, personas: dict, params: Params, seed: int, start: date, end: date,
             house_filter: set[str] | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, HouseholdProfile]]:
    days = day_contexts(params, start, end)
    profiles = draw_profiles(building, personas, params, seed)
    tables = {"events": [], "presence": [], "ac_intents": [], "heater_schedule": []}
    for house in building["houses"]:
        hid = house["house_id"]
        if house_filter and hid not in house_filter:
            continue
        result = simulate_house(profiles[hid], house, days, params, seed)
        for key in tables:
            tables[key].extend(result[key])
    frames = {k: pd.DataFrame(v) for k, v in tables.items()}
    if not frames["events"].empty:
        frames["events"] = frames["events"].sort_values(["house_id", "start"], kind="stable").reset_index(drop=True)
    return frames, profiles


def estimate_water_l(events: pd.DataFrame, building: dict, params: Params) -> pd.Series:
    """行为层用水量估算（仅用于自检量级）：全开流量 = 水效流量 × √(可用压力 / 0.10 MPa)。

    可用压力按入户静压扣除 0.05 MPa 管路损失近似；精确值由 1.5 的水力模型计算。
    """
    pressure = {h["house_id"]: h["entry_static_pressure_mpa"] for h in building["houses"]}
    ref = params["water.fixtures.efficiency_test_pressure_mpa"]
    full = {
        "BASIN": params["water.fixtures.faucet_efficiency_grade2_lps"],
        "KITCHEN_FAUCET": params["water.fixtures.faucet_efficiency_grade2_lps"],
        "SHOWER": params["water.fixtures.shower_efficiency_grade2_lps"],
    }
    water = events[events["kind"] == "WATER"]
    factor = np.sqrt(np.maximum(water["house_id"].map(pressure) - 0.05, 0.05) / ref)
    lps = water["device"].map(full) * factor
    litres = lps * water["open_fraction"].fillna(1.0) * water["duration_s"]
    litres = litres.where(water["volume_l"].isna(), water["volume_l"])
    return litres
