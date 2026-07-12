# 종목 소싱(Universe Sourcing) 구조 개선 — market_overlay 활성화 및 모멘텀 신호 보강 v1

작성일: 2026-07-12 / 최종 갱신: 2026-07-12 (UNIV-1 실측 반영)
상태: UNIV-1/2/4 완료, UNIV-3 shadow 신호(F5 fallback + 멀티데이 모멘텀)
구현 완료 — UNIV-3는 관측 승격 판단만 남음, 다음은 UNIV-5 착수 여부 재검토

### ⚠️ 2026-07-12 UNIV-1 실측 후 정정 (중요)
§2.1의 원래 전제("라이브 read-only client를 새로 배선해야 한다")는 **틀렸다**.
`run_decision_loop.py::_load_trading_universe_with_anchor()`에 `_build_kis_live_quote_client(settings)`
주입 배선이 **이미 존재**하며(git blame: 초기 프레임워크 커밋부터), 실측
결과 `env="live"`로 정상 동작한다. 실제 근본 원인은 §2.1이 아니라 **intraday
freeze materialize 시점과 F5(누적거래대금) 필터의 경합**이다 — 상세는
§2.1-정정 및 `[BACKLOG] backlog.md` UNIV-1-fix 항목 참고.

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

### 2.1-정정 (2026-07-12 실측 결과 — §2.1 원안 대체)

**실측 방법**: `scripts/diagnose_market_overlay_shadow.py`(신규, read-only,
DB 쓰기 없음)로 `_build_kis_live_quote_client(settings)` + `compose_with_diagnostics()`를
직접 호출 → `kis_client.env == "live"` 확인, market_overlay가 core 대비
신규 5종목(`005930, 009150, 105560, 240810, 402340`) 편입 확인
(`logs/univ1_market_overlay_shadow_compose_2026-07-12.log`). 이어서
`universe_freeze_run_items` DB 조회 + 보존된 `ops-scheduler` 로그로
2026-06-25~07-10 구간을 교차검증한 결과:

- **07-03**: freeze materialize 시각 `09:01:56`(장 시작 09:00 이후) →
  `market_overlay 편입 5건` 정상 성공, 실제 decision loop에 반영됨.
- **06-30, 07-01, 07-02, 07-05~07-10 (9거래일 중 8일)**: freeze materialize
  시각 정확히 `08:50:xx`(장 시작 **전**) → pre-pool/시세조회는 성공하지만
  "편입 N건" 로그 자체가 없음(`added_count=0`).

**근본 원인**: `_check_acc_trade_amount()`(F5 필터, `universe_selection.py`)가
`acml_tr_pbmn`(당일 누적 거래대금) < 임계값이면 탈락시키는데, 08:50은 장
시작(09:00) 전이라 **모든 종목의 당일 누적거래대금이 0에 가깝다** — 따라서
seed pool 전원이 F5에서 탈락해 `added_count=0`이 된다. 이 스킵은 지금까지
`logger.debug(...)`로만 남아 운영 로그(INFO 레벨)에서 전혀 보이지 않았다
(2026-07-12 turn에서 warning 레벨로 격상 완료 — §"완료" 참고).

**결론**: 원안(§2.1, 아래 취소선 처리)의 "라이브 client를 새로 주입해야
한다"는 전제 자체가 틀렸다 — 배선은 이미 존재하고 정상 동작한다. 진짜
문제는 **intraday freeze materialize 시점(`INTRADAY_START=08:50`)이 장 시작
시각(09:00)보다 이르다는 스케줄링 경합**이다. 이 문제의 수정(예: freeze
트리거 시각 조정, 또는 market_overlay 평가를 freeze materialize 시점과
분리)은 `INTRADAY_START`가 다른 장전 작업에 미치는 영향을 아직 조사하지
않았으므로 **이번 턴에서 단독으로 구현하지 않고 UNIV-1-fix로 백로그에만
기록**한다(§4 참고).

