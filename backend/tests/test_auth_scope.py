"""登录令牌与数据范围（app/security.py、services/event_access.py）的单元测试.

不连 MySQL：用内存 SQLite 顶替 app.database（见 tests/fake_db.py）；接口层的三角色冒烟检查需要启动后端，见第三步说明。
"""
import unittest

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_db  # noqa: E402

CONN = fake_db.install()

from fastapi import HTTPException  # noqa: E402

from app import security  # noqa: E402  必须在替换 app.database 之后导入
from app.services import event_access as ea  # noqa: E402


class TokenTest(unittest.TestCase):
    def test_roundtrip_and_expiry(self):
        token, exp = security.create_token(7, "RESIDENT", now=1_000_000, ttl_hours=1)
        self.assertEqual(exp, 1_000_000 + 3600)
        payload = security.decode_token(token, now=1_000_000 + 10)
        self.assertEqual((payload["sub"], payload["role"]), ("7", "RESIDENT"))
        with self.assertRaisesRegex(ValueError, "过期"):
            security.decode_token(token, now=exp)

    def test_tampered_payload_rejected(self):
        token, _ = security.create_token(7, "RESIDENT")
        other, _ = security.create_token(1, "ADMIN")
        header, _, sig = token.split(".")
        forged = f"{header}.{other.split('.')[1]}.{sig}"  # 把载荷换成管理员，签名不变
        with self.assertRaisesRegex(ValueError, "签名"):
            security.decode_token(forged)
        for bad in ("", "a.b", "a.b.c", token + "x"):
            with self.assertRaises(ValueError):
                security.decode_token(bad)


class ScopeTest(unittest.TestCase):
    def setUp(self):
        CONN.executescript(
            """
            DROP TABLE IF EXISTS user; DROP TABLE IF EXISTS house; DROP TABLE IF EXISTS user_house; DROP TABLE IF EXISTS repair_order;
            CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT, real_name TEXT, role TEXT, status INTEGER DEFAULT 1);
            CREATE TABLE house (id INTEGER PRIMARY KEY, house_code TEXT);
            CREATE TABLE user_house (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, house_code TEXT, relation TEXT);
            CREATE TABLE repair_order (id INTEGER PRIMARY KEY, order_no TEXT, reporter_id INTEGER, assigned_to INTEGER,
                                       status TEXT, house_id INTEGER);
            INSERT INTO user VALUES (1, 'resident1', '张三', 'RESIDENT', 1), (2, 'repairer1', '王工', 'REPAIRER', 1),
                                    (3, 'property1', '物业', 'PROPERTY', 1), (4, 'off', '停用', 'RESIDENT', 0);
            INSERT INTO house VALUES (10, '1302'), (11, '805'), (12, '503');
            INSERT INTO user_house (user_id, house_code, relation) VALUES (1, '1302', 'OWNER');
            INSERT INTO repair_order VALUES (100, 'WO-805', 1, 2, 'PROCESSING', 11), (101, 'WO-503', 3, NULL, 'PENDING_REVIEW', 12);
            """
        )

    def test_load_user(self):
        self.assertEqual(security.load_user(1).house_codes, ["1302"])
        self.assertIsNone(security.load_user(4))  # 已禁用
        self.assertIsNone(security.load_user(404))

    def test_house_access(self):
        resident, repairer, staff = (security.load_user(i) for i in (1, 2, 3))
        self.assertEqual(security.visible_house_codes(repairer), ["805"])
        self.assertIsNone(security.visible_house_codes(staff))
        security.ensure_house_access(resident, "1302")
        security.ensure_house_access(staff, "503")
        with self.assertRaises(HTTPException) as ctx:
            security.ensure_house_access(resident, "805")
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (403, "该房屋不属于您"))
        with self.assertRaises(HTTPException):
            security.ensure_house_access(repairer, "1302")

    def test_order_access(self):
        resident, repairer, staff = (security.load_user(i) for i in (1, 2, 3))
        # 805 的工单报修人字段是张三，但 805 不是张三的房子 → 不可看（系统建单的报修人不可靠，只按房屋判断）
        self.assertEqual(security.ensure_order_access(repairer, "WO-805")["order_no"], "WO-805")
        for user, order in ((resident, "WO-805"), (resident, "WO-503"), (repairer, "WO-503")):
            with self.assertRaises(HTTPException) as ctx:
                security.ensure_order_access(user, order)
            self.assertEqual(ctx.exception.status_code, 403)
        security.ensure_order_access(staff, "WO-503")
        with self.assertRaises(HTTPException) as ctx:
            security.ensure_order_access(staff, "NOPE")
        self.assertEqual(ctx.exception.status_code, 404)


