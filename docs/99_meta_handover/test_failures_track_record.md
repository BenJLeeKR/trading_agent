# Pre-existing Test Failures Track Record

> **최종 업데이트**: 2026-05-19  
> **분석자**: Roo (Ask Mode → Code Mode)  
> **대상**: `tests/services/` 전체 (1021 tests collected)

---

## 현재 실패 현황 (2026-05-19 기준)

| # | 테스트 파일 | 테스트명 | 실패 유형 | 관련 태스크 |
|---|-----------|---------|----------|-----------|
| 1 | [`tests/services/test_seeded_news_service.py`](../tests/services/test_seeded_news_service.py) | `TestCrossSymbolNoiseAndScoring::test_scoring_company_name_weight_reduced` | 시간 의존적(time-dependent) | **무관** (SeededNewsCandidateService) |
| 2 | [`tests/services/test_seeded_news_service.py`](../tests/services/test_seeded_news_service.py) | `TestCrossSymbolNoiseAndScoring::test_seed_quality_filter` | 시간 의존적(time-dependent) | **무관** (SeededNewsCandidateService) |

---

## 상세 분석

### 실패 1: `test_scoring_company_name_weight_reduced`

**파일**: [`tests/services/test_seeded_news_service.py:417`](../tests/services/test_seeded_news_service.py:417)

**테스트 기대값**:
```
company_name in title (+20) + freshness 24h이내 (+20) = 40점
```

**실제값**: `30.0`

**Traceback**:
```
assert score == 40.0, f"Expected score 40.0 (company=20 + freshness=20), got {score}"
AssertionError: Expected score 40.0 (company=20 + freshness=20), got 30.0
```

**원인 분석**:

테스트에서 사용하는 뉴스 아이템의 `pubDate`:
```
"Fri, 17 May 2026 09:00:00 +0900"  →  2026-05-17T00:00:00Z
```

현재 시간 (`datetime.now(timezone.utc)`):
```
2026-05-19T03:18:57Z  (테스트 실행 시점)
```

경과 시간: 약 **51시간** (17일 00:00 UTC → 19일 03:18 UTC)

[`_compute_score()`](../src/agent_trading/services/seeded_news_service.py:563)의 freshness 로직:
```python
if hours_ago < 24:
    score += 20       # 24h 이내 → +20
elif hours_ago < 72:
    score += 10       # 72h 이내 → +10 (여기에 해당)
```

- `company_name in title` = **20점** ✅
- `freshness` = **10점** (51h 경과, 24h 초과 72h 미만)
- `keyword overlap` = **0점** ("결정"은 boilerplate token)
- `description quality` = **0점** (description 길이 50자 미만 추정)
- **Total = 30점**

**결론**: 테스트는 `pubDate`가 24h 이내라고 가정했지만, 실제 테스트 실행 시점에서는 51시간이 경과하여 freshness가 20→10으로 감소.

---

### 실패 2: `test_seed_quality_filter`

**파일**: [`tests/services/test_seeded_news_service.py:597`](../tests/services/test_seeded_news_service.py:597)

**테스트 기대값**:
```python
assert metrics.seeds_with_results >= 1  # Valid seed should have results
```

**실제값**: `seeds_with_results = 0`

**Metrics 상세**:
```
PipelineMetrics(
    seeds_total=2,
    seeds_with_queries=1,
    seeds_with_results=0,
    queries_executed=2,
    raw_candidates_fetched=1,
    hard_gate_passed=1,
    hard_gate_dropped=0,
    deduped_count=1,
    kept_count=0,
    dropped_low_confidence=1,
    dropped_cross_symbol=0,
    seed_quality_drop_count=1,
    per_symbol={
        '005930': {
            'raw': 1, 'hard_gate_passed': 1, 'hard_gate_dropped': 0,
            'deduped': 1, 'scored_before_threshold': 1,
            'dropped_low_confidence': 1, 'dropped_cross_symbol': 0, 'kept': 0
        }
    }
)
```

