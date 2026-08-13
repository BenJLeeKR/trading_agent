# truth-probe와 KIS fill 누적→증분 해석 경로 병행 — 실행 계획

## 문서 성격

이 문서는 **실행 계획**이다. 상세 설계 근거는
[`docs/00_foundational_design/detailed_design/15_truth_probe_and_kis_fill_sync_coexistence_design.md`](../00_foundational_design/detailed_design/15_truth_probe_and_kis_fill_sync_coexistence_design.md)를
따른다. 이 문서를 작성한 턴 자체는 **설계/문서 작업**이며, 코드 구현·migration·
env/compose·런타임 변경은 포함하지 않는다.

## 1. 문제 재정의

- `sync_order_post_submit()`의 truth-probe(`_try_truth_probe()`)가 linked
  `broker_fill_snapshots` 기반으로 상태를 확정하면(`FILL_SNAPSHOT` reason),
  그 즉시 조기 반환하여 `_sync_fills()`(→ `get_fills()` → 누적→증분 해석
  → `fill_events`/ledger 적재)에 **전혀 도달하지 못한다.**
- 운영 관측(2026-08-13, non-terminal 주문 3건, 47분간 38 cycle) 결과 이
  차단이 예외 없이 매번 재현됐다 — 우연이 아니라 구조적 현상이다.
- 이 문제는 shadow(`KIS_FILL_INCREMENTAL_APPEND_ENABLED`) on/off와 무관한
  **선행 분기 구조 문제**다.

## 2. 현재 확인된 사실 / 미확정 쟁점 (요약 — 상세는 설계 문서 1절)

**확인된 사실**
- 조기 반환 지점은 `order_sync_service.py:719`.
- 차단 조건은 linked snapshot의 `filled_quantity > 0`(매수/매도 공통).
- 현재 운영 non-terminal 주문 3건 전부 이 조건에 해당.
- shadow 로그(`kis_fill_incremental summary` 등) 관측 0건 — 47분/38 cycle.

**미확정 쟁점**
- 신규 주문이 snapshot 없는 초기 구간에서 `_sync_fills()`까지 도달하는 실제 사례.
- 병행 호출 시 실제 중복 반영 발생 여부(이론적 방어선은 있으나 실측 없음).
- live 환경에서 동일 구조 재현 여부.
- `broker_fill_snapshots`와 `get_fills()` 누적값의 폴링 시점 차이로 인한 불일치 가능성.

## 3. 설계 대안 비교 (요약 — 상세는 설계 문서 4절)

| 대안 | 요지 | 채택 |
|---|---|---|
| 안 A | 모든 truth source에서 병행 호출 | 범위 과다 — 기각(원칙만 유지, 조건 좁힘) |
| 안 B | `FILL_SNAPSHOT` reason에서만 병행 호출 | **채택** |
| 안 C | `broker_fill_snapshots` 기반 별도 synthetic fill 경로 신설 | 과거 backfill 문제와 동일 축 — 이번 설계 범위 밖으로 분리 |
| 안 D | truth-probe와 fill 적재를 별도 worker로 완전 분리 | 구조는 깨끗하나 비용/범위 최대 — 이번 단계에서는 보류, 안 B가 불충분할 때 재검토 |

## 4. 추천안

**안 B — `FILL_SNAPSHOT` truth-probe 성공 시에만 `_sync_fills()` 병행 호출.**

핵심 근거(상세는 설계 문서 5절):
1. 실제 관측된 병목을 정확히 겨냥 — 다른 truth source는 건드리지 않아 회귀 위험 최소화.
2. 기존에 이미 구현된 2단계 dedup 방어선(`kis_fill_cumulative_state` delta 계산
   + `fill_events` 기존 broker_fill_id/composite key dedup)이 이 시나리오에도
   그대로 적용돼 중복 적재 위험이 구조적으로 낮다.
3. 병행 조건이 truth source 기준이라 시장가/지정가 분기가 필요 없다.
4. `FILL_SNAPSHOT`은 이미 partial/full을 하나의 함수(`_infer_linked_fill_snapshot_truth`)로
   판단하므로, 병행 호출도 별도 분기 없이 적용 가능하다.
5. `FILLED`(terminal) 결과에도 병행 호출을 유지해야 "마지막 증분" 누락을 막는다(설계 문서 5.5절).

## 5. 실행 단계별 계획

이 단계 구분은 **다음 구현 턴이 참고할 순서**이며, 이번 문서 작성 턴에서 실행하지 않는다.

