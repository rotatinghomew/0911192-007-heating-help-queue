"""交接回看文本：进度、证据、缺口与更正核对同时可见。"""
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from inspect_inputs import load_tables

from hotline import cli
from hotline.review import build_review

DATA = Path(__file__).resolve().parents[1] / "data"


def review_at(text):
    tables = load_tables(DATA)
    policy = json.loads((DATA / "policy.json").read_text(encoding="utf-8"))
    return build_review(tables, policy, datetime.fromisoformat(text))


class ReviewTests(unittest.TestCase):
    def test_handover_before_correction(self):
        text = review_at("2026-02-12T16:00")
        self.assertIn("交接回看", text)
        self.assertIn("t07+t08+t09", text)   # 早班尚未更正，三次来电并成一条
        self.assertIn("仍在等", text)
        self.assertIn("失去跟进（不算解除等待）", text)
        self.assertIn("难定", text)           # 覆盖不足的片区不套用全市平均
        self.assertIn("不可重派", text)
        self.assertIn("p2", text)             # 上一班已承诺的支援

    def test_handover_after_correction(self):
        text = review_at("2026-02-13T00:00")
        self.assertIn("t07+t08", text)
        self.assertNotIn("t07+t08+t09", text)
        self.assertIn("已回暖", text)
        self.assertIn("n3", text)             # 更正记录
        self.assertIn("n2", text)
        self.assertIn("p1", text)             # 旧班次派工仍可核对
        self.assertIn("p2", text)

    def test_cli_review_runs(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["review", "--data", str(DATA), "--at", "2026-02-12T16:00"])
        self.assertIn("交接回看", out.getvalue())

    def test_cli_default_at_uses_latest_known(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(["episodes", "--data", str(DATA)])
        text = out.getvalue()
        # 最新 known 为 t12 的 2026-03-04T10:05，此时 t12 才可见
        self.assertIn("t12", text)
        self.assertIn("2026-03-04T10:05", text)


if __name__ == "__main__":
    unittest.main()
