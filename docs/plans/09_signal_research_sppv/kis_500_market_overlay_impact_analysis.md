# KIS 500 18회의 market_overlay 품질 영향 분석

## 분석 개요

- **분석 대상**: Phase 24b (2026-05-27) dry-run 로그, 비교 기준 Phase 24a (2026-05-26) dry-run 로그
- **핵심 현상**: KIS paper API (openapivts.koreainvestment.com)가 `inquire-price` 엔드포인트에서 20개 중 18개 심볼에 HTTP 500 반환 (90% failure)
- **분석 범위**: universe_selection.py의 `_add_market_overlay()`, execution_service.py의 `_resolve_quote()`, rest_client.py의 `get_quotes_batch()` / `_fetch_one()`

---

## 수집된 데이터

| 지표 | Phase 24a (2026-05-26) | Phase 24b (2026-05-27) |
|---|---|---|
| pre_pool_size | 20 | 20 |
| KIS HTTP 500 | 18 | 18 |
| batch 성공/전체 | 2/20 | 2/20 |
| quotes fetched | 2/20 | 2/20 |
| market_overlay 추가됨 | 2 | 0 |
| source_type 분포 | held:9, mo:2, core:28 | held:9, core:30 |
| 총 결정 수 | 39 | 39 |
| HOLD 결정 | 39 (100%) | 39 (100%) |
| market_overlay 결정 | 000210(HOLD), 000670(HOLD) | 없음 |
| 총 소요시간 | 84.421s | 67.227s |

---

## Q1: KIS 500 18회가 market_overlay 품질에 미치는 실질적 영향

### 영향 경로 추적

```
KIS HTTP 500 (18/20)
  → _fetch_one()에서 except Exception: return None (재시도 없음)
  → _add_market_overlay()에서 if raw is None: continue (조용히 스킵)
  → 해당 심볼은 scoring/market_score 계산 불가
  → universe에 추가되지 않음
```

### Phase 24b의 실제 영향

1. **market_overlay 추가 = 0개**: 18개 실패 + 2개 성공했지만, 성공한 2개도 core가 cap(30)을 이미 채워서 universe에 진입 실패
2. **최종 universe 구성**: held_position 9 + core 30 = 39개 (market_overlay 0)
3. **모든 결정 HOLD**: 39개 전부 HOLD (no_material_events_no_position)

### Phase 24a와 비교

- Phase 24a에서는 2개 성공한 심볼(000210, 000670)이 market_overlay로 universe에 진입
- 하지만 두 심볼 모두 HOLD 결정 (no_material_events_no_position)
- **즉, KIS 500이 없었다고 가정해도 market_overlay에서 BUY/SELL 결정이 나오지 않았을 것**

### 결론: 영향은 **거의 없음 (negligible)**

KIS 500 18회의 실질적 영향은:
- market_overlay 심볼이 universe에 추가되지 못한 것
- 하지만 추가되더라도 모두 HOLD였을 것 (Phase 24a 증거)
- 전체 39개 결정 중 0개에만 영향 (market_overlay가 추가되어도 결정 방향은 바뀌지 않음)
- `_resolve_quote()` (execution-time quote)는 pre-pool quote와 **완전히 별개 코드 경로**이므로 영향 없음

---

## Q2: Paper 환경에서 overlay 추가 축소가 합리적인가?

### 현재 paper 환경의 제약

```python
# universe_selection.py:431-441
def _effective_pre_pool_size(self, ctx: CompositionContext) -> int:
    if self._kis_client is not None and self._kis_client.env == "paper":
        return min(ctx.pre_pool_size, 20)
    return ctx.pre_pool_size
```

- paper env: pre_pool_size = 20 (hard cap)
- live env: pre_pool_size = 50 (ctx.pre_pool_size)
- market_overlay_cap = 5 (최대 5개까지 추가 가능)

### paper 환경의 특수성

1. **KIS paper API 불안정**: HTTP 500이 지속적으로 발생 (90% failure rate)
2. **pre_pool_size 20개 제한**: live 대비 40% 수준
3. **market_overlay의 실질적 기여도 0%**: Phase 24a/24b 모두 market_overlay에서 단 1건의 BUY/SELL도 발생하지 않음
4. **Budget 소비**: quote fetch 1회당 budget 소모 (paper env에서 budget은 제한적)

### 판단: **축소가 합리적이지만, 우선순위는 낮음**

- market_overlay가 paper에서 실질적 기여를 하지 못하고 있음 (0% decision impact)
- pre_pool_size 20은 이미 live 대비 축소된 상태
- **그러나** 이 문제의 우선순위는 낮음:
  - paper env는 어차피 테스트 환경
  - live env에서는 pre_pool_size=50, KIS real API는 안정적
  - paper env에서 overlay를 줄여도 얻는 이점이 미미함 (budget 절약 정도)

---

## Q3: 5가지 완화 옵션 비교

