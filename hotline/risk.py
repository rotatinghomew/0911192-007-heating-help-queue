"""超承诺风险：按片区×服务类别拟合的竞争风险估计。

- 已证实解决（restored）与先出现其他离开原因（moved）分开计；
- lost 是去向缺失：计入缺失占比，超过上限则整格难定；
- 仍在等的按交接时已等时长截尾；
- 拟合只用交接时可见的等候过程与交接可知的条件（片区、类别、已等时长）；
- 样本不足、去向缺失过多或该等待时长无覆盖时返回「难定」，
  不用全市平均顶替本地承诺；
- 寒潮轮回看采用整轮留出：拟合不用该轮，再回看该轮可核对的结局。
"""
from __future__ import annotations

from dataclasses import dataclass

from .episodes import STATE_LOST, STATE_MOVED, STATE_RESTORED

DEFAULT_MIN_SAMPLE = 2
DEFAULT_MAX_MISSING = 0.34


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass
class Stratum:
    """一个片区×服务类别的拟合结果（Aalen–Johansen 式离散估计）。"""

    district: str
    kind: str
    promise: float | None
    entered: int
    n_restored: int
    n_moved: int
    n_missing: int
    n_waiting: int
    steps: tuple      # (t, S(t), CIF_回暖(t), CIF_先离开(t))，按事件时刻阶跃
    support: tuple    # 支撑本次判断的等候过程编号
    waves: tuple      # 支撑来自哪些寒潮轮
    determinable: bool
    reason: str | None

    @property
    def missing_fraction(self) -> float:
        return self.n_missing / self.entered if self.entered else 0.0

    def _value(self, t: float, index: int) -> float:
        value = 1.0 if index == 1 else 0.0
        for step in self.steps:
            if step[0] > t:
                break
            value = step[index]
        return value

    def survival(self, t: float) -> float:
        return self._value(t, 1)

    def cif_restored(self, t: float) -> float:
        return self._value(t, 2)

    def cif_moved(self, t: float) -> float:
        return self._value(t, 3)


def _aj_steps(obs: list) -> list:
    """由 (时长, 结局) 序列估计全因生存与分因累计发生率。"""
    times = sorted({t for t, code in obs if code in ("R", "M")})
    steps = []
    survival, cif_r, cif_m = 1.0, 0.0, 0.0
    for t in times:
        at_risk = sum(1 for ot, _ in obs if ot >= t)
        d_r = sum(1 for ot, code in obs if ot == t and code == "R")
        d_m = sum(1 for ot, code in obs if ot == t and code == "M")
        if at_risk <= 0:
            continue
        cif_r += survival * d_r / at_risk
        cif_m += survival * d_m / at_risk
        survival *= 1 - (d_r + d_m) / at_risk
        steps.append((t, survival, cif_r, cif_m))
    return steps


def fit_strata(episodes: list, at, promises: dict,
               min_sample: int = DEFAULT_MIN_SAMPLE,
               max_missing: float = DEFAULT_MAX_MISSING) -> dict:
    """按（片区, 服务类别）分格拟合。episodes 须为交接时可见的等候过程。"""
    groups = {}
    for e in episodes:
        groups.setdefault((e.district, e.kind), []).append(e)
    strata = {}
    for (district, kind), members in sorted(groups.items()):
        obs = []
        support = []
        waves = []
        n_restored = n_moved = n_missing = n_waiting = 0
        for e in members:
            support.append(e.id)
            if e.wave not in waves:
                waves.append(e.wave)
            if e.state == STATE_RESTORED:
                obs.append((e.wait_hours(at), "R"))
                n_restored += 1
            elif e.state == STATE_MOVED:
                obs.append((e.wait_hours(at), "M"))
                n_moved += 1
            elif e.state == STATE_LOST:
                obs.append((e.wait_hours(at), "X"))  # 去向缺失：截尾并计入缺失
                n_missing += 1
            else:
                obs.append((e.wait_hours(at), "X"))  # 仍在等：按已等时长截尾
                n_waiting += 1
        entered = len(members)
        resolved = n_restored + n_moved
        missing_fraction = n_missing / entered if entered else 0.0
        reason = None
        if resolved < min_sample:
            reason = f"已结样本 {resolved} 例，少于下限 {min_sample}"
        elif missing_fraction > max_missing:
            reason = f"去向缺失占比 {missing_fraction:.0%}，超过上限 {max_missing:.0%}"
        steps = tuple(_aj_steps(obs)) if reason is None else ()
        strata[(district, kind)] = Stratum(
            district=district, kind=kind, promise=promises.get(kind),
            entered=entered, n_restored=n_restored, n_moved=n_moved,
            n_missing=n_missing, n_waiting=n_waiting, steps=steps,
            support=tuple(support), waves=tuple(waves),
            determinable=reason is None, reason=reason)
    return strata


