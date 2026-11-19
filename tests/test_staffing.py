"""下一班借调：已承诺不可重派保底、不重复借、缺口如实上报。"""
import unittest
from datetime import datetime
from pathlib import Path

from inspect_inputs import load_tables

from hotline.episodes import Episode, build_episodes
from hotline.staffing import plan_shift

DATA = Path(__file__).resolve().parents[1] / "data"

STAFF = ["slot", "worker", "group", "starts", "ends", "skills", "access"]
ASSIGN = ["assignment", "slot", "ticket", "confirmed", "starts", "ends"]


def at(text):
    return datetime.fromisoformat(text)


def make_episode(eid, district, kind, access, start="2026-02-12T08:00"):
    return Episode(tickets=(eid,), home="H", district=district, kind=kind,
                   access=access, wave="W3", sources=("hotline",),
                   start=at(start), state="waiting", outcome_at=None,
                   forwarded=False, evidence=())


def tables_with(staff, assignments=()):
    return {
        "cold_waves": [], "intake": [], "identity_notices": [], "followups": [],
        "shift_staff": [dict(zip(STAFF, row)) for row in staff],
        "assignments": [dict(zip(ASSIGN, row)) for row in assignments],
    }


def slot(slot_id, worker, group, skills="repair", access="key"):
    return (slot_id, worker, group, "2026-02-12T08:00", "2026-02-12T16:00",
            skills, access)


class StaffingTests(unittest.TestCase):
    def test_real_handover_keeps_inherited_commitment(self):
        tables = load_tables(DATA)
        moment = at("2026-02-12T16:00")
        plan = plan_shift(tables, build_episodes(tables, moment), moment)
        self.assertEqual(plan.shift_end, at("2026-02-13T00:00"))
        inherited = {(i.assignment, i.slot) for i in plan.inherited}
        self.assertIn(("p2", "s4"), inherited)
        # s4 在 16:00–19:30 已被上一班承诺，本计划不得在该时段再派
        for offer in plan.offers:
            if offer.slot == "s4":
                self.assertGreaterEqual(offer.starts, at("2026-02-12T19:30"))
        self.assertEqual(plan.gaps, [])
        covered = {o.episode for o in plan.offers} | {i.episode for i in plan.inherited}
        self.assertEqual(covered, {"t07+t08+t09", "t06", "t10"})

    def test_floor_blocks_lending_last_slot(self):
        tables = tables_with([slot("s1", "A1", "west"), slot("s2", "B1", "east")])
        demand = [make_episode("e1", "west", "repair", "key"),
                  make_episode("e2", "west", "repair", "key")]
        plan = plan_shift(tables, demand, at("2026-02-12T08:00"))
        self.assertEqual(len(plan.offers), 1)
        self.assertFalse(any(o.borrowed for o in plan.offers))
        self.assertEqual(len(plan.gaps), 1)
        self.assertEqual(plan.gaps[0].reason, "抽调将使原组低于保底")

    def test_borrowing_allowed_when_floor_kept(self):
        tables = tables_with([slot("s1", "A1", "west"), slot("s2", "B1", "east"),
                              slot("s3", "B2", "east")])
        demand = [make_episode("e1", "west", "repair", "key"),
                  make_episode("e2", "west", "repair", "key")]
        plan = plan_shift(tables, demand, at("2026-02-12T08:00"))
        borrowed = [o for o in plan.offers if o.borrowed]
        self.assertEqual(len(borrowed), 1)
        self.assertEqual(plan.gaps, [])

    def test_same_worker_not_lent_to_two_places(self):
        tables = tables_with([slot("s1", "B1", "east"), slot("s2", "B1", "east")])
        demand = [make_episode("e1", "west", "repair", "key"),
                  make_episode("e2", "west", "repair", "key")]
        plan = plan_shift(tables, demand, at("2026-02-12T08:00"))
        borrowed = [o for o in plan.offers if o.borrowed]
        self.assertEqual(len(borrowed), 1)
        self.assertEqual(plan.gaps[0].reason, "同一人员不可借往两处")

    def test_unqualified_access_reports_gap(self):
        tables = tables_with([slot("s1", "A1", "west", access="desk")])
        demand = [make_episode("e1", "west", "repair", "key")]
        plan = plan_shift(tables, demand, at("2026-02-12T08:00"))
        self.assertEqual(plan.gaps[0].reason, "无合资格空闲工位")

    def test_no_shift_table_reports_gap(self):
        tables = load_tables(DATA)
        moment = at("2026-02-13T00:00")
        plan = plan_shift(tables, build_episodes(tables, moment), moment)
        self.assertIsNone(plan.shift_end)
        self.assertEqual({g.reason for g in plan.gaps}, {"本班无班表"})


if __name__ == "__main__":
    unittest.main()
