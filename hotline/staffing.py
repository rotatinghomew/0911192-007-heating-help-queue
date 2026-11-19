"""下一班借调计划。

- 只使用本班班表中的空闲合格工位（skills、access 与待处理需求匹配）；
- 本组优先，跨组为借调；抽调后原组每班至少保留一个本组在岗合资格工位（保底）；
- 同一人员不得借往两处；
- 上一班已确认的派工按覆盖时段占用工位，本班不得重新分配；
- 风险高低不改变工位有无：无法落实的需求如实列为缺口。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .common import parse_dt
from .episodes import STATE_WAITING

REASON_NO_TABLE = "本班无班表"
REASON_NO_QUALIFIED = "无合资格空闲工位"
REASON_BUSY = "合格工位已被上一班承诺或本计划占用"
REASON_FLOOR = "抽调将使原组低于保底"
REASON_DOUBLE_LEND = "同一人员不可借往两处"


@dataclass
class Slot:
    slot: str
    worker: str
    group: str
    starts: datetime
    ends: datetime
    skills: frozenset
    access: frozenset
    free: list  # 空闲时段 [start, end)，随计划推进被扣减

    def covers(self, kind: str, access: str) -> bool:
        return kind in self.skills and access in self.access


@dataclass
class Inherited:
    """上一班已确认、本班不可重派的派工。"""

    assignment: str
    slot: str
    worker: str
    group: str
    ticket: str
    episode: str | None
    starts: datetime
    ends: datetime
    confirmed: datetime | None


@dataclass
class Offer:
    episode: str
    slot: str
    worker: str
    group: str
    borrowed: bool
    starts: datetime
    ends: datetime


@dataclass
class Gap:
    episode: str
    starts: datetime
    ends: datetime | None
    reason: str


@dataclass
class Plan:
    shift_start: datetime
    shift_end: datetime | None
    demand: list
    inherited: list
    offers: list
    gaps: list


def _subtract(intervals: list, start: datetime, end: datetime) -> list:
    result = []
    for a, b in intervals:
        if end <= a or start >= b:
            result.append([a, b])
            continue
        if a < start:
            result.append([a, start])
        if end < b:
            result.append([end, b])
    return result


def _keeps_floor(candidate: Slot, slots: list, lent_slots: set, demand: list) -> bool:
    """抽调 candidate 后，原组本班是否仍保留至少一个本组合资格空闲工位。"""
    own_needs = {(e.kind, e.access) for e in demand if e.district == candidate.group}
    kept = 0
    for s in slots:
        if s.group != candidate.group or s.slot == candidate.slot or s.slot in lent_slots:
            continue
        if not s.free:
            continue
        if own_needs:
            if any(k in s.skills and a in s.access for k, a in own_needs):
                kept += 1
        elif s.skills:
            kept += 1
    return kept >= 1


def _find(ep, start, end, slots, used_slots, lent_slots, lent_workers, demand):
    qualified = []
    saw_floor_block = False
    saw_double_lend = False
    for slot in slots:
        if slot.slot in used_slots or not slot.covers(ep.kind, ep.access):
            continue
        cover = None
        for a, b in slot.free:
            if a < end and start < b:
                cover = (max(a, start), min(b, end))
                break
        if cover is None:
            continue
        if slot.group != ep.district:
            if slot.worker in lent_workers:
                saw_double_lend = True
                continue
            if not _keeps_floor(slot, slots, lent_slots, demand):
                saw_floor_block = True
                continue
        key = (slot.group != ep.district, cover[0], slot.slot)  # 本组优先，再按可覆盖先后
        qualified.append((key, slot, cover[0], cover[1]))
    if not qualified:
        if not any(s.covers(ep.kind, ep.access) for s in slots):
            reason = REASON_NO_QUALIFIED
        elif saw_floor_block:
            reason = REASON_FLOOR
        elif saw_double_lend:
            reason = REASON_DOUBLE_LEND
        else:
            reason = REASON_BUSY
        return None, reason
    qualified.sort(key=lambda item: item[0])
    _, slot, cstart, cend = qualified[0]
    return (slot, cstart, cend), None


def plan_shift(tables: dict, episodes: list, at: datetime) -> Plan:
    """为 at 交接后的那一班安排工位。班表中没有该班时，需求全部列为缺口。"""
    slots = []
    for row in tables["shift_staff"]:
        starts, ends = parse_dt(row["starts"]), parse_dt(row["ends"])
        if starts != at:
            continue
        slots.append(Slot(
            slot=row["slot"], worker=row["worker"], group=row["group"],
            starts=starts, ends=ends,
            skills=frozenset(x for x in row["skills"].split(";") if x),
            access=frozenset(x for x in row["access"].split(";") if x),
            free=[[starts, ends]],
        ))
    slots.sort(key=lambda s: s.slot)
    shift_end = max((s.ends for s in slots), default=None)

    by_ticket = {}
    for e in episodes:
        for tid in e.tickets:
            by_ticket[tid] = e

    inherited = []
    if shift_end is not None:
        for row in tables["assignments"]:
            confirmed = parse_dt(row["confirmed"])
            if confirmed is not None and confirmed > at:
                continue
            a0, a1 = parse_dt(row["starts"]), parse_dt(row["ends"])
            if a1 <= at or a0 >= shift_end:
                continue
            slot = next((s for s in slots if s.slot == row["slot"]), None)
            ep = by_ticket.get(row["ticket"])
            inherited.append(Inherited(
                assignment=row["assignment"], slot=row["slot"],
                worker=slot.worker if slot else "未知",
                group=slot.group if slot else "未知",
                ticket=row["ticket"], episode=ep.id if ep else None,
                starts=a0, ends=a1, confirmed=confirmed))
            if slot is not None:
                slot.free = _subtract(slot.free, a0, a1)

    demand = [e for e in episodes if e.state == STATE_WAITING]
    demand.sort(key=lambda e: (-e.wait_hours(at), e.id))

    inherited_by_episode = {}
    for inh in inherited:
        if inh.episode:
            inherited_by_episode.setdefault(inh.episode, []).append(inh)

    offers, gaps = [], []
    used_slots = set()
    lent_slots = set()
    lent_workers = {}
    for ep in demand:
        if shift_end is None:
            gaps.append(Gap(ep.id, at, None, REASON_NO_TABLE))
            continue
        needed = [[at, shift_end]]
        for inh in inherited_by_episode.get(ep.id, []):
            needed = _subtract(needed, inh.starts, inh.ends)
        while needed:
            start, end = needed[0]
            found, reason = _find(ep, start, end, slots, used_slots,
                                  lent_slots, lent_workers, demand)
            if found is None:
                gaps.append(Gap(ep.id, start, end, reason))
                needed.pop(0)
                continue
            slot, cstart, cend = found
            borrowed = slot.group != ep.district
            offers.append(Offer(ep.id, slot.slot, slot.worker, slot.group,
                                borrowed, cstart, cend))
            used_slots.add(slot.slot)
            slot.free = _subtract(slot.free, cstart, cend)
            if borrowed:
                lent_slots.add(slot.slot)
                lent_workers[slot.worker] = ep.district
            needed = _subtract(needed, cstart, cend)
    return Plan(at, shift_end, demand, inherited, offers, gaps)