@dataclass
class Assessment:
    """对一名仍在等的住户，在承诺时长内的去向分解。"""

    exceed: float | None        # 超承诺风险；None 表示难定
    reason: str | None
    p_restored: float | None = None   # 承诺内回暖
    p_moved: float | None = None      # 先出现其他离开原因
    p_still: float | None = None      # 到承诺时仍在等
    already_over: bool = False        # 当前已等时长已超过承诺


def assess(stratum: Stratum | None, current_wait: float) -> Assessment:
    if stratum is None:
        return Assessment(None, "该片区与服务类别没有交接时可见的样本")
    if stratum.promise is None:
        return Assessment(None, "承诺时长未配置")
    if not stratum.determinable:
        return Assessment(None, stratum.reason)
    if current_wait >= stratum.promise:
        return Assessment(1.0, None, already_over=True)
    base = stratum.survival(current_wait)
    if base <= 0:
        return Assessment(None, "该等待时长在拟合样本中无覆盖")
    p_r = _clamp((stratum.cif_restored(stratum.promise)
                  - stratum.cif_restored(current_wait)) / base)
    p_m = _clamp((stratum.cif_moved(stratum.promise)
                  - stratum.cif_moved(current_wait)) / base)
    p_s = _clamp(stratum.survival(stratum.promise) / base)
    return Assessment(_clamp(1.0 - p_r), None, p_r, p_m, p_s)


def backtest(episodes: list, waves: list, at, promises: dict,
             min_sample: int = DEFAULT_MIN_SAMPLE,
             max_missing: float = DEFAULT_MAX_MISSING) -> list:
    """整轮寒潮留出：每轮用其余各轮拟合，回看该轮接单时的预测是否可信。"""
    rows = []
    for wave in waves:
        name = wave["wave"]
        train = [e for e in episodes if e.wave != name]
        test = [e for e in episodes if e.wave == name]
        strata = fit_strata(train, at, promises, min_sample, max_missing)
        details = []
        preds, actuals = [], []
        undetermined = unverifiable = 0
        for e in test:
            promise = promises.get(e.kind)
            if e.state != STATE_RESTORED or promise is None:
                unverifiable += 1
                details.append({"episode": e.id, "pred": None, "actual": None,
                                "note": "结局不可核对（未回暖或去向缺失）"})
                continue
            got = assess(strata.get((e.district, e.kind)), 0.0)
            actual = e.wait_hours(at) > promise
            if got.exceed is None:
                undetermined += 1
                details.append({"episode": e.id, "pred": None, "actual": actual,
                                "note": got.reason})
            else:
                preds.append(got.exceed)
                actuals.append(actual)
                details.append({"episode": e.id, "pred": got.exceed, "actual": actual,
                                "note": None})
        rows.append({
            "wave": name,
            "level": wave.get("level", ""),
            "evaluable": len(preds) + undetermined,
            "undetermined": undetermined,
            "unverifiable": unverifiable,
            "mean_pred": sum(preds) / len(preds) if preds else None,
            "observed": sum(actuals) / len(actuals) if actuals else None,
            "details": details,
        })
    return rows
