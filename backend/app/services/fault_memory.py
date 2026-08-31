"""住宅故障记忆 Service —— 查询同一设备的历史维修记录，判断是否属于重复故障，
并基于真实历史数据生成 AI 维修连续性建议.

【为什么新增这个文件（快速开发阶段2）】
    物业在工单详情页只能看到「当前这张工单」，看不到「这台设备以前修过什么、
    上次是怎么修的、换过什么配件」。这导致维修师傅到现场前无法提前预判，
    住户也会觉得物业「怎么老修不好同一个地方」。
    本模块回答的问题：当前工单关联的设备，在过去 180 天内修过几次、结果如何。

【快速开发阶段3 新增内容】
    - 在「有历史维修记录」的前提下，调用项目已有的 llm.py 生成 AI 维修连续性建议；
    - AI 只是「总结 + 提检查建议」，历史事实全部由本模块的 SQL 查询提供；
    - LLM 未配置 / 超时 / 解析失败时返回 ai_suggestion=null（ai_available=false），
      历史时间线等核心内容不受影响 —— AI 是增强能力，不是单点故障。

【分层与调用关系】
    - 本文件属于 Service 层（业务逻辑层），不直接面向 HTTP；
    - 由 api/workorders.py 的路由（≈ Spring MVC Controller）调用，
      路由只负责把工单号传进来、把返回的 dict 转成 JSON 响应；
    - 只读查询数据库，不写任何表（无 INSERT / UPDATE / DELETE）。

【本模块不负责什么】
    - 不负责维修结果的数据写入（那是 complete_workorder 的事）；
    - 不做模糊匹配 / 相似度计算（device_id 为空时直接返回「无法关联」）；
    - 不修改任何现有接口和状态机；
    - AI 不负责查库、不负责判断历史关联 —— 程序负责事实，AI 只负责总结建议。

【Java / Spring Boot 类比】
    - fault_memory.py   ≈ FaultMemoryService（Service 层）
    - workorders.py 路由 ≈ Spring MVC Controller
    - 路由调用本函数    ≈ Controller 注入并调用 Service 方法
    - 本文件的 query_one/query_all ≈ Service 调用 Mapper / MyBatis 查询
    - 返回的 dict       ≈ 组装好的 VO / DTO（本模块返回「故障记忆视图对象」）
    - _generate_ai_suggestion ≈ Service 注入外部 AI 客户端（Feign/HttpClient），
      调用后把结果组装进 VO，try-catch 包裹，失败返回 null 不向上抛
"""
import json
from datetime import timedelta

from ..database import query_one, query_all, parse_json_field
# 【阶段3】用「模块引用」而不是 from .llm import xxx：
#   - 与 agent.py 一样复用项目唯一的一套 LLM 客户端（不新建第二套）；
#   - 通过 llm.is_llm_enabled() / llm.chat_json() 调用，
#     便于在测试时可控地验证「AI 不可用」与「AI 可用」两种路径
#     （Java 里类似通过接口注入，测试时替换 Mock 实现）。
from . import llm

# 关联窗口：向前回溯的天数（与需求约定一致，第一版固定 180 天）
TIME_RANGE_DAYS = 180

# COMPLETE_REPAIR 流水的 description 里是「中文键 JSON」，这里统一翻译成
# 与 workorders.py _parse_complete_description 相同的英文字段名，
# 保证前端两处展示（详情页维修结果 / 故障记忆时间线）字段一致，无需两套映射。
_COMPLETE_FIELD_MAP = {
    "实际故障": "actual_fault",
    "处理措施": "actual_action",
    "使用配件": "used_parts",
    "维修人": "repair_person",
    "结果": "result",
}


def _parse_complete_description(description) -> dict:
    """把一条 COMPLETE_REPAIR 流水的 description（中文键 JSON）解析成标准字段.

    【为什么数据存在 description 里】
        完成维修时（complete_workorder），系统把实际故障/处理措施/配件/维修人/结果
        打包成一段 JSON 字符串，写入 repair_record 的 description 列。
        这是历史约定（表结构里没有独立的「维修结果」字段），解析后才能展示。

    【解析失败时怎么兜底】
        用 parse_json_field 解析，任何异常都返回空 dict，调用方按
        「这条历史没有维修结果」处理 —— 时间线仍展示，但结果字段为 null，
        绝不让一条脏数据导致整个接口 500。

    【Java 类比】等价于把流水里的 JSON 字符串反序列化成 DTO 的
    ObjectMapper.readValue(...)，解析失败时吞掉异常返回空对象。
    """
    data = parse_json_field(description, {})  # 解析失败返回 {}，不抛异常
    if not data:
        return {}
    # 只取约定好的 5 个键；历史数据可能缺个别键，用 get 兜底为空字符串
    return {
        field: (data.get(cn_key) or "") for cn_key, field in _COMPLETE_FIELD_MAP.items()
    }


