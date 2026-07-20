# 근본 설계 검토 — 목표·소싱·신호·백테스트 정합성 분석

작성일: 2026-07-14
성격: 결정 기록(decision record) — 여러 문서(universe policy / entry_score /
core_risk_off / signal_backbone)에 걸친 교차 진단. 이 문서는 향후 작업이
"잘못된 레버"를 다시 당기지 않도록 근본 사실을 고정하기 위한 기준점이다.

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: 최고 기대수익률을 손실 제약 아래의 목적함수로 재정의하고,
  `2026-06-25` 이후 BUY 주문 0건의 DB funnel 실측과 `entry_score` 직접 병목,
  신호 검증부터 제한적 probe까지의 후속 순서를 반영했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: SPPV-2(신호 예측력 확장 검증) 완료 결과를 반영해 2순위를
  완료로 갱신하고, quintile spread 정체(시장 베타 vs 알파) 진단을
  2.5순위로 신설, 3순위(entry_score 재현)를 조건부 보류로 재분류했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: SPPV-2.5(quintile spread 정체 진단) 완료 결과를 반영 — pooled
  유의성이 국면 혼입 착시일 가능성이 높다는 결론을 2.5순위에 기록하고,
  3순위(entry_score 재현) 착수 조건을 "표본 확장 후 국면 내부 유의성
  재확인"으로 구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (3차, 사용자 지적 반영)
- 수정내용: **SPPV-2.5의 "국면 혼입 착시" 결론을 방법론 오류로 폐기**했다.
  `regime_label`이 시장이 아니라 종목 자신의 신호로 판정되는 라벨이었음을
  코드로 재확인했고, KODEX 200 벤치마크 기준 재검증(SPPV-2.6)에서 그
  결론이 반박됨을 확인했다. 2.5순위를 2.6순위로 확장·교체하고, 3순위 보류
  사유를 "국면 혼입 의심"에서 "하락장 표본 부재"로 교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (4차)
- 수정내용: **SPPV-2.6의 "알파 근거 강화" 결론을 다시 하향 조정**했다.
  벤치마크(069500)를 평가 universe에서 제외하고 조회 기간을 3년으로
  확장(SPPV-2.7)해 실제 하락장 표본(96거래일)을 확보한 결과, pooled
  유의성이 소멸하고 하락장에서는 신호 방향이 역전/역방향으로 나타났다.
  2.6순위를 2.7순위로 확장·교체하고, 3순위 보류 사유를 "신호 feature
  재설계 검토 필요"로 재교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (5차, 검증 기간 재설계)
- 수정내용: 이 시스템이 3개월 이하 중단기 공격형이라는 전제로 **SPPV
  검증 기간 기준을 재설계**했다(SPPV-2.8). 3년 pooled를 기본값으로 두지
  않고, 최근 12개월을 1차(primary) 기본 창, 3년(SPPV-2.7 재사용)을 국면
  커버리지 2차(supplementary) 게이트로 분리했다. 기존 3년 캐시로 최근
  12개월을 실측한 결과 하락장 거래일이 0일이라 1차 창만으로는 필수 국면
  게이트를 통과할 수 없음이 확인됐고, 1차 pooled 유의성도 없었다(§14의
  보류 판정은 유지). 2.7순위 뒤에 2.8순위를 신설했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (6차, 실행 증빙 재검증)
- 수정내용: SPPV-2.8의 실행 증빙을 재검증한 결과, 최초 저장했던 실행
  로그가 실제로는 호스트 python 환경의 `dotenv` 미설치로 즉시 실패한
  트레이스였고, JSON 산출물은 (호스트가 아닌) 컨테이너에서 만든 진짜
  결과였으나 그 실행의 정상 로그가 남지 않았던 증빙 결함을 발견했다.
  컨테이너에서 재실행해 stdout을 로그로 캡처한 결과, 종료 코드 0/`HTTP
  Request:` 0건/최근 12개월 bearish_trend 0일/`overall_score` T+20
  t_NW=1.18 전부 동일하게 재현됨을 확인했다 — 결론과 판정은 변경 없이
  증빙만 보강했다. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §16.6.

- 작성자: Claude
- 수정일자: 2026-07-14 (7차, 신호 feature 재설계 검토 — SPPV-2.9)
- 수정내용: §14.5가 지시한 **신호 feature 재설계 검토를 실제로 수행**했다.
  `fast_score`/`slow_score`의 6개 sub-component를 분해 실측하고 신규 후보
  feature(`risk_adj_momentum_3m`, `reversal_1m`)를 §16 이원 기준으로
  검증했다. **`rsi_signal`이 T+20에서 유의하게 역방향(t_NW=-2.94)임을
  특정 — `fast_score` 실패 원인 중 하나로 확인.** `risk_adj_momentum_3m`
  (변동성 조정 모멘텀)은 3년 pooled 유의(t_NW=2.07) + 하락장 역전 없음
  으로 유일한 Watch 후보이나 1차 창 유의성 미달로 완전한 Go는 아니다.
  SPPV-3 착수는 계속 보류하되 구체적 다음 과제(`rsi_signal` 제거/반전한
  `fast_score_v2` 검증, `risk_adj_momentum_3m` 재검증)를 확정했다. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §17.

- 작성자: Claude
- 수정일자: 2026-07-14 (8차, §17.5 후속 3과제 — SPPV-2.10)
- 수정내용: §17.5가 지시한 후속 3과제를 실제로 수행했다. **`fast_score_v2`
  (rsi_signal 제거/부호반전) 두 변형 모두 No-Go** — 하락장 T+5 spread가
  원안(t_NW=-2.79)과 거의 동일하게 역전(drop -2.41, flip -2.32)돼
  `rsi_signal`이 부분 원인일 뿐 주된 원인이 아니었음을 재확인, §17의
  낙관적 프레이밍을 하향 조정한다. `risk_adj_momentum_3m`은 1차 창을
  18개월로 넓히자 T+20 t_NW=2.03으로 §16 게이트를 겨우 통과했으나 T+5는
  여전히 미달인 marginal 결과라 "Watch 유지, 조건부 상향"에 그친다.
  `reversal_1m`은 하락장 표본 반분 검증에서 방향은 일관되나(전반 1.87/
  후반 1.33) 개별 유의 문턱 미달로 Hold 유지. SPPV-3 착수는 계속 보류.
  상세는 `plans/[DESIGN] signal_predictive_power_validation.md` §18.

- 작성자: Claude
- 수정일자: 2026-07-14 (9차, §18.6 후속 — SPPV-2.11)
- 수정내용: §18.6이 지시한 세 과제를 실행했다. **`fast_score`
  leave-one-out 4종 분해 결과, `fast_trend`(SMA20 이격) 제거 시 하락장
  T+5 spread가 -2.79→-1.60(비유의 전환)으로 가장 크게 개선 — §17/§18에서
  `rsi_signal`을 원인으로 지목한 것을 정정, 주된 원인은 `fast_trend`
  였음을 확인.** `risk_adj_momentum_3m`은 15~21개월 창에서 T+20
  t_NW=1.90→2.03→2.04로 안정적 plateau를 보여 18개월 결과가 우연이
  아님을 확인했으나 여전히 marginal. 국면 전환형 shadow 후보 `regime_
  switch_v1`(비하락장=risk_adj_momentum_3m, 하락장=reversal_1m)을 신설,
  2차(3년) pooled T+5=2.60/T+20=2.36으로 트랙 최고 수치를 냈으나
  1차(최근 12개월)는 하락장 표본 부재로 여전히 미달 — 가장 유망한 Watch
  후보로 격상하되 확정 Go는 아니다. SPPV-3 착수는 계속 보류. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §19.

- 작성자: Claude
- 수정일자: 2026-07-14 (10차, §19.6 후속 — SPPV-2.12)
- 수정내용: §19.6이 지시한 두 과제를 수행했다. `regime_switch_v1` 1차
  게이트 예외 규칙 3개를 비교한 결과, **적응형 최소창(규칙 C)이 n=30
  에서 t_NW=4.18로 급등하지만 n=48(규칙 B)에서는 1.33에 불과해 데이터
  스누핑 산물로 판정, 채택을 거부**했다. 규칙 B(고정 48일)는 정직한
  재검증에서도 미달(1.33~1.61) — **규칙 A(관찰 유예, 하락장 재발 시
  자동 재검증)를 유일하게 채택**한다. fast 계열 신규 feature 2종
  (`rsi_mean_reversion`, `sma5_over_sma20_gap`) 모두 범용 대체 후보로
  No-Go — 전자는 하락장 전용(`reversal_1m`과 동일 패턴), 후자는
  SMA20과 동일하게 하락장에서 역전. SPPV-3 착수는 계속 보류. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §20.

- 작성자: Claude
- 수정일자: 2026-07-14 (11차, §20.5 후속 — SPPV-2.13/2.14)
- 수정내용: `regime_switch_v1`의 규칙 A(관찰 유예)를 실제 실행 가능한
  모니터링 스크립트(`scripts/monitor_regime_switch_v1_gate.py`)로
  구현·실행했다 — 판정 결과 `NOT_TRIGGERED`(최근 12개월 bearish_trend
  0일), §20 판단과 일치. "절대 가격 수준"에 의존하지 않는 완전 신규
  fast 계열 feature 2종(`money_flow_5d`=자금 흐름, `relative_
  strength_rank_1m`=cross-sectional 상대강도)을 실측 — 둘 다 pooled/
  1차 유의성 없이 범용 대체 후보로 No-Go. `relative_strength_rank_1m`
  은 하락장에서 유의하게 역전(t=-2.13)해, 시장 베타를 제거한 상대강도
  조차 하락장에서는 반대로 작동한다는 더 강력한 규칙성을 재확인했다.
  SPPV-3 착수는 계속 보류. 상세는
  `plans/[DESIGN] signal_predictive_power_validation.md` §21, §22.

- 작성자: Claude
- 수정일자: 2026-07-15 (12차, 국면별 신호 극성 종합 및 상위 방향 확정)
- 수정내용: SPPV-2.9~2.14에서 산출된 10개 신호를 **국면별 신호 극성
  전환 종합표**로 통합했다(별도 문서 `plans/[ANALYSIS] sppv_regime_
  polarity_synthesis_and_next_direction.md`). 8/10 신호가 "추세형=
  상승/횡보 전용, 되돌림형=하락장 전용" 규칙성을 따르고(`rsi_signal`만
  상승장 역전 예외), 절대·상대·오실레이터·거래량·복합 5개 축을 모두
  시도해 매번 같은 결론에 수렴했다는 근거로 **feature 추가 실험을
  중단하고 국면 분기형 entry 설계 검토로 전환**하기로 판정했다.
  유니버스/미시구조 재검토는 §2의 "신호 미검증 시 잘못된 레버" 원칙에
  따라 후순위로 유지한다. SPPV-3의 다음 착수 형태는 `regime_switch_v1`
  아이디어를 entry_score 대체 설계 원형으로 삼는 것으로 재정의된다.

- 작성자: Claude
- 수정일자: 2026-07-15 (13차, 국면 분기형 entry 설계 초안 + shadow 계산기)
- 수정내용: 위 12차 판정을 실제 설계 문서로 구체화했다 — 신규 문서
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md`에 국면별 신호
  선택 매트릭스(비하락장=`risk_adj_momentum_3m`, 하락장=`reversal_1m`,
  판정불가=신호 미산출), `entry_score` alpha layer(0.80 가중치 블록)
  교체 제안(미적용), shadow 검증 Phase 1/2 계획을 작성했다. shadow
  계산기를 실행해 실시간(2026-07-14 기준) 스냅샷을 산출 — 시장 공통
  국면 `range_bound`로 87/87종목이 `risk_adj_momentum_3m` 분기를
  사용했고 하락장 분기는 미발동(§21 모니터링과 정합). `entry_score`
  코드/운영 변경 없음 — 설계·shadow 단계에 머문다.

- 작성자: Claude
- 수정일자: 2026-07-15 (14차, regime_conditional_signal Phase 2 shadow
  누적 사이클 구축)
- 수정내용: `regime_conditional_entry_signal_v1.md` §4.2의 Phase 2를
  실제 실행 가능한 오케스트레이터(`scripts/run_regime_conditional_
  shadow_cycle.py`)로 구현했다 — 게이트 판정(§21)과 신호 계산(§22)을
  벤치마크 bars 1회 조회로 통합, 누적 이력 파일(JSONL, append-only,
  거래일당 1줄, 중복 거래일 자동 skip)을 구축, `TRIGGERED` 전환 시
  재검증 절차(runbook)를 화면에 출력하도록 했다(자동 재검증은 하지
  않음). **실행 결과: 게이트 NOT_TRIGGERED(bearish_trend 0일), 신호
  2026-07-14 기준 `range_bound`로 87/87종목 `risk_adj_momentum_3m`
  분기 산출 — 이력에 1줄 추가.** 즉시 재실행해 중복 방지 로직이 정상
  발동함을 확인했다. `entry_score` 코드/운영 변경 없음. 상세는
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §6.

- 작성자: Claude
- 수정일자: 2026-07-15 (15차, entry_score 중복 penalty ablation 실측)
- 수정내용: SPPV-3 착수 전제인 "중복 억제 구조 재현·분해"를 실제
  실측으로 구체화했다(`regime_conditional_entry_signal_v1.md` §8).
  운영 함수(`_build_entry_score`, `_assess_buy_eligibility`)를 그대로
  호출해 세 penalty 축(entry_score regime penalty / eligibility
  regime 차단 / eligibility signal floor)을 오늘(87종목) 기준
  독립 평가한 결과, **B(60건)가 발동한 모든 종목에서 A·C도 예외 없이
  함께 발동(A∩B∩C=60=B 전체)** — 본 문서 §2의 "삼중 중복" 지적이
  오늘 데이터로 100% 재현됨을 확인했다. 종목별(per-symbol) regime_
  label(bearish_trend 69%)이 시장 공통 국면(`range_bound`)과 전혀
  다르다는 점도 재확인했다(§2에서 이미 코드로 지적한 문제가 운영
  코드에 여전히 남아있음). `entry_score`에 `regime_conditional_
  signal`을 통합하려면 국면 정의(종목별 vs 시장 공통) 통일이 새로운
  전제로 필요함을 발견했다. 운영 DB(`trade_decisions`) 직접 조회는
  이번 턴에 시도하지 않았다(자동 승인 경계 밖). 상세는
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §8.

- 작성자: Claude
- 수정일자: 2026-07-15 (16차, 중복 억제 시계열 누적 + 국면 정의 비교
  체계 구축)
- 수정내용: §8의 하루치 관찰을 시계열 누적 절차로 승격했다 — 신규
  오케스트레이터(`scripts/run_entry_score_penalty_ablation_cycle.py`)
  가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행에서 계산해 누적
  이력(중복 거래일 자동 skip)에 기록한다. **실행 결과: §8과 완전히
  동일한 수치(A=85/B=60/C=75/A∩B∩C=60)로 교차 검증됐고, 국면 일치
  18건/불일치 69건(79%)** — 그중 "시장 비하락장인데 종목별 하락장"
  60건. 재실행으로 중복 방지 로직 정상 발동을 확인했다. SPPV-3
  본작업용 비교 실험(현행 종목별 정의 vs 시장 공통 정렬, §16 이원
  기준 재사용)을 설계 문서 §9.6에 구체화했다. `entry_score` 코드/
  운영 변경 없음. 상세는 `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §9.

- 작성자: Claude
- 수정일자: 2026-07-15 (17차, §9.6 비교 실험 실측 — 종목별 vs 시장
  공통 regime 정의)
- 수정내용: §9.6에서 설계한 실험을 실제로 실행했다. 3년 rolling
  표본(87종목, 56,753건)에 운영 함수 `_assess_buy_eligibility()`를
  그대로 호출해 변형 A(종목별 regime)와 변형 B(시장 공통 regime)
  각각의 통과군 T+5/T+20 forward return을 비교한 결과, **변형 B가
  통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의 forward return은
  더 높았다(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%, 둘 다 baseline
  대비 유의, t_NW 7.3~7.7)** — "더 적게, 더 좋은 것만" 통과시키는
  방향으로 나타나 과잉 억제가 아니라 정밀한 억제일 가능성을 뒷받침
  한다. 다만 A-B 차이의 직접 유의성 검정은 하지 않았고, 통과군
  내부에서도 `overall_score` quintile spread가 여전히 유의하게
  역전(T+20 t_NW=-2.84~-3.06)해 **판정은 Watch(조건부 유리, 확정
  Go 아님)로 유지**한다. 이번 실행의 실제 KIS 호출 여부는 가정하지
  않고 로그로 확인 — `HTTP Request:` 0건(3년 캐시 완전 재사용). 상세는
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §10.

- 작성자: Claude
- 수정일자: 2026-07-15 (18차, A/B 판정 불일치 표본 direct 비교 + 1차
  창 재확인)
- 수정내용: §10.5의 두 과제를 실행했다. 같은 종목-거래일 표본을
  `A_only`/`B_only`/`both`/`neither` 4개 배타적 집합으로 분해한 결과,
  **`B_only`가 3년·최근 12개월 모두에서 정확히 0건임을 확인** —
  시장 공통 정의(B)는 종목별 정의(A)의 진부분집합(strict subset)이며
  새 종목을 발굴하는 효과 없이 A가 통과시킨 것 중 일부(`A_only`,
  3년간 1,072건)를 추가로 차단할 뿐이다. `A_only`의 forward return은
  방향상 음수(T+5 -0.17%, T+20 -0.70%)이나 통계적으로 유의하지
  않았다(|t_NW|<1). 최근 12개월 창은 A-B 차이 자체가 없음을 확인(§21
  모니터링과 정합). **판정: Watch 유지(No-Go에 근접), 시장 공통
  정의로의 확정 전환은 기각한다.** 이번 실행의 KIS 호출 여부도 가정
  없이 로그로 확인 — 0건. 상세는 `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §11.

- 작성자: Claude
- 수정일자: 2026-07-15 (19차, alpha layer vs regime_conditional_signal
  직접 비교)
- 수정내용: 무게중심을 "국면 정의 통일"(차단 축)에서 "alpha layer
  교체"(선별 축)로 옮겼다. 현행 `entry_score`의 alpha layer(순위상
  `0.45·overall+0.20·fast+0.15·slow`와 동일함을 코드로 확인)와
  `regime_conditional_signal`을 같은 3년 rolling 표본에서 직접
  비교한 결과, **2차(3년) 창에서 `regime_conditional_signal`이
  T+5(t_NW=2.52)/T+20(t_NW=2.33) 둘 다 유의한 반면 현행 alpha
  layer는 어디서도 유의하지 않았다(1.02~1.39)** — spread·t값·양수
  비율 4개 관측치 전부에서 일관되게 우세했다. 1차 창은 미달이나
  §21의 구조적 이유(하락장 부재)임을 재확인 — **판정: Conditional
  Go(2차 검증 통과, 1차 게이트 전환 대기)로 명시했다** — Watch로
  낮추지 않되 억지로 완전한 Go도 선언하지 않았다. 실행 로그로 KIS
  호출 0건 확인(가정 없이 실측). 상세는 `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §12.

