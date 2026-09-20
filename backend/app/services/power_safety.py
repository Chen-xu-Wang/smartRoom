"""用电安全检测：漏电（E2 绝缘劣化 + 受潮跳闸）与电压是否在电器安全范围内（E5）。

输入：住户逐分钟用电读数（户总电压/电流，各回路电流、剩余电流、断路器状态，室外湿度）、
同楼栋其它住户的电压与电流、扩展的一房一码档案。全部是纯函数，不访问数据库。

漏电
    回路正常泄漏会随湿度和负载变化（梅雨季卫生间回路泄漏升高属于正常现象）。先用入住后两周的数据，
    按"剩余电流 = a + b·湿度超额 + c·回路电流"做最小二乘拟合，得到每条回路自己的正常水平；
    之后只看超出预测值的部分（超额），湿度和用电习惯的影响就被扣除了。
    - 渐进劣化：连续 2 天超额的日 95% 分位 ≥ 5 mA 即预警（远低于 30 mA 保护动作值，留出检修时间）。
    - 受潮跳闸：断路器在剩余电流 ≥ 15 mA 的那一分钟断开，判定为漏电跳闸；统计 3 小时内的反复跳闸次数。

电压
    判据一，供电质量：GB/T 12325 单相 220 V 允许偏差 +7%/−10%，即 198–235.4 V。
    判据二，电器安全：各类电器铭牌允许电压范围，只统计该电器正在运行（或常通电）时越限的分钟。
    报出条件：最近 3 天累计越限 ≥ 20 分钟，且至少 2 天出现越限。
    （最初按"单日越限 ≥ 10 分钟、3 天内 2 天"判断，但接头松动引起的欠电压只在大功率电器同时运行时出现，
    每天只有几分钟，却可能低到 160 V；按单日门槛会漏报，见 run_sample_power.py 报告的调参记录。）
    判据三，定位：越限时同相其它住户是否同时越限。多数同时越限 → 供电侧（通知物业联系供电部门）；
    只有本户越限，且"电压随本户电流下降"的斜率（等效线路电阻）明显大于入住初期 → 本户进线或零线接头松动。
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from .water_blockage import DATA_SOURCE, SCHEMA_VERSION, Stream

# 电器允许工作电压（V），与 sim_params.yaml 的 power.appliances.voltage_ranges_v 一致（铭牌典型值，待按实际型号核对）
APPLIANCE_RANGES = {
    "FRIDGE": ("冰箱", 187, 242),
    "AC_INVERTER": ("变频空调", 165, 265),
    "WATER_HEATER": ("电热水器", 198, 242),
    "HEATING_SMALL": ("电水壶/微波炉/电饭煲/吹风机", 198, 242),
    "ELECTRONICS": ("电视/电脑/照明等", 90, 264),
}
RH_COLUMN = "SN-BLDG-OUT-TH01:rh_pct"


@dataclass(frozen=True)
class LeakageConfig:
    baseline_days: int = 14
    humidity_ref_pct: float = 60.0
    daily_quantile: float = 0.95
    excess_warn_ma: float = 5.0
    trend_start_ma: float = 2.0      # 超额首次超过此值记为开始变差
    persist_days: int = 2
    min_closed_minutes: int = 360
    trip_residual_ma: float = 15.0   # 跳闸分钟剩余电流不低于此值，判定为漏电跳闸（额定 30 mA 的一半）
    near_trip_fraction: float = 0.5  # 剩余电流达到额定动作电流的一半即"接近动作值"
    repeat_window_h: int = 3


@dataclass(frozen=True)
class VoltageConfig:
    nominal_v: float = 220.0
    upper_ratio: float = 0.07        # GB/T 12325-2008（待核对原文）
    lower_ratio: float = -0.10
    window_days: int = 3
    window_minutes: int = 20         # 窗口内累计越限分钟
    min_days_in_window: int = 2      # 窗口内至少几天出现越限
    same_phase_ratio: float = 0.6
    baseline_days: int = 14
    wiring_ohm_warn: float = 0.5
    wiring_ratio_warn: float = 3.0
    risk_minutes: int = 10

    @property
    def limits(self) -> tuple[float, float]:
        return round(self.nominal_v * (1 + self.lower_ratio), 1), round(self.nominal_v * (1 + self.upper_ratio), 1)


# 漏电定位先验（模型假设）：插座进水/受潮最常见，其次是回路上的电器，再次是线缆本身
LEAKAGE_PRIORS = {
    "GRADUAL": [("SOCKET", 0.45), ("APPLIANCE", 0.30), ("CABLE", 0.20)],
    "TRIP": [("SOCKET", 0.55), ("APPLIANCE", 0.25), ("CABLE", 0.10)],
}


def _ts_iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _q(values: list[float], q: float) -> float:
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _lstsq3(rows: list[tuple[float, float, float]], ys: list[float]) -> tuple[float, float, float]:
    """y ≈ β0·x0 + β1·x1 + β2·x2 的最小二乘解（正规方程 + 高斯消元，带微小岭项防奇异）。"""
    a = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for x, y in zip(rows, ys):
        for i in range(3):
            b[i] += x[i] * y
            for j in range(3):
                a[i][j] += x[i] * x[j]
    for i in range(3):
        a[i][i] += 1e-6
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        a[col], a[piv], b[col], b[piv] = a[piv], a[col], b[piv], b[col]
        for r in range(3):
            if r != col and a[col][col]:
                f = a[r][col] / a[col][col]
                for c in range(3):
                    a[r][c] -= f * a[col][c]
                b[r] -= f * b[col]
    return tuple(b[i] / a[i][i] if a[i][i] else 0.0 for i in range(3))


# ---------------------------------------------------------------------------
# 漏电
# ---------------------------------------------------------------------------
def _circuit_devices(house: dict, circuit_code: str) -> tuple[list[dict], list[dict]]:
    devices = [d for d in house["devices"] if d.get("circuit_code") == circuit_code]
    sockets = [d for d in devices if "SOCKET" in (d.get("role") or "")]
    appliances = [d for d in devices if d not in sockets and "LIGHT" not in (d.get("role") or "")]
    return sockets, appliances


def _leakage_candidates(house: dict, circuit: dict, pattern: str) -> list[dict]:
    code = circuit["circuit_code"]
    sockets, appliances = _circuit_devices(house, code)
    pools = {"SOCKET": sockets, "APPLIANCE": appliances}
    out = []
    for role, prior in LEAKAGE_PRIORS[pattern]:
        if role == "CABLE":
            out.append({"segment_code": code, "segment_name": f"{circuit['name']}线缆"[:40], "device_code": None,
                        "in_archive": False, "confidence": prior})
            continue
        pool = pools[role]
        if not pool:
            continue
        # 同类多个部件时平分先验，第一个略高（档案顺序：台面上方插座在前）
        share = [0.6, 0.4] if len(pool) >= 2 else [1.0]
        for d, w in zip(pool, share):
            out.append({"segment_code": code, "segment_name": f"{d['location'] or ''}{d['name']}"[:40],
                        "device_code": d["device_code"], "in_archive": bool(d.get("in_archive")),
                        "confidence": round(prior * w, 2)})
    return sorted(out, key=lambda c: c["confidence"], reverse=True)[:3]


def detect_leakage(stream: Stream, house: dict, building: dict, *, cfg: LeakageConfig = LeakageConfig(),
                   event_seq_start: int = 1) -> dict:
    """返回 {"events": [契约①...], "diagnostics": {...}}，每条回路至多一个事件（最早的那个）。"""
    rh = stream.columns.get(RH_COLUMN)
    first_day = stream.ts[0].date()
    baseline_end = first_day + timedelta(days=cfg.baseline_days)
    diagnostics = {"house_id": house["house_id"], "algorithm": "leakage_humidity_adjusted", "config": asdict(cfg),
                   "data_range": {"start": first_day.isoformat(), "end": stream.ts[-1].date().isoformat()},
                   "circuits": {}, "status": "NO_EVENT"}
    candidates_events = []
    for circuit in house["circuits"]:
        if not circuit.get("rcd_trip_ma"):
            continue
        code = circuit["circuit_code"]
        res, closed, cur = (stream.columns[f"{code}:residual_ma"], stream.columns[f"{code}:closed"],
                            stream.columns[f"{code}:current_a"])

        def feats(i):
            return (1.0, max((rh[i] or cfg.humidity_ref_pct) - cfg.humidity_ref_pct, 0.0) / 10.0, cur[i] or 0.0)

        base_idx = [i for i, t in enumerate(stream.ts) if t.date() < baseline_end and closed[i] == 1 and res[i] is not None]
        if len(base_idx) < 1000:
            continue
        beta = _lstsq3([feats(i) for i in base_idx], [res[i] for i in base_idx])
        base_raw_p95 = _q([res[i] for i in base_idx], cfg.daily_quantile)

        by_day: dict[date, dict] = {}
        for i, t in enumerate(stream.ts):
            if res[i] is None or closed[i] is None:
                continue
            d = by_day.setdefault(t.date(), {"raw": [], "excess": [], "trips": [], "rh": []})
            if closed[i] == 1:
                pred = sum(b * x for b, x in zip(beta, feats(i)))
                d["raw"].append(res[i])
                d["excess"].append(res[i] - pred)
                if rh and rh[i] is not None:
                    d["rh"].append(rh[i])
            elif res[i] >= cfg.trip_residual_ma:
                d["trips"].append((t, res[i]))

        daily, event, trend_start = [], None, None
        streak = 0
        for day in sorted(by_day):
            d = by_day[day]
            point = {"date": day.isoformat(), "p95_ma": None, "excess_p95_ma": None, "trips": len(d["trips"]),
                     "rh_mean": round(statistics.mean(d["rh"]), 1) if d["rh"] else None, "flagged": False}
            if len(d["raw"]) >= cfg.min_closed_minutes:
                point["p95_ma"] = round(_q(d["raw"], cfg.daily_quantile), 2)
                point["excess_p95_ma"] = round(_q(d["excess"], cfg.daily_quantile), 2)
                if day >= baseline_end:
                    point["flagged"] = point["excess_p95_ma"] >= cfg.excess_warn_ma
                    if trend_start is None and point["excess_p95_ma"] >= cfg.trend_start_ma:
                        trend_start = day
                    elif point["excess_p95_ma"] < cfg.trend_start_ma and not point["flagged"]:
                        trend_start = None
            daily.append(point)
            if event is not None or day < baseline_end:
                continue
            if d["trips"]:
                t0, ma0 = d["trips"][0]
                repeats = [x for day2 in sorted(by_day) if day2 >= day for x in by_day[day2]["trips"]
                           if x[0] - t0 <= timedelta(hours=cfg.repeat_window_h)]
                event = ("TRIP", t0, max(m for _, m in repeats), len(repeats), point, trend_start)
                continue
            streak = streak + 1 if point["flagged"] else 0
            if streak >= cfg.persist_days:
                event = ("GRADUAL", datetime.combine(day, datetime.max.time()).replace(microsecond=0),
                         point["p95_ma"], 0, point, trend_start)
        diagnostics["circuits"][code] = {"baseline_p95_ma": round(base_raw_p95, 2),
                                         "model": {"intercept": round(beta[0], 3), "per_10pct_rh": round(beta[1], 3),
                                                   "per_amp": round(beta[2], 3)},
                                         "daily": daily}
        if event:
            candidates_events.append((event[1], circuit, event, base_raw_p95))

    events = []
    for seq, (_, circuit, (pattern, when, recent_ma, trips, point, trend_start), base_p95) in enumerate(
            sorted(candidates_events, key=lambda x: x[0]), start=event_seq_start):
        events.append(_leakage_event(house, building, circuit, pattern, when, recent_ma, trips, point, trend_start,
                                     base_p95, cfg, seq))
    if events:
        diagnostics["status"] = "EVENT"
    return {"events": events, "diagnostics": diagnostics}


def _leakage_event(house, building, circuit, pattern, when, recent_ma, trips, point, trend_start, base_p95,
                   cfg: LeakageConfig, seq: int) -> dict:
    rated = circuit["rcd_trip_ma"]
    near = recent_ma >= cfg.near_trip_fraction * rated
    candidates = _leakage_candidates(house, circuit, pattern)
    trend_days = (when.date() - trend_start).days if (pattern == "GRADUAL" and trend_start) else 0
    if pattern == "TRIP":
        text = (f"{circuit['name']}在{when.strftime('%m-%d %H:%M')}因漏电跳闸，跳闸时漏电流{recent_ma:.0f} mA"
                f"（保护动作值{rated} mA）" + (f"，{cfg.repeat_window_h}小时内重新合闸后又跳闸，共{trips}次" if trips > 1 else ""))
    else:
        text = (f"{circuit['name']}漏电流近{max(trend_days, cfg.persist_days)}天持续升高，扣除湿度和用电影响后仍比入住初期高"
                f"{point['excess_p95_ma']:.1f} mA，目前约{recent_ma:.1f} mA，保护动作值{rated} mA"
                + ("，已接近动作值" if near else ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EVT-{when.strftime('%Y%m%d')}-{house['house_id']}-{seq:04d}",
        "scope": "HOUSE",
        "house_id": house["house_id"],
        "related_houses": [],
        "batch_id": house.get("batch_id"),
        "domain": "POWER",
        "event_type": "LEAKAGE_CURRENT",
        "severity": "HIGH" if (pattern == "TRIP" or near) else "MEDIUM",
        "detected_at": _ts_iso(when),
        **({"fault_started_est": trend_start.isoformat()} if trend_start and pattern == "GRADUAL" else {}),
        "location_candidates": candidates,
        "evidence": {
            "circuit_code": circuit["circuit_code"],
            "circuit_name": circuit["name"],
            "residual_ma_baseline": round(base_p95, 2),
            "residual_ma_recent": round(recent_ma, 1),
            "trip_threshold_ma": rated,
            "trend_days": trend_days,
            "pattern": pattern,
            "trip_count": trips,
            "near_trip": near,
            "excess_ma": point["excess_p95_ma"],
            "humidity_adjusted": True,
            "rh_mean_pct": point["rh_mean"],
        },
        "evidence_text": text[:200],
        "control_actions_taken": ([{"action": "TRIP_CIRCUIT", "target": circuit["circuit_code"],
                                    "executed_at": _ts_iso(when), "result": "SUCCESS"}] if pattern == "TRIP" else []),
        "archive_context": _archive_context(house, building, candidates[0] if candidates else None),
        "data_source": DATA_SOURCE,
    }


def _archive_context(house: dict, building: dict, top: dict | None) -> dict:
    ctx = {"building": building.get("building", ""), "unit": building.get("unit", ""), "floor": house["floor_label"],
           "layout": house["layout"], "in_archive": bool(house["in_archive"]), "recent_repairs_180d": 0}
    device = next((d for d in house["devices"] if top and d["device_code"] == top.get("device_code")), None)
    if device:
        ctx["device_name"] = device["name"]
        if device.get("spec"):
            ctx["device_model"] = device["spec"]
        if device.get("install_date"):
            ctx["install_date"] = device["install_date"]
    return ctx


# ---------------------------------------------------------------------------
# 电压
# ---------------------------------------------------------------------------
def _running_masks(stream: Stream, house: dict) -> dict[str, list[bool]]:
    """各类电器"正在运行或常通电"的逐行掩码。"""
    hid = house["house_id"]
    n = len(stream.ts)

    def col(short):
        return stream.columns.get(f"CB-{hid}-{short}:current_a", [0.0] * n)

    kt, bt, wh = col("KT"), col("BT"), col("WH")
    ac = [max(a or 0, b or 0) for a, b in zip(col("AC1"), col("AC2"))]
    return {
        "FRIDGE": [True] * n,
        "ELECTRONICS": [True] * n,
        "WATER_HEATER": [(x or 0) > 1.0 for x in wh],
        "AC_INVERTER": [x > 0.5 for x in ac],
        "HEATING_SMALL": [(a or 0) > 3.0 or (b or 0) > 3.0 for a, b in zip(kt, bt)],
    }


def _slope_ohm(pairs: list[tuple[float, float]]) -> float | None:
    """ΔV（本户 − 同相邻户中位数）对本户电流的线性回归斜率取负，即等效线路电阻。"""
    if len(pairs) < 200:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-9:
        return None
    return -sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def detect_voltage(stream: Stream, neighbors: Stream, house: dict, building_doc: dict, *,
                   cfg: VoltageConfig = VoltageConfig(), event_seq: int = 1) -> dict:
    """``building_doc`` 为完整的 sim_building（需要各户相别）。"""
    hid = house["house_id"]
    lo, hi = cfg.limits
    v = stream.columns[f"CB-{hid}-MAIN:voltage_v"]
    cur = stream.columns[f"CB-{hid}-MAIN:current_a"]
    phases = {h["house_id"]: h["phase"] for h in building_doc["houses"]}
    nb_ids = sorted({c.split(":")[0] for c in neighbors.columns})
    same = [h for h in nb_ids if phases.get(h) == house["phase"]]
    other = [h for h in nb_ids if phases.get(h) != house["phase"]]
    nb_index = {t: i for i, t in enumerate(neighbors.ts)}
    first_day = stream.ts[0].date()
    baseline_end = first_day + timedelta(days=cfg.baseline_days)

    def out(x):
        return x is not None and (x < lo or x > hi)

    daily: dict[date, dict] = {}
    for i, t in enumerate(stream.ts):
        if v[i] is None:
            continue
        d = daily.setdefault(t.date(), {"vmin": v[i], "vmax": v[i], "out": 0, "last_out": None})
        d["vmin"], d["vmax"] = min(d["vmin"], v[i]), max(d["vmax"], v[i])
        if out(v[i]):
            d["out"] += 1
            d["last_out"] = t
    points = [{"date": day.isoformat(), "vmin": round(d["vmin"], 1), "vmax": round(d["vmax"], 1),
               "minutes_out": d["out"], "flagged": d["out"] > 0} for day, d in sorted(daily.items())]
    diagnostics = {"house_id": hid, "algorithm": "voltage_gb12325_appliance_neighbors", "config": asdict(cfg),
                   "limits_v": [lo, hi], "data_range": {"start": first_day.isoformat(), "end": stream.ts[-1].date().isoformat()},
                   "daily": points, "status": "NO_EVENT", "same_phase_neighbors": same, "other_phase_neighbors": other}

    event_day = None
    for k in range(len(points)):
        window = points[max(0, k - cfg.window_days + 1):k + 1]
        if (points[k]["flagged"] and sum(p["minutes_out"] for p in window) >= cfg.window_minutes
                and sum(p["flagged"] for p in window) >= cfg.min_days_in_window):
            event_day = k
            break
    if event_day is None:
        return {"event": None, "diagnostics": diagnostics}

    window_days = {date.fromisoformat(p["date"]) for p in points[max(0, event_day - cfg.window_days + 1):event_day + 1]
                   if p["flagged"]}
    det_day = date.fromisoformat(points[event_day]["date"])
    run_start = det_day
    for p in reversed(points[:event_day + 1]):
        if not p["flagged"]:
            break
        run_start = date.fromisoformat(p["date"])

    running = _running_masks(stream, house)
    risk = {k: 0 for k in APPLIANCE_RANGES}
    same_hits, same_total, other_hits, other_total = 0, 0, 0, 0
    minutes_out, vmin, vmax, worst_t, worst_dev = 0, None, None, None, 0.0
    for i, t in enumerate(stream.ts):
        if t.date() not in window_days or v[i] is None:
            continue
        vmin = v[i] if vmin is None else min(vmin, v[i])
        vmax = v[i] if vmax is None else max(vmax, v[i])
        if not out(v[i]):
            continue
        minutes_out += 1
        dev = max(lo - v[i], v[i] - hi)
        if dev > worst_dev:
            worst_dev, worst_t = dev, t
        for key, (_, a, b) in APPLIANCE_RANGES.items():
            if running[key][i] and (v[i] < a or v[i] > b):
                risk[key] += 1
        j = nb_index.get(t)
        if j is None:
            continue
        for h in same:
            x = neighbors.columns[f"{h}:voltage_v"][j]
            if x is not None:
                same_total += 1
                same_hits += out(x)
        for h in other:
            x = neighbors.columns[f"{h}:voltage_v"][j]
            if x is not None:
                other_total += 1
                other_hits += out(x)
    same_ratio = same_hits / same_total if same_total else 0.0
    other_ratio = other_hits / other_total if other_total else 0.0

    def wiring_ohm(day_pred) -> float | None:
        pairs = []
        for i, t in enumerate(stream.ts):
            if not day_pred(t.date()) or v[i] is None or cur[i] is None:
                continue
            j = nb_index.get(t)
            if j is None:
                continue
            ref = [neighbors.columns[f"{h}:voltage_v"][j] for h in same if neighbors.columns[f"{h}:voltage_v"][j] is not None]
            if ref:
                pairs.append((cur[i], v[i] - statistics.median(ref)))
        return _slope_ohm(pairs)

    r_recent = wiring_ohm(lambda d: d in window_days)
    r_base = wiring_ohm(lambda d: d < baseline_end)

    if same and same_ratio >= cfg.same_phase_ratio:
        inference = "SUPPLY"
        phase_scope = "ALL_PHASES" if (other and other_ratio >= cfg.same_phase_ratio) else "SINGLE_PHASE"
    elif r_recent is not None and r_recent >= max(cfg.wiring_ohm_warn, cfg.wiring_ratio_warn * max(r_base or 0.0, 0.05)):
        inference, phase_scope = "HOUSE_WIRING", None
    else:
        inference, phase_scope = "UNKNOWN", None

    at_risk = [{"appliance": key, "name": APPLIANCE_RANGES[key][0], "range_v": [APPLIANCE_RANGES[key][1], APPLIANCE_RANGES[key][2]],
                "minutes_outside": risk[key]} for key in APPLIANCE_RANGES if risk[key] > 0]
    high = vmax is not None and vmax > hi
    low = vmin is not None and vmin < lo
    severity = "HIGH" if any(r["minutes_outside"] >= cfg.risk_minutes for r in at_risk) else "MEDIUM"
    last_out = daily[det_day]["last_out"]
    direction = "过电压" if high and not low else "欠电压" if low and not high else "电压忽高忽低"

    evidence = {
        "voltage_min_v": round(vmin, 1), "voltage_max_v": round(vmax, 1), "limits_v": [lo, hi],
        "minutes_out_of_range": minutes_out, "days_affected": len(window_days), "direction": direction,
        "source_inference": inference, "phase": house["phase"], "phase_scope": phase_scope,
        "same_phase_abnormal_ratio": round(same_ratio, 2), "other_phase_abnormal_ratio": round(other_ratio, 2),
        "wiring_resistance_ohm": None if r_recent is None else round(r_recent, 2),
        "wiring_resistance_baseline_ohm": None if r_base is None else round(r_base, 2),
        "appliances_at_risk": at_risk,
        "worst_at": _ts_iso(worst_t) if worst_t else None,
    }
    risk_text = "、".join(f"{r['name']}（{r['range_v'][0]}–{r['range_v'][1]} V）{r['minutes_outside']}分钟" for r in at_risk[:3])
    if inference == "SUPPLY":
        scope, house_id, related, archive = "BUILDING", None, [
            h["house_id"] for h in building_doc["houses"] if phase_scope == "ALL_PHASES" or h["phase"] == house["phase"]], None
        where = f"同为{house['phase']}相的邻户{same_ratio:.0%}同时越限" + ("，其它相也越限" if phase_scope == "ALL_PHASES" else "，其它相正常")
        event_key, candidates = "BLDG", []
    else:
        scope, house_id, related = "HOUSE", hid, []
        archive = {"building": building_doc["building"].get("building", ""), "unit": building_doc["building"].get("unit", ""),
                   "floor": house["floor_label"], "layout": house["layout"], "in_archive": bool(house["in_archive"]),
                   "recent_repairs_180d": 0}
        where = (f"同相邻户正常（{same_ratio:.0%}同时越限），本户电压随用电电流明显下降，等效线路电阻"
                 f"{evidence['wiring_resistance_ohm']} Ω（入住初期{evidence['wiring_resistance_baseline_ohm']} Ω）")
        event_key = hid
        candidates = ([{"segment_code": f"CB-{hid}-MAIN", "segment_name": "户配电箱进线及零线端子", "device_code": None,
                        "in_archive": False, "confidence": 0.7}] if inference == "HOUSE_WIRING" else [])
    text = (f"{len(window_days)}天内共{minutes_out}分钟电压超出{lo}–{hi} V（{direction}，最低{vmin:.0f} V、最高{vmax:.0f} V）；"
            f"{where}" + (f"；超出电器允许范围：{risk_text}" if risk_text else ""))
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EVT-{det_day.strftime('%Y%m%d')}-{event_key}-{event_seq:04d}",
        "scope": scope,
        "house_id": house_id,
        "related_houses": related,
        "batch_id": house.get("batch_id") if scope == "HOUSE" else None,
        "domain": "POWER",
        "event_type": "VOLTAGE_ABNORMAL",
        "severity": severity,
        "detected_at": _ts_iso(last_out),
        "fault_started_est": run_start.isoformat(),
        "location_candidates": candidates,
        "evidence": evidence,
        "evidence_text": text[:200],
        "control_actions_taken": [],
        "archive_context": archive,
        "data_source": DATA_SOURCE,
    }
    diagnostics["status"] = "EVENT"
    return {"event": event, "diagnostics": diagnostics}
