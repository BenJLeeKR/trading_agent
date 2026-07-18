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

- 작성자: Claude
- 수정일자: 2026-07-15 (14차, regime_conditional_signal Phase 2
  shadow 누적 사이클 구축)
- 수정내용: Phase 2를 실행 가능한 오케스트레이터(신규
  `scripts/run_regime_conditional_shadow_cycle.py`)로 구현했다 —
  게이트 판정(§21)과 신호 계산(§22)을 벤치마크 1회 조회로 통합, 누적
  이력 파일(JSONL, 중복 거래일 자동 skip) 구축, `TRIGGERED` 전환 시
  재검증 runbook 출력. 실행 결과: 게이트 NOT_TRIGGERED, 신호
  2026-07-14 기준 `range_bound`로 87/87종목 `risk_adj_momentum_3m`
  분기 — 이력에 1줄 추가, 재실행 중복 방지 확인. `entry_score` 코드/
  운영 변경 없음.

- 작성자: Claude
- 수정일자: 2026-07-15 (15차, entry_score 중복 penalty ablation 실측)
- 수정내용: SPPV-3 착수 전제("중복 억제 구조 재현·분해")를 실측으로
  구체화했다 — 운영 함수(`_build_entry_score`, `_assess_buy_
  eligibility`)를 그대로 호출해 오늘(87종목) 기준 세 penalty 축을
  독립 평가. B(60건) 발동 종목은 예외 없이 A·C도 함께 발동
  (A∩B∩C=60=B 전체) — "삼중 중복"이 오늘 데이터로 100% 재현됨.
  종목별 regime_label(bearish_trend 69%)이 시장 공통 국면(range_bound)
  과 전혀 다름을 재확인 — entry_score 통합 시 국면 정의 통일이 새로운
  전제로 필요함을 발견. 운영 DB 직접 조회는 자동 승인 경계 밖으로
  판단돼 시도하지 않았다.

- 작성자: Claude
- 수정일자: 2026-07-15 (16차, 중복 억제 시계열 누적 + 국면 정의 비교
  체계 구축)
- 수정내용: §8의 하루치 관찰을 시계열 누적 절차로 승격했다 — 신규
  오케스트레이터(`scripts/run_entry_score_penalty_ablation_cycle.py`)
  가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행에서 계산해 누적
  이력에 기록. 실행 결과: 이전 실측과 동일한 수치(A=85/B=60/C=75/
  A∩B∩C=60)로 교차 검증, 국면 일치 18건/불일치 69건(79%) — "시장
  비하락장인데 종목별 하락장" 60건. 재실행 중복 방지 확인. SPPV-3
  본작업용 비교 실험(현행 종목별 정의 vs 시장 공통 정렬)을 설계.

- 작성자: Claude
- 수정일자: 2026-07-15 (17차, §9.6 비교 실험 실측)
- 수정내용: 종목별 vs 시장 공통 regime 정의 비교 실험을 실제로
  실행했다 — 운영 `_assess_buy_eligibility()`를 그대로 호출해 변형
  A/B 각각의 통과군 forward return을 §16 이원 검증 도구로 비교. 변형
  B가 통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의 forward
  return은 더 높음(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%, 둘 다
  유의) — 과잉 억제가 아니라 정밀한 억제 가능성. A-B 차이 직접
  유의성 미검정, 통과군 내부 quintile spread 여전히 역전 — 판정
  Watch(조건부 유리, 확정 Go 아님). 실행 로그로 KIS 호출 0건 확인
  (가정 아닌 실측).

- 작성자: Claude
- 수정일자: 2026-07-15 (18차, A/B 판정 불일치 표본 direct 비교 + 1차
  창 재확인)
- 수정내용: 같은 종목-거래일 표본을 A_only/B_only/both/neither 4개
  집합으로 분해했다 — B_only가 3년·1차 창 모두 0건임을 확인, 시장
  공통 정의는 종목별 정의의 진부분집합일 뿐임을 구조적으로 확인.
  A_only의 forward return은 방향상 음수(T+5 -0.17%, T+20 -0.70%)
  이나 유의하지 않음(|t_NW|<1). 최근 12개월은 A-B 차이 자체가 없음.
  판정 Watch 유지(No-Go에 근접), 확정 전환 기각. 실행 로그로 KIS
  호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-15 (19차, alpha layer vs regime_conditional_signal
  직접 비교)
- 수정내용: 무게중심을 국면 정의 통일(차단)에서 alpha layer 교체
  (선별)로 이동했다 — 현행 alpha layer(순위상 0.45·overall+0.20·
  fast+0.15·slow와 동일함을 코드로 확인)와 regime_conditional_signal
  을 같은 3년 표본에서 직접 비교. 2차(3년) 창에서 regime_conditional_
  signal이 T+5/T+20 둘 다 유의(t_NW 2.52/2.33), 현행 alpha layer는
  어디서도 비유의(1.02~1.39) — spread·t값·양수 비율 4개 관측치 전부
  일관되게 우세. 1차 창은 미달이나 §21 구조적 이유(하락장 부재)
  때문. 판정 Conditional Go(2차 검증 통과, 1차 게이트 전환 대기) —
  Watch로 낮추지 않되 억지로 완전한 Go도 선언하지 않음. 실행 로그로
  KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-15 (20차, 새 alpha 상위군과 기존 차단 축 결합
  효과 검증 — 가장 빈번한 차단 사유 재발견; 당시 해석은
  이후 §2.24/§14 ablation으로 보정됨)
- 수정내용: regime_conditional_signal을 새 alpha로 넣었을 때 기존
  차단 로직이 그 효과를 상쇄하는지 검증했다 — 상위 20% 표본의
  68.3%(3년)/61.1%(최근 12개월)가 차단되나 차단된 표본도 forward
  return이 강하게 유의하게 양(+)(생존군과 큰 차이 없음). 실패 사유를
  집계한 결과 §8/§9/§11이 조사해온 regime 관련 축이 아니라 순수
  유동성 게이트 eligibility_low_relative_activity(거래량/거래대금
  급증 비율<1.10 차단)가 차단의 압도적 대부분(79.7%/99.6%)을 차지함을
  새로 발견 — regime 삼중 중복은 오히려 부차적(20.3%/0.4%). 판정:
  alpha 자체는 Conditional Go 유지, 결합 시나리오는 Watch(활동성
  필터 ablation 검증 필요). SPPV-3 최우선 조사 대상을 "국면 정의
  통일/regime penalty"에서 "활동성 필터 재검토"로 재조정. 두 스크립트
  실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (21차, 활동성 필터 정밀 ablation)
- 수정내용: eligibility_low_relative_activity가 실제로 과잉 억제인지
  threshold 현행(1.10)/완화(1.00)/완전 제거 3개 시나리오로 정밀
  판정했다. 완전 제거는 생존군 forward return이 무차단 상위군 전체
  수준으로 회귀하고 현행 유지보다도 낮아(2차 T+20 제거 +3.882% <
  현행 +4.381%) No-Go로 확정. 완화(1.00)는 생존 종목 수(2차
  31.7%→37.7%, 1차 38.9%→46.4%)와 T+5/T+20 평균 수익률·Newey-West
  t값·양수 비율이 1차·2차 창 모두 동시에 소폭 개선되는 방향은
  일관됐으나 개선폭이 작고 threshold 1개만 검증돼 Watch(추가 검증
  필요)로 기록 — Conditional Go로 단정하지 않음. "차단 비중이
  크다"≠"과잉 억제", "표본 증가로 t값이 커진다"≠"품질 개선"임을
  실측으로 반증(완전 제거가 그 역설 사례). 결론: 활동성 필터가
  BUY 0건의 "주범"인지 "과잉 억제"인지는 이번 실측만으로 확정할 수
  없다 — 재검토 필요 후보로 남김(2026-07-16 2차 검토, Codex 지적
  반영해 해석 보정). 결합 시나리오 판정은 Watch로 유지. 실행 로그로
  KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (22차, §13/§14 문서 내부 해석 일관성 정리)
- 수정내용: 새 실측 없이 SPPV-2.23 항목의 "진짜 병목 재발견" 등
  단정 표현을 "가장 빈번한 차단 사유 재발견(당시 해석은 이후
  §2.24/§14 ablation으로 보정됨)"으로 정정했다.
  `regime_conditional_entry_signal_v1.md` §13.4~§13.6도 함께
  "당시 해석(§14 보정 전)"으로 위치를 낮췄다(내용은 보존, 삭제
  없음) — 5개 정본 문서 전체의 일관성을 맞췄다.

- 작성자: Claude
- 수정일자: 2026-07-16 (23차, 활동성 필터 threshold sweep + 기간
  분할 재현성 검증)
- 수정내용: 완화안(1.10→1.00)을 Conditional Go로 올릴 수 있는지
  threshold 1.10/1.05/1.00/0.95/0.90 확장 스윕 + 3년 표본 전반부/
  후반부 분할로 검증했다(SPPV-2.25). 2차(3년) 전체·1차(최근
  12개월)·후반부에서는 완화할수록 개선되는 것처럼 보였으나 전반부
  (2023-10~2025-02)에서는 정반대로 완화할수록 악화됐다(T+5 기준
  1.10 +0.7394% → 0.90 +0.5728%). "완화=개선"은 후반부(=최근
  12개월과 거의 동일 시기) 효과가 pooled 평균을 끌어올린 것일 뿐
  3년 전체를 대표하는 재현성 있는 규칙성이 아니었다. 결론: 완화안을
  Conditional Go로 올릴 근거는 얻지 못했고 오히려 신중론 근거가
  추가됨 — Watch 유지(완전 제거는 여전히 No-Go). 실행 로그로 KIS
  호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (24차, 활동성 필터 완화 효과 전반부/후반부
  반전 원인 분해)
- 수정내용: SPPV-2.25가 발견한 반전의 원인을 규명했다(SPPV-2.26).
  전반부는 range_bound 45.4%+bearish_trend 28.5% 혼합/약세 편중,
  후반부는 bullish_trend 82.9% 극편중 — 상위 20% 무차단 기본
  수익률이 후반부가 전반부의 약 3.3~3.4배, 거래대금 중앙값도 약
  1.9배 확대됐다. 결정적으로, threshold 1.10→1.00 완화 시 새로
  통과하는 표본의 품질이 전반부에서는 기존 통과군보다 낮고 후반부
  에서는 오히려 높음을 확인 — 완화 효과의 반전은 필터 로직 결함이
  아니라 국면·유동성 구조 차이가 만든 결과로 판단. 정적 완화안은
  여전히 Watch, 완전 제거는 여전히 No-Go. 향후 방향은 "완화"가
  아니라 "국면 조건부 threshold"일 가능성(설계 제안, 이번 턴은
  원인 규명까지만). 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (25차, alpha layer 교체 BUY funnel 검증)
- 수정내용: 무게중심을 활동성 필터에서 alpha 교체(SPPV-2.22)로
  되돌려, 현행 alpha와 regime_conditional_signal을 candidate→
  eligible→would_buy(실제 운영 top-K=3 재사용)→blocked 4단계
  funnel로 비교했다(SPPV-2.27). would_buy 단계 forward return이
  2차(3년)·1차(최근 12개월)·전반부·후반부 4개 창, T+5/T+20 전부
  (8/8)에서 새 alpha가 현행보다 높았다 — 활동성 필터 완화와 달리
  방향이 한 번도 반전되지 않았다(전반부만 비유의). eligible 비율은
  낮아져 would_buy 표본이 약 20% 줄었지만 표본당 수익률 개선폭이
  더 커 누적 기대 성과는 여전히 개선. 결론: Conditional Go가
  funnel 레벨까지 보강됐으나, 전반부 비유의·국면 편향 가능성·거래
  빈도 감소로 확정 Go는 아니다. 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (26차, alpha layer 교체 virtual BUY funnel
  확장 검증)
- 수정내용: would_buy를 실제 운영 판단 경로에 한 단계 더 가깝게
  확장했다(SPPV-2.28). assess_deterministic_triggers()가 실제로
  쓰는 BUY_CANDIDATE 조건(eligible AND entry_score>=0.65 AND
  allocation_budget_ok, 실제 운영 상수 재사용)을 재현한 selected
  단계를 추가해 candidate→eligible→selected→would_buy 5단계로
  확장, MFE/MAE도 계측했다. would_buy 우위는 4개 창 전부(8/8)에서
  유지됐으나, 신규 alpha는 selected 비율이 4개 창 전부에서 정확히
  100.0%(0.65 문턱이 사실상 무력화)임을 새로 발견 — 현행은 66~72%
  만 통과. MFE/MAE는 신규 alpha가 상방·하방 모두 크지만 MFE/|MAE|
  비율은 4개 창 전부에서 신규가 더 높음. 결론: Conditional Go
  재확인, 다만 "0.65 문턱 무력화"·"MAE 확대" 계측 caveat 추가로
  확정 Go는 아니다. broker submit 미호출. 실행 로그로 KIS 호출
  0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (27차, 새 alpha entry_score 스케일 재보정
  shadow 검증)
- 수정내용: "0.65 문턱 무력화" caveat의 원인(regime_conditional_
  signal이 퍼센트 단위 비율이라 normalize 함수에서 상위 20%가
  거의 항상 saturate)을 분해했다(SPPV-2.29). 재보정 3안(R1 가중치
  축소 0.80→0.50/R2 z-score/R3 percentile)과 기준선(R0)을 비교한
  결과, R1은 forward return이 3/4 창에서 악화돼 기각, R2는
  selected_rate가 R0와 큰 차이 없어 문제 미해결, R3(percentile)는
  selected_rate를 93.7~96.5%로 낮추면서 forward return이 4개 창·
  2개 horizon 전부(8/8)에서 개선되고 MAE도 개선됨을 확인했다.
  결론: R1/R2 기각, R3를 유력한 재보정 후보로 채택 검토(단일 실험
  이라 확정 Go 아님). 운영 코드 변경 없음, broker submit 미호출.
  실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (28차, R3 재현성 검증 + percentile 계산
  민감도 점검)
- 수정내용: R3를 분기 4분할로 재검증했다(SPPV-2.30). R3의 "4개 창
  전부 우위" 결론이 분기 단위로는 무너짐 — 분기1·분기3에서 R3가
  R0보다 오히려 낮음을 발견. 이전 4개 창(2차/1차/전후반)은 서로
  겹치는 넓은 구간이라 해상도가 낮았던 것으로 판단. percentile을
  candidate 내부에서 재계산한 R3b는 8개 창 전부 우위를 보였으나
  selected_rate가 30%대까지 낮아져 R1과 유사한 극단적 선별 우려로
  별도 검증 필요. 결론: R3를 다시 Watch로 하향(유력 후보 격상
  철회), R3b는 신규 관찰 대상으로만 등록. 운영 코드 변경 없음,
  broker submit 미호출. 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (29차, R3b 엄격 재검증 + R3 실패 구간 원인
  분해)
- 수정내용: R3b를 R1이 실패한 것과 동일한 엄격 기준(8개 창 중
  하나라도 악화되면 기각)으로 재검증하고, would_buy 종목 겹침률
  (overlap)로 표본 급감 착시와 진짜 선별 개선을 분리했다(SPPV-
  2.31). R3b는 8개 창 전부(분기1·분기3 포함)에서 R0보다 높았다.
  핵심 발견: R3는 R0와 77~85%가 같은 종목을 고르는 미세 재조정인
  반면 R3b는 47~61%만 겹쳐 질적으로 다른 선별이다 — 표본 축소
  착시가 아닌 실제 재선별 효과. R3 실패 원인 분해에서는 saturation
  비율이 4개 분기 전부 100%로 동일해 원인이 아니었고, 국면 분포도
  설명력 없음(분기3 강세 67.5%인데 실패, 분기2 약세+횡보 90.8%인데
  성공). 결론: R3 실패는 국면 때문이 아니라 R0와의 높은 겹침에서
  오는 작은 효과 크기 때문. 판정: R3b를 유력한 재보정 후보로 신규
  격상(확정 Go 아님), R3는 Watch 유지. 문서 정정: "분기 25%" 오기를
  "2/4=50%"로 5개 문서 전체 정정(결론 불변). 운영 코드 변경 없음,
  broker submit 미호출. 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (30차, R3b 대응표본 검증 — overlap 근거 보정)
- 수정내용: 직전 턴의 overlap(간접) 근거를 대응표본(직접) 검증으로
  재확인했다(SPPV-2.32). 같은 거래일 대체 종목쌍의 forward return
  차이를 계산한 결과, R0 vs R3b 대체쌍 T+20 평균이 8개 창 중
  6개에서 양(+)이었으나 분기3에서는 음수(-0.47%p, 대체 우위일
  비율 45.8%)로 뒤집혔다. t_NW가 통상 유의 수준(1.96) 이상인 창은
  2개뿐. R0 vs R3 대체쌍은 더 약해 분기1·분기3에서 사실상 음수/0.
  핵심 정정: overlap만으로 "실제 재선별 효과"를 결론지은 것은
  근거 부족이었다 — aggregate 우위(8/8)는 부정되지 않으나 그
  우위가 대체 종목의 우수성에서 왔다는 인과관계는 확인되지 않았다.
  판정: R3b의 "유력 후보 격상"을 다시 Watch로 하향, R3는 Watch
  유지(근거 강화). 운영 코드 변경 없음, broker submit 미호출.
  실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (31차, R3b aggregate 우위 vs 대응표본 음수
  구간 3분해)
- 수정내용: 문서 정정 — "t_NW≥1.96 창 2개" 서술이 실제로는 3개
  (2차·전반부·분기1)였음을 확인(분기1 누락). common_kept/dropped_
  only/added_only 항등식 분해로 aggregate 우위 원인을 규명했다
  (SPPV-2.33). added_only 평균이 8개 창 전부에서 다른 그룹보다
  높아 R3b의 신규 선택 자체는 실제로 우수했으나, R0 자신의 저품질
  dropped_only 비중이 커서 구성 효과도 상당히 기여함을 확인. 분기3
  에서 pooled 교체효과(+2.594%p)와 paired 교체효과(-0.4666%p)의
  부호가 정반대인 것을 발견 — 가중 방식 차이 때문이며 R3b 효과가
  소수 스왑 밀집일에 집중된 비대칭 구조임을 시사. 판정: 재격상
  없이 R3b/R3 모두 Watch 유지(이번 턴은 원인 규명이 목적). 운영
  코드 변경 없음, broker submit 미호출. 실행 로그로 KIS 호출 0건
  확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (32차, R3b pooled 우위 날짜 집중도 검증 +
  교체효과/구성효과 정량 분리)
