"""给水侧堵塞检测与定位（W1 进水堵塞，P0）。

输入只有两样"物业可以合法拿到"的东西：
    1. 传感器读数流（流量 L/min、压力 MPa），用水时 1 秒一行、空闲时 1 分钟一行；
    2. 扩展的一房一码档案（给水拓扑、传感器布点、设备清单）。
算法不读取模拟器内部状态或故障真值。

核心指标是"出水能力"：一次淋浴稳态流量 Q 除以混水阀入口压力的平方根，
    cv = Q / √P
它只取决于混水阀之后的通流能力和住户开度，与供水压力高低无关，因此水压波动不会被
误判为堵塞。用近几天淋浴事件 cv 的中位数（典型出水能力）与入住初期的中位数（基线）比较。

统计量选择记录（种子 1001–5005 五份 1302 数据，每份含故障与两个对照，均参与了选择）：
    最初按"出水能力上限"设计，用 P90/P95。但住户很少全开阀门（有的家庭入住两周只全开
    过 1 次），上分位数的基线会被严重低估，5 份里有 2 份完全漏报，P90 还有误报。
    中位数：5/5 检出、首选定位 5/5 正确、对照 0/10 误报，对照最差日变化仅 −12%。
    代价：中位数假设住户开度习惯稳定；若住户因出水变小而主动开大阀门，下降会被部分掩盖
    （行为模型尚未模拟这种补偿）。盲测复核见 run_sample_blockage.py 报告。

本模块全部是纯函数，不访问数据库，便于在没有 MySQL 的环境做确定性测试。
"""
from __future__ import annotations

import csv
import gzip
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

SCHEMA_VERSION = "2.0"
DATA_SOURCE = "SIMULATED"

AREA_NAMES = {"B": "卫生间", "K": "厨房", "Y": "阳台", "IN": "入户", "WH": "热水器"}


@dataclass(frozen=True)
class BlockageConfig:
    """检测阈值。数值为模型假设，需在 sim_dev 上做灵敏度分析后再调整。"""
    baseline_days: int = 14          # 入住（或传感器安装）后用于学习基线的天数
    window_days: int = 5             # 近期窗口
    min_events: int = 6              # 窗口内至少这么多次淋浴才评估
    capability_quantile: float = 0.5 # 出水能力取事件 cv 的分位数（0.5 = 中位数，见模块说明）
    drop_threshold: float = 0.30     # 出水能力下降超过 30% 视为异常
    severe_threshold: float = 0.60   # 下降超过 60% 视为严重
    persist_days: int = 3            # 最近 persist_window 天内异常天数达到 persist_days 才报出
    persist_window: int = 4          # 允许持续期内有 1 天因开度随机未越线
    component_drop: float = 0.15     # 冷/热单路下降超过 15% 视为该路下降
    other_fixture_drop: float = 0.15 # 同支路其它器具下降超过 15% 视为也异常
    gradual_days: int = 7            # 从开始变差到报出超过 7 天为渐进型
    shower_min_s: int = 150          # 淋浴事件最短时长
    shower_min_hot_share: float = 0.20
    other_max_s: int = 120           # 同支路其它器具（马桶补水、洗脸盆）事件最长时长
    max_gap_s: int = 3               # 事件内允许的采样缺口（丢包）
    steady_tolerance: float = 0.15   # 稳态判定：采样与中位数偏差不超过 15%
    steady_fraction: float = 0.70    # 稳态判定：至少 70% 的采样满足上一条


