# Phase P-3: Seeded News Pipeline — Top-N 정합성 점검 및 수정

**작성일:** 2026-05-17  
**대상:** [`SeededNewsCandidateService`](src/agent_trading/services/seeded_news_service.py) — `Retained` 집계 정의 / Top-N 적용 정합성  
**관련 Script:** [`scripts/validate_seeded_news_pipeline.py`](scripts/validate_seeded_news_pipeline.py)  
**관련 테스트:** [`tests/services/test_seeded_news_service.py`](tests/services/test_seeded_news_service.py)

---

## 1. 문제 정의

Phase P-3 실측 결과에서 `Retained` 수치가 설계상 `Top-N per symbol = max 3`을 초과:

| 종목 | Symbol | Seeds | 보고서 Retained | 설계 max 3 |
|------|--------|-------|:---------------:|:----------:|
| 삼성전자 | `005930` | 40 | 15 | 3 |
| SK하이닉스 | `000660` | 40 | 10 | 3 |
| NAVER | `035420` | 40 | 5 | 3 |
| 현대차 | `005380` | 40 | 4 | 3 |

### 핵심 질문
1. **`Retained`의 정확한 정의는 무엇인가?**
2. **`Top-N per symbol`은 실제 서비스 로직에서 적용되는가?**
3. **적용된다면 왜 보고 수치가 3을 초과하는가?**
4. **적용되지 않는다면 버그인가, 검증 스크립트 문제인가?**
5. **EI에 넘길 최종 후보 집합은 현재 몇 개인가?**

---

## 2. Root Cause 분석

### 2.1 변수명과 실제 동작의 불일치

| 구분 | 설계/주석상 의미 | 실제 동작 |
|------|-----------------|-----------|
| `_MAX_CANDIDATES_PER_SYMBOL = 3` | 종목(symbol)당 max 3 | **seed당** max 3 |
| `kept_count` docstring | "after score threshold and top-N" | 정확 (seed 단위 top-N 합계) |
| 보고서 "Retained (top-N)" | top-N 적용 후 종목별 수 | seed 단위 top-N 누적 결과 |

### 2.2 동작 상세

[`_process_one_seed()`](src/agent_trading/services/seeded_news_service.py:307):
```python
top_n = qualified[:_MAX_CANDIDATES_PER_SYMBOL]  # ← seed 단위 적용
return top_n, seed_metrics
```

`process_seeds()`에서 각 seed의 `top_n`을 `all_candidates`에 `extend()` 하므로, 동일 종목에 40개 seed가 있으면 종목별 retained는 **최대 40 × 3 = 120**까지 가능.

### 2.3 결론

**`Retained` 불일치의 근본 원인:**
- `_MAX_CANDIDATES_PER_SYMBOL` 변수명이 **종목(symbol) 단위** 제한을 암시했지만, 실제 적용은 **seed 단위**였음
- 종목별 retained 15/10/5/4는 각 seed당 max 3 제한이 정상 작동한 **누적 결과** (40개 seed 중 통과한 seed만 retained에 기여)
- **버그가 아니라 용어 정의와 설계 의도 사이의 불일치**

---

## 3. 수정 내용

### 3.1 [`src/agent_trading/services/seeded_news_service.py`](src/agent_trading/services/seeded_news_service.py)

| 변경점 | 이전 | 이후 | 라인 |
|--------|------|------|------|
| 상수명 | `_MAX_CANDIDATES_PER_SYMBOL = 3` | `_MAX_CANDIDATES_PER_SEED = 3` | 33 |
| 신규 상수 | 없음 | `_MAX_CANDIDATES_PER_SYMBOL_GLOBAL = 3` | 35-36 |
| seed 단위 Top-N | `qualified[:_MAX_CANDIDATES_PER_SYMBOL]` | `qualified[:_MAX_CANDIDATES_PER_SEED]` | 307 |
| **종목별 글로벌 Top-N** | 없음 | `_apply_global_top_n(all_candidates)` | 160-175 |
| `kept_count` 집계 | seed 단위 누적 (`+= len(candidates)`) | 글로벌 Top-N 적용 후 재계산 (`= len(all_candidates)`) | 177 |
| `per_symbol["kept"]` | seed 단위 누적 | 글로벌 Top-N 적용 후 동기화 | 180-183 |
| return 타입 | `list[SeededNewsCandidate]` | `tuple[list[SeededNewsCandidate], PipelineMetrics]` | 193 |

