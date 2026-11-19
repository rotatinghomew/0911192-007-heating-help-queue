"""命令行入口：等候还原、超承诺风险、借调计划与回查。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import parse_dt
from .episodes import build_episodes
from .review import (audit_section, backtest_section, build_review,
                     episodes_section, model_limits, plan_section, promise_map,
                     risk_section, wait_buckets)

try:
    from inspect_inputs import load_tables
except ImportError:  # 从仓库外调用时，把仓库根目录补上
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from inspect_inputs import load_tables


def latest_known(tables: dict):
    stamps = []
    for name, field in (("intake", "known"), ("followups", "known"),
                        ("identity_notices", "known"), ("assignments", "confirmed")):
        for row in tables[name]:
            value = parse_dt(row[field])
            if value is not None:
                stamps.append(value)
    return max(stamps) if stamps else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hotline", description=__doc__)
    parser.add_argument("command", nargs="?", default="review",
                        choices=["review", "episodes", "risk", "plan", "backtest"],
                        help="要输出的部分，默认 review（完整回看）")
    parser.add_argument("--data", type=Path, default=Path("data"), help="资料目录")
    parser.add_argument("--at", default=None,
                        help="交接时点，如 2026-02-12T16:00；缺省取资料中最新 known")
    args = parser.parse_args(argv)
    try:
        tables = load_tables(args.data)
        policy = json.loads((args.data / "policy.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        parser.exit(2, f"资料校验失败：{error}\n")
    try:
        at = parse_dt(args.at) if args.at else latest_known(tables)
    except ValueError:
        parser.exit(2, f"交接时点格式不符：{args.at}\n")
    if at is None:
        parser.exit(2, "无法确定交接时点：请用 --at 指定\n")
    if args.command == "review":
        print(build_review(tables, policy, at))
        return
    promises = promise_map(policy)
    min_sample, max_missing = model_limits(policy)
    episodes = build_episodes(tables, at)
    if args.command == "episodes":
        lines = episodes_section(episodes, at, promises)
    elif args.command == "risk":
        lines, _ = risk_section(episodes, at, promises, wait_buckets(policy),
                                min_sample, max_missing)
    elif args.command == "plan":
        lines, _ = plan_section(tables, episodes, at)
    else:
        lines = backtest_section(episodes, tables["cold_waves"], at, promises,
                                 min_sample, max_missing)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