- 수정내용: 스왑 개수 상위 10% 거래일 제거 후 aggregate 우위
  잔존비율을 계산하고, `aggregate_diff=replacement_effect+
  composition_effect` 정확한 항등식으로 두 효과를 분리했다(SPPV-
  2.34). 스왑 상위 10% 제거 후에도 8개 창 중 7개에서 우위가
  80~120% 수준으로 유지돼 "소수 거래일 집중" 가설 기각, 분기3만
  잔존비율 30~65%로 예외. 핵심 정정: 직전 턴의 "구성효과 기여"
  서술은 방향이 틀렸다 — composition_effect는 8개 창 중 6개에서
  오히려 음(-)으로 우위를 상쇄했고, aggregate 우위는 순수
  replacement_effect에서 왔다. 판정: 재격상보다 원인 확정 우선,
  R3b/R3 모두 Watch 유지(분기3 반례는 실제 집중형으로 확인). 운영
  코드 변경 없음, broker submit 미호출. 실행 로그로 KIS 호출 0건
  확인.

- 작성자: Claude
- 수정일자: 2026-07-16 (33차, 분기3 스왑 집중일 세부 진단 + SPPV-
  2.34 해석 문구 정밀 보정)
- 수정내용: 직전 턴(32차/SPPV-2.34)의 두 서술을 실제 수치 기준으로
  정밀 보정했다(SPPV-2.35). **보정 1: "구성효과 8개 창 중 6개
  음(-)"은 T+5/T+20을 뒤섞은 표현 — 정확히는 T+20 기준 8/8, T+5
  기준 5/8에서 음(-)(전반부·분기1·분기2는 T+5에서 양(+)).** **보정
  2: "분기3만 실제 날짜 집중형"이라는 서술은 방향이 과했다 —
  분기3 스왑 상위 15개 거래일 개별 진단 결과, 대형 스왑일(상위
  10%, 약 8일)의 T+20 교체효과 평균은 +7.04%p로 뚜렷한 양(+)이고,
  분기3 전체 paired 평균(-0.4666%p)의 진짜 원인은 나머지 약 75개
  소규모 스왑일의 완만한 음(-) 누적(역산 약 -1.267%p)이다 — "대형
  스왑일이 나쁘다"가 아니라 "대형 스왑일은 유일한 양(+)의 원천이고
  그것을 빼면 넓게 퍼진 완만한 음(-)만 남는다"는 구조.** 이벤트/
  실적 연관은 2025-02-12~13 연속 악재일에 한해 정황(가설) 수준.
  판정: 재격상/재하향 없이 R3b/R3 모두 Watch 유지(원인 확정·표현
  정밀화 목적). 운영 코드 변경 없음, broker submit 미호출. 실행
  로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-17 (34차, 분기3 반례의 대형/소규모 스왑 구조
  정밀 확정 + "전적으로 의존" 문구 보수화)
- 수정내용: 33차(SPPV-2.35)의 "대형 스왑일은 유일한 양(+)의 원천"
  이라는 서술을 분기3 83개 스왑일 전체를 5분위(quintile)로
  구간화해 정량 검증했다(SPPV-2.36). **결과: "대형=양(+)/소규모=
  음(-)"은 양극단(Q1 최대·Q5 최소)에서만 성립하고 중간(Q2~Q4)은
  혼재한다(Q4는 소규모인데도 T+20 +4.38%p 양(+)).** aggregate(순
  기여) 관점에서는 대형 스왑일이 우위의 상당 부분(T+5 약 70%,
  T+20 약 35%)을 담당하지만, **총합(gross) 관점에서는 전체 양(+)
  합계의 15% 수준에 불과** — "전적으로 의존"·"유일한 원천"은
  과장이었다. 02-12~13 동시 제거는 음(-) paired 평균의 약 39%만
  설명(부분적). 판정: 재격상/재하향 없이 R3b/R3 모두 Watch 유지
  (구조 확정·문구 보수화 목적). 운영 코드 변경 없음, broker submit
  미호출. 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-17 (35차, R3b의 SPPV-3 진입 후보 여부 판단 —
  실제 BUY funnel 최소 검증)
- 수정내용: R3b 미세 해부를 멈추고 SPPV-3 착수 후보 여부를 판단
  (SPPV-2.37). 기존 8개 창 BUY funnel 계측(재사용) 결과 T+20 평균
  우위 8/8 일관, t_NW 6/8 유의. **신규: would_buy 모집단의 거래일
  편중도(top-decile-day leave-out) 계측 결과, 거래일 집중 의존은
  R3b만의 문제가 아니라 R0(기준선) 자체가 8개 창 중 3개에서 상위
  10%일 제거 시 평균이 마이너스로 뒤집히는 alpha 신호 계열 전반의
  특성이며, R3b는 8/8 창에서 R0보다 그 의존도가 더 낮다(더
  견고).** 판정: **R3b를 Watch에서 Conditional Go로 상향**
  (조건부: 분기1·분기2 marginal t_NW 재확인, selected_rate 급감의
  총 기대수익 영향 정량화, §3 전제조건 충족, point-in-time
  파이프라인 반영 shadow 실행이 확정 Go 전 필요). 운영 코드 변경
  없음, broker submit 미호출. 실행 로그로 KIS 호출 0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-17 (36차, SPPV-2.37 수치 정정 + Conditional Go
  재평가)
- 수정내용: 35차(SPPV-2.37)의 세 가지 수치 서술을 재검산해 정정
  했다(SPPV-2.38). **정정 1: R0의 top-decile-day 음(-) 반전 창
  수는 "3개"가 아니라 "4개"(2차 포함).** **정정 2: 양수 비율
  열세 창 수는 "3/8"이 아니라 T+20 기준 "1/8"(분기2만), T+5 기준
  "0/8".** **정정 3: "selected_rate 급감(약 30~40%)"은 R3b 자신의
  비율 수준(29.9~39.2%)이며 R0(100%) 대비 약 61~70%p 감소로
  명확화.** 세 정정 모두 R3b의 방향성 우위를 약화시키지 않아(정정
  1·2는 오히려 R3b에 유리한 방향) **R3b는 Conditional Go를
  유지한다.** 새 실험 없이 기존 JSON 재검산만 수행(신규 KIS 호출
  해당 없음). 운영 코드 변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (37차, selected_rate 감소가 총 기대수익에
  미치는 영향 정량화)
- 수정내용: R3b Conditional Go 확정 전 잔여 조건 중 조건 (2)를
  정량화했다(SPPV-2.39). 신규 실측 없이 기존 산출물 2개만 재사용해
  총 기대수익 proxy(=would_buy_n × mean_forward_return_pct)를 8개
  창×2horizon(16개 조합) 전부 계측한 결과, **14/16 조합에서 R3b의
  총proxy가 R0보다 높다**(92.0%~322.6%). 나머지 2개(1차 T+5, 분기3
  T+20)도 거의 동률. 판정: "거래 빈도 감소가 총 기대수익을
  훼손하는가"에 명확히 "아니다" — **확정 Go 전 잔여 조건 4가지 중
  1개(조건 2)가 해소돼 Conditional Go 근거가 보강됐다.** 나머지
  3개 조건(분기1·분기2 marginal t_NW, §3 전제조건, point-in-time
  파이프라인 반영)은 그대로 남아 확정 Go는 아니다. 운영 코드 변경
  없음, broker submit 미호출. 신규 KIS 호출 없음(신규 실행 없음).

- 작성자: Claude
- 수정일자: 2026-07-17 (38차, R3b 총 기대수익 proxy의 유휴 자본
  반영 보강 검증)
- 수정내용: 37차(SPPV-2.39)의 "조건 (2) 해소"를 유휴 자본 기회
  비용까지 반영해 보강 검증했다(SPPV-2.40). 신규 계측은 창별 전체
  거래일 수 하나뿐(캐시 봉 데이터만 사용, 신규 KIS 호출 없음).
  **엄격 기준(R0가 전체 슬롯을 자기 평균으로 100% 채웠다는 이론적
  최대와 비교) 적용 결과, T+20은 8개 창 중 7개에서 여전히 R3b
  우위(견고)이나, T+5는 8개 창 중 6개에서 우위가 사라지거나 이미
  열세(취약).** 판정: **"조건 (2) 해소"는 과장 — 정확히는 "T+20
  기준 완화, T+5 기준 여전히 미해결"** 수준으로 재조정. R3b는
  Conditional Go를 유지한다(확정 Go 아님). 운영 코드 변경 없음,
  broker submit 미호출. 신규 KIS 호출 없음(로그 확인).

- 작성자: Claude
- 수정일자: 2026-07-17 (39차, R3b Conditional Go의 운영 horizon
  적합성 판단)
- 수정내용: 38차(SPPV-2.40)가 남긴 "T+20 중심인가, T+5 취약성이
  실운영과 충돌하는가"를 코드·문서 조사로 판단했다(SPPV-2.41).
  **결과: `deterministic_trigger_engine.py`의 SELL/청산은 100%
  `exit_score`(신호/점수) 기반이며 경과일수를 전혀 참조하지 않고,
  `max_holding_days=20`은 AI Risk agent의 LLM 출력 힌트 기본값일
  뿐 실제로 20일 뒤 매도를 강제하는 코드가 없다.** 기존 §16 Go/
  No-Go 표준이 T+5·T+20을 이미 동시에 요구해온 것도 확인. 판정:
  **"T+20 중심이라 T+5 약점을 무시해도 된다"는 주장은 코드로
  뒷받침되지 않는다.** R3b는 Conditional Go를 유지하되(즉시 Watch
  재하향 근거는 부족), T+5 horizon 강건성 확보(또는 실거래 누적
  후 청산 시점 분포 실측)를 확정 Go의 필수조건으로 격상한다. 신규
  KIS 호출 없음(read-only 코드/문서 조사만 수행). 운영 코드 변경
  없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (40차, R3b를 point-in-time entry_score
  파이프라인에 반영한 shadow 검증)
