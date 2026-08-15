# 16. `broker_fill_snapshots` 기반 과거 체결 synthetic `fill_events` Backfill 설계 (최소 구현 완료 — apply는 미실행)

## 0. 문서 성격 — "미래 정상화"가 아니라 "과거 복원" 전용 축

이 문서는 **설계 문서**였고, 이후 별도 구현 턴에서 §5.2 추천안(안 A +
dry-run/승인 절차)의 최소 구현이 완료됐다.

### 0.1 구현 현황 (구현 턴에서 추가)

- **서비스 계층**: [`src/agent_trading/services/historical_fill_backfill.py`](../../../src/agent_trading/services/historical_fill_backfill.py)의
  `build_backfill_plan()`(§3.3 원가 완결성 판정 + §4.2 변환 규칙, read-only)과
  `apply_backfill_plan()`(§5.2 dry-run과 완전히 같은 계산 결과를 실제
  `fill_events`에 append, §6 idempotency)로 구현했다. 신규 테이블/migration은
  없다 — `fill_events.source_channel='backfill'`, `realized_pnl_recompute_
  queue.reason_code='manual_request'` 둘 다 기존 스키마가 이미 허용하던 값을
  그대로 썼다(§1.1).
- **원가 완결성 판정**은 `position_snapshots.get_latest_by_account_and_
  instrument_before()`로 zero-crossing anchor를 찾고, anchor~첫 주문 사이에
  "누락된" filled 주문이 있으면 전체 제외하는 방식으로 구현했다(§3.3).
- **변환 규칙**은 14번 문서의 `_infer_delta_price()`를 그대로 import해
  재사용했다(§4.2) — `kis_fill_cumulative_state`(실시간 폴링 상태 테이블)는
  참조하지 않는다. anomaly(음수 delta/가격 역산 불가/cancel 흔적/snapshot
  누락/lineage 불일치/최종수량 불일치) 발생 시 **계좌×종목 전체를 제외**한다
  (§4.3, 부분 반영 없음).
- **CLI 진입점**: [`scripts/backfill_broker_fill_snapshot_historical_fills.py`](../../../scripts/backfill_broker_fill_snapshot_historical_fills.py) —
  `--mode dry-run`(기본값)/`--mode apply`. `--mode`를 명시하지 않으면
  항상 dry-run이다(§5.2 안전장치의 코드 레벨 강제).
- **단위 테스트**: `tests/services/test_historical_fill_backfill.py`(원가
  완결성 판정의 각 제외 사유 + eligible 사례 + apply idempotency),
  `tests/scripts/test_backfill_broker_fill_snapshot_historical_fills.py`
  (CLI 인자 파싱 + dry-run이 실제로 DB에 안 씀 + apply의 eligible 분기).
- **아직 실행하지 않은 것**: 실제 운영 DB에 대한 `--mode apply` 실행. 이
  구현 턴은 코드/테스트만 완료했고, 확정된 후보(계좌 1개×종목 1개, 매수
  1건+매도 2건)에 대한 실제 apply는 별도로 사용자 승인을 받은 뒤 진행한다
  (§5.2의 "dry-run → 사람 승인 → 실제 apply" 절차를 그대로 유지).
- **`historical_policy_estimate` override(별도 구현 턴, 완료) + apply 실측
  완료(2026-08-15 KST)**: `001450`/`004370` initial backfill 파일럿용 —
  `use_historical_policy_estimate_for_buy_fee` opt-in 옵션으로 두 종목 모두
  실제 `--mode apply` 실행 완료(`fee=347`/`679`, 오차 0원, §8.10 참고).
  `007070`(overlay+recompute) 트랙과 완전히 별개다. `recompute_queue`는
  등록됐고 워커 처리 대기 중(`resolved_at` 아직 `NULL`) — `position_cost_
  basis_state`의 최종 `quantity`/`average_cost`는 그 처리 이후 반영된다.
- **`buy_fee_pool_provenance` 오분류 버그 수정 + `001450`/`004370` 정정
  recompute 완료(2026-08-15 KST)**: §8.11/§8.12 참고. 두 종목의
  `buy_fee_pool_provenance`가 `historically_estimated`로 정확히
  바로잡혔고, 다른 종목(`007070` 포함)은 영향받지 않았음을 확인했다.
- **`initial_entry` anchor 신설(구현 완료, apply는 미실행)**: `BackfillAnchorType`
  (`zero_crossing`/`initial_entry`), `BackfillPlan.anchor_type` 필드 추가.
  window_start 이전 filled 주문이 전혀 없는 종목(`007070`/`001450`/
  `004370` 제외 현재 보유 나머지 종목 대상)은 zero-crossing 스냅샷 없이도
  backfill 자격을 인정한다. 상세는 §8.12. 이번 turn은 코드/테스트/문서
  까지만 — 13종목의 실제 eligible 재확인과 apply는 별도 turn.

**이 설계는 오직 과거 복원(backfill) 전용이다.** 아래 두 가지를 명확히 구분한다.

| | 대상 문서 | 목적 | 상태 |
|---|---|---|---|
| **미래 체결 경로 정상화** | [`14_...`](14_kis_fill_normalization_and_incremental_interpretation_design.md), [`15_...`](15_truth_probe_and_kis_fill_sync_coexistence_design.md) | 앞으로 발생하는 체결이 실시간 `get_fills()` 경로를 통해 정상적으로 `fill_events`/ledger에 반영되도록 함 | 1차 구현 완료, shadow 모드 운영 중 |
| **과거 체결 복원(backfill)** | **이 문서(16번)** | 이미 지나간 과거 매도(및 그 원가 형성에 필요한 매수)를 `broker_fill_snapshots`의 관측 흔적만으로 사후 재구성 | **설계만, 구현 미착수** |

15번 문서 §5.7이 이미 이 경계를 선언했다: *"과거 backfill 설계(별도 문서, 아직
미작성)"* — 이 문서가 바로 그 문서다. **15번 문서의 결론(미래 경로가 먼저
안정화된 뒤 backfill로 넘어가는 순서)을 그대로 존중**하며, 이 설계는 그
전제 위에서 진행한다 — 15번 안 B가 운영에서 실제로 동작 중임은 이미 별도
turn에서 확인됐다(로그 페어링 관측 완료).

관련 선행 문서(표현 충돌 없이 그대로 존중한다):
- [`12_realized_pnl_moving_average_ledger.md`](12_realized_pnl_moving_average_ledger.md) — `fill_events` append-only, `realized_pnl_recompute_service`의 1차 입력은 `fill_events`뿐이라는 계약. 이 문서는 이 계약을 바꾸지 않는다 — synthetic fill도 결국 `fill_events`를 거쳐야만 ledger에 반영된다.
- [`14_...`](14_kis_fill_normalization_and_incremental_interpretation_design.md) — 누적→증분 해석의 공식(가중평균 분해, anomaly 분리 원칙). 이 설계는 그 **계산 원리**를 재사용하되, 그 구현이 쓰는 상태 저장소(`kis_fill_cumulative_state`)는 재사용하지 않는다(§4.2에서 근거 설명).
- [`15_...`](15_truth_probe_and_kis_fill_sync_coexistence_design.md) — 이 backfill 대상이 되는 주문들은 이미 `FILLED`(terminal)이고, 15번 §5.7이 확인한 대로 향후 `_sync_fills()`가 다시 이 주문들을 처리할 일이 없다. 이 사실이 이 설계의 dedup 안전성 근거 중 하나다(§5).

## 1. 문제 재정의

### 1.1 확인된 사실 (선행 read-only 조사에서 이미 확인)

