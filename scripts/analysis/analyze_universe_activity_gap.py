#!/usr/bin/env python3
"""Universe 활동성 사전 필터 보정 — read-only 다일자 실측 분석 (초안).

``docs/40_action_plans/universe_activity_prefilter_measurement_plan.md``
의 P0~P3를 구현한다. 이 스크립트는 **운영 DB에 대한 조회(read-only)만**
수행한다 — 쓰기/마이그레이션/캐시 갱신, 외부 API·KIS 호출은 전혀 하지
않는다.

구현 전 실제 저장소 구조를 확인한 결과, 계획 문서의 가정 중 아래 항목이
실제 스키마/런타임 산출물과 어긋났다. 이 스크립트는 그 차이를 반영해
구현했고, 각 지점에 `[구조 확인 결과]` 주석으로 명시한다.

1. **"실행 단위(run)"를 식별하는 전용 테이블이 없다.** 계획 문서는
   ``load_runs(date_from, date_to, account_alias)``가 명확한 실행 단위
   행을 반환한다고 가정하지만, 이 저장소에는 decision loop의 개별
   호출(사이클)을 기록하는 전용 run 테이블이 없다(``operations_day_
   runs``는 거래일 1행 단위이고, ``universe_freeze_runs``는 계정과
   무관하다). 이 스크립트는 ``trading.decision_contexts.created_at``을
   시간 간격 기준으로 클러스터링해 **파생(derived) 실행 단위**를
   재구성한다 — 근사치이며, 진짜 실행 로그가 아니다.
2. **차단 사유는 ``guardrail_evaluations``가 아니라 ``trade_decisions.
   decision_json.deterministic_trigger.eligibility_reasons``에 있다.**
   ``guardrail_evaluations``는 ``validators.py`` 기반 주문 단계
   validation 결과(사이징/규정 준수 등)를 저장하는 테이블이고,
   ``eligibility_low_average_volume``/``eligibility_low_turnover``/
   ``eligibility_low_relative_activity`` 같은 pre-AI 활동성 차단 사유
   코드는 이 테이블을 전혀 거치지 않는다. 이 셋은 오직
   ``deterministic_trigger_engine.py``의 ``_assess_buy_eligibility()``
   내부에서만 생성되고, 그 결과가 ``trade_decisions.decision_json``에
   직렬화된다. 이 스크립트는 후자만 사용한다.
3. **유니버스 종목/``source_type`` 복원은 ``universe_freeze_run_items``
   대신 ``trade_decisions.source_type``을 직접 사용한다.** 계획 문서는
   ``decision_loop summary/freeze/preview`` 계열을 유니버스 소스로
   지정했지만, ``trade_decisions``에는 이미 각 평가 대상 종목의
   ``source_type``이 컬럼으로 존재해 더 직접적이고 정확하다(그 결정
   순간에 실제로 평가된 종목 집합과 100% 일치). 대신
   ``decision_json.universe_anchor.universe_freeze_run_id``를 통해
   ``universe_freeze_runs``에 대한 참조 메타데이터(freeze_purpose,
   freeze_reused, business_date)는 보조적으로 조인한다.
4. **``market_overlay_enabled`` 플래그는 저장되지 않는다.**
   ``MarketOverlayDiagnostics.enabled``는 API 응답에만 쓰이고 DB에
   저장되지 않는다. 이 스크립트는 해당 실행 단위에 ``source_type=
   'market_overlay'`` 행이 하나라도 있으면 활성으로 **추정**한다 —
   실제 feature-flag 상태가 아니라 결과 기반 추정치임을 명시한다.

read-only 원칙, ``held_position``/``reconciliation_overlay``/
``event_overlay`` 예외 정책, ``relative_activity`` shadow-only 정책은
계획 문서 그대로 유지한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import UUID

# 이 파일은 scripts/analysis/ 아래에 있으므로 저장소 루트는 두 단계 위다.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(_REPO_ROOT / ".env"))

from agent_trading.db.connection import close_pool, create_pool, get_pool  # noqa: E402

KST = timezone(timedelta(hours=9))

# ── [구조 확인 결과 / PLACEHOLDER] ──────────────────────────────────────
#
# 계획 문서에 시간 버킷 경계가 명시돼 있지 않다. KRX 정규장(09:00~15:30
# KST) 관례를 근거로 아래 경계를 임시로 정의한다 — 실제 운영 정책과
# 다를 수 있으므로 다음 턴에서 재확인이 필요하다.
TIME_BUCKET_BOUNDARIES_KST = {
    "pre_open": (None, "09:00"),
    "open_30m": ("09:00", "09:30"),
    "intraday": ("09:30", "15:20"),
    "after_close": ("15:20", None),
}
ALL_TIME_BUCKETS = list(TIME_BUCKET_BOUNDARIES_KST.keys())

# ── [구조 확인 결과 / PLACEHOLDER] ──────────────────────────────────────
#
# "실행 단위(run)"를 식별하는 전용 테이블이 없어, decision_contexts.
# created_at을 시간 간격 기준으로 클러스터링해 파생 run을 재구성한다.
# 이 값(초)은 실제 decision loop 사이클 주기를 실측하지 않은 임시값
# 이다 — 너무 작으면 한 사이클이 여러 run으로 쪼개지고, 너무 크면
# 서로 다른 사이클이 한 run으로 합쳐진다. 다음 턴에서 실제 사이클
# 간격을 실측해 조정해야 한다.
RUN_CLUSTER_GAP_SECONDS = 120

# pre-AI 활동성 차단 사유 3종(deterministic_trigger_engine.py 기준,
# 코드로 직접 확인한 실제 reason code — 가정이 아니라 확인된 사실).
ACTIVITY_BLOCK_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_low_relative_activity",
    }
)

# BUY 경로 평가 대상 source_type(held_position/reconciliation_overlay는
# 계획 문서 지시대로 "실측 대상에는 포함하되 사전 필터 비교군에서는
# 기본 예외"로 별도 취급한다 — 아래 EXEMPT_SOURCE_TYPES 참고).
BUY_PATH_SOURCE_TYPES = frozenset({"core", "event_overlay", "market_overlay"})
EXEMPT_SOURCE_TYPES = frozenset({"held_position", "reconciliation_overlay"})
ALL_SOURCE_TYPES = BUY_PATH_SOURCE_TYPES | EXEMPT_SOURCE_TYPES | frozenset({"manual"})

# 절대 활동성 하한(가설 A/B, 계획 문서 그대로 — 임의 변경하지 않음).
HYPOTHESIS_A_MIN_AVERAGE_VOLUME = 3000.0
HYPOTHESIS_B_MIN_AVERAGE_TURNOVER = 50_000_000.0
# 상대 활동성 shadow 기준(가설 E, 계획 문서 그대로).
HYPOTHESIS_E_MIN_RELATIVE_ACTIVITY = 1.10


# ─────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RunWindow:
    """decision_contexts.created_at 클러스터링으로 파생한 실행 단위.

    [구조 확인 결과] 진짜 run 엔티티가 아니라 시간 간격 기준 근사
    재구성이다 — ``run_id``는 이 스크립트 내부에서만 의미가 있다.
    """

    run_id: str
    business_date: date
    started_at: datetime
    ended_at: datetime
    decision_context_ids: list[UUID]
    time_bucket: str = ""


@dataclass(slots=True)
class DecisionRow:
    """실행 단위 하나에 속한 decision 1건(=symbol 1건)의 통합 행.

    ``build_baseline_rows()``가 여러 원천(유니버스 멤버십, pre-AI
    차단 사유, signal feature)을 여기로 병합한다.
    """

    run_id: str
    business_date: date
    time_bucket: str
    created_at: datetime
    symbol: str
    market_code: str | None
    instrument_id: UUID | None
    source_type: str
    eligibility_passed: bool | None
    buy_candidate: bool | None
    entry_score: float | None
    block_reason: str | None  # None이면 차단 아님(또는 held/reconciliation 등 미평가)
    universe_freeze_run_id: str | None
    freeze_purpose: str | None
    freeze_reused: bool | None
    average_volume_20d: float | None = None
    average_turnover_20d: float | None = None
    volume_surge_ratio: float | None = None
    turnover_surge_ratio: float | None = None
    signal_feature_snapshot_at: datetime | None = None

    @property
    def relative_activity(self) -> float | None:
        vs = self.volume_surge_ratio
        ts = self.turnover_surge_ratio
        if vs is None and ts is None:
            return None
        return max(vs or 0.0, ts or 0.0)

    @property
    def is_pre_ai_activity_blocked(self) -> bool:
        return self.block_reason in ACTIVITY_BLOCK_REASONS

    @property
    def is_new_buy_candidate_scope(self) -> bool:
        """``new_buy_candidate_count``에 포함할 대상인지 — 계획 문서
        정의: "held_position 제외 후 신규 BUY 평가 대상"."""
        return self.source_type != "held_position"


# ─────────────────────────────────────────────────────────────────────
# 시간 버킷 분류
# ─────────────────────────────────────────────────────────────────────


def classify_time_bucket(run_started_at: datetime) -> str:
    """KST 기준 시각을 ``pre_open``/``open_30m``/``intraday``/``after_close``
    로 분류한다.

    [구조 확인 결과 / PLACEHOLDER] 경계값은 위 ``TIME_BUCKET_BOUNDARIES_
    KST``에 정의된 추정치를 그대로 사용한다.
    """
    ts = run_started_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=KST)
    else:
        ts = ts.astimezone(KST)
    hm = ts.hour * 60 + ts.minute
    if hm < 9 * 60:
        return "pre_open"
    if hm < 9 * 60 + 30:
        return "open_30m"
    if hm < 15 * 60 + 20:
        return "intraday"
    return "after_close"


# ─────────────────────────────────────────────────────────────────────
# P0 — 데이터 수집
# ─────────────────────────────────────────────────────────────────────


async def resolve_account_id(conn: Any, account_alias: str) -> UUID:
    row = await conn.fetchrow(
        "SELECT account_id FROM trading.accounts WHERE account_alias = $1",
        account_alias,
    )
    if row is None:
        raise SystemExit(
            f"account_alias='{account_alias}'에 대응하는 account를 찾지 못했습니다"
            " — trading.accounts.account_alias 값을 확인하세요."
        )
    return row["account_id"]


async def load_runs(
    conn: Any,
    date_from: date,
    date_to: date,
    account_id: UUID,
) -> list[RunWindow]:
    """``decision_contexts.created_at``을 클러스터링해 파생 실행 단위를
    만든다.

    [구조 확인 결과] 계획 문서가 가정한 전용 run 테이블이 없어, 이
    함수는 근사 재구성이다. ``RUN_CLUSTER_GAP_SECONDS``보다 간격이
    넓으면 새 run으로 분리한다.
    """
    rows = await conn.fetch(
        """
        SELECT decision_context_id, created_at
        FROM trading.decision_contexts
        WHERE account_id = $1
          AND (created_at AT TIME ZONE 'Asia/Seoul')::date >= $2
          AND (created_at AT TIME ZONE 'Asia/Seoul')::date <= $3
        ORDER BY created_at ASC
        """,
        account_id,
        date_from,
        date_to,
    )
    if not rows:
        return []

    runs: list[RunWindow] = []
    cluster_ids: list[UUID] = []
    cluster_start: datetime | None = None
    cluster_end: datetime | None = None
    prev_ts: datetime | None = None
    gap = timedelta(seconds=RUN_CLUSTER_GAP_SECONDS)

    def _flush() -> None:
        if not cluster_ids or cluster_start is None or cluster_end is None:
            return
        started_kst = cluster_start.astimezone(KST)
        run_id = f"run-{started_kst.strftime('%Y%m%d-%H%M%S')}"
        runs.append(
            RunWindow(
                run_id=run_id,
                business_date=started_kst.date(),
                started_at=cluster_start,
                ended_at=cluster_end,
                decision_context_ids=list(cluster_ids),
                time_bucket=classify_time_bucket(cluster_start),
            )
        )

    for r in rows:
        ts = r["created_at"]
        if prev_ts is not None and (ts - prev_ts) > gap:
            _flush()
            cluster_ids = []
            cluster_start = None
        if cluster_start is None:
            cluster_start = ts
        cluster_end = ts
        cluster_ids.append(r["decision_context_id"])
        prev_ts = ts
    _flush()

    return runs


async def fetch_run_decision_rows(conn: Any, run: RunWindow) -> list[Any]:
    """실행 단위(run)에 속한 decision들을 유니버스 멤버십·pre-AI 차단
    사유가 함께 담긴 raw row로 한 번에 조회한다.

    [구조 확인 결과] ``guardrail_evaluations``가 아니라
    ``trade_decisions.decision_json``에서 직접 추출한다.
    """
    return await conn.fetch(
        """
        SELECT
            td.symbol,
            td.market AS market_code,
            td.instrument_id,
            td.source_type,
            td.created_at,
            td.decision_json->'deterministic_trigger'->>'eligibility_passed'
                AS eligibility_passed,
            td.decision_json->'deterministic_trigger'->>'buy_candidate'
                AS buy_candidate,
            td.decision_json->'deterministic_trigger'->>'entry_score'
                AS entry_score,
            td.decision_json->'deterministic_trigger'->'eligibility_reasons'
                AS eligibility_reasons,
            td.decision_json->'universe_anchor'->>'universe_freeze_run_id'
                AS universe_freeze_run_id,
            td.decision_json->'universe_anchor'->>'freeze_purpose'
                AS freeze_purpose,
            td.decision_json->'universe_anchor'->>'freeze_reused'
                AS freeze_reused
        FROM trading.trade_decisions td
        WHERE td.decision_context_id = ANY($1::uuid[])
        ORDER BY td.symbol
        """,
        run.decision_context_ids,
    )


def load_universe_members(raw_rows: Sequence[Any]) -> list[dict[str, Any]]:
    """raw row에서 유니버스 멤버십(symbol/source_type)만 추출한다.

    별도 DB 조회를 추가하지 않고 ``fetch_run_decision_rows()`` 결과를
    재사용한다 — ``trade_decisions.source_type``이 이미 그 결정 순간의
    평가 대상 종목 집합과 1:1로 대응하기 때문이다(위 상단 docstring
    3번 참고).
    """
    return [
        {
            "symbol": r["symbol"],
            "market_code": r["market_code"],
            "instrument_id": r["instrument_id"],
            "source_type": r["source_type"],
        }
        for r in raw_rows
    ]


def load_pre_ai_blocks(raw_rows: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """raw row에서 pre-AI eligibility 차단 사유를 symbol 기준으로
    복원한다.

    ``eligibility_reasons`` 리스트는 통과 플래그가 먼저 쌓이고 마지막에
    실제 차단 사유가 append된 뒤 반환되는 구조다(코드 확인 사실) — 따라서
    "실제 차단 사유"는 리스트의 **마지막 원소**다.
    """
    result: dict[str, dict[str, Any]] = {}
    for r in raw_rows:
        reasons = r["eligibility_reasons"]
        if isinstance(reasons, str):
            reasons = json.loads(reasons)
        last_reason = (reasons or [None])[-1]
        eligibility_passed = r["eligibility_passed"]
        block_reason = None
        if eligibility_passed == "false":
            block_reason = last_reason
        result[r["symbol"]] = {
            "eligibility_passed": (
                None if eligibility_passed is None else eligibility_passed == "true"
            ),
            "buy_candidate": (
                None if r["buy_candidate"] is None else r["buy_candidate"] == "true"
            ),
            "entry_score": (
                float(r["entry_score"]) if r["entry_score"] is not None else None
            ),
            "block_reason": block_reason,
        }
    return result


async def load_signal_features(
    conn: Any,
    instrument_created_at_pairs: Sequence[tuple[UUID, datetime]],
) -> dict[tuple[UUID, datetime], dict[str, Any]]:
    """각 (instrument_id, decision 시각) 쌍에 대해 그 시각 이전(as-of)
    최신 signal feature snapshot을 조인한다.

    다일자 과거 실측이므로 "현재 최신값"이 아니라 **그 결정 시점에
    실제로 존재했던 snapshot**을 골라야 정확하다 — 단순 최신값 조인은
    미래 데이터 유출(look-ahead bias)이 된다.
    """
    if not instrument_created_at_pairs:
        return {}

    result: dict[tuple[UUID, datetime], dict[str, Any]] = {}
    seen: set[tuple[UUID, datetime]] = set()
    unique_pairs = [p for p in instrument_created_at_pairs if not (p in seen or seen.add(p))]

    for instrument_id, created_at in unique_pairs:
        row = await conn.fetchrow(
            """
            SELECT snapshot_at, average_volume_20d, average_turnover_20d,
                   volume_surge_ratio, turnover_surge_ratio
            FROM trading.signal_feature_snapshots
            WHERE instrument_id = $1
              AND timeframe = '1d'
              AND snapshot_at <= $2
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            instrument_id,
            created_at,
        )
        if row is None:
            continue
        result[(instrument_id, created_at)] = {
            "average_volume_20d": (
                float(row["average_volume_20d"])
                if row["average_volume_20d"] is not None
                else None
            ),
            "average_turnover_20d": (
                float(row["average_turnover_20d"])
                if row["average_turnover_20d"] is not None
                else None
            ),
            "volume_surge_ratio": (
                float(row["volume_surge_ratio"])
                if row["volume_surge_ratio"] is not None
                else None
            ),
            "turnover_surge_ratio": (
                float(row["turnover_surge_ratio"])
                if row["turnover_surge_ratio"] is not None
                else None
            ),
            "snapshot_at": row["snapshot_at"],
        }
    return result


