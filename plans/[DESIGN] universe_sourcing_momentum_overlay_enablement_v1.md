# 종목 소싱(Universe Sourcing) 구조 개선 — market_overlay 활성화 및 모멘텀 신호 보강 v1

작성일: 2026-07-12
상태: 설계 확정 대기 (구현 미착수)

## 0. 문서 성격과 배경

이 문서는 `entry_score`/`core_risk_off` 완화 시도가 **전면 영구 중단**된 이후의
후속 방향 설계다(사용자 확정, 2026-07-12).

### 확정된 전제 (변경 불가)
- 지난 6주(2026-06-01~07-12) 매수 0건은 시스템 오류가 아니라 **하락장에서
  자본을 지켜낸 올바른 방어 작동**이었음이 실측으로 증명됐다.
  - `deep_negative` T+3 평균 -5.39% < `inactive` T+3 평균 -3.17%
  - `0.55<=entry_score<0.65` 근접군 T+3 ≈ -3.56%
  - 게이트 해제 역-시뮬레이션(SF1~SF12) 전부 No-Go 또는 Shadow-Watch 수준
- **따라서 `core_risk_off` 완화·`entry_score` 조작 시도는 이 시점부로 전면
  영구 중단한다.** 관련 이력: `[BACKLOG] core_risk_off_slow_floor_shadow_relaxation.md`,
  `[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md`,
  `[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`,
  `[PLAN] core_risk_off_ranking_relaxation_phase1.md`.

### 2026-07-12 소싱 단계 분석으로 확인된 근본 원인
시스템은 원래 "정적 대형주 풀(core) + 동적 모멘텀 오버레이(market_overlay)"
2레이어로 설계됐는데(`[POLICY] trading_universe_policy_v1.md` §4.1/§4.4),
실제로는:

1. **core 레이어는 100% 가격/모멘텀 무관** —
   `_is_core_seed_instrument()`(`universe_selection.py:691-701`)의 판정 기준은
   ① `metadata.core_universe` 플래그 ② KOSPI100/200/LARGE 지수 편입
   ③ 하드코딩 allowlist(`core_universe_seed.py`, 90종목)뿐이며, 최근
   수익률·추세·이동평균 등 가격 신호는 어디에도 없다.
2. **core 회전(rotation) 부재** — 한번 편입되면 상장폐지/거래정지/관리종목
   지정/운영자 수동 제외 외에는 영원히 후보군에 남는다. "N일 연속 하락 시
   제외" 같은 규칙이 코드·설계 문서 어디에도 없다.
3. **모멘텀을 잡는 유일한 장치(`_add_market_overlay()`)가 6주 내내 완전
   비활성** — 이중 env 게이트 때문이다:
   - `universe_selection.py:1138` — `kis_client.env == "paper"`면 즉시 skip
     (`"market_overlay: skipped in paper env"`)
   - `rest_client.py:2431` `get_market_overlay_seed_symbols()` —
     `if self.env != "live": return []`
   - 현재 배포 설정이 `KIS_ENV=paper`이므로 **이 레이어는 단 한 번도 실행된
     적이 없다.**
4. **구현된 스코어링이 설계 의도보다 근시안적** — 정책 문서는 "상대
   거래량/거래대금 급증률로 새로 강해지는 종목을 조기 포착"을 의도했지만,
   실제 `_calc_market_score()`(`universe_selection.py:186-221`)는 당일
   등락률/당일 거래대금/당일 신고가 근접도만 본다(멀티데이 모멘텀 없음).
5. **지수 편입 데이터가 수동·일회성 스냅샷** — `instrument_index_memberships`는
   운영자 수동 업로드 파이프라인(`[RUNBOOK] index_membership_source_package_apply.md`)
   으로만 갱신되며 마지막 적용은 `as_of_date: 2026-06-24`. 자동 스케줄러는
   종목 마스터(활성여부/이름)만 매일 갱신하고 지수 구성은 갱신하지 않는다.

즉 **"게이트가 좋은 종목을 막는" 문제가 아니라 "좋은 종목이 게이트까지
도달할 경로 자체가 꺼져 있는" 문제**다. 이 문서는 그 경로를 복구·보강하는
작업의 설계와 백로그를 정의한다.

## 1. 목표 / 비목표

### 목표
- paper 트레이딩 환경을 유지한 채, **시세 조회만 라이브 read-only
  credential(`KIS_LIVE_INFO_*`)로 수행**해 market_overlay 레이어를 활성화한다.