### 2.1 P1 — market_overlay env 게이트 분리 (원안, 실측으로 전제 반증됨 — 참고용으로만 보존)

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
- **(2026-07-12 추가, UNIV-1-fix 통합)** 이 일봉 재사용 작업에 F5
  pre-market fallback을 함께 반영한다: 당일 `acml_tr_pbmn`이 미형성(장
  시작 전 freeze materialize) 상태로 F5가 전량 탈락시킬 때, 전일 종가
  기준 거래대금(일봉 최근 1건)을 대체 판정 기준으로 사용해 pre-market
  freeze에서도 market_overlay가 최소한의 후보를 편입할 수 있게 한다.
  근거: §2.1-fix 조사(`logs/univ1_fix_scope_investigation_2026-07-12.log`).

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

**2026-07-12 확인 결과 — 축소안으로 확정**: `rest_client.py`에 구현된
지수 관련 API는 `inquire_index_category_price`(업종 구분별 **시세**)뿐이며,
개별 종목 리스트(constituents)를 제공하는 KIS API는 코드베이스 어디에도
없다. 자동 갱신 어댑터를 새로 만들려면 미검증 API를 조사해야 하므로(리스크
불명), **이번 턴에서는 자동 갱신 대신 staleness 감시 축소안만 구현**한다.
`instrument_index_memberships`의 최근 활성 반영 시각(`effective_from`
최댓값)을 조회해 21일 초과 시 경고하는 read-only 로직 —
`src/agent_trading/services/index_membership_staleness.py`
(`evaluate_index_membership_staleness()`), 조회 메서드는
`InstrumentIndexMembershipRepository.get_latest_effective_from()`으로
추가(Postgres/in-memory 모두 구현). 실측:
`scripts/check_index_membership_staleness.py` 실행 결과 마지막 반영
`2026-06-27`, age=15일(threshold 21일) → **정상**, staleness 위험까지
6일 남음(`logs/univ4_index_membership_staleness_check_2026-07-12.log`).
운영 대시보드(프론트엔드) 노출은 이번 턴 범위 밖 — 백엔드 조회/판단 로직만
구현하고 다음 턴 대상으로 남긴다.

### 2.1-fix — UNIV-1-fix 범위 조사 결과 (2026-07-12)

freeze materialize 시각(`INTRADAY_START=08:50`)과 F5(누적거래대금) 필터
경합의 실제 수정 방안을 조사했다(코드 분석만, 변경 없음 — 상세:
`logs/univ1_fix_scope_investigation_2026-07-12.log`).

**대안 A — `INTRADAY_START`를 09:00 이후로 이동**: 스케줄러 파일 안에서는
`instrument_master_sync`(기본 04:50)/`instrument_status_snapshot`(기본
05:05) 완료 마감선으로도 쓰이지만, 이 두 작업엔 이미 margin이 충분해
직접 영향은 없다. 그러나 "Pre-Market 08:00-08:50 / Intraday 08:50-15:30"
경계는 스케줄러 파일 밖에서도 최소 8개 계획/운영 문서(EXPIRED fallback
suppression window, cadence 산정 등)에 하드코딩된 전제로 등장한다.
**→ 부적합. 넓은 blast radius, 이번 소싱 트랙 범위 밖이라 단독 변경하지
않는다.**

**대안 B — F5 threshold를 낮추거나 pre-market엔 F5를 skip**: 실측 근거
없는 단순 완화이며 "실측 근거 없는 완화 제안 금지" 원칙에 위배. **→ 채택
안 함.**

**대안 C — F5에 "당일 데이터 형성 전이면 전일 거래대금으로 대체 판정"하는
fallback 추가**: 근거 있는 대안이나, 현재 market_overlay pre-pool 조회에는
전일 거래대금 데이터가 없다 — `get_daily_price()`(심볼별, `rest_client.py`)
호출이 추가로 필요하다. 이는 §2.2(UNIV-3)가 이미 계획한 "일봉 데이터 재사용"
작업과 정확히 동일한 데이터 소스다. **→ 채택. 단, 독립 구현하지 않고 UNIV-3
착수 시 daily_price 연동에 F5 pre-market fallback을 함께 반영한다** —
동일 API 연동의 중복 구현을 피하기 위함.

