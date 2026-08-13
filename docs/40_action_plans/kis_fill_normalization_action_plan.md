# KIS 체결 응답 정규화 및 누적→증분 해석 — 실행 계획

## 문서 성격

이 문서는 **실행 계획**이다. 상세 설계 근거는
[`docs/00_foundational_design/detailed_design/14_kis_fill_normalization_and_incremental_interpretation_design.md`](../00_foundational_design/detailed_design/14_kis_fill_normalization_and_incremental_interpretation_design.md)를 따른다.
이번 문서를 작성한 턴 자체는 **설계/문서 작업**이며, 코드 구현·migration·런타임 변경은 포함하지 않는다.

## 1. 문제 재정의

- `trading.fill_events`가 전 기간 0건이라 실현손익 ledger(`realized_pnl_events` 등)도 전부 비어 있다.
- 원인은 (a) `KISRestClient.get_fills()`가 실제 paper 응답 필드명(`tot_ccld_qty`/`avg_prvs`, 소문자 키)과 어긋나는 필드명(`CCLD_QTY`/`CCLD_UNPR`, 대소문자 무관 처리 없음)을 읽고 있다는 점, (b) `TOT_CCLD_QTY`가 누적값이어서 그대로 fill 수량으로 쓰면 append-only ledger에 중복/과잉 계상이 발생할 수 있다는 점, 두 가지가 겹쳐 있다. (b)는 이후 `000227`/2026-06-23 KST 자연 발생 부분체결 표본으로 실증적으로 뒷받침됐다(2절 참고).
- 이번 실행 계획은 이 두 문제를 **주문 유형별 예외 경로가 아니라 범용 정규화/증분 해석 계층**으로 해결하는 구현을 준비하기 위한 단계별 계획이다.

## 2. 현재 확인된 사실 / 미확정 쟁점 (요약 — 상세는 설계 문서 1절)

**확인된 사실**
- `get_fills()`의 필드 접근이 실제 응답과 어긋난다(당일 체결완료 표본, read-only 실사로 직접 확인).
- `fill_history_sync.py`는 이미 `TOT_CCLD_QTY`→`CCLD_QTY`, `AVG_PRVS`→`CCLD_UNPR` fallback을 쓰고 있다(다른 저장소 `broker_fill_snapshots`용).
- `RealizedPnlLedgerService.apply_fill()`은 fill_event 1건을 "이번 증분"으로 간주하는 구조다.
- **`TOT_CCLD_QTY`가 누적값이라는 핵심 가정은 자연 발생 부분체결 표본(`000227`/2026-06-23 KST, `broker_fill_snapshots` 시계열 `0→11→259` staircase)으로 실증적으로 뒷받침됐다.** 이 근거는 당시 `fill_history_sync.py`가 캡처해 둔 관측값을 통한 간접 실증이며, 같은 상황에서 raw `inquire-daily-ccld`를 직접 여러 시점에 재호출해 확인한 것은 아니다(설계 문서 1.2절 참고). 이 확인은 주문 유형(시장가/지정가)과 무관하게 "누적 스냅샷" 해석 자체를 검증한 것이다.

**미확정 쟁점** (주문 유형 구분은 이 계획의 검증 축이 아니므로 미확정 항목에 포함하지 않는다)
- 정정/취소가 섞인 경우 delta 해석이 실제로 안전하게 anomaly로 분리되는지 — 표본 없음.
- live 환경의 실제 응답 스키마 및 누적 의미론 — 전혀 확인 안 됨(paper 전용 조사).
- 부분체결 진행 중 raw `inquire-daily-ccld` 응답을 직접 여러 시점에 재관측한 사례가 아직 없음(현재 근거는 `broker_fill_snapshots`를 통한 간접 확인).
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

## 5. 구현 단계별 계획 (이번 턴 미착수 — 향후 별도 구현 턴을 위한 순서 제안)

이 단계 구분은 **다음 구현 턴이 참고할 순서**이며, 이번 문서 작성 턴에서 실행하지 않는다.

1. **공통 필드 매핑 모듈 추출**: `kis_field_mapping.py` 신설, `_get_kis_field`/`_get_kis_value` 이관, `rest_client.py`/`fill_history_sync.py` import 경로 조정(동작 변경 없는 리팩터링만).
2. **정규화 계층 구현**: `NormalizedKisFillObservation` + `normalize_kis_fill_observation()`, 단위 테스트로 paper 응답 표본(당일 시장가 완전체결 케이스) 재현.
3. **상태 테이블 migration**: `kis_fill_cumulative_state` 추가(다음 가용 migration 번호는 구현 시점에 `db/migrations/` 최신 번호를 다시 확인해 정한다 — 이 문서 작성 시점 최신은 `0055_...`이며 임의로 다음 번호를 고정하지 않는다).
4. **해석 계층 구현**: `resolve_incremental_fill()` + repository, 동시성 락 포함. shadow 모드 feature flag(`KIS_FILL_INCREMENTAL_RESOLUTION_SHADOW_ENABLED` 등, 이름은 구현 턴에서 확정) 추가.
5. **shadow 관측 기간**: 운영에서 로그만 쌓으며 delta 계산이 실제 체결과 맞는지 확인(6절 체크리스트와 연계).
6. **전환**: 사전 검증 통과 후 실제 `fill_events.add()` 경로로 전환.
7. **회고/정리**: shadow 기간 로그를 근거로 anomaly 비율, delta 계산 정확도를 정리해 운영 판단 문서화(loss_cut_shadow_inspection_operations_guide.md와 유사한 성격의 문서를 이 경로용으로도 검토할 수 있음 — 필요 여부는 구현 이후 판단).

## 6. 추가 보정사항

- 이번 문서 및 상세 설계 문서는 **주문 유형별(시장가/지정가) 예외 경로나 단계적 도입(예: "시장가부터 먼저")을 기본안으로 삼지 않는다** — 범용 정규화 + 누적→증분 해석 경로가 유일한 기본안이며, 부분체결/완전체결은 같은 모델 안에서 해석되는 관측 형태의 차이일 뿐 설계 분기 축이 아니다.
- `TOT_CCLD_QTY`가 누적값이라는 핵심 가정은 `000227`/2026-06-23 KST 자연 발생 부분체결 표본으로 **실증적으로 보강됐다** — 이 쟁점을 이유로 구현을 보류할 단계는 아니다. 다만 이 근거는 `broker_fill_snapshots` 시계열을 통한 간접 확인이므로, 구현 턴은 shadow 관측 기간 동안 raw 응답을 직접 재관측해 재확인하는 것을 병행해야 한다(shadow 관측 자체를 생략할 근거는 아니다).
- live 환경 필드 스키마는 이번 설계 근거에 전혀 포함되지 않았다 — live 전개 전 별도 read-only 검증이 필수다.
- 정정/취소가 섞인 표본에 대한 처리는 이번 설계에서 "자동 처리하지 않고 분리"하는 수준까지만 다룬다 — 자동 역산 로직은 범위 밖이다. 이 쟁점은 여전히 표본이 없는 상태다.

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
- `TOT_CCLD_QTY` 누적 해석(간접 근거로 뒷받침됨)이 구현 단계의 직접 재관측(raw 응답 다단계 관측)으로 어떻게 재확인됐는지
- live 전개 전 사전 검증 체크리스트(설계 문서 6절) 충족 여부
- 아직 확정하지 못한 가정(정정/취소 처리, live 스키마 등)
