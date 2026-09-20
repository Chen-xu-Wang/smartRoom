"""漏水与用电安全检测、规则引擎单元测试（不连接 MySQL，用合成数据）。

拓扑取自仓库内的扩展档案 sim_building.json（1302）；文件不存在时跳过。
"""
import importlib.util
import json
import math
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.services import event_rules, power_safety as ps, water_leak as wl
from app.services.water_blockage import Stream

ROOT = Path(__file__).resolve().parents[2]
BUILDING_FILE = ROOT / "data" / "processed" / "sim_config" / "sim_building.json"
START = datetime(2026, 6, 1)


def _building():
    return json.loads(BUILDING_FILE.read_text(encoding="utf-8"))


def _validators():
    path = ROOT / "data" / "scripts" / "validate_contracts.py"
    if importlib.util.find_spec("jsonschema") is None or not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("validate_contracts", path)
    vc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vc)
    return vc


def assert_contract(test: unittest.TestCase, event: dict):
    decision = event_rules.decide(event)
    vc = _validators()
    if vc:
        v = vc.build_validators()
        errs = vc.schema_errors(v["event"], event, "event") + vc.schema_errors(v["event_decision"], decision, "decision")
        errs += vc.check_event_pair(event, decision, "pair")
        test.assertEqual(errs, [])
    return decision