- `fill_events`가 비어 있는 기간의 과거 매도 주문은, 현재 recompute
  (`RealizedPnlRecomputeService`)만으로는 실현손익이 복원되지 않는다 —
  recompute는 `fill_events`를 replay할 뿐, 새로운 fill을 만들어내지 않는다
  (`realized_pnl_recompute_service.py` 모듈 docstring, "이 서비스는
  `fill_events`만을 1차 입력으로 삼는다").
- `broker_fill_snapshots`는 `fill_history_sync.py`가 별도 폴링 주기로
  채우는 대사(reconciliation) 전용 테이블이며, 일부 과거 주문에 대해
  누적 체결 관측(여러 시점의 관측 row)을 보유하고 있다.
- `2026-08-01 KST` 이후 매도 주문 2건에 대해 snapshot 기반 복원 가능성을
  read-only로 조사한 결과, 복원 자체는 가능해 보였다 — 다만 표본이 **2건**
  으로 극히 작고, 둘 다 **정정/취소가 섞이지 않은 단순 케이스**였다.
- 부분체결·정정·취소가 혼재된 케이스에 대한 검증은 아직 없다 —
  14번 문서 1.3절이 이미 명시한 미확정 영역(정정/취소 anomaly 분기의
  실제 검증 부재)과 동일한 공백이 이 backfill 설계에도 그대로 이어진다.
- `realized_pnl_events.fill_event_id`는 UNIQUE NOT NULL이다(12번 문서
  4.2절) — 즉 `fill_events`를 거치지 않고 `realized_pnl_events`에
  직접 쓰는 경로는 스키마상 존재하지 않는다.
- `fill_events.source_channel`은 이미 `CHECK (source_channel IN
  ('websocket', 'rest_poll', 'backfill', 'manual'))`로 `'backfill'` 값을
  허용하도록 스키마에 준비돼 있다(`db/migrations/0001_initial_schema.sql:361-362`)
  — 이번 설계를 위해 스키마를 바꿀 필요가 없다는 뜻이다.
- `realized_pnl_recompute_queue.reason_code`도 이미 `'manual_request'`를
  허용한다(`db/migrations/0053_add_realized_pnl_ledger_tables.sql`) —
  backfill이 새로운 reason_code를 추가하지 않고 이 값을 그대로 쓸 수 있다.

### 1.2 아직 미확정인 점

- 부분체결 다단계 매도 일반적 품질 — 지금까지 확인된 자연 발생 staircase
  표본은 `000227`/2026-06-23 KST 1건(14번 문서 1.2절)뿐이며, 이것도
  매도가 아니라 해당 세션에서 별도로 관측된 사례다. backfill 대상 모집단
  안에 이런 다단계 케이스가 실제로 몇 건인지 조사된 바 없다.
- 취소/정정이 혼재된 케이스에서 anomaly 분리가 실제로 안전하게 동작하는지.
- `broker_fill_snapshots`에 관측이 전혀 없는(snapshot 누락) 주문의 처리.
- snapshot이 정확히 1건뿐인 주문의 일반적 안전성 — 완전체결 1회성으로
  해석하는 것이 항상 맞는지, 아니면 관측 공백(폴링 누락) 때문에 중간
  단계가 빠진 것인지 구분할 수 없는 경우가 있는지.
- live 환경 확장 가능성 — 이번 조사도 전부 paper 계좌 기준이다.

### 1.3 이번 설계가 반드시 다뤄야 하는 핵심 논리적 함정 (사용자 지적, §3.A에서 상술)

**매도만 복원하는 것으로는 실현손익 복원이 완결되지 않는다.** 이동평균
실현손익 계산(12번 문서 3.2절)은 매도 시점의 `average_cost`(그 시점까지
누적된 매수 원가)를 전제로 한다. `realized_pnl_engine.replay_fills()`는
직전 상태 없이 SELL이 오면 `MissingCostBasisStateError`/
`InsufficientPositionQuantityError`로 **명시 실패**한다(12번 문서 3.2절).
즉 매도 fill만 synthetic으로 만들어 넣으면, recompute가 그 매도를 처리할
차례에 원가가 없어 실패하거나(계좌×종목이 처음부터 이 매도만 갖는 경우),
기존에 이미 반영된(혹은 앞으로 반영될) 다른 fill들과 섞여 원가가 실제보다
낮게/높게 계산되는 조용한 오류를 만들 수 있다. 이 설계는 이 함정을
§3.A에서 정면으로 다룬다.

## 2. 설계 원칙 (재확인)

- **불확실하면 복원하지 않는다.** 이 원칙은 14번 문서 1.4절에서 이미 세운
  최우선 원칙이며, 이 backfill 설계에서는 오히려 더 강하게 적용해야 한다 —
  실시간 경로는 shadow 기간 동안 계속 관측하며 판단을 미룰 수 있지만,
  backfill은 **한 번 잘못 넣으면 append-only 구조상 되돌리기 어려운** 값을
  단번에 여러 건 넣는 작업이기 때문이다.
- **좁은 범위부터 시작한다.** 계좌 1개, 짧은 기간, 단순 케이스만 먼저
  다루고, 그 결과를 사람이 직접 확인한 뒤 범위를 넓히는 것을 기본 진행
  방식으로 삼는다(§7 실행 계획과 연결).
- **시장가/지정가를 설계 축으로 올리지 않는다.** KIS `inquire-daily-ccld`
  응답 스키마는 주문 유형과 무관하게 동일하다(14번 문서 2절과 동일 근거).
- **partial/full은 같은 snapshot→delta 해석 모델 안의 관측 차이일 뿐,
  별도 구현 축이 아니다.** snapshot이 1건이면 "완전체결 1회성", 여러
  건이면 "부분체결 staircase"로 보이지만, 계산 공식(§4.2)은 두 경우
  모두 동일하게 처리한다(prior_qty=0일 때 delta_price가 current_avg로
  자연히 수렴하는 것과 같은 원리, 14번 문서 3.2절).
- **truth-probe 병행 설계(15번)와 섞지 않는다.** 이 backfill은
  `sync_order_post_submit()`/`_sync_fills()`의 실시간 폴링 경로를 전혀
  건드리지 않는 독립 배치다.
- **`broker_fill_snapshots`를 recompute의 1차 입력으로 승격하지 않는다.**
  이 설계가 만드는 것은 `fill_events`에 들어갈 synthetic **fill**이며,
  `broker_fill_snapshots` 자체는 여전히 대사 전용 테이블로 남는다
  (10번 문서, 12번 문서 10절과 동일 경계 유지).
- **실현손익 정확성을 범위 확대보다 우선한다.** "더 많은 과거 주문을
  복원하는 것"보다 "복원한 값이 확실히 맞는 것"이 이 설계의 성공 기준이다.

## 3. 핵심 질문 A — backfill 입력 모집단을 어떻게 제한할 것인가

### 3.1 제한 축 검토

| 축 | 검토 결과 |
|---|---|
| **기간** | 하한: `2026-08-01 KST`(이미 조사된 시작점, `fill_history_sync.py`가 이 계좌에 대해 신뢰 가능한 관측을 시작한 시점으로 확인된 구간). 상한: 15번 안 B가 실제 배포된 시각(`2026-08-13` 오후, 별도 turn에서 확인) **이전**에 이미 `FILLED`로 전환된 주문만 — 그 이후 전환된 주문은 이론상 새 병행 호출 경로가 처리할 기회가 있었어야 하므로, 이 backfill의 "구조적으로 놓친 과거" 범주에 넣지 않는다(경계가 애매한 주문은 §3.3에서 별도로 다룬다). |
| **계좌** | **1개 계좌로 한정**(현재 운영 중인 paper 계좌). 여러 계좌로 확장하는 것은 이번 설계 범위 밖 — 1개 계좌에서의 안전성이 먼저 확인돼야 한다. |
| **주문 상태** | `order_requests.status='filled'`만 포함한다. `partially_filled`는 **제외** — 아직 진행 중일 가능성이 있는 주문은 15번 안 B가 이미 처리할 기회를 갖고 있으므로(§5.5, terminal 전환까지 병행 호출 유지), backfill이 개입할 이유가 없다. 만약 `partially_filled`인데 이미 오랫동안 정지된 주문이 발견되면, 그건 이 backfill이 아니라 별도의 "정지된 non-terminal 주문" 조사 대상이다. |
| **매도/매수 범위** | §3.2에서 별도로 상세히 다룬다 — 결론만 먼저 적으면: **매도만 복원 대상으로 삼지 않는다.** |
| **`cancel_yn`/정정 흔적** | `cancel_yn='Y'` 또는 `rvse_yn` 관측이 있는 주문은 **해당 주문 전체를 제외**한다(그 주문의 일부 snapshot만 무시하는 것이 아니라, 그 주문 전체를 backfill 대상에서 뺀다 — §4.3에서 이유 설명). |
| **snapshot 품질** | §3.4에서 다룬다. |

### 3.2 왜 "매도만 복원"으로는 부족한가 — 계좌×종목 단위 원가 완결성 요구

1.3절에서 지적한 함정을 그대로 반영해, 이 설계는 backfill의 최소 단위를
**개별 매도 주문이 아니라 계좌×종목**으로 정의한다.

- **원칙**: 어떤 매도를 backfill 대상에 포함하려면, 그 매도가 이동평균
  원가를 계산하는 데 필요한 **그 종목의 선행 매수 히스토리 전체**도
  함께 backfill 대상에 포함하거나, 이미 `fill_events`에 존재해야 한다.
- **실무적 결론**: 이 계좌가 paper 계좌이고 `fill_events`가 전 기간
  0건이라는 것이 이미 확인돼 있으므로(14번 문서 1.1절), "이미
  `fill_events`에 매수가 존재하는" 경우는 없다. 즉 **매도를 backfill
  대상에 포함하는 순간, 그 종목의 선행 매수도 함께 backfill해야 한다.**
- **범위가 저절로 넓어지는 것을 어떻게 제한하는가**: "그 종목의 선행
  매수"를 무한정 과거까지 추적하지 않는다. 대신 **"이 계좌×종목의
  현재 잔량(포지션)을 설명하는 데 필요한, `broker_fill_snapshots`가
  끊김 없이 커버하는 최초 매수 시점까지"**로 한정한다 — 아래 §3.3.
- **매도만 있고 매수 원가를 신뢰 가능하게 구성할 수 없는 종목은 그
  매도까지 포함해서 전체 제외한다.** 이것이 "불확실하면 복원하지
  않는다" 원칙의 이번 설계에서의 구체적 적용이다 — 원가 없이 매도만
  넣는 것은 12번 문서의 계산 엔진이 예외로 막아주므로 시스템이 조용히
  틀린 값을 내지는 않지만(엔진이 명시 실패한다), backfill 배치 입장에서는
  "일부만 성공하는 어정쩡한 상태"를 만들 수 있으므로 애초에 대상에서
  뺀다.

### 3.3 원가 완결성 판정 기준 (구체 규칙)

계좌×종목 단위로 아래를 만족해야 backfill 대상으로 포함한다.

1. 이 종목에 대해 **완전 청산(잔량=0) 이후 재매수로 시작하는 지점**을
   찾을 수 있어야 한다 — 즉 원가 계산의 시작점을 "잔량 0에서 시작"으로
   확정할 수 있어야 한다(12번 문서 3.2절, "완전 청산 후 원가 리셋"과
   같은 원리). 이 지점을 찾을 수 없으면(예: 조사 가능한 snapshot 범위
   전체에서 한 번도 잔량이 0이 된 적이 없다면) 이 종목은 **전체 제외**.
2. 그 시작점부터 지금까지, 이 종목에 대한 모든 매수/매도 주문이
   `broker_fill_snapshots`에 **관측 흔적을 갖고 있어야 한다** —
   `order_requests.status='filled'`인 주문인데 연결된 snapshot이 하나도
   없는 경우가 하나라도 있으면, 그 계좌×종목 전체를 제외한다(중간에
   구멍이 있는 원가 재구성은 신뢰할 수 없다).
3. 그 구간의 모든 관련 주문에 `cancel_yn`/정정 흔적이 없어야 한다(§3.1).
4. 이 판정은 **자동 스크립트가 계산하되, 사람이 최종 목록을 검토한다**
   (§7 실행 계획 1~2단계) — 자동 판정 결과를 즉시 실행에 옮기지 않는다.

### 3.4 snapshot 품질 기준

- snapshot row 수가 **1건**인 주문: `filled_quantity == ordered_quantity`
  (완전체결 1회성)이면 포함 후보. 그렇지 않으면(부분체결인데 관측이
  1건뿐 — 관측 공백 의심) **제외**.
- snapshot row 수가 **2건 이상**인 주문(staircase 후보): `filled_quantity`
  가 매 row마다 **단조 비감소**여야 한다(역행이 있으면 §4.3에서 anomaly
  처리, 해당 주문 전체 제외). 마지막 row의 `filled_quantity`가
  `ordered_quantity`와 다르면(미체결 잔량이 있는데 주문 상태가 `filled`인
  모순) **제외**하고 사람 확인 대상으로 남긴다.

### 3.5 요약 — 1차 도입 범위 (좁게)

```
계좌:        1개(현재 운영 paper 계좌)
기간:        2026-08-01 KST ~ (15번 안 B 실배포 시각 이전 FILLED 전환분)
주문 상태:   filled만
매도/매수:   종목 단위로 함께 — 완전 청산 시작점부터 원가 완결성 있는 종목만
cancel/정정: 흔적이 있으면 그 종목 전체 제외
snapshot:    끊김 없음 + 단조 비감소 + 최종 수량 일치만 포함
```

이 범위를 실제로 적용하면 대상 종목 수가 매우 작아질 가능성이 높다
(§1.1의 "표본 2건, 극히 작음"이 이미 이를 암시한다) — 이건 이 설계가
의도한 결과다. 표본이 작아도, **확실한 것만 복원한다**는 원칙이 표본
크기보다 우선한다.

## 4. 핵심 질문 B — snapshot → synthetic fill 변환 규칙

### 4.1 시계열 정렬 기준

같은 `broker_native_order_id`의 `broker_fill_snapshots` row들을 아래
순서로 정렬한다.

```
ORDER BY updated_at ASC, filled_quantity ASC
```

`fill_history_sync.py`는 매 관측마다 `filled_quantity`가 다르면
`dedupe_key`도 달라져 새 row가 append되고(`upsert()`가 사실상 insert로
동작), `updated_at=datetime.now(timezone.utc)`가 그 행이 실제로
관측/저장된 시각을 담는다(§fill_history_sync.py 317행). 이는 12번 문서
5절이 `fill_events.created_at`을 "수신 순서에 대한 유일하게 신뢰 가능한
fallback"으로 채택한 것과 같은 논리를 따른 것이다. `fill_timestamp`
(체결 시각 추정치)도 존재하지만, 이 필드는 같은 `order_day`+`fill_time`
조합이면 여러 row에서 동일할 수 있어(체결 시각을 KIS가 정밀하게
알려주지 않는다는 14번 문서의 기존 한계) 1차 정렬 키로 쓰지 않는다.

### 4.2 delta 계산 — 14번 문서의 "원리"를 재사용하되 "상태 저장소"는 재사용하지 않는다

**재사용하는 것**: 가중평균 분해 공식과 anomaly 판단 기준(14번 문서
3.2절 `_infer_delta_price`, `resolve_incremental_fill()`의 분기 로직) —
이 공식 자체를 다시 설계하지 않는다.

```
delta_qty = snapshot[i].filled_quantity - snapshot[i-1].filled_quantity  (snapshot[-1] = 0)
delta_price = (avg[i]*qty[i] - avg[i-1]*qty[i-1]) / delta_qty
```

`qty[-1]=0`이면 `delta_price == avg[i]`로 자연히 수렴한다(14번 문서와
동일 — snapshot 1건짜리 완전체결도 이 공식 하나로 처리된다).

**재사용하지 않는 것**: `kis_fill_cumulative_state` 상태 테이블. 이유:

1. 이 테이블은 **실시간 폴링의 "다음 관측을 올바르게 해석하기 위한
   캐시"**로 설계됐다(14번 문서 3.2절, "이 상태가 손상되거나 재구축이
   필요해도 fill_events에 이미 append된 사실 자체는 바뀌지 않는다" —
   즉 이 상태는 도메인 사실의 원천이 아니라 **폴링 진행 상태**다).
   backfill은 폴링이 아니라 **한 번에 전체 시계열을 이미 다 갖고 있는
   일괄 배치**이므로, "직전 관측치를 영속 저장해뒀다가 다음 폴링에서
   다시 조회"하는 이 테이블의 존재 이유 자체가 없다 — 같은 프로세스
   메모리 안에서 전체 시계열을 한 번에 순회하며 델타를 계산하면 된다.