async def build_baseline_rows(
    conn: Any,
    runs: Sequence[RunWindow],
) -> list[DecisionRow]:
    """run 목록을 순회하며 유니버스 멤버십·pre-AI 차단 사유·signal
    feature를 병합해 통합 ``DecisionRow`` 리스트를 만든다."""
    all_rows: list[DecisionRow] = []

    for run in runs:
        raw_rows = await fetch_run_decision_rows(conn, run)
        if not raw_rows:
            continue
        blocks = load_pre_ai_blocks(raw_rows)

        pairs = [
            (r["instrument_id"], r["created_at"])
            for r in raw_rows
            if r["instrument_id"] is not None
        ]
        features = await load_signal_features(conn, pairs)

        for r in raw_rows:
            symbol = r["symbol"]
            block_info = blocks.get(symbol, {})
            feat = (
                features.get((r["instrument_id"], r["created_at"]))
                if r["instrument_id"] is not None
                else None
            ) or {}

            all_rows.append(
                DecisionRow(
                    run_id=run.run_id,
                    business_date=run.business_date,
                    time_bucket=run.time_bucket,
                    created_at=r["created_at"],
                    symbol=symbol,
                    market_code=r["market_code"],
                    instrument_id=r["instrument_id"],
                    source_type=r["source_type"],
                    eligibility_passed=block_info.get("eligibility_passed"),
                    buy_candidate=block_info.get("buy_candidate"),
                    entry_score=block_info.get("entry_score"),
                    block_reason=block_info.get("block_reason"),
                    universe_freeze_run_id=r["universe_freeze_run_id"],
                    freeze_purpose=r["freeze_purpose"],
                    freeze_reused=(
                        None
                        if r["freeze_reused"] is None
                        else r["freeze_reused"] == "true"
                    ),
                    average_volume_20d=feat.get("average_volume_20d"),
                    average_turnover_20d=feat.get("average_turnover_20d"),
                    volume_surge_ratio=feat.get("volume_surge_ratio"),
                    turnover_surge_ratio=feat.get("turnover_surge_ratio"),
                    signal_feature_snapshot_at=feat.get("snapshot_at"),
                )
            )

    return all_rows


