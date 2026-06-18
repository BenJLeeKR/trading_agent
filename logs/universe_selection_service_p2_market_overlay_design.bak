# Universe Selection Service P2 — Market-Driven Overlay + Liquidity Filter 확장 설계안

> **목적**: P1에서 stub으로 남긴 `_add_market_overlay()`를 KIS `inquire-price` 기반 **budget-safe deterministic overlay**로 교체하고, `LiquidityFilter`를 확장한다.
>
> **중요**: 이 문서는 **구현 착수 가능한 상태**로 설계를 고정하는 것이 목적이다. 추정(assumed)과 확정(verified) 사항을 명확히 구분하며, 모든 미확인 항목은 대체 경로(fallback)를 함께 명시한다.
>
> **기준 문서**:
> - [`[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md) — Layer 4 Market-Driven Overlay, Layer 4.1 Liquidity Filter
> - [`universe_selection_service_p1_design.md`](plans/universe_selection_service_p1_design.md) — P1 완료 상태, 섹션 10.1 P2 확장 방향
> - [`[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) #28 (Universe Selection Agent), #30 (Signal Agent)
> - [`trading_universe_decision_loop_p0_report.md`](plans/trading_universe_decision_loop_p0_report.md) — 100-symbol latency 측정 결과

---

## 목차

1. [목표 / 비목표](#1-목표--비목표)
2. [P1 현재 상태 요약](#2-p1-현재-상태-요약)
3. [P2 Minimum vs P3 Deferred 비교표](#3-p2-minimum-vs-p3-deferred-비교표)
4. [KIS API 호출 단계도 + 예산](#4-kis-api-호출-단계도--예산)
5. [Candidate Pre-Pool → Price Ranking → Top-K Orderbook → Overlay Selection 흐름도](#5-candidate-pre-pool--price-ranking--top-k-orderbook--overlay-selection-흐름도)
6. [Market-Driven Score 계산 규칙 (P2 Minimum)](#6-market-driven-score-계산-규칙-p2-minimum)
7. [Liquidity Filter 확장 규칙 (필수/검증필요/P3)](#7-liquidity-filter-확장-규칙-필수검증필요p3)
8. [Verified / Assumed / Fallback 필드 표](#8-verified--assumed--fallback-필드-표)
9. [Fast Layer 정책](#9-fast-layer-정책)
10. [Cap 정책 (Overlay Cap + Total Cap)](#10-cap-정책-overlay-cap--total-cap)
11. [추천 코드 변경 파일](#11-추천-코드-변경-파일)
12. [P2 최소 구현안](#12-p2-최소-구현안)
13. [구현 착수 전 체크리스트](#13-구현-착수-전-체크리스트)
14. [리스크 및 검증 계획](#14-리스크-및-검증-계획)
15. [7개 설계 질문 답변](#15-7개-설계-질문-답변)

---

## 1. 목표 / 비목표

### 목표 (P2 Scope) — "Budget-Safe Deterministic Overlay"

| # | 항목 | 상세 | P/M (Priority) |
|---|------|------|---------------|
| G1 | **Market-Driven Overlay 실 구현** | P1 stub을 KIS `inquire-price` batch 호출 + **absolute intraday turnover ranking** 기반 구현으로 교체. N일 baseline 불필요 | **P2a** |
| G2 | **Score = absolute ranking 기반** | 거래대금(turnover) 절대 순위 + 등락률 순위의 합성 score. **historical baseline 비교 없음** | **P2a** |
| G3 | **Candidate pre-pool 축소** | Core Universe 100종목 전체가 아니라, 사전 정의된 pre-pool에만 `inquire-price` 호출 | **P2a** |
| G4 | **Liquidity Filter P2 확장** | iscd_stat_cls_code 필터(F4) + 누적 거래량 필터(F5) 추가. **F6~F8은 검증 또는 P3** | **P2b** |
| G5 | **API 호출 예산 한도 명시** | 각 단계별 최대 REST 호출 수를 표로 고정. Budget-safe 보장 | **P2a** |
| G6 | **Fast Layer = 동일 5분 loop 내 priority 조정** | 별도 sub-minute loop 없음. Priority sort로만 구현 | **P2b** |

### 비목표 (P2에서 하지 않을 것)

| # | 항목 | 이유 | 이관 |
|---|------|------|------|
| N1 | **N일 평균 대비 true volume surge** | P2에는 historical baseline 데이터 없음 | **P3** |
| N2 | **시가총액 추정 필터 (F6)** | 상장주식수 데이터 미확인 | **P3 또는 검증 후** |
| N3 | **이상체결 탐지 필터 (F7)** | 당일/평균 비율 계산에 baseline 필요 | **P3** |
| N4 | **호가 얇음 필터 (F8)** | top-K에만 적용 가능. orderbook API 호출 비용 추가 | **P2c (선택) 또는 P3** |
| N5 | **AI 기반 universe scoring** | P3+ 항목 | **P3+** |
| N6 | **DB migration** | code-level selector 유지 | **P2d 또는 P3** |
| N7 | **전략별 universe 분기** | Layer 3. P2는 전 계좌 공통 | **P3** |
| N8 | **WebSocket 실시간 overlay** | REST batch polling 기반 | **P3** |
| N9 | **52주 최고가 기반 신고가 근접** | `stck_52w_hgpr` 필드 미확인. 당일 고가로 대체 | **P3 (검증 후)** |

---

## 2. P1 현재 상태 요약

### 2.1 구현 완료 항목

| 모듈 | 상태 | 설명 |
|------|------|------|
| [`universe_selection_types.py`](src/agent_trading/services/universe_selection_types.py) | ✅ 완료 | `SourceType` enum (5종), `SelectedSymbol`, `CompositionContext`, `LiquidityFilterResult` |
| [`universe_selection.py`](src/agent_trading/services/universe_selection.py) | ✅ 완료 | `UniverseSelectionService` 7-step composition, `LiquidityFilter` (3 checks) |
| [`contracts.py`](src/agent_trading/repositories/contracts.py) | ✅ 완료 | `InstrumentRepository.list_active_by_market()` protocol |
| [`instruments.py`](src/agent_trading/repositories/postgres/instruments.py) | ✅ 완료 | Postgres `list_active_by_market()` SQL 구현 |
| [`memory.py`](src/agent_trading/repositories/memory.py) | ✅ 완료 | InMemory `list_active_by_market()` 구현 |
| [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | ✅ 완료 | `_read_trading_universe()` 3-priority fallback chain |
| [`test_universe_selection.py`](tests/services/test_universe_selection.py) | ✅ 완료 | 25개 단위 테스트 |
| [`test_run_paper_decision_loop.py`](tests/scripts/test_run_paper_decision_loop.py) | ✅ 완료 | 3개 DB fallback 테스트 |

### 2.2 P2에서 확장할 지점

| P1 지점 | P2 확장 방향 |
|---------|-------------|
| [`_add_market_overlay()`](src/agent_trading/services/universe_selection.py:210) — stub no-op | KIS `inquire-price` batch → **absolute turnover ranking** → top K overlay |
| [`LiquidityFilter.check()`](src/agent_trading/services/universe_selection.py:57) — 3 checks | + F4 (iscd_stat_cls_code), F5 (low volume). **F6~F8은 검증 또는 P3** |
| `UniverseSelectionService.__init__()` — repos + liquidity_filter | P2에서 `KISRestClient` optional injection |

---

## 3. P2 Minimum vs P3 Deferred 비교표

| 기능 | P2 Minimum | P3 Deferred | 근거 |
|------|-----------|-------------|------|
| **Volume surge 감지** | **Absolute intraday turnover ranking** — 당일 누적 거래대금 절대값 순위 (top 5) | **True volume surge** — 당일 / N일 평균 거래대금 비율 | P2에는 N일 baseline 데이터 없음 |
| **체결강도** | **등락률(prdy_ctrt) 순위** — 상승률 높은 종목 top 5 | 등락률 + 거래량 동반 증가 가중치 | P2는 단순 등락률 ranking |
| **신고가 근접** | **당일 고가(stck_hgpr) 대비 근접** — 현재가/당일고가 비율 상위 | 52주 최고가 대비 근접 (별도 데이터 필요) | 52주 최고가 필드 미확인 |
| **시가총액 필터** | ❌ 제외 | 상장주식수 확인 후 추가 | 상장주식수 필드 미확인 |
| **iscd_stat_cls_code 필터** | ✅ **P2 필수** — 관리종목/투자위험 등 제외 | — | `inquire-price` 응답에서 즉시 사용 가능 |
| **누적 거래량 필터** | ✅ **P2 필수** — 당일 누적 거래대금 < threshold 제외 | — | `acml_tr_pbmn`으로 즉시 사용 가능 |
| **이상체결 탐지** | ❌ 제외 | 당일/평균 거래량 비율 > 100x 감지 | baseline 데이터 부재 |
| **호가 얇음 필터** | ⚠️ **P2c 선택** (top-K 후보만) | 전체 종목 대상 | orderbook API 호출 비용 |
| **Fast Layer** | **5분 loop 내 priority 조정** | 별도 1분 sub-cycle loop | P2는 구조 변경 불필요 |
| **KIS REST batch** | `get_quotes_batch()` — inquire-price ONLY | + orderbook batch | 호출 예산 최소화 |
| **DB migration** | ❌ 제외 | universe_selection_runs 테이블 | P2는 code-level |
| **전략별 분기** | ❌ 제외 | Layer 3 Strategy Relevance Filter | P2는 전 계좌 공통 |

---

## 4. KIS API 호출 단계도 + 예산

### 4.1 API 호출 단계 (5분 cycle 내)

```mermaid
flowchart TB
    subgraph STEP0["Step 0: Pre-Pool 선정 (DB only, 0 REST call)"]
        POOL["Pre-Pool = Core Universe 상위 N개\n(Held/Event symbol 제외)"]
        POOL_SIZE["Pre-Pool 크기 = min(50, len(core_universe))\n구성: Core 중 held/event 제외 후\n상위 50종목 (symbol 순)"]
    end
    
    subgraph STEP1["Step 1: Price Batch (inquire-price)"]
        BATCH["get_quotes_batch(pre_pool_symbols)\n최대 50 REST calls / cycle\nMARKET_DATA bucket"]
        SCORE["Score 계산 (absolute 기준)\n1. 거래대금 순위\n2. 등락률 순위\n3. 당일고가 근접 순위"]
        RANK["Composite score → top 10 ranking"]
    end
    
    subgraph STEP2["Step 2: Orderbook (top 10 only, 선택)"]
        OB["get_orderbook(top_10_symbols)\n최대 10 REST calls / cycle\nMARKET_DATA bucket\n**선택 사항 (P2c)**"]
        THIN["Thin orderbook check\n매수1호가 수량 < 100주 → 제외"]
    end
    
    subgraph STEP3["Step 3: Overlay Selection (0 REST call)"]
        SELECT["top 5 overlay 편입\nLiquidityFilter F4+F5 적용"]
        MERGE["Universe composition 완료\n→ priority sort → daily cap"]
    end
    
    POOL -->|0 calls| BATCH
    BATCH -->|50 calls| SCORE
    SCORE --> RANK
    RANK -->|10 symbols| OB
    OB -->|0-10 calls| THIN
    THIN --> SELECT
    SELECT --> MERGE
```

### 4.2 API별 호출량 상한 (1 cycle = 5분)

| 단계 | API | TR ID | 최대 호출 수 | Bucket | 비고 |
|------|-----|-------|------------|--------|------|
| Step 0 | 없음 (DB only) | — | **0** | — | Pre-pool은 `list_active_by_market()` 결과에서 slicing |
| Step 1 | `inquire-price` | FHKST01010100 | **최대 50** | MARKET_DATA | Pre-pool 크기만큼. 실제로는 50 미만 |
| Step 2 (선택) | `inquire-asking-price-exp-ccn` | FHKST01010200 | **최대 10** | MARKET_DATA | top-K ranking 결과에만. P2c에서만 활성화 |
| **총합** | | | **최대 60** | MARKET_DATA | 기존 P1은 0 calls (stub). P2 추가분 |

### 4.3 Budget-Safe 보장 규칙

1. **Pre-pool 사이즈는 env config로 조정 가능**: `MARKET_OVERLAY_PRE_POOL_SIZE` (기본값 50)
2. **Step 2 (orderbook)는 기본 OFF**: P2 minimum에서는 호출하지 않음. P2c에서 ON
3. **REST call 실패 시 skip**: 특정 symbol의 `inquire-price`가 timeout/error면 해당 symbol score=0으로 처리, 재시도 없음
4. **5분 cycle 내 latency 예상**:
   - Step 1 (50 calls, async concurrent): **2-5초** (100ms-300ms per call, semaphore=10)
   - Step 2 (10 calls, 선택): **1-2초**
   - 기존 P1 composition: **~1초** (DB only)
   - **P2 total 예상: 3-8초** (기존 5.355s 대비 +3초, 5분 주기 내 여유 충분)

---

## 5. Candidate Pre-Pool → Price Ranking → Top-K Orderbook → Overlay Selection 흐름도

### 5.1 전체 흐름

```mermaid
flowchart TB
    START["_add_market_overlay() called"] --> PRE_POOL
    
    subgraph PRE_POOL["Pre-Pool Construction (0 REST call)"]
        CORE["Core Universe\n100 symbols (list_active_by_market)"]
        EXCLUDE["Exclude already-seen\n(Held/Event symbols)"]
        SLICE["Take top N = pre_pool_size\n(default 50)"]
    end
    
    PRE_POOL --> PRICE
    
    subgraph PRICE["Price Batch (REST calls)"]
        BATCH["inquire-price batch\n50 calls async concurrent"]
        PARSE["Parse 응답 → MarketDataSnapshot"]
        FILTER_F4["F4: iscd_stat_cls_code\n관리종목/투자위험 등 → 제외\n(verified: assumed)"]
        FILTER_F5["F5: acml_tr_pbmn < threshold\n→ 제외\n(verified: confirm)"]
    end
    
    PRICE --> SCORE_CALC
    
    subgraph SCORE_CALC["Score Calculation (0 REST call)"]
        TURNOVER["Score 1: Turnover ranking\ndesc(acml_tr_pbmn) 순위\nP2: absolute 기준"]
        CHANGE["Score 2: 등락률 ranking\ndesc(prdy_ctrt) 순위\nP2: 절대 등락률 기준"]
        HIGH["Score 3: 당일고가 근접\nratio = stck_prpr / stck_hgpr\nP2: 당일 기준 (52주 아님)"]
        COMPOSITE["Composite = avg(turnover_rank,\nchange_rank, high_ratio)\n→ top 10"]
    end
    
    SCORE_CALC --> ORDERBOOK
    
    subgraph ORDERBOOK["Orderbook Check (top 10 only, 선택)"]
        OB_CALL["get_orderbook(top_10)\n최대 10 calls\nP2c: 활성화"]
        THIN["F8: 매수1호가 < 100주 → 제외\nP2c에서만"]
    end
    
    ORDERBOOK --> SELECT
    
    subgraph SELECT["Overlay Selection (0 REST call)"]
        TOP5["top 5 overlay 편입\n(overlay_cap = 5)"]
        REASON["inclusion_reason 결정\nvolume_top / strength_top / high_near"]
        MERGE2["seen dict에 추가"]
    end
    
    PRE_POOL -->|"pre_pool_size=50"| PRICE
    PRICE -->|"남은 후보"| SCORE_CALC
    SCORE_CALC -->|"top 10"| ORDERBOOK
    ORDERBOOK -->|"최종 후보"| SELECT
```

### 5.2 Pre-Pool 구성 상세

```
Pre-Pool 선정 규칙 (우선순위 순):

1. Core Universe = list_active_by_market('KRX')   ≈ 100 symbols
2. 이미 seen에 있는 symbol 제외                    (held/event 중복 방지)
3. 남은 symbol 중 pre_pool_size만큼 채택           (기본값 50, 첫 N개)
   - sorting 기준: symbol 순 (deterministic)
   - 향후 P3: 거래대금/변동성 기반 pre-pool ranking

→ 실제 inquire-price 호출 대상: 최대 50 symbols
```

### 5.3 단계별 후보 수 변화

```
Step 0: Core Universe      → 100 symbols  (DB)
Step 0: - seen 제외         → ~95 symbols  (DB, held 3-5개 제외)
Step 0: pre-pool (top 50)  → 50 symbols   (DB slicing, 0 REST call)
Step 1: inquire-price      → 50 calls     (최대)
Step 1: - F4 필터 제외      → ~48 symbols  (관리종목 등 거의 없음)
Step 1: - F5 필터 제외      → ~40 symbols  (저거래량 종목 제외)
Step 1: score ranking      → top 10       (score 계산)
Step 2: orderbook (선택)    → 0-10 calls   (P2c)
Step 3: overlay cap=5      → 5 symbols    (최종 편입)
```

---

## 6. Market-Driven Score 계산 규칙 (P2 Minimum)

### 6.1 핵심 원칙

> **P2 Minimum은 "과한 알파 추구"가 아니라 "budget-safe deterministic overlay"다.**
>
> - N일 평균 거래대금 baseline ❌ (P3)
> - 52주 최고가 ❌ (P3)
> - True volume surge ❌ (P3)
> - **Absolute intraday turnover ranking** ✅ (P2)
> - **등락률 ranking** ✅ (P2)
> - **당일 고가 근접 ranking** ✅ (P2)

### 6.2 Score 정의

```python
def _calc_market_score(snapshot: MarketDataSnapshot) -> float:
    """P2 Minimum composite score (0.0 ~ 1.0).
    
    P2는 absolute 기준만 사용. historical baseline 비교 없음.
    """
    scores: list[float] = []
    
    # Score 1: Turnover ranking proxy (0.0 ~ 1.0)
    # acml_tr_pbmn의 절대값이 클수록 high score
    # P2: cross-sectional ranking이므로 normalize by max in batch
    if snapshot.acc_trade_amount is not None and snapshot.max_trade_amount_in_batch > 0:
        ratio = snapshot.acc_trade_amount / snapshot.max_trade_amount_in_batch
        scores.append(min(ratio, 1.0))
    
    # Score 2: 등락률 ranking proxy (0.0 ~ 1.0)
    # prdy_ctrt가 클수록 high score (상승 중)
    if snapshot.change_rate is not None:
        # 등락률 -5% ~ +10% 구간을 0.0 ~ 1.0으로 normalize
        normalized = (snapshot.change_rate + 5.0) / 15.0
        scores.append(max(0.0, min(normalized, 1.0)))
    
    # Score 3: 당일 고가 근접 (0.0 ~ 1.0)
    # P2: stck_hgpr 기준 (52주 최고가 아님)
    if snapshot.current_price and snapshot.high_price and snapshot.high_price > 0:
        near_high = snapshot.current_price / snapshot.high_price
        # 80% 미만은 0점, 80%~100% 구간 0.0~1.0
        near_high_score = max(0.0, (near_high - 0.8) / 0.2)
        scores.append(min(near_high_score, 1.0))
    
    if not scores:
        return 0.0
    return sum(scores) / len(scores)
```

### 6.3 Inclusion Reason 결정

```python
def _categorize_market_reason(
    snapshot: MarketDataSnapshot,
    score: float,
) -> str:
    """P2: score 구성 요소 기반 inclusion_reason 결정.
    
    우선순위: volume_top > strength_top > high_near
    """
    # 하나의 symbol에 여러 reason이 중복될 수 있지만,
    # inclusion_reason은 단일 값만 기록 (대표 reason)
    if snapshot.acc_trade_amount and snapshot.max_trade_amount_in_batch:
        turnover_ratio = snapshot.acc_trade_amount / snapshot.max_trade_amount_in_batch
        if turnover_ratio > 0.8:
            return INCLUSION_REASON_VOLUME_SURGE  # "volume_surge_top10"
    
    if snapshot.change_rate is not None and snapshot.change_rate > 3.0:
        return INCLUSION_REASON_TRADE_STRENGTH  # "trade_strength_top10"
    
    if snapshot.current_price and snapshot.high_price and snapshot.high_price > 0:
        high_ratio = snapshot.current_price / snapshot.high_price
        if high_ratio > 0.95:
            return INCLUSION_REASON_NEAR_HIGH  # "near_high_breakout"
    
    return INCLUSION_REASON_PRICE_VOLUME_BREAKOUT  # "price_volume_breakout"
```

---

## 7. Liquidity Filter 확장 규칙 (필수/검증필요/P3)

### 7.1 필터 전체 분류

| # | 필터 | P2 Priority | 데이터 소스 | 상태 |
|---|------|------------|-----------|------|
| F1 | Unknown Instrument | **P1 (유지)** | `InstrumentRepository` | ✅ 완료 |
| F2 | Inactive Instrument | **P1 (유지)** | `instrument.is_active` | ✅ 완료 |
| F3 | Tick Size >= 1000 | **P1 (유지)** | `instrument.tick_size` | ✅ 완료 |
| **F4** | **iscd_stat_cls_code** | **P2 필수** | `inquire-price` 응답 | 🔶 검증 필요 (코드 매핑) |
| **F5** | **누적 거래량 저조** | **P2 필수** | `inquire-price` → `acml_tr_pbmn` | 🔶 검증 필요 (threshold) |
| F6 | 시가총액 추정 | **P3 이관** | 상장주식수 데이터 부재 | ❌ P3 |
| F7 | 이상체결 탐지 | **P3 이관** | baseline 데이터 부재 | ❌ P3 |
| F8 | 호가 얇음 | **P2c (선택)** | `inquire-asking-price-exp-ccn` | 🔶 P2c |

### 7.2 P2 필수 필터 (F4, F5) 상세

#### F4: iscd_stat_cls_code 필터

```python
# KIS inquire-price 응답의 iscd_stat_cls_code
# ⚠️ verification required: 실제 코드 값과 의미는 KIS Excel 시트 확인 필요
# 아래는 가정(assumed) 값. 구현 시 KIS 문서 재확인 필수.

SUSPENDED_STATUS_CODES: frozenset[str] = frozenset({
    "01",  # assumed: 관리종목
    "02",  # assumed: 투자위험
    "03",  # assumed: 투자경고
    "04",  # assumed: 투자주의
    "05",  # assumed: 거래정지
    # 빈 문자열 "" 또는 None: 정상 (통과)
})

async def _check_iscd_stat_cls_code(
    status_code: str | None,
) -> LiquidityFilterResult:
    """F4: iscd_stat_cls_code 기반 종목 상태 필터.
    
    P2 필수. 단, 코드 매핑은 KIS Excel 확인 필요 (assumed).
    Fallback: status_code가 None이거나 empty면 PASS (보수적 허용).
    """
    if not status_code:  # None or empty → assume normal
        return LiquidityFilterResult(True)
    if status_code in SUSPENDED_STATUS_CODES:
        return LiquidityFilterResult(False, f"suspended_status:{status_code}")
    # 알 수 없는 코드 → PASS (보수적)
    return LiquidityFilterResult(True)
```

#### F5: 누적 거래량 필터

```python
# P2 필수. threshold는 env config로 조정 가능.
# 기본값: 10억원 (당일 누적 거래대금 10억 미만 → 제외)
# ⚠️ assumed: threshold는 실제 KIS 데이터 기반 튜닝 필요

ACC_VOLUME_THRESHOLD: Decimal = Decimal("1_000_000_000")  # 10억원

async def _check_acc_trade_amount(
    acc_trade_amount: Decimal | None,
    *,
    threshold: Decimal = ACC_VOLUME_THRESHOLD,
) -> LiquidityFilterResult:
    """F5: 당일 누적 거래대금 필터.
    
    P2 필수. acml_tr_pbmn이 threshold 미만 → 제외.
    Fallback: acc_trade_amount가 None이면 PASS (데이터 없으면 보수적 허용).
    """
    if acc_trade_amount is None:
        return LiquidityFilterResult(True)
    if acc_trade_amount < threshold:
        return LiquidityFilterResult(False, f"low_volume:{acc_trade_amount}")
    return LiquidityFilterResult(True)
```

### 7.3 P2 선택 필터 (F8) — P2c

```python
# P2c 선택 사항. 활성화 시 top-K 후보(최대 10)에만 호출.

THIN_ORDERBOOK_THRESHOLD: int = 100  # 매수1호가 수량 < 100주 → 제외

async def _check_thin_orderbook(
    bid_vol_1: str | None,  # KIS 응답은 문자열
) -> LiquidityFilterResult:
    """F8: 호가 얇음 필터.
    
    P2c 선택. inquire-asking-price-exp-ccn 응답 필요.
    Fallback: bid_vol_1이 None이면 PASS.
    """
    if bid_vol_1 is None:
        return LiquidityFilterResult(True)
    try:
        volume = int(bid_vol_1)
    except (ValueError, TypeError):
        return LiquidityFilterResult(True)
    if volume < THIN_ORDERBOOK_THRESHOLD:
        return LiquidityFilterResult(False, f"thin_orderbook:{volume}")
    return LiquidityFilterResult(True)
```

### 7.4 필터 적용 순서

```mermaid
flowchart LR
    F1["F1: Unknown\nInstrument"] -->|pass| F2
    F2 -->|pass| F3["F3: Tick Size\n>= 1000"]
    F3 -->|pass| F4["F4: iscd_stat_cls_code\n**P2 필수**"]
    F4 -->|pass| F5["F5: Low Volume\n**P2 필수**"]
    F5 -->|pass| F8["F8: Thin Orderbook\n**P2c 선택**"]
    
    F1 -->|fail| REJECT["REJECT"]
    F2 -->|fail| REJECT
    F3 -->|fail| REJECT
    F4 -->|fail| REJECT
    F5 -->|fail| REJECT
    F8 -->|fail| REJECT
    
    REJECT -->|"제외 (로그 기록)"| DONE
    F8 -->|pass| PASS["PASS: overlay 편입"]

    style F4 fill:#f96,stroke:#333,color:#000
    style F5 fill:#f96,stroke:#333,color:#000
    style F8 fill:#9cf,stroke:#333,color:#000
```

---

## 8. Verified / Assumed / Fallback 필드 표

### 8.1 KIS inquire-price 응답 필드

| 필드명 | 용도 | 상태 | Fallback / 대체 |
|--------|------|------|----------------|
| `stck_prpr` (현재가) | Score 3: 당일고가 근접 계산 | **verified** (현재 `get_quote()`에서 사용 중) | None → score=0, filter PASS |
| `prdy_ctrt` (등락률) | Score 2: 등락률 ranking | **verified** (현재 `get_quote()` 응답에 포함) | None → score=0 |
| `acml_tr_pbmn` (누적 거래대금) | Score 1: Turnover ranking, F5: volume filter | **assumed** (KIS 문서에 필드 존재 확인. 현재 코드에서 미사용) | None → score=0, F5 PASS |
| `acml_vol` (누적 거래량) | 향후 F7 이상체결 탐지용 | **assumed** (P3에서 사용. P2에서는 미사용) | — |
| `stck_hgpr` (당일 고가) | Score 3: 당일고가 근접 | **verified** (KIS 문서에 필드 존재) | None → 당일고가 score=0 |
| `stck_lwpr` (당일 저가) | 향후 daily range 계산 | **verified** | P2에서는 미사용 |
| `stck_oprc` (시가) | 향후 gap 분석 | **verified** | P2에서는 미사용 |
| `iscd_stat_cls_code` (종목상태코드) | F4: 관리종목/투자위험 등 제외 | **verification required** (코드 값 매핑은 KIS Excel 시트 Layout 시트에서 확인 필요) | None/empty → PASS. 알 수 없는 코드 → PASS |
| `temp_stop_yn` (임시정지 여부) | F4 보조 | **assumed** (KIS 요약 문서에 필드명 언급) | P2에서는 미사용 (iscd_stat_cls_code로 충분) |
| `marg_rate` (증거금률) | 향후 리스크 평가 | **assumed** | P2에서는 미사용 |

### 8.2 KIS inquire-asking-price-exp-ccn 응답 필드 (P2c 선택)

| 필드명 | 용도 | 상태 | Fallback |
|--------|------|------|----------|
| `ASKP1` (매도1호가) | F8: 호가 스프레드 계산 | **verified** (현재 `get_orderbook()`에서 사용 중) | P2c에서만 사용 |
| `BIDP1` (매수1호가) | F8: thin orderbook 체크 | **verified** | P2c에서만 사용 |
| `ASKP_RSQN1` (매도1호가 잔량) | F8: 호가 얇음 판단 | **assumed** (필드명 추정. KIS Excel 확인 필요) | None → PASS |

### 8.3 Instrument Entity 필드 (DB)

| 필드명 | 용도 | 상태 | Fallback |
|--------|------|------|----------|
| `tick_size` | F3: tick_size >= 1000 | **verified** (P1에서 사용 중) | None → PASS |
| `is_active` | F2: 거래정지/상장폐지 | **verified** (P1에서 사용 중) | None → FAIL (보수적) |
| `market_code` | Core universe 필터 | **verified** (P1에서 사용 중) | — |

### 8.4 Summary: 구현자가 알아야 할 것

| 분류 | 개수 | 리스트 |
|------|------|--------|
| **verified** (확정, 구현 가능) | 8 | `stck_prpr`, `prdy_ctrt`, `stck_hgpr`, `stck_lwpr`, `stck_oprc`, `ASKP1`, `BIDP1`, entity 필드 전부 |
| **assumed** (추정, 구현 가능하나 확인 권장) | 4 | `acml_tr_pbmn`, `acml_vol`, `temp_stop_yn`, `marg_rate` |
| **verification required** (구현 전 KIS Excel 확인 필수) | 1 | `iscd_stat_cls_code` (코드 값 매핑) |
| **fallback metric available** (검증 실패 시 대체 가능) | 모든 필드 | None → score=0, filter PASS. 보수적 기본값 |

---

## 9. Fast Layer 정책

### 9.1 P2: 동일 5분 loop 내 priority 조정

```
Fast Layer = 별도 sub-minute loop가 아니다.
             5분 decision loop 내에서 market-driven overlay 종목의
             평가 순서를 SourceType 우선순위에 따라 앞당기는 것.
```

### 9.2 실행 순서 (within `_run_one_cycle()`)

```mermaid
flowchart LR
    PRE["Pre-check\n(snapshot freshness)"]
    --> COMPOSE["Universe Composition\n(4 source 합성)"]
    --> SORT["Priority Sort\nHELD > EVENT > MARKET\n> MANUAL > CORE"]
    --> EVAL["Symbol Evaluation\n(sorted 순서대로)"]
    --> REPORT["Cycle Result\nSerialize"]
    
    style COMPOSE fill:#f96,stroke:#333,color:#000
    style SORT fill:#9cf,stroke:#333,color:#000
```

**P2 변화**: `Universe composition` 단계 내에서 `_add_market_overlay()`가 실제 KIS 데이터를 가져오고, 결과적으로 `MARKET_OVERLAY` type symbol이 `seen` dict에 추가됨. 이후 `SourceType.priority`에 따라 HELD(0) > EVENT(1) > MARKET(2) > MANUAL(3) > CORE(4) 순서로 정렬됨.

### 9.3 P2 vs P3 Fast Layer 비교

| 항목 | P2 | P3 |
|------|-----|-----|
| 구조 | **5분 loop 내 priority 조정** | 별도 1분 sub-cycle loop |
| Market-driven 평가 | 매 5분마다 inquire-price batch | 매 1분마다 경량 score refresh |
| Core Universe 평가 | 매 5분 (변경 없음) | 매 5분 (Slow Layer) |
| 구현 변경량 | **~10줄** (기존 sort 로직 재사용) | 신규 scheduler task |
| RPS 영향 | **0** (기존 5분 cycle 내에서만 호출) | +50 calls/min |

---

## 10. Cap 정책 (Overlay Cap + Total Cap)

### 10.1 2단계 Cap 구조

```mermaid
flowchart TB
    subgraph OVERLAY_CAP["Overlay Cap (개별 Source 제한)"]
        CORE_CAP["Core Universe\n100 symbols\n(P1 변경 없음)"]
        HELD_CAP["Held Positions\n무제한\n(P1 변경 없음)"]
        EVENT_CAP["Event Overlay\nmax 5\n(P1 변경 없음)"]
        MARKET_CAP["Market Overlay\nmax 5\n(P2 신규)"]
    end
    
    subgraph TOTAL_CAP["Total Daily Cap"]
        TOTAL["max_cap=30\n(held 제외)\n(P1 변경 없음)"]
    end
    
    CORE_CAP --> TOTAL
    HELD_CAP -->|cap 미차감| TOTAL
    EVENT_CAP --> TOTAL
    MARKET_CAP --> TOTAL
```

### 10.2 Cap 상호작용 예시

| 시나리오 | Held | Core | Event | Market | Total (held 제외) |
|---------|------|------|-------|--------|-------------------|
| 일반 | 3 | 20 | 2 | 5 | **30** (20+2+5=27, cap=30 여유) |
| Event 과다 | 5 | 15 | 5 | 5 | **30** (15+5+5=25, cap=30 여유) |
| Core 과다 | 2 | 28 | 3 | 5 | **30** (28+3+5=36 → priority sort 후 28 유지) |
| 모든 source 가득 | 5 | 20 | 5 | 5 | **30** (held 5는 면제. 20 non-held = cap=30 이내) |

---

## 11. 추천 코드 변경 파일

### 11.1 변경 파일 목록

| 파일 | 변경 유형 | 변경 내용 | 예상 변경량 |
|------|----------|----------|------------|
| [`universe_selection_types.py`](src/agent_trading/services/universe_selection_types.py) | **수정** | `CompositionContext`에 `market_overlay_cap`, `pre_pool_size` 필드 추가. `MarketDataSnapshot` dataclass 신규 | +40줄 |
| [`universe_selection.py`](src/agent_trading/services/universe_selection.py) | **수정** | `_add_market_overlay()` stub → 실제 구현 (pre-pool → batch → score → select). `LiquidityFilter`에 F4+F5 추가. `KISRestClient` optional injection | +140줄 |
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | **수정** | `get_quotes_batch()` 신규 메서드 (async concurrent, semaphore, timeout) | +50줄 |
| [`run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | **수정** | `postgres_runtime()` 내 `KISRestClient` 생성 + `UniverseSelectionService`에 주입. `CompositionContext` P2 필드 전달 | +15줄 |
| [`test_universe_selection.py`](tests/services/test_universe_selection.py) | **수정** | Market overlay score 계산 테스트. Pre-pool 구성 테스트. Overlay cap 테스트. F4+F5 필터 테스트. P2c 선택 테스트 | +100줄 |

### 11.2 변경 없는 파일

| 파일 | 이유 |
|------|------|
| [`contracts.py`](src/agent_trading/repositories/contracts.py) | P2는 기존 protocol만 사용 |
| [`instruments.py`](src/agent_trading/repositories/postgres/instruments.py) | P2 변경 불필요 |
| [`memory.py`](src/agent_trading/repositories/memory.py) | P2 변경 불필요 |
| [`decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | Universe composition 결과만 소비 |
| [`run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | Env var 미설정 → 자동 service 사용 |
| [`run_orchestrator_once.py`](scripts/run_orchestrator_once.py) | 단일 005930 smoke 전용 |
| [`bootstrap.py`](src/agent_trading/runtime/bootstrap.py) | P2는 script 수준 wiring |
| migration/*.sql | P2는 code-level selector 유지 |

---

## 12. P2 최소 구현안

### 12.1 구현 우선순위

| 우선순위 | 항목 | 파일 | 비고 |
|---------|------|------|------|
| **P2a-1** | `MarketDataSnapshot` dataclass | `universe_selection_types.py` | 선행 조건 |
| **P2a-2** | `CompositionContext` P2 필드 추가 | `universe_selection_types.py` | market_overlay_cap, pre_pool_size |
| **P2a-3** | `get_quotes_batch()` in KISRestClient | `rest_client.py` | async concurrent + semaphore |
| **P2a-4** | `_add_market_overlay()` 실제 구현 | `universe_selection.py` | pre-pool → batch → score → top K |
| **P2a-5** | Score 계산 pure function | `universe_selection.py` | `_calc_market_score()`, `_categorize_reason()` |
| **P2b-1** | F4: iscd_stat_cls_code 필터 | `universe_selection.py` | LiquidityFilter 확장 |
| **P2b-2** | F5: 누적 거래량 필터 | `universe_selection.py` | LiquidityFilter 확장 |
| **P2b-3** | `run_paper_decision_loop.py` wiring | `run_paper_decision_loop.py` | KIS client 생성 + 주입 |
| **P2c-1** | F8: 호가 얇음 필터 (선택) | `universe_selection.py` | top-K 후보에만 적용 |
| **P2d-1** | 단위 테스트 (P2a+b) | `test_universe_selection.py` | score, cap, filter, pre-pool |
| **P2d-2** | pytest 검증 | 전 테스트 | 기존 49개 + 신규 통과 |

### 12.2 P2 Minimum으로 확정된 범위 (Must-Have)

```
P2a (필수, overlay core):
  [x] _add_market_overlay(): pre-pool(50) → inquire-price batch(50 calls) → score ranking → top 5
  [x] get_quotes_batch(): async concurrent, semaphore, timeout
  [x] MarketDataSnapshot dataclass
  [x] CompositionContext: market_overlay_cap=5, pre_pool_size=50
  [x] Score 1: absolute turnover ranking (acml_tr_pbmn)
  [x] Score 2: 등락률 ranking (prdy_ctrt)
  [x] Score 3: 당일 고가 근접 (stck_prpr / stck_hgpr)
  [x] Composite score = avg(3 scores)

P2b (필수, liquidity filter):
  [x] F4: iscd_stat_cls_code — 관리종목/투자위험 등 제외 (코드 매핑은 KIS Excel 확인)
  [x] F5: acml_tr_pbmn < threshold(10억) → 제외

P2c (선택, orderbook filter):
  [ ] F8: thin orderbook — top 10 후보에만 inquire-asking-price-exp-ccn 호출
  [ ] 매수1호가 < 100주 → 제외

P2d (필수, 검증):
  [x] 단위 테스트: market score, overlay cap, F4, F5, pre-pool 구성
  [x] 기존 49개 테스트 전면 통과
  [x] 100-symbol dry-run 정상 종료 (latency 3-8초 예상)
```

### 12.3 P3로 내린 범위 (명시적 제외)

```
P3 (deferred):
  [ ] True volume surge: N일 평균 거래대금 대비 비율
  [ ] 52주 최고가 대비 신고가 근접
  [ ] F6: 시가총액 추정 필터
  [ ] F7: 이상체결 탐지 필터
  [ ] 별도 1분 sub-cycle Fast Layer loop
  [ ] DB migration (universe_selection_runs 테이블)
  [ ] 전략별 universe 분기
  [ ] AI 기반 scoring
```

---

## 13. 구현 착수 전 체크리스트

### 13.1 KIS Excel 확인 항목 (구현 전 필수)

- [ ] `iscd_stat_cls_code` 실제 코드 값과 의미 확인
  - [ ] 관리종목 코드
  - [ ] 투자위험 코드
  - [ ] 투자경고 코드
  - [ ] 투자주의 코드
  - [ ] 거래정지 코드
- [ ] `acml_tr_pbmn` 필드 타입 (문자열/숫자) 확인
- [ ] `stck_hgpr` 필드 존재 및 타입 확인
- [ ] `inquire-price` 응답에서 `temp_stop_yn` 필드 존재 확인

### 13.2 코드 구현 전 확인

- [ ] `KISRestClient.get_quote()`가 반환하는 dict에 `acml_tr_pbmn`, `prdy_ctrt`, `stck_hgpr` 키가 실제로 있는지
- [ ] `KISRestClient.get_orderbook()`가 반환하는 dict에 `ASKP1`, `BIDP1`, `ASKP_RSQN1` 키가 실제로 있는지
- [ ] Budget manager (`BucketType.MARKET_DATA`)의 RPS limit 확인
- [ ] `asyncio.gather()` + semaphore pattern이 KIS rate limit과 충돌하지 않는지

### 13.3 구현 순서

```
Step 1: MarketDataSnapshot + CompositionContext 필드 추가 (타입만)
Step 2: get_quotes_batch() 구현 (REST client)
Step 3: _add_market_overlay() 구현 (pre-pool → batch → score → select)
Step 4: F4 + F5 LiquidityFilter 추가
Step 5: run_paper_decision_loop.py wiring
Step 6: 단위 테스트
Step 7: pytest + dry-run 회귀
```

---

## 14. 리스크 및 검증 계획

### 14.1 위험 목록

| # | 위험 | 영향 | 완화 |
|---|------|------|------|
| R1 | **inquire-price batch latency (50 calls)** | 2-5초 추가. 전체 loop 8-10초 | `asyncio.gather` + semaphore=10. timeout=3s per call. 실패 symbol은 score=0 |
| R2 | **RPS budget 소진** | MARKET_DATA bucket limit 초과 | pre-pool=50으로 고정. 5분 cycle이므로 50/300s = 0.17 RPS. KIS paper RPS(기본 10) 대비 충분 |
| R3 | **iscd_stat_cls_code 매핑 불확실** | F4 필터 오작동 | 코드 값은 KIS Excel 확인. fallback: None/empty → PASS |
| R4 | **acml_tr_pbmn 타입 불일치** | F5 필터 오작동 | `Decimal` 변환 시 예외 처리. 실패 시 PASS |
| R5 | **Paper mode 제약** | inquire-price paper 미지원 | `FHKST01010100`은 paper/live 동일 TR ID. 단, paper mode 응답에 일부 필드 누락 가능 |
| R6 | **P2 overlay 효과 미미** | 5 symbols가 전체 universe에 영향 적음 | P2 목적은 "budget-safe deterministic overlay". 효과 증폭은 P3 |

### 14.2 검증 계획

| 검증 | 방법 | 통과 기준 |
|------|------|----------|
| Market score 계산 | 단위 테스트: turnover/등락률/고가근접 각각 0.0~1.0 | 3개 score 함수 각각 3개 이상 케이스 |
| Pre-pool 구성 | 단위 테스트: 100 symbols → exclude seen → top 50 | 정확히 50개 |
| Overlay cap | 단위 테스트: score top 10 → cap 5 → 5개 편입 | 5개만 편입 |
| F4 필터 | 단위 테스트: 각 status code별 fail/pass | 6개 케이스 (5 fail + 1 pass) |
| F5 필터 | 단위 테스트: threshold 미만/이상 | 2개 케이스 |
| P1 회귀 | 기존 25+24개 테스트 | 49/49 통과 |
| Dry-run latency | `--count 1 --dry-run --output json` | P2 total < 10초 |
| Budget 정합성 | 로그 기반 REST call count 확인 | Step 1 ≤ 50 calls, Step 2 ≤ 10 calls |

---

## 15. 7개 설계 질문 답변

### Q1. 어떤 KIS API로 거래량 급증/체결강도/신고가 근접 정보를 가져올 수 있는가?

**답변**: KIS Public API에는 전용 ranking API가 **없다** (확인 완료). 대신 `inquire-price` (FHKST01010100)를 pre-pool(최대 50 symbols)에 batch 호출하여 다음 필드를 추출한다:

| 지표 | P2 방식 | KIS 필드 | 비고 |
|------|---------|---------|------|
| 거래량 급증 | **Absolute turnover ranking** (P2) | `acml_tr_pbmn` | N일 평균 비교는 P3 |
| 체결강도 | **등락률 ranking** (P2) | `prdy_ctrt` | 단순 등락률 순위 |
| 신고가 근접 | **당일 고가 근접** (P2) | `stck_prpr` / `stck_hgpr` | 52주 최고가는 P3 |

### Q2. ranking API가 없다면 대체 가능한 시세/호가/현재가 API 조합?

**답변**: 4단계 접근법:

```
Step 0: Pre-pool 구성 (DB only, 0 REST call)
  Core Universe 100 → seen 제외 → top 50 slicing

Step 1: inquire-price batch (50 REST calls)
  50 symbols → acml_tr_pbmn, prdy_ctrt, stck_hgpr 수집 → composite score → top 10

Step 2: inquire-asking-price-exp-ccn (0-10 REST calls, 선택)
  top 10 → orderbook → thin filter (P2c)

Step 3: overlay selection (0 REST call)
  top 5 편입 + LiquidityFilter F4+F5
```

### Q3. Market-Driven Overlay를 전 계좌 공통 vs 계좌/전략별?

**답변**: **P2: 전 계좌 공통.** `CompositionContext.account_id`는 이미 존재하나, 동일 pre-pool + 동일 score 기준 사용. 전략별 분기는 Layer 3 (P3)에서 도입.

### Q4. Liquidity Filter는 selector 내부 vs 별도 service/protocol?

**답변**: **P2: selector 내부 유지** (현재 class 방식 유지). F4+F5만 추가. Protocol 분리와 Filter Chain 패턴은 P3.

### Q5. 가격/거래량/호가/시가총액 데이터 freshness 기준?

| 데이터 | 출처 | Freshness | P2 정책 |
|--------|------|-----------|---------|
| 현재가 (`stck_prpr`) | `inquire-price` | REST call 시점 | 5분마다 batch refresh |
| 누적 거래대금 (`acml_tr_pbmn`) | `inquire-price` | REST call 시점 | 5분마다 batch refresh |
| 등락률 (`prdy_ctrt`) | `inquire-price` | REST call 시점 | 5분마다 batch refresh |
| 호가 (1단계) | `inquire-asking-price-exp-ccn` | REST call 시점 | P2c: top 10에만 |
| 시가총액 | 현재가 * 상장주식수 | P2 미사용 | P3 |
| 52주 최고가 | 별도 필요 | P2 미사용 | P3 |

### Q6. Fast Layer: 5분 loop 우선순위 조정 vs 별도 interval loop?

**답변**: **P2: 5분 loop 내 priority 조정.** 별도 loop 불필요. Market-driven overlay 종목은 `SourceType.priority=2`로 HELD(0) > EVENT(1) 다음, CORE(4)보다 먼저 평가됨.

### Q7. P2 구현 시 어떤 파일이 바뀌고 어떤 것은 그대로?

| 파일 | 변경 | 변경량 | 사유 |
|------|------|--------|------|
| `universe_selection_types.py` | ✅ 수정 | +40줄 | `MarketDataSnapshot`, `CompositionContext` 확장 |
| `universe_selection.py` | ✅ 수정 | +140줄 | `_add_market_overlay()` 실 구현, F4+F5 |
| `rest_client.py` | ✅ 수정 | +50줄 | `get_quotes_batch()` |
| `run_paper_decision_loop.py` | ✅ 수정 | +15줄 | KIS client wiring |
| `test_universe_selection.py` | ✅ 수정 | +100줄 | P2 테스트 |
| `contracts.py` | ❌ 변경 없음 | — | P2는 기존 protocol |
| `instruments.py` | ❌ 변경 없음 | — | — |
| `memory.py` | ❌ 변경 없음 | — | — |
| `decision_orchestrator.py` | ❌ 변경 없음 | — | Universe consumer |

---

## 부록 A: 용어 정리

| 용어 | 설명 |
|------|------|
| **Absolute Intraday Turnover Ranking** | P2 Volume Surge 방식. N일 평균 비교 없이 당일 누적 거래대금 절대값 기준 순위 |
| **Pre-Pool** | Market-Driven overlay 평가 전, Core Universe 중 실제 `inquire-price`를 호출할 후보군 (기본 50개) |
| **Composite Score** | 3축(turnover ranking, 등락률 ranking, 당일고가 근접) unweighted average |
| **Budget-Safe** | 각 cycle 내 REST 호출 수가 정해진 상한을 초과하지 않도록 통제 |
| **Verified** | KIS 문서/현재 구현에서 필드 존재가 확인된 상태 |
| **Assumed** | 문서상 추정되나 현재 코드에서 미사용. 구현 시 재확인 권장 |
| **Verification Required** | 구현 전 KIS Excel 시트 확인이 필수인 항목 |
