"""规则引擎：契约① 异常事件 → 契约② 事件决策（住户提醒、工单草稿、优先级）。

本模块替代百炼应用①，逐条落实 ``data/processed/contracts/README.md`` 第五节的决策规则，
输出确定、可单元测试。后续接入百炼后，本模块作为回退路径继续保留，落库时用
``generated_by`` 区分（百炼）/（规则）。

当前实现的事件类型：``SUPPLY_BLOCKAGE``、``HIDDEN_LEAK``、``PIPE_BURST``、``LEAKAGE_CURRENT``、
``VOLTAGE_ABNORMAL``。其它类型抛出 ``UnsupportedEventType``，由调用方决定跳过或提示，不会静默生成不合规的决策。
"""
from __future__ import annotations

GENERATED_BY = "RULE_ENGINE"
SCHEMA_VERSION = "2.0"

# 户内堵塞类事件：先提醒住户自检，住户点"一键报修"或复查仍未恢复时再建单
DEFAULT_RECHECK_DAYS = 3


class UnsupportedEventType(ValueError):
    """规则引擎尚未覆盖的事件类型。"""


# 按定位首选部位选择模板。key 为给水拓扑编码的部件后缀（WS-{户}-{区域}-{部件}）。
SUPPLY_TEMPLATES = {
    "SH": {
        "cause": "花洒头水垢堵塞",
        "resident_title": "卫生间花洒出水变小",
        "resident_body": "最近{window}天，您家卫生间花洒的出水量比刚入住时少了约{pct_cn}，{context}大概率是花洒头里积了水垢（可能性约{conf}%）。可以先按下面的方法自行清理；如果您近期自己调小过阀门，请忽略本提醒。",
        "self_check": ["拧下花洒头", "用白醋浸泡约2小时后用清水冲洗", "装回后打开冷热水试一下出水"],
        "materials": ["花洒头", "淋浴混水阀芯", "生料带"],
        "safety": ["拆卸前关闭卫生间冷热水支路阀门", "注意热水烫伤，确认热水已放凉"],
        "advice": "建议先除垢，无效再更换阀芯",
        "knowledge": ["给排水维修手册-卫生间花洒出水异常"],
    },
    "MV": {
        "cause": "淋浴混水阀芯堵塞",
        "resident_title": "卫生间淋浴出水变小",
        "resident_body": "最近{window}天，您家淋浴的出水量比刚入住时少了约{pct_cn}，{context}可能是淋浴混水阀里卡了杂质（可能性约{conf}%）。阀芯需要专业工具拆装，建议点击一键报修；如果您近期自己调小过阀门，请忽略本提醒。",
        "self_check": ["确认混水阀手柄已开到最大", "单独开冷水、热水各试一次"],
        "materials": ["淋浴混水阀芯", "密封圈", "生料带"],
        "safety": ["拆卸前关闭卫生间冷热水支路阀门", "注意热水烫伤，确认热水已放凉"],
        "advice": "建议拆检混水阀芯并清理滤网",
        "knowledge": ["给排水维修手册-卫生间花洒出水异常"],
    },
    "C": {
        "cause": "冷水支路堵塞",
        "resident_title": "卫生间冷水出水变小",
        "resident_body": "最近{window}天，您家卫生间冷水出水量比刚入住时少了约{pct_cn}，{context}可能是卫生间冷水管路或角阀堵塞（可能性约{conf}%）。建议点击一键报修；如果您近期自己调小过阀门，请忽略本提醒。",
        "self_check": ["检查洗脸盆、马桶下方角阀是否完全打开"],
        "materials": ["角阀", "连接软管", "PPR管件"],
        "safety": ["作业前关闭入户总阀并泄压"],
        "advice": "建议逐个检查角阀与支路管件",
        "knowledge": [],
    },
    "H": {
        "cause": "热水支路堵塞",
        "resident_title": "卫生间热水出水变小",
        "resident_body": "最近{window}天，您家卫生间热水出水量比刚入住时少了约{pct_cn}，{context}可能是热水管路堵塞（可能性约{conf}%）。建议点击一键报修；如果您近期自己调小过阀门，请忽略本提醒。",
        "self_check": ["检查热水角阀是否完全打开"],
        "materials": ["角阀", "PPR管件"],
        "safety": ["作业前关闭热水器进水阀并泄压", "注意热水烫伤，确认热水已放凉"],
        "advice": "建议检查热水支路角阀与管件",
        "knowledge": [],
    },
    "FLT": {
        "cause": "热水器进水滤网堵塞",
        "resident_title": "热水出水变小",
        "resident_body": "最近{window}天，您家热水出水量比刚入住时少了约{pct_cn}，{context}可能是热水器进水滤网堵塞（可能性约{conf}%）。热水器需要断电后专业拆洗，建议点击一键报修。",
        "self_check": [],
        "materials": ["进水滤网", "密封圈"],
        "safety": ["拆洗前断开热水器电源", "关闭热水器进水阀并泄压", "注意热水烫伤，确认热水已放凉"],
        "advice": "建议断电后拆洗热水器进水滤网",
        "knowledge": [],
    },
}