**원인 분석**:

Valid seed("삼성전자", symbol="005930")의 뉴스 아이템:
```python
{
    "title": "삼성전자 유상증자",
    "description": "desc",  # ← 길이 4자
    "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
}
```

[`_compute_score()`](../src/agent_trading/services/seeded_news_service.py:511) 계산:
- `company_name in title` = **20점** ("삼성전자" in title)
- `freshness` = **10점** (51h 경과, 24h < 51h < 72h)
- `description quality` = **0점** (description "desc" = 4자, 20자 미만)
- `keyword overlap` = **0점** ("유상증자"는 headline "유상증자 결정"에서 추출되나, "결정"은 boilerplate로 제거 → "유상증자"만 남음. title "삼성전자 유상증자"에 "유상증자" 포함 → overlap=1 → +10점? 확인 필요)

다시 계산: headline "유상증자 결정" → `_extract_keywords` → "결정"은 boilerplate 제거 → ["유상증자"] → title "삼성전자 유상증자"에 "유상증자" 포함 → **keyword overlap = 1 → +10점**

그러면: `20(company) + 10(freshness) + 10(keyword) + 0(desc quality) = 40점`

[`_SCORE_THRESHOLD`](../src/agent_trading/services/seeded_news_service.py:31) = **50점**

**40 < 50 → threshold 미달 → dropped_low_confidence**

**결론**: 테스트는 freshness 20점을 기대했지만 실제로는 10점만 부여되어 총점 40점이 threshold 50에 미달. freshness 감소가 직접적 원인.

---

## 현재 태스크와의 관련성

| 항목 | 내용 |
|------|------|
| **현재 태스크** | KIS broker truth sync + duplicate sell guard |
| **영향받는 파일** | `rest_client.py`, `order_sync_service.py`, `decision_orchestrator.py`, `sell_guard.py` 등 |
| **실패 테스트 대상** | `SeededNewsCandidateService` (공시 → 뉴스 파이프라인) |
| **관련성** | **완전히 무관** — 서로 다른 서비스, 의존성 없음 |

두 실패 모두 `SeededNewsCandidateService`의 scoring 로직에서 발생하며, 이는 KIS broker truth sync나 duplicate sell guard와 **전혀 관련이 없습니다**.

---

## 실패 지속 기간

| 실패 | 최초 발생 추정 | 상태 |
|------|--------------|------|
| `test_scoring_company_name_weight_reduced` | 2026-05-18 이후 (pubDate 기준 24h 경과 시점) | **Pre-existing** |
| `test_seed_quality_filter` | 2026-05-18 이후 (동일 원인) | **Pre-existing** |

**판단**: 이 실패들은 **이번 변경(KIS broker truth sync + duplicate sell guard)으로 인해 발생한 것이 아닌, 기존(pre-existing) 실패**입니다. 테스트 데이터의 `pubDate`가 고정값(`2026-05-17`)이고 freshness 점수가 현재 시간 기준으로 계산되기 때문에, 시간이 지남에 따라 자연스럽게 발생합니다.

---

## 권장 조치

1. **Freeze time in tests**: `pubDate`를 `datetime.now(timezone.utc)` 기준 상대값으로 설정 (예: `1시간 전`)하여 시간 의존성 제거
2. **Freeze `datetime.now()`**: pytest fixture나 unittest.mock으로 `datetime.now()`를 고정
3. **Adjust test expectations**: freshness 점수를 10점(24-72h)으로 낮추고 threshold 통과를 위해 다른 점수 보강
4. **현재 태스크와 무관하므로 우선순위 낮음**: KIS broker truth sync + duplicate sell guard 구현에 집중

---

## 변경 이력

| 일자 | 변경 내용 | 작성자 |
|------|---------|-------|
| 2026-05-19 | 최초 작성 — 2건 pre-existing 실패 분석 | Roo |
