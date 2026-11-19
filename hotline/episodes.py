"""按交接时点已知资料还原等候过程（episode）。

口径：
- 同一住户同一停供（home+outage 相同，或签认 relation=same）只算一条等候过程；
- 同一对票据的后到签认替换早先签认（same/split 以 known 最新者为准），
  明确复暖后的新停供经 split 后另起一条；
- restored、moved 是已确认终点；lost 是随访缺失，不算解除等待；
  forwarded 仅转办，不表示居民已恢复供热，仍在等；
- 是否可见以 known（交接可见时间）为准，等待时长按 at（事件发生时间）计算。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .common import hours_between, parse_dt

RESOLVED_EVENTS = ("restored", "moved")  # 已确认终点：回暖 / 迁出不再需要
LOST_EVENT = "lost"                      # 随访缺失：不能算作正常解除等待
FORWARD_EVENT = "forwarded"              # 仅转办：居民仍在等

STATE_WAITING = "waiting"
STATE_RESTORED = "restored"
STATE_MOVED = "moved"
STATE_LOST = "lost"

STATE_LABELS = {
    STATE_WAITING: "仍在等",
    STATE_RESTORED: "已回暖",
    STATE_MOVED: "迁出不再需要",
    STATE_LOST: "失去跟进（不算解除等待）",
}


@dataclass
class Episode:
    """一条等候过程：同一住户同一次停供从受理到结局（或仍在等）。"""

    tickets: tuple
    home: str
    district: str
    kind: str
    access: str
    wave: str
    sources: tuple
    start: datetime
    state: str
    outcome_at: datetime | None
    forwarded: bool
    evidence: tuple

    @property
    def id(self) -> str:
        return "+".join(self.tickets)

    @property
    def resolved(self) -> bool:
        return self.state in RESOLVED_EVENTS

    def wait_hours(self, at: datetime) -> float:
        if self.start is None:
            return 0.0
        if self.state == STATE_WAITING:
            return max(0.0, hours_between(at, self.start))
        return max(0.0, hours_between(self.outcome_at, self.start))


def _visible(row: dict, at: datetime, field: str = "known") -> bool:
    seen = parse_dt(row.get(field, ""))
    return seen is None or seen <= at


def latest_notices(tables: dict, at: datetime) -> dict:
    """交接时可见的签认，同一对票据以 known 最新者为准。"""
    best = {}
    for row in tables["identity_notices"]:
        if not _visible(row, at):
            continue
        key = frozenset((row["left"], row["right"]))
        stamp = (parse_dt(row["known"]) or datetime.min, row["notice"])
        if key not in best or stamp > best[key][0]:
            best[key] = (stamp, row)
    return {key: row for key, (_, row) in best.items()}


def corrections(tables: dict, at: datetime) -> list:
    """交接时可见的更正：被后到签认替换掉的签认（用于回查核对）。"""
    by_pair = {}
    for row in tables["identity_notices"]:
        if not _visible(row, at):
            continue
        by_pair.setdefault(frozenset((row["left"], row["right"])), []).append(row)
    found = []
    for rows in by_pair.values():
        rows.sort(key=lambda r: (parse_dt(r["known"]) or datetime.min, r["notice"]))
        for old in rows[:-1]:
            found.append({"superseded": old, "superseding": rows[-1]})
    found.sort(key=lambda c: (parse_dt(c["superseding"]["known"]) or datetime.min,
                              c["superseding"]["notice"]))
    return found


def build_episodes(tables: dict, at: datetime) -> list:
    """按 at 时点交接可见的资料还原全部等候过程。"""
    tickets = {}
    for row in tables["intake"]:
        if _visible(row, at):
            tickets[row["ticket"]] = row

    parent = {tid: tid for tid in tickets}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rb < ra:
            ra, rb = rb, ra
        parent[rb] = ra

    # 同一住户同一事由号：渠道补录不另起等候
    by_event = {}
    for row in tickets.values():
        by_event.setdefault((row["home"], row["outage"]), []).append(row["ticket"])
    for tids in by_event.values():
        for other in tids[1:]:
            union(tids[0], other)

    # 签认 same 合并；split 不并（同对先到签认已被 latest_notices 替换）
    notices = latest_notices(tables, at)
    for row in notices.values():
        if row["relation"] == "same" and row["left"] in tickets and row["right"] in tickets:
            union(row["left"], row["right"])

    components = {}
    for tid in tickets:
        components.setdefault(find(tid), []).append(tid)

    followups = {}
    for row in tables["followups"]:
        if _visible(row, at) and row["ticket"] in tickets:
            followups.setdefault(row["ticket"], []).append(row)

    dispatches = {}
    for row in tables["assignments"]:
        if _visible(row, at, "confirmed") and row["ticket"] in tickets:
            dispatches.setdefault(row["ticket"], []).append(row)

    episodes = []
    for tids in components.values():
        tids = sorted(tids)
        members = [tickets[t] for t in tids]
        first = min(members, key=lambda r: (parse_dt(r["at"]) or datetime.max, r["ticket"]))
        events = []
        for tid in tids:
            events.extend(followups.get(tid, []))
        events.sort(key=lambda r: (parse_dt(r["at"]) or datetime.max,
                                   parse_dt(r["known"]) or datetime.max,
                                   r["evidence"]))
        state = STATE_WAITING
        outcome_at = None
        forwarded = False
        for ev in events:
            name = ev["event"]
            if name == FORWARD_EVENT:
                forwarded = True
                continue
            if name in RESOLVED_EVENTS or name == LOST_EVENT:
                state = name
                outcome_at = parse_dt(ev["at"])
                break
        episodes.append(Episode(
            tickets=tuple(tids),
            home=first["home"],
            district=first["district"],
            kind=first["kind"],
            access=first["access"],
            wave=first["wave"],
            sources=tuple(sorted({m["source"] for m in members})),
            start=parse_dt(first["at"]),
            state=state,
            outcome_at=outcome_at,
            forwarded=forwarded,
            evidence=tuple(_evidence(tids, members, notices, events, dispatches)),
        ))
    episodes.sort(key=lambda e: (e.start or datetime.min, e.id))
    return episodes


def _evidence(tids, members, notices, events, dispatches) -> list:
    """该等候过程的证据链：受理、签认、随访、派工，各带发生与交接可见时间。"""
    entries = []

    def add(sort_dt, seq, kind, text):
        entries.append({"sort": (sort_dt or datetime.min, seq), "kind": kind, "text": text})

    for m in members:
        add(parse_dt(m["known"]), m["ticket"], "受理",
            f"{m['ticket']} 经{m['source']}受理（发生 {m['at']}，交接可见 {m['known']}）")
    for n in notices.values():
        if n["left"] in tids or n["right"] in tids:
            label = "同次停供" if n["relation"] == "same" else "两次停供"
            add(parse_dt(n["known"]), n["notice"], "签认",
                f"{n['notice']} 认定 {n['left']} 与 {n['right']} 为{label}（交接可见 {n['known']}）")
    for f in events:
        add(parse_dt(f["known"]), f["evidence"], "随访",
            f"{f['evidence']} {f['ticket']} {f['event']}（发生 {f['at']}，交接可见 {f['known']}）")
    for tid in tids:
        for a in dispatches.get(tid, []):
            add(parse_dt(a["confirmed"]), a["assignment"], "派工",
                f"{a['assignment']} 工位 {a['slot']} 覆盖 {a['starts']}–{a['ends']}"
                f"（确认 {a['confirmed']}）")
    entries.sort(key=lambda e: e["sort"])
    return [{"kind": e["kind"], "text": e["text"]} for e in entries]