_CN_TENTHS = {1: "一成", 2: "两成", 3: "三成", 4: "四成", 5: "一半", 6: "六成", 7: "七成", 8: "八成", 9: "九成"}


def decide(event: dict) -> dict:
    """根据事件类型分派到对应规则。"""
    handler = _HANDLERS.get(event.get("event_type"))
    if handler is None:
        raise UnsupportedEventType(f"规则引擎暂不支持事件类型 {event.get('event_type')}")
    return handler(event)


def _supply_blockage(event: dict) -> dict:
    ev = event["evidence"]
    candidates = event["location_candidates"]
    top = candidates[0]
    suffix = top["segment_code"].rsplit("-", 1)[1]
    tpl = SUPPLY_TEMPLATES.get(suffix, SUPPLY_TEMPLATES["C"])
    conf = round(top["confidence"] * 100)
    drop = -float(ev["change_ratio"])
    window = ev.get("window_days", 5)
    house = event["house_id"]

    context = []
    if ev.get("same_branch_other_fixtures") == "NORMAL":
        context.append("洗脸盆等其它用水点")
    if abs(float(ev.get("inlet_pressure_change", 0))) < 0.05:
        context.append("入户水压")
    context_text = f"{'和'.join(context)}都正常，" if context else ""
    content = tpl["resident_body"].format(
        window=window, pct_cn=_CN_TENTHS.get(max(1, min(9, round(drop * 10))), f"{round(drop * 100)}%"),
        context=context_text, conf=conf,
    )[:200]

    alternatives = "，".join(f"次选{c['segment_name']}({c['confidence']:.2f})" for c in candidates[1:])
    trend_text = "渐进恶化" if ev.get("trend") == "GRADUAL" else "近期突然变差"
    summary = (
        f"{house}{top['segment_name']}出水能力较入住初期降{round(drop * 100)}%，"
        f"{ {'BOTH': '冷热同降', 'HOT': '热水侧下降', 'COLD': '冷水侧下降'}.get(ev.get('hot_cold'), '')}，{trend_text}；"
        f"同支路其它器具{ {'NORMAL': '正常', 'ABNORMAL': '也异常', 'UNKNOWN': '数据不足'}.get(ev.get('same_branch_other_fixtures'), '')}，"
        f"入户水压变化{round(float(ev.get('inlet_pressure_change', 0)) * 100)}%。"
        f"首选{tpl['cause']}({top['confidence']:.2f})"
        f"{'，' + alternatives if alternatives else ''}。{tpl['advice']}。"
    )[:300]

    severe = event["severity"] in ("HIGH", "CRITICAL")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event["event_id"],
        "actionable": True,
        "priority": "NORMAL",
        "fault_summary": f"{house}{top['segment_name'].split('-')[0]}{tpl['cause']}（可能性约{conf}%）"[:60],
        "notices": [{
            "audience": "RESIDENT",
            "house_ids": [house],
            "title": tpl["resident_title"],
            "content": content,
            "self_check_steps": tpl["self_check"][:4],
            "show_repair_button": True,
        }],
        "workorders": [{
            "create_mode": "DEFERRED",
            "recheck_after_days": 1 if severe else DEFAULT_RECHECK_DAYS,
            "fault_type": "给排水故障",
            "suggested_trade": "水电维修",
            "house_ids": [house],
            "location": top["segment_name"][:40],
            "device_code": top["device_code"],
            "ai_summary": summary,
            "materials": tpl["materials"][:6],
            "worker_safety_notice": tpl["safety"][:5],
        }],
        "control_suggestions": [],
        "escalation": None,
        "knowledge_refs": list(tpl["knowledge"]),
    }


