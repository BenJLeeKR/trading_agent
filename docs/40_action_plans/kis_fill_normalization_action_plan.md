# KIS 체결 응답 정규화 및 누적→증분 해석 — 실행 계획

## 문서 성격

이 문서는 **실행 계획**이다. 상세 설계 근거는
[`docs/00_foundational_design/detailed_design/14_kis_fill_normalization_and_incremental_interpretation_design.md`](../00_foundational_design/detailed_design/14_kis_fill_normalization_and_incremental_interpretation_design.md)를 따른다.

**구현 현황**: 아래 5절의 1~4단계는 별도 구현 턴에서 완료됐다(shadow 모드,
`KIS_FILL_INCREMENTAL_APPEND_ENABLED=false` 기본값). 5~7단계(shadow 관측
기간, 실 전환, 회고)는 아직 미착수다 — 지금은 shadow 모드로 관측 로그만
쌓이는 단계다.

## 1. 문제 재정의

- `trading.fill_events`가 전 기간 0건이라 실현손익 ledger(`realized_pnl_events` 등)도 전부 비어 있다.
- 원인은 (a) `KISRestClient.get_fills()`가 실제 paper 응답 필드명(`tot_ccld_qty`/`avg_prvs`, 소문자 키)과 어긋나는 필드명(`CCLD_QTY`/`CCLD_UNPR`, 대소문자 무관 처리 없음)을 읽고 있다는 점, (b) `TOT_CCLD_QTY`가 누적값일 가능성이 높아 그대로 fill 수량으로 쓰면 append-only ledger에 중복/과잉 계상이 발생할 수 있다는 점, 두 가지가 겹쳐 있다.
- 이번 실행 계획은 이 두 문제를 **주문 유형별 예외 경로가 아니라 범용 정규화/증분 해석 계층**으로 해결하는 구현을 준비하기 위한 단계별 계획이다.

## 2. 현재 확인된 사실 / 미확정 쟁점 (요약 — 상세는 설계 문서 1절)

**확인된 사실**
- `get_fills()`의 필드 접근이 실제 응답과 어긋난다(당일 체결완료 시장가 3건, read-only 실사로 직접 확인).
- `fill_history_sync.py`는 이미 `TOT_CCLD_QTY`→`CCLD_QTY`, `AVG_PRVS`→`CCLD_UNPR` fallback을 쓰고 있다(다른 저장소 `broker_fill_snapshots`용).
- `RealizedPnlLedgerService.apply_fill()`은 fill_event 1건을 "이번 증분"으로 간주하는 구조다.

**미확정 쟁점**
- `TOT_CCLD_QTY`가 정말 누적값인지(부분체결 반복 표본으로 아직 확인 못함).
- 지정가 주문의 필드셋.
- live 환경의 실제 응답 스키마.
- 오래된 주문의 조회 실패(0 rows) 원인(이 계획의 핵심 문제와는 별개 현상으로 분리).

## 3. 설계 대안 비교 (요약 — 상세는 설계 문서 3.2절)

| 대안 | 요지 | 채택 |
|---|---|---|
| 안 A | 누적 스냅샷 + 직전 관측 대비 delta 계산 | 전략으로 채택 |
| 안 B | row 자체를 fill event로 간주, 직전 최대치와 비교 | 안 A로 수렴하는 열등한 변형 — 기각 |
| 안 C | 전용 상태 테이블(`kis_fill_cumulative_state`)로 직전 관측치를 영속화 | 안 A의 구현 메커니즘으로 채택 |

## 4. 추천안

1. `KISRestClient._get_kis_field()` + `fill_history_sync._get_kis_value()`에 해당하는 로직을 공통 모듈(`agent_trading/brokers/koreainvestment/kis_field_mapping.py`, 신규)로 추출.
2. `get_fills()` 내부에 정규화 계층(`NormalizedKisFillObservation`)과 누적→증분 해석 계층(`resolve_incremental_fill()`)을 추가하되, **반환 타입(`Sequence[FillEvent]`)과 호출 계약은 바꾸지 않는다** — `order_sync_service._sync_fills()` 쪽 변경을 최소화.
3. 신규 상태 테이블 `kis_fill_cumulative_state`(계좌×브로커주문번호 단위, 마지막 관측 누적치 보관)를 도입해 delta 계산의 기준점을 영속화. 행 단위 트랜잭션 락으로 동시 폴러 경쟁 조건을 방지.
4. 음수 delta/파싱 실패/정정 플래그는 자동으로 처리하지 않고 anomaly로 분리 — `fill_events`에 아무것도 append하지 않는다.
5. 전개는 **shadow 모드 선행**(loss_cut_shadow 선례와 동일한 원칙)을 강력 권장 — 관측 로그만 쌓다가, live 사전 검증(6.6절 체크리스트)을 통과한 뒤 실제 append로 전환.

