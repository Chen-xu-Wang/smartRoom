"""AI Agent - 智能报修助手核心逻辑.

State machine:
  START → COLLECTING_INFO → INFO_COMPLETE → QUERYING_ARCHIVE →
  SEARCHING_KB → GENERATING_ORDER → ORDER_PENDING → COMPLETE

【v2 变更】意图理解（extract_info）与工单分析（_generate_work_order）已接入
真实大模型（services/llm.py，OpenAI 兼容协议）。当大模型不可用或返回异常时，
自动 fallback 到原关键词 / 规则逻辑，保证流程不中断、前端与 A/B 契约不变。
"""
import json
from datetime import datetime

from .archive import (
    get_house_by_id,
    get_house_equipment_by_location,
    get_house_pipeline_layout,
    get_maintenance_history,
)
from .rag import (
    search_knowledge_base,
    get_repair_trade_suggestion,
    get_urgency_suggestion,
    get_possible_causes,
)
from .llm import is_llm_enabled, chat_json

# ============ Keyword Dictionaries（兜底用，大模型不可用 / 异常时启用）============

LOCATION_KEYWORDS = {
    "厨房": ["厨房", "灶台", "操作台", "水槽下"],
    "卫生间": ["卫生间", "浴室", "马桶", "淋浴"],
    "卧室": ["卧室", "主卧", "次卧", "书房"],
    "客厅": ["客厅", "起居室", "餐厅"],
    "阳台": ["阳台", "露台"],
    "入户": ["入户", "进门", "门口"],
}

DEVICE_KEYWORDS = {
    "水槽": ["水槽", "洗菜盆"],
    "水龙头": ["水龙头", "龙头", "混水阀"],
    "角阀": ["角阀"],
    "管道": ["管道", "水管", "管子", "PPR"],
    "排水": ["排水", "下水", "地漏"],
    "软管": ["软管", "连接管", "进水管"],
    "插座": ["插座", "插孔"],
    "开关": ["开关"],
    "灯具": ["灯", "灯具", "LED", "吸顶灯", "吊灯"],
    "配电箱": ["配电箱", "电箱", "空气开关"],
    "空调": ["空调", "挂机", "柜机", "室外机", "室内机"],
    "窗户": ["窗", "窗户", "推拉门", "平开窗"],
    "门": ["门", "入户门", "房门"],
    "花洒": ["花洒", "淋浴头", "喷头"],
    "马桶": ["马桶", "坐便器"],
    "墙面": ["墙面", "墙", "裂缝", "开裂"],
}

SYMPTOM_KEYWORDS = {
    "漏水": ["漏水", "渗水", "滴水", "渗漏", "积水", "滴水"],
    "排水慢": ["排水慢", "下水慢", "堵了", "堵塞", "排不出去"],
    "不通电": ["没电", "不通电", "不亮", "不来电", "断电"],
    "不制冷": ["不制冷", "不冷", "不凉", "制冷差", "不够冷"],
    "关不严": ["关不严", "关不上", "关不紧", "漏风", "有缝"],
    "异响": ["异响", "噪音", "声音", "嗡嗡", "咯吱", "振动"],
    "异味": ["异味", "臭味", "有味道", "发臭"],
    "跳闸": ["跳闸", "跳了", "断电", "推不上"],
    "裂缝": ["裂缝", "开裂", "裂纹", "龟裂"],
    "不亮": ["不亮", "坏了", "没反应"],
    "渗水": ["渗水", "渗漏", "水印", "洇水"],
    "出水异常": ["不出水", "水小", "水流小", "没水"],
    "变形": ["变形", "下垂", "歪了", "翘了"],
}

SEVERITY_KEYWORDS = {
    "持续": ["一直", "持续", "不断", "一直在", "不停"],
    "严重": ["严重", "大量", "很多", "喷", "涌"],
    "轻微": ["慢慢", "一点", "轻微", "偶尔", "有时", "小"],
    "突发": ["突然", "刚", "今天", "刚才"],
}

CONFIRM_KEYWORDS = ["确认", "没问题", "可以", "同意", "好", "提交", "对的", "正确"]
MODIFY_KEYWORDS = ["修改", "不对", "错了", "不是", "重新", "纠正"]