- market_overlay 스코어링에 **멀티데이 모멘텀/상대 급증률 신호**를 추가해
  "당일 스파이크"가 아니라 "새로 시작되는 추세"를 포착하게 한다.
- 지수 편입 데이터(`instrument_index_memberships`)의 갱신을 자동화한다.
- 모든 변경은 **소싱(후보 공급) 단계에 한정**한다 — 하류 게이트
  (`entry_score`/`core_risk_off`/eligibility)는 일절 수정하지 않는다.

### 비목표 (명시적 금지)
- `entry_score` 구성/threshold 변경 — 영구 중단 확정.
- `core_risk_off` floor/bucket/threshold 완화 — 영구 중단 확정.
- 주문 실행 경로의 credential/env 변경 — 주문은 계속 paper 계좌로만 나간다.
- core universe에서 하락 종목을 실제로 **제외**하는 로직(4순위 검토 항목은
  후순위 백로그로만 기록, 이번 범위에서 구현하지 않음).

## 2. 설계

### 2.1 P1 — market_overlay env 게이트 분리 (핵심)

**현재 구조의 문제**: "주문 환경이 paper인가"와 "시세 랭킹 데이터를 라이브로
받을 수 있는가"가 하나의 `env` 판정으로 묶여 있다. 그러나 이 둘은 독립적이다
— 시세 랭킹 조회는 read-only이며, 이미 별도의 라이브 read-only 계좌
(`KIS_LIVE_INFO_*`, 2026-07-10 credential 통합으로 authoritative 확정)가
공시 조회·076 휴장일 조회·실시간 현재가 화면에 사용되고 있다.

**설계**:
- `UniverseSelectionService`가 주문용 `kis_client`(paper) 외에 **시세 랭킹
  전용 라이브 read-only client를 별도 주입**받을 수 있게 한다.
  - 후보 A(권장): `_build_kis_live_quote_client(settings)`(이미 존재,
    `runtime/bootstrap.py` — `KIS_LIVE_INFO_*` 기반 read-only client)를
    `UniverseSelectionService(kis_client=...)`에 넘기는 배선을 decision-loop
    호출부(`run_decision_loop.py`)에서 조정한다. 이 client는 `env="live"`이므로
    기존 이중 게이트를 코드 변경 없이 자연 통과한다.
  - 후보 B(비권장): 게이트 조건 자체를 `env` 대신 "ranking API 사용 가능
    여부" 플래그로 바꾸는 방안 — paper 주문 client로 라이브 랭킹 API를 호출할
    수는 없으므로 결국 별도 client 주입이 필요해져 A와 동일 결론.
- **안전 불변식 유지**:
  - 이 client는 시세/랭킹 read-only 엔드포인트만 호출한다(주문/잔고 금지 —
    기존 `_build_kis_live_quote_client`의 계약과 동일).
  - `KIS_LIVE_INFO_*` REST rate budget은 076/공시 조회와 공유되므로,
    market_overlay 랭킹 호출(거래량 상위/체결강도 상위 + `inquire-price`
    batch 최대 50건)의 호출량을 rate budget 관점에서 사전 산정한다.
  - decision loop는 5분 배치이므로 sustained RPS 부담은 낮다 —
    다만 pre-pool 50건 batch가 순간 burst가 되지 않게 기존
    `RateLimitBudgetManager` 경유를 유지한다.
- **paper 주문 경로는 무변경**: `_add_market_overlay`가 선정한 종목도 결국
  기존 eligibility/entry_score 게이트를 그대로 통과해야 주문이 나간다.
  즉 이 작업은 "후보 공급을 늘리는" 것이지 "매수 기준을 낮추는" 것이 아니다.

### 2.2 P2 — 멀티데이 모멘텀 신호 추가

**현재**: `_calc_market_score()` = 당일 등락률(prdy_ctrt) + 당일
거래대금(acml_tr_pbmn) + 당일 신고가 근접도(stck_prpr/stck_hgpr).

**추가 설계** (정책 문서 §4.4의 원래 의도 복원):
- `relative_volume_surge`: 당일 거래량 / 최근 N일(기본 20일) 평균 거래량 비율.
  일봉 데이터는 기존 `get_daily_price`(FHKST01010400 계열) 재사용.