### 옵션 A: paper env pre_pool_size 추가 축소 (예: 20→10)

| 항목 | 평가 |
|---|---|
| **효과** | KIS 500 노출 심볼 수 50% 감소 |
| **구현 난이도** | 매우 쉬움 (1줄 수정) |
| **리스크** | market_overlay 기회 자체를 추가로 제한 |
| **단점** | paper에서 overlay가 이미 무용하므로 큰 의미 없음 |
| **평가** | ⭐⭐ (낮은 우선순위) |

### 옵션 B: `_fetch_one()`에 HTTP 500 재시도 로직 추가

| 항목 | 평가 |
|---|---|
| **효과** | 일시적 500에 대해 재시도로 성공 가능성 |
| **구현 난이도** | 중간 (retry 로직 추가) |
| **리스크** | 지연 시간 증가, budget 추가 소비 |
| **단점** | KIS paper API의 500은 일시적이 아닐 가능성 높음 (18/20 = 90% → 구조적 문제) |
| **평가** | ⭐ (paper에서는 무의미, live에서는 필요 없음) |

### 옵션 C: paper env에서 market_overlay 자체를 skip

```python
async def _add_market_overlay(self, ctx, universe):
    if self._kis_client is not None and self._kis_client.env == "paper":
        logger.info("market_overlay: skipped in paper env")
        return universe
    # ... 기존 로직
```

| 항목 | 평가 |
|---|---|
| **효과** | KIS 500 로그 노이즈 제거, budget 절약, 67초 → 더 단축 |
| **구현 난이도** | 쉬움 |
| **리스크** | paper에서 overlay 테스트 불가 |
| **단점** | paper에서 overlay 로직 자체를 검증할 기회 상실 |
| **평가** | ⭐⭐⭐ (실용적, 단 테스트 커버리지 손실) |

### 옵션 D: pre-pool quote 실패 시 fallback quote 사용

| 항목 | 평가 |
|---|---|
| **효과** | KIS 500이어도 fallback 가격으로 scoring 가능 |
| **구현 난이도** | 어려움 (fallback 가격 소스 필요) |
| **리스크** | 부정확한 가격으로 overlay 심볼 선정 |
| **단점** | fallback 가격의 신뢰성 문제, 복잡도 증가 |
| **평가** | ⭐ (과도한 엔지니어링) |

### 옵션 E: paper env에서 quote fetch timeout 증가 (3.0s → 5.0s)

```python
# rest_client.py:1619
raw_batch = await self._kis_client.get_quotes_batch(
    pre_pool_candidates, timeout=5.0  # paper env에서만
)
```

| 항목 | 평가 |
|---|---|
| **효과** | timeout으로 인한 실패 가능성 감소 |
| **구현 난이도** | 쉬움 |
| **리스크** | 전체 사이클 시간 증가 |
| **단점** | HTTP 500은 timeout 문제가 아님 → 효과 없음 |
| **평가** | ⭐ (HTTP 500에는 무효) |

### 옵션 비교표

| 옵션 | 효과 | 난이도 | 리스크 | 실용성 |
|---|---|---|---|---|
| A: pre_pool 축소 | 낮음 | 매우 쉬움 | 낮음 | 중간 |
| B: 500 재시도 | 낮음 | 중간 | 중간 | 낮음 |
| **C: paper skip** | **중간** | **쉬움** | **낮음** | **높음** |
| D: fallback quote | 중간 | 어려움 | 높음 | 낮음 |
| E: timeout 증가 | 없음 | 쉬움 | 낮음 | 매우 낮음 |

---

## Q4: 추천 완화책 1개

### 추천: **옵션 C — paper env에서 market_overlay skip**

```python
async def _add_market_overlay(self, ctx, universe):
    if self._kis_client is not None and self._kis_client.env == "paper":
        logger.info("market_overlay: skipped in paper env (KIS paper API unstable)")
        return universe
    # ... 기존 로직 유지
```

### 선정 이유

1. **KIS paper API의 HTTP 500은 구조적 문제**: 90% failure rate는 일시적 장애가 아닌 paper API의 근본적 불안정
2. **market_overlay의 실질적 기여도 0%**: Phase 24a/24b 모두 market_overlay에서 단 1건의 BUY/SELL도 없음
3. **Budget 절약**: 불필요한 quote fetch 20회 × budget 소모 방지
4. **사이클 시간 단축**: 67초에서 quote fetch 대기시간(3s timeout × 20) 제거로 추가 단축 가능
5. **구현 단순성**: 3줄 코드 추가, 사이드 이펙트 없음
6. **rollback 용이**: 조건문 하나 제거로 원복 가능

### 보완 조치

- live env에서는 정상 동작하므로 overlay 로직 자체는 유지됨
- paper env에서 overlay 로직 검증이 필요하면 별도 통합 테스트에서 KIS mock으로 커버 가능
- KIS paper API가 안정화되면 조건문 제거로 즉시 복구 가능