**결론**: UNIV-1-fix는 별도 트랙이 아니라 **UNIV-3의 선행 요구사항으로
재scope**한다. UNIV-3 설계(§2.2)에 "일봉 재사용 시 F5 pre-market fallback도
함께 계산" 항목을 추가했다.

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

- [x] **UNIV-1 (P1)**: market_overlay용 라이브 read-only client 주입 배선
      확인. **2026-07-12 완료 — 배선은 이미 존재·정상 동작함을 실측으로
      확인**(신규 배선 불필요). 부가로 `_add_market_overlay()`의 3개 silent
      skip 로그(`empty_pre_pool`/`no_quotes_returned`/`all_candidates_filtered`)를
      debug→warning으로 격상 + 사유별 breakdown 추가
      (`src/agent_trading/services/universe_selection.py`), 회귀 테스트 3건
      추가(`tests/services/test_universe_selection.py`). — **완료**
- [x] **UNIV-2 (P1 검증)**: 활성화 후 실측 — `market_overlay_diagnostics`
      채워짐(pre_pool 14건, quotes 13/14, added 5건) 확인
      (`logs/univ1_market_overlay_shadow_compose_2026-07-12.log`). DB
      교차검증(`universe_freeze_run_items`)으로 07-03은 정상 동작, 06-30~07-10
      중 8거래일은 `added_count=0`임을 확인. — **완료(원인 규명까지 완료)**
- [x] **UNIV-1-fix 범위 조사 (완료, 2026-07-12)**: intraday freeze
      materialize 시점(08:50)과 F5 경합 문제의 수정 방안 3개(A: 시각 이동,
      B: threshold 완화, C: 전일 거래대금 fallback)를 조사·비교.
      A는 blast radius 과다(8+ 문서에 08:50 경계 하드코딩)로 부적합, B는
      실측 근거 없는 완화라 금지 원칙 위배, **C만 채택** —
      단 독립 구현 대신 **UNIV-3에 통합**(§2.2 참고, 동일 daily_price API
      연동 중복 방지). 상세: `logs/univ1_fix_scope_investigation_2026-07-12.log`.
      → UNIV-1-fix는 별도 백로그 항목이 아니라 UNIV-3의 하위 작업으로 재편.
- [~] **UNIV-3 (P2, UNIV-1-fix 통합)** — **1순위**, 부분 완료(2026-07-12):
  - [x] **F5 pre-market fallback shadow (완료)**: `_add_market_overlay()`가
        F5(low_volume)로 전량 탈락할 때, `get_daily_price()`(전일 종가×거래량)
        기반 추정 거래대금으로 "F5를 통과했을 후보"를 shadow로만 관측한다
        (`_evaluate_f5_shadow_fallback()`, `universe_selection.py`).
        `MarketOverlayDiagnostics`에 `shadow_fallback_evaluated`/
        `shadow_fallback_evaluated_count`/`shadow_fallback_pass_count`/
        `shadow_fallback_top_symbols` 필드 추가. **실제 선정에는 절대
        반영하지 않는다**(shadow-first) — `added_count`는 변경 없이 0 유지.
        테스트 2건 추가(정상 관측 1건 + `get_daily_price` 미지원 client
        하위호환 1건), 전체 103건 통과.
  - [x] **`relative_volume_surge`/`short_term_momentum` shadow 신호 (완료,
        2026-07-12)**: market_overlay가 실제로 선정한 top_n(기본 5건)에 한해
        `get_daily_price()` 기반으로 상대 거래량 급증(`relative_volume_surge`
        = 당일/최근 20일 평균)과 5일/20일 수익률·"하락 후 반등"
        플래그(`short_term_recovering`)를 계산해 `MomentumShadowSignal`로
        기록한다(`_calc_momentum_shadow_signal()`,
        `_evaluate_multiday_momentum_shadow()`). rate budget 보호를 위해
        pre-pool 전체가 아니라 이미 선정된 소수(top_n)에만 적용. **스코어링/
        선정 로직에는 영향을 주지 않는 순수 관측**(`MarketOverlayDiagnostics.
        momentum_shadow_evaluated`/`momentum_shadow_signals`). 테스트 3건
        추가(정상 관측/하위호환/실제 KIS raw dict 형태 재현), 전체 106건 통과.
  - **⚠️ 라이브 검증 중 발견·수정한 버그(2026-07-12)**: 최초 구현은
    `get_daily_price()`가 `.close`/`.volume` 속성을 가진 객체를 반환한다고
    가정했으나, 실제 주입되는 `KISRestClient.get_daily_price()`(raw REST
    client)는 KIS 원본 필드명(`stck_clpr`/`acml_vol`)의 **dict**를 반환한다
    — 라이브 read-only client로 재검증(`logs/univ3_momentum_shadow_recheck_
    2026-07-12.log`)하다가 모든 신호가 `None`으로 나오는 것을 발견해 원인을
    특정했다. `_extract_bar_close()`/`_extract_bar_volume()` 헬퍼로 dict/객체
    양쪽을 모두 지원하도록 수정, 재검증(`logs/univ3_momentum_shadow_recheck_
    fixed_2026-07-12.log`)으로 실제 값이 채워지는 것을 확인했다. F5 shadow
    fallback(`_evaluate_f5_shadow_fallback`)도 동일 버그가 있어 함께 수정.
  - [ ] **관측 승격 판단 (미착수, F5 fallback + 모멘텀 신호 공통)**: 실거래일에
        pre-market freeze/정상 사이클 모두에서 shadow 로그가 얼마나 자주/
        어떤 종목으로 관측되는지 수일 누적 후, 후행 proxy(T+1/T+3) 개선이
        확인되면 실제 선정/스코어링 반영으로 승격 판단.