- 작성자: Claude
- 수정일자: 2026-07-15 (20차, 새 alpha 상위군과 기존 차단 축 결합
  효과 검증 — 가장 빈번한 차단 사유 재발견; **당시 해석은 이후
  2.24순위/§14 ablation으로 보정됨**)
- 수정내용: `regime_conditional_signal`을 새 alpha로 넣었을 때 기존
  차단 로직이 그 효과를 상쇄하는지 검증한 결과, 상위 20% 표본의
  68.3%(3년)/61.1%(최근 12개월)가 차단됐으나 **차단된 표본도 forward
  return이 강하게 유의하게 양(+)**이었다(생존군과 큰 차이 없음).
  실패 사유를 집계한 결과 **본 문서 §2에서 지적한 regime 관련 축이
  아니라, 국면·신호와 무관한 순수 유동성 게이트
  `eligibility_low_relative_activity`(거래량/거래대금 급증 비율
  <1.10 차단)가 차단의 압도적 대부분(3년 79.7%, 최근 12개월 99.6%)
  을 차지함을 새로 발견했다** — §2의 regime 삼중 중복은 오히려
  부차적이었다(3년 20.3%, 최근 12개월 0.4%). **판정: alpha 자체는
  Conditional Go 유지, 결합 시나리오는 Watch(활동성 필터 ablation
  검증 필요).** SPPV-3 다음 최우선 조사 대상을 "국면 정의 통일/
  regime penalty"에서 "활동성 필터 재검토"로 재조정했다. 실행 로그로
  KIS 호출 0건 확인(가정 없이 실측). 상세는 `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §13.

---

## 0. 이 문서가 나온 배경

- 최근 수 주간 "주문 0건" 문제를 두고 소싱(universe sourcing) 개선(UNIV-1~5),
  freeze 타이밍, F5 필터 등 여러 표면 작업을 진행했으나, 2026-07-14 실측에서
  **오늘 편입된 19개 종목 전체의 `entry_score`가 매수 threshold(0.65)에 단
  하나도 근접하지 못함**(1위 001450=0.5749)을 확인했다.
- 이로써 "소싱을 아무리 넓혀도 주문은 계속 0건일 것"이라는 지적이 제기됐고,
  근본 설계 3개 질문에 대한 문서 기반 재검토를 수행했다.

### 0.1 BUY 0건 운영 실측 기준선

2026-07-14 운영 DB를 `2026-06-25` 이후 `symbol + trade_date` 첫 decision으로
중복 제거해 재검증했다.

| 항목 | 실측 |
|---|---:|
| 표본 | 297건 |
| `entry_score >= 0.52` | 24건 |
| `entry_score >= 0.65` | 0건 |
| `BUY_CANDIDATE` | 0건 |
| eligibility 통과 | 21건 |
| `risk_off_penalty` 적용 | 294건 |
| 최대 / 평균 `entry_score` | 0.6086 / 0.1699 |
| BUY 주문요청 / broker submit | 0건 / 0건 |

마지막 BUY 주문은 `2026-06-24`다. 정확히는 약 20일, 거래일 기준 약 14일의
BUY 0건 상태이며, 기간 표현과 별개로 매 거래일 최고 점수조차 threshold를
넘지 못한 것은 공격 목표와 진입 산식의 구조적 충돌을 뜻한다. eligibility
통과 21건도 후보가 되지 못했으므로 이 기간의 직접 병목은 하류 expected
value/compliance/broker가 아니라 `entry_score < 0.65`다.

---

## 1. 세 가지 근본 질문과 검토 결론

### Q1. "최고 기대수익률을 낼 종목을 찾는 작업"이 제대로 설계됐나?
**결론: 아니오 — 애초에 그렇게 설계된 적이 없다.**

- core universe 선정 기준은 ① `metadata.core_universe` 플래그 ② KOSPI100/200
  지수 편입 ③ 하드코딩 allowlist 90종목뿐(`universe_selection.py`
  `_is_core_seed_instrument`, `core_universe_seed.py`).
  `[POLICY] trading_universe_policy_v1.md` §4.1이 든 근거는 "유동성 충분 /
  슬리피지·노이즈 감소"로 **순수 방어적**이다.
- `[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`가 스스로
  **"core 레이어는 100% 가격/모멘텀 무관, 수익률·추세 신호가 어디에도 없다"**
  고 인정한다.
- "최고 기대수익률(highest expected return)" 목표는 universe/selection
  정책 문서 어디에도 **없다**. KPI는 포함률·소요시간·전환율 등 운영 지표다.
  ("최고 기대수익률" 문구는 `[DESIGN] expected_return_holding_horizon_and_
  churn_control_refactor.md`에만 등장하며, 그마저 churn 제어·보유기간
  정렬 목적이다.)
- 기대수익률(`expected_value_gate`)은 존재하나 **이미 선정된 종목을 걸러내는
  사후 게이트**일 뿐, 소싱 단계에 피드백하지 않는다. alpha 탐색 장치는
  Layer 4 market-driven overlay 하나뿐이며 현재 하루 0~1종목 수준이다.

### Q2. 종목을 찾는 방식 전반의 설계가 합당한가?
**결론: 목표에 따라 정반대다.**

- 목표가 **"자본 보전 + paper 안전 검증"**이면 → 합당하다. 방어적으로 잘
  작동한다.
- 목표가 **"최고 기대수익률"**이면 → 부적합하다. 결정적 이유는 신호 체계:
  - `slow_score`(=0.6·slow_momentum+0.4·slow_trend), `fast_score`,
    `entry_score`는 전부 **과거 가격의 추세·모멘텀 상태를 기술하는 룰 기반
    지표**이지, 미래 수익률을 예측하도록 만든 지표가 아니다
    (`signal_backbone.py` `_score_return_3m`/`_score_price_vs_ma` 등 계단식
    상수 매핑).
  - 가중치(0.6/0.4, 0.55/0.45, entry_score 0.45/0.20/0.15, ranking
    0.55/0.10/0.20…)는 전부 **백테스트 근거 없는 하드코딩 매직 넘버**다.
  - `regime_label`(bearish_trend)·`risk_tone`(risk_off)도 **시장 지수가
    아니라 개별 종목의 과거 가격 feature + 하드코딩 임계값**으로 판정된다
    (`market_regime.py` `classify_market_regime`).

### Q3. entry_score / risk_off가 백테스트로 충분히 검증됐다고 결론지어도 되나?
**결론: 아니오 — 검증된 명제는 "이번 하락 국면에서 매수 억제가 옳았다"뿐이다.**

- **표본이 단일 하락 국면에 집중**: 최장 6주(2026-06-01~07-10), 핵심 분석은
  약 2주(2026-06-27~07-10), 일부는 3~4거래일. active 표본 20건 평균
  `return_3m_pct=-30.49%`, `slow_trend=-0.8`이 20/20. **상승장·횡보장
  표본 전무.**
- **실집행 백테스트가 아니다**: 문서 스스로 "체결 기반 정식 백테스터가
  아니라 후행 수익률 proxy 기반 shadow 실측"이라 명시
  (`[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`).
  전 구간 `would_buy=0`, `submitted=0`.
- **핵심 결론의 표본이 빈약**: deep_negative vs inactive가 N=49 vs 155
  (재집계 N=35 vs 64), signal_backbone N=40 vs 165. 완화 후보군은
  N=3~4까지 축소되며 leave-one-out에서 T+3 수익률이 +0.85%↔-3.78%로
  부호가 뒤집힘("안정적 우위 아님"이라고 문서가 인정).
- **문서 스스로 검증 대상을 "하락장 방어"로 규정**했다. 어떤 항목도
  authoritative로 승격하지 않았고 "shadow-only 유지"를 반복 명시했다.

> ⚠️ **중요 경계**: 이전 세션에서 "매수 0건은 옳은 방어 → 완화 영구 중단"으로
> 확정한 것은 **여전히 유효하되, 그 유효 범위는 "이 하락 국면 한정"이다.**
> "모든 시장 국면에서 이 gate가 항구적으로 옳다"로 확대 해석하면 안 된다.
> 상승장/횡보장에서의 타당성은 **검증된 바 없다.**

---

## 2. 근본 원인 진단

지금까지의 "주문 0건" 문제의 표면 증상(소싱 부족, freeze 타이밍, F5 필터)
아래에 있는 **두 개의 진짜 뿌리**:

1. **목표-설계 불일치**: 시스템은 "자본 보전"용으로 설계됐는데 기대는
   "최고 기대수익률"에 있다. 방어 시스템에 공격을 기대한 구조다.
2. **검증되지 않은 신호 체계**: 종목의 좋고 나쁨을 판정하는 점수 자체가
   예측력(미래 수익률과의 상관)을 실증 검증받은 적이 없다. 이 토대가
   검증되기 전에는 gate 완화도 소싱 확장도 모래 위의 집이다.
3. **공격·방어 책임 중복**: 약한 signal이 이미 `entry_score`에 반영된 뒤
   `risk_off_penalty=-0.15`가 다시 차감되고, BUY eligibility가 동일한
   `bearish_trend + risk_off`를 다시 차단한다. 실측 297건 중 294건에 penalty가
   적용돼 리스크 제약이 사실상 상시 진입 금지로 동작했다.

→ 지난 세션의 "소싱 개선(UNIV-1~5)"은 **잘못된 레버**였다. 지금 국면에서
   소싱을 넓혀도 신규 종목 역시 같은 (미검증) entry_score를 거쳐 동일하게
   억눌리므로 주문 발생에 영향이 없다.

---

## 3. 목표 트레이드오프 정리표 (1순위 의사결정용)

시스템의 실제 목표를 확정하지 않으면 후속 작업의 성공 기준 자체가 없다.
두 목표는 정반대의 결론을 낸다.

| 관점 | 목표 A: 자본 보전(Capital Preservation) | 목표 B: 최고 기대수익률(Max Expected Return) |
|---|---|---|
| 현재 시스템 상태 | **이미 완성·정상 작동 중** | **핵심 엔진(검증된 예측 신호) 부재** |
| "주문 0건"의 의미 | 성공(하락장 손실 회피) | 실패(기회 미포착 + 검증 불가) |
| 필요한 다음 작업 | 없음 — 방어 모드 유지·모니터링만 | 신호 예측력 검증부터 재출발 |
| 신호 체계 요구수준 | 현 수준으로 충분(보수적 필터면 됨) | predictive power 실증 필수 |
| 리스크 성격 | 기회비용(안 사서 못 번 수익) | 실현손실 가능(사서 잃을 수 있음) |
| core universe 적합성 | 적합(방어적 대형주) | 부적합(alpha 소스 아님) |
| 완화 금지 원칙 | 그대로 유지 타당 | "국면 한정"이므로 재평가 대상 |

**결정 주체**: 이 선택은 기술 판단이 아니라 운영자(사용자)의 전략적 결정이다.

---

## 3.1 목표 확정 (2026-07-14, 사용자 결정)

> **✅ 목표 B(최고 기대수익률)로 확정.**
>
> 사용자 명시: *"이 시스템의 근본 목적은 최고 기대수익률이다. 기대수익률을
> 높이기 위해서는 아예 손실을 안 보는 것이 아니라, 일정 부분의 손실을
> 감내(손실은 최소화)하면서 투자하는 것이 목적이다."*
>
> 해석 — 목표는 **손실 제약 아래의 net expected return 극대화**다:
> - "주문 0건 = 손실 0"은 **성공이 아니라 실패**다(기회비용 = 미실현 수익).
> - 단, 무분별한 매수가 아니라 **손실을 최소화하면서** 감내 가능한 수준의
>   리스크를 지고 기대수익을 추구한다.
> - 수익률은 1순위 목적함수이고 VaR/drawdown/exposure/liquidity/compliance는
>   감내 불가능한 손실과 위반을 막는 제약조건이다.
> - 따라서 §3 표의 목표 B 열이 이 시스템의 기준이며, "신호 예측력 실증
>   검증"(2순위)이 즉시 착수 대상이 된다.
> - core_risk_off/entry_score 완화 금지 원칙은 "이번 하락 국면 한정"으로
>   그 유효 범위가 축소되며, 다른 국면에서의 타당성은 2순위 검증 결과에
>   따라 **재평가 대상**이 된다(무조건 완화가 아니라, 실증 기반 재설계).

## 4. 권장 진행 순서 (우선순위)

- **0순위(완료, 이 문서)**: 근본 진단 문서화 — 잘못된 레버 재발 방지 기준점.
- **1순위(완료, 2026-07-14)**: 목표 B(최고 기대수익률) 확정 — §3.1 참고.
- **2순위(완료, 2026-07-14 — SPPV-2)**: **신호 예측력 실증 검증** — core
  88종목 × cross-sectional 거래일별 IC × Newey-West 보정 × 국면별 분해
  완료. **결과: 8종목 파일럿(SPPV-1)의 "유의미"~"강함"(t=2.4~4.1)은
  overlap 편향의 산물이었음이 확인됐다** — 정확히 보정하면 전 신호·전
  horizon에서 |t_NW|<1.1로 통계적 유의성 없음. 단, 비용 차감 quintile
  spread(overall_score 기준 +3.88%p)는 방향성 있게 남아 있어 "완전
  무신호"로도 단정하지 않는다. 상세: `plans/[DESIGN] signal_predictive_
  power_validation.md` §9.
- **2.5순위(완료, 2026-07-14 — SPPV-2.5) — ⚠️ 방법론 오류로 결론 폐기**:
  quintile spread 정체 진단 시도. ~~결과: pooled 유의성이 국면 혼입 착시~~
  **오류 확인(사용자 지적): `regime_label`이 시장이 아니라 종목 자신의
  신호로 판정되는 라벨이었다(`market_regime.py:21-38`) — 검정 대상과 같은
  계열 변수로 조건화한 선택 편향.**
- **2.6순위(완료, 2026-07-14 — SPPV-2.6, 방법론 교정) — ⚠️ §2.7에서 표현
  하향 조정**: KODEX 200(069500, 이미 core universe 구성원)을 시장
  벤치마크로 써서 **거래일 단위 공통 국면**과 **초과수익**으로 재검증.
  ~~결과: "국면 혼입 착시" 결론은 반박되고, 최소 상승장 국면에서는 종목
  선택 알파일 가능성이 오히려 높아졌다.~~ **당시엔 벤치마크(069500)를
  평가 universe에도 포함시킨 자기참조 문제와 1년(하락장 0일) 표본
  한계가 있었다 — 아래 2.7순위에서 교정 후 결론이 다시 반박됨.**
- **2.7순위(완료, 2026-07-14 — SPPV-2.7, 자기참조 제거 + 3년 확장)**:
  평가 universe에서 벤치마크를 제외(core 87종목)하고 조회 기간을 3년
  (733일봉)으로 확장 — 시장 공통 국면 96거래일(15%)의 실제 하락장 표본을
  처음으로 확보했다. **결과: `overall_score` pooled spread 유의성이
  §12의 t_NW=2.30에서 **t_NW=1.32로 소멸**했고, 하락장 내부에서는 spread가
  **음수로 역전**(T+5 t_NW=-1.71)하거나 `fast_score`는 하락장에서 **유의
  하게 역방향**(T+5 t_NW=-2.79)이었다.** §2.6의 "알파 근거 강화" 결론은
  과도했음이 확인돼 하향 조정한다 — 안정적인 종목 선택 알파를 찾지
  못했다. 상세: `plans/[DESIGN] signal_predictive_power_validation.md`
  §14(최신 canonical 결론).
- **2.8순위(완료, 2026-07-14 — SPPV-2.8, 검증 기간 기준 재설계)**: 이
  시스템의 "3개월 이하 중단기 공격형" 성격에 맞춰 SPPV 검증의 기간(period)
  기준을 재설계했다 — 3년 pooled를 기본값으로 두지 않고 **최근 12개월을
  1차(primary) 기본 창, 3년(SPPV-2.7 재사용)을 국면 커버리지 확인용
  2차(supplementary) 게이트**로 분리했다. 기존 3년 캐시를 재사용해(신규
  KIS 호출 0건) 최근 12개월 창을 실측한 결과 **하락장(bearish_trend)
  거래일이 0일**로 나타나, "최근성 창"만으로는 필수 국면 게이트를 원천적
  으로 통과할 수 없음을 실증했고, 1차 pooled 유의성도 확보되지 않았다
  (`overall_score` T+20 t_NW=1.18). §14(SPPV-2.7)의 보류 판정은 유지되며,
  이번 작업은 앞으로의 재검증이 따를 **기간 기준을 확정**한 것이다.
  **(2026-07-14 6차 재검증)** 최초 저장 로그가 실패 트레이스였던 증빙
  결함을 발견해 컨테이너에서 재실행 — 종료 코드 0/KIS 호출 0건/
  bearish_trend 0일/t_NW=1.18 전부 재현 확인. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §16, §16.6.
- **2.9순위(완료, 2026-07-14 — SPPV-2.9, 신호 feature 재설계 검토)**:
  §14.5가 지시한 신호 feature 재설계 검토를 실행했다. `fast_score`/
  `slow_score`의 6개 sub-component를 분해 실측하고 신규 후보 feature
  (`risk_adj_momentum_3m`=변동성 조정 모멘텀, `reversal_1m`=단기 역추세)
  를 §16 이원 기준으로 검증했다. **결과: `rsi_signal`이 T+20에서 유의하게
  역방향(t_NW=-2.94)임을 특정** — `fast_score`가 반복적으로 실패/역전
  했던 원인 중 하나로 확인됨. `risk_adj_momentum_3m`은 3년 pooled
  유의(t_NW=2.07) + 하락장 역전 없음(t_NW=0.39)으로 유일한 Watch 후보
  이나 1차(최근 12개월) 유의성(t_NW=1.47)이 §16 게이트(|t|≥2) 미달 —
  **완전한 Go는 아니다**. `reversal_1m`은 하락장에서만 유의(t_NW=2.13)
  해 국면 조건부 후보로 분리 검토가 필요하다. SPPV-3 착수는 계속
  보류하되, 다음 과제를 구체화했다(`rsi_signal` 제거/반전한
  `fast_score_v2` 검증, `risk_adj_momentum_3m` 재검증). 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §17.
- **2.10순위(완료, 2026-07-14 — SPPV-2.10, §17.5 후속 3과제)**: `fast_
  score_v2`(rsi_signal 제거/부호반전) shadow 2종, `risk_adj_momentum_3m`
  1차 창 18개월 확장, `reversal_1m` 하락장 반분 안정성을 실측했다.
  **결과: `fast_score_v2` 2종 모두 No-Go** — 하락장 T+5 spread가
  원안(t_NW=-2.79)과 거의 동일하게 역전(drop -2.41, flip -2.32) —
  `rsi_signal`이 부분 원인일 뿐 주된 원인이 아니었음을 재확인, §2.9의
  낙관적 프레이밍을 하향 조정. `risk_adj_momentum_3m`은 18개월 창에서
  T+20 t_NW=2.03으로 §16 게이트를 겨우 통과했으나 T+5는 미달인
  marginal 결과 — "Watch 유지, 조건부 상향". `reversal_1m`은 하락장
  반분 검증에서 방향 일관되나(전반 1.87/후반 1.33) 개별 유의 미달 —
  Hold 유지. SPPV-3 착수는 계속 보류. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §18.
- **2.11순위(완료, 2026-07-14 — SPPV-2.11, §18.6 후속)**: `fast_score`
  leave-one-out 4종 분해, `risk_adj_momentum_3m` 창 경계 민감도(12~21
  개월), 국면 전환형 shadow 후보 `regime_switch_v1`을 실측했다. **결과:
  `fast_trend`(SMA20 이격) 제거 시 하락장 T+5 spread가
  -2.79→-1.60(비유의 전환)으로 가장 크게 개선 — 주된 원인은
  `rsi_signal`이 아니라 `fast_trend`였음을 정정.** `risk_adj_
  momentum_3m`은 15~21개월 창에서 T+20 t_NW 1.90→2.03→2.04로 안정적
  plateau(우연 아님, 크기는 marginal). `regime_switch_v1`(비하락장=
  risk_adj_momentum_3m, 하락장=reversal_1m)은 2차(3년) pooled
  T+5=2.60/T+20=2.36으로 트랙 최고 수치를 냈으나 1차(최근 12개월)는
  하락장 표본 부재로 여전히 미달 — 가장 유망한 Watch 후보로 격상하되
  확정 Go는 아니다. SPPV-3 착수는 계속 보류. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §19.
- **2.12순위(완료, 2026-07-14 — SPPV-2.12, §19.6 후속)**: `regime_
  switch_v1`의 1차 게이트 예외 규칙 3개(A 관찰 유예/B 최근-실사례
  고정창/C 적응형 최소 국면 표본 창)를 정의·비교하고, fast 계열 신규
  feature 2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`)을 실측했다.
  **결과: 규칙 C가 n=30에서 t_NW=4.18로 급등하지만 n=48(규칙 B)에서는
  1.33에 불과 — "문턱을 넘을 때까지 창을 줄이는" 데이터 스누핑으로
  판정해 채택을 거부한다.** 규칙 B(고정 48일)는 정직한 재검증에서도
  미달(1.33~1.61) — **규칙 A(관찰 유예, 하락장 재발 시 자동
  재검증)를 유일하게 채택**한다. fast 계열 신규 feature 2종 모두 범용
  대체 후보로는 No-Go — `rsi_mean_reversion`은 하락장 전용(t=2.26,
  `reversal_1m`과 동일 패턴), `sma5_over_sma20_gap`은 SMA20과 동일하게
  하락장에서 유의하게 역전(t=-2.67). SPPV-3 착수는 계속 보류. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §20.
- **2.13/2.14순위(완료, 2026-07-14 — SPPV-2.13/2.14, §20.5 후속)**:
  `regime_switch_v1`의 규칙 A(관찰 유예)를 실행 가능한 모니터링
  스크립트로 구현(벤치마크 1종목만 조회, 최근 12개월 국면 분포 확인 후
  `TRIGGERED`/`PARTIAL`/`NOT_TRIGGERED` 자동 판정) — 실행 결과 현재
  `NOT_TRIGGERED`(bearish_trend 0일). "절대 가격 수준"에 의존하지 않는
  완전 신규 fast 계열 feature 2종(`money_flow_5d`=자금 흐름 축,
  `relative_strength_rank_1m`=cross-sectional 상대강도 축)을 실측 —
  둘 다 범용 대체 후보로 No-Go. `relative_strength_rank_1m`은 하락장
  에서 유의하게 역전(t=-2.13)해, 시장 베타를 제거한 상대강도조차
  하락장에서는 반대로 작동한다는 더 강력한 규칙성을 재확인했다.
  SPPV-3 착수는 계속 보류. 상세:
  `plans/[DESIGN] signal_predictive_power_validation.md` §21, §22.
- **2.15순위(완료, 2026-07-15 — 국면별 신호 극성 종합 및 상위 방향
  확정)**: SPPV-2.9~2.14의 10개 신호를 종합표로 통합, 8/10이 "추세형=
  상승/횡보 전용, 되돌림형=하락장 전용" 규칙성을 따름(`rsi_signal`만
  상승장 역전 예외)을 확인했다. 5개 축 모두 시도 후 동일 결론 수렴을
  근거로 **feature 추가 실험을 중단하고 국면 분기형 entry 설계
  검토로 전환**을 확정했다 — 유니버스/미시구조 재검토는 후순위 유지.
  상세: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
  direction.md`.
- **2.16순위(완료, 2026-07-15 — 국면 분기형 entry 설계 초안 + shadow
  계산기)**: §2.15의 판정을 실제 설계 문서(`plans/[DESIGN] regime_
  conditional_entry_signal_v1.md`)로 구체화했다 — 국면별 신호 선택
  매트릭스, `entry_score` alpha layer 교체 제안(미적용), shadow 검증
  Phase 1/2 계획. shadow 계산기를 실행해 실시간(2026-07-14 기준)
  스냅샷 산출 — 시장 공통 국면 `range_bound`로 87/87종목이 `risk_adj_
  momentum_3m` 분기 사용, 하락장 분기는 미발동(§21 모니터링과 정합).
  `entry_score` 코드/운영 변경 없음.
- **2.17순위(완료, 2026-07-15 — regime_conditional_signal Phase 2
  shadow 누적 사이클 구축)**: `regime_conditional_entry_signal_v1.md`
  §4.2의 Phase 2를 실행 가능한 오케스트레이터(`scripts/run_regime_
  conditional_shadow_cycle.py`)로 구현했다 — 게이트 판정(§21)과 신호
  계산(§22)을 벤치마크 1회 조회로 통합, 누적 이력 파일(JSONL, 중복
  거래일 자동 skip) 구축, `TRIGGERED` 전환 시 재검증 runbook 출력.
  실행 결과: 게이트 NOT_TRIGGERED, 신호 2026-07-14 기준 `range_bound`
  로 87/87종목 `risk_adj_momentum_3m` 분기 — 이력에 1줄 추가, 재실행
  중복 방지 확인. `entry_score` 코드/운영 변경 없음.
- **2.18순위(완료, 2026-07-15 — entry_score 중복 penalty ablation
  실측)**: SPPV-3 착수 전제인 "중복 억제 구조 재현·분해"를 실제
  실측으로 구체화했다 — 운영 함수(`_build_entry_score`, `_assess_
  buy_eligibility`)를 그대로 호출해 세 penalty 축을 오늘(87종목)
  기준 독립 평가. **결과: B(60건) 발동 종목은 예외 없이 A·C도 함께
  발동(A∩B∩C=60=B 전체)** — 본 문서 §2의 "삼중 중복"이 오늘 데이터로
  100% 재현됨. 종목별 regime_label(bearish_trend 69%)이 시장 공통
  국면(`range_bound`)과 전혀 다름을 재확인. `entry_score` 통합 시
  국면 정의(종목별 vs 시장 공통) 통일이 새로운 전제로 필요함을
  발견. 운영 DB 직접 조회는 자동 승인 경계 밖으로 판단돼 시도하지
  않았다. 상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §8.
- **2.19순위(완료, 2026-07-15 — 중복 억제 시계열 누적 + 국면 정의 비교
  체계 구축)**: §8의 하루치 관찰을 시계열 누적 절차로 승격했다 — 신규
  오케스트레이터가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행에서
  계산해 누적 이력에 기록. **결과: §8과 동일한 수치(A=85/B=60/C=75/
  A∩B∩C=60)로 교차 검증, 국면 일치 18건/불일치 69건(79%)** — "시장
  비하락장인데 종목별 하락장" 60건. SPPV-3 본작업용 비교 실험(현행
  종목별 정의 vs 시장 공통 정렬)을 설계 문서 §9.6에 구체화. `entry_
  score` 코드/운영 변경 없음. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §9.
- **2.20순위(완료, 2026-07-15 — §9.6 비교 실험 실측)**: §9.6에서 설계한
  종목별 vs 시장 공통 regime 정의 비교 실험을 실제로 실행했다. **결과:
  변형 B(시장 공통)가 통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의
  forward return은 더 높음(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%,
  둘 다 유의)** — 과잉 억제가 아니라 정밀한 억제 가능성. A-B 차이
  직접 유의성 미검정, 통과군 내부 quintile spread 여전히 역전 —
  **판정 Watch(조건부 유리, 확정 Go 아님)**. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §10.
- **2.21순위(완료, 2026-07-15 — A/B 판정 불일치 표본 direct 비교 + 1차
  창 재확인)**: 같은 종목-거래일 표본을 `A_only`/`B_only`/`both`/
  `neither` 4개 배타적 집합으로 분해했다. **결과: `B_only`가 3년·1차
  창 모두 0건 — 시장 공통 정의(B)는 종목별 정의(A)의 진부분집합일 뿐,
  새 종목을 발굴하지 않고 A 통과분 일부(`A_only`, 1,072건)를 추가
  차단만 한다.** `A_only`의 forward return은 방향상 음수이나 유의하지
  않음(|t_NW|<1). 최근 12개월은 A-B 차이 자체가 없음. **판정: Watch
  유지(No-Go에 근접), 확정 전환 기각.** 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §11.
- **2.22순위(완료, 2026-07-15 — alpha layer vs regime_conditional_
  signal 직접 비교)**: 무게중심을 "국면 정의 통일"(차단)에서 "alpha
  layer 교체"(선별)로 옮겼다. 현행 alpha layer와 `regime_conditional_
  signal`을 같은 3년 표본에서 직접 비교한 결과, **2차(3년) 창에서
  `regime_conditional_signal`이 T+5/T+20 둘 다 유의(t_NW 2.52/2.33),
  현행 alpha layer는 어디서도 비유의(1.02~1.39) — 4개 관측치 전부
  일관되게 우세.** 1차 창은 미달이나 §21 구조적 이유(하락장 부재)
  때문. **판정: Conditional Go(2차 검증 통과, 1차 게이트 전환 대기).**
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §12.
- **2.23순위(완료, 2026-07-15 — 새 alpha 상위군과 기존 차단 축 결합
  효과 검증, 가장 빈번한 차단 사유 재발견; **당시 해석은 이후
  2.24순위/§14에서 보정됨**)**: `regime_conditional_signal`을 새
  alpha로 넣었을 때 기존 차단 로직이 그 효과를 상쇄하는지 검증했다.
  **결과: 상위 20% 표본의 68.3%(3년)/61.1%(최근 12개월)가 차단되나,
  차단된 표본도 forward return이 강하게 유의하게 양(+)(생존군과 큰
  차이 없음).** 실패 사유를 집계한 결과 **§2의 regime 관련 축이
  아니라 순수 유동성 게이트 `eligibility_low_relative_activity`
  (거래량/거래대금 급증 비율<1.10 차단)가 차단의 압도적 대부분(3년
  79.7%, 최근 12개월 99.6%)을 차지함을 새로 발견** — §2의 regime
  삼중 중복은 오히려 부차적(3년 20.3%, 최근 12개월 0.4%)이었다.
  **판정: alpha 자체는 Conditional Go 유지, 결합 시나리오는
  Watch(활동성 필터 ablation 검증 필요).** 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §13.
- **2.24순위(완료, 2026-07-16 — 활동성 필터 정밀 ablation, 제거만
  No-Go로 확정·완화는 Watch)**: §2.23이 발견한 `eligibility_low_
  relative_activity`가 실제로 과잉 억제인지 정밀 ablation으로
  판정했다. `regime_conditional_signal` 상위 20% 표본 대상 threshold
  현행(1.10)/완화(1.00)/완전 제거 3개 시나리오 비교 결과, **완전
  제거는 생존군 forward return이 무차단 상위군 전체 수준으로
  회귀하고 현행 유지보다도 낮아**(2차 T+20 제거 +3.882% < 현행
  +4.381%, ≈무차단 전체 +3.554%) **No-Go로 확정**했다. **임계값
  1.10→1.00 완화는 생존 종목 수(2차 31.7%→37.7%, 1차 38.9%→
  46.4%)와 T+5/T+20 평균 수익률·Newey-West t값·양수 비율이 1차·
  2차 창 모두 동시에 소폭(0.07~0.18%p) 개선되는 방향은 일관됐으나,
  검증한 threshold가 1.00 하나뿐이고 개선폭이 작아 Watch(추가
  검증 필요)로만 기록했다** — Conditional Go로 단정하지 않는다
  (2026-07-16 2차 검토, Codex 지적 반영해 해석 보정). 옳은 판단
  기준은 "차단된 표본이 플러스인지"가 아니라 "차단 제거/완화 시
  기대수익률이 실제로 개선되는지"다 — "차단 비중이 크다"≠"과잉
  억제", "표본 증가로 t값이 커진다"≠"품질 개선"임을 실측으로
  확인했다(완전 제거 시나리오가 그 역설 사례). **결론: 활동성
  필터가 BUY 0건의 "주범"인지 "과잉 억제"인지는 이번 실측만으로
  확정할 수 없다** — 재검토 필요 후보로 남기되, "주범 확정"·
  "과잉 억제 확정"·"제거 시 개선" 같은 확정적 결론은 쓰지 않는다.
  §2.23의 "결합 사용 시나리오 Watch" 판정은 이번 결과로도 Watch로
  유지한다. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §14.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.25순위, §2.23/§2.24 문서 내부 해석 일관성 정리)
- 수정내용: 새 실측 없이 §2.23 제목/본문의 "진짜 병목 재발견" 등
  §2.24 보정 결론과 충돌하는 단정 표현을 "가장 빈번한 차단 사유
  재발견(당시 해석은 이후 §2.24/§14로 보정됨)"으로 정정했다. 3순위
  항목의 "완화안이 Conditional Go로 확정됨"이라는 서술도 "완화
  방향의 추가 검증 필요(Watch)"로 정정 — 다른 4개 정본 문서와 함께
  일관성을 맞췄다.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.26순위, 활동성 필터 threshold sweep + 기간
  분할 재현성 검증)
- 수정내용: 2.24순위의 "1.00 완화 Watch" 판정을 Conditional Go
  이상으로 올릴 수 있는지 검증했다. threshold를 1.10/1.05/1.00/
  0.95/0.90으로 확장 스윕하고 3년 표본을 전반부/후반부로 양분한
  결과, **2차(3년) 전체·1차(최근 12개월)·후반부에서는 완화할수록
  개선되는 것처럼 보였으나, 전반부(2023-10~2025-02)에서는 정반대로
  완화할수록 악화됐다**(T+5 기준 1.10 +0.7394% → 0.90 +0.5728%).
  "완화=개선"은 사실상 후반부(=최근 12개월과 거의 동일 시기)의
  효과가 3년 pooled 평균을 끌어올린 것이었다 — 3년 전체를 대표하는
  재현성 있는 규칙성이 아니다. **결론: 완화안을 Conditional Go로
  올릴 근거는 얻지 못했고, 오히려 재현성 부재라는 신중론 근거가
  추가됐다 — 판정 Watch 유지(격상 없음), 완전 제거는 여전히
  No-Go.** 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §15.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.27순위, 활동성 필터 완화 효과 전반부/후반부
  반전 원인 분해)
- 수정내용: 2.26순위가 발견한 "완화 효과가 전반부에서는 반대로
  나타나는" 현상의 원인을 규명했다. 시장 공통 regime 분포(전반부
  range_bound 45.4%+bearish_trend 28.5% 혼합/약세 편중 vs 후반부
  bullish_trend 82.9% 극편중), 상위 20% 무차단 기본 수익률 레벨
  (후반부가 전반부의 약 3.3~3.4배), 유동성 구조(average_turnover_
  20d 중앙값 약 1.9배, trend_strength 약 2.4배 확대)를 비교하고,
  **threshold 완화 시 새로 통과하는 표본만 분리해 비교한 결과가
  결정적이었다** — 1.10→1.00 완화로 새로 통과하는 표본의 T+5 평균이
  전반부에서는 기존 통과군보다 낮고(+0.56%<+0.74%), 후반부에서는
  오히려 높다(+2.72%>+1.86%). **결론: 완화 효과의 반전은 활동성
  필터 로직 결함이 아니라 두 반기의 시장 국면·유동성 구조 차이가
  만들어낸 결과** — 국면·유동성 변화가 "완화 시 새로 들어오는 한계
  종목"의 실제 품질을 바꿔놓았다는 것이 직접적 인과 고리다. 정적
  threshold 완화안은 여전히 Watch 유지(격상도 강등도 아님), 완전
  제거는 여전히 No-Go. 향후 방향은 "완화"가 아니라 "국면 조건부
  threshold"일 가능성이 있으나 이번 턴은 원인 규명까지만 수행(새
  설계·구현·운영 코드 변경 없음). 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §16.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.28순위, alpha layer 교체 BUY funnel 검증)
- 수정내용: 무게중심을 활동성 필터에서 alpha 교체(§2.22)로 되돌려,
  현행 alpha와 `regime_conditional_signal`을 candidate→eligible→
  would_buy(실제 운영 top-K 상수 재사용)→blocked 4단계 BUY funnel
  로 비교했다. **결과: would_buy 단계 forward return이 2차(3년)·
  1차(최근 12개월)·3년 전반부·3년 후반부 4개 창, T+5/T+20 전부
  (8/8)에서 새 alpha가 현행보다 높았다** — 활동성 필터 완화(2.26
  순위)와 달리 방향이 한 번도 반전되지 않았다(3년 전반부만 두
  시나리오 모두 비유의했으나 방향은 유지). eligible 전환율은 신규
  alpha가 더 낮아 would_buy 표본 수도 약 20% 적었지만, 표본당 평균
  수익률 개선폭이 더 커서 누적 기대 성과 근사치는 신규 alpha가
  여전히 컸다. **결론: §2.22의 Conditional Go가 funnel 실제 매수
  후보 단계까지 보강됐으나, 3년 전반부 비유의·국면 편향 가능성·
  거래 빈도 감소 트레이드오프로 확정 Go는 아니다.** 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §17.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.29순위, alpha layer 교체 virtual BUY
  funnel 확장 검증)
- 수정내용: §2.28의 `would_buy`를 실제 운영 판단 경로에 한 단계 더
  가깝게 확장했다. 운영 함수 `assess_deterministic_triggers()`가
  실제로 쓰는 `BUY_CANDIDATE` 조건(`eligible AND entry_score>=0.65
  AND allocation_budget_ok`, 실제 운영 상수 재사용)을 그대로
  재현한 `selected` 단계를 추가해 candidate→eligible→selected→
  would_buy 5단계로 확장하고, MFE/MAE도 계측했다. would_buy 단계의
  forward return 우위는 4개 창·2개 horizon 전부(8/8)에서 유지됐다.
  **결정적 신규 계측: 새 alpha는 4개 창 전부에서 selected 비율이
  정확히 100.0%였다** — candidate 정의와 selected 조건이 같은
  alpha 신호를 두 번 거르는 구조라 0.65 문턱이 새 alpha에는 사실상
  무력화된다는 계측 caveat을 새로 발견했다(현행은 eligible의
  66~72%만 통과). MFE/MAE 비교에서는 새 alpha가 상방·하방 진폭
  모두 크지만 MFE/|MAE| 비율은 4개 창 전부에서 새 alpha가 더 높았다.
  **결론: Conditional Go를 재확인했으나, "0.65 문턱 사실상
  무력화"·"MAE 확대"라는 두 계측 caveat이 추가되어 여전히 확정
  Go는 아니다.** broker submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §18.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.30순위, 새 alpha entry_score 스케일
  재보정 shadow 검증)
- 수정내용: §2.29의 "0.65 문턱 사실상 무력화" caveat의 원인을
  분해했다 — `regime_conditional_signal`이 [-1,1] 스케일이 아닌
  퍼센트 단위 비율(예: 3개월 수익률/변동성=6.0)이라 `_normalize_
  signed_score`가 상위 20% quintile에서 거의 항상 saturate됨을
  확인했다. 재보정 3안(R1 가중치 축소 0.80→0.50/R2 z-score/R3
  percentile)과 기준선(R0)을 candidate→eligible→selected→
  would_buy funnel + MFE/MAE로 비교했다. **R1은 selected_rate를
  46.6~67.8%로 크게 낮췄지만 forward return이 4개 창 중 3개에서
  악화돼 기각.** **R2(z-score)는 selected_rate가 96.9~99.3%로
  R0(100%)와 큰 차이가 없어 문제를 충분히 해결하지 못함**(상위
  20% 멤버는 정의상 z>=1 saturate 경계 근처에 몰림). **R3
  (percentile)가 가장 균형 잡힌 결과 — selected_rate를 93.7~96.5%
  로 의미 있게 낮추면서(문턱 실질 회복), forward return이 4개 창·
  2개 horizon 전부(8/8)에서 개선됐고**(2차 T+20 R0 +2.818% vs R3
  +3.591%, 1차 T+20 R0 +4.307% vs R3 +6.050%), **would_buy 표본
  감소는 1.2~2.4%로 미미했으며 MAE도 3개 창에서 근소 개선됐다.**
  **결론: R1/R2는 기각, R3(percentile 기반 스케일링)를 유력한
  재보정 후보로 채택 검토한다 — 다만 단일 실험·재현성 미확인·
  §3 기존 전제조건 미충족으로 확정 Go는 아니다.** 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §19.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.31순위, R3 재현성 검증 + percentile 계산
  민감도 점검)
- 수정내용: §2.30이 채택 검토한 R3를 분기 4분할로 재검증했다.
  **R3의 "4개 창 전부 우위" 결론이 분기 단위로는 무너졌다 —
  분기1(2023-10~2024-06)·분기3(2025-02~2025-10)에서 R3가 R0보다
  오히려 낮았다**(분기1 T+20 R0 +1.208% vs R3 +1.041%, 분기3 T+20
  R0 +3.648% vs R3 +3.402%). §2.30의 4개 창은 서로 겹치는 넓은
  구간(특히 "후반부"≈"최근 12개월")이라 해상도가 낮았음이 원인으로
  판단된다. percentile 계산 기준을 candidate 내부로 바꾼 변형(R3b)
  은 8개 창 전부(분기1·분기3 포함)에서 R0보다 높았으나 selected_
  rate가 29.9~39.2%까지 낮아져 R1과 유사한 "극단적 선별" 우려가
  있어 별도 검증이 필요하다. **결론: §2.30의 "R3 유력 후보로 격상"
  판정을 철회하고 Watch로 하향한다** — 분기 50%에서 방향이 뒤집힌
  것은 "일부 분할 창에서 흔들리면 Watch/Hold"라는 판정 원칙에
  정확히 해당한다. R3b는 신규 관찰 대상으로만 등록하고 이번 턴에
  격상하지 않는다. 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §20.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.32순위, R3b 엄격 재검증 + R3 실패 구간
  원인 분해)
- 수정내용: R3b를 R1과 동일한 엄격 기준(8개 창 중 하나라도
  악화되면 기각)으로 재검증하고, would_buy 종목 겹침률(overlap)로
  "진짜 선별 개선"과 "표본 급감 착시"를 분리했다. **R3b는 8개 창
  전부(R3가 실패한 분기1·분기3 포함)에서 R0보다 높았다.** 핵심
  발견: R3는 R0와 77~85%가 같은 종목을 고르는 "미세 재조정"인 반면,
  R3b는 R0와 47~61%만 겹쳐 40~53%를 새로 골라 넣는 질적으로 다른
  선별이다 — 순수 표본 축소 착시가 아니라 실제 재선별 효과로
  판단했다. R3 실패 원인 분해에서는 saturation_rate가 4개 분기
  전부 100.0%로 동일해 분기간 차이의 원인이 아니었고, 국면 분포도
  설명력이 없었다(분기3은 강세장 67.5%인데도 실패, 분기2는
  약세+횡보 90.8%인데도 성공 — 정반대 패턴). 결론: R3의 실패는
  특정 국면 때문이 아니라 R0와의 높은 겹침에서 오는 작은 효과
  크기가 잡음에 취약했기 때문으로 판단. **판정(당시 판정, §2.33
  에서 재정정됨): R3b를 유력한 재보정 후보로 신규 격상(Watch→
  Conditional Go 경계) — R1이 실패한 엄격 기준을 통과한 첫
  재보정안이다.** 다만 selected_rate가 30%대로 낮고, 동일 3년
  표본 내부 분할이라 진정한 out-of-sample 검증은 아니며, §3 기존
  전제조건도 미충족이라 확정 Go는 아니다. **[중요] 이 판정의 핵심
  근거였던 overlap(간접 지표)은 §2.33의 대응표본(직접) 검증에서
  근거가 부족했음이 드러나 다시 Watch로 하향 정정됐다 — 상세는
  §2.33 참고.** **R3는 Watch 유지**(하향 판정 번복 없음, §2.33
  으로 오히려 근거 강화). 문서 정정: "분기 25%가 뒤집혔다"는
  계산 오류를 "2/4=50%"로 정정했다(결론 불변). 운영
  코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §21.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.33순위, R3b 대응표본 검증 — overlap
  근거 보정)
- 수정내용: §2.32의 overlap(간접) 근거를 대응표본(직접) 검증으로
  재확인했다 — 같은 거래일에 R0가 버리고 R3b가 새로 고른 "대체
  종목쌍"의 forward return 차이를 일별로 계산해 집계했다. **R0 vs
  R3b 대체쌍(added−dropped) T+20 평균은 8개 창 중 6개에서 양(+)
  이었으나 분기3에서는 음수(-0.47%p, 대체 우위일 비율 45.8%로
  절반 미만)로 뒤집혔다.** **(§2.34에서 정정: t_NW>=1.96 창은
  실제로 2차·전반부·분기1 3개다 — 최초 서술은 분기1을 누락한
  오류였다.)** 나머지 창은 marginal했다. R0 vs R3 대체쌍은 더 약해
  분기1(-0.44%p)·분기3(-0.04%p)에서 사실상 음수/0이었다. **핵심
  정정: §2.32가 overlap만으로 "실제 재선별 효과"라고 결론 낸 것은
  근거가 부족했다** — 이번 직접 검증에서 그 재선별이 분기3에서는
  오히려 더 나쁜 종목으로의 교체였음이 드러났다. aggregate 우위
  (8/8) 자체는 부정되지 않으나 그 우위가 "대체 종목의 우수성"에서
  왔다는 인과관계는 확인되지 않았다. **결론: §2.32의 "R3b 유력
  후보 격상" 판정을 다시 Watch로 하향한다.** R3는 Watch를
  유지하되 이번 직접 검증으로 근거가 강화됐다. 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §22.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.34순위, R3b aggregate 우위 vs 대응표본
  음수 구간 3분해)
- 수정내용: §2.33의 "t_NW≥1.96 창 2개" 서술을 재확인해 실제로는
  3개(2차=1.96, 전반부=2.07, 분기1=2.02)였음을 정정했다. common_
  kept/dropped_only/added_only 항등식 분해로 aggregate 우위의
  원인을 규명했다. **added_only 평균이 8개 창 전부에서 common_
  kept·dropped_only보다 뚜렷이 높아 R3b의 신규 선택 자체는 실제로
  우수했음을 확인**했으나, R0 자신의 구성이 저품질 dropped_only
  비중(63.3%, 2차)이 커서 aggregate 차이의 상당 부분이 "구성
  효과"에서도 왔다. **[§2.35에서 정정: 이 방향은 틀렸다 —
  정확한 항등식 분해 결과 구성효과는 8개 창 중 6개에서 오히려
  음(-)으로 우위를 상쇄하는 방향이었고, aggregate 우위 전체는
  순수 replacement_effect에서 왔다.]** **가장 중요한 발견: 분기3에서 이번 pooled
  교체효과(+2.594%p)와 §2.33의 paired 교체효과(-0.4666%p)의 부호가
  정반대다** — 가중 방식 차이(종목-일 동일가중 vs 거래일 동일가중)
  때문이며, R3b의 효과가 "매일 조금씩"이 아니라 "소수 스왑 밀집일에
  집중"된 비대칭 구조임을 시사한다. 결론: aggregate 우위는 부분적
  실체가 있으나(added_only 우수성) 비대칭적이고 특정 구간 집중형
  이라 안정적 재현으로 단정하기 이르다 — **R3b/R3 모두 §2.33의
  Watch 판정을 그대로 유지한다(이번 턴은 재격상이 아닌 원인
  규명이 목적).** 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §23.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.35순위, R3b pooled 우위 날짜 집중도
  검증 + 교체효과/구성효과 정량 분리)
- 수정내용: §2.34가 지시한 분기3 세밀 진단을 실행했다. 거래일별
  스왑 개수 상위 10% 제거 후 aggregate 우위 잔존비율을 계산하고,
  `aggregate_diff=replacement_effect+composition_effect` 정확한
  항등식으로 두 효과를 분리했다. **결과 1: 스왑 상위 10% 거래일
  제거 후에도 8개 창 중 7개에서 우위가 80~120% 수준으로 유지 —
  "소수 거래일 집중" 가설 기각. 분기3만 예외로 잔존비율 30~65%로
  크게 감소.** **결과 2(중요 정정): §2.34의 "구성효과도 상당히
  기여한다"는 서술은 방향이 틀렸다 — composition_effect는 8개
  창 중 6개에서 오히려 음(-)으로 우위를 상쇄하는 방향이었고,
  aggregate 우위 전체는 순수 replacement_effect에서 왔다.**
  판정: 재격상보다 원인 확정을 우선(지시에 따름) — R3b 우위 근거는
  명확해졌으나 분기3 반례가 실제 집중형임이 확인돼 **R3b/R3 모두
  Watch 판정을 그대로 유지한다.** 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §24.

- 작성자: Claude
- 수정일자: 2026-07-16 (2.36순위, 분기3 스왑 집중일 세부 진단 +
  §2.35 해석 문구 정밀 보정)
- 수정내용: §2.35의 두 서술을 실제 수치 기준으로 정밀 보정했다.
  **보정 1(horizon 구분): "구성효과 8개 창 중 6개 음(-)"은 T+5/
  T+20을 뒤섞은 표현 — 정확히는 T+20 기준 8/8, T+5 기준 5/8에서
  음(-)(전반부·분기1·분기2는 T+5에서 양(+)).** **보정 2(분기3
  해석 정밀화): "분기3만 실제 날짜 집중형"이라는 서술은 방향이
  과했다 — 분기3 스왑 상위 15개 거래일 개별 진단 결과, 대형
  스왑일(상위 10%, 약 8일)의 T+20 교체효과 평균은 +7.04%p로
  뚜렷한 양(+)이고, 분기3 전체 paired 평균(-0.4666%p)을 만드는
  진짜 원인은 나머지 약 75개 소규모 스왑일의 완만한 음(-) 누적
  (역산 약 -1.267%p)이다 — "대형 스왑일이 나쁘다"가 아니라
  "대형 스왑일은 유일한 양(+)의 원천이고 그것을 빼면 넓게 퍼진
  완만한 음(-)만 남는다"는 구조.** 이벤트/실적 연관은 2025-02-
  12~13 연속 악재일에 한해 정황(가설) 수준(외부 데이터 미조회).
  판정: 재격상/재하향 없이 R3b/R3 모두 Watch 판정을 그대로 유지
  (원인 확정·표현 정밀화 목적). 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §25.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.37순위, 분기3 반례의 대형/소규모 스왑
  구조 정밀 확정 + "전적으로 의존" 문구 보수화)
- 수정내용: §2.36의 "대형 스왑일은 유일한 양(+)의 원천"이라는
  서술을 분기3 83개 스왑일 전체를 5분위로 구간화해 정량 검증했다
  (§2.37). **결과: "대형=양(+)/소규모=음(-)"은 양극단(Q1 최대·Q5
  최소)에서만 성립하고 중간 구간(Q2~Q4)은 혼재한다**(Q4는
  소규모인데도 T+20 +4.38%p 양(+)). aggregate(순 기여) 관점에서는
  대형 스왑일이 우위의 상당 부분(T+5 약 70%, T+20 약 35%)을
  담당하지만, **총합(gross) 관점에서는 전체 양(+) 합계의 15% 수준
  에 불과** — "전적으로 의존"·"유일한 원천"은 과장이었다. 2025-
  02-12~13 동시 제거는 분기3 음(-) paired 평균의 약 39%만 설명
  (부분적 설명력). 판정: 재격상/재하향 없이 R3b/R3 모두 Watch
  판정을 그대로 유지(구조 확정·문구 보수화 목적). 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §26.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.38순위, R3b의 SPPV-3 진입 후보 여부 판단
  — 실제 BUY funnel 최소 검증)
- 수정내용: R3b 미세 해부를 멈추고 SPPV-3 착수 후보 여부를
  판단했다(§2.38). 기존 8개 창 BUY funnel 계측(재사용) 결과 T+20
  평균 우위 8/8 일관, t_NW 6/8 유의. **신규: would_buy 모집단의
  거래일 편중도(top-decile-day leave-out) 계측 결과, 거래일 집중
  의존은 R3b만의 문제가 아니라 R0(기준선) 자체가 8개 창 중 3개에서
  상위 10%일 제거 시 평균이 마이너스로 뒤집히는 alpha 신호 계열
  전반의 특성이며, R3b는 8/8 창에서 R0보다 그 의존도가 더 낮다
  (더 견고).** 판정: **R3b를 Watch에서 Conditional Go로 상향**
  (조건부: 분기1·분기2 marginal t_NW 재확인, selected_rate 급감의
  총 기대수익 영향 정량화, §3 전제조건 충족, point-in-time
  파이프라인 반영 shadow 실행이 확정 Go 전 필요). 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §27.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.39순위, §2.38 수치 정정 + Conditional Go
  재평가)
- 수정내용: §2.38의 세 가지 수치 서술을 재검산해 정정했다(§2.39).
  **정정 1: R0의 top-decile-day 음(-) 반전 창 수는 "3개"가 아니라
  "4개"(2차 포함).** **정정 2: 양수 비율 열세 창 수는 "3/8"이
  아니라 T+20 기준 "1/8"(분기2만), T+5 기준 "0/8".** **정정 3:
  "selected_rate 급감(약 30~40%)"은 R3b 자신의 비율 수준(29.9~
  39.2%)이며 R0(100%) 대비 약 61~70%p 감소로 명확화.** 세 정정
  모두 R3b의 방향성 우위를 약화시키지 않아(정정 1·2는 오히려 R3b에
  유리한 방향) **R3b는 Conditional Go를 유지한다.** 새 실험 없이
  기존 JSON 재검산만 수행. 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §28.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.40순위, selected_rate 감소가 총 기대수익에
  미치는 영향 정량화)
- 수정내용: R3b Conditional Go 확정 전 잔여 조건 중 조건 (2)를
  정량화했다(§2.40). 신규 실측 없이 기존 산출물 2개만 재사용해
  총 기대수익 proxy(=would_buy_n × mean_forward_return_pct)를 8개
  창×2horizon(16개 조합) 전부 계측한 결과, **14/16 조합에서 R3b의
  총proxy가 R0보다 높다**(92.0%~322.6%). 나머지 2개(1차 T+5, 분기3
  T+20)도 거의 동률. 판정: "거래 빈도 감소가 총 기대수익을
  훼손하는가"에 명확히 "아니다" — **확정 Go 전 잔여 조건 4가지 중
  1개(조건 2)가 해소돼 Conditional Go 근거가 보강됐다.** 나머지
  3개 조건(분기1·분기2 marginal t_NW, §3 전제조건, point-in-time
  파이프라인 반영)은 그대로 남아 확정 Go는 아니다. 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §29.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.41순위, R3b 총 기대수익 proxy의 유휴
  자본 반영 보강 검증)
- 수정내용: §2.40의 "조건 (2) 해소"를 유휴 자본 기회비용까지
  반영해 보강 검증했다(§2.41). 신규 계측은 창별 전체 거래일 수
  하나뿐(캐시 봉 데이터만 사용, 신규 KIS 호출 없음). **엄격 기준
  (R0가 전체 슬롯을 자기 평균으로 100% 채웠다는 이론적 최대와
  비교) 적용 결과, T+20은 8개 창 중 7개에서 여전히 R3b 우위
  (견고)이나, T+5는 8개 창 중 6개에서 우위가 사라지거나 이미
  열세(취약).** 판정: **"조건 (2) 해소"는 과장 — 정확히는 "T+20
  기준 완화, T+5 기준 여전히 미해결"** 수준으로 재조정. R3b는
  Conditional Go를 유지한다(확정 Go 아님). 운영 코드 변경 없음,
  broker submit 미호출. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §30.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.42순위, R3b Conditional Go의 운영
  horizon 적합성 판단)
- 수정내용: §2.41이 남긴 "T+20 중심인가, T+5 취약성이 실운영과
  충돌하는가"를 코드·문서 조사로 판단했다(§2.42). **결과:
  `deterministic_trigger_engine.py`의 SELL/청산은 100% `exit_
  score`(신호/점수) 기반이며 경과일수를 전혀 참조하지 않고,
  `max_holding_days=20`은 AI Risk agent의 LLM 출력 힌트 기본값일
  뿐 실제로 20일 뒤 매도를 강제하는 코드가 없다.** 기존 §16 Go/
  No-Go 표준이 T+5·T+20을 이미 동시에 요구해온 것도 확인. **판정:
  "T+20 중심이라 T+5 약점을 무시해도 된다"는 주장은 코드로
  뒷받침되지 않는다.** R3b는 Conditional Go를 유지하되(즉시 Watch
  재하향 근거는 부족), T+5 horizon 강건성 확보(또는 실거래 누적
  후 청산 시점 분포 실측)를 확정 Go의 필수조건으로 격상한다. 운영
  코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §31.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.43순위, R3b를 point-in-time entry_score
  파이프라인에 반영한 shadow 검증)
- 수정내용: §2.42가 남긴 "point-in-time entry_score 파이프라인
  반영 shadow 실행"을 수행했다(§2.43). 기존 검증이 이미 실제 운영
  함수(`build_signal_snapshot`/`_assess_buy_eligibility`/`_build_
  entry_score`)를 호출해왔음을 확인했으나, 실제 `strategy_
  selection` 조정항(+0.05 보너스)이 그동안 `None`으로 누락돼
  있었다 — 이를 실제 `select_strategy()` 호출로 채워 A/B 양쪽에
  공정하게 반영했다. **결과: 8개 창×2horizon 16개 조합 전부에서
  R3b>R0 방향 유지**, 다만 **분기1 T+20의 t_NW가 1.31→0.96으로
  더 약화**돼 기존 marginal 우려가 심화됐다. 판정: **R3b는
  Conditional Go를 유지한다.** "point-in-time 파이프라인 반영"
  조건은 부분 해소(핵심 우려는 해소, `portfolio_allocation` gap은
  미해결로 잔존). 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §32.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.44순위, 분기1 t_NW 약화의 원인 정밀
  진단 — 방향성 붕괴 vs 변동성/이상치 문제)
- 수정내용: §2.43이 남긴 "분기1 t_NW 약화(0.96) 우선 재확인"을
  실행했다(§2.44). 분기1은 세 분기 중 가장 "혼합 국면"(강세/횡보/
  약세 고른 분포 + event_driven_unstable 최다) 구간임을 확인.
  **R3b>R0 방향은 그대로 유지되고(1.815% vs 0.753%), 스왑일 46건
  중 33건(71.7%)이 양(+)으로 세 분기 중 최다 — 상위 스왑일 제거
  시 오히려 개선(157.8%)돼 분기3과 정반대 구조.** t_NW 약화의
  실체는 상위 10개 스왑일 중 3건의 극단치(±16~44%p)가 표준오차를
  키운 것으로 확인. 판정: **분기1 약화는 방향성 붕괴가 아니라
  소수 극단치로 인한 분산 문제로 좁혀진다 — R3b는 Conditional Go를
  유지한다**(Watch 재하향 근거 없음). 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §33.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.45순위, SPPV-3 진입 관문 3종 종합 판정 —
  §3 게이트 재확인 + 분기1/T+5 리스크 종합)
- 수정내용: SPPV-3 진입 전 마지막 관문 3가지(§3 전제조건, 분기1
  약화, T+5 취약성)를 종합 판정했다(§2.45). 기존 검증(분기1=§2.44,
  T+5=§2.42)을 반복하지 않고, 유일한 신규 실측인 §3 게이트(기존
  SPPV-2.13 모니터링 스크립트 재실행)만 확인 — **결과 `NOT_
  TRIGGERED`(불변, 최근 12개월 bearish_trend 0/30일).** 종합
  판정: ①§3 전제조건 미충족, ②분기1 약화는 관리 가능한 잔여
  리스크(치명적 결함 아님), ③T+5 취약성은 미해결이나 치명적 근거
  없음. 판정: **R3b는 Conditional Go를 유지한다.** 다만 **SPPV-3
  (운영 코드 반영) 진입은 아직 이르다 — 주된 차단 요인은 R3b 성과와
  무관한 §3 게이트(하락장 미도래)**이며, 규칙 A(관찰 유예)에 따라
  인위적으로 앞당길 수 없다. 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §34.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.46순위, SPPV-2.44 산출물 파일명/실행
  경로 불일치 정정)
- 수정내용: §2.45가 §3 게이트 재확인 산출물을 `..._2026-07-17.
  json`으로 표기한 것이 실제 스크립트 동작과 불일치해 정정했다
  (§2.46). `monitor_regime_switch_v1_gate.py`는 실행 시점과 무관
  하게 항상 하드코딩된 `..._2026-07-14.json`에 저장하며, §2.45가
  인용한 `..._2026-07-17.json`은 컨테이너 산출을 호스트로 복사
  하며 수동 재명명한 사본이다(내용은 실제 재실행 결과, 결론 영향
  없음). **판정: 정정 후에도 SPPV-3 관련 결론은 전혀 바뀌지 않는다
  — R3b Conditional Go 유지, SPPV-3 진입은 §3 게이트 미충족으로
  아직 이르다는 판정을 그대로 유지한다.** 운영 코드 변경 없음,
  broker submit 미호출. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §35.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.47순위, R3b 채택 시 risk_off_penalty
  중복 해소 ablation)
- 수정내용: §3 전제조건 ②(risk_off_penalty 중복 해소)를 R3b
  candidate 위에서 실측했다(§2.47). entry_score 축(-0.15)과
  eligibility 축(즉시 차단)이 서로 다른 함수의 별개 축임을 코드로
  확정하고, A(현행)/B(entry_score 축 무력화)/C(eligibility 축
  완화) 3개 시나리오를 실제 운영 함수 호출로 비교했다(운영 코드
  미수정). **결과: C는 A와 완전 동일**(eligibility 축이 R3b
  candidate pool에서 비활성) — 중복 우려는 애초에 발생하지 않는다.
  **B는 T+20 총 기대수익 proxy가 2차 +20.9%/1차 +20.5% 개선되나
  MAE도 소폭 악화(약 0.5%p)** — 실제 트레이드오프. 판정:
  **eligibility 축은 비활성, entry_score 축은 "완화 검토 후보"에
  가깝다는 실측 근거 확보 — R3b는 Conditional Go를 유지하고, §3
  조건②는 "방향 확인, 사용자 승인 대기"로 진전, SPPV-3 진입은
  §21 게이트 미충족으로 여전히 이르다(불변).** 운영 코드 변경
  없음, broker submit 미호출. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §36.

- 작성자: Claude
- 수정일자: 2026-07-17 (2.48순위, 승인 범위 확정 + risk_off_
  penalty(entry_score 축) 완화안 심층 해석)
- 수정내용: 사용자가 §2.47의 A/B/C 중 "B — entry_score risk_off_
  penalty만 완화"를 승인(eligibility 축 비승인)했다. 기존 산출물을
  신규 실행 없이 재사용해 T+5/T+20 양쪽·MAE 트레이드오프를 심층
  해석했다(§2.48). **결과: 총 기대수익 proxy가 2개 창×2horizon
  전부에서 개선(12.9~20.9%), t_NW도 함께 개선, MAE는 소폭
  악화(5.9~7.8% 상대)하나 개선폭보다 항상 작다.** 판정: **R3b +
  entry_score risk_off_penalty 제거 조합은 Conditional Go를
  보강한다.** SPPV-3 진입 관점에서 남은 조건은 사실상 §21 게이트
  하나로 좁혀졌다(entry_score 코드 반영은 게이트 충족 후 별도
  절차). **[§2.49에서 정정] "게이트 하나"는 §3 전제조건 범위로만
  정확하고 SPPV-3 진입 전체로는 과장 — 아래 §2.49 참고.** 운영
  코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §37.

- 작성자: Claude
- 수정일자: 2026-07-18 (2.49순위, SPPV-2.47 "게이트 하나만
  남았다" 표현 정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리)
- 수정내용: §2.48의 "SPPV-3 진입 관점에서 남은 조건은 사실상 §21
  게이트 하나로 좁혀졌다"는 서술이 §3 전제조건 범위로는 정확하나
  SPPV-3 진입 전체로는 과장이었음을 바로잡았다(§2.49). 새 실측·새
  설계 제안 없이 기존 문서(§2.41 T+5 구조적 리스크, §2.43 혼합
  국면 재확인, §2.40 portfolio_allocation gap)만 재해석했다.
  **재분류: ①주된 차단 요인(§21 게이트, 외생적) ②보조 잔여
  조건(entry_score 코드 반영 절차, T+5 구조적 리스크, 혼합 국면
  재확인) ③실거래 누적 없이는 못 푸는 조건(portfolio_allocation
  gap, 실제 청산 시점 분포).** 판정: **R3b는 Conditional Go를
  유지한다** — 방향 후퇴가 아니라 "남은 조건" 서술의 정밀도만
  회복하는 정정. 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §38.

- 작성자: Claude
- 수정일자: 2026-07-18 (2.50순위, 혼합 국면(분기1 유형) 재확인 —
  분기4 대조 계측)
- 수정내용: §2.49가 정리한 보조 잔여 조건 중 "혼합 국면 재확인"만
  지금 당장 전진 가능해 최우선으로 선택했다(§2.50). 승인된 조합
  (R3b+entry_score risk_off_penalty 제거, B 시나리오)으로 분기1
  (재계측)과 분기4(신규 계측)의 국면 분포·funnel을 비교했다.
  **결과: 분기4는 시장 공통 국면이 사실상 순수 bullish(98.2%)로
  분기1(혼합)과 정반대 — 분기4는 T+20 t_NW=3.00·양수율=60.3%로
  강하고 일관되나 분기1은 t_NW=1.27(marginal)·양수율=46.2%로
  대비된다.** 해석: "혼합 국면→약한 t_NW" 가설이 분기1 1건의
  우연이 아니라 대조쌍으로 확인됐다 — 조건 해소는 아니나 "미확인
  가설"에서 "확인된 패턴"으로 전진. 판정: **R3b는 Conditional Go를
  유지한다.** 운영 코드 변경 없음, broker submit 미호출. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §39.
- 수정일자: 2026-07-18 (2.51순위, "혼합 국면 약세" 가설 직접 분해 —
  거래일 단위 혼합도 3분위 버킷화)
- 수정내용: §2.50(분기1 vs 분기4 대조)은 N=2 분기 대조에 불과해
  "특정 분기 우연"일 가능성을 완전히 배제하지 못했다. 이번 턴은
  분기 경계와 무관하게 각 거래일마다 최근 60거래일(약 1분기) 창의
  시장 공통 국면 혼합도(`mixed_score = 1 - 최빈 라벨 비중`)를 직접
  계산해 3년 전체 634거래일을 혼합도 3분위(저혼합 217일/중혼합
  215일/고혼합 202일)로 버킷화하고 승인된 B 시나리오(R3b+entry_score
  risk_off_penalty 제거)로 funnel·수익률을 재측정했다. **결과:
  저혼합→중혼합→고혼합 순으로 T+20 평균수익률(12.25%→5.44%→0.61%),
  t_NW(3.64→2.51→0.37), 양수율(63.3%→56.8%→38.7%)이 전부 단조
  감소 — 고혼합 구간은 통계적으로 0과 구분 불가능하다.** 해석: 이는
  217/215/202일이 3년 전체에 고르게 분포해 특정 분기에 묶인 현상이
  아니며, 연속 변수(혼합도)와의 용량-반응(dose-response) 관계이므로
  "혼합 국면 약세" 가설은 **지지 증거 추가에서 구조적 패턴으로
  격상**됐다. 다만 저혼합·중혼합 2/3 구간은 여전히 강하고 고혼합
  구간도 점추정치는 양(+)을 유지해 R3b의 방향성 자체를 뒤집는 것은
  아니며, `SPPV-3` 착수를 추가로 늦출 사유도 아니다(주된 차단
  요인은 여전히 `§21` 게이트 하나뿐). 판정: **R3b는 Conditional
  Go를 유지한다.** 운영 코드 변경 없음, broker submit 미호출,
  신규 KIS 호출 0건. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §40.

- 수정일자: 2026-07-18 (2.52순위, SPPV-2.50 결론 문구 정밀화 —
  과장 없이 고정)
- 수정내용: 신규 실행 없이 §2.51(SPPV-2.50)이 사용한 두 문구를
  기존 산출물만으로 재점검했다(SPPV-2.51). **정정 1**: "구조적
  패턴으로 격상"은 과장이다 — 이 3분위 재확인이 R3b/entry_score
  조합을 이미 확정하는 데 쓰인 것과 동일한 3년 in-sample 캐시에서
  수행됐고, mixed_score가 60거래일 trailing window라 인접 거래일
  버킷이 서로 자기상관돼 634거래일이 634개의 독립 관측이 아니기
  때문이다. **확실히 말할 수 있는 것**: 단조 감소·217/215/202일의
  균등 분포는 그대로 사실이며 "지지 증거 추가" 단계는 명백히
  넘어섰다. **과장인 것**: "out-of-sample로 확정된 구조적 패턴"이라
  부르는 것 — 정확한 표현은 **"강한 구조적 정합 증거로 격상"**이다.
  **정정 2**: "주된 차단 요인은 §21 게이트 하나뿐"은 "SPPV-3 착수
  검토를 시작할 수 있는 유일한 외생적 조건"이라는 뜻이지 "진입
  전체에 남은 유일한 조건"이 아니다 — §2.48(§38)의 ①주된 차단
  요인(§21 게이트) ②보조 잔여 조건(entry_score 코드 반영 절차·
  T+5 구조적 리스크·혼합도 모니터링) ③실거래 누적 필요 조건 3단
  분류는 이번 턴에도 그대로 유효하다. 판정: **두 정정 모두 R3b
  방향성·Conditional Go를 바꾸지 않는다** — 서술 정밀도만 회복.
  신규 실행 없음, 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §40.6.

- 수정일자: 2026-07-18 (2.53순위, T+5 horizon 구조적 리스크 추가
  정량화 — 실제 exit_score 기반 signal-driven 청산 타이밍 시뮬레이션)
- 수정내용: §2.48이 정리한 보조 잔여 조건 3개 중 신규 설계 없이
  기존 3년 캐시만으로 실측 가능한 "T+5 구조적 리스크"를 전진시켰다
  (SPPV-2.52). 실제 운영 함수 `_build_exit_score`(순수 함수, DB/
  실시간 상태 불필요)를 R3b+entry_score risk_off_penalty 제거(B
  시나리오) would_buy candidate 1151건에 point-in-time으로 재호출해
  매도 신호(`sell_candidate_threshold=0.75`)를 처음 넘는 날을
  20거래일 관찰 창으로 시뮬레이션했다. **결과: 91.1%(1049건)가
  20거래일 안에 매도 신호를 넘지 않고 censored, 평균 보유일수=
  19.35일. signal-driven 청산 수익률(평균 6.14%, t=4.73)은 T+5
  (2.02%, t=4.18)보다 T+20(6.49%, t=3.87)에 훨씬 가깝다.** 해석:
  실제 청산 로직 기준으로는 T+5가 아니라 T+20 근방에서 청산되므로
  "T+5 평균이 약하다"는 우려가 실제 운영 리스크로 그대로 전이되지
  않는다 — "T+5 구조적 리스크"는 부분적으로 완화됐다. 다만 20일
  초과 구간의 청산 분포·경로 리스크(MAE)는 미검증이라 "완전 해소"
  라고 부르는 것은 과장이다. 판정: **R3b는 Conditional Go를
  유지한다.** 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §41.

- 수정일자: 2026-07-18 (2.54순위, T+5 horizon 구조적 리스크 —
  20거래일 초과 구간·경로 리스크(MAE) 확장 검증)
- 수정내용: §2.53(§41)이 20일 관찰 창으로 남긴 두 미확인 영역(20일
  초과 구간 청산 분포, 보유 중 경로 리스크)을 직접 검증했다
  (SPPV-2.53). 동일 candidate 정의를 재사용하되 관찰 창을 20→60
  거래일로 확장하고 MAE(보유 구간 중 최대 미실현 손실)를 추가
  계산했다(would_buy 1048건, 60일 확보를 위해 표본 소폭 감소).
  **결과: censored 비율 91.1%→51.3%로 감소, 평균 보유일수=48.0일.
  signal-driven 청산 수익률(9.29%, t=5.38)이 오히려 고정 T+20
  (4.46%, t=3.41)보다 강함. MAE 평균 -11.08%, 중앙값 -10.42%, 하위
  10% -21.77%, 최악값 -45.10%, -20% 이하 심각 손실 비율 12.8%.**
  해석: 실제 청산은 T+20보다도 더 늦게 일어나는 경우가 많고 그
  수익률은 T+20보다 강해 "T+5 구조적 리스크"는 "부분 완화"에서
  "거의 해소"로 격상됐다 — 그러나 이 검증으로 경로 리스크(MAE)·
  손절 정책 부재라는 **신규 잔여 조건**이 드러났다(코드상 별도
  손절 임계값 없음 재확인). 판정: **R3b는 Conditional Go를
  유지한다** — 방향성 반전 아님, 경로 리스크는 §38 보조 잔여
  조건에 신규 추가. 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §42.

- 수정일자: 2026-07-18 (2.55순위, SPPV-2.53 결론 문구 정밀화 —
  20일판·60일판 표본 동일성 검증 + "거의 해소" 표현 재점검)
- 수정내용: 신규 실행 없이 §2.54(§42)의 "censored 91.1%→51.3%"
  비교와 "T+5 구조적 리스크 거의 해소" 판정을 두 스크립트 코드
  대조로 재점검했다(SPPV-2.54). **코드 기준 판정**: 20일판·60일판
  모두 후보 스캔 범위가 `last_t = len(bars)-1-
  MAX_EXIT_OBSERVATION_DAYS`로 제한되는데, 60일판은 3년 캐시 끝
  약 40거래일이 스캔에서 제외돼 20일판(1151건)보다 좁은 표본
  (1048건)을 만든다 — candidate 선정 로직 자체는 관찰 창과 무관한
  당일 backward-looking 계산이므로 **60일판은 20일판의 약 91%
  부분집합으로 추정된다. 즉 두 결과는 동일 코호트의 순수 전/후
  비교가 아니라 겹치지만 완전히 같지는 않은 두 표본의 비교**다.
  **확실히 말할 수 있는 것**: 각 판의 표본 내부 측정치는 유효하고
  표본 차이(~9%)가 효과 크기를 설명하기엔 작아 방향성은 신뢰
  가능하다. **과장인 것**: 91.1%→51.3%를 엄밀한 페어드 비교치로
  인용하는 것, "거의 해소"라는 표현 — 60일 관찰 후에도 과반
  (51.3%)이 여전히 censored이기 때문이다. 판정: **정확한 표현은
  "부분 완화"(§41)에서 "추가 완화"(§42/§43)로 하향 정정** — R3b는
  Conditional Go를 유지한다(방향성 반전 아님). 신규 실행 없음,
  신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §43.

- 수정일자: 2026-07-18 (2.56순위, 손절(stop-loss) 정책 도입이 총
  기대수익에 미치는 영향 ablation)
- 수정내용: §2.55(§42)가 §38에 신규 추가한 "경로 리스크(MAE)·손절
  정책 부재"에서, "손절선을 도입하면 총 기대수익이 개선되는지
  악화되는지"를 처음으로 직접 검증했다(SPPV-2.55). §42/§43과 동일한
  candidate 정의(would_buy 1048건, 60거래일 관찰)로 baseline(손절
  없음)·-15% 손절·-20% 손절 3개 변형을 동시 시뮬레이션했다. **결과:
  baseline 총 기대수익 proxy=9734.7(t=5.38, 양수율 52.8%) 대비
  -15% 손절=7024.1(약 27.8% 악화, t=4.25, 양수율 46.4%), -20%
  손절=9093.8(약 6.6% 악화, t=5.02, 양수율 50.7%) — 두 손절
  임계값 모두 총 기대수익을 악화시켰고, 손절이 타이트할수록 악화
  폭이 컸다.** 해석: R3b candidate는 조정 구간(MAE)을 버텨야
  이후 회복분을 취하는 구조라 손절이 그 회복 기회를 원천 차단한다.
  판정: **"경로 리스크·손절 정책 부재"는 "미검증 공백"에서 "시험한
  범위(-15%/-20%) 내에서는 손절 미도입이 총 기대수익 관점에서
  근거 있는 선택"으로 재분류.** R3b는 Conditional Go를 유지한다 —
  방향성 반전 아님. 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §44.

- 수정일자: 2026-07-18 (2.57순위, entry_score 코드 반영 절차 구체화
  — shadow 재구현 정합성 검증)
- 수정내용: §21 게이트는 외생 조건이라 반복 관측만 가능한 반면,
  "entry_score 코드 반영 절차" 착수 전 확인해야 할 선행 질문 —
  SPPV-2.46부터 이 세션 내내 B 시나리오 non-alpha 조정을 수작업
  재구현 `_non_alpha`로 계산해왔을 뿐, 실제 운영 함수 `_build_
  entry_score`를 한 번도 직접 호출한 적이 없었다는 점을 검증했다
  (SPPV-2.56). 코드 대조 결과 `_build_entry_score`에는 `_non_alpha`
  가 담아내지 못하는 portfolio_allocation·source_type 조정 항·
  최종 clamp가 있었으나, 이 세션에서는 항상 `source_type="core"`,
  `portfolio_allocation=None`으로 써서 이론상 no-op이었다. 3년
  전체 후보 표본(58,493건)에서 실제 함수와 재구현을 전수 대조했다.
  **결과: 100.0% 완전 일치, 불일치 0건, 최대 절대 오차 0.0.** 해석:
  이 세션의 모든 B 시나리오 결과가 실제 운영 코드 동작을 정확히
  대표한다는 것이 처음으로 전수 검증됐다. 판정: **"entry_score
  코드 반영 절차"는 "설계 논의 단계"에서 "shadow 계산 정합성
  확보, 실제 코드 변경 PR 작성 가능 단계"로 격상**됐다 — 다만
  §21 게이트는 불변이라 SPPV-3 확정 Go는 아니다. R3b는 Conditional
  Go를 유지한다. 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §45.

- 수정일자: 2026-07-18 (2.58순위, SPPV-2.56 결론 문구 정밀화 —
  "직접 호출" 서술 범위·표본 서술 정정)
- 수정내용: 신규 실행 없이 §2.57(§45)의 두 표현을 기존 코드 재검토
  로 정정했다(SPPV-2.57). **정정 1**: "실제 함수를 한 번도 직접
  호출한 적이 없었다"는 과장 — `_build_entry_score`는 시나리오
  A(현행 regime)로는 `validate_alpha_layer_buy_funnel_comparison.py`
  와 `validate_r3b_point_in_time_pipeline_shadow.py`에서 이미
  직접 호출돼왔다. 정확한 표현: "B 시나리오(`risk_tone="neutral"`
  치환) 입력으로는 §45 이전까지 직접 호출한 적이 없었다". **정정
  2**: 이번 검증은 non-alpha 조정 항(core/None/neutral 조건)만
  증명했을 뿐, R3b alpha 교체 전체 경로의 실제 코드 반영 후 재현성과
  held_position/실제 portfolio_allocation 케이스는 미검증 — "B
  시나리오 전체가 실제 운영 코드와 동일"은 범위를 넘는다. **정정
  3**: "candidate 전량"은 부정확 — quintile 선별·eligibility
  필터링 없이 전체 거래일 스냅샷(58,493건)을 순회했으므로 정확한
  표현은 "전체 시점 스냅샷(모집단 전체)". 판정: **세 정정 모두
  R3b 방향성·Conditional Go를 바꾸지 않는다** — §45의 핵심 결론은
  그대로 유효하며 필요 이상으로 보수적으로 낮추지 않는다. 신규
  실행 없음, 신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §46.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.59순위, §21 gate 환경별 적용 범위 정밀화 —
  production 잠금과 paper/shadow 관측 분리)
- 수정내용: `§21 gate`의 목적과 적용 범위를 문서상 분리해 정정했다
  (SPPV-2.58). 기존 서술은 §21 게이트를 "SPPV-3 착수 검토를 시작할
  수 있는 유일한 외생적 차단 요인"으로 유지해 왔는데, 현재 단계가
  **Paper Probe / shadow 관측**이라는 점을 함께 읽지 않으면 paper
  실측 데이터 수집까지 일괄 보류해야 하는 것으로 오해될 여지가
  있었다. 이번 정정의 canonical 해석은 다음과 같다. **production**:
  §21 게이트는 실제 자본 파산 방지를 위한 엄격 잠금선으로 유지.
  **paper/shadow**: 향후 환경 인지형 우회(config 스위치) 구현 시
  §21 게이트는 실운영 승격 잠금선으로만 해석하고, compliance / VaR /
  broker submit 경계를 유지한 채 R3b 신호의 실측 수집은 허용 가능.
  이번 턴은 문서 정정만 수행했으며 운영 코드 변경·판정 변경은 없다.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.60순위, `§21 gate` config 기반 gate 제어 —
  mode-agnostic 신규 모듈 구현)
- 수정내용: **[정정] 바로 위 2.59순위 항목의 "환경 인지형 우회
  (paper/production 분기)" 프레이밍은 부정확하다 — 실제 구현은
  environment 분기가 아니라 config 스위치 하나만으로 판정하는
  mode-agnostic 방식이다.** 코드베이스 전수 조사 결과 `§21 게이트`
  (regime_switch_v1)는 지금까지 실제 운영 코드(`assess_
  deterministic_triggers`) 어디에도 연결되지 않은 순수 모니터링
  산출물이었다 — R3b shadow/paper 관측은 이 게이트에 의해 코드
  레벨에서 전혀 막힌 적이 없다. `deterministic_trigger_engine.py`
  는 이 세션의 "절대 수정하지 않는다" 원칙에 따라 이번에도 수정
  하지 않고, 신규 격리 모듈로만 구현했다. `AppSettings.regime_
  switch_v1_gate_override_enabled`(env: `REGIME_SWITCH_V1_GATE_
  OVERRIDE_ENABLED`, 기본값 False) + `services/regime_switch_
  gate.py`(신규)의 `assess_regime_switch_v1_gate()` 순수 함수 —
  paper/real/production 값은 전혀 참조하지 않는다. override off면
  기존 §21 해석과 동일(TRIGGERED일 때만 열림), override on이면
  국면 상태와 무관하게 항상 열림, reason_code로 항상 추적 가능.
  `scripts/validate_regime_switch_gate_config_override.py`로 검증:
  운영 코드 미수정 확인(소스 검사), 실제 게이트 상태 여전히 NOT_
  TRIGGERED, override off/on 및 3개 trigger_status 시나리오 전부
  예상대로 동작. 판정: R3b는 Conditional Go를 유지한다 — 게이트
  상태 불변, `deterministic_trigger_engine.py` 미수정, compliance/
  VaR/broker submit 경계 미변경, 아직 실제 파이프라인 미연결(별도
  승인 필요). 신규 KIS 호출 0건. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §47.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.61순위, `§21 gate` 실제 판단 경로 연결
  완료 — `deterministic_trigger_engine.py` 실제 수정)
- 수정내용: **[정정] 2.60순위(§47)의 "구현 완료"는 부정확 — 정확히
  는 "준비 모듈 + 런타임 미연결" 상태였다.** 이번 턴은 그 미완
  지점을 메웠다(SPPV-2.59). 사용자의 명시적 승인 아래 이 세션
  최초로 `deterministic_trigger_engine.py`를 실제로 수정 — `assess_
  deterministic_triggers`(실제 BUY_CANDIDATE 판정 함수)에 신규
  optional 파라미터(`regime_switch_v1_trigger_status`, 기본값 None
  = 게이트 체크 완전 비활성화; `regime_switch_v1_gate_override_
  enabled`, 기본값 False)를 추가하고 BUY_CANDIDATE 조건문에 실제로
  연결했다. 기존 호출부는 100% 무영향(하위 호환). `scripts/
  validate_r3b_gate_integration_path.py`로 동일한 실제 함수를 3가지
  (게이트 없음/override off/override on)로 직접 호출한 결과, 게이트
  가 실제로 `buy_candidate`를 차단하고 override가 실제로 그 차단을
  해제함을 확인(`gate_actually_blocks_real_path=True`, `override_
  actually_restores_real_path=True`). 기존 단위 테스트 20건 전부
  통과. 판정: **"§21 게이트 → 실제 판단 경로" 연결이 완료됐다** —
  다만 실제 운영 호출부(orchestrator)의 배선은 별도 미완료(그 전까지
  실제 운영 동작 무영향, 의도된 안전장치). R3b는 Conditional Go를
  유지한다. compliance/VaR/broker submit 경계 미변경. 신규 KIS
  호출 0건. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §48.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.62순위, `§21 gate` 상위 호출부(`decision_
  orchestrator.py`) 배선 완료)
- 수정내용: **[정정] 2.61순위(§48)의 "실제 판단 경로 연결 완료"는
  과장 — `assess_deterministic_triggers` 함수 내부는 연결됐으나
  그 유일한 실제 상위 호출부 `DecisionOrchestratorService`(`decision_
  orchestrator.py`)는 신규 파라미터를 전혀 넘기지 않고 있었다.**
  이번 턴이 그 gap을 메웠다(SPPV-2.60). `DecisionOrchestratorService.
  __init__`에 `regime_switch_v1_trigger_status`(기본값 None),
  `regime_switch_v1_gate_override_enabled`(기본값 False) 생성자
  인자를 추가하고 실제 호출에 전달, `scripts/run_decision_loop.py`
  의 두 생성 지점 전부에서 `resolve_cached_trigger_status()`(신규
  read-only 헬퍼, `logs/regime_switch_v1_gate_monitor_*.json` 캐시
  조회)와 config 값을 실제로 전달하도록 배선했다. `scripts/
  validate_r3b_orchestrator_gate_wiring.py`로 `DecisionOrchestrator
  Service`를 실제로 구성해 검증한 결과, 게이트가 실제로 buy_
  candidate를 차단하고 override가 실제로 그 차단을 해제함을 확인
  (`gate_blocks_via_orchestrator=True`, `override_restores_via_
  orchestrator=True`). 기존 단위 테스트 83건 전부 통과. **중요
  리스크**: 이 배선 완료로 `run_decision_loop.py`가 이제 실제 §21
  게이트 상태(NOT_TRIGGERED)를 읽어 전달하므로, override가 기본값
  False인 한 core BUY_CANDIDATE 판정이 실제로 영향받기 시작한다 —
  사용자 확인이 필요한 새로운 실제 동작 변화다. 판정: **"§21 게이트
  → 실제 판단 경로" 연결이 함수 내부뿐 아니라 상위 호출부까지
  완료됐다.** R3b는 Conditional Go를 유지한다. compliance/VaR/
  broker submit 경계 미변경. 신규 KIS 호출 0건. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §49.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.63순위, SPPV-2.60 보고 정정 — `resolve_
  cached_trigger_status()` None 원인 규명 + 테스트 증빙 재확인)
- 수정내용: **[정정] §49(2.62순위)의 검증 산출물에서 `resolve_
  cached_trigger_status_current_value=None`이었으나, 실제로는
  캐시 파일 2개(2026-07-14/2026-07-17) 모두 `trigger_status=
  "NOT_TRIGGERED"`를 담고 있었다.** 원인 규명(SPPV-2.61) 결과 코드
  결함이 아니라 기본 `glob_pattern`이 상대경로라 cwd에 의존했기
  때문이었다 — §49 검증이 실행된 Docker 컨테이너에 캐시 JSON 파일이
  복사돼 있지 않아 `glob`이 빈 결과를 반환한 것. `regime_switch_
  gate.py`에 프로젝트 루트 기준 절대경로 앵커링을 추가해 수정(환경
  분기 없음). 재검증 결과 cwd와 무관하게 `NOT_TRIGGERED`를 정확히
  반환함을 확인. "83건 테스트 통과"는 사실이었으나 실행 로그가
  남아있지 않았던 문제도 `python3 -m pytest`를 실제로 재실행하고
  `logs/r3b_pytest_run_2026-07-18.log`(83 passed)로 증빙을 보강해
  정정했다. 판정: **"배선은 완료됐으나 캐시 상태 전달에는 추가
  수정이 필요"했던 상태에서 "캐시 상태까지 정상 전달됨"으로
  확정.** §49.6의 리스크는 이번 수정으로 더 급해졌다. R3b는
  Conditional Go를 유지한다. compliance/VaR/broker submit 경계
  미변경. 신규 KIS 호출 0건. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §50.
  **[운영 결정 추가]** 게이트 배선은 유지하고, paper/shadow 관측
  단계에서는 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 상태로
  커밋/운영한다. 이는 environment 분기 코드가 아니라 명시적 config
  override 운영 절차다. `trigger_status` 공급원 자동화는 후속 과제로
  남긴다.

- 작성자: Codex
- 수정일자: 2026-07-18 (2.64순위, 국면 혼합도 모니터링 모듈 구현 및
  §40 재현성 검증)
- 수정내용: 최신 truth(commit `aa10caee`로 §21 게이트 배선 완료,
  `.env`에 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 설정,
  paper 관측 단계에서 게이트는 BUY를 막지 않음)를 확정한 뒤, 후속
  과제 후보(trigger_status 자동화/혼합도 모니터링 설계/T+5 후속
  검증/SPPV-3 착수 준비) 중 **혼합도 모니터링 설계**를 이번 턴
  최우선으로 선택했다(SPPV-2.62) — trigger_status 자동화는
  override=true인 동안 급하지 않고, T+5/경로 리스크는 §41~§44에서
  이미 충분히 답변됨. §40이 확정한 혼합도 3분위 경계값(cut1=0.15,
  cut2=0.3833)을 신규 모듈 `services/regime_mixedness_monitor.py`
  (BUY/SELL 미연결 순수 관측용)로 재구현하고, 벤치마크 3년 캐시
  bars만 재사용해(신규 KIS 호출 0건) 634거래일 전체를 재분류했다.
  **결과: 버킷별 거래일 수(저혼합 217일/중혼합 215일/고혼합 202일)
  가 §40 실측치와 정확히 일치.** 해석: 가설을 다시 검증한 것이
  아니라 그 검증 결과를 실제로 소비 가능한 재사용 가능 코드 모듈로
  정확히 이식했다는 것을 100% 재현성으로 확인 — "혼합도 모니터링
  설계" 다음 단계가 설계 스케치에서 검증된 모듈로 전진했다. 판정:
  **R3b는 Conditional Go를 유지한다.** 신규 KIS 호출 0건, 운영
  코드 미변경, compliance/VaR/broker submit 경계 미변경. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §51.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.65순위, 국면 혼합도 모니터링을 실제
  decision loop 관측 경로에 연결)
- 수정내용: §51(2.64순위)이 검증만 하고 미연결로 남긴 gap을
  메웠다(SPPV-2.63). 후속 과제 후보 중 **혼합도 모니터링의 실제
  소비 위치 연결**을 최우선으로 선택 — trigger_status 자동화는
  override=true인 동안 급하지 않고, T+5/경로 리스크는 §41~§44에서
  이미 답변됨. `scripts/run_decision_loop.py`에 신규 함수 `_run_
  mixedness_check()`를 추가 — 기존 `_run_precheck()`와 동일한
  cycle당 1회 안전 패턴으로, 벤치마크 `signal_feature_snapshots`
  최근 60건을 read-only 조회(신규 KIS 호출 없음)해 §51 모듈로
  국면 혼합도 버킷을 계산·로그에 남긴다. **BUY/SELL 판정에는 전혀
  연결하지 않았다.** in-memory repos로 저혼합/고혼합 두 시나리오를
  `_run_mixedness_check()` 실제 호출로 검증한 결과 둘 다 정확히
  분류됨을 확인, 소스 검사로 BUY/SELL 판정 코드가 전혀 없음도
  확인. 기존 단위 테스트 10건 실패는 변경 전에도 동일하게 실패하는
  사전 존재 결함임을 stash 재실행으로 확인(무관). 판정: **R3b는
  Conditional Go를 유지한다.** BUY/SELL 게이트 로직은 더 세지지
  않았다 — 관측/로깅 경로만 추가. 신규 KIS 호출 0건, `.env` 미수정,
  environment 분기 없음, compliance/VaR/broker submit 경계
  미변경. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §52.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.66순위, SPPV-2.63 미확정 항목 확정 —
  `test_run_decision_loop.py` 10건 실패 무관 확정)
- 수정내용: §52(2.65순위)의 "stash 재실행으로 확인(무관)"은
  증빙이 약했다 — `git worktree`로 §52 이전 커밋(`4fd3ad7e`)을
  메인 워크트리와 분리해 체크아웃한 뒤, Docker 컨테이너 안에서
  PRE/POST 두 버전을 각각 `pytest -v --tb=long`으로 전체 재실행,
  807줄 로그를 `diff`로 직접 비교했다(SPPV-2.64). 실패 10건 이름·
  에러 메시지·assertion 내용까지 완전히 동일(차이는 비결정적
  메모리 주소와 71줄 오프셋뿐), `grep`으로 mixedness 관련 문자열이
  실패 stack trace 어디에도 없음을 확인. 판정: **`무관 확정`** —
  10건 실패는 `universe_selection.py`/AsyncMock 타입 불일치 관련
  사전 존재 결함이며 §52의 국면 혼합도 모니터링 연결과 완전히
  무관하다. R3b는 Conditional Go를 유지한다 — 이번 턴은 코드를
  전혀 수정하지 않았다(순수 검증 확정). 신규 KIS 호출 0건. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §53.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.67순위, entry_score 코드 변경 PR 초안
  설계 — R3b alpha 교체 실제 파이프라인 연결 방안)
- 수정내용: "R3b alpha 전체 경로 재현 검증"은 §45(non-alpha 100%
  일치)의 논리적 귀결이라 다시 실측하지 않고, 이 세션에서 한 번도
  명시되지 않은 **아키텍처 제약**을 조사했다(SPPV-2.65): entry_
  score는 종목 단위로 계산되지만 R3b alpha(candidate_percentile)
  는 당일 cross-sectional 순위가 필요해 사전 계산 단계가 있어야
  한다. `run_decision_loop.py`의 기존 `_build_core_risk_off_
  apply_overrides_for_cycle()`(cycle당 1회 전체 universe precompute
  → override 주입)이 정확히 필요한 선례로 이미 존재함을 확인 —
  이를 근거로 실제 코드 diff 초안(신규 precompute 함수 1개 +
  optional 파라미터 2개 + config 스위치 1개, 전부 §48/§49와 동일
  기본값-비활성 패턴)을 설계했다. **미적용, 코드 변경 없음.** 판정:
  "entry_score 코드 반영 절차"는 "shadow 정합성 확보"에서
  "구체적 구현 설계 확보(diff 초안)"로 진전됐다 — 실제 적용은
  별도 승인 필요. R3b는 Conditional Go를 유지한다. 신규 KIS 호출
  0건, compliance/VaR/broker submit 경계 미변경. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §54.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.68순위, entry_score R3b alpha 교체 —
  1단계 엔진 파라미터 배선 실제 코드 적용)
- 수정내용: §54(SPPV-2.65) 설계 중 실전진에 직접 기여하는 "1단계:
  엔진 파라미터 배선"만 선택해 실제 코드로 적용했다(SPPV-2.66).
  `settings.py`에 `entry_score_r3b_alpha_enabled` config 스위치
  (기본값 False) 추가, `deterministic_trigger_engine.py`에 `r3b_
  alpha_percentile`/`r3b_alpha_enabled` optional 파라미터 2개 추가
  — §48/§49와 동일한 기본값-비활성 backward-compat 패턴. 기존
  회귀 테스트 83건 전부 통과, 활성 경로 ad-hoc 검증(percentile=0.9
  → entry_score=0.72, 기대값과 완전 일치) 완료. cycle 단위
  precompute("2단계")는 범위 밖, 별도 승인 대상 유보. `.env` 미변경,
  gate 로직 강화 없음. R3b는 Conditional Go를 유지한다. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §55.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.69순위, entry_score R3b alpha 교체 —
  2단계 순수 계산 모듈 + orchestrator 배선 실제 코드 적용)
- 수정내용: §54.5 설계 중 "2단계"를 실제 코드로 전환했다(SPPV-2.67).
  신규 `services/r3b_alpha_percentile.py`(shadow 스크립트 로직 이식,
  200회 무작위 trial 전부 일치), `decision_orchestrator.py` config·
  metadata 추출·배선, `run_decision_loop.py` 두 지점 config 전달.
  cycle당 1회 실제 계산·주입("3단계")은 범위 밖 — 현재는 활성화해도
  alpha 교체가 실제 발동하지 않는다. 이번 턴 직접 재실행 근거만
  사용(재인용 금지): `test_deterministic_trigger_engine.py`+
  `test_decision_orchestrator.py` 83 passed/0 failed; `test_run_
  decision_loop.py` 10 failed/109 passed(§53 확정 실패와 동일);
  DB 연동 테스트 6건 실패는 `TooManyColumnsError` 사전 존재 환경
  이슈로 확인(코드 배선과 무관). `.env` 미변경. R3b는 Conditional
  Go를 유지한다. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §56.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.70순위, SPPV-2.67 보고 정정 — "2단계
  완료" 표현의 과장 부분 확정)
- 수정내용: 새 기능 구현 없이 §56(SPPV-2.67)의 서술을 코드 기준
  으로 재검증했다(SPPV-2.68). 3개 파일(`r3b_alpha_percentile.py`/
  `decision_orchestrator.py`/`run_decision_loop.py`) 직접 확인 결과
  — 순수 계산 모듈은 존재하나 production 코드 어디서도 import되지
  않는 고립 모듈; orchestrator의 metadata 읽기·엔진 전달 배선은
  실제로 존재(사실); `run_decision_loop.py`에는 config 전달 두 줄
  뿐이고 `r3b_alpha_percentile`을 계산·주입하는 코드는 전무(grep
  확인). "2단계 선택·실행"/"orchestrator까지 배선 완료"/"전원이
  꽂히지 않은 상태" 표현은 과장으로 확정 — cycle 단위 precompute는
  이 세션 전체에서 production 코드로 옮겨진 적이 없다. R3b 판정은
  코드 변경이 없어 불변(Conditional Go). 이력 보존형 정정. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §57.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.71순위, entry_score R3b alpha 교체 —
  cycle precompute 실제 구현·발동 확인)
- 수정내용: §57이 남긴 유일한 실행 단계(cycle precompute)를 실제로
  구현했다(SPPV-2.69). `run_decision_loop.py`에 신규 precompute
  함수 + cycle당 1회 호출 + `SubmitOrderRequest.metadata["r3b_
  alpha_percentile"]` 실제 주입. end-to-end 검증: 실제 DB 종목
  (000080) 기준 비활성 시 entry_score=0.1159 vs 활성+percentile=
  0.9 주입 시 entry_score=0.5999(reason_code 발생) — 실제 발동
  증명. 회귀 테스트 83건 통과, `test_run_decision_loop.py` 8
  failed/111 passed는 git stash 대조로 이번 턴과 무관함(사전 존재
  비결정성) 확인. `.env` 미변경. R3b는 Conditional Go를 유지한다.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §58.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.72순위, SPPV-2.69 보고 증빙 정정 — 테스트
  수치·실행 증빙 재확인)
