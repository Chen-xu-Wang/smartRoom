"""进水堵塞检测与规则引擎单元测试（不连接 MySQL，不依赖模拟器生成的数据文件）。"""
import importlib.util
import math
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.services import event_rules, water_blockage as wb

START = datetime(2026, 6, 1)
CV_FULL = 0.36       # 花洒全开时的出水能力 L/s/√MPa
HOT_SHARE = 0.6
OPENINGS = [0.45, 0.55, 0.65, 0.5, 0.6, 1.0, 0.4, 0.7, 0.55]

HOUSE = {
    "house_id": "1302", "floor_label": "13层", "layout": "三室两厅一卫", "in_archive": True, "batch_id": "C",
    "supply_network": [
        {"segment_code": "WS-1302-IN-MT", "name": "智能水表", "kind": "METER", "parents": [], "side": "COLD", "area": "IN", "fixture": None},
        {"segment_code": "WS-1302-IN-MV", "name": "电动总阀", "kind": "VALVE", "parents": ["WS-1302-IN-MT"], "side": "COLD", "area": "IN", "fixture": None},
        {"segment_code": "WS-1302-IN-MAIN", "name": "户内主管", "kind": "PIPE", "parents": ["WS-1302-IN-MV"], "side": "COLD", "area": "IN", "fixture": None},
        {"segment_code": "WS-1302-B-C", "name": "卫生间冷水支路", "kind": "PIPE", "parents": ["WS-1302-IN-MAIN"], "side": "COLD", "area": "B", "fixture": None},
        {"segment_code": "WS-1302-B-AVT", "name": "马桶角阀", "kind": "ANGLE_VALVE", "parents": ["WS-1302-B-C"], "side": "COLD", "area": "B", "fixture": None},
        {"segment_code": "WS-1302-B-WC", "name": "马桶进水阀", "kind": "FIXTURE", "parents": ["WS-1302-B-AVT"], "side": "COLD", "area": "B", "fixture": "TOILET"},
        {"segment_code": "WS-1302-WH-FLT", "name": "热水器进水滤网", "kind": "HEATER_FILTER", "parents": ["WS-1302-IN-MAIN"], "side": "COLD", "area": "WH", "fixture": None},
        {"segment_code": "WS-1302-WH", "name": "电热水器", "kind": "HEATER", "parents": ["WS-1302-WH-FLT"], "side": "HOT", "area": "WH", "fixture": None},
        {"segment_code": "WS-1302-B-H", "name": "卫生间热水支路", "kind": "PIPE", "parents": ["WS-1302-WH"], "side": "HOT", "area": "B", "fixture": None},
        {"segment_code": "WS-1302-B-MV", "name": "淋浴混水阀", "kind": "MIXER", "parents": ["WS-1302-B-C", "WS-1302-B-H"], "side": "MIXED", "area": "B", "fixture": None},
        {"segment_code": "WS-1302-B-SH", "name": "花洒头", "kind": "FIXTURE", "parents": ["WS-1302-B-MV"], "side": "MIXED", "area": "B", "fixture": "SHOWER"},
    ],
    "sensors": [
        {"sensor_code": "SN-1302-B-FL01", "type": "FL", "target": "WS-1302-B-C"},
        {"sensor_code": "SN-1302-B-FL02", "type": "FL", "target": "WS-1302-B-H"},
        {"sensor_code": "SN-1302-B-PR01", "type": "PR", "target": "WS-1302-B-MV"},
        {"sensor_code": "SN-1302-IN-PR01", "type": "PR", "target": "WS-1302-IN-MV"},
    ],
    "devices": [
        {"device_code": "EQ-1302-B-02", "name": "花洒", "spec": "HS-200", "install_date": "2026-03-19", "in_archive": True, "segment_code": "WS-1302-B-SH"},
        {"device_code": "EQ-1302-B-04", "name": "淋浴混水阀", "in_archive": False, "segment_code": "WS-1302-B-MV"},
    ],
}
BUILDING = {"building": "1栋", "unit": "1单元"}
COLS = ["SN-1302-B-FL01", "SN-1302-B-FL02", "SN-1302-B-PR01", "SN-1302-IN-PR01"]


def make_stream(days=28, shower_factor=lambda d: 1.0, pressure=lambda d: 0.32, hot_factor=lambda d: 1.0):
    """每天：凌晨 10 分钟空闲静压、2 次马桶补水、3 次淋浴（开度循环变化）。"""
    ts, cols = [], {c: [] for c in COLS}

    def add(t, cold_lpm, hot_lpm, p_mix, p_in):
        ts.append(t)
        for c, v in zip(COLS, (cold_lpm, hot_lpm, p_mix, p_in)):
            cols[c].append(v)

    k = 0
    for d in range(days):
        day = START + timedelta(days=d)
        p = pressure(d)
        for m in range(10):
            add(day + timedelta(hours=3, minutes=m), 0.0, 0.0, p, p)
        for hour in (8, 12):
            q = 0.30 * math.sqrt(p)
            for s in range(40):
                add(day + timedelta(hours=hour, seconds=s), q * 60, 0.0, p - 0.01, p)
        for n in range(3):
            opening = OPENINGS[k % len(OPENINGS)]
            k += 1
            cold = CV_FULL * shower_factor(d) * opening * math.sqrt(p) * (1 - HOT_SHARE)
            hot = CV_FULL * shower_factor(d) * hot_factor(d) * opening * math.sqrt(p) * HOT_SHARE
            t0 = day + timedelta(hours=20, minutes=30 * n)
            for s in range(300):
                add(t0 + timedelta(seconds=s), cold * 60, hot * 60, p - 0.02, p)
    return wb.Stream(ts, cols)