2. 만약 backfill이 이 상태 테이블에 값을 써넣으면, 그 값의 출처가
   `broker_fill_snapshots`(대사 관측)인지 실시간 `get_fills()`(polling
   관측)인지 이 테이블 자체로는 구분할 수 없게 된다 — 14번 문서 3.2절이
   이 상태를 "브로커 관측(observation) 상태"로 명확히 규정했는데,
   두 개의 서로 다른 관측 소스가 하나의 baseline을 공유하면 그 경계가
   흐려진다. 15번 문서가 안 C(별도 synthetic 경로)를 기각하며 지적한
   "두 로직이 같은 주문을 서로 다르게 해석해 이중 반영될 위험"과
   본질적으로 같은 우려다.
3. 다행히 이 위험은 실질적으로 제한적이다 — backfill 대상 주문은
   이미 `FILLED`(terminal)이고, 15번 §5.7이 확인한 대로 앞으로
   `_sync_fills()`가 이 주문들을 다시 조회할 일이 없다(최상단
   terminal-skip). 즉 "오염된 baseline이 미래 실시간 해석에 영향을
   준다"는 시나리오는 이 population에서는 발생하지 않는다. 그럼에도
   **원칙적으로 상태 테이블을 공유하지 않는 것**을 선택한다 — 실질적
   위험이 낮다는 것이 "설계상 경계를 지킬 필요가 없다"는 뜻은 아니다.

