"""任务 1.2：生成模拟楼栋拓扑与画像分配，并输出自检报告。

用法::

    python data/scripts/build_building.py

输出：
    data/processed/sim_config/sim_building.json
    data/processed/sim_config/_truth/household_personas.json
    data/processed/evaluation/building_check_report.md
返回码 0=全部自检通过，1=有未通过项。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sim import building as bld  # noqa: E402
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE, EVALUATION_DIR, PERSONA_TRUTH_FILE  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _report(building: dict, truth: dict, results, params) -> str:
    houses = building["houses"]
    passed = sum(ok for _, ok, _ in results)
    lines = [
        "# 楼栋拓扑自检报告（任务 1.2）",
        "",
        f"> 生成脚本：`data/scripts/build_building.py`；楼栋种子 {params['seeds.building']}；数据来源 SIMULATED",
        f"> 结果：**{passed}/{len(results)} 项通过**",
        "",
        "## 一、自检结果",
        "",
        "| # | 检查项 | 结果 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for i, (name, ok, detail) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {'✅' if ok else '❌'} | {str(detail).replace('|', '/')} |")

    persona_by_layout = Counter((h["layout_id"], truth["households"][h["house_id"]]["persona"]) for h in houses)
    personas = ["FAMILY", "COUPLE", "ELDER", "TRAVELER", "VACANT"]
    lines += ["", "## 二、户型 × 画像（真值统计，仅供核对）", "",
              "| 户型 | " + " | ".join(personas) + " | 合计 |", "| --- |" + " --- |" * (len(personas) + 1)]
    for lay in ("T89", "T75", "T65"):
        row = [persona_by_layout[(lay, p)] for p in personas]
        lines.append(f"| {lay} | " + " | ".join(map(str, row)) + f" | {sum(row)} |")

    lines += ["", "## 三、批次 × 画像", "", "| 批次 | " + " | ".join(personas) + " |", "| --- |" + " --- |" * len(personas)]
    by_batch = Counter((h["batch_id"], truth["households"][h["house_id"]]["persona"]) for h in houses)
    for b in ("A", "B", "C"):
        lines.append(f"| {b} | " + " | ".join(str(by_batch[(b, p)]) for p in personas) + " |")

    lines += ["", "## 四、各楼层入户静压", "", "| 楼层 | 分区 | 减压阀 | 未减压静压 (MPa) | 入户静压 (MPa) |",
              "| --- | --- | --- | --- | --- |"]
    for floor in range(1, params["building.floors"] + 1):
        h = next(x for x in houses if x["floor"] == floor)
        lines.append(f"| {floor} | {h['supply_zone']} | {'有' if h['has_prv'] else '无'} | "
                     f"{h['raw_static_pressure_mpa']:.3f} | {h['entry_static_pressure_mpa']:.3f} |")

    sizes = Counter()
    for h in houses:
        sizes["给水节点"] += len(h["supply_network"])
        sizes["排水节点"] += len(h["drain_network"])
        sizes["电气回路"] += len(h["circuits"])
        sizes["传感器"] += len(h["sensors"])
        sizes["设备"] += len(h["devices"])
    lines += ["", "## 五、规模", "", "| 对象 | 数量 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in sizes.items()]

    lines += ["", "## 六、档案住户设备映射", ""]
    for hid in bld.ARCHIVE_HOUSE_IDS:
        h = next(x for x in houses if x["house_id"] == hid)
        arch = [d for d in h["devices"] if d["in_archive"]]
        added = [d for d in h["devices"] if not d["in_archive"]]
        lines.append(f"- **{hid}**（{h['layout']}，{h['batch_id']} 批次）：档案设备 {len(arch)} 件全部保留；"
                     f"按户型补充 {len(added)} 件（`in_archive: false`），如 "
                     + "、".join(f"`{d['device_code']}` {d['name']}" for d in added[:4]) + "。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    params = load_params()
    building, truth = bld.build(params)
    results = bld.check(building, truth, params)
    _write_json(BUILDING_FILE, building)
    _write_json(PERSONA_TRUTH_FILE, truth)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    report_path = EVALUATION_DIR / "building_check_report.md"
    report_path.write_text(_report(building, truth, results, params), encoding="utf-8", newline="\n")

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"楼栋：{len(building['houses'])} 户 → {BUILDING_FILE}")
    print(f"自检：{len(results) - len(failed)}/{len(results)} 通过 → {report_path}")
    for name, detail in failed:
        print(f"  ❌ {name}：{detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