def infer_market_overlay_enabled(rows: Sequence[DecisionRow]) -> dict[str, bool]:
    """run_id -> market_overlay 활성 추정(결과 기반 추정치, 실제
    feature-flag 상태 아님 — 상단 docstring 4번 참고)."""
    by_run: dict[str, bool] = defaultdict(bool)
    for r in rows:
        if r.source_type == "market_overlay":
            by_run[r.run_id] = True
    return dict(by_run)


# ─────────────────────────────────────────────────────────────────────
# 통계 보조 함수
# ─────────────────────────────────────────────────────────────────────


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


def _feature_percentiles(rows: Sequence[DecisionRow], attr: str) -> dict[str, float | None]:
    values = [v for r in rows if (v := getattr(r, attr)) is not None]
    return {
        "p10": _percentile(values, 0.10),
        "p25": _percentile(values, 0.25),
        "p50": _percentile(values, 0.50),
        "n": len(values),
    }


# ─────────────────────────────────────────────────────────────────────
# P1 — baseline 지표 계산
# ─────────────────────────────────────────────────────────────────────


def build_baseline_summary(rows: Sequence[DecisionRow]) -> dict[str, Any]:
    buy_path_rows = [r for r in rows if r.is_new_buy_candidate_scope]
    new_buy_candidate_count = len(buy_path_rows)
    blocked_rows = [r for r in buy_path_rows if r.is_pre_ai_activity_blocked]
    pre_ai_activity_block_count = len(blocked_rows)

    reason_counts = Counter(r.block_reason for r in blocked_rows)

    by_source_type: dict[str, dict[str, Any]] = {}
    for source_type in sorted({r.source_type for r in buy_path_rows}):
        scoped = [r for r in buy_path_rows if r.source_type == source_type]
        blocked_scoped = [r for r in scoped if r.is_pre_ai_activity_blocked]
        by_source_type[source_type] = {
            "n": len(scoped),
            "blocked": len(blocked_scoped),
            "block_rate": round(len(blocked_scoped) / len(scoped), 4) if scoped else None,
        }

    by_time_bucket: dict[str, dict[str, Any]] = {}
    for bucket in ALL_TIME_BUCKETS:
        scoped = [r for r in buy_path_rows if r.time_bucket == bucket]
        blocked_scoped = [r for r in scoped if r.is_pre_ai_activity_blocked]
        by_time_bucket[bucket] = {
            "n": len(scoped),
            "blocked": len(blocked_scoped),
            "block_rate": round(len(blocked_scoped) / len(scoped), 4) if scoped else None,
        }

    return {
        "universe_count": len(rows),
        "new_buy_candidate_count": new_buy_candidate_count,
        "pre_ai_activity_block_count": pre_ai_activity_block_count,
        "pre_ai_activity_block_rate": (
            round(pre_ai_activity_block_count / new_buy_candidate_count, 4)
            if new_buy_candidate_count
            else None
        ),
        "reason_distribution": dict(reason_counts),
        "block_rate_by_source_type": by_source_type,
        "block_rate_by_time_bucket": by_time_bucket,
        "feature_distribution": {
            "average_volume_20d": _feature_percentiles(buy_path_rows, "average_volume_20d"),
            "average_turnover_20d": _feature_percentiles(buy_path_rows, "average_turnover_20d"),
        },
    }


