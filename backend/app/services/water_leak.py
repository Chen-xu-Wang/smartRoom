"""漏水检测：暗漏（W2，最小夜间流量法）与爆管 / 软管脱落（W3，支路流量越限 → 自动关阀）。

与 ``water_blockage`` 相同，输入只有传感器读数流与扩展的一房一码档案，全部是纯函数。

暗漏
    凌晨 2–5 点住户基本不用水。正常家庭这段时间总有连续多分钟流量为 0；
    如果每一分钟都有流量（取夜间逐分钟最小值的 5% 分位），就是有东西一直在漏。
    连续多晚都这样才报出，排除偶尔起夜、夜间洗衣等正常用水。
    再看各支路流量计：哪条支路夜间也有持续小流量，漏点就在哪条支路；
    冷/热哪一侧有流量决定候选部件；支路流量之和解释不了的部分指向热水器或户内主管。

爆管 / 软管脱落
    直接比较流量不可靠：器具流量随水压的平方根变化，高区住户洗衣机进水就能超过"额定流量"。
    改用"出水口流量系数" cv = Q / √P（Q 为支路流量，P 为该支路上最近的压力测点）。
    正常器具全开时 cv 不超过器具自身的流量系数；软管脱落相当于出现一个几乎没有阻力的出口，
    流量变大的同时末端压力塌陷，cv 会高出一个数量级。支路 cv 持续 60 秒超过该支路全部器具
    流量系数之和的 1.5 倍（多个器具同时全开也达不到），即判定为爆管，按规则立即关闭入户电动总阀。
    已知局限：没有支路压力测点时退而使用入户压力，包含沿程损失，灵敏度偏低。
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

from .water_blockage import AREA_NAMES, DATA_SOURCE, SCHEMA_VERSION, Stream

# 器具额定流量（L/s），与 sim_params.yaml 的 water.fixtures.*_rated_lps 一致，出处 GB 50015-2019（待核对原文）
FIXTURE_RATED_LPS = {"KITCHEN_FAUCET": 0.20, "BASIN": 0.15, "SHOWER": 0.15, "TOILET": 0.10, "WASHER": 0.20}
# 器具全开流量系数 cv（L/s/√MPa）= 水效流量或额定流量 / √0.10 MPa，与模拟参数库 efficiency_test_pressure_mpa 的约定一致
FIXTURE_CV = {"KITCHEN_FAUCET": 0.125 / 0.3162, "BASIN": 0.125 / 0.3162, "SHOWER": 0.12 / 0.3162,
              "TOILET": 0.10 / 0.3162, "WASHER": 0.20 / 0.3162}


@dataclass(frozen=True)
class LeakConfig:
    night_start_h: int = 2
    night_end_h: int = 5
    night_quantile: float = 0.05     # 夜间逐分钟最小流量的分位数
    min_leak_lpm: float = 0.05       # 高于水表低流量截止（0.03 L/min），低于此值不判暗漏
    consecutive_nights: int = 3
    min_night_minutes: int = 120     # 一个夜间窗口至少有这么多分钟的数据才评估
    unexplained_ratio: float = 0.3   # 支路流量解释不了的部分超过总表的 30% 时，怀疑支路之外的部位
    burst_factor: float = 1.5        # 支路出水口流量系数超过该支路器具流量系数之和的倍数
    burst_min_flow_lpm: float = 6.0  # 流量太小时压力测量相对误差大，不做爆管判断
    burst_min_duration_s: int = 60
    burst_max_gap_s: int = 3
    valve_close_delay_s: int = 5     # 下发关阀指令到阀门关闭的时间


# 暗漏定位先验（模型假设）：同一支路、同一侧有持续小流量时各部件的相对可能性。
# 依据：马桶进水阀/排水阀密封老化是户内暗漏最常见的来源；角阀与软管接口次之。
HIDDEN_LEAK_PRIORS = {
    ("B", "COLD"): [("TOILET", 0.65), ("ANGLE_VALVE_COLD", 0.15), ("BRANCH", 0.10)],
    ("B", "HOT"): [("ANGLE_VALVE_HOT", 0.45), ("MIXER", 0.35), ("BRANCH", 0.10)],
    ("B", "BOTH"): [("MIXER", 0.55), ("FAUCET", 0.30)],
    ("K", "COLD"): [("HOSE_COLD", 0.45), ("ANGLE_VALVE_COLD", 0.35), ("BRANCH", 0.10)],
    ("K", "HOT"): [("HOSE_HOT", 0.45), ("ANGLE_VALVE_HOT", 0.35), ("BRANCH", 0.10)],
    ("K", "BOTH"): [("FAUCET", 0.60), ("HOSE_COLD", 0.20)],
    ("Y", "COLD"): [("WASHER_TAP", 0.60), ("BRANCH", 0.25)],
    ("UNMETERED", None): [("HEATER", 0.50), ("MAIN", 0.30)],
}
# 爆管定位先验：支路流量越限时，软管脱落远比硬管爆裂常见
BURST_PRIORS = {
    "COLD": [("HOSE_COLD", 0.70), ("ANGLE_VALVE_COLD", 0.20)],
    "HOT": [("HOSE_HOT", 0.70), ("ANGLE_VALVE_HOT", 0.20)],
    "BOTH": [("HOSE_COLD", 0.45), ("HOSE_HOT", 0.45)],
}


# ---------------------------------------------------------------------------
# 拓扑
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Branch:
    area: str
    side: str            # COLD / HOT
    segment: str
    flow_sensor: str
    rated_lpm: float      # 支路下游全部器具额定流量之和
    cv_capacity: float    # 支路下游全部器具流量系数之和
    pressure_sensor: str  # 支路上最近的压力测点（没有时为入户压力）


def _nodes(house: dict) -> dict:
    return {n["segment_code"]: n for n in house["supply_network"]}


def _children(nodes: dict) -> dict:
    out: dict[str, list[str]] = {}
    for code, n in nodes.items():
        for p in n["parents"]:
            out.setdefault(p, []).append(code)
    return out


def _descendant_fixtures(nodes: dict, children: dict, code: str) -> set[str]:
    found, stack = set(), [code]
    while stack:
        cur = stack.pop()
        if nodes[cur]["fixture"]:
            found.add(nodes[cur]["fixture"])
        stack.extend(children.get(cur, []))
    return found


def discover_branches(house: dict) -> tuple[list[Branch], str]:
    """返回 (有流量计的支路, 入户总表流量传感器)。"""
    nodes = _nodes(house)
    children = _children(nodes)
    sensors = house["sensors"]
    meter_node = next(c for c, n in nodes.items() if n["kind"] == "METER")
    meter_sensor = next(s["sensor_code"] for s in sensors if s["type"] == "FL" and s["target"] == meter_node)
    pressure = [s for s in sensors if s["type"] == "PR"]
    # 入户压力：取最下游的入户测点（过滤器之后）
    inlet = [s for s in pressure if nodes[s["target"]]["area"] == "IN"]
    inlet_pr = max(inlet, key=lambda s: len(_ancestors(nodes, s["target"])))["sensor_code"]
    branches = []
    for s in sensors:
        if s["type"] != "FL" or s["target"] == meter_node:
            continue
        n = nodes[s["target"]]
        fixtures = _descendant_fixtures(nodes, children, s["target"])
        below = _descendants(children, s["target"])
        local = [p["sensor_code"] for p in pressure if p["target"] in below]
        branches.append(Branch(
            n["area"], "HOT" if n["side"] == "HOT" else "COLD", s["target"], s["sensor_code"],
            sum(FIXTURE_RATED_LPS.get(f, 0.15) for f in fixtures) * 60.0,
            sum(FIXTURE_CV.get(f, 0.4) for f in fixtures),
            local[0] if local else inlet_pr,
        ))
    return branches, meter_sensor


def _ancestors(nodes: dict, code: str) -> list[str]:
    out, cur = [], nodes[code]
    while cur["parents"]:
        out.append(cur["parents"][0])
        cur = nodes[cur["parents"][0]]
    return out


def _descendants(children: dict, code: str) -> set[str]:
    found, stack = set(), [code]
    while stack:
        cur = stack.pop()
        found.add(cur)
        stack.extend(children.get(cur, []))
    return found


def _role_node(house: dict, area: str, role: str) -> str | None:
    """按角色在给水拓扑里找部件编码。"""
    nodes = _nodes(house)

    def pick(pred):
        return next((c for c, n in nodes.items() if pred(n)), None)

    side_of = {"COLD": ("COLD",), "HOT": ("HOT",)}
    if role == "TOILET":
        return pick(lambda n: n["area"] == area and n["fixture"] == "TOILET")
    if role == "WASHER_TAP":
        return pick(lambda n: n["area"] == area and n["fixture"] == "WASHER")
    if role == "FAUCET":
        return pick(lambda n: n["area"] == area and n["fixture"] in ("BASIN", "KITCHEN_FAUCET"))
    if role == "MIXER":
        return pick(lambda n: n["area"] == area and n["kind"] == "MIXER")
    if role.startswith("ANGLE_VALVE_"):
        side = role.rsplit("_", 1)[1]
        # 优先洗脸盆/水槽角阀（马桶角阀漏水通常表现为马桶本身的暗漏）
        cands = [c for c, n in nodes.items() if n["area"] == area and n["kind"] == "ANGLE_VALVE"
                 and n["side"] in side_of[side]]
        cands.sort(key=lambda c: "马桶" in nodes[c]["name"])
        return cands[0] if cands else None
    if role.startswith("HOSE_"):
        side = role.rsplit("_", 1)[1]
        return pick(lambda n: n["area"] == area and n["kind"] == "HOSE" and n["side"] in side_of[side])
    if role == "BRANCH":
        return pick(lambda n: n["area"] == area and n["kind"] == "PIPE" and n["side"] == "COLD")
    if role == "HEATER":
        return pick(lambda n: n["kind"] == "HEATER")
    if role == "MAIN":
        return pick(lambda n: n["area"] == "IN" and n["kind"] == "PIPE")
    return None


def _candidates(house: dict, area: str, priors: list[tuple[str, float]], strength: float = 1.0) -> list[dict]:
    nodes = _nodes(house)
    out, seen = [], set()
    for role, prior in priors:
        code = _role_node(house, area, role)
        if not code or code in seen:
            continue
        seen.add(code)
        n = nodes[code]
        device = next((d for d in house["devices"] if d.get("segment_code") == code), None)
        out.append({
            "segment_code": code,
            "segment_name": f"{AREA_NAMES.get(n['area'], n['area'])}-{n['name']}"[:40],
            "device_code": device["device_code"] if device else None,
            "in_archive": bool(device and device.get("in_archive")),
            "confidence": round(prior * strength, 2),
        })
    return sorted(out, key=lambda c: c["confidence"], reverse=True)[:3]


def _archive_context(house: dict, building: dict, top: dict | None) -> dict:
    ctx = {"building": building.get("building", ""), "unit": building.get("unit", ""), "floor": house["floor_label"],
           "layout": house["layout"], "in_archive": bool(house["in_archive"]), "recent_repairs_180d": 0}
    device = next((d for d in house["devices"] if top and d.get("segment_code") == top["segment_code"]), None)
    if device:
        ctx["device_name"] = device["name"]
        if device.get("spec"):
            ctx["device_model"] = device["spec"]
        if device.get("install_date"):
            ctx["install_date"] = device["install_date"]
    return ctx


# ---------------------------------------------------------------------------
# 暗漏
# ---------------------------------------------------------------------------
def _night_minute_minima(stream: Stream, code: str, cfg: LeakConfig) -> dict[date, list[float]]:
    """{夜间日期: [该夜每分钟的最小流量]}。1 秒数据先按分钟取最小值，避免用水期间的高频行主导统计。"""
    per_minute: dict[datetime, float] = {}
    col = stream.columns[code]
    for t, v in zip(stream.ts, col):
        if v is None or not (cfg.night_start_h <= t.hour < cfg.night_end_h):
            continue
        key = t.replace(second=0)
        per_minute[key] = min(per_minute.get(key, v), v)
    nights: dict[date, list[float]] = {}
    for t, v in per_minute.items():
        nights.setdefault(t.date(), []).append(v)
    return nights


def _q(values: list[float], q: float) -> float:
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def nightly_min_flow(stream: Stream, house: dict, cfg: LeakConfig = LeakConfig()) -> list[dict]:
    """逐夜：总表与各支路夜间最小流量（L/min）。"""
    branches, meter = discover_branches(house)
    meter_nights = _night_minute_minima(stream, meter, cfg)
    branch_nights = {b.flow_sensor: _night_minute_minima(stream, b.flow_sensor, cfg) for b in branches}
    out = []
    for d in sorted(meter_nights):
        minutes = meter_nights[d]
        point = {"date": d.isoformat(), "minutes": len(minutes), "meter_lpm": None, "branches": {}, "flagged": False}
        if len(minutes) >= cfg.min_night_minutes:
            point["meter_lpm"] = round(_q(minutes, cfg.night_quantile), 3)
            point["flagged"] = point["meter_lpm"] >= cfg.min_leak_lpm
            for b in branches:
                vals = branch_nights[b.flow_sensor].get(d, [])
                point["branches"][b.flow_sensor] = round(_q(vals, cfg.night_quantile), 3) if len(vals) >= cfg.min_night_minutes else None
        out.append(point)
    return out


def detect_hidden_leak(stream: Stream, house: dict, building: dict, *, as_of: date | None = None,
                       cfg: LeakConfig = LeakConfig(), event_seq: int = 1) -> dict:
    nights = [p for p in nightly_min_flow(stream, house, cfg) if as_of is None or date.fromisoformat(p["date"]) <= as_of]
    diagnostics = {"house_id": house["house_id"], "algorithm": "hidden_leak_min_night_flow", "config": asdict(cfg),
                   "data_range": {"start": stream.ts[0].date().isoformat(), "end": stream.ts[-1].date().isoformat()},
                   "as_of": (as_of or stream.ts[-1].date()).isoformat(), "nightly": nights,
                   "status": "NO_EVENT" if nights else "INSUFFICIENT_DATA"}
    event = None
    streak: list[dict] = []
    for p in nights:
        streak = streak + [p] if p["flagged"] else []
        if event is None and len(streak) >= cfg.consecutive_nights:
            event = _hidden_leak_event(house, building, streak, cfg, event_seq)
            diagnostics["status"] = "EVENT"
    return {"event": event, "diagnostics": diagnostics}


def _hidden_leak_event(house, building, streak, cfg: LeakConfig, event_seq: int) -> dict:
    branches, _ = discover_branches(house)
    night_flow = statistics.median(p["meter_lpm"] for p in streak)
    by_sensor = {b.flow_sensor: b for b in branches}
    branch_flow = {}
    for code in by_sensor:
        vals = [p["branches"].get(code) for p in streak if p["branches"].get(code) is not None]
        branch_flow[code] = statistics.median(vals) if vals else 0.0
    leaking = {code: v for code, v in branch_flow.items() if v >= cfg.min_leak_lpm}
    explained = sum(leaking.values())
    unexplained = max(0.0, night_flow - explained)

    if leaking and unexplained < cfg.unexplained_ratio * night_flow:
        # 流量最大的支路所在区域；同区域冷热两侧都有流量视为 BOTH
        main = max(leaking, key=leaking.get)
        area = by_sensor[main].area
        sides = {by_sensor[c].side for c in leaking if by_sensor[c].area == area}
        side = "BOTH" if sides == {"COLD", "HOT"} else sides.pop()
        priors = HIDDEN_LEAK_PRIORS.get((area, side), [("BRANCH", 0.5)])
        location_area, where = area, f"{AREA_NAMES.get(area, area)}{ {'COLD': '冷水', 'HOT': '热水', 'BOTH': '冷热水'}[side]}支路"
    else:
        priors = HIDDEN_LEAK_PRIORS[("UNMETERED", None)]
        location_area, where = "IN", "各支路流量计之外（热水器或户内主管）"
    strength = min(1.0, 0.8 + 0.05 * (len(streak) - cfg.consecutive_nights))
    candidates = _candidates(house, location_area, priors, strength)
    last = date.fromisoformat(streak[-1]["date"])
    detected = datetime.combine(last, time(cfg.night_end_h, 0))
    loss = night_flow * 1440
    evidence_text = (f"连续{len(streak)}晚凌晨{cfg.night_start_h}–{cfg.night_end_h}点总表始终有流量，最小约{night_flow:.2f} L/min，"
                     f"每天约漏{loss:.0f} L；持续小流量出现在{where}")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EVT-{last.strftime('%Y%m%d')}-{house['house_id']}-{event_seq:04d}",
        "scope": "HOUSE",
        "house_id": house["house_id"],
        "related_houses": [],
        "batch_id": house.get("batch_id"),
        "domain": "WATER",
        "event_type": "HIDDEN_LEAK",
        "severity": "HIGH" if night_flow >= 2.0 else "MEDIUM",
        "detected_at": detected.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "fault_started_est": streak[0]["date"],
        "location_candidates": candidates,
        "evidence": {
            "night_min_flow_lpm": round(night_flow, 2),
            "consecutive_nights": len(streak),
            "est_daily_loss_l": round(loss),
            "night_window": f"{cfg.night_start_h:02d}:00-{cfg.night_end_h:02d}:00",
            "branch_night_flow_lpm": {c: round(v, 2) for c, v in branch_flow.items()},
            "unexplained_lpm": round(unexplained, 2),
        },
        "evidence_text": evidence_text[:200],
        "control_actions_taken": [],
        "archive_context": _archive_context(house, building, candidates[0] if candidates else None),
        "data_source": DATA_SOURCE,
    }


def leak_still_present(stream: Stream, house: dict, day: date, cfg: LeakConfig = LeakConfig()) -> dict | None:
    """复查：取不晚于 ``day`` 的最后一个有效夜间，返回该夜数据点（含 flagged）。"""
    nights = [p for p in nightly_min_flow(stream, house, cfg)
              if date.fromisoformat(p["date"]) <= day and p["meter_lpm"] is not None]
    return nights[-1] if nights else None


# ---------------------------------------------------------------------------
# 爆管 / 软管脱落
# ---------------------------------------------------------------------------
def detect_pipe_burst(stream: Stream, house: dict, building: dict, *, cfg: LeakConfig = LeakConfig(),
                      event_seq: int = 1) -> dict:
    branches, meter = discover_branches(house)
    diagnostics = {"house_id": house["house_id"], "algorithm": "pipe_burst_branch_overflow", "config": asdict(cfg),
                   "data_range": {"start": stream.ts[0].date().isoformat(), "end": stream.ts[-1].date().isoformat()},
                   "branch_cv_capacity": {b.flow_sensor: round(b.cv_capacity, 3) for b in branches},
                   "trace": [], "status": "NO_EVENT"}
    for b in branches:
        limit = cfg.burst_factor * b.cv_capacity
        col, pcol = stream.columns[b.flow_sensor], stream.columns[b.pressure_sensor]
        run_start = run_last = None
        for i, (t, v) in enumerate(zip(stream.ts, col)):
            if v is None or v < cfg.burst_min_flow_lpm or pcol[i] is None:
                continue
            if v / 60.0 / (max(pcol[i], 0.005) ** 0.5) <= limit:
                continue
            # 超限采样之间的间隔超过允许缺口（丢包）就重新计时
            if run_start is None or (t - stream.ts[run_last]).total_seconds() > cfg.burst_max_gap_s:
                run_start = i
            run_last = i
            if (t - stream.ts[run_start]).total_seconds() >= cfg.burst_min_duration_s:
                event = _burst_event(stream, house, building, b, branches, meter, run_start, i, limit, cfg, event_seq)
                diagnostics["trace"] = _burst_trace(stream, meter, b.flow_sensor, stream.ts[run_start], cfg)
                diagnostics["threshold_cv"] = round(limit, 3)
                diagnostics["status"] = "EVENT"
                return {"event": event, "diagnostics": diagnostics}
    return {"event": None, "diagnostics": diagnostics}


def _burst_event(stream, house, building, branch: Branch, branches, meter, i0, i1, limit, cfg: LeakConfig, event_seq):
    onset, detected = stream.ts[i0], stream.ts[i1]
    closed = detected + timedelta(seconds=cfg.valve_close_delay_s)
    # 损失：起始到关阀之间的总表流量积分（L/min × 秒 / 60），关阀后按零计
    meter_col = stream.columns[meter]
    loss, peak, prev_t = 0.0, 0.0, None
    for t, v in zip(stream.ts, meter_col):
        if t < onset or t > closed or v is None:
            continue
        if t <= detected:
            peak = max(peak, v)
        dt = 1.0 if prev_t is None else min((t - prev_t).total_seconds(), 60.0)
        loss += v * dt / 60.0
        prev_t = t
    same_area = [b for b in branches if b.area == branch.area]

    def cv_at(b: Branch) -> float:
        q, p = stream.columns[b.flow_sensor][i1] or 0.0, stream.columns[b.pressure_sensor][i1] or 0.0
        return q / 60.0 / (max(p, 0.005) ** 0.5)

    outlet_cv = cv_at(branch)
    hot_over = any(b.side == "HOT" and b.flow_sensor != branch.flow_sensor and cv_at(b) > limit for b in same_area)
    side = "BOTH" if hot_over else branch.side
    candidates = _candidates(house, branch.area, BURST_PRIORS[side])
    nodes = _nodes(house)
    valve = next(c for c, n in nodes.items() if n["kind"] == "VALVE" and n["area"] == "IN")
    # 楼下同户位住户可能被渗漏波及（模拟楼栋每层 6 户，楼下一定存在）
    related = [f"{house['floor'] - 1}{house['position']}"] if house["floor"] > 1 else []
    where = f"{AREA_NAMES.get(branch.area, branch.area)}{'冷水' if branch.side == 'COLD' else '热水'}支路"
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EVT-{detected.strftime('%Y%m%d')}-{house['house_id']}-{event_seq:04d}",
        "scope": "HOUSE",
        "house_id": house["house_id"],
        "related_houses": related,
        "batch_id": house.get("batch_id"),
        "domain": "WATER",
        "event_type": "PIPE_BURST",
        "severity": "CRITICAL",
        "detected_at": detected.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "location_candidates": candidates,
        "evidence": {
            "peak_flow_lpm": round(peak, 1),
            "duration_s": int((closed - onset).total_seconds()),
            "rated_max_lpm": round(branch.rated_lpm, 1),
            "outlet_cv": round(outlet_cv, 2),
            "cv_capacity": round(branch.cv_capacity, 2),
            "threshold_cv": round(limit, 2),
            "branch_pressure_mpa": stream.columns[branch.pressure_sensor][i1],
            "matched_fixture": "NONE",
            "est_loss_l": round(loss),
            "occupancy": "UNKNOWN",
            "branch_sensor": branch.flow_sensor,
            "onset_at": onset.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        },
        "evidence_text": (f"{where}流量{peak:.0f} L/min的同时末端水压降到{stream.columns[branch.pressure_sensor][i1]:.2f} MPa，"
                          f"出水口通流能力是该支路全部器具之和的{outlet_cv / branch.cv_capacity:.1f}倍，持续{cfg.burst_min_duration_s}秒，"
                          f"不像任何正常用水；已自动关闭入户总阀，估计漏水约{loss:.0f} L")[:200],
        "control_actions_taken": [{
            "action": "CLOSE_MAIN_VALVE", "target": valve,
            "executed_at": closed.strftime("%Y-%m-%dT%H:%M:%S+08:00"), "result": "SUCCESS",
        }],
        "archive_context": _archive_context(house, building, candidates[0] if candidates else None),
        "data_source": DATA_SOURCE,
    }


def _burst_trace(stream: Stream, meter: str, branch_sensor: str, onset: datetime, cfg: LeakConfig) -> list[dict]:
    """事件前后逐分钟最大流量，供前端画图（前 10 分钟到后 20 分钟）。"""
    lo, hi = onset - timedelta(minutes=10), onset + timedelta(minutes=20)
    buckets: dict[datetime, dict] = {}
    for t, m, b in zip(stream.ts, stream.columns[meter], stream.columns[branch_sensor]):
        if lo <= t < hi:
            key = t.replace(second=0)
            cur = buckets.setdefault(key, {"meter": 0.0, "branch": 0.0})
            cur["meter"] = max(cur["meter"], m or 0.0)
            cur["branch"] = max(cur["branch"], b or 0.0)
    return [{"time": k.strftime("%H:%M"), "meter_lpm": round(v["meter"], 1), "branch_lpm": round(v["branch"], 1)}
            for k, v in sorted(buckets.items())]
