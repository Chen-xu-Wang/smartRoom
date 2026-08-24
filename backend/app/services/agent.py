"""AI Agent - 智能报修助手核心逻辑.

State machine:
  START → COLLECTING_INFO → INFO_COMPLETE → QUERYING_ARCHIVE →
  SEARCHING_KB → GENERATING_ORDER → ORDER_PENDING → COMPLETE

The agent uses keyword-based NLP for intent recognition and info extraction,
followed by tool calls to house archive and RAG knowledge base.
"""
import json
import re
from datetime import datetime, timedelta
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

# ============ Keyword Dictionaries ============

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

# ============ Info Extraction ============

def extract_info(text: str, current_info: dict = None):
    """Extract structured information from natural language input."""
    info = dict(current_info) if current_info else {}

    # Extract location
    for loc, keywords in LOCATION_KEYWORDS.items():
        if loc not in info.get("location", ""):
            for kw in keywords:
                if kw in text:
                    info["location"] = loc
                    break

    # Extract device
    for device, keywords in DEVICE_KEYWORDS.items():
        if not info.get("device"):
            for kw in keywords:
                if kw in text:
                    info["device"] = device
                    break

    # Extract symptom
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

    # Extract severity cues
    for severity, keywords in SEVERITY_KEYWORDS.items():
        if not info.get("severity"):
            for kw in keywords:
                if kw in text:
                    info["severity"] = severity
                    break

    # Extract time info
    if "今天" in text or "刚才" in text:
        info["occurrence_time"] = "今天"
    elif "昨天" in text:
        info["occurrence_time"] = "昨天"
    elif "这周" in text or "这几天" in text:
        info["occurrence_time"] = "本周"

    # Special: check if water still leaks after closing tap
    if "关掉" in text or "关闭" in text or "关了" in text:
        if "漏" in text or "滴" in text:
            info["leak_after_close"] = True

    # Store raw description
    if "raw_description" not in info:
        info["raw_description"] = text
    else:
        info["raw_description"] += " " + text

    return info

# ============ Follow-up Question Logic ============

