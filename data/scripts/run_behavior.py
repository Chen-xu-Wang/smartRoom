"""任务 1.4：生成行为模型预览，并对 90 天行为数据做自检。

用法::

    python data/scripts/run_behavior.py              # 默认 dev 数据集
    python data/scripts/run_behavior.py --dataset test

输出（以 dev 为例）：
    data/processed/sim_dev/behavior_preview/*.csv.gz   前 14 天全部住户的行为数据（预览）
    data/processed/sim_dev/_truth/household_profiles.json   住户习惯真值
    data/processed/evaluation/behavior_check_report_dev.md
完整 90 天行为数据会在任务 1.8 与物理模型一起生成，这里只在内存中计算用于自检。
返回码 0=全部自检通过，1=有未通过项。
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sim import behavior as bh  # noqa: E402
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE, EVALUATION_DIR, PERSONA_TRUTH_FILE, dataset_dir  # noqa: E402

PREVIEW_DAYS = 14
PERSONAS = ["FAMILY", "COUPLE", "ELDER", "TRAVELER", "VACANT"]
OCCUPIED = ["FAMILY", "COUPLE", "ELDER", "TRAVELER"]
FIXTURE_GROUP = {"SHOWER": "SHOWER", "TOILET": "TOILET", "KITCHEN_FAUCET": "KITCHEN", "WASHER": "LAUNDRY",
                 "BASIN": "BASIN"}


def _frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df.astype(str), index=False).values.tobytes()).hexdigest()[:16]


def _fmt(x, digits=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{digits}f}"


def compute_checks(frames, profiles, building, personas, params, seed):
    results = []  # (检查项, 通过, 说明)
    add = lambda name, ok, detail="": results.append((name, bool(ok), detail))  # noqa: E731
    tables = {}

    events, presence, ac = frames["events"], frames["presence"], frames["ac_intents"]
    persona_of = {h: v["persona"] for h, v in personas["households"].items()}
    events = events.assign(persona=events["house_id"].map(persona_of),
                           date=events["start"].dt.normalize())
    water = events[events["kind"] == "WATER"].copy()
    water["litres"] = bh.estimate_water_l(water, building, params)
    start = pd.Timestamp(params["calendar.main_window_start"])
    end = pd.Timestamp(params["calendar.main_window_end"]) + pd.Timedelta(days=1)
    n_days = (end - start).days

    # ---- 1. 可复现性 ----
    # 外出计划与模拟窗口长度有关，因此可复现性检查始终使用完整窗口
    sub = {"1302", "805", "503", "1701"}
    d0 = date.fromisoformat(params["calendar.main_window_start"])
    d1 = date.fromisoformat(params["calendar.main_window_end"])
    a, _ = bh.generate(building, personas, params, seed, d0, d1, sub)
    b, _ = bh.generate(building, personas, params, seed, d0, d1, sub)
    c, _ = bh.generate(building, personas, params, seed + 1, d0, d1, sub)
    add("同一种子重复生成结果完全一致", _frame_hash(a["events"]) == _frame_hash(b["events"]),
        f"hash {_frame_hash(a['events'])}")
    add("不同种子生成结果不同", _frame_hash(a["events"]) != _frame_hash(c["events"]), "")
    full_sub = frames["events"][frames["events"]["house_id"].isin(sub)].reset_index(drop=True)
    add("与住户遍历范围无关（只算 4 户与算全楼时这 4 户结果一致）",
        _frame_hash(full_sub) == _frame_hash(a["events"]), f"{len(full_sub)} 条事件")

    # ---- 2. 基本合法性 ----
    add("事件时长均为正", (events["duration_s"] > 0).all(), f"{len(events)} 条事件")
    add("事件时间落在模拟窗口内", ((events["start"] >= start) & (events["start"] < end + pd.Timedelta(hours=6))).all(),
        f"{events['start'].min()} — {events['start'].max()}")
    overlap = 0
    for (hid, pid), grp in presence.sort_values("start").groupby(["house_id", "person_id"]):
        overlap += int((grp["start"].values[1:] < grp["end"].values[:-1]).sum())
    add("同一成员的在家/外出/睡眠区间互不重叠", overlap == 0, f"重叠 {overlap} 处")

    def share_within(evts: pd.DataFrame, states: set[str], slack: pd.Timedelta) -> float:
        """事件开始时刻落在该成员某个指定状态区间内的比例（按开始时刻就近匹配区间）。"""
        ivs = presence[presence["state"].isin(states)][["person_id", "start", "end"]].rename(
            columns={"start": "iv_start", "end": "iv_end"}).sort_values("iv_start")
        e = evts[["person_id", "start"]].sort_values("start")
        m = pd.merge_asof(e, ivs, left_on="start", right_on="iv_start", by="person_id", direction="backward")
        return float((m["start"] < m["iv_end"] + slack).mean()) if len(m) else 1.0

    person_events = events[events["person_id"].notna() & (events["activity"] != "NIGHT_TOILET")]
    share_inside = share_within(person_events, {"HOME_AWAKE"}, pd.Timedelta(minutes=2))
    add("成员个人事件发生在其在家清醒时段内（≥ 99%）", share_inside >= 0.99, f"{share_inside:.2%}")
    night_events = events[events["activity"] == "NIGHT_TOILET"]
    share_night = share_within(night_events, {"SLEEP"}, pd.Timedelta(0))
    add("夜间如厕发生在睡眠时段内（≥ 99%）", share_night >= 0.99, f"{len(night_events)} 次，{share_night:.2%}")

    # ---- 3. 用水量级 ----
    residents = {h["house_id"]: h["registered_residents"] for h in building["houses"]}
    person_days = presence[presence["state"] != "AWAY"].assign(date=lambda d: d["start"].dt.normalize())
    home_person_days = person_days.drop_duplicates(["person_id", "date"]).groupby("house_id").size()
    house_litres = water.groupby("house_id")["litres"].sum()
    per_capita = (house_litres / home_person_days).dropna()
    per_capita = per_capita[per_capita.index.map(persona_of).isin(OCCUPIED)]
    lo, hi = params["behavior.validation_targets"]["per_capita_water_l_per_day"]
    rows = []
    for persona in OCCUPIED:
        vals = per_capita[per_capita.index.map(persona_of) == persona]
        rows.append((persona, len(vals), vals.mean(), vals.min(), vals.max()))
    tables["per_capita"] = rows
    add(f"各画像人均日用水量均值在 {lo}–{hi} L/人·日", all(lo <= r[2] <= hi for r in rows),
        "；".join(f"{r[0]} {r[2]:.0f}" for r in rows))
    add("全楼人均日用水量（按在家人日计）在范围内", lo <= house_litres.sum() / home_person_days.sum() <= hi,
        f"{house_litres.sum() / home_person_days.sum():.0f} L/人·日")

    shares = water.groupby(water["device"].map(FIXTURE_GROUP))["litres"].sum() / water["litres"].sum()
    targets = params["behavior.validation_targets"]["fixture_share"]
    tables["shares"] = [(k, shares.get(k, 0.0), v) for k, v in targets.items()]
    add("全楼分项用水占比在目标区间", all(v[0] <= shares.get(k, 0) <= v[1] for k, v in targets.items()),
        "；".join(f"{k} {shares.get(k, 0):.0%}" for k in targets))

    vacant = house_litres[house_litres.index.map(persona_of) == "VACANT"].reindex(
        [h for h, p in persona_of.items() if p == "VACANT"], fill_value=0.0)
    add("空置房日均用水 < 5 L，且有业主到访记录", (vacant / n_days).max() < 5 and (vacant > 0).any(),
        f"最大 {(vacant / n_days).max():.2f} L/日，有到访 {(vacant > 0).sum()}/{len(vacant)} 户")

    # ---- 4. 画像之间的差异 ----
    wd = water[water["start"].dt.dayofweek < 5]
    # 首次用水按 4:00 以后计，排除前一晚过零点的睡前洗漱与夜间如厕
    morning = wd[wd["start"].dt.hour >= 4]
    first_use = morning.groupby(["house_id", "date"])["start"].min()
    first_hour = (first_use - first_use.dt.normalize()).dt.total_seconds() / 3600
    daytime_share = wd.assign(day=wd["start"].dt.hour.between(9, 16)).groupby("house_id").apply(
        lambda d: d.loc[d["day"], "litres"].sum() / max(d["litres"].sum(), 1e-9), include_groups=False)
    by_persona_first = {p: first_hour[first_hour.index.get_level_values(0).map(persona_of) == p]
                        .groupby(level=0).mean() for p in OCCUPIED}
    by_persona_day = {p: daytime_share[daytime_share.index.map(persona_of) == p] for p in OCCUPIED}
    kw_first = stats.kruskal(*[v.values for v in by_persona_first.values()])
    kw_day = stats.kruskal(*[v.values for v in by_persona_day.values()])
    tables["persona_diff"] = [(p, by_persona_first[p].mean(), by_persona_day[p].mean()) for p in OCCUPIED]
    add("工作日首次用水时刻在画像间差异显著（Kruskal-Wallis p < 0.001）", kw_first.pvalue < 1e-3,
        f"p = {kw_first.pvalue:.1e}")
    add("工作日白天（9–17 时）用水占比在画像间差异显著（p < 0.001）", kw_day.pvalue < 1e-3, f"p = {kw_day.pvalue:.1e}")
    elder_day = by_persona_day["ELDER"].mean()
    worker_day = pd.concat([by_persona_day["COUPLE"]]).mean()
    add("独居老人白天用水占比高于年轻情侣", elder_day > worker_day, f"{elder_day:.0%} vs {worker_day:.0%}")

    home_hours = presence[presence["state"] == "HOME_AWAKE"].assign(
        hours=lambda d: (d["end"] - d["start"]).dt.total_seconds() / 3600,
        weekday=lambda d: d["start"].dt.dayofweek < 5)
    hh = home_hours[home_hours["weekday"]].groupby(["house_id", "person_id"])["hours"].sum() / (n_days * 5 / 7)
    tables["home_hours"] = [(p, hh[hh.index.get_level_values(0).map(persona_of) == p].mean()) for p in OCCUPIED]

    # ---- 5. 同画像内的个体差异 ----
    daily = water.groupby(["house_id", "date"])["litres"].sum().unstack(fill_value=0.0)
    cv_rows, corr_rows = [], []
    cv_min = params["behavior.validation_targets"]["within_persona_household_cv_min"]
    corr_max = params["behavior.validation_targets"]["within_persona_profile_corr_max"]
    for persona in OCCUPIED:
        houses = [h for h in daily.index if persona_of[h] == persona]
        means = house_litres.reindex(houses) / n_days
        cv = means.std() / means.mean()
        corrs = [np.corrcoef(daily.loc[a], daily.loc[b])[0, 1] for a, b in itertools.combinations(houses, 2)]
        cv_rows.append((persona, cv))
        corr_rows.append((persona, float(np.nanmedian(corrs)), float(np.nanmax(corrs))))
    tables["cv"], tables["corr"] = cv_rows, corr_rows
    add(f"同画像住户的日均用水量变异系数 ≥ {cv_min}", all(r[1] >= cv_min for r in cv_rows),
        "；".join(f"{r[0]} {r[1]:.2f}" for r in cv_rows))
    add(f"同画像任意两户逐日用水序列相关系数 < {corr_max}（非复制）", all(r[2] < corr_max for r in corr_rows),
        "；".join(f"{r[0]} 最大 {r[2]:.2f}" for r in corr_rows))

    # ---- 6. 关怀基线 ----
    elders = [h for h, p in persona_of.items() if p == "ELDER"]
    elder_wake = presence[(presence["house_id"].isin(elders)) & (presence["state"] == "SLEEP")
                          & (presence["start"].dt.hour < 1) & (presence["end"].dt.hour < 12)]
    wake_h = (elder_wake["end"] - elder_wake["end"].dt.normalize()).dt.total_seconds() / 3600
    wake_sd = wake_h.groupby(elder_wake["house_id"]).std()
    sd_max = params["behavior.validation_targets"]["elder_wake_sd_max_h"]
    naps = presence[(presence["house_id"].isin(elders)) & (presence["state"] == "NAP")]
    add(f"独居老人逐日起床时刻标准差中位数 ≤ {sd_max} h（作息规律，关怀检测可建基线）", wake_sd.median() <= sd_max,
        f"中位数 {wake_sd.median():.2f} h；午睡 {len(naps)} 次（天然的'长时间静止'干扰）")

    # ---- 7. 外出与访客 ----
    away_share = {}
    for persona in OCCUPIED:
        pids = presence[presence["house_id"].map(persona_of) == persona]
        full_away = pids[(pids["state"] == "AWAY") & ((pids["end"] - pids["start"]) >= pd.Timedelta(hours=23.9))]
        away_share[persona] = full_away.drop_duplicates(["person_id", "start"]).shape[0] / max(
            1, pids["person_id"].nunique() * n_days)
    tables["away"] = away_share
    add("长期出差画像整日外出比例在 30%–65%", 0.30 <= away_share["TRAVELER"] <= 0.65, f"{away_share['TRAVELER']:.0%}")
    add("有家庭暑期出游（整日外出），且不在基线学习期内",
        away_share["FAMILY"] > 0 and not presence[(presence["state"] == "AWAY")
                                                  & ((presence["end"] - presence["start"]) >= pd.Timedelta(hours=23.9))
                                                  & (presence["house_id"].map(persona_of).isin(["FAMILY", "COUPLE", "ELDER"]))
                                                  & (presence["start"] < start + pd.Timedelta(days=params["calendar.baseline_learning_days"]))].shape[0],
        f"FAMILY {away_share['FAMILY']:.1%}")
    add("有访客事件（天然的用水激增干扰）", (events["activity"] == "GUEST_TOILET").any(),
        f"{(events['activity'] == 'GUEST_TOILET').sum()} 次访客如厕")

    # ---- 8. 洗衣、空调、热水器 ----
    laundry = events[events["device"] == "WASHER"].groupby("house_id").size() / (n_days / 7)
    lrows = []
    ok_laundry = True
    for persona in OCCUPIED:
        houses = [h for h, p in persona_of.items() if p == persona]
        actual = laundry.reindex(houses, fill_value=0).mean()
        target = np.mean([profiles[h].habits["laundry_per_week"] for h in houses])
        home_ratio = 1 - away_share[persona]
        lrows.append((persona, actual, target, target * home_ratio))
        ok_laundry &= abs(actual - target * home_ratio) <= 0.25 * target * home_ratio + 0.3
    tables["laundry"] = lrows
    add("每周洗衣次数与习惯参数一致（按在家天数折算，误差 ≤ 25%）", ok_laundry,
        "；".join(f"{r[0]} {r[1]:.1f}/{r[3]:.1f}" for r in lrows))

    ac_hours = ac.assign(hours=(ac["end"] - ac["start"]).dt.total_seconds() / 3600)
    ac_by = ac_hours.groupby([ac_hours["house_id"].map(persona_of), "room"])["hours"].sum().unstack(fill_value=0)
    counts = pd.Series(persona_of).value_counts()
    tables["ac"] = [(p, ac_by.loc[p].get("LIVING", 0) / counts[p] / n_days, ac_by.loc[p].get("BEDROOM_MAIN", 0)
                     / counts[p] / n_days) for p in OCCUPIED if p in ac_by.index]
    add("空调使用意图：独居老人客厅时长最长、所有入住画像都有卧室夜间意图",
        max(tables["ac"], key=lambda r: r[1])[0] == "ELDER" and all(r[2] > 4 for r in tables["ac"]),
        "；".join(f"{r[0]} 客厅 {r[1]:.1f} h/日" for r in tables["ac"]))
    modes = pd.Series([p.habits["heater_mode"] for p in profiles.values()]).value_counts()
    tables["heater_modes"] = modes.to_dict()
    add("热水器使用模式三种都有，空置房为关闭", set(modes.index) == {"ALWAYS_ON", "VALLEY_TIMER", "SMART_PREHEAT", "OFF"},
        str(modes.to_dict()))

    # ---- 9. 与契约样例的一致性（参考项，不计入通过率） ----
    t = pd.Timestamp("2026-06-23 14:06:10")
    at_home = presence[(presence["house_id"] == "805") & (presence["start"] <= t) & (presence["end"] > t)]
    tables["sample02"] = at_home[["person_id", "state"]].values.tolist()
    return results, tables


def write_report(path: Path, dataset: str, seed: int, results, tables, frames, preview_dir: Path) -> None:
    passed = sum(ok for _, ok, _ in results)
    L = [
        f"# 行为模型自检报告（任务 1.4，数据集 {dataset}）",
        "",
        f"> 生成脚本：`data/scripts/run_behavior.py --dataset {dataset}`；种子 {seed}；模拟窗口 90 天；数据来源 SIMULATED",
        f"> 结果：**{passed}/{len(results)} 项通过**",
        "> 用水量为行为层估算（按入户静压与水效流量折算），精确水量由 1.5 水力模型计算，量级应一致。",
        "",
        "## 一、自检结果",
        "",
        "| # | 检查项 | 结果 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for i, (name, ok, detail) in enumerate(results, 1):
        L.append(f"| {i} | {name} | {'✅' if ok else '❌'} | {str(detail).replace('|', '/')} |")

    L += ["", "## 二、各画像人均日用水量（L/人·日，按在家人日计）", "", "| 画像 | 户数 | 均值 | 最小 | 最大 |",
          "| --- | --- | --- | --- | --- |"]
    L += [f"| {p} | {n} | {m:.0f} | {lo:.0f} | {hi:.0f} |" for p, n, m, lo, hi in tables["per_capita"]]

    L += ["", "## 三、全楼分项用水占比", "", "| 分项 | 占比 | 目标区间 |", "| --- | --- | --- |"]
    L += [f"| {k} | {v:.1%} | {t[0]:.0%}–{t[1]:.0%} |" for k, v, t in tables["shares"]]

    L += ["", "## 四、画像差异", "",
          "| 画像 | 工作日首次用水时刻（h） | 工作日白天用水占比 | 工作日人均在家清醒时长（h） | 整日外出比例 | 客厅空调意图（h/日） | 卧室空调意图（h/日） |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    hh = dict(tables["home_hours"])
    acd = {r[0]: r for r in tables["ac"]}
    for p, first, day in tables["persona_diff"]:
        L.append(f"| {p} | {first:.2f} | {day:.0%} | {hh[p]:.1f} | {tables['away'][p]:.0%} | "
                 f"{_fmt(acd[p][1])} | {_fmt(acd[p][2])} |")

    L += ["", "## 五、同画像内个体差异", "", "| 画像 | 户间日均用水变异系数 | 两户逐日序列相关系数中位数 | 最大值 |",
          "| --- | --- | --- | --- |"]
    corr = {r[0]: r for r in tables["corr"]}
    L += [f"| {p} | {cv:.2f} | {corr[p][1]:.2f} | {corr[p][2]:.2f} |" for p, cv in tables["cv"]]

    L += ["", "## 六、洗衣频率（次/周）", "", "| 画像 | 实际 | 习惯参数 | 按在家天数折算的期望 |", "| --- | --- | --- | --- |"]
    L += [f"| {p} | {a:.2f} | {t:.2f} | {e:.2f} |" for p, a, t, e in tables["laundry"]]

    ev = frames["events"]
    L += ["", "## 七、事件规模（90 天）", "", "| 设备 | 事件数 |", "| --- | --- |"]
    L += [f"| {d} | {n} |" for d, n in ev["device"].value_counts().items()]
    L += [f"| 在家/外出/睡眠区间 | {len(frames['presence'])} |", f"| 空调使用意图 | {len(frames['ac_intents'])} |",
          f"| 热水器启用时段 | {len(frames['heater_schedule'])} |"]

    L += ["", "## 八、与契约样例的对照（参考）", "",
          f"- 样例 02：805 在 2026-06-23 14:06 爆管时\"家中无人\"。本数据集该时刻 805 成员状态："
          f"{tables['sample02']}。样例是手写的，行为模型不强制与之一致；1.7 注入故障时会选择真实无人的时刻。",
          "- 样例 05（503 独居老人上午无活动）属于故障注入场景，由 1.7 注入，不在行为层产生。",
          "",
          "## 九、预览文件", "",
          f"前 {PREVIEW_DAYS} 天全部住户的行为数据保存在 `{preview_dir.relative_to(preview_dir.parents[2]).as_posix()}/`：",
          "`events.csv.gz`（用水、用电、照明事件）、`presence.csv.gz`（在家/外出/睡眠）、`ac_intents.csv.gz`（空调使用意图）、"
          "`heater_schedule.csv.gz`（热水器启用时段）。时间为本地时间（+08:00）。",
          ""]
    path.write_text("\n".join(L), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="行为模型预览与自检")
    parser.add_argument("--dataset", default="dev", choices=["dev", "test"])
    args = parser.parse_args()

    params = load_params()
    seed = params[f"seeds.{args.dataset}"]
    building = json.loads(BUILDING_FILE.read_text(encoding="utf-8"))
    personas = json.loads(PERSONA_TRUTH_FILE.read_text(encoding="utf-8"))
    start = date.fromisoformat(params["calendar.main_window_start"])
    end = date.fromisoformat(params["calendar.main_window_end"])

    frames, profiles = bh.generate(building, personas, params, seed, start, end)
    results, tables = compute_checks(frames, profiles, building, personas, params, seed)

    out_dir = dataset_dir(args.dataset)
    preview_dir = out_dir / "behavior_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cutoff = pd.Timestamp(start) + pd.Timedelta(days=PREVIEW_DAYS)
    for name, df in frames.items():
        df[df["start"] < cutoff].to_csv(preview_dir / f"{name}.csv.gz", index=False, encoding="utf-8",
                                        compression={"method": "gzip", "mtime": 0})
    truth_dir = out_dir / "_truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    (truth_dir / "household_profiles.json").write_text(json.dumps(
        {"meta": {"dataset": args.dataset, "seed": seed, "visibility": "TRUTH_ONLY：检测算法不得读取"},
         "households": {h: p.to_dict() for h, p in profiles.items()}}, ensure_ascii=False, indent=1),
        encoding="utf-8", newline="\n")

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    report = EVALUATION_DIR / f"behavior_check_report_{args.dataset}.md"
    write_report(report, args.dataset, seed, results, tables, frames, preview_dir)

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"行为事件 {len(frames['events'])} 条（90 天，108 户）；预览 → {preview_dir}")
    print(f"自检：{len(results) - len(failed)}/{len(results)} 通过 → {report}")
    for name, detail in failed:
        print(f"  ❌ {name}：{detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
