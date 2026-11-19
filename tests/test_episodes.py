"""等候过程还原：可见性、合并与更正、各类结局。"""
import unittest
from datetime import datetime
from pathlib import Path

from inspect_inputs import load_tables

from hotline.episodes import build_episodes, corrections

DATA = Path(__file__).resolve().parents[1] / "data"


def at(text):
    return datetime.fromisoformat(text)


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.tables = load_tables(DATA)

    def find(self, episodes, eid):
        for e in episodes:
            if e.id == eid:
                return e
        self.fail(f"没有等候过程 {eid}")

    def test_visibility_follows_known_not_at(self):
        # t09 发生于 2026-02-11T23:00，但 2026-02-12T00:00 才交接可见
        episodes = build_episodes(self.tables, at("2026-02-11T23:30"))
        self.assertNotIn("t09", {t for e in episodes for t in e.tickets})
        episodes = build_episodes(self.tables, at("2026-02-12T00:00"))
        self.assertIn("t09", {t for e in episodes for t in e.tickets})

    def test_morning_merge_then_evening_split(self):
        # 早班按 n1、n2 把 t07/t08/t09 并成一条；f8 回暖 18:00 才可见
        merged = self.find(build_episodes(self.tables, at("2026-02-12T12:00")),
                           "t07+t08+t09")
        self.assertEqual(merged.start, at("2026-02-10T06:15"))
        self.assertEqual(merged.state, "waiting")
        self.assertTrue(merged.forwarded)
        # n3 改判 split 后：第一次停供已回暖，新停供另起
        episodes = build_episodes(self.tables, at("2026-02-13T00:00"))
        first = self.find(episodes, "t07+t08")
        second = self.find(episodes, "t09")
        self.assertEqual(first.state, "restored")
        self.assertEqual(first.outcome_at, at("2026-02-11T12:00"))
        self.assertAlmostEqual(first.wait_hours(at("2026-02-13T00:00")), 29.75)
        self.assertEqual(second.state, "waiting")
        self.assertEqual(second.start, at("2026-02-11T23:00"))

    def test_lost_is_not_resolved(self):
        lost = self.find(build_episodes(self.tables, at("2025-12-06T00:00")), "t03")
        self.assertEqual(lost.state, "lost")
        self.assertFalse(lost.resolved)

    def test_forwarded_still_waiting(self):
        forwarded = self.find(build_episodes(self.tables, at("2026-02-12T16:00")), "t06")
        self.assertEqual(forwarded.state, "waiting")
        self.assertTrue(forwarded.forwarded)

    def test_moved_leaves_waiting(self):
        moved = self.find(build_episodes(self.tables, at("2025-12-04T00:00")), "t02")
        self.assertEqual(moved.state, "moved")
        self.assertTrue(moved.resolved)

    def test_same_home_same_outage_dedupes(self):
        extra = dict(self.tables["intake"][0], ticket="t99",
                     source="property", known="2025-12-01T09:00")
        self.tables["intake"].append(extra)
        episodes = build_episodes(self.tables, at("2025-12-02T00:00"))
        merged = self.find(episodes, "t01+t99")
        self.assertEqual(merged.home, "H1")
        self.assertEqual(merged.start, at("2025-12-01T08:02"))

    def test_corrections_list_superseded_notice(self):
        self.assertEqual(corrections(self.tables, at("2026-02-12T12:00")), [])
        found = corrections(self.tables, at("2026-02-13T00:00"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["superseded"]["notice"], "n2")
        self.assertEqual(found[0]["superseding"]["notice"], "n3")


if __name__ == "__main__":
    unittest.main()