**결론**: backfill 전용 순수 함수(가칭 `resolve_historical_fill_series()`,
14번 문서의 `_infer_delta_price`를 그대로 import해 재사용)가, 정렬된
snapshot 목록 전체를 입력으로 받아 `IncrementalFillDecision`의 리스트를
한 번에 반환한다. `kis_fill_cumulative_state` repository는 전혀 참조하지
않는다.

### 4.3 anomaly 처리 — "그 row만 건너뛰기"가 아니라 "그 주문 전체 제외"

14번 문서의 실시간 경로는 anomaly가 나면 그 fill 건만 append를 보류하고
다음 polling cycle에서 재평가할 기회가 있다(폴링이 반복되므로). backfill
은 **재시도 기회가 없는 1회성 배치**이므로, 이 설계는 더 보수적으로
접근한다 — 시계열 안에서 다음 중 하나라도 발생하면 **그 주문 전체
(이미 처리된 이전 delta 포함)를 backfill 대상에서 제외**한다:

- 음수 delta(누적 체결량 역행) — §3.4의 사전 필터가 대부분 걸러내지만,
  이중 방어로 계산 단계에서도 다시 확인한다.
- `average_fill_price`가 없어 가격을 산출할 수 없는 delta.
- `cancel_yn='Y'`/`rvse_yn` 관측(§3.1의 사전 필터와 이중 방어).

"부분적으로만 반영하고 나머지는 보류"하지 않는 이유: 이동평균 계산은
순서 의존적(12번 문서 6절)이라, 한 주문의 일부 delta만 넣고 나머지를
빼면 그 이후 같은 종목의 모든 계산이 이미 틀린 상태로 진행된다 — 이건
"불확실한 부분만 보류"가 아니라 "확실한 부분까지 함께 오염시키는" 결과다.
따라서 원자적으로 **주문 단위(사실상 §3.2~3.3에서 이미 종목 단위로
묶었으므로, 실제로는 종목 단위)**로 전부 포함하거나 전부 제외한다.

## 5. 핵심 질문 C — synthetic fill을 어디에 넣을 것인가

### 5.1 대안 비교

#### 안 A. `fill_events`에 직접 synthetic 행 append + 이후 recompute

- **장점**: 12번 문서가 이미 정의한 정석 경로를 그대로 따른다.
  `fill_events`가 recompute의 유일한 1차 입력이라는 계약을 그대로
  유지한다. `RealizedPnlRecomputeService.recompute_account_instrument()`
  를 그대로 재사용할 수 있어 신규 계산 코드가 필요 없다. `source_channel
  ='backfill'`이 이미 스키마에 준비돼 있어 신규 migration이 필요 없다.
- **단점**: `fill_events`에 "사후 재구성된" 행이 실시간 관측 행과 뒤섞인다
  — 구분자(`source_channel='backfill'`)로 구분 가능하지만, 한 번
  append되면 append-only 구조상 되돌리기 어렵다. idempotency(같은
  backfill을 두 번 실행해도 안전한가)를 신경 써서 설계해야 한다(§6).

#### 안 B. synthetic fill을 별도 staging에 쌓고 검증 후 promote

- **장점**: `fill_events`(append-only 원장)를 직접 건드리기 전에 사람이
  결과를 검토할 시간을 번다 — 실수로 잘못된 값이 원장에 영구히 박히는
  리스크를 낮춘다.
- **단점**: 별도 staging 테이블 + promote 로직이 추가로 필요해 구현
  범위가 늘어난다. "검토 후 promote"가 실제로 안전하려면 결국 사람이
  개입하는 수동 게이트가 필요한데, 이는 순수 배치 자동화가 아니라
  운영 프로세스까지 설계 범위에 포함시켜야 한다는 뜻이다.

#### 안 C. `realized_pnl_events`를 직접 재구성하는 우회 경로

- **왜 기각하는가**: `realized_pnl_events.fill_event_id`가 UNIQUE
  NOT NULL이다(12번 문서 4.2절) — `fill_events` 행이 없으면 이 테이블에
  정상적으로 쓸 방법이 없다. 가짜 `fill_event_id`를 만들어 우회하는
  것은 사실상 "`fill_events`에 synthetic 행을 넣는 것"과 동일한 일을
  더 불투명하게 하는 것뿐이며, 오히려 "이 손익이 어떤 체결에서
  파생됐는가"라는 감사 추적성을 해친다. 또한 `RealizedPnlRecomputeService`
  의 replay 계약("`fill_events`를 처음부터 재생")과 정면으로 어긋난다 —
  나중에 누군가 recompute를 실행하면 이 우회로 만든 `realized_pnl_events`
  행이 `fill_events`에 대응하는 행이 없어 다음 replay에서 통째로
  사라지거나 무시된다. **명확히 기각.**