- 수정내용: 39차(SPPV-2.41)가 남긴 "point-in-time entry_score
  파이프라인 반영 shadow 실행"을 수행했다(SPPV-2.42). 기존 검증이
  이미 실제 운영 함수(`build_signal_snapshot`/`_assess_buy_
  eligibility`/`_build_entry_score`)를 호출해왔음을 확인했으나,
  실제 `strategy_selection` 조정항(+0.05 보너스)이 그동안 `None`
  으로 누락돼 있었다 — 이를 실제 `select_strategy()` 호출로 채워
  A/B 양쪽에 공정하게 반영했다. **결과: 8개 창×2horizon 16개
  조합 전부에서 R3b>R0 방향 유지**(붕괴 없음), 다만 **분기1 T+20의
  t_NW가 1.31→0.96으로 더 약화**돼 기존 marginal 우려가 심화됐다.
  판정: **R3b는 Conditional Go를 유지한다.** "point-in-time
  파이프라인 반영" 조건은 부분 해소(핵심 우려는 해소, `portfolio_
  allocation` gap은 미해결로 잔존). 신규 KIS 호출 0건. 운영 코드
  변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (41차, 분기1 t_NW 약화의 원인 정밀 진단 —
  방향성 붕괴 vs 변동성/이상치 문제)
- 수정내용: 40차(SPPV-2.42)가 남긴 "분기1 t_NW 약화(0.96) 우선
  재확인"을 실행했다(SPPV-2.43). 분기1은 세 분기 중 가장 "혼합
  국면"(강세/횡보/약세 고른 분포 + event_driven_unstable 최다)
  구간임을 확인. **R3b>R0 방향은 그대로 유지되고(1.815% vs
  0.753%), 스왑일 46건 중 33건(71.7%)이 양(+)으로 세 분기 중 최다
  — 상위 스왑일 제거 시 오히려 개선(157.8%)돼 분기3과 정반대
  구조.** t_NW 약화의 실체는 상위 10개 스왑일 중 3건의 극단치
  (±16~44%p)가 표준오차를 키운 것으로 확인. 판정: **분기1 약화는
  방향성 붕괴가 아니라 소수 극단치로 인한 분산 문제로 좁혀진다 —
  R3b는 Conditional Go를 유지한다**(Watch 재하향 근거 없음). 신규
  KIS 호출 0건. 운영 코드 변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (42차, SPPV-3 진입 관문 3종 종합 판정 — §3
  게이트 재확인 + 분기1/T+5 리스크 종합)
- 수정내용: SPPV-3 진입 전 마지막 관문 3가지(§3 전제조건, 분기1
  약화, T+5 취약성)를 종합 판정했다(SPPV-2.44). 기존 검증(분기1=
  SPPV-2.43, T+5=SPPV-2.41)을 반복하지 않고, 유일한 신규 실측인
  §3 게이트(기존 SPPV-2.13 모니터링 스크립트 재실행)만 확인 —
  **결과 `NOT_TRIGGERED`(불변, 최근 12개월 bearish_trend 0/30일).**
  종합 판정: ①§3 전제조건 미충족, ②분기1 약화는 관리 가능한 잔여
  리스크(치명적 결함 아님), ③T+5 취약성은 미해결이나 치명적 근거
  없음. 판정: **R3b는 Conditional Go를 유지한다.** 다만 **SPPV-3
  (운영 코드 반영) 진입은 아직 이르다 — 주된 차단 요인은 R3b 성과와
  무관한 §3 게이트(하락장 미도래)**이며, 규칙 A(관찰 유예)에 따라
  인위적으로 앞당길 수 없다. 신규 KIS 호출 0건. 운영 코드 변경
  없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (43차, SPPV-2.44 산출물 파일명/실행 경로
  불일치 정정)
- 수정내용: 42차(SPPV-2.44)가 §3 게이트 재확인 산출물을 `..._2026-
  07-17.json`으로 표기한 것이 실제 스크립트 동작과 불일치해
  정정했다(SPPV-2.45). **확인된 사실: `monitor_regime_switch_v1_
  gate.py`는 실행 시점과 무관하게 항상 하드코딩된 `..._2026-07-
  14.json`에 저장한다** — 42차가 인용한 `..._2026-07-17.json`은
  컨테이너 산출을 호스트로 복사하며 수동 재명명한 사본이다. 내용은
  실제 이번 재실행 결과가 맞고(as_of 일치), 결론에 영향을 주는
  차이는 없다. **판정: 정정 후에도 SPPV-3 관련 결론은 전혀 바뀌지
  않는다 — R3b Conditional Go 유지, SPPV-3 진입은 §3 게이트
  미충족으로 아직 이르다는 판정을 그대로 유지한다.** 새 실측/새
  스크립트 없이 기존 코드·로그 재확인만 수행. 운영 코드 변경
  없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (44차, R3b 채택 시 risk_off_penalty 중복
  해소 ablation)
- 수정내용: §3 전제조건 ②(risk_off_penalty 중복 해소)를 R3b
  candidate 위에서 실측했다(SPPV-2.46). entry_score 축(-0.15)과
  eligibility 축(즉시 차단)이 서로 다른 함수의 별개 축임을 코드로
  확정하고, A(현행)/B(entry_score 축 무력화)/C(eligibility 축
  완화) 3개 시나리오를 실제 운영 함수 호출로 비교했다(운영 코드
  미수정, market_regime 입력만 국소 중립화). **결과: C는 A와
  완전 동일**(eligibility 축이 R3b candidate pool에서 비활성) —
  중복 우려는 애초에 발생하지 않는다. **B는 T+20 총 기대수익
  proxy가 2차 +20.9%/1차 +20.5% 개선되나 MAE도 소폭 악화(약
  0.5%p)** — 실제 트레이드오프. 판정: **eligibility 축은 비활성,
  entry_score 축은 "완화 검토 후보"에 가깝다는 실측 근거 확보 —
  R3b는 Conditional Go를 유지하고, §3 조건②는 "방향 확인, 사용자
  승인 대기"로 진전, SPPV-3 진입은 §21 게이트 미충족으로 여전히
  이르다(불변).** 신규 KIS 호출 0건. 운영 코드 변경 없음, broker
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-17 (45차, 승인 범위 확정 + risk_off_penalty
  (entry_score 축) 완화안 심층 해석)
- 수정내용: 사용자가 44차(SPPV-2.46)의 A/B/C 중 "B — entry_score
  risk_off_penalty만 완화"를 승인(eligibility 축 비승인)했다.
  기존 산출물을 신규 실행 없이 재사용해 T+5/T+20 양쪽·MAE
  트레이드오프를 심층 해석했다(SPPV-2.47). **결과: 총 기대수익
  proxy가 2개 창×2horizon 전부에서 개선(12.9~20.9%), t_NW도 함께
  개선, MAE는 소폭 악화(5.9~7.8% 상대)하나 개선폭보다 항상
  작다.** 판정: **R3b + entry_score risk_off_penalty 제거 조합은
  Conditional Go를 보강한다.** SPPV-3 진입 관점에서 남은 조건은
  사실상 §21 게이트 하나로 좁혀졌다(entry_score 코드 반영은 게이트
  충족 후 별도 절차). 신규 KIS 호출 없음(신규 실행 자체가
  없었음). 운영 코드 변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (46차, SPPV-2.47 "게이트 하나만 남았다"
  표현 정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리)
- 수정내용: 45차(SPPV-2.47)의 "SPPV-3 진입 관점에서 남은 조건은
  사실상 §21 게이트 하나로 좁혀졌다"는 서술이 §3 전제조건 범위로는
  정확하나 SPPV-3 진입 전체로는 과장이었음을 바로잡았다(SPPV-2.48).
  새 실측·새 설계 제안 없이 기존 문서(§2.41 T+5 구조적 리스크,
  §2.43 혼합 국면 재확인, §2.40 portfolio_allocation gap)만
  재해석했다. **재분류: ①주된 차단 요인(§21 게이트, 외생적)
  ②보조 잔여 조건(entry_score 코드 반영 절차, T+5 구조적 리스크,
  혼합 국면 재확인) ③실거래 누적 없이는 못 푸는 조건(portfolio_
  allocation gap, 실제 청산 시점 분포).** 판정: **R3b는 Conditional
  Go를 유지한다** — 방향 후퇴가 아니라 "남은 조건" 서술의 정밀도만
  회복하는 정정. 신규 KIS 호출 없음(신규 실측 없음). 운영 코드
  변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (47차, 혼합 국면(분기1 유형) 재확인 — 분기4
  대조 계측)
- 수정내용: 46차(SPPV-2.48)가 정리한 보조 잔여 조건 중 "혼합 국면
  재확인"만 지금 당장 전진 가능해 최우선으로 선택했다(SPPV-2.49).
  승인된 조합(R3b+entry_score risk_off_penalty 제거, B 시나리오)
  으로 분기1(재계측)과 분기4(신규 계측)의 국면 분포·funnel을
  비교했다. **결과: 분기4는 시장 공통 국면이 사실상 순수
  bullish(98.2%)로 분기1(혼합)과 정반대 — 분기4는 T+20 t_NW=
  3.00·양수율=60.3%로 강하고 일관되나 분기1은 t_NW=1.27(marginal)·
  양수율=46.2%로 대비된다.** 해석: "혼합 국면→약한 t_NW" 가설이
  분기1 1건의 우연이 아니라 대조쌍으로 확인됐다 — 조건 해소는
  아니나 "미확인 가설"에서 "확인된 패턴"으로 전진. 판정: **R3b는
  Conditional Go를 유지한다.** 신규 KIS 호출 0건. 운영 코드 변경
  없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (48차, "혼합 국면 약세" 가설 직접 분해 —
  거래일 단위 혼합도 3분위 버킷화)
- 수정내용: 47차(SPPV-2.49)의 분기1 vs 분기4 대조는 N=2 분기 대조에
  불과해 특정 분기 우연 가능성을 완전히 배제하지 못했다. 분기 경계와
  무관하게 각 거래일마다 최근 60거래일 창의 시장 공통 국면 혼합도
  (mixed_score=1-최빈 라벨 비중)를 계산해 3년 전체 634거래일을
  혼합도 3분위(저혼합 217일/중혼합 215일/고혼합 202일)로 버킷화하고
  승인된 B 시나리오로 재측정했다(SPPV-2.50). **결과: 저혼합→중혼합→
  고혼합 순으로 T+20 t_NW(3.64→2.51→0.37)·양수율(63.3%→56.8%→
  38.7%)이 단조 감소 — 고혼합 구간은 통계적으로 0과 구분 불가능
  하다.** 해석: 217/215/202일이 3년 전체에 고르게 분포해 특정 분기
  편중이 아니며, 연속 변수와의 용량-반응 관계이므로 "혼합 국면
  약세"는 지지 증거 추가에서 **구조적 패턴으로 격상**됐다. 다만
  저혼합·중혼합 2/3 구간은 여전히 강하고 고혼합 구간도 점추정치는
  양(+)이라 R3b 방향 반전도, SPPV-3 추가 지연 사유도 아니다(주된
  차단 요인은 여전히 §21 게이트 하나뿐). 판정: **R3b는 Conditional
  Go를 유지한다.** 신규 KIS 호출 0건. 운영 코드 변경 없음, broker
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (49차, SPPV-2.50 결론 문구 정밀화 — 과장
  없이 고정)
- 수정내용: 신규 실행 없이 48차(SPPV-2.50)가 사용한 두 문구를
  기존 산출물만으로 재점검했다(SPPV-2.51). **정정 1**: "구조적
  패턴으로 격상"은 과장 — 이 3분위 재확인이 R3b/entry_score 조합을
  이미 확정하는 데 쓰인 것과 동일한 3년 in-sample 캐시에서 수행됐고,
  mixed_score가 60거래일 trailing window라 인접 거래일 버킷이
  자기상관돼 634거래일이 634개의 독립 관측이 아니다. 단조 감소·
  217/215/202일의 균등 분포는 그대로 사실이라 "지지 증거 추가"
  단계는 명백히 넘어섰으나, "out-of-sample로 확정된 구조적 패턴"
  이라 부르는 것은 과장 — 정확한 표현은 **"강한 구조적 정합
  증거로 격상"**이다. **정정 2**: "주된 차단 요인은 §21 게이트
  하나뿐"은 "SPPV-3 착수 검토를 시작할 수 있는 유일한 외생적
  조건"이라는 뜻이지 "진입 전체에 남은 유일한 조건"이 아니다 —
  46차(§38)의 ①주된 차단 요인(§21 게이트) ②보조 잔여 조건
  (entry_score 코드 반영 절차·T+5 구조적 리스크·혼합도 모니터링)
  ③실거래 누적 필요 조건 3단 분류는 이번 턴에도 그대로 유효하다.
  판정: **두 정정 모두 R3b 방향성·Conditional Go를 바꾸지
  않는다** — 서술 정밀도만 회복. 신규 실행 없음, 신규 KIS 호출
  0건, 운영 코드 변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (50차, T+5 horizon 구조적 리스크 추가 정량화 —
  실제 exit_score 기반 signal-driven 청산 타이밍 시뮬레이션)
- 수정내용: 46차(§38)가 정리한 보조 잔여 조건 3개 중 지금 당장 신규
  설계 없이 기존 3년 캐시만으로 실측 가능한 "T+5 구조적 리스크"를
  전진시켰다(SPPV-2.52). 실제 운영 함수 `_build_exit_score`(순수
  함수, DB/실시간 상태 불필요)를 R3b+entry_score risk_off_penalty
  제거(B 시나리오) would_buy candidate 1151건에 point-in-time으로
  재호출해 매도 신호(`sell_candidate_threshold=0.75`)를 처음 넘는
  날을 20거래일 관찰 창으로 시뮬레이션했다. **결과: 91.1%(1049건)
  가 20거래일 안에 매도 신호를 넘지 않고 censored, 평균 보유일수=
  19.35일. signal-driven 청산 수익률(평균 6.14%, t=4.73)은 T+5
  (2.02%, t=4.18)보다 T+20(6.49%, t=3.87)에 훨씬 가깝다.** 해석:
  실제 청산 로직 기준으로는 T+5가 아니라 T+20 근방에서 청산되므로
  "T+5 평균이 약하다"는 우려가 실제 운영 리스크로 그대로 전이되지
  않는다 — "T+5 구조적 리스크"는 부분적으로 완화됐다. 다만 20일
  초과 구간의 청산 분포·경로 리스크(MAE)는 미검증이라 "완전 해소"
  라 부르는 것은 과장이다. 판정: **R3b는 Conditional Go를
  유지한다.** 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (51차, T+5 horizon 구조적 리스크 — 20거래일
  초과 구간·경로 리스크(MAE) 확장 검증)
- 수정내용: 50차(§41)가 20일 관찰 창으로 남긴 두 미확인 영역(20일
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
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (52차, SPPV-2.53 결론 문구 정밀화 — 20일판·
  60일판 표본 동일성 검증 + "거의 해소" 표현 재점검)
- 수정내용: 신규 실행 없이 51차(§42)의 "censored 91.1%→51.3%"
  비교와 "T+5 구조적 리스크 거의 해소" 판정을 두 스크립트 코드
  대조로 재점검했다(SPPV-2.54). **코드 기준 판정**: 20일판·60일판
  모두 후보 스캔 범위가 `last_t = len(bars)-1-
  MAX_EXIT_OBSERVATION_DAYS`로 제한되는데, 60일판은 3년 캐시 끝
  약 40거래일이 스캔에서 제외돼 20일판(1151건)보다 좁은 표본
  (1048건)을 만든다 — candidate 선정 로직 자체는 관찰 창과 무관한
  당일 backward-looking 계산이므로 60일판은 20일판의 약 91%
  부분집합으로 추정된다. **즉 두 결과는 동일 코호트의 순수 전/후
  비교가 아니라 겹치지만 완전히 같지는 않은 두 표본의 비교**다.
  확실히 말할 수 있는 것: 각 판의 표본 내부 측정치는 유효하고
  표본 차이(~9%)가 효과 크기를 설명하기엔 작아 방향성은 신뢰
  가능하다. 과장인 것: 91.1%→51.3%를 엄밀한 페어드 비교치로
  인용하는 것, "거의 해소"라는 표현 — 60일 관찰 후에도 과반
  (51.3%)이 여전히 censored이기 때문이다. 판정: **정확한 표현은
  "부분 완화"(§41)에서 "추가 완화"(§42/§43)로 하향 정정** — R3b는
  Conditional Go를 유지한다(방향성 반전 아님). 신규 실행 없음,
  신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (53차, 손절(stop-loss) 정책 도입이 총
  기대수익에 미치는 영향 ablation)
- 수정내용: 51차(§42)가 §38에 신규 추가한 "경로 리스크(MAE)·손절
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
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (54차, entry_score 코드 반영 절차 구체화 —
  shadow 재구현 정합성 검증)
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
  submit 미호출.

- 작성자: Claude
- 수정일자: 2026-07-18 (55차, SPPV-2.56 결론 문구 정밀화 — "직접
  호출" 서술 범위·표본 서술 정정)
- 수정내용: 신규 실행 없이 54차(§45)의 두 표현을 기존 코드 재검토
  로 정정했다(SPPV-2.57). **정정 1**: "실제 함수를 한 번도 직접
  호출한 적이 없었다"는 과장 — `_build_entry_score`는 시나리오
  A(현행 regime)로는 `validate_alpha_layer_buy_funnel_comparison.py`
  와 `validate_r3b_point_in_time_pipeline_shadow.py`에서 이미
  직접 호출돼왔다. 정확한 표현: "B 시나리오(`risk_tone="neutral"`
  치환) 입력으로는 §45 이전까지 직접 호출한 적이 없었다". **정정
  2**: 이번 검증은 non-alpha 조정 항(core/None/neutral 조건)만
  증명했을 뿐 — R3b alpha 교체 전체 경로의 실제 코드 반영 후
  재현성과 held_position/실제 portfolio_allocation 케이스는
  미검증이다. **정정 3**: "candidate 전량"은 부정확 — quintile
  선별·eligibility 필터링 없이 전체 거래일 스냅샷(58,493건)을
  순회했으므로 정확한 표현은 "전체 시점 스냅샷(모집단 전체)".
  판정: **세 정정 모두 R3b 방향성·Conditional Go를 바꾸지
  않는다** — §45의 핵심 결론은 그대로 유효하며 필요 이상으로
  보수적으로 낮추지 않는다. 신규 실행 없음, 신규 KIS 호출 0건,
  운영 코드 변경 없음, broker submit 미호출.

- 작성자: Codex
- 수정일자: 2026-07-18 (56차, §21 gate 환경별 적용 범위 정밀화 —
  production 잠금과 paper/shadow 관측 분리)
- 수정내용: 백로그 상의 `§21 gate` 해석을 **production 자본 보호용
  잠금선**과 **paper/shadow 실측 관측선**으로 분리해 정정했다
  (SPPV-2.58). 기존 표현은 `§21 gate`를 SPPV-3의 주된 차단 요인으로
  유지했지만, 현재 단계가 모의 투자/Shadow 관측이라는 점까지 함께
  읽지 않으면 paper 단계의 데이터 수집 자체를 멈춰야 하는 것으로
  오해될 수 있었다. canonical 해석은 다음과 같다. **production**:
  gate 엄격 유지. **paper/shadow**: 환경 인지형 우회(config 스위치)
  구현 시 gate는 실운영 승격 잠금선으로만 적용하며, 실측 데이터 수집과
  shadow 관측은 별도 허용 가능. 이번 턴은 문서 정정만 수행했고 신규
  실행·코드 변경·판정 변경은 없다.

- 작성자: Codex
- 수정일자: 2026-07-18 (57차, `§21 gate` config 기반 gate 제어 —
  mode-agnostic 신규 모듈 구현)
- 수정내용: **[정정] 바로 위 56차 항목의 "environment 인지형 우회
  (paper/production 분기)" 프레이밍은 부정확하다 — 실제 구현은
  environment 분기가 아니라 config 스위치 하나만으로 판정하는
  mode-agnostic 방식이다.** 코드베이스 전수 조사 결과 `§21 게이트`
  (regime_switch_v1)는 실제 운영 코드(`assess_deterministic_
  triggers`) 어디에도 연결되지 않은 순수 모니터링 산출물이었다 —
  R3b shadow/paper 관측은 이 게이트에 의해 코드 레벨에서 전혀 막힌
  적이 없었다. `deterministic_trigger_engine.py`는 "절대 수정하지
  않는다"는 원칙에 따라 이번에도 수정하지 않고 신규 격리 모듈로만
  구현했다: `AppSettings.regime_switch_v1_gate_override_enabled`
  (env: `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 False) +
  `services/regime_switch_gate.py`(신규)의 `assess_regime_switch_
  v1_gate()` 순수 함수 — paper/real/production 값은 전혀 참조하지
  않는다. override off면 기존 §21 해석과 동일(TRIGGERED일 때만
  열림), override on이면 국면 상태와 무관하게 항상 열림, reason_
  code로 항상 추적 가능. `scripts/validate_regime_switch_gate_
  config_override.py`로 검증: 운영 코드 미수정 확인(소스 검사),
  실제 게이트 상태 여전히 NOT_TRIGGERED, override off/on 및 3개
  trigger_status 시나리오 전부 예상대로 동작. 판정: R3b는
  Conditional Go를 유지한다 — 게이트 상태 불변, `deterministic_
  trigger_engine.py` 미수정, compliance/VaR/broker submit 경계
  미변경, 아직 실제 파이프라인 미연결(별도 승인 필요). 신규 KIS
  호출 0건.

- 작성자: Codex
- 수정일자: 2026-07-18 (58차, `§21 gate` 실제 판단 경로 연결 완료 —
  `deterministic_trigger_engine.py` 실제 수정)
- 수정내용: **[정정] 57차(§47)의 "구현 완료"는 부정확 — 정확히는
  "준비 모듈 + 런타임 미연결" 상태였다.** 이번 턴은 그 미완 지점을
  메웠다(SPPV-2.59). 사용자의 명시적 승인 아래 이 세션 최초로
  `deterministic_trigger_engine.py`를 실제로 수정 — `assess_
  deterministic_triggers`(실제 BUY_CANDIDATE 판정 함수)에 신규
  optional 파라미터(`regime_switch_v1_trigger_status`, 기본값 None;
  `regime_switch_v1_gate_override_enabled`, 기본값 False)를 추가하고
  BUY_CANDIDATE 조건문에 실제로 연결했다. 기존 호출부는 100%
  무영향. `scripts/validate_r3b_gate_integration_path.py`로 동일한
  실제 함수를 3가지(게이트 없음/override off/override on)로 직접
  호출한 결과, 게이트가 실제로 `buy_candidate`를 차단하고 override
  가 실제로 그 차단을 해제함을 확인. 기존 단위 테스트 20건 전부
  통과. 판정: **"§21 게이트 → 실제 판단 경로" 연결 완료** — 다만
  실제 운영 호출부 배선은 별도 미완료(그 전까지 실제 운영 동작
  무영향). R3b는 Conditional Go를 유지한다. compliance/VaR/broker
  submit 경계 미변경. 신규 KIS 호출 0건.

- 작성자: Codex
- 수정일자: 2026-07-18 (59차, `§21 gate` 상위 호출부(`decision_
  orchestrator.py`) 배선 완료)
- 수정내용: **[정정] 58차(§48)의 "실제 판단 경로 연결 완료"는
  과장 — 함수 내부는 연결됐으나 유일한 실제 상위 호출부
  `DecisionOrchestratorService`(`decision_orchestrator.py`)는
  신규 파라미터를 전혀 넘기지 않고 있었다.** 이번 턴이 그 gap을
  메웠다(SPPV-2.60): `DecisionOrchestratorService.__init__`에
  `regime_switch_v1_trigger_status`(기본값 None), `regime_switch_
  v1_gate_override_enabled`(기본값 False) 생성자 인자 추가 → 실제
  호출에 전달, `scripts/run_decision_loop.py`의 두 생성 지점 전부
  에서 `resolve_cached_trigger_status()`(신규 read-only 헬퍼)와
  config 값을 실제로 전달. `scripts/validate_r3b_orchestrator_
  gate_wiring.py`로 `DecisionOrchestratorService`를 실제로 구성해
  검증한 결과, 게이트가 실제로 buy_candidate를 차단하고 override가
  실제로 그 차단을 해제함을 확인. 기존 단위 테스트 83건 전부 통과.
  **중요 리스크**: 이 배선 완료로 `run_decision_loop.py`가 이제
  실제 §21 게이트 상태(NOT_TRIGGERED)를 읽어 전달하므로, override
  가 기본값 False인 한 core BUY_CANDIDATE 판정이 실제로 영향받기
  시작한다 — 사용자 확인 필요한 새로운 실제 동작 변화. 판정: **"§21
  게이트 → 실제 판단 경로" 연결이 함수 내부뿐 아니라 상위 호출부
  까지 완료됐다.** R3b는 Conditional Go를 유지한다. compliance/
  VaR/broker submit 경계 미변경. 신규 KIS 호출 0건.

- 작성자: Codex
- 수정일자: 2026-07-18 (60차, SPPV-2.60 보고 정정 — `resolve_cached_
  trigger_status()` None 원인 규명 + 테스트 증빙 재확인)
- 수정내용: **[정정] 59차(§49)의 검증 산출물에서 `resolve_cached_
  trigger_status_current_value=None`이었으나, 실제로는 캐시 파일
  2개(2026-07-14/2026-07-17) 모두 `trigger_status="NOT_TRIGGERED"`
  를 담고 있었다.** 원인 규명(SPPV-2.61) 결과 코드 결함이 아니라
  기본 `glob_pattern`이 상대경로라 cwd에 의존했기 때문이었다 —
  §49 검증이 실행된 Docker 컨테이너에 캐시 JSON 파일이 복사돼
  있지 않아 `glob`이 빈 결과를 반환한 것. `regime_switch_gate.py`
  에 프로젝트 루트 기준 절대경로 앵커링을 추가해 수정(환경 분기
  없음). 재검증 결과 cwd와 무관하게 `NOT_TRIGGERED`를 정확히
  반환함을 확인. "83건 테스트 통과"는 사실이었으나 실행 로그가
  남아있지 않았던 문제도 pytest를 실제로 재실행하고 `logs/r3b_
  pytest_run_2026-07-18.log`(83 passed)로 증빙을 보강해 정정했다.
  판정: **"배선은 완료됐으나 캐시 상태 전달에는 추가 수정이
  필요"했던 상태에서 "캐시 상태까지 정상 전달됨"으로 확정.**
  §49.6의 리스크는 이번 수정으로 더 급해졌다. R3b는 Conditional
  Go를 유지한다. compliance/VaR/broker submit 경계 미변경. 신규
  KIS 호출 0건.

- 작성자: Codex
- 수정일자: 2026-07-18 (61차, 국면 혼합도 모니터링 모듈 구현 및
  §40 재현성 검증)