# ---------------------------------------------------------------------------
# 暗漏（HIDDEN_LEAK）：户内漏水，先提醒住户自检，DEFERRED 建单
# ---------------------------------------------------------------------------
WATER_PRICE_YUAN_PER_M3 = 3.5  # 示例水价，与 price_tables.yaml 一致

HIDDEN_LEAK_TEMPLATES = {
    "WC": {
        "cause": "马桶进水阀或排水阀密封不严",
        "title": "马桶可能在悄悄漏水",
        "body_where": "卫生间冷水管路",
        "self_check": ["在水箱里滴几滴食用色素，30分钟内不冲水，看马桶内壁是否出现颜色",
                       "关闭马桶角阀，观察水表是否停止走动", "留意水箱是否有持续的细小进水声"],
        "materials": ["马桶进水阀", "排水阀密封垫", "马桶角阀"],
        "safety": ["作业前关闭马桶角阀并排空水箱"],
        "knowledge": [],
    },
    "AV": {
        "cause": "角阀或连接软管接口渗漏",
        "title": "水管接口可能在渗漏",
        "body_where": "{area}冷水管路",
        "self_check": ["查看水槽或洗脸盆下方的角阀和软管接口是否有水迹", "用干纸巾擦干接口，半小时后看是否变湿"],
        "materials": ["角阀", "连接软管", "生料带"],
        "safety": ["作业前关闭对应角阀，无法关闭时关闭入户总阀"],
        "knowledge": ["给排水维修手册-厨房水槽持续漏水"],
    },
    "HS": {
        "cause": "连接软管或接口渗漏",
        "title": "水管接口可能在渗漏",
        "body_where": "{area}管路",
        "self_check": ["查看水槽下方软管和两端接口是否有水迹", "用干纸巾擦干接口，半小时后看是否变湿"],
        "materials": ["连接软管", "角阀", "生料带"],
        "safety": ["作业前关闭对应角阀，无法关闭时关闭入户总阀"],
        "knowledge": ["给排水维修手册-厨房水槽持续漏水"],
    },
    "MV": {
        "cause": "混水阀或龙头关不严",
        "title": "龙头可能在滴水",
        "body_where": "{area}冷热水管路",
        "self_check": ["关紧花洒和洗脸盆龙头后，看出水口是否仍在滴水"],
        "materials": ["混水阀芯", "密封圈"],
        "safety": ["拆卸前关闭冷热水支路阀门", "注意热水烫伤，确认热水已放凉"],
        "knowledge": ["给排水维修手册-卫生间花洒出水异常"],
    },
    "WT": {
        "cause": "洗衣机龙头关不严",
        "title": "洗衣机龙头可能关不严",
        "body_where": "阳台冷水管路",
        "self_check": ["关紧洗衣机龙头，看进水管接口是否有水迹"],
        "materials": ["洗衣机龙头", "密封圈"],
        "safety": ["作业前拔掉洗衣机电源插头"],
        "knowledge": [],
    },
    "WH": {
        "cause": "电热水器泄压阀滴水或罐体渗漏",
        "title": "热水器可能在滴漏",
        "body_where": "热水器附近",
        "self_check": ["查看热水器泄压阀出口和下方地面是否有水迹"],
        "materials": ["泄压阀", "密封圈"],
        "safety": ["作业前断开热水器电源", "关闭热水器进水阀并泄压", "注意热水烫伤，确认热水已放凉"],
        "knowledge": [],
    },
    "MAIN": {
        "cause": "户内供水管道渗漏",
        "title": "家里水管可能在渗漏",
        "body_where": "入户主管附近",
        "self_check": ["查看墙面、地面和吊顶是否有水渍或发霉"],
        "materials": ["PPR管件", "热熔工具"],
        "safety": ["作业前关闭入户总阀并泄压"],
        "knowledge": ["给排水维修手册-厨房水槽持续漏水"],
    },
}


def _leak_template(segment_code: str) -> dict:
    suffix = segment_code.rsplit("-", 1)[1]
    if suffix in ("AVB", "AVBH", "AVH", "AVT", "AV"):
        return HIDDEN_LEAK_TEMPLATES["AV"]
    if suffix in ("HS", "HSH"):
        return HIDDEN_LEAK_TEMPLATES["HS"]
    if suffix in ("MV", "BS", "FC"):
        return HIDDEN_LEAK_TEMPLATES["MV"]
    if suffix == "MAIN":
        return HIDDEN_LEAK_TEMPLATES["MAIN"]
    return HIDDEN_LEAK_TEMPLATES.get(suffix, HIDDEN_LEAK_TEMPLATES["MAIN"])


