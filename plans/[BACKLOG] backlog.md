# Backlog — Future Work Candidates

> **목적**: 번호가 부여된 실행 계획(canonical numbered plan)과 아직 착수하지 않은 작업 아이디어를 분리하여 관리한다.
>
> **원칙**: "실행할 때만 번호 Plan 생성, 아직 시작하지 않을 작업은 BACKLOG에만 기록."

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: BUY 주문 0건의 `entry_score` 직접 병목 실측을 반영하고, 신호
  통계 보정부터 전체 BUY funnel back-simulation 및 제한적 probe까지의
  최우선 후속 백로그를 추가했다. 기존 universe sourcing 최우선 표기는
  2026-07-12 이력으로 격하했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: SPPV-2(core 88종목 확장 검증) 완료 결과를 반영 — SPPV-1
  파일럿의 낙관적 결론이 overlap 편향이었음을 확인하고, SPPV-2.5(quintile
  spread 정체 진단)를 신설, SPPV-3을 조건부 보류로 재분류했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: SPPV-2.5(quintile spread 국면 내부 재검증) 완료 결과를 반영 —
  pooled 유의성이 국면 혼입 착시일 가능성이 높다는 결론을 기록하고, SPPV-3
  착수 조건을 "표본 확장 후 국면 내부 유의성 재확인 또는 신호 feature
  재설계"로 구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (3차, 사용자 지적 반영)
- 수정내용: SPPV-2.5의 "국면 혼입 착시" 결론을 방법론 오류(`regime_label`이
  시장이 아니라 종목 자신의 신호였음)로 폐기했다. KODEX 200 시장 벤치마크
  기준 재검증(SPPV-2.6)을 신설해 반영 — 결론이 반박되어 알파 근거가
  강화됐으나, 하락장 표본 전무라는 새 한계가 확인돼 SPPV-3 보류 사유를
  "하락장 검증 공백"으로 교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (4차)
- 수정내용: SPPV-2.6의 "알파 근거 강화" 결론을 다시 하향 조정했다.
  벤치마크(069500) 자기참조 제거 + 3년 확장 검증(SPPV-2.7)에서 pooled
  유의성이 소멸하고 하락장에서 신호가 역전/역방향으로 나타났다. SPPV-3
  보류 사유를 "신호 feature 재설계 검토 필요"로 재교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (5차, 검증 기간 재설계)
- 수정내용: 이 시스템이 3개월 이하 중단기 공격형이라는 전제로 **SPPV 검증
  기간 기준을 재설계**했다(SPPV-2.8 신설). 3년 pooled를 기본값으로 두지
  않고, 최근 12개월을 1차(primary), 3년(SPPV-2.7 재사용)을 국면 커버리지
  2차(supplementary) 게이트로 분리했다. 최근 12개월 실측 결과 하락장
  거래일이 0일이라 1차만으로는 필수 국면 검증이 불가능함을 실증했고, 1차
  pooled 유의성도 확보되지 않았다. §14의 보류 판정은 유지.

- 작성자: Claude
- 수정일자: 2026-07-14 (6차, 실행 증빙 재검증)
- 수정내용: SPPV-2.8의 최초 실행 로그가 실제로는 호스트 `dotenv` 미설치로
  즉시 실패한 트레이스였던 증빙 결함을 발견하고, 컨테이너에서 재실행해
  정상 로그를 재확보했다. 종료 코드 0/KIS 호출 0건/bearish_trend 0일/
  `overall_score` T+20 t_NW=1.18 전부 재현 — 결론·판정 변경 없이 증빙만
  보강했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (7차, 신호 feature 재설계 검토 — SPPV-2.9)
- 수정내용: §14.5가 지시한 신호 feature 재설계 검토를 실행했다(SPPV-2.9
  신설). `fast_score`/`slow_score`의 6개 sub-component 분해 + 신규 후보
  feature(`risk_adj_momentum_3m`, `reversal_1m`) 검증 결과, `rsi_signal`
  이 T+20에서 유의하게 역방향(t_NW=-2.94)임을 특정했고, `risk_adj_
  momentum_3m`이 3년 pooled 유의(t_NW=2.07) + 하락장 역전 없음으로
  유일한 Watch 후보로 확인됐으나 1차 창 유의성 미달로 완전한 Go는
  아니다. SPPV-3 착수는 계속 보류, 다음 과제(`fast_score_v2` shadow
  검증 등)를 구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (8차, §17.5 후속 3과제 — SPPV-2.10)
- 수정내용: §17.5가 지시한 후속 3과제를 실행했다(SPPV-2.10 신설).
  `fast_score_v2`(rsi_signal 제거/부호반전) shadow 2종 모두 No-Go —
  하락장 T+5 spread가 원안(t_NW=-2.79)과 거의 동일하게 역전(drop -2.41/
  flip -2.32) — `rsi_signal`이 부분 원인일 뿐이었음을 재확인. `risk_
  adj_momentum_3m`은 1차 창을 18개월로 넓히자 T+20 t_NW=2.03으로 §16
  게이트를 겨우 통과 — Watch 유지, 조건부 상향. `reversal_1m`은 하락장
  반분(전/후반부) 검증에서 개별 유의 미달로 Hold 유지. SPPV-3 착수는
  계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (9차, §18.6 후속 — SPPV-2.11)
- 수정내용: §18.6이 지시한 세 과제를 실행했다(SPPV-2.11 신설). `fast_
  score` leave-one-out 4종 분해 결과 `fast_trend` 제거 시 하락장 T+5
  spread가 -2.79→-1.60으로 가장 크게 개선 — `rsi_signal`이 아니라
  `fast_trend`가 주된 원인이었음을 정정. `risk_adj_momentum_3m`은
  15~21개월 창에서 안정적 plateau(우연 아님, marginal). 국면 전환형
  shadow 후보 `regime_switch_v1`을 신설해 2차(3년) pooled 트랙 최고
  수치(T+5=2.60/T+20=2.36)를 확인했으나 1차는 하락장 표본 부재로 미달 —
  가장 유망한 Watch 후보로 격상, 확정 Go는 아니다. `fast_score`는 전면
  재설계 대상으로 확정. SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (10차, §19.6 후속 — SPPV-2.12)
- 수정내용: §19.6이 지시한 두 과제를 실행했다(SPPV-2.12 신설). `regime_
  switch_v1`의 1차 게이트 예외 규칙 3개(A 관찰 유예/B 최근-실사례
  고정창/C 적응형 최소 국면 표본 창)를 비교 — 규칙 C가 n=30에서
  t_NW=4.18로 급등하지만 n=48(규칙 B)에서는 1.33에 불과해 데이터
  스누핑으로 판정, 채택 거부. 규칙 A(관찰 유예)를 유일하게 채택. fast
  계열 신규 feature 2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`)도
  범용 대체 후보로 No-Go. SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (11차, §20.5 후속 — SPPV-2.13/2.14)
- 수정내용: §20.5가 지시한 두 과제를 실행했다(SPPV-2.13/2.14 신설).
  `regime_switch_v1`의 규칙 A(관찰 유예)를 실행 가능한 모니터링
  스크립트로 구현(벤치마크 1종목만 조회, 신규 KIS 호출 0건) — 실행
  결과 현재 NOT_TRIGGERED(bearish_trend 0일). "절대 가격 수준" 미의존
  완전 신규 fast 계열 feature 2종(`money_flow_5d`, `relative_
  strength_rank_1m`)을 실측 — 둘 다 범용 대체 후보로 No-Go.
  `relative_strength_rank_1m`은 하락장에서 유의하게 역전(t=-2.13) —
  시장 베타 제거 상대강도조차 하락장에서 반대로 작동한다는 규칙성
  재확인. SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-15 (12차, 국면별 신호 극성 종합 및 상위 방향 확정)
- 수정내용: SPPV-2.9~2.14의 10개 신호를 종합표로 통합(신규 문서
  `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`)
  — 8/10이 "추세형=상승/횡보 전용, 되돌림형=하락장 전용" 규칙성을
  따름(`rsi_signal`만 상승장 역전 예외). feature 추가 실험을 중단하고
  **국면 분기형 entry 설계 검토로 전환**을 확정, 유니버스/미시구조
  재검토는 후순위 유지. SPPV-3의 다음 착수 형태를 `regime_switch_v1`
  아이디어 기반 entry 설계 원형으로 재정의했다.

- 작성자: Claude
- 수정일자: 2026-07-15 (13차, 국면 분기형 entry 설계 초안 + shadow 계산기)
- 수정내용: 12차 판정을 실제 설계 문서(신규
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md`)로
  구체화했다 — 국면별 신호 선택 매트릭스, `entry_score` alpha layer
  교체 제안(미적용), shadow 검증 Phase 1/2 계획. shadow 계산기 실행
  (2026-07-14 기준) — 시장 공통 국면 `range_bound`로 87/87종목이
  `risk_adj_momentum_3m` 분기 사용, 하락장 분기는 미발동(§21 모니터링과
  정합). `entry_score` 코드/운영 변경 없음 — 설계·shadow 단계 유지.

---

## 관리 원칙

1. **Backlog 항목이 실제 실행으로 전환될 때**: [BACKLOG] backlog.md에서 해당 항목을 `[x]`로 표시하고, 새 numbered plan을 생성한다. [BACKLOG] backlog.md에는 짧게 상태 업데이트 (예: `→ Plan 41로 승격`).
2. **새로운 아이디어는 항상 BACKLOG 우선**: numbered plan에 바로 포함하지 않는다. 일단 BACKLOG에 기록하고, 실행 시점에 평가 후 승격.
3. **정기적 검토**: Plan 완료 시 BACKLOG를 검토하여 다음 우선순위를 결정한다.
4. **기존 numbered plan 문서는 건드리지 않는다**: [BACKLOG] backlog.md가 future work의 단일 진실 공급원(single source of truth).

## 최근 추가 상세 백로그

- **KIS 토큰 캐시 통합(appkey당 1개)** (2026-07-13 신설, 신규 트랙 — universe
  sourcing과 무관):
  - **배경**: `.cache/kis_disclosure_token.json` 조사 중, 같은
    `KIS_LIVE_INFO_APP_KEY`가 서로 다른 3개 캐시 파일로 쪼개져 있음을
    발견 — `kis_live_oauth_token.json`(076 holiday client),
    `kis_disclosure_token.json`(공시 클라이언트 + market_overlay 라이브
    시세 클라이언트가 공유), `kis_live_token.json`(설정만 있고 163 WS
    제거 이후 사실상 미사용). 각 캐시가 서로 다른 파일만 보고 다른 파일의
    유효 토큰 존재 여부를 확인하지 않아, cold start 시 같은 appkey로
    `oauth2/tokenP`가 중복 발급될 위험이 있다(`EGW00133`: 1분당 1회 제한
    — 이 저장소에 실제 발생 이력 다수).
  - **정책 확정(사용자, 2026-07-13)**:
    1. 트레이딩 계좌(`KIS_APP_KEY`/`KIS_ENV`) 관련 live 환경은 기본
       비활성화 유지 — 계좌 관련은 전부 `KIS_ENV=paper` 기준.
    2. 정보성(시세/공시) 목적의 `KIS_LIVE_INFO_*`는 live에서 계속
       활성화하여 사용.
    3. **하나의 appkey에는 하나의 토큰 캐시 파일만 사용**한다 — 이 원칙이
       `KIS_LIVE_INFO_*` 계열(076 holiday + 공시/시세)에서 지켜지도록
       통합.
  - **관련 문서 갱신 완료**: `plans/kis_dev_token_cache.md`(상단 banner +
    §2/§7 표 수정), `plans/kis_oauth_cache_centralization_2026-05-17.md`
    (상단 banner — "구현 중앙화"와 "파일 통합"은 다른 것이었음을 명시),
    `plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`
    (§후속 액션에 관련 실측 링크 추가).
  - **구현 완료(2026-07-13)**:
    - `holiday_client.py`의 `KISHolidayClient.__init__`에
      `share_rest_access_token_cache: bool = False` 옵션 추가 — `True`일 때
      holiday 전용 fingerprint/purpose(`build_holiday_oauth_cache_config`)
      대신 disclosure/시세 client와 동일한
      `build_rest_access_token_cache_config(cache_purpose=
      CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN, api_key=app_key, kis_env=
      "live", base_url=...)`를 사용하게 했다 — cache_purpose와 fingerprint가
      완전히 동일해야 `KisTokenCache.load()`가 "다른 파일처럼" 취급하지
      않고 진짜로 캐시를 공유한다(단순히 cache_path만 맞추는 걸로는
      부족했음 — `purpose_mismatch`로 매번 miss 처리됨).
    - `market_session.py`의 `create_session_provider()`가
      `KIS_DISCLOSURE_TOKEN_CACHE_ENABLED`/`KIS_DISCLOSURE_TOKEN_CACHE_PATH`
      (기본 `kis_disclosure_token.json`)를 쓰도록 변경, `share_rest_access_
      token_cache=True` 전달. 기존 076 전용 파일(`kis_live_oauth_token.json`)
      은 더 이상 생성/참조되지 않는다.
    - `run_ops_scheduler.py`의 `_build_token_cache_health_summary()` 진단
      summary도 `holiday_oauth` 항목이 `live_disclosure_access_token`과
      동일한 캐시를 참조하도록 갱신(더 이상 사용하지 않는
      `build_holiday_oauth_cache_config` import 제거).
    - `.env.example`에 `KIS_DISCLOSURE_TOKEN_CACHE_ENABLED`/`_PATH` 신규
      문서화 + `KIS_LIVE_TOKEN_CACHE_PATH`가 이제 WS approval-key 전용임을
      명시.
    - (WS approval-key 캐시(`KisMarketStateClient`, `CachePurpose.
      LIVE_APPROVAL_KEY`)는 REST access token과 다른 종류의 자원이라 이번
      통합 범위에서 제외 — 그대로 유지.)
  - **검증 완료(2026-07-13)**: 캐시 파일 삭제 후 cold start 재현 —
    076 client가 `oauth2/tokenP`로 토큰 발급 후 `kis_disclosure_token.json`
    에 저장 → 곧바로 disclosure client를 별도로 기동해도 **같은 파일에서
    캐시 hit**(추가 토큰 발급 없음) 확인
    (`logs/token_cache_unification_verify_2026-07-13.log`). 관련 테스트
    242건(holiday_client/market_session/run_ops_scheduler/token_cache)
    전체 통과, 회귀 없음.

