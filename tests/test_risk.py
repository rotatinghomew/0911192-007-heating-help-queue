"""超承诺风险：分格拟合、难定口径与寒潮轮回看。"""
import unittest
from datetime import datetime
from pathlib import Path

from inspect_inputs import load_tables

from hotline.episodes import build_episodes
from hotline.risk import assess, backtest, fit_strata

DATA = Path(__file__).resolve().parents[1] / "data"
PROMISES = {"repair": 24.0, "check": 10.0}
LATEST = "2026-03-04T10:05"


def at(text):
    return datetime.fromisoformat(text)


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.tables = load_tables(DATA)
        self.episodes = build_episodes(self.tables, at(LATEST))

    def test_west_repair_stratum(self):
        strata = fit_strata(self.episodes, at(LATEST), PROMISES, 2, 0.34)
        st = strata[("west", "repair")]
        self.assertTrue(st.determinable)
        self.assertEqual((st.n_restored, st.n_moved, st.n_missing), (3, 0, 0))
        got = assess(st, 0.0)
        self.assertAlmostEqual(got.exceed, 1 / 3)
        self.assertAlmostEqual(got.p_restored, 2 / 3)
        # 已等 10h 的等候者：只剩 t04 一例超过 24h 才回暖
        self.assertAlmostEqual(assess(st, 10.0).exceed, 0.5)
        # 已等 30h：已超过 24h 承诺
        self.assertTrue(assess(st, 30.0).already_over)

    def test_components_sum_to_one(self):
        strata = fit_strata(self.episodes, at(LATEST), PROMISES, 2, 0.34)
        got = assess(strata[("west", "repair")], 0.0)
        self.assertAlmostEqual(got.p_restored + got.p_moved + got.p_still, 1.0)

    def test_sparse_stratum_is_undetermined_not_city_average(self):
        strata = fit_strata(self.episodes, at(LATEST), PROMISES, 2, 0.34)
        got = assess(strata.get(("east", "check")), 0.0)
        self.assertIsNone(got.exceed)
        self.assertIn("样本", got.reason)

    def test_missing_outcome_gate(self):
        # (west, check)：t05 回暖、t10 失联，去向缺失 1/2 超过上限
        episodes = build_episodes(self.tables, at("2026-02-13T00:00"))
        strata = fit_strata(episodes, at("2026-02-13T00:00"), PROMISES, 1, 0.34)
        st = strata[("west", "check")]
        self.assertFalse(st.determinable)
        self.assertIn("去向缺失", st.reason)
        self.assertIsNone(assess(st, 0.0).exceed)

    def test_backtest_leaves_out_whole_wave(self):
        rows = backtest(self.episodes, self.tables["cold_waves"], at(LATEST),
                        PROMISES, 2, 0.34)
        by_wave = {r["wave"]: r for r in rows}
        self.assertEqual(set(by_wave), {"W1", "W2", "W3", "W4"})
        # W4 留出后 (west, repair) 用 t01、t04 拟合：24h 内回暖率 1/2
        w4 = {d["episode"]: d for d in by_wave["W4"]["details"]}
        self.assertAlmostEqual(w4["t11"]["pred"], 0.5)
        self.assertFalse(w4["t11"]["actual"])
        self.assertIsNone(w4["t12"]["pred"])  # 仍在等，结局不可核对
        # W2 留出后 (west, repair) 用 t01、t11 拟合：承诺内全部回暖
        w2 = {d["episode"]: d for d in by_wave["W2"]["details"]}
        self.assertAlmostEqual(w2["t04"]["pred"], 0.0)
        self.assertTrue(w2["t04"]["actual"])


if __name__ == "__main__":
    unittest.main()