# 定位先验：同一种证据组合下各部位的相对可能性（模型假设）。
# 依据：花洒头水垢是渐进型出水变小最常见的原因；突发型更可能是混水阀芯卡入杂质。
LOCALIZATION_PRIORS = {
    ("NORMAL", "BOTH", "GRADUAL"): [("SHOWER_HEAD", 0.82), ("MIXER", 0.13)],
    ("NORMAL", "BOTH", "SUDDEN"): [("MIXER", 0.55), ("SHOWER_HEAD", 0.35)],
    ("NORMAL", "HOT", None): [("MIXER", 0.70), ("HOT_BRANCH", 0.15)],
    ("NORMAL", "COLD", None): [("MIXER", 0.70), ("COLD_BRANCH", 0.15)],
    ("ABNORMAL", "HOT", None): [("HOT_BRANCH", 0.55), ("HEATER_FILTER", 0.30)],
    ("ABNORMAL", "COLD", None): [("COLD_BRANCH", 0.75)],
    ("ABNORMAL", "BOTH", None): [("COLD_BRANCH", 0.50), ("HOT_BRANCH", 0.30)],
}


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
@dataclass
class Stream:
    ts: list[datetime]
    columns: dict[str, list[float | None]]


def read_stream_csv(path: str) -> Stream:
    """读取模拟器输出的 ``sensor_stream.csv.gz``（也兼容未压缩 CSV）。"""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        codes = header[1:]
        ts: list[datetime] = []
        cols: dict[str, list[float | None]] = {c: [] for c in codes}
        for row in reader:
            if not row:
                continue
            ts.append(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
            for code, raw in zip(codes, row[1:]):
                cols[code].append(float(raw) if raw not in ("", "nan", "NaN") else None)
    return Stream(ts, cols)


# ---------------------------------------------------------------------------
# 拓扑：从档案里找出淋浴相关的传感器
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ShowerMonitor:
    house_id: str
    shower_node: str
    mixer_node: str | None
    cold_branch: str
    hot_branch: str | None
    heater_filter: str | None
    cold_flow_sensor: str
    hot_flow_sensor: str | None
    mixer_pressure_sensor: str
    inlet_pressure_sensor: str


def discover_shower_monitor(house: dict) -> ShowerMonitor:
    nodes = {n["segment_code"]: n for n in house["supply_network"]}
    sensors = house["sensors"]
    shower = next(n for n in nodes.values() if n["fixture"] == "SHOWER")
    mixer = nodes[shower["parents"][0]] if nodes[shower["parents"][0]]["kind"] == "MIXER" else None
    feed = mixer or shower
    cold_branch = hot_branch = None
    for p in feed["parents"]:
        if nodes[p]["side"] == "HOT":
            hot_branch = p
        else:
            cold_branch = p

    def sensor_on(code: str | None, typ: str) -> str | None:
        return next((s["sensor_code"] for s in sensors if s["type"] == typ and s["target"] == code), None)

    def ancestors(code: str) -> list[str]:
        out, cur = [], nodes[code]
        while cur["parents"]:
            out.append(cur["parents"][0])
            cur = nodes[cur["parents"][0]]
        return out

    heater_filter = None
    if hot_branch:
        heater_filter = next((a for a in ancestors(hot_branch) if nodes[a]["kind"] == "HEATER_FILTER"), None)

    cold_flow = sensor_on(cold_branch, "FL")
    mixer_pr = sensor_on(feed["segment_code"], "PR")
    root_path = [cold_branch] + ancestors(cold_branch)
    inlet_pr = next((sensor_on(c, "PR") for c in reversed(root_path) if sensor_on(c, "PR")), None)
    if not (cold_flow and mixer_pr and inlet_pr):
        raise ValueError(f"{house['house_id']} 缺少淋浴支路流量或压力传感器，无法做进水堵塞检测")
    return ShowerMonitor(
        house_id=house["house_id"], shower_node=shower["segment_code"],
        mixer_node=mixer["segment_code"] if mixer else None, cold_branch=cold_branch, hot_branch=hot_branch,
        heater_filter=heater_filter, cold_flow_sensor=cold_flow, hot_flow_sensor=sensor_on(hot_branch, "FL"),
        mixer_pressure_sensor=mixer_pr, inlet_pressure_sensor=inlet_pr,
    )


# ---------------------------------------------------------------------------
# 事件切分与特征
# ---------------------------------------------------------------------------
@dataclass
class UseEpisode:
    start: datetime
    end: datetime
    duration_s: int
    hot_share: float
    q_lps: float
    q_cold_lps: float
    q_hot_lps: float
    pressure_mpa: float
    kind: str  # SHOWER / OTHER / MIXED

    @property
    def cv(self) -> float:
        return self.q_lps / math.sqrt(self.pressure_mpa)

    @property
    def cv_cold(self) -> float:
        return self.q_cold_lps / math.sqrt(self.pressure_mpa)

    @property
    def cv_hot(self) -> float:
        return self.q_hot_lps / math.sqrt(self.pressure_mpa)


def segment_episodes(stream: Stream, mon: ShowerMonitor, cfg: BlockageConfig) -> list[UseEpisode]:
    cold = stream.columns[mon.cold_flow_sensor]
    hot = stream.columns[mon.hot_flow_sensor] if mon.hot_flow_sensor else [0.0] * len(stream.ts)
    pres = stream.columns[mon.mixer_pressure_sensor]
    episodes: list[UseEpisode] = []
    cur: list[int] = []

    def flush():
        if len(cur) >= 5:
            ep = _episode(stream, cur, cold, hot, pres, cfg)
            if ep:
                episodes.append(ep)
        cur.clear()

    for i, t in enumerate(stream.ts):
        flow = (cold[i] or 0.0) + (hot[i] or 0.0)
        if flow > 0:
            if cur and (t - stream.ts[cur[-1]]).total_seconds() > cfg.max_gap_s:
                flush()
            cur.append(i)
        elif cur:
            flush()
    flush()
    return episodes


def _episode(stream: Stream, idx: list[int], cold, hot, pres, cfg: BlockageConfig) -> UseEpisode | None:
    start, end = stream.ts[idx[0]], stream.ts[idx[-1]]
    duration = int((end - start).total_seconds()) + 1
    # 去掉开关阀的过渡段，只取中间稳态
    core = idx[3:-2] if len(idx) > 8 else idx
    c = [cold[i] or 0.0 for i in core]
    h = [hot[i] or 0.0 for i in core]
    p = [pres[i] for i in core if pres[i] is not None]
    if not p:
        return None
    q_cold, q_hot = statistics.median(c) / 60.0, statistics.median(h) / 60.0
    total = sum(c) + sum(h)
    hot_share = sum(h) / total if total > 0 else 0.0
    # 稳态检查：大部分采样应落在总流量中位数附近；多器具长时间叠加时不是单一器具的出水能力
    flows = [a + b for a, b in zip(c, h)]
    m = statistics.median(flows)
    steady = sum(1 for f in flows if abs(f - m) <= cfg.steady_tolerance * m) / len(flows) if m > 0 else 0.0
    if steady < cfg.steady_fraction:
        kind = "MIXED"
    elif duration >= cfg.shower_min_s and hot_share >= cfg.shower_min_hot_share:
        kind = "SHOWER"
    elif duration <= cfg.other_max_s:
        kind = "OTHER"
    else:
        kind = "MIXED"
    p_med = statistics.median(p)
    if p_med <= 0.01:
        return None
    return UseEpisode(start, end, duration, round(hot_share, 3), q_cold + q_hot, q_cold, q_hot, p_med, kind)


def quantile(values: Iterable[float], q: float) -> float | None:
    """线性插值分位数（与 numpy 默认方法一致）。"""
    vals = sorted(values)
    if not vals:
        return None
    pos = (len(vals) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _ratio(recent: float | None, baseline: float | None) -> float | None:
    if recent is None or not baseline:
        return None
    return recent / baseline - 1.0


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------
def detect_supply_blockage(
    stream: Stream,
    house: dict,
    building: dict,
    *,
    as_of: date | None = None,
    cfg: BlockageConfig = BlockageConfig(),
    event_seq: int = 1,
    recent_repairs_180d: int = 0,
) -> dict:
    """逐日评估淋浴出水能力，返回 ``{"event": 契约① 或 None, "diagnostics": {...}}``。

    ``as_of`` 为评估截止日期（含当天），默认为数据最后一天。报出的是截止日期之前
    **第一次**满足持续异常条件的那一天，这样回放同一份数据得到的事件稳定可复现。
    """
    mon = discover_shower_monitor(house)
    episodes = segment_episodes(stream, mon, cfg)
    first_day = stream.ts[0].date()
    last_day = as_of or stream.ts[-1].date()
    baseline_end = first_day + timedelta(days=cfg.baseline_days)  # 不含

    showers = [e for e in episodes if e.kind == "SHOWER" and e.start.date() <= last_day]
    others = [e for e in episodes if e.kind == "OTHER" and e.start.date() <= last_day]
    base_showers = [e for e in showers if e.start.date() < baseline_end]
    base_others = [e for e in others if e.start.date() < baseline_end]

    diagnostics = {
        "house_id": mon.house_id,
        "algorithm": "supply_blockage_cv_capability",
        "config": asdict(cfg),
        "data_range": {"start": first_day.isoformat(), "end": stream.ts[-1].date().isoformat()},
        "as_of": last_day.isoformat(),
        "episodes": {"shower": len(showers), "other": len(others)},
        "baseline": None,
        "daily": [],
        "status": "INSUFFICIENT_DATA",
    }
    base_cv = quantile((e.cv for e in base_showers), cfg.capability_quantile)
    # 基线学习期未走完（数据不足 baseline_days 天）时不评估，避免用几天数据当基线
    if last_day < baseline_end or len(base_showers) < cfg.min_events or base_cv is None:
        return {"event": None, "diagnostics": diagnostics}
    base_cold, base_hot = quantile((e.cv_cold for e in base_showers), cfg.capability_quantile), quantile((e.cv_hot for e in base_showers), cfg.capability_quantile)
    base_other = quantile((e.cv for e in base_others), cfg.capability_quantile) if len(base_others) >= cfg.min_events else None
    base_inlet = _idle_median(stream, mon.inlet_pressure_sensor, first_day, baseline_end)
    diagnostics["baseline"] = {
        "cv_cap": round(base_cv, 4), "events": len(base_showers),
        "other_cv_cap": round(base_other, 4) if base_other else None,
        "inlet_static_mpa": round(base_inlet, 4) if base_inlet else None,
    }
    diagnostics["status"] = "NO_EVENT"

    streak: list[dict] = []
    event = None
    day = baseline_end
    # 报出后继续逐日评估到 as_of，复查时据此判断故障是否仍在
    while day <= last_day:
        win_start = day - timedelta(days=cfg.window_days - 1)
        recent = [e for e in showers if win_start <= e.start.date() <= day and e.start.date() >= baseline_end]
        point = {"date": day.isoformat(), "events": len(recent), "cv_cap": None, "change_ratio": None, "flagged": False}
        if len(recent) >= cfg.min_events:
            cv = quantile((e.cv for e in recent), cfg.capability_quantile)
            change = _ratio(cv, base_cv)
            point.update(cv_cap=round(cv, 4), change_ratio=round(change, 3), flagged=change <= -cfg.drop_threshold)
        diagnostics["daily"].append(point)
        # 允许持续期内偶有一天因住户开度随机而未越线，避免一次噪声把连续计数清零
        window = diagnostics["daily"][-cfg.persist_window:]
        streak = [p for p in window if p["flagged"]] if point["flagged"] else []
        if event is None and len(streak) >= cfg.persist_days:
            event = _build_event(stream, house, building, mon, cfg, showers, others, recent, point, streak,
                                 diagnostics, base_cv, base_cold, base_hot, base_other, base_inlet,
                                 event_seq, recent_repairs_180d)
            diagnostics["status"] = "EVENT"
        day += timedelta(days=1)
    return {"event": event, "diagnostics": diagnostics}


def _idle_median(stream: Stream, code: str, start: date, end: date) -> float | None:
    """空闲时刻（所有流量为 0 的分钟行）入户静压中位数。"""
    flow_cols = [c for c in stream.columns if "-FL" in c]
    vals = []
    for i, t in enumerate(stream.ts):
        if not (start <= t.date() < end) or t.second != 0:
            continue
        if any((stream.columns[c][i] or 0.0) > 0 for c in flow_cols):
            continue
        v = stream.columns[code][i]
        if v is not None:
            vals.append(v)
    return statistics.median(vals) if vals else None


def _build_event(stream, house, building, mon, cfg, showers, others, recent, point, streak, diagnostics,
                 base_cv, base_cold, base_hot, base_other, base_inlet, event_seq, recent_repairs_180d) -> dict:
    day = date.fromisoformat(point["date"])
    win_start = day - timedelta(days=cfg.window_days - 1)
    change = point["change_ratio"]

    # 冷/热两路分别比较，判断是一路还是两路同时变差
    cold_change = _ratio(quantile((e.cv_cold for e in recent), cfg.capability_quantile), base_cold)
    hot_change = _ratio(quantile((e.cv_hot for e in recent), cfg.capability_quantile), base_hot) if mon.hot_flow_sensor else None
    cold_down = cold_change is not None and cold_change <= -cfg.component_drop
    hot_down = hot_change is not None and hot_change <= -cfg.component_drop
    hot_cold = "BOTH" if cold_down and hot_down else "HOT" if hot_down else "COLD" if cold_down else "BOTH"

    recent_others = [e for e in others if win_start <= e.start.date() <= day]
    other_change = None
    if base_other and len(recent_others) >= cfg.min_events:
        other_change = _ratio(quantile((e.cv for e in recent_others), cfg.capability_quantile), base_other)
    if other_change is None:
        same_branch = "UNKNOWN"
    else:
        same_branch = "ABNORMAL" if other_change <= -cfg.other_fixture_drop else "NORMAL"

    recent_inlet = _idle_median(stream, mon.inlet_pressure_sensor, win_start, day + timedelta(days=1))
    inlet_change = round(_ratio(recent_inlet, base_inlet), 3) if recent_inlet and base_inlet else 0.0

    # 估计开始变差的日期：从报出日往前找，出水能力仍在基线 90% 以上的最后一天；
    # 再往前推半个窗口，抵消滑动窗口带来的滞后
    started = day
    for p in reversed(diagnostics["daily"]):
        if p["change_ratio"] is None or p["change_ratio"] > -0.10:
            break
        started = date.fromisoformat(p["date"])
    started = max(started - timedelta(days=cfg.window_days // 2), date.fromisoformat(diagnostics["data_range"]["start"]))
    trend = "GRADUAL" if (day - started).days >= cfg.gradual_days else "SUDDEN"

    candidates = _localize(house, mon, same_branch, hot_cold, trend, change, cfg)
    last_shower = max(e.end for e in recent)
    severity = "HIGH" if change <= -cfg.severe_threshold else "MEDIUM"
    top_device = _device_for(house, candidates[0]["segment_code"]) if candidates else None

    archive_context = {
        "building": building.get("building", ""), "unit": building.get("unit", ""),
        "floor": house["floor_label"], "layout": house["layout"], "in_archive": bool(house["in_archive"]),
        "recent_repairs_180d": int(recent_repairs_180d),
    }
    if top_device:
        archive_context["device_name"] = top_device["name"]
        if top_device.get("spec"):
            archive_context["device_model"] = top_device["spec"]
        if top_device.get("install_date"):
            archive_context["install_date"] = top_device["install_date"]

    pct = round(-change * 100)
    parts = [f"花洒近{cfg.window_days}天出水能力比入住初期下降{pct}%"]
    parts.append({"BOTH": "冷热水同时下降", "HOT": "主要是热水侧下降", "COLD": "主要是冷水侧下降"}[hot_cold])
    parts.append({"NORMAL": "同卫生间其它用水点正常", "ABNORMAL": "同卫生间其它用水点也变差",
                  "UNKNOWN": "同卫生间其它用水点数据不足"}[same_branch])
    parts.append("入户水压正常" if abs(inlet_change) < 0.05 else f"入户水压变化{round(inlet_change * 100)}%")
    parts.append(f"约{max((day - started).days // 7, 1)}周内逐渐变差" if trend == "GRADUAL" else "近几天突然变差")

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"EVT-{day.strftime('%Y%m%d')}-{mon.house_id}-{event_seq:04d}",
        "scope": "HOUSE",
        "house_id": mon.house_id,
        "related_houses": [],
        "batch_id": house.get("batch_id"),
        "domain": "WATER",
        "event_type": "SUPPLY_BLOCKAGE",
        "severity": severity,
        "detected_at": last_shower.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "fault_started_est": started.isoformat(),
        "location_candidates": candidates,
        "evidence": {
            "metric": _metric_name(cfg),
            "baseline": round(base_cv, 3),
            "recent": round(point["cv_cap"], 3),
            "change_ratio": round(change, 2),
            "duration_days": len(streak),
            "window_days": cfg.window_days,
            "trend": trend,
            "inlet_pressure_change": inlet_change,
            "same_branch_other_fixtures": same_branch,
            "other_fixtures_change_ratio": None if other_change is None else round(other_change, 2),
            "hot_cold": hot_cold,
            "cold_change_ratio": None if cold_change is None else round(cold_change, 2),
            "hot_change_ratio": None if hot_change is None else round(hot_change, 2),
            "events_used": len(recent),
            "baseline_events": diagnostics["baseline"]["events"],
        },
        "evidence_text": "；".join(parts)[:200],
        "control_actions_taken": [],
        "archive_context": archive_context,
        "data_source": DATA_SOURCE,
    }


def _localize(house, mon: ShowerMonitor, same_branch: str, hot_cold: str, trend: str, change: float,
              cfg: BlockageConfig) -> list[dict]:
    branch_key = "ABNORMAL" if same_branch == "ABNORMAL" else "NORMAL"
    priors = (LOCALIZATION_PRIORS.get((branch_key, hot_cold, trend))
              or LOCALIZATION_PRIORS.get((branch_key, hot_cold, None))
              or LOCALIZATION_PRIORS[("NORMAL", "BOTH", trend)])
    # 证据强度：下降越明显越可信；同支路其它器具数据不足时再打折
    strength = min(1.0, 0.75 + (-change - cfg.drop_threshold))
    if same_branch == "UNKNOWN":
        strength *= 0.85
    role_node = {
        "SHOWER_HEAD": mon.shower_node, "MIXER": mon.mixer_node, "COLD_BRANCH": mon.cold_branch,
        "HOT_BRANCH": mon.hot_branch, "HEATER_FILTER": mon.heater_filter,
    }
    nodes = {n["segment_code"]: n for n in house["supply_network"]}
    out = []
    for role, prior in priors:
        code = role_node.get(role)
        if not code:
            continue
        node = nodes[code]
        device = _device_for(house, code)
        out.append({
            "segment_code": code,
            "segment_name": f"{AREA_NAMES.get(node['area'], node['area'])}-{node['name']}"[:40],
            "device_code": device["device_code"] if device else None,
            "in_archive": bool(device and device.get("in_archive")),
            "confidence": round(prior * strength, 2),
        })
    return sorted(out, key=lambda c: c["confidence"], reverse=True)[:3]


def _device_for(house: dict, segment_code: str) -> dict | None:
    return next((d for d in house["devices"] if d.get("segment_code") == segment_code), None)


def _metric_name(cfg: BlockageConfig) -> str:
    """契约① evidence.metric：cv_p90、cv_p95、cv_max 等。"""
    q = cfg.capability_quantile
    return "cv_max" if q >= 1.0 else f"cv_p{round(q * 100)}"
