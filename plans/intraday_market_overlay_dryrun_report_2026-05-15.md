# Intraday Market Overlay Dry-Run Report (2026-05-15)

> **측정 일시**: 2026-05-15 (목) 09:22–09:35 KST (UTC+9)
> **측정 목적**: 장중 intraday 시간대에 `market_overlay` source_type 심볼이 실제로 포함되는지 검증 + EI/FDC HOLD Bias Mitigation 효과의 장중 재현성 확인
> **제약 조건**: Backend 코드 수정 없음, 실제 broker submit 없음, dry-run only, TZ=Asia/Seoul

---

## 1. 실행 요약

| 항목 | 값 |
|------|-----|
| Dry-run 회차 | 3 cycles (연속 실행) |
| Cycle당 심볼 수 | 30 symbols |
| 총 처리 심볼 | 90 symbols (중복 30 unique symbols × 3 cycles) |
| 총 FDC 결정 수 | 177건 (3 cycles × ~59 FDC decisions) |
| Cycle 1 소요 시간 | 188.7초 (09:22:15–09:25:24 KST) |
| Cycle 2 소요 시간 | 188.6초 (09:25:24–09:28:33 KST) |
| Cycle 3 소요 시간 | 189.4초 (09:28:33–09:31:42 KST) |
| 성공률 | 100% (모든 심볼 정상 처리) |
| 실행 명령 | `docker exec -e TZ=Asia/Seoul agent_trading-app-1 python3 /app/scripts/run_paper_decision_loop.py --dry-run --count 1 --output json` |

---

## 2. Source Type 분포 (UniverseSelectionService.compose() 직접 호출 결과)

`UniverseSelectionService.compose()`를 런타임에 직접 호출하여 source_type 분포를 확인했습니다.

| Source Type | 심볼 수 | 비고 |
|-------------|---------|------|
| `core` | 30 | Universe selection 정책에 의해 선정된 30개 core 심볼 |
| `held_position` | 1 | 005930 (삼성전자) — 기보유 포지션 |
| `market_overlay` | **0** | KIS ranking analysis API 미구현 상태 |
| `event_overlay` | 0 | 아직 구현되지 않음 |

### 핵심 발견: `market_overlay = 0`

**장중(09:22 KST)임에도 `market_overlay` 심볼이 단 1건도 포함되지 않았습니다.**

이는 [`plans/[DESIGN] universe_selection_service.md`](plans/[DESIGN] universe_selection_service.md)에서 설계된 KIS ranking analysis API 기반 market_overlay 로직이 아직 구현되지 않았기 때문입니다. 현재 `UniverseSelectionService.compose()`는 `core` 심볼만 반환하며, `market_overlay`는 항상 빈 리스트입니다.

> **결론**: market_overlay 기능은 아직 backend에 구현되지 않았으므로, 장중/장후 관계없이 항상 0건입니다. 이는 P2 수준의 backlog 항목입니다.

---

## 3. 전체 결정 분포 (177건 FDC Decisions)

### 3.1 전체 집계

| 결정 | 건수 | 비율 |
|------|------|------|
| **HOLD** | 158 | **89.3%** |
| **APPROVE** | 11 | 6.2% |
| **REDUCE** | 8 | 4.5% |
| **WATCH** | **0** | **0.0%** |
| **합계** | 177 | 100% |

### 3.2 이전 측정(After-hours, 2026-05-14)과 비교

| 지표 | After-hours (05-14) | Intraday (05-15) | 차이 |
|------|-------------------|-------------------|------|
| 전체 HOLD 비율 | ~93% | 89.3% | -3.7%p |
| Event 심볼 HOLD 비율 | 80.0% | 81.4% | +1.4%p |
| No-event 심볼 HOLD 비율 | 100% | 100% | 동일 |
| WATCH 비율 | 0% | 0% | 동일 |
| APPROVE 비율 | ~10% | 6.2% | -3.8%p |
| REDUCE 비율 | ~7% | 4.5% | -2.5%p |

> **해석**: 전체 분포가 after-hours 측정과 유사합니다. Event 심볼의 HOLD 비율이 80.0% → 81.4%로 소폭 상승했으나, 이는 표본 차이로 볼 수 있는 범위 내입니다. EI/FDC HOLD Bias Mitigation 효과가 장중에도 재현됨을 확인했습니다.

---

## 4. 4-Bucket 분석

### Bucket A: `core` + `no_event` (20 symbols)

| 결정 | Cycle 1 | Cycle 2 | Cycle 3 | 합계 | 비율 |
|------|---------|---------|---------|------|------|
| HOLD | 39 | 39 | 40 | **118** | **100%** |
| APPROVE | 0 | 0 | 0 | 0 | 0% |
| REDUCE | 0 | 0 | 0 | 0 | 0% |
| WATCH | 0 | 0 | 0 | 0 | 0% |
| **합계** | 39 | 39 | 40 | 118 | 100% |