def _area_of(segment_name: str) -> str:
    return segment_name.split("-")[0]


def _hidden_leak(event: dict) -> dict:
    ev = event["evidence"]
    candidates = event["location_candidates"]
    top = candidates[0]
    tpl = _leak_template(top["segment_code"])
    conf = round(top["confidence"] * 100)
    house = event["house_id"]
    loss = int(ev["est_daily_loss_l"])
    cost = loss * 30 / 1000 * WATER_PRICE_YUAN_PER_M3
    where = tpl["body_where"].format(area=_area_of(top["segment_name"]))
    content = (f"最近{ev['consecutive_nights']}晚，您家半夜没人用水时水表也一直在走，每天约多用{loss}升水"
               f"（一个月约{cost:.0f}元），漏水出现在{where}，大概率是{tpl['cause']}（可能性约{conf}%）。"
               f"可以先按下面的方法自查；如果这几天夜里有人持续用水（如给鱼缸补水），请忽略本提醒。")[:200]
    alternatives = "，".join(f"次选{c['segment_name']}({c['confidence']:.2f})" for c in candidates[1:])
    summary = (f"{house}连续{ev['consecutive_nights']}晚凌晨总表最小流量{ev['night_min_flow_lpm']} L/min（约{loss} L/天），"
               f"持续小流量在{where}，支路之外未解释流量{ev.get('unexplained_lpm', 0)} L/min。"
               f"首选{top['segment_name']}({top['confidence']:.2f}){'，' + alternatives if alternatives else ''}。"
               f"建议先关闭该处角阀确认水表是否停转，再更换密封件。")[:300]
    severe = event["severity"] in ("HIGH", "CRITICAL")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event["event_id"],
        "actionable": True,
        "priority": "NORMAL",
        "fault_summary": f"{house}{_area_of(top['segment_name'])}疑似暗漏：{tpl['cause']}（可能性约{conf}%）"[:60],
        "notices": [{
            "audience": "RESIDENT", "house_ids": [house], "title": tpl["title"], "content": content,
            "self_check_steps": [s[:40] for s in tpl["self_check"][:4]], "show_repair_button": True,
        }],
        "workorders": [{
            "create_mode": "DEFERRED", "recheck_after_days": 1 if severe else DEFAULT_RECHECK_DAYS,
            "fault_type": "给排水故障", "suggested_trade": "水电维修", "house_ids": [house],
            "location": top["segment_name"][:40], "device_code": top["device_code"], "ai_summary": summary,
            "materials": tpl["materials"][:6], "worker_safety_notice": tpl["safety"][:5],
        }],
        "control_suggestions": [],
        "escalation": None,
        "knowledge_refs": list(tpl["knowledge"]),
    }


