"""交接回看：把等候人群、风险证据、借调缺口与更正核对放在同一份回查里。"""
from __future__ import annotations

from .common import fmt_dt, fmt_hours, fmt_pct, parse_dt
from .episodes import STATE_LABELS, STATE_WAITING, build_episodes, corrections
from .risk import assess, backtest, fit_strata
from .staffing import plan_shift

STATE_ORDER = ["waiting", "lost", "restored", "moved"]


def promise_map(policy: dict) -> dict:
    return {k: float(v) for k, v in policy.get("风险承诺小时", {}).items()}


def model_limits(policy: dict) -> tuple:
    limits = policy.get("拟合下限", {})
    return (int(limits.get("每格最小已结样本", 2)),
            float(limits.get("去向缺失占比上限", 0.34)))


def wait_buckets(policy: dict) -> list:
    return [float(x) for x in policy.get("等待分档小时", [8, 16, 24])]


def episodes_section(episodes: list, at, promises: dict) -> list:
    lines = ["一、等候人群（按交接时已知资料还原）"]
    by_state = {}
    for e in episodes:
        by_state.setdefault(e.state, []).append(e)
    for state in STATE_ORDER:
        group = by_state.get(state) or []
        lines.append(f"  {STATE_LABELS[state]} {len(group)} 条")
        for e in sorted(group, key=lambda e: (-e.wait_hours(at), e.id)):
            bits = [f"    {e.id}｜{e.district}/{e.kind}/{e.access}",
                    f"等待起点 {fmt_dt(e.start)}", f"已等 {fmt_hours(e.wait_hours(at))}"]
            promise = promises.get(e.kind)
            if promise is not None:
                over = "，已超承诺" if e.wait_hours(at) > promise else ""
                bits.append(f"承诺 {promise:.0f}h{over}")
            if e.forwarded and e.state == STATE_WAITING:
                bits.append("已转办（仍在等）")
            if e.outcome_at is not None and e.state != STATE_WAITING:
                bits.append(f"结局于 {fmt_dt(e.outcome_at)}")
            lines.append("｜".join(bits))
            for entry in e.evidence:
                lines.append(f"      链·{entry['kind']} {entry['text']}")
    return lines


def risk_section(episodes: list, at, promises: dict, buckets: list,
                 min_sample: int, max_missing: float) -> tuple:
    strata = fit_strata(episodes, at, promises, min_sample, max_missing)
    lines = ["二、超承诺风险（只用交接可知条件；样本不足不套用全市平均）"]
    if not strata:
        lines.append("  交接时没有任何可见样本")
    for (district, kind), st in sorted(strata.items()):
        head = f"  片区 {district}｜类别 {kind}"
        head += f"｜承诺 {st.promise:.0f}h" if st.promise is not None else "｜承诺未配置"
        head += (f"：已结 {st.n_restored + st.n_moved} 例"
                 f"（回暖 {st.n_restored}、先离开 {st.n_moved}）"
                 f"，去向缺失 {st.n_missing}/{st.entered}，仍在等 {st.n_waiting}")
        lines.append(head)
        if not st.determinable:
            lines.append(f"    难定：{st.reason}；不按全市平均顶替")
            continue
        for w0 in [0.0, *buckets]:
            got = assess(st, w0)
            if got.exceed is None:
                lines.append(f"    已等 {w0:.0f}h：难定（{got.reason}）")
            elif got.already_over:
                lines.append(f"    已等 {w0:.0f}h：已超承诺（风险 100%）")
            else:
                lines.append(
                    f"    已等 {w0:.0f}h：超承诺风险 {fmt_pct(got.exceed)}"
                    f"（回暖 {fmt_pct(got.p_restored)}｜先离开 {fmt_pct(got.p_moved)}"
                    f"｜到期仍等 {fmt_pct(got.p_still)}）")
        lines.append(f"    支撑：{'、'.join(st.support)}（{'、'.join(st.waves)}）")
    waiting = [e for e in episodes if e.state == STATE_WAITING]
    lines.append("  当前等候者：")
    if not waiting:
        lines.append("    无")
    for e in sorted(waiting, key=lambda e: (-e.wait_hours(at), e.id)):
        got = assess(strata.get((e.district, e.kind)), e.wait_hours(at))
        if got.exceed is None:
            verdict = f"难定（{got.reason}）"
        elif got.already_over:
            verdict = "已超承诺（风险 100%）"
        else:
            verdict = f"超承诺风险 {fmt_pct(got.exceed)}"
        lines.append(f"    {e.id}｜{e.district}/{e.kind}"
                     f"｜已等 {fmt_hours(e.wait_hours(at))}：{verdict}")
    return lines, strata


