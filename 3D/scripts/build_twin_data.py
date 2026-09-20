"""导出 3D 数字孪生所需数据到 backend/app/data/twin/。

输入（只读）：
  data/processed/sim_config/sim_building.json        楼栋拓扑与扩展档案（公开部分）
  data/processed/samples/supply_blockage_1302/fault/  检测算法产出的样例事件、决策、诊断
  data/processed/bailian_kit/events + expected/       契约样例事件与参考决策

输出（放在后端，不放前端 public：含全部住户档案，由 /api/twin/* 按登录账号裁剪后下发）：
  backend/app/data/twin/building.json      精简后的楼栋拓扑（去掉模拟器内部参数名）
  backend/app/data/twin/demo_events.json   演示事件：来源分为 DETECTION_SAMPLE / CONTRACT_SAMPLE / DEMO_SCRIPT

演示样例事件（DEMO_SCRIPT）为人工构造，用于覆盖全部 13 类 P0 事件的定位演示，
不是检测算法的输出；导出时校验其中引用的编码都存在于楼栋拓扑中。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"
OUT = ROOT / "backend" / "app" / "data" / "twin"

HOUSE_KEEP = [
    "house_id", "floor", "position", "layout_id", "layout", "area_m2", "batch_id", "mic_module_id",
    "production_date", "delivery_date", "in_archive", "registered_residents", "care_registered",
    "supply_zone", "has_prv", "entry_static_pressure_mpa", "drain_stack", "phase", "heater_volume_l",
    "pipeline_layout", "electric_meter",
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def slim_building(src: dict) -> dict:
    houses = []
    for h in src["houses"]:
        item = {k: h.get(k) for k in HOUSE_KEEP}
        item["rooms"] = h["rooms"]
        item["supply"] = [
            {k: s[k] for k in ("segment_code", "name", "kind", "parents", "side", "area", "fixture")}
            for s in h["supply_network"]
        ]
        item["drain"] = [
            {k: s[k] for k in ("segment_code", "name", "kind", "downstream", "receives", "area")}
            for s in h["drain_network"]
        ]
        item["circuits"] = [
            {k: c[k] for k in ("circuit_code", "name", "rating_a", "rcd_trip_ma", "rooms")}
            for c in h["circuits"]
        ]
        item["sensors"] = h["sensors"]
        item["devices"] = [
            {k: d[k] for k in ("device_code", "name", "role", "category", "spec", "location",
                               "install_date", "manufacturer", "in_archive", "segment_code", "circuit_code")}
            for d in h["devices"]
        ]
        houses.append(item)
    return {
        "meta": {**src["meta"], "exported_by": "3D/scripts/build_twin_data.py"},
        "building": src["building"],
        "batches": src["batches"],
        "supply_zones": src["supply_zones"],
        "stacks": [{"stack_id": s["stack_id"], "position": s["position"], "houses": s["houses"]} for s in src["stacks"]],
        "building_points": src["building_points"],
        "layouts": src["layouts"],
        "houses": houses,
    }


# ---------------------------------------------------------------------------
# 演示样例事件（人工构造，覆盖其余 P0 类型）
# ---------------------------------------------------------------------------
def _ctx(h: dict, **extra) -> dict:
    return {"building": "1栋", "unit": "1单元", "floor": f"{h['floor']}层", "layout": h["layout"],
            "in_archive": h["in_archive"], **extra}


def _notice(audience, houses, title, content, steps=(), repair=False):
    return {"audience": audience, "house_ids": list(houses), "title": title, "content": content,
            "self_check_steps": list(steps), "show_repair_button": repair}


def _order(mode, fault_type, trade, houses, location, summary, materials, safety, device=None, recheck=None):
    return {"create_mode": mode, "recheck_after_days": recheck, "fault_type": fault_type, "suggested_trade": trade,
            "house_ids": list(houses), "location": location, "device_code": device, "ai_summary": summary,
            "materials": list(materials), "worker_safety_notice": list(safety)}


def _decision(event, priority, summary, notices, orders, controls=(), escalation=None):
    return {"schema_version": "2.0", "event_id": event["event_id"], "actionable": True, "priority": priority,
            "fault_summary": summary, "notices": notices, "workorders": orders,
            "control_suggestions": list(controls), "escalation": escalation, "knowledge_refs": []}


def demo_script_events(houses: dict) -> list[dict]:
    H = houses
    out = []

    def ev(event_id, house, domain, etype, severity, detected, candidates, evidence, text,
           related=(), controls=(), scope="HOUSE", ctx_extra=None):
        h = H[house] if house else None
        return {
            "schema_version": "2.0", "event_id": event_id, "scope": scope, "house_id": house,
            "related_houses": list(related), "batch_id": h["batch_id"] if h else None, "domain": domain,
            "event_type": etype, "severity": severity, "detected_at": detected,
            "location_candidates": candidates, "evidence": evidence, "evidence_text": text,
            "control_actions_taken": list(controls),
            "archive_context": _ctx(h, **(ctx_extra or {})) if h else None, "data_source": "SIMULATED",
        }

    def cand(code, name, conf, device=None, in_archive=False):
        return {"segment_code": code, "segment_name": name, "device_code": device, "in_archive": in_archive,
                "confidence": conf}

    # 1106 卫生间地漏堵塞
    e = ev("EVT-20260719-1106-0021", "1106", "WATER", "DRAIN_BLOCKAGE", "MEDIUM", "2026-07-19T21:14:00+08:00",
           [cand("WD-1106-B-FD", "卫生间-地漏", 0.78), cand("WD-1106-B-BR", "卫生间-排水横支管", 0.15)],
           {"metric": "tau_s", "baseline": 6.2, "recent": 19.5, "change_ratio": 2.15, "duration_days": 4,
            "other_drains_in_room": "NORMAL", "standing_water": False},
           "淋浴后卫生间地漏的退水时间从约6秒变为约20秒，持续4天；同卫生间洗脸盆排水正常，判断为地漏滤网堵塞")
    out.append((e, _decision(e, "NORMAL", "1106卫生间地漏堵塞（可能性约78%）",
        [_notice("RESIDENT", ["1106"], "卫生间地漏排水变慢",
                 "最近4天，您家淋浴后卫生间地漏退水明显变慢，洗脸盆排水正常，大概率是地漏滤网被头发杂物堵住。可以先自己清理一下地漏滤网，清理后若仍然很慢，点击报修即可。",
                 ["取出地漏滤网盖", "清理头发和杂物", "冲水观察退水是否变快"], True)],
        [_order("DEFERRED", "给排水故障", "水电维修", ["1106"], "卫生间-地漏",
                "1106卫生间地漏退水时间常数由6.2s升至19.5s，持续4天，同房间其它排水点正常。首选地漏滤网堵塞(0.78)，次选卫生间横支管(0.15)。清理地漏，必要时疏通横支管。",
                ["地漏疏通器", "新地漏芯", "手套"], ["作业区域地面湿滑，注意防滑"], recheck=3)])))

    # ST04 立管堵塞（9层与8层之间）
    related = ["904", "1004", "1104", "1204"]
    e = ev("EVT-20260728-ST04-0003", None, "WATER", "STACK_BLOCKAGE", "HIGH", "2026-07-28T20:40:00+08:00",
           [cand("ST04-F8-F9", "04号排水立管 8–9层段", 0.71), cand("ST04-F7-F8", "04号排水立管 7–8层段", 0.18)],
           {"trigger_house": "904", "backflow_correlation": 0.83, "upper_drain_events": 27,
            "lowest_normal_floor": 8, "affected_floors": [9, 10, 11, 12], "standing_water_house": "904"},
           "904卫生间地漏在本户未用水时水位多次上升，与10–12层同立管住户排水时间高度相关(0.83)；8层以下正常，判断04号立管在8–9层之间堵塞",
           related=related, scope="STACK")
    e["batch_id"] = "B"
    e["archive_context"] = {"building": "1栋", "unit": "1单元", "stack_id": "ST04", "in_archive": True}
    out.append((e, _decision(e, "HIGH", "04号排水立管8–9层段堵塞（可能性约71%）",
        [_notice("RESIDENT", ["904"], "卫生间地漏可能返水，请暂缓用水",
                 "楼上排水时，您家卫生间地漏出现返水迹象，原因是公共排水立管堵塞，不是您家的问题。物业已安排疏通，疏通完成前请尽量少用卫生间排水，地漏附近不要放置电器。",
                 ["暂缓淋浴和洗衣排水", "地漏旁不要放置电器"], False),
         _notice("NEIGHBOR", ["1004", "1104", "1204"], "公共排水立管疏通中，请减少排水",
                 "04号公共排水立管在8–9层之间堵塞，疏通完成前请减少淋浴、洗衣等大量排水，避免楼下住户返水。",
                 ["疏通期间减少大量排水"], False),
         _notice("PROPERTY", ["904"], "04号立管8–9层段堵塞",
                 "904地漏返水与10–12层排水高度相关，8层以下正常，判断04号立管8–9层段堵塞。已生成公共部位疏通工单，请通知同立管住户。", [], False)],
        [_order("IMMEDIATE", "给排水故障", "水电维修", ["904"], "公共排水立管ST04 8–9层段",
                "904地漏在未用水时多次返水，与上层排水时间相关0.83，8层及以下正常。首选ST04 8–9层段堵塞(0.71)。从9层检查口进入疏通，完成后请10–12层配合放水验证。",
                ["电动管道疏通机", "检查口密封垫", "防水布"],
                ["立管疏通时上层住户必须暂停排水，派专人通知", "打开检查口前做好防污水外溢措施", "疏通机为电动设备，远离积水区域接电"])])))

    # 902 马桶暗漏（B 批次）
    e = ev("EVT-20260712-902-0014", "902", "WATER", "HIDDEN_LEAK", "MEDIUM", "2026-07-12T06:00:00+08:00",
           [cand("WS-902-B-WC", "卫生间-马桶进水阀", 0.84),cand("WS-902-B-AVT", "卫生间-马桶角阀", 0.09)],
           {"mnf_lpm": 0.42, "nights": 5, "branch": "卫生间冷水支路", "est_daily_loss_l": 380, "periodic_refill": True},
           "连续5晚凌晨2–5点卫生间冷水支路有0.42升/分钟的持续小流量，并伴随周期性补水，判断为马桶进水阀关闭不严",
           ctx_extra={"device_name": "马桶", "batch_lot": "FV-2512-B"})
    out.append((e, _decision(e, "NORMAL", "902马桶进水阀内漏（可能性约84%）",
        [_notice("RESIDENT", ["902"], "马桶可能在悄悄漏水",
                 "最近5个晚上，您家马桶在没人使用时仍在断断续续进水，估计每天浪费约380升水，大概率是马桶水箱里的进水阀关不严。可以先把马桶角阀关小观察，点击报修可安排上门更换。",
                 ["打开水箱盖听是否有持续进水声", "暂时把马桶角阀关小"], True)],
        [_order("DEFERRED", "给排水故障", "水电维修", ["902"], "卫生间-马桶进水阀",
                "902卫生间冷水支路夜间最小流量0.42L/min，连续5晚，伴随周期性补水，估计日漏水380L。首选马桶进水阀内漏(0.84)，该户属B批次，进水阀批号FV-2512-B。更换进水阀。",
                ["马桶进水阀", "密封垫"], ["更换前关闭马桶角阀并放空水箱"], recheck=2)])))

    # 1605 热水器漏水 → 1505 天花渗水
    e = ev("EVT-20260802-1605-0031", "1605", "JOINT", "WATER_INTRUSION", "HIGH", "2026-08-02T13:22:00+08:00",
           [cand("WS-1605-WH", "卫生间-电热水器", 0.69), cand("WS-1605-B-H", "卫生间-热水支路", 0.22)],
           {"water_sensor": "TRIGGERED:SN-1605-WH-WL01", "heater_branch_flow_lpm": 0.9, "occupancy": "ABSENT",
            "downstairs_report": "1505 卫生间吊顶水浸传感器同时报警"},
           "家中无人时热水器下方水浸传感器报警，热水支路有0.9升/分钟持续流量，楼下1505卫生间吊顶同时报警；已自动关闭入户总阀并断开热水器回路",
           related=["1505"],
           controls=[{"action": "CLOSE_MAIN_VALVE", "target": "WS-1605-IN-MV", "executed_at": "2026-08-02T13:22:03+08:00", "result": "SUCCESS"},
                     {"action": "TRIP_CIRCUIT", "target": "CB-1605-WH", "executed_at": "2026-08-02T13:22:04+08:00", "result": "SUCCESS"}],
           ctx_extra={"device_name": "电热水器"})
    out.append((e, _decision(e, "HIGH", "1605热水器漏水并渗到1505（可能性约69%），已关阀断电",
        [_notice("RESIDENT", ["1605"], "卫生间热水器漏水，已自动关水断电",
                 "您家卫生间热水器下方检测到积水，楼下也有渗水，系统已自动关闭入户总阀并断开热水器电源。请不要自行开阀合闸，维修师傅会尽快联系您。",
                 ["不要自行打开总阀", "不要触碰热水器及周边插座"], False),
         _notice("NEIGHBOR", ["1505"], "楼上漏水已处理，请查看卫生间吊顶",
                 "楼上住户热水器漏水，水阀和电源已关闭。请查看卫生间吊顶是否滴水，暂停使用卫生间照明和排风扇，如有积水请点击报修。",
                 ["查看卫生间吊顶是否滴水", "暂停使用卫生间照明和排风扇"], True)],
        [_order("IMMEDIATE", "给排水故障", "水电维修", ["1605", "1505"], "卫生间-电热水器",
                "1605热水器下方水浸报警，热水支路0.9L/min持续流量，1505吊顶同时报警，总阀已关、热水器回路已分闸。首选热水器进出水接口或泄压阀漏水(0.69)。检查接口与泄压阀，处理后检查1505吊顶受潮情况。",
                ["热水器进出水软管", "泄压阀", "生料带", "吸水毛巾"],
                ["热水器回路已分闸，作业前再次验电", "水浸区域有插座，确认卫生间插座回路也已断开", "热水器内可能仍有热水，泄压放水时防烫伤"])])))

    # 706 卫生间插座回路漏电劣化
    e = ev("EVT-20260725-706-0017", "706", "POWER", "LEAKAGE_CURRENT", "HIGH", "2026-07-25T08:10:00+08:00",
           [cand("CB-706-BT", "卫生间插座回路", 0.8)],
           {"circuit_code": "CB-706-BT", "residual_ma_baseline": 2.1, "residual_ma_recent": 21.4, "rcd_trip_ma": 30,
            "trend_days": 9, "humidity_related": True},
           "卫生间插座回路剩余电流9天内从2.1毫安升到21.4毫安，淋浴后明显升高，已接近30毫安动作值，判断为回路绝缘受潮劣化",
           ctx_extra={"device_name": "卫生间插座回路"})
    out.append((e, _decision(e, "HIGH", "706卫生间插座回路绝缘劣化，漏电流接近动作值",
        [_notice("RESIDENT", ["706"], "卫生间插座漏电风险提醒",
                 "您家卫生间插座这一路的漏电电流近期明显升高，淋浴后更明显，存在触电隐患。请暂停在卫生间使用吹风机等电器，电工师傅会上门检查。",
                 ["暂停使用卫生间插座", "保持卫生间通风干燥"], False)],
        [_order("IMMEDIATE", "电气故障", "电工维修", ["706"], "卫生间插座回路",
                "706卫生间插座回路(CB-706-BT)剩余电流由2.1mA升至21.4mA，9天持续上升，与淋浴湿度相关，接近30mA动作值。首选插座或接线盒受潮导致绝缘下降(0.8)。逐个断开插座测绝缘电阻，更换受潮插座或防水盒。",
                ["防溅水插座", "防水盒", "绝缘电阻表"],
                ["作业前验电，断开卫生间插座回路并挂牌上锁", "卫生间地面潮湿，穿绝缘鞋", "测绝缘电阻前确认回路无负载"])])))

    # 1501 客厅空调能效衰减
    e = ev("EVT-20260810-1501-0026", "1501", "POWER", "AC_EFFICIENCY_DROP", "LOW", "2026-08-10T15:00:00+08:00",
           [cand("CB-1501-AC2", "客厅空调", 0.66)],
           {"circuit_code": "CB-1501-AC2", "cop_baseline": 3.6, "cop_recent": 2.7, "change_ratio": -0.25,
            "trend_days": 20, "likely_cause": "滤网脏堵或缺氟"},
           "同样室外温度下客厅空调耗电上升、降温变慢，估算能效比从3.6降到2.7，20天内逐渐变差",
           ctx_extra={"device_name": "客厅空调"})
    out.append((e, _decision(e, "LOW", "1501客厅空调能效下降25%",
        [_notice("RESIDENT", ["1501"], "客厅空调变得费电了",
                 "和刚入住时相比，您家客厅空调在同样天气下耗电多了约三成、降温也慢了，常见原因是滤网脏了。可以先清洗滤网，若仍无改善可预约空调师傅检查是否缺氟。",
                 ["断电后取下室内机滤网", "用清水冲洗晾干后装回"], True)],
        [_order("DEFERRED", "空调故障", "空调维修", ["1501"], "客厅空调",
                "1501客厅空调(CB-1501-AC2)估算COP由3.6降至2.7，20天渐变。首选滤网脏堵，其次缺氟。清洗滤网与换热器，检测压力，必要时补氟。",
                ["滤网清洁剂", "压力表", "冷媒"], ["登高清洗室内机使用稳固梯子", "作业前断开空调回路"], recheck=7)])))

    # 1203 热水器结垢
    e = ev("EVT-20260805-1203-0024", "1203", "JOINT", "WATER_HEATER_SCALING", "LOW", "2026-08-05T22:30:00+08:00",
           [cand("WS-1203-WH", "卫生间-电热水器", 0.73), cand("WS-1203-WH-FLT", "卫生间-热水器进水滤网", 0.14)],
           {"efficiency_baseline": 0.93, "efficiency_recent": 0.78, "change_ratio": -0.16, "heating_time_increase": 0.21,
            "trend_days": 30},
           "按热水用量和进出水温差计算，热水器热效率30天内从93%降到78%，加热时间变长约21%，判断为加热管结垢")
    out.append((e, _decision(e, "LOW", "1203热水器加热管结垢，热效率下降",
        [_notice("RESIDENT", ["1203"], "热水器效率下降，建议除垢",
                 "您家电热水器最近烧同样多的热水需要更长时间，效率下降约15%，多半是加热管结了水垢，每月会多花一些电费。可以预约师傅上门除垢并检查镁棒。",
                 [], True)],
        [_order("DEFERRED", "给排水故障", "水电维修", ["1203"], "卫生间-电热水器",
                "1203热水器热效率由0.93降至0.78，加热时间增加21%，30天渐变。首选加热管结垢(0.73)，次选进水滤网堵塞(0.14)。放水除垢、更换镁棒、清洗进水滤网。",
                ["镁棒", "除垢剂", "密封圈"], ["作业前断开热水器回路", "放水前确认水温已降低，防止烫伤"], recheck=14)])))

    # 304 智能水表离线
    e = ev("EVT-20260820-304-0008", "304", "WATER", "METER_OFFLINE", "LOW", "2026-08-20T10:00:00+08:00",
           [cand("WS-304-IN-MT", "入户-智能水表", 0.9)],
           {"sensor_code": "SN-304-IN-FL01", "last_seen": "2026-08-19T03:12:00+08:00", "offline_hours": 30.8},
           "304入户智能水表自8月19日03:12起无数据上报，已离线约31小时")
    out.append((e, _decision(e, "LOW", "304入户智能水表离线",
        [_notice("PROPERTY", ["304"], "304智能水表离线", "304入户水表离线约31小时，暗漏、爆管检测对该户暂时失效，请安排运维检查通信模块。", [], False)],
        [_order("IMMEDIATE", "其他故障", "综合维修", ["304"], "入户管井-智能水表",
                "304入户智能水表(SN-304-IN-FL01)自08-19 03:12起离线30.8小时。检查通信模块供电与信号，必要时更换模块。",
                ["水表通信模块", "备用电池"], ["管井内作业注意照明，勿误碰其它住户阀门"])])))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = load(DATA / "sim_config" / "sim_building.json")
    building = slim_building(src)
    houses = {h["house_id"]: h for h in building["houses"]}
    codes = set()
    for h in building["houses"]:
        codes.update(s["segment_code"] for s in h["supply"])
        codes.update(s["segment_code"] for s in h["drain"])
        codes.update(c["circuit_code"] for c in h["circuits"])
        codes.update(s["sensor_code"] for s in h["sensors"])
    for s in src["stacks"]:
        codes.update(s["segments"])

    events = []
    # 检测样例
    det_dir = DATA / "samples" / "supply_blockage_1302" / "fault"
    if (det_dir / "detection.json").exists():
        det = load(det_dir / "detection.json")
        events.append({"origin": "DETECTION_SAMPLE", "source_ref": "data/processed/samples/supply_blockage_1302/fault",
                       "status": "NOTIFIED", "event": det["event"], "decision": load(det_dir / "decision.json"),
                       "trend": {"daily": det["diagnostics"].get("daily", []), "threshold": -0.3}})
    # 契约样例
    kit = DATA / "bailian_kit"
    status_map = {"02": "WORKORDER_CREATED", "03": "WORKORDER_CREATED", "04": "WORKORDER_CREATED", "05": "ESCALATED"}
    for f in sorted((kit / "events").glob("*.json")):
        if f.name.startswith("01_"):
            continue  # 1302 花洒已由检测样例覆盖
        exp = kit / "expected" / f.name.replace(".json", ".expected.json")
        events.append({"origin": "CONTRACT_SAMPLE", "source_ref": f"data/processed/bailian_kit/events/{f.name}",
                       "status": status_map.get(f.name[:2], "NOTIFIED"), "event": load(f),
                       "decision": load(exp) if exp.exists() else None})
    # 演示样例
    script_status = {"DRAIN_BLOCKAGE": "NOTIFIED", "STACK_BLOCKAGE": "WORKORDER_CREATED", "HIDDEN_LEAK": "NOTIFIED",
                     "WATER_INTRUSION": "WORKORDER_CREATED", "LEAKAGE_CURRENT": "WORKORDER_CREATED",
                     "AC_EFFICIENCY_DROP": "NOTIFIED", "WATER_HEATER_SCALING": "NOTIFIED", "METER_OFFLINE": "WORKORDER_CREATED"}
    for e, d in demo_script_events(houses):
        events.append({"origin": "DEMO_SCRIPT", "source_ref": "3D/scripts/build_twin_data.py", "status": script_status[e["event_type"]],
                       "event": e, "decision": d})

    # 编码校验
    missing = []
    for item in events:
        e = item["event"]
        for c in e.get("location_candidates") or []:
            code = c["segment_code"]
            base = code.rsplit("-", 1)[0] if code.endswith(("-OUT", "-IN")) else code
            if base not in codes:
                missing.append((e["event_id"], code))
        for hid in ([e["house_id"]] if e.get("house_id") else []) + list(e.get("related_houses") or []):
            if hid not in houses:
                missing.append((e["event_id"], hid))
    if missing:
        print("编码不存在：", missing)
        return 1

    # 演示工单（维修人员视角使用）
    repairers = {"水电维修": "王工", "电工维修": "李工", "空调维修": "张工", "综合维修": "张工"}
    orders = []
    seq = 1
    for item in events:
        d = item["decision"] or {}
        for wo in d.get("workorders") or []:
            immediate = wo["create_mode"] == "IMMEDIATE"
            if not immediate:
                continue
            house = (wo.get("house_ids") or [item["event"].get("house_id")])[0]
            orders.append({
                "order_no": f"WO-DEMO-{seq:03d}", "event_id": item["event"]["event_id"], "house_id": house,
                "status": "ASSIGNED" if seq % 2 else "PROCESSING", "repairer": repairers.get(wo["suggested_trade"], "王工"),
                "priority": d.get("priority"), "fault_type": wo["fault_type"], "trade": wo["suggested_trade"],
                "location": wo["location"], "materials": wo["materials"], "safety": wo["worker_safety_notice"],
                "summary": wo["ai_summary"],
            })
            seq += 1

    (OUT / "building.json").write_text(json.dumps(building, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "demo_events.json").write_text(json.dumps(
        {"generated_by": "3D/scripts/build_twin_data.py", "data_source": "SIMULATED", "events": events, "work_orders": orders},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"building.json：{len(building['houses'])} 户；demo_events.json：{len(events)} 个事件、{len(orders)} 张演示工单")
    print("事件类型：", sorted({i['event']['event_type'] for i in events}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
