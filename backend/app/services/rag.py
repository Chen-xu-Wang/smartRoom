"""RAG knowledge base service - 运维知识库检索."""
import os
import re
from pathlib import Path
from ..config import KNOWLEDGE_DIR

# Keyword to category mapping for retrieval
CATEGORY_MAP = {
    "plumbing": {
        "file": "plumbing.md",
        "keywords": ["漏水", "水槽", "水管", "角阀", "排水", "花洒", "马桶", "软管",
                      "管道", "水龙头", "滴水", "渗水", "给排水", "地漏", "漏水", "持续"],
    },
    "electrical": {
        "file": "electrical.md",
        "keywords": ["插座", "没电", "不通电", "灯不亮", "灯具", "开关", "配电箱",
                      "跳闸", "漏电", "电路", "LED", "电", "短路", "过载"],
    },
    "hvac": {
        "file": "hvac.md",
        "keywords": ["空调", "制冷", "不冷", "不制冷", "漏水", "异响", "室外机",
                      "室内机", "压缩机", "冷凝水", "制冷剂", "充氟", "滤网", "风轮"],
    },
    "general": {
        "file": "general.md",
        "keywords": ["窗户", "门", "关不严", "渗水", "密封", "铰链", "裂缝",
                      "墙面", "重复维修", "保修"],
    },
}

_knowledge_cache = {}

def load_knowledge():
    """Load all knowledge base documents into memory."""
    if _knowledge_cache:
        return _knowledge_cache
    for cat, info in CATEGORY_MAP.items():
        filepath = os.path.join(KNOWLEDGE_DIR, info["file"])
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                _knowledge_cache[cat] = f.read()
        else:
            _knowledge_cache[cat] = ""
    return _knowledge_cache

def split_sections(text: str):
    """Split markdown into sections by ## headers."""
    sections = []
    current_header = ""
    current_content = []
    for line in text.split("\n"):
        if line.startswith("## "):
            if current_header:
                sections.append({"header": current_header, "content": "\n".join(current_content)})
            current_header = line.replace("## ", "").strip()
            current_content = []
        else:
            current_content.append(line)
    if current_header:
        sections.append({"header": current_header, "content": "\n".join(current_content)})
    return sections

def search_knowledge_base(query: str, extracted_info: dict = None, top_k: int = 5):
    """Search the knowledge base and return relevant sections.

    Uses keyword matching to find the most relevant sections.
    """
    knowledge = load_knowledge()

    # Determine relevant categories based on query and extracted info
    search_text = query
    if extracted_info:
        for v in extracted_info.values():
            if isinstance(v, str):
                search_text += " " + v

    # Score each category
    category_scores = {}
    for cat, info in CATEGORY_MAP.items():
        score = sum(1 for kw in info["keywords"] if kw in search_text)
        category_scores[cat] = score

    # Sort by score
    sorted_cats = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for cat, score in sorted_cats:
        if score == 0 and not results:
            # Always include at least one category（补齐 relevance_score，避免排序时 KeyError）
            if not results:
                text = knowledge.get(cat, "")
                sections = split_sections(text)
                for sec in sections[:2]:
                    results.append({
                        "category": cat,
                        "header": sec["header"],
                        "content": sec["content"].strip(),
                        "relevance_score": 1,
                    })
            continue
        if score > 0:
            text = knowledge.get(cat, "")
            sections = split_sections(text)
            # Filter sections by keywords in query
            for section in sections:
                section_text = section["header"] + section["content"]
                section_score = sum(1 for kw in CATEGORY_MAP[cat]["keywords"] if kw in section_text)
                if section_score > 0:
                    results.append({
                        "category": cat,
                        "header": section["header"],
                        "content": section["content"].strip(),
                        "relevance_score": section_score + score * 2,
                    })

    # Also search remaining categories
    for cat, score in sorted_cats:
        if score == 0:
            text = knowledge.get(cat, "")
            sections = split_sections(text)
            for section in sections:
                section_text = section["header"] + section["content"]
                section_score = sum(1 for kw in CATEGORY_MAP[cat]["keywords"] if kw in section_text)
                if section_score > 0:
                    results.append({
                        "category": cat,
                        "header": section["header"],
                        "content": section["content"].strip(),
                        "relevance_score": section_score,
                    })

    # Sort by relevance score and deduplicate
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    seen = set()
    unique_results = []
    for r in results:
        key = r["header"]
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    return unique_results[:top_k]

def get_repair_trade_suggestion(extracted_info: dict, rag_results: list):
    """Determine suggested repair trade based on analysis."""
    location = extracted_info.get("location", "")
    symptom = extracted_info.get("symptom", "")
    device = extracted_info.get("device", "")
    combined = f"{location} {symptom} {device}"

    if any(kw in combined for kw in ["水", "管", "漏", "水槽", "排水", "花洒", "角阀", "软管"]):
        return "水电维修"
    if any(kw in combined for kw in ["插座", "电", "灯", "开关", "配电", "跳闸"]):
        return "电工维修"
    if any(kw in combined for kw in ["空调", "制冷", "室外机", "压缩机"]):
        return "空调维修"
    if any(kw in combined for kw in ["窗", "门", "密封", "铰链"]):
        return "门窗维修"
    if any(kw in combined for kw in ["墙", "裂缝", "漆"]):
        return "油漆维修"
    return "综合维修"

def get_urgency_suggestion(extracted_info: dict):
    """Determine urgency level based on extracted info."""
    symptom = extracted_info.get("symptom", "")
    severity = extracted_info.get("severity", "")
    combined = f"{symptom} {severity}"

    if any(kw in combined for kw in ["大量", "紧急", "破裂", "不能使用", "全屋"]):
        return "紧急"
    if any(kw in combined for kw in ["持续", "一直", "渗水", "影响", "重复"]):
        return "高"
    if any(kw in combined for kw in ["有时", "偶尔", "轻微", "小"]):
        return "低"
    return "中"

def get_possible_causes(rag_results: list):
    """Extract possible causes from RAG results."""
    causes = []
    for r in rag_results:
        content = r.get("content", "")
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line and (line.startswith("1.") or line.startswith("2.") or line.startswith("3.") or line.startswith("4.")):
                cause = re.sub(r'^\d+\.\s*', '', line)
                cause = cause.split("\u3001")[0].split("：")[0].split(":")[0].strip()
                cause = cause.replace("**", "").strip()
                if cause and len(cause) > 2:
                    causes.append(cause)
    return causes[:5] if causes else ["需现场检查确定"]