#### 글로벌 Top-N enforcement 로직

[`process_seeds()`](src/agent_trading/services/seeded_news_service.py:160-175):
```python
# process_seeds() — all_candidates 전역 정렬 후, return 직전
from collections import defaultdict
per_symbol: dict[str, list[SeededNewsCandidate]] = defaultdict(list)
for c in all_candidates:
    per_symbol[c.symbol].append(c)

final: list[SeededNewsCandidate] = []
for sym, candidates in per_symbol.items():
    candidates.sort(key=lambda x: x.confidence_score, reverse=True)
    final.extend(candidates[:_MAX_CANDIDATES_PER_SYMBOL_GLOBAL])

final.sort(key=lambda c: c.confidence_score, reverse=True)
all_candidates = final
metrics.kept_count = len(all_candidates)
```

### 3.2 [`scripts/validate_seeded_news_pipeline.py`](scripts/validate_seeded_news_pipeline.py)

| 변경점 | 이전 | 이후 |
|--------|------|------|
| 출력 컬럼 | 모호한 "Retained" | `Seeds \| Raw \| HardGate \| Deduped \| Threshold \| Top-N(global) \| Top Score` |
| 종목별 breakdown | `results` 단순 필터링 | `metrics.per_symbol` + `results` 병합 |
| EI 전달 후보 수 | 미표시 | `✅ Total candidates delivered to EI: N (max 3 per symbol globally)` |
| Metrics 출력 | `PipelineMetrics` 직접 참조 | `metrics` 객체 사용 (tuple return) |

### 3.3 [`tests/services/test_seeded_news_service.py`](tests/services/test_seeded_news_service.py)

| 변경점 | 내용 |
|--------|------|
| 기존 테스트 3개 | return 타입 변경에 따라 `results, metrics = await service.process_seeds(...)`로 tuple unpacking |
| **신규 테스트:** `test_global_top_n_limits_per_symbol` | 4개 seed (동일 symbol 005930) → 각 seed당 3개 candidate (총 12개) → 글로벌 Top-N(3) 적용 후 최종 **3개**만 retained 검증 |

---

## 4. 용어 정의 정리

### 4.1 단계별 Count 정의

| 용어 | 정의 | 코드 변수 | 계산 방식 |
|------|------|-----------|-----------|
| **Seeds** | 입력 seed 총 개수 | `metrics.seeds_total` | `len(seeds)` |
| **Raw** | NAVER API raw candidates | `metrics.raw_candidates_fetched` | 각 seed별 NAVER 검색 결과 합계 |
| **HardGate** | hard gate 통과 candidates | `metrics.hard_gate_passed` | company_name + keyword 필터 통과 |
| **Deduped** | 중복 제거 후 candidates | `metrics.deduped_count` | URL 기준 dedup 후 |
| **Threshold** | score threshold 통과 (≥50) | `metrics.dropped_low_confidence`의 여집합 | `len(qualified)` per seed 합계 |
| **Top-N(global)** | **종목별 글로벌 Top-3 적용 후 최종 retained** | `metrics.kept_count` | 글로벌 Top-N enforcement 후 `len(all_candidates)` |
| **EI 전달** | EI에 실제 전달되는 후보 수 | `len(all_candidates)` | `kept_count`와 동일 |

### 4.2 `Retained` 폐기

