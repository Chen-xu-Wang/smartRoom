import unittest
from datetime import datetime, timedelta

from app.services.dispatcher import (
    build_dispatch_plan,
    calculate_fatigue,
    calculate_sla_risk,
    parse_skills,
    workload_balance_score,
)


NOW = datetime(2026, 8, 31, 10, 0, 0)


def candidate(
    user_id,
    name,
    skills,
    active=0,
    max_active=3,
    completed_today=0,
    daily_capacity=5,
    on_duty=True,
    similar=0,
):
    return {
        "id": user_id,
        "username": f"repairer{user_id}",
        "real_name": name,
        "skills": skills,
        "active_orders": active,
        "active_load": active,
        "max_active_orders": max_active,
        "completed_today": completed_today,
        "daily_capacity": daily_capacity,
        "on_duty": on_duty,
        "similar_jobs_90d": similar,
        "same_building_jobs_90d": 0,
    }


class DispatcherTests(unittest.TestCase):
    def test_parse_skills_accepts_json_and_chinese_commas(self):
        self.assertEqual(parse_skills('["水电维修", "电工维修"]'), ["水电维修", "电工维修"])
        self.assertEqual(parse_skills("空调维修，综合维修"), ["空调维修", "综合维修"])

    def test_exact_skill_and_safe_capacity_win(self):
        order = {"suggested_trade": "水电维修", "repair_category": "给排水故障"}
        candidates = [
            candidate(1, "忙碌王工", ["水电维修"], active=2, similar=4),
            candidate(2, "空闲李工", ["水电维修"], active=0, similar=1),
            candidate(3, "综合张工", ["综合维修"], active=0, similar=4),
        ]
        plan = build_dispatch_plan(order, candidates, NOW)
        self.assertTrue(plan["assignment_available"])
        self.assertEqual(plan["recommended"]["name"], "空闲李工")
        self.assertEqual(plan["recommended"]["skill_match"], "exact")

    def test_capacity_and_off_duty_are_hard_blockers(self):
        order = {"suggested_trade": "电工维修"}
        candidates = [
            candidate(1, "满载", ["电工维修"], active=2, max_active=2),
            candidate(2, "休班", ["电工维修"], on_duty=False),
        ]
        plan = build_dispatch_plan(order, candidates, NOW)
        self.assertFalse(plan["assignment_available"])
        self.assertEqual(plan["no_assignment_reason"], "NO_SAFE_CANDIDATE")
        self.assertTrue(all(not item["available"] for item in plan["candidates"]))

    def test_daily_capacity_protects_repairer(self):
        fatigue = calculate_fatigue(
            candidate(
                1,
                "王工",
                ["综合维修"],
                completed_today=5,
                daily_capacity=5,
            ),
            NOW,
        )
        self.assertTrue(any("今日完工量" in text for text in fatigue["workload_blockers"]))

    def test_equal_candidates_rotate_by_last_assignment_time(self):
        order = {"suggested_trade": "综合维修"}
        recent = candidate(1, "刚派过", ["综合维修"])
        recent["last_assigned_at"] = NOW - timedelta(minutes=5)
        older = candidate(2, "较久未派", ["综合维修"])
        older["last_assigned_at"] = NOW - timedelta(hours=3)
        plan = build_dispatch_plan(order, [recent, older], NOW)
        self.assertEqual(plan["recommended"]["name"], "较久未派")

    def test_recent_completion_adds_rest_penalty(self):
        worker = candidate(1, "王工", ["综合维修"])
        worker["last_completed_at"] = NOW - timedelta(minutes=20)
        fatigue = calculate_fatigue(worker, NOW)
        self.assertGreater(fatigue["fatigue_index"], 0)

    def test_high_fatigue_blocks_even_before_concurrent_limit(self):
        worker = candidate(
            1,
            "需要休息的王工",
            ["水电维修"],
            active=2,
            max_active=3,
            completed_today=4,
            daily_capacity=5,
        )
        worker["active_load"] = 3.2  # 两张紧急单的加权负载
        plan = build_dispatch_plan({"suggested_trade": "水电维修"}, [worker], NOW)
        self.assertFalse(plan["assignment_available"])
        self.assertTrue(any("休息保护" in text for text in plan["candidates"][0]["blockers"]))

    def test_projected_fatigue_blocks_a_new_urgent_order(self):
        worker = candidate(1, "王工", ["水电维修"], active=2, max_active=3)
        worker["active_load"] = 2.6
        plan = build_dispatch_plan(
            {"suggested_trade": "水电维修", "priority": "URGENT"},
            [worker],
            NOW,
        )
        self.assertFalse(plan["assignment_available"])
        self.assertTrue(any("接单后预计疲劳" in text for text in plan["candidates"][0]["blockers"]))

    def test_sla_risk_marks_urgent_order_overdue(self):
        risk = calculate_sla_risk(
            {"priority": "URGENT", "created_at": NOW - timedelta(hours=2)},
            NOW,
        )
        self.assertEqual(risk["risk_level"], "overdue")
        self.assertTrue(risk["is_at_risk"])
        self.assertLess(risk["remaining_hours"], 0)

    def test_balance_score_falls_when_load_is_uneven(self):
        balanced = workload_balance_score(
            [{"active_orders": 1, "max_active_orders": 3}] * 3
        )
        uneven = workload_balance_score(
            [
                {"active_orders": 3, "max_active_orders": 3},
                {"active_orders": 0, "max_active_orders": 3},
                {"active_orders": 0, "max_active_orders": 3},
            ]
        )
        self.assertEqual(balanced, 100)
        self.assertLess(uneven, balanced)


if __name__ == "__main__":
    unittest.main()