# ---------------------------------------------------------------------------
# 爆管（PIPE_BURST）：CRITICAL → URGENT，立即建单，住户 + 物业 + 楼下住户
# ---------------------------------------------------------------------------
def _pipe_burst(event: dict) -> dict:
    ev = event["evidence"]
    top = event["location_candidates"][0]
    house = event["house_id"]
    area = _area_of(top["segment_name"])
    when = event["detected_at"][11:16]
    valve_closed = any(a["action"] == "CLOSE_MAIN_VALVE" and a["result"] == "SUCCESS" for a in event["control_actions_taken"])
    valve_text = "系统已自动关闭入户总阀" if valve_closed else "系统关闭总阀失败，请立即手动关闭总阀"
    loss = int(ev["est_loss_l"])
    notices = [
        {
            "audience": "RESIDENT", "house_ids": [house], "title": "紧急：家中疑似水管爆裂",
            "content": (f"{when}检测到您家{area}用水量异常大（每分钟约{ev['peak_flow_lpm']:.0f}升），不像正常用水，{valve_text}，"
                        f"估计漏水约{loss}升。物业维修人员将尽快上门；确认安全前请不要自行打开总阀。")[:200],
            "self_check_steps": ["回家后先查看水槽下方软管和角阀", "地面有积水时不要触碰插座和电器"],
            "show_repair_button": False,
        },
        {
            "audience": "PROPERTY", "house_ids": [house], "title": f"{house}爆管，{'已自动关阀' if valve_closed else '关阀失败'}"[:30],
            "content": (f"{event['evidence_text']}。请立即安排维修人员上门，并联系住户；"
                        f"同时查看楼下住户是否渗水。")[:200],
            "self_check_steps": [], "show_repair_button": False,
        },
    ]
    if event["related_houses"]:
        notices.append({
            "audience": "NEIGHBOR", "house_ids": event["related_houses"], "title": "楼上住户家中发生漏水",
            "content": "楼上住户家中刚发生水管漏水，总阀已自动关闭。请留意厨房、卫生间天花板是否有渗水，如有请联系物业。",
            "self_check_steps": ["查看厨房和卫生间天花板、吊顶是否有水渍"], "show_repair_button": False,
        })
    summary = (f"{house}{area}支路流量峰值{ev['peak_flow_lpm']} L/min，超过该支路器具额定流量之和{ev['rated_max_lpm']} L/min，"
               f"判定爆管/软管脱落；{valve_text}，估计漏水{loss} L。首选{top['segment_name']}({top['confidence']:.2f})。"
               f"到场后更换软管或角阀，打压试验无渗漏后再开总阀。")[:300]
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event["event_id"],
        "actionable": True,
        "priority": "URGENT",
        "fault_summary": f"{house}{area}爆管/软管脱落，{'已自动关阀' if valve_closed else '关阀失败'}（约漏{loss}升）"[:60],
        "notices": notices,
        "workorders": [{
            "create_mode": "IMMEDIATE", "recheck_after_days": None,
            "fault_type": "给排水故障", "suggested_trade": "水电维修", "house_ids": [house],
            "location": top["segment_name"][:40], "device_code": top["device_code"], "ai_summary": summary,
            "materials": ["连接软管", "角阀", "生料带", "吸水工具"],
            "worker_safety_notice": ["进场前确认入户总阀已关闭并泄压", "地面有积水时先断开厨房插座回路电源再作业",
                                     "维修后打压试验无渗漏再开总阀"],
        }],
        "control_suggestions": [] if valve_closed else [
            {"action": "CLOSE_MAIN_VALVE", "target": event["control_actions_taken"][0]["target"] if event["control_actions_taken"] else "入户总阀",
             "reason": "自动关阀失败，需要人工或远程再次关闭"}],
        "escalation": None,
        "knowledge_refs": ["给排水维修手册-厨房水槽持续漏水", "主动运维补充-爆管与水浸处置"],
    }


# ---------------------------------------------------------------------------
# 漏电（LEAKAGE_CURRENT）：IMMEDIATE，接近动作值或已跳闸时 HIGH
# ---------------------------------------------------------------------------
ELECTRIC_SAFETY = ["作业前断开该回路断路器并用验电笔验电", "断电后挂牌警示，防止他人误合闸"]