@unittest.skipUnless(BUILDING_FILE.exists(), "缺少 sim_building.json")
class WaterLeakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building = _building()
        cls.house = next(h for h in cls.building["houses"] if h["house_id"] == "1302")
        cls.cols = sorted(s["sensor_code"] for s in cls.house["sensors"] if s["type"] in ("FL", "PR"))

    def _stream(self, days=10, leak_from_day=None, leak_lpm=0.3, extra=None):
        """每分钟一行：夜间空闲；从 leak_from_day 起卫生间冷水支路与总表有持续小流量。``extra`` 追加 1 秒行。"""
        ts, cols = [], {c: [] for c in self.cols}
        for m in range(days * 1440):
            t = START + timedelta(minutes=m)
            leak = leak_lpm if leak_from_day is not None and m >= leak_from_day * 1440 else 0.0
            ts.append(t)
            for c in self.cols:
                if c.endswith("PR01") or c.endswith("PR02"):
                    cols[c].append(0.34)
                elif c in ("SN-1302-IN-FL01", "SN-1302-B-FL01"):
                    cols[c].append(leak)
                else:
                    cols[c].append(0.0)
        for t, values in (extra or []):
            ts.append(t)
            for c in self.cols:
                cols[c].append(values.get(c, 0.34 if "PR" in c else 0.0))
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        return Stream([ts[i] for i in order], {c: [v[i] for i in order] for c, v in cols.items()})

    def test_no_leak_no_event(self):
        r = wl.detect_hidden_leak(self._stream(), self.house, self.building["building"])
        self.assertIsNone(r["event"])

    def test_toilet_leak_localized_to_bathroom_cold_branch(self):
        r = wl.detect_hidden_leak(self._stream(leak_from_day=3), self.house, self.building["building"])
        event = r["event"]
        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "HIDDEN_LEAK")
        self.assertEqual(event["evidence"]["consecutive_nights"], 3)
        self.assertEqual(event["location_candidates"][0]["segment_code"], "WS-1302-B-WC")
        self.assertAlmostEqual(event["evidence"]["est_daily_loss_l"], 0.3 * 1440, delta=1)
        d = assert_contract(self, event)
        self.assertEqual(d["workorders"][0]["create_mode"], "DEFERRED")

    def test_hose_burst_detected_and_valve_closed(self):
        t0 = START + timedelta(days=2, hours=14)
        burst = [(t0 + timedelta(seconds=s), {"SN-1302-IN-FL01": 28.0, "SN-1302-K-FL01": 27.8, "SN-1302-K-PR01": 0.03})
                 for s in range(120)]
        r = wl.detect_pipe_burst(self._stream(days=3, extra=burst), self.house, self.building["building"])
        event = r["event"]
        self.assertIsNotNone(event)
        self.assertEqual(event["location_candidates"][0]["segment_code"], "WS-1302-K-HS")
        self.assertEqual(event["control_actions_taken"][0]["action"], "CLOSE_MAIN_VALVE")
        self.assertEqual(event["detected_at"], (t0 + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S+08:00"))
        d = assert_contract(self, event)
        self.assertEqual(d["priority"], "URGENT")
        self.assertEqual(d["workorders"][0]["create_mode"], "IMMEDIATE")

    def test_high_pressure_washer_fill_is_not_burst(self):
        t0 = START + timedelta(days=2, hours=20)
        fill = [(t0 + timedelta(seconds=s), {"SN-1302-IN-FL01": 20.0, "SN-1302-Y-FL01": 20.0, "SN-1302-IN-PR02": 0.33})
                for s in range(120)]
        r = wl.detect_pipe_burst(self._stream(days=3, extra=fill), self.house, self.building["building"])
        self.assertIsNone(r["event"])


@unittest.skipUnless(BUILDING_FILE.exists(), "缺少 sim_building.json")
class PowerSafetyTests(unittest.TestCase):
    NEIGHBORS = ["1202", "1402", "1305", "1301"]

    @classmethod
    def setUpClass(cls):
        cls.building = _building()
        cls.house = next(h for h in cls.building["houses"] if h["house_id"] == "1302")

    def _streams(self, days=30, *, leak=None, rh_high_from=None, trip_at=None, supply_high_from=None, wiring_from=None):
        ts, main, nb = [], {}, {}
        circuits = [c["circuit_code"] for c in self.house["circuits"]]
        for c in circuits:
            main.update({f"{c}:current_a": [], f"{c}:residual_ma": [], f"{c}:closed": []})
        for k in ("CB-1302-MAIN:voltage_v", "CB-1302-MAIN:current_a", ps.RH_COLUMN):
            main[k] = []
        for h in self.NEIGHBORS:
            nb[f"{h}:voltage_v"], nb[f"{h}:current_a"] = [], []
        tripped = False
        for m in range(days * 1440):
            t = START + timedelta(minutes=m)
            day, hour = m // 1440, t.hour + t.minute / 60
            rh = 94.0 if rh_high_from is not None and day >= rh_high_from else 70 + 8 * math.cos(2 * math.pi * (hour - 5) / 24)
            load = 3.0 + (12.0 if 19 <= hour < 21 else 0.0) + (8.0 if t.minute < 10 and hour >= 7 else 0.0)
            bus = 228 - 4 * math.exp(-((hour - 20.5) / 2) ** 2)
            if supply_high_from is not None and day >= supply_high_from and (hour >= 23 or hour < 6):
                bus += 17
            r = 0.12 + (1.4 if wiring_from is not None and day >= wiring_from else 0.0)
            ts.append(t)
            main["CB-1302-MAIN:voltage_v"].append(bus - load * r)
            main["CB-1302-MAIN:current_a"].append(load)
            main[ps.RH_COLUMN].append(rh)
            for c in circuits:
                base = 1.0 + (0.15 * (rh - 60) / 10 if c.endswith(("KT", "BT", "WH")) else 0.0)
                extra = leak(c, day) if leak else 0.0
                closed = 1
                if trip_at and c == trip_at[0] and t >= trip_at[1] and not tripped:
                    extra, closed, tripped = 34.0, 0, True
                elif trip_at and c == trip_at[0] and tripped:
                    extra, closed = 0.0, 0
                main[f"{c}:current_a"].append(load / 7 if closed else 0.0)
                main[f"{c}:residual_ma"].append(base + extra + 0.05 * ((m * 7919) % 5) if (closed or extra) else 0.0)
                main[f"{c}:closed"].append(closed)
            for h in self.NEIGHBORS:
                same = next(x["phase"] for x in self.building["houses"] if x["house_id"] == h) == self.house["phase"]
                v = 228 - 4 * math.exp(-((hour - 20.5) / 2) ** 2) - 2.0 * 0.12
                if same and supply_high_from is not None and day >= supply_high_from and (hour >= 23 or hour < 6):
                    v += 17
                nb[f"{h}:voltage_v"].append(v)
                nb[f"{h}:current_a"].append(2.0)
        return Stream(ts, main), Stream(ts, nb)

    def test_normal_and_humid_season_no_event(self):
        for kwargs in ({}, {"rh_high_from": 16}):
            s, n = self._streams(**kwargs)
            self.assertEqual(ps.detect_leakage(s, self.house, self.building["building"])["events"], [], kwargs)
            self.assertIsNone(ps.detect_voltage(s, n, self.house, self.building)["event"], kwargs)

    def test_gradual_insulation_degradation_warns_before_trip(self):
        s, _ = self._streams(leak=lambda c, d: max(0, d - 15) * 1.5 if c == "CB-1302-BT" else 0.0)
        events = ps.detect_leakage(s, self.house, self.building["building"])["events"]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual((ev["evidence"]["circuit_code"], ev["evidence"]["pattern"]), ("CB-1302-BT", "GRADUAL"))
        self.assertLess(ev["evidence"]["residual_ma_recent"], 24)  # 在实际动作值之前预警
        d = assert_contract(self, ev)
        self.assertIn("验电", "".join(d["workorders"][0]["worker_safety_notice"]))

    def test_wet_socket_trip(self):
        s, _ = self._streams(trip_at=("CB-1302-KT", START + timedelta(days=20, hours=19, minutes=5)))
        events = ps.detect_leakage(s, self.house, self.building["building"])["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["evidence"]["pattern"], "TRIP")
        self.assertEqual(events[0]["control_actions_taken"][0]["action"], "TRIP_CIRCUIT")
        d = assert_contract(self, events[0])
        self.assertEqual(d["priority"], "HIGH")

    def test_supply_side_overvoltage_is_building_event(self):
        s, n = self._streams(supply_high_from=18)
        ev = ps.detect_voltage(s, n, self.house, self.building)["event"]
        self.assertIsNotNone(ev)
        self.assertEqual((ev["scope"], ev["evidence"]["source_inference"], ev["evidence"]["phase_scope"]),
                         ("BUILDING", "SUPPLY", "SINGLE_PHASE"))
        self.assertIn("FRIDGE", [r["appliance"] for r in ev["evidence"]["appliances_at_risk"]])
        self.assertIn("1302", ev["related_houses"])
        assert_contract(self, ev)

    def test_loose_neutral_is_house_wiring(self):
        s, n = self._streams(wiring_from=18)
        ev = ps.detect_voltage(s, n, self.house, self.building)["event"]
        self.assertIsNotNone(ev)
        self.assertEqual((ev["scope"], ev["evidence"]["source_inference"]), ("HOUSE", "HOUSE_WIRING"))
        self.assertGreater(ev["evidence"]["wiring_resistance_ohm"], 1.0)
        assert_contract(self, ev)


if __name__ == "__main__":
    unittest.main()