- 수정내용: **최신 truth 갱신**: commit `aa10caee`로 §21 게이트
  배선 완료·푸시 확정, 현재 `.env`에 `REGIME_SWITCH_V1_GATE_
  OVERRIDE_ENABLED=true` 설정 — paper 관측 단계에서 게이트는 BUY를
  막지 않는다(paper/production 코드 분기·배선 원복은 더 이상 검토
  대상 아님). 후속 과제 후보(trigger_status 자동화/혼합도 모니터링
  설계/T+5 후속 검증/SPPV-3 착수 준비) 중 **혼합도 모니터링 설계**
  를 이번 턴 최우선으로 선택했다(SPPV-2.62) — trigger_status 자동화
  는 override=true인 동안 급하지 않고, T+5/경로 리스크는 §41~§44
  에서 이미 답변됨. §40이 확정한 혼합도 3분위 경계값(cut1=0.15,
  cut2=0.3833)을 신규 모듈 `services/regime_mixedness_monitor.py`
  (BUY/SELL 미연결 순수 관측용)로 재구현하고, 벤치마크 3년 캐시
  bars만 재사용해(신규 KIS 호출 0건) 634거래일 전체를 재분류했다.
  **결과: 버킷별 거래일 수(저혼합 217일/중혼합 215일/고혼합 202일)
  가 §40 실측치와 정확히 일치(`matches_sppv_2_50=True`).** 해석:
  가설을 다시 검증한 것이 아니라 그 검증 결과를 실제로 소비 가능한
  재사용 가능 코드 모듈로 정확히 이식했다는 것을 100% 재현성으로
  확인 — "혼합도 모니터링 설계" 다음 단계가 설계 스케치에서 검증된
  모듈로 전진했다. 판정: **R3b는 Conditional Go를 유지한다.** 신규
  KIS 호출 0건, 운영 코드 미변경, compliance/VaR/broker submit
  경계 미변경.

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
  - **SPPV-2.17(완료, 2026-07-15, Phase 2 shadow 누적 사이클 구축)**:
    Phase 2를 실행 가능한 오케스트레이터(신규
    `scripts/run_regime_conditional_shadow_cycle.py`)로 구현했다 —
    게이트 판정(§21)과 신호 계산(§22)을 벤치마크 1회 조회로 통합(중복
    KIS 호출 없음), 누적 이력 파일 `logs/regime_conditional_signal_
    shadow_history.jsonl`(append-only, 거래일당 1줄, 중복 거래일 자동
    skip) 구축, `TRIGGERED`/`PARTIAL` 전환 시 재검증 절차(runbook)를
    화면에 출력한다(자동 재검증은 하지 않음). **결과: 신규 KIS 호출
    0건으로 게이트 NOT_TRIGGERED(bearish_trend 0일), 신호 2026-07-14
    기준 `range_bound`로 87/87종목 `risk_adj_momentum_3m` 분기 — 이력에
    1줄 추가. 즉시 재실행해 중복 방지 로직이 정상 발동함을 확인
    (같은 거래일 재추가 skip).** `entry_score` 코드/운영 변경 없음.
    산출: `scripts/run_regime_conditional_shadow_cycle.py`(read-only),
    `logs/regime_conditional_signal_shadow_history.jsonl`. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §6.
  - **SPPV-2.18(완료, 2026-07-15, entry_score 중복 penalty ablation
    실측)**: SPPV-3 착수 전제를 실측으로 구체화했다 — 운영 함수
    (`_build_entry_score`, `_assess_buy_eligibility`)를 그대로
    호출해 오늘(87종목) 기준 세 penalty 축(entry_score regime
    penalty/eligibility regime 차단/eligibility signal floor)을
    독립 평가. **결과: A(85건)/B(60건)/C(75건) 중 B가 발동한 60건은
    예외 없이 A·C도 함께 발동(A∩B∩C=60=B 전체)** — 근본 진단 §2의
    "삼중 중복"이 오늘 데이터로 100% 재현됨을 확인. 종목별(per-symbol)
    regime_label 분포(bearish_trend 69%)가 시장 공통 국면
    (`range_bound`)과 전혀 다름을 재확인 — `entry_score` 통합 시
    국면 정의(종목별 vs 시장 공통) 통일이 새로운 전제로 필요함을
    발견. 운영 DB(`trade_decisions`) 직접 조회는 자동 승인 경계 밖
    으로 판단돼 시도하지 않았다. 산출:
    `scripts/shadow_entry_score_penalty_ablation.py`(read-only,
    신규 KIS 호출 0건),
    `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §8.
  - **SPPV-2.19(완료, 2026-07-15, 중복 억제 시계열 누적 + 국면 정의
    비교 체계 구축)**: §8의 하루치 관찰을 시계열 누적 절차로 승격했다
    — 신규 `scripts/run_entry_score_penalty_ablation_cycle.py`가
    `shadow_entry_score_penalty_ablation.py`(penalty 축 A/B/C)와
    `shadow_regime_conditional_entry_signal.py`(시장 공통 국면)의
    함수를 그대로 재사용해, 종목별 국면과 시장 공통 국면을 같은
    실행에서 나란히 계산하고 누적 이력(`logs/entry_score_penalty_
    ablation_history.jsonl`, 중복 거래일 자동 skip)에 기록한다.
    **결과: §8과 완전히 동일한 수치(A=85/B=60/C=75/A∩B∩C=60)로 교차
    검증, 국면 일치 18건/불일치 69건(79%)** — "시장 비하락장인데
    종목별 하락장" 60건, "시장 하락장인데 종목별 비하락장" 0건.
    재실행으로 중복 방지 정상 발동 확인. **SPPV-3 본작업용 비교
    실험**(기존 3년 rolling 표본에 (a) 현행 종목별 국면 정의와 (b)
    시장 공통 국면 정의로 `_assess_buy_eligibility`를 각각 재계산해
    두 정의 아래 통과 종목의 forward return을 §16 이원 기준으로
    비교, 신규 KIS 호출 없이 수행 가능)을 §9.6에 구체화했다. 산출:
    `scripts/run_entry_score_penalty_ablation_cycle.py`(read-only,
    신규 KIS 호출 0건), `logs/entry_score_penalty_ablation_
    history.jsonl`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §9.
  - **SPPV-2.20(완료, 2026-07-15, §9.6 비교 실험 실측)**: 종목별 vs
    시장 공통 regime 정의 비교 실험을 실제로 실행했다 — 신규
    `scripts/validate_entry_score_regime_definition_comparison.py`가
    운영 `_assess_buy_eligibility()`를 그대로 호출해 변형 A(종목별)/
    변형 B(시장 공통) 각각의 통과군 T+5/T+20 forward return을 §16
    이원 검증 도구로 비교. **결과: 변형 B가 통과율은 더 낮으면서
    (18.75%<20.64%) 통과 종목의 forward return은 더 높음(T+5
    +1.0357%>+0.9254%, T+20 +3.5780%>+3.1861%, 둘 다 baseline 대비
    유의, t_NW 7.3~7.7)** — 과잉 억제가 아니라 정밀한 억제 가능성을
    뒷받침. A-B 차이 자체의 직접 유의성은 미검정, 통과군 내부
    `overall_score` quintile spread는 여전히 유의하게
    역전(T+20 t_NW=-2.84~-3.06) — **판정 Watch(조건부 유리, 확정
    Go 아님)**. 실행 로그를 가정 없이 확인한 결과 `HTTP Request:`
    0건(3년 캐시 완전 재사용). 산출:
    `scripts/validate_entry_score_regime_definition_comparison.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_entry_score_regime_definition_comparison_
    2026-07-15.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §10.
  - **SPPV-2.21(완료, 2026-07-15, A/B 판정 불일치 표본 direct 비교 +
    1차 창 재확인)**: 같은 종목-거래일 표본을 신규
    `scripts/validate_entry_score_regime_definition_ab_diff.py`로
    A_only/B_only/both/neither 4개 배타적 집합으로 분해했다. **결과:
    B_only가 3년(56,753건)·최근 12개월(21,315건) 모두 정확히 0건 —
    시장 공통 정의(B)는 종목별 정의(A)의 진부분집합(strict subset)
    일 뿐, 새 종목을 발굴하지 않고 A가 통과시킨 것 중 일부(A_only,
    3년간 1,072건)를 추가로 차단만 함을 구조적으로 확인.** A_only의
    forward return은 방향상 음수(T+5 -0.1694%, T+20 -0.7028%)이나
    통계적으로 유의하지 않음(t_NW -0.62/-0.79, |t|<1). 최근 12개월
    창은 A_only=B_only=0으로 A-B 차이 자체가 존재하지 않음(§21
    모니터링과 정합) — 재현되지 않은 것이 아니라 검증 기회 자체가
    없는 것. 원래 계획한 "일별 짝비교"는 B_only=0이라 정의상 계산
    불가함을 확인, A_only 자체의 유의성 검정으로 대체. **판정: Watch
    유지(No-Go에 근접), 시장 공통 정의로의 확정 전환(Go)은 기각.**
    실행 로그를 가정 없이 확인 — `HTTP Request:` 0건. 산출:
    `scripts/validate_entry_score_regime_definition_ab_diff.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §11.
  - **SPPV-2.22(완료, 2026-07-15, alpha layer vs regime_conditional_
    signal 직접 비교)**: 무게중심을 국면 정의 통일(차단)에서 alpha
    layer 교체(선별)로 이동했다 — 신규
    `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`가
    현행 alpha layer(순위상 `0.45·overall+0.20·fast+0.15·slow`와
    동일함을 코드로 확인)와 `regime_conditional_signal`을 같은 3년
    표본에서 §16 이원 검증 도구로 직접 비교. **결과: 2차(3년) 창에서
    `regime_conditional_signal`이 T+5(t_NW=2.52)/T+20(t_NW=2.33) 둘
    다 유의, 현행 alpha layer는 어디서도 비유의(1.02~1.39) — spread·
    t값·양수 비율 4개 관측치 전부 일관되게 우세.** 1차 창은 미달이나
    §21 구조적 이유(하락장 부재) 때문. **판정: Conditional Go(2차
    검증 통과, 1차 게이트 전환 대기)** — Watch로 낮추지 않되 억지로
    완전한 Go도 선언하지 않음. 실행 로그로 KIS 호출 0건 확인(가정
    없이 실측). 산출:
    `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_alpha_layer_vs_regime_conditional_signal_
    2026-07-15.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §12.
  - **SPPV-2.23(완료, 2026-07-15, 새 alpha 상위군과 기존 차단 축
    결합 효과 검증 — 가장 빈번한 차단 사유 재발견; 당시 해석은
  이후 §2.24/§14 ablation으로 보정됨)**: `regime_conditional_
    signal`을 새 alpha로 넣었을 때 기존 차단 로직이 그 효과를
    상쇄하는지 신규 `scripts/validate_new_alpha_vs_existing_
    blocking_axes.py`로 검증했다. **결과: 상위 20% 표본의 68.3%
    (3년)/61.1%(최근 12개월)가 차단되나, 차단된 표본도 forward
    return이 강하게 유의하게 양(+)(3년 T+5 +0.815%/t_NW=6.86, T+20
    +3.170%/t_NW=8.35 — 생존군과 큰 차이 없음).** §8/§9/§11이
    조사해온 regime 관련 세 축이 원인일 것이라는 예상과 달리, 신규
    `scripts/diagnose_blocked_reason_distribution.py`로 실제
    eligibility 실패 사유를 집계한 결과 **`eligibility_low_
    relative_activity`(거래량/거래대금 급증 비율<1.10 차단,
    `deterministic_trigger_engine.py:493-499`, 국면·신호와 무관한
    순수 유동성 게이트)가 차단의 압도적 대부분(3년 79.7%, 최근
    12개월 99.6%)을 차지함을 새로 발견** — regime 삼중 중복(축B/C)
    은 오히려 부차적(3년 20.3%, 최근 12개월 0.4%)이었다. **판정:
    `regime_conditional_signal`의 alpha 대체 가치(§12)는 훼손되지
    않아 Conditional Go 유지, 결합 시나리오는 Watch(활동성 필터
    ablation 검증 필요).** 두 스크립트 실행 로그로 KIS 호출 0건
    확인(가정 없이 실측). 산출:
    `scripts/validate_new_alpha_vs_existing_blocking_axes.py`,
    `scripts/diagnose_blocked_reason_distribution.py`(둘 다
    read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_new_alpha_vs_existing_blocking_axes_
    2026-07-15.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §13.
  - **SPPV-2.24(완료, 2026-07-16, 활동성 필터 정밀 ablation — 완전
    제거만 No-Go로 확정, 완화는 Watch)**: `eligibility_low_relative_
    activity`가 실제로 과잉 억제인지 신규 `scripts/validate_
    activity_filter_ablation.py`로 threshold 현행(1.10)/완화
    (1.00)/완전 제거 3개 시나리오를 정밀 비교했다. **완전 제거는
    생존군 forward return이 무차단 상위군 전체 수준으로 회귀하고
    현행 유지보다도 낮아**(2차 T+20 제거 +3.882% < 현행 +4.381%,
    ≈무차단 전체 +3.554%) **No-Go로 확정**. **완화(1.00)는 생존
    종목 수(2차 31.7%→37.7%, 1차 38.9%→46.4%)와 T+5/T+20 평균
    수익률·t_NW·양수율이 1차·2차 창 모두 동시에 소폭(0.07~
    0.18%p) 개선되는 방향은 일관됐으나, 검증 threshold가 1개뿐이고
    개선폭이 작아 Watch(추가 검증 필요)로 기록** — Conditional
    Go로 단정하지 않는다. 판단 기준을 "차단 표본이 플러스인지"에서
    "차단 제거/완화 시 기대수익률이 실제 개선되는지"로 재정정했다
    (2026-07-16 2차 검토, Codex 지적 반영). "차단 비중이 크다"가
    "과잉 억제"를 뜻하지 않고, "표본 증가로 t값이 커진다"가 "품질
    개선"을 뜻하지 않음을 실측으로 확인(완전 제거가 그 역설 사례).
    **결론: 활동성 필터가 BUY 0건의 "주범"인지 "과잉 억제"인지는
    이번 실측만으로 확정할 수 없다** — 재검토 필요 후보로 남기되
    확정적 결론은 쓰지 않는다. §2.23의 "결합 시나리오 Watch" 판정은
    이번 결과로도 Watch로 유지. 실행 로그로 KIS 호출 0건 확인. 산출:
    `scripts/validate_activity_filter_ablation.py`(read-only, 신규
    KIS 호출 0건),
    `logs/signal_ic_activity_filter_ablation_2026-07-16.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §14.
  - **SPPV-2.25(완료, 2026-07-16, 활동성 필터 threshold sweep + 기간
    분할 재현성 검증 — 격상 근거 없음, Watch 유지)**: SPPV-2.24의
    "1.00 완화 Watch" 판정을 Conditional Go 이상으로 올릴 수
    있는지, threshold 1.10/1.05/1.00/0.95/0.90 확장 스윕 + 3년 표본
    전반부(2023-10-10~2025-02-11)/후반부(2025-02-12~2026-06-16)
    분할로 검증했다. **결과: 2차(3년) 전체·1차(최근 12개월)·후반부
    에서는 완화할수록 개선되는 것처럼 보였으나, 전반부에서는
    정반대로 완화할수록 악화됐다**(T+5 기준 1.10 +0.7394% → 0.90
    +0.5728%, 단조 하락). "완화=개선"은 후반부(=최근 12개월과
    거의 동일 시기) 효과가 3년 pooled 평균을 끌어올린 것일 뿐,
    3년 전체를 대표하는 재현성 있는 규칙성이 아니었다. 창마다 최적
    threshold도 달라 단일 sweet spot도 없다. **결론: 완화안을
    Conditional Go로 올릴 근거는 얻지 못했고, 오히려 재현성 부재라는
    신중론 근거가 추가됐다 — 판정 Watch 유지(격상 없음), 완전
    제거는 여전히 No-Go.** 실행 로그로 KIS 호출 0건 확인. 산출:
    `scripts/validate_activity_filter_threshold_sweep.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_activity_filter_threshold_sweep_2026-07-16.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §15.
  - **SPPV-2.26(완료, 2026-07-16, 활동성 필터 완화 효과 전반부/
    후반부 반전 원인 분해)**: SPPV-2.25가 발견한 반전의 원인을
    규명했다. 시장 공통 regime 분포, activity_ratio 분포, 상위
    20% 무차단 기본 수익률 레벨, volatility/turnover/trend 보조
    축, threshold 완화 시 새로 통과하는 표본만 분리한 forward
    return을 비교했다. **결과: 전반부는 range_bound 45.4%+
    bearish_trend 28.5% 혼합/약세 편중, 후반부는 bullish_trend
    82.9% 극편중. 상위 20% 무차단 기본 수익률은 후반부가 전반부의
    약 3.3~3.4배. average_turnover_20d 중앙값도 약 1.9배(378억→
    706억), trend_strength도 약 2.4배 확대. 결정적으로, threshold
    1.10→1.00 완화 시 새로 통과하는 표본의 T+5 평균이 전반부에서는
    기존 통과군보다 낮고(+0.56%<+0.74%, 비유의), 후반부에서는
    오히려 높다(+2.72%>+1.86%, 유의).** **결론: 완화 효과의 반전은
    활동성 필터 로직 결함이 아니라 두 반기의 시장 국면·유동성 구조
    차이가 결합된 결과다** — 국면·유동성 변화가 "완화 시 새로
    들어오는 한계 종목"의 실제 품질을 바꿔놓았다는 것이 직접적
    인과 고리. **판정: 정적 threshold 완화안은 여전히 Watch
    유지(격상도 강등도 아님), 완전 제거는 여전히 No-Go.** 향후
    방향은 "완화"가 아니라 "국면 조건부 threshold"일 가능성(새
    설계 제안, 이번 턴은 원인 규명까지만). 신규 KIS 호출 0건. 산출:
    `scripts/diagnose_activity_filter_half_period_divergence.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_activity_filter_half_period_divergence_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §16.
  - **SPPV-2.27(완료, 2026-07-16, alpha layer 교체 BUY funnel
    검증 — Conditional Go 보강, 확정 Go는 아님)**: 무게중심을
    활동성 필터에서 alpha 교체(§2.22)로 되돌려, 현행 alpha와
    `regime_conditional_signal`을 candidate(상위 20%)→eligible
    (운영 `_assess_buy_eligibility` 그대로)→would_buy(eligible 중
    entry_score 상위 `WATCH_TOP_K_BUY=3`, `trigger_proxy_
    attribution.py:38`의 실제 운영 상수 재사용)→blocked 4단계
    funnel로 비교했다. **결과: would_buy 단계 forward return이
    2차(3년)·1차(최근 12개월)·전반부·후반부 4개 창, T+5/T+20 전부
    (8/8)에서 새 alpha가 현행보다 높았다**(2차 T+20 현행 +1.90%/
    t_NW=2.38 vs 신규 +2.82%/t_NW=2.90). **활동성 필터 완화(SPPV-
    2.25/2.26)와 달리 방향이 한 번도 반전되지 않았다** — 전반부만
    두 시나리오 모두 비유의했으나 방향은 유지됐다. eligible 비율이
    낮아져(2차 31.7% vs 49.2%) would_buy 표본이 약 20% 줄었지만
    표본당 수익률 개선폭이 더 커 누적 기대 성과 근사치는 신규
    alpha가 여전히 컸다. **결론: §2.22의 Conditional Go가 funnel
    실제 매수 후보 단계까지 방향 일관되게 보강됐으나, 전반부
    비유의·국면 편향 가능성·거래 빈도 감소(약 20%)로 확정 Go는
    아니다.** 신규 KIS 호출 0건. 산출:
    `scripts/validate_alpha_layer_buy_funnel_comparison.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_alpha_layer_buy_funnel_comparison_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §17.
  - **SPPV-2.28(완료, 2026-07-16, alpha layer 교체 virtual BUY
    funnel 확장 검증 — Conditional Go 재확인, caveat 2건 발견)**:
    would_buy를 실제 운영 판단 경로에 한 단계 더 가깝게 확장했다.
    운영 함수 `assess_deterministic_triggers()`가 실제로 쓰는
    `BUY_CANDIDATE` 조건(`eligible AND entry_score>=0.65 AND
    allocation_budget_ok`, `deterministic_trigger_engine.py:89`의
    실제 상수 재사용)을 그대로 재현한 `selected` 단계를 추가해
    candidate→eligible→selected→would_buy 5단계로 확장하고,
    MFE/MAE도 계측했다. **결과: selected 단계 추가 후에도
    would_buy의 forward return 우위는 4개 창·2개 horizon 전부
    (8/8)에서 유지됐다.** **결정적 신규 계측: 새 alpha는 4개 창
    전부에서 selected 비율이 정확히 100.0%였다**(`blocked_by_
    score_threshold=0`, 예외 없음) — candidate 정의와 selected
    조건이 같은 alpha 신호를 두 번 거르는 구조라 **0.65 문턱이 새
    alpha에는 사실상 무력화된다는 계측 caveat**을 새로 발견했다
    (현행은 eligible의 66~72%만 통과). **MFE/MAE: 새 alpha는
    상방·하방 진폭 모두 크지만, MFE/|MAE| 비율은 4개 창 전부에서
    새 alpha가 더 높았다**(2차 T+20 현행 1.50 vs 신규 1.68).
    **판정: §2.27의 Conditional Go를 재확인했으나, "0.65 문턱
    사실상 무력화"·"MAE 확대" 두 계측 caveat이 추가되어 여전히
    확정 Go는 아니다.** 신규 KIS 호출 0건, broker submit 미호출.
    산출: `scripts/validate_alpha_layer_virtual_buy_funnel_
    extended.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_alpha_layer_virtual_buy_funnel_extended_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §18.
  - **SPPV-2.29(완료, 2026-07-16, 새 alpha entry_score 스케일
    재보정 shadow 검증 — R3 유력 후보로 격상, 확정 Go는 아님)**:
    §2.28의 "0.65 문턱 사실상 무력화" caveat의 원인을 분해했다 —
    `regime_conditional_signal`이 [-1,1] 스케일이 아닌 퍼센트 단위
    비율(예: 3개월 수익률/변동성=6.0)이라 `_normalize_signed_
    score`가 상위 20% quintile에서 거의 항상 saturate됨을
    확인했다. candidate 정의는 그대로 두고 entry_score 계산에만
    재보정을 적용한 3안(R1 가중치 축소 0.80→0.50/R2 그날 z-score/
    R3 그날 percentile)과 기준선(R0)을 비교했다. **결과: R1은
    selected_rate를 46.6~67.8%로 크게 낮췄지만 forward return이
    4개 창 중 3개에서 오히려 악화돼 기각**(문턱 회복만으로 성공
    판정하지 않는다는 원칙). **R2(z-score)는 selected_rate가
    96.9~99.3%로 R0(100%)와 큰 차이가 없어 문제를 충분히 해결하지
    못했다**(상위 20% 멤버는 정의상 z>=1 saturate 경계 근처에
    몰림). **R3(percentile)가 가장 균형 잡힌 결과 — selected_
    rate를 93.7~96.5%로 의미 있게 낮추면서(문턱 실질 회복),
    forward return이 4개 창·2개 horizon 전부(8/8)에서 개선됐고**
    (2차 T+20 R0 +2.818% vs R3 +3.591%, 1차 T+20 R0 +4.307% vs
    R3 +6.050%), **would_buy 표본 감소는 1.2~2.4%로 미미했으며
    MAE도 3개 창에서 근소 개선됐다.** **판정: R1/R2는 기각, R3
    (percentile 기반 스케일링)를 유력한 재보정 후보로 채택
    검토한다(Watch→Conditional Go 경계) — 다만 단일 실험이고
    재현성을 추가 확인하지 않았으며, §3의 기존 전제조건도 여전히
    미충족이라 확정 Go는 아니다.** 신규 KIS 호출 0건, broker
    submit 미호출. 산출: `scripts/validate_alpha_layer_score_
    rescaling_comparison.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_alpha_layer_score_rescaling_comparison_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §19.
  - **SPPV-2.30(완료, 2026-07-16, R3 재현성 검증 + percentile 계산
    민감도 점검 — R3 유력 후보 격상 철회, Watch로 하향)**: §2.29가
    채택 검토한 R3를 분기 4분할로 재검증하고 percentile 계산
    기준(그날 전체 universe vs candidate 컷 이후 내부)의 민감도를
    점검했다. **결과: R3의 "4개 창 전부 우위" 결론이 분기 단위로는
    무너졌다 — 분기1(2023-10~2024-06)과 분기3(2025-02~2025-10)
    에서 R3가 오히려 R0보다 forward return이 낮았다**(분기1 T+20
    R0 +1.208% vs R3 +1.041%, 분기3 T+20 R0 +3.648% vs R3
    +3.402%). §2.29의 4개 창은 서로 겹치는 넓은 구간이라 해상도가
    낮았음이 원인으로 판단된다. **percentile 계산 기준 민감도도
    컸다 — candidate 컷 이후 내부에서 재계산한 R3b는 8개 창 전부
    (분기1·분기3 포함)에서 R0보다 일관되게 높았으나**, selected_
    rate가 29.9~39.2%까지 낮아져 §2.29에서 기각한 R1과 유사한
    "극단적 선별" 패턴이라 개선이 진짜인지 확정할 수 없다. **판정:
    §2.29의 "R3 유력한 후보로 격상" 판정을 철회하고 Watch로
    하향한다** — 분기 50%에서 방향이 뒤집힌 것은 "일부 분할 창에서
    흔들리면 Watch/Hold"라는 판정 원칙에 정확히 해당한다. **R3b는
    새로운 관찰 대상으로 등록하되 이번 턴에 격상하지 않는다.**
    신규 KIS 호출 0건, broker submit 미호출. 산출:
    `scripts/validate_alpha_layer_r3_reproducibility.py`
    (read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §20.
  - **SPPV-2.31(완료, 2026-07-16, R3b 엄격 재검증 + R3 실패 구간
    원인 분해 — R3b 유력 후보 신규 격상, R3는 Watch 유지)**: R3b를
    R1이 실패한 것과 동일한 엄격 기준(8개 창 중 하나라도 forward
    return이 악화되면 기각)으로 재검증하고, would_buy 종목 집합의
    겹침률(overlap)로 "진짜 선별 품질 개선"과 "표본 급감 착시"를
    분리했다. **결과: R3b는 8개 창 전부(R3가 실패한 분기1·분기3
    포함)에서 R0보다 forward return이 높았다**(2차 T+20 R0
    +2.818% vs R3b +6.134%, 분기1 T+20 R0 +1.208% vs R3b +2.616%,
    분기3 T+20 R0 +3.648% vs R3b +4.932%). **핵심 발견 — overlap
    진단: R3(전체 universe 기준)는 R0와 77~85%가 같은 종목을 고르는
    "미세 재조정"인 반면, R3b(candidate 내부 기준)는 R0와 47~61%
    만 겹친다** — R0가 고르지 않았을 종목의 40~53%를 새로 골라
    넣는 질적으로 다른 선별이며, 순수 표본 축소 착시라면 겹침률이
    100%에 가까워야 하는데 그렇지 않아 **실제 재선별 효과로
    판단**한다. R3 실패 원인 분해에서는 saturation_rate가 4개
    분기 전부 100.0%로 동일해 원인이 아니었고, 국면 분포도 설명력이
    없었다(분기3은 강세장 67.5%가 지배적인데도 실패, 분기2는
    약세+횡보 90.8%가 지배적인데도 성공 — 정반대 패턴). **결론:
    R3의 실패는 특정 국면·유동성 조건 때문이 아니라 R0와의 높은
    겹침에서 오는 작은 효과 크기가 분기 단위 잡음에 취약했기
    때문으로 판단한다.** **판정(당시 판정, SPPV-2.32에서 재정정됨):
    R3b를 유력한 재보정 후보로 신규
    격상한다(Watch→Conditional Go 경계) — R1이 실패한 엄격 기준을
    통과한 첫 재보정안이다.** 다만 selected_rate가 29.9~39.2%로
    매우 낮아 거래 빈도가 최대 36% 줄고, 동일 3년 표본 내부 분할
    이라 진정한 out-of-sample 검증은 아니며, §3 기존 전제조건도
    미충족이라 확정 Go는 아니다. **[중요] 이 판정의 핵심 근거였던
    overlap(간접 지표)은 SPPV-2.32의 대응표본(직접) 검증에서
    근거가 부족했음이 드러나 다시 Watch로 하향 정정됐다.** **R3는
    Watch를 그대로 유지한다.**
    **문서 정정**: "분기 25%가 뒤집혔다"는 계산 오류를 "2/4=50%"로
    5개 정본 문서 전체에서 정정했다(결론 불변). 신규 KIS 호출 0건,
    broker submit 미호출. 산출: `scripts/validate_r3b_strict_and_
    r3_failure_decomposition.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_r3b_strict_and_r3_failure_decomposition_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §21.
  - **SPPV-2.32(완료, 2026-07-16, R3b 대응표본 검증 — overlap
    근거 보정, R3b 다시 Watch로 하향)**: SPPV-2.31의 overlap(간접)
    근거를 대응표본(직접) 검증으로 재확인했다 — 같은 거래일에 R0가
    버리고 R3b가 새로 고른 "대체 종목쌍"의 forward return 차이를
    일별로 계산해 집계했다. **결과: R0 vs R3b 대체쌍(added−
    dropped) T+20 평균이 8개 창 중 6개에서 양(+)이었으나 분기3
    에서는 음수(-0.47%p, 대체 우위일 비율 45.8%로 절반 미만)로
    뒤집혔다.** t_NW가 통상 유의 수준(1.96) 이상인 창은(SPPV-2.33
    에서 3개로 정정됨 — 2차·전반부·분기1, 최초 서술은 분기1 누락)
    나머지는 marginal했다. **R0 vs R3(전체
    universe) 대체쌍은 더 약해** 분기1(-0.44%p)·분기3(-0.04%p)
    에서 사실상 음수/0이었다. **핵심 정정: SPPV-2.31이 overlap
    만으로 "실제 재선별 효과"라고 결론 낸 것은 근거가 부족했다**
    — 이번 직접 검증에서 그 재선별이 분기3에서는 오히려 더 나쁜
    종목으로의 교체였음이 드러났다. aggregate 우위(8/8) 자체는
    부정되지 않으나 그 우위가 "대체 종목의 우수성"에서 왔다는
    인과관계는 확인되지 않았다. **판정: SPPV-2.31의 "R3b 유력
    후보 격상" 판정을 다시 Watch로 하향한다.** R3는 Watch를
    유지하되 이번 직접 검증으로 근거가 강화됐다. 신규 KIS 호출
    0건, broker submit 미호출. 산출: `scripts/validate_r3b_
    paired_replacement_analysis.py`(read-only, 신규 KIS 호출
    0건), `logs/signal_ic_r3b_paired_replacement_analysis_
    2026-07-16.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §22.
  - **SPPV-2.33(완료, 2026-07-16, R3b aggregate 우위 vs 대응표본
    음수 구간 3분해 — 원인 규명, Watch 판정 유지)**: 문서 정정 —
    "t_NW≥1.96 창 2개" 서술을 산출 JSON으로 재확인해 **실제로는
    3개(2차=1.96, 전반부=2.07, 분기1=2.02)**였음을 정정했다(분기1
    누락). common_kept/dropped_only/added_only 항등식 분해로
    aggregate 우위 원인을 규명했다. **결과: R0 vs R3b에서 added_
    only의 평균이 8개 창 전부에서 common_kept·dropped_only보다
    뚜렷이 높았다**(2차 T+20 added +8.98% vs common +3.83% vs
    dropped +2.23%) — R3b의 신규 선택 자체는 실제로 우수했으며,
    §2.32의 표본 급감 착시 우려를 상당 부분 반박한다. **다만 R0의
    구성이 저품질 dropped_only 비중(63.3%, 2차)이 커서 aggregate
    차이의 상당 부분이 "구성 효과"에서도 왔다.** **[SPPV-2.34에서
    정정: 이 방향은 틀렸다 — 구성효과는 실제로 우위를 상쇄하는
    음(-) 방향이었다.]** **가장 중요한
    발견: 분기3에서 이번 pooled 교체효과(+2.594%p)와 §2.32의
    paired 교체효과(-0.4666%p)의 부호가 정반대다** — 가중 방식
    차이(종목-일 동일가중 vs 거래일 동일가중) 때문이며, R3b의
    효과가 "매일 조금씩"이 아니라 "소수 스왑 밀집일에 집중"된
    비대칭 구조임을 시사한다. R0 vs R3에서는 분기1·분기3 모두
    added_only<dropped_only로 "미세 재조정" 가설이 pooled 직접
    계측으로도 재확인됐다. **판정: aggregate 우위는 부분적 실체가
    있으나(added_only 우수성) 비대칭적이고 특정 구간 집중형이라
    안정적 재현으로 단정하기 이르다 — R3b/R3 모두 §2.32의 Watch
    판정을 그대로 유지한다(이번 턴은 재격상이 아닌 원인 규명이
    목적).** 신규 KIS 호출 0건, broker submit 미호출. 산출:
    `scripts/validate_r3b_aggregate_vs_paired_decomposition.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_
    aggregate_vs_paired_decomposition_2026-07-16.json`. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §23.
  - **SPPV-2.34(완료, 2026-07-16, R3b pooled 우위 날짜 집중도
    검증 + 교체효과/구성효과 정량 분리 — 원인 확정, Watch 판정
    유지)**: 거래일별 스왑 개수 상위 10% 제거 후 aggregate 우위
    잔존비율을 계산하고, `aggregate_diff=replacement_effect+
    composition_effect` 정확한 항등식으로 두 효과를 정확히
    분리했다. **결과 1(날짜 집중도): 스왑 상위 10% 거래일을
    제거해도 8개 창 중 7개에서 aggregate 우위가 80~120% 수준으로
    거의 그대로 남거나 오히려 커졌다** — "소수 거래일 집중" 가설은
    이 7개 창에서 기각된다. **분기3만 예외로 잔존비율이 T+5=29.7%,
    T+20=65.2%로 크게 줄어들어**, pooled·paired 부호 불일치가
    실제로 소수 스왑 밀집일의 아티팩트임이 직접 확인됐다. **결과
    2(중요 정정): §2.33의 "구성효과도 상당히 기여한다"는 서술은
    방향이 틀렸다** — `composition_effect`는 8개 창 중 6개에서
    오히려 음(-)이었다(2차 T+20 aggregate=+3.32%p = replacement
    +4.27%p + composition **-0.96%p**) — 구성효과는 R3b의 우위를
    상쇄하는 방향이었고, 우위 전체는 순수 `replacement_effect`
    에서 왔다. R0 vs R3도 같은 패턴. **판정: 이번 턴도 재격상보다
    원인 확정을 우선했다.** R3b 우위 근거는 명확해졌으나 분기3
    반례가 실제 집중형임이 확인돼 **R3b/R3 모두 §2.32~§2.33의
    Watch 판정을 그대로 유지한다.** 신규 KIS 호출 0건, broker
    submit 미호출. 산출: `scripts/validate_r3b_day_concentration_
    and_effect_decomposition.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_r3b_day_concentration_and_effect_
    decomposition_2026-07-16.json`. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §24. **[SPPV-2.35에서 정정]
    "구성효과 8개 창 중 6개 음(-)"은 T+5/T+20을 뒤섞은 표현이었다
    — 정확히는 T+20 기준 8/8, T+5 기준 5/8에서 음(-). "분기3만
    실제 집중형"이라는 서술도 방향이 과했다 — §2.35 참고.**
  - **SPPV-2.35(완료, 2026-07-16, 분기3 스왑 집중일 세부 진단 +
    SPPV-2.34 해석 문구 정밀 보정 — 원인 확정, Watch 판정 유지)**:
    분기3 스왑 발생일 83건 중 상위 15건을 개별 진단(스왑 개수,
    common_kept/dropped_only/added_only 평균, 그날 교체효과,
    leave-one-day-out). **보정 1: "구성효과 8개 창 중 6개 음(-)"
    은 T+5/T+20을 뒤섞은 표현 — 정확히는 T+20 기준 8/8, T+5 기준
    5/8에서 음(-)(전반부·분기1·분기2는 T+5에서 양(+)).** **보정
    2: "분기3만 실제 날짜 집중형"이라는 서술은 방향이 과했다 —
    대형 스왑일(상위 10%, 약 8일)의 T+20 교체효과 단순평균은
    +7.04%p로 뚜렷한 양(+)이고, 분기3 전체 83일 paired 평균
    (-0.4666%p, 음)의 진짜 원인은 나머지 약 75개 소규모 스왑일
    에서 평균 약 -1.267%p의 완만하지만 지속적인 음(-) 효과가
    누적된 것이다(가중평균 항등식 역산) — "대형 스왑일이 나쁘다"
    가 아니라 "대형 스왑일은 유일한 강한 양(+)의 원천이고, 그것을
    빼면 넓게 퍼진 다수의 완만한 음(-) 거래일만 남는다"는 구조다.**
    가장 나쁜 두 거래일(2025-02-12, 02-13)이 연속 거래일이라는
    점은 짧은 이벤트/뉴스 군집 가능성을 시사하나, 외부 데이터를
    조회하지 않아 가설 수준이다. **판정: 재격상/재하향 없이 R3b/R3
    모두 §2.32~§2.34의 Watch 판정을 그대로 유지한다.** 신규 KIS
    호출 0건, broker submit 미호출. 산출: `scripts/validate_r3b_
    q3_day_level_diagnostics.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_r3b_q3_day_level_diagnostics_2026-07-16.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §25. **[SPPV-2.36에서 정정] "대형 스왑일은 유일한 강한 양(+)의
    원천"은 과장이었다 — 아래 SPPV-2.36 참고.**
  - **SPPV-2.36(완료, 2026-07-17, 분기3 반례의 대형/소규모 스왑
    구조 정밀 확정 + "전적으로 의존" 문구 보수화 — 구조 확정,
    Watch 판정 유지)**: 분기3 83개 스왑일 전체를 5분위(quintile)로
    구간화하고 leave-top-k-days-out, 부호별 총합 분해, 02-12/13
    동시 제거 효과를 계측했다. **결과 1(5분위): T+20 기준 Q1(최대,
    스왑4~6)=+6.29%p, Q2=-3.04%p, Q3=-2.96%p, Q4(스왑2~3)=
    **+4.38%p**, Q5(최소, 스왑2)=**-7.57%p** — "대형=양(+)/소규모=
    음(-)"은 양극단(Q1·Q5)에서만 성립하고 중간(Q2~Q4)은 혼재한다.**
    **결과 2(전적 의존 여부): aggregate(순 기여) 관점에서 대형
    스왑일(상위 10%)이 우위의 상당 부분(leave-top-decile-out
    잔존비율 T+5=29.7%, T+20=65.2% → 대형이 T+5 약 70%, T+20 약
    35% 담당)을 차지하지만, **총합(gross) 관점에서는 전체 양(+)
    합계의 15%(T+5 15.6%, T+20 15.0%) 수준에 불과** — "전적으로
    의존"·"유일한 원천"은 과장이었다.** **결과 3: 02-12/13 동시
    제거는 T+20 paired 평균의 음(-) 갭을 -0.4666%p→-0.2829%p(약
    39.4% 축소)로 만들 뿐 — 유의미하나 부분적(과반 미만) 설명력.**
    **판정: 재격상/재하향 없이 R3b/R3 모두 §2.32~§2.35의 Watch
    판정을 그대로 유지한다**(구조 확정·문구 보수화가 목적).
    "완전한 착시가 아니다"는 여전히 유효(Q1의 실제 양(+),
    replacement_effect의 순수 기여는 실재). 신규 KIS 호출 0건,
    broker submit 미호출. 산출: `scripts/validate_r3b_q3_swap_size_
    bucket_decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_q3_swap_size_bucket_decomposition_2026-07-17.
    json`. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §26.
  - **SPPV-2.37(완료, 2026-07-17, R3b의 SPPV-3 진입 후보 여부 판단
    — 실제 BUY funnel 최소 검증 — Watch→Conditional Go 상향)**:
    R3b 미세 해부를 멈추고 SPPV-3 착수 후보 여부를 판단. 기존
    §2.30의 8개 창 BUY funnel 계측(candidate→eligible→selected→
    would_buy, 재실행 없이 재사용) 결과 **T+20 평균 우위 8/8 창
    일관**(R3b>R0), t_NW 6/8 창 유의(≥1.96), 나머지 2개(분기1=1.31,
    분기2=1.68)는 marginal. **신규 계측(결정적 근거): would_buy
    모집단을 거래일별로 묶어 top-decile-day leave-out을 8개 창
    전부에 적용 — "거래일 집중 의존"은 R3b만의 문제가 아니라
    R0(기준선) 자체가 8개 창 중 3개(전반부/분기1/분기2)에서 상위
    10% 거래일 제거 시 T+20 평균이 마이너스로 뒤집히는 alpha 신호
    계열 전반의 특성이며, R3b는 8개 창 전부(8/8)에서 R0보다 잔존
    비율이 더 높다**(예: 2차 R0 -0.1% vs R3b 41.9%, 분기2 R0
    -173.3% vs R3b 35.2%) — R3b가 R0보다 거래일 집중에 덜 의존.
    **판정: R3b를 Watch에서 Conditional Go로 상향한다.** 단, 확정
    Go 전 잔여 조건: (1) 분기1·분기2 marginal t_NW의 out-of-sample
    재확인, (2) selected_rate 급감(29.9~39.2%)이 총 기대수익(거래
    빈도×종목당 수익)에 미치는 영향 정량화, (3) §3 전제조건(1차
    게이트 TRIGGERED 전환) 충족 확인, (4) 실제 point-in-time
    `entry_score` 파이프라인 반영 shadow 실행. 신규 KIS 호출 0건,
    broker submit 미호출. 산출: `scripts/validate_r3b_sppv3_entry_
    readiness_check.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_sppv3_entry_readiness_check_2026-07-17.json`.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §27. **[SPPV-2.38에서 정정] "8개 창 중 3개"와 "3/8 창"은 계산
    오류였다 — 아래 SPPV-2.38 참고.**
  - **SPPV-2.38(완료, 2026-07-17, SPPV-2.37 수치 정정 + Conditional
    Go 재평가 — Conditional Go 유지)**: §2.37의 세 가지 수치
    서술을 재검산해 정정. **정정 1: R0의 top-decile-day 음(-)
    반전 창 수는 "3개"가 아니라 "4개"(2차 포함).** **정정 2: 양수
    비율 열세 창 수는 "3/8"이 아니라 T+20 기준 "1/8"(분기2만),
    T+5 기준 "0/8".** **정정 3: "selected_rate 급감(약 30~40%)"은
    R3b 자신의 비율 수준(29.86~39.16%)이며 R0(100%) 대비 약
    61~70%p 감소로 명확화.** **판정: 세 정정 모두 R3b의 방향성
    우위를 약화시키지 않아 R3b는 Conditional Go를 유지한다.**
    §2.37의 확정 Go 전 잔여 조건 4가지는 이번 정정과 무관하게
    그대로 유효. 새 실험 없이 기존 JSON `python3 -c` read-only
    재검산만 수행(신규 실행 없음, KIS 호출 해당 없음). 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §28.
  - **SPPV-2.39(완료, 2026-07-17, selected_rate 감소가 총 기대
    수익에 미치는 영향 정량화 — Conditional Go 근거 보강)**: R3b
    Conditional Go 확정 전 잔여 조건 중 조건 (2)를 정량화. 신규
    실측 없이 기존 산출물 2개만 재사용해 총 기대수익 proxy(=
    would_buy_n × mean_forward_return_pct)를 8개 창×2horizon(16개
    조합) 전부 계측한 결과 **14/16 조합에서 R3b의 총proxy가 R0
    보다 높다**(92.0%~322.6%). 나머지 2개(1차 T+5, 분기3 T+20)도
    거의 동률. 활동일당 평균 매수 수는 R0(2.69~2.80) 대비 R3b
    (2.15~2.31)가 낮아 "덜 산다"는 사실은 확인되나, 거래당 수익률
    개선이 거래 횟수 감소를 상쇄하고도 남는다. **판정: "거래 빈도
    감소가 총 기대수익을 훼손하는가"에 명확히 "아니다" — 확정 Go
    전 잔여 조건 4가지 중 1개(조건 2)가 해소돼 Conditional Go
    근거가 보강됐다.** 나머지 3개 조건(분기1·분기2 marginal t_NW,
    §3 전제조건, point-in-time 파이프라인 반영)은 그대로 남아
    확정 Go는 아니다. 신규 KIS 호출 없음(신규 실행 없음). 산출:
    `scripts/validate_r3b_total_expected_return_proxy.py`(read-only,
    KIS 호출 없음), `logs/signal_ic_r3b_total_expected_return_
    proxy_2026-07-17.json`. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §29. **[SPPV-2.40에서 정정]
    "조건 (2) 해소"는 과장이었다 — 아래 SPPV-2.40 참고.**
  - **SPPV-2.40(완료, 2026-07-17, R3b 총 기대수익 proxy의 유휴
    자본 반영 보강 검증 — "조건 (2) 해소"→"완화/축소"로 재조정)**:
    SPPV-2.39의 "조건 (2) 해소"를 유휴 자본 기회비용까지 반영해
    보강 검증. 신규 계측은 창별 전체 거래일 수 하나뿐(캐시 봉
    데이터만 사용, 신규 KIS 호출 없음). **엄격 기준("R0가 전체
    슬롯(거래일×3)을 자기 평균으로 100% 채웠다"는 이론적 최대와
    R3b의 실현 총합을 비교) 적용 결과, T+20은 8개 창 중 7개(분기3
    제외)에서 여전히 R3b가 우위**(108.5%~177.5%, 견고)**이나, T+5
    는 8개 창 중 6개에서 우위가 사라지거나 이미 열세**(84.3%~
    98.8%, 전반부·분기2만 통과, 취약)**.** 전체 슬롯 정규화
    (per-slot) proxy는 raw proxy와 대수적으로 완전히 같은 비율을
    보여(항등식) 새 정보를 주지 않음도 확인. **판정: "조건 (2)
    해소"는 과장 — 정확히는 "T+20 기준 완화, T+5 기준 여전히
    미해결" 수준으로 재조정한다.** R3b는 Conditional Go를 유지한다
    (확정 Go 아님). 확정 Go 전 잔여 조건에 "T+5 horizon 의존
    여부에 따른 유휴 자본 취약성 확인"을 추가. 신규 KIS 호출
    0건(로그 확인). 산출: `scripts/validate_r3b_capital_
    utilization_adjusted_proxy.py`(read-only, 신규 KIS 호출 0건),
    `logs/signal_ic_r3b_capital_utilization_adjusted_proxy_2026-
    07-17.json`. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §30.
  - **SPPV-2.41(완료, 2026-07-17, R3b Conditional Go의 운영
    horizon 적합성 판단 — Conditional Go 유지, T+5 강건성을 확정
    Go 필수조건으로 격상)**: R3b의 T+5 취약성(§30)이 실운영과
    충돌하는지 판단하기 위해 운영 코드(`deterministic_trigger_
    engine.py`, `ai_agents/schemas.py`, `common_types.py`)와 5개
    기준 문서를 read-only로 조사(신규 KIS 호출 없음, 스크립트
    실행 자체가 없었음). **결과: SELL/청산 판정은 `exit_score`
    (신호/점수)를 계산해 임계값과 비교하는 100% 신호 기반이며,
    경과일수·보유일수를 입력으로 쓰는 코드 경로가 전혀 없다.**
    `max_holding_days=20`(`schemas.py`의 `ExitPlanHint`)은 AI
    Risk agent의 **LLM 출력 힌트 기본값**일 뿐 실제로 20일 뒤
    매도를 강제하는 코드가 없다 — T+20과 우연히 일치하는 숫자
    이지만 인과관계는 없다. 문서상 1차/2차 구분도 horizon이 아닌
    **기간 창** 구분이며, 기존 §16 Go/No-Go 표준은 T+5·T+20을
    이미 동시에 요구해왔다(새 기준 아님). 실거래 이력도 진입-청산
    쌍이 없어 평균 보유기간을 실측할 수 없다. **판정: "이 시스템이
    T+20 중심이라 T+5 약점을 무시해도 된다"는 주장은 코드로
    뒷받침되지 않는다.** R3b는 **Conditional Go를 유지**한다(즉시
    Watch 재하향 근거는 부족). 확정 Go 전 잔여 조건에 **"T+5
    horizon 강건성 확보(또는 실거래 누적 후 청산 시점 분포 실측)"
    를 기존 3개 조건과 동등한 필수조건으로 격상**한다. 신규 KIS
    호출 없음(read-only 조사만 수행, 산출 파일 없음). 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §31.
  - **SPPV-2.42(완료, 2026-07-17, R3b를 point-in-time entry_score
    파이프라인에 반영한 shadow 검증 — Conditional Go 유지, 조건
    부분 해소)**: §18(SPPV-2.28)부터 이미 실제 운영 함수(`build_
    signal_snapshot`/`_assess_buy_eligibility`/`_build_entry_
    score`)를 직접 호출해왔음을 확인했으나, 실제 `strategy_
    selection` 조정항(+0.05 보너스)이 그동안 `None`으로 누락돼
    있었다. `portfolio_allocation`과 달리 `strategy_selection`은
    market_regime·source_type만으로 계산되는 순수 함수라 오프라인
    에서도 실제 `select_strategy()`로 채울 수 있어, A(현행)와
    R0/R3b(가상 alpha 교체) 양쪽에 동일하게 반영해 8개 창 BUY
    funnel을 재계측했다(신규 KIS 호출 0건). **결과: 8개 창×
    2horizon(16개 조합) 전부에서 R3b>R0 방향이 그대로 유지된다**
    (방향 붕괴 없음) — 6개 조합은 강화(1차 양쪽, 후반부 T+5, 분기3
    T+20, 분기4 양쪽), 나머지는 소폭 약화. **단 분기1 T+20의
    t_NW가 1.31→0.96으로 더 약화**돼 기존 marginal 우려가
    심화됐다. R3b의 selected_rate도 소폭 상승(예: 2차 35.4%→
    39.4%). **판정: R3b는 Conditional Go를 유지한다.** "point-
    in-time 파이프라인 반영" 조건은 **부분 해소**로 기록한다 —
    핵심 우려(실제 파이프라인에 가까워지면 우위가 사라질 수
    있다)는 해소됐으나 `portfolio_allocation` gap(계좌 상태 필요,
    실거래 이력 없어 재현 불가)은 여전히 미해결. 신규 KIS 호출
    0건, broker submit 미호출. 산출: `scripts/validate_r3b_
    point_in_time_pipeline_shadow.py`(read-only, 신규 KIS 호출
    0건), `logs/signal_ic_r3b_point_in_time_pipeline_shadow_
    2026-07-17.json`. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §32.
  - **SPPV-2.43(완료, 2026-07-17, 분기1 t_NW 약화의 원인 정밀
    진단 — 방향성 붕괴 vs 변동성/이상치 문제 — Conditional Go
    유지, 잔여 리스크 성격 구체화)**: 분기1은 세 분기 중 가장
    "혼합 국면" 구간이다(강세 40.6%/횡보 46.6%/약세 10.4% 고른
    분포, event_driven_unstable 2.4%로 다른 분기 대비 약 4배) —
    분기2는 약세(46.6%) 지배, 분기3은 강세(67.5%) 지배로 단일
    국면 편중이 뚜렷한 것과 대비. **R3b>R0 방향은 분기1에서도
    그대로 유지된다**(1.815% vs 0.753%, 약 2.4배) — **스왑
    발생일 46건 중 33건(71.7%)이 양(+) 방향으로 세 분기 중 최다**,
    상위 10% 스왑일 제거 시 잔존비율이 157.8%로 **개선**(분기3과
    정반대 구조). t_NW 약화의 실체: 상위 10개 스왑일 중 3건이
    절댓값 16~44%p의 극단치(2건 강한 음(-), 1건 강한 양(+))로
    표준오차를 키운 것으로 확인. **판정: 분기1 t_NW 약화는 R3b
    전체를 뒤집는 치명적 결함이 아니라 혼합 국면 구간의 변동성/
    이상치 문제로 좁혀진다 — 방향 반전 증거는 없다.** R3b는
    **Conditional Go를 유지**한다(Watch 재하향 근거 없음). 신규
    KIS 호출 0건, broker submit 미호출. 산출: `scripts/validate_
    r3b_quarter1_weakness_diagnosis.py`(read-only, 신규 KIS 호출
    0건), `logs/signal_ic_r3b_quarter1_weakness_diagnosis_2026-
    07-17.json`. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §33.
  - **SPPV-2.44(완료, 2026-07-17, SPPV-3 진입 관문 3종 종합 판정
    — §3 게이트 재확인 + 분기1/T+5 리스크 종합 — Conditional Go
    유지, SPPV-3 진입은 §3 게이트 미충족으로 아직 이름)**: SPPV-3
    진입 전 마지막 관문 3가지(①§3 전제조건, ②분기1 약화, ③T+5
    취약성)를 종합 판정. 기존 검증(분기1=SPPV-2.43, T+5=SPPV-2.41)
    을 반복하지 않고, 유일한 신규 실측인 §3 게이트(`regime_switch_
    v1` 1차 게이트, 기존 SPPV-2.13 모니터링 스크립트 `scripts/
    monitor_regime_switch_v1_gate.py` 재실행)만 확인(신규 KIS
    호출 0건, 벤치마크 캐시로 전량 서빙). **결과: `NOT_TRIGGERED`
    (불변)** — 기준일 2026-06-16 기준 최근 12개월 창에 `bullish_
    trend` 239일, `range_bound` 6일, `bearish_trend` **0일**
    (문턱 30일 미달). **종합 판정표: ①§3 전제조건(게이트+risk_
    off_penalty 중복 해소) — 미충족. ②분기1 약화 — 제한된 잔여
    리스크(치명적 결함 아님). ③T+5 취약성 — 미해결이나 치명적
    근거 없음.** **판정: R3b는 Conditional Go를 유지한다.** 다만
    **SPPV-3(운영 코드 반영) 진입은 아직 이르다 — 주된 차단 요인은
    R3b의 성과와 무관한 §3 게이트(하락장 미도래)**이며, "규칙
    A(관찰 유예)"에 따라 인위적으로 앞당길 수 없다. Watch로
    재하향할 근거는 없다. 산출: `logs/regime_switch_v1_gate_
    monitor_2026-07-17.json`(스크립트의 실제 하드코딩 출력 경로는
    `..._2026-07-14.json` — 컨테이너 산출을 호스트로 복사하며
    수동 재명명한 사본, SPPV-2.45에서 정정), `logs/regime_switch_
    v1_gate_monitor_run_2026-07-17.log`(신규 스크립트 없음). 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §34.
  - **SPPV-2.45(완료, 2026-07-17, SPPV-2.44 산출물 파일명/실행
    경로 불일치 정정 — 결론 유지, 기록만 정정)**: `monitor_regime_
    switch_v1_gate.py`는 실행 시점과 무관하게 항상 하드코딩된
    `..._2026-07-14.json`에 저장한다 — SPPV-2.44가 인용한 `..._
    2026-07-17.json`은 컨테이너 산출을 호스트로 복사하며 수동
    재명명한 사본이지, 스크립트가 그 이름으로 직접 저장한 것이
    아니다. 내용은 실제 재실행 결과가 맞고(as_of 일치) 결론에
    영향을 주는 차이는 없다. **판정: 정정 후에도 SPPV-3 관련
    결론은 전혀 바뀌지 않는다 — R3b Conditional Go 유지, SPPV-3
    진입은 §3 게이트 미충족으로 아직 이르다는 판정을 그대로
    유지한다.** 새 실측/새 스크립트 없이 기존 코드·로그 재확인만
    수행(신규 KIS 호출 해당 없음). 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §35.
  - **SPPV-2.46(완료, 2026-07-17, R3b 채택 시 risk_off_penalty
    중복 해소 ablation — Conditional Go 유지, §3 조건② 방향 확인)**:
    entry_score 축(-0.15, `_build_entry_score:1139-1141`)과
    eligibility 축(즉시 차단, `_assess_buy_eligibility:421-438`)이
    서로 다른 함수의 별개 축임을 코드로 확정하고, A(현행)/B
    (entry_score 축 무력화)/C(eligibility 축 완화) 3개 시나리오를
    R3b candidate 위에서 실제 운영 함수 호출로 비교(운영 코드
    미수정, market_regime 입력만 국소 중립화). **결과: C는 2차·
    1차 창 모두 A와 완전 동일**(eligibility 축이 R3b candidate
    pool에서 비활성) — 중복 우려는 애초에 발생하지 않는다. **B는
    T+20 총 기대수익 proxy가 2차 +20.9%/1차 +20.5% 개선되나 MAE도
    소폭 악화(약 0.5%p)** — 실제 트레이드오프. **판정: eligibility
    축은 비활성, entry_score 축은 "완화 검토 후보"에 가깝다는
    실측 근거 확보 — R3b는 Conditional Go를 유지하고, §3 조건②는
    "방향 확인, 사용자 승인 대기"로 진전, SPPV-3 진입은 §21 게이트
    미충족으로 여전히 이르다(불변).** 신규 KIS 호출 0건, broker
    submit 미호출. 산출: `scripts/validate_r3b_risk_off_penalty_
    duplication_ablation.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_risk_off_penalty_duplication_ablation_2026-
    07-17.json`. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §36.
  - **SPPV-2.47(완료, 2026-07-17, 승인 범위 확정 + risk_off_
    penalty(entry_score 축) 완화안 심층 해석 — Conditional Go
    보강, SPPV-3 진입 관점에서 남은 조건은 사실상 §21 게이트
    하나로 좁혀짐)**: 사용자가 §2.46의 A/B/C 중 "B — entry_score
    risk_off_penalty만 완화"를 승인(eligibility 축 비승인 — C는
    이미 A와 완전 동일해 애초에 완화 대상이 아니었음을 재확인).
    **신규 실행 없이** §2.46 산출물을 재사용해 T+5/T+20 양쪽·MAE
    트레이드오프를 심층 재해석했다. **결과: 총 기대수익 proxy가
    2개 창(2차/1차)×2horizon 전부에서 개선한다**(2차 T+5 +14.3%,
    T+20 +20.9%, 1차 T+5 +12.9%, T+20 +20.5%) — **T+20뿐 아니라
    T+5도 유의미하게 개선**되며, t_NW도 함께 개선(+4.2~5.4%).
    **MAE는 소폭 악화하나(5.9~7.8% 상대 증가) 개선폭보다 항상
    작다** — 손실 심화가 수익 개선을 초과하지 않는 트레이드오프.
    **판정: R3b + entry_score risk_off_penalty 제거 조합은
    Conditional Go를 보강한다.** SPPV-3 진입 관점에서 남은 조건은
    §3 전제조건 ②가 "실측 근거 확보 + 사용자 승인"까지 진행되면서
    **사실상 §21 게이트 하나로 좁혀졌다** — 다만 entry_score 코드
    반영 자체는 게이트 충족 이후 별도 절차이며 확정 Go는 아니다.
    신규 KIS 호출 없음(신규 실행 자체가 없었음). 산출물: 신규
    산출물 없음(§2.46 재사용). 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §37. **[SPPV-2.48에서 정정]
    "게이트 하나"는 §3 전제조건 범위로만 정확하고 SPPV-3 진입
    전체로는 과장 — 아래 SPPV-2.48 참고.**
  - **SPPV-2.48(완료, 2026-07-18, SPPV-2.47 "게이트 하나만
    남았다" 표현 정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리 —
    Conditional Go 유지, 방향 후퇴 아님)**: §2.47의 서술을
    재점검한 결과 **§3 전제조건 범위로 한정하면 정확하나 SPPV-3
    진입 전체로는 과장**이었음을 확인했다. 새 실측·새 설계 제안
    없이 기존 문서(§2.41 T+5 구조적 리스크, §2.43 혼합 국면
    재확인, §2.40 portfolio_allocation gap)만 재해석 — 이 세
    항목은 §3의 하위 항목이 아니라 독립적으로 확정 Go 조건에 이미
    명시돼 있었다. **재분류: ①주된 차단 요인(§21 게이트, 외생적)
    ②보조 잔여 조건(entry_score 코드 반영 절차, T+5 구조적 리스크,
    혼합 국면 재확인) ③실거래 누적 없이는 못 푸는 조건(portfolio_
    allocation gap, 실제 청산 시점 분포).** **판정: R3b는
    Conditional Go를 유지한다** — 방향 후퇴가 아니라 서술 정밀도만
    회복. 신규 KIS 호출 없음(신규 실측 없음). 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §38.
  - **SPPV-2.49(완료, 2026-07-18, 혼합 국면(분기1 유형) 재확인 —
    분기4 대조 계측 — Conditional Go 유지, 조건이 "확인·추적
    대상 패턴"으로 전진)**: 보조 잔여 조건 중 "혼합 국면 재확인"
    만 지금 당장(실거래 없이) 전진 가능해 최우선으로 선택 — T+5
    구조적 리스크는 실거래 청산 이력 필요, entry_score 코드 반영
    절차는 §21 게이트 충족 후 별도 트랙. 승인된 조합(R3b+entry_
    score risk_off_penalty 제거, B 시나리오)으로 분기1(재계측)과
    분기4(신규 계측, 이번 세션 최초 국면 계측)의 국면 분포·funnel
    을 비교했다(신규 KIS 호출 0건). **결과: 분기4는 시장 공통
    국면이 사실상 순수 단일**(bullish_trend 98.2%, range_bound
    1.8%)로 **분기1(혼합 국면)과 정반대** — 분기4는 **T+20 t_NW=
    3.00, 양수율=60.3%, 총 기대수익 proxy=4436.0**으로 강하고
    일관되나, **분기1은 T+20 t_NW=1.27(marginal), 양수율=46.2%,
    총 기대수익 proxy=661.7**로 뚜렷이 대비된다. **판정: "혼합
    국면→약한 t_NW" 가설이 분기1 1건의 우연이 아니라 대조쌍으로
    확인됐다 — 조건 해소는 아니나 "미확인 가설"에서 "확인·추적
    대상 패턴"으로 전진.** R3b는 Conditional Go를 유지한다. 신규
    KIS 호출 0건, broker submit 미호출. 산출: `scripts/validate_
    r3b_mixed_regime_quarter4_check.py`(read-only, 신규 KIS 호출
    0건), `logs/signal_ic_r3b_mixed_regime_quarter4_check_2026-
    07-18.json`. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §39.
  - **SPPV-2.50(완료, 2026-07-18, "혼합 국면 약세" 가설 직접 분해 —
    거래일 단위 혼합도 3분위 버킷화 — Conditional Go 유지, "구조적
    패턴"으로 격상)**: §2.49의 분기1 vs 분기4 대조는 N=2 분기
    대조에 불과해 "특정 분기 우연" 가능성을 완전히 배제하지
    못했다. 분기 경계와 무관하게 각 거래일마다 최근 60거래일(약
    1분기) 창의 시장 공통 국면 혼합도(mixed_score=1-최빈 라벨
    비중)를 직접 계산해 3년 전체 634거래일을 혼합도 3분위(저혼합
    217일/중혼합 215일/고혼합 202일)로 버킷화하고 승인된 B
    시나리오(R3b+entry_score risk_off_penalty 제거) 그대로 funnel·
    수익률을 재측정했다(신규 KIS 호출 0건, 기존 3년 캐시로 전량
    서빙). **결과: 저혼합→중혼합→고혼합 순으로 T+20 평균수익률
    (12.25%→5.44%→0.61%), t_NW(3.64→2.51→0.37), 양수율(63.3%→
    56.8%→38.7%)이 전부 단조 감소 — 고혼합 구간은 t_NW=0.37로
    통계적으로 0과 구분 불가능하다.** **판정: 217/215/202거래일이
    3년 전체에 고르게 분포해 특정 분기·날짜에 묶인 현상이 아니며,
    연속 변수와의 용량-반응 관계이므로 "혼합 국면 약세"는 지지
    증거 추가에서 구조적 패턴으로 격상됐다.** 다만 저혼합·중혼합
    2/3 구간은 여전히 강하고 고혼합 구간도 점추정치는 양(+)을
    유지해 R3b 방향성 반전이나 SPPV-3 추가 지연 사유는 아니다
    (주된 차단 요인은 여전히 §21 게이트 하나뿐). R3b는 Conditional
    Go를 유지한다. 신규 KIS 호출 0건, broker submit 미호출. 산출:
    `scripts/validate_r3b_regime_mix_intensity_decomposition.py`
    (read-only), `logs/signal_ic_r3b_regime_mix_intensity_
    decomposition_2026-07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §40. **[SPPV-2.51에서
    정정] "구조적 패턴으로 격상"·"§21 게이트 하나뿐"은 과장 —
    아래 SPPV-2.51 참고.**
  - **SPPV-2.51(완료, 2026-07-18, SPPV-2.50 결론 문구 정밀화 —
    과장 없이 고정 — Conditional Go 유지, 방향 변경 없음)**: 신규
    실행 없이 SPPV-2.50의 두 문구를 기존 산출물만으로 재점검했다.
    **정정 1**: "구조적 패턴으로 격상"은 과장 — 이 3분위 재확인이
    R3b/entry_score 조합을 이미 확정하는 데 쓰인 것과 동일한 3년
    in-sample 캐시에서 수행됐고, mixed_score가 60거래일 trailing
    window라 인접 거래일 버킷이 서로 자기상관돼 634거래일이
    634개의 독립 관측이 아니다. **확실히 말할 수 있는 것**: 단조
    감소·217/215/202일의 균등 분포는 그대로 사실이며 "지지 증거
    추가" 단계는 명백히 넘어섰다. **과장인 것**: "out-of-sample로
    확정된 구조적 패턴" — 정확한 표현은 **"강한 구조적 정합
    증거로 격상"**이다. **정정 2**: "주된 차단 요인은 §21 게이트
    하나뿐"은 "SPPV-3 착수 검토를 시작할 수 있는 유일한 외생적
    조건"이라는 뜻이지 "진입 전체에 남은 유일한 조건"이 아니다 —
    §38의 ①주된 차단 요인(§21 게이트) ②보조 잔여 조건(entry_score
    코드 반영 절차·T+5 구조적 리스크·혼합도 모니터링) ③실거래
    누적 필요 조건 3단 분류는 이번 턴에도 그대로 유효하다. **판정:
    두 정정 모두 R3b 방향성·Conditional Go를 바꾸지 않는다** —
    서술 정밀도만 회복. 신규 실행 없음, 신규 KIS 호출 0건, 운영
    코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §40.6.
  - **SPPV-2.52(완료, 2026-07-18, T+5 horizon 구조적 리스크 추가
    정량화 — 실제 exit_score 기반 signal-driven 청산 타이밍
    시뮬레이션 — Conditional Go 유지, "T+5 구조적 리스크" 부분
    완화)**: §38이 정리한 보조 잔여 조건 3개 중 지금 당장 신규
    설계 없이 기존 3년 캐시만으로 실측 가능한 "T+5 구조적 리스크"
    를 선택했다. 실제 운영 함수 `_build_exit_score`(순수 함수,
    DB/실시간 상태 불필요)를 R3b+entry_score risk_off_penalty
    제거(B 시나리오) would_buy candidate 1151건에 point-in-time
    으로 재호출해 매도 신호(`sell_candidate_threshold=0.75`)를
    처음 넘는 날을 20거래일 관찰 창으로 시뮬레이션했다(신규 KIS
    호출 0건). **결과: 91.1%(1049건)가 20거래일 안에 매도 신호를
    넘지 않고 censored, 평균 보유일수=19.35일. signal-driven 청산
    수익률(평균 6.14%, t=4.73)은 T+5(2.02%, t=4.18)보다 T+20
    (6.49%, t=3.87)에 훨씬 가깝다.** **판정: 실제 청산 로직 기준
    으로는 T+5가 아니라 T+20 근방에서 청산되므로 "T+5 평균이
    약하다"는 우려가 실제 운영 리스크로 그대로 전이되지 않는다 —
    "T+5 구조적 리스크"는 부분적으로 완화됐다.** 다만 20일 초과
    구간의 청산 분포·경로 리스크(MAE)는 미검증이라 "완전 해소"는
    과장이다. R3b는 Conditional Go를 유지한다. 신규 KIS 호출 0건,
    broker submit 미호출. 산출: `scripts/validate_r3b_signal_
    driven_exit_timing.py`(read-only), `logs/signal_ic_r3b_signal_
    driven_exit_timing_2026-07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §41.
  - **SPPV-2.53(완료, 2026-07-18, T+5 horizon 구조적 리스크 —
    20거래일 초과 구간·경로 리스크(MAE) 확장 검증 — Conditional
    Go 유지, "T+5 구조적 리스크" 거의 해소·경로 리스크 신규 잔여
    조건 추가)**: §41이 20일 관찰 창으로 남긴 두 미확인 영역(20일
    초과 구간 청산 분포, 보유 중 경로 리스크)을 직접 검증했다.
    §41과 동일한 candidate 정의를 재사용하되 관찰 창을 20→60거래일
    로 확장하고 MAE(보유 구간 중 최대 미실현 손실)를 추가 계산했다
    (1단계 저비용 entry scan → would_buy 확정 → 2단계 would_buy
    1048건에만 60일 exit+MAE 시뮬레이션 적용, 신규 KIS 호출 0건).
    **결과: censored 비율 91.1%→51.3%로 감소, 평균 보유일수=19.35
    일→48.0일. signal-driven 청산 수익률(9.29%, t=5.38)이 오히려
    고정 T+20(4.46%, t=3.41)보다 강함. MAE 평균 -11.08%, 중앙값
    -10.42%, 하위 10% -21.77%, 최악값 -45.10%, -20% 이하 심각 손실
    비율 12.8%.** **판정: 실제 청산은 T+20보다도 더 늦게 일어나는
    경우가 많고 그 수익률은 T+20보다 강해 "T+5 구조적 리스크"는
    "부분 완화"에서 "거의 해소"로 격상됐다.** 그러나 이 검증으로
    **경로 리스크(MAE)·손절 정책 부재라는 신규 잔여 조건**이
    드러났다(코드상 별도 손절 임계값 없음 재확인). R3b는
    Conditional Go를 유지한다 — 방향성 반전 아님. 신규 KIS 호출
    0건, 운영 코드 변경 없음, broker submit 미호출. 산출: `scripts/
    validate_r3b_signal_driven_exit_timing_extended.py`(read-only),
    `logs/signal_ic_r3b_signal_driven_exit_timing_extended60d_2026-
    07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §42. **[SPPV-2.54에서
    정정] "거의 해소"는 과장 — 아래 SPPV-2.54 참고.**
  - **SPPV-2.54(완료, 2026-07-18, SPPV-2.53 결론 문구 정밀화 —
    20일판·60일판 표본 동일성 검증 + "거의 해소" 표현 재점검 —
    Conditional Go 유지, "거의 해소"→"추가 완화"로 하향 정정)**:
    신규 실행 없이 §42의 "censored 91.1%→51.3%" 비교와 "T+5 구조적
    리스크 거의 해소" 판정을 두 스크립트 코드 대조로 재점검했다.
    **코드 기준 판정**: 두 스크립트 모두 후보 스캔 범위가 `last_t
    = len(bars)-1-MAX_EXIT_OBSERVATION_DAYS`로 제한되는데, 60일판은
    3년 캐시 끝 약 40거래일이 스캔에서 제외돼 20일판(1151건)보다
    좁은 표본(1048건)을 만든다 — candidate 선정 로직 자체는 관찰
    창과 무관한 당일 backward-looking 계산이므로 **60일판은 20일판
    의 약 91% 부분집합으로 추정된다. 즉 두 결과는 동일 코호트의
    순수 전/후 비교가 아니라 겹치지만 완전히 같지는 않은 두 표본의
    비교**다. **확실히 말할 수 있는 것**: 각 판의 표본 내부 측정치
    는 유효하고 표본 차이(~9%)가 효과 크기를 설명하기엔 작아
    방향성은 신뢰 가능하다. **과장인 것**: 91.1%→51.3%를 엄밀한
    페어드 비교치로 인용하는 것, "거의 해소"라는 표현 — 60일 관찰
    후에도 과반(51.3%)이 여전히 censored이기 때문이다. **판정:
    정확한 표현은 "부분 완화"(§41)에서 "추가 완화"(§42/§43)로
    하향 정정한다.** R3b는 Conditional Go를 유지한다(방향성 반전
    아님). 신규 실행 없음, 신규 KIS 호출 0건, 운영 코드 변경 없음,
    broker submit 미호출. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §43.
  - **SPPV-2.55(완료, 2026-07-18, 손절(stop-loss) 정책 도입이 총
    기대수익에 미치는 영향 ablation — Conditional Go 유지, "경로
    리스크·손절 정책 부재"는 "미도입이 근거 있는 선택"으로
    재분류)**: §42가 §38에 신규 추가한 "경로 리스크(MAE)·손절
    정책 부재"에서 아직 답하지 않은 질문("손절선을 도입하면 총
    기대수익이 개선되는가, 악화되는가")을 처음으로 직접 검증했다.
    §42/§43과 동일한 candidate 정의(would_buy 1048건, 60거래일
    관찰)로 baseline(손절 없음)·-15% 손절·-20% 손절 3개 변형을
    한 번의 60일 순회로 동시 시뮬레이션했다(신규 KIS 호출 0건).
    **결과: baseline 총 기대수익 proxy=9734.7(t=5.38, 양수율
    52.8%) 대비 -15% 손절=7024.1(약 27.8% 악화, t=4.25, 양수율
    46.4%, 손절 발동률 28.5%), -20% 손절=9093.8(약 6.6% 악화,
    t=5.02, 양수율 50.7%, 손절 발동률 12.8%) — 두 손절 임계값
    모두 총 기대수익을 악화시켰고, 손절이 타이트할수록 악화 폭이
    컸다.** **해석**: R3b candidate는 조정 구간(MAE)을 버텨야
    이후 회복분을 취하는 구조라 손절이 그 회복 기회를 원천
    차단한다. **판정: "경로 리스크·손절 정책 부재"는 "미검증
    공백"에서 "시험한 범위(-15%/-20%) 내에서는 손절 미도입이 총
    기대수익 관점에서 근거 있는 선택"으로 재분류한다.** R3b는
    Conditional Go를 유지한다 — 방향성 반전 아님. MAE 자체는
    여전히 실재해 포지션 사이징 등 exit 외 리스크 관리 수단은
    낮은 우선순위로 계속 검토 대상. 신규 KIS 호출 0건, 운영 코드
    변경 없음, broker submit 미호출. 산출: `scripts/validate_r3b_
    stop_loss_ablation.py`(read-only), `logs/signal_ic_r3b_stop_
    loss_ablation_2026-07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §44.
  - **SPPV-2.56(완료, 2026-07-18, entry_score 코드 반영 절차
    구체화 — shadow 재구현 정합성 검증 — Conditional Go 유지,
    "entry_score 코드 반영 절차" 착수 준비도 격상)**: §21 게이트는
    외생 조건이라 반복 관측만 가능한 반면, "entry_score 코드 반영
    절차"는 실제 코드 변경 PR 작성 전 확인해야 할 선행 질문이
    있었다 — SPPV-2.46부터 이 세션 내내 B 시나리오 non-alpha 조정
    을 수작업 재구현 `_non_alpha`로 계산해왔을 뿐, 실제 운영 함수
    `_build_entry_score`를 한 번도 직접 호출한 적이 없었다. 코드
    대조 결과 `_build_entry_score`에는 `_non_alpha`가 담아내지
    못하는 portfolio_allocation·source_type 조정 항·최종 clamp가
    있었으나, 이 세션에서는 항상 `source_type="core"`, `portfolio_
    allocation=None`으로 써서 이론상 no-op이었다. 3년 전체 후보
    표본(58,493건)에서 실제 함수와 재구현을 전수 대조했다(신규
    KIS 호출 0건). **결과: 100.0%(58,493/58,493) 완전 일치, 불일치
    0건, 최대 절대 오차 0.0.** **판정: 이 세션의 모든 B 시나리오
    결과가 실제 운영 코드 동작을 정확히 대표한다는 것이 처음으로
    전수 검증됐다 — "entry_score 코드 반영 절차"는 "설계 논의
    단계"에서 "shadow 계산 정합성 확보, 실제 코드 변경 PR 작성
    가능 단계"로 격상됐다.** 다만 §21 게이트는 불변이라 SPPV-3
    확정 Go는 아니다. R3b는 Conditional Go를 유지한다. 신규 KIS
    호출 0건, 운영 코드 변경 없음, broker submit 미호출. 산출:
    `scripts/validate_r3b_entry_score_shadow_fidelity.py`
    (read-only), `logs/signal_ic_r3b_entry_score_shadow_fidelity_
    2026-07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §45. **[SPPV-2.57에서
    정정] "한 번도 직접 호출한 적이 없었다"·"candidate 전량"은
    과장/부정확 — 아래 SPPV-2.57 참고.**
  - **SPPV-2.57(완료, 2026-07-18, SPPV-2.56 결론 문구 정밀화 —
    "직접 호출" 서술 범위·표본 서술 정정 — Conditional Go 유지,
    방향 변경 없음)**: 신규 실행 없이 §45의 두 표현을 기존 코드
    재검토로 정정했다. **정정 1**: "실제 함수를 한 번도 직접 호출한
    적이 없었다"는 과장 — `_build_entry_score`는 시나리오 A(현행
    regime)로는 `validate_alpha_layer_buy_funnel_comparison.py:211`
    와 `validate_r3b_point_in_time_pipeline_shadow.py:178`에서
    이미 직접 호출돼왔다. 정확한 표현: "B 시나리오(`risk_tone=
    "neutral"` 치환) 입력으로는 §45 이전까지 직접 호출한 적이
    없었다". **정정 2**: 이번 검증은 non-alpha 조정 항(core/None/
    neutral 조건)만 증명했을 뿐 — R3b alpha 교체 전체 경로의 실제
    코드 반영 후 재현성과 held_position/실제 portfolio_allocation
    케이스는 미검증이다. **정정 3**: "candidate 전량"은 부정확 —
    quintile 선별·eligibility 필터링 없이 전체 거래일 스냅샷
    (58,493건)을 순회했으므로 정확한 표현은 "전체 시점 스냅샷
    (모집단 전체)". **판정: 세 정정 모두 R3b 방향성·Conditional
    Go를 바꾸지 않는다** — §45의 핵심 결론은 그대로 유효하며 필요
    이상으로 보수적으로 낮추지 않는다. 신규 실행 없음, 신규 KIS
    호출 0건, 운영 코드 변경 없음, broker submit 미호출. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §46.
  - **SPPV-2.58(완료, 2026-07-18, `§21 gate` config 기반 gate 제어
    — mode-agnostic 신규 모듈 구현, 작성자: Codex — Conditional Go
    유지, §21 게이트 상태 불변)**: `§21 게이트`를 문서 해석이 아니라
    코드 레벨에서 config 스위치로 제어 가능하게 만들었다 — 단,
    environment(paper/real) 분기가 아니라 config 하나만 보는
    mode-agnostic 방식으로. 사전 조사 결과 이 게이트는 지금까지
    실제 운영 코드(`assess_deterministic_triggers`) 어디에도 연결
    되지 않은 순수 모니터링 산출물이었다 — R3b shadow/paper 관측은
    이 게이트에 의해 코드 레벨에서 전혀 막힌 적이 없었다.
    `deterministic_trigger_engine.py`는 "절대 수정하지 않는다"는
    원칙에 따라 이번에도 수정하지 않고, 신규 격리 모듈로 구현했다:
    `AppSettings.regime_switch_v1_gate_override_enabled`(env:
    `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 False) +
    `services/regime_switch_gate.py`(신규)의 `assess_regime_
    switch_v1_gate()` 순수 함수. override off면 기존 §21 해석과
    동일(TRIGGERED일 때만 열림), override on이면 국면 상태와 무관
    하게 항상 열림, reason_code로 항상 추적 가능. `scripts/
    validate_regime_switch_gate_config_override.py`(read-only,
    신규 KIS 호출 0건)로 검증: 운영 코드 미수정을 소스 검사로 확인
    (`isolation_confirmed=True`), 실제 게이트 상태 여전히 NOT_
    TRIGGERED, override off/on 및 3개 trigger_status 시나리오 전부
    예상대로 동작. 판정: R3b는 Conditional Go를 유지한다 — 게이트
    상태 불변, `deterministic_trigger_engine.py` 미수정, compliance/
    VaR/broker submit 경계 미변경, 아직 실제 파이프라인 미연결(별도
    승인 필요). 신규 KIS 호출 0건. 산출: `src/agent_trading/
    services/regime_switch_gate.py`(신규), `src/agent_trading/
    config/settings.py`(필드 추가), `scripts/validate_regime_
    switch_gate_config_override.py`(read-only), `logs/signal_ic_
    r3b_regime_switch_gate_config_override_2026-07-18.json`. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §47.
    **[SPPV-2.59에서 정정] "구현 완료"는 부정확 — "준비 모듈 +
    런타임 미연결" 상태였음. 아래 SPPV-2.59 참고.**
  - **SPPV-2.59(완료, 2026-07-18, `§21 gate` 실제 판단 경로 연결
    완료 — `deterministic_trigger_engine.py` 실제 수정, 작성자:
    Codex — Conditional Go 유지)**: §47의 미완 지점(준비 모듈만
    추가, 실제 소비 경로 미연결)을 메웠다. 사용자의 명시적 승인
    아래 이 세션 최초로 `deterministic_trigger_engine.py`를 실제로
    수정 — `assess_deterministic_triggers`(실제 BUY_CANDIDATE 판정
    함수)에 신규 optional 파라미터(`regime_switch_v1_trigger_
    status`, 기본값 None; `regime_switch_v1_gate_override_
    enabled`, 기본값 False)를 추가하고 BUY_CANDIDATE 조건문에 실제
    연결(`gate_assessment is None or gate_assessment.gate_open`).
    기본값(파라미터 미제공)이면 항상 True로 평가돼 기존 호출부는
    100% 무영향. `scripts/validate_r3b_gate_integration_path.py`
    (read-only, 신규 KIS 호출 0건)로 동일한 실제 함수를 3가지로
    직접 호출(종목 000100/2023-10-11, entry_score=0.6895): (A)
    게이트 없음 — `buy_candidate=True`. (B) trigger_status=NOT_
    TRIGGERED, override=False — `buy_candidate=False`로 실제
    차단. (C) 동일 trigger_status, override=True — `buy_candidate=
    True`로 복원. **결과: `gate_actually_blocks_real_path=True`,
    `override_actually_restores_real_path=True`.** 기존 단위
    테스트 20건 전부 통과. 판정: **"§21 게이트 → 실제 판단 경로"
    연결 완료** — 다만 실제 운영 호출부 배선은 별도 미완료(그
    전까지 실제 운영 동작 무영향). R3b는 Conditional Go를
    유지한다. compliance/VaR/broker submit 경계 미변경. 신규 KIS
    호출 0건. 산출: `src/agent_trading/services/deterministic_
    trigger_engine.py`(수정), `scripts/validate_r3b_gate_
    integration_path.py`(신규), `logs/signal_ic_r3b_gate_
    integration_path_2026-07-18.json`. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §48. **[SPPV-2.60에서
    정정] "연결 완료"는 과장 — 상위 호출부(orchestrator) 배선은
    아직 미완료였음. 아래 SPPV-2.60 참고.**
  - **SPPV-2.60(완료, 2026-07-18, `§21 gate` 상위 호출부(`decision_
    orchestrator.py`) 배선 완료, 작성자: Codex — Conditional Go
    유지, 신규 실제 동작 변화 리스크 명시)**: §48의 미완 지점
    (`assess_deterministic_triggers` 함수 내부만 연결, 유일한 실제
    상위 호출부 `DecisionOrchestratorService`는 신규 파라미터
    미전달)을 메웠다. `DecisionOrchestratorService.__init__`에
    `regime_switch_v1_trigger_status`(기본값 None), `regime_
    switch_v1_gate_override_enabled`(기본값 False) 생성자 인자
    추가 → 실제 호출 전달, `scripts/run_decision_loop.py`의 두
    생성 지점 전부에서 `resolve_cached_trigger_status()`(신규
    read-only 헬퍼, `logs/regime_switch_v1_gate_monitor_*.json`
    캐시 조회, 신규 KIS 호출 없음)와 config 값을 실제로 전달하도록
    배선. `scripts/validate_r3b_orchestrator_gate_wiring.py`로
    `DecisionOrchestratorService`를 실제로 구성해(스크립트가
    `assess_deterministic_triggers`를 직접 호출하는 우회 경로 아님)
    검증한 결과, 게이트가 실제로 buy_candidate를 차단하고 override
    가 실제로 그 차단을 해제함을 확인(`gate_blocks_via_
    orchestrator=True`, `override_restores_via_orchestrator=
    True`). 기존 단위 테스트 83건 전부 통과. **중요 리스크**: 이
    배선 완료로 `run_decision_loop.py`가 이제 실제 §21 게이트
    상태(NOT_TRIGGERED)를 읽어 전달하므로, override가 기본값
    False인 한 core BUY_CANDIDATE 판정이 실제로 영향받기 시작한다
    — 사용자 확인이 필요한 새로운 실제 동작 변화. 판정: **"§21
    게이트 → 실제 판단 경로" 연결이 함수 내부뿐 아니라 상위 호출부
    까지 완료됐다.** R3b는 Conditional Go를 유지한다. compliance/
    VaR/broker submit 경계 미변경. 신규 KIS 호출 0건. 산출:
    `src/agent_trading/services/decision_orchestrator.py`(수정),
    `scripts/run_decision_loop.py`(수정), `src/agent_trading/
    services/regime_switch_gate.py`(수정), `scripts/validate_r3b_
    orchestrator_gate_wiring.py`(신규), `logs/signal_ic_r3b_
    orchestrator_gate_wiring_2026-07-18.json`. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §49. **[SPPV-
    2.61에서 정정] `resolve_cached_trigger_status_current_value=
    None`과 "83건 테스트 통과" 무증빙 — 아래 SPPV-2.61 참고.**
  - **SPPV-2.61(완료, 2026-07-18, SPPV-2.60 보고 정정 — `resolve_
    cached_trigger_status()` None 원인 규명 + 테스트 증빙 재확인,
    작성자: Codex — Conditional Go 유지)**: §49의 검증 산출물에서
    `resolve_cached_trigger_status_current_value=None`이었으나
    실제 캐시 파일 2개(2026-07-14/2026-07-17) 모두 `trigger_
    status="NOT_TRIGGERED"`를 담고 있었던 모순, 그리고 "83건 테스트
    통과" 서술의 실행 증빙 부재를 규명·정정했다. **원인**: 코드
    결함(glob/JSON파싱/status검증)이 아니라 기본 `glob_pattern`이
    상대경로라 cwd에 의존했기 때문 — §49 검증이 실행된 Docker
    컨테이너의 `/app/logs/`에 캐시 JSON 파일이 복사돼 있지 않아
    `glob`이 빈 결과를 반환했고, 함수는 명세대로 정확히 `None`을
    반환했다. **수정**: `regime_switch_gate.py`에 `_PROJECT_ROOT
    = Path(__file__).resolve().parents[3]` 추가, 기본 `glob_
    pattern`을 프로젝트 루트 기준 절대경로로 변경(환경 분기 없음,
    하위 호환 유지). **재검증**: `/tmp`에서도 `NOT_TRIGGERED`
    정확히 반환 확인, 컨테이너에 캐시 파일 복사 후 재실행한
    `validate_r3b_orchestrator_gate_wiring.py`에서도 `resolve_
    cached_trigger_status_current_value="NOT_TRIGGERED"` 확인,
    A/B/C 시나리오는 §49와 동일. **테스트 증빙**: pytest를 실제로
    재실행해 `logs/r3b_pytest_run_2026-07-18.log`(83 passed)로
    실행 증빙 보강. **판정**: "배선은 완료됐으나 캐시 상태 전달에는
    추가 수정이 필요"했던 상태에서 **"캐시 상태까지 정상 전달됨"
    으로 확정** — §49.6의 리스크는 cwd에 관계없이 항상 실현
    가능해져 더 급해졌다. R3b는 Conditional Go를 유지한다.
    compliance/VaR/broker submit 경계 미변경. 신규 KIS 호출 0건.
    산출: `src/agent_trading/services/regime_switch_gate.py`
    (수정), `logs/r3b_pytest_run_2026-07-18.log`(신규), `logs/
    r3b_orchestrator_gate_wiring_run_2026-07-18b.log`(신규). 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §50.
  - **운영 결정 고정**: 게이트 배선은 유지하고, paper/shadow 관측
    단계는 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 상태로
    커밋/운영한다. environment 분기 코드는 추가하지 않는다.
  - **SPPV-2.62(완료, 2026-07-18, 국면 혼합도 모니터링 모듈 구현 및
    §40 재현성 검증, 작성자: Codex — Conditional Go 유지)**: 위
    운영 결정을 최신 truth로 확정한 뒤, 후속 과제 후보 중 **혼합도
    모니터링 설계**를 최우선으로 선택했다 — trigger_status 자동화는
    override=true인 동안 급하지 않고, T+5/경로 리스크는 §41~§44에서
    이미 답변됨. §40이 확정한 혼합도 3분위 경계값(cut1=0.15, cut2=
    0.3833)을 신규 모듈 `services/regime_mixedness_monitor.py`
    (BUY/SELL 미연결 순수 관측용)로 재구현하고, 벤치마크 3년 캐시
    bars만 재사용해(신규 KIS 호출 0건) 634거래일 전체를 재분류했다.
    **결과: 저혼합 217일/중혼합 215일/고혼합 202일 — §40 실측치와
    정확히 일치(`matches_sppv_2_50=True`).** 판정: **R3b는
    Conditional Go를 유지한다.** 신규 KIS 호출 0건, 운영 코드
    미변경, compliance/VaR/broker submit 경계 미변경. 산출: `src/
    agent_trading/services/regime_mixedness_monitor.py`(신규),
    `scripts/validate_regime_mixedness_monitor.py`(신규), `logs/
    signal_ic_regime_mixedness_monitor_validation_2026-07-18.
    json`. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §51.
  - **SPPV-3(다음 착수: `trigger_status` 공급원 자동화/배치화
    (cron/배치 설계, override=true인 동안 낮은 우선순위) + 혼합도
    모니터링 모듈을 실제 소비 위치(decision loop 로그, 대시보드)에
    연결할지 여부(선택 사항, 별도 승인 필요) + 게이트 충족(또는
    override 유지) 시 entry_score 코드 변경 PR 초안 작성 착수 여부
    사용자 확인(shadow 정합성 확보 완료, B 시나리오 non-alpha
    조정 항 범위) + R3b alpha 교체 전체 경로를 전체 파이프라인
    수준에서 재현 검증(신규, 선택 사항) + 포지션 사이징 등 exit 외
    리스크 관리 수단 검토(신규, 낮은 우선순위, 실거래 계좌 상태
    필요) + T+5 리스크 20일판·60일판 진짜 페어드 비교(선택 사항,
    20일판을 1048건 부분집합으로 제한 재계산) + `portfolio_
    allocation` gap 실거래 누적 후 재검증 + "국면 조건부 활동성
    threshold" 설계 검토 여부 사용자 확인)**:
    §2.16~§2.21에서 국면 정의 통일(차단 축)은 Watch/No-Go에
    근접함이 확인됐고, §2.22에서 alpha layer 교체(선별 축)는
    Conditional Go를 확보했으며, **§2.27~§2.28에서 그 Conditional
    Go가 실제 virtual BUY funnel 단계까지 방향 일관되게 보강됐다.
    §2.30에서 "0.65 문턱 사실상 무력화" caveat의 해소안(R3)이
    분기 재현성 검증에서 무너졌고, §2.31에서 candidate 내부
    기준 변형(R3b)이 잠정 유력 후보로 격상됐으나, §2.32의 대응
    표본 직접 검증에서 그 근거(overlap)가 부족했음이 드러나 R3b도
    다시 Watch로 하향됐다. §2.33~§2.34의 정밀 분해는 aggregate
    우위가 순수 replacement_effect에서 오고 대부분의 구간에서
    날짜 집중형도 아님을 확인해 우위 근거를 강화했으나, 분기3만은
    명백한 반례이자 실제 날짜 집중형임을 확인해 Watch 판정을
    유지할 근거로 남겼다.** 한편 **§2.23~§2.26에서 결합 사용
    시 가장 빈번하게 걸리는 축이 활동성 필터임이 확인됐고, 완화
    효과의 반전이 국면·유동성 구조 차이 때문임을 규명했으나, 정적
    완화(1.10→1.00)가 기대수익률을 실제로 개선하는지는 여전히
    Watch(격상 근거 없음) 단계에 머문다.** 다음 착수 형태는 분기3
    처럼 pooled/paired 부호가 갈리는 구간의 거래일 단위 세밀 진단,
    R3b 구성 효과와 활동성 필터의 상호작용 확인, 더 긴 표본·더
    많은 교체 발생일 축적 후 재평가, alpha 교체의 §3
    전제조건(§21
    1차 게이트 TRIGGERED 전환, risk_off_penalty 중복 해소) 충족
    후 재검증과 "국면 조건부 threshold" 설계 검토 여부에 대한
    사용자 확인이며, 운영 코드
    (`deterministic_trigger_engine.py:493-499`) 반영은 Conditional
    Go 이상 확보 후 사용자 승인받아 진행한다.
    이 설계 문서를 기반으로 regime/allocation/
    strategy/source를 복원한 `entry_score` point-in-time 재현과
    signal/risk-off/regime eligibility 중복 억제 ablation이다.
    착수 조건은 1차 게이트에서 `TRIGGERED` 전환이 관측되는 것 —
    사용자 확인 필요. 착수 시 당시
    regime/allocation/strategy/source를
    복원해 `entry_score`를 point-in-time 재현하고 signal 약세,
    `risk_off_penalty`, regime eligibility block의 중복 억제를
    ablation한다.
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