모호한 용어 `Retained`는 더 이상 사용하지 않음. 대신:
- 중간 단계: `Threshold pass count` (score threshold 통과)
- 최종 단계: `Top-N(global)` (종목별 글로벌 Top-3 적용 후)

---

## 5. 테스트 결과

### 5.1 신규 테스트 (`test_global_top_n_limits_per_symbol`)

```python
# Given: 4 seeds, 모두 005930 symbol, 각 seed당 3개 candidate mock
# When: process_seeds() 실행
# Then: 최종 retained = 3 (글로벌 Top-N 제한)
#       metrics.kept_count = 3 (일치)
#       score descending 정렬 유지
```

**결과: ✅ PASSED**

### 5.2 기존 테스트 회귀

```
tests/services/test_seeded_news_service.py::test_full_pipeline_integration       PASSED
tests/services/test_seeded_news_service.py::test_empty_seeds_returns_empty        PASSED
tests/services/test_seeded_news_service.py::test_hard_gate_filters_unrelated      PASSED
tests/services/test_seeded_news_service.py::test_global_top_n_limits_per_symbol   PASSED  ← 신규
```

**기존 회귀: 없음** ✅

---

## 6. Full Pipeline 재검증 결과

Docker rebuild 후 [`python3 -m scripts.validate_seeded_news_pipeline`](scripts/validate_seeded_news_pipeline.py) 실행.

### 6.1 Pipeline Metrics

```
seeds=160  queries=320  raw=412  hard_gate_pass=76  hard_gate_drop=336
deduped=76  dropped_low_conf=5  kept=12
```

### 6.2 종목별 Pipeline 결과

| Symbol | 종목명 | Seeds | Raw | HardGate | Deduped | Threshold | **Top-N(global)** | Top Score |
|--------|--------|:----:|:---:|:--------:|:-------:|:---------:|:-----------------:|:---------:|
| 005930 | 삼성전자 | 40 | — | — | — | — | **3** | 90.0 |
| 000660 | SK하이닉스 | 40 | — | — | — | — | **3** | 90.0 |
| 035420 | NAVER | 40 | — | — | — | — | **3** | 90.0 |
| 005380 | 현대차 | 40 | — | — | — | — | **3** | 90.0 |
| **Total** | | **160** | **412** | **76** | **76** | **71** | **12** | |

### 6.3 최종 EI 전달 후보 리스트

| # | Symbol | Score | Top-3 / Symbol |
|---|--------|:-----:|:--------------:|
| 1 | 005930 (삼성전자) | 90.0 | 1/3 |
| 2 | 005930 (삼성전자) | 90.0 | 2/3 |
| 3 | 000660 (SK하이닉스) | 90.0 | 1/3 |
| 4 | 035420 (NAVER) | 90.0 | 1/3 |
| 5 | 005380 (현대차) | 90.0 | 1/3 |
| 6 | 005930 (삼성전자) | 85.0 | **3/3** |
| 7 | 000660 (SK하이닉스) | 85.0 | 2/3 |
| 8 | 000660 (SK하이닉스) | 85.0 | **3/3** |
| 9 | 035420 (NAVER) | 85.0 | 2/3 |
| 10 | 035420 (NAVER) | 80.0 | **3/3** |
| 11 | 005380 (현대차) | 75.0 | 2/3 |
| 12 | 005380 (현대차) | 70.0 | **3/3** |

**Score descending 정렬 유지 확인** ✅ (90→90→90→90→90→85→85→85→85→80→75→70)

### 6.4 검증 결과 요약

| 항목 | 상태 | 값 |
|------|:----:|-----|
| Pipeline 정상 실행 | ✅ | Syntax error 없음 |
| 종목별 Threshold pass | ✅ | 여러 seed 통과 |
| 종목별 Top-N(global) 제한 | ✅ | **005930:3, 000660:3, 035420:3, 005380:3** |
| Score descending 정렬 | ✅ | 유지 |
| **Total EI 전달 후보** | ✅ | **12** (4 symbols × 3) |
| `metrics.kept_count` 일치 | ✅ | kept=12 === EI 전달 12 |
| **Top-N 정합성 수정 검증** | **✅ PASS** | 변경 코드가 의도대로 동작 |