- 수정내용: 새 기능 구현 없이 §58(SPPV-2.69)의 수치·실행 증빙을
  실제 파일/로그 기준으로 재검증했다(SPPV-2.70). 기존 `logs/r3b_
  pytest_run_decision_loop_2026-07-19.log`는 §53의 오래된 로그
  (10 failed/109 passed)였고, §58이 인용한 "8 failed/111 passed"는
  저장소 로그가 아니라 대화 출력 인용이었음을 확인. end-to-end
  검증 스크립트 실행 결과도 저장소 산출물이 없었음을 확인. 이번
  턴 재실행으로 4개 신규 로그/JSON 저장 — 수치 전부 §58과 정확히
  일치 재현(8 failed/111 passed; entry_score 0.1159→0.5999). 판정:
  "결론 유지 + 증빙 보강"(결론 하향 아님). R3b는 Conditional Go를
  유지한다. `.env` 미변경, production 코드 미변경. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §59.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.73순위, R3b alpha paper 운영 전환 최종
  착수 준비 상태 점검)
- 수정내용: "config만 켜면 되는가"를 판정하는 준비 턴(SPPV-2.71).
  DB 직접 조회로 신규 사실 확인 — 벤치마크(069500) `signal_
  feature_snapshot`이 DB에 0건, 일일 배치 입력 목록(`data/signal_
  feature_snapshot_input.json`)에 애초에 미포함. 이 때문에 `ENTRY_
  SCORE_R3B_ALPHA_ENABLED=true` 전환해도 alpha 교체가 실제로는
  발동하지 않는다 — "구현 완료"와 "운영 전환 준비 완료"를 분리
  확정. SPPV-3 남은 항목을 실제 차단 요소/사용자 결정 대기/후속
  검증 과제 3분류로 재정리. R3b는 Conditional Go를 유지한다. `.env`
  미변경, 코드 변경 없음. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §60.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.74순위, 벤치마크(069500) signal_feature_
  snapshot 배치 미포함 문제 실제 해소)