# ─────────────────────────────────────────────────────────────────────
# P2 — 가설 시뮬레이션(공용 함수 + 가설별 predicate)
# ─────────────────────────────────────────────────────────────────────


def simulate_filter_hypothesis(
    rows: Sequence[DecisionRow],
    hypothesis_name: str,
    predicate: Callable[[DecisionRow], bool],
    *,
    scope: Callable[[DecisionRow], bool] | None = None,
) -> dict[str, Any]:
    """가설 하나를 시뮬레이션한다 — 새 가설 추가는 ``predicate``
    (제외 여부 판정 함수)와 ``scope``(적용 대상 제한, 예: core만)만
    새로 작성하면 된다.

    - ``predicate(row) == True`` 면 이 가설의 universe 사전 필터에
      의해 그 종목이 애초에 평가 대상에서 제외된다고 가정한다.
    - ``EXEMPT_SOURCE_TYPES``(``held_position``/``reconciliation_
      overlay``)는 계획 문서 지시대로 항상 예외로 두어, 어떤 가설도
      이 종목들을 제외 대상으로 세지 않는다.
    """
    buy_path_rows = [r for r in rows if r.is_new_buy_candidate_scope]
    applicable = [r for r in buy_path_rows if r.source_type not in EXEMPT_SOURCE_TYPES]
    if scope is not None:
        applicable = [r for r in applicable if scope(r)]

    excluded = [r for r in applicable if predicate(r)]
    excluded_symbols = {(r.run_id, r.symbol) for r in excluded}

    currently_blocked = [r for r in applicable if r.is_pre_ai_activity_blocked]
    currently_blocked_keys = {(r.run_id, r.symbol) for r in currently_blocked}

    # 차단 감소량: 가설로 제외된 것 중 "지금도 pre-AI 활동성으로 차단되던" 것.
    block_reduction = len(excluded_symbols & currently_blocked_keys)

    # 후보 손실: 가설로 제외됐지만 실제로는 활동성 차단이 아니었던(=멀쩡한
    # 후보였을 수 있는) 것.
    candidate_loss_keys = excluded_symbols - currently_blocked_keys
    candidate_loss_count = len(candidate_loss_keys)

    remaining_after_filter = len(applicable) - len(excluded_symbols)
    remaining_still_blocked = len(currently_blocked_keys - excluded_symbols)
    simulated_block_rate_after_filter = (
        round(remaining_still_blocked / remaining_after_filter, 4)
        if remaining_after_filter > 0
        else None
    )

    efficiency_score = (
        round(block_reduction / candidate_loss_count, 4)
        if candidate_loss_count > 0
        else (None if block_reduction == 0 else float("inf"))
    )

    return {
        "hypothesis": hypothesis_name,
        "applicable_population": len(applicable),
        "simulated_universe_filtered_count": len(excluded_symbols),
        "simulated_activity_block_reduction": block_reduction,
        "simulated_candidate_loss_count": candidate_loss_count,
        "simulated_candidate_loss_rate": (
            round(candidate_loss_count / len(applicable), 4) if applicable else None
        ),
        "simulated_block_rate_after_filter": simulated_block_rate_after_filter,
        "baseline_block_rate": (
            round(len(currently_blocked_keys) / len(applicable), 4) if applicable else None
        ),
        "efficiency_score": efficiency_score,
    }