### 5.2 추천안 — 안 A를 기본으로, 안 B의 안전장치를 "절차"로 흡수

새 테이블을 추가하지 않고, 안 A(직접 append) 위에 안 B가 노리는 안전성을
**절차적 게이트**로 확보한다:

1. backfill 배치는 항상 **dry-run 모드**로 먼저 실행한다 — 계산 결과
   (어떤 계좌×종목, 몇 건의 synthetic fill, 각각의 수량/가격/시각)를
   사람이 읽을 수 있는 리포트로만 출력하고 `fill_events`에 아무것도
   쓰지 않는다.
2. 사람이 이 dry-run 리포트를 검토하고, 대상 목록(계좌×종목 단위)을
   **명시적으로 승인**한다(예: 승인된 종목 ID 목록을 별도 인자로 전달).
3. 승인된 대상만 **실제 append 모드**로 재실행한다 — 승인되지 않은
   대상은 절대 append하지 않는다.
4. 이 절차는 14번 문서 6.1절의 "shadow → 관측 → 전환" 3단계와 같은
   정신(정책을 바로 반영하지 않고 먼저 관측 가능한 형태로 노출한 뒤
   사람이 판단)이며, backfill이라는 1회성 배치 성격에 맞게 "shadow
   기간"이 아니라 "dry-run 1회 + 사람 승인"으로 압축한 것이다.

새 staging 테이블(안 B의 문자 그대로의 형태)을 만들지 않는 이유: dry-run
출력(리포트/로그)이 이미 "검토 대상"의 역할을 하므로, 별도 테이블+promote
코드까지 추가하는 것은 이번 1차 도입 범위(좁게 시작)에는 과한 사전 설계다.
대상 범위가 넓어지고 반복 실행 빈도가 늘어나면, 그때 안 B의 staging
테이블을 재검토할 수 있다(§8 향후 확장).

## 6. 핵심 질문 D — idempotency / 중복 방지 / 감사 가능성

### 6.1 같은 backfill run을 두 번 실행해도 안전한가

- synthetic fill이 `broker_fill_id`를 채울 수 있는 경우
  (`broker_fill_snapshots.broker_fill_id`, KIS `CCLD_NUM`이 있는 경우):
  기존 `fill_events` UNIQUE 제약(`uq_fill_events_native
  (broker_order_id, broker_fill_id)`)이 그대로 두 번째 삽입을 막는다.
- `broker_fill_id`가 없는 경우: `order_sync_service._sync_fills()`가
  쓰는 것과 같은 composite key 사고방식(broker_order_id + fill_timestamp
  + fill_price + fill_quantity)으로, append 직전 `list_by_broker_order()`
  결과와 비교해 이미 같은 조합이 있으면 건너뛴다. 이 dedup 체크는
  backfill 배치 코드 안에 **직접 구현**한다(기존 `_sync_fills()` 내부
  helper를 그대로 import하지 않는다 — 그 helper는 실시간 경로의 다른
  전제(예: `since` 파라미터 기반 최근 구간만 조회)를 갖고 있어, 그대로
  재사용하면 오히려 결합이 늘어난다. 로직의 **원리**만 따르고 코드는
  독립적으로 유지한다).

### 6.2 미래 경로에서 쌓인 `fill_events`와 충돌하지 않는가

- 이 backfill의 대상 population은 §3.5에서 이미 "15번 안 B 실배포 이전에
  `FILLED`로 전환된 주문"으로 제한했다. 15번 §5.7이 확인한 대로, 이미
  `FILLED`인 주문은 앞으로 `_sync_fills()`가 다시 처리하지 않는다 —
  즉 이 population에 대해 미래에 실시간 경로가 새로 fill을 만들어
  넣을 가능성이 구조적으로 없다. 충돌 여지가 원천적으로 낮다.

### 6.3 synthetic fill임을 어떻게 구분하는가

- `fill_events.source_channel = 'backfill'`(이미 스키마가 허용하는 값,
  §1.1) — 신규 컬럼/migration이 필요 없다.

### 6.4 감사 가능성 — "이 row는 과거 snapshot에서 복원된 것"임을 확인할 수 있는가

- `fill_events.raw_payload_uri`(기존 nullable 컬럼, `entities.py:379`)에
  이 synthetic fill이 파생된 `broker_fill_snapshot_id`(들)와 backfill
  실행 식별자를 문자열로 남긴다(예: `backfill:<run_id>:snapshot:<id1>,<id2>`
  — 정확한 포맷은 구현 턴에서 확정). 신규 스키마 추가 없이 기존 nullable
  필드를 재사용하는 보수적 선택이다.
- `source_channel='backfill'` + `raw_payload_uri`의 snapshot 참조만으로,
  사람이 나중에 "이 fill이 어느 snapshot들에서, 어떤 배치 실행으로
  만들어졌는가"를 역추적할 수 있다.

### 6.5 backfill run 단위 추적이 필요한가

- **필요하다.** `realized_pnl_computation_runs`(12번 문서 4.4절)는
  이미 `run_type IN ('realtime_incremental', 'backfill_replay')`를
  갖고 있지만, 이건 **recompute(replay) 실행**의 추적용이고, "fill
  자체가 어떤 backfill 배치에서 만들어졌는가"의 추적용이 아니다.
- 이번 설계에서는 신규 테이블을 추가하지 않고, backfill 배치 실행 시
  콘솔/로그에 남기는 **실행 식별자(run_id, UUID)**를 §6.4의
  `raw_payload_uri`에 문자열로 새겨 넣는 것으로 최소 범위 감사성을
  확보한다. 더 정교한 추적(예: 별도 `historical_backfill_runs` 테이블)
  이 필요해지면 §8 향후 확장에서 재검토한다 — 1차 도입 범위(계좌 1개,
  극소 표본)에서는 과한 사전 설계로 판단한다.

## 7. 핵심 질문 E — recompute와의 관계

- backfill 배치는 **fill을 채우는 것까지만** 책임진다. 실제 이동평균
  원가/실현손익 계산은 여전히 `realized_pnl_engine.py`/
  `RealizedPnlRecomputeService`에 전속된다(12번 문서와 동일 경계) —
  backfill이 손익 계산식을 다시 구현하지 않는다.
- fill append가 끝나면, 대상 계좌×종목마다
  `realized_pnl_recompute_queue`에 `reason_code='manual_request'`
  (이미 존재하는 CHECK 값, §1.1)로 등록하고
  `position_cost_basis_state.recompute_required=true`로 표시한다.
- **직접 recompute를 실행하지 않는다** — 이미 배포된
  `realized-pnl-recompute-worker`(300초 주기, `process_pending_queue()`)
  가 이 큐를 자동으로 소진한다. fill 저장과 recompute 실행을 같은
  스텝에 묶지 않는 이유는 12번 문서 8절의 장애 복구 계약(fill 저장 성공
  자체는 롤백하지 않고, ledger 반영 실패는 별도로 관측 가능하게 큐에
  남긴다)과 같은 원칙을 backfill에도 그대로 적용하기 위함이다 — "fill을
  넣었는데 그 자리에서 recompute까지 실패하면 무엇이 반영됐는지 불명확
  해지는" 상황을 피한다.