- 수정내용: §60이 확인한 유일한 실제 차단 요소를 실제로 해소했다
  (SPPV-2.72). `generate_signal_feature_snapshot_input.py`에 신규
  함수 추가(기존 벤치마크 상수 재사용, 거래 universe 불변). 실제
  KIS 조회+CLI 실행+DB 재조회로 069500 snapshot 0건→1건 실측 확인,
  precompute 재호출로 빈 dict 탈출 확인. 회귀 무손상. 판정: 실제
  차단 요소 해소 — `ENTRY_SCORE_R3B_ALPHA_ENABLED=true` 전환 시
  이제 실제 발동 가능. R3b는 Conditional Go를 유지한다. `.env`
  미변경, 신규 KIS 호출 1건(read-only). 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §61.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.75순위, R3b alpha 운영 반영 여부 실제
  점검 — docker-compose 환경변수 배선 미비 신규 발견)
- 수정내용: "이미 `.env`에 반영된 값이 실제 paper decision loop에
  도달했는지"를 점검했다(SPPV-2.73). 호스트 `.env`에는 `ENTRY_
  SCORE_R3B_ALPHA_ENABLED=true`가 실제로 있음을 확인(사용자 전제
  정확). 그러나 실행 중인 `ops-scheduler` 컨테이너는 이 값을
  전혀 읽지 못한다 — `Dockerfile`이 `.env`를 COPY하지 않고,
  `docker-compose.yml`도 `env_file`/마운트로 지정하지 않으며,
  `environment:` 화이트리스트에 이 변수(및 `REGIME_SWITCH_V1_
  GATE_OVERRIDE_ENABLED`)가 없다. 실행 중 프로세스 실제 환경변수를
  직접 읽어 부재 확인 — R3b alpha에 국한되지 않는 구조적 문제.
  최근 3일 연속 비거래일로 decision loop 자체도 최근 실행되지
  않았음을 로그로 확인. 3단계 분리: 코드 완료(예)/env 설정(예)/
  실행 중 반영(**아니오**). 코드/`.env`/`docker-compose.yml` 미변경,
  컨테이너 재시작 없음. R3b는 Conditional Go를 유지한다. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §62.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.76순위, docker-compose 환경변수 배선
  실제 수정 — R3b alpha/§21 게이트 override 운영 반영 완료)
- 수정내용: §62가 확인한 실제 차단 요소를 실제로 해소했다(SPPV-
  2.74). `docker-compose.yml`의 `ops-scheduler` `environment:`
  블록에 기존 패턴 그대로 두 변수 추가(기본값 false, 분기 없음),
  `--force-recreate --no-deps`로 재생성. 재생성 후 실제 프로세스
  env 확인 결과 두 값 모두 `true`, `/app/.env` 파일은 여전히
  없음(compose 주입만으로 전달 증명), 컨테이너 안에서 `AppSettings
  ()` 실행 결과도 `True True`. 재생성 후 로그 정상(비거래일 정상
  판정, submit_count=0, 예기치 않은 주문 없음). 판정: 실제 차단
  요소 완전 해소 — R3b alpha/§21 게이트 override 모두 이제 실제
  paper 운영 프로세스에 도달. R3b는 Conditional Go를 유지한다.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §63.

- 작성자: Codex
- 수정일자: 2026-07-19 (2.77순위, 보유기간/Churn 제어가 R3b BUY
  빈도를 얼마나 깎는지 정량 검증 — canonical 문서 `docs/` 재배치
  이후 첫 턴)
- 수정내용: churn guard가 R3b BUY_CANDIDATE 빈도를 실제로 얼마나
  억제하는지 운영 함수·실제 운영 DB로 정량 분해했다(SPPV-2.75).
  실제 운영 창(2026-05-13~07-16)의 churn 관련 guard 차단 144
  episode를 `_build_entry_score()`로 재계산한 결과 전부 entry_
  score<0.65(candidate 0건) — R3b 고품질 BUY 과잉 억제 증거 없음,
  다만 표본이 작고 일부 guard 미발동이라 판정은 Watch. R3b 자체
  판정(Conditional Go)은 이 검증과 무관하게 유지. 코드 변경 없음,
  신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §64.

- 작성자: Codex
- 수정일자: 2026-07-20 (2.78순위, R3b alpha가 실제 paper 운영
  경로에서 정말 발동하는지 최종 실증)
- 수정내용: env/config→코드 경로→percentile 계산·주입→실제
  decision 영향 4단계로 분리 실측했다(SPPV-2.76). 오늘 실제 운영
  로그에 R3b alpha precompute 26회 반복 확인, 실제 `trade_
  decisions`에서 000810이 `entry_score=0.7856, buy_candidate=
  True`로 24시간 26/26회 재현됐으나 `candidate_vs_final.alignment_
  status=downgraded`로 AI 최종 결정 합성기가 매번 WATCH/HOLD로
  하향(risk/compliance/expected_value_gate 통과 상태였음 — 별도
  후속 축). 판정: **작동하나 체감 무효**. R3b 구현 판정(Conditional
  Go) 불변. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
  v1.md` §65.