1. **회귀 안전망 확인**: 구현 착수 전, 기존 `test_truth_probe_conflict.py`가
   다루는 시나리오(특히 `FILL_SNAPSHOT` reason 관련 테스트)를 다시 확인해
   병행 호출 추가로 깨질 수 있는 기존 기대값을 미리 파악한다.
2. **`sync_order_post_submit()`의 `FILL_SNAPSHOT` 분기 수정**: 조기 반환
   직전에 `_sync_fills()` 호출을 추가하고, 그 결과를 `SyncOrderResult`에
   반영한다(설계 문서 6절 개념 참고). `FILLED`/`PARTIALLY_FILLED` 결과
   모두에서 실행되도록 한다 — 조건에 "non-terminal일 때만"을 추가하지 않는다.
3. **관측 로그 추가**: "truth-probe가 `FILL_SNAPSHOT`으로 걸렸지만 이번엔
   `_sync_fills()`가 병행 실행됐다"를 구분할 수 있는 로그 문구를 추가한다
   (INFO 레벨 — 운영에서 보이도록, DEBUG 금지는 이전 turn들의 교훈 반복 적용).
4. **단위/통합 테스트 추가**(설계 문서 8절 4가지 시나리오):
   - `FILL_SNAPSHOT` + 병행 호출 → 정확히 1건만 append.
   - 반복 호출 → delta=0 no-op 확인.
   - terminal(`FILLED`) 전환 cycle에서도 병행 호출 및 마지막 증분 반영 확인.
   - `resolve_unknown_state`/`BUY_POSITION_FILL` 경로 회귀 없음(기존 테스트 그대로 통과).
5. **shadow 상태로 운영 배포** — `KIS_FILL_INCREMENTAL_APPEND_ENABLED=false` 기본값 유지, 병행 호출만 활성화.
6. **shadow 관측 기간**: 처음으로 `kis_fill_incremental summary`/`shadow_skip`/anomaly
   로그와 `kis_fill_cumulative_state` row 증가를 관측(설계 문서 8절 "운영에서
   확인해야 할 로그/테이블").
7. **회고 후 shadow 전환 여부 판단**: 관측 결과를 근거로 `KIS_FILL_INCREMENTAL_APPEND_ENABLED=true`
   전환 여부를 별도 턴에서 판단.
8. **(선택, 별도 축)** 과거 backfill 설계로 진행 여부 판단 — 이 실행계획의
   범위 밖이며, 위 1~7단계가 안정화된 뒤에만 검토 권장(설계 문서 5.7절).

## 6. 추가 보정사항

- 이번 문서 및 상세 설계 문서는 `resolve_unknown_state`/`BUY_POSITION_FILL`
  경로를 함께 고치는 것을 기본안으로 삼지 않는다 — 병목 증거가 있는
  `FILL_SNAPSHOT`만 좁게 다룬다.
- 시장가/지정가, 부분체결/전체체결을 별도 조건으로 나누지 않는다 —
  병행 여부의 유일한 조건은 truth source(`FILL_SNAPSHOT`)다.
- shadow 없는 즉시 실적재 전환은 이번 실행계획에 포함하지 않는다 — 6단계
  (shadow 관측)를 반드시 거친 뒤에만 7단계(전환 판단)로 넘어간다.
- 과거 backfill(2026-08-01 KST 이후 매도 등)은 이 실행계획의 8단계(선택,
  별도 축)로만 언급하며, 정식 설계/실행계획은 별도 문서에서 다뤄야 한다.

## 7. 그 외 유지해야 할 원칙

- `fill_events`는 계속 append-only, `realized_pnl_recompute_service`의
  1차 입력은 계속 `fill_events`만.
- `broker_fill_snapshots`는 계속 대사(reconciliation) 전용 — 이번 병행
  호출로도 recompute 입력으로 승격되지 않는다.
- truth-probe의 상태 확정 능력 자체는 그대로 유지 — "나쁜 코드"로 보고
  걷어내지 않는다.
- 불확실하면 append하지 않는다는 원칙(14번 문서)을 그대로 유지.

## 8. 완료 후 보고 가이드 (향후 구현 턴 대상)

이 실행 계획을 실제로 구현하는 턴은 완료 보고에 다음을 포함해야 한다:
- 변경 파일 목록(수정 지점이 `FILL_SNAPSHOT` 분기 하나로 좁게 유지됐는지)
- 추가한 관측 로그 문구
- 5절 4가지 테스트 시나리오의 실행 결과
- `test_truth_probe_conflict.py` 등 기존 테스트의 회귀 여부
- shadow 상태 유지 여부(반드시 `false` 기본값이어야 함)
- 아직 확정하지 못한 가정(§1의 미확정 쟁점 재확인 결과)
