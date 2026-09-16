"""给水传感器数据流生成：行为事件 → 水力模型 → 传感器读数（含噪声、丢包、故障注入）。

输出两类数据，严格分开存放：
- 公开：``sensor_stream``（检测算法唯一能读的数据）。用水期间 1 秒一行，空闲时 1 分钟一行；
  流量 L/min，压力 MPa。
- 真值：``fixture_uses``（每次用水的器具、开度、冷热比例、真实流量、故障倍数），只用于评估。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import rng as rngmod
from .hydraulics import ActiveUse, HouseNetwork, build_network, solve
from .params import Params

WATER_SENSOR_TYPES = ("FL", "PR")
RAMP_S = 2  # 开阀后流量爬升到稳态的秒数


@dataclass
class Fault:
    """故障注入。

    - ``cv_factor``（器具出口通流能力倍数）/ ``k_factor``（管段阻力倍数）：在 [start, end] 间按
      ``profile`` 从 1 变化到 ``factor_end``，end 之后保持。
    - ``leak``（泄漏孔口系数 c，L/s/√MPa，见 hydraulics.solve）：``LINEAR`` 从 0 渐增到 ``factor_end``
      后保持（暗漏）；``STEP`` 只在 [start, end) 内以 ``factor_end`` 泄漏（爆管、软管脱落，end 为无人
      处置时自然停止的时刻，用于估算"不关阀"的反事实损失）。
    """
    fault_id: str
    fault_type: str
    target: str
    mode: str
    start: str
    end: str
    factor_end: float
    profile: str = "LINEAR"

    def factor(self, t: pd.Timestamp) -> float:
        start, end = pd.Timestamp(self.start), pd.Timestamp(self.end)
        if t < start:
            return 1.0
        if self.profile == "STEP" or t >= end:
            return self.factor_end
        frac = (t - start) / (end - start)
        return 1.0 + (self.factor_end - 1.0) * frac

    def leak_c(self, t: pd.Timestamp) -> float:
        start, end = pd.Timestamp(self.start), pd.Timestamp(self.end)
        if t < start:
            return 0.0
        if self.profile == "STEP":
            return self.factor_end if t < end else 0.0
        if t >= end:
            return self.factor_end
        return self.factor_end * ((t - start) / (end - start))


@dataclass
class PressureEvent:
    """供水压力扰动（干扰工况 N1），在 [start, end) 内入户压力叠加 ``delta_mpa``。"""
    start: str
    end: str
    delta_mpa: float
    note: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    faults: list[Fault] = field(default_factory=list)
    pressure_events: list[PressureEvent] = field(default_factory=list)


def _hot_fraction(row: pd.Series, params: Params, heater_setpoint_c: float) -> float:
    if row["device"] in ("TOILET", "WASHER"):
        return 0.0
    if pd.notna(row.get("hot_fraction")):
        return float(row["hot_fraction"])
    if pd.isna(row.get("mix_temp_c")):
        return 0.0
    month = f"{row['start'].month:02d}"
    t_cold = params["water.hot_water.cold_water_temp_c"][month]
    t_hot = heater_setpoint_c - params["water.hot_water.hot_outlet_drop_c"]
    return float(np.clip((row["mix_temp_c"] - t_cold) / (t_hot - t_cold), 0.0, 1.0))


def expand_uses(events: pd.DataFrame, net: HouseNetwork, params: Params, heater_setpoint_c: float) -> pd.DataFrame:
    """行为层用水事件 → 水力层"器具使用区间"。马桶、洗衣机按水量和实际流量换算时长。"""
    water = events[events["kind"] == "WATER"].sort_values("start")
    solo = {}
    for fx in ("TOILET", "WASHER"):
        if fx in net.fixtures:
            solo[fx] = solve(net, [ActiveUse(fx, 1.0, 0.0)], net.entry_static_mpa).fixture_flow_lps[fx]
    fills = params["water.fixtures.washer_fills_per_cycle"]
    rows = []
    for _, e in water.iterrows():
        dev = e["device"]
        if dev not in net.fixtures:
            continue
        h = _hot_fraction(e, params, heater_setpoint_c)
        start = e["start"]
        if dev == "TOILET":
            rows.append((dev, start, e["volume_l"] / solo[dev], 1.0, 0.0))
        elif dev == "WASHER":
            fill_s = e["volume_l"] / fills / solo[dev]
            for i in range(fills):
                rows.append((dev, start + pd.Timedelta(seconds=e["duration_s"] * i / fills), fill_s, 1.0, 0.0))
        else:
            rows.append((dev, start, e["duration_s"], float(e["open_fraction"]), h))
    uses = pd.DataFrame(rows, columns=["fixture", "start", "duration_s", "open_fraction", "hot_fraction"])
    uses["start_s"] = (uses["start"] - pd.Timestamp("1970-01-01")).dt.total_seconds().round().astype("int64")
    uses["end_s"] = uses["start_s"] + np.maximum(uses["duration_s"].round().astype("int64"), 1)
    uses = uses.sort_values("start_s", kind="stable").reset_index(drop=True)
    # 行为层会给同一器具排出时间重叠的使用（如两人同时淋浴），物理上不可能：
    # 同一器具同一时刻只能一人使用，后到者排队，时长不变
    free_at: dict[str, int] = {}
    for i in uses.index:
        fx = uses.at[i, "fixture"]
        if uses.at[i, "start_s"] < free_at.get(fx, 0):
            shift = free_at[fx] - uses.at[i, "start_s"]
            uses.at[i, "start_s"] += shift
            uses.at[i, "end_s"] += shift
        free_at[fx] = int(uses.at[i, "end_s"])
    return uses.sort_values("start_s", kind="stable").reset_index(drop=True)


def _sensor_columns(net: HouseNetwork) -> list[dict]:
    return sorted((s for s in net.sensors if s["type"] in WATER_SENSOR_TYPES), key=lambda s: s["sensor_code"])


def _reading(state, net: HouseNetwork, sensor: dict, entry_mpa: float) -> float:
    target = sensor["target"]
    if sensor["type"] == "FL":
        return state.segment_flow_lps.get(target, 0.0) * 60.0  # L/min
    node = net.nodes[target]
    # 压力传感器读数 = 目标部件入口压力
    if not node.parents:
        return entry_mpa
    return min(state.node_pressure_mpa[p] for p in node.parents)


def _entry_pressure_series(house: dict, params: Params, minutes: pd.DatetimeIndex, scenario: Scenario,
                           g: np.random.Generator) -> np.ndarray:
    """逐分钟入户静压：分区水源波动（AR(1)）+ 市政早晚高峰压降（仅市政直供区）+ 场景扰动。"""
    base = house["entry_static_pressure_mpa"]
    zone = house["supply_zone"]
    sd = params["water.supply.booster_pressure_noise_mpa"]
    phi = 0.95
    noise = np.empty(len(minutes))
    x = 0.0
    shocks = g.normal(0.0, sd * np.sqrt(1 - phi * phi), len(minutes))
    for i, s in enumerate(shocks):
        x = phi * x + s
        noise[i] = x
    p = base + noise
    if zone == "LOW":
        hour = minutes.hour + minutes.minute / 60
        dip = params["water.supply.municipal_diurnal_dip_mpa"]
        p -= dip * (np.exp(-((hour - 7.5) / 1.0) ** 2) + np.exp(-((hour - 19.5) / 1.5) ** 2))
    for ev in scenario.pressure_events:
        mask = (minutes >= pd.Timestamp(ev.start)) & (minutes < pd.Timestamp(ev.end))
        p[mask] += ev.delta_mpa
    return p


def generate_stream(house: dict, events: pd.DataFrame, heater_setpoint_c: float, params: Params, seed: int,
                    start: date, end: date, scenario: Scenario) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (sensor_stream, fixture_uses_truth)。"""
    net = build_network(house, params)
    hid = house["house_id"]
    g = rngmod.stream(seed, hid, "water_stream", scenario.name)
    sensors = _sensor_columns(net)
    cols = [s["sensor_code"] for s in sensors]

    t0 = pd.Timestamp(start)
    t1 = pd.Timestamp(end) + pd.Timedelta(days=1)
    minutes = pd.date_range(t0, t1, freq="60s", inclusive="left")
    entry = _entry_pressure_series(house, params, minutes, scenario, g)
    epoch = pd.Timestamp("1970-01-01")
    minute0_s = int((t0 - epoch).total_seconds())

    def entry_at(sec: int) -> float:
        idx = min(max((sec - minute0_s) // 60, 0), len(entry) - 1)
        return float(entry[idx])

    uses = expand_uses(events[(events["start"] >= t0) & (events["start"] < t1)], net, params, heater_setpoint_c)
    bursts = [f for f in scenario.faults if f.mode == "leak" and f.profile == "STEP"]
    burst_bounds = [(int((pd.Timestamp(f.start) - epoch).total_seconds()), int((pd.Timestamp(f.end) - epoch).total_seconds()))
                    for f in bursts]

    # 传感器漂移：每个压力传感器一个线性漂移斜率
    drift_90d = params["sensors.pressure_drift_mpa_per_90d"]
    drift_rate = {c: g.uniform(-drift_90d, drift_90d) / (90 * 86400) for c, s in zip(cols, sensors) if s["type"] == "PR"}
    flow_acc = params["sensors.flow_accuracy"]
    p_noise = params["sensors.pressure_noise_mpa"]
    cutoff = params["sensors.flow_low_cutoff_lpm"]

    # ---- 用水期间：按变化点切段，每段水力状态恒定 ----
    # 爆管期间流量大、变化快，和用水期间一样按 1 秒输出
    bounds = sorted(set(uses["start_s"]).union(uses["end_s"]).union(x for bb in burst_bounds for x in bb))
    starts, ends = uses["start_s"].to_numpy(), uses["end_s"].to_numpy()
    blocks, truth_rows = [], []
    active_seconds = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        live = np.nonzero((starts <= a) & (ends > a))[0]
        bursting = any(s0 <= a < s1 for s0, s1 in burst_bounds)
        if len(live) == 0 and not bursting:
            continue
        t_mid = epoch + pd.Timedelta(seconds=a)
        leaks = _apply_faults(net, scenario, t_mid)
        active = [ActiveUse(uses.at[i, "fixture"], uses.at[i, "open_fraction"], uses.at[i, "hot_fraction"]) for i in live]
        p_in = entry_at(a)
        state = solve(net, active, p_in, leaks=leaks)
        secs = np.arange(a, b, dtype="int64")
        active_seconds.append(secs)
        n = len(secs)
        block = {"ts_s": secs}
        # 开阀爬升：只对本段开始时刚开启的器具生效（近似为整段流量读数的前 RAMP_S 秒按比例）
        newly_opened = any(starts[i] == a for i in live) or any(s0 == a for s0, _ in burst_bounds)
        ramp = np.ones(n)
        if newly_opened:
            k = min(RAMP_S, n)
            ramp[:k] = np.linspace(0.5, 1.0, k + 1)[:k]
        for code, s in zip(cols, sensors):
            base = _reading(state, net, s, p_in)
            if s["type"] == "FL":
                val = base * ramp * (1 + g.normal(0.0, flow_acc, n))
                val[val < cutoff] = 0.0
            else:
                val = base + g.normal(0.0, p_noise, n) + drift_rate[code] * (secs - minute0_s)
            block[code] = val
        blocks.append(pd.DataFrame(block))
        for i in live:
            if starts[i] == a:
                fx = uses.at[i, "fixture"]
                node = net.fixtures[fx].node
                truth_rows.append({
                    "fixture": fx, "start": epoch + pd.Timedelta(seconds=int(starts[i])),
                    "duration_s": int(ends[i] - starts[i]), "open_fraction": uses.at[i, "open_fraction"],
                    "hot_fraction": uses.at[i, "hot_fraction"], "flow_lps_at_start": state.fixture_flow_lps[fx],
                    "cv_factor": net.cv_factor.get(node, 1.0), "entry_mpa": p_in,
                    "concurrent_uses": len(live),
                })
        for code, q in state.leak_flow_lps.items():
            truth_rows.append({"fixture": f"LEAK:{code}", "start": t_mid, "duration_s": int(b - a),
                               "open_fraction": None, "hot_fraction": None, "flow_lps_at_start": q,
                               "cv_factor": None, "entry_mpa": p_in, "concurrent_uses": len(live)})

    # ---- 空闲时刻：每分钟一行静压读数 ----
    busy = np.unique(np.concatenate(active_seconds)) if active_seconds else np.array([], dtype="int64")
    minute_s = minute0_s + 60 * np.arange(len(minutes), dtype="int64")
    idle_s = minute_s[~np.isin(minute_s, busy)]
    # 无用水时：没有暗漏则各压力测点等于入户静压；有暗漏则按泄漏稳态计算流量和压降
    p_entry = entry[np.clip((idle_s - minute0_s) // 60, 0, len(entry) - 1)]
    idle_flow, idle_drop, leak_truth = _idle_leak_state(net, scenario, idle_s, p_entry, cols, sensors, epoch)
    idle = {"ts_s": idle_s}
    for code, s in zip(cols, sensors):
        if s["type"] == "FL":
            val = idle_flow[code]
            if val.any():  # 没有暗漏时不消耗随机数，保证无泄漏场景与旧样例逐字节一致
                val = val * (1 + g.normal(0.0, flow_acc, len(idle_s)))
                val[val < cutoff] = 0.0
            idle[code] = val
        else:
            idle[code] = (p_entry - idle_drop[code] + g.normal(0.0, p_noise, len(idle_s))
                          + drift_rate[code] * (idle_s - minute0_s))
    blocks.append(pd.DataFrame(idle))
    truth_rows.extend(leak_truth)

    stream = pd.concat(blocks, ignore_index=True).sort_values("ts_s", kind="stable")
    stream = stream.drop_duplicates("ts_s", keep="first")
    keep = g.random(len(stream)) >= params["sensors.packet_loss_rate"]
    stream = stream[keep].reset_index(drop=True)
    stream.insert(0, "ts", (epoch + pd.to_timedelta(stream.pop("ts_s"), unit="s")).dt.strftime("%Y-%m-%d %H:%M:%S"))
    for code, s in zip(cols, sensors):
        stream[code] = stream[code].round(2 if s["type"] == "FL" else 4)
    return stream, pd.DataFrame(truth_rows)


def _apply_faults(net: HouseNetwork, scenario: Scenario, t: pd.Timestamp) -> dict[str, float]:
    """设置器具/管段倍数，返回此刻的泄漏 {部件: c}。"""
    net.cv_factor, net.k_factor = {}, {}
    leaks: dict[str, float] = {}
    for f in scenario.faults:
        if f.mode == "leak":
            c = f.leak_c(t)
            if c > 0:
                leaks[f.target] = leaks.get(f.target, 0.0) + c
            continue
        target = net.cv_factor if f.mode == "cv_factor" else net.k_factor
        target[f.target] = f.factor(t)
    return leaks


def _path_to_root(net: HouseNetwork, code: str) -> list[str]:
    out, cur = [], net.nodes[code]
    while True:
        out.append(cur.code)
        if not cur.parents:
            return out
        cur = net.nodes[cur.parents[0]]


def _idle_leak_state(net: HouseNetwork, scenario: Scenario, idle_s: np.ndarray, p_entry: np.ndarray,
                     cols: list[str], sensors: list[dict], epoch: pd.Timestamp):
    """空闲分钟的暗漏稳态（向量化）。只有一个泄漏点、且没有其它用水时有解析解：
    Q = c·√P / √(1 + c²·ΣK)，ΣK 为泄漏点到入户的管段阻力之和。多个暗漏同时存在时逐分钟求解。
    """
    n = len(idle_s)
    flow = {c: np.zeros(n) for c, s in zip(cols, sensors) if s["type"] == "FL"}
    drop = {c: np.zeros(n) for c, s in zip(cols, sensors) if s["type"] == "PR"}
    gradual = [f for f in scenario.faults if f.mode == "leak" and f.profile != "STEP"]
    if not gradual or n == 0:
        return flow, drop, []
    times = epoch + pd.to_timedelta(idle_s, unit="s")
    target = gradual[0].target
    if len({f.target for f in gradual}) == 1:
        c = np.array([sum(f.leak_c(t) for f in gradual) for t in times])
        path = _path_to_root(net, target)
        k_path = sum(net.k(x) for x in path)
        q = np.where(c > 0, c * np.sqrt(np.maximum(p_entry, 0)) / np.sqrt(1 + c * c * k_path), 0.0)
        segs = {x: q for x in path}
    else:
        segs = {}
        for i, t in enumerate(times):
            leaks = {}
            for f in gradual:
                leaks[f.target] = leaks.get(f.target, 0.0) + f.leak_c(t)
            st = solve(net, [], float(p_entry[i]), leaks=leaks)
            for x, v in st.segment_flow_lps.items():
                segs.setdefault(x, np.zeros(n))[i] = v
        q = segs.get(target, np.zeros(n))
    for code, s in zip(cols, sensors):
        if s["type"] == "FL" and s["target"] in segs:
            flow[code] = segs[s["target"]] * 60.0
        elif s["type"] == "PR":
            node = net.nodes[s["target"]]
            if node.parents:
                upstream = _path_to_root(net, node.parents[0])
                drop[code] = sum(net.k(x) * segs[x] ** 2 for x in upstream if x in segs)
    truth = [{"fixture": f"LEAK:{target}", "start": times[i], "duration_s": 60, "open_fraction": None,
              "hot_fraction": None, "flow_lps_at_start": float(q[i]), "cv_factor": None,
              "entry_mpa": float(p_entry[i]), "concurrent_uses": 0} for i in np.nonzero(q > 0)[0]]
    return flow, drop, truth


def stream_manifest(house: dict, net_sensors: list[dict], seed: int, start: date, end: date, scenario: Scenario) -> dict:
    return {
        "house_id": house["house_id"],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "sampling": {"active_s": 1, "idle_s": 60},
        "columns": [
            {"sensor_code": s["sensor_code"], "type": s["type"], "target": s["target"],
             "unit": "L/min" if s["type"] == "FL" else "MPa"}
            for s in sorted((s for s in net_sensors if s["type"] in WATER_SENSOR_TYPES), key=lambda s: s["sensor_code"])
        ],
        "scenario": scenario.name,
        "seed": seed,
        "timezone": "+08:00",
        "data_source": "SIMULATED",
        "generator": "data/scripts/run_sample_*.py",
        "note": "只含传感器读数；故障注入计划与器具使用真值在 _truth/ 中，检测算法不得读取。",
    }
