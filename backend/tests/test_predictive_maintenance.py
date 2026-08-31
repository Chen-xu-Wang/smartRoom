"""预测性维护评分和聚合单元测试（不连接 MySQL）。"""
import unittest
from datetime import datetime

from app.services.predictive_maintenance import (
    build_maintenance_risk_report,
    calculate_risk_score,
    get_maintenance_risks,
)


NOW = datetime(2026, 8, 31, 12, 0, 0)


class CalculateRiskScoreTests(unittest.TestCase):
    def test_healthy_new_device_is_low_risk(self):
        result = calculate_risk_score(
            {
                "device_status": "NORMAL",
                "install_date": "2025-01-01",
                "recent_repair_count": 0,
                "open_order_count": 0,
            },
            now=NOW,
        )

        self.assertEqual(result["health_score"], 100)
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["risk_factors"], [])

    def test_repeat_fault_and_urgent_work_is_high_risk(self):
        result = calculate_risk_score(
            {
                "device_status": "FAULT",
                "install_date": "2012-01-01",
                "recent_repair_count": 4,
                "open_order_count": 2,
                "urgent_open_order_count": 1,
                "last_repair_at": "2026-08-20 08:00:00",
            },
            now=NOW,
        )

        self.assertEqual(result["health_score"], 0)
        self.assertEqual(result["risk_level"], "HIGH")
        codes = {factor["code"] for factor in result["risk_factor_details"]}
        self.assertIn("FREQUENT_REPAIRS", codes)
        self.assertIn("URGENT_OPEN_ORDERS", codes)
        self.assertIn("ABNORMAL_DEVICE_STATUS", codes)
        self.assertIn("AGING_DEVICE", codes)

    def test_null_and_dirty_historical_fields_are_safe(self):
        result = calculate_risk_score(
            {
                "device_status": None,
                "install_date": "not-a-date",
                "recent_repair_count": None,
                "open_order_count": "bad-number",
                "last_repair_at": None,
            },
            now=NOW,
        )

        self.assertEqual(result["health_score"], 100)
        self.assertEqual(result["risk_level"], "LOW")

    def test_two_repairs_plus_missing_closure_is_medium_risk(self):
        result = calculate_risk_score(
            {
                "recent_repair_count": 2,
                "incomplete_repair_count": 1,
                "last_repair_at": "2026-06-01",
            },
            now=NOW,
        )

        self.assertEqual(result["risk_score"], 29)
        self.assertEqual(result["health_score"], 71)
        self.assertEqual(result["risk_level"], "MEDIUM")


class BuildRiskReportTests(unittest.TestCase):
    def test_aggregates_devices_and_legacy_location_orders(self):
        devices = [
            {
                "device_id": 10,
                "house_id": 1,
                "house_code": "1302",
                "building_no": "1栋",
                "unit_no": None,
                "room_no": "1302",
                "device_code": "AC-01",
                "device_name": "空调外机",
                "device_type": "hvac",
                "location": "阳台",
                "install_date": "2015-03-01",
                "device_status": "NORMAL",
            }
        ]
        orders = [
            # 精确设备关联：两次近期维修 + 一张紧急待处理工单。
            *[
                {
                    "order_id": order_id,
                    "house_id": 1,
                    "house_code": "1302",
                    "device_id": 10,
                    "location": "阳台",
                    "priority": "NORMAL",
                    "status": "COMPLETED",
                    "created_at": created,
                    "completed_at": created,
                }
                for order_id, created in (
                    (101, "2026-07-01 10:00:00"),
                    (102, "2026-08-10 10:00:00"),
                )
            ],
            {
                "order_id": 103,
                "house_id": 1,
                "house_code": "1302",
                "device_id": 10,
                "location": "阳台",
                "priority": "URGENT",
                "status": "PROCESSING",
                "created_at": "2026-08-30 10:00:00",
                "completed_at": None,
            },
            # 旧数据 device_id 为空，仍应形成一个位置风险目标。
            {
                "order_id": 201,
                "house_id": 1,
                "house_code": "1302",
                "device_id": None,
                "location": "厨房",
                "priority": "NORMAL",
                "status": "COMPLETED",
                "created_at": None,
                "completed_at": "2026-08-01 10:00:00",
            },
        ]
        records = [
            {"repair_order_id": 101, "action_type": "COMPLETE_REPAIR"},
            {"repair_order_id": 102, "action_type": "COMPLETE_REPAIR"},
            # 201 故意缺完工流水，验证历史空数据兼容和闭环风险。
        ]

        report = build_maintenance_risk_report(devices, orders, records, now=NOW)

        self.assertEqual(report["summary"]["total_targets"], 2)
        by_id = {item["target_id"]: item for item in report["risks"]}
        device = by_id["device:10"]
        self.assertEqual(device["recent_repair_count"], 2)
        self.assertEqual(device["open_order_count"], 1)
        self.assertEqual(device["risk_level"], "HIGH")

        location = next(item for item in report["risks"] if item["target_type"] == "LOCATION")
        self.assertEqual(location["location"], "厨房")
        self.assertEqual(location["recent_repair_count"], 1)
        self.assertIn("MISSING_REPAIR_RESULT", {
            factor["code"] for factor in location["risk_factor_details"]
        })
        self.assertEqual(
            report["high_risk_summary"]["count"],
            sum(1 for item in report["risks"] if item["risk_level"] == "HIGH"),
        )

    def test_empty_data_returns_empty_summaries(self):
        report = build_maintenance_risk_report([], [], [], now=NOW)

        self.assertEqual(report["risks"], [])
        self.assertEqual(report["high_risk_summary"]["count"], 0)
        self.assertEqual(report["medium_risk_summary"]["count"], 0)
        self.assertIsNone(report["summary"]["average_health_score"])


class DatabaseAggregationTests(unittest.TestCase):
    def test_house_filter_uses_mysql_placeholders_and_three_bulk_queries(self):
        calls = []
        result_sets = [
            [{"device_id": 1, "house_id": 1, "house_code": "1302"}],
            [],
            [],
        ]

        def fake_query_all(sql, params):
            calls.append((sql, params))
            return result_sets[len(calls) - 1]

        report = get_maintenance_risks(
            "1302", now=NOW, query_all_fn=fake_query_all
        )

        self.assertEqual(len(calls), 3)
        self.assertTrue(all("h.house_code = %s" in sql for sql, _ in calls))
        self.assertTrue(all(params == ("1302",) for _, params in calls))
        self.assertEqual(report["summary"]["total_targets"], 1)


if __name__ == "__main__":
    unittest.main()