def _get_complete_results(order_db_ids: list) -> dict:
    """批量获取多张历史工单的维修结果（避免 N+1 查询）.

    【为什么批量】历史工单可能很多张，若逐张查 repair_record 就是 N+1
    查询（Java 里同样要避免循环查库）。这里一次 IN 查询取回全部流水，
    在内存里按 repair_order_id 分组。

    【同一工单多条 COMPLETE_REPAIR】只保留最后一条（id 大的覆盖小的）：
    与 workorders.py 的既有策略一致，业务上以最近一次完成记录为准。

    【返回】{ repair_order_id(int): {actual_fault, actual_action, used_parts,
            repair_person, result}, ... }
    """
    if not order_db_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(order_db_ids))  # 动态 IN 占位符
    rows = query_all(
        "SELECT repair_order_id, description FROM repair_record"
        " WHERE action_type = 'COMPLETE_REPAIR'"
        f" AND repair_order_id IN ({placeholders}) ORDER BY id ASC",
        tuple(order_db_ids),
    )
    results = {}
    for r in rows:
        data = _parse_complete_description(r["description"])
        if data:
            results[r["repair_order_id"]] = data  # 后面的覆盖前面的（id 大的胜出）
    return results


def get_fault_memory(order_no: str) -> dict | None:
    """【对外唯一入口】根据工单号返回该设备的历史维修记忆（结构化 dict）.

    【输入】order_no：工单号（repair_order.order_no，如 "WO-1302-20260824203825"）
    【输出】
        - 工单不存在：返回 None（由 Router 决定返回 404）
        - 工单存在：返回字典，核心字段：
            has_history / is_repeat_fault / history_count / history[] / ai_suggestion
    【主要步骤】定位工单 → 校验设备 → 按「当前工单时间向前180天」查历史 →
              批量解析维修结果 → 判定重复故障 → 组装返回。
    【为什么用 order_no 而不是 repair_order.id】接口统一使用系统已有的
    工单号，前端不需要额外获取自增主键 id（与现有 /workorders/{order_no} 一致）。

    【Java 类比】相当于 FaultMemoryService.getFaultMemory(String orderNo)，
    返回的 dict ≈ VO；Controller 层再决定 HTTP 状态码。
    """
    # ---- 1. 定位当前工单（只取本模块需要的字段）----
    order = query_one(
        "SELECT id, order_no, house_id, device_id, device_description,"
        "       created_at, status, original_description"
        " FROM repair_order WHERE order_no = %s",
        (order_no,),
    )
    if not order:
        return None  # 工单不存在：由 Router 抛 404，Service 不掺和 HTTP 语义

    base = {
        "order_no": order["order_no"],
        "house_id": order["house_id"],
        "device_id": order["device_id"],
        "device_name": None,          # 下面查 house_device 后填充
        "device_description": order["device_description"] or "",
        "has_history": False,
        "is_repeat_fault": False,
        "history_count": 0,
        "time_range_days": TIME_RANGE_DAYS,
        "history": [],
        "ai_suggestion": None,        # AI 连续性建议正文;无历史 / AI不可用时为 null
        "ai_available": False,        # AI 是否成功生成建议(供前端区分「无建议」和「暂不可用」)
        # 是否具备「按设备定位历史」的条件：有 device_id 即为 True，
        # device_id 为空的分支会把它覆盖为 False（见下）
        "can_identify_device": True,
        "message": None,              # 异常/不可识别时给前端的人话提示，正常为 null
    }

    # ---- 2. device_id 为空：第一版不做模糊匹配，直接返回「无法关联」----
    # 为什么直接返回而不是报错：当前工单可能还在 AI 分析早期（还没识别出设备），
    # 此时「没有历史」是正常业务状态，不应让接口 500 或让前端崩溃。
    if not order["device_id"]:
        base["can_identify_device"] = False
        base["message"] = "当前工单未关联具体设备，暂无法准确查询设备历史维修记录"
        return base

    # ---- 3. 取设备名称（house_device），前端时间线标题需要显示「哪台设备」----
    device = query_one(
        "SELECT device_name FROM house_device WHERE id = %s", (order["device_id"],)
    )
    base["device_name"] = (device["device_name"] if device else "") or ""

    # ---- 4. 计算历史时间窗口 ----
    # 为什么以「当前工单 created_at」为基准向前 180 天，而不是系统当前时间：
    #   以后翻看旧工单时，也应该按那张工单发生时的历史关系判断
    #   （例如 3 个月前看的是一张老工单，它当时只能看到更早的维修记录，
    #     不能把后来才发生的维修算进它的「历史」）。
    current_created = order["created_at"]
    # created_at 是 DATETIME 列，PyMySQL 返回 datetime 对象；防御性处理字符串
    if isinstance(current_created, str):
        from datetime import datetime
        current_created = datetime.fromisoformat(current_created)
    window_start = current_created - timedelta(days=TIME_RANGE_DAYS)

    # ---- 5. 查询同一房屋 + 同一设备的历史 COMPLETED 工单 ----
    # 为什么同时用 house_id + device_id + COMPLETED + 时间范围四个条件：
    #   - house_id：不同房屋的设备是独立的（同一型号也可能同款，但维修记录
    #     按「这一户」算，才符合住户视角）；
    #   - device_id：精确到具体这台设备（如 1302 的冷水管），是关联的核心；
    #   - status='COMPLETED'：只有真正修完的才算有效历史
    #     （AI_PROCESSING / DRAFT 等中途状态的工单不参与统计，避免虚高）；
    #   - created_at 范围：历史必须「发生在这张工单之前、且不早于 180 天」。
    # 另外排除当前工单自身（它是被查询对象，不是历史）。
    histories = query_all(
        "SELECT id, order_no, created_at, completed_at, original_description"
        " FROM repair_order"
        " WHERE house_id = %s AND device_id = %s AND id <> %s"
        "   AND status = 'COMPLETED'"
        "   AND created_at >= %s AND created_at <= %s"
        " ORDER BY created_at ASC",  # 时间正序，时间线自然从小到大
        (order["house_id"], order["device_id"], order["id"], window_start,
         current_created),
    )
    if not histories:
        return base  # 无历史：has_history=False / is_repeat_fault=False，正常返回

    # ---- 6. 批量解析这些历史工单的维修结果（一次 IN 查询，避免 N+1）----
    results = _get_complete_results([h["id"] for h in histories])

    # ---- 7. 组装历史时间线 ----
    # 每条历史 = 工单基本信息 + 维修结果；历史数据缺维修结果（脏数据/旧数据）
    # 时，结果字段为 null/空，不虚构内容。
    history_list = []
    for h in histories:
        res = results.get(h["id"], {})
        history_list.append({
            "order_no": h["order_no"],
            "created_at": str(h["created_at"]) if h["created_at"] else None,
            "completed_at": str(h["completed_at"]) if h["completed_at"] else None,
            "original_description": h["original_description"] or "",
            # 以下 5 个字段来自 COMPLETE_REPAIR JSON；缺失时为 ""
            "actual_fault": res.get("actual_fault", ""),
            "actual_action": res.get("actual_action", ""),
            "used_parts": res.get("used_parts", ""),
            "repair_person": res.get("repair_person", ""),
            "result": res.get("result", ""),
        })
    base["history"] = history_list
    base["history_count"] = len(history_list)

    # ---- 8. 重复故障判定（第一版纯计数，不做相似度/Embedding/RAG）----
    # 规则：0 条 → 无历史；1 条 → 有历史但不算重复；>=2 条 → 重复故障。
    # 为什么 2 条才算「重复」：同设备第二次维修通常是同一故障复发，
    # 值得给物业/住户预警；只修过一次则属正常维护，不应过度打扰。
    base["has_history"] = True
    base["is_repeat_fault"] = len(history_list) >= 2

    # ---- 9. AI 维修连续性分析（仅在「确认有历史」之后调用）----
    # 为什么放在这里：没有历史就没有可总结的事实，调用 LLM 只会浪费 Token；
    # 失败时 _generate_ai_suggestion 返回 ai_available=False / ai_suggestion=None，
    # 历史时间线与重复故障判定已在上方组装完成，不受影响。
    ai = _generate_ai_suggestion(order, history_list)
    base["ai_available"] = ai["ai_available"]
    base["ai_suggestion"] = ai["ai_suggestion"]
    return base