def gradual(start_day=15, end_day=27, end_factor=0.5):
    def f(d):
        if d < start_day:
            return 1.0
        return 1.0 + (end_factor - 1.0) * min(1.0, (d - start_day) / (end_day - start_day))
    return f


class SupplyBlockageDetectionTests(unittest.TestCase):
    def test_no_fault_no_event(self):
        result = wb.detect_supply_blockage(make_stream(), HOUSE, BUILDING)
        self.assertIsNone(result["event"])
        self.assertEqual(result["diagnostics"]["status"], "NO_EVENT")

    def test_pressure_drop_is_not_blockage(self):
        stream = make_stream(pressure=lambda d: 0.32 if d < 16 else 0.22)
        result = wb.detect_supply_blockage(stream, HOUSE, BUILDING)
        self.assertIsNone(result["event"])
        worst = min(p["change_ratio"] for p in result["diagnostics"]["daily"] if p["change_ratio"] is not None)
        self.assertGreater(worst, -0.05)

    def test_gradual_shower_head_blockage_detected_and_localized(self):
        result = wb.detect_supply_blockage(make_stream(shower_factor=gradual()), HOUSE, BUILDING)
        event = result["event"]
        self.assertIsNotNone(event)
        self.assertRegex(event["event_id"], r"^EVT-\d{8}-1302-0001$")
        self.assertEqual(event["event_type"], "SUPPLY_BLOCKAGE")
        self.assertEqual(event["location_candidates"][0]["segment_code"], "WS-1302-B-SH")
        self.assertEqual(event["location_candidates"][0]["device_code"], "EQ-1302-B-02")
        ev = event["evidence"]
        self.assertLessEqual(ev["change_ratio"], -0.30)
        self.assertEqual(ev["trend"], "GRADUAL")
        self.assertEqual(ev["hot_cold"], "BOTH")
        self.assertEqual(ev["same_branch_other_fixtures"], "NORMAL")
        self.assertAlmostEqual(ev["inlet_pressure_change"], 0.0, places=2)
        confidences = [c["confidence"] for c in event["location_candidates"]]
        self.assertEqual(confidences, sorted(confidences, reverse=True))
        self.assertLessEqual(sum(confidences), 1.0)

    def test_hot_side_only_points_to_mixer(self):
        stream = make_stream(hot_factor=lambda d: 1.0 if d < 15 else 0.3)
        event = wb.detect_supply_blockage(stream, HOUSE, BUILDING)["event"]
        self.assertIsNotNone(event)
        self.assertEqual(event["evidence"]["hot_cold"], "HOT")
        self.assertEqual(event["location_candidates"][0]["segment_code"], "WS-1302-B-MV")

    def test_evaluation_continues_after_event_for_recheck(self):
        result = wb.detect_supply_blockage(make_stream(shower_factor=gradual()), HOUSE, BUILDING)
        self.assertEqual(result["diagnostics"]["daily"][-1]["date"], "2026-06-28")
        self.assertTrue(result["diagnostics"]["daily"][-1]["flagged"])

    def test_insufficient_baseline(self):
        result = wb.detect_supply_blockage(make_stream(days=3), HOUSE, BUILDING)
        self.assertIsNone(result["event"])
        self.assertEqual(result["diagnostics"]["status"], "INSUFFICIENT_DATA")


class EventRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event = wb.detect_supply_blockage(make_stream(shower_factor=gradual()), HOUSE, BUILDING)["event"]
        cls.decision = event_rules.decide(cls.event)

    def test_household_blockage_is_deferred_with_resident_notice(self):
        d = self.decision
        self.assertTrue(d["actionable"])
        self.assertEqual(d["priority"], "NORMAL")
        self.assertEqual([n["audience"] for n in d["notices"]], ["RESIDENT"])
        self.assertEqual(d["workorders"][0]["create_mode"], "DEFERRED")
        self.assertEqual(d["workorders"][0]["recheck_after_days"], 3)
        self.assertEqual(d["workorders"][0]["fault_type"], "给排水故障")
        self.assertIsNone(d["escalation"])

    def test_resident_text_has_no_jargon(self):
        content = self.decision["notices"][0]["content"]
        for term in ("Cv", "P90", "基线", "百分位", "tau"):
            self.assertNotIn(term, content)
        self.assertIn("花洒", content)

    def test_unsupported_event_type(self):
        with self.assertRaises(event_rules.UnsupportedEventType):
            event_rules.decide({**self.event, "event_type": "TERMINAL_OVERHEAT"})

    def test_contract_schemas(self):
        validator_path = Path(__file__).resolve().parents[2] / "data" / "scripts" / "validate_contracts.py"
        if importlib.util.find_spec("jsonschema") is None or not validator_path.exists():
            self.skipTest("未安装 jsonschema 或缺少契约目录")
        spec = importlib.util.spec_from_file_location("validate_contracts", validator_path)
        vc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vc)
        validators = vc.build_validators()
        errors = vc.schema_errors(validators["event"], self.event, "event")
        errors += vc.schema_errors(validators["event_decision"], self.decision, "decision")
        errors += vc.check_event_pair(self.event, self.decision, "pair")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