def _leakage_current(event: dict) -> dict:
    ev = event["evidence"]
    house = event["house_id"]
    top = event["location_candidates"][0] if event["location_candidates"] else None
    cable = next((c["segment_name"] for c in event["location_candidates"] if c["device_code"] is None), None)
    circuit_label = ev.get("circuit_name") or (cable.replace("线缆", "") if cable else ev["circuit_code"])
    tripped = ev.get("pattern") == "TRIP"
    near = bool(ev.get("near_trip"))
    priority = "HIGH" if (tripped or near) else "NORMAL"
    wet_room = any(k in circuit_label for k in ("厨房", "卫生间", "热水器"))
    if tripped:
        repeat = f"，重新合上后又跳闸，共{ev['trip_count']}次" if ev.get("trip_count", 1) > 1 else ""
        title = f"{circuit_label}因漏电跳闸"
        content = (f"{event['detected_at'][5:16].replace('T', ' ')}，您家{circuit_label}因为漏电自动断电{repeat}。"
                   f"可能是插座进水或电器受潮。请先不要再合闸，拔掉这条回路上的电器插头并保持干燥，物业电工会尽快上门检查。")
        steps = ["拔掉该回路插座上的所有电器插头", "查看插座附近是否有水渍或溅水", "确认干燥前不要再次合闸"]
    else:
        title = f"{circuit_label}漏电在增大"
        content = (f"系统发现您家{circuit_label}的漏电最近几天明显变大，目前约{ev['residual_ma_recent']:.0f}毫安，"
                   f"保护开关在{ev['trip_threshold_ma']}毫安左右会自动断电。可能是插座受潮或线路老化。"
                   + ("为了安全，建议暂时不要在卫生间、厨房使用吹风机等大功率电器。" if wet_room else "为了安全，建议暂时减少使用这条回路上的电器。")
                   + "物业已安排电工上门检查。")
        steps = ["查看插座面板是否发黑、发烫或有水渍"]
    alternatives = "，".join(f"{c['segment_name']}({c['confidence']:.2f})" for c in event["location_candidates"])
    summary = (f"{house}{ev['circuit_code']}{'漏电跳闸' if tripped else '漏电流渐增'}：入住初期约{ev['residual_ma_baseline']} mA，"
               f"{'跳闸时' if tripped else '近期'}{ev['residual_ma_recent']} mA（动作值{ev['trip_threshold_ma']} mA），"
               f"已扣除湿度与负载影响。可疑部位：{alternatives}。建议逐个断开插座/电器做绝缘电阻测试。")[:300]
    safety = ELECTRIC_SAFETY + (["潮湿环境作业穿绝缘鞋、戴绝缘手套"] if wet_room else [])
    notices = [{"audience": "RESIDENT", "house_ids": [house], "title": title[:30], "content": content[:200],
                "self_check_steps": [s[:40] for s in steps], "show_repair_button": False}]
    if tripped:
        notices.append({"audience": "PROPERTY", "house_ids": [house], "title": f"{house}漏电跳闸"[:30],
                        "content": f"{event['evidence_text']}。请安排电工尽快上门，排查前不要恢复供电。"[:200],
                        "self_check_steps": [], "show_repair_button": False})
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event["event_id"],
        "actionable": True,
        "priority": priority,
        "fault_summary": f"{house}{circuit_label}{'漏电跳闸' if tripped else '漏电流持续升高'}（{ev['residual_ma_recent']:.0f} mA）"[:60],
        "notices": notices,
        "workorders": [{
            "create_mode": "IMMEDIATE", "recheck_after_days": None,
            "fault_type": "电气故障", "suggested_trade": "电工维修", "house_ids": [house],
            "location": circuit_label[:40], "device_code": top["device_code"] if top else None, "ai_summary": summary,
            "materials": ["绝缘电阻测试仪", "防水插座面板", "插座", "绝缘胶带"],
            "worker_safety_notice": safety[:5],
        }],
        "control_suggestions": [],
        "escalation": None,
        "knowledge_refs": ["电气维修手册-配电箱跳闸"],
    }


# ---------------------------------------------------------------------------
# 电压异常（VOLTAGE_ABNORMAL）：供电侧 → 楼栋工单 + 物业/同相住户；本户接线 → 户内电工工单
# ---------------------------------------------------------------------------
def _voltage_extreme_text(ev: dict, lo: float, hi: float) -> str:
    """只说越限的那一侧，避免"218–248伏之间超出范围"这种住户看不懂的表述。"""
    parts = []
    if ev["voltage_max_v"] > hi:
        parts.append(f"最高达到{ev['voltage_max_v']:.0f}伏，高于正常上限{hi:.0f}伏")
    if ev["voltage_min_v"] < lo:
        parts.append(f"最低降到{ev['voltage_min_v']:.0f}伏，低于正常下限{lo:.0f}伏")
    return "；".join(parts) or f"超出正常范围{lo:.0f}–{hi:.0f}伏"


