"""模拟器基础层单元测试（任务 1.2–1.4）。

运行::

    python -m unittest discover -s data/scripts/tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim import behavior as bh  # noqa: E402
from sim import building as bld  # noqa: E402
from sim.params import ParamsError, load_params  # noqa: E402

PARAMS = load_params()


class ParamsTest(unittest.TestCase):
    def _load(self, text: str):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(text)
        return load_params(Path(f.name))

    def test_every_leaf_has_registered_source(self):
        for leaf in PARAMS.leaves.values():
            self.assertIn(leaf.source, PARAMS.sources, leaf.path)

    def test_missing_source_rejected(self):
        with self.assertRaises(ParamsError):
            self._load("sources: {A: a}\nx:\n  y: {value: 1, unit: ''}\n")

    def test_unregistered_source_rejected(self):
        with self.assertRaises(ParamsError):
            self._load("sources: {A: a}\nx: {value: 1, unit: '', source: B}\n")

    def test_bare_value_rejected(self):
        with self.assertRaises(ParamsError):
            self._load("sources: {A: a}\nx:\n  y: 3\n")

    def test_kitchen_breaker_matches_contract_sample_03(self):
        self.assertEqual(PARAMS["power.breakers.ratings_a"]["KT"], 16)


class BuildingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building, cls.truth = bld.build(PARAMS)

    def test_deterministic(self):
        again, truth = bld.build(PARAMS)
        self.assertEqual(json.dumps(self.building, sort_keys=True), json.dumps(again, sort_keys=True))
        self.assertEqual(self.truth, truth)

    def test_all_self_checks_pass(self):
        failed = [(n, d) for n, ok, d in bld.check(self.building, self.truth, PARAMS) if not ok]
        self.assertEqual(failed, [])

    def test_entry_pressure_zones(self):
        self.assertEqual(bld.entry_pressure(PARAMS, 5)["has_prv"], True)
        self.assertEqual(bld.entry_pressure(PARAMS, 6)["has_prv"], False)
        self.assertEqual(bld.entry_pressure(PARAMS, 12)["supply_zone"], "HIGH")
        self.assertAlmostEqual(bld.entry_pressure(PARAMS, 18)["raw_static_mpa"], 0.2004, places=3)

    def test_persona_truth_not_in_public_file(self):
        self.assertNotIn("persona", json.dumps(self.building, ensure_ascii=False))


class IntervalTest(unittest.TestCase):
    def test_subtract_merge_intersect(self):
        self.assertEqual(bh.subtract([(0, 10)], (3, 5)), [(0, 3), (5, 10)])
        self.assertEqual(bh.subtract([(0, 10)], (0, 10)), [])
        self.assertEqual(bh.merge([(5, 6), (0, 2), (1, 3)]), [(0, 3), (5, 6)])
        self.assertEqual(bh.intersect([(0, 4), (6, 9)], [(3, 7)]), [(3, 4), (6, 7)])

    def test_sun_times_summer_solstice(self):
        sunrise, sunset = bh.sun_times(date(2026, 6, 21), 31.0, 121.0)
        self.assertTrue(4.5 < sunrise < 5.5, sunrise)
        self.assertTrue(13.5 < sunset - sunrise < 14.5, sunset - sunrise)


class BehaviorTest(unittest.TestCase):
    HOUSES = {"1302", "805", "503", "1405"}

    @classmethod
    def setUpClass(cls):
        cls.building, cls.truth = bld.build(PARAMS)
        cls.start = date.fromisoformat(PARAMS["calendar.main_window_start"])
        cls.end = date.fromisoformat(PARAMS["calendar.main_window_end"])
        cls.frames, cls.profiles = bh.generate(cls.building, cls.truth, PARAMS, 2002, cls.start, cls.end, cls.HOUSES)

    def test_reproducible(self):
        again, _ = bh.generate(self.building, self.truth, PARAMS, 2002, self.start, self.end, self.HOUSES)
        self.assertTrue(self.frames["events"].equals(again["events"]))

    def test_presence_intervals_positive_and_non_overlapping(self):
        pr = self.frames["presence"]
        self.assertTrue((pr["end"] > pr["start"]).all())
        for _, grp in pr.sort_values(["start", "end"]).groupby("person_id"):
            self.assertTrue((grp["start"].values[1:] >= grp["end"].values[:-1]).all())

    def test_vacant_house_has_no_residents(self):
        vacant = [h for h, v in self.truth["households"].items() if v["persona"] == "VACANT"][0]
        frames, profiles = bh.generate(self.building, self.truth, PARAMS, 2002, self.start, self.end, {vacant})
        self.assertEqual(profiles[vacant].persons, [])
        self.assertTrue(frames["presence"].empty or set(frames["presence"]["role"]) == {"OWNER"})

    def test_elder_is_care_registered_and_home_more(self):
        home = self.frames["presence"][self.frames["presence"]["state"] == "HOME_AWAKE"]
        hours = ((home["end"] - home["start"]).dt.total_seconds() / 3600).groupby(home["house_id"]).sum()
        self.assertGreater(hours["503"], hours["805"] / 2)


if __name__ == "__main__":
    unittest.main()
