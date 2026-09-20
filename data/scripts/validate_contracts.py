"""数据契约校验工具（契约①–④，schema v2.0）。

两种用法：

1. 校验整个样例包（Schema + 业务一致性）::

       python data/scripts/validate_contracts.py

2. 校验单个文件，例如百炼应用① 返回的 JSON::

       python data/scripts/validate_contracts.py --contract event_decision --file out.json

依赖：``jsonschema>=4.18``（含 ``referencing``）。``scipy`` 可选，装了才会复核批次统计的 p 值。
本脚本只做校验，不修改任何文件；返回码 0=通过，1=有错误。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

try:
    from scipy.stats import fisher_exact
except ImportError:  # 统计复核是可选项
    fisher_exact = None

PROCESSED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "processed")
CONTRACTS = os.path.join(PROCESSED, "contracts")
KIT = os.path.join(PROCESSED, "bailian_kit")

# 示例价格（与样例 price_note 一致）；接入可配置价格表后应改为读取配置。
PEAK_PRICE, VALLEY_PRICE, WATER_PRICE, CO2_FACTOR = 0.62, 0.32, 3.5, 0.5703

# 住户、家属、邻户文案中不应出现的术语。
JARGON = re.compile(r"Cv|τ|tau|P90|剩余电流|基线|百分位")

# 样例包目录 → (输入契约, 期望输出文件名模板, 输出契约)
KIT_LAYOUT = [
    ("events", "event", "{}.expected.json", "event_decision"),
    ("monthly", "monthly_input", "monthly_{}.expected.json", "report_output"),
    ("batch_brief", "monthly_input", "batch_brief_{}.expected.json", "report_output"),
    ("qa", "qa_context", "qa_{}.expected.json", "qa_answer"),
]


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_validators() -> dict[str, Draft202012Validator]:
    schemas = {
        os.path.basename(p)[: -len(".schema.json")]: _load(p)
        for p in glob.glob(os.path.join(CONTRACTS, "*.schema.json"))
    }
    registry = Registry().with_resources(
        [(s["$id"], Resource.from_contents(s)) for s in schemas.values()]
    )
    validators = {}
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema, registry=registry)
    return validators


def schema_errors(validator: Draft202012Validator, data, label: str) -> list[str]:
    return [
        f"[{label}] {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message[:200]}"
        for e in validator.iter_errors(data)
    ]


def batch_houses(batch_id: str) -> set[str]:
    floors = {"A": range(1, 7), "B": range(7, 13), "C": range(13, 19)}[batch_id]
    return {f"{f}0{p}" for f in floors for p in range(1, 7)}


def check_event_pair(event: dict, decision: dict, label: str) -> list[str]:
    """契约① 输入与契约② 输出之间的业务规则（Schema 表达不了的部分）。"""
    errs = []
    if decision["event_id"] != event["event_id"]:
        errs.append(f"[{label}] 输出 event_id 与输入不一致")
    if event["scope"] == "HOUSE" and event["event_id"].split("-")[2] != event["house_id"]:
        errs.append(f"[{label}] event_id 中的户号与 house_id 不一致")

    confidences = [c["confidence"] for c in event["location_candidates"]]
    if sum(confidences) > 1.0001 or confidences != sorted(confidences, reverse=True):
        errs.append(f"[{label}] 定位候选置信度之和须 ≤1 且降序")

    audiences = [n["audience"] for n in decision["notices"]]
    if len(audiences) != len(set(audiences)):
        errs.append(f"[{label}] 同一 audience 出现多条提醒")
    for n in decision["notices"]:
        if n["audience"] in ("RESIDENT", "FAMILY", "NEIGHBOR") and JARGON.search(n["content"]):
            errs.append(f"[{label}] {n['audience']} 文案含术语：{JARGON.findall(n['content'])}")

    for w in decision["workorders"]:
        safety = "".join(w["worker_safety_notice"])
        if w["fault_type"] == "电气故障" and not ("验电" in safety and "挂牌" in safety):
            errs.append(f"[{label}] 电气工单的作业安全提示须含“验电”和“挂牌”")
    if event["event_type"] == "WATER_INTRUSION":
        text = "".join(n["content"] for n in decision["notices"]) + "".join(
            "".join(w["worker_safety_notice"]) for w in decision["workorders"]
        )
        if "插座" not in text:
            errs.append(f"[{label}] 水浸事件须提示插座回路风险")

    executed = {(a["action"], a["target"]) for a in event["control_actions_taken"]}
    if any((c["action"], c["target"]) in executed for c in decision["control_suggestions"]):
        errs.append(f"[{label}] 建议了已执行过的控制动作")

    if event["severity"] == "CRITICAL" and decision["priority"] != "URGENT":
        errs.append(f"[{label}] CRITICAL 事件的 priority 须为 URGENT")
    if event["event_type"] == "CARE_ABNORMAL" and decision["workorders"] and event["evidence"]["care_level"] < 3:
        errs.append(f"[{label}] 关怀事件仅在 3 级时创建上门工单")
    if event["event_type"] != "CARE_ABNORMAL" and decision["escalation"] is not None:
        errs.append(f"[{label}] 非关怀事件的 escalation 须为 null")

    if event["event_type"] == "BATCH_QUALITY_ALERT":
        ev = event["evidence"]
        faulted, related = set(ev["faulted_houses"]), set(event["related_houses"])
        if faulted & related or (faulted | related) != batch_houses(event["batch_id"]):
            errs.append(f"[{label}] 已故障住户与巡检住户须互斥，且合起来等于整个批次")
        for w in decision["workorders"]:
            if set(w["house_ids"]) != related:
                errs.append(f"[{label}] 批量巡检工单住户须等于 related_houses")
        errs += check_defect_stats(ev["defects"], ev["batch_house_count"], ev["other_house_count"], label)
    return errs


def check_defect_stats(defects, n_batch, n_other, label) -> list[str]:
    errs = []
    for d in defects:
        ratio = (d["batch_count"] / n_batch) / (d["other_count"] / n_other) if d["other_count"] else None
        if ratio is not None and abs(ratio - d["rate_ratio"]) > 0.01:
            errs.append(f"[{label}] {d['event_type']} 发生率比应为 {ratio:.2f}")
        if fisher_exact is not None:
            p = fisher_exact(
                [[d["batch_count"], n_batch - d["batch_count"]], [d["other_count"], n_other - d["other_count"]]],
                alternative="greater",
            ).pvalue
            if abs(p - d["p_value"]) > 0.001:
                errs.append(f"[{label}] {d['event_type']} p 值应为 {p:.3f}")
    return errs


def check_power_block(power: dict, label: str) -> list[str]:
    errs = []
    if abs(sum(power["by_circuit_kwh"].values()) - power["total_kwh"]) > 1:
        errs.append(f"[{label}] 各回路电量之和 ≠ 总电量")
    if "peak_kwh" in power:
        if abs(power["peak_kwh"] + power["valley_kwh"] - power["total_kwh"]) > 1:
            errs.append(f"[{label}] 峰谷电量之和 ≠ 总电量")
        cost = power["peak_kwh"] * PEAK_PRICE + power["valley_kwh"] * VALLEY_PRICE
        if abs(cost - power["cost_yuan"]) > 0.01:
            errs.append(f"[{label}] 电费应为 {cost:.2f}")
    if "shiftable_kwh" in power and abs(power["shiftable_kwh"] * (PEAK_PRICE - VALLEY_PRICE) - power["est_saving_yuan"]) > 0.01:
        errs.append(f"[{label}] 错峰节省金额与可转移电量不符")
    if "co2_kg" in power and abs(power["total_kwh"] * CO2_FACTOR - power["co2_kg"]) > 0.1:
        errs.append(f"[{label}] 碳排放与电量不符")
    return errs


def check_monthly_input(data: dict, label: str) -> list[str]:
    if data["report_type"] == "BATCH_BRIEF":
        faulted, inspect = set(data["faulted_houses"]), set(data["inspect_houses"])
        errs = []
        if faulted & inspect or (faulted | inspect) != batch_houses(data["batch_id"]):
            errs.append(f"[{label}] 已故障住户与巡检住户须互斥，且合起来等于整个批次")
        return errs + check_defect_stats(data["defects"], data["batch_house_count"], data["other_house_count"], label)
    water = data["water"]
    errs = check_power_block(data["power"], label)
    if abs(sum(water["by_fixture_m3"].values()) - water["total_m3"]) > 0.1:
        errs.append(f"[{label}] 各器具用水之和 ≠ 总用水量")
    if abs(water["total_m3"] * WATER_PRICE - water["cost_yuan"]) > 0.01:
        errs.append(f"[{label}] 水费与用水量不符")
    return errs


def check_qa_pair(context: dict, answer: dict, label: str) -> list[str]:
    errs = []
    for m in context["monthly"]:
        errs += check_power_block(m["power"], f"{label} {m['month']}")
    for e in answer["evidence"]:
        node = context
        try:
            for part in re.findall(r"[^.\[\]]+", e["source_path"]):
                node = node[int(part)] if part.isdigit() else node[part]
        except (KeyError, IndexError, TypeError):
            errs.append(f"[{label}] evidence 路径不存在：{e['source_path']}")
            continue
        number = f"{node:g}" if isinstance(node, (int, float)) else str(node)
        if number not in e["value"]:
            errs.append(f"[{label}] evidence {e['source_path']}={number} 与展示值 {e['value']} 不符")
    return errs


def validate_kit(validators) -> tuple[int, list[str]]:
    checked, errs = 0, []
    for folder, in_contract, expected_tpl, out_contract in KIT_LAYOUT:
        for path in sorted(glob.glob(os.path.join(KIT, folder, "*.json"))):
            stem = os.path.basename(path)[: -len(".json")]
            data = _load(path)
            errs += schema_errors(validators[in_contract], data, f"{folder}/{stem}")
            checked += 1
            expected_path = os.path.join(KIT, "expected", expected_tpl.format(stem))
            if not os.path.exists(expected_path):
                errs.append(f"[{folder}/{stem}] 缺少期望输出 {os.path.basename(expected_path)}")
                continue
            out = _load(expected_path)
            out_errs = schema_errors(validators[out_contract], out, f"expected/{os.path.basename(expected_path)}")
            errs += out_errs
            checked += 1
            if out_errs:
                continue  # Schema 不通过时跳过业务检查，避免连锁报错
            if in_contract == "event":
                errs += check_event_pair(data, out, stem)
            elif in_contract == "monthly_input":
                errs += check_monthly_input(data, stem)
            elif in_contract == "qa_context":
                errs += check_qa_pair(data, out, stem)
    return checked, errs


def main() -> int:
    parser = argparse.ArgumentParser(description="校验筑维AI 数据契约")
    parser.add_argument("--contract", help="契约名：event / event_decision / monthly_input / report_output / qa_context / qa_answer")
    parser.add_argument("--file", help="待校验的 JSON 文件")
    parser.add_argument("--event", help="与 --contract event_decision 搭配：对应的契约① 输入文件，用于业务规则检查")
    args = parser.parse_args()

    validators = build_validators()
    if args.file:
        if args.contract not in validators:
            parser.error(f"--contract 须为：{', '.join(sorted(validators))}")
        data = _load(args.file)
        errs = schema_errors(validators[args.contract], data, os.path.basename(args.file))
        if not errs and args.contract == "event_decision" and args.event:
            errs = check_event_pair(_load(args.event), data, os.path.basename(args.file))
        checked = 1
    else:
        checked, errs = validate_kit(validators)

    print(f"契约 Schema：{len(validators)} 个；已校验文件：{checked} 个")
    if errs:
        print("\n".join(errs))
        print(f"失败：{len(errs)} 处")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