def _generate_ai_suggestion(order: dict, history_list: list) -> dict:
    """基于「程序已查出的真实历史事实」调用 LLM 生成维修连续性建议。

    【为什么只在有历史时才调用（需求第13条）】
        - 没有历史时，AI 没有可总结的事实，调用只会空耗 Token；
        - device_id 为空的分支在 get_fault_memory 里更早 return，到不了这里。
        所以本函数只会在 has_history=True 的路径被调用 —— 双重避免无意义消耗。

    【输入事实来自哪里】
        全部来自本模块 SQL 已经查出的真实数据（不允许 AI 查库）：
        - 当前工单：device_name / device_description / original_description
        - 每条历史：created_at / original_description / actual_fault /
          actual_action / used_parts / repair_person / result
        程序负责事实；AI 只负责「总结 + 提辅助性检查建议」，
        因此 AI 无法虚构历史次数/故障/维修人员/材料/结果。

    【LLM 负责什么 / 不负责什么】
        - 负责：总结历史发生过什么、此前怎么修的、提示本次可重点检查什么；
        - 不负责：最终诊断、强制维修指令、虚构任何事实。
        所以 prompt 里明确要求「最终故障原因以维修人员现场检查结果为准」。

    【为什么失败不能影响主业务（需求第14条）】
        LLM 是外部依赖（未配置/超时/限流/返回坏 JSON 都可能），
        try-except 捕获所有异常后返回 ai_available=False + ai_suggestion=None，
        上层照常返回历史时间线 —— AI 是增强能力，不是单点故障。

    【Java / Spring Boot 类比】
        ≈ Service 层调用外部 AI 客户端（Feign / HttpClient）：
            messages ≈ 请求 DTO（这里用 dict 直接构造）；
            返回值   ≈ 响应 DTO；
            try-catch 包裹调用，失败打日志后返回 null，不让 RemoteException
            把整个 Controller 接口打挂。本项目为了控制依赖，不打日志，
            仅通过 ai_available=False 向上层表达「AI 暂不可用」。
    """
    # ---- 1. system prompt：给 AI 立「人设与红线」----
    # 为什么必须写清楚：LLM 没有「自觉」，只有在 prompt 里明确禁止，
    # 它才不会编造历史维修次数/故障/人员/材料，也不会越权给最终诊断。
    system_prompt = (
        "你是住宅物业「维修连续性分析助手」。"
        "你只能基于用户提供的历史维修记录做总结与辅助性检查建议；"
        "禁止编造历史维修次数、故障内容、维修人员、使用材料或维修结果；"
        "禁止给出最终故障诊断结论或强制维修指令。"
    )

    # ---- 2. user prompt：当前工单 + 历史事实（程序负责事实，AI 不查库）----
    # 结构：先给「当前工单」上下文，再逐条列出历史维修记录，
    # 最后要求按固定 JSON 字段输出（chat_json 需要 JSON 才能解析）。
    history_lines = []
    for i, h in enumerate(history_list, start=1):
        history_lines.append(
            f"{i}. 维修时间:{h['created_at']} 工单号:{h['order_no']}\n"
            f"   原始报修:{h['original_description'] or '无'}\n"
            f"   实际故障:{h['actual_fault'] or '无'}\n"
            f"   处理措施:{h['actual_action'] or '无'}\n"
            f"   使用配件:{h['used_parts'] or '无'}\n"
            f"   维修人员:{h['repair_person'] or '无'}\n"
            f"   维修结果:{h['result'] or '无'}"
        )
    user_prompt = (
        f"【当前工单】设备:{order.get('device_name') or order.get('device_description') or '未知'}\n"
        f"设备描述:{order.get('device_description') or '无'}\n"
        f"本次报修描述:{order.get('original_description') or '无'}\n\n"
        f"【该设备近{TIME_RANGE_DAYS}天历史维修记录】\n"
        + "\n".join(history_lines)
        + "\n\n请输出一段100~200字的『AI维修连续性建议』JSON，"
          "格式:{\"suggestion\": \"建议正文\"}。要求:"
          "1) 总结该设备历史上发生过什么、此前采取过哪些维修措施；"
          "2) 根据历史连续性，提示本次维修可以重点检查什么（辅助性建议）；"
          "3) 明确最终故障原因仍以维修人员现场检查结果为准。"
    )

    # ---- 3. 调用 LLM（复用项目唯一一套客户端，不新建第二套）----
    # is_llm_enabled() 未配置时 chat_json 内部会抛 RuntimeError，
    # 与超时/坏 JSON 一样被统一捕获，走「暂不可用」兜底。
    try:
        resp = llm.chat_json([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        suggestion = (resp.get("suggestion") or "").strip()
        if not suggestion:
            raise ValueError("LLM 未返回 suggestion 字段")
        return {"ai_available": True, "ai_suggestion": suggestion}
    except Exception:
        # 任何失败（未配置/超时/限流/坏JSON/缺字段）统一兜底：
        # 历史时间线已在上层组装好，这里只表达「AI 暂不可用」。
        return {"ai_available": False, "ai_suggestion": None}