- 작성자: Codex
- 수정일자: 2026-07-20 (2.79순위, SPPV-2.76 해석 정밀 보정 — "BUY
  부재" 원인의 3층 분리 정량화)
- 수정내용: §65의 "downgrade가 BUY 부재의 직접 원인"이라는 서술은
  000810 1개 종목에만 적용되는 설명을 전체로 일반화한 과장이었음을
  정정했다(SPPV-2.77). 실제 `trade_decisions` 재조회(24시간, R3b
  reason code 66건)로 층1(downgrade, 33건 전부 000810)/층2(애초
  비후보, 33건 전부 000660)를 정확히 절반씩 분리 확인. 운영 로그
  재확인 결과 층3(pre-AI core_risk_off_ranking 차단)이 universe
  12종목 중 11종목(91.7%)에 영향 — R3b 후보 풀(2종목)보다 훨씬
  넓은 범위. 판정: **복합 병목** — 세 층을 같은 원인으로 묶으면
  안 됨. R3b 작동 자체 판정(작동하나 체감 무효) 불변. 코드 변경
  없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §66.

- 작성자: Codex
- 수정일자: 2026-07-20 (2.80순위, BUY_CANDIDATE 최종 통과 0건의
  직접 병목 정밀 분해)
- 수정내용: "차단 장치 전면 완화"가 아니라 000810 BUY_CANDIDATE
  (24h 36건)이 최종 BUY 0건으로 귀결되는 정확한 지점을 funnel로
  특정했다(SPPV-2.78). candidate→eligibility→candidate_intent=
  buy까지 무손실(36→36→36), `candidate_vs_final`에서 100% 손실
  (final_intent=buy 0, decision_type=BUY 0, order request 0).
  universe 전체 24h decision_type도 BUY=SELL=REDUCE=EXIT=0(더 넓은
  맥락). 000810의 AI 최종 합성기 실제 호출(`fdc_skipped=False`)과
  `opposing_evidence`(risk_off/전략 충돌/weak evidence)가 36회
  거의 동일 문구 반복 — 정당한 방어 논리일 수 있으나 국면 라벨
  고착 가능성도 배제 못 함. 판정: 층1(downgrade)만 **정밀 보정
  필요**(우선 완화 아님), 층2·층3은 유지. R3b 작동 판정 불변. 코드
  변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
  sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §67.
- **3순위(보류 유지, 형태 재정의 — 우선순위 재조정)**: **`entry_
  score`와 BUY funnel 재현** — §2.7 확장 검증에서 하락장 안정성이
  확인되지 않아 단순 재현으로는 착수하지 않는다. §2.16~§2.21에서
  국면 정의 통일(차단 축)은 Watch/No-Go에 근접한다는 것이 확인됐고,
  §2.22에서 alpha layer 교체(선별 축)는 Conditional Go를 확보했고,
  **§2.28~§2.29에서 그 Conditional Go가 실제 virtual BUY funnel
  (candidate→eligible→selected→would_buy, MFE/MAE 포함)까지 방향
  일관되게 보강됨을 확인했다. §2.30에서 "0.65 문턱 사실상 무력화"
  caveat의 해소안(R3)이 분기 재현성 검증에서 무너졌고, §2.32에서
  candidate 내부 기준 변형(R3b)이 잠정 유력 후보로 격상됐으나,
  §2.33의 대응표본 직접 검증에서 그 근거(overlap)가 부족했음이
  드러나 R3b도 다시 Watch로 하향됐다. §2.34~§2.35의 정밀 분해는
  그 aggregate 우위가 순수 replacement_effect에서 오고 대부분의
  구간에서 날짜 집중형도 아님을 확인해 우위의 근거를 강화했으나,
  분기3만은 명백한 반례이자 실제 날짜 집중형임을 확인해 Watch
  판정을 유지할 근거로 남겼다. §2.36의 분기3 거래일별 세부 진단은
  이 반례의 구조를 더 정밀화했으나, §2.37에서 5분위 구간화로
  재검증한 결과 "대형 스왑일 전적 의존"은 과장으로 정정됐다 —
  aggregate 순 기여는 상당하나(T+5 약 70%, T+20 약 35%), 총 양(+)
  합계 관점에서는 15%에 불과하고 "대형=양(+)/소규모=음(-)"도
  양극단(Q1·Q5)에서만 성립한다. **§2.38에서 R3b의 SPPV-3 진입
  후보 여부를 판단한 결과, 실제 BUY funnel 8개 창에서 T+20 평균
  우위 8/8 일관·t_NW 6/8 유의를 재확인했고, 신규로 would_buy
  모집단의 거래일 편중도를 계측해 "거래일 집중 의존"이 R3b만의
  문제가 아니라 R0(기준선) 자체의 특성(8개 창 중 3개에서 상위 10%
  거래일 제거 시 평균이 마이너스로 반전)이며 R3b가 오히려 8/8 창
  에서 R0보다 덜 의존적임을 확인했다 — R3b를 Watch에서 Conditional
  Go로 상향한다(조건부: marginal t_NW 재확인, 거래 빈도 축소의
  총 기대수익 영향 정량화, §3 전제조건, point-in-time 파이프라인
  반영 shadow 실행이 확정 Go 전 필요). §2.39에서 §2.38의 수치
  오류 3건을 정정했으나 모두 방향성 우위를 약화시키지 않아
  Conditional Go는 유지됐고, §2.40에서 "거래 빈도 축소의 총
  기대수익 영향 정량화" 조건을 실제로 계측한 결과 8개 창×2horizon
  16개 조합 중 14개에서 R3b의 총 기대수익 proxy가 R0보다 높아
  (92.0%~322.6%) 확정 Go 전 잔여 조건 4개 중 1개가 해소되고
  Conditional Go 근거가 보강됐다 — 나머지 3개 조건(marginal t_NW,
  §3 전제조건, point-in-time 파이프라인 반영)은 그대로 남아
  확정 Go는 아니다. §2.41에서 §2.40의 "조건 (2) 해소"를 유휴 자본
  기회비용까지 반영해 다시 검증한 결과, T+20은 8개 창 중 7개에서
  엄격 기준(R0 이론적 최대 대비)에서도 여전히 R3b 우위이나 T+5는
  8개 창 중 6개에서 우위가 사라지거나 이미 열세임을 확인해 "조건
  (2) 해소"를 "T+20 완화·T+5 미해결" 수준으로 재조정했다 — R3b는
  Conditional Go를 유지한다(확정 Go 아님). **§2.42에서 "이 시스템이
  T+20 중심인가"를 코드로 직접 조사한 결과, SELL/청산이 100%
  exit_score(신호/점수) 기반이고 경과일수를 참조하지 않으며
  max_holding_days=20이 실제로 집행되지 않는 LLM 힌트 기본값에
  불과함을 확인했다 — "T+20 중심이라 T+5를 무시해도 된다"는 주장은
  코드로 뒷받침되지 않는다. R3b는 Conditional Go를 유지하되, T+5
  horizon 강건성 확보(또는 실거래 누적 후 청산 시점 분포 실측)를
  확정 Go의 필수조건으로 격상했다. **§2.43에서 실제 point-in-time
  entry_score 파이프라인의 누락된 조정항(`strategy_selection`,
  +0.05 보너스)을 실제 `select_strategy()`로 채워 A/B 양쪽에 반영한
  결과, 8개 창×2horizon 16개 조합 전부에서 R3b>R0 방향이 유지됐으나
  분기1 T+20의 t_NW가 1.31→0.96으로 더 약화됐다 — R3b는 Conditional
  Go를 유지하되, "point-in-time 파이프라인 반영" 조건은 부분 해소
  (`portfolio_allocation` gap은 미해결)로 기록했다. **§2.44에서
  분기1 t_NW 약화 원인을 정밀 진단한 결과, 분기1은 세 분기 중
  가장 혼합 국면(강세/횡보/약세 고른 분포) 구간이며 R3b>R0 방향은
  그대로 유지(스왑일 71.7%가 양(+), 최다)되나 상위 스왑일 10건 중
  3건의 극단치(±16~44%p)가 표준오차를 키워 t_NW를 낮췄음을 확인 —
  방향성 붕괴가 아니라 소수 극단치로 인한 분산 문제로 좁혀져 R3b는
  Conditional Go를 유지한다. **§2.45에서 SPPV-3 진입 관문 3종(§3
  전제조건/분기1 약화/T+5 취약성)을 종합 판정한 결과, §3 게이트를
  재확인해도 여전히 NOT_TRIGGERED(하락장 미도래)이고, 분기1·T+5는
  각각 관리 가능한 잔여 리스크·미해결이나 치명적이지 않은 리스크로
  확인됐다 — R3b는 Conditional Go를 유지하되, SPPV-3(운영 코드
  반영) 진입은 R3b의 성과와 무관한 §3 게이트 미충족 때문에 아직
  이르다. §2.47에서 §3 전제조건 ②(risk_off_penalty 중복 해소)를
  R3b candidate 위에서 실측한 결과, eligibility 축은 R3b candidate
  pool에서 비활성(중복 우려 자체가 발생하지 않음)이고 entry_score
  축은 제거 시 총 기대수익 proxy가 약 20% 개선되나 MAE도 소폭
  악화되는 실제 트레이드오프임을 확인 — §3 조건②를 "방향 확인,
  사용자 승인 대기"로 진전시켰으나 §21 게이트 미충족은 불변이라
  SPPV-3 진입은 여전히 이르다. §2.48에서 사용자가 entry_score
  축만 승인함에 따라 기존 산출물을 재해석한 결과, T+5/T+20 양쪽
  에서 총 기대수익 proxy가 12.9~20.9% 개선되고 MAE 악화(5.9~
  7.8% 상대)는 개선폭보다 항상 작아 정당화 가능함을 확인 — R3b +
  entry_score risk_off_penalty 제거 조합은 Conditional Go를
  보강하며, SPPV-3 진입 관점에서 남은 조건은 사실상 §21 게이트
  하나로 좁혀졌다. §2.49에서 이 "게이트 하나" 서술이 §3 전제조건
  범위로는 정확하나 SPPV-3 진입 전체로는 과장이었음을 바로잡고,
  잔여 조건을 ①주된 차단 요인(§21 게이트) ②보조 잔여 조건
  (entry_score 코드 반영 절차, T+5 구조적 리스크, 혼합 국면
  재확인) ③실거래 누적 없이는 못 푸는 조건(portfolio_allocation
  gap, 실제 청산 시점 분포)으로 재분류했다 — R3b는 Conditional
  Go를 유지한다(방향 후퇴 아님, 서술 정밀도만 회복). §2.50에서
  보조 잔여 조건 중 "혼합 국면 재확인"을 분기4와의 대조로 실행한
  결과, 분기4(시장 공통 국면 사실상 순수 bullish)는 T+20 t_NW=
  3.00·양수율=60.3%로 강하고 일관되나 분기1(혼합 국면)은 t_NW=
  1.27(marginal)로 대비돼 "혼합 국면→약한 t_NW" 가설이 표본 1개의
  우연이 아니라 대조쌍으로 확인됐다 — 조건 해소는 아니나 "미확인
  가설"에서 "확인된 패턴"으로 전진, R3b는 Conditional Go를
  유지한다. §2.51에서 §2.50의 N=2 분기 대조를 넘어 분기 경계와
  무관한 거래일 단위 혼합도(최근 60거래일 창의 최빈 국면 비중 기반
  연속 변수)로 3년 634거래일을 3분위 버킷화한 결과, 저혼합→중혼합→
  고혼합 순으로 T+20 t_NW(3.64→2.51→0.37)·양수율(63.3%→56.8%→
  38.7%)이 단조 감소하고 217/215/202일이 특정 분기에 편중되지 않고
  고르게 분포함을 확인 — "혼합 국면 약세"는 이제 지지 증거 추가를
  넘어 구조적 패턴으로 격상됐으나, R3b 방향성 반전이나 SPPV-3 진입
  추가 지연 사유는 아니다(주된 차단 요인은 여전히 §21 게이트
  하나뿐). §2.52에서 이 §2.51(SPPV-2.50)의 두 결론 문구를 신규
  실행 없이 재점검해 정밀화했다 — "구조적 패턴으로 격상"은 동일
  in-sample 3년 캐시 재확인 + 60일 trailing window 자기상관 때문에
  과장이며 정확히는 "강한 구조적 정합 증거로 격상"이 맞고, "주된
  차단 요인은 §21 게이트 하나뿐"은 "SPPV-3 착수 검토를 시작할 수
  있는 유일한 외생적 조건"이라는 뜻이지 "진입 전체의 유일한 남은
  조건"이 아니다(§38의 ①②③ 분류 불변) — 두 정정 모두 R3b 방향성·
  Conditional Go는 바꾸지 않는다. §2.53에서 §2.48의 보조 잔여
  조건 중 "T+5 구조적 리스크"를 실제 운영 함수 `_build_exit_score`
  (순수 함수)로 point-in-time 재호출해 would_buy candidate 1151건의
  signal-driven 청산 타이밍을 시뮬레이션한 결과, 91.1%가 20거래일
  안에 매도 신호를 넘지 않고 평균 보유일수=19.35일 — 실제 청산은
  T+5가 아니라 T+20 근방(6.14%, t=4.73)에서 발생해 "T+5 평균이
  약하다"는 우려가 실제 운영 리스크로 그대로 전이되지 않음을
  확인했다. 20일 초과 구간·경로 리스크(MAE)는 미검증이라 "부분
  완화"이지 "완전 해소"는 아니다. §2.54에서 관찰 창을 20→60거래일로
  확장해 would_buy 1048건을 재시뮬레이션한 결과, censored 비율
  91.1%→51.3%, 평균 보유일수=48.0일, signal-driven 청산 수익률
  (9.29%, t=5.38)이 오히려 T+20(4.46%, t=3.41)보다 강해 "T+5 구조적
  리스크"는 "부분 완화"에서 "거의 해소"로 격상됐다 — 그러나 MAE
  평균 -11.08%·심각 손실(-20% 이하) 12.8%·손절 임계값 부재가 새로
  드러나 §38 보조 잔여 조건에 "경로 리스크·손절 정책 부재"를 신규
  추가했다(§42). §2.55에서 §2.54(§42)의 "censored 91.1%→51.3%"
  비교와 "거의 해소" 판정을 코드 대조로 재점검한 결과, 20일판·
  60일판 스캔 범위가 서로 달라(60일판이 20일판의 약 91% 부분집합
  으로 추정) 동일 코호트의 순수 전/후 비교가 아니었고, 60일 관찰
  후에도 과반(51.3%)이 여전히 censored라 "거의 해소"는 과장임을
  확인 — 정확한 표현은 "부분 완화"에서 "추가 완화"로 하향 정정
  했다. R3b 방향성·Conditional Go는 바꾸지 않는다(§43). §2.56에서
  §42가 신규 추가한 "경로 리스크(MAE)·손절 정책 부재"에 대해
  -15%/-20% 손절선을 실제 도입하면 총 기대수익이 개선되는지 직접
  검증한 결과, 두 임계값 모두 총 기대수익 proxy를 악화시켰다
  (baseline 9734.7→-15% 손절 7024.1(약 27.8% 악화)→-20% 손절
  9093.8(약 6.6% 악화)) — R3b candidate는 조정 구간을 버텨야
  이후 회복분을 취하는 구조이기 때문이다. "손절 정책 부재"는
  "미검증 공백"에서 "시험한 범위 내에서는 손절 미도입이 총 기대
  수익 관점에서 근거 있는 선택"으로 재분류했다. R3b 방향성·
  Conditional Go는 바꾸지 않는다(§44). §2.57에서 이 세션 내내
  B 시나리오 계산에 써온 수작업 재구현 `_non_alpha`가 실제 운영
  함수 `_build_entry_score`와 정확히 일치하는지 3년 전체 후보
  표본(58,493건)에서 전수 검증한 결과, 100.0% 완전 일치(불일치
  0건)를 확인 — 이 세션의 모든 B 시나리오 결과가 실제 운영 코드
  동작을 정확히 대표한다는 것이 처음으로 검증됐다. "entry_score
  코드 반영 절차"는 "설계 논의 단계"에서 "shadow 계산 정합성
  확보, 실제 코드 변경 PR 작성 가능 단계"로 격상됐으나 §21 게이트는
  불변이라 SPPV-3 확정 Go는 아니다(§45). §2.58에서 §2.57(§45)의
  두 표현을 정정했다 — "한 번도 직접 호출한 적이 없었다"는 과장이며
  `_build_entry_score`는 시나리오 A(현행 regime)로는 이미 이전
  스크립트에서 직접 호출돼왔고, §45가 새로 확인한 것은 "B 시나리오
  (neutral 치환) 입력으로 직접 호출한 적이 없었다"는 좁은 간극이다.
  또한 이번 검증은 non-alpha 조정 항만 증명했을 뿐 R3b alpha 교체
  전체 경로의 실제 코드 반영 후 재현성·held_position 케이스는
  미검증이며, "candidate 전량"이라는 표본 서술도 부정확해 "전체
  시점 스냅샷(모집단 전체)"으로 바로잡았다. R3b 방향성·Conditional
  Go는 바꾸지 않는다(§46).** 한편
  **§2.23~§2.27에서
  결합 사용 시 가장 빈번하게 걸리는 축이 regime 관련 축이 아니라
  활동성 필터(`eligibility_low_relative_activity`)임이 확인됐고,
  완화 효과의 반전이 국면·유동성 구조 차이 때문임을 규명했으나,
  이 필터가 과잉 억제인지·정적 완화가 실제로 기대수익률을
  개선하는지는 여전히 미확정이다(Watch — 격상 근거 없음)**.
  SPPV-3의 다음 착수 항목은 분기3의 스왑 상위 10% 거래일을
  구체적으로 나열해 특정 사유(이벤트/실적 발표 등) 존재 여부 확인,
  R3b의 §3 공식 정식 반영 여부 사용자 종합 판단, 더 긴 표본으로
  재평가, alpha 교체의 §3
  전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_penalty 중복
  해소) 충족 후 재검증과 "국면 조건부 activity threshold" 설계
  검토 여부에 대한 사용자 확인이며, 운영 코드 반영은 Conditional
  Go 이상이 확보된 뒤 사용자 승인을 받아 진행한다. 1차
  게이트(§21 모니터링)가 `TRIGGERED`로 전환되는 즉시
  alpha layer 교체의 최종 Go 여부도 재확인해야 하며, 그 전까지 코드
  변경은 보류한다.