---

## 7. EI Suitability 재판정

### 판정: **GO** ✅ (변경 없음)

| 평가 항목 | 상태 | 비고 |
|-----------|:----:|------|
| Top-N 적용 정합성 | ✅ 수정 완료 | 변수명 + 글로벌 Top-N enforcement |
| 단계별 count 명확화 | ✅ 완료 | 7단계 count 분리 |
| 테스트 커버리지 | ✅ 확보 | 신규 테스트 + 기존 회귀 없음 |
| EI 전달 후보 수 | ✅ **12 (max 3/symbol)** | 설계와 일치 |
| Pipeline 실측 검증 | ✅ 재확인 | 160 seeds → 12 retained |

---

## 8. 변경 파일 목록

| 파일 | 변경 유형 | 주요 내용 |
|------|-----------|-----------|
| [`src/agent_trading/services/seeded_news_service.py`](src/agent_trading/services/seeded_news_service.py) | 수정 | 상수명 정정, 글로벌 Top-N enforcement 추가, return 타입 변경 (tuple) |
| [`scripts/validate_seeded_news_pipeline.py`](scripts/validate_seeded_news_pipeline.py) | 수정 | 단계별 count 출력 분리, EI 전달 후보 수 명시 |
| [`tests/services/test_seeded_news_service.py`](tests/services/test_seeded_news_service.py) | 수정 | return 타입 변경 대응, 신규 테스트 추가 |

> **프런트엔드 변경 없음** — Admin UI는 이번 작업 범위 밖.

---

## 9. Q&A

### Q1. `Retained`의 정확한 정의는 무엇인가?
**A:** 수정 전 보고서에서 `Retained`는 **seed 단위 Top-N(3)이 적용된 후의 각 seed 결과를 종목별로 합산한 누적치**였습니다. 수정 후 모호한 `Retained` 용어를 폐기하고, `Threshold pass count`(중간 단계)와 `Top-N(global)`(최종 단계)로 분리했습니다.

### Q2. `Top-N per symbol`은 실제 서비스 로직에서 적용되는가?
**A:** 수정 전 **seed 단위**로만 적용되어 종목별 제한이 없었습니다. 수정 후 `_MAX_CANDIDATES_PER_SYMBOL_GLOBAL = 3` 상수가 `process_seeds()` 반환 직전에 종목별 글로벌 Top-3를 강제 적용합니다.

### Q3. 왜 보고 수치가 3을 초과했는가?
**A:** 동일 종목에 40개의 seed가 있고, 각 seed당 max 3개 retained가 허용되었으므로 종목별 최대 120개까지 가능했기 때문입니다.

### Q4. 버그인가, 검증 스크립트 문제인가?
**A:** **설계 의도(종목당 max 3)와 실제 구현(seed당 max 3) 사이의 용어/변수명 불일치**가 근본 원인입니다. 버그는 아니지만 의도와 다른 동작이었으며, 이번 수정으로 종목당 글로벌 Top-3 enforcement가 추가되어 설계 의도와 구현이 일치하게 되었습니다.

### Q5. EI에 넘길 최종 후보 집합은 현재 몇 개인가?
**A:** **12개** (4 symbols × max 3 per symbol). `PipelineMetrics.kept_count`와 일치합니다.

---

## 10. Pipeline 단계별 흐름도

```
KIS 공시 API (160 seeds) 
    → NAVER Search (320 queries → 412 raw)
    → Hard Gate (pass: 76, drop: 336)
    → Dedupe (76 unique)
    → Score & Threshold (≥50: 71 pass, <50: 5 drop)
    → Seed Top-N (max 3 per seed)
    → Global Top-N (max 3 per symbol) 
    → EI 전달 (total: 12)
```
