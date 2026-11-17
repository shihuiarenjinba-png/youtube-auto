# -*- coding: utf-8 -*-
"""Balanced zodiac ordering helpers for recurring ranking content.

Each daily ranking is a no-replacement draw of all 12 signs. Starting with the
2026-09-12 cutover, the No.1/spotlight sign follows shuffled no-replacement
laps: every 12-day lap contains every sign exactly once, then the next lap is
reshuffled. A hard cross-lap cooldown prevents short-gap repeats. Across each
720-day block, every sign still cycles through every rank sixty times.

Dates before the cutover intentionally keep the legacy schedule so historical
videos and the monthly recap continue to agree with what was actually posted.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from functools import lru_cache
from math import gcd
from typing import Any, Dict, Iterable, List, Sequence


_PREFERRED_STEPS = (5, 7, 11)
_DAILY_CYCLE_MULTIPLIER = 60
_LEGACY_BALANCE_VERSION = "v20260829_top_weighted_random"
_STRICT_BALANCE_VERSION = "v20260912_shuffled_prefix_balanced_v3"
_BALANCE_START = date(2026, 8, 29)
_STRICT_CYCLE_START = date(2026, 9, 12)
_STRICT_TOP1_COOLDOWN_DAYS = 3
_STRICT_SHUFFLE_ATTEMPTS = 10_000
_STRICT_LAP_CANDIDATES = 192
_STRICT_FRONT_SPREAD_LIMIT = 2
_TOP1_HARD_COOLDOWN_DAYS = 2
_TOP1_SOFT_COOLDOWN_DAYS = 10
_SCHEDULE_LOOKBACK_DAYS = 14
_TOP_RANK_DEPTH = 6
_POSITION_WEIGHTS = (30, 22, 16, 10, 6, 3)
_SCHEDULE_SAMPLE_SIZE = 160
_SCHEDULE_CHOICE_POOL = 18


def _seed_int(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


def _coprime_step(n: int, seed_text: str) -> int:
    choices = [s for s in _PREFERRED_STEPS if s < n and gcd(s, n) == 1]
    if not choices:
        choices = [s for s in range(1, n) if gcd(s, n) == 1]
    if not choices:
        return 1
    return choices[_seed_int(seed_text) % len(choices)]


def _shuffled_code_values(codes: Sequence[str], seed_text: str) -> List[str]:
    out = list(codes)
    rnd = random.Random(_seed_int(seed_text) % (2 ** 32))
    rnd.shuffle(out)
    return out


def _sign_codes(signs: Sequence[Dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(s.get("code", "")) for s in signs if s.get("code"))


def _by_code(signs: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(s.get("code", "")): s for s in signs if s.get("code")}


def _balanced_row_pool(codes: Sequence[str], block: int,
                       version: str) -> List[List[str]]:
    """Build 720 balanced candidate rows before scheduling them by day.

    Each 12-row lap is a randomized Latin-square slice: every sign appears
    exactly once in every rank inside that lap, but day order and rank offsets
    are randomized so the output does not look like a simple vertical cycle.
    """
    n = len(codes)
    rows: List[List[str]] = []
    for lap in range(_DAILY_CYCLE_MULTIPLIER):
        base = _shuffled_code_values(
            codes, f"daily-zodiac-base:{version}:{block}:{lap}")
        rnd = random.Random(
            _seed_int(f"daily-zodiac-lap:{version}:{block}:{lap}") % (2 ** 32))
        starts = list(range(n))
        rank_offsets = list(range(n))
        rnd.shuffle(starts)
        rnd.shuffle(rank_offsets)
        for start in starts:
            rows.append([base[(start + offset) % n] for offset in rank_offsets])
    rnd = random.Random(
        _seed_int(f"daily-zodiac-pool:{version}:{block}") % (2 ** 32))
    rnd.shuffle(rows)
    return rows


def _schedule_score(row: Sequence[str], history: Sequence[Sequence[str]],
                    top1_counts: Dict[str, int],
                    top3_counts: Dict[str, int],
                    top6_counts: Dict[str, int]) -> int:
    score = 0
    recent = list(history[-_SCHEDULE_LOOKBACK_DAYS:])
    for age, prev in enumerate(reversed(recent), start=1):
        recency = _SCHEDULE_LOOKBACK_DAYS - age + 1
        prev_top = list(prev[:_TOP_RANK_DEPTH])
        if row[0] == prev[0]:
            score += recency * 6000
        elif row[0] in prev_top[:3]:
            score += recency * 900
        elif row[0] in prev_top:
            score += recency * 240
        for rank_idx, code in enumerate(row[:_TOP_RANK_DEPTH]):
            try:
                prev_idx = prev_top.index(code)
            except ValueError:
                continue
            score += recency * _POSITION_WEIGHTS[rank_idx] * _POSITION_WEIGHTS[prev_idx]
            if rank_idx == prev_idx:
                score += recency * 80

    for rank_idx, code in enumerate(row[:_TOP_RANK_DEPTH]):
        weight = _POSITION_WEIGHTS[rank_idx]
        score += top6_counts.get(code, 0) * weight
        if rank_idx < 3:
            score += top3_counts.get(code, 0) * weight * 4
        if rank_idx == 0:
            score += top1_counts.get(code, 0) * weight * 5
    return score


def _pick_scheduled_index(sample: Sequence[int], remaining: Sequence[Sequence[str]],
                          history: Sequence[Sequence[str]],
                          top1_counts: Dict[str, int],
                          top3_counts: Dict[str, int],
                          top6_counts: Dict[str, int],
                          rnd: random.Random) -> int:
    scored = sorted(
        ((idx, _schedule_score(remaining[idx], history, top1_counts,
                               top3_counts, top6_counts))
         for idx in sample),
        key=lambda item: (item[1], rnd.random()))
    pool = scored[:min(len(scored), _SCHEDULE_CHOICE_POOL)]
    weights = [1.0 / ((rank + 1) ** 1.35) for rank in range(len(pool))]
    return rnd.choices([idx for idx, _ in pool], weights=weights, k=1)[0]


def _legacy_top1_sequence(codes: Sequence[str], block: int) -> List[str]:
    """Return the pre-cutover weighted schedule, unchanged for history."""
    rnd = random.Random(
        _seed_int(f"daily-zodiac-top1:{_LEGACY_BALANCE_VERSION}:{block}") % (2 ** 32))
    remaining = {code: _DAILY_CYCLE_MULTIPLIER for code in codes}
    out: List[str] = []
    while any(remaining.values()):
        recent = set(out[-_TOP1_HARD_COOLDOWN_DAYS:])
        candidates = [code for code, count in remaining.items()
                      if count > 0 and code not in recent]
        if not candidates:
            candidates = [code for code, count in remaining.items() if count > 0]
        weights = []
        for code in candidates:
            try:
                distance = len(out) - 1 - max(i for i, c in enumerate(out) if c == code)
            except ValueError:
                distance = _TOP1_SOFT_COOLDOWN_DAYS + 1
            if distance < _TOP1_SOFT_COOLDOWN_DAYS:
                recency_factor = max(0.12, distance / _TOP1_SOFT_COOLDOWN_DAYS)
            else:
                recency_factor = 1.0
            weights.append((remaining[code] ** 1.8) * recency_factor
                           * (0.65 + rnd.random() * 0.7))
        pick = rnd.choices(candidates, weights=weights, k=1)[0]
        out.append(pick)
        remaining[pick] -= 1
    return out


def _is_rotation(candidate: Sequence[str], previous: Sequence[str]) -> bool:
    if len(candidate) != len(previous) or not candidate:
        return False
    doubled = list(previous) + list(previous)
    width = len(candidate)
    return any(list(candidate) == doubled[i:i + width] for i in range(width))


def _lap_respects_cooldown(lap: Sequence[str], history: Sequence[str],
                           cooldown: int) -> bool:
    recent = list(history)
    for code in lap:
        if cooldown and code in recent[-cooldown:]:
            return False
        recent.append(code)
    return True


def _random_cooldown_lap(codes: Sequence[str], history: Sequence[str],
                         cooldown: int, rnd: random.Random) -> List[str]:
    """Draw one random permutation that respects the cross-lap cooldown."""
    prefix: List[str] = []

    def visit(remaining: List[str]) -> bool:
        if not remaining:
            return True
        recent = (list(history) + prefix)[-cooldown:] if cooldown else []
        choices = [code for code in remaining if code not in recent]
        rnd.shuffle(choices)
        for code in choices:
            prefix.append(code)
            next_remaining = list(remaining)
            next_remaining.remove(code)
            if visit(next_remaining):
                return True
            prefix.pop()
        return False

    if not visit(list(codes)):
        raise RuntimeError(
            f"Could not draw a zodiac lap with cooldown={cooldown}")
    return prefix


def _front_balance_score(lap: Sequence[str], front_counts: Dict[str, int],
                         completed_laps: int) -> tuple[int, int]:
    """Score cumulative first-half exposure; lower is more even."""
    front_depth = len(lap) // 2
    after = dict(front_counts)
    for code in lap[:front_depth]:
        after[code] = after.get(code, 0) + 1
    values = list(after.values())
    spread = max(values) - min(values) if values else 0
    # The ideal exposure after k laps is k/2. Multiplying by two keeps this
    # integer-only while penalizing both early and late cumulative bias.
    deviation = sum((count * 2 - completed_laps) ** 2
                    for count in values)
    return spread, deviation


def _strict_top1_sequence(codes: Sequence[str], block: int,
                          recent_history: Sequence[str]) -> List[str]:
    """Return 60 independently shuffled, no-replacement zodiac laps.

    Each lap contains every sign once. Consecutive laps cannot reuse the same
    order or a simple cyclic shift, and a hard cooldown protects the boundary
    between laps. The seed keeps same-day retries reproducible without making
    every 12-day lap follow one permanent routine.
    """
    rnd = random.Random(
        _seed_int(f"daily-zodiac-top1:{_STRICT_BALANCE_VERSION}:{block}") % (2 ** 32))
    cooldown = min(_STRICT_TOP1_COOLDOWN_DAYS, max(0, len(codes) - 1))
    history = list(recent_history)
    previous_lap = history[-len(codes):] if codes else []
    out: List[str] = []
    front_counts = {code: 0 for code in codes}
    front_target = _DAILY_CYCLE_MULTIPLIER // 2

    for lap_index in range(_DAILY_CYCLE_MULTIPLIER):
        candidates: List[tuple[tuple[int, int], List[str]]] = []
        seen: set[tuple[str, ...]] = set()
        remaining_laps = _DAILY_CYCLE_MULTIPLIER - lap_index - 1
        for _ in range(_STRICT_SHUFFLE_ATTEMPTS):
            lap = _random_cooldown_lap(codes, history, cooldown, rnd)
            lap_key = tuple(lap)
            if lap_key in seen:
                continue
            seen.add(lap_key)
            if (len(codes) >= 4 and previous_lap
                    and _is_rotation(lap, previous_lap)):
                continue
            after = dict(front_counts)
            for code in lap[:len(codes) // 2]:
                after[code] += 1
            if any(count > front_target
                   or count + remaining_laps < front_target
                   for count in after.values()):
                continue
            score = _front_balance_score(
                lap, front_counts, lap_index + 1)
            if score[0] <= _STRICT_FRONT_SPREAD_LIMIT:
                candidates.append((score, lap))
            if len(candidates) >= _STRICT_LAP_CANDIDATES:
                break
        if not candidates:
            raise RuntimeError(
                f"Could not build prefix-balanced zodiac lap {lap_index} "
                f"with cooldown={cooldown}")
        candidates.sort(key=lambda item: item[0])
        best_score = candidates[0][0]
        choice_pool = [lap for score, lap in candidates
                       if score == best_score][:_SCHEDULE_CHOICE_POOL]
        lap = rnd.choice(choice_pool)
        out.extend(lap)
        history.extend(lap)
        previous_lap = lap
        for code in lap[:len(codes) // 2]:
            front_counts[code] += 1
    return out


def _strict_balanced_rows(codes: Sequence[str], block: int,
                          top_sequence: Sequence[str]) -> List[List[str]]:
    """Build random-looking rankings balanced inside every 12-day lap.

    A fresh shuffled Latin-square basis is used for every lap. This preserves
    the selected daily leader while making every sign appear exactly once at
    every rank during each lap; balance therefore exists from the beginning,
    rather than appearing only after the full 720-day block.
    """
    n = len(codes)
    rows: List[List[str]] = []
    for lap_index in range(_DAILY_CYCLE_MULTIPLIER):
        top_lap = list(top_sequence[lap_index * n:(lap_index + 1) * n])
        symbol_cycle = _shuffled_code_values(
            codes,
            f"daily-zodiac-symbol-cycle:{_STRICT_BALANCE_VERSION}:{block}:{lap_index}")
        offsets = list(range(1, n))
        rnd = random.Random(_seed_int(
            f"daily-zodiac-rank-offsets:{_STRICT_BALANCE_VERSION}:{block}:{lap_index}"
        ) % (2 ** 32))
        rnd.shuffle(offsets)
        rank_offsets = [0] + offsets
        symbol_index = {code: idx for idx, code in enumerate(symbol_cycle)}
        for top_code in top_lap:
            start = symbol_index[top_code]
            rows.append([
                symbol_cycle[(start + offset) % n]
                for offset in rank_offsets
            ])
    return rows


def _schedule_rows(rows: List[List[str]], block: int, version: str,
                   top_sequence: Sequence[str]) -> List[List[str]]:
    rnd = random.Random(
        _seed_int(f"daily-zodiac-schedule:{version}:{block}") % (2 ** 32))
    groups: Dict[str, List[List[str]]] = {}
    for row in rows:
        if row:
            groups.setdefault(row[0], []).append(row)
    for group in groups.values():
        rnd.shuffle(group)

    out: List[List[str]] = []
    history: List[List[str]] = []
    top1_counts: Dict[str, int] = {}
    top3_counts: Dict[str, int] = {}
    top6_counts: Dict[str, int] = {}
    for top_code in top_sequence:
        remaining = groups[top_code]
        if not remaining:
            continue
        candidate_pool = list(range(len(remaining)))
        if len(candidate_pool) <= _SCHEDULE_SAMPLE_SIZE:
            sample = candidate_pool
        else:
            sample = rnd.sample(candidate_pool, _SCHEDULE_SAMPLE_SIZE)
        best_idx = _pick_scheduled_index(
            sample, remaining, history, top1_counts, top3_counts, top6_counts, rnd)
        row = remaining.pop(best_idx)
        out.append(row)
        history.append(row)
        top1_counts[row[0]] = top1_counts.get(row[0], 0) + 1
        for code in row[:3]:
            top3_counts[code] = top3_counts.get(code, 0) + 1
        for code in row[:6]:
            top6_counts[code] = top6_counts.get(code, 0) + 1
    return out


@lru_cache(maxsize=16)
def _legacy_daily_cycle_order_codes(codes_key: tuple[str, ...],
                                    block: int) -> tuple[tuple[str, ...], ...]:
    pool = _balanced_row_pool(codes_key, block, _LEGACY_BALANCE_VERSION)
    group_codes = tuple(dict.fromkeys(row[0] for row in pool if row))
    top_sequence = _legacy_top1_sequence(group_codes, block)
    ordered = _schedule_rows(
        pool, block, _LEGACY_BALANCE_VERSION, top_sequence)
    return tuple(tuple(row) for row in ordered)


def _legacy_order_codes_for_day(codes_key: tuple[str, ...],
                                day: date) -> tuple[str, ...]:
    cycle_days = len(codes_key) * _DAILY_CYCLE_MULTIPLIER
    block, offset = _cycle_position(day, cycle_days, _BALANCE_START)
    return _legacy_daily_cycle_order_codes(codes_key, block)[offset]


@lru_cache(maxsize=16)
def _strict_daily_cycle_order_codes(codes_key: tuple[str, ...],
                                    block: int) -> tuple[tuple[str, ...], ...]:
    if block == 0:
        recent_history = tuple(
            _legacy_order_codes_for_day(
                codes_key, _STRICT_CYCLE_START - timedelta(days=days))[0]
            for days in range(len(codes_key), 0, -1)
        )
    else:
        previous_rows = _strict_daily_cycle_order_codes(codes_key, block - 1)
        recent_history = tuple(row[0] for row in previous_rows[-len(codes_key):])

    top_sequence = _strict_top1_sequence(codes_key, block, recent_history)
    ordered = _strict_balanced_rows(codes_key, block, top_sequence)
    return tuple(tuple(row) for row in ordered)


def _cycle_position(day: date, cycle_days: int,
                    start: date = _BALANCE_START) -> tuple[int, int]:
    serial = (day - start).days if day >= start else day.toordinal()
    return serial // cycle_days, serial % cycle_days


def balanced_daily_order(signs: Sequence[Dict[str, Any]], day: date) -> List[Dict[str, Any]]:
    """Return a full ranking with strict No.1 rotation after the cutover.

    The output is always one permutation of all signs, like pulling all 12 signs
    from a box without replacement. From 2026-09-12, every aligned 12-day lap
    uses every sign as No.1 exactly once, then reshuffles for the next lap.
    Rank positions remain balanced so every sign gets every rank sixty times
    per 720-day block.
    """
    if not signs:
        return []
    n = len(signs)
    cycle_days = n * _DAILY_CYCLE_MULTIPLIER
    codes_key = _sign_codes(signs)
    if day >= _STRICT_CYCLE_START:
        block, offset = _cycle_position(day, cycle_days, _STRICT_CYCLE_START)
        rows = _strict_daily_cycle_order_codes(codes_key, block)
    else:
        block, offset = _cycle_position(day, cycle_days, _BALANCE_START)
        rows = _legacy_daily_cycle_order_codes(codes_key, block)
    mapping = _by_code(signs)
    ordered_codes = rows[offset]
    return [mapping[c] for c in ordered_codes if c in mapping]


def balanced_topic_order(signs: Sequence[Dict[str, Any]], day: date, topic: str,
                         topic_order: Iterable[str]) -> List[Dict[str, Any]]:
    """Return a topic ranking derived from the day's full zodiac ranking.

    The full daily ranking is the parent order. Each topic takes a different
    window from that parent order, so TOP3 cards stay consistent with the day's
    overall flow while exposure remains balanced across all 15 daily topics.
    """
    if not signs:
        return []
    n = len(signs)
    topics = list(topic_order)
    try:
        topic_index = topics.index(topic)
    except ValueError:
        topic_index = _seed_int(f"{day.isoformat()}:{topic}:index") % n

    if day >= _STRICT_CYCLE_START:
        block, _ = _cycle_position(
            day, n * _DAILY_CYCLE_MULTIPLIER, _STRICT_CYCLE_START)
        step_seed = f"topic-zodiac-step:{_STRICT_BALANCE_VERSION}:{block}"
    else:
        block, _ = _cycle_position(
            day, n * _DAILY_CYCLE_MULTIPLIER, _BALANCE_START)
        step_seed = f"topic-zodiac-step:{block}"
    parent_codes = [str(s.get("code", "")) for s in balanced_daily_order(signs, day)
                    if s.get("code")]
    step = _coprime_step(n, step_seed)
    # Shift topic windows away from the parent No.1 so the visible TOP3 uploads
    # do not keep repeating the same lead sign as the daily all-sign ranking.
    start = (topic_index * step + 1 + topic_index // n) % n

    mapping = _by_code(signs)
    top_codes = [parent_codes[(start + i) % n] for i in range(min(3, n))]
    top_set = set(top_codes)
    rest = [c for c in parent_codes if c not in top_set]
    rest.sort(key=lambda c: _seed_int(f"{day.isoformat()}:{topic}:{c}"),
              reverse=True)
    return [mapping[c] for c in top_codes + rest if c in mapping]