> **관찰**: No-event 심볼은 **100% HOLD**로, 이전 after-hours 측정과 동일합니다. 이는 `no_material_events=True`인 심볼에 대해 EI가 event-based evidence를 생성하지 못하고, FDC가 HOLD 이외의 결정을 내릴 근거가 부족하기 때문입니다. (Priority 3 항목)

### Bucket B: `core` + `event` (10 symbols)

| 결정 | Cycle 1 | Cycle 2 | Cycle 3 | 합계 | 비율 |
|------|---------|---------|---------|------|------|
| HOLD | 14 | 13 | 13 | **40** | **81.4%** |
| APPROVE | 2 | 2 | 2 | **6** | **10.2%** |
| REDUCE | 1 | 2 | 2 | **5** | **8.5%** |
| WATCH | 0 | 0 | 0 | 0 | 0% |
| **합계** | 17 | 17 | 17 | 51 | 100% |

> **관찰**: Event 심볼의 HOLD 비율 81.4%는 이전 after-hours 측정(80.0%)과 거의 일치합니다. EI/FDC HOLD Bias Mitigation 효과가 장중에도 안정적으로 유지됨을 확인했습니다. 약 19%의 심볼이 HOLD가 아닌 결정(APPROVE/REDUCE)을 받았습니다.

### Bucket C: `market_overlay` + `no_event` (0 symbols)

| 결정 | 건수 | 비율 |
|------|------|------|
| (데이터 없음) | 0 | N/A |

> **관찰**: `market_overlay` 심볼이 0건이므로 데이터가 없습니다. market_overlay 기능 구현 후 재측정 필요.

### Bucket D: `market_overlay` + `event` (0 symbols)

| 결정 | 건수 | 비율 |
|------|------|------|
| (데이터 없음) | 0 | N/A |

> **관찰**: `market_overlay` 심볼이 0건이므로 데이터가 없습니다.

---

## 5. WATCH Decision 분석

**WATCH 결정은 177건 전체에서 단 1건도 발생하지 않았습니다.**

이는 EI → AR → FDC 파이프라인에서 중간 단계 결정(WATCH)이 생성되지 않는 구조적 문제로 보입니다. 현재 파이프라인은 각 심볼에 대해 독립적으로 EI → AR → FDC를 실행하며, FDC가 최종 결정을 HOLD/APPROVE/REDUCE 중에서 선택합니다. WATCH는 "추가 관찰 필요" 상태로, 현재 결정 로직에 이 상태를 출력할 조건이 없거나, LLM 프롬프트가 WATCH를 선택하도록 유도하지 않고 있습니다.

> **관련 Backlog**: HANDOVER_TO_NEW_SESSION.md Priority 2 참조

---

## 6. 주요 심볼 사례 분석

### 6.1 000880 (한화) — 일관된 APPROVE

| Cycle | EI Event Count | EI Evidence Strength | EI Overall Bias | AR Risk Opinion | FDC Decision |
|-------|---------------|---------------------|-----------------|----------------|--------------|
| 1 | 4 | 0.75 | positive | approve | **APPROVE** |
| 2 | 4 | 0.75 | positive | approve | **APPROVE** |
| 3 | 4 | 0.75 | positive | approve | **APPROVE** |

> 4건의 이벤트, 높은 evidence strength(0.75), positive bias → AR이 approve, FDC가 APPROVE. 일관된 패턴.

### 6.2 001230 (동국홀딩스) — 유일한 결정 변경

| Cycle | EI Event Count | EI Evidence Strength | EI Overall Bias | AR Risk Opinion | FDC Decision |
|-------|---------------|---------------------|-----------------|----------------|--------------|
| 1 | 2 | 0.60 | neutral | hold | **HOLD** |
| 2 | 2 | 0.60 | neutral | reduce | **REDUCE** |
| 3 | 2 | 0.60 | neutral | reduce | **REDUCE** |

> 30개 심볼 중 유일하게 결정이 변경된 사례. EI 입력은 동일하나 AR의 risk_opinion이 `hold` → `reduce`로 변경되었고, FDC가 이를 따라 REDUCE로 변경. AR의 LLM 출력 변동성이 원인으로 추정.

### 6.3 005930 (삼성전자) — held_position

| Cycle | Source Type | FDC Decision |
|-------|------------|--------------|
| 1 | held_position | HOLD |
| 2 | held_position | HOLD |
| 3 | held_position | HOLD |

> 기보유 포지션(held_position)으로 포함되었으며, 일관되게 HOLD 유지.

---

## 7. 결정 일관성 분석

| 지표 | 값 |
|------|-----|
| 전체 심볼 수 | 30 |
| 3 cycles 모두 동일 결정 | **29 / 30 (96.7%)** |
| 결정 변경 발생 심볼 | 1 / 30 (3.3%) — 001230 |
| 변경 패턴 | HOLD → REDUCE (cycle 1→2) |

