"""End-to-end test script."""
import requests, json

BASE = "http://localhost:8000"

print("========== 端到端测试 ==========")
print()

# 1. Init chat
print("1. 初始化AI报修对话...")
r = requests.post(f"{BASE}/api/chat/init", json={"house_id": "1302"})
data = r.json()
sid = data["session_id"]
print(f"   会话ID: {sid}")
print(f"   AI: {data['message']['content'][:50]}...")
print()

# 2. First message
print("2. 住户: 厨房水槽下面今天一直漏水")
r = requests.post(f"{BASE}/api/chat/message", json={"session_id": sid, "message": "厨房水槽下面今天一直漏水"})
data = r.json()
print(f"   Agent状态: {data['agent_state']}")
print(f"   提取信息: {json.dumps(data.get('extracted_info',{}), ensure_ascii=False)}")
print(f"   AI追问: {data.get('content','')[:60]}")
print()

# 3. Answer follow-up
print("3. 住户: 关掉水龙头之后还是会慢慢漏")
r = requests.post(f"{BASE}/api/chat/message", json={"session_id": sid, "message": "关掉水龙头之后还是会慢慢漏"})
data = r.json()
print(f"   Agent状态: {data['agent_state']}")
print(f"   工具调用: {len(data.get('tool_calls',[]))}个")
for tc in data.get("tool_calls", []):
    print(f"     - {tc['description']}: {tc['status']}")
wo = data.get("work_order", {})
print(f"   工单ID: {wo.get('id')}")
print(f"   故障类型: {wo.get('fault_type')}")
print(f"   AI分析: {wo.get('ai_analysis')}")
print(f"   建议工种: {wo.get('suggested_trade')}")
print(f"   紧急度: {wo.get('urgency')}")
print(f"   置信度: {wo.get('confidence')}%")
print()

# 4. Confirm order
print("4. 住户确认提交工单...")
r = requests.post(f"{BASE}/api/chat/action", json={"session_id": sid, "action": "confirm_order"})
data = r.json()
print(f"   结果: {data.get('message')}")
wo_id = data.get("work_order_id")
print(f"   工单号: {wo_id}")
print()

# 5. Property review
print("5. 物业审核工单...")
r = requests.put(f"{BASE}/api/workorders/{wo_id}/review", json={
    "reviewed_by": "物业管理员张姐",
    "urgency": "高",
    "assigned_to": "水电维修组A",
    "review_notes": "持续漏水可能影响楼下，升级为高优先级",
    "status": "approved"
})
print(f"   审核结果: {r.json().get('status')}")
print()

# 6. Complete repair
print("6. 维修人员完成维修...")
r = requests.put(f"{BASE}/api/workorders/{wo_id}/complete", json={
    "repair_person": "水电工李师傅",
    "actual_fault": "角阀AF-105密封圈老化失效",
    "actual_action": "更换角阀密封圈及AF-105角阀",
    "used_parts": "AF-105角阀 x1",
    "result": "完成"
})
data = r.json()
print(f"   结果: {data.get('message')}")
print()

# 7. Verify data write-back
print("7. 验证数据回写至一房一码档案...")
r = requests.get(f"{BASE}/api/houses/1302/history")
history = r.json()
print(f"   维修记录数: {len(history['records'])}")
for rec in history["records"]:
    print(f"     - {rec.get('date')} | {rec.get('fault')} | {rec.get('cause')} | {rec.get('repairPerson')}")
print()

# 8. Check repeat maintenance warnings
print("8. 检查重复维修预警...")
r = requests.get(f"{BASE}/api/maintenance/history/503")
warnings = r.json().get("repeat_warnings", [])
if warnings:
    for w in warnings:
        print(f"   预警: {w}")
else:
    print("   无预警")
print()

# 9. Stats
print("9. 工单统计...")
r = requests.get(f"{BASE}/api/workorders/stats/summary")
stats = r.json()
print(f"   工单总数: {stats['total']}")
print(f"   状态分布: {json.dumps(stats['by_status'], ensure_ascii=False)}")
print(f"   平均置信度: {stats['avg_confidence']}%")
print()
print("========== 测试完成 ==========")