def _voltage_abnormal(event: dict) -> dict:
    ev = event["evidence"]
    at_risk = ev["appliances_at_risk"]
    priority = "HIGH" if any(r["minutes_outside"] >= 10 for r in at_risk) else "NORMAL"
    lo, hi = ev["limits_v"]
    direction = ev.get("direction", "电压异常")
    risk_names = "、".join(r["name"] for r in at_risk[:3])
    risk_text = f"，已超出{risk_names}的允许电压" if at_risk else ""
    if ev["source_inference"] == "SUPPLY":
        phase = ev.get("phase", "")
        houses = event["related_houses"]
        where = f"1栋1单元配电室{phase}相" if ev.get("phase_scope") != "ALL_PHASES" else "1栋1单元配电室进线"
        notices = [
            {"audience": "PROPERTY", "house_ids": houses[:1] if houses else [], "title": f"楼栋{phase}相{direction}"[:30],
             "content": (f"{event['evidence_text']}。属于供电侧问题，请联系供电部门检查变压器挡位和线路，并通知受影响住户。")[:200],
             "self_check_steps": [], "show_repair_button": False},
            {"audience": "NEIGHBOR", "house_ids": houses, "title": f"近期楼栋供电{direction}",
             "content": (f"近期楼栋部分时段供电电压{_voltage_extreme_text(ev, lo, hi)}"
                         f"{risk_text}。物业已联系供电部门处理，"
                         f"期间外出时建议拔掉不用的电器插头。")[:200],
             "self_check_steps": ["外出时拔掉不用的电器插头", "发现电器异常发热或有焦味立即断电"],
             "show_repair_button": False},
        ]
        summary = (f"楼栋{phase}相{direction}：{ev['days_affected']}天内{ev['minutes_out_of_range']}分钟超出{lo}–{hi} V，"
                   f"同相邻户{ev['same_phase_abnormal_ratio']:.0%}同时越限、其它相{ev['other_phase_abnormal_ratio']:.0%}，判断为供电侧。"
                   f"请测量配电室各相电压并联系供电部门调整变压器挡位。")[:300]
        workorder_houses, location, materials = houses, where, ["钳形电流表", "电能质量记录仪"]
        summary_title = f"楼栋{phase}相{direction}，供电侧问题"
    else:
        house = event["house_id"]
        wiring = ev["source_inference"] == "HOUSE_WIRING"
        notices = [{
            "audience": "RESIDENT", "house_ids": [house], "title": "家里电压明显偏低" if "欠" in direction else f"家里{direction}",
            "content": ((f"系统发现您家用电较多时电压会降到{ev['voltage_min_v']:.0f}伏左右，低于正常的{lo:.0f}伏{risk_text}，"
                         f"而同楼层邻居电压正常。可能是家里进线或零线接头松动，接头松动会发热，存在安全隐患。"
                         f"请暂时避免同时使用热水器、电水壶、空调等大功率电器，电工将尽快上门检查。") if wiring else
                        (f"系统发现您家电压{direction}，最低{ev['voltage_min_v']:.0f}伏、最高{ev['voltage_max_v']:.0f}伏{risk_text}，"
                         f"原因尚不确定，电工将上门检测。期间请避免同时使用多个大功率电器。"))[:200],
            "self_check_steps": ["避免同时使用热水器、电水壶、空调等大功率电器", "留意配电箱附近是否有焦味或异响"],
            "show_repair_button": False,
        }]
        summary = (f"{house}{direction}：{ev['days_affected']}天内{ev['minutes_out_of_range']}分钟超出{lo}–{hi} V（最低{ev['voltage_min_v']} V），"
                   f"同相邻户{ev['same_phase_abnormal_ratio']:.0%}同时越限；等效线路电阻{ev.get('wiring_resistance_ohm')} Ω"
                   f"（入住初期{ev.get('wiring_resistance_baseline_ohm')} Ω），"
                   f"{'判断为户内进线或零线端子松动，重点检查户表箱与配电箱接线端子温升与紧固力矩。' if wiring else '原因未定，建议上门测量。'}")[:300]
        workorder_houses, location, materials = [house], "户配电箱进线及零线端子", ["接线端子", "扭力螺丝刀", "红外测温仪", "绝缘胶带"]
        summary_title = f"{house}{direction}，疑似{'进线/零线接头松动' if wiring else '户内供电异常'}"
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event["event_id"],
        "actionable": True,
        "priority": priority,
        "fault_summary": summary_title[:60],
        "notices": [n for n in notices if n["house_ids"]],
        "workorders": [{
            "create_mode": "IMMEDIATE", "recheck_after_days": None,
            "fault_type": "电气故障", "suggested_trade": "电工维修", "house_ids": workorder_houses,
            "location": location[:40], "device_code": None, "ai_summary": summary, "materials": materials,
            "worker_safety_notice": ELECTRIC_SAFETY + ["紧固端子前确认上级开关已断开并验电"],
        }],
        "control_suggestions": [],
        "escalation": None,
        "knowledge_refs": [],
    }


_HANDLERS = {
    "SUPPLY_BLOCKAGE": _supply_blockage,
    "HIDDEN_LEAK": _hidden_leak,
    "PIPE_BURST": _pipe_burst,
    "LEAKAGE_CURRENT": _leakage_current,
    "VOLTAGE_ABNORMAL": _voltage_abnormal,
}