- **4순위**: out-of-sample 기대수익 양수와 손실 제약을 만족한 formula만
  shadow로 유지한 뒤 일일 top-k·최소 수량·계좌 위험한도 아래 제한적 paper
  probe 승격을 별도 승인한다. compliance/VaR/guardrail 경계는 유지한다.
- **차후 보류**: UNIV-5 및 소싱 확장(현 국면 효과 0 확인), freeze 타이밍/
  F5 수정(표면 증상). 어제 배포한 shadow 관측(F5 fallback/momentum)은
  데이터만 축적하도록 방치.

---

## 5. 관련 문서

- `plans/[POLICY] trading_universe_policy_v1.md` — 종목 정책(방어적 설계 확인)
- `plans/[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md` —
  소싱 개선 트랙(현 국면 효과 0으로 확인된 트랙)
- `plans/[ANALYSIS] core_risk_off_floor_v5_report_measurement_2026-07-11.md` —
  백테스트(하락국면 한정)
- `plans/[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md` —
  slow_score 튜닝(proxy shadow, 실집행 아님)
- `plans/[DESIGN] signal_predictive_power_validation.md` — 신호 IC,
  `entry_score`, 전체 BUY funnel과 제한적 probe까지의 단계별 검증 설계
- `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
  — 국면별 신호 극성 전환 종합표 + 상위 재설계 방향 확정(2026-07-15)
- `plans/[DESIGN] regime_conditional_entry_signal_v1.md` — 국면 분기형
  entry 설계 초안 + shadow 계산기(2026-07-15)
- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`