## 5. 구현 단계별 계획

1. **공통 필드 매핑 모듈 추출** — ✅ 완료: `kis_field_mapping.py` 신설, `get_kis_field`/`get_kis_value`로 `_get_kis_field`/`fill_history_sync._get_kis_value`를 공통화, `rest_client.py`/`fill_history_sync.py` import 조정.
2. **정규화 계층 구현** — ✅ 완료: `kis_fill_normalization.py`의 `NormalizedKisFillObservation` + `normalize_kis_fill_observation()`. 단위 테스트로 실제 paper 응답 표본(`odno`/`pdno`/`tot_ccld_qty`/`avg_prvs` 소문자 키) 재현.
3. **상태 테이블 migration** — ✅ 완료: `db/migrations/0056_add_kis_fill_cumulative_state.sql`(구현 시점 최신 번호 `0055_...` 확인 후 `0056`으로 결정).
4. **해석 계층 구현** — ✅ 완료: `kis_fill_incremental_resolver.py`의 `resolve_incremental_fill()` + `KisFillCumulativeStateRepository`(postgres는 `SELECT ... FOR UPDATE`로 동시성 락). shadow 모드 flag는 `KIS_FILL_INCREMENTAL_APPEND_ENABLED`(기본값 `false`)로 확정, `docker-compose.yml` `ops-scheduler`에도 배선.
5. **shadow 관측 기간** — 미착수. 운영에서 로그만 쌓으며 delta 계산이 실제 체결과 맞는지 확인(설계 문서 6절 체크리스트와 연계) — 다음 단계.
6. **전환** — 미착수. 사전 검증 통과 후 `KIS_FILL_INCREMENTAL_APPEND_ENABLED=true`로 전환.
7. **회고/정리** — 미착수.

## 6. 추가 보정사항

- 이번 문서 및 상세 설계 문서는 **시장가만**, **완전체결만** 한정하는 경로를 기본안으로 삼지 않는다 — 범용 정규화/증분 해석 경로가 기본안이다.
- `TOT_CCLD_QTY`가 누적값이라는 것은 강한 가설이며 완전한 확정은 아니었다 — 구현 자체는 이 가설을 전제로 진행했으나(안 A 채택), shadow 모드 기본값 `false`로 실제 append 전환은 자연 발생 부분체결 표본으로 재검증한 뒤에만 켜야 한다.
- live 환경 필드 스키마는 이번 설계 근거에 전혀 포함되지 않았다 — live 전개 전 별도 read-only 검증이 필수다.
- 정정/취소가 섞인 표본에 대한 처리는 이번 설계에서 "자동 처리하지 않고 분리"하는 수준까지만 다룬다 — 자동 역산 로직은 범위 밖이다.

## 7. 그 외 유지해야 할 원칙

- `order_sync_service._sync_fills()`의 기존 dedup(broker_fill_id/composite key)은 삭제하지 않는다 — 2차 방어선으로 유지.
- `fill_history_sync.py` → `broker_fill_snapshots` 경로는 그대로 두고, 신규 경로와 저장소를 합치지 않는다(대사 전용 vs 도메인 원장 분리 유지).
- `realized_pnl_recompute_service.py`의 "`fill_events`만을 1차 입력으로 삼는다"는 기존 계약을 바꾸지 않는다.
- 로그는 INFO 레벨로 남기고(DEBUG는 운영에서 보이지 않는다는 점이 이미 확인됨), 원문 응답 본문은 로그/문서 어디에도 남기지 않는다.

## 8. 완료 후 보고 가이드 (향후 구현 턴 대상)

이 실행 계획을 실제로 구현하는 턴은 완료 보고에 다음을 포함해야 한다:
- 신규/변경 파일 목록(공통 모듈, 정규화 계층, 상태 테이블 migration, feature flag 배선 등)
- shadow 모드로 시작했는지 여부, 전환 조건
- `bash scripts/harness/run.sh accept backend-file <file>` 등 대응 계층별 검증 결과
- `TOT_CCLD_QTY` 누적/증분 가설이 실제 구현 검증 단계에서 어떻게 재확인됐는지
- live 전개 전 사전 검증 체크리스트(설계 문서 6절) 충족 여부
- 아직 확정하지 못한 가정(정정/취소 처리, live 스키마 등)