- `short_term_momentum`: 5일/20일 수익률 양전환 여부(예: 5일 수익률 > 0 이고
  20일 수익률이 -5% 이상으로 회복 중). 목적은 "이미 다 오른 종목"이 아니라
  "하락을 멈추고 돌아서는 종목"의 조기 포착.
- 스코어 합성은 기존 `_calc_market_score` 가중 합에 항목 추가하되,
  **초기에는 shadow 필드로만 기록**(선정 결과에 반영하지 않고
  `market_overlay_diagnostics`에 병기)한 후, 수일 관측으로 후행 proxy(T+1/T+3)
  개선이 확인되면 실제 가중치에 반영한다 — `core_risk_off` 세션에서 확립된
  "shadow 먼저, authoritative 나중" 원칙을 그대로 따른다.
- 일봉 조회 추가 비용: pre-pool 50종목 × 일봉 1회 = 호출 50건/사이클 증가.
  캐시(당일 내 재사용) 도입으로 실질 증가는 1일 1회 수준으로 억제 가능.

### 2.3 P3 — 지수 편입 데이터 자동 갱신

- 현행: `[RUNBOOK] index_membership_source_package_apply.md`의 수동 4단계
  파이프라인(`build → validate ×2 → import`). 이미 체이닝 스크립트
  (`run_index_membership_source_package_pipeline.py`)가 존재한다.
- 설계: KIS 지수구성종목 조회 API로 constituents CSV를 자동 생성하는 소스
  어댑터를 추가하고, `run_ops_scheduler.py`의 장전 배치(instrument master
  sync 04:50 부근)에 **주 1회(예: 월요일) 지수 편입 갱신 단계**를 추가한다.
  - 지수 구성 변경은 분기 리밸런싱 중심이므로 일 단위 갱신은 과잉 — 주 1회로
    충분하며 API 비용도 낮다.
  - 기존 검증 스크립트(`validate_*` 2종)를 그대로 자동 파이프라인의 gate로
    사용해, 검증 실패 시 기존 데이터를 유지하고 경고만 남긴다(보수적 실패).
- KIS에 적절한 지수구성 API가 없거나 불안정하면: 수동 업로드 절차는
  유지하되, **staleness 감시**(마지막 `as_of_date`가 21일 초과 시 운영
  대시보드 경고)만 자동화하는 축소안으로 대체한다.

### 2.4 P4 — (후순위 검토) core 종목 장기 하락 시 사이클 내 후순위화

- core에서 **제외하지 않고**, `slow_trend/slow_momentum`이 N일 연속 심한
  음수인 core 종목을 `_apply_cap()`의 우선순위 정렬에서 뒤로 미루는 방안.
- 이는 "좋은 종목 찾기"가 아니라 "나쁜 종목의 자리 차지 방지"라 효과가
  간접적이고, cap(현재 core_cap 여유 있음)이 실제 병목이라는 실측도 아직
  없다. **P1~P3 효과 관측 이후에만 착수 여부를 재판단**한다.

## 3. 작업 진행 순서

| 순서 | 작업 | 규모 | 선행 조건 |
|---|---|---|---|
| 1 | P1-a: rate budget 사전 산정 — market_overlay 활성 시 `KIS_LIVE_INFO_*` 계좌의 REST 호출량 증가분 계산(랭킹 2종 + inquire-price ≤50건/사이클 × 5분 배치) 및 기존 076/공시 사용량과 합산 검증 | 소 | 없음 |
| 2 | P1-b: `run_decision_loop.py`에서 `UniverseSelectionService`에 `_build_kis_live_quote_client(settings)` 주입 배선 추가(라이브 read-only client 없으면 기존처럼 skip — 무설정 환경 하위 호환) | 소 | 1 |
| 3 | P1-c: `universe_selection.py` paper-skip 조건 정리 — "주입된 client의 env"기준 판정은 유지하되, 라이브 read-only client가 주입된 경우의 로그/diagnostics(`seed_pool_source`, `skipped_reason`) 정확화 + 회귀 테스트 | 소 | 2 |
| 4 | P1-d: 1~2 거래일 실측 — `market_overlay_diagnostics`(pre_pool/quotes_received/scored/added)가 실제로 채워지는지, 신규 편입 종목이 freeze/decision loop에 나타나는지, rate budget 소진 여부 확인 | 관측 | 3 |
| 5 | P2-a: `relative_volume_surge`/`short_term_momentum` 신호를 shadow 필드로 추가(선정 미반영, diagnostics 기록만) | 중 | 4 |
| 6 | P2-b: shadow 신호 수일 관측 → 후행 proxy(T+1/T+3) 기준 개선 확인 시 스코어 가중치 반영 승격 | 관측+소 | 5 |
| 7 | P3: 지수 편입 자동 갱신(주 1회 스케줄러 단계) 또는 staleness 감시 축소안 | 중 | 1~4와 병렬 가능 |
| 8 | P4: core 장기 하락 종목 사이클 내 후순위화 — 착수 여부 재판단만 | 판단 | 6 관측 결과 |