def _hypothesis_a_predicate(row: DecisionRow) -> bool:
    v = row.average_volume_20d
    return v is not None and v < HYPOTHESIS_A_MIN_AVERAGE_VOLUME


def _hypothesis_b_predicate(row: DecisionRow) -> bool:
    v = row.average_turnover_20d
    return v is not None and v < HYPOTHESIS_B_MIN_AVERAGE_TURNOVER


def _hypothesis_c_predicate(row: DecisionRow) -> bool:
    return _hypothesis_a_predicate(row) or _hypothesis_b_predicate(row)


def _core_scope(row: DecisionRow) -> bool:
    return row.source_type == "core"


def measure_shadow_relative_activity(rows: Sequence[DecisionRow]) -> dict[str, Any]:
    """가설 E — shadow-only 관찰. 정책 반영/제외 시뮬레이션은 하지
    않고 분포만 측정한다(계획 문서 지시대로 universe 정책에 바로
    반영하지 않음)."""
    buy_path_rows = [r for r in rows if r.is_new_buy_candidate_scope]
    applicable = [r for r in buy_path_rows if r.source_type not in EXEMPT_SOURCE_TYPES]
    values = [r.relative_activity for r in applicable if r.relative_activity is not None]
    fail_count = sum(1 for v in values if v < HYPOTHESIS_E_MIN_RELATIVE_ACTIVITY)
    return {
        "hypothesis": "E_relative_activity_shadow",
        "mode": "shadow_only_no_policy_change",
        "applicable_population": len(applicable),
        "measured_n": len(values),
        "relative_activity_fail_count": fail_count,
        "relative_activity_fail_rate": (
            round(fail_count / len(values), 4) if values else None
        ),
        "distribution": {
            "p10": _percentile(values, 0.10),
            "p25": _percentile(values, 0.25),
            "p50": _percentile(values, 0.50),
        },
        "note": (
            "relative_activity는 시점 민감성이 높아 계획 문서 지시대로 "
            "universe 정책에 바로 반영하지 않는다 — 여기서는 분포만 관측한다."
        ),
    }


