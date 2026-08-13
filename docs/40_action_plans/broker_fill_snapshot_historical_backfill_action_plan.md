# `broker_fill_snapshots` 기반 과거 체결 backfill — 실행 계획

## 문서 성격

이 문서는 **실행 계획**이다. 상세 설계 근거는
[`docs/00_foundational_design/detailed_design/16_broker_fill_snapshot_historical_backfill_design.md`](../00_foundational_design/detailed_design/16_broker_fill_snapshot_historical_backfill_design.md)를
따른다.

**구현 현황**: 아래 5절의 1~4단계는 별도 구현 턴에서 완료됐다(원가
완결성 판정 + 변환 규칙 순수 로직 + dry-run/apply 겸용 서비스/CLI,
단위 테스트 포함). 5~8단계(실제 후보에 대한 사람 승인 + apply 실행,
recompute 워커 소비 확인, 회고)는 아직 미착수다 — 이번 구현 턴에서는
실제 운영 DB에 대한 apply를 실행하지 않았다.

**이 실행 계획은 과거 복원(backfill) 전용이다.** 미래 체결 경로 정상화는
[`kis_fill_normalization_action_plan.md`](kis_fill_normalization_action_plan.md)/
[`truth_probe_kis_fill_sync_coexistence_action_plan.md`](truth_probe_kis_fill_sync_coexistence_action_plan.md)
를 따르며, 이 문서와는 별개 축이다.

## 1. 문제 재정의

- `fill_events`가 비어 있던 기간의 과거 매도(및 그 원가 형성에 필요한
  매수)는, 현재 recompute만으로는 복원되지 않는다 — recompute는
  `fill_events`를 replay할 뿐 신규 fill을 만들지 않는다.
- `broker_fill_snapshots`에 일부 과거 주문의 누적 체결 관측 흔적이
  남아 있어, 이를 근거로 synthetic `fill_events`를 사후 재구성하는
  것이 이론적으로 가능하다.
- 다만 이미 조사된 표본(`2026-08-01 KST` 이후 매도 2건)은 매우 작고
  단순한 케이스뿐이라, 일반화하기 전에 보수적으로 접근해야 한다.

## 2. 현재 확인된 사실 / 미확정 쟁점 (요약 — 상세는 설계 문서 1절)

**확인된 사실**
- `realized_pnl_events.fill_event_id`가 UNIQUE NOT NULL이라 `fill_events`를
  거치지 않고 손익 원장에 직접 쓰는 경로는 스키마상 없다.
- `fill_events.source_channel` CHECK 제약이 이미 `'backfill'` 값을
  허용한다 — 신규 migration 없이 구분자로 쓸 수 있다.
- `realized_pnl_recompute_queue.reason_code`가 이미 `'manual_request'`를
  허용한다 — backfill이 이 값을 그대로 재사용할 수 있다.
- 매도만 복원해서는 이동평균 원가 계산이 완결되지 않는다 — 그 매도의
  원가 형성에 필요한 선행 매수까지 함께 복원해야 한다(설계 문서 1.3절/
  3.2절).

**미확정 쟁점**
- 실제 원가 완결성 기준(설계 문서 3.3절)을 만족하는 계좌×종목이 몇
  건인지 — 아직 read-only로 조사되지 않았다.
- 부분체결 다단계 매도의 일반적 품질, 정정/취소 혼재 케이스 처리의
  실제 검증 — 표본 없음.
- snapshot 1건짜리 주문의 일반적 안전성(완전체결 vs 관측 공백 구분).
- live 환경 확장 가능성.

## 3. 설계 대안 비교 (요약 — 상세는 설계 문서 5절)

| 대안 | 요지 | 채택 |
|---|---|---|
| 안 A | `fill_events`에 직접 synthetic 행 append + 이후 recompute | **채택(dry-run 승인 절차를 얹은 형태로)** |
| 안 B | 별도 staging 테이블에 먼저 적재 후 검증 후 promote | 별도 테이블은 두지 않되, "검토 후 진행"이라는 정신은 dry-run 절차로 흡수 |
| 안 C | `realized_pnl_events`를 직접 재구성 | 기각 — `fill_event_id` UNIQUE 제약과 충돌, 감사 추적성 저해 |

## 4. 추천안

1. **모집단 제한**: 계좌 1개, `2026-08-01 KST` ~ 15번 안 B 실배포 이전
   `FILLED` 전환분, 종목 단위 원가 완결성(완전 청산 시작점 확인 가능,
   snapshot 끊김 없음, cancel/정정 흔적 없음) 기준을 만족하는 경우만.
2. **변환 규칙**: 14번 문서의 가중평균 분해 공식을 재사용하되,
   `kis_fill_cumulative_state`(실시간 폴링 전용 상태 테이블)는 재사용하지
   않는다 — 정렬된 snapshot 시계열 전체를 한 번에 순회하는 순수 함수로
   구현한다. anomaly가 하나라도 나오면 그 종목 전체를 backfill 대상에서
   제외한다(부분 반영하지 않는다).
3. **저장 경로**: `fill_events`에 `source_channel='backfill'`로 직접
   append하되, 반드시 **dry-run(계산 결과만 리포트) → 사람 승인 →
   실제 append** 순서를 지킨다.
4. **idempotency/감사**: 기존 dedup 원리(broker_fill_id 우선,
   composite key fallback)를 backfill 배치 코드에 독립적으로 구현하고,
   `raw_payload_uri`에 근거 snapshot id와 backfill 실행 식별자를 남긴다.