- [x] **UNIV-4 (P3)** — **2순위**, 완료(2026-07-12):
  - [x] **staleness 감시 축소안 (완료)**: KIS에 지수 구성종목 API가 없음을
        확인(§2.3), 자동 갱신 대신 `get_latest_effective_from()` +
        `evaluate_index_membership_staleness()`로 read-only 감시 구현.
        실측: age=15일(threshold 21일) → 정상. 테스트 7건 추가(pure function
        5건 + postgres/in-memory repo 각 1건), 전체 통과.
  - [x] **운영 대시보드 노출 (완료)**: `GET /instruments/index-membership/
        staleness` read-only 엔드포인트 추가(`api/routes/instruments.py`,
        `api/schemas.py::IndexMembershipStalenessResponse`) + 프론트엔드
        `OperationsDashboardView`에 연결 — `is_stale=true`일 때만
        WarningBanner 노출(정상 시 화면 변화 없음). API 테스트 3건,
        프론트엔드 `tsc --noEmit` clean, `dashboard.test.tsx` 16건 +
        전체 프론트엔드 스위트 361/363건 통과(나머지 2건은 무관 파일
        `decisions.test.tsx`의 병렬 실행 타이밍 flake — 격리 실행 시
        31/31 통과 확인, 이번 변경과 무관).
  - [ ] **지수 구성종목 자동 갱신 (보류, 영구)**: KIS API 부재로 원안(§2.3
        본문) 자체가 불가 — 수동 업로드 절차(RUNBOOK) 유지, staleness
        감시로 영구 대체 확정.
- [ ] **UNIV-5 (P4)**: core 장기 하락 종목 사이클 내 후순위화 — UNIV-3 관측
      후 착수 여부만 재판단. — **다음 우선순위**

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
  - F5 shadow fallback(구현 완료): 실거래일 pre-market freeze 발생 시
    `shadow_fallback_evaluated=true` 사이클에서 `shadow_fallback_top_symbols`가
    실제로 채워지는지, 그 종목들의 후행 proxy가 `market_overlay` 정규 편입
    종목과 유사한 수준인지 확인 — 확인되면 실제 선정 반영으로 승격.
  - 멀티데이 모멘텀 shadow(구현 완료): `momentum_shadow_signals`에서
    `short_term_recovering=true`인 종목군의 후행 proxy(T+1/T+3)가 그렇지
    않은 종목군보다 개선되는지 수일 관측 후 확인 — 확인되면
    `_calc_market_score()` 가중치에 실제 반영 승격 판단.
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