- 예외로, §5.2의 dry-run 단계에서는 계산 결과를 사람이 즉시 확인하기
  위해 `recompute_account_instrument()`를 **읽기 전용 시뮬레이션**
  (실제 DB에 쓰지 않고 계산 결과만 출력)으로 호출하는 옵션을 배치
  스크립트에 둘 수 있다 — 이건 운영 데이터에 아무것도 쓰지 않으므로
  이 설계의 "보수적으로 시작한다" 원칙과 충돌하지 않는다. 구현 세부는
  구현 턴에서 결정한다.

## 8. 추천안 종합

### 8.1 추천안

**§3(모집단: 계좌 1개×종목 단위 원가 완결성) + §4(변환: 14번 문서 공식
재사용, 상태 저장소 비재사용, anomaly는 주문 전체 제외) + §5 안 A
(dry-run 승인 절차를 얹은 직접 append) + §6(idempotency: 기존 dedup
원리 재사용 + `source_channel='backfill'` + `raw_payload_uri` 감사)
+ §7(recompute는 기존 큐 메커니즘에 위임)**의 조합을 추천한다.

### 8.2 왜 이 안이 기존 append-only 원장 철학과 가장 잘 맞는가

- `fill_events`를 여전히 유일한 1차 입력으로 유지하고(안 C를 기각한
  이유와 동일), 새로운 저장 경로나 우회 경로를 만들지 않는다.
- 정정은 하지 않는다 — backfill이 잘못됐다고 판단되면(예: dry-run
  검토 단계에서 발견), append 자체를 하지 않는 것으로 대응한다.
  이미 append된 뒤에 잘못이 발견되는 상황을 최대한 피하기 위해
  dry-run 승인 절차를 필수 게이트로 둔 것이 바로 이 이유다.

### 8.3 왜 recompute 경로와 가장 자연스럽게 연결되는가

- 기존 `realized_pnl_recompute_queue`/`recompute_required`/
  `realized-pnl-recompute-worker` 파이프라인을 그대로 재사용한다 —
  backfill 전용 recompute 코드를 새로 만들지 않는다.

### 8.4 왜 시장가/지정가 분기 없이 유지할 수 있는가

- 변환 규칙(§4)의 유일한 조건은 "snapshot 시계열의 누적 관측 패턴"이며,
  주문 유형과 무관하다 — 14번 문서와 동일한 이유.

### 8.5 왜 partial/full을 별도 경로로 나누지 않아도 되는가

- snapshot 1건(완전체결로 보이는 경우)과 다건(부분체결 staircase)이
  §4.2의 같은 공식(`qty[-1]=0` 극한에서 자연히 수렴)으로 처리된다.

### 8.6 복원 대상에 포함/제외하는 주문군

| 포함 | 제외 |
|---|---|
| `filled`, cancel/정정 흔적 없음, snapshot이 끊김 없이 단조 비감소, 최종 수량이 요청 수량과 일치, 해당 종목이 완전 청산 이후 재매수로 시작하는 구간을 확인 가능 | `partially_filled`(아직 15번 경로가 처리 가능), cancel/정정 흔적 있음, snapshot 누락/역행/불일치, 원가 시작점(완전 청산 지점)을 확인할 수 없는 종목, snapshot이 1건인데 부분체결로 의심되는 경우 |

### 8.7 첫 도입 범위를 얼마나 좁게 잡을 것인가

§3.5의 범위를 그대로 1차 도입 범위로 확정한다 — 계좌 1개, 기간
`2026-08-01 KST` ~ 15번 안 B 실배포 이전 `FILLED` 전환분, 원가 완결성
있는 종목만. **이 범위를 적용한 뒤 대상이 0건이거나 극소수로 나오는
것을 실패로 보지 않는다** — 오히려 이 설계의 보수적 원칙이 제대로
작동한 결과로 해석한다.

### 8.8 보류가 더 타당한 경우

다음 중 하나라도 사실로 확인되면, 이번 1차 도입 자체를 보류하고 대신
"read-only로 표본을 더 넓게 조사"하는 것을 먼저 권장한다:

- §3.3 원가 완결성 기준을 충족하는 종목이 **0건**으로 나오는 경우 —
  이건 backfill을 서두를 이유가 없다는 뜻이다(애초에 복원 가능한
  대상이 없다).
- dry-run 결과, 계산된 synthetic fill의 수량 합계가 최종 잔량/누적
  체결량과 맞지 않는 경우가 하나라도 나오면 — 변환 규칙(§4) 자체에
  아직 발견 못 한 결함이 있을 수 있으므로, 실제 append 전에 반드시
  원인을 규명해야 한다.
- 이번 조사 범위에서 정정/취소 혼재 표본을 하나도 못 찾은 경우 —
  이는 "이번 backfill 대상에는 그 위험이 없다"는 확인이 되므로 보류
  이유는 아니지만, 만약 향후 범위를 넓히려는 시점에 정정/취소 흔적이
  있는 종목이 나타나면 그 확장은 반드시 별도 설계 turn으로 넘긴다.

### 8.9 `historical_policy_estimate` — initial backfill 전용 BUY fee 추정 override(구현 완료)

**배경**: `build_backfill_plan()`은 synthetic BUY fill의 fee를
`compute_fee_tax()`로 계산하는데, 이 함수는 `get_active_at(fill_timestamp)`
(그 체결 시각 기준 활성 정책)만 본다. `execution.fee_tax` 정책이 그 체결
이후에야 등록된 경우(이 저장소에서 실제로 발생한 사례 — `001450`(BUY
2026-08-12), `004370`(BUY 2026-08-09), 정책 활성 2026-08-14), 이 BUY는
영원히 `assumed_zero`로 남는다. 앞으로 이 종목을 매도할 때 C안 확장형
(`remaining_buy_fee_pool`, 12번 문서 14절)의 pool이 처음부터 비어 있게
되어, 미래 SELL의 `allocated_buy_fee`가 구조적으로 과소평가된다.

**이건 `007070`(이미 `fill_events`/`realized_pnl_events`가 존재하는
overlay + recompute 문제)과 근본적으로 다르다** — `001450`/`004370`는
아직 내부 원장 자체가 없는 **initial backfill 문제**다. 처음 `fill_events`
를 만들 때부터 올바른 값을 채우면, 나중에 다시 손볼 필요가 없다.

**구현**: `build_backfill_plan()`에 `use_historical_policy_estimate_for_buy_fee`
(기본값 `False`) 옵션을 추가했다. `False`면 기존 동작과 100% 동일. `True`면,
`_maybe_override_with_historical_policy_estimate()`가 아래 조건을 **전부**
만족할 때만 override한다:

1. `side == BUY`(SELL은 이 파일럿 범위 밖 — `007070` 트랙에서 별도 검토).
2. 기본 `compute_fee_tax()` 결과가 `ASSUMED_ZERO`(= 그 시점엔 활성 정책이
   없었음).
3. **현재 시각**을 `fill_timestamp`로 넘겨 `compute_fee_tax()`를 다시
   호출한 결과가 `CALCULATED_FROM_POLICY`로 성립함(= 지금은 활성 정책이
   있고, 이 자산군/시장군이 지원 대상임 — `compute_fee_tax()` 자체의
   판정 로직을 그대로 재사용해 별도 파싱/매칭 코드를 새로 만들지 않았다).

override 시 provenance는 `calculated_from_policy`가 **아니라**
`RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE`(신규,
`db/migrations/0060_add_historical_policy_estimate_fee_tax_source.sql`)로
저장한다 — `calculated_from_policy`는 "그 시점에 실제 활성이던 정책으로
계산됨"이라는 인과관계이고, `historical_policy_estimate`는 "그 시점엔
없었지만 initial backfill 단계에서 현재 정책을 소급 추정으로 적용했다"는
전혀 다른 인과관계이기 때문이다 — 절대 섞으면 안 된다(감사 가능성).