---

## 최종 JSON 출력

```json
{
  "analysis_scope": "Phase 24b dry-run (2026-05-27) vs Phase 24a dry-run (2026-05-26)",
  "data": {
    "phase_24b": {
      "pre_pool_size": 20,
      "kis_500_count": 18,
      "batch_success": "2/20",
      "market_overlay_added": 0,
      "source_type_distribution": {"held_position": 9, "core": 30},
      "total_decisions": 39,
      "all_hold": true,
      "market_overlay_decisions": [],
      "duration_seconds": 67.227
    },
    "phase_24a": {
      "pre_pool_size": 20,
      "kis_500_count": 18,
      "batch_success": "2/20",
      "market_overlay_added": 2,
      "source_type_distribution": {"held_position": 9, "market_overlay": 2, "core": 28},
      "total_decisions": 39,
      "all_hold": true,
      "market_overlay_decisions": [
        {"symbol": "000210", "decision": "HOLD"},
        {"symbol": "000670", "decision": "HOLD"}
      ],
      "duration_seconds": 84.421
    }
  },
  "q1_impact_assessment": {
    "summary": "KIS 500 18회의 market_overlay 품질 영향은 거의 없음 (negligible)",
    "reasoning": [
      "18/20 심볼이 HTTP 500으로 quote fetch 실패 → _fetch_one()에서 None 반환 → _add_market_overlay()에서 silent skip",
      "Phase 24b: 2개 성공했지만 core가 cap(30)을 채워 market_overlay 0개 추가",
      "Phase 24a: 2개 성공한 심볼(000210, 000670)이 market_overlay로 추가되었으나 모두 HOLD",
      "pre-pool quote fetch 실패는 execution-time _resolve_quote()와 별개 코드 경로이므로 영향 없음",
      "39개 결정 모두 HOLD로, KIS 500 유무가 최종 결정에 미친 영향은 0%"
    ],
    "severity": "low"
  },
  "q2_paper_overlay_reduction": {
    "summary": "paper 환경에서 overlay 축소는 합리적이나 우선순위 낮음",
    "reasoning": [
      "paper env pre_pool_size는 이미 20으로 live(50) 대비 60% 축소됨",
      "market_overlay의 실질적 기여도 0% (0 BUY/SELL in 2 cycles)",
      "KIS paper API 90% failure rate는 구조적 문제",
      "그러나 paper env는 테스트 환경이므로 우선순위 낮음",
      "live env에서는 KIS real API 안정적, pre_pool_size=50으로 정상 동작"
    ]
  },
  "q3_mitigation_comparison": {
    "options": {
      "A_pre_pool_reduction": {
        "description": "paper env pre_pool_size 추가 축소 (20→10)",
        "effect": "low",
        "difficulty": "very_easy",
        "risk": "low",
        "practicality": "medium"
      },
      "B_retry_500": {
        "description": "_fetch_one()에 HTTP 500 재시도 로직 추가",
        "effect": "low",
        "difficulty": "medium",
        "risk": "medium",
        "practicality": "low"
      },
      "C_skip_in_paper": {
        "description": "paper env에서 market_overlay 자체를 skip",
        "effect": "medium",
        "difficulty": "easy",
        "risk": "low",
        "practicality": "high"
      },
      "D_fallback_quote": {
        "description": "pre-pool quote 실패 시 fallback quote 사용",
        "effect": "medium",
        "difficulty": "hard",
        "risk": "high",
        "practicality": "low"
      },
      "E_increase_timeout": {
        "description": "paper env quote fetch timeout 증가 (3.0s→5.0s)",
        "effect": "none",
        "difficulty": "easy",
        "risk": "low",
        "practicality": "very_low"
      }
    }
  },
  "q4_recommendation": {
    "chosen_option": "C_skip_in_paper",
    "rationale": [
      "KIS paper API의 90% HTTP 500 failure rate는 구조적 문제로, 재시도나 timeout 조정으로 해결 불가",
      "market_overlay의 실질적 기여도 0% (2 cycles 동안 0 BUY/SELL)",
      "3줄 코드 추가로 구현 가능, 사이드 이펙트 없음, rollback 용이",
      "불필요한 quote fetch budget 소모와 로그 노이즈 제거",
      "live env에서는 정상 동작하므로 overlay 로직 자체는 유지",
      "paper에서 overlay 검증 필요시 KIS mock으로 별도 테스트 가능"
    ],
    "implementation": {
      "file": "src/agent_trading/services/universe_selection.py",
      "location": "_add_market_overlay() method,约 line 443",
      "change": "Add early return if self._kis_client.env == 'paper'",
      "code_snippet": "async def _add_market_overlay(self, ctx, universe):\n    if self._kis_client is not None and self._kis_client.env == 'paper':\n        logger.info('market_overlay: skipped in paper env (KIS paper API unstable)')\n        return universe\n    # ... existing logic"
    }
  }
}
```
