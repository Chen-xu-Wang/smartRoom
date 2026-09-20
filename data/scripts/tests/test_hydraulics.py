"""给水水力模型与传感器数据流单元测试（任务 1.5 给水部分）。

运行::

    python -m unittest discover -s data/scripts/tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from math import sqrt
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.hydraulics import ActiveUse, build_network, solve  # noqa: E402
from sim.params import load_params  # noqa: E402
from sim.paths import BUILDING_FILE  # noqa: E402
from sim.water_stream import expand_uses  # noqa: E402

PARAMS = load_params()
HOUSE = next(h for h in json.loads(BUILDING_FILE.read_text(encoding="utf-8"))["houses"] if h["house_id"] == "1302")


def mixer_inlet(state, net):
    return min(state.node_pressure_mpa[p] for p in net.nodes["WS-1302-B-MV"].parents)


class HydraulicsTest(unittest.TestCase):
    def setUp(self):
        self.net = build_network(HOUSE, PARAMS)
        self.p_in = HOUSE["entry_static_pressure_mpa"]

    def test_full_open_shower_flow_in_plausible_range(self):
        q = solve(self.net, [ActiveUse("SHOWER", 1.0, 0.6)], self.p_in).fixture_flow_lps["SHOWER"]
        self.assertTrue(0.12 < q < 0.30, q)

    def test_blockage_lowers_flow_and_raises_upstream_pressure(self):
        clean = solve(self.net, [ActiveUse("SHOWER", 1.0, 0.6)], self.p_in)
        self.net.cv_factor = {"WS-1302-B-SH": 0.5}
        blocked = solve(self.net, [ActiveUse("SHOWER", 1.0, 0.6)], self.p_in)
        self.assertLess(blocked.fixture_flow_lps["SHOWER"], 0.65 * clean.fixture_flow_lps["SHOWER"])
        self.assertGreater(mixer_inlet(blocked, self.net), mixer_inlet(clean, self.net))

    def test_supply_pressure_drop_keeps_flow_coefficient(self):
        normal = solve(self.net, [ActiveUse("SHOWER", 0.8, 0.6)], self.p_in)
        dip = solve(self.net, [ActiveUse("SHOWER", 0.8, 0.6)], self.p_in - 0.06)
        cv = lambda s: s.fixture_flow_lps["SHOWER"] / sqrt(mixer_inlet(s, self.net))  # noqa: E731
        self.assertLess(dip.fixture_flow_lps["SHOWER"], normal.fixture_flow_lps["SHOWER"])
        self.assertAlmostEqual(cv(dip), cv(normal), places=6)

    def test_concurrent_use_shares_upstream_loss(self):
        alone = solve(self.net, [ActiveUse("SHOWER", 1.0, 0.6)], self.p_in).fixture_flow_lps["SHOWER"]
        shared = solve(self.net, [ActiveUse("SHOWER", 1.0, 0.6), ActiveUse("WASHER", 1.0, 0.0)],
                       self.p_in).fixture_flow_lps["SHOWER"]
        self.assertLess(shared, alone)

    def test_same_fixture_uses_are_queued(self):
        t = pd.Timestamp("2026-06-01 20:00:00")
        events = pd.DataFrame([
            {"kind": "WATER", "device": "SHOWER", "start": t, "duration_s": 300.0, "open_fraction": 0.6,
             "mix_temp_c": 40.0, "hot_fraction": None, "volume_l": None},
            {"kind": "WATER", "device": "SHOWER", "start": t + pd.Timedelta(seconds=60), "duration_s": 200.0,
             "open_fraction": 0.7, "mix_temp_c": 40.0, "hot_fraction": None, "volume_l": None},
        ])
        uses = expand_uses(events, self.net, PARAMS, 50)
        self.assertEqual(int(uses.at[1, "start_s"]), int(uses.at[0, "end_s"]))
        self.assertEqual(int(uses.at[1, "end_s"] - uses.at[1, "start_s"]), 200)


if __name__ == "__main__":
    unittest.main()