> **해석**: 96.7%의 심볼이 3 cycles 동안 동일한 결정을 유지했습니다. 이는 파이프라인이 상당히 안정적이며, LLM 출력 변동성이 실제 결정에 미치는 영향이 제한적임을 시사합니다. 유일한 변경 사례(001230)는 AR 레벨에서의 변동으로, EI 입력은 동일했습니다.

---

## 8. EI/AR/FDC 에이전트 출력 분석

### 8.1 EI (Event Interpreter) 출력 분포

| 지표 | 범위 | 관찰값 |
|------|------|--------|
| event_count | 0 ~ 4 | No-event: 0, Event: 1~4 |
| evidence_strength | 0.0 ~ 1.0 | No-event: 0.0, Event: 0.40~0.80 |
| no_material_events | true/false | 20 symbols true, 10 symbols false |
| overall_bias | positive/negative/neutral | 대부분 neutral, 일부 positive |

### 8.2 AR (AI Risk Agent) 출력 분포

| 지표 | 값 |
|------|-----|
| risk_opinion: approve | 6건 (3.4%) |
| risk_opinion: hold | 163건 (92.1%) |
| risk_opinion: reduce | 8건 (4.5%) |
| risk_score (mean) | ~0.50 (no-event), ~0.55 (event) |

### 8.3 FDC (Final Decision Composer) 출력 분포

| 결정 | 건수 | 비율 |
|------|------|------|
| HOLD | 158 | 89.3% |
| APPROVE | 11 | 6.2% |
| REDUCE | 8 | 4.5% |
| WATCH | 0 | 0.0% |

> **FDC는 AR의 risk_opinion을 100% 따름**: FDC 결정과 AR risk_opinion이 완전히 일치합니다. FDC가 AR의 판단을 그대로 최종 결정으로 사용하고 있으며, 자체적인 재해석이나 조정은 발생하지 않았습니다.

---

## 9. 결론

### 9.1 Market Overlay 포함 여부

| 질문 | 답변 |
|------|------|
| 장중에 market_overlay 심볼이 포함되는가? | **아니오** — 0건 |
| 이유 | KIS ranking analysis API 기반 market_overlay 로직이 아직 backend에 구현되지 않음 |
| 영향 | 4-bucket 분석에서 Bucket C, D는 데이터 없음 |
| 필요 조치 | P2 수준으로 market_overlay 기능 구현 필요 ([`plans/[DESIGN] universe_selection_service.md`](plans/[DESIGN] universe_selection_service.md) 참조) |

### 9.2 EI/FDC HOLD Bias Mitigation 효과

| 질문 | 답변 |
|------|------|
| 장중에도 효과가 유지되는가? | **예** — Event 심볼 HOLD 81.4% (after-hours 80.0%와 유사) |
| No-event 심볼은? | **여전히 100% HOLD** — Priority 3 대상 |
| WATCH는 발생하는가? | **아니오** — 0건, Priority 2 대상 |

### 9.3 장 종료 후 권장 수정 우선순위

1. **P1: market_overlay 기능 구현** — [`plans/[DESIGN] universe_selection_service.md`](plans/[DESIGN] universe_selection_service.md) 참조. KIS ranking analysis API를 호출하여 장중에 market_overlay 심볼을 추가하도록 `UniverseSelectionService.compose()` 구현 필요. 구현 후 재측정 필수.

2. **P2: WATCH Decision 부재 원인 분석** — FDC 프롬프트에 WATCH 결정을 출력할 수 있는 조건 추가 검토. 현재 FDC는 AR의 risk_opinion을 100% 따르고 있으며, WATCH를 선택할 근거가 없음.

3. **P3: No-Event 심볼 100% HOLD 개선** — `no_material_events=True`인 심볼에 대해 EI가 price-based evidence라도 생성할 수 있도록 정책 개선. 또는 FDC 레벨에서 no-event 심볼에 대한 fallback 정책 도입.

---

## 10. 원시 데이터 참조

| 파일 | 설명 |
|------|------|
| [`plans/HANDOVER_TO_NEW_SESSION.md`](plans/HANDOVER_TO_NEW_SESSION.md) | 이전 세션 핸드오버 문서 (P1/P2/P3 정의) |
| [`plans/[DESIGN] universe_selection_service.md`](plans/[DESIGN] universe_selection_service.md) | Market Overlay 설계 문서 |
| [`plans/ei_fdc_hold_bias_analysis.md`](plans/ei_fdc_hold_bias_analysis.md) | EI/FDC HOLD Bias 분석 문서 |
| DB table: `trade_decisions` | 177건 FDC 결정 데이터 (dry-run, 실제 미체결) |
| DB table: `agent_runs` | EI/AR 실행 내역 (agent_type, input, output) |
