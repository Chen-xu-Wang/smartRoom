"""端到端样例：1302 卫生间花洒头渐进结垢（WF3 进水堵塞）。

流程：行为模型 → 给水水力模型 + 故障注入 → 传感器数据流 → 检测与定位（后端纯函数）
      → 规则引擎决策 → 契约校验 → 与真值对比的评估报告。

三个场景，行为数据完全相同，只有注入不同：
    fault                 06-20 起花洒头通流能力线性下降，07-12 降到 50%
    control_normal        不注入，检测不应报出
    control_pressure_dip  06-25 起高区供水压力下降 0.06 MPa（干扰工况 N1），检测不应报堵塞

样例数据（落盘、供后端演示）使用 sim_dev 种子；另用两个从未参与调参的种子做盲测复核
（只在内存中计算，结果写进报告）。

用法::

    python data/scripts/run_sample_blockage.py

输出：
    data/processed/samples/supply_blockage_1302/<场景>/sensor_stream.csv.gz   公开：传感器读数
    data/processed/samples/supply_blockage_1302/<场景>/manifest.json
    data/processed/samples/supply_blockage_1302/<场景>/_truth/                 真值（检测不可读）
    data/processed/samples/supply_blockage_1302/<场景>/detection.json         检测结果（事件 + 诊断）
    data/processed/samples/supply_blockage_1302/<场景>/decision.json          规则引擎决策（有事件时）
    data/processed/evaluation/sample_supply_blockage_report.md
返回码 0=全部检查通过，1=有未通过项。
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
from sim.water_stream import Fault, PressureEvent, Scenario, generate_stream, stream_manifest  # noqa: E402
from validate_contracts import build_validators, check_event_pair, schema_errors  # noqa: E402

from app.services import event_rules, water_blockage  # noqa: E402

HOUSE_ID = "1302"
START, END = date(2026, 6, 1), date(2026, 7, 12)
SAMPLE_DIR = PROCESSED_DIR / "samples" / "supply_blockage_1302"
# 盲测种子：未参与统计量与阈值选择。第一次盲测用的 4004、5005 因出现漏报被拿去分析原因，
# 已并入调参集（见 water_blockage 模块说明），改用下面三个新种子。
HOLDOUT_SEEDS = [6006, 7007, 8008]
DELAY_TARGET_DAYS = 5.0       # 工作方案 4.3：渐进劣化检测延迟目标

SCENARIOS = [
    Scenario(
        name="fault",
        description="WF3 花洒头渐进结垢：06-20 起通流能力线性下降，07-12 降到 50%",
        faults=[Fault("WF3", "SHOWER_HEAD_SCALING", "WS-1302-B-SH", "cv_factor", "2026-06-20", "2026-07-12", 0.50)],
    ),
    Scenario(name="control_normal", description="无故障对照：检测不应报出"),
    Scenario(
        name="control_pressure_dip",
        description="干扰工况 N1：06-25 起高区变频泵出口压力下降 0.06 MPa，检测不应报进水堵塞",
        pressure_events=[PressureEvent("2026-06-25", "2026-07-13", -0.06, "高区变频泵出口压力下降")],
    ),
]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_seed(seed: int, params, building, personas, house, save: bool, validators) -> tuple[dict, list]:
    """生成一个种子下的三个场景并检测。返回 (场景结果, 契约校验项)。"""
    frames, profiles = bh.generate(building, personas, params, seed,
                                   date.fromisoformat(params["calendar.main_window_start"]),
                                   date.fromisoformat(params["calendar.main_window_end"]), {HOUSE_ID})
    heater_setpoint = profiles[HOUSE_ID].habits["heater_setpoint_c"]
    results, checks = {}, []
    for sc in SCENARIOS:
        stream_df, truth = generate_stream(house, frames["events"], heater_setpoint, params, seed, START, END, sc)
        if save:
            out = SAMPLE_DIR / sc.name
            (out / "_truth").mkdir(parents=True, exist_ok=True)
            stream_path = out / "sensor_stream.csv.gz"
            stream_df.to_csv(stream_path, index=False, compression={"method": "gzip", "mtime": 0})
            _write_json(out / "manifest.json", stream_manifest(house, house["sensors"], seed, START, END, sc))
            truth.to_csv(out / "_truth" / "fixture_uses.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
            _write_json(out / "_truth" / "scenario.json", {
                "scenario": sc.name, "description": sc.description,
                "faults": [asdict(f) for f in sc.faults], "pressure_events": [asdict(p) for p in sc.pressure_events],
            })
            stream = water_blockage.read_stream_csv(str(stream_path))
        else:
            stream = water_blockage.Stream(
                [pd.Timestamp(t).to_pydatetime() for t in stream_df["ts"]],
                {c: stream_df[c].tolist() for c in stream_df.columns if c != "ts"},
            )
        result = water_blockage.detect_supply_blockage(stream, house, building["building"])
        decision = event_rules.decide(result["event"]) if result["event"] else None
        if save:
            _write_json(SAMPLE_DIR / sc.name / "detection.json", result)
            decision_path = SAMPLE_DIR / sc.name / "decision.json"
            if decision:
                _write_json(decision_path, decision)
            elif decision_path.exists():
                decision_path.unlink()
        if decision:
            errs = schema_errors(validators["event"], result["event"], f"{seed}/{sc.name}/event")
            errs += schema_errors(validators["event_decision"], decision, f"{seed}/{sc.name}/decision")
            errs += check_event_pair(result["event"], decision, f"{seed}/{sc.name}")
            checks.append((f"种子 {seed} {sc.name}：事件与决策通过契约 Schema 与业务规则校验", not errs, "；".join(errs) or "通过"))
        results[sc.name] = {"rows": len(stream_df), "truth": truth, "result": result, "decision": decision}
    return results, checks


def seed_metrics(results: dict) -> dict:
    fault = SCENARIOS[0].faults[0]
    res = results["fault"]["result"]
    ev = res["event"]
    showers = results["fault"]["truth"]
    showers = showers[showers["fixture"] == "SHOWER"]
    crossed = showers[showers["cv_factor"] <= 1 - 0.30]
    cross_t = crossed["start"].min() if not crossed.empty else None
    m = {
        "detected": ev is not None, "top1": None, "delay_days": None, "cross_t": cross_t,
        "trend": None, "same_branch": None,
        "false_alarm_normal": results["control_normal"]["result"]["event"] is not None,
        "false_alarm_dip": results["control_pressure_dip"]["result"]["event"] is not None,
        "worst_control_change": min(
            (p["change_ratio"] for name in ("control_normal", "control_pressure_dip")
             for p in results[name]["result"]["diagnostics"]["daily"] if p["change_ratio"] is not None), default=None),
    }
    if ev:
        detected = pd.Timestamp(ev["detected_at"][:19])
        m.update(
            top1=ev["location_candidates"][0]["segment_code"] == fault.target,
            top1_code=ev["location_candidates"][0]["segment_code"],
            detected_at=ev["detected_at"],
            delay_days=(detected - cross_t).total_seconds() / 86400 if cross_t is not None else None,
            true_factor=float(showers[showers["start"] <= detected]["cv_factor"].iloc[-1]),
            trend=ev["evidence"]["trend"], same_branch=ev["evidence"]["same_branch_other_fixtures"],
        )
    return m


def main() -> int:
    params = load_params()
    building = json.loads(BUILDING_FILE.read_text(encoding="utf-8"))
    personas = json.loads(PERSONA_TRUTH_FILE.read_text(encoding="utf-8"))
    house = next(h for h in building["houses"] if h["house_id"] == HOUSE_ID)
    validators = build_validators()

    dev_seed = params["seeds.dev"]
    dev, checks = run_seed(dev_seed, params, building, personas, house, True, validators)
    for sc in SCENARIOS:
        print(f"[dev {sc.name}] 传感器行数 {dev[sc.name]['rows']}，状态 {dev[sc.name]['result']['diagnostics']['status']}")
    metrics = {dev_seed: seed_metrics(dev)}
    holdout = {}
    for seed in HOLDOUT_SEEDS:
        holdout[seed], more = run_seed(seed, params, building, personas, house, False, validators)
        checks += more
        metrics[seed] = seed_metrics(holdout[seed])
        print(f"[盲测 {seed}] 故障 {holdout[seed]['fault']['result']['diagnostics']['status']}")

    fault_target = SCENARIOS[0].faults[0].target
    for seed, m in metrics.items():
        tag = "样例" if seed == dev_seed else "盲测"
        checks.append((f"{tag} 种子 {seed}：检测到进水堵塞事件", m["detected"], "EVENT" if m["detected"] else "未报出"))
        if m["detected"]:
            checks.append((f"{tag} 种子 {seed}：首选定位 = 注入位置", m["top1"], f"首选 {m['top1_code']}，真值 {fault_target}"))
        checks.append((f"{tag} 种子 {seed}：两个对照场景均无误报", not (m["false_alarm_normal"] or m["false_alarm_dip"]),
                       f"正常 {'误报' if m['false_alarm_normal'] else '无'}，压力下降 {'误报' if m['false_alarm_dip'] else '无'}"))

    lines = render_report(dev, metrics, checks, dev_seed)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "sample_supply_blockage_report.md").write_text("\n".join(lines), encoding="utf-8")
    for name, ok, detail in checks:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"：{detail}"))
    for seed, m in metrics.items():
        if m["delay_days"] is not None:
            print(f"  · 种子 {seed} 检测延迟 {m['delay_days']:.1f} 天（目标 ≤ {DELAY_TARGET_DAYS:.0f} 天，仅报告）")
    return 1 if any(not ok for _, ok, _ in checks) else 0


def _fmt_delay(d):
    if d is None:
        return "—"
    flag = "" if d <= DELAY_TARGET_DAYS else "（超出目标）"
    return f"{d:+.1f} 天{flag}" if d < 0 else f"{d:.1f} 天{flag}"


def render_report(dev, metrics, checks, dev_seed) -> list[str]:
    cfg = water_blockage.BlockageConfig()
    lines = [
        "# 端到端样例评估：1302 花洒头渐进结垢（WF3）",
        "",
        f"> 生成：`data/scripts/run_sample_blockage.py`　数据来源：SIMULATED",
        f"> 时段：{START} → {END}；基线学习期 {cfg.baseline_days} 天；出水能力取 P{round(cfg.capability_quantile * 100)}，"
        f"{cfg.window_days} 天窗口，最近 {cfg.persist_window} 天内 {cfg.persist_days} 天下降超过 {cfg.drop_threshold:.0%} 报出",
        "",
        "## 一、检查结果",
        "",
        "| 检查项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in checks]

    lines += ["", "## 二、各种子汇总", "",
              "| 种子 | 用途 | 报出时刻 | 报出时真实通流能力 | 检测延迟（相对降到 70%） | 首选定位 | 趋势 | 对照最差日变化 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for seed, m in metrics.items():
        use = "样例（参与调参）" if seed == dev_seed else "盲测"
        lines.append(
            f"| {seed} | {use} | {m.get('detected_at', '未报出')} | "
            f"{'—' if 'true_factor' not in m else f'{m['true_factor']:.0%}'} | {_fmt_delay(m['delay_days'])} | "
            f"{'✅ ' if m['top1'] else '❌ '}{m.get('top1_code', '—')} | {m['trend'] or '—'} | "
            f"{'—' if m['worst_control_change'] is None else f'{m['worst_control_change']:+.0%}'} |"
        )
    lines += ["", f"检测延迟目标 ≤ {DELAY_TARGET_DAYS:.0f} 天（工作方案 4.3）只作报告、不作为通过条件：阈值越激进延迟越短，但对照场景的误报会增加。"]

    lines += ["", f"## 三、样例场景（种子 {dev_seed}，已落盘供后端演示）", "",
              "| 场景 | 注入 | 传感器行数 | 检测状态 | 事件 |", "| --- | --- | --- | --- | --- |"]
    for sc in SCENARIOS:
        r = dev[sc.name]
        ev = r["result"]["event"]
        brief = "—" if not ev else f"{ev['event_id']}，首选 {ev['location_candidates'][0]['segment_name']}（{ev['location_candidates'][0]['confidence']}）"
        lines.append(f"| {sc.name} | {sc.description} | {r['rows']:,} | {r['result']['diagnostics']['status']} | {brief} |")

    ev = dev["fault"]["result"]["event"]
    if ev:
        e = ev["evidence"]
        m = metrics[dev_seed]
        lines += [
            "", "### 故障场景明细", "",
            "| 项 | 值 |", "| --- | --- |",
            f"| 故障注入开始（真值） | {SCENARIOS[0].faults[0].start} |",
            f"| 通流能力降到 70%（真值） | {m['cross_t']} |",
            f"| 报出时刻 | {ev['detected_at']} |",
            f"| 估计开始变差日期 | {ev['fault_started_est']} |",
            f"| 出水能力 基线 → 近期 | {e['baseline']} → {e['recent']}（{e['change_ratio']:+.0%}） |",
            f"| 冷水 / 热水变化 | {e['cold_change_ratio']:+.0%} / {e['hot_change_ratio']:+.0%} → {e['hot_cold']} |",
            f"| 同支路其它器具变化 | {e['other_fixtures_change_ratio']} → {e['same_branch_other_fixtures']} |",
            f"| 入户静压变化 | {e['inlet_pressure_change']:+.1%} |",
            "| 定位候选 | " + "；".join(f"{c['segment_name']} {c['confidence']}" for c in ev["location_candidates"]) + " |",
        ]
        lines += ["", "逐日出水能力（相对入住初期）：", "", "| 日期 | 淋浴次数 | 变化 | 越线 |", "| --- | --- | --- | --- |"]
        for p in dev["fault"]["result"]["diagnostics"]["daily"]:
            chg = "—" if p["change_ratio"] is None else f"{p['change_ratio']:+.0%}"
            lines.append(f"| {p['date']} | {p['events']} | {chg} | {'⚠️' if p['flagged'] else ''} |")

    lines += [
        "", "## 四、已知局限与发现", "",
        "- 每个种子只有 1 户、1 类故障、1 次注入，结论只证明链路跑通和方法可行，不代表统计意义上的检出率；批量盲测在任务 1.12 完成。",
        "- **调参过程如实记录**：最初用出水能力上限（P90/P95），在种子 1001–3003 上选定参数后，第一次盲测（种子 4004、5005）"
        "两份均漏报。原因是这两户很少全开阀门，上分位数基线被低估。4004、5005 因此并入调参集，五份数据比较后改用中位数"
        "（5/5 检出、0/10 误报），再用从未看过的种子 " + "、".join(map(str, HOLDOUT_SEEDS)) + " 做本次盲测。",
        "- 中位数假设住户开度习惯稳定；住户因出水变小而主动开大阀门的补偿行为尚未模拟，可能掩盖部分下降。",
        "- 定位置信度来自先验表（`water_blockage.LOCALIZATION_PRIORS`，模型假设）乘以证据强度，尚未用多次注入标定。",
        "- 花洒头与混水阀芯在现有布点下压力特征相同，只能靠趋势（渐进/突发）区分，这是布点限制。",
        "- 水力模型忽略立管动压损失、器具安装高度差和开关水瞬态。",
        "- **行为模型发现**：任务 1.4 的行为层会给同一器具排出时间重叠的使用（每个种子约 260–280 次，如两人同时淋浴）。"
        "给水模型已按\"同一器具同一时刻只能一人使用、后到者排队\"处理，行为层本身尚未修改。",
    ]
    return lines


if __name__ == "__main__":
    sys.exit(main())