5. **recompute 연결**: backfill이 직접 recompute를 실행하지 않고,
   `realized_pnl_recompute_queue`(`reason_code='manual_request'`)에
   등록해 이미 배포된 `realized-pnl-recompute-worker`가 소비하게 한다.

## 5. 실행 단계별 계획

1. **read-only 모집단 조사(구현 착수 전 필수)** — ✅ 완료(별도 read-only
   조사 턴). `2026-08-01 KST` 이후 filled 주문 14건(매수 12/매도 2) 중
   매도가 존재하는 종목은 1개뿐이었고, 이 1개 종목(1 buy + 2 sell)이
   원가 완결성 기준을 충족하는 것으로 확인됐다.
2. **변환 규칙 순수 함수 구현 + 단위 테스트** — ✅ 완료:
   `historical_fill_backfill.py`가 14번 문서 `_infer_delta_price()`를
   재사용해 음수 delta/가격 산출 불가/cancel 흔적을 anomaly로 분리한다.
   `tests/services/test_historical_fill_backfill.py`의
   `TestExclusionReasons`로 각 사유를 독립 검증했다.
3. **원가 완결성 판정 로직 구현 + 단위 테스트** — ✅ 완료: `build_backfill_
   plan()`이 `position_snapshots.get_latest_by_account_and_instrument_
   before()`로 zero-crossing anchor를 찾고, anchor~첫 주문 사이 gap
   주문/snapshot 누락/lineage 불일치를 각각 감지해 전체 제외한다.
4. **dry-run 배치 스크립트 구현** — ✅ 완료: `scripts/backfill_broker_
   fill_snapshot_historical_fills.py --mode dry-run`(기본값)가 계좌×종목
   별 예상 synthetic fill/최종 잔량/브로커 잔량 대비 정합성을 리포트로만
   출력한다. `--mode apply`도 같은 턴에서 구현했으나(§0.1), 실제 운영
   DB에 대한 apply 실행은 아직 하지 않았다.
5. **dry-run 결과에 대한 사람 검토 + 승인** — 미착수. 이 단계는
   자동화하지 않는다 — 사용자가 리포트를 직접 확인하고, 실제 append를
   진행할 대상(계좌×종목 목록)을 명시적으로 승인해야 다음 단계로
   진행한다.
6. **승인된 대상만 실제 append 모드로 실행** — 미착수. `source_channel
   ='backfill'`로 `fill_events`에 append하고, 해당 계좌×종목을
   `realized_pnl_recompute_queue`에 등록한다.
7. **recompute 워커의 자연 소비 확인 + 결과 read-only 재확인** — 미착수.
   배치 실행 후 `realized-pnl-recompute-worker`가 큐를 소비했는지,
   결과 `realized_pnl_events`/`realized_pnl_daily_aggregates` 값이
   기대와 일치하는지 read-only로 재확인하는 별도 후속 turn을 둔다.
8. **회고 + 범위 확장 여부 판단** — 미착수. 1개 계좌에서의 결과를
   바탕으로 다른 계좌/기간으로 확장할지, 안 B(staging 테이블)로
   전환할지, 정정/취소 혼재 케이스를 별도 설계로 다룰지 결정한다.

## 6. 추가 보정사항

- 이번 문서와 설계 문서는 시장가/지정가 예외 경로나 부분체결/완전체결
  별도 분기를 기본안으로 삼지 않는다 — 설계 문서 4.2절의 단일 공식이
  둘 다 처리한다.
- "미래 정상화"(14, 15번 문서)와 "과거 backfill"(이 문서, 16번 문서)을
  섞지 않는다 — truth-probe 병행 호출 코드, `kis_fill_cumulative_state`
  상태 테이블 어느 쪽도 이 backfill이 건드리지 않는다.
- `broker_fill_snapshots`를 recompute의 1차 입력으로 승격하는 설계로
  바꾸지 않는다 — 여전히 대사 전용이며, 이 backfill이 만드는 것은
  `fill_events`에 들어갈 synthetic fill이다.

## 7. 그 외 유지해야 할 원칙

- `fill_events`는 계속 append-only, recompute의 1차 입력은 계속
  `fill_events`만.
- 불확실하면 복원하지 않는다 — 원가 완결성 기준을 만족하지 못하는
  종목, anomaly가 하나라도 나온 종목은 전체 제외한다(부분 반영 금지).
- dry-run → 사람 승인 → 실제 append 순서를 생략하지 않는다.
- backfill은 계좌 1개, 좁은 기간, 단순 케이스로 시작하고, 그 결과를
  사람이 직접 확인한 뒤에만 범위를 넓힌다.

## 8. 완료 후 보고 가이드 (향후 구현 턴 대상)

이 실행 계획을 실제로 구현하는 턴은 완료 보고에 다음을 포함해야 한다:
- 신규/변경 파일 목록(변환 규칙 순수 함수, 원가 완결성 판정 로직,
  dry-run/append 배치 스크립트 등)
- read-only 모집단 조사 결과(대상 계좌×종목 수, 구체 목록)
- dry-run 리포트 내용과 사람 승인 여부/범위
- 실제 append 여부, append했다면 몇 건, `source_channel='backfill'`
  건수
- `realized_pnl_recompute_queue` 등록 건수와 워커 소비 확인 결과
- 아직 확정하지 못한 가정(정정/취소 처리, live 확장 등, 설계 문서 1.2절
  재확인 결과)
