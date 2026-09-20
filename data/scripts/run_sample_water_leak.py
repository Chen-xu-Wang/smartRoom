"""端到端样例：1302 漏水（W2 暗漏 + W3 爆管自动关阀）。

四个场景，行为数据相同，只有注入不同：
    hidden_leak        06-18 起马桶进水阀密封渐渐失效，一周内漏水量增到约 0.35 L/min，之后持续
    pipe_burst         07-01 14:20 厨房冷水连接软管脱落（家中无人），无人处置时 30 分钟后才被发现
    control_normal     不注入：两类检测都不应报出
    control_night_use  06-20 至 07-05 每晚凌晨多次起夜冲马桶、洗手，并有夜间谷电洗衣：暗漏检测不应报出

样例数据（落盘、供后端演示）使用 sim_dev 种子；种子 6006、7007、8008 未参与阈值选择，做盲测复核。

用法::

    python data/scripts/run_sample_water_leak.py
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
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE, EVALUATION_DIR, PERSONA_TRUTH_FILE, PROCESSED_DIR  # noqa: E402
from sim.water_stream import Fault, Scenario, generate_stream, stream_manifest  # noqa: E402
from validate_contracts import build_validators, check_event_pair, schema_errors  # noqa: E402

from app.services import event_rules, water_blockage, water_leak  # noqa: E402

HOUSE_ID = "1302"
START, END = date(2026, 6, 1), date(2026, 7, 12)
SAMPLE_DIR = PROCESSED_DIR / "samples" / f"water_leak_{HOUSE_ID}"
# 调参记录：最初用"支路流量 > 额定流量之和 × 1.5"判爆管，种子 6006 的高区住户洗衣机进水就超过门槛（误报），
# 据此改为按压力归一化的出水口流量系数。1001–3003 与 6006 都参与了调参，不再当盲测。
HOLDOUT_SEEDS = [4004, 5005, 7007, 8008]
LEAK_TARGET, BURST_TARGET = "WS-1302-B-WC", "WS-1302-K-HS"
HIDDEN_DELAY_TARGET_DAYS = 5.0    # 工作方案 4.3：渐进劣化 ≤ 5 天（相对漏水量超过检测下限的时刻）
BURST_DELAY_TARGET_MIN = 5.0      # 工作方案 4.3：爆管 ≤ 5 分钟

SCENARIOS = [
    Scenario("hidden_leak", "WF8 马桶进水阀密封渐渐失效：06-18 起漏水量一周内增到约 0.35 L/min 后持续",
             faults=[Fault("WF8", "TOILET_FILL_VALVE_LEAK", LEAK_TARGET, "leak", "2026-06-18", "2026-06-25", 0.01)]),
    Scenario("pipe_burst", "WF9 厨房冷水连接软管脱落：07-01 14:20 发生，无人处置时 14:50 才被发现",
             faults=[Fault("WF9", "HOSE_BURST", BURST_TARGET, "leak", "2026-07-01 14:20:00", "2026-07-01 14:50:00", 3.0, "STEP")]),
    Scenario("control_normal", "无故障对照：暗漏与爆管都不应报出"),
    Scenario("control_night_use", "干扰：06-20 至 07-05 每晚凌晨多次起夜冲马桶、洗手，隔天夜间谷电洗衣"),
]


def night_use_events(house_id: str) -> pd.DataFrame:
    """干扰场景额外的夜间用水事件（行为层字段）。"""
    rows = []
    for d in pd.date_range("2026-06-20", "2026-07-05", freq="D"):
        for hh, mm in ((2, 15), (3, 10), (4, 20)):
            t = d + pd.Timedelta(hours=hh, minutes=mm)
            rows.append({"house_id": house_id, "start": t, "duration_s": 60.0, "kind": "WATER", "device": "TOILET",
                         "open_fraction": None, "mix_temp_c": None, "hot_fraction": None, "volume_l": 5.0})
            rows.append({"house_id": house_id, "start": t + pd.Timedelta(minutes=2), "duration_s": 25.0,
                         "kind": "WATER", "device": "BASIN", "open_fraction": 0.5, "mix_temp_c": None,
                         "hot_fraction": None, "volume_l": None})
        if d.day % 2 == 0:
            rows.append({"house_id": house_id, "start": d + pd.Timedelta(hours=2, minutes=30), "duration_s": 3900.0,
                         "kind": "WATER", "device": "WASHER", "open_fraction": 1.0, "mix_temp_c": None,
                         "hot_fraction": None, "volume_l": 48.0})
    return pd.DataFrame(rows)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def detect_all(stream, house, building) -> list[dict]:
    """与后端服务一致：先检测爆管，再检测暗漏，返回 [{event, diagnostics}]。"""
    burst = water_leak.detect_pipe_burst(stream, house, building, event_seq=1)
    hidden = water_leak.detect_hidden_leak(stream, house, building, event_seq=2 if burst["event"] else 1)
    return [burst, hidden]


def run_seed(seed, params, building, personas, house, save, validators):
    frames, profiles = bh.generate(building, personas, params, seed,
                                   date.fromisoformat(params["calendar.main_window_start"]),
                                   date.fromisoformat(params["calendar.main_window_end"]), {HOUSE_ID})
    heater = profiles[HOUSE_ID].habits["heater_setpoint_c"]
    results, checks = {}, []
    for sc in SCENARIOS:
        events = frames["events"]
        if sc.name == "control_night_use":
            events = pd.concat([events, night_use_events(HOUSE_ID)], ignore_index=True)
        stream_df, truth = generate_stream(house, events, heater, params, seed, START, END, sc)
        if save:
            out = SAMPLE_DIR / sc.name
            (out / "_truth").mkdir(parents=True, exist_ok=True)
            stream_df.to_csv(out / "sensor_stream.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
            _write_json(out / "manifest.json", stream_manifest(house, house["sensors"], seed, START, END, sc))
            truth.to_csv(out / "_truth" / "fixture_uses.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
            _write_json(out / "_truth" / "scenario.json", {"scenario": sc.name, "description": sc.description,
                                                           "faults": [asdict(f) for f in sc.faults]})
            stream = water_blockage.read_stream_csv(str(out / "sensor_stream.csv.gz"))
        else:
            stream = water_blockage.Stream([pd.Timestamp(t).to_pydatetime() for t in stream_df["ts"]],
                                           {c: stream_df[c].tolist() for c in stream_df.columns if c != "ts"})
        found = detect_all(stream, house, building["building"])
        decisions = []
        for r in found:
            if r["event"]:
                d = event_rules.decide(r["event"])
                decisions.append(d)
                label = f"{seed}/{sc.name}/{r['event']['event_type']}"
                errs = schema_errors(validators["event"], r["event"], label)
                errs += schema_errors(validators["event_decision"], d, label)
                errs += check_event_pair(r["event"], d, label)
                checks.append((f"种子 {seed} {sc.name} {r['event']['event_type']}：通过契约校验", not errs, "；".join(errs) or "通过"))
        if save:
            _write_json(SAMPLE_DIR / sc.name / "detection.json", found)
            _write_json(SAMPLE_DIR / sc.name / "decision.json", decisions)
        results[sc.name] = {"rows": len(stream_df), "truth": truth, "found": found}
    return results, checks


def seed_metrics(results) -> dict:
    m = {}
    hidden = results["hidden_leak"]["found"][1]["event"]
    truth = results["hidden_leak"]["truth"]
    leak = truth[truth["fixture"] == f"LEAK:{LEAK_TARGET}"]
    over = leak[leak["flow_lps_at_start"] * 60 >= water_leak.LeakConfig().min_leak_lpm]
    cross = over["start"].min() if not over.empty else None
    m["hidden"] = {"detected": hidden is not None, "top1": hidden and hidden["location_candidates"][0]["segment_code"],
                   "detected_at": hidden and hidden["detected_at"], "cross": cross,
                   "delay_days": (pd.Timestamp(hidden["detected_at"][:19]) - cross).total_seconds() / 86400
                   if hidden and cross is not None else None,
                   "night_flow": hidden and hidden["evidence"]["night_min_flow_lpm"],
                   "burst_false": results["hidden_leak"]["found"][0]["event"] is not None}
    burst = results["pipe_burst"]["found"][0]["event"]
    btruth = results["pipe_burst"]["truth"]
    bleak = btruth[btruth["fixture"] == f"LEAK:{BURST_TARGET}"]
    counterfactual = float((bleak["flow_lps_at_start"] * bleak["duration_s"]).sum())
    onset = pd.Timestamp(SCENARIOS[1].faults[0].start)
    m["burst"] = {"detected": burst is not None, "top1": burst and burst["location_candidates"][0]["segment_code"],
                  "detected_at": burst and burst["detected_at"],
                  "delay_min": (pd.Timestamp(burst["detected_at"][:19]) - onset).total_seconds() / 60 if burst else None,
                  "loss_l": burst and burst["evidence"]["est_loss_l"], "counterfactual_l": round(counterfactual),
                  "hidden_false": results["pipe_burst"]["found"][1]["event"] is not None}
    for name in ("control_normal", "control_night_use"):
        f = results[name]["found"]
        nights = f[1]["diagnostics"]["nightly"]
        m[name] = {"false_burst": f[0]["event"] is not None, "false_hidden": f[1]["event"] is not None,
                   "flagged_nights": sum(1 for p in nights if p["flagged"]),
                   "max_night_lpm": max((p["meter_lpm"] or 0) for p in nights)}
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
            (f"{tag} {seed}：暗漏检出", m["hidden"]["detected"], m["hidden"]["detected_at"] or "未报出"),
            (f"{tag} {seed}：暗漏首选定位 = 马桶进水阀", m["hidden"]["top1"] == LEAK_TARGET, str(m["hidden"]["top1"])),
            (f"{tag} {seed}：暗漏场景未误报爆管", not m["hidden"]["burst_false"], ""),
            (f"{tag} {seed}：爆管检出", m["burst"]["detected"], m["burst"]["detected_at"] or "未报出"),
            (f"{tag} {seed}：爆管首选定位 = 厨房冷水软管", m["burst"]["top1"] == BURST_TARGET, str(m["burst"]["top1"])),
            (f"{tag} {seed}：爆管检测 ≤ {BURST_DELAY_TARGET_MIN:.0f} 分钟",
             m["burst"]["delay_min"] is not None and m["burst"]["delay_min"] <= BURST_DELAY_TARGET_MIN,
             f"{m['burst']['delay_min']:.1f} 分钟" if m["burst"]["delay_min"] is not None else "—"),
            (f"{tag} {seed}：爆管场景未误报暗漏", not m["burst"]["hidden_false"], ""),
            (f"{tag} {seed}：正常对照无误报", not (m["control_normal"]["false_burst"] or m["control_normal"]["false_hidden"]),
             f"越线夜数 {m['control_normal']['flagged_nights']}"),
            (f"{tag} {seed}：频繁夜间用水对照无误报",
             not (m["control_night_use"]["false_burst"] or m["control_night_use"]["false_hidden"]),
             f"越线夜数 {m['control_night_use']['flagged_nights']}，夜间最小流量最大 {m['control_night_use']['max_night_lpm']} L/min"),
        ]
    lines = render_report(all_results[dev_seed], metrics, checks, dev_seed)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "sample_water_leak_report.md").write_text("\n".join(lines), encoding="utf-8")
    for name, ok, detail in checks:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"：{detail}"))
    for seed, m in metrics.items():
        print(f"  · 种子 {seed} 暗漏延迟 {m['hidden']['delay_days'] and round(m['hidden']['delay_days'], 1)} 天；"
              f"爆管 {m['burst']['delay_min'] and round(m['burst']['delay_min'], 1)} 分钟，"
              f"关阀后损失 {m['burst']['loss_l']} L（不关阀约 {m['burst']['counterfactual_l']} L）")
    return 1 if any(not ok for _, ok, _ in checks) else 0


def render_report(dev, metrics, checks, dev_seed) -> list[str]:
    cfg = water_leak.LeakConfig()
    lines = [
        "# 端到端样例评估：1302 漏水（暗漏 + 爆管自动关阀）", "",
        "> 生成：`data/scripts/run_sample_water_leak.py`　数据来源：SIMULATED",
        f"> 暗漏：凌晨 {cfg.night_start_h}–{cfg.night_end_h} 点逐分钟最小流量的 {cfg.night_quantile:.0%} 分位 ≥ {cfg.min_leak_lpm} L/min，"
        f"连续 {cfg.consecutive_nights} 晚报出；爆管：支路流量 > 该支路器具额定流量之和 × {cfg.burst_factor}，持续 {cfg.burst_min_duration_s} 秒报出并关阀",
        "", "## 一、检查结果", "", "| 检查项 | 结果 | 说明 |", "| --- | --- | --- |",
    ]
    lines += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in checks]
    lines += ["", "## 二、各种子汇总", "",
              "| 种子 | 用途 | 暗漏报出 | 暗漏延迟（相对漏量超过 0.05 L/min） | 夜间最小流量 | 爆管报出 | 爆管延迟 | 关阀后损失 / 不关阀损失 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for seed, m in metrics.items():
        h, b = m["hidden"], m["burst"]
        lines.append(
            f"| {seed} | {'样例（参与调参）' if seed == dev_seed else '盲测'} | {h['detected_at'] or '未报出'} | "
            f"{'—' if h['delay_days'] is None else f'{h['delay_days']:.1f} 天'} | {h['night_flow'] or '—'} L/min | "
            f"{b['detected_at'] or '未报出'} | {'—' if b['delay_min'] is None else f'{b['delay_min']:.1f} 分钟'} | "
            f"{b['loss_l']} L / {b['counterfactual_l']} L |")
    lines += ["", f"## 三、样例场景（种子 {dev_seed}，已落盘供后端演示）", "",
              "| 场景 | 注入 | 传感器行数 | 事件 |", "| --- | --- | --- | --- |"]
    for sc in SCENARIOS:
        r = dev[sc.name]
        evs = [x["event"] for x in r["found"] if x["event"]]
        brief = "；".join(f"{e['event_type']} 首选 {e['location_candidates'][0]['segment_name']}（{e['location_candidates'][0]['confidence']}）" for e in evs) or "—"
        lines.append(f"| {sc.name} | {sc.description} | {r['rows']:,} | {brief} |")
    hidden = dev["hidden_leak"]["found"][1]["diagnostics"]["nightly"]
    lines += ["", "### 暗漏场景逐夜最小流量（L/min）", "", "| 夜间 | 总表 | 越线 |", "| --- | --- | --- |"]
    lines += [f"| {p['date']} | {p['meter_lpm']} | {'⚠️' if p['flagged'] else ''} |" for p in hidden if p["meter_lpm"] is not None]
    lines += [
        "", "## 四、已知局限", "",
        "- 每个种子各 1 次注入，只证明链路跑通与方法可行，不代表统计意义的检出率。",
        "- **调参过程如实记录**：爆管最初按\"支路流量 > 该支路器具额定流量之和 × 1.5\"判断，种子 6006 中高区（入户静压 0.35 MPa）"
        "洗衣机进水流量就达到约 20 L/min，超过门槛造成误报。器具流量随水压平方根变化，固定流量门槛不成立，"
        "因此改为按压力归一化的出水口流量系数。种子 1001–3003、6006 参与了调参，盲测只看 " + "、".join(map(str, HOLDOUT_SEEDS)) + "。",
        "- 暗漏定位只能到\"支路 + 冷/热侧\"，同支路同侧的马桶与洗脸盆角阀靠先验区分（`water_leak.HIDDEN_LEAK_PRIORS`，模型假设）。",
        "- 检测下限 0.05 L/min（约 72 L/天）受水表低流量截止限制，更小的渗漏测不到。",
        "- 仿真没有把\"关阀\"反馈回水力模型：原始数据里漏水持续到无人处置的时刻，关阀后的损失按检测时刻截断估算。",
        "- 卫生间支路器具多、合计额定流量高，支路末端小口径爆裂可能达不到倍数门槛（本样例是厨房软管）。",
        "- 夜间最小流量法假设住户凌晨不会连续数小时用水；夜间长时间灌溉、鱼缸补水等会被误判，需要住户在提醒里确认。",
    ]
    return lines


if __name__ == "__main__":
    sys.exit(main())