def backtest_section(episodes: list, waves: list, at, promises: dict,
                     min_sample: int, max_missing: float) -> list:
    rows = backtest(episodes, waves, at, promises, min_sample, max_missing)
    lines = ["三、寒潮轮回看（拟合未使用该轮，回看接单时预测是否可信）"]
    for row in rows:
        line = (f"  寒潮 {row['wave']}（{row['level']} 级）：可核对 {row['evaluable']} 例"
                f"｜难定 {row['undetermined']}｜结局不可核对 {row['unverifiable']}")
        if row["mean_pred"] is not None:
            line += (f"｜预测均值 {fmt_pct(row['mean_pred'])}"
                     f"，实际超承诺 {fmt_pct(row['observed'])}")
        lines.append(line)
        for d in row["details"]:
            if d["actual"] is None:
                lines.append(f"    {d['episode']}：{d['note']}")
                continue
            pred = "难定" if d["pred"] is None else fmt_pct(d["pred"])
            actual = "超承诺" if d["actual"] else "承诺内"
            note = f"（{d['note']}）" if d["note"] else ""
            lines.append(f"    {d['episode']}：预测 {pred}｜实际 {actual}{note}")
    return lines


def plan_section(tables: dict, episodes: list, at) -> tuple:
    plan = plan_shift(tables, episodes, at)
    lines = ["四、下一班借调"]
    if plan.shift_end is None:
        lines.append(f"  {fmt_dt(at)} 起本班无班表，无法安排工位")
    else:
        lines.append(f"  班次 {fmt_dt(plan.shift_start)}–{fmt_dt(plan.shift_end)}")
    lines.append("  上一班已承诺（不可重派）：")
    inherited = [f"    {i.assignment}：{i.worker}（{i.slot}，{i.group} 组）"
                 f"→ {i.episode or i.ticket}，{fmt_dt(i.starts)}–{fmt_dt(i.ends)}"
                 f"，确认于 {fmt_dt(i.confirmed)}" for i in plan.inherited]
    lines += inherited or ["    无"]
    lines.append("  本班安排（本组优先，跨组为借调）：")
    offers = [f"    {o.episode}：{o.worker}（{o.slot}，{o.group} 组"
              f"{'，借调' if o.borrowed else ''}）{fmt_dt(o.starts)}–{fmt_dt(o.ends)}"
              for o in plan.offers]
    lines += offers or ["    无"]
    lines.append("  无法落实的缺口：")
    gaps = [f"    {g.episode} {fmt_dt(g.starts)}–{fmt_dt(g.ends)}：{g.reason}"
            for g in plan.gaps]
    lines += gaps or ["    无"]
    return lines, plan


def audit_section(tables: dict, at) -> list:
    lines = ["五、更正与核对"]
    found = corrections(tables, at)
    lines.append("  签认更正（后到替换先到，等待起点与服务归属已按更正重算）：")
    if not found:
        lines.append("    无")
    for c in found:
        old, new = c["superseded"], c["superseding"]
        label = "同次停供" if new["relation"] == "same" else "两次停供"
        lines.append(f"    {new['notice']}（{new['known']}）替换"
                     f" {old['notice']}（{old['known']}）："
                     f"{new['left']} 与 {new['right']} 改判为{label}")
    lines.append("  派工核对（旧班次的响应承诺与实际派工仍可查）：")
    seen = False
    for row in tables["assignments"]:
        confirmed = parse_dt(row["confirmed"])
        if confirmed is not None and confirmed > at:
            continue
        seen = True
        lines.append(f"    {row['assignment']}：工位 {row['slot']} → 票 {row['ticket']}，"
                     f"覆盖 {row['starts']}–{row['ends']}，确认于 {row['confirmed']}")
    if not seen:
        lines.append("    无")
    return lines


def build_review(tables: dict, policy: dict, at) -> str:
    promises = promise_map(policy)
    min_sample, max_missing = model_limits(policy)
    buckets = wait_buckets(policy)
    episodes = build_episodes(tables, at)
    lines = [f"供热求助交接回看（资料截至 {fmt_dt(at)}）", ""]
    lines += episodes_section(episodes, at, promises) + [""]
    risk_lines, _ = risk_section(episodes, at, promises, buckets,
                                 min_sample, max_missing)
    lines += risk_lines + [""]
    lines += backtest_section(episodes, tables["cold_waves"], at, promises,
                              min_sample, max_missing) + [""]
    plan_lines, _ = plan_section(tables, episodes, at)
    lines += plan_lines + [""]
    lines += audit_section(tables, at)
    return "\n".join(lines)