- **BUY 주문 0건 근본 복구 — 신호 예측력·`entry_score`·전체 주문 funnel 재설계**
  (2026-07-14 신설, 최우선):
  [`plans/[DESIGN] signal_predictive_power_validation.md`](./%5BDESIGN%5D%20signal_predictive_power_validation.md)
  - 목표: 손실 0이 아니라 VaR/drawdown/exposure/liquidity 한도 안에서 비용 차감
    기대수익을 최대화한다. risk/compliance는 목적함수가 아니라 제약조건이다.
  - 운영 기준선: `2026-06-25` 이후 `symbol + trade_date` 첫 decision 297건 중
    `entry_score >= 0.65=0`, `BUY_CANDIDATE=0`, eligibility 통과 21건,
    `risk_off_penalty=294`, BUY 주문요청/submit 0건. 직접 병목은
    `entry_score < 0.65`다.
  - **SPPV-1(파일럿 완료, 결론 보류)**: core 8종목 pooled IC로
    `slow_momentum`/`overall_score`의 예측 가능성 가설을 확보했다. overlap과
    군집 의존성 보정 전이므로 통계적 입증으로 확정하지 않는다.
  - **SPPV-2(완료, 2026-07-14)**: core 88종목 전체 × 거래일별 cross-sectional
    Spearman IC × ICIR × Newey-West 보정 × 국면별 분해 × 비용 차감 quintile
    성과(T+1/T+3/T+5/T+10/T+20)를 산출했다. **결과: SPPV-1의 t=2.4~4.1
    ("유의미"~"강함")은 overlap 편향의 산물이었음이 확인됨 — 정확 보정 시
    전 신호·전 horizon |t_NW|<1.1로 통계적 유의성 없음.** 단
    `overall_score` quintile spread(+3.88%p, T+20)는 방향성 있게 잔존해
    "완전 무신호"로 단정하지 않는다. 하락장(bearish_trend)에서는
    overall/fast_score IC가 음(-)으로 역전 — 현재 risk_off 방어가 근거
    없는 게 아니라는 정황도 함께 확인됨. 산출:
    `scripts/validate_signal_predictive_power_v2.py`(read-only),
    `logs/signal_ic_sppv2_expanded_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §9.
    point-in-time universe(당시 편입·편출 종목)와 시장·업종 대비 초과수익은
    이번 턴에 시도하지 못해 한계로 남김(§9.5).
  - **SPPV-2.5(완료, 2026-07-14) — ⚠️ 방법론 오류로 결론 폐기**: quintile
    spread 자체의 Newey-West 유의성 검정 + 국면 내부(within-regime) 분해
    시도. ~~결과: pooled spread(T+20, t_NW=2.30)는 유의하나 국면 내부
    어디서도 재현되지 않음 — 국면 혼입 착시~~ **→ 오류(사용자 지적):
    `regime_label`이 시장이 아니라 그 종목 자신의 신호(slow_score/
    return_3m 등)로 판정되는 라벨이었다(`market_regime.py:21-38`) —
    검정 대상(`overall_score`)과 같은 계열 변수로 표본을 조건화한 선택
    편향. SPPV-2.6에서 정정.** 산출:
    `scripts/validate_signal_predictive_power_v2_5.py`(read-only),
    `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §11(이력 보존).
  - **SPPV-2.6(완료, 2026-07-14, 방법론 교정) — ⚠️ SPPV-2.7에서 표현
    하향 조정**: KODEX 200(`069500`, 이미 core universe 구성원)을 시장
    벤치마크로 써서 거래일 단위 공통 국면 + 초과수익으로 재검증.
    ~~결과: "국면 혼입 착시" 결론은 반박되고 알파 근거는 오히려 강화됐다.~~
    **→ 벤치마크를 평가 universe에도 포함시킨 자기참조 문제와 1년(하락장
    0일) 표본 한계가 있었다. 아래 SPPV-2.7에서 교정.** 산출:
    `scripts/validate_signal_predictive_power_v3_market_regime.py`,
    `logs/signal_ic_sppv_market_regime_correction_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §12(이력).
  - **SPPV-2.7(완료, 2026-07-14, 자기참조 제거 + 3년 확장)**: 평가
    universe에서 벤치마크 심볼을 제외(core 87종목)하고 조회 기간을
    1년→**3년**(종목당 일봉 733개)으로 확장 — 시장 공통 국면 기준 실제
    하락장 표본(96거래일, 15%)을 처음으로 확보했다. **결과: `overall_score`
    pooled spread 유의성이 소멸(t_NW 2.30→1.32)했고, 하락장 내부에서는
    spread가 음수로 역전(T+5 t_NW=-1.71, T+20 t_NW=-0.14)하거나
    `fast_score`는 하락장에서 통계적으로 유의하게 역방향(T+5 t_NW=-2.79)
    이었다. 어떤 국면 내부도 |t_NW|≥2를 넘지 못했다(유일한 유의는
    fast_score의 역방향 하락장 신호뿐).** SPPV-2.6의 "알파 근거 강화"
    결론은 과도했음이 확인돼 하향 조정한다 — 안정적인 종목 선택 알파를
    찾지 못했다. 산출:
    `scripts/validate_signal_predictive_power_v4_extended_period.py`
    (read-only), `logs/signal_ic_sppv2_7_extended_period_2026-07-14.json`,
    `logs/_bars_cache_core87_3y_2026-07-14/`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §14(최신
    canonical 결론).
  - **SPPV-2.8(완료, 2026-07-14, 검증 기간 기준 재설계)**: 이 시스템이
    3개월 이하 중단기 공격형이라는 전제로 검증 기간 기준을 재설계했다 —
    3년 pooled 기본값 대신 **최근 12개월(1차, primary)과 3년(2차,
    supplementary 국면 게이트)**을 분리했다. 국면(특히 하락장) 최소
    표본(30거래일) 미달 시 1차만으로 판정하지 않고 2차(장기)를 반드시
    함께 참고한다. 기존 3년 캐시를 재사용해(신규 KIS 호출 0건) 최근
    12개월(2025-06-16~2026-07-14, 245거래일)을 실측한 결과 **하락장
    거래일 0일** — 최근성 창만으로는 필수 국면 게이트를 통과할 수 없음을
    실증했고, 1차 pooled 유의성도 미확보(`overall_score` T+20
    t_NW=1.18). §14의 보류 판정은 변경하지 않으며, 향후 재검증은 이
    이원 기준을 따른다. 산출:
    `scripts/validate_signal_predictive_power_v5_recency_window.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_sppv_recency_window_primary_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §16.
    **실행 증빙 재검증(2026-07-14, 6차)**: 최초 로그가 실패 트레이스
    (호스트 `dotenv` 미설치)였음을 발견해 컨테이너에서 재실행 — 종료
    코드 0/KIS 호출 0건/bearish_trend 0일/t_NW=1.18 전부 재현. §16.6.
  - **SPPV-2.9(완료, 2026-07-14, 신호 feature 재설계 검토)**: `fast_
    score`/`slow_score`의 6개 sub-component(`slow_momentum`/`slow_
    trend`/`fast_trend`/`volume_confirmation`/`rsi_signal`/`volatility_
    penalty`)를 운영 코드 그대로 분해 실측 + 신규 후보 feature 2개
    (`risk_adj_momentum_3m`=변동성 조정 모멘텀, `reversal_1m`=단기
    역추세)를 §16 이원 기준으로 검증(3년 캐시 재사용, 신규 KIS 호출
    0건). **결과: `rsi_signal`이 T+20에서 유의하게 역방향(1차
    t_NW=-2.94, bullish_trend 내부 -2.79) — `fast_score` 실패 원인
    특정.** `risk_adj_momentum_3m`은 2차(3년) pooled 유의(t_NW=2.07) +
    하락장 역전 없음(t_NW=0.39)으로 유일한 Watch 후보이나 1차(최근
    12개월) 유의성(t_NW=1.47)이 §16 게이트 미달로 완전한 Go는 아니다.
    `reversal_1m`은 하락장에서만 유의(T+5 t_NW=2.13)해 국면 조건부
    후보로 분리 검토가 필요하다. SPPV-3 착수는 계속 보류, 다음 과제로
    `rsi_signal` 제거/반전한 `fast_score_v2` shadow 검증과 `risk_adj_
    momentum_3m` 재검증을 확정했다. 산출:
    `scripts/validate_signal_predictive_power_v6_feature_redesign.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_sppv2_9_feature_redesign_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §17.
  - **SPPV-2.10(완료, 2026-07-14, §17.5 후속 3과제)**: `fast_score_v2`
    (rsi_signal 제거/부호반전) shadow 2종 + `risk_adj_momentum_3m` 1차
    창 18개월 확장 + `reversal_1m` 하락장 반분 안정성을 실측(3년 캐시
    재사용, 신규 KIS 호출 0건). **결과: `fast_score_v2` 2종 모두
    No-Go** — 하락장 T+5 spread가 원안(t_NW=-2.79)과 거의 동일하게
    역전(drop -2.41, flip -2.32) — `rsi_signal`은 부분 원인일 뿐 주된
    원인이 아니었음을 재확인, §17의 낙관적 프레이밍을 하향 조정한다.
    `risk_adj_momentum_3m`은 18개월 창에서 T+20 t_NW=1.47→**2.03**으로
    §16 게이트를 겨우 통과했으나 T+5(1.97)는 여전히 미달인 marginal
    결과 — "Watch 유지, 조건부 상향". `reversal_1m`은 하락장 96거래일을
    반분(전/후반부 48일씩)해 안정성 확인 — 방향은 일관되나(전반 1.87/
    후반 1.33) 개별 유의 문턱 미달 — Hold 유지. SPPV-3 착수는 계속
    보류. 산출: `scripts/validate_signal_predictive_power_v7_followup.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_sppv2_10_followup_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §18.
  - **SPPV-2.11(완료, 2026-07-14, §18.6 후속)**: `fast_score`
    leave-one-out 4종(fast_trend/volume_confirmation/rsi_signal/
    volatility_penalty 각각 제거) + `risk_adj_momentum_3m` 창 경계
    민감도(12/15/18/21개월) + 국면 전환형 shadow `regime_switch_v1`
    (비하락장=risk_adj_momentum_3m, 하락장=reversal_1m)을 실측(3년
    캐시 재사용, 신규 KIS 호출 0건). **결과: `fast_trend` 제거 시
    하락장 T+5 spread가 -2.79→-1.60(비유의 전환)으로 가장 크게 개선 —
    §17/§18의 `rsi_signal` 원인 지목을 정정, 실제 주된 원인은 `fast_
    trend`였다.** `risk_adj_momentum_3m`은 15~21개월 창에서 T+20
    t_NW 1.90→2.03→2.04로 안정적 plateau(우연 아님, 여전히 marginal).
    `regime_switch_v1`은 2차(3년) pooled T+5=2.60/T+20=2.36으로 트랙
    최고 수치를 냈으나 1차(최근 12개월)는 하락장 표본 부재로 미달 —
    가장 유망한 Watch 후보로 격상, 확정 Go는 아니다. `fast_score`는
    전면 재설계 대상으로 확정. SPPV-3 착수는 계속 보류. 산출:
    `scripts/validate_signal_predictive_power_v8_fast_score_teardown.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_sppv2_11_fast_score_teardown_2026-07-14.json`.
    상세: `plans/[DESIGN] signal_predictive_power_validation.md` §19.
  - **SPPV-2.12(완료, 2026-07-14, §19.6 후속)**: `regime_switch_v1`의
    1차 게이트 예외 규칙 3개(A 관찰 유예/B 최근-실사례 고정창(n=48)/
    C 적응형 최소 국면 표본 창(최소 30일)) + fast 계열 신규 feature
    2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`)을 실측(3년 캐시
    재사용, 신규 KIS 호출 0건). **결과: 규칙 C가 n=30에서
    t_NW=4.18로 급등하지만 n=48(규칙 B)에서는 1.33에 불과 — "문턱을
    넘을 때까지 창을 줄이는" 데이터 스누핑으로 판정, 채택 거부.** 규칙
    B는 정직한 재검증에서도 미달(1.33~1.61) — **규칙 A(관찰 유예)를
    유일하게 채택**한다. fast 계열 신규 feature 2종 모두 범용 대체
    후보로 No-Go — `rsi_mean_reversion`은 하락장 전용(t=2.26,
    `reversal_1m`과 동일 패턴), `sma5_over_sma20_gap`은 SMA20과 동일
    하게 하락장에서 유의하게 역전(t=-2.67). SPPV-3 착수는 계속 보류.
    산출: `scripts/validate_signal_predictive_power_v9_gate_and_fast_
    features.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_sppv2_12_gate_and_fast_features_2026-07-14.json`.
    상세: `plans/[DESIGN] signal_predictive_power_validation.md` §20.
  - **SPPV-2.13/2.14(완료, 2026-07-14, §20.5 후속)**: `regime_
    switch_v1` 규칙 A(관찰 유예)를 실행 가능한 모니터링 스크립트로
    구현(벤치마크 1종목만 조회, 신규 KIS 호출 0건) + 완전 신규 fast
    계열 feature 2종(`money_flow_5d`=자금 흐름 축, `relative_
    strength_rank_1m`=cross-sectional 상대강도 축)을 실측. **결과:
    모니터링 판정 NOT_TRIGGERED(bearish_trend 0일, §20과 일치).** fast
    계열 신규 feature 2종 모두 범용 대체 후보로 No-Go — `money_
    flow_5d`는 방향성조차 없는 완전 무신호(|t|<1.2), `relative_
    strength_rank_1m`은 하락장에서 유의하게 역전(t=-2.13) — 시장 베타
    제거 상대강도조차 하락장에서 반대로 작동한다는 규칙성 재확인.
    SPPV-3 착수는 계속 보류. 산출:
    `scripts/monitor_regime_switch_v1_gate.py`,
    `scripts/validate_signal_predictive_power_v10_new_fast_features.py`
    (둘 다 read-only, 신규 KIS 호출 0건),
    `logs/regime_switch_v1_gate_monitor_2026-07-14.json`,
    `logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json`. 상세:
    `plans/[DESIGN] signal_predictive_power_validation.md` §21, §22.
  - **SPPV-2.15(완료, 2026-07-15, 국면별 신호 극성 종합 및 상위 방향
    확정)**: SPPV-2.9~2.14의 10개 신호(`fast_score`, `fast_trend`,
    `sma5_over_sma20_gap`, `rsi_signal`, `rsi_mean_reversion`,
    `relative_strength_rank_1m`, `reversal_1m`, `money_flow_5d`,
    `risk_adj_momentum_3m`, `regime_switch_v1`)를 절대추세/오실레이터/
    자금흐름/상대강도/복합 5개 축으로 분류해 종합표로 정리했다(신규
    문서 `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
    direction.md`). **결과: 8/10이 "추세형=상승/횡보 전용, 되돌림형=
    하락장 전용" 규칙성을 따름(`rsi_signal`만 상승장 역전 예외), `fast_
    trend` 단독은 하락장 비유의(-0.79)이나 `fast_score`(합성)는 유의
    역전(-2.79) — 개별 성분보다 조합 효과가 큼.** 5개 축 모두 시도 후
    동일 결론 수렴 + `regime_switch_v1`이 정적 신호로는 얻지 못한 트랙
    최고 2차 유의성(T+5=2.60/T+20=2.36)을 국면 전환만으로 달성한 것을
    근거로 **feature 추가 실험을 중단하고 국면 분기형 entry 설계
    검토로 전환**을 확정했다. 유니버스/미시구조 재검토는 후순위 유지.
    상세: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
    direction.md`.
  - **SPPV-2.16(완료, 2026-07-15, 국면 분기형 entry 설계 초안 + shadow
    계산기)**: SPPV-2.15의 판정을 실제 설계 문서(신규
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md`)로
    구체화했다 — 국면별 신호 선택 매트릭스(비하락장=`risk_adj_
    momentum_3m`, 하락장=`reversal_1m`, 판정불가=신호 미산출),
    `entry_score` alpha layer(0.80 가중치 블록) 교체 제안(미적용),
    shadow 검증 Phase 1/2 계획. **결과: shadow 계산기
    (`scripts/shadow_regime_conditional_entry_signal.py`) 실행
    (2026-07-14 기준, 신규 KIS 호출 0건) — 시장 공통 국면
    `range_bound`로 87/87종목이 `risk_adj_momentum_3m` 분기 사용,
    하락장 분기는 미발동(§21 모니터링과 정합). `entry_score` 코드/
    운영 변경 없음.** 산출:
    `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`.
  - **SPPV-3(보류 유지, 형태 재정의)**: §2.16(SPPV-2.16)에서 국면
    분기형 entry 설계 초안이 마련됐다 — 다음 착수 형태는 이 설계 문서를
    기반으로 regime/allocation/strategy/source를 복원한 `entry_score`
    point-in-time 재현과 signal/risk-off/regime eligibility 중복 억제
    ablation이다. 착수 조건은 모니터링 스크립트가 `TRIGGERED`를
    반환하거나 shadow 설계를 추가 검증할지 — 사용자 확인 필요. 착수 시
    당시 regime/allocation/strategy/source를 복원해
    `entry_score`를 point-in-time 재현하고 signal 약세, `risk_off_
    penalty`, regime eligibility block의 중복 억제를 ablation한다.
  - **SPPV-4**: 각 shadow formula별 Virtual BUY를 만들고 `candidate → selected
    → expected value → would_buy → submitted` 전환, MFE/MAE/낙폭/비용 차감
    기대수익을 비교한다.
  - **SPPV-5**: out-of-sample 기대수익 양수와 사전 손실 제약을 충족한 공식만
    shadow 후보로 유지한다. 후보 증가나 WATCH 증가만으로 Go 판정하지 않는다.
  - **SPPV-6**: 별도 승인 후 일일 top-k, 최소 수량, 계좌 위험한도 아래 제한적
    paper probe로 승격한다. deterministic risk/compliance/guardrail과 broker
    submit 경계는 유지한다.

- **종목 소싱(Universe Sourcing) 구조 개선 — market_overlay 활성화 및 모멘텀 신호 보강** (2026-07-12 신설, 2026-07-14 기준 이력/차후 보류):
  [`plans/[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`](./%5BDESIGN%5D%20universe_sourcing_momentum_overlay_enablement_v1.md)
  - 2026-07-12 당시 확정: 매수 0건은 하락장 방어의 올바른 작동이었으므로
    **`core_risk_off` 완화·`entry_score` 조작 시도는 전면 영구 중단**한다.
    후속 방향은 게이트 완화가 아니라 소싱(후보 공급) 단계 복구였다. 이 결론은
    2026-07-14 근본 재검토와 DB funnel 실측으로 대체됐으며 현재는 이력이다.
  - 근본 원인: 모멘텀 포착 레이어(`_add_market_overlay`)가 `KIS_ENV=paper`
    이중 게이트로 6주 내내 완전 비활성 + core는 가격 무관·회전 없음 +
    지수 편입 데이터는 2026-06-24 수동 스냅샷으로 stale.
  - **2026-07-12 UNIV-1/2 실측 완료 — 원안 정정**: 라이브 read-only client
    주입 배선은 이미 존재·정상 동작(신규 배선 불필요, `env=paper` 가설은
    틀렸음). 실제 원인은 intraday freeze materialize 시각(`08:50`, 장 시작
    09:00 전)과 F5 누적거래대금 필터의 경합 — 08:50에 freeze되면 당일
    누적거래대금이 0이라 market_overlay 후보 전원이 탈락(`added_count=0`).
    07-03처럼 freeze가 09:00 이후 materialize된 날은 정상 동작(5건 편입)
    확인. 관련 3개 silent debug 로그를 warning으로 격상 + 회귀 테스트 3건
    추가 완료. 상세: `[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`
    §2.1-정정, `logs/univ1_*_2026-07-12.log`.
  - **2026-07-12 UNIV-1-fix 범위 조사 완료**: freeze 시각(08:50) 이동은
    8개+ 다른 문서에 하드코딩된 경계라 blast radius 과다로 부적합, F5
    threshold 단순 완화는 금지 원칙 위배 → **전일 거래대금 fallback 방식을
    채택하되 독립 구현 대신 UNIV-3(일봉 데이터 재사용)에 통합**하기로 결정.
    상세: `[DESIGN]` 문서 §2.1-fix, `logs/univ1_fix_scope_investigation_2026-07-12.log`.
  - 백로그: UNIV-1(완료) → UNIV-2(완료) → UNIV-3(1순위, 부분 완료
    2026-07-12) → **UNIV-4(2순위, 부분 완료 2026-07-12)** → UNIV-5(core
    후순위화, 보류).
  - **2026-07-12 UNIV-3 shadow 신호 구현 완료(F5 fallback + 멀티데이
    모멘텀)**: (1) F5(low_volume) 전량 탈락 시 전일 종가×거래량 추정
    거래대금으로 "F5를 통과했을 후보"를 관측(`_evaluate_f5_shadow_fallback`).
    (2) market_overlay가 실제 선정한 top_n에 한해 상대 거래량 급증/5·20일
    수익률/반등 플래그를 `MomentumShadowSignal`로 관측
    (`_evaluate_multiday_momentum_shadow`, `_calc_momentum_shadow_signal`).
    둘 다 **선정/스코어링에 미반영**(shadow-first). 라이브 재검증 중
    `get_daily_price()`가 실제로는(raw `KISRestClient`) dict(`stck_clpr`/
    `acml_vol`)를 반환하는데 객체 속성(`.close`/`.volume`)으로 잘못
    가정했던 버그를 발견·수정(`_extract_bar_close`/`_extract_bar_volume`
    헬퍼로 dict/객체 이중 지원). 테스트 5건 추가, 전체 106건 통과.
    다음 단계는 코드 구현이 아니라 **수일 관측 후 승격 판단**.
  - **2026-07-12 UNIV-4 staleness 감시 구현 완료**: KIS에 지수 구성종목
    (전체 종목 리스트) API가 없음을 코드 조사로 확인(`rest_client.py`에는
    업종 시세 API만 존재) → 자동 갱신 원안 대신 read-only staleness 감시만
    구현. `InstrumentIndexMembershipRepository.get_latest_effective_from()`
    (Postgres+in-memory) + `services/index_membership_staleness.py`
    (`evaluate_index_membership_staleness()`, 21일 임계값). 실측
    (`scripts/check_index_membership_staleness.py`): 마지막 반영
    2026-06-27, age=15일 → 정상(6일 여유). 테스트 7건 추가. **운영 대시보드
    노출까지 완료(2026-07-12)** — `GET /instruments/index-membership/
    staleness` read-only 엔드포인트 + `OperationsDashboardView` WarningBanner
    연결(`is_stale=true`일 때만 노출). API 테스트 3건 추가, 프론트엔드
    타입체크/`dashboard.test.tsx` 16건 통과. **UNIV-4 완료.**

- `core_risk_off` / `slow_score_v5` shadow 완화 후속 작업 — **⚠️ 2026-07-12
  전면 영구 중단** (관측 데이터/이력 문서로만 유지):
  [`plans/[BACKLOG] core_risk_off_slow_floor_shadow_relaxation.md`](./%5BBACKLOG%5D%20core_risk_off_slow_floor_shadow_relaxation.md)
  - ~~`overall_missing` 보정 이후 실측 결과를 기준으로
    `slow_trend` 경계 구간만 shadow 완화 후보로 먼저 분리하고,
    `slow_momentum`은 관측 유지 후 판단하는 후속 작업 정리본이다.~~
  - 2026-07-12 사용자 확정: 매수 0건은 시스템 오류가 아니라 하락장 자본 방어의
    올바른 작동이었음이 증명됨(SF1~SF12 역-시뮬레이션 전부 No-Go/Shadow-Watch).
    따라서 이 백로그의 완화 작업은 전면 영구 중단하고, 후속 방향은 위
    "종목 소싱 구조 개선"으로 이관한다.

---

## 14-Agent 설계 vs 현재 구현/Backlog 정리

이 섹션은 `plan_docs/agents/`의 14-agent 책임 분해와 실제 구현/Backlog 분해 단위를 맞춰 보기 위한 보정표다.

- **중요**: 14개 `Agent`는 모두 provider LLM agent 구현 대상이 아니다.
- 현재 v1에서 **실제 런타임 AI core**로 연결된 것은 `Event Interpretation`, `AI Risk`, `Final Decision Composer` 3개다.
- 나머지 상당수는 설계상 `deterministic service/engine/worker` 또는 `hybrid`가 목표 형태이며, 일부는 이미 기능 축 기준으로 부분 구현돼 있다.
- 따라서 아래 표의 목적은 “왜 14개가 BACKLOG에 agent 이름 그대로 안 보이는가”를 설명하고, 아직 **별도 backlog 작업으로 재분해되지 않은 축**을 표시하는 것이다.

| Agent 책임 | 목표 형태 | 현재 상태 | 현재 구현/Backlog 앵커 | Backlog 분해 상태 |
|---|---|---|---|---|
| Data Collector Agent | Deterministic worker + adapter | 부분 구현 | KIS REST/WS, polling worker, source adapter, snapshot/event sync loop | 기존 backlog/plan에 기능 축으로 반영됨 |
| Data Quality Agent | Deterministic validator/service | 부분 구현 | freshness guard, stale snapshot guard, sync health, dedup, gap handling | 기존 backlog/plan에 기능 축으로 반영됨 |
| Market Regime Agent | Hybrid | 구현 완료 | deterministic regime backbone + decision pipeline 입력 반영 완료 | backlog는 후속 고도화만 유지 |
| Universe Selection Agent | Deterministic ranking/filter + optional AI | 부분 구현 | universe freeze, source_type 합성, liquidity filter, market/event overlay 일부 구현 | backlog는 실측/고도화 중심으로 유지 |
| Strategy Selection Agent | Hybrid policy service | 구현 완료 | deterministic strategy selection과 prompt/read-only projection 반영 완료 | backlog는 후속 고도화만 유지 |
| Signal Agent | Deterministic scoring engine | 부분 구현 | signal_backbone, signal_feature_snapshot, deterministic_trigger, expected_value_gate 반영 완료 | backlog는 후보화/계측/고도화 중심으로 유지 |
| News/RAG Agent | Provider AI + retrieval/event pipeline hybrid | 부분 구현 | `EventInterpretationAgent`, OpenDART adapter, external event pipeline | 일부 반영됨, 전용 backlog로는 미분해 |
| Portfolio Agent | Deterministic portfolio construction | 구현 완료 | portfolio_allocation deterministic 계층과 sizing 연계 반영 완료 | backlog는 고도화만 유지 |
| Order Construction Agent | Deterministic order-construction service | 미구현 | 현재는 FDC + sizing/order translation에 임시 흡수 | **별도 backlog 재분해 필요** |
| AI Risk Manager Agent | Provider AI + deterministic hard-limit 후단 | 구현 완료 | `services/ai_agents/ai_risk.py`, `decision_orchestrator.py` | 구현됨 |
| AI Compliance Agent | Hybrid policy/compliance + hard validator | 구현 완료 | `AI Compliance` + `compliance_validator_v1` 분리 및 inspection 반영 완료 | backlog는 모니터링/고도화만 유지 |
| Execution Agent | Deterministic execution pipeline | 부분 구현 | `order_manager.py`, broker adapter, reconciliation, post-submit sync | 기존 backlog/plan에 기능 축으로 반영됨 |
| Performance Agent | Deterministic analytics + optional AI commentary | 부분 구현 | performance summary/history/metrics/benchmark/gate/exit/live-readiness | 기능 축으로는 상당 부분 구현, “agent” 단위 backlog는 미분해 |
| Model Monitor Agent | Deterministic monitoring + offline analysis | 미구현 | provider failover/quality hardening 일부만 인접 구현 | **현재 핵심 미구현 축** |

### 현재 해석 규칙

1. **EI / AR / FDC는 v1 실전 코어**다. 나머지 agent 역할 일부는 아직 FDC나 deterministic backend에 임시 흡수돼 있다.
2. **Execution Agent는 AI agent가 아니다.** 주문 제출, 체결 추적, 정합성 수렴은 `OrderManager + BrokerAdapter + ReconciliationService` 중심 deterministic path로 유지한다.
3. **Backlog 누락처럼 보이는 이유는 작업 분해 단위 차이**다. 현재 BACKLOG는 agent 이름보다 `snapshot sync`, `paper gate`, `event ingestion`, `performance`, `submit/sync/reconcile` 같은 기능 축으로 정리돼 있다.
4. 현재 backlog에서 실제로 별도 추적이 더 필요한 축은 아래다.
   - Universe Selection Agent 고도화
   - Signal Agent 고도화
   - Model Monitor Agent

---

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Paper Trading Loop 연속 실행**: 주기적 orchestrator loop + fill sync + position/cash refresh. `run_paper_decision_loop.py` (300s 간격, CLI 옵션 6종, graceful shutdown). `verify_paper_loop.py --interval`은 assemble/submit만 반복; fill polling, position/cash 자동 갱신은 미포함 | Paper Trading Loop Validation | ✅ 승격됨 |
| 1b | **Event Ingestion Loop**: 외부 이벤트 수집을 독립 운영 데몬으로 승격. `scripts/run_event_ingestion_loop.py` + `_build_polling_workers()` 재사용. Source isolation + cycle summary. 60s 간격. ~14 tests | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | ✅ 승격됨 |
| 2 | **Replay-Style 검증 엔진 고도화**: 저장된 decision context 기반 결정론적 재현 검증 엔진. core replay engine (ReplayBundle + _build_repos + 5 scenarios + 2-run identity) 구현 완료. 전체 DB 기반 replay 경로는 후속 과제로 잔류 | Paper Trading Loop Validation | ✅ 승격됨 |
| 3 | **Snapshot Staleness Guardrail (Phase 5)**: submit 단계에서 position/cash snapshot freshness 검사. stale snapshot 시 RECONCILE_REQUIRED + status_reason_code="STALE_SNAPSHOT". `test_scenario_4_stale_snapshot_guard` 참조 | Paper Trading Loop Validation | ✅ 승격됨 |
| 4 | **Fill Sync / Post-Submit Update**: 주문 제출 후 broker로부터 fill 상태를 주기적으로 polling하는 루틴. `reconciliation_service.resolve_unknown_state()` 자동화 | Paper Trading Loop Validation | ✅ 승격됨 |
| 5 | **Plan 40 Phase 2 — API endpoints 확장**: `GET /orders/{id}/broker-orders`, `GET /accounts`, `GET /accounts/{id}`, `GET /clients/{id}`, `GET /instruments/{id}`, `GET /positions`, `GET /cash-balances`, `GET /guardrail-evaluations`, `GET /risk-limit-snapshots`, `GET /agent-runs` | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ 승격됨 |
| 6 | **Plan 40 Phase 2 — Postgres-backed API mode**: `create_app()`에 Postgres repository 주입 지원, `runtime_mode="postgres"` 모드 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ 승격됨 |
| 7 | **Reconciliation blocking lock list API**: `GET /reconciliation/locks` 구현을 위해 reconciliation repository에 `list_locks()` 메서드 추가. 현재 `is_blocked()`만 존재 | [Plan 40](plans/40_fastapi_inspection_api.md) | ✅ 승격됨 |
| 8 | **KIS real credential + combined submit smoke**: KIS 실제 API key 확보 후 `tests/smoke/test_kis_paper_smoke.py` 등 combined submit smoke 실행 | [Plan 36](plans/36_kis_paper_ai_runtime_smoke.md) | ❌ 미착수 |
| 8a | **장중 의사결정/주문 경로 운영 확인 우선**: 다음 실행 전에 먼저 현재 장중 경로가 실제로 정상 동작하는지 확인. 최소 확인 항목: ① `decision_submit_gate`가 `ok=True timeout=False`로 끝나는지 ② `agent_runs`에 실제 요약/근거가 채워지는지 ③ held position 종목에서 `reduce/exit sell` 판단이 실제로 나오는지 ④ 장중 미체결 주문이 조기 `expired`로 떨어지지 않는지 ⑤ 취소/정정 준비 경로가 실제 사용 가능한지. **시장가/시장성 지정가 전환 작업은 이 확인이 끝난 뒤 진행** | 2026-05-20 운영 점검 정리 | ❌ 미착수 |
| 8b | **현재가(`last`) 기반 지정가 제출 정책 교체**: 현재 `run_paper_decision_loop.py`가 `broker.get_quote(...).last`를 그대로 `OrderType.LIMIT` 가격으로 사용하고 있어 장중 체결 가능성을 떨어뜨릴 수 있음. 다음 단계로 ① 기본 제출 정책을 `시장가` 또는 `시장성 지정가`로 재설계하고 ② 신규 진입(BUY) / 축소·청산(REDUCE/EXIT/SELL) / 유동성 낮은 종목을 구분한 execution style 정책을 추가 검토. 또한 **submit budget 1건 정책은 왜곡 없이 단계적으로 완화**할 것. 완화 기준: ① 장중 `decision_submit_gate`가 안정적으로 `ok=True timeout=False` 유지 ② `agent_runs`가 fallback이 아닌 실제 출력으로 채워짐 ③ 주문 상태 동기화/`reconcile_required` 수렴/장중 `미체결→만료` 오표시가 안정화 ④ 취소/정정 경로 사용 가능 ⑤ 이후에도 최초 단계는 `held_position`의 `REDUCE/EXIT sell` 또는 `RECONCILE_REQUIRED`가 아닌 정상 제출 건에 한해 1→2건으로 제한적 확대 ⑥ 신규 진입(BUY) 다건 제출은 그 다음 단계로 분리. **우선순위는 8a 운영 확인 이후** | 2026-05-20 주문 제출 정책 점검 | ❌ 미착수 |
| 8c | **KIS 제출 주문의 장중 `미체결` → `만료` 오표시 수정**: KIS에 실제 제출된 주문 중 장중에는 `미체결`로 남아 있어야 하는 주문이 너무 이르게 `만료(EXPIRED)`로 전이되거나 화면에 `만료`로 보이는 문제를 우선 수정. 우선 검토 범위: ① 장중 세션 중 `EXPIRED` 조기 전이 차단 ② broker truth/fill truth 부재 시 `미체결` 유지 조건 정리 ③ 취소/정정 주문으로 이어질 수 있도록 open 상태 보존 ④ 주문 화면/주문추적 화면과 DB 상태 정합성 확인. **우선순위는 8b 이후** | 2026-05-20 미체결/만료 상태 정책 보정 메모 | ❌ 미착수 |
| 8d | **에이전트 판단근거 UI 가시성 강화**: 시장가/시장성 지정가 정책과 미체결/만료 상태 보정 다음 우선순위로, Admin UI와 inspection API에서 에이전트 판단근거를 요약뿐 아니라 더 풍부하게 볼 수 있도록 개선. 우선 검토 범위: ① `agent_runs.structured_output_json`의 핵심 필드(`summary`, `aggregate_view`, `events`, `risk_opinion`, `opposing_evidence`, `reason_codes`) 노출 ② EI는 top-level `summary` 외에 이벤트 해석 근거를 읽기 쉽게 표시 ③ `trade_decisions.rationale_summary`와 `agent_runs`를 함께 연결해 최종 결정 근거를 한 화면에서 추적 가능하게 구성. **우선순위는 8c 이후** | 2026-05-20 에이전트 판단근거 UI 개선 메모 | ❌ 미착수 |
| 8e | **Header 상태 텍스트/색상 정합성 확인**: Header 프레임 상단의 `API`, `DB` 상태 표시가 버튼/배지 색상만 바뀌고 텍스트는 여전히 `정상`, `연결됨`으로 고정되어 보이는 문제 점검. 우선 검토 범위: ① 실제 health/status 값과 표시 텍스트 매핑 확인 ② 오류 상태일 때 `비정상`, `연결 안됨` 등으로 문구도 함께 바뀌는지 확인 ③ 상태 색상, 아이콘, 텍스트가 동일한 소스 데이터를 보는지 점검 ④ Dashboard/Header 공통 상태 컴포넌트 사용 여부와 회귀 범위 확인. **우선순위는 8d 이후** | 2026-05-21 Header 상태 라벨 표시 점검 메모 | ❌ 미착수 |
| 9 | **Docs/OpenAPI 보호 옵션 (inspection API)**: `/docs`와 `/openapi.json`을 auth 보호 대상에 포함. 현재는 공개 유지 중 | Plan 47 | ✅ 진단 및 P0 수정 완료 — [`plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md`](plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md) 참고. 추가 개선은 universe/instrument master로 연결. |
| 10 | **Admin UI P1 — DecisionsView detail panel**: 특정 decision 행 클릭 시 TradeDecisionDetail 또는 DecisionContextDetail 내용을 inline panel 또는 modal로 표시. 현재는 단순 리스트만 존재 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 11 | **Admin UI P1 — AccountsView filter/selection 개선**: 계좌 목록 필터 (type, strategy) 및 선택 시 상세 영역 시각적 개선 | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | ❌ 미착수 |
| 12 | **Admin UI — Dashboard reconciliation metrics**: Dashboard에 정합성 점검 메트릭 (불일치 수, 마지막 실행 시각) 추가. 현재는 locks만 표시 | Plan 53 | ❌ 미착수 |
| 13 | **Admin UI — Dashboard/Accounts/Broker Capacity freshness visualization**: 데이터 신선도(freshness) 시각화. 각 데이터 소스별 마지막 업데이트 시각 표시 및 지연 경고 | Plan 53 | ❌ 미착수 |
| 13a | **운영/업무자용 주문 흐름 문서 패키지**: 모든 핵심 개발이 끝난 뒤, 현재 작성된 end-to-end 주문 흐름 문서를 바탕으로 아래 3종 문서를 추가 작성. ① **매수 경로만 따로 분리한 요약본** ② **매도/체결/재조회 경로만 따로 분리한 운영 매뉴얼** ③ **장애 대응 체크리스트 버전**. 목적은 비개발 업무자가 주문 실패/체결/재조회 흐름을 더 빠르게 이해하도록 돕는 것. **개발 완료 전에는 착수하지 않고 보류** | 2026-06-05 운영 문서 정리 요청 | ❌ 미착수 |
| 14 | **Position/Cash Refresh After Fill**: Fill 발생 후 position snapshot/cash balance snapshot 자동 갱신 경로. Snapshot sync loop와 decision pipeline 연결 | Paper Trading Loop Validation | ❌ 미착수 |
| 15 | **Paper PnL / Performance Summary**: 체결/포지션/현금 데이터 기반 성과 집계. `AccountPerformanceSummary` + `StrategyPerformanceSummary`. Realized/Unrealized/Total PnL. `GET /performance-summary` API. 18개 신규 테스트 | Paper Trading Loop Validation | ✅ 승격됨 |
| 16 | **Postgres BrokerOrderRepository.update() 구현**: 현재 InMemory 전용 `update()`를 Postgres에도 구현. `PostgresBrokerOrderRepository.update()`에 SQL UPDATE + `last_synced_at` 반영 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 17 | **Scheduler 기반 정기 Post-Submit Sync**: `OrderSyncService`를 주기적으로 실행하는 scheduler loop. 미체결/부분체결 주기적 polling으로 상태 최신성 유지 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 18 | **FillEvent에 broker_fill_id 필드 추가**: 현재 fill dedup이 `(timestamp, price, quantity)` tuple 기반. broker 고유 fill ID로 dedup 강화 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 19 | **WebSocket 기반 실시간 order event 수신**: polling → WS event 기반 post-submit update 전환. KIS WS order event channel 연동 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 20 | **Pipeline Phase 5.5 Post-Submit Sync 연동**: `assemble_and_submit()`에서 submit 직후 첫 1회 `OrderSyncService.sync_order_post_submit()` 호출. 실패 무시, timeout 5s | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 21 | **Snapshot refresh 직접 통합**: `OrderSyncService`가 FILLED terminal 감지 시 snapshot refresh callback 직접 호출. 현재는 optional callback으로 위임 | Fill Sync / Post-Submit Update | ✅ 승격됨 |
| 22 | **Paper PnL History / Trend**: 기간 필터 기반 일별 성과 시계열 조회. `DailyPerformancePoint` dataclass + `get_daily_history()` service method. `GET /performance-history` API. Per-fill PnL 계산. Snapshot 날짜 선택 로직. 15개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |
| 23 | **Paper Performance Metrics**: 기간 기반 성과 지표 추가. `PerformanceMetrics` dataclass(17 fields) + `_calc_equity_metrics()`/`_calc_win_loss_metrics()` pure helpers. Cumulative return/drawdown/win-rate/avg-win-avg-loss/profit-factor. `get_performance_metrics()` service method. `GET /performance-metrics` API. Per-order 기준 win/loss 정책. 10개 신규 테스트 | Paper Performance Summary | ✅ 승격됨 |
| 24 | **Paper Go/No-Go Gate**: 성과/안정성/운영 지표 기반 paper 운용 통과 여부 자동 판정. `PaperGateService` (8개 check) + `GET /paper-go-no-go` API. `PAPER_GATE_*` env 6개 threshold. `GateStatus`(PASS/WARN/FAIL) + `OverallStatus`(GO/HOLD/NO_GO). 7개 신규 테스트. | Paper Go/No-Go Gate | ✅ 승격됨 |
| 25 | **Paper Exit Criteria (3-Layer)**: Paper → Live Canary 전환 전 최종 합격 기준. Layer A (Auto, PaperGateService 8 checks + health/readyz 2 checks), Layer B (Semi-Auto, 5 checks), Layer C (Manual, 5 체크리스트). 최종 종합: A FAIL→FAIL(exit 2), A+B FAIL→HOLD(exit 1), A/B+C pending→HOLD(exit 1), all complete→PASS(exit 0). NOT_RUN/HOLD/FAIL/PASS 구분. [`scripts/evaluate_paper_exit.py`](scripts/evaluate_paper_exit.py) CLI 4개 출력 모드(text/json/manual-template). 8개 신규 테스트. | [paper_exit_criteria.md](plans/paper_exit_criteria.md) | ✅ 승격됨 |
| 26 | **Live Gate / Canary Readiness (Phase 3)**: Paper Exit 통과 후 Live 검토 자격 + 추가 보호 조건. `LiveGateEvaluator` (PaperExitEvaluator 재사용). Live-specific 8개 auto check (filled orders 10↑/drawdown 10%↓/excess return 0%p↑/win rate/reconcile failures/blocking locks/readyz/post-submit sync). 6개 manual checklist (credential/account masking/operator approval/paper log review/rate limit review/final decision). 5개 신규 env thresholds. Overall: BLOCKED/HOLD/READY. [`scripts/evaluate_live_gate.py`](scripts/evaluate_live_gate.py) CLI 4개 출력 모드(text/json/manual-template) + exit code 0/1/2. 10개 신규 테스트. | [live_gate_canary_readiness.md](plans/live_gate_canary_readiness.md) | ✅ 승격됨 |
| 27 | **Market Regime Agent 분해**: deterministic regime feature set + rule-based classifier + optional AI commentary. 우선 구현 범위는 변동성/추세/risk-on-off 3축 feature 정리, regime label contract 정의, decision pipeline 입력 연결, replay 가능한 pure helper 우선. 초기 목표는 provider agent 추가보다 deterministic backbone 구축. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md) | ✅ 구현 완료 — regime backbone과 decision pipeline read-path 반영 완료 |
| 28 | **Universe Selection Agent 분해**: 거래 가능 종목 풀 생성과 ranking/filter service. 유동성/슬리피지/시장/브로커 제약/이벤트 존재 여부를 기준으로 candidate universe를 만들고, paper/live 공통 contract로 orchestrator 입력에 주입. 초기 목표는 deterministic filter + ranking engine, optional AI commentary는 후순위.<br><br>**V1.1 반영 범위**:<br>① `instrument master`와 `trading universe`를 명시적으로 분리<br>② `core universe` + `held positions` + `event-driven overlay` + `market-driven (flow/volatility) overlay` 합성<br>③ `market-driven overlay`는 KIS 순위 분석 API(거래량 급증, 체결강도 상위, 신고가 근접 등) 기반 후보를 사용<br>④ overlay 편입 전 `Liquidity Filter` 적용 (호가 얇음, 저유동성, micro-cap, 이상체결 제외)<br>⑤ 최종 universe reason/source_type 기록 (`core`, `held_position`, `event_overlay`, `market_overlay`, `manual`)<br>⑥ `market-driven overlay` 편입 종목은 Fast Layer에서 우선 스코어링하도록 policy contract 정의<br>⑦ 최종 cap과 submit gate는 기존 예산/정합성 정책을 유지<br><br>**비즈니스 기준 문서**: [`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md) — instrument master와 trading universe 분리, core universe / operational eligibility / event-driven overlay / market-driven overlay / liquidity filter / daily cap / Fast Layer 우선 정책을 정의. 구현은 이 정책 문서를 authoritative business source로 사용한다. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md) | 진행중 — universe freeze, source composition, overlay/liquidity filter 구현 완료. 후속은 실측/튜닝 중심 |
| 29 | **Strategy Selection Agent 분해**: 현재 국면과 계좌 상태를 기준으로 허용 전략/실행 스타일을 고르는 hybrid policy service. 전략 registry, enable/disable gate, regime-aware selection contract, paper 성과 기반 감쇠/중지 기준을 포함. 현재 FDC에 임시 흡수된 “어떤 스타일로 진입할지” 책임을 별도 계층으로 분리. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md) | ✅ 구현 완료 — preferred_strategy / allowed_strategies / entry_style read-path 반영 완료 |
| 30 | **Signal Agent 분해**: 기술/수급/모멘텀/변동성 점수화 deterministic engine. feature registry + score aggregation + replay/backtest 친화적 pure helper 우선. Event/news 파생 factor는 News/RAG 입력과 결합하되, 최종 score는 수치 재현 가능한 backend가 authoritative source가 되도록 유지.<br><br>**Universe Policy V1.1 연결 포인트**:<br>① KIS 순위 분석 API 기반 `market-driven overlay` 후보의 거래량 급증, 체결강도, 신고가 근접, 가격/거래대금 돌파 신호를 feature set으로 반영<br>② Fast Layer score와 Slow Layer score를 구분해 `market-driven overlay` 종목의 초/분 단위 우선 평가를 지원<br>③ Liquidity Filter를 통과한 종목만 signal engine 입력 대상으로 허용<br>④ **향후 AI 판단 고도화용 가격기반 지표 배치 포함**: 최근 `n개월` 시세를 수집해 추세/모멘텀/변동성/거래량 계열 지표(예: 이동평균, 이격도, RSI, ATR, 변동성 percentile, 거래대금 변화율 등)를 수치화하여 PostgreSQL에 저장하고, 장 시작 전 deterministic input으로 decision pipeline/AI prompt에 주입할 수 있게 한다. 이 계산은 장중 실시간이 아니라 **새벽 배치 또는 장후 저녁 배치**로 수행해 토큰 사용과 장중 계산 부하를 줄인다. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [08_ai_decision_policy.md](../plan_docs/detailed_design/08_ai_decision_policy.md), [`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md) | 진행중 — signal_backbone, signal_feature_snapshot, deterministic_trigger, expected_value_gate까지 반영. 후속은 후보화/성과계측/추가 feature |
| 30a | **가격기반 판단지표 배치 파이프라인**: AI 판단 및 Signal Agent 고도화를 위해 최근 `n개월` 시세 이력을 기반으로 추세/모멘텀/변동성/거래량 지표를 정규화된 수치 테이블로 적재하는 배치 파이프라인. 우선 구현 범위는 ① 일봉/필요 시 분봉 기준의 시세 history 확보, ② 종목별 lookback window(`1M`, `3M`, `6M`, `12M`) 산출, ③ 이동평균/RSI/MACD/ATR/볼린저/수익률/최대낙폭/변동성/거래량 급증률 등 feature registry 설계, ④ PostgreSQL snapshot 테이블 또는 별도 feature store에 저장, ⑤ 새벽 또는 장후 배치로 계산, ⑥ 장 시작 전 decision loop가 이 수치를 read-only로 참조, ⑦ AI prompt에는 원시 시세 대신 압축된 수치 요약만 넣어 토큰 사용량을 줄이는 방향 정리.<br><br>**성공 기준**:<br>① 특정 종목에 대해 최근 `n개월` 기술지표 row가 DB에 누적 저장됨<br>② 장 시작 전 snapshot/decision 준비 단계에서 최신 feature snapshot을 읽을 수 있음<br>③ AI 판단 입력에서 “최근 시세 추이/기술지표”가 텍스트 설명이 아니라 구조화 수치로 재사용됨<br>④ 장중 재계산 없이도 morning decision quality 개선 실험이 가능함 | User request (2026-06-05), [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md) | 진행중 — signal_feature_snapshot 장후 배치와 feature 저장/read-path 구현 완료. 후속은 확장 feature와 계측 |
| 31 | **Portfolio Agent 분해**: 목표 비중, concentration budget, exposure budget, 계좌별 capital allocation을 담당하는 deterministic portfolio construction service. 현재 sizing/risk/decision 사이에 흩어진 배분 책임을 하나의 정책 계층으로 모으고, strategy-level target allocation과 account-level order budget을 분리한다. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md) | ✅ 구현 완료 — portfolio_allocation과 sizing 연결 완료 |
| 32 | **AI Compliance Agent 분해**: 정책 위반 가능성 해석(AI)과 hard validator(deterministic)를 분리한 hybrid compliance layer. 금지 종목/권한 불일치/필수 필드 누락/브로커 제약 위반은 deterministic 차단, ambiguous policy/event risk만 AI가 의견을 제공. paper/live 공통 pre-submit verification chain에 read-only 또는 blocking gate로 연결. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [08_ai_decision_policy.md](../plan_docs/detailed_design/08_ai_decision_policy.md) | ✅ 구현 완료 — 4-agent chain, inspection, disagreement 계측, runbook 반영 완료 |
| 33 | **Model Monitor Agent 분해**: provider drift, prompt drift, fallback rate, replay/live divergence, backtest-production 괴리 모니터링 service. 우선 구현 범위는 AI agent별 success/fallback/timeout/reason_code 집계, contract drift 알림, replay vs runtime 비교 보고서, model/provider별 품질 회귀 지표 수집. provider failover hardening과 연결되지만 별도 monitoring 관점의 backlog로 관리. | [01_agent_inventory_and_status.md](../plan_docs/agents/01_agent_inventory_and_status.md), [02_agent_target_shapes.md](../plan_docs/agents/02_agent_target_shapes.md), [ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN_V2.md) | ❌ 미착수 — 현재 남은 핵심 미구현 계층 |
| 34 | **KIS 토큰 캐시 공통 모듈화 및 중앙 재발급 경로 정리**: 현재 KIS 인증 캐시는 `KISRestClient`의 paper/dev access token file cache, `KISHolidayClient`의 live holiday OAuth cache, `KisMarketStateClient`의 live approval key cache로 분산되어 있으며 공통 모듈이 없다. 각 경로가 자체적으로 load/save/expiry/fingerprint를 구현하고 있어 cache format, 만료 처리, 재발급 규칙이 분기된다. 우선 구현 범위는 ① token/approval cache 공통 contract 정의, ② cache purpose(`paper_access_token`, `live_holiday_oauth`, `live_approval_key`) metadata 표준화, ③ load/save/expiry/fingerprint 검증 공통 helper 추출, ④ 각 백엔드 프로그램이 토큰 만료 시 개별 구현 대신 공통 모듈을 통해 refresh 하도록 정리, ⑤ 기존 dev/paper/live 회귀 테스트 보강. 이 작업은 향후 `KIS 종합 시장_공시(제목)` live-only seed client와 live token reuse, scheduler/snapshot/post-submit/reconciliation worker의 인증 일관성 확보를 위한 선행 기술부채로 관리한다. | [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py), [`src/agent_trading/brokers/koreainvestment/holiday_client.py`](../src/agent_trading/brokers/koreainvestment/holiday_client.py), [`src/agent_trading/brokers/koreainvestment/market_state_client.py`](../src/agent_trading/brokers/koreainvestment/market_state_client.py), [`src/agent_trading/services/market_session.py`](../src/agent_trading/services/market_session.py) | ❌ 미착수 |
| 35 | **OpenDART(T1) vs Seeded News(T3) 상호작용 심층 분석**: seeded news가 EI 품질을 개선하는 것은 확인됐지만, OpenDART 같은 authoritative source(T1)와 함께 들어갈 때 우선순위/상호작용/충돌 패턴은 아직 정량 분석이 부족하다. 우선 구현 범위는 ① 동일 종목에서 T1만 있는 경우 / T1+T3 함께 있는 경우 비교, ② EI `event_bias`, `event_conflict`, `reason_codes`, 최종 decision 변화 추적, ③ T3가 T1을 과도하게 덮는지 여부 점검, ④ source tier/정렬/labeling 정책의 적절성 재평가, ⑤ 필요 시 seeded news threshold 또는 prompt labeling 보강안 도출. 이 항목은 seeded news를 장기 운영 경로로 확정하기 전의 품질 검증 backlog로 관리한다. | [`plans/phase_p5_1_seeded_news_live_comparison_2026-05-17.md`](plans/phase_p5_1_seeded_news_live_comparison_2026-05-17.md), [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py), [`src/agent_trading/services/seeded_news_converter.py`](../src/agent_trading/services/seeded_news_converter.py) | ❌ 미착수 |
| 36 | **`test_market_state_client.py` pre-existing 실패 2건 수정**: `TestPaperEnv.test_paper_env_skips_connect`와 `TestPaperEnv.test_paper_env_mock_env_also_skips`가 `httpx.UnsupportedProtocol`로 실패한다. 토큰 캐시 중앙화 작업과는 무관한 기존 실패이지만, paper/mock 환경에서 `KisMarketStateClient`가 실제로 connection attempt를 우회하지 못하거나 base URL 정규화가 부족할 가능성을 시사한다. 우선 구현 범위는 ① 실패 재현 및 root cause 분리, ② paper/mock env에서 `connect()`가 네트워크 호출 없이 조기 skip 되는지 보장, ③ URL 초기화/validation 보강, ④ 해당 테스트 2건을 green 으로 복구, ⑤ 시장상태 클라이언트 회귀 없음 확인. | [`tests/brokers/koreainvestment/test_market_state_client.py`](../tests/brokers/koreainvestment/test_market_state_client.py), [`src/agent_trading/brokers/koreainvestment/market_state_client.py`](../src/agent_trading/brokers/koreainvestment/market_state_client.py) | ❌ 미착수 |
| 37 | **KIS WebSocket 기반 실시간 현재가 조회 운영 화면**: Admin UI "기본 운영" 메뉴 아래 신규 read-only 화면. 운영자가 선택한 종목의 실시간 현재가(체결가 `H0STCNT0`)/호가(`H0STASP0`, 둘 다 KRX 전용으로 통일)를 조회한다. **주문 제출, 자동매매 판단, universe 편입과는 완전히 분리된 조회 전용 기능**이며, 기존 항목 `#19`(WebSocket 기반 실시간 **order event** 수신 — 체결통보 `H0STCNI0` 기반 post-submit sync 자동화)와는 목적이 다르다: `#19`는 주문 체결 확인 자동화이고, 이 항목은 **시세(current price) 화면**이다. 세션/rate-limit 충돌을 피하기 위해 ~~기존 트레이딩 계좌(`KIS_APP_KEY`) 및 공시/163 전용 계좌(`KIS_LIVE_INFO_*`)와 **완전히 분리된 별도 Live 계좌·앱키**를 사용하며, 이 별도 계좌·앱키는 이미 발급/행정 처리가 완료된 상태다.~~ **[2026-07-08 당시 설계 — 2026-07-10 credential 통합 구현으로 대체됨]** 처음엔 신규 전용 계좌(`KIS_REALTIME_QUOTE_*`)를 썼으나, `ops-scheduler`의 163 WS 제거로 세션 충돌 우려가 해소되어 현재는 공시 계좌와 동일한 `KIS_LIVE_INFO_*`를 authoritative credential로 쓴다(트레이딩 계좌 `KIS_APP_KEY`와는 여전히 분리). 상세는 항목 `#37`(credential 통합 재검토) 참고. **2026-07-08 기준 Phase 1~3 구현 완료**, **2026-07-09 Phase 4(push relay) 구현 완료**, **2026-07-10 Step 4(REST Fallback 연동) 구현 완료**, **2026-07-10 credential 통합 구현 완료**: 문서/API contract/UI mock → 전용 KIS WebSocket-backed quote source → Admin UI polling 화면/딥링크/프레임 유지 UX(Phase 1~3) → SSE 기반 push relay(`QuoteBroadcaster` fan-out, 전송 실패 시 REST polling degraded fallback, Phase 4) → KIS WS 연결 자체가 끊기거나 재연결 중일 때 REST 현재가 조회로 snapshot을 보정하는 quote source fallback(Step 4, Phase 4의 "SSE 전송 실패 시 REST polling"과는 별개 항목) → credential을 `KIS_LIVE_INFO_*`로 통합(신규 전용 계좌 폐기, `KIS_REALTIME_QUOTE_*`는 deprecated fallback)까지 반영 완료. `data_source`가 실제로 `"rest_fallback"`을 값으로 가질 수 있다(종목별 10초 쿨다운, WS 회복 시 자동 복귀). | [`plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`](../plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md), [`plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md`](./[DESIGN]_kis_realtime_quote_operations_screen_plan.md), User request (2026-07-08, 2026-07-09, 2026-07-10) | ✅ Phase 1~4 + Step 4(REST Fallback) + credential 통합(KIS_LIVE_INFO_* 기준) 완료 |

| 37 | **KIS 실시간 현재가 credential/appkey 통합 재검토 (Phase 4 후단)** — ✅ **[현재 최종 상태, 2026-07-10] credential 통합 구현 완료 — 최종 authoritative key는 `KIS_LIVE_INFO_*`다(`KIS_REALTIME_QUOTE_*`는 deprecated fallback으로만 코드에 남음).** `runtime/bootstrap.py::build_realtime_quote_source()`가 `settings.kis_live_app_key`/`kis_live_app_secret`/`kis_live_info_base_url`/`kis_live_info_ws_url`(`_build_kis_live_quote_client()`가 쓰는 것과 동일한 disclosure/live-info 필드) + 신규 `kis_live_info_approval_cache_path`(env `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`)를 authoritative credential로 쓴다. `docker-compose.yml`(`api` 서비스)/`.env.example`의 표준 설정에서 `KIS_REALTIME_QUOTE_*`를 제거했다(코드에는 `KIS_LIVE_INFO_*`가 비어 있을 때만 타는 짧은 legacy fallback만 남김). `KisRealtimeQuoteSource`/`QuoteBroadcaster`/REST fallback 로직 자체는 수정하지 않아 실시간 현재가 기능(WS 수신/SSE push/REST fallback)은 그대로다. 검증: `tests/services/test_kis_realtime_quote_source.py`(legacy fallback 검증용 신규 테스트 포함 3개) + 실시간 현재가/`ops-scheduler`/`market_session` 관련 테스트 283개를 DB 없이 통과, `docker compose config`로 compose 정합성 확인. **(이하는 이 최종 상태에 도달하기까지의 진행 이력 — 전부 같은 날 2026-07-10 안에 순서대로 일어났으며, 중간 결론은 전부 이후 단계에서 대체되었다.)** **[① 2026-07-10 오전, 당시 중간 결론 — 이후 대체됨]** 재검토 완료 — 당시 결론은 "당분간 분리 유지"였고, 이건 구현이 아니라 판단 문서화 작업이었다(그 시점에는 실제 credential 통합/코드 변경 없음). 재검토로 새로 확인된 핵심 사실: 두 credential은 같은 `api` 프로세스 안의 문제가 아니라 서로 다른 두 컨테이너 프로세스 간의 문제였다 — `KisRealtimeQuoteSource`(당시 `KIS_REALTIME_QUOTE_*`)는 `api` 프로세스 전용, `KisMarketStateClient`(`KIS_LIVE_INFO_*`)는 `ops-scheduler` 프로세스 전용(`run_ops_scheduler.py::_init_market_state_provider()`)이었고 `api/app.py`의 lifespan에는 `KisMarketStateClient`가 아예 등장하지 않았다 — 상세 비교표는 `11_kis_realtime_quote_operations_screen.md`의 "Credential 분리/통합 판단 메모" 참고. **[② 같은 날 뒤이어, 선행 조건 검토]** 163 WS(장운영정보) 제거 가능성 검토 — 결론 "제거 가능성 높음, 장기 shadow 검증 없이 진행 가능"(163의 실질 게이팅 효과는 하루 1회 캐시로 이미 제한적이고, `KIS_ENV=paper`에서는 163 WS 연결 자체가 이미 매번 스킵되고 있어 076-only 경로가 사실상 매일 실운영되고 있었으며, 실제 주문 판단/제출이 5분 배치로만 이뤄져 즉시 반응이 필요한 실시간 경로가 없었다). **[③ 같은 날 뒤이어, 163 WS 제거 구현 완료]** `scripts/run_ops_scheduler.py`에서 `KisMarketStateClient`/`CombinedSessionProvider`/`_init_market_state_provider()`/`_session_phase_monitor()`/`_handle_phase_change()`/`_insert_session_event()`를 전부 제거, `_init_session_provider()`는 항상 076 REST(`KisHolidayProvider`) + `FallbackSessionProvider`만 반환하게 됐다. `core_risk_off` 장후 검증 배치는 `market_phase`가 아니라 고정 시계 트리거로만 게이팅되므로 영향 없음을 회귀 테스트(148 passed)로 검증했다. **[④ 같은 날 뒤이어, 최종 credential 통합 구현 — 맨 앞 "현재 최종 상태"와 동일]** 163 WS 제거로 ①의 "당분간 분리 유지" 근거(프로세스 경계를 넘는 WS 세션 소유권 문제)가 사라져, 곧바로 통합을 구현했다 — 상세는 `11_...md`의 "163 WS 제거 가능성 검토 메모"/"Credential 분리/통합 판단 메모"(둘 다 2026-07-10 갱신) 참고. | User request (2026-07-09, 2026-07-10), KIS realtime quote 운영 설계 검토 메모 | ✅ credential 통합 구현 완료(KIS_LIVE_INFO_* 기준) — 재검토/163 WS 제거는 그 전 단계 이력 |

## Medium-term (다음 마일스톤)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Admin UI**: 시스템 상태 모니터링, 주문/계좌 조회, 설정 관리 웹 UI | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ✅ Plan 48로 승격 |
| 2 | **Auth / RBAC for admin API**: Static Bearer token 인증, viewer/admin RBAC, public/protected endpoint 정책 | [Plan 40](plans/40_fastapi_inspection_api.md:78) | ✅ Plan 46으로 승격 |
| 3 | **Operator intervention workflow**: 사람이 개입하여 주문 상태 강제 변경, kill switch override, 수동 reconciliation | [ENTERPRISE_TRADING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | ❌ 미착수 |
| 4 | **Migration 0010: Drop legacy `decision` column**: `trade_decisions.decision` 컬럼 제거. Plan 39에서 nullable로 완화한 후 추가 검증 후 완전 삭제 | [Plan 39](plans/39_trade_decision_schema_alignment.md:294) | ❌ 미착수 |
| 5 | **E2E test with TradeDecisionEntity creation**: AI agent 통합 완료 후 E2E 테스트에서 실제 `TradeDecisionEntity` 생성 및 `trade_decision_id` 참조 검증 | [Plan 39](plans/39_trade_decision_schema_alignment.md:296) | ❌ 미착수 |
| 6 | **Near-real scheduler Docker daemon/service화**: 현재는 Ubuntu crontab이 `python3 scripts/run_near_real_ops_scheduler.py`를 직접 실행하는 방식. 향후 Docker Compose service 또는 별도 daemon container로 전환하여 운영 안정성과 관측성을 확보. 컨테이너 restart policy(`always`/`unless-stopped`) 적용. 컨테이너 healthcheck 추가 (scheduler heartbeat 응답 확인). Scheduler run 상태/heartbeat를 DB에 기록하여 프로세스 생존 여부를 DB 기반으로 추적 가능하게 함. DB advisory lock 또는 scheduler run 테이블 기반 중복 실행 방지 lock 도입. 로그를 container stdout/stderr + 파일 또는 DB로 표준화. Admin UI에서 scheduler 상태(마지막 heartbeat, 현재 phase, submit_count, failed_tasks)를 확인 가능하도록 API/화면 연동. **내일(2026-05-14) 운영 blocker는 아님** — 현재 crontab 기반 운영을 유지하면서 점진적으로 전환. | [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md), [`plans/near_real_scheduler_runbook_2026-05-14.md`](plans/near_real_scheduler_runbook_2026-05-14.md), [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md) | ❌ 미착수 |
| 7 | **P0 — Trading Universe 기반 decision loop 전환**: 현재 `run_paper_decision_loop.py` / `run_orchestrator_once.py`가 `SYMBOL = "005930"`, `MARKET = "KRX"` 상수 기반으로 하드코딩되어 단일 종목(삼성전자)만 판단함. `instruments` 테이블에 등록된 다른 종목을 순회하지 못함. 1개월 near-real 운영의 의미를 살리려면 watchlist/universe 기반 종목 순회가 필요함.<br><br>**범위**:<br>① `TRADING_UNIVERSE_SYMBOLS` 또는 설정 기반 watchlist 도입<br>② hardcoded `SYMBOL = "005930"` 제거 또는 fallback으로만 유지<br>③ decision loop가 universe 종목을 순회하며 `SubmitOrderRequest` 생성<br>④ symbol별 OpenDART 이벤트, position, recent orders를 context에 반영<br>⑤ 전체 계좌 기준 daily submit budget은 유지<br>⑥ KRX/Paper near-real 운영 대상만 우선 지원<br>⑦ AAPL 등 해외 종목은 이번 P0 범위에서 제외 또는 명시적 skip<br><br>**성공 기준**:<br>- decision loop 로그에 각 symbol별 cycle/result가 남음<br>- 최소 2개 이상 KRX 종목에 대해 dry-run 판단 가능<br>- FDC APPROVE 시에도 daily submit budget 1회 제한 유지<br>- 기존 단일 005930 smoke는 fallback으로 유지 가능<br><br>**착수 시점**: 장 종료 직후 바로 착수. **장중 작업 금지** — 이 항목은 백엔드/스케줄러 수정이 필요하므로 장 종료 전에는 구현하지 않음. | [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md), [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md), [`plans/paper_daily_ops_report_2026-05-14.md`](plans/paper_daily_ops_report_2026-05-14.md) | ✅ 구현 완료 — [`plans/trading_universe_decision_loop_p0_report.md`](plans/trading_universe_decision_loop_p0_report.md) 참고. DB 기반 100종목 universe fallback 적용. `run_orchestrator_once.py` 단일 smoke fallback은 유지. |
| 8 | **P1 — Decision/Snapshot/Event 주기 정량 산정 및 adaptive scheduling**: 현재 scheduler/decision loop 기본 주기는 안정성을 위한 보수적 기본값(`DEFAULT_DECISION_INTERVAL_SECONDS = 300`, `DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 300`, `DEFAULT_EVENT_INTERVAL_SECONDS = 300`, `DEFAULT_INTERVAL_SECONDS = 300`). KIS 호출량, LLM latency/cost, event source freshness, OpenDART 이벤트 빈도를 정량 계산하여 산정한 최적값이 아님. KIS rate limit, cash balance partial 이력, LLM 3-agent 호출 비용, OpenDART 중심 이벤트 소스 특성을 감안해 초기 안정성 위주로 설정된 값.<br><br>**범위**:<br>① decision cycle 1회당 KIS REST 호출 수 측정<br>② snapshot sync 1회당 KIS REST 호출 수 측정<br>③ post-submit sync 1회당 KIS REST 호출 수 측정<br>④ EI/Risk/FDC 3-agent 호출 latency/cost 측정<br>⑤ OpenDART ingestion 주기와 신규 high-importance event 발생 빈도 측정<br>⑥ KIS paper/live RPS budget 대비 여유율 계산<br>⑦ decision/snapshot/event/post-submit 각 loop 주기를 분리 설계<br>⑧ 가능하면 event-driven trigger 도입 검토<br><br>**검토 후보**:<br>- P0 현재값: decision 5분, snapshot 5분, event 5분, post-submit 30초<br>- 후보 A: decision 3분, snapshot 5분, event 5분, post-submit 30초<br>- 후보 B: normal decision 5분 + high importance OpenDART event 발생 시 즉시 decision trigger<br>- 후보 C: KIS budget manager 기반 adaptive throttle<br><br>**성공 기준**:<br>- 운영 주기 설정 근거 문서화<br>- KIS 호출량/RPS 여유율 표 작성<br>- LLM 비용/latency 표 작성<br>- 최종 운영 interval 추천안 확정<br>- 필요 시 env/config로 interval 조정 가능하도록 정리<br><br>**착수 시점**: 장 종료 후, universe loop P0 작업 이후 또는 병행 검토. **장중 작업 금지** — 이 항목은 scheduler/backend interval 정책 변경을 포함할 수 있으므로 장 종료 전에는 구현하지 않음.<br><br>**2026-05-14 측정 결과 반영**:<br>- Decision loop (100 symbols, stub agents): **5.4초** ✅ 5분 주기 안전<br>- Snapshot sync (1 cycle): **1.3초** (KIS 인증 실패, 실제 추정 3–8초)<br>- Event ingestion (1 cycle): **0.03초** (polling workers 미설정, 실제 추정 1–5초)<br>- **현재 stub agent 기준 total ~7초 → 5분 주기 여유 충분**<br>- **실제 LLM agent 기준 추정 100–500초 → 5분 주기 위험 가능성 있음**<br>- 상세 보고서: [`plans/near_real_100_symbol_latency_measurement_report.md`](plans/near_real_100_symbol_latency_measurement_report.md) | [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md), [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md), [`plans/paper_daily_ops_report_2026-05-14.md`](plans/paper_daily_ops_report_2026-05-14.md), [`plans/paper_one_month_ops_checklist.md`](plans/paper_one_month_ops_checklist.md), [`plans/near_real_100_symbol_latency_measurement_report.md`](plans/near_real_100_symbol_latency_measurement_report.md) | 🔄 1차 측정 완료 — [`plans/near_real_100_symbol_latency_measurement_report.md`](plans/near_real_100_symbol_latency_measurement_report.md) 참고. 실제 LLM agent latency 측정은 미완료 (stub agent 한계). |
| 9 | **P0 — EI/AR/FDC 판단 체인 HOLD 원인 진단**: 현재 near-real 운영에서 AR은 allow/risk_score 낮음으로 판단하지만 FDC 최종 decision_type이 계속 HOLD로 귀결되는 패턴 관찰됨. FDC 내부 출력상 매수 쪽 선호/확률이 높아 보여도 최종 HOLD가 나오는 이유가 EI 입력 근거 부족 때문일 수 있음. 현재 v1 external event source는 OpenDART 중심이며, 005930 직접 매핑 이벤트가 부족하거나 없을 수 있음. EI가 `events=0`, `symbol=UNKNOWN`, `neutral`, `no significant event` 등으로 나오면 FDC가 "근거 부족"으로 HOLD를 선택하는 것이 자연스러움. 이 현상은 Trading Universe P0 작업과도 연결됨 — 005930 단일 종목만 반복 판단하면 신호가 없는 날에는 계속 HOLD가 정상일 수 있음.<br><br>**범위**:<br>① 최근 agent_runs에서 EI/AR/FDC structured_output_json 수집<br>② FDC가 HOLD를 선택한 cycle의 EI 입력 이벤트 수, event_bias, symbol, reason_codes 확인<br>③ AR allow/risk_score와 FDC HOLD 사이의 불일치가 실제 모순인지 판단<br>④ FDC output의 confidence/conviction/sizing_hint/reason_codes/opposing_evidence 확인<br>⑤ `recent_events`가 FDC prompt까지 제대로 전달되는지 확인<br>⑥ OpenDART 이벤트의 symbol 매핑 상태 확인 (005930 직접 매핑 여부)<br>⑦ importance=high 이벤트가 상위 prompt context에 포함되는지 확인<br>⑧ HOLD 사유가 반복적으로 `insufficient_evidence`, `no_material_event`, `neutral_event_bias` 계열인지 분류<br>⑨ 필요 시 EI/FDC prompt 개선 또는 universe selection 개선으로 분리<br><br>**성공 기준**:<br>- 최근 N개 decision cycle에 대해 EI/AR/FDC 판단 체인 표 작성<br>- "HOLD가 정상적 보수 판단인지 / 데이터 연결 문제인지 / prompt 문제인지" 판정<br>- Trading Universe P0와 연결해야 할 개선점 도출<br>- 장중 운영 중 임의 APPROVE 유도는 금지한다는 원칙 재확인<br><br>**착수 시점**: 장 종료 후, Trading Universe 기반 decision loop 전환(P0 #7)과 함께 또는 직후. **장중 작업 금지** — 이 항목은 AI pipeline/backend 판단 로직 진단을 포함하므로 장 종료 전에는 구현/수정하지 않음. | [`plans/paper_daily_ops_report_2026-05-14.md`](plans/paper_daily_ops_report_2026-05-14.md), [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md), [`plans/opendart_disclosure_importance_ranking.md`](plans/opendart_disclosure_importance_ranking.md), [`plans/news_source_adapter_3rd_evaluation.md`](plans/news_source_adapter_3rd_evaluation.md), [`plans/[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) | ✅ 진단 및 P0 수정 완료 — [`plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md`](plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md) 참고. 추가 개선은 universe/instrument master로 연결 |
| 10 | **P1 — operations_day_runs 기반 운영일 상태 관리**: 운영일 마감 완료 표시의 정식 해결책. Pre-Market/Intraday/End-of-Day phase 상태를 DB에 기록하여 Admin UI에서 오늘 운영 상태와 마감 완료 여부를 정확히 표시하는 기능.<br><br>**범위**:<br>① 신규 테이블 `operations_day_runs` 또는 동등한 운영일 상태 테이블 설계<br>② 필드: operations_day_run_id, run_date, environment, phase (pre_market, intraday, end_of_day), status (pending, running, completed, failed), started_at, completed_at, error_message, metadata<br>③ `run_near_real_ops_scheduler.py`에서 phase 시작/완료/실패 시점 기록<br>④ API: `GET /operations/day-status?date=YYYY-MM-DD`<br>⑤ Admin UI 운영 대시보드/운영 경고에 표시 (장전 완료, 장중 운영 중, 마감 진행 중, 마감 완료, 마감 실패)<br>⑥ 운영 경고 rule: 장 마감 이후 EOD 미완료 → 주의/긴급, EOD failed → 긴급, EOD completed → 마감 완료 표시<br><br>**성공 기준**:<br>- 스케줄러가 phase별 상태를 DB에 남김<br>- Admin UI에서 오늘 운영 상태를 추정이 아니라 DB 상태로 표시<br>- 장 마감 후 마감 완료가 명확히 표시됨<br>- crash/restart 시에도 마지막 phase 상태 확인 가능<br><br>**착수 시점**: 장 종료 후, 당장 급한 P0 작업들 (#7, #9) 이후 진행. **장중 작업 금지** — DB 스키마 변경과 백엔드/스케줄러 수정이 필요하므로 장 종료 전에는 구현하지 않음.<br>**비고**: 임시 workaround로 `audit_logs` 기반 마감 완료 표시는 별도 P0로 분리 검토 가능 | [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md), [`plans/near_real_scheduler_runbook_2026-05-14.md`](plans/near_real_scheduler_runbook_2026-05-14.md), [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md), [`plans/[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) | ❌ 미착수 |
| 11 | **P1 — WATCH decision 부재 원인 분석 및 정책 보완**: 현재 dry-run/intraday 관측에서 `WATCH` decision이 0건인 상태. FDC가 `HOLD`와 `APPROVE`/`REDUCE` 사이만 오가고 `WATCH` 중간 상태를 거의 사용하지 않는 원인을 분석하고, source_type별 `WATCH` 허용 정책을 점검하여 개선 방향을 도출한다.<br><br>**포함할 핵심**:<br>① FDC가 `WATCH`를 선택한 사례가 전혀 없는 원인 분석 — prompt threshold, event signal 부족, policy 누락 중 어느 계층 문제인지 진단<br>② `EventInterpretationAgent`의 event_bias/reason_codes가 FDC의 WATCH 선택에 어떤 영향을 주는지 확인<br>③ Source_type별 (`core` / `event_overlay` / `market_overlay`) WATCH 허용 정책 점검 — 현재는 암묵적으로 모든 source_type에 동일 정책이 적용됨<br>④ `FinalDecisionComposerAgent`의 prompt에 WATCH 조건이 명시적으로 존재하는지, threshold가 너무 높은 것은 아닌지 검토<br>⑤ `WATCH`가 의미 있는 중간 상태로 기능하려면 어떤 조건(이벤트 존재, 가격 변동, risk score 경계)에서 트리거되어야 하는지 정리<br><br>**연결 관계**:<br>- [#30 Signal Agent](#30-signal-agent-분해) — Signal Agent가 구현되면 WATCH decision의 quantitative trigger로 활용 가능<br>- [#28 Universe Selection Agent](#28-universe-selection-agent-분해) — universe source_type별 WATCH 정책 분리가 universe design과 연결됨<br><br>**성공 기준**:<br>- WATCH 부재 원인 문서화 (prompt / policy / data 중 결정적 원인 식별)<br>- prompt/policy/decision thresholds 중 구체적 수정 포인트 식별<br>- core / market_overlay / event_overlay별 WATCH 정책 초안 도출<br>- WATCH가 도입될 경우 예상 영향 (submit budget, false positive 위험) 평가<br><br>**착수 시점**: 장 종료 후. 현재 운영 분석 보고서([`plans/ei_fdc_hold_bias_analysis.md`](plans/ei_fdc_hold_bias_analysis.md), [`plans/intraday_reconcile_required_convergence_observation_2026-05-15.md`](plans/intraday_reconcile_required_convergence_observation_2026-05-15.md)) 결과를 입력으로 사용. **장중 작업 금지** — prompt/policy 분석 및 수정이 필요하므로 장 종료 전에는 진행하지 않음. | [`plans/ei_fdc_hold_bias_analysis.md`](plans/ei_fdc_hold_bias_analysis.md), [`plans/intraday_reconcile_required_convergence_observation_2026-05-15.md`](plans/intraday_reconcile_required_convergence_observation_2026-05-15.md), [`plans/[BACKLOG] backlog.md`](plans/[BACKLOG]%20backlog.md) (#30, #28) | ❌ 미착수 |
| 12 | **P1 — core + no_event 100% HOLD 완화 정책**: 현재 `core` source_type이면서 `no_material_events=True`인 상황에서 거의 100% HOLD로 귀결되는 패턴 관찰. no-event와 negative-signal을 더 분리하는 정책을 검토하고, core 종목에 대해 `WATCH` 또는 저신뢰 signal 분기 가능성을 탐색한다.<br><br>**포함할 핵심**:<br>① `no_material_events`와 `negative_signal`의 FDC prompt 내 처리 차이 분석 — 현재는 event 부재 시 HOLD가 기본값<br>② Core 종목은 event 유무와 무관하게 정기적 평가가 필요한지 정책 결정 — 보유 비중, 가격 변동, 시장 상황을 별도 signal로 간주할지<br>③ `EventInterpretationAgent`의 output에서 `events=0`이 `neutral`/`no_significant_event`로 해석되는 경로 vs `insufficient_evidence`로 해석되는 경로 분기<br>④ `no_event + HOLD`가 보수적 운용 관점에서 적절한지, 아니면 기회 비용이 발생하는지 평가<br>⑤ HOLD bias 완화 방향 (예: no-event core는 confidence threshold를 낮춰 WATCH 가능, 또는 별도 `no_event_hold_decay` 정책 도입) 초안<br>⑥ 위험 통제 관점 — no-event에서 무조건 non-HOLD로 전환하는 것이 아니라, 특정 조건(보유 중, 가격 급변, 시장 이벤트)에서만 분기하도록 제한<br><br>**연결 관계**:<br>- [#30 Signal Agent](#30-signal-agent-분해) — Signal Agent가 no-event core에 대해 정량 feature 기반 스코어를 제공할 수 있음<br>- [#11 WATCH decision 부재 원인 분석](#11-p1--watch-decision-부재-원인-분석-및-정책-보완) — WATCH 정책과 HOLD 완화는 동전의 양면, 두 항목의 결과를 종합해야 함<br><br>**성공 기준**:<br>- no-event core 처리 정책 초안 도출 (명시적 decision tree 또는 rule set)<br>- HOLD bias 완화 방향 정리 (어느 조건에서, 어떤 수준으로 완화할지)<br>- 위험 통제와 actionability 균형안 제시 (HOLD가 정답인 조건 명시)<br>- EI → FDC prompt에 no-event 처리 지침 개선안 포함<br><br>**착수 시점**: 장 종료 후, #11 WATCH 분석과 병행 또는 직후. **장중 작업 금지** — prompt/policy 변경이 수반되므로 장 종료 전에는 진행하지 않음. | [`plans/ei_fdc_hold_bias_analysis.md`](plans/ei_fdc_hold_bias_analysis.md), [`plans/intraday_reconcile_required_convergence_observation_2026-05-15.md`](plans/intraday_reconcile_required_convergence_observation_2026-05-15.md), [`plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md`](plans/ei_ar_fdc_hold_chain_diagnosis_2026-05-14.md) | ❌ 미착수 |
| 13 | **P1 — market_overlay 실운영 반영 검증 및 장중 효과 측정**: 현재 `UniverseSelectionService`에 market-driven overlay 설계/코드 경로(`source_type=market_overlay`)는 존재하나, 실제 장중 관측에서 `market_overlay` 심볼이 0건이었음. 실운영에서 market_overlay가 실제로 universe 편입/평가/판단에 반영되는지 검증하고, 반영되지 않는다면 병목 단계를 식별하여 개선한다.<br><br>**포함할 핵심**:<br>① `UniverseSelectionService`가 `market_overlay` source_type의 심볼을 실제로 생성하는지 — KIS 순위 분석 API 호출 여부, 필터 조건, fallback 동작 확인<br>② `market_overlay` 심볼이 `_run_one_cycle()`에서 정상적으로 AI agent 평가를 받는지 — universe에 포함되어도 decision loop가 실제로 판단하는지(end-to-end 추적)<br>③ 실운영에서 `market_overlay` 편입 건수 = 0인 원인 — universe selection 단계에서 누락, 또는 생성되었지만 cap/source_type 필터에서 제외, 또는 decision loop가 skip<br>④ `market_overlay` 심볼이 편입될 경우 decision 품질에 미치는 영향 평가 — event 부족, liquidity 문제, false positive 위험<br>⑤ KIS 순위 분석 API의 실제 응답 샘플을 수집하여 어떤 종목이 후보로 올라오는지, API가 정상 응답하는지 확인<br>⑥ 편입되지 않는다면 병목 단계 3가지 중 하나:<br>   - Universe selection: KIS API 호출 실패 또는 결과 0건<br>   - Intermediate: cap 도달로 overflow 제외<br>   - Decision loop: 편입되었으나 모두 HOLD로 귀결<br><br>**연결 관계**:<br>- [#28 Universe Selection Agent](#28-universe-selection-agent-분해) — market_overlay는 universe design의 핵심 구성 요소<br>- [#30 Signal Agent](#30-signal-agent-분해) — KIS 순위 분석 API feature가 Signal Agent 입력으로 사용될 수 있음<br>- [#12 core + no_event HOLD 완화](#12-p1--core--no_event-100-hold-완화-정책) — market_overlay 종목도 no_event 상태에서 HOLD로 귀결될 가능성 높음<br><br>**성공 기준**:<br>- 장중 실측 보고서 (최소 1회 운영 cycle에서 market_overlay 편입 추적)<br>- `market_overlay` 편입 여부 확인 (편입 건수, source_type 분포)<br>- 편입되지 않는다면 병목 단계 식별 (universe selection / cap / decision loop 중)<br>- 편입 시 decision 품질 영향 평가 (HOLD 비율, APPROVE/REDUCE 비율, false positive 위험)<br>- 개선이 필요하다면 구체적 수정 범위 도출<br><br>**착수 시점**: 장 종료 후, Universe Selection 정책([`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md))의 V1.1 반영 범위와 연결하여 진행. **장중 작업 금지** — universe selection / scheduler 백엔드 코드 수정이 수반될 수 있으므로 장 종료 전에는 진행하지 않음. | [`plans/[POLICY] trading_universe_policy_v1.md`](plans/[POLICY]%20trading_universe_policy_v1.md), [`plans/[DESIGN] universe_selection_service.md`](plans/[DESIGN] universe_selection_service.md), [`plans/intraday_reconcile_required_convergence_observation_2026-05-15.md`](plans/intraday_reconcile_required_convergence_observation_2026-05-15.md) | ❌ 미착수 |
| 14 | **P0 — `reconcile_required` 잔존 해소 및 주문/정합성 화면 정상화**: 현재 `정합성 조정` 화면과 `주문` 화면에서 `reconcile_required` 상태가 장시간 잔류하며, 실제 포지션 스냅샷상 체결 완료 또는 브로커 진실 상태와 화면 상태가 어긋나는 문제가 반복 관측됨. 최근 로그에서는 `post_submit_sync`가 `inquire-daily-ccld`의 `ODNO match FAILED`를 반복하면서 약 113초씩 점유하고, 이 동안 새 decision cycle이 지연되거나 누락되는 현상도 확인됨. 이 항목은 단순 UI 표현 문제가 아니라 **주문 정합성 복구 지연 + post-submit sync 병목 + 운영 화면 stale 상태**를 함께 다루는 P0 backlog로 관리한다.<br><br>**포함할 핵심**:<br>① `order_requests.status='reconcile_required'` 및 `broker_orders.broker_status='reconcile_required'` 잔존 원인 분해 — KIS daily ccld 조회, broker_order_id ↔ ODNO 매핑, paper truth 한계, sync policy 중 어느 계층 문제인지 구분<br>② `post_submit_sync` 장기 점유 원인 분석 — 동일 주문 재조회 반복, timeout/retry 구조, active sync 대상 선정 기준 검토<br>③ 포지션 스냅샷상 체결 완료인데 주문/정합성 화면은 `조정 필요`로 남는 케이스에 대한 상태 전이 설계 정리<br>④ `reconcile_required` 주문이 decision gate / scheduler cadence / submit budget에 미치는 영향 측정<br>⑤ 운영 화면에서 stale `reconcile_required`를 더 잘 드러내는 UX 또는 분류(예: broker truth unavailable vs manual review required) 검토<br>⑥ 필요 시 `reconcile_required` 해소용 별도 worker / manual resolution queue / aging alert 기준 재정리<br><br>**연결 관계**:<br>- [`plans/post_submit_sync_e2e_report.md`](plans/post_submit_sync_e2e_report.md) — post-submit sync 관측 결과<br>- [`plans/paper_truth_unavailable_manual_resolution_policy_2026-05-16.md`](plans/paper_truth_unavailable_manual_resolution_policy_2026-05-16.md) — manual resolution 정책 초안<br>- [`plans/scheduler_submit_gate_block_reason_2026-05-15.md`](plans/scheduler_submit_gate_block_reason_2026-05-15.md) — submit gate 차단 연쇄 영향<br>- [`plans/reconciliation_view_loading_diagnostics_and_improvement_2026-05-17.md`](plans/reconciliation_view_loading_diagnostics_and_improvement_2026-05-17.md) — 운영 화면 관찰성/UX 관련<br><br>**성공 기준**:<br>- `reconcile_required` 잔존 원인과 정상/비정상 케이스를 분리한 진단 문서화<br>- 최소 1건 이상 stale `reconcile_required` 주문이 왜 남았는지 end-to-end 추적 가능<br>- `post_submit_sync`의 장기 점유가 줄거나, 적어도 병목 위치와 개선안이 명확해짐<br>- 주문/정합성 화면에서 operator가 “체결 완료인데 왜 조정 필요인지” 설명 가능한 기준 확보<br><br>**착수 시점**: 우선순위 높음. 장중 운영에 직접 영향을 주므로 관찰/진단은 장중 가능, submit policy/worker 수정은 장 종료 후 적용 권장. | [`plans/post_submit_sync_e2e_report.md`](plans/post_submit_sync_e2e_report.md), [`plans/paper_truth_unavailable_manual_resolution_policy_2026-05-16.md`](plans/paper_truth_unavailable_manual_resolution_policy_2026-05-16.md), [`plans/scheduler_submit_gate_block_reason_2026-05-15.md`](plans/scheduler_submit_gate_block_reason_2026-05-15.md), User request (2026-05-18) | ❌ 미착수 |
| 15 | **P0 — 장후 subprocess isolation 배포 + 다음 장중 `decision_submit_gate`/sell order 실운영 검증**: LLM API httpx C-level blocking을 우회하기 위해 agent subprocess isolation 코드는 준비되었으나, 장중 정책상 아직 운영 컨테이너에 배포되지 않았음. 장후(15:30 KST 이후) 안전 배포 후 다음 장중에 `decision_submit_gate`가 timeout 없이 정상 종료되는지, 그리고 `REDUCE/EXIT`가 실제 `order_requests(side='sell')` 및 가능하면 `broker_orders`까지 연결되는지 검증해야 한다.<br><br>**포함할 핵심**:<br>① 장후 `docker compose up --build -d` 기준으로 `ops-scheduler`/app 재배포<br>② 다음 장중 `decision_submit_gate complete ok=... timeout=... duration=...` 로그 확인<br>③ `trade_decisions(side='sell')` → `order_requests(side='sell')` → `broker_orders` 실데이터 경로 검증<br>④ subprocess isolation fallback이 실제로 triggered 되는지와 agent/provider duration 관측<br>⑤ `_DECISION_TIMEOUT`과 scheduler task timeout을 다시 줄일 수 있는지 사후 평가<br><br>**성공 기준**:<br>- 장후 배포 완료 및 `/health` 정상<br>- 다음 장중 `decision_submit_gate timeout=False` 확인<br>- 최소 1건 이상 `REDUCE/EXIT` sell order request 생성 확인<br>- 남는 blocker가 있으면 후속 P0/P1로 분해 가능<br><br>**착수 시점**: 장후(15:30 KST 이후) 배포, 다음 장중 실측 필수. 장중 코드 배포 금지. | [`plans/llm_hang_root_cause_and_fast_degrade_submit_recovery_2026-05-19.md`](plans/llm_hang_root_cause_and_fast_degrade_submit_recovery_2026-05-19.md), [`plans/live_reduce_exit_sell_order_intraday_validation_2026-05-19.md`](plans/live_reduce_exit_sell_order_intraday_validation_2026-05-19.md), User request (2026-05-19) | ❌ 미착수 |
| 16 | **P2 — KIS paper/live 전환 메타데이터 정리 및 파일명/설정 스위치 일원화**: 현재 시스템은 `KIS_ENV`에 따라 paper/live를 스위치하는 구조이므로, 파일명이나 설정 구조에 `paper`, `live`, `near_real`, `real` 같은 단어가 직접 박혀 있는 부분을 줄이고, KIS paper/live 전환에 필요한 TR_ID 및 설정값을 DB 또는 config 계층에서 일괄 관리하도록 정리할 필요가 있다.<br><br>**포함할 핵심**:<br>① 파일명 자체에 `paper` / `live` / `near_real` / `real` 등이 들어간 파일 inventory 작성 후, 실제 역할이 env-agnostic이면 해당 단어 제거 방향으로 rename 계획 수립<br>② KIS live용 TR_ID와 paper용 TR_ID를 한눈에 비교할 수 있는 매핑 테이블 또는 config 구조 설계<br>③ `KIS_ENV`만 바꾸면 적절한 TR_ID가 자동 선택되도록 구현 경로 정리<br>④ paper/live에 따라 달라지는 설정값(rate limit, endpoint 정책, submit/snapshot/query 제약 등)을 DB 또는 config 관련 파일에서 일괄 관리하도록 정리<br>⑤ env별 차이를 코드 곳곳의 조건문에 흩뿌리지 않고, broker/config layer에서 일관되게 해결하는 방향 검토<br><br>**성공 기준**:<br>- env-specific 파일명 inventory와 rename 후보 목록 확보<br>- KIS paper/live TR_ID 매핑 구조 초안 도출<br>- paper/live 설정값 inventory 및 config centralization 설계 정리<br>- `KIS_ENV` 중심 스위칭 아키텍처 개선안 문서화<br><br>**착수 시점**: 장중 운영 blocker 해소 이후. 광범위한 rename/refactor 가능성이 있어 장 종료 후 순차 진행 권장. | User request (2026-05-19), [`plans/mode_boundary_paper_live.md`](plans/mode_boundary_paper_live.md), [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py) | ❌ 미착수 |
---

## Longer-term (아키텍처 개선 / 안정성)

| # | 항목 | 출처 | 상태 |
|---|------|------|------|
| 1 | **Soak / recovery / chaos tests**: 장기 실행 안정성, 장애 복구, 비정상 입력 내성 검증 | 여러 Plan | ❌ 미착수 |
| 2 | **Provider failover / fallback hardening**: LLM provider 장애 시 fallback 전략 고도화 (auto-retry, provider 전환) | [Plan 29](plans/29_ai_decision_backend_contract.md:471), [Plan 30](plans/30_runtime_three_agent_smoke.md:555) | ❌ 미착수 |
| 3 | **Replay UX / audit inspection 개선**: Replay Engine UX 개선, audit 로그 검색/필터 고도화 | [Plan 37](plans/37_long_path_end_to_end_integration.md) | ❌ 미착수 |
| 4 | **Event loop gap-fill path `transition_to()` 검토**: `trigger_gap_fill()`이 ExternalEvent persist만 수행. 향후 fill data → order state 반영 경로 필요 여부 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:844) | ❌ 미착수 |
| 5 | **Reconciliation 결과로 PARTIALLY_FILLED 반영 검토**: 현재는 authoritative reflection에서 PARTIALLY_FILLED 제외. 실제 broker 사례 발생 시 재검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:845) | ❌ 미착수 |
| 6 | **Reconciliation Run에 order_id 직접 매핑**: `_resolve_order_for_reflection()`이 broker_order_id/client_order_id로 찾는 방식. 향후 run에 직접 order_id 저장 검토 | [Plan 35](plans/35_reconciliation_authoritative_state_reflection.md:846) | ❌ 미착수 |
| 7 | **장 운영 세션 정보 수집/저장 + 운영 체크리스트 자동 점검**: KIS 또는 대체 공식 소스에서 장전/장중/장후/휴장/조기종료/특수 세션 정보를 수집해 PostgreSQL에 저장하고, 이를 기반으로 “장 시작 전 할 일 / 장중에 할 일 / 장 종료 후 할 일” 점검 로직 및 운영 체크리스트를 구성 | User request (2026-05-13) | ❌ 미착수 |
| 8 | **KIS 기본종목정보 instrument master 적재/갱신**: KIS 기본종목정보를 PostgreSQL instrument master로 적재하고 주기적으로 갱신하는 파이프라인. symbol/market/name/name_kr/식별코드/활성상태/metadata를 보존해 snapshot sync, external event mapping, UI/inspection 종목 정보 노출의 공통 기준 데이터로 사용 | User request (2026-05-13) | ❌ 미착수 |
| 8a | **운영 수동 배치 Admin UI**: instrument master sync, placeholder instrument seed 등 운영성 배치를 Admin UI에서 `dry-run → apply → 실행 이력 조회` 구조로 실행할 수 있게 한다. 장중 override 권한 분리, 실행자/audit log, 파라미터 기록, 비동기 job 상태 조회를 포함한 안전한 실행 contract를 먼저 고정해야 함 | User request (2026-06-13) | ❌ 미착수 |

---

## Deferred / Nice-to-have (현재 계획 없음)

| # | 항목 | 출처 | 비고 |
|---|------|------|------|
| 1 | KIS 실통신 (real API key + live trading) | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | Paper mode 우선 |
| 2 | 키움증권 Broker Adapter | [ENTERPRISE_TRA`DING_SYSTEM_DESIGN.md](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md:99) | KIS 우선 |
| 3 | Full reconciliation automation (auto-resolve) | [Plan 10](plans/10.milestone6_broker_contract_reconciliation_alignment.md) | 현재는 minimal recovery hook만 |
| 4 | Real event data ingestion (OpenDART/KRX polling, news feed) | [Plan 12](plans/12.milestone7_broker_capacity_and_event_data.md:428) | v1 제외 |
| 5 | Redis cache layer (rate limit, session cache) | [Enterprise Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | 현재는 in-memory |
| 6 | CI/CD pipeline (K8s, Terraform, GitHub Actions) | [Plan 01](plans/01.dev_infrastructure_plan.md:6) | v1 제외 |
| 7 | Observability stack (metrics, tracing, structured logging, alerting) | [Enterpris`e Design](../plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md) | v1 제외 |
| 8 | Extended market session intelligence (pre/open/intraday/post/holiday checklist automation) | User request (2026-05-13) | v2/Phase X 후보 |
| 9 | Broker-backed instrument master sync and enrichment | User request (2026-05-13) | v2/Phase X 후보 |

---

## 상태 범례

| 표시 | 의미 |
|------|------|
| ❌ 미착수 | 아직 시작하지 않음 |
| 🔄 검토 중 | 우선순위 평가 중 |
| ✅ 승격됨 | Numbered plan으로 승격됨 (하단 기록 참조) |
| 🗑️ 폐기 | 더 이상 추진하지 않기로 결정 |

## 승격 기록

| 날짜 | 항목 | Plan 번호 | 비고 |
|------|------|-----------|------|
| 2026-05-04 | Auth / RBAC for Inspection API | [Plan 46](plans/46_auth_rbac_inspection_api.md) | Static Bearer token, viewer/admin RBAC, router-level dependency, safe default |
| 2026-05-04 | Auth Policy Hardening (Pre-UI Security Pass) | [Plan 47](plans/47_auth_policy_hardening.md) | Docs/OpenAPI 공개 정책 고정, token/role validation 강화, 운영 문서 정리 |
| 2026-05-05 | Admin UI Phase 1 (Read-Only Operations Dashboard) | [Plan 48](plans/48_admin_ui_phase1.md) | Vite + React + TypeScript + Pico CSS SPA. FastAPI static serve. 5 screens. sessionStorage token. Phase 1 read-only. |
| 2026-05-05 | Admin UI Smoke / Component Test Hardening | [Plan 49](plans/49_admin_ui_test_hardening.md) | Vitest + RTL + jsdom. 24 tests (P0 16 + P1 8). Auth flow, Dashboard/OrdersView smoke, common components. URL+Method 분기 명확화. |
| 2026-05-05 | Admin UI Test Coverage Phase 2 | [Plan 50](plans/50_admin_ui_test_coverage_phase2.md) | P0 19개 + P1 7개 = 26개 신규 테스트. OrderDetail (7), AccountsView (6), ReconciliationView (6), Layout (4), DecisionsView (3). Fixture 8종 추가. 총 50 tests. |
| 2026-05-05 | Admin UI Operations Workflow Enhancements (P0) | [Plan 51](plans/51_admin_ui_operations_workflow_enhancements.md) | OrdersView filter/search, OrderDetail→Decisions drill-down, ReconciliationView quick-filter+lock 강조, Dashboard signal+drill-down. 8개 신규 테스트. 총 58 tests. Backend API 변경 없음. |
| 2026-05-05 | Admin UI Phase 1.5 (Decisions / Accounts UX Completion) | [Plan 52](plans/52_admin_ui_phase1_5.md) | DecisionsView detail panel + context lazy-load (stale guard) + side/symbol/confidence filter + empty placeholder. AccountsView search/type filter + detail clarity + filter-reset policy. DataTable selectedKey prop. 12개 신규 테스트. 총 69 tests. Backend API 변경 없음. |
| 2026-05-08 | Admin UI 전면 한글화 + Pretendard 폰트 적용 | [Plan 66](plans/66_admin_ui_korean_localization.md) | 모든 사용자 노출 텍스트 한국어 변환 (14개 컴포넌트 + 11개 테스트). Pretendard 폰트 CDN 적용. 80/80 테스트 통과. Backend API 변경 없음. |
| 2026-05-08 | KIS Snapshot Sync 운영화 | [kis_snapshot_sync_operationalization.md](plans/kis_snapshot_sync_operationalization.md) | 수동 스크립트 기반 적재를 정기 실행 가능한 백엔드 작업으로 승격. `BatchSyncResult` + `sync_kis_accounts_by_ids()` + `sync_all_kis_accounts()` 추가. `--account-id` N개 + `--all` 플래그. `AccountLookup.broker_account_id` 필드 추가. 5개 batch sync 테스트 추가. 총 18/18 테스트 통과. |
| 2026-05-08 | KIS Snapshot Sync 운영화 — CLI 고도화 | [kis_snapshot_sync_operationalization.md](plans/kis_snapshot_sync_operationalization.md) | `sync_all_kis_accounts()`에 `env`/`account_status` 필터 파라미터 추가. CLI에 `--env paper\|live`, `--status`, `--account-ref`, `--dry-run`, `--format json` 5개 옵션 추가. `BrokerAccountRepository.list_by_broker_and_env()` contract 추가. 신규 테스트 6개(env 3 + status 3). 총 24/24 테스트. |
| 2026-05-08 | KIS Snapshot Sync 실행 이력 저장 | [kis_snapshot_sync_run_history.md](plans/kis_snapshot_sync_run_history.md) | `SnapshotSyncRunEntity` + migration 0011 + `SnapshotSyncRunRepository`(Protocol/Postgres/InMemory) + `build_sync_run_entity()` helper. CLI(`sync_kis_snapshots.py`) 및 Scheduler(`run_snapshot_sync_loop.py`)에 실행 이력 저장 연결. 신규 테스트 3개 클래스(Entity 6 + helper 6 + Repository 2 = 14 tests). 총 38/38 테스트. |
| 2026-05-08 | Snapshot Sync Run Inspection API | [kis_snapshot_sync_inspection_api.md](plans/kis_snapshot_sync_inspection_api.md) | `SnapshotSyncRunRepository.list_runs()/get()` 추가 (Protocol + Postgres + InMemory). `SnapshotSyncRunSummary` Pydantic schema. `GET /snapshot-sync-runs`(목록 + 필터) + `GET /snapshot-sync-runs/{run_id}`(상세) 라우트. app.py Phase 4 등록. 신규 테스트 11개 (목록 6 + 상세 3 + 인증 3). |
| 2026-05-08 | Snapshot Sync Freshness / Health Summary | [kis_snapshot_sync_freshness.md](plans/kis_snapshot_sync_freshness.md) | `SnapshotSyncHealthSummary` dataclass + `get_sync_health_summary()` (Protocol/Postgres/InMemory). `KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS` env config (default 900s). `SnapshotSyncRunHealthSummary` Pydantic schema. `GET /snapshot-sync-runs/summary` 라우트 (단일 엔드포인트, list보다 먼저 등록). 신규 테스트 7개 (empty, fresh, stale, consecutive_failures, auth_required, auth_passes). |
| 2026-05-08 | Snapshot Sync Freshness → Health/Readiness 신호 연결 | [kis_snapshot_sync_readiness.md](plans/kis_snapshot_sync_readiness.md) | HealthResponse에 snapshot sync freshness optional 필드 4개 추가. `/health`에 snapshot sync detail 포함. `/health/readyz`에 stale sync → degraded 정책 구현. 신규 테스트 4개 + 기존 readyz 테스트 degraded 반영. 27/27 통과. |
| 2026-05-08 | Snapshot Sync Startup Grace Period | [kis_snapshot_sync_grace.md](plans/kis_snapshot_sync_grace.md) | `KIS_SNAPSHOT_STARTUP_GRACE_SECONDS` env config (default 600s). `_app.state.started_at` in lifespan. Grace 내 readiness: `ok` + health detail: `starting_up`. Grace 경과 후 기존 degraded 정책 유지. Grace 무관 DB unreachable → `not_ready`. 신규 테스트 5개 + 기존 3개 수정. |
| 2026-05-08 | Broker-Agnostic Operations Runner | [broker_agnostic_operations_runner.md](plans/broker_agnostic_operations_runner.md) | `SnapshotFetchProvider` Protocol + `FetchedSnapshot` dataclass. `sync_account_snapshots()`/`sync_accounts_by_ids()`/`sync_all_accounts()` broker-agnostic runner. `KISSyncSnapshotProvider` (KIS 구현체). `scripts/sync_snapshots.py` 신규 CLI. `run_snapshot_sync_loop.py` broker-aware. `settings.py` env alias additive. `sync_kis_snapshots.py` deprecated wrapper 유지. 신규 테스트 33개 (공통 runner 24 + KIS provider 9). 총 113/113 통과. |
| 2026-05-08 | Broker-Aware Snapshot Client/Provider Factory | [broker_agnostic_operations_runner.md](plans/broker_agnostic_operations_runner.md) | `SnapshotSyncComponents` dataclass + `build_snapshot_sync_components()` factory. `scripts/sync_snapshots.py`에서 `_build_provider()` 제거 → factory 호출. `scripts/run_snapshot_sync_loop.py`에서 KIS 직접 wiring 제거 → factory 호출. `sync_kis_snapshots.py` deprecated wrapper 유지. 신규 테스트 8개. 총 121/121 테스트 통과. |
| 2026-05-08 | AuthenticatableSnapshotClient Protocol | [authenticatable_snapshot_client_protocol.md](plans/authenticatable_snapshot_client_protocol.md) | `SnapshotSyncComponents.client`를 `Any` → `AuthenticatableSnapshotClient` Protocol로 승격. Scheduler(`run_snapshot_sync_loop.py`)에서 `type: ignore[union-attr]` 제거, `\| None` 타입 제거. 신규 테스트 1개. 총 122/122 테스트 통과. |
| 2026-05-09 | **AI Decision → Order Submit 파이프라인 (Gap 1)** | [gap1_ai_decision_to_order_submit.md](plans/gap1_ai_decision_to_order_submit.md) | FDC 결과 → `TradeDecisionEntity` 저장 → `OrderManager` → broker submit 전 경로 연결. `SubmitResult` dataclass, `assemble_and_submit()` 5-phase pipeline, `build_submit_order_request_from_decision()` pure function, runtime wiring (`bootstrap.py` + `run_orchestrator_once.py --submit`). 20/20 신규 테스트 통과. |
| 2026-05-09 | **AI Agent comment/rationale 저장 한국어 강제** | [gap4_korean_text_enforcement.md](plans/gap4_korean_text_enforcement.md) | PostgreSQL 서술형 텍스트 한국어 강제. Dual Defense: Prompt 수준 + Backend 정규화. `korean_normalizer.py` (validate_or_normalize_korean, normalize_structured_output, contains_korean). 3개 Agent prompt 한국어 지시. `recorder.py` `normalize_structured_output()` 적용. `decision_orchestrator.py` `validate_or_normalize_korean()` 적용. 34/34 신규 테스트 통과 (26 unit + 8 integration). |
| 2026-05-09 | **Decision ↔ Order 추적성 강화 (Gap 2)** | [gap2_decision_order_traceability.md](plans/gap2_decision_order_traceability.md) | `decision_context_id` 6개 경로 전파: OrderManager.create_order() → OrderRequestEntity, PostgresOrderRepository.add() SQL INSERT, OrderQuery 필터 2종(trade_decision_id, decision_context_id), OrderSummary/GET /orders trace query params, TradeDecisionRepository.get() PK 조회, SubmitResult.decision_context_id 7개 return site. 20/20 pipeline + 82/82 관련 테스트 통과. |
| 2026-05-09 | **Safe Order Path E2E 검증 (Gap 3)** | [gap3_safe_order_path_e2e.md](plans/gap3_safe_order_path_e2e.md) | Fake broker adapter 기반 E2E 시나리오 7개 검증: happy path(SUBMITTED), uncertain(RECONCILE_REQUIRED+lock), blocking lock 차단(RECONCILE_REQUIRED+broker 0회), lock 재시도(차단+broker 1회), reject(REJECTED), duplicate guard(ERROR), requires_reconciliation(RECONCILE_REQUIRED+lock). 7/7 신규 + 40/40 기존 테스트 통과. |
| 2026-05-09 | **Backend Sizing Math 고도화 (Gap 4)** | [gap4_backend_sizing_math.md](plans/gap4_backend_sizing_math.md) | Position-aware/config-driven deterministic sizing engine 도입. `SizingInputs`(18-field) / `SizingResult`(4-field) dataclass. `calculate_sizing()` 8-step pure function pipeline. Phase 1.5 pipeline step (`_build_sizing_inputs()`+`calculate_sizing()`). 37/37 sizing engine 단위 테스트 + 2/2 pipeline 통합 테스트 + 444/444 기존 테스트 회귀 없음. 총 483/483 테스트 통과. |
| 2026-05-09 | **Paper Trading Loop Validation** | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | Paper 운영 루프 검증 기반 완성. 사용자 통합테스트 5개 시나리오(`test_paper_trading_scenarios.py`), Replay 결정론적 검증(`test_decision_replay.py`), `run_orchestrator_once.py` 개선(`--dry-run`, `--output json`), `verify_paper_loop.py` 신규(반복 실행 전용), Go/No-Go 기준 문서화. |
| 2026-05-09 | **Fill Sync / Post-Submit Update** | [fill_sync_post_submit_update.md](plans/fill_sync_post_submit_update.md) | `OrderSyncService` 신규 생성. `sync_order_post_submit()` 진입점. chain transition (SUBMITTED→FILLED 3-step). Fill event ingestion + dedup. `BrokerOrderRepository.update()/get()` Protocol + InMemory. `last_synced_at` 초기값 설정. 11개 신규 테스트. 470/470 기존 테스트 회귀 없음. |
| 2026-05-09 | **Scheduler 기반 정기 Post-Submit Sync** | [post_submit_sync_scheduler_loop.md](plans/post_submit_sync_scheduler_loop.md) | `OrderQuery.statuses` 필드 추가 (filters/memory/postgres). `PostSubmitSyncRunner` + `SyncCycleResult` batch runner. `run_post_submit_sync_loop.py` scheduler script. Snapshot refresh callback 연결. 8개 신규 테스트. 19/19 테스트 통과. |
| 2026-05-09 | **WebSocket 기반 실시간 Order Event 수신** | [post_submit_sync_ws_event.md](plans/post_submit_sync_ws_event.md) | `RealTimeEventLoop.__init__()`에 `sync_service`/`account_ref`/`snapshot_refresh_cb` optional param 추가. `_handle_fill_notification()`에 WS-triggered sync (debounce 5s + fire-and-forget) 추가. 기존 10개 + 신규 5개 테스트 통과. polling fallback 유지. |
| 2026-05-09 | **Pipeline Phase 5.5 Post-Submit Sync 연동** | [pipeline_phase55_post_submit_sync.md](plans/pipeline_phase55_post_submit_sync.md) | `assemble_and_submit()` Phase 5.5: SUBMITTED만 호출, timeout 5s, 결과는 SubmitResult와 무관. WS/polling 공존. `_PHASE55_SYNC_TIMEOUT` 상수. `__init__()`에 `sync_service`/`snapshot_refresh_cb` optional param. 신규 테스트 7개 (호출/인자/timeout/exception/REJECTED skip/RECONCILE_REQUIRED skip/backward compat/콜백 전달). 36/36 테스트 통과. |
| 2026-05-09 | **Snapshot refresh 직접 통합** | [backlog_21_snapshot_refresh_integration.md](plans/backlog_21_snapshot_refresh_integration.md) | 세 경로 refresh 조건 통일(FILLED+status_changed+fills_synced>0). WS 직접 refresh 경로(`_filled_refresh_fired` dedup). SyncCycleResult.snapshots_refreshed 집계. runner summary log. 신규 테스트 6개(order_sync 3 + event_loop 3). 40/40 테스트 통과. |
| 2026-05-09 | **Snapshot Staleness Guardrail (Phase 5) — Account-Level Freshness** | [account_level_snapshot_freshness.md](plans/account_level_snapshot_freshness.md) | Run-level → Account-level freshness 정밀화. `AccountSnapshotFreshness` dataclass. `_check_account_snapshot_freshness()` private method. `STALE_SNAPSHOT_ACCOUNT` vs `STALE_SNAPSHOT` rule code 분리. Zero-position account policy. 6개 신규 테스트. |
| 2026-05-09 | **Replay/Backtest Validation 고도화 (Backlog Item 2)** | [replay_backtest_validation.md](plans/replay_backtest_validation.md) | `ReplayBundle` dataclass + `_build_repos()` factory + `_make_stub_fdc()` factory. 5개 parametrize 시나리오 (happy_buy/reduce/exit/stale_guard/cash_constraint). 2-run identity 검증. `replay_test_harness.py` 공유 모듈. `replay_verification.py` 운영 검증 스크립트. 19/19 replay 테스트 + 검증 스크립트 5/5 통과. |
| 2026-05-09 | **Paper Continuous Decision Loop (Backlog Item 1)** | [paper_continuous_decision_loop.md](plans/paper_continuous_decision_loop.md) | `scripts/run_paper_decision_loop.py` 신규 생성. 300s 간격, `--count`, `--dry-run`, `--submit`, `--interval`, `--output json` CLI. `_seed_if_empty` + seed constants 재사용. `get_sync_health_summary()` pre-check. cycle/aggregate summary. asyncio.Event graceful shutdown. `postgres_runtime` per-cycle. 17/17 단위 테스트 통과. `verify_paper_loop.py`와 역할 분리 (검증 vs 운영). |
| 2026-05-09 | **Event Ingestion Loop (외부 이벤트 수집 운영 데몬)** | [paper_trading_loop_validation.md](plans/paper_trading_loop_validation.md) | `scripts/run_event_ingestion_loop.py` 신규 생성. `_build_polling_workers()` 재사용. 60s 간격. source isolation. cycle/aggregate summary. graceful shutdown. ~14개 단위 테스트. |
| 2026-05-09 | **Paper PnL / Performance Summary** | [paper_performance_summary.md](plans/paper_performance_summary.md) | `PerformanceSummaryService` + `calc_realized_pnl_for_order()`/`calc_unrealized_pnl_from_positions()`/`calc_position_market_value()` pure functions. `AccountPerformanceSummary`(12 fields)/`StrategyPerformanceSummary`(7 fields) dataclasses. `GET /performance-summary` API. 18개 신규 테스트. 563/563 기존 테스트 회귀 없음. |
| 2026-05-09 | **Paper PnL History / Trend** | [paper_performance_history.md](plans/paper_performance_history.md) | `DailyPerformancePoint`(7 fields) + `_calc_per_fill_pnl()`/`_latest_cash_on_or_before()`/`_latest_positions_on_or_before()` pure helpers + `get_daily_history()` service method. `GET /performance-history` API. `CashBalanceSnapshotRepository.list_by_account()` contract/memory/postgres. 15개 신규 테스트(Pure helper 3 + snapshot selection 7 + service integration 5). 33/33 테스트 통과. |
| 2026-05-09 | **Paper Performance Metrics** | [paper_performance_metrics.md](plans/paper_performance_metrics.md) | `PerformanceMetrics` dataclass(17 fields) + `_calc_equity_metrics()`/`_calc_win_loss_metrics()` pure helpers. Cumulative return/drawdown/win-rate/avg-win-avg-loss/profit-factor. Per-order 기준 win/loss 정책. `get_performance_metrics()` service method. `GET /performance-metrics` API. 10개 신규 테스트 (6 pure + 4 통합). 44/44 + 86/86 테스트 통과. |
| 2026-05-09 | **Paper Benchmark Comparison** | [paper_benchmark_comparison.md](plans/paper_benchmark_comparison.md) | `BenchmarkComparison` dataclass(13 fields) + `BenchmarkPriceRepository` Protocol + `InMemoryBenchmarkPriceRepository` + `_calc_benchmark_metrics()` pure function. Portfolio metrics reused from `PerformanceSummaryService`. `GET /performance-benchmark` API (4 required + 1 optional query params). 10개 신규 테스트 (5 pure + 5 통합). 54/54 + 96/96 회귀 없음. |
| 2026-05-09 | **Paper Go/No-Go Gate** | [paper_go_no_go_gate.md](plans/paper_go_no_go_gate.md) | 성과/안정성/운영 3축 자동 판정 Gate. `PAPER_GATE_*` env 6개 threshold. `PaperGateService.evaluate()` 8개 check (return/drawdown/excess_return/win_rate/filled_orders/snapshot_freshness/sync_failures/blocking_locks). `GET /performance/paper-go-no-go` API. 7개 신규 테스트 (GO/HOLD/NO_GO 각각 + benchmark 분기). 전체 회귀 없음. |
| 2026-05-09 | **테스트 스위트 정상화 — pre-existing 2 failed / 14 errors 제거** | [fix_pre_existing_test_failures.md](plans/fix_pre_existing_test_failures.md) | `runtime/bootstrap.py`에 `ensure_schema` import 누락 수정. `test_settings.py`에 `KIS_WS_URL` env cleanup 누락 수정. `tests/services/` 589/589 all green 달성. |
| 2026-05-09 | **Paper Exit Criteria — 3층 평가 체계** | [paper_exit_criteria.md](plans/paper_exit_criteria.md) | Layer A: PaperGateService 재사용(8개 check) + health/readyz. Layer B: pytest/script subprocess(B1-B3), snapshot sync health(B4). Layer C: 18개 manual checklist. 평가 CLI 4개 output mode(text/JSON/manual-template). 8개 테스트 시나리오(PASS/HOLD/FAIL). |
| 2026-05-09 | **Paper/Live Mode Boundary 정리 — 동일 시스템 + 설정 스위치 구조** | [mode_boundary_paper_live.md](plans/mode_boundary_paper_live.md) | 4분류 inventory(공통/env-specific/paper-only/paper-named-but-common). mode switch checklist 9항목. 설계 문서 mode-agnostic 표기 정리. **대규모 rename/refactor 없이 최소 변경으로 high-signal 정리.** |
| 2026-05-09 | **Live Gate / Canary Readiness (Phase 3)** | [live_gate_canary_readiness.md](plans/live_gate_canary_readiness.md) | Paper Exit 재사용 + live-specific 8개 auto check + 6개 manual checklist. `LiveGateEvaluator`(PaperExitEvaluator wrapping). 5개 신규 env thresholds. `_determine_overall()` 5 static rules. CLI 4개 출력 모드 + exit code. 10개 테스트(unit 6 + integration 4). 설계 문서 + settings.py + evaluate_live_gate.py + test_evaluate_live_gate.py. |
| 2026-05-09 | **Phase 2 Inspection API Expansion (Backlog #5, #6, #7)** | [phase2_inspection_api_expansion.md](plans/phase2_inspection_api_expansion.md) | `GET /agent-runs/{id}` detail endpoint. `GET /guardrail-evaluations` (list + detail + 3 filter params). `GET /risk-limit-snapshots` (list + /latest). `GuardrailEvaluationRepository.get()/list_by_account()` protocol + InMemory + Postgres. `AgentRunRepository.get()` protocol + InMemory + Postgres. `GuardrailEvaluationView`/`RiskLimitSnapshotView` Pydantic schemas. 신규 테스트 16개 (in-memory 9 + Postgres smoke 5 + 기존 수정 2). 총 53/53 테스트 통과. |
| 2026-05-09 | **Postgres BrokerOrderRepository.update() (Backlog #16)** | [postgres_broker_order_update.md](plans/postgres_broker_order_update.md) | `PostgresBrokerOrderRepository.get()` + `update()` 구현. 동적 SET clause SQL UPDATE. `updated_at` 항상 갱신. `ValueError` on not found (InMemory 일관성). `OrderSyncService` 3개 호출 지점 Postgres 경로 안전. 5개 신규 Postgres 테스트 추가. |
| 2026-05-10 | **FillEvent broker_fill_id + fill dedup 강화 (Backlog #18)** | [broker_fill_id_dedup.md](plans/broker_fill_id_dedup.md) | `FillEvent.domain`에 `broker_fill_id` 추가. `FillEventRepository.get_by_broker_fill_id()` Protocol/InMemory/Postgres 구현. `OrderSyncService._sync_fills()` two-tier dedup(broker_fill_id 우선 → 4-field composite fallback). KIS REST CCLD_NUM 매핑 + 기존 생성자 버그 수정. 8개 신규 테스트 전부 통과. |
| 2026-05-10 | **Benchmark Daily Relative Trend** | [benchmark_relative_trend.md](plans/benchmark_relative_trend.md) | `GET /performance-benchmark-history` 신규 엔드포인트. `RelativeBenchmarkPoint`(9 fields) + `_calc_relative_benchmark_points()` pure function + `get_benchmark_daily_history()` service method. 14개 pure + 5개 integration 테스트(29/29 통과). 설계 문서 6개 보정사항 반영(필드 고정/streak 규칙/기준선 선택/보간 금지/drawdown 부호/API 정책). 기존 API 회귀 없음(53/53 inspection API 테스트 통과). |
| 2026-05-10 | **Performance Metrics 심화 — Sharpe / Sortino / Calmar** | [paper_performance_risk_adjusted_metrics.md](plans/paper_performance_risk_adjusted_metrics.md) | `PerformanceMetrics` dataclass + `PerformanceMetricsView` schema에 3개 field 추가(sharpe_ratio/sortino_ratio/calmar_ratio). `_calc_sharpe_sortino()` pure helper. `get_performance_metrics()` step 5 통합. 비연율화(raw daily) 고정, rf=0. Sortino 음수 수익률 m>=2 조건. Calmar max_drawdown=0 → None. 12개 신규 테스트(pure 6 + service 3 + API 3). 53/53 performance + 56/56 inspection API 통과. |
