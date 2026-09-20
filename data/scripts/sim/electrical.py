"""用电模型（任务 1.6 的简化版）：行为事件 → 回路负载 → 电压、剩余电流、断路器状态（逐分钟）。

模型
----
- 回路负载：行为层电器事件按功率摊到分钟；冰箱按日耗电折算占空比；洗衣机按洗涤/脱水功率；
  电热水器按"每次热水用量需要补回的热量"加待机散热；空调按使用意图和室外温度估算输入功率。
  **简化**：还没有房间热模型（1.6 完整版），空调负载只随室外温度变化。
- 电压：各相母线电压 = 正常均值 − 晚高峰压降 + AR(1) 波动 + 场景扰动；
  住户电压 = 母线电压 − 户内电流 × (线路电阻 + 接线故障附加电阻)。
- 剩余电流（每分钟最大值）：回路正常泄漏 + 湿度项（厨房、卫生间、热水器回路）+ 负载项 + 噪声 + 故障泄漏。
  超过剩余电流保护实际动作值即跳闸：回路断电、负载归零，按场景设定的时刻重新合闸。

故障与干扰
----------
- ``LeakageFault``：GRADUAL（绝缘渐进劣化，泄漏按平方规律增长）/ WET（插座进水，突发大泄漏，干燥后恢复）。
- ``WiringFault``：户内进线或零线端子松动，附加电阻逐渐增大，大负载时电压明显下降。
- ``PhaseVoltageEvent``：供电侧某相在每天固定时段电压偏移（如夜间轻载过电压）。
- ``HumidityEvent``：梅雨季高湿（干扰工况，检测不应把湿度引起的泄漏上升判为故障）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import rng as rngmod
from .params import Params

WET_CIRCUITS = ("KT", "BT", "WH")
POWER_DEVICE_CIRCUIT = {"KETTLE": "KT", "MICROWAVE": "KT", "RICE_COOKER": "KT", "RANGE_HOOD": "KT",
                        "TV": "SK", "PC": "SK", "HAIR_DRYER": "BT", "BATH_FAN": "BT", "LIGHT": "LT"}


@dataclass
class LeakageFault:
    circuit_code: str
    mode: str                 # GRADUAL / WET
    start: str
    end: str                  # GRADUAL：泄漏达到 ma_end 的时刻；WET：干燥恢复的时刻
    ma_end: float
    reclose_times: list[str] = field(default_factory=list)  # WET：住户尝试重新合闸的时刻
    reclose_daily_at: str = "07:30"                          # GRADUAL：跳闸后住户第二天早上重新合闸
    fault_id: str = ""

    def leak_ma(self, t: pd.Timestamp) -> float:
        start, end = pd.Timestamp(self.start), pd.Timestamp(self.end)
        if t < start:
            return 0.0
        if self.mode == "WET":
            return self.ma_end if t < end else 0.0
        frac = min(1.0, (t - start) / (end - start))
        return self.ma_end * frac * frac


@dataclass
class WiringFault:
    house_id: str
    start: str
    end: str
    r_end_ohm: float
    fault_id: str = ""

    def extra_ohm(self, t: pd.Timestamp) -> float:
        start, end = pd.Timestamp(self.start), pd.Timestamp(self.end)
        if t < start:
            return 0.0
        return self.r_end_ohm * min(1.0, (t - start) / (end - start))


@dataclass
class PhaseVoltageEvent:
    phase: str
    start: str
    end: str
    hour_from: float
    hour_to: float
    delta_v: float
    note: str = ""


@dataclass
class HumidityEvent:
    start: str
    end: str
    rh_pct: float
    note: str = ""


@dataclass
class PowerScenario:
    name: str
    description: str
    leakage_faults: list[LeakageFault] = field(default_factory=list)
    wiring_faults: list[WiringFault] = field(default_factory=list)
    phase_events: list[PhaseVoltageEvent] = field(default_factory=list)
    humidity_events: list[HumidityEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 天气
# ---------------------------------------------------------------------------
def weather(params: Params, minutes: pd.DatetimeIndex, seed: int, scenario: PowerScenario) -> tuple[np.ndarray, np.ndarray]:
    """逐分钟室外温度与相对湿度（合成气象，楼栋共用）。"""
    g = rngmod.stream(seed, "BLDG", "weather")
    days = pd.date_range(minutes[0].normalize(), minutes[-1].normalize(), freq="D")
    t_anom = _ar1(g, len(days), params["environment.outdoor_daily_anomaly"]["sd"], params["environment.outdoor_daily_anomaly"]["ar1"])
    h_spec = params["environment.outdoor_humidity_daily_anomaly"]
    h_anom = _ar1(g, len(days), h_spec["sd"], h_spec["ar1"])
    day_idx = ((minutes.normalize() - days[0]).days).to_numpy()
    hour = (minutes.hour + minutes.minute / 60).to_numpy()
    monthly = params["environment.outdoor_monthly_mean_c"]
    t_mean = np.array([monthly.get(f"{m:02d}", 28.0) for m in minutes.month])
    temp = t_mean + params["environment.outdoor_diurnal_amplitude_c"] * np.cos(2 * np.pi * (hour - 14.5) / 24) + t_anom[day_idx]
    rh = (params["environment.outdoor_humidity_mean_pct"]
          + params["environment.outdoor_humidity_diurnal_amplitude_pct"] * np.cos(2 * np.pi * (hour - 5) / 24)
          + h_anom[day_idx])
    for ev in scenario.humidity_events:
        mask = (minutes >= pd.Timestamp(ev.start)) & (minutes < pd.Timestamp(ev.end))
        rh[mask] = ev.rh_pct + 2.0 * np.cos(2 * np.pi * (hour[mask] - 5) / 24)
    return temp, np.clip(rh, 35, 98)


def _ar1(g: np.random.Generator, n: int, sd: float, phi: float) -> np.ndarray:
    out = np.empty(n)
    x = 0.0
    for i, s in enumerate(g.normal(0.0, sd * math.sqrt(1 - phi * phi), n)):
        x = phi * x + s
        out[i] = x
    return out


# ---------------------------------------------------------------------------
# 负载
# ---------------------------------------------------------------------------
def _add(arr: np.ndarray, t0: pd.Timestamp, start: pd.Timestamp, duration_s: float, watts: float) -> None:
    """把一段恒定功率按秒精度摊到分钟平均功率上。"""
    s0 = (start - t0).total_seconds()
    s1 = s0 + max(duration_s, 0.0)
    if s1 <= 0 or s0 >= len(arr) * 60:
        return
    s0, s1 = max(s0, 0.0), min(s1, len(arr) * 60.0)
    m0, m1 = int(s0 // 60), int(math.ceil(s1 / 60))
    for m in range(m0, m1):
        overlap = min(s1, (m + 1) * 60) - max(s0, m * 60)
        if overlap > 0:
            arr[m] += watts * overlap / 60.0


def circuit_loads(house: dict, frames: dict, profile, params: Params, minutes: pd.DatetimeIndex, temp: np.ndarray,
                  seed: int) -> dict[str, np.ndarray]:
    """{回路代码: 逐分钟平均功率 W}。回路代码为 LT/SK/KT/BT/WH/AC1/AC2。"""
    hid = house["house_id"]
    g = rngmod.stream(seed, hid, "electrical_loads")
    n, t0 = len(minutes), minutes[0]
    codes = [c["circuit_code"].rsplit("-", 1)[1] for c in house["circuits"]]
    loads = {c: np.zeros(n) for c in codes}
    ev = frames["events"]
    ev = ev[ev["house_id"] == hid]
    t_end = minutes[-1] + pd.Timedelta(minutes=1)

    for e in ev[(ev["kind"] == "POWER") & (ev["start"] < t_end)].itertuples():
        circuit = POWER_DEVICE_CIRCUIT.get(e.device)
        if circuit in loads and not pd.isna(e.power_w):
            _add(loads[circuit], t0, e.start, e.duration_s, float(e.power_w))

    # 常开待机（路由器、机顶盒等）
    if "SK" in loads:
        loads["SK"] += profile.habits.get("always_on_w", 0.0)

    # 冰箱：按日耗电折算占空比，周期 60 分钟、相位按户随机
    if "KT" in loads and profile.persona != "VACANT":
        comp_w = params["power.appliances.fridge_compressor_w"]
        duty = min(0.9, profile.habits.get("fridge_daily_kwh", 0.85) * 1000 / 24 / comp_w)
        phase = g.uniform(0, 60)
        on = ((np.arange(n) + phase) % 60) < duty * 60
        loads["KT"] += on * comp_w

    # 洗衣机：洗涤 + 末尾脱水
    washer_circuit = "SK" if house.get("layout_id") in ("T89", "T75") else "BT"
    spin_min = params["power.appliances.washer_spin_min"]
    for e in ev[(ev["device"] == "WASHER") & (ev["start"] < t_end)].itertuples():
        wash_s = max(e.duration_s - spin_min * 60, 0)
        _add(loads[washer_circuit], t0, e.start, wash_s, params["power.appliances.washer_wash_w"])
        _add(loads[washer_circuit], t0, e.start + pd.Timedelta(seconds=wash_s), spin_min * 60, params["power.appliances.washer_spin_w"])

    # 电热水器：补回热水用量的热量 + 待机散热（按时段均匀补热）
    if "WH" in loads:
        heater_w = params["water.hot_water.heater_power_w"]
        setpoint = profile.habits.get("heater_setpoint_c", 55)
        drop = params["water.hot_water.hot_outlet_drop_c"]
        eff_flow = params["water.fixtures.shower_efficiency_grade2_lps"]
        for e in ev[(ev["kind"] == "WATER") & (ev["device"].isin(["SHOWER", "KITCHEN_FAUCET", "BASIN"])) & (ev["start"] < t_end)].itertuples():
            cold = params["water.hot_water.cold_water_temp_c"].get(f"{e.start.month:02d}", 26.0)
            if not pd.isna(e.hot_fraction):
                hot = e.hot_fraction
            elif not pd.isna(e.mix_temp_c):
                hot = min(max((e.mix_temp_c - cold) / max(setpoint - drop - cold, 1), 0), 1)
            else:
                continue
            litres = eff_flow * (e.open_fraction if not pd.isna(e.open_fraction) else 0.6) * e.duration_s * hot
            kwh = litres * 4.186 * (setpoint - cold) / 3600
            if kwh > 0.01:
                _add(loads["WH"], t0, e.start + pd.Timedelta(seconds=e.duration_s * 0.3), kwh / (heater_w / 1000) * 3600, heater_w)
        standby = params["water.hot_water.heater_standby_loss_kwh_per_day"]
        if profile.persona != "VACANT":
            # 每 8 小时补热一次
            per_burst_s = standby / 3 / (heater_w / 1000) * 3600
            for day in pd.date_range(minutes[0].normalize(), minutes[-1].normalize(), freq="D"):
                for h in (2, 10, 18):
                    _add(loads["WH"], t0, day + pd.Timedelta(hours=h, minutes=int(g.uniform(0, 60))), per_burst_s, heater_w)

    # 空调：按意图时段；输入功率随室外温度增大，开机前 10 分钟满功率
    models = params["power.appliances.ac_models"]
    lo, hi = params["power.appliances.ac_modulation_range"]
    for circuit in ("AC1", "AC2"):
        if circuit not in loads:
            continue
        device = next((d for d in house["devices"] if d.get("circuit_code") == f"CB-{hid}-{circuit}"), None)
        rated = models.get(device["spec"] if device else "", models["KFR-26GW"])["rated_input_w"]
        intents = frames["ac_intents"]
        intents = intents[(intents["house_id"] == hid) & (intents["circuit"] == f"CB-{hid}-{circuit}")]
        mask = np.zeros(n, dtype=bool)
        first = np.zeros(n, dtype=bool)
        for it in intents.itertuples():
            a = max(int((it.start - t0).total_seconds() // 60), 0)
            b = min(int((it.end - t0).total_seconds() // 60), n)
            if b > a:
                mask[a:b] = True
                first[a:min(a + 10, b)] = True
        modulation = np.clip(0.45 + 0.04 * (temp - 28.0), lo, hi)
        loads[circuit] += np.where(first, rated, np.where(mask, rated * modulation, 0.0))
        loads[circuit] += params["power.appliances.ac_models"]["KFR-26GW"]["standby_w"]
    return loads


# ---------------------------------------------------------------------------
# 电压、剩余电流、跳闸
# ---------------------------------------------------------------------------
def phase_bus_voltage(params: Params, minutes: pd.DatetimeIndex, seed: int, scenario: PowerScenario) -> dict[str, np.ndarray]:
    hour = (minutes.hour + minutes.minute / 60).to_numpy()
    base = params["power.grid.normal_voltage_mean_v"] - params["power.grid.evening_voltage_drop_v"] * np.exp(-((hour - 20.5) / 2.0) ** 2)
    out = {}
    for phase in ("L1", "L2", "L3"):
        g = rngmod.stream(seed, "BLDG", "voltage", phase)
        v = base + g.normal(0, 0.8) + _ar1(g, len(minutes), params["power.grid.voltage_noise_v"], params["power.grid.voltage_noise_ar1"])
        for ev in scenario.phase_events:
            if ev.phase != phase:
                continue
            in_days = (minutes >= pd.Timestamp(ev.start)) & (minutes < pd.Timestamp(ev.end))
            if ev.hour_from <= ev.hour_to:
                in_hours = (hour >= ev.hour_from) & (hour < ev.hour_to)
            else:
                in_hours = (hour >= ev.hour_from) | (hour < ev.hour_to)
            v = v + np.where(in_days & in_hours, ev.delta_v, 0.0)
        out[phase] = v
    return out


def simulate_house(house: dict, frames: dict, profile, params: Params, minutes: pd.DatetimeIndex, bus: dict,
                   temp: np.ndarray, rh: np.ndarray, seed: int, scenario: PowerScenario) -> tuple[pd.DataFrame, dict]:
    """返回 (逐分钟传感器表, 真值)。列名为 ``{回路编码}:{指标}``。"""
    hid = house["house_id"]
    g = rngmod.stream(seed, hid, "electrical", scenario.name)
    n = len(minutes)
    loads = circuit_loads(house, frames, profile, params, minutes, temp, seed)
    v_bus = bus[house["phase"]]
    r_line = params["power.grid.service_resistance_ohm"]
    wiring = [f for f in scenario.wiring_faults if f.house_id == hid]
    r_extra = np.array([sum(f.extra_ohm(t) for f in wiring) for t in minutes]) if wiring else np.zeros(n)

    residual_spec = params["power.breakers.residual_baseline_ma"]
    trip_frac = params["power.breakers.rcd_actual_trip_fraction"]
    hum_coef = params["power.breakers.residual_humidity_coef_ma_per_10pct"]
    load_coef = params["power.breakers.residual_load_coef_ma_per_kw"]
    noise = params["sensors.residual_noise_ma"]

    cols: dict[str, np.ndarray] = {}
    truth = {"house_id": hid, "trips": [], "leak_daily_max_ma": {}, "wiring_extra_ohm_daily": {}}
    closed_all = {}
    for c in house["circuits"]:
        code = c["circuit_code"]
        short = code.rsplit("-", 1)[1]
        base = max(residual_spec["min"], g.normal(residual_spec["mean"], residual_spec["sd"]))
        humid = hum_coef * np.maximum(rh - 60, 0) / 10 if short in WET_CIRCUITS else np.zeros(n)
        faults = [f for f in scenario.leakage_faults if f.circuit_code == code]
        leak = np.array([sum(f.leak_ma(t) for f in faults) for t in minutes]) if faults else np.zeros(n)
        if faults:
            # 绝缘劣化后受潮更明显：故障泄漏随湿度放大
            leak = leak * (1 + 0.03 * np.maximum(rh - 60, 0) / 10)
            s = pd.Series(leak, index=minutes)
            truth["leak_daily_max_ma"][code] = {str(k.date()): round(float(v), 2) for k, v in s.resample("D").max().items()}
        load_w = loads.get(short, np.zeros(n)).copy()
        residual = base + humid + load_coef * load_w / 1000 + leak + np.abs(g.normal(0, noise, n))
        closed = np.ones(n, dtype=bool)
        trip_minute = np.zeros(n, dtype=bool)
        trip_at = (c["rcd_trip_ma"] or 0) * trip_frac
        if c["rcd_trip_ma"]:
            reclose_minutes = set()
            for f in faults:
                for rt in f.reclose_times:
                    reclose_minutes.add(int((pd.Timestamp(rt) - minutes[0]).total_seconds() // 60))
            is_open = False
            daily_reclose = faults[0].reclose_daily_at if faults and faults[0].mode == "GRADUAL" else None
            for i in range(n):
                if is_open:
                    t = minutes[i]
                    if i in reclose_minutes or (daily_reclose and t.strftime("%H:%M") == daily_reclose):
                        is_open = False
                        truth["trips"].append({"circuit": code, "event": "RECLOSE", "at": str(t)})
                    else:
                        closed[i] = False
                        continue
                if residual[i] >= trip_at:
                    closed[i] = False  # 该分钟内跳闸：记录到的最大剩余电流保留，之后断电
                    trip_minute[i] = True
                    is_open = True
                    truth["trips"].append({"circuit": code, "event": "TRIP", "at": str(minutes[i]), "residual_ma": round(float(residual[i]), 1)})
        # 断开期间没有电流，也测不到剩余电流（跳闸那一分钟保留读数）
        load_w[~closed] = 0.0
        residual = np.where(closed | trip_minute, residual, 0.0)
        loads[short] = load_w
        closed_all[code] = closed
        cols[f"{code}:residual_ma"] = residual
        cols[f"{code}:closed"] = closed.astype(int)

    total_w = sum(loads.values())
    current = total_w / v_bus
    v_house = v_bus - current * (r_line + r_extra)
    step = np.abs(np.diff(current, prepend=current[0]))
    cols[f"CB-{hid}-MAIN:voltage_v"] = v_house
    cols[f"CB-{hid}-MAIN:voltage_min_v"] = v_house - np.abs(g.normal(0, 0.4, n)) - step * (r_line + r_extra)
    cols[f"CB-{hid}-MAIN:voltage_max_v"] = v_house + np.abs(g.normal(0, 0.4, n))
    cols[f"CB-{hid}-MAIN:current_a"] = current * (1 + g.normal(0, params["sensors.current_accuracy"], n))
    for c in house["circuits"]:
        short = c["circuit_code"].rsplit("-", 1)[1]
        cols[f"{c['circuit_code']}:current_a"] = np.maximum(loads[short] / v_house, 0) * (1 + g.normal(0, params["sensors.current_accuracy"], n))
    if wiring:
        s = pd.Series(r_extra, index=minutes)
        truth["wiring_extra_ohm_daily"] = {str(k.date()): round(float(v), 3) for k, v in s.resample("D").max().items()}

    df = pd.DataFrame(cols)
    order = ([f"CB-{hid}-MAIN:voltage_v", f"CB-{hid}-MAIN:voltage_min_v", f"CB-{hid}-MAIN:voltage_max_v", f"CB-{hid}-MAIN:current_a"]
             + [f"{c['circuit_code']}:{m}" for c in house["circuits"] for m in ("current_a", "residual_ma", "closed")])
    return df[order], truth


def generate_power(building: dict, frames: dict, profiles: dict, params: Params, seed: int, start: date, end: date,
                   scenario: PowerScenario, target: str, neighbors: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """返回 (目标住户逐分钟表, 邻户电压与电流表, 真值)。两张表都含室外温湿度列。"""
    minutes = pd.date_range(pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1), freq="60s", inclusive="left")
    temp, rh = weather(params, minutes, seed, scenario)
    bus = phase_bus_voltage(params, minutes, seed, scenario)
    houses = {h["house_id"]: h for h in building["houses"]}
    ts = minutes.strftime("%Y-%m-%d %H:%M:%S")

    main_df, truth = simulate_house(houses[target], frames, profiles[target], params, minutes, bus, temp, rh, seed, scenario)
    main_df.insert(0, "ts", ts)
    main_df["SN-BLDG-OUT-TH01:temp_c"] = temp
    main_df["SN-BLDG-OUT-TH01:rh_pct"] = rh

    nb = {"ts": ts}
    for hid in neighbors:
        df, _ = simulate_house(houses[hid], frames, profiles[hid], params, minutes, bus, temp, rh, seed, scenario)
        nb[f"{hid}:voltage_v"] = df[f"CB-{hid}-MAIN:voltage_v"].to_numpy()
        nb[f"{hid}:current_a"] = df[f"CB-{hid}-MAIN:current_a"].to_numpy()
    nb_df = pd.DataFrame(nb)

    g = rngmod.stream(seed, target, "electrical_packet_loss", scenario.name)
    loss = params["sensors.packet_loss_rate"]
    main_df = main_df[g.random(len(main_df)) >= loss].reset_index(drop=True)
    nb_df = nb_df[g.random(len(nb_df)) >= loss].reset_index(drop=True)
    for df in (main_df, nb_df):
        for c in df.columns:
            if c == "ts":
                continue
            if c.endswith(":closed"):
                df[c] = df[c].astype(int)
            else:
                df[c] = df[c].round(3 if c.endswith("current_a") or c.endswith("residual_ma") else 2)
    truth["phase_bus_daily_max_v"] = {
        p: {str(k.date()): round(float(v), 1) for k, v in pd.Series(bus[p], index=minutes).resample("D").max().items()}
        for p in bus
    }
    return main_df, nb_df, truth