# ============ Info Extraction ============

def _keyword_extract(text: str, current_info: dict = None):
    """原关键词匹配抽取（兜底用）。"""
    info = dict(current_info) if current_info else {}

    for loc, keywords in LOCATION_KEYWORDS.items():
        if loc not in info.get("location", ""):
            for kw in keywords:
                if kw in text:
                    info["location"] = loc
                    break

    for device, keywords in DEVICE_KEYWORDS.items():
        if not info.get("device"):
            for kw in keywords:
                if kw in text:
                    info["device"] = device
                    break

    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if not info.get("symptom"):
            for kw in keywords:
                if kw in text:
                    info["symptom"] = symptom
                    break
        elif symptom not in info.get("symptom", ""):
            for kw in keywords:
                if kw in text:
                    info["symptom"] = info["symptom"] + ", " + symptom
                    break

    for severity, keywords in SEVERITY_KEYWORDS.items():
        if not info.get("severity"):
            for kw in keywords:
                if kw in text:
                    info["severity"] = severity
                    break

    if "今天" in text or "刚才" in text:
        info["occurrence_time"] = "今天"
    elif "昨天" in text:
        info["occurrence_time"] = "昨天"
    elif "这周" in text or "这几天" in text:
        info["occurrence_time"] = "本周"

    if "关掉" in text or "关闭" in text or "关了" in text:
        if "漏" in text or "滴" in text:
            info["leak_after_close"] = True

    if "raw_description" not in info:
        info["raw_description"] = text
    else:
        info["raw_description"] += " " + text

    return info


def _llm_extract(text: str, current_info: dict = None) -> dict | None:
    """用真实大模型抽取结构化字段；不可用 / 异常时返回 None。"""
    if not is_llm_enabled():
        return None

    sys_prompt = (
        "你是住宅报修智能助手的「意图理解」模块。请从住户的自然语言描述中抽取结构化字段，"
        "只返回一个 JSON 对象，不要任何解释或代码块标记。\n"
        "字段与取值：\n"
        "- location: 故障区域，取值之一或 null：厨房/卫生间/卧室/客厅/阳台/入户\n"
        "- device: 涉及设备/部件（如 水槽/水龙头/插座/空调/窗户/墙面/角阀/花洒），或 null\n"
        "- symptom: 故障现象，字符串，可含多个用英文逗号分隔（如 \"漏水,滴水\"）\n"
        "- severity: 严重程度线索，取值之一或 null：持续/严重/轻微/突发\n"
        "- occurrence_time: 发生时间，取值之一或 null：今天/昨天/本周\n"
        "- leak_after_close: 布尔，关闭水源后是否仍在漏（仅漏水相关时判断，否则 null）\n"
        "- other_devices_affected: 布尔或 null，是否同一区域多个设备受影响（电气相关时判断）\n"
        "- ac_detail: 字符串或 null，空调相关细节\n"
        "- is_confirm: 布尔，用户是否在确认/提交工单（含 确认/可以/没问题/提交 等）\n"
        "- is_modify: 布尔，用户是否在要求修改（含 修改/不对/错了 等）\n"
        "- raw_description: 住户原话（直接复制最近一句）\n"
        "规则：若某字段在本次描述中未出现，填空（null 或空串）；"
        "已存在信息请沿用，不要清空。"
    )
    user_payload = {
        "current_info": current_info or {},
        "user_input": text,
    }
    try:
        return chat_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ], temperature=0.2)
    except Exception:
        return None


def extract_info(text: str, current_info: dict = None):
    """抽取结构化信息：优先大模型，失败兜底到关键词匹配。"""
    llm_out = _llm_extract(text, current_info)

    if isinstance(llm_out, dict):
        info = dict(current_info) if current_info else {}
        for k in ["location", "device", "symptom", "severity", "occurrence_time"]:
            v = llm_out.get(k)
            if v and not info.get(k):
                info[k] = v
        if llm_out.get("leak_after_close") and not info.get("leak_after_close"):
            info["leak_after_close"] = True
        if llm_out.get("other_devices_affected") is not None and "other_devices_affected" not in info:
            info["other_devices_affected"] = llm_out.get("other_devices_affected")
        if llm_out.get("ac_detail") and not info.get("ac_detail"):
            info["ac_detail"] = llm_out.get("ac_detail")
        if "raw_description" not in info:
            info["raw_description"] = text
        else:
            info["raw_description"] += " " + text
        # 记录本次意图判断（供状态机 ORDER_PENDING 分支使用）
        info["_is_confirm"] = bool(llm_out.get("is_confirm"))
        info["_is_modify"] = bool(llm_out.get("is_modify"))
        return info

    return _keyword_extract(text, current_info)