def run_all_hypotheses(rows: Sequence[DecisionRow]) -> list[dict[str, Any]]:
    results = [
        simulate_filter_hypothesis(rows, "A_min_average_volume", _hypothesis_a_predicate),
        simulate_filter_hypothesis(rows, "B_min_average_turnover", _hypothesis_b_predicate),
        simulate_filter_hypothesis(rows, "C_absolute_activity_combined", _hypothesis_c_predicate),
        simulate_filter_hypothesis(
            rows,
            "D_absolute_activity_core_only",
            _hypothesis_c_predicate,
            scope=_core_scope,
        ),
    ]
    results.append(measure_shadow_relative_activity(rows))
    return results


# ─────────────────────────────────────────────────────────────────────
# 요약표
# ─────────────────────────────────────────────────────────────────────


def summarize_daily(rows: Sequence[DecisionRow]) -> list[dict[str, Any]]:
    by_date: dict[date, list[DecisionRow]] = defaultdict(list)
    for r in rows:
        by_date[r.business_date].append(r)

    out: list[dict[str, Any]] = []
    for business_date in sorted(by_date):
        day_rows = by_date[business_date]
        summary = build_baseline_summary(day_rows)
        out.append({"business_date": business_date.isoformat(), **summary})
    return out


def summarize_by_source_type(rows: Sequence[DecisionRow]) -> dict[str, Any]:
    buy_path_rows = [r for r in rows if r.is_new_buy_candidate_scope]
    out: dict[str, Any] = {}
    for source_type in sorted({r.source_type for r in buy_path_rows}):
        scoped = [r for r in buy_path_rows if r.source_type == source_type]
        blocked = [r for r in scoped if r.is_pre_ai_activity_blocked]
        out[source_type] = {
            "n": len(scoped),
            "blocked": len(blocked),
            "block_rate": round(len(blocked) / len(scoped), 4) if scoped else None,
            "reason_distribution": dict(Counter(r.block_reason for r in blocked)),
        }
    return out