`compute_fee_tax()` 자체, `get_active_at()` 의미론, 실시간 경로
(`order_sync_service`)는 전혀 건드리지 않았다 — 이 override는
`historical_fill_backfill.py` 내부에만 존재하는, 명시적 opt-in 후처리다.

SELL이 없는 종목(`001450`, `004370` 둘 다 이 파일럿 window 안에서 매도
0건)이라, `realized_pnl_events`/`remaining_buy_fee_pool`/`allocated_buy_fee`
는 이번 구현에서 실측 대상이 아니다 — BUY fill이 `fill_events`에 올바른
`fill_fee`/`fee_tax_source=historical_policy_estimate`로 저장되면, 이후
실제 SELL이 발생할 때 기존 C안 확장형 경로(`realized_pnl_engine._apply_buy`)
가 그 pool을 자연스럽게 채운다 — 이번 구현이 별도로 손댈 필요가 없다.

CLI: `scripts/backfill_broker_fill_snapshot_historical_fills.py`에
`--use-historical-policy-estimate-for-buy-fee`(기본값 off) 추가, dry-run
리포트에 override된 fill을 `[HISTORICAL_POLICY_ESTIMATE]` 마커로 표시한다.

### 8.10 종목별 추정 수수료의 성격과 허용 오차 기준(운영 정책, 실측 적용 완료)

**이 값의 성격**: `historical_policy_estimate`로 계산되는 fee는 증권사가
그 체결 건에 대해 **개별적으로 확정해 준 수수료가 아니다**. 실제 KIS
수수료는 계좌 단위로 하루(또는 정산 주기) 전체 매매 금액을 합산한 뒤
정책 요율을 적용하는 방식에 가깝고, 이 시스템은 그 합산 기준 정책을
**체결 1건 단위로 역산**해 종목별/체결별 추정치로 환산한다. 이 환산
과정에서 반올림 단위(`rounding_unit`)가 체결별로 개별 적용되기 때문에,
"하루 전체를 한 번에 반올림한 값"과 "체결마다 나눠 반올림한 값의 합"이
정확히 일치하지 않을 수 있다.

**허용 오차 기준**: 이런 이유로, 이 시스템은 **종목별/체결별 추정
수수료가 다른 기준값(예: 향후 KIS 총괄 대사, 하루 합산 재계산)과 비교해
차이가 9원 이하이면 허용 오차 범위 내 일치로 본다.** 이 기준은 계산
로직의 버그를 눈감기 위한 것이 **아니다** — 합산 기준 정책을 체결 단위
추정치로 쪼갤 때 구조적으로 생기는 반올림 한계를 인정하는 **운영
기준**이다. 이 허용 범위는 **수수료(fee) 검산에만** 적용되며, 세금
금액, 체결 수량/가격, 잔량 정합성 같은 다른 불변식에는 전혀 적용되지
않는다 — 그런 값들은 여전히 정확히 일치해야 한다.

**`001450`/`004370` 파일럿 실측(2026-08-15 KST, `apply` 실행 완료)**:

| 종목 | fill_price × fill_quantity | 계산식(`× 0.0140527% → round_half_up`) | 기대값 | `fill_events.fill_fee` 저장값 | 차이 |
|---|---|---|---|---|---|
| `001450` | 44,153 × 56 = 2,472,568 | 2,472,568 × 0.0140527 / 100 = 347.4626 | 347 | 347 | **0원** |
| `004370` | 402,500 × 12 = 4,830,000 | 4,830,000 × 0.0140527 / 100 = 678.7454 | 679 | 679 | **0원** |

두 건 모두 오차 0원으로 9원 허용 기준을 여유 있게 충족했다. 두 종목 모두
`fee_tax_source='historical_policy_estimate'`, `fill_tax=0`(BUY이므로),
`source_channel='backfill'`로 저장됐고, 이후 `realized_pnl_recompute_queue`
에 `reason_code='manual_request'`로 등록되어(`resolved_at`은 아직 `NULL`
— 워커의 다음 주기 처리 대기 중) `position_cost_basis_state`가 갱신될
예정이다. 이번 파일럿은 SELL이 없는 종목이라 `realized_pnl_events`/
`remaining_buy_fee_pool`/`allocated_buy_fee`는 이 시점에 여전히 실측
대상이 아니다(recompute가 완료돼도 SELL이 없으면 이 필드들이 생성/변경될
계기 자체가 없다) — 향후 실제 SELL이 발생할 때가 진짜 검증 시점이다.

`007070`(overlay+recompute) 트랙은 이 파일럿과 완전히 별개이며, 이번
apply는 그 트랙에 어떤 영향도 주지 않았다.

### 8.11 발견된 버그 — `buy_fee_pool_provenance` 오분류(수정 완료)

§8.10 apply 이후 recompute가 완료된 뒤 확인한 결과, `remaining_buy_fee_pool`
금액(347/679)은 정확했지만 `position_cost_basis_state.buy_fee_pool_
provenance`가 `fully_assumed_zero`로 잘못 남아 있었다(기대값은
`historically_estimated`). 원인은 `realized_pnl_engine.py`의 pool
provenance 판정 집합이 `historical_policy_estimate`를 인식하지 못해
"계산값 아님"으로 오분류한 것 — **금액 계산 경로와 provenance 분류 경로가
서로 다른 로직을 쓰고 있었다.** 상세 원인 분석과 수정(4번째 값
`historically_estimated` 신설, 3부류 분류 체계 재구성)은 12번 문서 §14.7을
참고. 기존 `001450`/`004370` 2건은 이 코드 수정만으로는 안 고쳐지고,
`fill_events` 원본은 그대로 둔 채 별도 recompute 재실행으로 바로잡아야
한다(운영 write는 이 문서 갱신 시점 기준 아직 미실행).

**후속(별도 turn)**: `001450`/`004370` 2건은 기존 `realized_pnl_recompute_
queue` 메커니즘(`reason_code='manual_request'`)을 재사용해 재계산을
등록하고, 이미 5분 주기로 도는 `realized-pnl-recompute-worker`가 자동
처리했다. `fill_events` 원본은 전혀 건드리지 않았고(`fill_fee`/`fee_tax_
source` 불변 확인), `remaining_buy_fee_pool`/`quantity`/`average_cost`도
그대로 유지된 채 `buy_fee_pool_provenance`만 `fully_assumed_zero` →
`historically_estimated`로 정확히 바로잡혔다(전/후 값 read-only 대사로
확인). 이 두 종목 외 다른 종목(`007070` 포함)은 전혀 영향받지 않았음을
`position_cost_basis_state`/`realized_pnl_recompute_queue`/
`realized_pnl_computation_runs` 전체 건수 증분(+2, +2)으로 확인했다.

### 8.12 `initial_entry` anchor — zero-crossing 없이도 backfill을 허용하는 두 번째 원가 완결성 anchor(구현 완료)

**배경**: `007070`을 제외한 현재 보유 나머지 종목(13개)은 실제로 `2026-08-01
KST` 이후 dry-run을 재시도해도 전부 `zero_crossing_not_found`로 막혔다.
그런데 사용자가 이미 확정한 운영 사실로, 이 13종목은 전부 **그 이전에
해당 종목에 대한 매수/매도 주문 자체가 없었던, 첫 진입 종목**이다.
`build_backfill_plan()`의 기존 anchor 판정(`position_snapshots`에서
`quantity==0`인 관측을 찾는 §3.3-1 방식)은 "관측이 없음"(`anchor is
None`)과 "관측은 있는데 0이 아님"을 똑같이 위험으로 취급했는데, 전자는
사실 두 가지로 갈린다 — (a) 스냅샷 폴링 공백(위험, 뭔가 있었을 수도 있음)
과 (b) 종목 자체가 그 이전엔 존재하지 않았음(안전, 관측할 대상 자체가
없었던 것). 이 구분을 코드가 하지 않아 (b) 케이스까지 막고 있었다.

