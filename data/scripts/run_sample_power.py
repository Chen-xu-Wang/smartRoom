"""端到端样例：1302 用电安全（E2 漏电 + E5 电压是否在电器安全范围内）。

六个场景，行为数据相同，只有注入不同：
    leakage_gradual        卫生间插座回路绝缘渐进劣化：06-15 起漏电流按平方规律增大，约 07-05 达到保护动作值跳闸
    leakage_wet            07-08 19:05 厨房插座进水，漏电跳闸；住户 19:15、19:40 两次重新合闸又跳闸，21:30 干燥后恢复
    control_humid          干扰：06-18 至 07-02 梅雨季室外湿度约 94%，漏电检测不应报出
    voltage_supply_high    供电侧：06-24 起 L2 相每晚 23:00–06:00 轻载过电压（+17 V），同相住户都受影响
    voltage_house_neutral  本户接线：06-26 起 1302 进线/零线端子松动，附加电阻一周内增到 1.4 Ω，大负载时电压明显下降
    control_normal         不注入：两类检测都不应报出

电压判断需要对比同楼栋住户，同时模拟同相（L2）的 1202、1402、1305、1505、1105 与其它相的 1301（L1）、1303（L3）。
样例数据（落盘、供后端演示）使用 sim_dev 种子；种子 1001–5005、7007、8008 参与了调参，9009、10010、11011、12012 做盲测复核。

用法::

    python data/scripts/run_sample_power.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR.parent.parent / "backend"))

from sim import behavior as bh  # noqa: E402
from sim.electrical import HumidityEvent, LeakageFault, PhaseVoltageEvent, PowerScenario, WiringFault, generate_power  # noqa: E402
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE, EVALUATION_DIR, PERSONA_TRUTH_FILE, PROCESSED_DIR  # noqa: E402
from validate_contracts import build_validators, check_event_pair, schema_errors  # noqa: E402

from app.services import event_rules, power_safety  # noqa: E402
from app.services.water_blockage import read_stream_csv, Stream  # noqa: E402

HOUSE_ID = "1302"
NEIGHBORS = ["1202", "1402", "1305", "1505", "1105", "1301", "1303"]
START, END = date(2026, 6, 1), date(2026, 7, 12)
SAMPLE_DIR = PROCESSED_DIR / "samples" / f"power_{HOUSE_ID}"
# 调参记录：电压最初按"单日越限 ≥ 10 分钟、3 天内 2 天"报出，第一次盲测（4004/5005/7007/8008）中 5005、8008
# 的零线松动漏报——欠电压每天只有几分钟但低到 160 V。改为 3 天累计越限分钟后，这 4 个种子并入调参集，改用新种子盲测。
HOLDOUT_SEEDS = [9009, 10010, 11011, 12012]
LEAD_TARGET_DAYS = 7.0     # 工作方案 4.3：劣化类相对故障（跳闸）的提前预警 ≥ 7 天

SCENARIOS = [
    PowerScenario("leakage_gradual", "EF1 卫生间插座回路绝缘渐进劣化：06-15 起漏电流按平方规律增大，约 07-05 达到保护动作值",
                  leakage_faults=[LeakageFault("CB-1302-BT", "GRADUAL", "2026-06-15", "2026-07-10", 32.0, fault_id="EF1")]),
    PowerScenario("leakage_wet", "厨房插座进水：07-08 19:05 漏电跳闸，19:15、19:40 两次重新合闸又跳闸，21:30 干燥后恢复",
                  leakage_faults=[LeakageFault("CB-1302-KT", "WET", "2026-07-08 19:05", "2026-07-08 21:30", 34.0,
                                               reclose_times=["2026-07-08 19:15", "2026-07-08 19:40", "2026-07-08 21:35"],
                                               fault_id="EF1-WET")]),
    PowerScenario("control_humid", "干扰：06-18 至 07-02 梅雨季室外湿度约 94%，漏电检测不应报出",
                  humidity_events=[HumidityEvent("2026-06-18", "2026-07-02", 94.0, "梅雨季")]),
    PowerScenario("voltage_supply_high", "供电侧：06-24 起 L2 相每晚 23:00–06:00 轻载过电压 +17 V",
                  phase_events=[PhaseVoltageEvent("L2", "2026-06-24", "2026-07-13", 23, 6, 17.0, "变压器挡位偏高、夜间轻载")]),
    PowerScenario("voltage_house_neutral", "本户接线：06-26 起 1302 进线/零线端子松动，附加电阻至 07-04 增到 1.4 Ω",
                  wiring_faults=[WiringFault("1302", "2026-06-26", "2026-07-04", 1.4, "EF-NEUTRAL")]),
    PowerScenario("control_normal", "无故障对照：漏电与电压检测都不应报出"),
]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _to_stream(df: pd.DataFrame) -> Stream:
    return Stream([pd.Timestamp(t).to_pydatetime() for t in df["ts"]],
                  {c: [None if pd.isna(x) else float(x) for x in df[c]] for c in df.columns if c != "ts"})


def detect_all(stream: Stream, neighbors: Stream, house: dict, building: dict) -> dict:
    """与后端服务一致：先漏电（可能多条回路），再电压。"""
    leak = power_safety.detect_leakage(stream, house, building["building"])
    volt = power_safety.detect_voltage(stream, neighbors, house, building, event_seq=len(leak["events"]) + 1)
    return {"leakage": leak, "voltage": volt,
            "events": leak["events"] + ([volt["event"]] if volt["event"] else [])}


def manifest(seed: int, sc: PowerScenario, main_cols, nb_cols) -> dict:
    return {"house_id": HOUSE_ID, "neighbors": NEIGHBORS, "window": {"start": START.isoformat(), "end": END.isoformat()},
            "sampling": {"minute_s": 60}, "columns": {"sensor_stream": list(main_cols), "neighbors": list(nb_cols)},
            "units": {"voltage_v": "V", "current_a": "A", "residual_ma": "mA", "closed": "1=合闸 0=断开", "rh_pct": "%", "temp_c": "℃"},
            "scenario": sc.name, "seed": seed, "timezone": "+08:00", "data_source": "SIMULATED",
            "generator": "data/scripts/run_sample_power.py",
            "note": "只含传感器读数；故障注入计划与跳闸真值在 _truth/ 中，检测算法不得读取。"}


def run_seed(seed, params, building, personas, house, save, validators):
    frames, profiles = bh.generate(building, personas, params, seed,
                                   date.fromisoformat(params["calendar.main_window_start"]),
                                   date.fromisoformat(params["calendar.main_window_end"]), set([HOUSE_ID] + NEIGHBORS))
    results, checks = {}, []
    for sc in SCENARIOS:
        main_df, nb_df, truth = generate_power(building, frames, profiles, params, seed, START, END, sc, HOUSE_ID, NEIGHBORS)
        if save:
            out = SAMPLE_DIR / sc.name
            (out / "_truth").mkdir(parents=True, exist_ok=True)
            main_df.to_csv(out / "sensor_stream.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
            nb_df.to_csv(out / "neighbors.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
            _write_json(out / "manifest.json", manifest(seed, sc, main_df.columns, nb_df.columns))
            _write_json(out / "_truth" / "scenario.json", {"scenario": sc.name, "description": sc.description, **asdict(sc)})
            _write_json(out / "_truth" / "electrical_truth.json", truth)
            stream, neighbors = read_stream_csv(str(out / "sensor_stream.csv.gz")), read_stream_csv(str(out / "neighbors.csv.gz"))
        else:
            stream, neighbors = _to_stream(main_df), _to_stream(nb_df)
        found = detect_all(stream, neighbors, house, building)
        decisions = []
        for ev in found["events"]:
            d = event_rules.decide(ev)
            decisions.append(d)
            label = f"{seed}/{sc.name}/{ev['event_type']}"
            errs = schema_errors(validators["event"], ev, label) + schema_errors(validators["event_decision"], d, label)
            errs += check_event_pair(ev, d, label)
            checks.append((f"种子 {seed} {sc.name} {ev['event_type']}：通过契约校验", not errs, "；".join(errs) or "通过"))
        if save:
            _write_json(SAMPLE_DIR / sc.name / "detection.json", {k: found[k] for k in ("leakage", "voltage")})
            _write_json(SAMPLE_DIR / sc.name / "decision.json", decisions)
        results[sc.name] = {"rows": len(main_df), "truth": truth, "found": found}
    return results, checks


def seed_metrics(results) -> dict:
    def events(name, typ):
        return [e for e in results[name]["found"]["events"] if e["event_type"] == typ]

    m = {}
    g = events("leakage_gradual", "LEAKAGE_CURRENT")
    first_trip = next((pd.Timestamp(x["at"]) for x in results["leakage_gradual"]["truth"]["trips"] if x["event"] == "TRIP"), None)
    m["gradual"] = {
        "event": g[0] if g else None, "first_trip": first_trip,
        "lead_days": (first_trip - pd.Timestamp(g[0]["detected_at"][:19])).total_seconds() / 86400 if g and first_trip is not None else None,
        "ok": bool(g) and g[0]["evidence"]["circuit_code"] == "CB-1302-BT" and g[0]["evidence"]["pattern"] == "GRADUAL",
        "extra": len(results["leakage_gradual"]["found"]["events"]) - len(g),
    }
    w = events("leakage_wet", "LEAKAGE_CURRENT")
    wet_trip = next((pd.Timestamp(x["at"]) for x in results["leakage_wet"]["truth"]["trips"] if x["event"] == "TRIP"), None)
    m["wet"] = {
        "event": w[0] if w else None,
        "delay_min": (pd.Timestamp(w[0]["detected_at"][:19]) - wet_trip).total_seconds() / 60 if w and wet_trip is not None else None,
        "ok": bool(w) and w[0]["evidence"]["circuit_code"] == "CB-1302-KT" and w[0]["evidence"]["pattern"] == "TRIP"
        and w[0]["evidence"]["trip_count"] >= 2,
        "extra": len(results["leakage_wet"]["found"]["events"]) - len(w),
    }
    s = events("voltage_supply_high", "VOLTAGE_ABNORMAL")
    m["supply"] = {
        "event": s[0] if s else None,
        "delay_days": (pd.Timestamp(s[0]["detected_at"][:10]) - pd.Timestamp("2026-06-24")).days if s else None,
        "ok": bool(s) and s[0]["evidence"]["source_inference"] == "SUPPLY" and s[0]["evidence"]["phase_scope"] == "SINGLE_PHASE"
        and any(r["appliance"] == "FRIDGE" for r in s[0]["evidence"]["appliances_at_risk"]),
        "extra": len(results["voltage_supply_high"]["found"]["events"]) - len(s),
    }
    n = events("voltage_house_neutral", "VOLTAGE_ABNORMAL")
    m["neutral"] = {
        "event": n[0] if n else None,
        "delay_days": (pd.Timestamp(n[0]["detected_at"][:10]) - pd.Timestamp("2026-06-26")).days if n else None,
        "ok": bool(n) and n[0]["evidence"]["source_inference"] == "HOUSE_WIRING" and n[0]["scope"] == "HOUSE",
        "extra": len(results["voltage_house_neutral"]["found"]["events"]) - len(n),
    }
    for name in ("control_humid", "control_normal"):
        m[name] = {"events": len(results[name]["found"]["events"]),
                   "max_excess": max((p["excess_p95_ma"] or 0) for c in results[name]["found"]["leakage"]["diagnostics"]["circuits"].values() for p in c["daily"]),
                   "flagged_voltage_days": sum(p["flagged"] for p in results[name]["found"]["voltage"]["diagnostics"]["daily"])}
    return m


def main() -> int:
    params = load_params()
    building = json.loads(BUILDING_FILE.read_text(encoding="utf-8"))
    personas = json.loads(PERSONA_TRUTH_FILE.read_text(encoding="utf-8"))
    house = next(h for h in building["houses"] if h["house_id"] == HOUSE_ID)
    validators = build_validators()
    dev_seed = params["seeds.dev"]

    all_results, checks, metrics = {}, [], {}
    for seed in [dev_seed] + HOLDOUT_SEEDS:
        res, more = run_seed(seed, params, building, personas, house, seed == dev_seed, validators)
        all_results[seed], metrics[seed] = res, seed_metrics(res)
        checks += more
        print(f"[种子 {seed}] 完成")
    for seed, m in metrics.items():
        tag = "样例" if seed == dev_seed else "盲测"
        checks += [
            (f"{tag} {seed}：渐进漏电在卫生间插座回路报出", m["gradual"]["ok"], _brief(m["gradual"]["event"])),
            (f"{tag} {seed}：渐进漏电提前跳闸 ≥ {LEAD_TARGET_DAYS:.0f} 天预警",
             m["gradual"]["lead_days"] is not None and m["gradual"]["lead_days"] >= LEAD_TARGET_DAYS,
             "—" if m["gradual"]["lead_days"] is None else f"{m['gradual']['lead_days']:.1f} 天"),
            (f"{tag} {seed}：受潮跳闸在厨房插座回路报出且识别反复跳闸", m["wet"]["ok"], _brief(m["wet"]["event"])),
            (f"{tag} {seed}：受潮跳闸检测 ≤ 5 分钟", m["wet"]["delay_min"] is not None and m["wet"]["delay_min"] <= 5,
             "—" if m["wet"]["delay_min"] is None else f"{m['wet']['delay_min']:.0f} 分钟"),
            (f"{tag} {seed}：供电侧过电压判为 L2 单相供电问题且识别冰箱风险", m["supply"]["ok"], _brief(m["supply"]["event"])),
            (f"{tag} {seed}：零线松动判为本户接线问题", m["neutral"]["ok"], _brief(m["neutral"]["event"])),
            (f"{tag} {seed}：故障场景没有多余事件",
             all(m[k]["extra"] == 0 for k in ("gradual", "wet", "supply", "neutral")),
             "，".join(f"{k} 多 {m[k]['extra']}" for k in ("gradual", "wet", "supply", "neutral") if m[k]["extra"]) or "无"),
            (f"{tag} {seed}：梅雨季高湿对照无误报", m["control_humid"]["events"] == 0,
             f"最大超额 {m['control_humid']['max_excess']} mA"),
            (f"{tag} {seed}：正常对照无误报", m["control_normal"]["events"] == 0,
             f"电压越限天数 {m['control_normal']['flagged_voltage_days']}"),
        ]
    lines = render_report(all_results[dev_seed], metrics, checks, dev_seed)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "sample_power_safety_report.md").write_text("\n".join(lines), encoding="utf-8")
    for name, ok, detail in checks:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"：{detail}"))
    for seed, m in metrics.items():
        print(f"  · 种子 {seed} 渐进漏电提前 {m['gradual']['lead_days'] and round(m['gradual']['lead_days'], 1)} 天；"
              f"过电压第 {m['supply']['delay_days']} 天报出；零线松动第 {m['neutral']['delay_days']} 天报出")
    return 1 if any(not ok for _, ok, _ in checks) else 0


def _brief(ev) -> str:
    if not ev:
        return "未报出"
    e = ev["evidence"]
    if ev["event_type"] == "LEAKAGE_CURRENT":
        return f"{ev['detected_at'][:16]} {e['circuit_code']} {e['pattern']} {e['residual_ma_recent']} mA 跳闸 {e['trip_count']} 次"
    return f"{ev['detected_at'][:16]} {e['source_inference']} {e.get('phase_scope') or ''} {e['voltage_min_v']}–{e['voltage_max_v']} V"


def render_report(dev, metrics, checks, dev_seed) -> list[str]:
    lc, vc = power_safety.LeakageConfig(), power_safety.VoltageConfig()
    lines = [
        "# 端到端样例评估：1302 用电安全（漏电 + 电压是否在电器安全范围内）", "",
        "> 生成：`data/scripts/run_sample_power.py`　数据来源：SIMULATED",
        f"> 漏电：按湿度与负载拟合回路正常泄漏，超额日 95% 分位 ≥ {lc.excess_warn_ma} mA 连续 {lc.persist_days} 天预警；"
        f"跳闸分钟剩余电流 ≥ {lc.trip_residual_ma} mA 判为漏电跳闸",
        f"> 电压：GB/T 12325 {vc.limits[0]}–{vc.limits[1]} V，最近 {vc.window_days} 天累计越限 ≥ {vc.window_minutes} 分钟且至少 {vc.min_days_in_window} 天出现越限报出；"
        f"同相邻户 ≥ {vc.same_phase_ratio:.0%} 同时越限判供电侧，否则看等效线路电阻",
        "", "## 一、检查结果", "", "| 检查项 | 结果 | 说明 |", "| --- | --- | --- |",
    ]
    lines += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in checks]
    lines += ["", "## 二、各种子汇总", "",
              "| 种子 | 用途 | 渐进漏电预警 → 首次跳闸 | 提前天数 | 受潮跳闸 | 供电侧过电压 | 零线松动（等效电阻） |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for seed, m in metrics.items():
        g, w, s, n = m["gradual"], m["wet"], m["supply"], m["neutral"]
        lines.append(
            f"| {seed} | {'样例（参与调参）' if seed == dev_seed else '盲测'} | "
            f"{g['event']['detected_at'][:10] if g['event'] else '未报出'} → {g['first_trip']} | "
            f"{'—' if g['lead_days'] is None else f'{g['lead_days']:.1f}'} | {_brief(w['event'])} | {_brief(s['event'])} | "
            f"{_brief(n['event'])}（{n['event']['evidence']['wiring_resistance_ohm'] if n['event'] else '—'} Ω） |")
    lines += ["", f"## 三、样例场景（种子 {dev_seed}，已落盘供后端演示）", "", "| 场景 | 注入 | 事件 |", "| --- | --- | --- |"]
    for sc in SCENARIOS:
        evs = dev[sc.name]["found"]["events"]
        lines.append(f"| {sc.name} | {sc.description} | {'；'.join(_brief(e) for e in evs) or '—'} |")
    lines += [
        "", "## 四、已知局限", "",
        "- 每个种子各 1 次注入，只证明链路跑通与方法可行，不代表统计意义的检出率。",
        "- **调参过程如实记录**：电压最初按\"单日越限 ≥ 10 分钟、3 天内 2 天\"报出，在种子 1001–3003 上全部通过；第一次盲测"
        "（4004、5005、7007、8008）中 5005、8008 的零线松动漏报。原因是接头松动引起的欠电压只在大功率电器同时运行时出现，"
        "每天只有几分钟，但最低到 160 V 左右（低于冰箱允许的 187 V）。改为\"最近 3 天累计越限 ≥ 20 分钟且至少 2 天出现\"后，"
        "这 4 个种子并入调参集，本次盲测使用新种子 " + "、".join(map(str, HOLDOUT_SEEDS)) + "。",
        "- 用电模型是任务 1.6 的简化版：没有房间热模型，空调负载只随室外温度变化；电压为分钟平均值，没有模拟秒级电压暂降。",
        "- 电器允许电压范围取铭牌典型值（`power.appliances.voltage_ranges_v`，待按档案实际型号核对）。",
        "- 漏电定位只能到回路；回路上具体哪个插座或电器，靠先验排序（`power_safety.LEAKAGE_PRIORS`，模型假设），需电工逐个断开测试。",
        "- 供电侧判断依赖同楼栋其它住户的电表数据；只接入本户电表时只能给出\"原因未定\"。",
        "- 零线松动在负载较轻的日子不一定越限，检测时间取决于住户何时同时使用大功率电器。",
    ]
    return lines


if __name__ == "__main__":
    sys.exit(main())