## 4. 백로그

- [ ] **UNIV-1 (P1)**: market_overlay용 라이브 read-only client 주입 배선
      (`run_decision_loop.py` + `universe_selection.py` diagnostics 정리).
      rate budget 사전 산정 포함. — **1순위**
- [ ] **UNIV-2 (P1 검증)**: 활성화 후 1~2 거래일 실측 —
      `market_overlay_diagnostics` 채워짐 / freeze에 market_overlay 종목 등장 /
      rate budget 여유 확인. — **1순위(UNIV-1 직후)**
- [ ] **UNIV-3 (P2)**: 멀티데이 모멘텀 신호(`relative_volume_surge`,
      `short_term_momentum`) shadow 추가 → 관측 → 승격 판단. — **2순위**
- [ ] **UNIV-4 (P3)**: 지수 편입 데이터 자동 갱신(주 1회) 또는 staleness
      경고 축소안. — **3순위**
- [ ] **UNIV-5 (P4)**: core 장기 하락 종목 사이클 내 후순위화 — UNIV-3 관측
      후 착수 여부만 재판단. — **4순위(보류)**

## 5. 우선순위 근거

1. **UNIV-1/2가 1순위인 이유**: 근본 원인(모멘텀 레이어 완전 비활성)을 가장
   직접적으로 해소하고, 코드 변경 범위가 작으며(배선 + diagnostics), 주문
   경로 무변경이라 리스크가 낮다. 이미 존재하는 인프라
   (`_build_kis_live_quote_client`, `KIS_LIVE_INFO_*` credential 통합 완료)를
   재사용만 하면 된다.
2. **UNIV-3이 2순위인 이유**: UNIV-1 없이는 신호를 추가해도 실행 자체가
   안 되므로 순서상 뒤. 또한 authoritative 반영 전 shadow 관측이 필요해
   리드타임이 있다.
3. **UNIV-4가 3순위인 이유**: 소싱 신선도 문제이긴 하나 "모멘텀 포착"과는
   별개 축(대형주 풀 최신화)이고, 지수 구성 변경 주기가 길어 시급성이 낮다.
4. **UNIV-5가 보류인 이유**: 후보 공급 확대(1~3)의 효과를 본 뒤에야 cap
   경합이 실제 병목인지 판단할 수 있다.

## 6. 검증 기준

- UNIV-1/2: `market_overlay_diagnostics.enabled=true`,
  `quotes_received_count > 0`, `added_count > 0`인 사이클이 실거래일에 관측될 것.
  `KIS_LIVE_INFO_*` REST 사용량이 rate budget 내일 것. 기존 테스트
  (`tests/services/test_universe_selection.py` 98건 등) 전건 통과.
- UNIV-3: shadow 필드가 기록된 표본으로 "신호 상위군 vs 하위군" 후행
  proxy(T+1/T+3) 차이가 확인될 것 — `core_risk_off` 세션과 동일한 판단 원칙
  ("WATCH 증가가 아니라 후행 proxy 개선"이 기준).
- 공통: 하류 게이트(`entry_score`/`core_risk_off`) 코드는 diff 0이어야 한다.

## 7. 관련 문서

- `plans/[POLICY] trading_universe_policy_v1.md` — §4.1(core 소싱 우선순위),
  §4.4(market-driven overlay 설계 의도)
- `plans/[DESIGN] universe_selection_service.md` — P2a-4 market_overlay 구현 내역
- `plans/[RUNBOOK] index_membership_source_package_apply.md` — 지수 편입 수동 파이프라인
- `plans/[BACKLOG] core_risk_off_slow_floor_shadow_relaxation.md` — 완화 중단에
  이르는 실측 이력(§2.4 2026-07-12 pivot)
- `plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md`
- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`