**핵심 통찰**: "그 종목에 대한 주문 이력이 아예 없다"는 사실은 "잔고가
0이었다는 스냅샷 관측"보다 논리적으로 **더 강한 증거**다 — 수량이 바뀔
수 있는 유일한 경로(주문 체결)가 애초에 발생한 적이 없으므로, 그 이전
잔고가 0이 아니었을 가능성 자체가 없다. 즉 이건 zero-crossing 규칙을
느슨하게 하는 게 아니라, **이미 갖고 있던 더 강한 사실을 anchor로
정식 인정**하는 것이다.

**구현**: `BackfillAnchorType`(`ZERO_CROSSING`/`INITIAL_ENTRY`) 신설,
`BackfillPlan.anchor_type` 필드 추가(`eligible=False`면 `None`). 판정
순서:
1. 기존 방식대로 `position_snapshots`에서 zero-crossing 스냅샷을 먼저
   시도 — 있으면 `anchor_type=ZERO_CROSSING`(기존 동작 100% 유지, 기존
   `gap_orders` 검증도 그대로 적용).
2. 실패하면(`anchor is None` 또는 `quantity != 0`), 이미 `build_backfill_
   plan()`이 구하고 있는 `all_filled_orders`(새 쿼리 없음)를 그대로
   재사용해 **`window_start` 이전 filled 주문이 하나도 없는지** 확인한다.
   있으면(과거 거래 이력 있음) 기존과 동일하게 `ZERO_CROSSING_NOT_FOUND`
   로 제외. 없고, **window 안 첫 주문이 BUY**이면(사용자 전제 "매수가
   그 종목의 첫 진입" 그대로 — 첫 주문이 SELL이면 공매도가 되어 논리적
   으로 성립하지 않으므로 이 경우도 제외) `anchor_type=INITIAL_ENTRY`,
   `zero_crossing_at=None`으로 계속 진행.
3. 이후 검증(lineage/snapshot 존재/cancel/negative delta/가격 역산/최종
   잔량 정합)은 anchor 종류와 무관하게 **전혀 완화하지 않고** 그대로
   적용된다 — `gap_orders` 개념만 `INITIAL_ENTRY` 경로에서는 정의상
   no-op이다(anchor 자체가 "window 이전 주문 전무"라 gap이 있을 수 없음).

CLI(`scripts/backfill_broker_fill_snapshot_historical_fills.py`) dry-run
리포트에 `anchor_type` 줄을 추가해 운영자가 어느 anchor로 통과했는지
바로 알 수 있게 했다.

**자격 판정(eligibility)과 fee 추정(provenance)의 계층 분리 유지**: 이
확장은 오직 `build_backfill_plan()`의 anchor 판정에만 관여하며,
`compute_fee_tax()`/`--use-historical-policy-estimate-for-buy-fee`/
`historical_policy_estimate`/`historically_estimated`(§8.9~§8.11) 로직은
전혀 건드리지 않았다 — initial-entry로 통과한 종목의 BUY fee가
`assumed_zero`가 될지 `historical_policy_estimate`가 될지는 여전히
완전히 별개의 계층(fee 계산)이 독립적으로 결정한다.

**이번 turn 범위**: 코드/테스트/문서까지만. 13종목이 실제로 이 새 anchor로
eligible이 되는지, eligible이 된 종목에 대한 실제 apply는 **별도 turn에서
진행**한다(이번 turn은 운영 apply를 포함하지 않는다).

## 9. 리스크

| 리스크 | 평가 |
|---|---|
| 잘못된 synthetic fill이 append-only 원장에 영구히 남음 | §5.2의 dry-run + 사람 승인 게이트로 완화. 그래도 append 이후 발견되는 오류는 12번 문서 7.3절의 upsert 정정 경로(계산값만 다시 쓰기)로 recompute를 다시 돌리는 것 외에는 표준 해법이 없다는 것을 인지한다. |
| 원가 완결성 판정 로직 자체의 결함(경계 케이스 누락) | §8.8의 보류 조건으로 1차 방어. 구현 턴에서 판정 로직에 대한 좁은 단위 테스트를 반드시 둔다. |
| 미래 실시간 경로와의 우연한 충돌 | §6.2에서 이미 population 제한으로 구조적으로 낮음을 확인. |
| `broker_fill_snapshots` 자체가 실제 체결과 다르게 관측됐을 가능성(대사 소스 자체의 신뢰도) | 이 설계의 범위 밖 — `fill_history_sync.py`가 이미 이 값을 대사 목적으로 신뢰하고 있다는 기존 전제를 그대로 물려받는다. 이 전제 자체가 흔들리면 이 backfill 설계 전체가 재검토 대상이다. |
| 표본이 작아 검증력이 낮음 | 이 설계는 애초에 "표본이 작아도 확실한 것만 다룬다"를 목표로 하므로, 표본이 작다는 것 자체는 이 설계의 실패 조건이 아니다. |

## 10. 검증 계획

- **구현 전 추가 read-only 조사 필요 여부**: 필요하다 — §3.3의 원가
  완결성 판정을 실제 DB에 대해 read-only로 먼저 실행해, 대상 종목 수가
  몇 건인지 확인하는 조사 turn을 구현 turn 이전에 별도로 두는 것을
  권장한다(이번 설계 문서는 그 조사를 수행하지 않았다 — 문서 작성만
  지시받았기 때문).
- **구현 후 필요한 좁은 테스트**:
  1. §4.2 delta 계산 순수 함수의 단위 테스트(snapshot 1건, 단조
     staircase, 음수 역행 anomaly, 가격 산출 불가 anomaly).
  2. §3.3 원가 완결성 판정 로직의 단위 테스트(완전 청산 시작점 탐지,
     snapshot 누락 감지, cancel/정정 흔적 감지).
  3. dry-run 모드가 실제로 아무것도 쓰지 않는지 확인하는 테스트.
  4. idempotency 테스트 — 같은 backfill을 두 번 실행해도 `fill_events`
     행 수가 늘지 않는지.
- **운영에서 확인해야 할 표본**: dry-run 결과 리포트를 사람이 직접
  §3.3/§3.4 기준과 대조해 눈으로 재확인한다(자동 판정을 그대로
  신뢰하지 않는다).
- **backfill dry-run/shadow류 검증**: 이미 §5.2에 설계에 포함돼 있다 —
  dry-run은 이 backfill의 필수 1단계이며 선택 사항이 아니다.

## 11. 이번 설계가 명시적으로 다루지 않는 것 (범위 밖)

- 실제 코드 구현, migration, 배치 스크립트 작성 — 전부 미착수.
- 여러 계좌로의 확장 — 1개 계좌 검증 이후로 명시적으로 미룬다.
- 정정/취소가 혼재된 케이스의 자동 처리 — anomaly로 전체 제외하는
  수준까지만 다루고, 그 케이스를 실제로 복원하는 로직은 표본 확보 후
  별도 설계.
- live 환경 확장 — paper 검증 이후로 미룬다.
- `broker_fill_snapshots` 자체의 관측 신뢰도 검증(대사 리포트 정식화,
  12번 문서 10절의 향후 확장 항목과 동일선상) — 이 설계는 그 신뢰도를
  전제로만 사용한다.
- 안 B(별도 staging 테이블)로의 전환 — 대상 범위가 넓어지면 재검토
  (§8.2 참고).