def check_missing_info(info: dict):
    """Check what information is missing and generate follow-up questions."""
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

    # If symptom is leak-related but no detail on whether it continues after closing
    symptom = info.get("symptom", "")
    if ("漏水" in symptom or "渗水" in symptom or "滴水" in symptom) and not info.get("leak_after_close"):
        questions.append({
            "field": "leak_after_close",
            "question": "请问关闭水龙头后是否仍然漏水？是持续滴水还是大量出水？",
        })

    # If symptom is electrical but no detail
    if "不通电" in symptom or "不亮" in symptom or "跳闸" in symptom:
        if not info.get("other_devices_affected"):
            questions.append({
                "field": "other_devices_affected",
                "question": "请问是单个插座/灯具无电，还是同一区域多个设备都受影响？",
            })

    # If symptom is AC related
    if "不制冷" in symptom:
        if not info.get("ac_detail"):
            questions.append({
                "field": "ac_detail",
                "question": "空调能正常开机吗？室外机是否在运转？出风是否正常只是不冷？",
            })

    return questions

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

        # Extract info from user input
        self.extracted_info = extract_info(user_input, self.extracted_info)

        response = None

        if self.state == AgentState.COLLECTING_INFO:
            # Check if we have enough info
            missing = check_missing_info(self.extracted_info)

            if missing:
                # Ask follow-up question
                question = missing[0]["question"]
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
                # Enough info, move to next stage
                self.state = AgentState.INFO_COMPLETE
                response = self._run_tools_and_generate()

        elif self.state == AgentState.ORDER_PENDING:
            # User is responding to the generated order
            if any(kw in user_input for kw in ["确认", "没问题", "可以", "同意", "好"]):
                self.state = AgentState.COMPLETE
                response = {
                    "role": "assistant",
                    "content": "工单已提交！物业管理人员将尽快审核并安排维修。\n\n您可以在「我的工单」中查看工单进度。",
                    "timestamp": datetime.now().isoformat(),
                    "agent_state": self.state,
                    "work_order": self.generated_order,
                }
            elif any(kw in user_input for kw in ["修改", "不对", "错了", "不是"]):
                self.state = AgentState.COLLECTING_INFO
                response = {
                    "role": "assistant",
                    "content": "好的，请补充或修正信息。您可以重新描述问题，或直接告诉我哪里需要修改。",
                    "timestamp": datetime.now().isoformat(),
                    "agent_state": self.state,
                }
            else:
                # Treat as additional info
                self.state = AgentState.COLLECTING_INFO
                response = self.process(user_input)
        else:
            # Re-process
            response = self.process(user_input)

        self.conversation_history.append(response)
        return response

    def _run_tools_and_generate(self):
        """Run tools (archive query, RAG search) and generate work order."""
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

        # Tool 2: RAG search
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

        possible_causes = get_possible_causes(self.rag_results)
        suggested_trade = get_repair_trade_suggestion(self.extracted_info, self.rag_results)
        urgency = get_urgency_suggestion(self.extracted_info)

        self.tool_calls[-1]["output"] = {
            "results_count": len(self.rag_results),
            "possible_causes": possible_causes,
            "suggested_trade": suggested_trade,
            "urgency": urgency,
            "sections": [{"header": r["header"], "category": r.get("category", "")} for r in self.rag_results[:3]],
        }
        self.tool_calls[-1]["status"] = "completed"

        # Generate work order
        self.state = AgentState.GENERATING_ORDER
        order = self._generate_work_order(possible_causes, suggested_trade, urgency)

        # Build response
        equipment_str = "、".join([f"{e['name']}({e['spec']})" for e in equipment[:3]]) if equipment else "未找到关联设备"
        causes_str = "、".join(possible_causes[:3]) if possible_causes else "需现场检查确定"

        content = (
            f"## AI分析完成\n\n"
            f"**已调用工具：**\n"
            f"1. ✅ 房屋数字档案查询 — 获取到{location}区域{len(equipment)}个关联设备\n"
            f"2. ✅ 运维知识库检索 — 匹配到{len(self.rag_results)}条相关知识\n\n"
            f"**关联设备：** {equipment_str}\n\n"
            f"**AI初步分析：** 疑似{causes_str}\n\n"
            f"**建议工种：** {suggested_trade}\n\n"
            f"**紧急等级：** {urgency}\n\n"
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

    def _generate_work_order(self, causes, trade, urgency):
        """Generate a structured work order."""
        house = get_house_by_id(self.house_id)
        equipment = self.archive_data.get("equipment", [])
        equipment_ids = [e["id"] for e in equipment[:5]] if equipment else []

        # Calculate confidence
        confidence = self._calculate_confidence()

        order_id = f"WO-{self.house_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        order = {
            "id": order_id,
            "house_id": self.house_id,
            "house_name": f"{house['building']}{house['room']}" if house else self.house_id,
            "location": self.extracted_info.get("location", ""),
            "fault_type": self._determine_fault_type(),
            "user_description": self.extracted_info.get("raw_description", ""),
            "related_equipment": equipment_ids,
            "equipment_details": [{"name": e["name"], "spec": e["spec"], "id": e["id"]} for e in equipment[:3]],
            "ai_analysis": f"疑似{'、'.join(causes[:3])}" if causes else "需现场检查确定",
            "possible_causes": causes,
            "suggested_trade": trade,
            "urgency": urgency,
            "confidence": confidence,
            "status": "pending_review",
            "created_at": datetime.now().isoformat(),
            "pipeline_info": self.archive_data.get("pipeline_layout", {}),
            "maintenance_history": self.archive_data.get("maintenance_history", []),
        }
        return order

    def _determine_fault_type(self):
        """Determine fault type category from symptoms."""
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
        """Calculate AI confidence score."""
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

        # Cap at 95
        return min(score, 95)

    def _safe_info(self):
        """Return a safe copy of extracted info for JSON serialization."""
        info = dict(self.extracted_info)
        # Remove raw_description for brevity in API response
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