def _burst_805():
    event = {
        "event_id": "EVT-805", "event_type": "PIPE_BURST", "domain": "WATER", "severity": "CRITICAL", "scope": "HOUSE",
        "detected_at": "2026-06-23T14:06:00+08:00", "house_id": "805", "related_houses": ["705"],
        "location_candidates": [{"segment_code": "WS-805-K-HS"}], "evidence": {"x": 1}, "evidence_text": "805 厨房软管爆裂",
        "control_actions_taken": [{"action": "CLOSE_VALVE", "target": "WS-805-IN-MV"}],
    }
    decision = {
        "priority": "URGENT", "fault_summary": "805 厨房爆管",
        "notices": [
            {"audience": "RESIDENT", "house_ids": ["805"], "title": "您家厨房漏水"},
            {"audience": "NEIGHBOR", "house_ids": ["705", "706"], "title": "楼上住户漏水，请留意厨房天花"},
            {"audience": "PROPERTY", "house_ids": ["805"], "title": "805 爆管已关阀"},
        ],
        "workorders": [{"house_ids": ["805"], "materials": ["软管"]}],
    }
    return event, decision


class EventRedactionTest(unittest.TestCase):
    def test_visibility(self):
        event, decision = _burst_805()
        self.assertTrue(ea.resident_can_see(event, decision, ["805"]))
        self.assertTrue(ea.resident_can_see(event, decision, ["706"]))  # 只在提醒对象里
        self.assertFalse(ea.resident_can_see(event, decision, ["1302"]))
        live_notices = [{"audience": "NEIGHBOR", "house_id": "905"}]
        self.assertTrue(ea.resident_can_see({"house_id": None}, {}, ["905"], live_notices))

    def test_neighbor_sees_only_impact_hint(self):
        event, decision = _burst_805()
        e, d, notices, neighbor = ea.redact_for_resident(event, decision, None, ["705"])
        self.assertTrue(neighbor)
        self.assertIsNone(e["house_id"])
        self.assertEqual((e["location_candidates"], e["evidence_text"], e["control_actions_taken"], e["evidence"]), ([], "", [], {}))
        self.assertEqual(e["related_houses"], ["705"])
        self.assertEqual(d["fault_summary"], "楼上住户漏水，请留意厨房天花")
        self.assertEqual(d["notices"], [{"audience": "NEIGHBOR", "house_ids": ["705"], "title": "楼上住户漏水，请留意厨房天花"}])
        self.assertEqual(d["workorders"], [])
        self.assertTrue(e["event_id"].startswith("EVT-NB-"))
        self.assertEqual(e["event_id"], ea.neighbor_event_id("EVT-805"))  # 同一事件别名稳定
        self.assertNotIn("805", str((e, d)))

    def test_own_event_keeps_detail_but_hides_others(self):
        event, decision = _burst_805()
        e, d, _, neighbor = ea.redact_for_resident(event, decision, None, ["805"])
        self.assertFalse(neighbor)
        self.assertEqual(e["location_candidates"], event["location_candidates"])
        self.assertEqual(e["related_houses"], [])
        self.assertEqual([n["audience"] for n in d["notices"]], ["RESIDENT"])
        self.assertEqual(d["workorders"], [])

    def test_live_notices_filtered(self):
        event, decision = _burst_805()
        live = [{"id": 1, "audience": "NEIGHBOR", "house_id": "705"}, {"id": 2, "audience": "NEIGHBOR", "house_id": "706"},
                {"id": 3, "audience": "PROPERTY", "house_id": "805"}]
        _, _, notices, _ = ea.redact_for_resident(event, decision, live, ["705"])
        self.assertEqual([n["id"] for n in notices], [1])
        self.assertEqual([n["id"] for n in ea.repairer_notices(live)], [3])


if __name__ == "__main__":
    unittest.main()