def _read_intent(text: str) -> dict:
    """判断用户意图（确认 / 修改 / 补充）。优先大模型，兜底关键词。"""
    llm_out = _llm_extract(text, {})
    if isinstance(llm_out, dict):
        return {
            "confirm": bool(llm_out.get("is_confirm")),
            "modify": bool(llm_out.get("is_modify")),
        }
    return {
        "confirm": any(kw in text for kw in CONFIRM_KEYWORDS),
        "modify": any(kw in text for kw in MODIFY_KEYWORDS),
    }


# ============ Follow-up Question Logic ============

def check_missing_info(info: dict):
    """检查还缺哪些信息并生成追问项（兜底用，大模型追问也基于它判断缺字段）。"""
    questions = []

    if not info.get("location"):
        questions.append({
            "field": "location",
            "question": "请问问题出现在哪个区域？比如厨房、卫生间、卧室、客厅或阳台？",
        })

    if not info.get("symptom"):
        questions.append({
            "field": "symptom",
            "question": "能否具体描述一下故障现象？比如漏水、不通电、不制冷、异响等？",
        })

    symptom = info.get("symptom", "")
    if ("漏水" in symptom or "渗水" in symptom or "滴水" in symptom) and not info.get("leak_after_close"):
        questions.append({
            "field": "leak_after_close",
            "question": "请问关闭水龙头后是否仍然漏水？是持续滴水还是大量出水？",
        })

    if "不通电" in symptom or "不亮" in symptom or "跳闸" in symptom:
        if not info.get("other_devices_affected"):
            questions.append({
                "field": "other_devices_affected",
                "question": "请问是单个插座/灯具无电，还是同一区域多个设备都受影响？",
            })

    if "不制冷" in symptom:
        if not info.get("ac_detail"):
            questions.append({
                "field": "ac_detail",
                "question": "空调能正常开机吗？室外机是否在运转？出风是否正常只是不冷？",
            })

    return questions


