"""用电模型单元测试（任务 1.6 简化版）。

运行::

    python -m unittest discover -s data/scripts/tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim import behavior as bh  # noqa: E402
from sim.electrical import LeakageFault, PhaseVoltageEvent, PowerScenario, WiringFault, generate_power  # noqa: E402
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE, PERSONA_TRUTH_FILE  # noqa: E402

PARAMS = load_params()
START, END = date(2026, 6, 1), date(2026, 6, 20)


class ElectricalModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building = json.loads(BUILDING_FILE.read_text(encoding="utf-8"))
        personas = json.loads(PERSONA_TRUTH_FILE.read_text(encoding="utf-8"))
        cls.frames, cls.profiles = bh.generate(cls.building, personas, PARAMS, 1001,
                                               date.fromisoformat(PARAMS["calendar.main_window_start"]),
                                               date.fromisoformat(PARAMS["calendar.main_window_end"]), {"1302", "1202", "1301"})

    def run_sc(self, sc):
        return generate_power(self.building, self.frames, self.profiles, PARAMS, 1001, START, END, sc, "1302", ["1202", "1301"])

    def test_normal_voltage_within_gb_range_and_no_trips(self):
        m, nb, truth = self.run_sc(PowerScenario("n", ""))
        v = m["CB-1302-MAIN:voltage_v"]
        self.assertTrue(((v > 198) & (v < 235.4)).all())
        self.assertEqual(truth["trips"], [])
        self.assertTrue((m[[c for c in m.columns if c.endswith(":closed")]] == 1).all().all())

    def test_wet_fault_trips_and_retrips_on_reclose(self):
        sc = PowerScenario("w", "", leakage_faults=[LeakageFault("CB-1302-KT", "WET", "2026-06-18 19:05", "2026-06-18 21:30", 34,
                                                                 reclose_times=["2026-06-18 19:15", "2026-06-18 21:35"])])
        m, _, truth = self.run_sc(sc)
        trips = [x for x in truth["trips"] if x["event"] == "TRIP"]
        self.assertEqual([x["at"][11:16] for x in trips], ["19:05", "19:15"])
        rows = m.set_index("ts")
        self.assertGreater(rows.loc["2026-06-18 19:15:00", "CB-1302-KT:residual_ma"], 30)  # 重合闸那一分钟又跳闸，读数保留
        self.assertEqual(rows.loc["2026-06-18 19:30:00", "CB-1302-KT:closed"], 0)
        self.assertEqual(rows.loc["2026-06-18 21:40:00", "CB-1302-KT:closed"], 1)

    def test_phase_event_only_affects_that_phase(self):
        sc = PowerScenario("p", "", phase_events=[PhaseVoltageEvent("L2", "2026-06-10", "2026-06-21", 23, 6, 17)])
        m, nb, _ = self.run_sc(sc)
        t = pd.to_datetime(nb["ts"])
        night = (t >= "2026-06-12") & ((t.dt.hour >= 23) | (t.dt.hour < 6))
        self.assertGreater(nb.loc[night, "1202:voltage_v"].median(), 240)   # 同为 L2
        self.assertLess(nb.loc[night, "1301:voltage_v"].median(), 235)      # L1

    def test_loose_neutral_drop_scales_with_load(self):
        m0, _, _ = self.run_sc(PowerScenario("n", ""))
        m1, _, _ = self.run_sc(PowerScenario("f", "", wiring_faults=[WiringFault("1302", "2026-06-01", "2026-06-02", 1.4)]))
        # 两个场景的丢包行不同，按时间戳对齐后再比较
        both = m0.merge(m1, on="ts", suffixes=("_0", "_1"))
        both = both[pd.to_datetime(both["ts"]) >= "2026-06-03"]
        cur = both["CB-1302-MAIN:current_a_0"].to_numpy()
        drop = (both["CB-1302-MAIN:voltage_v_0"] - both["CB-1302-MAIN:voltage_v_1"]).to_numpy()
        slope = np.polyfit(cur, drop, 1)[0]
        self.assertAlmostEqual(slope, 1.4, delta=0.1)


if __name__ == "__main__":
    unittest.main()