def summarize_by_time_bucket(rows: Sequence[DecisionRow]) -> dict[str, Any]:
    buy_path_rows = [r for r in rows if r.is_new_buy_candidate_scope]
    out: dict[str, Any] = {}
    for bucket in ALL_TIME_BUCKETS:
        scoped = [r for r in buy_path_rows if r.time_bucket == bucket]
        blocked = [r for r in scoped if r.is_pre_ai_activity_blocked]
        out[bucket] = {
            "n": len(scoped),
            "blocked": len(blocked),
            "block_rate": round(len(blocked) / len(scoped), 4) if scoped else None,
        }
    return out


# ─────────────────────────────────────────────────────────────────────
# P3 — 권고안 초안
# ─────────────────────────────────────────────────────────────────────


def build_recommendation(hypotheses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """효율 점수(``efficiency_score``) 기준 권장/보류/기각 초안을
    자동 생성한다. **이 결과는 초안이며, 최종 판단은 사용자가 한다**
    — 계획 문서의 해석 기준(가설 D가 가장 낮은 손실률이면 1순위)을
    코드로 옮긴 것일 뿐이다."""
    recommended: list[str] = []
    hold: list[str] = []
    rejected: list[str] = []

    for h in hypotheses:
        name = h["hypothesis"]
        if h.get("mode") == "shadow_only_no_policy_change":
            hold.append(name)
            continue

        loss_count = h.get("simulated_candidate_loss_count")
        block_reduction = h.get("simulated_activity_block_reduction")
        if loss_count is None or block_reduction is None:
            hold.append(name)
            continue

        if block_reduction <= 0:
            rejected.append(name)
        elif loss_count == 0:
            recommended.append(name)
        else:
            eff = h.get("efficiency_score")
            if eff is not None and eff != float("inf") and eff >= 3.0:
                recommended.append(name)
            else:
                hold.append(name)

    return {
        "recommended": recommended,
        "hold": hold,
        "rejected": rejected,
        "note": (
            "efficiency_score >= 3.0(차단 감소량이 후보 손실의 3배 이상)을 "
            "권장 임계값으로 임시 사용했다 — 계획 문서에 정량 임계값이 "
            "명시돼 있지 않아 이 스크립트가 도입한 PLACEHOLDER다. "
            "held_position/reconciliation_overlay는 모든 가설에서 항상 "
            "예외로 유지된다(EXEMPT_SOURCE_TYPES)."
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────────────────────────────


def _row_to_csv_dict(r: DecisionRow) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "business_date": r.business_date.isoformat(),
        "time_bucket": r.time_bucket,
        "created_at": r.created_at.astimezone(KST).isoformat(),
        "symbol": r.symbol,
        "source_type": r.source_type,
        "eligibility_passed": r.eligibility_passed,
        "buy_candidate": r.buy_candidate,
        "entry_score": r.entry_score,
        "block_reason": r.block_reason,
        "average_volume_20d": r.average_volume_20d,
        "average_turnover_20d": r.average_turnover_20d,
        "relative_activity": r.relative_activity,
        "universe_freeze_run_id": r.universe_freeze_run_id,
    }


def write_outputs(
    *,
    output_json: str | None,
    output_csv_dir: str | None,
    date_from: date,
    date_to: date,
    run_count: int,
    daily_summary: list[dict[str, Any]],
    baseline: dict[str, Any],
    by_source_type: dict[str, Any],
    by_time_bucket: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    recommendation: dict[str, Any],
    blocked_rows: list[DecisionRow],
    structural_notes: list[str],
) -> None:
    summary_obj = {
        "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "run_count": run_count,
        "baseline": baseline,
        "by_source_type": by_source_type,
        "by_time_bucket": by_time_bucket,
        "hypotheses": hypotheses,
        "recommendation": recommendation,
        "structural_notes": structural_notes,
    }

    if output_json:
        os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(summary_obj, f, ensure_ascii=False, indent=2, default=str)
        print(f"[출력] summary JSON 저장: {output_json}")

    if output_csv_dir:
        os.makedirs(output_csv_dir, exist_ok=True)

        daily_path = os.path.join(output_csv_dir, "daily_summary.csv")
        with open(daily_path, "w", encoding="utf-8", newline="") as f:
            if daily_summary:
                fieldnames = [
                    "business_date",
                    "universe_count",
                    "new_buy_candidate_count",
                    "pre_ai_activity_block_count",
                    "pre_ai_activity_block_rate",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in daily_summary:
                    writer.writerow(row)
        print(f"[출력] {daily_path}")

        hyp_path = os.path.join(output_csv_dir, "hypothesis_comparison.csv")
        with open(hyp_path, "w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "hypothesis",
                "applicable_population",
                "simulated_universe_filtered_count",
                "simulated_activity_block_reduction",
                "simulated_candidate_loss_count",
                "simulated_candidate_loss_rate",
                "simulated_block_rate_after_filter",
                "efficiency_score",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for h in hypotheses:
                writer.writerow(h)
        print(f"[출력] {hyp_path}")

        detail_path = os.path.join(output_csv_dir, "blocked_symbols_detail.csv")
        with open(detail_path, "w", encoding="utf-8", newline="") as f:
            fieldnames = list(_row_to_csv_dict(blocked_rows[0]).keys()) if blocked_rows else [
                "run_id", "business_date", "time_bucket", "created_at", "symbol",
                "source_type", "eligibility_passed", "buy_candidate", "entry_score",
                "block_reason", "average_volume_20d", "average_turnover_20d",
                "relative_activity", "universe_freeze_run_id",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in blocked_rows:
                writer.writerow(_row_to_csv_dict(r))
        print(f"[출력] {detail_path}")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Universe 활동성 사전 필터 실측 분석(read-only 초안) — "
            "docs/40_action_plans/universe_activity_prefilter_measurement_plan.md 구현체"
        )
    )
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--account-alias", required=True, help="trading.accounts.account_alias")
    parser.add_argument(
        "--time-buckets",
        default=",".join(ALL_TIME_BUCKETS),
        help="쉼표로 구분된 시간대 버킷 필터(기본: 전체)",
    )
    parser.add_argument("--output-json", default=None, help="summary.json 저장 경로")
    parser.add_argument("--output-csv-dir", default=None, help="CSV 산출물 저장 디렉터리")
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()
    selected_buckets = {b.strip() for b in args.time_buckets.split(",") if b.strip()}
    unknown_buckets = selected_buckets - set(ALL_TIME_BUCKETS)
    if unknown_buckets:
        raise SystemExit(f"알 수 없는 time bucket: {sorted(unknown_buckets)}")

    structural_notes = [
        "실행 단위(run)는 전용 run 테이블이 없어 decision_contexts.created_at을"
        f" {RUN_CLUSTER_GAP_SECONDS}초 간격 클러스터링으로 파생 재구성했다(근사치).",
        "pre-AI 활동성 차단 사유는 guardrail_evaluations가 아니라"
        " trade_decisions.decision_json.deterministic_trigger.eligibility_reasons"
        "에서 추출했다.",
        "유니버스/source_type 복원은 universe_freeze_run_items 대신"
        " trade_decisions.source_type을 직접 사용했다"
        "(universe_freeze_run_id는 참조 메타데이터로만 보조 조인).",
        "market_overlay_enabled는 저장된 플래그가 아니라 해당 run에"
        " source_type='market_overlay' 행 존재 여부로 추정한 값이다.",
        f"시간 버킷 경계({TIME_BUCKET_BOUNDARIES_KST})는 계획 문서에 명시돼 있지"
        " 않아 KRX 정규장 관례 기반 추정치를 사용했다 — 재확인 필요.",
    ]

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            account_id = await resolve_account_id(conn, args.account_alias)
            runs = await load_runs(conn, date_from, date_to, account_id)
            print(f"[수집] 파생 실행 단위(run) {len(runs)}건 (근사 재구성, 상단 구조 확인 결과 참고)")

            all_rows = await build_baseline_rows(conn, runs)
            print(f"[수집] 전체 decision 행 {len(all_rows)}건")

        if selected_buckets != set(ALL_TIME_BUCKETS):
            all_rows = [r for r in all_rows if r.time_bucket in selected_buckets]
            print(f"[필터] time_buckets={sorted(selected_buckets)} 적용 후 {len(all_rows)}건")

        baseline = build_baseline_summary(all_rows)
        by_source_type = summarize_by_source_type(all_rows)
        by_time_bucket = summarize_by_time_bucket(all_rows)
        daily_summary = summarize_daily(all_rows)
        hypotheses = run_all_hypotheses(all_rows)
        recommendation = build_recommendation(hypotheses)

        blocked_rows = [
            r for r in all_rows if r.is_new_buy_candidate_scope and r.is_pre_ai_activity_blocked
        ]

        print("\n=== baseline ===")
        print(json.dumps(baseline, ensure_ascii=False, indent=2, default=str))
        print("\n=== 가설 비교 ===")
        for h in hypotheses:
            print(json.dumps(h, ensure_ascii=False, default=str))
        print("\n=== 권고안 초안 ===")
        print(json.dumps(recommendation, ensure_ascii=False, indent=2, default=str))

        write_outputs(
            output_json=args.output_json,
            output_csv_dir=args.output_csv_dir,
            date_from=date_from,
            date_to=date_to,
            run_count=len(runs),
            daily_summary=daily_summary,
            baseline=baseline,
            by_source_type=by_source_type,
            by_time_bucket=by_time_bucket,
            hypotheses=hypotheses,
            recommendation=recommendation,
            blocked_rows=blocked_rows,
            structural_notes=structural_notes,
        )
    finally:
        await close_pool()

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