def _make_followup(missing: list, info: dict) -> str:
    """生成追问话术：优先大模型自然追问，兜底用规则问题。"""
    if is_llm_enabled():
        try:
            sys_prompt = (
                "你是住宅报修助手。根据已收集信息与缺失字段，用一句自然、友好的话向住户追问，"
                "只返回追问文案本身，不要解释、不要列表。保持口语化、不超过 40 字。"
            )
            user_payload = {
                "collected": {k: v for k, v in info.items() if not k.startswith("_")},
                "missing_fields": [q["field"] for q in missing],
                "fallback_question": missing[0]["question"],
            }
            content = chat_json(
                [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0.5,
            )
            if isinstance(content, dict):
                # 有些模型会返回 {"question": "..."} 结构
                return content.get("question") or content.get("text") or missing[0]["question"]
            return str(content)
        except Exception:
            pass
    return missing[0]["question"]


# ============ Agent State Machine ============

class AgentState:
    START = "start"
    COLLECTING_INFO = "collecting_info"
    INFO_COMPLETE = "info_complete"
    QUERYING_ARCHIVE = "querying_archive"
    SEARCHING_KB = "searching_kb"
    GENERATING_ORDER = "generating_order"
    ORDER_PENDING = "order_pending"
    COMPLETE = "complete"


class MaintenanceAgent:
    """The main AI agent for maintenance reporting."""

    def __init__(self):
        self.state = AgentState.START
        self.house_id = None
        self.extracted_info = {}
        self.archive_data = None
        self.rag_results = []
        self.generated_order = None
        self.conversation_history = []
        self.tool_calls = []  # Track tool calls for transparency

    def init(self, house_id: str):
        self.house_id = house_id
        self.state = AgentState.COLLECTING_INFO
        house = get_house_by_id(house_id)
        if house:
            self.conversation_history.append({
                "role": "assistant",
                "content": f"您好！已识别您的房屋为{house['building']}{house['room']}，数字档案已加载。\n\n请描述您遇到的问题，比如「厨房水槽下面漏水」或「卧室插座没电」。",
                "timestamp": datetime.now().isoformat(),
            })
        return self.conversation_history[-1]

    def process(self, user_input: str):
        """Process user input and return response."""
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat(),
        })

        # 抽取信息（大模型优先，关键词兜底）
        self.extracted_info = extract_info(user_input, self.extracted_info)

        response = None

        if self.state == AgentState.COLLECTING_INFO:
            missing = check_missing_info(self.extracted_info)
            if missing:
                question = _make_followup(missing, self.extracted_info)
                self.state = AgentState.COLLECTING_INFO
                response = {
                    "role": "assistant",
                    "content": question,
                    "timestamp": datetime.now().isoformat(),
                    "agent_state": self.state,
                    "extracted_info": self._safe_info(),
                    "missing_info": [q["field"] for q in missing],
                }
            else:
                self.state = AgentState.INFO_COMPLETE
                response = self._run_tools_and_generate()

        elif self.state == AgentState.ORDER_PENDING:
            intent = _read_intent(user_input)
            if intent["confirm"]:
                self.state = AgentState.COMPLETE
                response = {
                    "role": "assistant",
                    "content": "工单已提交！物业管理人员将尽快审核并安排维修。\n\n您可以在「我的工单」中查看工单进度。",
                    "timestamp": datetime.now().isoformat(),
                    "agent_state": self.state,
                    "work_order": self.generated_order,
                }
            elif intent["modify"]:
                self.state = AgentState.COLLECTING_INFO
                response = {
                    "role": "assistant",
                    "content": "好的，请补充或修正信息。您可以重新描述问题，或直接告诉我哪里需要修改。",
                    "timestamp": datetime.now().isoformat(),
                    "agent_state": self.state,
                }
            else:
                # 视为补充信息，回到收集阶段
                self.state = AgentState.COLLECTING_INFO
                response = self.process(user_input)
        else:
            response = self.process(user_input)

        self.conversation_history.append(response)
        return response

    def _run_tools_and_generate(self):
        """运行工具（档案查询、RAG 检索）并生成工单。"""
        self.tool_calls = []

        # Tool 1: Query house archive
        self.state = AgentState.QUERYING_ARCHIVE
        self.tool_calls.append({
            "tool": "get_house_archive",
            "description": "查询房屋数字档案",
            "input": {"house_id": self.house_id, "location": self.extracted_info.get("location")},
            "status": "executing",
        })

        house = get_house_by_id(self.house_id)
        location = self.extracted_info.get("location", "")
        equipment = get_house_equipment_by_location(self.house_id, location)
        pipeline = get_house_pipeline_layout(self.house_id)
        history = get_maintenance_history(self.house_id)

        self.archive_data = {
            "house": house["room"] if house else "",
            "location": location,
            "equipment": equipment,
            "pipeline_layout": pipeline.get(location, {}) if pipeline else {},
            "maintenance_history": history,
        }

        self.tool_calls[-1]["output"] = {
            "equipment_count": len(equipment),
            "equipment_list": [{"name": e["name"], "spec": e["spec"], "id": e["id"]} for e in equipment],
            "pipeline_info": pipeline.get(location, {}) if pipeline else {},
            "history_count": len(history),
        }
        self.tool_calls[-1]["status"] = "completed"

        # Tool 2: RAG search（本地知识库检索仍保留，作为 LLM 分析的事实依据）
        self.state = AgentState.SEARCHING_KB
        self.tool_calls.append({
            "tool": "search_knowledge_base",
            "description": "检索运维知识库",
            "input": {"query": self.extracted_info.get("raw_description", ""), "extracted_info": self._safe_info()},
            "status": "executing",
        })

        self.rag_results = search_knowledge_base(
            self.extracted_info.get("raw_description", ""),
            self.extracted_info,
        )
        self.tool_calls[-1]["status"] = "completed"

        # Generate work order（分析交给大模型，失败兜底规则）
        self.state = AgentState.GENERATING_ORDER
        order = self._generate_work_order()

        # Build response
        equipment_str = "、".join([f"{e['name']}({e['spec']})" for e in equipment[:3]]) if equipment else "未找到关联设备"
        causes_str = "、".join(order["possible_causes"][:3]) if order.get("possible_causes") else "需现场检查确定"
        analysis_src = "大模型" if order.get("_by_llm") else "规则"

        content = (
            f"## AI分析完成（{analysis_src}）\n\n"
            f"**已调用工具：**\n"
            f"1. ✅ 房屋数字档案查询 — 获取到{location}区域{len(equipment)}个关联设备\n"
            f"2. ✅ 运维知识库检索 — 匹配到{len(self.rag_results)}条相关知识\n\n"
            f"**关联设备：** {equipment_str}\n\n"
            f"**AI初步分析：** {order['ai_analysis']}\n\n"
            f"**建议工种：** {order['suggested_trade']}\n\n"
            f"**紧急等级：** {order['urgency']}\n\n"
            f"**AI置信度：** {order['confidence']}%\n\n"
            f"---\n\n"
            f"以上为AI自动生成的维修工单建议，请确认或修改后提交。"
        )

        response = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "agent_state": self.state,
            "extracted_info": self._safe_info(),
            "tool_calls": self.tool_calls,
            "work_order": order,
            "rag_results": [{"header": r["header"], "content": r["content"][:200]} for r in self.rag_results[:3]],
            "archive_data": {
                "equipment": [{"name": e["name"], "spec": e["spec"], "id": e["id"], "installDate": e.get("installDate", "")} for e in equipment],
                "pipeline_info": pipeline.get(location, {}) if pipeline else {},
                "maintenance_history": history,
            },
        }

        self.state = AgentState.ORDER_PENDING
        self.generated_order = order
        return response

    def _llm_generate_analysis(self, equipment, rag_results) -> dict | None:
        """用大模型基于「抽取信息 + 档案 + 知识库」生成维修分析。失败返回 None。"""
        if not is_llm_enabled():
            return None

        equipment_text = "；".join([f"{e['name']}({e.get('spec','')})" for e in equipment]) or "无"
        rag_text = "\n".join([f"【{r.get('header','')}】{r.get('content','')[:300]}" for r in rag_results[:3]]) or "无"

        sys_prompt = (
            "你是资深住宅运维工程师。基于住户问题、房屋数字档案、运维知识库，输出维修分析，"
            "只返回一个 JSON 对象，不要解释或代码块。\n"
            "字段：\n"
            "- fault_type: 故障分类，取值之一：给排水故障/电气故障/空调故障/门窗故障/墙面裂缝/其他故障\n"
            "- ai_analysis: 一句专业分析（说明疑似原因链，不超过 60 字）\n"
            "- possible_causes: 字符串数组，最多 3 条可能原因\n"
            "- suggested_trade: 建议工种，取值之一：水电维修/电工维修/空调维修/门窗维修/油漆维修/综合维修\n"
            "- urgency: 紧急程度，取值之一：紧急/高/中/低\n"
            "- confidence: 0-100 整数，信息越充分越高（一般 70-92）"
        )
        user_payload = {
            "住户问题": self.extracted_info.get("raw_description", ""),
            "抽取信息": {k: v for k, v in self.extracted_info.items() if not k.startswith("_")},
            "关联设备": equipment_text,
            "知识库片段": rag_text,
        }
        try:
            out = chat_json([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ], temperature=0.3)
            if isinstance(out, dict) and out.get("fault_type"):
                out["_by_llm"] = True
                return out
        except Exception:
            # 大模型不可用 / 返回非 JSON / 超时：交给调用方走原规则兜底
            pass
        return None

    def _rule_analysis(self):
        """原规则分析（兜底）。"""
        possible_causes = get_possible_causes(self.rag_results)
        suggested_trade = get_repair_trade_suggestion(self.extracted_info, self.rag_results)
        urgency = get_urgency_suggestion(self.extracted_info)
        return {
            "fault_type": self._determine_fault_type(),
            "ai_analysis": f"疑似{'、'.join(possible_causes[:3])}" if possible_causes else "需现场检查确定",
            "possible_causes": possible_causes,
            "suggested_trade": suggested_trade,
            "urgency": urgency,
            "confidence": self._calculate_confidence(),
            "_by_llm": False,
        }

    def _generate_work_order(self):
        """生成结构化工单（分析来自大模型，失败兜底规则）。"""
        equipment = self.archive_data.get("equipment", []) if self.archive_data else []
        analysis = self._llm_generate_analysis(equipment, self.rag_results) or self._rule_analysis()

        house = get_house_by_id(self.house_id)
        equipment_ids = [e["id"] for e in equipment[:5]] if equipment else []

        order_id = f"WO-{self.house_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        order = {
            "id": order_id,
            "house_id": self.house_id,
            "house_name": f"{house['building']}{house['room']}" if house else self.house_id,
            "location": self.extracted_info.get("location", ""),
            "fault_type": analysis.get("fault_type", "其他故障"),
            "user_description": self.extracted_info.get("raw_description", ""),
            "related_equipment": equipment_ids,
            "equipment_details": [{"name": e["name"], "spec": e["spec"], "id": e["id"]} for e in equipment[:3]],
            "ai_analysis": analysis.get("ai_analysis", "需现场检查确定"),
            "possible_causes": analysis.get("possible_causes", []),
            "suggested_trade": analysis.get("suggested_trade", "综合维修"),
            "urgency": analysis.get("urgency", "中"),
            "confidence": analysis.get("confidence", 60),
            "status": "pending_review",
            "created_at": datetime.now().isoformat(),
            "pipeline_info": self.archive_data.get("pipeline_layout", {}) if self.archive_data else {},
            "maintenance_history": self.archive_data.get("maintenance_history", []) if self.archive_data else {},
            "_by_llm": analysis.get("_by_llm", False),
        }
        return order

    def _determine_fault_type(self):
        """Determine fault type category from symptoms（兜底用）."""
        symptom = self.extracted_info.get("symptom", "")
        if any(kw in symptom for kw in ["漏水", "渗水", "滴水", "排水"]):
            return "给排水故障"
        if any(kw in symptom for kw in ["不通电", "不亮", "跳闸"]):
            return "电气故障"
        if any(kw in symptom for kw in ["不制冷"]):
            return "空调故障"
        if any(kw in symptom for kw in ["关不严", "变形"]):
            return "门窗故障"
        if any(kw in symptom for kw in ["裂缝"]):
            return "墙面裂缝"
        return "其他故障"

    def _calculate_confidence(self):
        """Calculate AI confidence score（兜底用）。"""
        score = 50
        info = self.extracted_info

        if info.get("location"):
            score += 10
        if info.get("symptom"):
            score += 10
        if info.get("device"):
            score += 5
        if info.get("severity") or info.get("leak_after_close"):
            score += 10
        if self.archive_data and self.archive_data.get("equipment"):
            score += 10
        if self.rag_results:
            score += 5
        if info.get("raw_description") and len(info["raw_description"]) > 20:
            score += 5

        return min(score, 95)

    def _safe_info(self):
        """Return a safe copy of extracted info for JSON serialization."""
        info = dict(self.extracted_info)
        # 去掉内部意图标记与超长原文
        info.pop("_is_confirm", None)
        info.pop("_is_modify", None)
        if "raw_description" in info:
            info["raw_description"] = info["raw_description"][:200]
        return info

    def get_state(self):
        return {
            "state": self.state,
            "house_id": self.house_id,
            "extracted_info": self._safe_info(),
            "tool_calls": self.tool_calls,
            "generated_order": self.generated_order,
            "conversation_count": len(self.conversation_history),
        }

    def to_dict(self):
        return {
            "state": self.state,
            "house_id": self.house_id,
            "extracted_info": self.extracted_info,
            "archive_data": self.archive_data,
            "rag_results": [{"header": r.get("header", ""), "content": r.get("content", "")[:200]} for r in self.rag_results],
            "generated_order": self.generated_order,
            "conversation_history": self.conversation_history,
            "tool_calls": self.tool_calls,
        }
