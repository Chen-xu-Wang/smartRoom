"""本地端到端冒烟脚本（需要已启动的后端与可写数据库）。

不会作为 unittest 自动运行；它会创建一张真实工单，请仅在开发/测试库执行：
    cd backend && python test_e2e.py
"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE = "http://localhost:8000"


def call(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} → HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接后端 {BASE}，请先启动服务：{exc.reason}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main():
    print("========== 筑维AI端到端冒烟测试 ==========")

    chat = call("POST", "/api/chat/init", {"house_id": "1302"})
    session_id = chat["session_id"]
    print("1. 已创建报修会话")

    call("POST", "/api/chat/message", {
        "session_id": session_id,
        "message": "厨房水槽下面今天一直漏水",
    })
    analyzed = call("POST", "/api/chat/message", {
        "session_id": session_id,
        "message": "关掉水龙头之后还是会慢慢漏，地面已经有积水",
    })
    require(analyzed.get("work_order"), "AI 未生成结构化工单")
    print("2. AI 已生成结构化工单")

    confirmed = call("POST", "/api/chat/action", {
        "session_id": session_id,
        "action": "confirm_order",
    })
    order_no = confirmed.get("work_order_id")
    require(order_no, "住户确认后未返回工单号")
    print(f"3. 住户已确认工单：{order_no}")

    reviewed = call("PUT", f"/api/workorders/{order_no}/review", {
        "reviewed_by": "物业管理员",
        "urgency": "高",
        "suggested_trade": "水电维修",
        "review_notes": "持续漏水，优先处理",
        "status": "approved",
        "auto_assign": True,
    })
    dispatch = reviewed.get("dispatch") or {}
    require(dispatch.get("status") == "assigned", f"审核后未能安全自动派单：{dispatch}")
    repairer = dispatch.get("assigned_to")
    require(repairer, "自动派单未返回维修人员")
    print(f"4. 审核通过，AI 已派给：{repairer}")

    detail = call("GET", f"/api/workorders/{order_no}")
    require(detail.get("assigned_to") == repairer, "工单详情中的派单人员不一致")

    started = call("PUT", f"/api/workorders/{order_no}/start", {
        "repair_person": repairer,
    })
    require(started.get("status") == "PROCESSING", "工单未成功进入维修中")
    print("5. 指派维修人员已开工")

    completed = call("PUT", f"/api/workorders/{order_no}/complete", {
        "repair_person": repairer,
        "actual_fault": "角阀密封圈老化失效",
        "actual_action": "更换密封圈并复紧角阀接口",
        "used_parts": "角阀密封圈 x1",
        "result": "完成",
    })
    require(completed.get("success"), "维修完成接口未成功")
    print("6. 维修完成并回写数字档案")

    overview = call("GET", "/api/workorders/dispatch/overview")
    require("summary" in overview and "repairers" in overview, "调度看板接口返回不完整")
    risks = call("GET", "/api/maintenance/risks")
    require("risks" in risks and "summary" in risks, "预测性维护接口返回不完整")
    print("7. 调度看板与预测性维护风险中心返回正常")
    print("========== 测试通过 ==========")


if __name__ == "__main__":
    main()
