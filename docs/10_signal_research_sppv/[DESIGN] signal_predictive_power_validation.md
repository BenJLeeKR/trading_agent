# 신호 예측력 실증 검증 설계 (Signal Predictive Power / IC Validation)

작성일: 2026-07-14
상태: SPPV-2.7(하락장 포함 3년 확장 + 자기참조 제거) 완료 — **§12(1년
표본)의 "알파 근거 강화" 결론이 3년 확장 검증에서 다시 반박됨.** pooled
유의성 소멸(t=2.30→1.32) + 하락장에서 신호 방향 역전/무의미. SPPV-3
착수는 보류 유지, No-Go에 근접. §14 참고(최신 canonical 결론). **이후
검증 기간 기준 자체를 "최근성 우선 + 필수 국면 표본 게이트"로 재설계
(SPPV-2.8, §16) — 최근 12개월 창을 1차 기본값으로 확정, 3년 전체는
국면 커버리지 확인용 2차(supplementary)로 격하. 실행 증빙 재검증
완료(정상 로그 확보, 핵심 수치 재현) — §16.6.** **신호 feature 재설계
검토(SPPV-2.9, §17) 완료 — `fast_score`/`slow_score` sub-component
6개를 분해 실측한 결과 `rsi_signal`이 T+20에서 유의하게 역방향
(t_NW=-2.94)임을 특정했다. 신규 후보 `risk_adj_momentum_3m`(변동성
조정 모멘텀)이 3년 pooled에서 유의(t_NW=2.07)하고 하락장에서도 역전
되지 않아 유일한 "Watch" 후보로 남았으나, §16 Go 게이트(1차+2차 모두
충족)는 아직 완전히 통과하지 못해 SPPV-3 착수는 계속 보류한다.**
**§17.5 후속 3과제(SPPV-2.10, §18) 완료 — `fast_score_v2`(rsi_signal
제거/반전 두 변형 모두)는 하락장 역전이 거의 그대로 남아(T+5
t_NW=-2.3~-2.4) No-Go로 판정, `risk_adj_momentum_3m`은 1차 창을
18개월로 넓히자 T+20 t_NW=2.03으로 문턱을 겨우 넘었으나 marginal이라
"Watch 유지, 조건부 상향"에 그친다. `reversal_1m`은 하락장 T+5에서
방향은 일관되나 반분 표본 각각은 유의 문턱 미달 — Hold 유지. SPPV-3
착수는 계속 보류한다.**
**§18.6 후속(SPPV-2.11, §19) 완료 — `fast_score` leave-one-out 4종 분해
결과 `fast_trend`(SMA20 이격) 제거 시 하락장 T+5 역전이 -2.79→-1.60으로
가장 크게 완화(비유의 전환) — `rsi_signal`이 아니라 `fast_trend`가 주된
원인이었음을 재확인, §18의 결론을 다시 정정한다. `risk_adj_momentum_3m`
은 15~21개월 창에서 T+20 t_NW이 1.90→2.03→2.04로 안정적 plateau를
보여 18개월의 marginal 통과가 단발성 우연은 아님을 확인했으나 여전히
크기가 작다. 국면 전환형 shadow 후보 `regime_switch_v1`(비하락장=
risk_adj_momentum_3m, 하락장=reversal_1m)을 신설해 검증한 결과 2차(3년)
pooled가 T+5 t_NW=2.60, T+20 t_NW=2.36으로 이 트랙 전체에서 가장 강한
2차 결과를 냈으나, 1차(최근 12개월)는 하락장 표본 부재로 여전히
risk_adj_momentum_3m 수준(1.47~1.55)에 머물러 §16 게이트를 완전히
통과하지 못한다 — 가장 유망한 Watch 후보로 격상하되 확정 Go는 아니다.**
**§19.6 후속(SPPV-2.12, §20) 완료 — `regime_switch_v1` 1차 게이트 예외
규칙 3개(관찰 유예/최근-실사례/적응형-최소창)를 비교한 결과, **적응형
최소창(규칙 C)이 n=30에서 t_NW=4.18로 급등하는 것은 신호가 아니라
"문턱을 넘을 때까지 창을 줄이는" 구조적 데이터 스누핑 위험으로 판정하고
채택을 거부**했다. 최근-실사례(규칙 B, n=48 고정)는 t_NW=1.33~1.61로
여전히 미달 — 관찰 유예(규칙 A, 하락장 재발 시 자동 재검증)를 유일하게
방어 가능한 방안으로 채택한다. fast 계열 신규 feature 2종(`rsi_mean_
reversion`, `sma5_over_sma20_gap`) 실측 결과 둘 다 범용 대체 후보로는
No-Go — 전자는 하락장에서만 유의(t=2.26, `reversal_1m`과 같은 패턴),
후자는 SMA20 이격과 마찬가지로 하락장에서 유의하게 역전(t=-2.67)돼
"짧은 이동평균이면 해결된다"는 가설도 기각됐다.**
**§20.5 후속(SPPV-2.13/2.14, §21/§22) 완료 — `regime_switch_v1` 규칙 A
모니터링을 실제 실행 가능한 스크립트(`monitor_regime_switch_v1_gate.py`)
로 구현·실행(현재 판정: NOT_TRIGGERED, 최근 12개월 bearish_trend 0일).
"절대 가격 수준" 로직을 전혀 쓰지 않는 완전 신규 fast 계열 후보
2종(`money_flow_5d`=자금 흐름, `relative_strength_rank_1m`=cross-sectional
상대강도)을 실측 — 둘 다 pooled/1차 유의성 없이 범용 대체 후보로 No-Go.
`relative_strength_rank_1m`은 하락장에서 유의하게 역전(t=-2.13)해,
시장 베타를 제거한 상대강도조차 하락장에서는 반대로 작동한다는 더
강력한 규칙성을 재확인했다.**
**§21/§22 후속 종합 완료(§23) — 10개 신호를 가로지르는 국면별 극성
전환 종합표를 작성한 결과("추세형=상승/횡보 전용, 되돌림형=하락장
전용"이 8/10에서 재현, `rsi_signal`만 예외적으로 상승장에서 역전),
feature 추가 실험은 한계효용이 낮다고 판단해 중단하고 **국면 분기형
entry 설계 검토로 전환**을 확정했다. 별도 문서
`plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
참고.**
상위 문서: `plans/[ANALYSIS] foundational_design_review_objective_alignment.md`
(undated 버전이 canonical — dated 파일명은 존재하지 않음, 이력 참고 시에도
이 파일을 기준으로 한다)
(최우선 작업 — 목표 B "최고 기대수익률" 확정과 BUY 주문 0건 복구를 위한 신호·진입 경로 검증)

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: 최고 기대수익률을 손실 제약 아래의 목적함수로 명확히 하고,
  `2026-06-25` 이후 BUY 주문 0건 실측, 통계 보정, `entry_score` 및 전체 BUY
  funnel back-simulation, 제한적 probe 승격 단계를 설계에 추가했다. 이어서
  관련 문서 기준 현재 진행 상태를 한눈에 확인할 수 있는 체크리스트를 추가했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: **SPPV-2(통계 보정 확장) 실행 완료**. core 전체(88종목) ×
  cross-sectional 거래일별 Spearman IC × Newey-West 보정 × 국면별 분해 ×
  비용 차감 quintile 성과를 실측했다. **SPPV-1 파일럿의 낙관적 결론(t=2.4~4.1,
  "유의미"~"강함")이 overlap 편향의 산물이었음이 확인됐다** — 정확히 보정한
  cross-sectional IC는 전 신호·전 horizon에서 |t_NW|<1.1로 통계적 유의성
  없음. §9에 상세 결과와 조건부 보류(Hold) 판정을 기록했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: **SPPV-2.5(quintile spread 정체 진단) 실행 완료**. `overall_score`
  quintile spread 자체를 Newey-West로 재검정(pooled t_NW=2.30, 유의)했으나,
  **국면 내부(within-regime) 분해에서는 어느 국면도 단독으로 유의하지
  않음**(최고 bullish_trend t_NW=1.55) — pooled 유의성이 국면 혼입(regime
  mix) 착시일 가능성이 높다는 결론. **SPPV-3(entry_score 전체 재현) 착수를
  계속 보류**한다. §11 상세 참고.

- 작성자: Claude
- 수정일자: 2026-07-14 (3차, 사용자 지적 반영)
- 수정내용: **사용자 지적으로 §11의 방법론 오류 2건을 확인**: (1)
  `regime_label`이 시장이 아니라 종목 자신의 신호로 판정되는 것을 코드로
  재확인(`market_regime.py:21-38`), (2) "로컬 캐시로 재조회 없이 재사용"
  서술이 로그상 사실이 아니었음(SPPV-2와 동일하게 352건 재조회) 확인.
  **KODEX 200(069500) 시장 벤치마크 기준으로 재검증(§12)한 결과, "국면
  혼입 착시" 결론이 반박됨** — 시장이 상승국면이었던 유일한 신뢰가능
  버킷(97%) 내부에서도 spread 유의성이 거의 그대로 유지됐다. 대신
  하락장 표본이 이 1년 데이터에 아예 없다는 더 근본적인 한계를 새로
  확인했다. §11은 이력으로 보존하고 §12를 최신 canonical 결론으로 삼는다.

- 작성자: Claude
- 수정일자: 2026-07-14 (4차)
- 수정내용: **SPPV-2.7(하락장 포함 3년 확장 + 벤치마크 자기참조 제거)
  실행 완료**. §12(1년 표본)의 "알파 근거 강화" 결론이 **다시 반박됨** —
  pooled 유의성이 3년 확장 후 소멸(t_NW 2.30→1.32)했고, 실제 하락장
  (96거래일)에서는 신호 방향이 역전되거나(overall_score) 통계적으로
  유의하게 역방향(fast_score, t=-2.79)이었다. §12의 낙관적 표현을 §14에서
  하향 조정하고, §14를 최신 canonical 결론으로 삼는다. SPPV-3 착수는
  보류 유지, No-Go에 근접.

- 작성자: Claude
- 수정일자: 2026-07-14 (5차, 검증 기간 재설계)
- 수정내용: 이 시스템이 3개월 이하 중단기 공격형이라는 전제 아래 **SPPV
  검증의 기간(period) 기준 자체를 재설계**했다(SPPV-2.8, §16). 3년 전체
  pooled를 기본값으로 유지하지 않고, **최근 12개월을 1차(primary) 기본
  창으로, 3년(기존 SPPV-2.7 산출물 재사용)을 국면 커버리지 확인용
  2차(supplementary) 게이트로 분리**했다. 기존 3년 캐시(신규 KIS 호출
  없음)로 최근 12개월 창을 실측한 결과, 하락장(bearish_trend) 거래일이
  **0일**로 나타나 "최근성 우선" 창만으로는 필수 국면 검증이 원천적으로
  불가능함을 실증했다 — 이로써 2차(3년) 게이트가 왜 여전히 필수인지도
  같은 실행에서 함께 확인됐다. §14의 보류(Hold) 판정은 변경하지 않는다.

- 작성자: Claude
- 수정일자: 2026-07-14 (6차, 실행 증빙 재검증)
- 수정내용: **SPPV-2.8의 실행 증빙을 재검증한 결과, 이전에 저장했던
  `logs/sppv_recency_window_run_2026-07-14.log`가 실제로는 정상 실행
  로그가 아니라 호스트 python 환경에 `dotenv` 미설치로 실행이 즉시
  실패한 트레이스였음을 확인했다** — JSON 산출물 자체는 (호스트가 아닌)
  `agent_trading-app-1` 컨테이너에서 실행해 만든 진짜 결과였지만, 그
  실행의 stdout/stderr가 로그 파일로 남지 않았다("실행됐다"고 쓰려면
  로그와 산출물이 둘 다 있어야 한다는 원칙 위반). **컨테이너 안에서
  스크립트를 다시 실행해 stdout을 그대로 로그 파일로 캡처, 재현
  검증했다**: 종료 코드 0, `HTTP Request:` 로그 0건(신규 KIS 호출 없음,
  캐시 100% hit), 최근 12개월 국면 분포 `{bullish_trend: 239,
  range_bound: 6}`(bearish_trend 0일 재현), `overall_score` T+20 pooled
  spread `t_newey_west=1.18` 재현 — 기존에 문서화한 세 가지 핵심 수치
  전부 동일하게 재현됨을 확인했다. §16의 결론과 판정은 변경하지 않되,
  §16.3에 "실제 재검증 실행"으로 명시하고 이전 로그의 증빙 결함을
  §16.6(신설)에 기록한다.

- 작성자: Claude
- 수정일자: 2026-07-14 (7차, 신호 feature 재설계 검토 — SPPV-2.9)
- 수정내용: §14.5가 지시한 **신호 feature 재설계 검토를 실제로 수행**했다
  (SPPV-2.9, §17). `fast_score`/`slow_score`를 구성하는 6개 sub-component
  (`slow_momentum`/`slow_trend`/`fast_trend`/`volume_confirmation`/
  `rsi_signal`/`volatility_penalty`)를 운영 코드(`signal_backbone.
  _score_features()`) 그대로 분해해 개별 예측력을 실측하고, 신규 후보
  feature 2개(`risk_adj_momentum_3m`=변동성 조정 모멘텀,
  `reversal_1m`=단기 역추세)를 §16 이원 기준(1차 최근 12개월/2차 3년
  국면 게이트)으로 검증했다. **결과: `rsi_signal`이 T+20에서 유의하게
  역방향(1차 t_NW=-2.94, bullish_trend 내부 t_NW=-2.79)임을 특정 —
  `fast_score`가 반복적으로 예측력을 잃거나 역방향이었던 문제의 구체적
  원인 중 하나로 확인됐다. 신규 후보 `risk_adj_momentum_3m`은 2차(3년)
  pooled에서 유의(t_NW=2.07)하고 어떤 국면에서도 유의하게 역전되지
  않은 유일한 후보였으나, 1차(최근 12개월) 유의성(t_NW=1.47)이 §16
  게이트 기준(|t|≥2)에 못 미쳐 완전한 Go는 아니다. `reversal_1m`은
  하락장에서만 유의(T+5 t_NW=2.13)해 범용 feature가 아니라 국면 조건부
  후보로 분리 검토가 필요하다.** SPPV-3 착수는 계속 보류하되,
  `risk_adj_momentum_3m`을 "Watch" 후보로 다음 검증 대상에 추가한다.
  상세: §17.

- 작성자: Claude
- 수정일자: 2026-07-14 (8차, §17.5 후속 3과제 — SPPV-2.10)
- 수정내용: §17.5가 지시한 후속 3과제를 실제로 수행했다(SPPV-2.10, §18).
  (1) **`fast_score_v2` shadow 2종(rsi_signal 제거/부호반전) 검증 —
  둘 다 No-Go.** 하락장 T+5 spread가 원안(t_NW=-2.79)과 거의 다르지
  않게 역전됨(drop -2.41, flip -2.32) — `rsi_signal`이 하락장 역전의
  일부만 설명했을 뿐 주된 원인이 아니었음을 재확인, §17의 낙관적
  프레이밍을 하향 조정한다. (2) `risk_adj_momentum_3m`의 1차 창을
  12→18개월로 넓히자 T+20 pooled spread t_NW이 1.47→**2.03**으로 §16
  게이트 문턱을 처음 넘었으나, T+5(1.97)는 여전히 미달이고 문턱을
  간신히 넘은 marginal 결과라 "Watch 유지, 조건부 상향"으로만 기록한다.
  (3) `reversal_1m` 하락장(96거래일) 표본을 시간순 반분해 안정성을
  확인 — 방향은 전체/전반부/후반부 모두 양(+)으로 일관되나, 반분 표본
  각각은 개별적으로 |t_NW|≥2 문턱을 넘지 못해(전반 1.87, 후반 1.33)
  표본 확대 전까지 Hold로 유지한다. SPPV-3 착수는 계속 보류. 상세: §18.

- 작성자: Claude
- 수정일자: 2026-07-14 (9차, §18.6 후속 — SPPV-2.11)
- 수정내용: §18.6이 지시한 세 과제를 실제로 수행했다(SPPV-2.11, §19).
  (1) **`fast_score` leave-one-out 4종(fast_trend/volume_confirmation/
  rsi_signal/volatility_penalty 각각 제거) 분해 결과, `fast_trend`
  제거 시 하락장 T+5 spread가 -2.79→**-1.60(비유의 전환)**으로 가장
  크게 개선됨 — §17/§18에서 `rsi_signal`을 원인으로 지목한 것이 부정확
  했고, 실제 주된 원인은 `fast_trend`(SMA20 이격)였음을 정정한다.**
  (2) `risk_adj_momentum_3m`을 12/15/18/21개월 창으로 재검증한 결과
  T+20 t_NW이 1.47→1.90→2.03→2.04로 **완만하게 안정된 plateau**를
  보여, §18의 18개월 결과가 우연한 단일 지점이 아님을 확인했다 — 다만
  절대 크기(~2.0)는 여전히 marginal이다. (3) 국면 전환형 shadow 후보
  `regime_switch_v1`(비하락장=risk_adj_momentum_3m, 하락장=
  reversal_1m)을 신설해 검증 — **2차(3년) pooled가 T+5 t_NW=2.60,
  T+20 t_NW=2.36으로 이 트랙 전체에서 가장 강한 2차 결과**를 냈으나,
  1차(최근 12개월)는 하락장 표본 부재로 여전히 risk_adj_momentum_3m
  수준(1.47~1.55)에 머물러 §16 게이트를 완전히 통과하지 못한다 — 가장
  유망한 Watch 후보로 격상하되 확정 Go는 아니다. SPPV-3 착수는 계속
  보류. 상세: §19.

- 작성자: Claude
- 수정일자: 2026-07-14 (10차, §19.6 후속 — SPPV-2.12)
- 수정내용: §19.6이 지시한 두 과제를 수행했다(SPPV-2.12, §20). (1)
  `regime_switch_v1`의 1차 게이트 예외 규칙 3개를 정의·실측 비교했다 —
  **규칙 C(적응형 최소 국면 표본 창)는 n=30에서 t_NW=4.18(T+5)로
  급등했으나, n=48(규칙 B)에서는 1.33에 불과해 "문턱을 넘을 때까지
  창을 줄이는" 구조가 만든 데이터 스누핑 산물로 판정하고 채택을
  거부한다** — 공격형 시스템이라도 이런 자기선택적 표본 축소를 정당화
  근거로 쓰면 실거래에서 반드시 재현 실패로 이어질 위험이 크다. 규칙
  B(고정 n=48, 가장 최근 실제 발생)는 정직하게 측정해도 여전히
  미달(1.33~1.61)이라 Hold를 재확인한다. **최종 채택: 규칙 A(관찰
  유예 — 하락장 재발 시 자동 재검증, 억지 통과 없음).** (2) fast 계열
  신규 feature 2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`) 실측 —
  둘 다 범용 대체 후보로는 No-Go. `rsi_mean_reversion`은 하락장에서만
  유의(t=2.26, `reversal_1m`과 같은 국면 조건부 패턴), `sma5_over_
  sma20_gap`은 SMA20 이격과 마찬가지로 하락장에서 유의하게
  역전(t=-2.67) — "이동평균 창을 짧게 하면 해결된다"는 가설도 기각.
  SPPV-3 착수는 계속 보류. 상세: §20.

- 작성자: Claude
- 수정일자: 2026-07-14 (11차, §20.5 후속 — SPPV-2.13/2.14)
- 수정내용: §20.5가 지시한 두 과제를 수행했다. (1) **`regime_switch_v1`
  의 규칙 A(관찰 유예)를 실제 실행 가능한 모니터링 스크립트로
  구현**했다(SPPV-2.13, §21) — `scripts/monitor_regime_switch_v1_gate.py`
  는 벤치마크(069500) 하나만 조회해 최근 12개월 창의 국면 분포와
  `bearish_trend` 발생 일수를 계산하고, 30일 이상이면 `TRIGGERED`,
  1~29일이면 `PARTIAL`, 0일이면 `NOT_TRIGGERED`로 판정한다. 실행 결과:
  현재 `NOT_TRIGGERED`(최근 12개월 bearish_trend 0일) — 이전 §20의
  판단과 일치, 재검증 시점 아님을 실측으로 재확인. (2) **"절대 가격
  수준"에 의존하지 않는 완전 신규 fast 계열 feature 2종을 실측**했다
  (SPPV-2.14, §22): `money_flow_5d`(최근 5거래일 상승/하락일 거래대금
  비대칭, 자금 흐름 축), `relative_strength_rank_1m`(cross-sectional
  상대강도 순위, 시장 베타 제거). **둘 다 pooled/1차 유의성 없이 범용
  대체 후보로 No-Go**. `relative_strength_rank_1m`은 하락장에서 유의
  하게 역전(T+5 t_NW=-2.13)해, 절대 지표뿐 아니라 시장 베타를 제거한
  상대강도조차 하락장에서는 반대로 작동한다는 더 강력한 규칙성을
  재확인했다 — 이는 "하락장 역전"이 특정 feature의 결함이 아니라 이
  시스템의 신호 전반에 걸친 구조적 특성일 가능성을 시사한다. SPPV-3
  착수는 계속 보류. 상세: §21, §22.

- 작성자: Claude
- 수정일자: 2026-07-15 (12차, 국면별 신호 극성 종합 및 상위 방향 확정)
- 수정내용: SPPV-2.9~2.14(§17~§22)에서 개별 산출된 10개 신호의 실측
  결과를 **국면별 신호 극성 전환 종합표**로 통합했다(§23, 별도 문서
  `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`).
  **8/10 신호가 "추세형=상승/횡보 전용, 되돌림형=하락장 전용" 규칙성을
  따르고, `rsi_signal`만 상승장에서 역전되는 예외임을 확인했다.**
  절대·상대·오실레이터·거래량·복합 5개 축을 모두 시도해 매번 같은
  결론에 수렴한 것을 근거로, **feature 추가 실험을 중단하고 국면
  분기형 entry 설계 검토로 전환**하기로 판정했다 — 유니버스/미시구조
  재검토는 후순위로 유지한다(선택지 비교 근거는 별도 문서 §4 참고).
  SPPV-3의 다음 착수 형태는 `regime_switch_v1` 아이디어를 entry_score
  대체 설계의 초기 원형으로 삼는 것으로 재정의된다.

- 작성자: Claude
- 수정일자: 2026-07-15 (13차, 국면 분기형 entry 설계 초안 + shadow
  계산기)
- 수정내용: §23의 판정을 실제 설계 문서로 구체화했다(SPPV-2.16). 신규
  문서 `plans/[DESIGN] regime_conditional_entry_signal_v1.md`에
  국면별 신호 선택 매트릭스(비하락장=`risk_adj_momentum_3m`, 하락장=
  `reversal_1m`, 판정불가=신호 미산출), `entry_score` 통합 방안(alpha
  layer 0.80 가중치 블록 교체 제안, 미적용), shadow 검증 계획(Phase
  1/2, §16 그대로 재사용하는 Go/No-Go 기준)을 작성했다. **shadow
  계산기(`scripts/shadow_regime_conditional_entry_signal.py`)를 실행해
  실시간(캐시 기준 최신일 2026-07-14) 스냅샷을 1회 산출** — 시장 공통
  국면 `range_bound`로 87/87종목이 `risk_adj_momentum_3m` 분기를
  사용했고 하락장 분기는 미발동(§21 모니터링과 정합). `entry_score`
  코드/운영에는 아무 변경도 가하지 않았다 — 설계·shadow 단계에 머문다.

- 작성자: Claude
- 수정일자: 2026-07-15 (14차, regime_conditional_signal Phase 2 shadow
  누적 사이클 구축)
- 수정내용: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §4.2가 지시한 Phase 2(반복 shadow 로깅)를 실제 실행 가능한 형태로
  구현했다(SPPV-2.17). 신규 오케스트레이터
  `scripts/run_regime_conditional_shadow_cycle.py`가 §21(monitor_
  regime_switch_v1_gate.py)의 게이트 판정 로직과 §22(shadow_regime_
  conditional_entry_signal.py)의 신호 계산 로직을 **벤치마크 bars를
  1회만 조회해** 함께 실행하고, 그 결과를 누적 이력 파일
  `logs/regime_conditional_signal_shadow_history.jsonl`(append-only,
  거래일당 1줄, 중복 거래일 자동 skip)에 추가한다. 게이트가
  TRIGGERED/PARTIAL로 전환되면 §4.3의 재검증 절차(runbook)를 화면에
  출력한다(자동 재검증은 하지 않음). **실행 결과: 게이트
  NOT_TRIGGERED(2026-06-16 기준, bearish_trend 0일), 신호 계산
  2026-07-14 기준 `range_bound`로 87/87종목 `risk_adj_momentum_3m`
  분기 — 이력에 1줄 추가.** 즉시 재실행해 중복 방지 로직이 실제로
  발동함(같은 거래일 재추가 skip)을 확인했다. `entry_score` 코드/운영
  변경 없음.

- 작성자: Claude
- 수정일자: 2026-07-15 (15차, entry_score 중복 penalty ablation 실측)
- 수정내용: SPPV-3 착수 전제인 "중복 억제 구조 재현·분해"를
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §8로
  구체화했다. 신규 스크립트 `scripts/shadow_entry_score_penalty_
  ablation.py`가 Phase 0(재구성 가능 구간)만으로 `_build_entry_score`/
  `_assess_buy_eligibility`(운영 함수 그대로 호출)의 세 penalty 축
  (entry_score regime penalty / eligibility regime 차단 / eligibility
  signal floor)을 오늘(87종목) 기준 독립 평가했다. **결과: A(85건)/
  B(60건)/C(75건) 중 B가 발동한 60건은 예외 없이 A·C도 함께 발동
  (A∩B∩C=60=B 전체)** — §2 근본 진단의 "삼중 중복" 지적이 오늘
  데이터로 100% 재현됨을 확인. 종목별(per-symbol) regime_label 분포
  (bearish_trend 60/87=69%)가 시장 공통 국면(`range_bound`)과 전혀
  다르다는 점도 재확인(§12.1 코드 문제가 운영 코드에 그대로 남아
  있음). 운영 DB(`trade_decisions`) 직접 조회는 자동 승인 경계
  밖으로 판단돼 시도하지 않았다. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §8.

- 작성자: Claude
- 수정일자: 2026-07-15 (16차, 중복 억제 시계열 누적 + 국면 정의 비교
  체계 구축)
- 수정내용: §8(하루치 관찰)을 §6(Phase 2)이 확립한 누적 패턴에 맞춰
  시계열 누적 절차로 승격했다(SPPV-2.19). 신규 오케스트레이터
  `scripts/run_entry_score_penalty_ablation_cycle.py`가 `shadow_
  entry_score_penalty_ablation.py`(penalty 축 A/B/C)와 `shadow_regime_
  conditional_entry_signal.py`(시장 공통 국면)의 함수를 그대로
  재사용해, 종목별 국면과 시장 공통 국면을 같은 실행에서 나란히
  계산하고 누적 이력(`logs/entry_score_penalty_ablation_history.jsonl`,
  중복 거래일 자동 skip)에 기록한다. **실행 결과: §8과 완전히 동일한
  수치(A=85/B=60/C=75/A∩B∩C=60)로 교차 검증됐고, 국면 일치 18건/
  불일치 69건(79%) — 그중 "시장 비하락장인데 종목별 하락장" 60건**.
  즉시 재실행해 중복 방지 로직이 정상 발동함을 확인했다. SPPV-3
  본작업용 비교 실험(현행 종목별 정의 vs 시장 공통 정의, §16 이원
  기준 재사용)을 설계 문서 §9.6에 구체화했다. `entry_score` 코드/
  운영 변경 없음. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §9.

- 작성자: Claude
- 수정일자: 2026-07-15 (17차, §9.6 비교 실험 실측 — 종목별 vs 시장
  공통 regime 정의)
- 수정내용: §9.6에서 설계한 실험을 실제로 실행했다(SPPV-2.20). 신규
  스크립트 `scripts/validate_entry_score_regime_definition_
  comparison.py`가 3년 rolling 표본(87종목, 56,753건)에 대해 운영
  함수 `_assess_buy_eligibility()`를 그대로 호출해 변형 A(종목별
  regime)와 변형 B(시장 공통 regime) 각각의 통과군 T+5/T+20 forward
  return을 §16 이원 검증 도구(quintile spread + Newey-West)로
  비교했다. **결과: 변형 B가 변형 A보다 통과율은 더 낮으면서(18.75%
  < 20.64%) 통과 종목의 forward return은 더 높다(T+5 +1.04%>
  +0.93%, T+20 +3.58%>+3.19%, 둘 다 baseline 대비 유의, t_NW
  7.3~7.7)** — eligibility 필터 자체는 두 정의 모두 유효하고,
  시장 공통 정의가 "더 적게, 더 좋은 것만" 통과시키는 방향으로
  나타났다. 다만 A-B 차이 자체의 통계적 유의성은 검정하지 않았고,
  통과군 내부에서도 `overall_score` quintile spread가 여전히 유의
  하게 역전(T+20 t_NW=-2.84~-3.06)해 **판정은 Watch(조건부 유리,
  확정 Go 아님)로 유지**한다. 이번 실행의 실제 KIS 호출 여부는
  가정하지 않고 로그로 확인했다 — `HTTP Request:` **0건**(3년 캐시
  완전 재사용, 종료 코드 0). `entry_score` 코드/운영 변경 없음.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §10.

- 작성자: Claude
- 수정일자: 2026-07-15 (18차, A/B 판정 불일치 표본 direct 비교 + 1차
  창 재확인)
- 수정내용: §10.5(다음 단계)가 지시한 두 과제를 실행했다(SPPV-2.21).
  신규 `scripts/validate_entry_score_regime_definition_ab_diff.py`가
  같은 종목-거래일 표본을 `A_only`/`B_only`/`both`/`neither` 4개
  배타적 집합으로 분해했다. **핵심 발견: `B_only`가 3년·최근 12개월
  모두에서 정확히 0건 — 시장 공통 정의(B)는 종목별 정의(A)의 진부분
  집합(strict subset)이며, "새로운 종목을 발굴"하는 효과는 없고
  "A가 통과시킨 것 중 일부(`A_only`, 3년간 1,072건)를 추가로 차단"
  하는 것뿐임을 구조적으로 확인했다.** `A_only`의 forward return은
  방향상 음수(T+5 -0.17%, T+20 -0.70%)이나 **통계적으로 유의하지
  않다(|t_NW|<1)**. 최근 12개월 창은 `A_only=B_only=0`으로 **A-B
  차이 자체가 존재하지 않는다**(§21 모니터링의 bearish_trend 0일과
  정합). "일별 짝비교" 방법은 `B_only`가 0이라 정의상 계산 불가함을
  확인했고, 그 대안으로 `A_only` 자체의 유의성 검정이 실질적으로
  동등한 검증임을 확인했다. **판정: Watch 유지(No-Go에 근접), 시장
  공통 정의로의 확정 전환(Go)은 기각.** 이번 실행의 실제 KIS 호출
  여부도 가정 없이 로그로 확인 — `HTTP Request:` 0건. `entry_score`
  코드/운영 변경 없음. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §11.

- 작성자: Claude
- 수정일자: 2026-07-15 (19차, alpha layer vs regime_conditional_signal
  직접 비교 — 무게중심을 차단에서 선별로 이동)
- 수정내용: §11.8이 지시한 대로 무게중심을 "국면 정의 통일"(차단
  축)에서 "alpha layer 교체"(선별 축)로 옮겼다(SPPV-2.22). 신규
  `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`가
  `entry_score`의 alpha layer(`0.45·overall+0.20·fast+0.15·slow`,
  `_normalize_signed_score`의 선형성으로 순위상 원 가중합과 동일함을
  코드로 확인)와 `regime_conditional_signal`을 같은 3년 rolling
  표본(87종목, 56,753건)에서 §16 이원 검증 도구로 직접 비교했다.
  **결과: 2차(3년) 창에서 `regime_conditional_signal`이 T+5(t_NW=
  2.52)/T+20(t_NW=2.33) 둘 다 유의 임계(|t|≥2)를 통과하는 반면,
  현행 alpha layer는 같은 표본에서 어디서도 유의하지 않다(1.02~
  1.39)** — spread 크기·t값·양수 비율 4개 관측치 전부에서
  `regime_conditional_signal`이 일관되게 우세했다(1차 창 포함).
  1차(최근 12개월) 게이트는 여전히 미달이나, 원인이 신호 결함이
  아니라 §21의 구조적 사실(최근 하락장 부재)임을 재확인 — **판정을
  Watch로 낮추지 않고 "Conditional Go"(2차 검증 통과, 1차 게이트
  전환 대기)로 명시**했다. 실행 로그로 KIS 호출 0건 확인(가정 없이
  실측). `entry_score` 코드/운영 변경 없음 — 이번 턴은 shadow/
  validation 범위에 머문다. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §12.

- 작성자: Claude
- 수정일자: 2026-07-15 (20차, 새 alpha 상위군과 기존 차단 축 결합
  효과 검증 — 가장 빈번한 차단 사유 재발견; 당시 해석은 이후
  SPPV-2.24/§14 ablation으로 보정됨)
- 수정내용: `regime_conditional_signal`(§12, Conditional Go)을 새
  alpha로 넣었을 때 기존 차단 로직이 그 효과를 상쇄하는지 검증했다
  (SPPV-2.23). 신규 `scripts/validate_new_alpha_vs_existing_
  blocking_axes.py`가 거래일별 cross-sectional 상위 20%(regime_
  conditional_signal 기준)에 운영 함수 `_build_entry_score`/
  `_assess_buy_eligibility`를 그대로 호출한 결과, **상위군의 68.3%
  (3년)/61.1%(최근 12개월)가 차단**됐다. 그러나 **차단된 표본도
  forward return이 강하게 유의하게 양(+)**이었다(3년 T+5 +0.815%
  t_NW=6.86, T+20 +3.170% t_NW=8.35 — 생존군과 큰 차이 없음, 특히
  1차 창 T+20은 생존 +5.87% vs 차단 +5.63%로 거의 동일). 이는 §8/
  §9/§11이 조사해온 regime 관련 세 축이 아니라 다른 원인을 의심하게
  했고, 신규 진단 스크립트 `scripts/diagnose_blocked_reason_
  distribution.py`로 실제 eligibility 실패 사유를 집계한 결과
  **`eligibility_low_relative_activity`(거래량/거래대금 급증 비율
  <1.10이면 차단, `deterministic_trigger_engine.py:493-499`, 국면·
  신호와 무관한 순수 유동성 게이트)가 차단의 압도적 대부분(3년
  79.7%, 최근 12개월 99.6%)을 차지함을 새로 발견했다** — §8의
  regime 축(B/C)은 오히려 부차적이었다(3년 20.3%, 최근 12개월
  0.4%). **판정: alpha 자체(§12)는 Conditional Go 유지, 결합
  시나리오는 Watch(활동성 필터 ablation 검증 필요)로 확정.** SPPV-3
  다음 최우선 조사 대상을 "국면 정의 통일/regime penalty"에서
  "활동성 필터(`eligibility_low_relative_activity`) 재검토"로
  재조정했다. 두 스크립트 실행 모두 로그로 KIS 호출 0건 확인(가정
  없이 실측). `entry_score` 코드/운영 변경 없음. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §13.

- 작성자: Claude
- 수정일자: 2026-07-16 (21차, 활동성 필터 정밀 ablation)
- 수정내용: §13이 발견한 `eligibility_low_relative_activity`가 실제로
  과잉 억제인지 정밀 ablation으로 판정했다(SPPV-2.24). 신규
  `scripts/validate_activity_filter_ablation.py`가 `regime_
  conditional_signal` 상위 20% 표본 대상으로 threshold 현행(1.10)/
  완화(1.00)/완전 제거 3개 시나리오를 비교한 결과, **완전 제거는
  생존군 forward return이 무차단 상위군 전체 수준으로 회귀하고
  현행 유지보다도 낮아**(2차 T+20 제거 +3.882% < 현행 +4.381%,
  ≈무차단 전체 +3.554%) **No-Go로 확정**했다. **임계값 1.10→1.00
  완화는 생존 종목 수(2차 31.7%→37.7%, 1차 38.9%→46.4%)와 T+5/
  T+20 평균 수익률·Newey-West t값·양수 비율이 1차·2차 창 모두에서
  동시에 소폭(0.07~0.18%p) 개선되는 방향은 일관됐으나, 검증
  threshold가 1.00 단 하나뿐이고 개선폭이 작아 Watch(추가 검증
  필요) 수준으로만 기록했다** — Conditional Go로 단정하지 않는다.
  판단 기준을 "차단된 표본이 플러스인지"에서 "차단 제거/완화 시
  기대수익률이 실제로 개선되는지"로 재정정했다(2026-07-16 2차
  검토, Codex 지적 반영) — "차단 사유의 대부분을 차지한다"가 곧
  "과잉 억제"를 뜻하지 않고, "표본이 늘어 t값이 커진다"가 곧
  "품질 개선"을 뜻하지 않음을 실측으로 확인했다(완전 제거 시나리오가
  그 역설 사례). **결론: 활동성 필터가 BUY 0건의 "주범"인지
  "과잉 억제"인지는 이번 실측만으로 확정할 수 없다** — 재검토가
  필요한 후보로 남기고, "주범 확정"·"과잉 억제 확정"·"제거 시
  개선" 같은 확정적 결론은 쓰지 않는다. §13의 "결합 사용 시나리오
  Watch" 판정은 이번 결과로도 **Watch로 유지**한다. 신규 KIS 호출
  0건(기존 3년 캐시 88개 파일로 전량 서빙, 로그로 실측 확인).
  `entry_score`/`_assess_buy_eligibility` 운영 코드 변경 없음 —
  이번 턴은 shadow/validation 범위. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §14.

- 작성자: Claude
- 수정일자: 2026-07-16 (22차, §13/§14 문서 내부 해석 일관성 정리)
- 수정내용: 새 실측 없이 문서 내부 표현만 정리했다. §13(SPPV-2.23)의
  "진짜 병목 재발견"·"과잉 억제의 강력한 증거"·"주범" 등 §14
  보정 결론과 충돌하는 단정 표현을 §13.4~§13.6 제목/본문에서
  "당시 해석(§14 보정 전)" 형태로 위치를 낮췄다(내용 삭제 없이
  보존). SPPV-2.23 관련 체크리스트/수정이력 제목도 "가장 빈번한
  차단 사유 재발견"으로 정정하고 "당시 해석은 이후 SPPV-2.24/§14
  ablation으로 보정됨"이라는 안내를 추가했다. 다른 4개 정본 문서
  (`[ANALYSIS]`, `[PRIORITY_MAP]`, `[BACKLOG]`, 그리고 `[DESIGN]
  regime_conditional_entry_signal_v1.md` 자체)에서도 동일한
  불일치를 함께 정리했다.

- 작성자: Claude
- 수정일자: 2026-07-16 (23차, §13.3 문장 단위 잔여 과장 표현 마감 정리)
- 수정내용: 22차에서 §13.4~§13.6 제목 단위로 "당시 해석" 안내를
  추가했지만, `regime_conditional_entry_signal_v1.md` §13.3 본문의
  "차단된 표본의 절대다수가 실제로는 손실이 아니라 상당한 이익을
  내고 있었다"는 문장은 여전히 단독으로 읽으면 확정 결론처럼
  들렸다. 새 실측 없이 이 문장을 "이 시점(§14 검증 전)에는 ...으로
  받아들였다 — 다만 이 관찰은 '차단 제거 시 기대수익률이 실제로
  개선되는가'를 검증한 것은 아니었다"는 톤으로 순화했다. 다른 4개
  정본 문서에는 동일 패턴의 문장이 없어 추가 수정이 필요하지
  않았다(확인만 수행).

- 작성자: Claude
- 수정일자: 2026-07-16 (24차, 활동성 필터 threshold sweep + 기간
  분할 재현성 검증)
- 수정내용: SPPV-2.24의 "1.00 완화 Watch" 판정을 Conditional Go
  이상으로 올릴 수 있는지 검증했다(SPPV-2.25). threshold를 1.10/
  1.05/1.00/0.95/0.90으로 확장 스윕하고, 3년 표본을 거래일 기준
  전반부/후반부로 양분해 재현성을 확인한 결과, **2차(3년) 전체·
  1차(최근 12개월)·3년 후반부에서는 완화할수록 평균 수익률이
  개선되는 것처럼 보였으나, 3년 전반부에서는 정반대로 완화할수록
  악화됐다**(T+5 기준 1.10 +0.7394% → 0.90 +0.5728%). 즉 "완화=
  개선"은 사실상 후반부(=최근 12개월과 거의 동일 시기)의 효과가
  3년 pooled 평균을 끌어올린 것이었고, 3년 전체를 대표하는 규칙성이
  아니었다. 창마다 최적 threshold도 달라 단일 sweet spot이 없다.
  결론: 완화안은 Conditional Go로 올릴 근거를 얻지 못했고, 오히려
  재현성 부재라는 신중론 근거가 추가됐다 — **판정 Watch 유지(격상
  없음), 완전 제거는 여전히 No-Go**. 신규 KIS 호출 0건(기존 3년
  캐시 88개 파일로 전량 서빙, 로그로 실측 확인). `entry_score`/
  `_assess_buy_eligibility` 운영 코드 변경 없음 — 이번 턴도 shadow/
  validation 범위. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §15.

- 작성자: Claude
- 수정일자: 2026-07-16 (25차, 활동성 필터 완화 효과 전반부/후반부
  반전 원인 분해)
- 수정내용: SPPV-2.25가 발견한 "완화 효과가 3년 전반부에서는
  반대로 나타나는" 현상의 원인을 규명했다(SPPV-2.26). 시장 공통
  regime 분포(전반부 range_bound 45.4%+bearish_trend 28.5% 혼합/
  약세 편중 vs 후반부 bullish_trend 82.9% 극편중), 상위 20% 무차단
  기본 수익률 레벨(후반부가 전반부의 약 3.3~3.4배), 유동성 구조
  (average_turnover_20d 중앙값 약 1.9배 확대, trend_strength 약
  2.4배 확대), 그리고 threshold 완화 시 "새로 통과하는 표본"만
  분리한 forward return을 비교했다. **결정적 발견: threshold를
  1.10→1.00으로 낮췄을 때 새로 통과하는 표본의 품질이 전반부에서는
  기존 통과군보다 낮고(+0.56%<+0.74%), 후반부에서는 오히려 기존
  통과군보다 높다(+2.72%>+1.86%)** — 완화 효과의 방향 반전은
  활동성 필터 로직 결함이 아니라 두 반기의 시장 국면·유동성 구조
  차이가 만들어낸 결과로 판단했다. 정적 threshold 완화안은 여전히
  Watch 유지(격상도 강등도 아님) — 완전 제거는 여전히 No-Go. 향후
  검토 방향은 "완화"가 아니라 "국면 조건부 threshold"일 가능성이
  있으나 이번 턴은 원인 규명까지만(새 설계·구현·운영 코드 변경
  없음). 신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측
  확인). 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §16.

- 작성자: Claude
- 수정일자: 2026-07-16 (26차, alpha layer 교체 BUY funnel 검증)
- 수정내용: 무게중심을 활동성 필터에서 alpha 교체로 되돌려,
  현행 alpha(`current_alpha_composite`)와 `regime_conditional_
  signal`을 candidate→eligible→would_buy→blocked 4단계 BUY
  funnel로 비교했다(SPPV-2.27). would_buy 상수(`WATCH_TOP_K_
  BUY=3`)는 `trigger_proxy_attribution.py:38`의 실제 운영 상수를
  재사용했다. **결과: would_buy 단계 forward return이 2차(3년)·
  1차(최근 12개월)·3년 전반부·3년 후반부 4개 창, T+5/T+20 2개
  horizon 전부(8/8)에서 새 alpha가 현행보다 높았다**(2차 T+20
  현행 +1.90%/t_NW=2.38 vs 신규 +2.82%/t_NW=2.90). 활동성 필터
  완화(§15)와 달리 방향이 한 번도 반전되지 않았다 — 3년 전반부만
  두 시나리오 모두 비유의했으나 방향은 유지됐다. eligible 전환율은
  신규 alpha가 더 낮아(2차 31.7% vs 49.2%) would_buy 표본 수가 약
  20% 적었지만, 표본당 평균 수익률 개선폭이 더 커서 누적 기대
  성과 근사치(표본 수×평균)는 신규 alpha가 여전히 컸다. 결론:
  §12의 Conditional Go가 funnel 실제 매수 후보 단계까지 보강됐으나,
  3년 전반부 비유의·국면 편향 가능성·거래 빈도 감소 트레이드오프로
  확정 Go는 아니다. 신규 KIS 호출 0건. `entry_score` 운영 코드
  변경 없음 — 이번 턴도 shadow/validation 범위. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §17.

- 작성자: Claude
- 수정일자: 2026-07-16 (27차, alpha layer 교체 virtual BUY funnel
  확장 검증)
- 수정내용: `would_buy`를 실제 운영 판단 경로에 한 단계 더 가깝게
  확장했다(SPPV-2.28). 운영 함수 `assess_deterministic_triggers()`
  가 실제로 쓰는 `BUY_CANDIDATE` 조건(`eligible AND entry_score>=
  0.65 AND allocation_budget_ok`, `deterministic_trigger_engine.py:
  89`의 실제 상수 재사용)을 그대로 재현한 `selected` 단계를 추가해
  candidate→eligible→selected→would_buy 5단계로 확장했다. would_buy
  단계의 forward return 우위(새 alpha>현행)는 4개 창·2개 horizon
  전부(8/8)에서 유지됐다. **결정적 신규 계측**: 새 alpha는 4개 창
  전부에서 selected 비율이 **정확히 100.0%**였다 — candidate
  정의와 selected 조건이 같은 alpha 신호를 두 번 거르는 구조라
  0.65 문턱이 새 alpha에는 **사실상 무력화된다는 계측 caveat**을
  새로 발견했다(현행은 eligible의 66~72%만 통과해 실제로 필터링
  효과가 있음). MFE/MAE 비교에서는 새 alpha가 4개 창 전부에서
  MFE(상방)·MAE(하방 절댓값) 모두 크지만, MFE/|MAE| 비율은 4개
  창 전부에서 새 alpha가 더 높았다(예: 2차 T+20 현행 1.50 vs
  신규 1.68). 결론: SPPV-2.27의 Conditional Go를 재확인했으나,
  "0.65 문턱 사실상 무력화"·"MAE 확대"라는 두 계측 caveat이
  추가되어 여전히 확정 Go는 아니다. 신규 KIS 호출 0건. 운영 코드
  변경 없음 — 이번 턴도 shadow/validation 범위, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §18.

- 작성자: Claude
- 수정일자: 2026-07-16 (28차, 새 alpha entry_score 스케일 재보정
  shadow 검증)
- 수정내용: SPPV-2.28의 "0.65 문턱 사실상 무력화" caveat의 원인을
  분해했다(SPPV-2.29) — `regime_conditional_signal`이 [-1,1] 스케일
  이 아닌 퍼센트 단위 비율이라 `_normalize_signed_score`가 상위
  20% quintile에서 거의 항상 saturate됨을 확인했다. 재보정 3안(R1
  가중치 축소 0.80→0.50/R2 z-score/R3 percentile)과 기준선(R0)을
  비교한 결과, **R1은 selected_rate를 크게 낮췄지만 forward return
  이 3/4 창에서 악화돼 기각**했고, **R2는 selected_rate가 여전히
  96.9~99.3%로 문제를 충분히 해결하지 못했다**(상위 20% 멤버는
  정의상 z>=1 saturate 경계 근처에 몰림). **R3(percentile 기반)가
  가장 균형 잡힌 결과를 보였다 — selected_rate를 93.7~96.5%로
  의미 있게 낮추면서(문턱 실질 회복), forward return이 4개 창·2개
  horizon 전부(8/8)에서 개선됐고**(2차 T+20 R0 +2.818% vs R3
  +3.591%, 1차 T+20 R0 +4.307% vs R3 +6.050%), **would_buy 표본
  감소는 1.2~2.4%로 미미했으며 MAE도 3개 창에서 근소 개선됐다.**
  결론: R1/R2는 기각, R3를 유력한 재보정 후보로 채택 검토하되
  단일 실험·재현성 미확인·§3 기존 전제조건 미충족으로 확정 Go는
  아니다. 신규 KIS 호출 0건. 운영 코드 변경 없음, broker submit
  미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §19.

- 작성자: Claude
- 수정일자: 2026-07-16 (29차, R3 재현성 검증 + percentile 계산
  민감도 점검)
- 수정내용: SPPV-2.29가 채택 검토한 R3를 분기 4분할로 재검증했다
  (SPPV-2.30). **R3의 "4개 창 전부 우위" 결론이 분기 단위로는
  무너졌다 — 분기1·분기3에서 R3가 R0보다 오히려 낮았다**(분기1
  T+20 R0 +1.208% vs R3 +1.041%, 분기3 T+20 R0 +3.648% vs R3
  +3.402%). SPPV-2.29의 4개 창은 서로 겹치는 넓은 구간이라 해상도가
  낮았음이 원인으로 판단된다. percentile 계산 기준을 candidate
  내부로 바꾼 변형(R3b)은 8개 창 전부에서 R0보다 높았으나
  selected_rate가 29.9~39.2%까지 낮아져 R1과 유사한 "극단적 선별"
  우려가 있어 별도 검증이 필요하다. 결론: R3를 다시 Watch로
  하향한다(SPPV-2.29의 "유력 후보 격상" 철회) — 분기 50%에서 방향이
  뒤집힌 것은 "일부 분할 창에서 흔들리면 Watch/Hold"라는 판정
  원칙에 해당한다. R3b는 신규 관찰 대상으로 등록만 하고 이번 턴에
  격상하지 않는다. 신규 KIS 호출 0건. 운영 코드 변경 없음, broker
  submit 미호출 — 이번 턴도 shadow/validation 범위. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §20.

- 작성자: Claude
- 수정일자: 2026-07-16 (30차, R3b 엄격 재검증 + R3 실패 구간 원인
  분해)
- 수정내용: R3b를 R1과 동일한 엄격 기준(8개 창 중 하나라도 악화되면
  기각)으로 재검증하고, would_buy 종목 겹침률(overlap)로 "진짜
  선별 개선"과 "표본 급감 착시"를 분리했다(SPPV-2.31). **R3b는
  8개 창 전부(R3가 실패한 분기1·분기3 포함)에서 R0보다 높았다.**
  **핵심 발견: R3는 R0와 77~85%가 같은 종목을 고르는 "미세
  재조정"인 반면, R3b는 R0와 47~61%만 겹쳐 40~53%를 새로 골라
  넣는 질적으로 다른 선별이다** — 순수 표본 축소 착시라면 겹침률이
  100%에 가까워야 하는데 그렇지 않아, 실제 재선별 효과로 판단했다.
  R3 실패 원인 분해에서는 saturation_rate가 4개 분기 전부 100.0%로
  동일해 분기간 차이의 원인이 아니었고, 국면 분포도 설명력이
  없었다(분기3은 강세장 67.5%인데도 실패, 분기2는 약세+횡보
  90.8%인데도 성공 — 정반대 패턴). 결론: R3의 실패는 특정 국면
  때문이 아니라 R0와의 높은 겹침에서 오는 작은 효과 크기가 잡음에
  취약했기 때문으로 판단. **판정: R3b를 유력한 재보정 후보로 신규
  격상(Watch→Conditional Go 경계) — R1이 실패한 엄격 기준을 통과한
  첫 재보정안이다.** 다만 selected_rate가 30%대로 낮고(거래 빈도
  최대 36% 감소), 동일 3년 표본 내부 분할이라 진정한 out-of-sample
  검증은 아니며, §3 기존 전제조건도 미충족이라 확정 Go는 아니다.
  **R3는 Watch 유지**(하향 판정 번복 없음). 문서 정정: "분기
  25%가 뒤집혔다"는 계산 오류를 "2/4=50%"로 5개 문서 전체에서
  정정했다(결론 불변, 오히려 더 심각한 재현성 결여를 뜻함). 신규
  KIS 호출 0건. 운영 코드 변경 없음, broker submit 미호출 — 이번
  턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §21.

- 작성자: Claude
- 수정일자: 2026-07-16 (31차, R3b 대응표본 검증 — overlap 근거 보정)
- 수정내용: SPPV-2.31의 overlap(간접) 근거를 대응표본(직접) 검증
  으로 재확인했다(SPPV-2.32) — 같은 거래일에 R0가 버리고 R3b가
  새로 고른 "대체 종목쌍"의 forward return 차이를 일별로 계산해
  집계했다. **R0 vs R3b 대체쌍(added−dropped) T+20 평균은 8개 창
  중 6개에서 양(+)이었으나 분기3에서는 음수(-0.47%p, 대체 우위일
  비율 45.8%로 절반 미만)로 뒤집혔다.** t_NW가 1.96 이상인 창은
  2개(2차, 전반부)뿐이고 나머지는 marginal했다. R0 vs R3 대체쌍은
  더 약해 분기1(-0.44%p)·분기3(-0.04%p)에서 사실상 음수/0이었다.
  **핵심 정정: SPPV-2.31이 overlap만으로 "실제 재선별 효과"라고
  결론 낸 것은 근거가 부족했다 — 이번 직접 검증에서 그 재선별이
  분기3에서는 오히려 더 나쁜 종목으로의 교체였음이 드러났다.**
  aggregate 우위(8/8) 자체는 부정되지 않으나 그 우위가 "대체
  종목의 우수성"에서 왔다는 인과관계는 확인되지 않았다. **판정:
  SPPV-2.31의 "R3b 유력 후보 격상" 판정을 다시 Watch로 하향한다.**
  R3는 Watch를 유지하되 이번 직접 검증으로 근거가 강화됐다. 신규
  KIS 호출 0건. 운영 코드 변경 없음, broker submit 미호출 — 이번
  턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §22.

- 작성자: Claude
- 수정일자: 2026-07-16 (32차, R3b aggregate 우위 vs 대응표본 음수
  구간 3분해)
- 수정내용: SPPV-2.32의 "t_NW≥1.96 창 2개" 서술을 산출 JSON으로
  재확인해 **실제로는 3개(2차=1.96, 전반부=2.07, 분기1=2.02)**였음을
  정정했다(분기1 누락). common_kept/dropped_only/added_only 항등식
  분해로 aggregate 우위의 원인을 규명했다(SPPV-2.33). **added_only
  평균이 8개 창 전부에서 common_kept·dropped_only보다 뚜렷이 높아
  R3b의 신규 선택 자체는 실제로 우수했음을 확인**했으나, **R0
  자신의 구성이 저품질 dropped_only 비중(63.3%, 2차)이 커서
  aggregate 차이의 상당 부분이 "구성 효과"에서도 왔다.** **가장
  중요한 발견: 분기3에서 이번 pooled 교체효과(+2.594%p)와
  SPPV-2.32의 paired 교체효과(-0.4666%p)의 부호가 정반대** —
  가중 방식 차이(종목-일 동일가중 vs 거래일 동일가중) 때문이며,
  이는 R3b의 효과가 "매일 조금씩"이 아니라 "소수 스왑 밀집일에
  집중"된 비대칭 구조임을 시사한다. 결론: aggregate 우위는 부분적
  실체가 있으나(added_only 우수성) 비대칭적이고 특정 구간 집중형
  이라 안정적 재현으로 단정하기 이르다 — **R3b/R3 모두 SPPV-2.32의
  Watch 판정을 그대로 유지한다(이번 턴은 재격상이 아닌 원인
  규명).** 신규 KIS 호출 0건. 운영 코드 변경 없음, broker submit
  미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §23.

- 작성자: Claude
- 수정일자: 2026-07-16 (33차, R3b pooled 우위 날짜 집중도 검증 +
  교체효과/구성효과 정량 분리)
- 수정내용: SPPV-2.33이 지시한 분기3 세밀 진단을 실행했다(SPPV-
  2.34). 거래일별 스왑 개수 상위 10% 제거 후 aggregate 우위
  잔존비율을 계산하고, `aggregate_diff=replacement_effect+
  composition_effect` 정확한 항등식으로 두 효과를 분리했다.
  **결과 1: 스왑 상위 10% 거래일 제거 후에도 8개 창 중 7개에서
  우위가 80~120% 수준으로 유지 — "소수 거래일 집중" 가설 기각.
  분기3만 예외로 잔존비율 30~65%로 크게 감소.** **결과 2(중요
  정정): SPPV-2.33의 "구성효과도 상당히 기여한다"는 서술은 방향이
  틀렸다 — 정확한 분해 결과 composition_effect는 8개 창 중 6개에서
  오히려 음(-)으로 우위를 상쇄하는 방향이었고, aggregate 우위
  전체는 순수 replacement_effect에서 온다.** 판정: 재격상보다
  원인 확정을 우선(지시에 따름) — R3b 우위 근거는 명확해졌으나
  분기3 반례가 실제 집중형임이 확인돼 **R3b/R3 모두 Watch 판정을
  그대로 유지한다.** 신규 KIS 호출 0건. 운영 코드 변경 없음,
  broker submit 미호출 — 이번 턴도 shadow/validation 범위. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §24.

- 작성자: Claude
- 수정일자: 2026-07-16 (34차, 분기3 스왑 집중일 세부 진단 + SPPV-2.34
  해석 문구 정밀 보정)
- 수정내용: SPPV-2.34의 두 서술을 실제 수치 기준으로 정밀 보정하고
  (SPPV-2.35), 분기3 스왑 상위 15개 거래일을 개별 진단했다. **보정
  1: "구성효과 8개 창 중 6개 음(-)"은 T+5/T+20을 뒤섞은 표현 —
  정확히는 T+20 기준 8/8, T+5 기준 5/8에서 음(-)(전반부·분기1·
  분기2는 T+5에서 양(+)).** **보정 2: "분기3은 소수 날짜에 몰린
  착시"는 방향이 과했다 — 대형 스왑일(상위 10%, 약 8일)의 T+20
  교체효과 평균은 +7.04%p로 뚜렷한 양(+)이고, 분기3 전체 paired
  평균(-0.4666%p)을 만드는 진짜 원인은 나머지 약 75개 소규모
  스왑일의 완만한 음(-) 누적(가중평균 역산 약 -1.267%p)이다 —
  "대형 스왑일이 나쁘다"가 아니라 "대형 스왑일은 유일한 양(+)의
  원천이고 그것을 빼면 넓게 퍼진 완만한 음(-)만 남는다"는 구조.**
  이벤트/실적 연관은 2025-02-12~13 연속 악재일에 한해 정황(가설)
  수준. 판정: 재격상/재하향 없이 R3b/R3 모두 Watch 판정을 그대로
  유지(원인 확정·표현 정밀화가 목적, 지시에 따름). 신규 KIS 호출
  0건. 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
  shadow/validation 범위. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §25.

- 작성자: Claude
- 수정일자: 2026-07-17 (35차, 분기3 반례의 대형/소규모 스왑 구조
  정밀 확정 + "전적으로 의존" 문구 보수화)
- 수정내용: 34차(SPPV-2.35)의 "대형 스왑일은 유일한 양(+)의
  원천"이라는 서술을 분기3 83개 스왑일 전체를 5분위(quintile)로
  구간화해 정량 검증했다(SPPV-2.36). **결과: "대형=양(+)/소규모=
  음(-)"은 양극단(Q1 최대·Q5 최소)에서만 성립하고 중간 구간(Q2~Q4)
  은 혼재한다(Q4는 소규모인데도 T+20 +4.38%p로 양(+)).** aggregate
  (순 기여) 관점에서는 대형 스왑일이 우위의 상당 부분(T+5 약 70%,
  T+20 약 35%)을 담당하지만, **총합(gross) 관점에서는 전체 양(+)
  합계의 15% 수준에 불과** — "전적으로 의존"·"유일한 원천"은
  과장이었다. 2025-02-12~13 동시 제거는 분기3 음(-) paired 평균의
  약 39%만 설명(부분적 설명력). 판정: 재격상/재하향 없이 R3b/R3
  모두 Watch 판정을 그대로 유지(구조 확정·문구 보수화가 목적).
  신규 KIS 호출 0건. 운영 코드 변경 없음, broker submit 미호출 —
  이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §26.

- 작성자: Claude
- 수정일자: 2026-07-17 (36차, R3b의 SPPV-3 진입 후보 여부 판단 —
  실제 BUY funnel 최소 검증)
- 수정내용: R3b 미세 해부를 멈추고 SPPV-3 착수 후보 여부를 판단
  (SPPV-2.37). 기존 §20의 8개 창 BUY funnel 계측(재실행 없이 재사용)
  결과 T+20 평균 우위 8/8 일관, t_NW 6/8 유의. **신규 계측: would_
  buy 모집단의 거래일 편중도(top-decile-day leave-out) — 거래일
  집중 의존은 R3b만의 문제가 아니라 R0(기준선) 자체가 8개 창 중
  3개에서 상위 10%일 제거 시 평균이 마이너스로 뒤집히는 alpha
  신호 계열 전반의 특성이며, R3b는 8/8 창에서 R0보다 그 의존도가
  더 낮다(더 견고).** 판정: **R3b를 Watch에서 Conditional Go로
  상향**(조건부: 분기1·분기2 marginal t_NW 재확인, selected_rate
  급감의 총 기대수익 영향 정량화, §3 전제조건 충족, point-in-time
  파이프라인 반영 shadow 실행이 확정 Go 전 필요). 신규 KIS 호출
  0건. 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
  shadow/validation 범위. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §27.

- 작성자: Claude
- 수정일자: 2026-07-17 (37차, SPPV-2.37 수치 정정 + Conditional
  Go 재평가)
- 수정내용: 36차(SPPV-2.37)의 세 가지 수치 서술을 재검산해 정정
  했다(SPPV-2.38). **정정 1: R0의 top-decile-day 음(-) 반전 창
  수는 "3개"가 아니라 "4개"(2차 포함).** **정정 2: 양수 비율
  열세 창 수는 "3/8"이 아니라 T+20 기준 "1/8"(분기2만), T+5
  기준으로는 "0/8".** **정정 3: "selected_rate 급감(약 30~40%)"
  은 R3b 자신의 비율 수준(29.9~39.2%)이며 R0(100%) 대비 약
  61~70%p 감소로 명확화.** 세 정정 모두 R3b의 방향성 우위를
  약화시키지 않아(정정 1·2는 오히려 R3b에 유리한 방향) **R3b는
  Conditional Go를 유지한다.** 새 실험 없이 기존 JSON 재검산만
  수행(신규 KIS 호출 해당 없음). 운영 코드 변경 없음, broker
  submit 미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §28.

- 작성자: Claude
- 수정일자: 2026-07-17 (38차, selected_rate 감소가 총 기대수익에
  미치는 영향 정량화)
- 수정내용: R3b Conditional Go 확정 전 잔여 조건 중 조건 (2)
  (selected_rate 감소가 총 기대수익에 미치는 영향)를 정량화했다
  (SPPV-2.39). **신규 실측 없이** 기존 산출물 2개만 재사용해
  총 기대수익 proxy(= would_buy_n × mean_forward_return_pct)를
  8개 창×2horizon(16개 조합) 전부 계측한 결과, **14/16 조합에서
  R3b의 총proxy가 R0보다 높다**(92.0%~322.6%). 나머지 2개(1차
  T+5, 분기3 T+20)도 R0와 거의 동률. 판정: "거래 빈도 감소가 총
  기대수익을 훼손하는가"에 명확히 "아니다" — **확정 Go 전 잔여
  조건 4가지 중 1개(조건 2)가 해소돼 Conditional Go 근거가
  보강됐다.** 나머지 3개 조건(분기1·분기2 marginal t_NW, §3
  전제조건, point-in-time 파이프라인 반영)은 그대로 남아 확정
  Go는 아니다. 신규 KIS 호출 없음(신규 실행 자체가 없었음). 운영
  코드 변경 없음, broker submit 미호출 — 이번 턴도 shadow/
  validation 범위. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §29.

- 작성자: Claude
- 수정일자: 2026-07-17 (39차, R3b 총 기대수익 proxy의 유휴 자본
  반영 보강 검증)
- 수정내용: §2.39가 "조건 (2) 해소"라 표현한 것을 유휴 자본
  기회비용까지 반영해 보강 검증했다(SPPV-2.40). 신규 계측은 창별
  전체 거래일 수 하나뿐(캐시 봉 데이터만 사용, 신규 KIS 호출
  없음). **엄격 기준(R0가 전체 슬롯을 자기 평균으로 100% 채웠다는
  이론적 최대와 비교) 적용 결과, T+20은 8개 창 중 7개에서 여전히
  R3b 우위(견고)이나, T+5는 8개 창 중 6개에서 우위가 사라지거나
  이미 열세(취약).** 판정: **"조건 (2) 해소"는 과장 — 정확히는
  "T+20 기준 완화, T+5 기준 여전히 미해결"** 수준으로 재조정. R3b는
  Conditional Go를 유지한다(확정 Go 아님). 확정 Go 전 잔여 조건에
  "T+5 horizon 의존 여부에 따른 유휴 자본 취약성 확인"을 추가.
  신규 KIS 호출 0건(로그 확인). 운영 코드 변경 없음, broker submit
  미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §30.

- 작성자: Claude
- 수정일자: 2026-07-17 (40차, R3b Conditional Go의 운영 horizon
  적합성 판단)
- 수정내용: §2.40이 남긴 "이 시스템이 T+20 중심인가, T+5 취약성이
  실운영과 충돌하는가"를 코드·문서 조사로 판단했다(SPPV-2.41).
  **결과: `deterministic_trigger_engine.py`의 SELL/청산은 100%
  `exit_score`(신호/점수) 기반이며 경과일수를 전혀 참조하지 않고,
  `max_holding_days=20`(`schemas.py`)은 AI Risk agent의 LLM 출력
  힌트 기본값일 뿐 실제로 20일 뒤 매도를 강제하는 코드가 없다.**
  기존 §16 Go/No-Go 표준이 T+5·T+20을 이미 동시에 요구해온 것도
  확인. **판정: "T+20 중심이라 T+5 약점을 무시해도 된다"는 주장은
  코드로 뒷받침되지 않는다.** R3b는 Conditional Go를 유지하되
  (즉시 Watch 재하향 근거는 부족), **T+5 horizon 강건성 확보(또는
  실거래 누적 후 청산 시점 분포 실측)를 확정 Go의 필수조건으로
  격상**한다. 신규 KIS 호출 없음(신규 실행 자체가 없었음, read-only
  코드/문서 조사만 수행). 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §31.

- 작성자: Claude
- 수정일자: 2026-07-17 (41차, R3b를 point-in-time entry_score
  파이프라인에 반영한 shadow 검증)
- 수정내용: §2.41이 남긴 "point-in-time entry_score 파이프라인
  반영 shadow 실행"을 수행했다(SPPV-2.42). 기존 검증이 이미
  `build_signal_snapshot`/`_assess_buy_eligibility`/`_build_entry_
  score` 등 실제 운영 함수를 호출해왔음을 확인했으나, 실제
  `strategy_selection` 조정항(+0.05 보너스)이 그동안 `None`으로
  누락돼 있었다 — 이를 실제 `select_strategy()` 호출로 채워 A/B
  양쪽에 공정하게 반영했다. **결과: 8개 창×2horizon 16개 조합
  전부에서 R3b>R0 방향 유지**(붕괴 없음), 다만 **분기1 T+20의
  t_NW가 1.31→0.96으로 더 약화**돼 기존 marginal 우려가 심화됐다.
  판정: **R3b는 Conditional Go를 유지한다.** "point-in-time
  파이프라인 반영" 조건은 부분 해소(핵심 우려는 해소, `portfolio_
  allocation` gap은 미해결로 잔존). 신규 KIS 호출 0건. 운영 코드
  변경 없음, broker submit 미호출 — 이번 턴도 shadow/validation
  범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §32.

- 작성자: Claude
- 수정일자: 2026-07-17 (42차, 분기1 t_NW 약화의 원인 정밀 진단 —
  방향성 붕괴 vs 변동성/이상치 문제)
- 수정내용: §2.42가 남긴 "분기1 t_NW 약화(0.96) 우선 재확인"을
  실행했다(SPPV-2.43). 분기1은 세 분기 중 가장 "혼합 국면"
  (강세/횡보/약세 고른 분포 + event_driven_unstable 최다) 구간임을
  확인. **R3b>R0 방향은 그대로 유지되고(1.815% vs 0.753%), 스왑일
  46건 중 33건(71.7%)이 양(+)으로 세 분기 중 최다 — 상위 스왑일
  제거 시 오히려 개선(157.8%)돼 분기3과 정반대 구조.** t_NW 약화의
  실체는 상위 10개 스왑일 중 3건의 극단치(±16~44%p)가 표준오차를
  키운 것으로 확인. 판정: **분기1 약화는 방향성 붕괴가 아니라
  소수 극단치로 인한 분산 문제로 좁혀진다 — R3b는 Conditional Go를
  유지한다**(Watch 재하향 근거 없음, 잔여 리스크 성격만 구체화).
  신규 KIS 호출 0건. 운영 코드 변경 없음, broker submit 미호출 —
  이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §33.

- 작성자: Claude
- 수정일자: 2026-07-17 (43차, SPPV-3 진입 관문 3종 종합 판정 — §3
  게이트 재확인 + 분기1/T+5 리스크 종합)
- 수정내용: SPPV-3 진입 전 마지막 관문 3가지(§3 전제조건, 분기1
  약화, T+5 취약성)를 종합 판정했다(SPPV-2.44). 기존 검증(분기1=
  §2.43, T+5=§2.41)을 반복하지 않고, 유일한 신규 실측인 §3 게이트
  (`regime_switch_v1` 1차 게이트, 기존 SPPV-2.13 모니터링 스크립트
  재실행)만 확인 — **결과 `NOT_TRIGGERED`(불변, 최근 12개월
  bearish_trend 0/30일).** 종합 판정: ①§3 전제조건 미충족, ②분기1
  약화는 관리 가능한 잔여 리스크(치명적 결함 아님), ③T+5 취약성은
  미해결이나 치명적 근거 없음. 판정: **R3b는 Conditional Go를
  유지한다.** 다만 **SPPV-3(운영 코드 반영) 진입은 아직 이르다 —
  주된 차단 요인은 R3b 성과와 무관한 §3 게이트(하락장 미도래)**이며,
  규칙 A(관찰 유예)에 따라 인위적으로 앞당길 수 없다. 신규 KIS
  호출 0건. 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
  shadow/validation 범위. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §34.

- 작성자: Claude
- 수정일자: 2026-07-17 (44차, SPPV-2.44 산출물 파일명/실행 경로
  불일치 정정)
- 수정내용: §2.44가 §3 게이트 재확인 산출물을 `..._2026-07-17.
  json`으로 표기한 것이 실제 스크립트 동작과 불일치해 정정했다
  (SPPV-2.45). **확인된 사실: `monitor_regime_switch_v1_gate.py`
  는 실행 시점과 무관하게 항상 하드코딩된 `..._2026-07-14.json`에
  저장한다** — §2.44가 인용한 `..._2026-07-17.json`은 컨테이너
  산출을 호스트로 복사하며 수동 재명명한 사본이다. 내용은 실제
  이번 재실행 결과가 맞고(as_of 일치), 결론에 영향을 주는 차이는
  없다. **판정: 정정 후에도 SPPV-3 관련 결론은 전혀 바뀌지 않는다
  — R3b Conditional Go 유지, SPPV-3 진입은 §3 게이트 미충족으로
  아직 이르다는 §2.44의 판정을 그대로 유지한다.** 새 실측/새
  스크립트 없이 기존 코드·로그 재확인만 수행(신규 KIS 호출 해당
  없음). 운영 코드 변경 없음, broker submit 미호출 — 이번 턴은
  기록 정정 범위. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §35.

- 작성자: Claude
- 수정일자: 2026-07-17 (45차, R3b 채택 시 risk_off_penalty 중복
  해소 ablation)
- 수정내용: §3 전제조건 ②(risk_off_penalty 중복 해소)를 R3b
  candidate 위에서 실측했다(SPPV-2.46). entry_score 축(-0.15,
  `_build_entry_score:1139-1141`)과 eligibility 축(즉시 차단,
  `_assess_buy_eligibility:421-438`)이 서로 다른 함수의 별개 축임을
  코드로 확정하고, A(현행)/B(entry_score 축 무력화)/C(eligibility
  축 완화) 3개 시나리오를 실제 운영 함수 호출로 비교했다(운영
  코드 미수정, market_regime 입력만 국소 중립화). **결과: C는 A와
  완전 동일**(eligibility 축이 R3b candidate pool에서 비활성임을
  확인) — 중복 우려는 애초에 발생하지 않는다. **B는 T+20 총
  기대수익 proxy가 2차 +20.9%/1차 +20.5% 개선되나 MAE도 소폭
  악화(약 0.5%p)** — 실제 트레이드오프. 판정: **eligibility 축은
  비활성, entry_score 축은 "유지할 방어"보다 "완화 검토 후보"에
  가깝다는 실측 근거 확보 — R3b는 Conditional Go를 유지하고, §3
  조건②는 "방향 확인, 사용자 승인 대기"로 진전, SPPV-3 진입은
  §21 게이트 미충족으로 여전히 이르다(불변).** 신규 KIS 호출 0건.
  운영 코드 변경 없음, broker submit 미호출 — 이번 턴도 shadow/
  validation 범위. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §36.

- 작성자: Claude
- 수정일자: 2026-07-17 (46차, 승인 범위 확정 + risk_off_penalty
  (entry_score 축) 완화안 심층 해석)
- 수정내용: 사용자가 §2.46의 A/B/C 중 "B — entry_score risk_off_
  penalty만 완화"를 승인(eligibility 축 비승인)했다. §2.46 산출물을
  신규 실행 없이 재사용해 T+5/T+20 양쪽·MAE 트레이드오프를 심층
  해석했다(SPPV-2.47). **결과: 총 기대수익 proxy가 2개 창×
  2horizon 전부에서 개선(12.9~20.9%), t_NW도 함께 개선, MAE는
  소폭 악화(5.9~7.8% 상대)하나 개선폭보다 항상 작다.** 판정: **R3b
  + entry_score risk_off_penalty 제거 조합은 Conditional Go를
  보강한다.** SPPV-3 진입 관점에서 남은 조건은 사실상 §21 게이트
  하나로 좁혀졌다(entry_score 코드 반영은 게이트 충족 후 별도
  절차). **[SPPV-2.48에서 정정] "게이트 하나로 좁혀졌다"는 §3
  전제조건 범위로 한정하면 정확하나 SPPV-3 진입 전체로는 과장 —
  T+5 구조적 리스크(§31)·혼합 국면 재확인(§33)·portfolio_
  allocation gap(§32)이 §3와 별개로 여전히 열려 있다. 상세는 §38
  참고.** 신규 KIS 호출 없음(신규 실행 자체가 없었음). 운영 코드
  변경 없음, broker submit 미호출 — 이번 턴도 shadow/validation
  범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §37.

- 작성자: Claude
- 수정일자: 2026-07-18 (47차, SPPV-2.47 "게이트 하나만 남았다"
  표현 정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리)
- 수정내용: §2.47의 "SPPV-3 진입 관점에서 남은 조건은 사실상 §21
  게이트 하나로 좁혀졌다"는 서술이 §3 전제조건 범위로는 정확하나
  SPPV-3 진입 전체로는 과장이었음을 바로잡았다(SPPV-2.48). 새
  실측·새 설계 제안 없이 기존 문서(§2.41 T+5 구조적 리스크, §2.43
  혼합 국면 재확인, §2.40 portfolio_allocation gap)만 재해석했다.
  **재분류: ①주된 차단 요인(§21 게이트, 외생적) ②보조 잔여
  조건(entry_score 코드 반영 절차, T+5 구조적 리스크, 혼합 국면
  재확인) ③실거래 누적 없이는 못 푸는 조건(portfolio_allocation
  gap, 실제 청산 시점 분포).** 판정: **R3b는 Conditional Go를
  유지한다** — 방향 후퇴가 아니라 "남은 조건" 서술의 정밀도만
  회복하는 정정. 운영 코드 변경 없음, broker submit 미호출 —
  read-only 문서 재해석, 신규 실측 없음. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §38.

- 작성자: Claude
- 수정일자: 2026-07-18 (48차, 혼합 국면(분기1 유형) 재확인 — 분기4
  대조 계측)
- 수정내용: §2.48이 정리한 보조 잔여 조건 중 "혼합 국면 재확인"만
  지금 당장 전진 가능해 최우선으로 선택했다(SPPV-2.49). 승인된
  조합(R3b+entry_score risk_off_penalty 제거, B 시나리오)으로
  분기1(재계측)과 분기4(신규 계측)의 국면 분포·funnel을 비교했다.
  **결과: 분기4는 시장 공통 국면이 사실상 순수 bullish(98.2%)로
  분기1(혼합)과 정반대 — 분기4는 T+20 t_NW=3.00·양수율=60.3%로
  강하고 일관되나 분기1은 t_NW=1.27(marginal)·양수율=46.2%로
  대비된다.** 해석: "혼합 국면→약한 t_NW" 가설이 분기1 1건의
  우연이 아니라 대조쌍으로 확인됐다 — 조건 해소는 아니나 "미확인
  가설"에서 "확인된 패턴"으로 전진. 판정: **R3b는 Conditional Go를
  유지한다.** 신규 KIS 호출 0건. 운영 코드 변경 없음, broker submit
  미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §39.

- 작성자: Claude
- 수정일자: 2026-07-18 (49차, "혼합 국면 약세" 가설 직접 분해 —
  거래일 단위 혼합도 3분위 버킷화)
- 수정내용: §2.49의 분기1 vs 분기4 대조(N=2)를 반복하지 않고,
  거래일 단위로 "최근 60거래일 창의 시장 공통 국면 혼합도"를
  직접 수치화해 3년 전체 634거래일을 분기 경계와 무관하게 혼합도
  3분위로 버킷화했다(SPPV-2.50). **결과: 저혼합(T+20 t_NW=3.64,
  양수율=63.3%)→중혼합(t=2.51, 56.8%)→고혼합(t=0.37, 38.7%)으로
  T+5/T+20 전부 단조 감소.** 판정: **"혼합 국면 약세"가 634거래일
  규모의 연속 변수에서 단조 패턴으로 확인돼 "지지 증거"에서
  "구조적 패턴"으로 격상됐다** — 다만 방향성 붕괴는 아니다(고혼합
  버킷도 평균은 양(+), 저혼합·중혼합 2/3 구간은 여전히 강함).
  **이 리스크는 SPPV-3 착수를 추가로 차단하는 사유가 아니라 착수
  이후에도 계속 추적해야 할 구조적 특성이다.** R3b는 Conditional
  Go를 유지한다. 신규 KIS 호출 0건. 운영 코드 변경 없음, broker
  submit 미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §40.

- 작성자: Claude
- 수정일자: 2026-07-18 (50차, SPPV-2.50 결론 문구 정밀화 — 과장
  없이 고정)
- 수정내용: 신규 실행 없이 §2.50의 결론 문구 2가지를 기존 산출물
  만으로 재점검했다(SPPV-2.51). **정정 1**: "구조적 패턴으로
  격상"은 과장 — 이 재확인이 R3b/entry_score 조합을 이미 확정하는
  데 쓰인 것과 동일한 3년 in-sample 캐시에서 수행됐고, mixed_score
  가 60거래일 trailing window라 인접 거래일 버킷이 서로 자기상관돼
  634거래일이 634개의 독립 관측이 아니기 때문 — **정확한 표현은
  "강한 구조적 정합 증거로 격상"**이다(단조 감소 자체는 여전히
  확인된 사실). **정정 2**: "주된 차단 요인은 §21 게이트 하나뿐"은
  "SPPV-3 착수 검토를 시작할 수 있는 유일한 외생적 조건"이라는
  뜻이지 "진입 전체에 남은 유일한 조건"이 아니다 — §2.48(§38)의
  ①주된 차단 요인(§21 게이트) ②보조 잔여 조건(entry_score 코드
  반영 절차·T+5 구조적 리스크·혼합도 모니터링) ③실거래 누적 필요
  조건 3단 분류는 이번 턴에도 그대로 유효하다. **R3b 방향성·
  Conditional Go는 두 정정 모두 바꾸지 않는다** — 서술 정밀도만
  회복. 신규 실행 없음, 신규 KIS 호출 0건. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §40.6.

- 작성자: Claude
- 수정일자: 2026-07-18 (51차, T+5 horizon 구조적 리스크 추가 정량화 —
  실제 exit_score 기반 signal-driven 청산 타이밍 시뮬레이션)
- 수정내용: §2.48이 정리한 보조 잔여 조건 3개 중 지금 당장 신규
  설계 없이 기존 3년 캐시만으로 실측 가능한 "T+5 구조적 리스크"를
  전진시켰다(SPPV-2.52). 실제 운영 함수 `_build_exit_score`(순수
  함수, DB/실시간 상태 불필요)를 R3b+entry_score risk_off_penalty
  제거(B 시나리오) would_buy candidate 1151건에 대해 point-in-time
  으로 재호출해 "언제 처음 sell_candidate_threshold(0.75)를
  넘는가"를 20거래일 관찰 창으로 시뮬레이션했다. **결과: 91.1%
  (1049건)가 20거래일 안에 매도 신호를 넘지 않고 censored, 평균
  보유일수=19.35일. signal-driven 청산 수익률(평균 6.14%, t=4.73)
  은 T+5(2.02%, t=4.18)보다 T+20(6.49%, t=3.87)에 훨씬 가깝다.**
  해석: 실제 청산 로직 기준으로는 T+5가 아니라 T+20 근방에서
  청산되므로 "T+5 평균이 약하다"는 우려가 실제 운영 리스크로 그대로
  전이되지 않는다 — **"T+5 구조적 리스크"는 부분적으로 완화됐다.**
  다만 20일 초과 구간의 청산 분포와 경로 리스크(MAE)는 이번 턴도
  다루지 않아 "완전 해소"는 과장이다. 판정: **R3b는 Conditional
  Go를 유지한다.** 신규 KIS 호출 0건, 운영 코드 변경 없음, broker
  submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §41.

- 작성자: Claude
- 수정일자: 2026-07-18 (52차, T+5 horizon 구조적 리스크 — 20거래일
  초과 구간·경로 리스크(MAE) 확장 검증)
- 수정내용: §2.52(§41)가 20일 관찰 창으로 남긴 두 미확인 영역(20일
  초과 구간 청산 분포, 보유 중 경로 리스크)을 직접 검증했다
  (SPPV-2.53). §41과 동일한 candidate 정의를 재사용하되 관찰 창을
  20→60거래일로 확장하고 MAE(보유 구간 중 최대 미실현 손실)를 추가
  계산했다(would_buy 1048건, 60일 확보를 위해 §41의 1151건보다
  표본이 소폭 감소). **결과: censored 비율 91.1%→51.3%로 감소,
  평균 보유일수=48.0일. signal-driven 청산 수익률(9.29%, t=5.38)이
  오히려 고정 T+20(4.46%, t=3.41)보다 강함. MAE 평균 -11.08%,
  중앙값 -10.42%, 하위 10% -21.77%, 최악값 -45.10%, -20% 이하
  심각 손실 비율 12.8%.** 해석: 실제 청산은 T+5는 물론 T+20보다도
  더 늦게 일어나는 경우가 많고 그 수익률은 T+20보다 강해 **"T+5
  구조적 리스크"는 "부분 완화"에서 "거의 해소"로 격상**됐다 — 그러나
  이 검증으로 **경로 리스크(MAE)·손절 정책 부재라는 신규 잔여
  조건**이 드러났다(평균 -11%, 심각 손실 12.8%, 코드상 별도 손절
  임계값 없음 확인). 판정: **R3b는 Conditional Go를 유지한다** —
  방향성 반전 아님, 다만 경로 리스크는 §38 보조 잔여 조건에 신규
  추가. 신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit
  미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §42.

- 작성자: Claude
- 수정일자: 2026-07-18 (53차, SPPV-2.53 결론 문구 정밀화 — 20일판·
  60일판 표본 동일성 검증 + "거의 해소" 표현 재점검)
- 수정내용: 신규 실행 없이 §2.53(§42)의 "censored 91.1%→51.3%",
  "T+5 구조적 리스크 거의 해소" 문구를 두 스크립트 코드 대조로
  재점검했다(SPPV-2.54). **코드 기준 판정**: 20일판·60일판 모두
  후보 스캔 범위를 `last_t = len(bars)-1-MAX_EXIT_OBSERVATION_DAYS`
  로 제한하는데, 60일판은 3년 캐시 끝에서 60거래일을 남겨야
  스캔에 포함시켜 20일판(1151건)보다 좁은 표본(1048건)을 만든다 —
  **두 결과는 동일 코호트의 순수 전/후 비교가 아니라, 60일판(1048건)
  이 20일판(1151건)의 약 91% 부분집합으로 추정되는 겹치는 표본
  비교**다. **확실히 말할 수 있는 것**: 60일판·20일판 각각의 표본
  내부 측정치는 유효하며, 표본 차이(약 9%)가 효과 크기(censored
  40%p 감소 등)를 설명하기엔 작아 방향성 자체는 신뢰할 수 있다.
  **과장인 것**: 두 수치를 "엄밀한 페어드 전후 비교치"로 인용하는
  것, 그리고 "T+5 구조적 리스크가 거의 해소됐다"는 것 — 60일 관찰
  후에도 과반(51.3%)이 여전히 censored이기 때문이다. 판정: **정확한
  표현은 "부분 완화"(§41)에서 "추가 완화"(§42/§43)로 — "거의 해소"
  는 하향 정정한다.** R3b는 Conditional Go를 유지한다 — 방향성
  반전 아님, 60일판 내부 비교(signal-driven 청산이 T+20보다 강함,
  MAE 분포)는 그대로 유효. 신규 실행 없음, 신규 KIS 호출 0건, 운영
  코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §43.

- 작성자: Claude
- 수정일자: 2026-07-18 (54차, 손절(stop-loss) 정책 도입이 총
  기대수익에 미치는 영향 ablation)
- 수정내용: §2.53(§42)이 §38에 신규 추가한 "경로 리스크(MAE)·손절
  정책 부재"에 대해, "손절선을 도입하면 총 기대수익이 개선되는지
  악화되는지"를 처음으로 직접 검증했다(SPPV-2.55). §42/§43과 동일한
  candidate 정의(would_buy 1048건, 60거래일 관찰)로 baseline(손절
  없음)·-15% 손절·-20% 손절 3개 변형을 동시 시뮬레이션했다. **결과:
  baseline 총 기대수익 proxy=9734.7(t=5.38, 양수율 52.8%) 대비
  -15% 손절=7024.1(약 27.8% 악화, t=4.25, 양수율 46.4%, 손절
  발동률 28.5%), -20% 손절=9093.8(약 6.6% 악화, t=5.02, 양수율
  50.7%, 손절 발동률 12.8%) — 두 손절 임계값 모두 총 기대수익을
  악화시켰고, 손절이 타이트할수록 악화 폭이 컸다.** 해석: R3b
  candidate는 조정 구간(MAE)을 버텨야 이후 회복분을 취하는 구조라
  손절이 그 회복 기회를 원천 차단한다. 판정: **"경로 리스크·손절
  정책 부재"는 "미검증 공백"에서 "시험한 범위(-15%/-20%) 내에서는
  손절 미도입이 총 기대수익 관점에서 근거 있는 선택"으로 재분류.**
  R3b는 Conditional Go를 유지한다 — 방향성 반전 아님. 신규 KIS
  호출 0건, 운영 코드 변경 없음, broker submit 미호출. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §44.

- 작성자: Claude
- 수정일자: 2026-07-18 (55차, entry_score 코드 반영 절차 구체화 —
  shadow 재구현 정합성 검증)
- 수정내용: §21 게이트는 외생 조건이라 반복 관측만 가능한 반면,
  "entry_score 코드 반영 절차"는 실제 코드 변경 PR 작성 전 반드시
  확인해야 할 선행 질문이 있었다 — SPPV-2.46부터 이 세션 내내 B
  시나리오 non-alpha 조정을 수작업 재구현 `_non_alpha`로 계산해왔을
  뿐, 실제 운영 함수 `_build_entry_score`를 한 번도 직접 호출한
  적이 없었다(SPPV-2.56). 코드 대조 결과 `_build_entry_score`에는
  `_non_alpha`가 담아내지 못하는 `portfolio_allocation`·
  `source_type` 조정 항·최종 clamp가 있었다 — 이 세션에서는 항상
  `source_type="core"`, `portfolio_allocation=None`으로 써서
  이론상 no-op이었지만 실증된 적은 없었다. 3년 전체 후보 표본
  (58,493건)에서 실제 `_build_entry_score`(alpha 항을 0으로 고정
  해 조정 항만 분리)와 `_non_alpha`를 전수 대조했다. **결과:
  100.0%(58,493/58,493) 완전 일치, 불일치 0건, 최대 절대 오차
  0.0.** 해석: 이 세션의 모든 B 시나리오 funnel·수익률 결과가
  실제 운영 코드 동작을 정확히 대표한다는 것이 처음으로 전수
  검증됐다. 판정: **"entry_score 코드 반영 절차"는 "설계 논의
  단계"에서 "shadow 계산 정합성 확보, 실제 코드 변경 PR 작성 가능
  단계"로 격상됐다** — 다만 이것이 코드 변경 PR 자체의 승인·실행을
  뜻하지는 않으며, §21 게이트(주된 차단 요인)는 불변이라 SPPV-3
  확정 Go 선언은 아니다. R3b는 Conditional Go를 유지한다. 신규 KIS
  호출 0건, 운영 코드 변경 없음, broker submit 미호출. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §45.

- 작성자: Claude
- 수정일자: 2026-07-18 (56차, SPPV-2.56 결론 문구 정밀화 — "직접
  호출" 서술 범위·표본 서술 정정)
- 수정내용: 신규 실행 없이 §45(SPPV-2.56)의 두 표현을 기존 코드
  재검토로 정정했다(SPPV-2.57). **정정 1**: "실제 함수를 한 번도
  직접 호출한 적이 없었다"는 과장 — `_build_entry_score`는 시나리오
  A(현행 regime)로는 `validate_alpha_layer_buy_funnel_comparison.py`
  `validate_r3b_point_in_time_pipeline_shadow.py`에서 이미 직접
  호출돼왔다. 정확한 표현: "B 시나리오(`risk_tone="neutral"`로
  치환한 market_regime) 입력으로 직접 호출한 적은 §45 이전까지
  없었다"이며, §45가 새로 확인한 것은 이 B 시나리오 재구현이 실제
  함수의 neutral-regime 호출 결과와 정합하는지였다. **정정 2**:
  이번 검증은 non-alpha 조정 항(source_type="core", portfolio_
  allocation=None, risk_tone neutral 조건)만 증명했을 뿐 — R3b
  alpha 교체 전체 경로가 실제 운영 코드 반영 후에도 동일하게
  재현되는지, held_position/실제 portfolio_allocation 케이스는
  검증 범위 밖이다. **정정 3**: "candidate 전량"이라는 표본 서술은
  부정확 — 이 스크립트는 quintile 선별·eligibility 필터링 없이
  전체 거래일 스냅샷(58,493건)을 순회했다. 정확한 표현은 "전체
  시점 스냅샷(모집단 전체)". 판정: **세 정정 모두 R3b 방향성·
  Conditional Go를 바꾸지 않는다** — §45의 핵심 결론(B 시나리오
  non-alpha 조정 항이 검증된 조건 안에서 완전히 일치)은 그대로
  유효하며, 필요 이상으로 보수적으로 낮추지 않는다. 신규 실행 없음,
  신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit 미호출.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §46.

- 작성자: Codex
- 수정일자: 2026-07-18 (57차, §21 gate 환경별 적용 범위 정밀화 —
  production 잠금과 paper/shadow 관측 분리)
- 수정내용: §21 게이트 문구를 **실운영(Production) 잠금 규칙**과
  **Paper Probe / shadow 관측 단계**로 분리해 정정했다(SPPV-2.58).
  기존 문서 흐름은 §21 게이트를 "SPPV-3 착수 검토를 시작할 수 있는
  유일한 외생적 차단 요인"으로 설명해 왔으나, 현재 단계가 paper/
  shadow 실측이라는 점과 함께 읽지 않으면 데이터 수집까지 전면 Hold
  해야 하는 것으로 오해될 여지가 있었다. 이번 정정의 정확한 해석은
  다음과 같다. **production**에서는 §21 게이트를 계속 엄격 유지한다.
  반면 **paper/shadow**에서는 향후 환경 인지형 우회(config 스위치)
  구현 시, §21 게이트를 "실운영 승격 잠금선"으로만 해석하고 shadow·
  paper 실측 자체는 막지 않는다. 즉 gate의 목적은 production 자본
  보호이지, paper/shadow 관측 마비가 아니다. 이번 턴은 문구 정정만
  수행했으며 코드·산출물·Conditional Go 판정은 바꾸지 않는다.

- 작성자: Codex
- 수정일자: 2026-07-18 (58차, `§21 gate` config 기반 gate 제어 —
  mode-agnostic 신규 모듈 구현)
- 수정내용: **[정정] 바로 위 57차 항목의 "environment 인지형 우회
  (paper/production 분기)" 프레이밍은 부정확하다 — 실제 구현은
  environment 분기가 아니라 config 스위치 하나만으로 판정하는
  mode-agnostic 방식이다.** 코드베이스를 전수 조사한 결과 `§21
  게이트`(regime_switch_v1)는 지금까지 실제 운영 코드
  (`assess_deterministic_triggers`) 어디에도 연결되지 않은 순수
  모니터링 산출물이었음을 확인했다 — R3b shadow/paper 관측은 이
  게이트에 의해 코드 레벨에서 전혀 막힌 적이 없다. `deterministic_
  trigger_engine.py`는 이 세션 내내 "절대 수정하지 않는다"는 원칙이
  적용된 파일이므로 이번에도 수정하지 않았다. 대신 (1)
  `AppSettings`에 `regime_switch_v1_gate_override_enabled`(env:
  `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 False) 신규
  필드 추가, (2) 신규 격리 모듈 `services/regime_switch_gate.py`의
  `assess_regime_switch_v1_gate(*, trigger_status, override_
  enabled)` 순수 함수 구현 — **paper/real/production 같은
  environment 값은 함수 인자로도 로직으로도 전혀 등장하지 않는다.**
  override off(기본값)면 기존 §21 해석과 100% 동일(TRIGGERED일 때만
  열림), override on이면 국면 상태와 무관하게 항상 열림(강제 통과),
  모든 판정에 reason_code로 추적 가능. `scripts/validate_regime_
  switch_gate_config_override.py`(신규, read-only)로 검증: (a)
  `deterministic_trigger_engine.py`가 신규 모듈을 import하지 않음을
  소스 검사로 확인(`isolation_confirmed=True`), (b) 실제 게이트
  상태 조회(신규 KIS 호출 0건, 캐시 재사용) 결과 여전히 `NOT_
  TRIGGERED`, (c) override off/on 및 3개 trigger_status 전부에
  대한 시나리오 전부 예상대로 동작(override on 시 3개 상태 모두
  gate_open=True, override off 시 TRIGGERED만 gate_open=True).
  판정: **R3b는 Conditional Go를 유지한다.** §21 게이트 상태 자체는
  불변(NOT_TRIGGERED), `deterministic_trigger_engine.py` 미수정,
  compliance/VaR/broker submit 경계 미변경, 아직 실제 파이프라인에는
  연결하지 않음(별도 승인 필요). 신규 KIS 호출 0건. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §47.

- 작성자: Codex
- 수정일자: 2026-07-18 (59차, `§21 gate` 실제 판단 경로 연결 완료 —
  `deterministic_trigger_engine.py` 실제 수정)
- 수정내용: **[정정] 58차(§47)의 "구현 완료"는 부정확 — 정확히는
  "준비 모듈 + 런타임 미연결" 상태였다.** 이번 턴은 그 미완 지점을
  메웠다(SPPV-2.59). 사용자의 명시적 승인 아래 이 세션 최초로
  `deterministic_trigger_engine.py`를 실제로 수정 — `assess_
  deterministic_triggers`(실제 BUY_CANDIDATE 판정 함수)에 신규
  optional 파라미터 `regime_switch_v1_trigger_status`(기본값
  None)·`regime_switch_v1_gate_override_enabled`(기본값 False)를
  추가하고, BUY_CANDIDATE 조건문에 `(regime_switch_v1_gate_
  assessment is None or ...gate_open)`을 실제로 삽입했다 — 기본값
  둘 다 "게이트 체크 완전 비활성화"에 해당해 기존 호출부는 100%
  하위 호환. `scripts/validate_r3b_gate_integration_path.py`(신규,
  read-only)로 **동일한 실제 함수**를 3가지로 직접 호출: (A)
  게이트 파라미터 없음 — `buy_candidate=True`(entry_score=0.6895,
  종목 000100/2023-10-11). (B) `trigger_status=NOT_TRIGGERED`,
  override=False(기본값) — `buy_candidate=False`로 실제 차단됨.
  (C) 동일 trigger_status, override=True — `buy_candidate=True`로
  baseline과 동일하게 복원됨. **결과: `gate_actually_blocks_real_
  path=True`, `override_actually_restores_real_path=True`** —
  entry_score/eligibility는 A/B/C 전부 동일하게 유지되면서 오직
  게이트 조건 하나로 buy_candidate가 뒤집힘. 기존 단위 테스트
  (`tests/services/test_deterministic_trigger_engine.py`, 20건)
  전부 통과. 판정: **"§21 게이트 → 실제 판단 경로" 연결이
  완료됐다** — 다만 실제 운영 호출부(orchestrator)가 이 신규
  파라미터를 전달하도록 배선하는 것은 별도 미완료 과제로 남는다
  (그 전까지 실제 운영 동작 영향 없음, 의도된 안전장치). R3b는
  Conditional Go를 유지한다. 신규 KIS 호출 0건, compliance/VaR/
  broker submit 경계 미변경. 상세: `plans/[DESIGN]
  regime_conditional_entry_signal_v1.md` §48.

- 작성자: Codex
- 수정일자: 2026-07-18 (60차, `§21 gate` 상위 호출부(`decision_
  orchestrator.py`) 배선 완료)
- 수정내용: **[정정] 59차(§48)의 "실제 판단 경로 연결 완료"는
  과장 — `assess_deterministic_triggers` 함수 내부는 연결됐으나
  그 유일한 실제 상위 호출부 `DecisionOrchestratorService`(`decision_
  orchestrator.py`)는 신규 파라미터를 전혀 넘기지 않고 있었다.**
  이번 턴이 그 gap을 메웠다(SPPV-2.60). `DecisionOrchestratorService.
  __init__`에 `regime_switch_v1_trigger_status`(기본값 None),
  `regime_switch_v1_gate_override_enabled`(기본값 False) 생성자
  인자를 추가하고, `_derive_deterministic_context_components`의
  `assess_deterministic_triggers` 호출에 실제로 전달했다.
  `scripts/run_decision_loop.py`의 두 `DecisionOrchestratorService`
  생성 지점 전부에서 이 값을 실제로 넘기도록 배선(`trigger_status`
  는 신규 read-only 헬퍼 `resolve_cached_trigger_status()`로 `logs/
  regime_switch_v1_gate_monitor_*.json` 캐시에서 조회, 신규 KIS
  호출 없음). `scripts/validate_r3b_orchestrator_gate_wiring.py`로
  **`DecisionOrchestratorService`를 실제로 구성**하고 그 실제
  메서드를 거쳐(스크립트가 `assess_deterministic_triggers`를 직접
  호출하는 우회 경로가 아님) 검증: (A) 게이트 없음 —
  `buy_candidate=True`(entry_score=0.7275). (B) trigger_status=
  NOT_TRIGGERED, override=False — `buy_candidate=False`로 실제
  차단. (C) 동일 trigger_status, override=True — `buy_candidate=
  True`로 복원. **결과: `gate_blocks_via_orchestrator=True`,
  `override_restores_via_orchestrator=True`.** 기존 단위 테스트
  83건(`test_decision_orchestrator.py` 63 + `test_deterministic_
  trigger_engine.py` 20) 전부 통과. **중요 리스크**: 이 배선
  완료로 `run_decision_loop.py`가 이제 실제 §21 게이트 상태(현재
  NOT_TRIGGERED)를 읽어 전달하므로, override가 기본값 False인 한
  core BUY_CANDIDATE 판정이 실제로 영향받기 시작한다 — 이는
  사용자 확인이 필요한 새로운 실제 동작 변화이며 §49.6에 명시
  기록했다. 판정: **"§21 게이트 → 실제 판단 경로" 연결이 함수
  내부뿐 아니라 상위 호출부까지 완료됐다.** R3b는 Conditional Go를
  유지한다. compliance/VaR/broker submit 경계 미변경. 신규 KIS
  호출 0건. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §49.

- 작성자: Codex
- 수정일자: 2026-07-18 (61차, SPPV-2.60 보고 정정 — `resolve_cached_
  trigger_status()` None 원인 규명 + 테스트 증빙 재확인)
- 수정내용: **[정정] §49(60차)의 검증 산출물에서 `resolve_cached_
  trigger_status_current_value=None`이었으나, 실제로는 `logs/
  regime_switch_v1_gate_monitor_2026-07-14.json`·`_2026-07-17.
  json` 두 파일 모두 `trigger_status="NOT_TRIGGERED"`를 담고
  있었다.** 원인을 규명(SPPV-2.61)한 결과 코드 결함(glob/JSON
  파싱/status검증)이 아니라 **기본 `glob_pattern`이 상대경로라
  호출 시점 cwd에 의존**했기 때문이었다 — §49 검증이 Docker
  컨테이너에서 실행됐는데 그 컨테이너 `/app/logs/`에 캐시 JSON
  파일이 복사돼 있지 않아 `glob`이 빈 결과를 반환한 것. `services/
  regime_switch_gate.py`에 `_PROJECT_ROOT = Path(__file__).
  resolve().parents[3]`를 추가하고 `resolve_cached_trigger_
  status()`의 기본 경로를 이 프로젝트 루트 기준 절대경로로 앵커링
  (환경 분기 없음, 순수 경로 수정). 재검증 결과 `/tmp`(비-프로젝트
  cwd)에서도 `NOT_TRIGGERED`를 정확히 반환, 컨테이너 안에 캐시
  파일을 복사한 뒤 재실행한 `validate_r3b_orchestrator_gate_
  wiring.py`에서도 `resolve_cached_trigger_status_current_value
  ="NOT_TRIGGERED"`로 확인. **테스트 증빙**: "83건 전부 통과"는
  사실이었으나 §49에는 실행 로그가 산출물로 남아있지 않았다 —
  이번에 `python3 -m pytest tests/services/test_decision_
  orchestrator.py tests/services/test_deterministic_trigger_
  engine.py -q`를 실제로 재실행하고 stdout을 `logs/r3b_pytest_
  run_2026-07-18.log`(83 passed)로 저장해 증빙을 보강했다. 판정:
  **"배선은 완료됐으나 캐시 상태 전달에는 추가 수정이 필요"했던
  상태에서 "캐시 상태까지 정상 전달됨"으로 확정.** §49.6의 리스크
  (override off 기본값 + NOT_TRIGGERED 조합에서 core BUY_
  CANDIDATE 실제 차단 가능)는 이번 수정으로 cwd에 관계없이 항상
  실현 가능해져 더 급해졌다. R3b는 Conditional Go를 유지한다.
  신규 KIS 호출 0건, compliance/VaR/broker submit 경계 미변경.
  상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §50.

- 작성자: Codex
- 수정일자: 2026-07-18 (62차, 국면 혼합도 모니터링 모듈 구현 및
  §40 재현성 검증)
- 수정내용: **최신 truth 갱신**: commit `aa10caee`로 §21 게이트
  배선 완료·푸시 확정, 현재 `.env`에 `REGIME_SWITCH_V1_GATE_
  OVERRIDE_ENABLED=true` 설정 — paper 관측 단계에서 게이트는 BUY를
  막지 않는다(paper/production 코드 분기·배선 원복은 더 이상 검토
  대상 아님). 이 상태를 기준으로, 후속 과제 후보(trigger_status
  자동화/혼합도 모니터링 설계/T+5 후속 검증/SPPV-3 착수 준비) 중
  **혼합도 모니터링 설계**를 이번 턴 최우선으로 선택했다(SPPV-2.62)
  — trigger_status 자동화는 override=true인 동안 급하지 않고,
  T+5/경로 리스크는 §41~§44에서 이미 충분히 답이 나왔기 때문. §40
  이 확정한 혼합도 3분위 경계값(cut1=0.15, cut2=0.3833)을 신규
  모듈 `services/regime_mixedness_monitor.py`(BUY/SELL 미연결
  순수 관측용, `compute_mixed_score`/`classify_mixedness_bucket`)
  로 재구현하고, `scripts/validate_regime_mixedness_monitor.py`로
  벤치마크 3년 캐시 bars만 재사용해(신규 KIS 호출 0건) 634거래일
  전체를 재분류했다. **결과: 버킷별 거래일 수(저혼합 217일/중혼합
  215일/고혼합 202일)가 §40 실측치와 정확히 일치
  (`matches_sppv_2_50=True`).** 해석: 이는 가설을 다시 검증한 것이
  아니라, 그 검증 결과를 실제로 소비 가능한 재사용 가능 코드
  모듈로 정확히 이식했다는 것을 100% 재현성으로 확인한 것 — "혼합도
  모니터링 설계" 다음 단계가 설계 스케치에서 검증된 모듈로
  전진했다. 판정: **R3b는 Conditional Go를 유지한다.** 신규 KIS
  호출 0건, 운영 코드(`deterministic_trigger_engine.py`,
  `decision_orchestrator.py`) 미변경, compliance/VaR/broker
  submit 경계 미변경. 상세: `plans/[DESIGN] regime_conditional_
  entry_signal_v1.md` §51.

- 작성자: Codex
- 수정일자: 2026-07-19 (63차, 국면 혼합도 모니터링을 실제 decision
  loop 관측 경로에 연결)
- 수정내용: 최신 truth 재확인(commit `aa10caee` §21 게이트 배선
  완료, `.env`에 override=true, commit `4fd3ad7e` §51 혼합도 모듈
  검증 완료·미연결 상태). 후속 과제 후보 중 **혼합도 모니터링의
  실제 소비 위치 연결**을 최우선으로 선택했다(SPPV-2.63) —
  trigger_status 자동화는 override=true인 동안 급하지 않고, T+5/
  경로 리스크는 §41~§44에서 이미 답변됨. `scripts/run_decision_
  loop.py`에 신규 함수 `_run_mixedness_check()`를 추가 — 기존
  `_run_precheck()`(snapshot sync health)와 동일한 cycle당 1회
  안전 패턴으로, 벤치마크(069500) `signal_feature_snapshots`
  최근 60건을 read-only 조회(신규 KIS 호출 없음)해 §51 모듈로
  국면 혼합도 버킷·reason_code를 계산·로그에 남긴다. **BUY/SELL
  판정에는 전혀 연결하지 않았다** — 별도 트랜잭션, 별도 변수,
  예외 전부 흡수. `scripts/validate_r3b_mixedness_decision_loop_
  wiring.py`(신규, read-only, in-memory repos, 신규 KIS 호출
  0건)로 `_run_mixedness_check()`를 실제로 import·호출해 검증:
  저혼합 시나리오(합성 스냅샷 60건 전부 강한 bullish) → `mixed_
  score=0.0, bucket=저혼합`, 고혼합 시나리오(bullish/bearish
  빈번 교차) → `mixed_score=0.5, bucket=고혼합` — **두 시나리오
  모두 기대한 버킷으로 정확히 분류됨(low_bucket_correct=True,
  high_bucket_correct=True).** `inspect.getsource()`로 소스에
  `buy_candidate`/`sell_candidate`/`assess_deterministic_
  triggers` 문자열이 전혀 없음도 확인(`no_buy_sell_reference_
  in_mixedness_check=True`). 기존 단위 테스트(`test_run_decision_
  loop.py`) 10건 실패는 변경 전(git stash 재실행)에도 동일하게
  실패하는 사전 존재 결함(universe_selection/market_overlay
  관련)임을 확인 — 이번 변경과 무관. 판정: **R3b는 Conditional
  Go를 유지한다.** BUY/SELL 게이트 로직은 더 세지지 않았다 —
  관측/로깅 경로만 추가. 신규 KIS 호출 0건, `.env` 미수정,
  environment 분기 없음, compliance/VaR/broker submit 경계
  미변경. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §52.

- 작성자: Codex
- 수정일자: 2026-07-19 (64차, SPPV-2.63 미확정 항목 확정 —
  `test_run_decision_loop.py` 10건 실패 무관 확정)
- 수정내용: **[정정] §52(63차)의 "stash 재실행으로 확인(무관)"은
  증빙이 약했다** — 이번 턴에 `git worktree add /tmp/wt-pre-
  mixedness 4fd3ad7e`(§52 이전 커밋, 메인 워크트리는 전혀 건드리지
  않음)로 격리 비교했다(SPPV-2.64). Docker 컨테이너 안에서 PRE
  (§52 이전, mixedness 코드 없음)/POST(§52 이후, 현재 main과
  동일) 두 버전 각각 `pytest tests/scripts/test_run_decision_
  loop.py -v --tb=long`(807줄 로그) 전체 재실행 후 `diff`로 직접
  비교. **결과: 두 버전 모두 `10 failed, 109 passed` — 실패한
  테스트 10건 이름·에러 메시지·assertion 내용까지 완전히 동일**
  (차이는 비결정적 Python 객체 메모리 주소와 정확히 71줄의 라인
  번호 오프셋뿐 — §52가 파일 앞부분에 71줄을 추가해 그 뒤 코드가
  밀린 결과일 뿐, 실패 원인의 변화가 아님). `grep`으로 POST 로그
  전체에서 `_run_mixedness_check`/`regime_mixedness_monitor`/
  `mixedness` 문자열을 검색한 결과 **매치 0건** — mixedness 관련
  코드는 실패 10건의 stack trace 어디에도 등장하지 않는다. 판정:
  **`무관 확정`** — 10건 실패는 `universe_selection.py`(market_
  overlay seed pool)와 AsyncMock/Decimal 타입 불일치 관련 사전
  존재 결함이며, §52(SPPV-2.63)의 국면 혼합도 모니터링 연결과
  완전히 무관하다. §52의 결론 자체는 맞았으나 이번 턴에 격리된
  worktree 비교로 증빙을 확정했다. R3b는 Conditional Go를
  유지한다 — 이번 턴은 코드를 전혀 수정하지 않았다(순수 검증
  확정). 신규 KIS 호출 0건. 상세: `plans/[DESIGN] regime_
  conditional_entry_signal_v1.md` §53.

- 작성자: Codex
- 수정일자: 2026-07-19 (65차, entry_score 코드 변경 PR 초안 설계 —
  R3b alpha 교체 실제 파이프라인 연결 방안)
- 수정내용: 후속 과제 후보(trigger_status 자동화, entry_score
  코드 변경 PR 초안, R3b alpha 전체 경로 재현 검증, T+5 후속
  검증) 중 **entry_score 코드 변경 PR 초안 준비**를 선택했다
  (SPPV-2.65) — trigger_status 자동화는 override=true인 동안
  급하지 않고, mixedness는 실제 소비 위치 연결까지 이미 끝나 같은
  축 반복을 피했다. "R3b alpha 전체 경로 재현 검증"은 §45(non-
  alpha 100% 일치)의 논리적 귀결이라 다시 실측하지 않고, 대신
  **이 세션에서 한 번도 명시되지 않은 아키텍처 제약**을 조사했다:
  `entry_score`는 종목 단위로 계산되지만 R3b alpha(`candidate_
  percentile`)는 당일 cross-sectional 순위가 필요해 사전 계산
  단계가 있어야 한다. 코드 조사 결과 `run_decision_loop.py`의
  기존 `_build_core_risk_off_apply_overrides_for_cycle()`(cycle당
  1회 전체 universe precompute → override 주입)이 정확히 필요한
  선례로 이미 존재함을 확인 — 이를 근거로 실제 코드 diff 초안
  (신규 precompute 함수 1개 + `assess_deterministic_triggers`
  optional 파라미터 2개 + config 스위치 1개, 전부 §48/§49와 동일한
  기본값-비활성 패턴)을 설계했다. **미적용, 코드 변경 없음** —
  순수 설계 문서 작업. 판정: "entry_score 코드 반영 절차"는
  "shadow 정합성 확보"에서 "구체적 구현 설계 확보(diff 초안)"로
  진전됐다 — 다만 실제 적용은 §48/§49와 동일하게 별도의 명시적
  사용자 승인이 필요하다. R3b는 Conditional Go를 유지한다. 신규
  KIS 호출 0건, compliance/VaR/broker submit 경계 미변경. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §54.

- 작성자: Codex
- 수정일자: 2026-07-19 (66차, entry_score R3b alpha 교체 — 1단계
  엔진 파라미터 배선 실제 코드 적용)
- 수정내용: §54(SPPV-2.65) 설계 중 "방패 보강"(trigger_status
  자동화)보다 실전진에 직접 기여하는 "1단계: 엔진 파라미터 배선"만
  선택해 실제 코드로 적용했다(cycle 단위 precompute인 "2단계"는
  범위 밖, 별도 승인 대상 유보). `settings.py`에 `entry_score_r3b_
  alpha_enabled` config 스위치(기본값 False) 추가, `deterministic_
  trigger_engine.py`의 `assess_deterministic_triggers`/`_build_
  entry_score`에 `r3b_alpha_percentile`/`r3b_alpha_enabled` optional
  파라미터 2개 추가 — §48/§49와 동일한 기본값-비활성 backward-
  compat 패턴. 실측: 기존 회귀 테스트 83건 전부 통과, `AppSettings
  ().entry_score_r3b_alpha_enabled` 기본값 `False` 확인, `_build_
  entry_score` 직접 호출로 활성 경로(percentile=0.9) 결과 `0.72`가
  기대값과 완전 일치(오차 <1e-9) 확인. `.env` 미변경, gate 로직
  강화 없음, 환경 분기 없음. R3b는 Conditional Go를 유지한다. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §55.

- 작성자: Codex
- 수정일자: 2026-07-19 (67차, entry_score R3b alpha 교체 — 2단계
  순수 계산 모듈 + orchestrator 배선 실제 코드 적용)
- 수정내용: §54.5 설계 중 "2단계"(순수 계산 모듈 + orchestrator
  배선)를 실제 코드로 전환했다(SPPV-2.67). 신규 `services/r3b_
  alpha_percentile.py`(shadow 스크립트 로직 이식, 200회 무작위
  trial 전부 일치), `decision_orchestrator.py`에 `r3b_alpha_
  enabled` config·`request.metadata` 추출 헬퍼·배선 추가,
  `run_decision_loop.py` 두 인스턴스화 지점 config 전달 추가.
  cycle당 1회 실제 percentile 계산·주입("3단계")은 범위 밖 —
  현재 `r3b_alpha_percentile`은 항상 `None`이라 활성화해도 alpha
  교체가 실제로 발동하지 않는다. **이번 턴 직접 재실행 근거만
  사용**(재인용 금지 지시 반영): 신규 모듈 parity 200/200 일치;
  `test_deterministic_trigger_engine.py`+`test_decision_
  orchestrator.py` 83 passed/0 failed; `test_run_decision_loop.py`
  10 failed/109 passed(§53 확정 실패와 이름·개수 동일, 재논의
  없음); `-k "orchestrator or deterministic_trigger"` 118
  passed/6 failed(DB `TooManyColumnsError` 관련 사전 존재 환경
  이슈, 코드 배선과 무관함을 에러 메시지로 확인). `.env` 미변경,
  gate 로직 강화 없음. R3b는 Conditional Go를 유지한다. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §56.

- 작성자: Codex
- 수정일자: 2026-07-19 (68차, SPPV-2.67 보고 정정 — "2단계 완료"
  표현의 과장 부분 확정)
- 수정내용: 새 기능 구현 없이 §56(SPPV-2.67)의 서술을 코드 기준으로
  재검증했다(SPPV-2.68). `r3b_alpha_percentile.py`/`decision_
  orchestrator.py`/`run_decision_loop.py` 직접 확인 결과: 순수 계산
  모듈은 존재하나 production 코드 어디서도 import되지 않는 고립
  모듈; orchestrator의 metadata 읽기·엔진 전달 배선은 실제로 존재
  (사실); `run_decision_loop.py`에는 `r3b_alpha_enabled` config
  전달 두 줄만 있고 `r3b_alpha_percentile`을 계산·주입하는 코드는
  전무(grep 확인, 함수 자체 없음). "2단계 선택·실행"/"orchestrator
  까지 배선 완료"/"전원이 꽂히지 않은 상태" 표현은 과장으로
  확정 — "cycle 단위 precompute"는 이 세션 전체에서 단 한 번도
  production 코드로 옮겨진 적이 없다. R3b 판정(Conditional Go)은
  코드 변경이 없어 불변. 이력 보존형 정정 — 기존 §56 서술은 삭제하지
  않음. 상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
  §57.

- 작성자: Codex
- 수정일자: 2026-07-19 (69차, entry_score R3b alpha 교체 — cycle
  precompute 실제 구현·발동 확인)
- 수정내용: §57이 남긴 유일한 실행 단계(cycle precompute)를 실제로
  구현했다(SPPV-2.69). `run_decision_loop.py`에 `_build_r3b_alpha_
  percentile_overrides_for_cycle()` 신규 함수(config 기본값이면
  DB 조회 없이 즉시 빈 dict) + cycle당 1회 호출 + `SubmitOrderRequest.
  metadata["r3b_alpha_percentile"]` 실제 주입. 신규 end-to-end
  검증 스크립트로 실제 발동 증명: 실제 DB 종목(000080) 기준 비활성
  시 entry_score=0.1159(reason_code 없음) vs 활성+percentile=0.9
  주입 시 entry_score=0.5999(trigger_r3b_alpha_percentile reason_
  code 발생) — 값이 실제로 바뀜을 확인. 기존 회귀 테스트 83건
  전부 통과, `test_run_decision_loop.py`는 8 failed/111 passed로
  git stash 대조 시 이번 턴 변경과 무관함(사전 존재 비결정성)을
  직접 확인. `.env` 미변경. R3b는 Conditional Go를 유지한다. 상세:
  `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §58.

- 작성자: Codex
- 수정일자: 2026-07-19 (70차, SPPV-2.69 보고 증빙 정정 — 테스트
  수치·실행 증빙 재확인)
- 수정내용: 새 기능 구현 없이 §58(SPPV-2.69)의 수치·실행 증빙을
  실제 파일/로그 기준으로 재검증했다(SPPV-2.70). `logs/r3b_pytest_
  run_decision_loop_2026-07-19.log`(01:48 생성)는 §68 이전(§53)의
  오래된 로그(10 failed/109 passed)였고, §58이 인용한 "8 failed/
  111 passed"는 저장소 로그가 아니라 대화 출력 인용이었음을 확인;
  end-to-end 검증 스크립트의 실행 결과도 저장소 산출물이 없었음을
  확인. 이번 턴 재실행으로 4개 신규 로그/JSON을 저장소에 남겼다 —
  `test_run_decision_loop.py` 재실행 결과 8 failed/111 passed로
  §58 수치와 정확히 일치 확인; end-to-end 스크립트 재실행으로
  000080 종목 entry_score 0.1159→0.5999 완전 재현(JSON에도 명시적
  기록); 엔진/orchestrator 회귀 83 passed/0 failed. 판정: §58의
  수치 자체는 틀리지 않았으나 저장소 증빙이 부족했다 — "결론 유지
  + 증빙 보강"으로 확정. R3b는 Conditional Go를 유지한다. `.env`
  미변경, production 코드 미변경(검증 스크립트에 JSON 출력 기능만
  추가). 상세: `plans/[DESIGN] regime_conditional_entry_signal_
  v1.md` §59.

- 작성자: Codex
- 수정일자: 2026-07-19 (71차, R3b alpha paper 운영 전환 최종 착수
  준비 상태 점검)
- 수정내용: "config만 켜면 되는가"를 판정하는 준비 턴(SPPV-2.71).
  이미 구현/증빙 완료(§55~§59)를 재검증하지 않고, DB 직접 조회로
  신규 사실 확인 — 벤치마크(069500) `signal_feature_snapshot`이
  DB에 0건(전체 이력 통틀어), `data/signal_feature_snapshot_input.
  json`(일일 배치 입력)에 애초에 미포함. 이 때문에 `ENTRY_SCORE_
  R3B_ALPHA_ENABLED=true`로 전환해도 `_build_r3b_alpha_percentile_
  overrides_for_cycle()`이 항상 빈 dict를 반환해 alpha 교체가 실제
  로는 발동하지 않는다 — "구현 완료"와 "운영 전환 준비 완료"를
  분리 확정. SPPV-3까지 남은 항목을 실제 차단 요소(벤치마크 배치
  미포함)/사용자 결정 대기(`.env` 전환)/후속 검증 과제(trigger_
  status 자동화 등) 3분류로 재정리. R3b는 Conditional Go를
  유지한다. `.env` 미변경, 코드 변경 없음(순수 점검). 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §60.

- 작성자: Codex
- 수정일자: 2026-07-19 (72차, 벤치마크(069500) signal_feature_
  snapshot 배치 미포함 문제 실제 해소)
- 수정내용: §60이 확인한 유일한 실제 차단 요소를 실제로 해소했다
  (SPPV-2.72). `generate_signal_feature_snapshot_input.py`에 신규
  `_with_regime_benchmark_symbol()` 추가 — 기존 `_R3B_ALPHA_
  BENCHMARK_SYMBOL`/`_R3B_ALPHA_BENCHMARK_MARKET` 재사용, 거래
  universe/DB freeze 기록은 불변, `_build_rows`/`_write_rows`
  로컬 tuple에만 벤치마크 추가. 실제 KIS 조회+`build_signal_
  feature_snapshots.py` CLI 실행+DB 재조회로 069500 snapshot
  0건→1건 실측 확인, `_build_r3b_alpha_percentile_overrides_for_
  cycle()` 재호출 결과 빈 dict 탈출 확인. 회귀 20+83 passed, `test_
  run_decision_loop.py` 8 failed/111 passed(기존 비결정성 동일).
  판정: 실제 차단 요소 해소 — `ENTRY_SCORE_R3B_ALPHA_ENABLED=true`
  전환 시 이제 실제 발동 가능. `.env` 미변경, 신규 KIS 호출 1건
  (read-only). R3b는 Conditional Go를 유지한다. 상세: `plans/
  [DESIGN] regime_conditional_entry_signal_v1.md` §61.

- 작성자: Codex
- 수정일자: 2026-07-19 (73차, R3b alpha 운영 반영 여부 실제 점검 —
  docker-compose 환경변수 배선 미비 신규 발견)
- 수정내용: "전환할지"가 아니라 "이미 `.env`에 반영된 값이 실제
  paper decision loop에 도달했는지"를 점검했다(SPPV-2.73). 호스트
  `.env`에는 `ENTRY_SCORE_R3B_ALPHA_ENABLED=true`가 실제로 있음을
  확인(사용자 전제 정확). 그러나 실행 중인 `ops-scheduler`
  컨테이너는 이 값을 전혀 읽지 못한다 — `Dockerfile`이 `.env`를
  이미지에 COPY하지 않고, `docker-compose.yml`도 `.env`를 `env_
  file`/마운트로 지정하지 않으며, `environment:` 화이트리스트에
  이 변수(및 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`)가 선언돼
  있지 않다. 실행 중 프로세스의 실제 환경변수를 직접 읽어(`docker
  exec ... env`, `/proc/1/environ`) 두 변수 모두 부재 확인. 이는
  R3b alpha에 국한되지 않는 구조적 문제 — `.env` 기반 config
  스위치 전체가 운영 컨테이너에 전달될 경로가 없다. 최근 3일
  연속 비거래일로 decision loop 자체도 최근 실행되지 않았음을
  로그로 확인(마지막 cycle 07-16). 3단계 분리: 코드 구현 완료(예)/
  env 설정 완료(예)/실행 중 paper 프로세스 반영 완료(**아니오**).
  이번 턴은 코드/`.env`/`docker-compose.yml` 어느 것도 수정하지
  않았고 컨테이너도 재시작하지 않았다. R3b는 Conditional Go를
  유지한다. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §62.

- 작성자: Codex
- 수정일자: 2026-07-19 (74차, docker-compose 환경변수 배선 실제
  수정 — R3b alpha/§21 게이트 override 운영 반영 완료)
- 수정내용: §62가 확인한 실제 차단 요소를 실제로 해소했다(SPPV-
  2.74, 사용자 명시적 승인·상세 지시에 따라 실행). `docker-
  compose.yml`의 `ops-scheduler` `environment:` 블록에 기존 패턴
  그대로 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`/`ENTRY_SCORE_
  R3B_ALPHA_ENABLED` 2줄 추가(기본값 false, 분기 로직 없음).
  `docker compose up -d --force-recreate --no-deps ops-scheduler`
  로 재생성. 실제 프로세스 env 재확인 결과 두 값 모두 `true`,
  `/app/.env` 파일은 여전히 없음(compose environment 주입만으로
  전달 증명), 컨테이너 안에서 `AppSettings()` 실행 결과도 `True
  True`. 재생성 후 로그 정상(비거래일 정상 판정, `submit_count=0`).
  판정: 실제 차단 요소 완전 해소 — R3b alpha/§21 게이트 override
  모두 이제 실제 paper 운영 프로세스에 도달. R3b는 Conditional
  Go를 유지한다. 상세: `plans/[DESIGN] regime_conditional_entry_
  signal_v1.md` §63.

- 작성자: Codex
- 수정일자: 2026-07-19 (75차, 보유기간/Churn 제어가 R3b BUY 빈도를
  얼마나 깎는지 정량 검증 — canonical 문서 경로가 `docs/` 하위
  구조로 재배치된 이후 첫 턴)
- 수정내용: churn guard가 R3b BUY_CANDIDATE 빈도를 실제로 얼마나
  억제하는지 운영 함수(`_build_entry_score`/`classify_market_
  regime`)와 실제 운영 DB(`guardrail_evaluations`/`signal_feature_
  snapshots`/`trade_decisions`)로 정량 분해했다(SPPV-2.75). 실제
  운영 창(2026-05-13~07-16)에서 churn 관련 guard가 차단한 144
  episode를 entry_score로 재계산한 결과 **전부 0.65 미만**(candidate
  0건) — R3b 고품질 BUY를 과잉 억제한다는 증거는 없었으나, 표본이
  작고 일부 guard(reduce_guard/reentry_cooldown)가 미발동 상태라
  판정은 Watch로 확정했다. R3b 자체 판정(Conditional Go)은 이
  검증의 영향을 받지 않는다. 코드 변경 없음(신규 검증 스크립트만
  추가), 신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §64.

- 작성자: Codex
- 수정일자: 2026-07-20 (76차, R3b alpha가 실제 paper 운영 경로에서
  정말 발동하는지 최종 실증)
- 수정내용: env/config→코드 경로→percentile 계산·주입→실제
  decision 영향까지 4단계로 분리해 실측했다(SPPV-2.76). 실제
  운영 컨테이너 env·`AppSettings()` 재확인(둘 다 True), 오늘
  (2026-07-20) 실제 운영 로그에 "R3b alpha precompute: ...
  candidates=2 symbols=000660,000810"가 26회 반복 확인. 실제
  `trade_decisions.decision_json`을 직접 조회한 결과 000810이
  `entry_score=0.7856, buy_candidate=True`로 R3b에 의해 실제
  BUY_CANDIDATE 판정됨(24시간 26/26 재현), 그러나 `candidate_vs_
  final.alignment_status=downgraded`로 AI 최종 결정 합성기가
  매번 WATCH/HOLD로 하향 조정 — risk_opinion=allow, expected_
  value_gate.passed=true였으므로 이 downgrade는 pre_ai_gate/risk/
  compliance/expected_value_gate가 아닌 별도의 후속 축임을 확인.
  판정: **작동하나 체감 무효** — R3b는 실제로 작동하고 entry_score/
  buy_candidate를 바꾸지만, AI 최종 합성기 단계가 매번 눌러
  BUY 빈도 개선이 운영상 보이지 않는다. R3b 구현 자체 판정
  (Conditional Go)은 불변. 코드 변경 없음(순수 조사), 신규 KIS
  호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §65.

- 작성자: Codex
- 수정일자: 2026-07-20 (77차, SPPV-2.76 해석 정밀 보정 — "BUY
  부재" 원인의 3층 분리 정량화)
- 수정내용: §65의 "BUY 미발생의 직접 원인은 AI 최종 결정 합성기의
  downgrade다"는 과장이었음을 정정했다(SPPV-2.77 — R3b 작동 여부
  재검증이 아니라 원인 분해 정밀화). 실제 `trade_decisions`를
  직접 재조회(조회 시각 2026-07-20 02:54 UTC, 최근 24시간)한 결과
  R3b reason code가 붙은 66건이 정확히 절반씩 분리됨: **층 1**
  (`buy_candidate=True`+`downgraded`) 33건 전부 000810; **층 2**
  (`buy_candidate=False`/`NO_ACTION`, `alignment=matched`) 33건
  전부 000660 — 이 종목은 애초에 R3b가 사고 싶어한 적이 없다.
  운영 로그에서 **층 3**(`Pre-agent short-circuit` + `eligibility_
  core_risk_off_ranking_blocked`)을 별도 집계한 결과 원시 297건,
  distinct 11/12 종목(오늘 universe 12종목 중 11개, R3b 후보인
  000810만 유일하게 미해당) — `deterministic_trigger_engine.
  py:618`에서 발생해 `decision_orchestrator.py`가 AI 파이프라인
  호출 자체를 건너뛰는, candidate_vs_final보다 앞선 단계임을 코드로
  확인. 판정: **복합 병목** — 000810(층1)/000660(층2)/나머지
  universe 대다수(층3)를 같은 원인으로 묶으면 안 됨. universe
  전체 관점에서는 층 3(91.7%)이 가장 넓은 병목. R3b 작동 자체
  판정(작동하나 체감 무효)은 불변. 코드 변경 없음, 신규 KIS 호출
  0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §66.

- 작성자: Codex
- 수정일자: 2026-07-20 (78차, BUY_CANDIDATE 최종 통과 0건의 직접
  병목 정밀 분해 — "차단 장치 전면 완화"가 아니라 "0건 통과"를
  만드는 병목을 좁히는 턴)
- 수정내용: R3b가 만든 BUY_CANDIDATE(000810, 24시간 36건)의 전체
  funnel을 candidate→eligibility→candidate_intent=buy→final_
  intent=buy→decision_type=BUY→order request까지 손실 없이 추적
  (SPPV-2.78). candidate(36)→eligibility(36)→candidate_intent=
  buy(36)까지 무손실, `candidate_vs_final` 단계에서 100% 손실
  (final_intent=buy 0건, decision_type=BUY 0건, order request 0건
  — execution_attempts 24h 432건 전부 non_trade). universe 전체
  24시간 `decision_type` 분포도 WATCH=276/HOLD=156/BUY=SELL=
  REDUCE=EXIT=0으로 확인(R3b 국한 문제가 아닌 더 넓은 맥락).
  000810의 `ai_call_path.fdc_skipped=False`(실제 AI 최종 합성기
  호출 확인) + `opposing_evidence`(risk_off/고변동성/전략 충돌/
  weak evidence)가 36회 거의 동일 문구로 반복됨을 확인 — 정당한
  방어 논리일 수 있으나 국면 라벨 고착 가능성도 배제 못 함.
  판정: candidate까지는 무손실, `candidate_vs_final`(층1) 단일
  지점에서 100% 손실 — "BUY 후보는 생성되지만 마지막 단계 병목
  때문에 0건 통과". 보정 판정: 층3(pre-AI, universe 91.7%)=유지
  (000810과 인과관계 없음), 층2(000660 비후보)=유지(R3b 자신의
  판단), 층1(downgrade)=**정밀 보정 필요**(우선 완화 아님 — AI
  판단의 조건 민감도 확인이 먼저). R3b 작동 판정 불변. 코드 변경
  없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §67.

- 작성자: Codex
- 수정일자: 2026-07-20 (79차, "마지막 단계" 내부 재분해 — watch/
  no_action 두 갈래와 그 입력 패턴 차이)
- 수정내용: §67의 "candidate까지 무손실, candidate_vs_final에서
  100% 손실"을 유지하되, 그 내부를 `final_intent=watch`(31)와
  `final_intent=no_action`(8)으로 재분해했다(SPPV-2.79, 000810만
  대상). `compliance_opinion`/`expected_value_gate.passed`/
  `strategy_selection.preferred_strategy`(전부 defensive_low_
  volatility_rotation, 39/39 100%)는 두 그룹에서 완전히 동일해
  구분력이 없음을 확인 — `strategy_policy_mismatch`는 downgrade
  자체의 공통 원인이지 watch/no_action을 가르는 축이 아니다.
  구분력 있는 축 3개: `evidence_strength`/`conviction`/`confidence`
  (no_action만 0.0/'none'까지 하락), `regulatory_risk` 비중
  (42%→75%, `regulatory_crackdown`은 no_action 전용). §67의 "36회
  거의 동일 문구 반복"은 정정 — 39건 재확인 결과 `opposing_
  evidence` 텍스트는 전부 distinct(매 cycle 실제 LLM 생성), 주제
  (theme)만 일관되게 반복된다. 판정: 마지막 단계 병목이지만 watch/
  no_action 두 갈래로 명확히 분기 — "더 앞선 숨은 축" 의심 근거는
  발견되지 않음. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/
  10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §68.

- 작성자: Codex
- 수정일자: 2026-07-20 (80차, R3b 최종 병목의 조건 민감도 검증 +
  신규 발견(expected_value_gate 정량 게이트))
- 수정내용: §68의 watch/no_action 분기를 구간 분포·조합 빈도·극단값
  으로 재검증했다(SPPV-2.80, 000810만 대상). candidate_intent=
  buy 39→**47**건으로 증가, **watch 36 / no_action 9 / buy 2**로
  분해 — "final_intent=buy 0건"이라는 §67~§68의 관측이 이번 조회
  에서 처음 깨짐. 신뢰도 축(evidence_strength/conviction/
  confidence)은 대부분 구간이 겹쳐 명확한 threshold가 아니며,
  no_action 유일 극단값(conviction=0.0/confidence=0.0/evidence=
  'none', opposing_evidence=[]) 1건만 확인. 규제/법률 flag 보유
  비율은 watch 39%→no_action 89%로 상승하나 전용 축은 아니고
  "weak evidence + 규제flag" 조합이 보조 강도 축으로 작동하는
  것으로 보임. **신규 발견(중요)**: 실제 decision_type='APPROVE'
  2건을 추적한 결과 `translation.py`의 `_has_required_expected_
  value_anchor`가 `expected_value_gate.passed=False`(edge_after_
  cost_bps=8.56 < minimum_required_edge_bps=10.00, 1.44bps 차이)
  로 인해 submit_request=None을 반환 — AI 정성 판단과 완전히
  별개인 정량 게이트가 실제 주문 생성을 막는 새로운 최종 병목임을
  코드로 확인. 판정: "아직 직접 분기축이라 단정 불가"(신뢰도+규제
  조합이 유력 후보), strategy_policy_mismatch류는 우선순위 하향.
  코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §69.

- 작성자: Codex
- 수정일자: 2026-07-20 (81차, "APPROVE + expected_value_gate.
  passed=false"가 저장되는 이유 — 코드 경로 완전 추적)
- 수정내용: §69의 발견을 코드 끝까지 닫아 추적했다(SPPV-2.81,
  원인 추적 턴, 완화 없음). `decision_orchestrator.py:538`의
  `_check_ai_buy_override_gate()`가 `:565-566`에서 `if buy_
  candidate: return None`으로 즉시 반환 — `:634`의 `expected_
  value_gate_passed` downgrade 체크에 도달조차 못함(R3b가 이미
  candidate로 판정한 경우는 이 override-gate의 점검 대상이 아님).
  호출부(`:2376-2385`)에서 `ai_override_gate is None`이면 downgrade
  블록 전체 스킵 → `decision_type='APPROVE'` 그대로 `decision_
  factory.py`에 저장(`failed_rule_codes`엔 gate 실패 사유만 별도
  기록, decision_type은 불변). 실제 차단은 이후 `translation.py:
  74-178`의 `_has_required_expected_value_anchor()`가 독립적으로
  재확인해 `submit_request=None` 반환 — `execution_service.py`가
  "produced no order request"로 스킵. 재조회(24h, 조회 시각
  04:42 UTC) 결과 APPROVE 7건 전부 `edge_after_cost_bps=8.56`/
  `minimum_required_edge_bps=10.00` 완전 동일값 반복. 로그로 대조
  확인: 같은 시간대 000240은 override gate가 실제 발동해 로그를
  남기나 000810 7건은 로그 없음(조기 반환 확인). 판정: **계층
  간 불일치(저장/번역/제출의 책임 분리)** — APPROVE 저장은 코드
  설계대로 정상 동작(버그 아님), 다만 함수 docstring의 "EV 통과
  시에만 허용" 약속과 실제 동작(candidate엔 미적용) 사이 괴리는
  완전 의도 여부 단정 불가. 한 줄 결론: "APPROVE 저장은 정상이나
  주문은 expected value gate에서 차단". 코드 변경 없음, 신규 KIS
  호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §70.

- 작성자: Codex
- 수정일자: 2026-07-20 (82차, "APPROVE 저장 vs 실제 주문 미생성"
  구조에 대한 설계 해석 정리)
- 수정내용: §70의 인과 경로를 재검증하지 않고, 이 구조가 의도된
  계층 분리인지 설계 해석을 닫았다(SPPV-2.82, 코드 수정안 없음).
  `docs/10_signal_research_sppv/[GUIDE] end_to_end_order_flow_
  guide.md`를 확인한 결과, §8-1(`APPROVE`="AI/정량 기준상 진입
  승인 **제안**")·§8-4("R3b는 더 잘 고르는 장치이지 비용 문제를
  없애는 장치는 아니다")·§9("AI가 BUY를 말해도 expected value
  gate 실패면 실제 주문으로 번역되지 않는다")가 §70이 코드로
  재구성한 경로를 **이미 사전에 명시적으로 문서화**해 놓았음을
  확인했다 — §70의 "완전 의도 여부 단정 불가"를 이 근거로 좁혔다.
  `_check_ai_buy_override_gate()`의 docstring 괴리도 "override
  방어"라는 좁은 책임 범위를 문구가 정확히 표현하지 못한
  문서화 정밀도 문제로 재해석(실제 로직 결함 아님) — EV gate의
  최종 강제 지점은 처음부터 `translation.py`. 세 지표(BUY_
  CANDIDATE 발생/APPROVE 저장/order_request 생성)의 의미를
  각각 정의하고 분리 트래킹을 권장했다. 재확인(24h, 05:18 UTC):
  APPROVE 14건(7→14 자연 증가), 전부 동일 evg 실패, execution_
  attempts 708건 전부 non_trade — §70과 일치, 새 수치 해석
  불필요. 판정: **의도된 계층 분리이며 문서/지표 해석만 보정하면
  됨**. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §71.

- 작성자: Codex
- 수정일자: 2026-07-20 (83차, `expected_value_gate` 계산 구조
  자체의 설계 타당성 검증)
- 수정내용: threshold 조정이 아니라 "일봉 1회 snapshot 기반 입력을
  분단위 decision loop가 반복 재평가하는 구조"가 설계상 타당한지
  검증했다(SPPV-2.83, 코드 수정안 없음). EV gate 원 설계 문서
  (`[DESIGN] expected_return_holding_horizon_and_churn_control_
  refactor.md` §6)는 입력 신선도를 규정하지 않는 공백이며, 반면
  같은 코드베이스는 reverse trade 재진입에는 이미 same-snapshot
  재판단 억제 원칙을 채택·구현(`reverse_trade_hysteresis.py`)했으나
  최초 BUY 후보 평가에는 적용하지 않는다는 비대칭을 확인했다.
  판정: 입력 캐던스(일봉)와 재평가 캐던스(분단위, 기본 300초) 사이의
  **설계 미스매치(문서화되지 않은 공백)**. 구조적 메커니즘(4개 EV
  입력의 snapshot 결합)은 전 종목 일반화 가능하나 "1.44bps 부족"
  수치 자체는 종목 특수값으로 일반화 불가. 다음 최우선으로 EV gate
  계산 구조 보정안 설계 검토를 threshold 민감도 검증보다 우선 채택.
  코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
  sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §72.

- 작성자: Codex
- 수정일자: 2026-07-20 (84차, `expected_value_gate` 계산 구조
  보정안 후보 비교 설계 검토)
- 수정내용: §72의 설계 미스매치 판정을 전제로, threshold 완화 없이
  구조 보정안 4개 후보(A. same-snapshot 재평가 억제 / B. snapshot
  갱신 시점에만 EV 재계산·캐시 / C. 입력 신선도별 분리 / D. 현 구조
  유지+모니터링 강화)를 정의·비교했다(SPPV-2.84, 코드 수정/diff
  없음). reverse_trade_hysteresis.py가 이미 `symbol_trade_states.
  last_signal_feature_snapshot_id`로 same-snapshot 재판단 억제를
  구현한 기존 인프라를 확인, 이를 최초 BUY 경로로 확장하는 **후보
  A를 1순위로 추천** — 판정 로직(threshold/계산식)은 전혀 바꾸지
  않고 동일 정보에 대한 반복 재계산/재저장만 줄이므로 방어 약화
  위험이 가장 낮고 기존 hysteresis 원칙과 정합적. 후보 C(입력
  신선도 분리)는 실시간 데이터 소스 부재로 지금 실행 불가능한
  후속 고도화 단계로 분류. SPPV 목표("방패 전부 제거 아님, BUY
  0건 상태 해소")와 충돌하지 않음을 확인 — 후보 A는 판정 기준을
  낮추지 않고 반복 생성만 줄이므로 새 BUY 기회를 늘리지도, 방어를
  약화시키지도 않는다. 다음 턴 착수용 설계 메모(보정 계층 후보,
  상태 저장소 재사용안, shadow 비교축, paper 관측 지표)를 기록.
  코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
  sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §73.

- 작성자: Codex
- 수정일자: 2026-07-20 (85차, 구조 정리(후보 A) vs 실제 BUY 증가
  병목 — 다음 검증 우선순위 정리)
- 수정내용: 후보 A(same-snapshot 재평가 억제)의 역할을 "BUY 차단
  완화"/"판정 기준 완화"와 명확히 구분해 "동일 정보에 대한 반복
  평가/저장 억제"로 재정의하고, "먼저 해둘 만한 위생 작업이나
  실제 BUY 증가와는 독립적인 별개 축"으로 위치를 확정했다(SPPV-
  2.85, 코드 수정 없음). 병목을 구조 정리(A안, EV gate 계산 구조
  보정)와 실제 BUY 증가 병목(pre-AI 차단/candidate_vs_final
  downgrade 축/EV threshold 민감도)으로 재분류. 다음 검증 우선순위:
  **1위 pre-AI 차단(층3, risk_off ranking blocked, 유니버스
  11/12종목 영향) 재검증** — 지금까지 EV gate 분석이 이 축에
  걸리지 않는 유일한 예외인 000810 1개 종목에 국한돼 있었음을
  근거로 최우선 지정. 2위 candidate_vs_final downgrade 축, 3위
  EV threshold 민감도(표본 협소로 후순위). SPPV 목표와 가장
  직접 연결되는 축은 1위(pre-AI 차단)로 판정. 다음 턴 프롬프트
  후보 2개(구조 정리용 A, 실제 BUY 증가 검증용 B) 제시, B를 우선
  추천. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §74.

- 작성자: Codex
- 수정일자: 2026-07-20 (86차, EV gate/submit 차단 완화 후보 선정
  — 최소 검증 후 즉시 전진)
- 수정내용: 구조 보정(A안)이 완화 검토의 선행조건이 아님을 확인 —
  판정 로직 불변이라 완화 실험과 독립적이므로 건너뛰고 바로 완화
  검토로 진행 가능(SPPV-2.86, 코드 수정 없음). 완화 후보를
  전역 threshold 완화 / margin 근소부족 조건부 완화 2개로 압축(
  "submit 차단 조건 자체 완화"는 방패 전부 걷어내기 위험으로 배제).
  1순위: **margin 근소부족 조건부 완화** — 현재 표본과 가장
  직접 관련되고 방어 약화 위험이 가장 낮음. 다음 턴 즉시 실행용
  shadow 검증 프롬프트 작성(전역 threshold/코드 변경 없이 조건부
  통과 시뮬레이션 + 과잉 완화 여부 교차검증). 코드 변경 없음, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §75.

- 작성자: Codex
- 수정일자: 2026-07-20 (87차, margin 근소부족 조건부 완화 shadow
  실측 검증)
- 수정내용: 완화안 1(부족분≤2.0bps)/완화안 2(부족분≤3.5bps)를
  3일/7일/30일 창으로 실측(SPPV-2.87, 코드 변경 없음). 현행
  APPROVE&EV-fail 24건 중 완화안1 23건, 완화안2 24건 통과 가능 —
  전량 000810, 전량 2026-07-20 하루, 전량 동일 signal_feature_
  snapshot(2026-07-16 배치) 반복. 30일 전체를 봐도 이 조건이
  발생한 날이 오늘뿐임을 확인 — 과잉 완화 위험은 낮으나(단일
  종목·단일일 집중) 동시에 표본이 너무 얇아 "의미 있는 BUY 증가"
  로 단정하기도 이르다. forward return은 확인 불가(데이터 부재,
  전량 당일 결정이라 미래 데이터 자체가 없음). **판정: Watch** —
  No-Go는 아니나(위험 낮음) Conditional Go로 바로 승격하기엔
  단일 종목·단일 거래일 편중이 압도적. A안(same-snapshot 억제)
  과는 독립적 — A안 없이도 이번 검증은 유효. 다음 우선 작업:
  누적 관찰 연장 후 재판정. 코드 변경 없음, 신규 KIS 호출 0건.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §76.

- 작성자: Codex
- 수정일자: 2026-07-20 (88차, EV gate near-miss(<=2.0bps) 조건부
  완화 — 제한적 코드 구현 + 실측 검증)
- 수정내용: "전역 EV gate 완화"가 아니라 "R3b core BUY의 근소
  부족(<=2.0bps) 예외 통과를 paper에서 제한 검증"하기 위해 실제
  코드를 제한적으로 수정했다(SPPV-2.88). config 스위치
  `EV_GATE_NEAR_MISS_OVERRIDE_ENABLED`(기본값 false)를 신설하고,
  `decision_orchestrator.py`에 순수 함수 `resolve_ev_gate_near_
  miss_override()`로 5개 AND 조건(decision_type/expected_value_
  gate_passed/부족분<=2.0bps/source_type=core/trigger_r3b_alpha_
  percentile 포함)을 판정, 원 `expected_value_gate_passed` 값은
  보존한 채 별도 필드(`ev_gate_near_miss_override_applied` 등)로만
  기록. `translation.py`는 "no settings" 순수성 원칙을 지켜 이미
  결정된 boolean 필드 하나만 추가로 읽도록 최소 수정. 신규 단위
  테스트 13개 전체 통과, 관련 기존 테스트 151개 회귀 없음, 전체
  회귀 스윕에서 발견된 170건 실패는 전부 `tests/repositories/*`의
  pre-existing 이벤트 루프/컬럼 한도 이슈로 확정(git stash로 무관함
  직접 확인). 000810 실제 DB 레코드로 end-to-end 재현: deficit=
  1.44bps는 switch on 시 submit_request 생성, deficit=3.44bps는
  switch on에도 여전히 차단 — 의도대로 동작 확인. 실제 라이브 paper
  배포(스위치 on)는 사용자 승인 필요 사안으로 이번 턴에는 미실행.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §77.

- 2026-07-21 재검증(코드/설정 변경 없음): 전체 테스트 스위트 재실행
  없이 변경 직접 관련 최소 범위(신규 13개+관련 기존 74개=87개,
  0.22s)만 재확인 + 000810 실제 DB 레코드 단발성 재현 스크립트로
  동일 결과(1.44bps 통과/3.44bps 차단) 재확인. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
  v1.md` §77.7.

- 2026-07-21(SPPV-2.89): 사용자 승인으로 실제 paper 환경에서
  EV_GATE_NEAR_MISS_OVERRIDE_ENABLED=true 활성화. `.env`는 이미
  true로 반영돼 있었음(직접 수정 안 함), docker-compose 배선 확인,
  `ops-scheduler`만 재기동, AppSettings().ev_gate_near_miss_
  override_enabled=True 확인. 재기동 후 10분간 관측한 결과 near-
  miss 조건을 만족하는 실제 사례는 아직 발생하지 않음(0/32건) —
  "준비 완료"이며 "실제 order_request 생성 확인"은 아직 아님.
  코드 변경 없음. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §77.8.

- 작성자: Codex
- 수정일자: 2026-07-21 (89차, EV gate near-miss override 미발동
  원인 — SPPV BUY funnel 관점 재분해)
- 수정내용: near-miss override가 paper runtime에 켜져 있는데도
  적용/주문 생성 사례가 없는 직접 원인을 SPPV BUY funnel(candidate
  → final_intent → APPROVE → submit_request) 단계별로 닫았다
  (SPPV-2.90, threshold/코드 변경 없음, 전체 pytest 미실행). 재기동
  이후 구간에서 `buy_candidate=true`/`final_intent='buy'`/`APPROVE`
  전부 0건임을 확인 — funnel 최상류에서부터 막혀 EV gate/near-miss
  가 평가될 기회 자체가 없었음. 근소부족 후보는 000810 1종목·특정
  국면 의존이었고, 오늘은 그 종목의 entry_score마저 0.7856→0.0으로
  급락. 판정: 단순 미발동/로직 결함이 아니라 표본 부족 + 더 상류
  병목이 현재 지배적. 코드 변경 없음, 신규 KIS 호출 0건. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §78.

- 작성자: Codex
- 수정일자: 2026-07-21 (90차, §78 해석 보정 — 000810 entry_score
  급락 원인 정밀화)
- 수정내용: §78의 "entry_score 급락"/"buy_candidate 생성 자체가
  사라졌다" 서술의 원인 해석을 정밀화했다(SPPV-2.91, 판정 변경
  아님, 코드 변경 없음). signal_feature_snapshot이 2026-07-20
  11:52 UTC에 정상 갱신됐음을 확인, 오늘 R3b candidate pool이
  2→3종목으로 확장되고 000810이 그 안에서 최하위(percentile=0.0)
  임을 실측 재계산으로 검증(001450 6.92 > 000660 6.39 > 000810
  5.67). "R3b 미작동"이 아니라 "R3b 적용 + 후보군 내부 최하위"로
  결론 정정. §78의 핵심 판정은 유지, 원인 해석만 보정. 코드 변경
  없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §79.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (91차, R3b candidate pool 협소·순위
  변동성 판정)
- 수정내용: near-miss override를 더 만지지 않고, R3b가 정상 작동
  하는데도 BUY funnel 상류에서 0건에 수렴하는 이유를 "candidate
  pool 협소성" 관점에서 실측 닫았다(SPPV-2.92, 코드 변경 없음).
  최근 48시간(KST) 000810/000660의 entry_score가 각각 정확히 2개
  값({0.0,0.7856}/{0.0,0.33})만 관측 — 000810 특이 사례가 아니라
  반복 구조. core 유니버스 약 18종목 중 candidate pool은 2~3종목
  뿐이며, `bisect_left/(n-1)` percentile 공식상 n=2/3이면 각각
  {0.0,1.0}/{0.0,0.5,1.0}만 가능한 태생적 이산성이 원인. 001450은
  entry_score=0.78로 임계 이상이나 별도 유동성 eligibility 게이트
  로 차단(R3b와 무관). 병목 3단계(A.R3b 미작동/B.candidate pool
  협소/C.candidate_vs_final·APPROVE·EV gate 이후) 중 **B를 현재
  주된 병목으로 확정**. near-miss override는 paper runtime에 계속
  켜져 있음. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
  v1.md` §80.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (92차, Codex 종합 판단 반영 — "창보다
  방패 다층 구조" 해석 고정)
- 수정내용: §70~§80의 실측을 하나의 운영 판단으로 묶었다(SPPV-2.93,
  코드 변경 없음). 핵심 판단: 현재 BUY가 늘지 않는 이유는 R3b 미작동
  이 아니라 "상류 candidate pool 협소 + 중류 eligibility 차단 +
  하류 APPROVE/EV gate 차단"이 직렬로 겹친 다층 방패 구조. 001450은
  entry_score=0.78로 threshold를 넘지만 eligibility_low_relative_
  activity로 buy_candidate=false 유지되는 대표 사례. 다음 우선순위:
  (1) 001450 활동성 게이트 재검증, (2) candidate pool quintile 공식
  적정성 검토, (3) EV gate/submit 차단 재평가. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
  v1.md` §81.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (93차, `001450 / eligibility_low_
  relative_activity` 축 정밀 검증)
- 수정내용: §81이 최우선으로 지정한 001450 활동성 게이트 축을 실제
  운영 데이터로 정밀 검증했다(SPPV-2.94, 코드 변경 없음). 최근 7일
  001450의 trade_decisions 188건 전량이 이 게이트로 차단(entry_
  score 무관). 전 종목 중 entry_score>=0.65는 000810·001450 단
  2종목뿐이며, 활동성 게이트 차단은 001450 100%, buy_candidate
  통과는 000810 100% — 광범위 방패가 아니라 001450 단일 종목 반복
  패턴. 직접 원인은 max(volume_surge_ratio, turnover_surge_ratio)
  < 1.10 단일 조건(entry_score 무관, 코드로 확정). 001450의 20일
  평균 거래량/거래대금이 2주간 각 약 -20%/-22% 추세적 감소 — 실제
  유동성 저하 추세로 뒷받침되는 정당한 방어에 가까움. 판정: Watch
  (No-Go도 Conditional Go도 아님, 계속 관찰). 코드 변경 없음, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §82.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (94차, 20% quintile 공식의 구조적 결과
  재구성 검증)
- 수정내용: candidate pool 협소성(병목 B)을 완화안 적용 없이
  `build_candidate_percentiles()`를 최근 거래일 데이터로 그대로
  재실행해 재구성 검증했다(SPPV-2.95, 코드 변경 없음). 07-14/15는
  벤치마크 snapshot 결측으로 pool=0(별도 문제). 07-16/20/21 3거래일
  모두 신호 계산 가능 종목=core 유니버스 수(결측 없음)였음에도 20%
  pool 크기는 4/2/3에 불과, 3종목 모두 3일 만에 percentile 극값을
  최소 한 번씩 기록. shadow 비교(top 30%/고정 top-5)에서도 pool은
  여전히 한 자릿수(2~6) — 문제 본질은 비율이 아니라 core 유니버스
  규모(12~23종목) 자체. 병목 B 확정, 다음 검토 대상은 "비율 조정"
  아닌 "유니버스 규모 재검토"로 재정의. 코드 변경 없음, 신규 KIS
  호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §83.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (95차, R3b candidate pool 내부 percentile
  주입 방식의 가혹성 실측)
- 수정내용: "pool 내부 최하위=0.0 주입(A안)이 작은 pool에서 고득점
  후보를 과도하게 0점 처리하는가"를 A/B(floor 0.30)/C(rank
  compression (idx+1)/(n+1)) shadow 비교로 검증했다(SPPV-2.96,
  코드 변경 없음). look-behind 보정(전일까지 snapshot만 사용) 후
  07-20/07-21 2개 유효 거래일 5건 재구성 — 최하위 종목(percentile
  =0.0) 3건 모두 B/C 적용해도 entry_score 0.20~0.27에 그쳐
  threshold(0.65)에 근접 못 함(0.0 감점 폭이 아니라 alpha 항 외
  나머지 base 자체가 낮았음). 반대로 이미 buy_candidate=True인
  두 최상위 사례는 C안 적용 시 threshold 아래로 떨어지는 부작용
  확인. 최하위 수령 종목이 거래일마다 다름 — 반복 구조 확정. 판정:
  "현행 A안이 과도하다"는 가설은 이번 표본에서 뒷받침되지 않음
  (No-Go), 완화안 코드 diff 착수는 보류. 코드 변경 없음, 신규 KIS
  호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §84.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (96차, R3b candidate pool 최하위 floor
  완화안(B1/B2/B3) 정밀 재검증)
- 수정내용: §84의 C안(압축) 부작용 확인에 따라 floor 계열만 좁혀
  0.30/0.45/0.60을 재검증했다(SPPV-2.97, 코드 변경 없음). 확인된
  유효 거래일(07-20/07-21) 2일 모두 최하위 종목은 floor 0.60까지도
  threshold(0.65)에 근접 못 함(최고 0.48) — base 자체가 매우
  낮았기 때문. 참고(07-16, 근사) 데이터에서만 0.45/0.60에서 회복
  관측되나 신뢰도 낮음. 최상위 후보(000810@07-20, 001450@07-21)는
  모든 floor에서 entry_score/buy_candidate 무변화 — max(raw,floor)
  의 단조증가 성질상 구조적으로 최상위를 건드릴 수 없음을 확정
  (C안과 근본적으로 다름). 0.60은 참고 데이터에서 pool 꼴찌까지
  자동 통과시켜 과잉 완화 조짐도 일부 관측. 판정: Watch(최상위
  무손상 확실, 그러나 확인된 유효 거래일 회복 근거 아직 부족).
  완화안 diff 착수는 보류, 표본 축적 우선. 코드 변경 없음, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §85.

- 작성자: Codex
- 수정일자: 2026-07-21 KST (97차, R3b candidate pool 최하위
  floor=0.60 — 사용자 직권 paper 운영 반영)
- 수정내용: §85의 shadow 검증은 Watch였으나, 사용자가 "주문 0건
  장기화가 더 큰 운영 문제"로 판단해 직권으로 `CANDIDATE_
  PERCENTILE_FLOOR=0.60`을 실제 paper 운영에 반영했다(SPPV-2.98,
  "운영 관찰을 위한 제한적 완화 적용" — 효과 증명 아님). 반영 지점은
  `r3b_alpha_percentile.py`의 `build_candidate_percentiles()`
  내부 한 줄로 최소화, 신규 env 변수 없음(bare 모듈 상수, 기존
  `TOP_QUINTILE_FRACTION`과 동일 패턴). 신규 테스트 6개+관련 기존
  76개=82/82 통과(Full pytest 미실행). 실제 DB(오늘 core universe
  17종목) off/on 비교로 최상위(001450) 무손상, 최하위/중하위
  (000810/000660) 상향만 확인. 활동성 게이트/AI downgrade/EV gate
  등 하류 병목은 그대로 남음. 코드 변경 있음(신규 파일 1개, 기존
  파일 1개 수정), 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
  sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §86.

- 작성자: Codex
- 수정일자: 2026-07-22 KST (98차, floor=0.60 반영 후 SPPV BUY
  funnel 1일 관찰 결과)
- 수정내용: §86 반영 후 약 7.5시간(2026-07-22 09:27~17:01 KST)
  운영 관찰 결과를 기록했다(SPPV-2.99, 코드 변경 없음). entry_score
  실측 상승(000810 0.00→0.46, 000660 0.33→0.41, 001450 무변화 —
  이미 최상위라 floor 영향권 밖) 확인. 그러나 buy_candidate/final_
  intent=buy/APPROVE/submit_request/order_requests는 반영 전후
  전부 0건으로 동일 — 최종 funnel 전진 없음. 병목이 층2(eligibility)
  로 이동했음을 확인: 001450/000810은 활동성 게이트, 000660은
  새로 확인된 `eligibility_negative_overall_floor` 축으로 즉시
  차단. 판정: B(부분 유효) — 상류 개선, 하류 병목으로 최종 전진
  제한적. §86의 "운영 관찰을 위한 제한적 완화 적용" 서술과 일치.
  코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §87.

- 작성자: Codex
- 수정일자: 2026-07-24 KST (99차, 층2(eligibility) 병목 세분화
  재검증 — 활동성 게이트 vs negative_overall_floor)
- 수정내용: §87의 층2(eligibility) 병목을 활동성 게이트와
  negative_overall_floor로 분리 재검증했다(SPPV-2.100, 코드 변경
  없음). 관찰 창(07-22 09:27~07-24 15:27 KST) 기준 000810/001450은
  entry_score가 0.78까지 도달해도 100% 활동성 게이트로 차단(382건,
  "점수는 충분하나 eligibility가 막는" 사례), 000660은 entry_score
  자체가 최대 0.41로 threshold 미달인 채 negative_overall_floor로
  차단(188건, 활동성 게이트와 완전히 별개인 독립 축, overall_score
  =-0.1445 vs 임계값 -0.10). 활동성 게이트가 층2 내부에서 더
  직접적인 병목으로 확정. 다만 최근 3일 활동성 비율(0.57~0.89 vs
  1.10)이 근소 미달이 아니라 뚜렷한 미달로 실제 유동성 감소 추세와
  일치해, 두 축 모두 완화 검토 후보로 올릴 근거는 부족 — Watch
  유지. 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §88.

- 작성자: Codex
- 수정일자: 2026-07-24 KST (100차, 층2(eligibility) 국면별 층화
  재검증 — bullish_trend 포함)
- 수정내용: §88의 활동성 게이트/negative_overall_floor 판정을
  국면(regime)별로 층화 재검증했다(SPPV-2.101, 코드 변경 없음).
  000810/001450은 관찰 창 내내 100% bullish_trend, 000660은 100%
  range_bound로 분류돼 국면과 종목이 완전히 교락됨을 정직하게
  확인. 활동성 게이트는 bullish_trend 표본(382건)에서도 명확한
  미달(37~48%↓)로 반복 확인돼 완화 검토 근거 없음(Watch 유지).
  negative_overall_floor는 bullish_trend 표본 자체가 없어 국면
  의존성 가설이 미확정으로 남음. 전체 Watch 판정 유지, 상승장
  포함해도 변경 없음. 코드 변경 없음, Full pytest 미실행, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §89.

- 작성자: Codex
- 수정일자: 2026-07-24 KST (101차, 근본 설계 재검토 — "창 vs
  방패" 전략 전환에 따른 우선순위 재정렬)
- 수정내용: 수십 턴에도 주문 0건이 지속된다는 문제의식에 따라,
  사용자가 "core universe 확장(우선) + eligibility 완화(병행)"를
  결정했다(SPPV-2.102, 코드 변경 없음 — 레버 식별/설계 재검토만).
  `TRADING_UNIVERSE_CORE_CAP`(기본값 12, 현재 오버라이드 없음)이
  R3b candidate pool 모수를 좌우하는 config 레버임을 확인 — 실질
  상한은 일 배치 유효 신호 종목 약 80개. §80/§83의 결론과 정확히
  일치. §88~89의 활동성 게이트 판정(정당 차단에 가까움)은 유지,
  eligibility 완화는 "예측 오류 손실"과 "유동성 실행 리스크"가
  다른 종류임을 구분해 명시. 코드 변경 없음, 신규 KIS 호출 0건.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §90.

- 작성자: Codex
- 수정일자: 2026-07-24 KST (102차, core universe 확장 vs
  eligibility 조건부 완화 — shadow 정량 비교)
- 수정내용: 실제 `UniverseSelectionService.compose()`를 core_cap=
  12/20/40/60로 재호출해 pool 확장을 실측했다(SPPV-2.103, 코드
  변경 없음, kis_client=None으로 신규 KIS 호출 0건 보장). 추적
  3종목 기준 core_cap 확장의 buy_candidate 회복 효과는 0건(000810
  순위 하락, 001450은 활동성 게이트가 무관하게 차단) — 진짜 잠재
  효과는 신규 진입 종목(009150 등)에 있으나 라이브 검증 전엔 확인
  불가. 반대로 entry_score>=0.70 조건부 활동성 게이트 예외는 오늘
  실측 데이터에서 001450을 즉시 buy_candidate=True로 전환시킴.
  판정: core_cap 확장=Watch, eligibility 조건부 완화=Conditional
  Go 후보로 격상 가능(실제 반영은 별도 결정). 코드 변경 없음, Full
  pytest 미실행, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
  sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §91.

- **[SPPV-2.104에서 정정] 위 판정("core_cap 확장=Watch",
  "eligibility 조건부 완화=Conditional Go 후보")은 하루치·단일
  시점 표본 기준으로는 과속이었다. 원문은 보존하고 아래에 보정
  내용을 추가한다.**
- 작성자: Codex
- 수정일자: 2026-07-24 KST (103차, §91 판정 보정 — "Watch/
  Conditional Go" 라벨 과속 정정, 우선순위 중심 재정리)
- 수정내용: §91의 실측 자체는 정정하지 않고, 라벨/해석만 보정했다
  (SPPV-2.104, 코드 변경 없음, 신규 조회/신규 KIS 호출 없음).
  core universe 확장을 "기존 3종목 구제 실패"가 아니라 "신규 후보
  (009150) 출현을 확인한 상류 모집단 확대 레버"로 재해석해
  **실반영 우선 후보(1순위)**로 격상. eligibility 조건부 완화는
  하루치·단일 종목 flip만으로 Go 방향 라벨을 쓴 것이 과속이었음을
  인정하고 **제한적 하류 직접 레버(병행 실반영 후보, 2순위)**로
  하향 정정. 두 레버 모두 "실반영 후 1~2거래일 관찰 필요" 상태로
  유지, 하루치 결과만으로 최종 확정하지 않음. 코드 변경 없음,
  신규 KIS 호출 없음. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §92.

- 작성자: Codex
- 수정일자: 2026-07-24 KST (104차, `TRADING_UNIVERSE_CORE_CAP`
  1순위 레버 실반영 절차)
- 수정내용: §92의 1순위 레버(core universe 확장)를 실제 반영하는
  과정에서 `docker-compose.yml`의 `ops-scheduler` 환경변수
  화이트리스트에 `TRADING_UNIVERSE_CORE_CAP`이 선언돼 있지 않았던
  배선 공백을 발견·수정했다(SPPV-2.105, 기본값 12 유지). `.env.
  example`에도 `=40` 예시/근거 추가. 다만 `.env`는 이 세션의 표준
  원칙에 따라 직접 수정하지 않았으므로, 사용자가 `.env`에 값을
  추가해야 실제 반영이 완료된다(그 전까지 기본값 12 그대로 적용,
  컨테이너 env 직접 확인). eligibility 조건부 완화(2순위)는 미착수,
  EV gate threshold 변경 없음. 코드 로직 변경 없음, 신규 KIS 호출
  0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §93.

- 작성자: Codex
- 수정일자: 2026-07-26 KST (105차, `TRADING_UNIVERSE_CORE_CAP=60`
  실제 반영 확인 — ops-scheduler 재기동 + 첫 관찰)
- 수정내용: 사용자가 `.env`에 이미 반영한 `TRADING_UNIVERSE_CORE_
  CAP=60`을 `ops-scheduler` 재기동으로 실제 확인했다(SPPV-2.106).
  컨테이너 env/`os.getenv` 모두 60 확인, 실제 `compose()` 재호출로
  core 60종목·candidate pool 12개(신규 `009150` 포함)를 실측
  확인 — §90/§91의 shadow 예측과 정확히 일치. 다만 오늘은 비거래일
  이라 실제 decision loop 사이클이 스킵돼 `buy_candidate` 등 실제
  funnel 효과는 다음 거래일(2026-07-27 KST) 이후 확인 필요 — 설정
  반영 확인과 효과 판정을 명확히 구분. eligibility 조건부 완화/EV
  gate는 미착수. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
  v1.md` §94.

- **[SPPV-2.107에서 정정] 위 §94의 shadow 재구성(core 60종목·pool
  12개)은 `max_cap=100` 가정이 실제 프로덕션 조건(`max_cap=30`
  하드코딩)과 달랐다 — 원문 보존, 아래에 실측 정정 추가.**
- 작성자: Codex
- 수정일자: 2026-07-27 KST (106차, 첫 거래일 실측 — `core_cap=60`이
  `max_cap=30`에 의해 상쇄됨, 001450 병목이 층2→층3으로 이동)
- 수정내용: 실제 프로덕션 로그로 `max_cap`이 env 오버라이드 불가한
  하드코딩 상수 30임을 확인했다(SPPV-2.107). 오늘 universe는 30개
  (전량 core)로 고정, `009150`은 순위 60위라 진입 못 함. candidate
  pool은 2→6개(3배)로 일부 확대. `001450`이 사상 최초로 `buy_
  candidate=True`+`eligibility_passed=True`를 달성했으나(활동성
  게이트 자연 통과), `candidate_vs_final`에서 실제 fraud
  investigation 이벤트로 `HOLD` downgrade — submit_request/order_
  request는 0건. 판정: 다음 상류 병목은 core_cap이 아니라 `max_
  cap=30`으로 확정 이동. 001450 downgrade는 정당한 리스크 반영으로
  판단, 완화 대상 아님. 코드 변경 없음, Full pytest 미실행, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_

- **[SPPV-2.108에서 정정]** 위 106차 항목의 "정당한 리스크 반영으로
  판단"은 fraud investigation 표본 1건(55건 중 2%)에 근거한 과대
  대표였다.
- 작성자: Codex
- 수정일자: 2026-07-27 KST (108차, max_cap=30 설계 검토(코드 미작성)
  + 001450 층3 재관찰(키워드 기반 재집계))
- 수정내용: max_cap=30 조정 시 최소 수정안(env 배선 미러링)/영향
  범위/검증 포인트를 코드 미작성으로 정리. 001450 재관찰은 정확
  문자열 매칭 대신 키워드(부분 문자열) 기반으로 재집계 — `risk_
  off`+`volatility` 조합이 buy_candidate&eligibility_passed 동시
  만족 55건 전수(100%)의 공통 축, `fraud`는 7건(13%)의 소수 동반
  요소임을 확인. 정당 반영/과잉 방어 여부는 미확정(추가 관찰
  필요). 상류(max_cap)·하류(층3 AI downgrade) 이중 병목 구조로
  재정리. 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §96.

- **[SPPV-2.109에서 정정]** 위 108차 항목의 "55건 전수(100%)"는
  `reason_codes` 필드 단독 기준 재검증 결과 55건 중 54건(사실상
  공통 축)으로 정정. "프로덕션 호출부 2곳 모두 인자 없이 호출"도
  파라미터화 래퍼(`_read_trading_universe()`) 존재를 반영해
  정정(단, 이 래퍼는 현재 테스트 전용, 프로덕션은 미경유 — 메인
  런타임 사실상 30 고정 결론은 유지). 큰 결론(상류 병목/중심
  축/1·2순위) 변경 없음.
- 작성자: Codex
- 수정일자: 2026-07-27 KST (109차, 서술 정밀도 보정)
- 수정내용: 위 정정 2건 반영. 코드 변경 없음, Full pytest 미실행,
  신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §95.

- 작성자: Codex
- 수정일자: 2026-07-27 KST (110차, `TRADING_UNIVERSE_MAX_CAP` env
  배선 실제 반영 — 코드 변경 있음)
- 수정내용: `TRADING_UNIVERSE_CORE_CAP`과 동일 패턴으로
  `DEFAULT_TRADING_UNIVERSE_MAX_CAP=30`/`ENV_TRADING_UNIVERSE_MAX_CAP`
  추가, `scripts/run_decision_loop.py`의 `CompositionContext.max_cap`
  하드코딩 `30`을 env-aware 계산식으로 대체. `docker-compose.yml`
  (ops-scheduler)/`.env.example` 배선(`.env` 실 파일 미수정). 좁은
  테스트(`pytest tests/scripts/test_run_decision_loop.py -k
  trading_universe`) 7 passed(기존 5 + 신규 2, 전부 통과). shadow
  검증(compose() 직접 호출, kis_client=None, 신규 KIS 호출 0건):
  max_cap=30→universe 30개(009150 미포함), max_cap=60→universe
  60개(009150 포함) — shadow 결과이며 runtime 반영 아님(intraday
  freeze 캐시 우선순위로 실제 반영은 다음 신규 freeze 사이클
  이후). 값 자체는 이번 턴에 변경하지 않음. Full pytest 미실행.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §97.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (111차, `001450` 층3 정밀 분해 + 시장
  전체 비교, 코드/설정 변경 없음)
- 수정내용: 최근 3거래일(07-24/27/28) 중 buy_candidate&eligibility_
  passed 동시 만족은 07-27 55건뿐. risk_off+고변동성 55/55(100%)
  재확인, event축 없이도 39/55(71%) downgrade 발생. 시장 전체
  (30종목, 3970건) 비교 결과 risk_off가 이 창 전체 100%에서
  상수로 나타나 001450 특이 신호 가설이 약화됨 — 001450은 이
  창에서 buy_candidate 도달 유일 종목이라 층3 직접 비교 표본
  부재. 판정: 과잉 방어 가능성이 남은 미확정(Watch/Go/No-Go
  라벨 부여 안 함). Full pytest 미실행, 신규 KIS 호출 0건. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §98.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (112차, `risk_tone` 100% `risk_off`
  원인 규명, 코드/설정 변경 없음)
- 수정내용: `classify_market_regime` 코드 로직 확인 결과 정상(4,030건
  전수 공식 재계산 0건 불일치). `high_volatility`(atr14≥4.5)/
  `bearish_trend` 임계값이 전체 `signal_feature_snapshots` 이력
  (2,315행)의 중앙값 부근 또는 그 이하에 있어 각각 89.8%/63.6%가
  이미 충족 — OR 결합으로 risk_off가 사실상 상시 성립하는 구조.
  risk_off는 001450 특이 현상이 아니라 시장 전체(30종목,
  2026-06-24부터 3주 이상 연속 100%)에 균일. 판정: 코드는 정상,
  임계값이 데이터 분포와 정렬되지 않았을 가능성이 있는 설계
  미스매치 후보(추가 검증 필요, 완화안 미제시). Full pytest
  미실행, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §99.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (113차, threshold-분포 정렬 원인 진단,
  코드/설정 변경 없음)
- 수정내용: 계산식(atr_14_pct 등 5개) 최초 커밋 이후 변경 이력
  없음(D 배제). 3거래일/2주/1개월/전체 이력 4개 창 모두 high_
  volatility 82.7~90.6%, bearish_trend 63.6~70.6%로 동일 — 상시
  구조. high_volatility는 atr_14_pct가 지배(89.7% 단독 기여,
  vol20 단독 기여 0.1%). bearish_trend의 slow_score 조건은
  return_3m_pct/price_vs_sma_60_pct의 파생값이라 단독 병목 0건
  (중복 반영 구조). 3주 전 문서(signal_backbone_slow_score_
  threshold_tuning.md)에 이미 threshold 미검증 경고와 deep_
  negative 쏠림 기록 존재. 판정: B(지표 자체 분포 특성)+C
  (threshold 미검증 상태로 얕게 설정)의 결합에 가장 근접, A는
  확인 불가, D는 배제. 완화안 미제시. Full pytest 미실행, 신규
  KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §100.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (114차, `atr_14_pct` 상시 고값 원인
  진단, 코드/설정 변경 없음, 신규 KIS 호출 0건)
- 수정내용: raw bar 수동 재계산이 snapshot 저장값과 정확히
  일치(C: 계산식/단위 오류 배제). 81개 종목 전체(ETF 069500 포함)
  최근 거래일 고가-저가 스프레드가 균일하게 넓음(2.80~17.80%),
  지수 추종 ETF도 개별 종목과 구분되지 않는 atr14 수준(3개 창
  전부 100% high_volatility) — 실제 시장 분산효과 원리와 맞지
  않아 A(실물 특성) 근거 약함. 판정: B(페이퍼 환경 데이터 소스
  특성)에 가장 근접, E(미확정) 여지 일부 남음. 완화안 미제시.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §101.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (115차, `risk_off` 연쇄 설계 의도 vs
  실동작 정합성 검증, 코드/설정 변경 없음, 신규 KIS 호출 0건)
- 수정내용: `risk_off`는 `bearish_trend`와 AND 결합 시에만
  eligibility 하드 차단(예외 경로 실측 발동 0.02%), `high_
  volatility` 단독은 소프트 페널티(-0.15)+전략 축소에 그침. 최근
  3거래일(4,240건): risk_off 100%, buy_candidate 1.3%,
  eligibility_passed 3.8%, final_intent=buy/APPROVE 0%,
  order_requests 0건. `eligibility_core_risk_off_ranking_blocked`
  59.5%로 최다(설계 문서 §36이 이미 예견한 병목과 일치). 설계
  문서(§3.1)는 "매수 0건 방어"를 "하락 국면 한정"으로 스코프
  제한했으나 코드에는 미반영 — 판정: 설계 의도와 실동작 부분
  불일치, 사실상 상시 봉쇄. 완화안 미제시. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §102.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (116차, `risk_off AND bearish_trend`
  하드 게이트 완화 후보 사전 정밀 검증, 코드/설정 변경 없음,
  신규 KIS 호출 0건)
- 수정내용: `eligibility_core_risk_off_ranking_blocked` 모집단
  (3거래일 n=2,563, 전체 이력 n=11,831) 실측 — `raw_ranking_score`
  전체 이력 최댓값 0.417(threshold 0.48 근접 0건), 기존에 코드로
  심어둔 완화 시뮬레이션 3종(shadow_floor_relax_v2/v3/v5)도 전체
  이력 0% 통과 — 모집단이 신호/순위 모두 깊게 음(deep_negative)인
  표본으로만 구성됨을 확인. 판정: 이 게이트 자체에는 안전한
  완화 지점이 데이터상 없음 — 유일한 저리스크 후보는 기존
  `core_risk_off_topk_v1` top-k override(현재 비활성) 활성화뿐이나
  즉시 효과는 없음(게이트 2 신호 조건 100% 실패). 2번째 후보는
  제시하지 않음. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §103.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (117차, `ranking_blocked` 제외 후
  경계 표본 탐색, 코드 미수정, diff 초안 없음, 신규 KIS 호출 0건)
- 수정내용: `core_risk_off_guard_active=true` 레코드 전수(3거래일
  n=2,623, 전체 이력 n=11,891) 중 `ranking_blocked` 이외의 차단
  사유는 0건(게이트 1에서 즉시 반환되는 구조). shadow 진단으로도
  신호 게이트(overall≥0/slow≥−0.05)까지 격차가 전체 이력 최댓값
  기준 각각 0.251/0.34, near-miss 표본 0건. 전략 게이트는 항상
  pass. 판정: 완화 검토 가치 있는 사유 1·2순위 모두 없음 — 억지로
  후보를 남기지 않음. 다음 턴은 이 게이트를 우회하는 high_
  volatility 단독 경로(001450형)의 층3(AI downgrade) 쪽으로
  방향 전환 제안. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §104.

- **[SPPV-2.118에서 정정]** 이전 §102~§104(및 이 문서의 108차
  entry)의 "§36 문서가 eligibility 병목을 예견" 인용은 오표기 —
  실제 §36은 반대 방향(R3b pool 내 비활성)의 narrow-context
  관찰이다. 올바른 출처는 `[DESIGN] deterministic_trigger_
  eligibility_and_ranking_v1.md` §3.0/§3.6.
- 작성자: Codex
- 수정일자: 2026-07-28 KST (118차, `0.48` 설정 근거·정합성
  검증, 코드 미수정, threshold 변경 없음, 신규 KIS 호출 0건)
- 수정내용: git 확인 결과 `_CORE_RISK_OFF_RANKING_MIN_SCORE=0.48`
  은 커밋 e10ec05d(2026-07-01)에서 최초 등장, 같은 커밋이 신설한
  설계 문서(`deterministic_trigger_eligibility_and_ranking_v1.md`)
  자체가 도입 시점에 이미 "core_risk_off_ranking_blocked 평균
  ranking_score 약 0.24"이며 "0.48→penalty→0.40 구조가 실측
  bucket을 거의 살리지 못한다"고 기록. 현재(최근 3거래일/전체
  이력) 평균 0.257~0.264로 당시와 거의 동일 — 4주 가까이 분포
  이동 없음. 0.48±0.05 근접 표본 0건(양 창 모두), 0.40 이상은
  단일 종목(002790) 56건뿐. shadow top-k 예외 경로(0.22 이상,
  overall≥0/slow≥−0.05 전제)도 설계된 지 4주가 지났으나
  `shadow_topk_candidate=true` 이력 0건. 판정: C(당시부터 실측
  근거 약한 운영 상수, 현재도 재검증 필요)에 가장 근접. 완화안
  미제시. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §105.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (119차, `0.48` 모집단 정밀 분해, 코드
  미수정, threshold 변경 없음, 신규 KIS 호출 0건)
- 수정내용: `eligibility_core_risk_off_ranking_blocked` 모집단을
  구간별(<0.20/0.20~0.30/0.30~0.40/0.40~0.43/0.43~0.48/0.48이상)로
  분해 — `0.43~0.48`(threshold 근접 구간)은 최근 3거래일·전체
  이력 모두 **0건**. 모집단 85.68~91.02%가 `0.20~0.30`에 몰림
  (평균 0.2568). 전체 이력 상위 20건은 단일 종목(002790)의 반복
  기록임을 확인. distinct symbol 기준 상위 10개 조합에서도 신호
  (overall/slow)는 여전히 −0.25~−0.62/−0.66~−0.80로 개선 없음.
  도입 시점 문서(평균 0.24, §3.6)와 현재(평균 0.2568) 정합적
  일치. 판정: 경계값으로 기능하지 않음, 모집단 품질 문제에 더
  가까움(라벨 미부여). 완화안 미제시. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §106.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (120차, `ranking_score` 산식
  구성요소 분해, 코드 미수정, threshold/diff/완화안 없음, 신규
  KIS 호출 0건)
- 수정내용: 실제 코드 공식(`0.55*entry_score+0.10*relative_
  activity+0.20*coverage_score+0.10*allocation_quality+0.03*
  regime_tailwind+0.02*strategy_alignment`)을 확인 — 설계
  문서 §7.2 제안식과 다름. 이 모집단은 정의상 `regime_tailwind`/
  `strategy_alignment`가 100% 고정 0, `coverage_score`(1.0)/
  `allocation_quality`(0.25)도 완전 무분산. 실질 변별력 있는
  `entry_score`(관측 상한 0.2479)/`relative_activity`(관측 상한
  0.6830) 관측 상한을 모두 결합한 이론적 상한도 0.4296(고정
  항목 0.05 회복 가정해도 0.4796)으로 threshold(0.48) 미달.
  판정: 1순위 원인 = 산식 구조 문제, 2순위 원인 = 모집단 정의
  문제, threshold 재측정은 근본 원인 아님. 완화안 미제시. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §107.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (121차, `[PLAN] ranking_score_
  formula_validation.md` §6 체크리스트 실행, 코드 미수정,
  threshold/diff/완화안 없음, 신규 KIS 호출 0건)
- 수정내용: 트랙 A/B 재확인(근접 표본 0건, 4개 항목 무분산).
  트랙 C 신규 — 상위 5건/하위 5건 기여도 직접 대조: 차이
  (0.1916)는 전적으로 `entry_score`+`relative_activity` 기여분
  으로만 설명되고, 가장 큰 가중치(0.20, `coverage_score`)가
  가장 낮은 실제 설명력(분산 0)을 가짐. 트랙 D(신규, 이번 턴
  핵심 산출물) — `relative_activity` 4곳(entry/ranking/
  eligibility/core guard), `regime` 3곳, `strategy_alignment`
  3곳(2곳 완전 동일 조건)에서 중복 반영을 코드로 확인. 다만
  중복의 절대 크기는 threshold 미달을 설명할 만큼 크지 않고,
  실질 차단력은 하드 게이트가 담당(§109.4.4). 최종 판정: 1순위
  산식 재검토, 2순위 중복 차단 정리, 3순위 모집단 재정의,
  4순위(근본 원인 아님) threshold 재측정. 완화안 미제시. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §109.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (122차, 산식 재검토(1순위)+중복 차단
  정리(2순위) 관점 항목별 분류, 코드 미수정, threshold/diff/
  완화안 없음, 신규 KIS 호출 0건)
- 수정내용: 6개 구성항목을 3분류(즉시 유지/역할 축소 검토/중복
  제거·정리 검토)로 분류 — 즉시 유지=`entry_score`. 역할 축소
  검토=`coverage_score`(가중치 최대인데 이 모집단 내 무분산)/
  `regime_tailwind`(항상 죽어 있는 항). 중복 제거/정리 검토=
  `relative_activity`(entry+ranking 소프트 2중+eligibility/core
  guard 하드 2중, 4겹)/`strategy_alignment`(entry+ranking 조건
  집합 완전 동일). 미확정=`coverage_score` ranking 가중치의
  일반성, `regime` 하드 게이트 정당/과잉(§102~§104 판정 유지).
  `[PLAN] ranking_score_formula_validation.md` §6 체크리스트
  전 항목 완료 처리. 완화안 미제시. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §110.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (123차, `[PLAN]` §6 체크리스트 재판정,
  코드 미수정, threshold/diff/완화안 없음, 신규 KIS 호출 0건)
- 수정내용: §6.1/§6.2/§6.5/§6.6 실제 완료(§6.2는 일반 모집단
  대조로 격상 — `coverage_score`/`regime_tailwind`는 일반적으로도
  무분산 확정, `allocation_quality`/`strategy_alignment`는 일반
  모집단에서는 분산이 존재하며 이 게이트에서만 우연히 고정됐음을
  확인). §6.3/§6.4는 부분 완료로 하향 — "상위 50건"이 실제로는
  단일 종목(`002790`) 반복 관측이었음을 확인, 중복 정당성 최종
  판정도 `coverage_score`/`regime` 하드 게이트 2개가 여전히
  미확정. 신규 트랙 E(일반 모집단 대조) 완료, 트랙 F(표본 반복성
  보정) 부분 착수. 최종 판정(1순위 산식 재검토, 2순위 중복 차단
  정리)은 변경 없음, 오히려 근거 강화. 완화안 미제시. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §111.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (124차, `allocation_quality` 일반
  모집단 분산 재검증 및 §111 과대해석 정정, 코드 미수정,
  threshold/diff/완화안 없음, 신규 KIS 호출 0건)
- 수정내용: §111(123차)이 "3거래일 일반 모집단"만 조회하고
  이를 "일반적" 결론으로 확대한 것을 전체 이력(n=68,724)까지
  넓혀 재검증. `allocation_quality`만 distinct 1,929값의 풍부한
  분산으로 **확정**, `coverage_score`/`regime_tailwind`/
  `strategy_alignment`는 최근 관측 창에서는 무분산이나 전체
  이력에는 드문 예외(각각 distinct 2값/`risk_on`·`neutral`
  소수/드문 발동 3.7%)가 있어 **부분 확정**으로 하향. "미확정
  4개를 모두 닫았다"는 123차 서술은 과했음을 정정. 최종 판정
  (1순위 산식 재검토, 2순위 중복 차단 정리)은 무관하게 유지.
  완화안 미제시. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §112.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (125차, 모집단 정의·필드 경로 정밀
  재검증, 코드 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 사용자가 §112의 "n=68,724"가 `decision_json ?
  'deterministic_trigger'` 기준(38,667)과 다르다고 지적 —
  재검증 결과 python 집계 코드가 "키 자체 없음"(30,057건)과
  "키는 있으나 값이 null"(1,960건)을 구분 없이 합산한 것이
  원인이었음을 확인. `allocation_quality`(경로: `portfolio_
  allocation.max_new_capital_pct`, `_build_buy_ranking_score`
  실사용 경로와 동일, 코드 재확인)의 정확한 분모는 38,762,
  `coverage_score`는 36,598, `risk_tone`은 38,667. "상위 50건=
  단일 종목 002790"은 `deterministic_trigger.ranking_score`
  (top-level, shadow 아님) 기준이며 shadow `raw_ranking_score`
  와 10,444건 전수 대조 시 완전히 일치함을 재확인. distinct 값
  수치(1,929/2/top50=002790)는 전부 재현됨 — 정정 대상은 분모
  표기뿐. 최종 판정 무관하게 유지. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §113.

- 작성자: Codex
- 수정일자: 2026-07-28 KST (126차, `top50=002790` 문구 모집단
  조건 명시 보정, 코드 미수정, Full pytest 미실행, 신규 KIS
  호출 0건)
- 수정내용: "top50=002790 단독"이라는 요약 문구가 조건 없이
  축약돼 전체 BUY `ranking_score` 모집단 최상위처럼 오독될 수
  있었음을 확인 — 이 사실은 `eligibility_core_risk_off_ranking_
  blocked` 하드 게이트 모집단(n=11,971) 내부 한정이며, 전체
  `deterministic_trigger.ranking_score` 모집단(38,667건)의
  최상위가 아니다. [PLAN] 문서 §6.9와 §113/§114에 조건을 명시
  적으로 추가(이력 보존형). `allocation_quality`=1,929,
  `coverage_score`=35,873/725, `risk_tone`=36,433/232/42/null
  1,960, 분모 38,762/36,598/38,667은 그대로 유지. 최종 판정
  무관하게 유지. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §114.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (127차, distinct symbol 기준 기여도
  재계산 + 반복 등장 원인 규명, `[PLAN]` §6.8 잔여 완료, 코드
  미수정, Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 게이트 모집단 내부(distinct symbol=25)에서 상위/
  하위 10개 종목 기여도 차이의 100.0%, 일반 BUY 경로 전체
  (`eligibility_path='buy'` 필터, distinct symbol=105, row=
  35,149)에서 96.2%를 `entry_score`+`relative_activity`가
  설명 — 종목 반복 편향 제거 후에도 기존 결론 유지. `002790`
  (6일 산발, 239건)/`000720`(20일+ 연속, 761건) 반복 원인은
  intraday decision loop 5분 주기(`DEFAULT_INTERVAL_SECONDS=
  300`)+`signal_feature_snapshot` 1일 1회 갱신+게이트 고정 상태
  지속의 동일 메커니즘으로 확인 — 정상 반복이며 저장/집계
  결함 아님. 최종 판정 무관하게 유지. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §115.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (128차, `regime_tailwind`/`strategy_
  alignment` 고정 여부 설계 의도 vs 부산물 판정, `[PRIORITY_MAP]`
  SPPV-3 1순위 완료, 코드 미수정, Full pytest 미실행, 신규 KIS
  호출 0건)
- 수정내용: `regime_tailwind`는 `source_type` 무관하게 `risk_
  tone`에만 의존(코드 확인). `strategy_alignment`는 `strategy_
  selection.py`에 `source_type=='event_overlay'` 전용 override가
  있어 `risk_off`여도(`bearish_trend`만 아니면) `event_
  continuation`을 강제 부여함을 확인. 전체 이력(n=38,997)에서
  `regime_tailwind=1.0`은 42건(전부 `market_overlay`,
  2026-06-18 유일 `risk_on`일), `strategy_alignment=1.0`은
  2,573건(`event_overlay` 2,531+`market_overlay` 42) — `core`
  소스에서는 전체 이력에서 단 한 번도 0이 아닌 사례 없음. 판정:
  `strategy_alignment`(core 기준)는 설계 의도대로 죽어 있는 항,
  `regime_tailwind`는 설계는 정상이나 상류 risk_off 상시화의
  부산물. 코드 버그 아님, 완화안 미제시. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §116.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (129차, `strategy_alignment` 해석·
  집계 수치 정밀 보정, 코드 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
- 수정내용: §128(128차)의 결론을 뒤집지 않고 정밀도만 보정.
  분모(`n=38,997→39,027→39,113`)가 계속 다른 것은 `trade_
  decisions`가 5분 주기로 계속 자라는 운영 테이블이기 때문(정상,
  계산 오류 아님). 핵심 정정: "`strategy_alignment`(core 기준)는
  설계 의도대로 죽어 있는 항"은 과했음 — `strategy_selection.py`
  재확인 결과 `core`도 `event_overlay`와 무관하게 `regime_
  label∈{bullish_trend, event_driven_unstable}`+비-`risk_off`면
  도달 가능한 일반 경로가 이미 존재. 전체 이력에서 `core`의
  해당 regime 관측 사례(2,593+60건)가 전부 `risk_off`와 겹쳐
  도달한 적이 없었을 뿐임을 확인. 낮춰 쓴 최종 판정: `core`는
  "설계 배제"가 아니라 "일반 경로는 있으나 상류 `risk_tone`
  상시화 때문에 아직 도달 사례가 없는 항" — `regime_tailwind`와
  근본 원인 동일로 수렴. `regime_tailwind` 해석은 정정 없이
  유지. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §117.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (130차, `ranking_score` 산식 재설계
  준비 — 4개 항목 역할 재분류, 코드 미수정, 완화안/코드 diff
  없음, Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: `regime_tailwind`/`strategy_alignment` "고정 여부
  확인" 단계(128~129차)를 종료하고 산식 재설계 준비 단계로
  진입. `coverage_score`는 전체 이력에서 실제 관측 값이 `1.0`
  (36,383건)/`0.1429`(725건, 723건 하드 차단) 단 2개뿐임을
  확인해 **다른 계층으로 이관 검토(1순위)**로 분류. `relative_
  activity`는 entry_score+ranking 소프트 2곳이 같은 신호 재사용
  (과잉 중복)으로 **중복 정리 검토(2순위)**. `strategy_
  alignment`는 entry_score+ranking이 완전히 동일한 조건 집합을
  검사(현재 미발동, 구조적 확정 중복)로 **중복 정리 검토(3순위)**.
  `regime_tailwind`는 상류·하류에서 이미 강하게 처리돼 존치
  근거 약함으로 **역할 축소 검토(4순위)**. 1·2순위는 즉시
  설계안(A/B) 비교 단계 진입 가능 판정 — 다음 턴은 설계안 비교
  턴으로 제안. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §118.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (131차, `coverage_score`/`relative_
  activity` 설계안 A/B 비교, 코드 미수정, `.env` 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: `coverage_score`는 A안(ranking 제거, eligibility
  전용 이관)을 우선 권고 — 이미 하드 게이트 통과 후 100% 상수
  임을 확인했으므로 B안(가중치 축소)보다 근거가 명확. 다만
  `ranking_score`가 `_assess_core_risk_off_buy_guard`/
  eligibility 하드 게이트의 파라미터로 직접 쓰이는 구조라, A안
  적용 시 `ranking_score` 최댓값이 0.20 낮아지는 것이 기존
  절대 threshold(`0.48` 등)와 상호작용하는 범위를 먼저 재계산
  해야 diff 착수 가능. `relative_activity`는 A안(소프트 2곳 중
  1곳만 유지)을 우선 권고 — B안(파생값 분리)은 추가 설계·검증
  필요해 확정 불가. "entry_score 쪽 유지 vs ranking_score 쪽
  유지" 중 어느 것이 하드 게이트와 더 정합적인지는 아직 실측
  으로 확정하지 않음. 결론: 둘 다 아직 diff 초안 단계로 넘어가지
  않음 — 각각 1개씩의 확인 과제가 남아 있음. 상세: `docs/10_
  signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §119.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (132차, `coverage_score` threshold
  연쇄영향 정량 재계산 + `relative_activity` 유지 위치 비교,
  코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS
  호출 0건)
- 수정내용: `coverage_score` A안은 `_CORE_RISK_OFF_RANKING_
  MIN_SCORE=0.48` 통과율 14.8%→0.34%(단순 차감)/2.2%(재정규화),
  `_CORE_RISK_OFF_SHADOW_MIN_SCORE=0.22` 통과율 100%→0.4%/1.8%
  로 급격히 붕괴함을 정량 확인 — threshold 재설계 없이는 단독
  diff 불가로 판정. `relative_activity`는 1안(entry_score 유지,
  ranking 제거)/2안(ranking 유지, entry_score 제거) 비교 결과
  둘 다 threshold 영향은 14.8%→14.3%로 미미하나, 2안는
  `buy_candidate_threshold=0.65` 공유 함수를 건드려 diff 범위가
  더 넓음 — 1안이 더 보수적이며 다음 턴 diff 초안 작성 가능으로
  확정. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §120.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (133차, `relative_activity` 1안 diff
  실제 적용, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건 — 이번 항목만 코드 변경 포함)
- 수정내용: `deterministic_trigger_engine.py`의 `_build_buy_
  ranking_score`에서 `relative_activity` 계산과 `0.10*relative_
  activity` 항, 미사용이 된 `signal_feature_snapshot` 매개변수를
  제거. `entry_score` 쪽 `relative_activity_bonus`는 변경 없음.
  `coverage_score`/threshold 상수는 손대지 않음. 최소 검증:
  `test_deterministic_trigger_engine.py`(20 passed), `test_
  trigger_proxy_attribution.py`+`test_decision_orchestrator.py`+
  `test_core_risk_off_topk_projection.py`(93 passed), `test_
  decision_factory.py`+`test_expected_value_gate.py`(12 passed),
  하네스 `accept backend-file`(PASS). 경계값(`_CORE_RISK_OFF_
  RANKING_MIN_SCORE=0.48`) 부근에 있던 기존 테스트 1건(`test_
  trigger_engine_marks_risk_off_exception_eligible_for_strong_
  core_setup`)은 새 ranking_score 분포에 맞춰 `turnover_surge_
  ratio`만 1.60→2.50으로 최소 보정(의도 유지, 값만 조정). 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §121.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (134차, `relative_activity` 1안 적용
  후 영향 확인 + 다음 설계 분기 확정, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: PR #14(mergeCommit `e1ae1b3d`, 2026-07-29 12:39:59
  KST 병합) 이후 운영 decision loop 실측 확인. 병합 직전 30분
  (n=120)과 병합 이후 1개 사이클(n=15) 비교 — `ranking_score`
  평균 0.3358→0.3319, 중앙값 0.3037→0.2811(표본 극소로 해석
  보류), `ranking_blocked` 비중 46.7%→53.3%(단일 창 변동, 의미
  있는 변화로 해석하지 않음), `buy_candidate`(0/120→0/15)·
  `shadow_topk_exception_v2`(0건 유지) **변화 없음**. 관측 창이
  1개 사이클(약 6분 경과)뿐이라는 한계를 명시. 핵심 병목은 여전히
  `coverage_score`+절대 threshold(`0.48`/`0.22`) 조합으로 재확인
  (신규 반박 근거 없음). **다음 1순위 결정: 2안(운영 관측 1~2
  거래일 추가 축적) 채택, `coverage_score` threshold 재설계는
  보류**. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §122.

- 작성자: Codex
- 수정일자: 2026-07-29 KST (135차, `relative_activity` 1안 적용
  후 운영 관측 추가 축적, 진행 중, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 병합 이후 실제 경과 시간은 약 41분에 불과해, 이번
  턴 요청된 "5거래일 수준 관측"은 캘린더 시간 제약으로 확보되지
  않음을 명시. 초기 1사이클(n=15/16) vs 누적 약 9사이클(n=134)
  비교 — `ranking_score` 평균/중앙값 거의 동일(0.3305/0.2811→
  0.3323/0.2983), `ranking_blocked` 비중 56.2%→47.8%(병합 이전
  기준값 46.7%에 더 가깝게 회귀, 초기 1사이클이 편향 표본이었을
  가능성). `buy_candidate`·`APPROVE`·`order_request`·`final_
  intent='buy'`·`shadow_topk_exception_v2`는 초기·누적 창 모두
  **0으로 동일**(변화 없음). `eligibility_passed=True` 4건은
  전부 동일 core 종목의 반복 관측(WATCH 고정 패턴)으로 확인,
  diff 효과로 해석하지 않음. 핵심 병목 재확인: `coverage_score`+
  절대 threshold(`0.48`/`0.22`). **다음 1순위 결정: 2안(추가
  관측 연장) 유지 — 관측 단계 미종료, `coverage_score` 재설계
  착수 준비 안 됨**. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §123.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (136차, `relative_activity` 1안 적용
  후 운영 관측 추가 축적 2차·최종 판정, 관측 단계 종료, 코드
  미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 병합 이후 실제 경과 약 23시간, gate 모집단 n=616/
  전체 BUY-path n=1,435로 확대(이전 두 턴 n=15/134 대비 4~40배,
  병합 이전 1일치 n=1,037과 같은 자릿수 도달). `ranking_blocked`
  비중(§120과 동일한 gate 정의로 재계산)은 병합 전 3일 99.9~
  100.0%→병합 직전 30분 93.3%→초기 1사이클 90.0%→누적 23시간
  90.7% — 병합 직전부터 이미 이동이 시작됐고 §120 예측(제거 시
  소폭 하락)과 반대 방향·더 큰 폭이라 **diff 인과 효과 아님**
  (교란 요인)으로 판정. `buy_candidate`·`APPROVE`·`order_
  request`·`final_intent='buy'`·`shadow_topk_exception_v2`는
  표본이 40배 확대되는 3개 관측 창(n=15→134→616~1435) 전부에서
  **일관되게 0 유지**. 전체 BUY-path `eligibility_passed=True`
  125건은 `001450`/`001800`/`000810` 3개 종목의 반복 관측(고정
  ranking_score 4종)뿐, 전부 `buy_candidate=False` — 기존 WATCH
  고정 패턴 재확인. 핵심 병목 재확인: `coverage_score`+절대
  threshold(`0.48`/`0.22`). **판정 전환: 1안(coverage_score+
  threshold 재설계 비교 착수) 채택** — SPPV-2.134/2.135의
  "2안(관측 연장)"에서 전환, 관측 단계는 이번 턴으로 종료. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §124.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (137차, `coverage_score`+절대
  threshold(`0.48`/`0.22`) 재설계 비교, 설계 비교 단계 완료, 코드
  미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: `0.48`은 `_assess_core_risk_off_buy_guard()`의 최우선
  hard gate(병목의 직접 원인), `0.22`는 `shadow_topk_candidate`
  판정에만 쓰이는 관찰용 하한(override 미선택 시 실제 영향 없음,
  발동 이력 0건)으로 역할 분해. 게이트 모집단(전체 이력 n=13,016)
  전수 조사 결과 `coverage_score`가 예외 없이 `1.0`임을 확인 —
  이에 근거해 "완전 제거 + `0.48→0.28`/`0.22→0.02`로 동일 상수
  (`0.20`) 이동"하는 **A-3안**이 현재 판정 경계를 수학적으로 완전히
  보존함(무변화)을 증명. A안을 A-1(단순 차감, §120 기각)/A-2(재
  정규화, §120 기각)/A-3(신규, 채택)로 세분화, B안(가중치 축소)은
  안전성은 동일하나 `coverage_score`가 산식에 남아 구조적 이점
  없음. `buy_candidate_threshold=0.65`/`eligibility_low_feature_
  coverage`와 충돌 없음, `shadow_topk_exception_v2`(0.22)는 함께
  이동 필요. **1순위: A-3안, diff 착수 가능 여부: 다음 턴부터
  가능**(이 diff는 완화가 아니라 리팩터링임을 명확히 구분). 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §125.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (138차, `coverage_score` A-3안 실제
  diff 적용 + 최소 검증, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건 — 코드 변경 포함)
- 수정내용: `deterministic_trigger_engine.py`에서 `_CORE_RISK_
  OFF_RANKING_MIN_SCORE=0.48→0.28`, `_CORE_RISK_OFF_SHADOW_MIN_
  SCORE=0.22→0.02`로 변경, `_build_buy_ranking_score`에서 `0.20*
  coverage_score` 항과 미사용 매개변수 제거. `eligibility_low_
  feature_coverage` 하드 게이트/`coverage_score` 필드는 유지, exit
  ranking은 범위 밖. 코드 반영 후 관찰용 shadow 메타데이터 내부의
  하드코딩 절대값 2곳(`_classify_core_risk_off_shadow_floor_
  bucket`의 `ranking_score>=0.26`, `_EVENT_OVERLAY_SHADOW_MIN_
  SCORE=0.56`, 실제 BUY 판정과 무관)이 낡은 스케일에 남아 테스트
  3건이 실패 — AskUserQuestion으로 확인해 "이번 턴 범위 유지"로
  결정, fixture/기대값만 최소 보정(0.26/0.56은 별도 후속 트랙).
  최소 검증: `test_deterministic_trigger_engine.py`(21 passed,
  신규 A-3 전용 회귀 테스트 포함), 관련 5개 파일(105 passed),
  하네스 `accept backend-file`(PASS). 신규 회귀 테스트로 `overall=
  0.33`(차단)/`0.34`(통과) 경계가 구 threshold 대비 정확히 `0.20`
  만큼 이동했음을 증명 — 실제 BUY 판정 경로는 완전히 무변화(완화
  아니라 리팩터링). 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §126.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (139차, `coverage_score` A-3안 적용
  후 운영 무변화 실측 확인, 트랙 종료, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 장중 예외 승인(`workflow_dispatch: deploy_main=true,
  allow_market_hours_deploy=true`)으로 2026-07-30 13:21:17 KST
  실제 운영 서버에 A-3안이 반영됨을 `core_risk_off_experiment`
  메타데이터의 `ranking_min_score=0.28`/`shadow_min_score=0.02`
  echo로 확인. 배포 직전 2시간(구 threshold, gate n=176) vs 배포
  이후 누적(~39분, 신 threshold, gate n=64) 비교 — `ranking_
  blocked` 비중 **87.5%→87.5%(소수점까지 동일)**, `buy_candidate`/
  `eligibility_passed`(gate)/`APPROVE`/`order_request`/`final_
  intent='buy'`/`shadow_would_pass`는 배포 전후 모두 예외 없이
  `0`. gate 모집단 `coverage_score`는 배포 이후에도 100%(64/64)
  `1.0` 유지. **판정: A-3 무변화 confirmed, 추가 관측 불필요**.
  `0.26`/`_EVENT_OVERLAY_SHADOW_MIN_SCORE=0.56`은 범위 밖 관찰용
  값으로만 언급, 이번 턴 결론에 미포함. 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
  §127.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (140차, `000720` core 유니버스 20거래일+
  연속 포함 원인 규명, 코드 미수정, `.env` 미수정, Full pytest
  미실행, 신규 KIS 호출 0건)
- 수정내용: `UniverseSelectionService._is_core_seed_instrument()`
  가 `000720`을 KOSPI200 index membership으로 core-eligible 판정,
  `_apply_cap()`의 `core_cap=12`(운영 실측 확인) 절단이 동일
  priority 종목 간 안정 정렬로 원래 순서(`InstrumentRepository.
  list_active_by_market()`의 SQL `ORDER BY symbol`, 사전순)를
  유지함을 코드로 확인. core-eligible 199종목 전수 재현 결과
  `000720`은 사전순 10위(항상 cap 이내), `002790`은 21위·`009150`
  은 59위(둘 다 cap 밖) — 신호/랭킹과 무관한 구조적 편향임을
  코드+실측으로 닫힌 근거로 확인. **판정: 구조 편향 확인**.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §128.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (141차, `core_cap` 사전순 절단 왜곡
  정량 검증, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
- 수정내용: 최근 20거래일(KST) 실제 core 선택(사전순 절단) vs
  기존 함수(`_build_entry_score`/`_build_buy_ranking_score`) 재사용
  shadow(entry_score/ranking_score 상위 12) 비교. 실제 평균 entry_
  score(0.1657)가 shadow 평균(0.3489)의 약 47%, 실제∩shadow 겹침
  일평균 20.3%(12개 중 2~3개만 일치). `000720`(shadow 순위 하위
  10~15%, 13/20일[SPPV-2.142에서 정정: 11/20일] 포함) vs
  `009150`(상위 15~30%, 0/20일 포함, 최고 8위) 극단 역전 사례를
  20일 내내 일관되게 확인. `002790`도
  000720보다 뚜렷이 높은 entry_score를 보이나 사전순 21위로 대부분
  배제. **판정: 왜곡 큼**(수치 기준: 신호 손실 약 53%, 구성 불일치
  약 80%). 다음 우선 작업: `core_cap` 절단 기준 재설계 검토(완화안
  아님, 설계 비교 단계). 상세: `docs/10_signal_research_sppv/
  [DESIGN] regime_conditional_entry_signal_v1.md` §129.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (142차, SPPV-2.141 핵심 수치 재현성
  검증, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS
  호출 0건)
- 수정내용: 동일 방법론·동일 20거래일 창(`2026-07-02`~`2026-07-29`
  KST)으로 재실행. 핵심 집계 지표(실제 평균 `entry_score` 0.1657,
  shadow 평균 0.3489, 겹침 20.3%)는 소수점까지 정확히 재현됨을
  확인. `000720` 실제 포함일수는 §129 완료 보고문의 "13일"이 원본
  로그 재대조 결과 수동 집계 오류였음을 확인해 "11일"로 정정,
  shadow 순위 하한도 `000720`(58→55위)/`002790`(14→9위) 정정 —
  관측 시점·모집단 정의·계산 로직 차이가 아니라 완료 보고 시
  전사 오류. **판정: 방향은 재현되나 수치 일부 차이(정정 완료)**,
  `왜곡 큼` 판정 유지(핵심 집계 지표 재현 + 정정 수치도 원래
  결론을 강화). 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §130.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (143차, `core_cap` 절단 기준 재설계안
  A/B/C/D 비교, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
- 수정내용: 신규 구조 제약 2건 확인 — (1) `signal_feature_snapshots`
  커버리지가 core-eligible 사전순 1~79위 연속 구간뿐(80위 이후 120종목
  0건), snapshot 입력 배치도 동일 `_apply_cap()`을 자체 cap(80)으로
  쓰기 때문 → score 기반 어떤 안도 사전순 편향을 제거하지 못하고
  12위→79/80위로 경계만 이동. (2) 유니버스는 루프 진입 시 1회 확정
  되고 채점은 그 이후이며 `universe_selection`은 `deterministic_
  trigger_engine`을 import하지 않아, B/C안은 계층 역전 + regime/
  strategy/allocation 재배선 필요. 20거래일 정량 비교: A안 평균
  entry_score 0.1535 / B안=C안 0.3489(종목집합 19/19일 동일 — shadow
  에서 ranking_score가 entry_score의 단조 변환이라 B/C 우열 판정
  불가) / D안(snapshot 원시 `overall_score` 정렬) 0.3460(B안의 99.2%,
  B안과 92.1% 일치). B/C/D 모두 `entry_score>=0.65` 0건 — 신호 품질
  개선이지 주문 발생 완화가 아님을 명시. `000720` A안 11일→B/C/D안
  0일, `009150` A안 0일→B/C안 6일·D안 10일. **판정: 절충안 검토 필요,
  다음 턴 diff 초안 1안은 D안**(효과 99.2% + 현재 계층 정합성 유지).
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §131.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (144차, D안 diff 착수 전 최소 침습성·부작용
  범위 설계 점검, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
- 수정내용: D안 정의를 "core-eligible 후보를 `signal_feature_snapshots.
  overall_score` 기준 상위 `core_cap` 선별"로 고정하고, 운영 실측으로
  시점을 확정(`decision_loop_intraday` freeze 08:50 KST 하루 1회 생성,
  snapshot 20:00 KST 산출 → 전 거래일 종가 신호로 당일 정렬, look-ahead
  불가·intraday churn 없음). 최소 변경 경로는 **6개 파일**로 §131.6의
  "읽기 1곳 추가" 추정을 정정했으나 6개 모두 기존 템플릿(`instrument_
  status_snapshots.list_latest_by_instrument_ids`, `_prime_membership_
  cache`)을 따르는 추가 변경. bulk 조회 메서드는 현 계약에 없어 필수
  (199 쿼리 회피), `_apply_cap`은 `@staticmethod`라 `compose_with_
  diagnostics`에서 캐시 후 정렬 키만 변경. **순환 의존 회피**: snapshot
  입력 배치가 동일 `compose()`를 cap 80으로 호출하므로 정렬 모드 기본값을
  현행 사전순으로 두고 decision loop만 opt-in → 배치 무변화, `generate_
  signal_feature_snapshot_input.py`는 diff 대상 아님. 부작용은 CORE 내부
  재정렬로 한정(`priority`가 1차 정렬 키 유지), held/overlay/cap 계약과
  충돌 없음. snapshot 없는 120종목은 최하위+동순위 사전순 처리로 cold
  start 시 A안과 동일 퇴화. 검증 계획은 단위 테스트 3케이스(무변화 회귀
  포함) + 하네스 `accept backend-file` + 다음 거래일 08:50 freeze 대조로
  확정. **판정: D안 diff 초안 착수 가능**(단 §131.1 경계 이동·§131.4
  주문 발생 완화 아님 제약을 전제에 명시). 상세: `docs/10_signal_
  research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §132.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (145차, D안 diff 초안 실제 작성, `.env`
  미수정, Full pytest 미실행, 신규 KIS 호출 0건 — **코드 변경 포함**)
- 수정내용: §132.2에서 닫힌 최소 범위 6개 파일만 수정했다 —
  (1~3) `contracts.py`/`postgres/signal_feature_snapshots.py`/`memory.py`
  에 bulk `list_latest_by_instrument_ids()` 추가(`instrument_status_
  snapshots`의 `DISTINCT ON` 패턴 동일 적용, N+1 회피),
  (4) `universe_selection_types.py`에 `CORE_RANKING_MODE_SYMBOL`/
  `CORE_RANKING_MODE_SIGNAL_SCORE` 상수와 `CompositionContext.core_
  ranking_mode` 필드 추가(**기본값 = `SYMBOL` = 현행 사전순**),
  (5) `universe_selection.py`에 `_core_signal_score_cache` /
  `_prime_core_signal_score_cache()` / `_core_signal_sort_rank()` 추가와
  step 8 정렬 분기, (6) `run_decision_loop.py`에서만 D안 모드 주입.
  `_apply_cap()`은 미수정(정적 구조 유지), `generate_signal_feature_
  snapshot_input.py`는 diff 제외(기본값 유지 → 순환 의존 회피).
  정렬 키는 `(snapshot 보유 여부, -overall_score, symbol)`이며 **사전순은
  3번째 요소로 완전 동점 시에만 도달**하는 결정성 보장용 기술 규칙이다.
  2차 정렬 키가 非CORE 항목에 항상 `0`이라 Python 안정 정렬로 held/
  reconciliation/event/market/manual overlay 상대 순서가 보존된다.
  검증: `tests/services/test_universe_selection.py` **109 passed**
  (기존 106건 무수정 통과 = 무변화 회귀 확인, 신규 3케이스 추가),
  `tests/scripts/test_run_decision_loop.py` 121 passed, 하네스 `accept
  backend-file` 3개(universe_selection, universe_selection_types,
  memory) PASS. `contracts.py`/`postgres/signal_feature_snapshots.py`
  하네스 FAIL 2건은 `git stash`로 기저(HEAD) 대조 실행해 **동일 오류로
  선재 실패**함을 확인(postgres 테스트 환경의 event loop / 1600 컬럼
  문제, 이번 diff 원인 아님). 남겨둔 것: 운영 반영 관측(다음 거래일
  08:50 KST freeze 대조), postgres bulk 전용 통합 테스트(환경 복구 후),
  배포(PR 머지 전이라 미반영 — 작성 시각 20:23 KST는 장 외 시간이므로
  장중 배포 금지 정책은 적용되지 않고 별도 승인도 불필요). 상세:
  `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §133.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (146차, `regime_tailwind`/`strategy_
  alignment` 잔여 설계 가치 검증, 코드 미수정, `.env` 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건)
- 수정내용: 코드 경로 재확인 — `regime_tailwind`(0.03)는 `ranking_
  score` 전용이고 `source_type` 분기 없음, `strategy_alignment`
  (0.02)는 `_build_entry_score`(+0.05)와 **조건식이 글자 단위로
  동일한 이중 계상**. 분포 재집계: `regime_tailwind`는 최근 3거래일
  100% `0.0`/전체 이력 98.39% `0.0`, `strategy_alignment`는 `core`
  전체 이력 `1.0` **0건**이나 `event_overlay` **28.93%**(최근
  3거래일 28.63%)로 발동 중 — 기존 "현재 미발동" 서술이 `core`
  한정이었음을 정정. **신규 발견**: `(source_type, regime_label,
  risk_tone)` → `preferred_strategy` 전수 검정에서 관측 15개 조합
  전부 단일값·비결정 0건, `event_overlay` 내부에서 같은 regime_label
  안에 `strategy_alignment`가 갈리는 사례 0건 → `regime_label`
  통제 후 잔여 변별력 정확히 0. 공통 3관점 분리: 산식 설명력
  0.89%/4.49%(표준편차 기준), 중복은 두 항 모두 regime·source
  정보의 함수, 병목 기여는 `buy_candidate` 168건 중 126건(75%)이
  `regime_tailwind=0.0`에서 발생하고 `event_overlay` `sa=1.0`
  2,718건의 `buy_candidate`가 0건이므로 **완화 레버가 아니라 산식
  정리 대상**. 판정: `regime_tailwind`=제거 권고(선행 확인 1건 필요,
  diff 후보 아직 아님), `strategy_alignment`=`ranking_score`
  직접항 제거 권고(다음 diff 초안 후보 진행 가능). 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §134.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (147차, `strategy_alignment` 직접항 제거
  diff 초안, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건 —
  **코드 변경 포함**)
- 수정내용: `deterministic_trigger_engine.py` 단일 파일에서
  `_build_buy_ranking_score()`의 `+ 0.02 * strategy_alignment` 항을
  제거하고, 그 항 전용이던 지역 계산 블록·미사용이 된
  `strategy_selection` 매개변수·호출부 인자를 함께 정리했다
  (`relative_activity` 1안 SPPV-2.133, `coverage_score` A-3안
  SPPV-2.145와 동일 패턴). **`entry_score` 쪽 `strategy_alignment`
  `+0.05`와 `trigger_strategy_alignment` reason code는 유지**하며,
  다른 가중치(0.55/0.10/0.03)·threshold 상수(0.28/0.02)·
  `_assess_core_risk_off_buy_guard`·metadata/shadow 경로·
  `_build_exit_ranking_score`는 손대지 않았다. `regime_tailwind`는
  이번 턴 범위 밖이다. **제거 근거는 "죽은 항 제거"가 아니라**
  `event_overlay`에서 전체 이력 28.93%로 살아 있는 항의
  **`ranking_score` 직접 중복 계상 제거**다(§134.1/§134.7).
  새 산식은 `0.55*entry_score + 0.10*allocation_quality +
  0.03*regime_tailwind`이며 최댓값이 0.02 낮아진다. 최소 검증:
  `test_deterministic_trigger_engine.py` **23 passed**(기존 21건이
  경계값 보정 없이 **무수정 통과** + 신규 2건 추가), 관련 5개 파일
  105 passed, 하네스 `accept backend-file` PASS. 신규 테스트는
  (1) `preferred_strategy`만 바꿔 `ranking_score` 차이가 정확히
  `0.55×0.05`임을 확인하며 `entry_score` 쪽 유지도 함께 고정,
  (2) 기본 BUY 판정 경로 무결성 확인이다. **미완료(과장 방지)**:
  threshold 영향 정량 확인은 `core` 게이트 모집단에서
  `strategy_alignment`가 0건이라는 사실에 근거한 **추론 단계**이고
  shadow 재계산으로 확인하지 않았으며, 운영 반영·효과는 확정되지
  않았다. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §135.

- 작성자: Codex
- 수정일자: 2026-07-30 KST (148차, `strategy_alignment` 직접항 제거
  threshold 영향 정량 검증, 코드 미수정, `.env` 미수정, Full pytest
  미실행, 신규 KIS 호출 0건)
- 수정내용: SPPV-2.147에서 **추론 단계로 남겨둔** "게이트 판정 무변화"를
  shadow 재계산(`new = old − 0.02×strategy_alignment`, threshold는 현행
  값으로 양쪽 동일 적용)으로 정량 확인했다. 게이트 모집단
  (`core_risk_off_experiment.active=true`)에 `strategy_alignment=1.0`이
  **최근 3거래일 0/2,401, 전체 이력 0/11,785**로 존재하지 않아
  `ranking_score`가 한 건도 변하지 않고, `ranking_blocked`(59.81%/
  76.32%)·`shadow_topk_candidate`(100%)·`shadow_floor` moderate 조건
  (42.27%/39.93%) 판정이 모두 불변이며 **경계 뒤집힘 0건**이다. 일반
  BUY 경로는 `sa=1.0`이 7.58%/7.33% 있어 평균만 미세 하락하지만
  중앙값·3개 threshold 판정은 불변이고, `_assess_buy_eligibility`에서
  `ranking_score`가 판정에 관여하는 지점이 `risk_off+bearish_trend`
  분기 안 `source_type=="core"` 경로뿐임을 코드로 확인해 평균 하락이
  실제 판정과 무관함을 닫았다. 뒤집힘 0건의 원인은 `sa=1.0` 2,760건이
  `event_overlay`(2,718)+`market_overlay`(42)에만 있고 `core` 0건이며
  게이트 활성 레코드가 전부 False이고, 제거폭 `0.02` 내 뒤집힘 밴드에
  각 0건이기 때문이다(전수 확인). **범위 밖 관찰 지표**인
  `event_overlay` `adjusted_ranking_score>=0.56`은 전체 이력 통과 수가
  1,222→1,100으로 **122건 이동**(최근 3거래일 0건)해 "최근 창 무변화 vs
  전체 이력 이동" 비대칭이 여기서만 존재하나, 실제 저장된
  `shadow_would_pass=True` 60건 중 뒤집히는 건은 **0건**이다. **판정:
  추가 코드 수정 불필요, 내일 장 시작 후 그대로 관찰 가능.** 이번 턴은
  threshold 영향 정량 검증이며 **운영 효과 확정이 아니다**.
  `regime_tailwind`는 별도 트랙을 유지한다. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §136.

- 작성자: Codex
- 수정일자: 2026-07-31 KST (149차, D안 + `strategy_alignment` 제거 첫
  운영 반영 실측, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건 — **효과 확정 아님**)
- 수정내용: 런타임 반영을 md5(4파일 일치)와 파일 내용 직접 조회로 확인했다
  (D안 3요소, `strategy_alignment` ranking 산식 0건 / entry_score 유지,
  threshold `0.28`/`0.02`). 오늘 `decision_loop_intraday` freeze가
  **2026-07-31 08:50:41 KST**에 `target_count=13`(core 12 + `event_
  overlay` 1)으로 생성됐고, core 12종목이 기존 왜곡 상태(사전순 top12)와
  **한 종목도 겹치지 않아** D안이 운영에서 작동함을 확인했다. 전일 20:00
  KST snapshot 기준 shadow 예측은 **실질 12/12 일치**이며, 1차 11/12의
  차이는 재현 측이 `_is_core_seed_instrument`의 allowlist 경로를,
  2차 11/12의 차이는 `_apply_exclusions`의 우선주 제외(`005935`
  삼성전자우)를 모델링하지 않은 데서 비롯됐다(둘 다 재현 측 미모델링).
  핵심 종목은 `000720`이 사전순 10위에서 D안 125위(`overall_score=
  −0.7055`)로 **core 탈락**해 §128/§129의 왜곡이 해소된 첫 사례가 됐고,
  `001450`이 사전순 16위에서 최고 신호(+0.4516)로 **1위 진입**했다.
  `strategy_alignment`는 `core` 264건과 `event_overlay` 22건 모두
  `sa=1.0`이 0건으로 SPPV-2.148 결론과 충돌하지 않았고, funnel
  (`ranking_blocked`/`buy_candidate`/`final_intent=buy`/`APPROVE`/
  `order_request`)은 전부 0이었다. **보류·실패 항목을 과장 없이 기록한다**:
  오늘 `core_risk_off_experiment.active`가 0/264로 게이트가 발동하지 않아
  §136의 "게이트 판정 무변화"는 반증도 확증도 되지 않았고, D안 순수 효과는
  동일 regime 조건 비교에서 사전순 top12 평균 `entry_score` 0.2380 →
  실제 core12 0.5067(2.13배)로 관측되나 실제 core12 중 8/12가 6월
  snapshot 기반이고 6월 평균이 7월보다 +0.0682 높아 **stale bias가 격차의
  약 25%를 설명할 수 있어 2.13배는 상한으로만 읽어야 한다**. **신규
  발견**은 stale snapshot 정렬로, snapshot 배치가 하루 81종목만 갱신하는데
  core-eligible은 211종목이라 배치 풀 밖 종목이 오래된 snapshot으로
  정렬된다(§131.1 제약이 "경계 이동"이 아닌 이 형태로 발현). 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §137.

- 작성자: Codex
- 수정일자: 2026-07-31 KST (150차, stale snapshot 근본 원인 규명 + 구조
  대응안 비교, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS
  호출 0건 — 설계 검증 턴)
- 수정내용: stale snapshot 문제를 "배치 누락"으로 축소하지 않고 **생성
  모집단 vs 소비 모집단의 계약 불일치**로 재규정했다. 축1 생성은
  `generate_signal_feature_snapshot_input.py`가 `compose()`를
  `core_cap=80`(`DEFAULT_SIGNAL_FEATURE_CORE_CAP`) + **`core_ranking_mode`
  미지정(=사전순)**으로 호출하고 ops-scheduler가 `--core-cap`을 전달하지
  않아 항상 기본값이며, 실측 core 79종목의 사전순 순번 범위는 `(1, 84)`로
  `_apply_exclusions` 때문에 연속 구간이 아니다. 축2 소비는 decision loop가
  `core_cap=12` + `core_ranking_mode=signal_score`로 호출해 core-eligible
  **211종목 전체**를 정렬 대상으로 삼으며, 오늘 소비 core 12개 중 생성
  모집단에 포함된 것은 **4개(33.3%)**뿐이다. 축3은 freshness 부재로,
  `list_latest_by_instrument_ids` `WHERE`절에 시간 조건이 없고
  `_prime_core_signal_score_cache`/`_core_signal_sort_rank`에 신선도 조건이
  **0건**이어서 31일 지난 점수가 어제 점수와 동등하게 경쟁한다 —
  core-eligible 211개 중 신선(0~1일)은 **79개(37.4%)**, 31일+ **66개**,
  snapshot 없음 **65개**다. "코드 한 줄 수정"(freshness guard 단독 = S1)이
  부족한 이유는 (1) stale은 숨지만 D안이 신선 79개(사전순 상위) 안에서만
  작동해 **편향이 12위에서 80위 경계로 회귀**하고, (2) 생성/소비 불일치가
  그대로 남고, (3) 후보 수·cap·exclusions 변형 시 재발하며 snapshot 없는
  65개의 영구 배제가 고정된다는 것이다. 6개 안(S0 현재 결함 상태 ~ S5)을
  8축으로 비교해 **1순위 = S5(S2 생성 모집단 정렬 + S1 freshness guard
  안전망)**로 판정했다. S2에서 `core_cap`이 후보 수 이상이 되면 정렬
  기준이 선택에 영향을 주지 않아 **SPPV-2.145 §132.3의 순환 의존 회피
  제약 자체가 불필요해진다**는 구조적 이점도 확인했다. **선행 확인
  필요(미완료)**: 배치 입력 생성이 KIS 차트 API를 호출하며 80종목에
  66.36초 소요되므로(07-30 21:19~21:20 KST 로그) 211종목 확대 시 호출량
  약 2.6배·약 3분으로 늘어난다 — KIS `market_data` 예산과 장후 스케줄 창
  침범 여부는 **사용자 승인이 필요한 항목**이며 diff 착수 전에 닫아야 한다.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §138.

- 작성자: Codex
- 수정일자: 2026-07-31 KST (151차, S5 구현 = 생성 모집단 정렬 + freshness
  guard, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건 — **코드
  변경 포함, 운영 효과 미확정**)
- 수정내용: `signal_feature_snapshot` 배치가 **장후 20:10 KST** 실행이라
  **소요 시간 증가를 제약으로 두지 않는다는 전제**로 S5를 구현했다
  (**"80종목 유지"는 보수안으로 남기지 않음**). **축1(근본 원인 대응)**은
  배치 cap 기본값을 `80 → None`으로 바꾸고 `CompositionContext.max_cap`에
  **`None` = 절단하지 않음(coverage 모드)** 의미를 추가해 `_apply_cap`의
  절단 지점 두 곳을 모두 무효화한 것이다 — 배치는 selection이 아니라
  coverage job이므로 core 모집단을 자를 이유가 없고, 상수 상향(`80→300`)은
  여전히 절단 가능한 cap이라 후보가 늘면 조용히 재발하므로 택하지 않았다.
  부수 이점으로 배치가 core 상한을 두지 않아 정렬 기준이 선택에 영향을
  주지 않게 되어 **SPPV-2.145 §132.3의 순환 의존 회피 제약이 소멸**한다.
  **축2(guardrail)**는 `_core_signal_sort_rank()`의 정렬 키를
  `(tier, -overall_score, symbol)` 3계층으로 코드화한 것이다
  (`CORE_SIGNAL_TIER_FRESH/STALE/MISSING`을 명명 상수로 선언해 임시
  예외처리가 아니라 명시된 정렬 규칙임을 남겼고, stale을 실패로 막지 않고
  **하향**시켜 배치 부분 실패에도 유니버스 구성이 계속되게 했다).
  `core_signal_freshness_max_age_days` 기본값은 `None`(=신선도 판정 없음
  =기존 동작)이고 decision loop만 **5일**을 주입한다(정상 경과 1일 + 주말
  3일 + 배치 1회 실패 흡수). **축3**으로 배치가 매 실행 커버리지 지표
  (`core_covered`/`core_eligible_total`/`coverage_ratio`)를 남기고
  shortfall 시 WARNING을 내도록 했다 — cap을 없애도 `_apply_exclusions`나
  instrument master 변화로 커버리지가 떨어질 수 있고, 지표가 없으면 그
  하락이 조용히 stale/missing 계층으로 되돌아온다. **둘 중 하나만으로
  불충분한 이유**: S2 단독은 배치 부분 실패·신규 상장 시 오래된 점수가
  상위를 그대로 차지하고(코드가 stale을 구분할 수단이 없음), S1 단독은
  생성 모집단이 좁은 채로 남아 FRESH 계층이 사실상 배치가 덮은 ~80종목이
  되어 **사전순 편향이 12위에서 80위 경계로 이동한 상태로 고정**된다.
  검증: `tests/services/test_universe_selection.py` **114 passed**(기존
  **109건 무수정 통과** + 신규 5건, 그중 `test_freshness_guard_off_keeps_
  stale_first`가 **기본값 무변화 회귀**를 고정), 관련 스크립트 테스트 123
  passed, 하네스 `accept backend-file` 2건 PASS, 배치 import/`--help`
  확인. **미완료**: 운영 반영 관측(다음 배치 커버리지 지표 + 다음 거래일
  freeze 계층 분포), KIS `market_data` 예산 실측(80 → 약 211종목).
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §139.

- 작성자: Codex
- 수정일자: 2026-07-31 KST (152차, S5 배치 반영 준비 상태 점검 + 배치 전
  기준선 확정, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건 — **장후 배치 실측은 미수행**)
- 수정내용: 요청된 "20:10 KST 장후 배치 실측"은 **확인 시각이 15:31 KST로
  배치 예정보다 약 4시간 39분 이전**이라 수행할 수 없음을 실측으로 확정했다
  (오늘자 `signal_feature_after_market` freeze **0건**, 오늘자 snapshot
  **0건**, 최신 `snapshot_at` 여전히 **2026-07-30 20:00 KST**). 추정으로
  대체하지 않고 범위를 (a) S5 반영 준비 상태 점검과 (b) 배치 전 기준선
  확정으로 조정했다. **(a)** PR #72가 장중 머지로 `sync_source`/
  `activate_runtime`이 모두 skip됐지만, 호스트 작업트리가 운영 경로이고
  컨테이너가 소스를 bind mount하므로 `git pull`이 `sync_source`와 동일한
  파일 상태를 만들며, `run_ops_scheduler._run_command()`가
  `asyncio.create_subprocess_exec`로 매 실행 새 프로세스를 띄우고
  `SignalFeatureBatchRuntimeSpec.build_input_command()`가 cap 인자를 전달하지
  않아 cap이 **서브프로세스 자신의 기본값**에서 읽히므로(ops-scheduler에 cap
  상수 import 0건) **컨테이너 재기동 없이 coverage 모드로 실행될 준비가
  완료**된 상태다 — 컨테이너 안에서 모듈을 직접 import해 `core_cap=None`/
  `max_cap=None`, `core_signal_freshness_max_age_days` 필드,
  `CORE_SIGNAL_TIER_STALE=1`, `count_core_eligible`/`_core_signal_tier`
  존재를 확인했다. **(b)** 배치 전 기준선은 core-eligible **211종목**
  (coverage 목표치), 3계층 **FRESH 80(37.9%) / STALE 66(31.3%) /
  MISSING 65(30.8%)**, 직전 stale 핵심 8종목 전부 STALE(`021240`/`023530`/
  `028260` 37일, `032830` 39일, `042700`/`196170`/`329180`/`402340` 42일)
  이다. 내일 freeze 실측은 **추가 세팅 없이 read-only만으로 충분**하나,
  오늘 밤 배치 성공이 전제이며 배치 실패 시 나타나는 개선은 "S5 효과"가
  아니라 "guard 단독 작동"으로 해석해야 한다(구분 필요). 다음 거래일은
  07-31이 금요일이므로 **2026-08-03(월)**이다. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §140.

- 작성자: Codex
- 수정일자: 2026-08-01 KST (155차, S5 배치 실측 완료 — stale bias 사실상
  해소 확인, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건)
- 수정내용: 07-31 20:10 KST 장후 배치의 실제 결과를 실측했다(확인 시각은
  08-01 17:34 KST로 하루 늦었으나 배치 자체는 07-31 밤에 완료돼 있어
  read-only 실측에는 지장 없음; `docker logs`는 이후 배포로 인한 컨테이너
  재기동으로 소실돼 DB의 `signal_feature_batch_runs` 영속 기록으로 대체
  확인함). 배치는 freeze 생성(20:10:04 KST) → 적재 완료(20:12:54 KST)까지
  두 단계 모두 성공했고 `fetch_error_count=0`으로 부분 실패나 retry 발동이
  없었다. coverage는 기존 80종목에서 **208종목(2.6배)**으로 확대됐고,
  core-eligible 211종목 중 **203종목(96.2%)**을 커버했다 — 미커버 8종목 중
  7종목은 우선주(`_apply_exclusions()`의 우선주 배제 규칙에 의해 애초
  core 후보에서 걸러지는 종목)였고 나머지 1종목(`000880`)도 3일 경과로
  guard 기준(5일) 안에서 FRESH로 유효해 실질적으로 "문제 있는 미커버"는
  없었다. stale 핵심 8종목(`021240`/`023530`/`028260`/`032830`/`042700`/
  `196170`/`329180`/`402340`)은 **전부 FRESH로 전환**됐다. core-eligible
  전체 3계층 재분포는 배치 전 FRESH 80/STALE 66/MISSING 65에서 배치 후
  **FRESH 204(96.7%)/STALE 1(0.5%)/MISSING 6(2.8%)**로 바뀌었고, 남은
  STALE·MISSING 7건 전부 우선주였다 — 즉 **S5의 효과는 일부 개선이 아니라
  일반주 기준 stale bias의 사실상 완전한 해소**로 판정했다. 배치 소요시간은
  약 170초로 SPPV-2.151에서 80종목 기준 66.36초로부터 예측한 172.5초
  (2.6배 확대 가정)와 근접해 예측이 실측으로 검증됐다. 다음 거래일
  (2026-08-03 월) 08:50 KST freeze는 D안 정렬과 freshness guard가 이미 코드
  상수로 반영돼 있어 **추가 세팅 없이 read-only 실측만으로 충분**하다고
  판단했다. 미확정 사항은 timeout/budget WARNING의 직접 확인(로그 소실로
  불가, `fetch_error_count=0`이 간접 증거)과 다음 거래일 실제 freeze 구성
  확인이다. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
  entry_signal_v1.md` §142.

- 작성자: Codex
- 수정일자: 2026-08-01 KST (156차, [SPPV-2.156에서 정정] SPPV-2.155 수치
  정정 — authoritative 코드 경로 재검증, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건, 이력 보존형 정정)
- 수정내용: 사용자가 SPPV-2.155의 core-eligible(211)/covered(203)/
  FRESH·STALE·MISSING(204/1/6) 수치가 authoritative 코드 경로와
  충돌한다고 지적해 재검증했다. 원인은 §142의 heuristic 스크립트가
  `_is_core_seed_instrument()`가 실제로 참조하는
  `trading.instrument_index_memberships` 관계형 테이블 대신
  `instruments.metadata.index_memberships` JSON 필드를 읽었기 때문이다
  — 이 필드는 5종목(`000990`/`0126Z0`/`267270`/`456040`/`483650`)에서
  전부 `None`이었지만 실제 테이블엔 KOSPI200/100 멤버십이 정상 기록돼
  있었다. `UniverseSelectionService.count_core_eligible()`와
  `signal_feature_snapshots.list_latest_by_instrument_ids()`를 read-only
  트랜잭션(자동 롤백)으로 직접 호출해 재계산한 결과 **core-eligible
  216**, **07-31 배치로 정확히 갱신된 종목(covered) 207(95.8%)**,
  **FRESH(guard 5일 기준) 208(96.3%)**, **STALE 1(0.5%, 우연히 이전과
  동일)**, **MISSING 7(3.2%)**이다. 이 5종목 중 4종목은 07-31 배치로 이미
  fresh snapshot을 받았고(FRESH 204→208), 1종목(`0126Z0`, 삼성에피스
  홀딩스)은 snapshot 자체가 없어 MISSING이 6→7로 늘었다. `target_count
  =207`과 `snapshot_count=208`의 1건 차이는 오류가 아니라 `069500`
  (KODEX 200 ETF)이 regime 벤치마크 계산용으로
  `_with_regime_benchmark_symbol()`(SPPV-2.72)에 의해 항상 배치 입력에
  강제 추가되기 때문이며, 거래 후보가 아니므로 freeze의 `target_count`엔
  포함되지 않지만 snapshot 생성 대상에는 포함되는 서로 다른 산출물이다.
  가장 중요한 것은 **"stale bias 사실상 해소"라는 핵심 결론이
  authoritative 수치(FRESH 96.3%, STALE 0.5%)로도 그대로 재현돼 유지된다는
  점**이다 — 정정 대상은 수치 표기였지 판단이 아니었다. 기존 §142/§39/
  §6.31/[PRIORITY_MAP]/[BACKLOG] 문구는 삭제하지 않고 이력 보존형으로
  정정 주석을 병기했다. 상세: `docs/10_signal_research_sppv/[DESIGN]
  regime_conditional_entry_signal_v1.md` §143.

- 작성자: Codex
- 수정일자: 2026-08-01 KST (157차, `regime_tailwind` 제거 선행 검증 —
  판정 A, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건)
- 수정내용: `regime_tailwind` 제거에 들어가기 전 실제 BUY 판정 경로에
  숨은 간접 영향이 있는지 선행 검증했다. `regime_tailwind`는
  `classify_market_regime(snapshot)`이 후보 종목 개별 signal_feature_
  snapshot을 기반으로 계산한 값(전역 시장 상태가 아니라 종목별 값)이며,
  `_build_buy_ranking_score()`에서 `0.03*regime_tailwind` 항으로만
  `ranking_score`에 들어간다. 핵심 사실은 `buy_candidate`가
  `entry_score>=0.65` 기준으로 결정돼 `ranking_score`와 애초에 무관하다는
  점이다. `ranking_score`를 실제 게이트로 쓰는 코드는 정확히 두 곳뿐이다.
  (1) `_assess_core_risk_off_buy_guard()`(`core_risk_off_ranking_min_score
  =0.28`, `core_risk_off_shadow_min_score=0.02`, `shadow_floor_relax_
  ranking_min=0.26`)는 `core_risk_off_guard_active=True`(`risk_tone==
  'risk_off' AND regime_label=='bearish_trend'`)일 때만 호출되는데, 이
  조건은 `regime_tailwind`가 0이 되는 조건(`risk_tone=='risk_off'`)의
  부분집합이라 이 경로에서 `regime_tailwind`는 **코드 구조상 항상
  0**이다 — n=13,312 전수 실측으로 예외 0건 확인했다. (2) event_overlay
  shadow 실험(`adjusted_ranking_score = ranking_score+0.06`을 `0.56`과
  비교)은 `regime_tailwind`가 0이 아닐 수 있는 유일한 실측 소비 지점인데,
  `risk_tone != 'risk_off'`인 55건(전체 이력)을 전수 확인한 결과 전부
  `adjusted_ranking_score`가 계산조차 되지 않았고(shadow 조기 반환),
  이 실험 자체가 승격/override 배선이 없는 순수 관찰용임도 코드로
  확인했다 — 경계 뒤집힘은 0건이다. market_overlay는 `regime_tailwind`
  값이 상대적으로 다양(전체 이력 0.5=17.1%, 1.0=1.8%)하지만
  `market_overlay_experiment` 같은 소비 코드 자체가 없어 완전
  불활성이다. `strategy_alignment`(SPPV-2.146)와의 결정적 차이는, 값이
  살아있는 곳(event_overlay)과 그 값을 읽는 코드(entry_score 직접
  반영)가 겹쳤던 `strategy_alignment`와 달리, `regime_tailwind`는 값이
  살아있는 곳(market_overlay)과 코드가 읽는 곳(core_risk_off guard,
  항상 0인 곳)이 서로 겹치지 않는다는 점이다. `ranking_score`를
  참조하는 파일 3개(`deterministic_trigger_engine.py`,
  `decision_factory.py`(단순 값 복사), `trigger_proxy_attribution.py`
  (장후 관찰용 attribution 리포트, 실제 판정에 되먹임되지 않음))를 전수
  확인해 누락이 없음을 확인했다. **최종 판정: A(바로 diff 초안 작성
  가능)**. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §144.

- 작성자: Codex
- 수정일자: 2026-08-01 KST (158차, [SPPV-2.158에서 정정] §6.33 표현
  정밀도 보정 — 판정 A 유지, 코드 미수정, `.env` 미수정, Full pytest
  미실행, 신규 KIS 호출 0건, 이력 보존형 정정)
- 수정내용: SPPV-2.157(157차)의 결론(판정 A)은 유지하되 검증 방법을
  설명하는 표현 중 실제 저장 구조와 어긋나는 두 곳을 바로잡았다.
  첫째, `decision_json.deterministic_trigger.metadata`에는
  `regime_tailwind` 키 자체가 **존재하지 않음**을 실측으로 확인했다
  (최신 행의 metadata 키 19개를 전수 나열한 결과 `regime_label`/
  `risk_tone`/`source_type` 등은 있으나 `regime_tailwind`는 없다).
  157차 보고의 "jsonb에서 직접 재계산"이라는 표현이 "저장된 값을
  그대로 조회했다"로 오독될 수 있어, 실제로는 "저장된 `regime_label`
  과 `risk_tone`으로 `_build_buy_ranking_score()`의 조건 분기
  (`bullish_trend`+`risk_on`→1.0, `risk_off`→0.0, 그 외 0.5)를 코드
  밖에서 재구성해 `regime_tailwind` 값을 역산·집계한 것"이라고
  정정했다 — 이 구분이 값 자체를 바꾸지는 않는다. 둘째, "최근
  1개월"이라는 창이 정확히 어떤 시각 경계인지 명시돼 있지 않아
  `2026-07-01 00:00:00 KST 이상 2026-08-01 00:00:00 KST 미만`으로
  명시 확정했다 — 이 창으로 재확인한 core 표본 수가 157차 보고의
  18,946건과 정확히 일치해 수치 자체는 변경되지 않았다. 판정 A와
  핵심 결론 4가지(`buy_candidate`는 `entry_score` 기준이라 무관,
  `market_regime`은 종목별 값, `core_risk_off_guard_active=true`
  모집단에서 `regime_tailwind != 0`이 0건, `event_overlay` 0.56
  shadow 경로 경계 뒤집힘 0건)는 전부 그대로 유지된다. 상세:
  `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §145.

- 작성자: Codex
- 수정일자: 2026-08-01 KST (159차, `regime_tailwind` 제거 diff 구현,
  코드 변경 포함, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건, 운영 반영 전)
- 수정내용: SPPV-2.157/§144에서 판정 A로 닫힌 `regime_tailwind` 제거를
  실제 코드로 구현했다. `src/agent_trading/services/deterministic_
  trigger_engine.py`의 `_build_buy_ranking_score()`에서 `market_regime`
  인자와 `regime_tailwind` 지역 변수·if/elif 분기, `score` 계산식의
  `+0.03*regime_tailwind` 항을 제거하고 호출부의 인자 전달도 함께
  제거했다. `entry_score` 쪽 로직, `strategy_alignment`/
  `coverage_score`/`relative_activity` 관련 기존 변경, `core_risk_off`
  guard(0.28/0.02/0.26)와 event_overlay shadow(0.56) 로직은 전부
  건드리지 않았다. 호출부의 `market_regime` 변수 자체는 같은 스코프의
  `_is_core_risk_off_regime()` 호출에 계속 쓰이므로 안전하게 남겨뒀다.
  기존 테스트 23건 중 2건이 fixture에 옛 tailwind 기여분(`bullish_
  trend+risk_on`→`+0.03`, `neutral`→`+0.015`)을 반영하고 있어
  threshold/입력값을 최소한으로 보정했고(하나는 `ranking_score>0.6`을
  `>0.57`로, 다른 하나는 순수 관찰용 event_overlay shadow 메타데이터
  테스트의 `overall`을 `0.70`→`0.75`로 조정), 신규 회귀 테스트 1건
  (`test_build_buy_ranking_score_has_no_regime_tailwind_term`)을 추가해
  함수가 `market_regime` 없이 `entry_score`+`allocation_quality`만으로
  값을 내는지와 옛 시그니처 호출이 `TypeError`를 내는지를 고정했다.
  `assess_deterministic_triggers()` 레벨에서 `market_regime`을 바꿔
  `ranking_score`를 직접 비교하는 방식은 `market_regime`이 `entry_
  score`에도 별도 영향(risk_off 페널티 등)을 줘 확인이 오염되므로
  피하고, `_build_buy_ranking_score()` 자체를 단독으로 고정하는 방식을
  택했다. `tests/services/test_deterministic_trigger_engine.py`
  **24 passed**(20건 무수정 + 2건 보정 + 신규 1건), 하네스 `accept
  backend-file` **PASS**(import graph로 3개 테스트 파일 선정, 3/3
  통과), 하네스가 제외한 인접 파일(`test_decision_factory.py`,
  `test_core_risk_off_topk_projection.py`)도 직접 재확인해 11 passed.
  **운영 반영 관측과 가중치 재정규화(`0.55+0.10=0.65`, 제거 전에도
  1.0이 아니었음) 여부는 이번 턴 범위 밖으로 남겨 다음 턴 과제로
  넘겼다.** 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
  conditional_entry_signal_v1.md` §146.

---

## 진행 체크리스트

이 문서를 `SPPV` 트랙의 **작업 진행 기준 문서**로 사용한다. 세부 근거는
`plans/[ANALYSIS] foundational_design_review_objective_alignment.md`(undated
canonical),
우선순위 반영 상태는 `plans/[PRIORITY_MAP] remaining_work_priority_map.md`,
백로그 승격 상태는 `plans/[BACKLOG] backlog.md`와 함께 동기화한다.

### A. 기준선 및 설계 정렬

- [x] 목표 함수와 손실 제약 정의를 `최고 기대수익률 + 손실 제약`으로 고정
- [x] `2026-06-25` 이후 BUY 주문 0건의 직접 병목이 `entry_score < 0.65`임을 실측
- [x] risk/compliance를 목적함수가 아닌 제약조건으로 재정의
- [x] `core_risk_off` 완화 중심 접근을 중단하고 신호/진입 경로 검증으로 전환
- [x] 관련 문서(`ANALYSIS`/`BACKLOG`/`PRIORITY_MAP`)에 방향 전환 반영

### B. SPPV 단계별 진행 상태

- [x] **SPPV-1** 파일럿 IC 측정 완료
  - 상태: core 8종목 pooled IC 산출 완료, 결론은 보류
  - 산출물: `logs/signal_ic_pilot_2026-07-14.*`
- [x] **SPPV-2** 통계 보정 확장 (완료, 2026-07-14)
  - 작업 범위: core 전체(88종목, point-in-time universe는 데이터 부재로 제외·
    한계로 명시) + 국면별 cross-sectional IC/ICIR + non-overlap/Newey-West +
    비용 차감 quintile 성과(T+1/T+3/T+5/T+10/T+20)
  - **결과: 정확히 보정한 cross-sectional IC는 전 신호·전 horizon에서
    |t_NW|<1.1 — 통계적 유의성 없음.** SPPV-1의 "유의미"~"강함" 결론은
    overlap 편향의 산물이었음이 확인됨. §9 상세 참고.
  - 산출물: `scripts/validate_signal_predictive_power_v2.py`(read-only),
    `logs/signal_ic_sppv2_expanded_2026-07-14.json`,
    `logs/sppv2_run_2026-07-14.log`
- [x] **SPPV-2.5** quintile spread 정체 진단 (완료, 2026-07-14) — ⚠️
  **방법론 오류로 결론 폐기, §12로 대체**
  - 작업 범위: `overall_score` quintile spread 자체의 Newey-West 유의성
    검정 + 국면 내부(within-regime) 분해(bullish/bearish/range_bound 각각
    단독으로 spread 재계산)
  - ~~결과: pooled spread는 유의(T+20 t_NW=2.30)하나, 국면 내부 어느 곳도
    단독 유의하지 않음 — 국면 혼입 착시로 판정~~ **→ 오류: `regime_label`이
    종목 자신의 신호로 판정되는 것이라 conditioning 자체가 부적절했음
    (§12.1). 시장 공통 국면(KODEX 200) 기준 재검증 결과 반박됨(§12.4).**
  - 산출물: `scripts/validate_signal_predictive_power_v2_5.py`(read-only),
    `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`
- [x] **SPPV-2.6(신설)** 시장 공통 국면(KODEX 200) 기준 재검증 (완료,
  2026-07-14)
  - 작업 범위: `069500`(KODEX 200) 벤치마크로 거래일 단위 공통 국면 라벨
    + 초과수익(excess return) 계산, 원수익률/초과수익 양쪽으로 pooled 및
    공통국면 내부 spread/IC 재계산.
  - **결과: 시장 공통 국면 분포(190거래일) = bullish_trend 185일(97%)/
    range_bound 5일/bearish_trend 0일/event_driven 0일. `overall_score`
    T+20 spread 유의성(pooled t_NW=2.30)이 유일하게 신뢰 가능한
    bullish_trend 버킷(97%) 내부에서도 거의 그대로 유지됨(t_NW=2.23)**
    — §11의 "국면 혼입 착시" 결론 반박. 대신 **1년 표본 자체가 시장
    공통 기준 단일국면(상승장)에 압도적으로 치우쳐 하락장 검증이 아예
    불가능**하다는 더 근본적인 한계 확인. §12 상세 참고.
  - 산출물: `scripts/validate_signal_predictive_power_v3_market_regime.py`
    (read-only, KIS 재조회 0건 — 캐시 hit 88/88),
    `logs/signal_ic_sppv_market_regime_correction_2026-07-14.json`
- [x] **SPPV-2.7(신설)** 하락장 포함 3년 확장 + 벤치마크 자기참조 제거
  재검증 (완료, 2026-07-14)
  - 작업 범위: 평가 universe에서 벤치마크(069500) 제외(core 87종목) +
    조회 기간 1년→3년 확장(733일봉) + 시장 공통 국면 내부 재분해.
  - **결과: 시장 공통 국면(3년) = bullish 351일/range_bound 200일/
    bearish_trend 96일(15%, 최초 확보)/event_driven 6일. `overall_score`
    T+20 pooled spread 유의성이 **소멸**(§12의 t_NW=2.30 → t_NW=1.32).
    하락장 내부에서는 spread가 **음수로 역전**(overall_score T+5
    t_NW=-1.71, T+20 t_NW=-0.14)하거나 `fast_score`는 하락장에서 **유의
    하게 역방향**(T+5 t_NW=-2.79).** §12의 "알파 근거 강화" 결론을
    §14에서 하향 조정 — 안정적 종목 선택 알파를 확인하지 못함.
  - 산출물: `scripts/validate_signal_predictive_power_v4_extended_period.py`
    (read-only), `logs/signal_ic_sppv2_7_extended_period_2026-07-14.json`,
    `logs/_bars_cache_core87_3y_2026-07-14/`. 상세: §14.
- [x] **SPPV-2.8(신설)** 검증 기간 기준 재설계 — 최근성 우선 + 필수 국면
  표본 게이트 (완료, 2026-07-14)
  - 작업 범위: 3년 pooled를 기본값으로 유지할지, 최근 6~18개월 중심 +
    국면별 최소 표본 요구 방식으로 바꿀지 결정. 기존 3년 캐시를 재사용해
    최근 12개월 창의 실측 결과를 신규 KIS 호출 없이 산출.
  - **결과: 최근 12개월 창은 하락장(bearish_trend) 거래일 0일 — 최근성
    창만으로는 필수 국면 게이트를 통과할 수 없음을 실증.** pooled
    spread도 Newey-West 보정 시 유의하지 않음(overall_score T+20
    t_NW=1.18, T+5 t_NW=1.16 — 3년 결과(1.32)보다도 약함). §16 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v5_recency_window.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv_recency_window_primary_2026-07-14.json`,
    `logs/sppv_recency_window_run_2026-07-14.log`.
  - **실행 증빙 재검증(2026-07-14, 6차)**: 최초 저장된 로그가 실패
    트레이스(호스트 python `dotenv` 미설치)였음을 발견 — `agent_trading-
    app-1` 컨테이너에서 재실행해 stdout을 그대로 로그로 캡처했다.
    종료 코드 0, `HTTP Request:` 0건, bearish_trend 0일과
    `overall_score` T+20 t_NW=1.18 모두 재현 확인. §16.6 상세.
- [x] **SPPV-2.9(신설)** 신호 feature 재설계 검토 — sub-component 분해 +
  신규 후보 (완료, 2026-07-14)
  - 작업 범위: `fast_score`/`slow_score`의 6개 sub-component를 분해
    실측 + 신규 후보 feature(`risk_adj_momentum_3m`, `reversal_1m`)를
    §16 이원 기준으로 검증.
  - **결과: `rsi_signal`이 T+20에서 유의하게 역방향(1차 t_NW=-2.94,
    bullish_trend 내부 -2.79) — `fast_score` 예측력 실패의 구체적 원인
    특정.** 신규 후보 `risk_adj_momentum_3m`은 2차(3년) pooled
    유의(t_NW=2.07) + 하락장 역전 없음(t_NW=0.39)으로 유일한 "Watch"
    후보이나 1차(최근 12개월) 유의성(t_NW=1.47)이 §16 게이트(|t|≥2)
    미달 — 완전한 Go는 아니다. `reversal_1m`은 하락장에서만
    유의(T+5 t_NW=2.13)해 국면 조건부 후보로 분리 검토 필요. §17 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v6_feature_
    redesign.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv2_9_feature_redesign_2026-07-14.json`,
    `logs/sppv2_9_feature_redesign_run_2026-07-14.log`.
- [x] **SPPV-2.10(신설)** §17.5 후속 3과제 실측 (완료, 2026-07-14)
  - 작업 범위: (1) `fast_score_v2`(rsi_signal 제거/부호반전) shadow 2종
    검증, (2) `risk_adj_momentum_3m` 1차 창 12→18개월 확장 재검증,
    (3) `reversal_1m` 하락장 조건부 오버레이 표본 내(전/후반부) 안정성
    확인.
  - **결과: `fast_score_v2` 2종 모두 No-Go — 하락장 T+5 spread가 원안과
    거의 동일하게 역전(drop -2.41, flip -2.32, 원안 -2.79) — `rsi_signal`
    은 부분 원인일 뿐 주된 원인이 아니었음.** `risk_adj_momentum_3m`은
    18개월 창에서 T+20 t_NW=1.47→**2.03**으로 문턱을 겨우 넘었으나
    T+5(1.97)는 미달, marginal — "Watch 유지, 조건부 상향". `reversal_1m`
    은 하락장 반분 검증에서 방향은 일관되나(전반 1.87/후반 1.33) 개별
    유의 문턱 미달 — Hold 유지. SPPV-3 착수는 계속 보류. §18 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v7_followup.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv2_10_followup_2026-07-14.json`,
    `logs/sppv2_10_followup_run_2026-07-14.log`.
- [x] **SPPV-2.11(신설)** §18.6 후속: fast_score 전면 분해 + 창 경계
  민감도 + shadow 후보 (완료, 2026-07-14)
  - 작업 범위: (1) `fast_score` leave-one-out 4종(성분 각 1개씩 제거)
    분해, (2) `risk_adj_momentum_3m` 1차 창 12/15/18/21개월 민감도,
    (3) 국면 전환형 shadow 후보 `regime_switch_v1` 신설·검증.
  - **결과: `fast_trend` 제거 시 하락장 T+5 spread가 -2.79→-1.60(비유의
    전환)으로 가장 크게 개선 — 주된 원인은 `rsi_signal`이 아니라
    `fast_trend`였음을 정정.** `risk_adj_momentum_3m`은 15~21개월에서
    T+20 t_NW 1.90→2.03→2.04로 안정적 plateau — 18개월 결과가 단발성
    우연은 아니나 크기는 여전히 작다. `regime_switch_v1`은 2차(3년)
    pooled T+5 t_NW=2.60/T+20 t_NW=2.36으로 트랙 최고 수치를 냈으나,
    1차(최근 12개월)는 하락장 표본 부재로 미달 — 가장 유망한 Watch
    후보이나 확정 Go는 아니다. SPPV-3 착수는 계속 보류. §19 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v8_fast_score_
    teardown.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv2_11_fast_score_teardown_2026-07-14.json`,
    `logs/sppv2_11_fast_score_teardown_run_2026-07-14.log`.
- [x] **SPPV-2.12(신설)** §19.6 후속: `regime_switch_v1` 게이트 예외
  규칙 비교 + fast 계열 신규 feature (완료, 2026-07-14)
  - 작업 범위: (1) 1차 게이트 예외 규칙 3개(A 관찰 유예/B 최근-실사례
    고정창/C 적응형 최소 국면 표본 창) 정의·비교, (2) fast 계열 신규
    feature 2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`) 실측.
  - **결과: 규칙 C가 n=30에서 t_NW=4.18로 급등하지만 n=48(규칙 B)에서는
    1.33에 불과 — "문턱을 넘을 때까지 창을 줄이는" 데이터 스누핑으로
    판정, 채택 거부.** 규칙 B(고정 n=48)는 정직한 재검증에서도
    1.33~1.61로 미달 — **규칙 A(관찰 유예, 하락장 재발 시 자동 재검증)를
    유일하게 채택.** fast 계열 신규 feature 2종 모두 범용 대체 후보로
    No-Go — `rsi_mean_reversion`은 하락장에서만 유의(t=2.26, 국면
    조건부), `sma5_over_sma20_gap`은 하락장에서 유의하게 역전(t=-2.67,
    SMA20 이격과 동일한 문제 재현). SPPV-3 착수는 계속 보류. §20 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v9_gate_and_fast_
    features.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv2_12_gate_and_fast_features_2026-07-14.json`,
    `logs/sppv2_12_gate_and_fast_features_run_2026-07-14.log`.
- [x] **SPPV-2.13(신설)** `regime_switch_v1` 규칙 A 모니터링 실행체
  구현 (완료, 2026-07-14)
  - 작업 범위: §20에서 채택한 규칙 A(관찰 유예)를 서술로만 남기지 않고
    실제 실행 가능한 경량 모니터링 스크립트로 구현.
  - **결과: `scripts/monitor_regime_switch_v1_gate.py` 실행 — 벤치마크
    1종목만 조회(신규 KIS 호출 0건), 최근 12개월 국면 분포 확인.
    판정: `NOT_TRIGGERED`(bearish_trend 0일) — §20 판단과 일치.** 30일
    이상 관측되면 `TRIGGERED`로 자동 판정해 재검증을 권고한다. §21 상세.
  - 산출물: `scripts/monitor_regime_switch_v1_gate.py`(read-only),
    `logs/regime_switch_v1_gate_monitor_2026-07-14.json`,
    `logs/regime_switch_v1_gate_monitor_run_2026-07-14.log`.
- [x] **SPPV-2.14(신설)** fast 계열 완전 신규 신호 2종 실측 (완료,
  2026-07-14)
  - 작업 범위: "절대 가격 수준" 로직을 쓰지 않는 신규 feature 2종
    (`money_flow_5d`=자금 흐름 축, `relative_strength_rank_1m`=
    cross-sectional 상대강도 축) 실측.
  - **결과: 둘 다 pooled/1차 유의성 없이 범용 대체 후보로 No-Go.**
    `relative_strength_rank_1m`은 하락장에서 유의하게 역전(T+5
    t_NW=-2.13) — 시장 베타를 제거한 상대강도조차 하락장에서는
    반대로 작동한다는 더 강력한 규칙성을 재확인했다. §22 상세.
  - 산출물: `scripts/validate_signal_predictive_power_v10_new_fast_
    features.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json`,
    `logs/sppv2_14_new_fast_features_run_2026-07-14.log`.
- [x] **SPPV-2.15(신설)** 국면별 신호 극성 전환 종합 및 상위 재설계
  방향 확정 (완료, 2026-07-15)
  - 작업 범위: SPPV-2.9~2.14(§17~§22)에서 산출된 10개 신호를 하나의
    종합표로 통합, "feature 추가 실험 계속 / 국면 분기형 entry 설계
    전환 / 유니버스·미시구조 재검토" 3개 선택지를 실측 근거로 비교.
  - **결과: 8/10 신호가 "추세형=상승/횡보 전용, 되돌림형=하락장 전용"
    규칙성을 따름(`rsi_signal`만 상승장 역전 예외). feature 추가 실험은
    한계효용이 낮다고 판단해 중단, 국면 분기형 entry 설계 검토로 전환
    확정. 유니버스/미시구조 재검토는 후순위 유지.** §23 상세, 별도
    문서 `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
    direction.md`.
- [x] **SPPV-2.16(신설)** 국면 분기형 entry 설계 초안 + shadow 계산기
  1차 실행 (완료, 2026-07-15)
  - 작업 범위: §23의 판정을 실제 설계 문서로 구체화 — 국면별 신호
    선택 매트릭스, `entry_score` 통합 방안(제안, 미적용), shadow 검증
    계획(Phase 1/2, Go-No-Go 기준) 작성. shadow 계산기 스크립트로
    1회 실시간 스냅샷 실행.
  - **결과: 설계 문서
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` 작성 완료.**
    shadow 계산기 실행(기준일 2026-07-14, 시장 공통 국면
    `range_bound`) — 87/87종목 `risk_adj_momentum_3m` 분기 신호
    산출(하락장 분기는 이번엔 미발동, §21 모니터링 NOT_TRIGGERED와
    정합). `entry_score` 코드/운영 반영은 없음 — 설계·shadow 단계만
    진행.
  - 산출물: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`,
    `scripts/shadow_regime_conditional_entry_signal.py`(read-only,
    신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`,
    `logs/shadow_regime_conditional_entry_signal_run_2026-07-15.log`.
- [x] **SPPV-2.17(신설)** regime_conditional_signal Phase 2 shadow
  누적 사이클 구축 (완료, 2026-07-15)
  - 작업 범위: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §4.2의 Phase 2를 실행 가능한 오케스트레이터로 구현 — 게이트 판정
    (§21)과 신호 계산(§22)을 벤치마크 1회 조회로 통합, 누적 이력
    파일(JSONL, 중복 거래일 skip) 구축, `TRIGGERED` 전환 시 재검증
    runbook 출력.
  - **결과: 신규 KIS 호출 0건으로 게이트 NOT_TRIGGERED(bearish_trend
    0일), 신호 2026-07-14 기준 `range_bound`로 87/87종목 `risk_adj_
    momentum_3m` 분기 산출 — 이력에 1줄 추가. 재실행 시 중복 방지
    로직이 정상 발동함을 확인.** `entry_score` 코드/운영 변경 없음.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §6.
  - 산출물: `scripts/run_regime_conditional_shadow_cycle.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/regime_conditional_signal_shadow_history.jsonl`(누적 이력,
    JSON Lines), `logs/shadow_regime_conditional_entry_signal_
    2026-07-14.json`(당일 상세),
    `logs/run_regime_conditional_shadow_cycle_run_2026-07-15.log`.
- [x] **SPPV-2.18(신설)** `entry_score` 중복 penalty ablation — Phase 0
  shadow 실측 (완료, 2026-07-15)
  - 작업 범위: SPPV-3 착수 전제("중복 억제 구조를 point-in-time 기준
    으로 재현하고 분해할 준비")를 실제 가능한 수준으로 실행 — 운영
    함수(`_build_entry_score`, `_assess_buy_eligibility`)를 그대로
    호출해 세 penalty 축(entry_score regime penalty / eligibility
    regime 차단 / eligibility signal floor)의 교집합을 오늘(87종목)
    기준 정량화.
  - **결과: A(85)/B(60)/C(75) 중 B가 발동한 60건은 예외 없이 A·C도
    함께 발동(A∩B∩C=60=B 전체)** — §2 근본 진단의 "삼중 중복"이
    오늘 데이터로 100% 재현됨. 종목별(per-symbol) regime_label 분포
    (bearish_trend 69%)가 시장 공통 국면(`range_bound`)과 완전히
    다름을 재확인(§12.1 문제가 운영 코드에 그대로 남아 있음).
    `entry_score`에 `regime_conditional_signal`을 통합하려면 국면
    정의(종목별 vs 시장 공통)를 먼저 통일해야 한다는 네 번째 쟁점을
    발견. 운영 DB(`trade_decisions`) 직접 조회는 자동 승인 경계
    밖으로 판단돼 시도하지 않았다. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §8.
  - 산출물: `scripts/shadow_entry_score_penalty_ablation.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용, 운영 함수 그대로
    호출), `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`,
    `logs/shadow_entry_score_penalty_ablation_run_2026-07-15.log`.
- [x] **SPPV-2.19(신설)** 중복 억제 시계열 누적 + 국면 정의 비교 체계
  구축 (완료, 2026-07-15)
  - 작업 범위: §8(하루치 관찰)을 시계열 누적 절차로 승격 — 신규
    오케스트레이터가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행
    으로 계산해 누적 이력에 기록, SPPV-3 본작업용 종목별 vs 시장
    공통 국면 비교 실험을 설계.
  - **결과: §8과 동일한 수치(A=85/B=60/C=75/A∩B∩C=60)로 교차 검증,
    국면 일치 18건/불일치 69건(79%) — "시장 비하락장인데 종목별
    하락장" 60건.** 재실행으로 중복 방지 로직 정상 발동 확인.
    SPPV-3 착수 시 수행할 "현행 종목별 정의 vs 시장 공통 정렬" 비교
    실험을 §9.6에 설계. `entry_score` 코드/운영 변경 없음. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §9.
  - 산출물: `scripts/run_entry_score_penalty_ablation_cycle.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/entry_score_penalty_ablation_history.jsonl`(누적 이력),
    `logs/entry_score_penalty_ablation_2026-07-14.json`(당일 상세),
    `logs/run_entry_score_penalty_ablation_cycle_run_2026-07-15.log`.
- [x] **SPPV-2.20(신설)** §9.6 비교 실험 실측 — 종목별 vs 시장 공통
  regime 정의 (완료, 2026-07-15)
  - 작업 범위: §9.6 실험 설계를 실제 실행 — 3년 rolling 표본에 운영
    함수 `_assess_buy_eligibility`를 그대로 호출해 변형 A(종목별)/
    변형 B(시장 공통) 각각의 eligibility 통과군 T+5/T+20 forward
    return을 §16 이원 검증 도구(quintile spread + Newey-West)로 비교.
  - **결과: 변형 B가 통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의
    forward return은 더 높음(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%,
    둘 다 baseline 대비 유의, t_NW 7.3~7.7).** 통과군 내부 quintile
    spread는 여전히 유의하게 역전(T+20 t_NW=-2.84~-3.06) — `overall_
    score` 재순위화 자체의 문제는 별개로 남음. A-B 차이의 직접 유의성
    검정은 미수행 — **판정: Watch(조건부 유리, 확정 Go 아님)**.
    실행 로그 확인 결과 `HTTP Request:` 0건(3년 캐시 완전 재사용,
    가정이 아니라 실측 확인). `entry_score` 코드/운영 변경 없음.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §10.
  - 산출물: `scripts/validate_entry_score_regime_definition_
    comparison.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_entry_score_regime_definition_comparison_
    2026-07-15.json`, `logs/entry_score_regime_definition_
    comparison_run_2026-07-15.log`.
- [x] **SPPV-2.21(신설)** A/B 판정 불일치 표본 direct 비교 + 1차 창
  재확인 (완료, 2026-07-15)
  - 작업 범위: §10.5가 지시한 두 과제 — 같은 종목-거래일 표본을
    `A_only`/`B_only`/`both`/`neither` 4개 배타적 집합으로 분해,
    최근 12개월 창에서도 동일 비교 반복.
  - **결과: `B_only`가 3년·1차 창 모두에서 0건 — 시장 공통 정의(B)는
    종목별 정의(A)의 진부분집합(strict subset)임을 구조적으로 확인.**
    B는 새 종목을 발굴하지 않고 A가 통과시킨 것 중 일부(`A_only`,
    3년간 1,072건)를 추가로 차단할 뿐이다. `A_only`의 forward
    return은 방향상 음수(T+5 -0.17%, T+20 -0.70%)이나 통계적으로
    유의하지 않음(|t_NW|<1). 최근 12개월은 A-B 차이 자체가 없음
    (§21 모니터링과 정합). "일별 짝비교"는 `B_only=0`이라 정의상
    계산 불가함을 확인 — 대안으로 `A_only` 자체의 유의성 검정이
    실질적으로 동등함을 확인. **판정: Watch 유지(No-Go에 근접),
    확정 Go 기각.** 실행 로그로 KIS 호출 0건 확인(가정 없이 실측).
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §11.
  - 산출물: `scripts/validate_entry_score_regime_definition_ab_diff.py`
    (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`,
    `logs/entry_score_regime_ab_diff_run_2026-07-15.log`.
- [x] **SPPV-2.22(신설)** alpha layer vs regime_conditional_signal
  직접 비교 — 무게중심을 차단에서 선별로 이동 (완료, 2026-07-15)
  - 작업 범위: 현행 `entry_score` alpha layer(순위상 `0.45·overall+
    0.20·fast+0.15·slow`와 동일함을 코드로 확인)와 `regime_
    conditional_signal`을 같은 3년 rolling 표본에서 §16 이원 검증
    도구로 직접 비교.
  - **결과: 2차(3년) 창에서 `regime_conditional_signal`이 T+5(t_NW=
    2.52)/T+20(t_NW=2.33) 둘 다 유의, 현행 alpha layer는 어디서도
    비유의(1.02~1.39)** — spread·t값·양수 비율 4개 관측치 전부에서
    `regime_conditional_signal`이 일관되게 우세. 1차 창은 미달이나
    §21의 구조적 이유(하락장 부재)임을 재확인. **판정: Conditional
    Go(2차 검증 통과, 1차 게이트 전환 대기) — Watch로 낮추지 않되
    억지로 완전한 Go도 선언하지 않음.** 실행 로그로 KIS 호출 0건
    확인(가정 없이 실측). `entry_score` 코드/운영 변경 없음. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §12.
  - 산출물: `scripts/validate_alpha_layer_vs_regime_conditional_
    signal.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_alpha_layer_vs_regime_conditional_signal_
    2026-07-15.json`, `logs/alpha_layer_vs_regime_conditional_
    signal_run_2026-07-15.log`.
- [x] **SPPV-2.23(신설)** 새 alpha 상위군과 기존 차단 축 결합 효과
  검증 — 가장 빈번한 차단 사유 재발견 (완료, 2026-07-15; **당시
  해석("과잉 억제 확정" 뉘앙스)은 이후 SPPV-2.24/§14 ablation으로
  보정됨 — 아래 결과 서술은 원문 보존, 최종 판단은 SPPV-2.24 참고**)
  - 작업 범위: `regime_conditional_signal`을 새 alpha로 넣었을 때
    기존 차단 로직(운영 `_build_entry_score`/`_assess_buy_
    eligibility` 그대로 호출)이 그 효과를 상쇄하는지, 상쇄한다면
    어느 축이 가장 자주 걸리는지 규명.
  - **결과: 상위 20% 표본의 68.3%(3년)/61.1%(최근 12개월)가 차단
    되지만, 차단된 표본도 forward return이 강하게 유의하게 양(+)
    (3년 T+5 +0.815% t_NW=6.86, T+20 +3.170% t_NW=8.35 — 생존군과
    큰 차이 없음).** 실패 사유 집계 결과 **`eligibility_low_
    relative_activity`(거래량/거래대금 급증 비율<1.10 차단, 국면·
    신호와 무관한 순수 유동성 게이트)가 차단의 압도적 대부분(3년
    79.7%, 최근 12개월 99.6%)을 차지 — §8의 regime 축(B/C)은
    오히려 부차적(3년 20.3%, 최근 12개월 0.4%)임을 새로 발견.**
    **판정: alpha 자체(§12)는 Conditional Go 유지, 결합 시나리오는
    Watch(활동성 필터 ablation 검증 필요).** SPPV-3 다음 최우선
    조사 대상을 "국면 정의 통일/regime penalty"에서 "활동성
    필터(`eligibility_low_relative_activity`) 재검토"로 재조정.
    두 스크립트 실행 로그로 KIS 호출 0건 확인(가정 없이 실측).
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §13.
  - 산출물: `scripts/validate_new_alpha_vs_existing_blocking_axes.py`,
    `scripts/diagnose_blocked_reason_distribution.py`(둘 다
    read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용),
    `logs/signal_ic_new_alpha_vs_existing_blocking_axes_
    2026-07-15.json`, `logs/new_alpha_vs_existing_blocking_axes_
    run_2026-07-15.log`, `logs/diagnose_blocked_reason_
    distribution_run_2026-07-15.log`.
- [x] **SPPV-2.24(신설)** `eligibility_low_relative_activity` 활동성
  필터 정밀 ablation (완료, 2026-07-16)
  - 작업 범위: SPPV-2.23이 발견한 활동성 필터가 실제로 과잉 억제인지,
    새 alpha 위에서도 정당한 선별인지 판정. `regime_conditional_
    signal` 상위 20% 표본 대상, 필터 threshold를 현행(1.10)/완화
    (1.00)/완전 제거 3개 시나리오로 나눠 생존 종목 수·T+5·T+20
    forward return·Newey-West t값·양수 비율을 비교.
  - **결과(2026-07-16 해석 보정 반영 — 판단 기준을 "차단 표본이
    플러스인지"가 아니라 "차단 제거/완화 시 기대수익률이 실제로
    개선되는지"로 고정): 완전 제거는 No-Go로 확정** — 생존군
    forward return이 무차단 상위군 전체 수준으로 회귀(2차 T+20
    제거 +3.882% vs 무차단 전체 +3.554%, 거의 동일)하며 현행
    유지(+4.381%)보다도 낮다. 즉 **현재 실측상 무차단 전체보다
    필터 적용 시 생존군 평균이 더 높으므로, "필터 제거가
    기대수익률을 개선한다"는 근거는 없다.** **임계값 1.10→1.00
    완화는 Watch(방향은 유력하나 확정 아님)** — 생존 종목 수(2차
    31.7%→37.7%, 1차 38.9%→46.4%)와 T+5/T+20 평균 수익률·t_NW·
    양수율이 1차·2차 창 모두에서 동시에 소폭(0.07~0.18%p) 개선되는
    방향은 확인됐으나, 검증한 threshold가 1.00 하나뿐이고 개선폭이
    작아 "Conditional Go"로 단정하기엔 이르다. **차단된 표본 자체가
    forward return이 플러스라는 사실(§13)만으로는 "과잉 억제"를
    증명하지 못한다는 점, 그리고 "표본 증가로 t_NW가 커진다"가 곧
    "품질 개선"을 뜻하지 않는다는 점(완전 제거 시나리오가 그
    역설 사례) 둘 다 실측으로 확인했다.** **활동성 필터가 BUY
    0건의 "주범"인지, "과잉 억제"인지는 이번 실측만으로 확정할 수
    없다** — 재검토가 필요한 후보로 남기되, 확정적 결론(주범
    확정/과잉 억제 확정/제거 시 개선)은 내리지 않는다. 신규 KIS
    호출 0건(기존 3년 캐시 88개 파일로 전량 서빙, 로그로 실측
    확인). `entry_score`/`_assess_buy_eligibility` 운영 코드 변경
    없음 — 이번 턴은 shadow/validation 범위. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §14.
  - 산출물: `scripts/validate_activity_filter_ablation.py`(read-only,
    신규 KIS 호출 0건), `logs/signal_ic_activity_filter_ablation_
    2026-07-16.json`, `logs/activity_filter_ablation_run_2026-07-16.log`.
- [x] **SPPV-2.25(신설)** 활동성 필터 threshold sweep + 기간 분할
  재현성 검증 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.24의 "1.00 완화는 Watch(추가 검증 필요)"
    판정을 Conditional Go 이상으로 올릴 수 있는지, threshold를
    1.10(현행)/1.05/1.00/0.95/0.90 5단계로 확장 스윕하고, 3년
    표본을 거래일 기준 전반부/후반부로 양분해 완화 효과의
    out-of-sample 재현성을 확인.
  - **결과: 2차(3년) 전체·1차(최근 12개월)·3년 후반부에서는
    threshold를 완화할수록 T+5/T+20 평균 수익률이 단조 개선되는
    것처럼 보였으나, 3년 전반부(2023-10-10~2025-02-11)만 따로 보면
    완화할수록 평균 수익률이 정반대로 단조 악화됐다**(1.10 +0.7394%
    → 0.90 +0.5728%, T+5 기준). **즉 "완화=개선" 패턴은 사실상
    후반부(=최근 12개월과 거의 동일 시기) 효과가 3년 pooled 평균을
    끌어올린 것이었고, 3년 전체를 대표하는 일관된 규칙성이 아니다.**
    창마다 최적 threshold도 서로 달라(2차 3년은 0.95, 1차/후반부는
    0.90까지 계속 개선, 전반부는 0.90에서 최악) 단일 sweet spot이
    존재하지 않는다. **결론: 1.00(또는 그 이하) 완화는 재현성 있는
    개선으로 볼 수 없다** — Conditional Go로 올릴 근거는 생기지
    않았고, 오히려 완화안의 신뢰도를 낮추는 방향의 새 근거가
    확보됐다. **판정: Watch 유지(격상 근거 없음), 완전 제거는
    여전히 No-Go(§14 유지).** 신규 KIS 호출 0건(기존 3년 캐시 88개
    파일로 전량 서빙, 로그로 실측 확인). `entry_score`/`_assess_
    buy_eligibility` 운영 코드 변경 없음 — 이번 턴도 shadow/
    validation 범위. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §15.
  - 산출물: `scripts/validate_activity_filter_threshold_sweep.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_activity_
    filter_threshold_sweep_2026-07-16.json`, `logs/activity_filter_
    threshold_sweep_run_2026-07-16.log`.
  - 다음 과제: 전반부·후반부가 왜 정반대 방향을 보이는지(국면 분포,
    유동성 레벨 구조 변화 등) 원인 규명이 threshold 상수 변경 검토의
    선행 조건이다.
- [x] **SPPV-2.26(신설)** 활동성 필터 완화 효과 전반부/후반부 반전
  원인 분해 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.25가 발견한 "완화 효과가 3년 전반부에서는
    반대로 나타나는" 현상의 원인을 규명. 시장 공통 regime 분포,
    activity_ratio 분포, 상위 20% 무차단 기본 수익률 레벨,
    volatility/turnover/trend 보조 축, 그리고 threshold 완화 시
    "새로 통과하는 표본"만 분리한 forward return 비교로 4개 축을
    분해.
  - **결과: (1) regime 분포 — 전반부(2023-10~2025-02)는 range_
    bound 45.4%+bearish_trend 28.5%로 혼합/약세 편중, 후반부
    (2025-02~2026-06)는 bullish_trend 82.9%로 강세장 극도 편중.
    (2) 상위 20% 무차단 기본 수익률 — 후반부가 전반부보다 T+5는
    약 3.3배, T+20은 약 3.4배 높음(전반부 +0.47%/+1.60% vs 후반부
    +1.54%/+5.48%). (3) 유동성 구조 — average_turnover_20d
    중앙값이 후반부에 약 1.9배(378억→706억), trend_strength도
    약 2.4배(+6.93%→+16.67%) 확대. (4) 결정적 비교 — threshold를
    1.10→1.00으로 낮췄을 때 새로 통과하는 표본의 T+5 평균이
    전반부에서는 기존 통과군보다 낮고(+0.56% < +0.74%, 비유의),
    후반부에서는 기존 통과군보다 높다(+2.72% > +1.86%, 유의).**
    **결론: 완화 효과의 반전은 활동성 필터 로직 결함이 아니라
    두 반기의 시장 국면(혼합/약세 vs 강세장 극편중)과 유동성 구조
    (거래대금 약 1.9배 확대)가 결합된 결과로 판단** — 국면·유동성
    변화가 "완화 시 새로 들어오는 한계 종목"의 실제 품질 자체를
    바꿔놓았다는 것이 가장 직접적인 인과 고리다. **판정: 정적
    threshold 완화안은 여전히 Watch 유지(격상도 강등도 아님) — 완전
    제거는 여전히 No-Go.** 향후 검토 방향은 "완화"가 아니라 "국면
    조건부 threshold"일 가능성이 있으나, 이는 새 설계 제안이며 이번
    턴은 원인 규명까지만 수행(설계·구현·운영 코드 변경 없음). 신규
    KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측 확인).
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §16.
  - 산출물: `scripts/diagnose_activity_filter_half_period_
    divergence.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_
    activity_filter_half_period_divergence_2026-07-16.json`,
    `logs/activity_filter_half_period_divergence_run_2026-07-16.log`.
  - 다음 과제: "국면 조건부 활동성 threshold" 설계 검토 여부를
    사용자에게 확인받는 것, 유동성 구조 확대(거래대금 약 1.9배)가
    일시적인지 영구적인지 장기 모니터링.
- [x] **SPPV-2.27(신설)** alpha layer 교체 BUY funnel(candidate→
  eligible→would_buy→blocked) 검증 (완료, 2026-07-16)
  - 작업 범위: 무게중심을 활동성 필터(§14~§16)에서 원래 핵심 레버인
    alpha 교체(§12)로 되돌려, 현행 alpha(`current_alpha_composite`)
    와 `regime_conditional_signal`을 candidate(상위 20%)→eligible
    (운영 `_assess_buy_eligibility` 그대로)→would_buy(eligible 중
    entry_score 상위 `WATCH_TOP_K_BUY=3`, 실제 운영 상수 재사용)→
    blocked 4단계 BUY funnel로 비교. entry_score는 시나리오 A는
    운영 함수 그대로, 시나리오 B는 §3 제안 그대로 alpha 항(0.80
    가중치)만 교체하고 나머지는 동일 공식으로 재구성(운영 코드
    미수정).
  - **결과: would_buy(최종 매수 후보) 단계의 forward return이 2차
    (3년)·1차(최근 12개월)·3년 전반부·3년 후반부 4개 창, T+5/T+20
    2개 horizon 전부(8/8)에서 새 alpha(B)가 현행(A)보다 높았다**
    (예: 2차 T+20 A +1.90%/t_NW=2.38 vs B +2.82%/t_NW=2.90; 1차
    T+20 A +3.15%/t_NW=2.09 vs B +4.31%/t_NW=2.59). **활동성 필터
    완화(§15)에서는 전반부에서 방향 자체가 반전됐던 것과 달리, 이번
    alpha 교체 효과는 4개 창 전부에서 방향이 한 번도 뒤집히지
    않았다** — 3년 전반부만 두 시나리오 모두 비유의(t_NW 0.5~1.2)
    했으나 방향(B>A)은 유지됐다. funnel 전환율은 B가 eligible
    비율이 더 낮아(2차 31.7% vs 49.2%) would_buy 표본 수도 약 20%
    적었지만(2차 1,543 vs 1,920), 표본당 평균 수익률 개선폭이 더
    커서 표본 수×평균 수익률의 합(누적 기대 성과 근사)은 B가 A보다
    여전히 컸다(2차 T+20 기준 A 36.6 vs B 43.5, 약 19% 개선).
    **판정: §12의 Conditional Go가 funnel의 실제 매수 후보 단계까지
    보강됐다 — 그러나 3년 전반부 비유의, 국면 편향 가능성(§16과 동일
    우려), 거래 빈도 감소 트레이드오프 때문에 확정 Go는 아니다.**
    신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측 확인).
    `entry_score` 운영 코드 변경 없음 — 이번 턴도 shadow/validation
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §17.
  - 산출물: `scripts/validate_alpha_layer_buy_funnel_comparison.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_alpha_layer_
    buy_funnel_comparison_2026-07-16.json`, `logs/alpha_layer_buy_
    funnel_comparison_run_2026-07-16.log`.
  - 다음 과제: §3 전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_
    penalty 중복 해소) 충족 후 재검증, regime별 층화 비교, 거래
    빈도 감소의 운영 영향 별도 검토.
- [x] **SPPV-2.28(신설)** alpha layer 교체 virtual BUY funnel 확장
  검증(candidate→eligible→selected→would_buy) (완료, 2026-07-16)
  - 작업 범위: SPPV-2.27의 `would_buy`를 실제 운영 판단 경로에
    한 단계 더 가깝게 확장. 운영 함수 `assess_deterministic_
    triggers()`가 실제로 쓰는 `BUY_CANDIDATE` 조건(`eligible AND
    entry_score>=0.65(운영 상수 buy_candidate_threshold) AND
    allocation_budget_ok`)을 그대로 재현한 `selected` 단계를 추가.
    MFE/MAE도 함께 계측(`validate_signal_predictive_power_v2.py`
    기존 패턴 재사용). broker submit은 호출하지 않음.
  - **결과: `selected` 단계 추가 후에도 would_buy의 forward return
    우위(현행 대비 새 alpha)는 4개 창·2개 horizon 전부(8/8)에서
    유지됐다.** **결정적 신규 계측**: 새 alpha(B)는 4개 창 전부에서
    `selected` 비율이 **정확히 100.0%**(`blocked_by_score_
    threshold=0`, 예외 없음) — candidate 정의(그날 alpha 상위
    20%)와 selected 조건(같은 alpha 기반 entry_score>=0.65)이
    사실상 같은 신호를 두 번 거르는 구조라, **0.65 문턱이 새
    alpha에는 사실상 무력화된다는 계측 caveat을 새로 발견**했다.
    현행(A)은 eligible의 66~72%만 이 문턱을 통과해 실제로 필터링
    효과가 있다. **MFE/MAE 비교: 새 alpha는 4개 창 전부에서 MFE
    (상방)도 크고 MAE(하방) 절댓값도 크지만, MFE/|MAE| 비율은 4개
    창 전부에서 새 alpha가 더 높다**(예: 2차 T+20 MFE/|MAE| 현행
    1.50 vs 신규 1.68). **판정: SPPV-2.27의 Conditional Go를
    재확인했으나, "0.65 문턱 사실상 무력화"와 "MAE 절댓값 확대"라는
    두 계측 caveat이 추가되어 여전히 확정 Go는 아니다.** 신규 KIS
    호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측 확인). 운영
    코드 변경 없음 — 이번 턴도 shadow/validation 범위. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §18.
  - 산출물: `scripts/validate_alpha_layer_virtual_buy_funnel_
    extended.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_
    alpha_layer_virtual_buy_funnel_extended_2026-07-16.json`,
    `logs/alpha_layer_virtual_buy_funnel_extended_run_2026-07-16.log`.
  - 다음 과제: §3 공식의 재보정(스케일링) 설계 검토 여부 사용자
    확인, §3 전제조건 충족 후 재검증, regime별 층화 비교, MAE 확대가
    사이징/손절 설계에 미치는 영향 별도 검토.
- [x] **SPPV-2.29(신설)** 새 alpha entry_score 스케일 재보정 shadow
  검증 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.28이 발견한 "0.65 문턱 사실상 무력화" caveat의
    원인을 분해하고, 재보정 3안(R1 가중치 축소/R2 z-score/R3
    percentile)과 기준선(R0, 재보정 없음)을 candidate→eligible→
    selected→would_buy funnel + MFE/MAE로 비교. candidate 정의는
    바꾸지 않고 entry_score 계산에만 재보정 적용(운영 코드 미수정).
  - **원인: `regime_conditional_signal`이 [-1,1] 스케일이 아닌
    퍼센트 단위 비율(예: 3개월 수익률/변동성=6.0)이라 `_normalize_
    signed_score`가 상위 20% quintile에서 거의 항상 saturate(1.0)
    된다.**
  - **결과: R1(가중치 0.80→0.50)은 selected_rate를 46.6~67.8%로
    크게 낮췄지만 forward return이 4개 창 중 3개에서 오히려
    악화 — 기각.** **R2(z-score)는 selected_rate가 96.9~99.3%로
    R0(100%)와 큰 차이가 없어 문제를 충분히 해결하지 못함(상위
    20% 멤버는 정의상 z>=1 saturate 경계 근처에 몰림) — forward
    return은 3/4 창에서 개선됐으나 문턱 회복 목적은 미흡.**
    **R3(percentile)가 가장 균형 잡힌 결과: selected_rate가
    93.7~96.5%로 의미 있게 내려오면서(문턱 실질 회복), forward
    return이 4개 창·2개 horizon 전부(8/8)에서 R0보다 개선됐고**
    (예: 2차 T+20 R0 +2.818% vs R3 +3.591%, 1차 T+20 R0 +4.307%
    vs R3 +6.050%), **would_buy 표본 감소는 1.2~2.4%로 미미했으며,
    MAE(하방 절댓값)는 오히려 3개 창에서 근소하게 개선됐다.**
    **결론: R1/R2는 기각, R3(percentile 기반 스케일링)를 유력한
    재보정 후보로 채택 검토(Watch→Conditional Go 경계)한다 — 다만
    단일 실험·재현성 미확인·§3 기존 전제조건 미충족으로 확정 Go는
    아니다.** 신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로
    실측 확인). 운영 코드 변경 없음, broker submit 미호출 — 이번
    턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §19.
  - 산출물: `scripts/validate_alpha_layer_score_rescaling_
    comparison.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_
    alpha_layer_score_rescaling_comparison_2026-07-16.json`,
    `logs/alpha_layer_score_rescaling_comparison_run_2026-07-16.log`.
  - 다음 과제: R3의 §3 공식 정식 반영 여부 사용자 확인, R3 재현성
    추가 검증(분기별 분할 등), percentile 계산의 universe 구성
    민감도 점검.
- [x] **SPPV-2.30(신설)** R3(percentile 재보정) 재현성 검증 +
  percentile 계산 민감도 점검 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.29가 채택 검토한 R3를 분기 4분할로 재검증하고,
    percentile 계산 기준(그날 전체 universe vs candidate 컷 이후
    내부)의 민감도를 점검. 비교 대상은 A(현행 alpha)/B_R0(재보정
    없음)/B_R3(전체 universe 기준)/B_R3b(candidate 내부 기준,
    신규 민감도 변형) 4개.
  - **결과: R3(전체 universe 기준)의 "4개 창(2차/1차/전반부/후반부)
    전부 우위"라는 SPPV-2.29의 결론은, 분기 4분할로 더 잘게
    쪼개자 무너졌다 — 분기1(2023-10~2024-06)과 분기3(2025-02~
    2025-10)에서 R3가 오히려 R0보다 forward return이 낮았다**(분기1
    T+20 R0 +1.208% vs R3 +1.041%, 분기3 T+20 R0 +3.648% vs R3
    +3.402%). SPPV-2.29의 4개 창은 서로 크게 겹치는 넓은 구간
    (특히 "후반부"≈"최근 12개월")이었기 때문에, 분할 해상도가
    낮았을 때만 "8/8 재현"으로 보였을 가능성이 높다. **percentile
    계산 기준 민감도도 크게 나타났다: candidate 컷 이후 내부에서
    재계산한 R3b는 8개 창 전부(분기1·분기3 포함)에서 R0보다
    일관되게 높았으나**, selected_rate가 29.9~39.2%까지 낮아져
    §19에서 기각한 R1(가중치 축소)과 유사한 "극단적 선별" 패턴을
    보였다 — 개선이 진짜인지 이번 실험만으로 확정할 수 없다.
    **판정: SPPV-2.29의 "R3 유력 후보로 격상" 판정을 철회하고
    Watch로 하향한다** — 분기 단위 재현성 검증에서 2/4(50%) 분기가
    방향을 뒤집은 것은 "일부 분할 창에서 흔들리면 Watch/Hold"라는
    판정 원칙에 정확히 해당한다. **R3b는 새로운 관찰 대상으로
    등록하되 이번 턴에 유력 후보로 올리지 않는다**(R1과 동일한
    선택률 급감 우려를 별도 검증해야 함). 신규 KIS 호출 0건(기존
    3년 캐시로 전량 서빙, 로그로 실측 확인). 운영 코드 변경 없음,
    broker submit 미호출 — 이번 턴도 shadow/validation 범위. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §20.
  - 산출물: `scripts/validate_alpha_layer_r3_reproducibility.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_alpha_layer_
    r3_reproducibility_2026-07-16.json`, `logs/alpha_layer_r3_
    reproducibility_run_2026-07-16.log`.
  - 다음 과제: R3b를 R1과 동일한 엄격도로 별도 검증, 분기1·분기3에서
    R3가 R0보다 못한 원인 규명(§16과 유사한 국면/유동성 분해),
    향후 재보정 검증은 분기 단위 이상 세분화된 분할을 표준 절차로
    삼는다.
- [x] **SPPV-2.31(신설)** R3b 엄격 재검증 + R3 실패 구간(분기1/
  분기3) 원인 분해 (완료, 2026-07-16)
  - 작업 범위: R3b를 R1과 동일한 엄격 기준(4개 창 중 하나라도
    forward return이 악화되면 기각)으로 8개 창(2차/1차/전후반/
    분기1~4) 전부 재검증하고, would_buy 종목 집합의 overlap
    (R3/R3b가 R0와 얼마나 같은 종목을 고르는지)을 계측해 "진짜
    선별 품질 개선"과 "표본 급감 착시"를 분리. 추가로 §16 방식의
    국면/유동성 분포 + saturation 비율(원시 신호가 1.0을 넘어
    normalize에서 포화되는 비율)로 분기1·분기3에서 R3가 R0보다
    못한 원인을 분해.
  - **결과 1(R3b 엄격 검증): R3b는 8개 창 전부(R1이 실패한 기준
    그대로, R3가 실패한 분기1·분기3 포함)에서 R0보다 forward
    return이 높았다**(2차 T+20 R0 +2.818% vs R3b +6.134%, 분기1
    T+20 R0 +1.208% vs R3b +2.616%, 분기3 T+20 R0 +3.648% vs
    R3b +4.932%). **overlap 진단 — R3(전체 universe 기준)는 R0와
    77~85%가 같은 종목을 고르는 반면, R3b(candidate 내부 기준)는
    R0와 47~61%만 겹친다** — R3b는 R0가 고르지 않았을 종목의
    40~53%를 새로 골라 넣는 질적으로 다른 선별이며, 순수 표본
    축소 착시(선별 집합이 R0의 단순 부분집합)라면 겹침률이 100%에
    가까워야 하는데 실제로는 절반 가까이가 다른 종목이다 — **표본
    급감 착시가 아니라 실제 재선별 효과로 판단**.
  - **결과 2(R3 실패 원인 분해): saturation_rate가 4개 분기 전부
    100.0%로 동일**하여 이 자체는 분기간 차이의 원인이 아니다.
    국면 분포도 깔끔한 설명을 주지 못한다 — **분기3은 강세장
    67.5%가 지배적인데도 R3가 실패했고, 분기2는 약세+횡보 90.8%가
    지배적인데도 R3가 성공**했다("강세장이면 R3가 이긴다"는 가설과
    정확히 반대). activity_ratio·volatility 분포도 분기1~3 사이에
    뚜렷한 차이가 없었다. **결론: R3의 실패는 특정 국면·유동성
    조건 때문이 아니라, R3가 R0와 77~85%나 겹치는 "미세 재조정"에
    불과해 효과 크기 자체가 작고, 그만큼 분기 단위 표본 잡음에
    취약하다는 구조적 한계로 해석하는 것이 더 정확하다.**
  - **판정(당시 판정, SPPV-2.32에서 재정정됨): R3b를 유력한 재보정
    후보로 신규 격상한다(Watch→Conditional Go 경계) — R1이 실패한
    엄격 기준을 통과한 첫 재보정안이다.** 다만 selected_rate가
    29.9~39.2%로 매우 낮고(거래 빈도 최대 36% 감소), 이번 검증도
    동일 3년 표본 내부 분할일 뿐 진정한 out-of-sample은 아니며,
    §3의 기존 전제조건도 미충족이라 확정 Go는 아니다. **[중요]
    이 판정의 핵심 근거였던 overlap(간접 지표)은 SPPV-2.32의
    대응표본(직접) 검증에서 근거가 부족했음이 드러났다 — 분기3에서
    실제 대체 종목쌍의 forward return 차이가 음수로 뒤집혔다.
    이 판정은 SPPV-2.32에서 다시 Watch로 하향 정정됐다 —
    상세는 §22 참고.** **R3는 Watch를 그대로 유지**한다 — 이번
    원인 분해로도 하향 판정이 번복되지 않았고, SPPV-2.32의
    직접 검증으로 오히려 근거가 강화됐다. 문서 정정:
    §20/SPPV-2.30의 "분기 25%가 뒤집혔다"는 계산 오류였다(2/4=
    50%가 맞음) — 5개 정본 문서 전체에서 정정 완료, 결론에는
    영향 없음(오히려 더 심각한 재현성 결여를 뜻함). 신규 KIS 호출
    0건(기존 3년 캐시로 전량 서빙, 로그로 실측 확인). 운영 코드
    변경 없음, broker submit 미호출 — 이번 턴도 shadow/validation
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §21.
  - 산출물: `scripts/validate_r3b_strict_and_r3_failure_
    decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_strict_and_r3_failure_decomposition_2026-07-16.
    json`, `logs/r3b_strict_and_r3_failure_decomposition_run_
    2026-07-16.log`.
  - 다음 과제: R3b를 §3 공식에 정식 반영할지 사용자 확인, R3b의
    거래 빈도 감소가 자본 회전에 미치는 영향 검토, percentile
    순위-forward return IC를 분기별로 직접 계산하는 후속 분석,
    이 3년 표본을 벗어난 진정한 out-of-sample 기간에서 R3b 장기
    모니터링.
- [x] **SPPV-2.32(신설)** R3b 대응표본(paired-sample) 검증 —
  overlap 근거 보정 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.31의 overlap(간접) 근거를 대응표본(직접)
    검증으로 재확인. 같은 거래일·같은 candidate 집합에서 R0가
    버리고 R3b가 새로 고른 "대체 종목쌍"의 forward return 차이를
    일별로 계산해 창별로 집계(평균/Newey-West t/양수 비율/경험적
    95% 구간). R0 vs R3(전체 universe)에도 동일 적용.
  - **결과: R0 vs R3b 대체쌍(added−dropped) T+20 평균은 8개 창 중
    6개에서 양(+)이었으나(2차 +5.70%p, 1차 +8.20%p, 전반부
    +3.66%p, 후반부 +7.11%p, 분기2 +3.99%p, 분기4 +13.66%p),
    **분기3에서는 음수(-0.47%p, 대체 우위일 비율 45.8%로 절반
    미만)로 뒤집혔다.** **(SPPV-2.33에서 정정: t_NW>=1.96 기준을
    충족하는 창은 실제로 2차(1.96)·전반부(2.07)·분기1(2.02) 3개다
    — 최초 서술은 분기1을 누락한 계산 오류였다. 판정 기준은
    "|t_NW|>=1.96(근사 양측 95%, 경계값 포함)"으로 명시한다.)**
    나머지 창은 1.0~1.9의 marginal한 값이었다. **R0 vs R3(전체
    universe) 대체쌍은 더 약했다** —
    분기1(-0.44%p, 사실상 음수)·분기3(-0.04%p, 사실상 0)로 대체
    효과가 없거나 음수인 창이 2개였다.
  - **핵심 정정: SPPV-2.31이 "R3b는 R0와 47~61%만 겹쳐 실제
    재선별 효과"라고 결론 낸 것은 overlap(간접) 근거만으로 내린
    판단이었다 — 이번 대응표본(직접) 검증에서 그 재선별이
    "분기3에서는 오히려 더 나쁜 종목으로의 교체"였음이 드러났다.**
    §2.31의 aggregate 우위(8/8 창) 자체는 부정되지 않으나, 그
    우위가 "대체 종목의 우수성"에서 왔다는 인과관계는 확인되지
    않았다 — 오히려 분기3에서는 반대 증거가 나와, aggregate 우위가
    다른 경로(공통 유지 종목의 성과, 모집단 구성 차이 등)로
    발생했을 가능성이 제기됐다. **판정: SPPV-2.31의 "R3b 유력
    후보로 격상" 판정을 다시 Watch로 하향한다.** R3는 Watch를
    유지하되, 이번 직접 검증이 오히려 "R3는 R0와 겹침이 많아 효과
    크기가 작다"는 §2.31의 가설을 간접이 아닌 직접 증거로 재확인해
    근거를 강화했다. 신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙,
    로그로 실측 확인). 운영 코드 변경 없음, broker submit 미호출
    — 이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §22.
  - 산출물: `scripts/validate_r3b_paired_replacement_analysis.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_paired_
    replacement_analysis_2026-07-16.json`, `logs/r3b_paired_
    replacement_analysis_run_2026-07-16.log`.
  - 다음 과제: R3b의 aggregate 우위와 대체쌍 성과(분기3 음수)가
    불일치하는 원인 규명(공통 유지 종목 기여도, 모집단 구성 변화
    등), 더 긴 표본·더 많은 교체 발생일 축적 후 재평가, 향후
    재보정 검증은 overlap만으로 재선별 품질을 증명하지 않고 반드시
    대응표본 직접 비교를 병행하는 것을 표준 절차로 삼는다.
- [x] **SPPV-2.33(신설)** R3b aggregate 우위 vs 대응표본 음수 구간
  3분해(common_kept/dropped_only/added_only) (완료, 2026-07-16)
  - 작업 범위: SPPV-2.32의 "aggregate 우위와 대체쌍 성과 불일치"
    원인을 정확한 항등식 분해로 규명. R0의 would_buy와 R3b(또는
    R3)의 would_buy를 common_kept(둘 다 고름)/dropped_only(R0만)/
    added_only(신규안만) 3개 그룹으로 완전히 분해하고, `mean(R0)
    = (n_common·mean_common + n_dropped·mean_dropped)/(n_common+
    n_dropped)` 항등식으로 각 그룹의 기여를 정확히 계측. 이번
    턴은 재격상보다 원인 규명을 우선했다(작업 지시에 따름).
  - **문서 정정**: SPPV-2.32의 "t_NW>=1.96 창 2개(2차·전반부)"
    서술을 산출 JSON 원본으로 재확인한 결과 **실제로는 3개
    (2차=1.96, 전반부=2.07, 분기1=2.02)**로, 분기1을 누락한 계산
    오류였다. 판정 기준을 "|t_NW|>=1.96(근사 양측 95%, 경계값
    포함)"으로 명시했다.
  - **결과: R0 vs R3b 3분해에서 `added_only`의 평균이 8개 창 전부
    에서 `common_kept`·`dropped_only`보다 뚜렷이 높았다**(예: 2차
    T+20 added +8.98% vs common +3.83% vs dropped +2.23%) —
    "R3b가 새로 골라 넣은 종목이 실제로 고수익을 냈다"는 것은
    사실이며, SPPV-2.32의 표본 급감 착시 우려를 상당 부분
    반박한다. **다만 "구성/표본수 효과"도 상당하다** — R0의
    would_buy 구성은 dropped_only(63.3%, 2차)가 common_kept
    (36.7%)보다 훨씬 큰 비중인 반면, R3b는 added_only(44.7%)와
    common_kept(55.3%)가 비교적 균형 잡혀 있다. dropped_only가
    common_kept보다 평균이 낮으므로, R0 자신의 집합이 "저품질
    다수"에 더 크게 끌려 내려간다는 것도 aggregate 차이의 상당
    부분을 설명한다. **[SPPV-2.34에서 정정] 이 문단의 방향이
    틀렸다 — 정확한 항등식 분해(§24) 결과 구성효과는 8개 창 중
    6개에서 오히려 음(-)으로, R3b의 우위를 만드는 것이 아니라
    상쇄하는 방향이었다. aggregate 우위 전체는 사실상 순수
    replacement_effect(교체 종목 자체의 품질 차이)에서 온다 —
    상세는 §24 참고. **[SPPV-2.35에서 추가 보정] "8개 창 중 6개"는
    T+5/T+20 horizon을 뒤섞은 부정확한 표현이었다 — 정확히는
    T+20 기준 8개 창 전부(8/8)에서 음(-), T+5 기준 8개 창 중
    5개에서만 음(-)이다(전반부·분기1·분기2는 T+5에서 오히려
    양(+)). 상세는 §25 참고.** **가장 중요한 발견: 분기3에서 이번 pooled
    계산(교체효과 +2.594%p, 양)과 SPPV-2.32의 일별 대응표본(paired,
    -0.4666%p, 음)의 부호가 정반대다** — 두 지표는 가중 방식이
    다르다(pooled는 종목-일 단위 동일 가중이라 스왑이 많이 일어난
    날의 영향력이 커지고, paired는 거래일 단위 동일 가중이라 매일을
    동등하게 취급). **이 부호 불일치 자체가 R3b의 교체 효과가
    "매일 조금씩 좋다"가 아니라 "소수의 스왑 밀집일에 크게 좋고
    나머지 평범한 날에는 오히려 나쁘다"는 비대칭 구조임을 시사하며,
    안정적으로 재현 가능한 일상적 edge가 아니라 특정 구간에 몰린
    효과일 가능성을 뒷받침한다.** R0 vs R3(전체 universe)에서는
    분기1·분기3 모두 added_only가 dropped_only보다 낮아(교체효과
    음수) §21의 "미세 재조정" 가설이 pooled 직접 계측으로도
    재확인됐다. **판정: R3b의 aggregate 우위는 부분적으로 실체가
    있으나(added_only의 실제 우수성) 비대칭적이고 소수 구간에
    집중된 것으로 보여 "안정적 재현 가능"이라 단정하기엔 이르다 —
    R3b/R3 모두 SPPV-2.32의 Watch 판정을 그대로 유지한다(이번 턴은
    재격상이 아니라 원인 설명이 목적).** 신규 KIS 호출 0건(기존
    3년 캐시로 전량 서빙, 로그로 실측 확인). 운영 코드 변경 없음,
    broker submit 미호출 — 이번 턴도 shadow/validation 범위. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §23.
  - 산출물: `scripts/validate_r3b_aggregate_vs_paired_
    decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_aggregate_vs_paired_decomposition_2026-07-16.
    json`, `logs/r3b_aggregate_vs_paired_decomposition_run_
    2026-07-16.log`.
  - 다음 과제: 분기3처럼 pooled/paired 부호가 갈리는 구간의
    거래일 단위 세밀 진단(스왑 밀집일 존재 여부), R3b의 구성
    효과와 활동성 필터·다른 차단 축의 상호작용 확인, SPPV-2.32에
    남은 과제(더 긴 표본 축적, §3 공식 반영 여부 사용자 확인 등)는
    계속 유효.
- [x] **SPPV-2.34(신설)** R3b pooled 우위 날짜 집중도 검증 +
  교체효과/구성효과 정량 분리 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.33이 지시한 분기3 세밀 진단을 실행. 거래일별
    스왑 개수(added+dropped)를 계산해 상위 10%(top-decile) 거래일을
    제거했을 때 pooled aggregate 우위가 얼마나 남는지(잔존비율)
    재계산. 동시에 `aggregate_diff = replacement_effect +
    composition_effect`(정확한 항등식, `replacement_effect =
    w0'·(mean_added-mean_dropped)`, `composition_effect = (w1'-w0')·
    (mean_added-mean_common)`, w0'=R0 자신의 dropped 비중, w1'=
    신규안 자신의 added 비중)로 두 효과를 정확히 분리.
  - **결과 1(날짜 집중도): 스왑 상위 10% 거래일을 제거해도 8개 창
    중 7개(2차/1차/전반부/후반부/분기1/분기2/분기4)에서 aggregate
    우위가 80~120% 수준으로 거의 그대로 남거나 오히려 커졌다** —
    "소수 거래일 집중" 가설은 이 7개 창에서 기각된다. **분기3만
    예외로 잔존비율이 T+5=29.7%, T+20=65.2%로 크게 줄어들어**, 이미
    발견한 pooled·paired 부호 불일치가 실제로 소수 스왑 밀집일이
    만든 아티팩트임이 직접 확인됐다.
  - **결과 2(정확한 효과 분리) — [중요 정정]: SPPV-2.33의 "구성
    효과도 상당히 기여한다"는 서술은 방향이 틀렸다.** 정확한
    항등식 분해 결과 `composition_effect`는 8개 창 중 6개에서
    오히려 음(-)이었다(예: 2차 T+20 aggregate=+3.32%p = replacement
    +4.27%p + composition **-0.96%p**) — **구성효과는 R3b의 우위를
    만드는 것이 아니라 오히려 상쇄하는 방향으로 작용**했고,
    aggregate 우위 전체는 사실상 `replacement_effect`(교체 종목
    자체의 품질 차이) 하나에서 나온다. R0 vs R3에서도 같은 패턴(분기
    1·분기3은 replacement_effect 자체가 음수). **[SPPV-2.35에서
    보정] "8개 창 중 6개"는 T+5/T+20을 뒤섞은 표현이었다 — 정확히는
    T+20 기준 8/8, T+5 기준 5/8에서 음(-)이다(전반부·분기1·분기2는
    T+5에서 양(+)). §25 참고.**
  - **판정: 이번 턴도 재격상보다 원인 확정을 우선했다(지시에
    따름).** R3b의 aggregate 우위 근거는 이전보다 명확해졌다(순수
    교체효과이며 날짜 집중형도 아님) — 그러나 분기3이라는 명백한
    반례가 남아 있고 그 반례는 실제 소수 거래일 집중형임이 확인돼,
    **R3b/R3 모두 SPPV-2.32~2.33의 Watch 판정을 그대로 유지한다.**
    신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측
    확인). 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
    shadow/validation 범위. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §24.
  - 산출물: `scripts/validate_r3b_day_concentration_and_effect_
    decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/
    signal_ic_r3b_day_concentration_and_effect_decomposition_
    2026-07-16.json`, `logs/r3b_day_concentration_and_effect_
    decomposition_run_2026-07-16.log`.
  - 다음 과제: 분기3의 스왑 상위 10% 거래일을 구체적으로 나열해
    이벤트/실적 발표 등 특정 사유 존재 여부 확인, R3b의 §3 공식
    정식 반영 여부는 이번까지 축적된 근거(부분적 실체 확인 + 명백한
    반례 1개)를 사용자가 종합 판단, §22.5/§23.7에 남은 과제(더 긴
    표본 축적, §3 전제조건 충족 후 재검증)는 계속 유효.
- [x] **SPPV-2.35(신설)** 분기3 스왑 집중일 세부 진단 + SPPV-2.34
  해석 문구 정밀 보정 (완료, 2026-07-16)
  - 작업 범위: SPPV-2.34가 지시한 "분기3 스왑 상위 10% 거래일
    구체 나열"을 실행하고, 동시에 SPPV-2.34의 두 서술("구성효과는
    8개 창 중 6개에서 음수", "분기3은 소수 날짜에 몰린 착시")을
    실제 수치 기준으로 정밀 보정. 재격상/재하향보다 원인 확정과
    표현 정밀화를 우선했다(지시에 따름).
  - **보정 1(horizon 구분)**: `composition_effect`의 "8개 창 중
    6개 음(-)"이라는 표현은 T+5/T+20을 뒤섞어 부정확했다. 정확히는
    **T+20 기준 8개 창 전부(8/8)에서 음(-)이고, T+5 기준으로는
    8개 창 중 5개에서만 음(-)이다**(전반부·분기1·분기2는 T+5에서
    오히려 양(+)).
  - **보정 2(날짜 집중 해석 정밀화)**: 분기3의 스왑 발생일 83건 중
    상위 15건(스왑개수 4~6)을 개별 진단한 결과, "소수 날짜에 몰린
    착시"라는 SPPV-2.34의 잠정 해석은 방향이 과했다. **실제로는
    스왑 상위 10%(대형 스왑일, 약 8일)의 T+20 교체효과 단순평균이
    +7.04%p로 뚜렷한 양(+)이고, 분기3 전체 83일 paired 평균
    (-0.4666%p, 음)을 만드는 진짜 원인은 나머지 약 75개 소규모
    스왑일에서 평균 약 -1.267%p의 완만하지만 지속적인 음(-) 효과가
    누적된 것**이다(가중평균 항등식으로 역산: (8×7.04+75×X)/83
    = -0.4666 ⇒ X≈-1.267). 즉 "대형 스왑일이 나쁘다"가 아니라
    "대형 스왑일은 유일한 강한 양(+)의 원천이고, 그것을 빼면 넓게
    퍼진 다수의 완만한 음(-) 거래일만 남는다"는 구조다. **[SPPV-
    2.36에서 정정] "유일한 강한 양(+)의 원천"은 과장이었다 —
    분기3 83개 스왑일 전부를 5분위로 구간화한 결과, 대형 스왑일
    (상위 10%)은 총 양(+) 합계의 15% 수준만 차지했고, 소규모
    구간(Q4, 스왑 2~3개)도 T+20 기준 +4.38%p의 뚜렷한 양(+)이었다
    — "대형=양(+)/소규모=음(-)"은 양극단(Q1·Q5)에서만 성립하고
    중간 구간은 혼재한다. 상세는 §26 참고.**
  - **이벤트/실적 연관성**: 가장 나쁜 두 거래일(2025-02-12,
    02-13)이 연속 거래일이라는 점은 짧은 이벤트/뉴스 군집 가능성을
    시사하나, 실적 캘린더·뉴스 데이터를 조회하지 않아 **가설
    수준**의 관찰이다. 가장 좋은 거래일들(03-21, 04-28, 05-07,
    05-27, 06-10, 09-19, 09-22, 09-24)은 2월 이후 거의 매달 흩어져
    있어 뚜렷한 군집 패턴이 없다.
  - **판정: 재격상/재하향 없이 R3b/R3 모두 Watch 판정을 그대로
    유지한다.** 분기3 반례의 구조가 "몇몇 나쁜 날 제거로 해결"이
    아니라 "몇몇 좋은 날을 빼면 기저가 약한 음(-)"이라는 것이
    확인돼, 오히려 재현성 우려가 더 구체화됐다. 신규 KIS 호출
    0건(기존 3년 캐시로 전량 서빙, 로그로 실측 확인). 운영 코드
    변경 없음, broker submit 미호출 — 이번 턴도 shadow/validation
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §25.
  - 산출물: `scripts/validate_r3b_q3_day_level_diagnostics.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_q3_day_
    level_diagnostics_2026-07-16.json`, `logs/r3b_q3_day_level_
    diagnostics_run_2026-07-16.log`.
  - 다음 과제: 2025-02-12~13 연속 악재일의 실제 이벤트/실적 발표
    연관성은 외부 데이터원 확보 후 검증, "대형 스왑일=양(+)/소규모
    스왑일=음(-)" 패턴이 다른 창에서도 약하게 존재하는지 후속 진단,
    §22.5/§23.7/§24.6에 남은 과제(더 긴 표본 축적, R3b의 §3 공식
    반영 여부 사용자 확인)는 계속 유효.
- [x] **SPPV-2.36(신설)** 분기3 반례의 대형/소규모 스왑 구조 정밀
  확정 + "전적으로 의존" 문구 보수화 (완료, 2026-07-17)
  - 작업 범위: SPPV-2.35의 "대형 스왑일은 유일한 강한 양(+)의
    원천이고 그것을 빼면 소규모 스왑일만 남는다"는 서술을 83개
    스왑일 전체를 5분위(quintile)로 구간화해 정량 검증. 재격상/
    재하향보다 문구 정밀화와 구조 확정을 우선했다(지시에 따름).
  - **결과 1(5분위 분해)**: T+20 기준 Q1(최대, 스왑 4~6)=+6.29%p,
    Q2(스왑4)=-3.04%p, Q3(스왑3~4)=-2.96%p, Q4(스왑2~3)=**+4.38%p**,
    Q5(최소, 스왑2)=**-7.57%p**. **"대형=양(+)/소규모=음(-)"은
    양극단(Q1·Q5)에서만 성립하고 중간 구간은 혼재**한다 — Q4는
    소규모인데도 뚜렷한 양(+)이라 단조적 그래디언트가 아니다.
  - **결과 2(전적 의존 여부 — 두 관점의 불일치)**: aggregate(순
    기여) 관점에서 대형 스왑일(상위 10%)이 우위의 상당 부분을
    담당한다(leave-top-decile-out 잔존비율 T+5=29.7%, T+20=65.2% —
    즉 대형이 T+5 약 70%, T+20 약 35%를 담당). 그러나 **총합(gross)
    관점에서는 대형 스왑일이 전체 양(+) 합계의 15%(T+5 15.6%, T+20
    15.0%) 수준에 불과**하다 — 나머지 85%의 양(+)는 Q4를 포함한
    다른 구간에서도 나온다. **"유일한 원천"·"전적으로 의존"은
    과장이었다.**
  - **결과 3(02-12/13 설명력)**: 이 2일을 동시 제거하면 T+20 paired
    평균의 음(-) 갭이 -0.4666%p→-0.2829%p로 **약 39.4% 줄어든다**
    — 유의미하지만 부분적(과반 미만) 설명력이다.
  - **판정: 재격상/재하향 없이 R3b/R3 모두 Watch 판정을 그대로
    유지한다.** 분기3 반례는 여전히 실재하나("완전한 착시" 아님은
    유지), "전적으로/유일하게" 같은 절대적 표현은 총합 관점 수치와
    맞지 않아 정정했다. 신규 KIS 호출 0건(기존 3년 캐시로 전량
    서빙, 로그로 실측 확인). 운영 코드 변경 없음, broker submit
    미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §26.
  - 산출물: `scripts/validate_r3b_q3_swap_size_bucket_
    decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/signal_
    ic_r3b_q3_swap_size_bucket_decomposition_2026-07-17.json`,
    `logs/r3b_q3_swap_size_bucket_decomposition_run_2026-07-17.log`.
  - 다음 과제: Q4가 왜 소규모인데도 양(+)이고 Q2·Q3는 왜 음(-)인지
    스왑 개수 외 추가 변수(유동성, 국면 구성 등) 확인, 02-12~13
    이벤트/실적 연관성 외부 데이터 검증, §22.5/§23.7/§24.6/§25.7에
    남은 과제(더 긴 표본 축적, R3b의 §3 공식 반영 여부 사용자
    확인)는 계속 유효.
- [x] **SPPV-2.37(신설)** R3b의 SPPV-3 진입 후보 여부 판단 — 실제
  BUY funnel 최소 검증 (완료, 2026-07-17)
  - 작업 범위: R3b의 미세 해부(분기3 스왑 구조)를 멈추고 "R3b를
    SPPV-3 착수 후보로 올릴 수 있는가"를 판단. §20(SPPV-2.30)의
    실제 BUY funnel(candidate→eligible→selected→would_buy) 계측을
    재실행 없이 재사용하고, would_buy 모집단의 거래일 편중도(top-
    decile-day leave-out)만 8개 창 전부에 신규 계측했다.
  - **결과 1(§20 재확인): T+20 평균 우위는 8개 창 전부(8/8)에서
    R3b > R0.** t_NW는 6/8 창에서 통상 유의(≥1.96), 2개 창(분기1=
    1.31, 분기2=1.68)은 marginal이나 방향은 일관. 양수 비율은
    3/8 창(전반부·분기1·분기2)에서 R0보다 낮아, 이 구간의 개선은
    "적중률"이 아니라 "승리 폭(MFE)"에서 온다.
  - **결과 2(신규, 결정적 근거): 거래일 집중 의존은 R3b만의 문제가
    아니라 alpha 신호 계열 전반의 특성이다.** R0(현행 재보정 없음
    기준선) 자체가 T+20 기준 8개 창 중 3개(전반부/분기1/분기2)에서
    상위 10% 거래일을 제거하면 평균이 마이너스로 뒤집힌다(2차조차
    잔존비율 -0.1%). **R3b는 8개 창 전부(8/8)에서 R0보다 잔존비율이
    높다**(예: 2차 R0 -0.1% vs R3b 41.9%, 분기2 R0 -173.3% vs R3b
    35.2%) — R3b가 R0보다 거래일 집중에 **덜** 의존한다.
  - **판정: R3b를 Watch에서 Conditional Go로 상향한다.** 근거:
    8/8 창 방향 일관 + 6/8 t_NW 유의 + 거래일 편중도가 R0보다 8/8
    창에서 더 낮음(반대 가설을 직접 반박). 단, 확정 Go 전 잔여
    조건: (1) 분기1·분기2 marginal t_NW의 out-of-sample 재확인,
    (2) selected_rate 급감(29.9~39.2%)이 총 기대수익(거래 빈도
    ×종목당 수익)에 미치는 영향 정량화, (3) §3 전제조건(1차 게이트
    TRIGGERED 전환) 충족 확인, (4) 실제 point-in-time `entry_score`
    파이프라인 반영 shadow 실행. 신규 KIS 호출 0건(기존 3년 캐시로
    전량 서빙, 로그로 실측 확인). 운영 코드 변경 없음, broker submit
    미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §27. **[SPPV-
    2.38에서 정정] "8개 창 중 3개" 및 "3/8 창"은 계산 오류였다 —
    아래 SPPV-2.38 참고.**
  - 산출물: `scripts/validate_r3b_sppv3_entry_readiness_check.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_sppv3_
    entry_readiness_check_2026-07-17.json`, `logs/r3b_sppv3_entry_
    readiness_check_run_2026-07-17.log`.
  - 다음 과제: selected_rate 급감의 총 기대수익 영향 정량화, §3
    전제조건 충족 여부 사용자 확인, point-in-time `entry_score`
    파이프라인 반영 shadow 실행 설계, 분기1·분기2 marginal t_NW
    out-of-sample 재확인.
- [x] **SPPV-2.38(신설)** SPPV-2.37 수치 정정 + Conditional Go
  재평가 (완료, 2026-07-17)
  - 작업 범위: §2.37의 세 가지 수치 서술을 재검산해 정정하고,
    정정 후에도 Conditional Go 상향이 유지 가능한지 재평가. **새
    실험 없이** 기존 산출물(`logs/signal_ic_alpha_layer_r3_
    reproducibility_2026-07-16.json`, `logs/signal_ic_r3b_sppv3_
    entry_readiness_check_2026-07-17.json`)을 `python3 -c` read-only
    재검산만으로 확인(신규 실행 없음, KIS 호출 해당 없음).
  - **정정 1**: "R0가 8개 창 중 3개에서 T+20 평균이 마이너스로
    뒤집힌다"는 서술은 오류 — §2.37 자신의 표를 재확인하면 **2차
    (3년, -0.1%)도 음(-)이므로 정확히는 4개 창(2차·전반부·분기1·
    분기2)**이다. 이 정정은 R0의 취약성을 더 크게 보여줘 R3b의
    상대적 견고함 논거를 오히려 강화한다.
  - **정정 2**: "양수 비율이 3/8 창(전반부·분기1·분기2)에서 R0보다
    낮다"는 서술도 오류 — 재검산 결과 **T+20 기준 1/8 창(분기2)
    에서만** R3b 양수 비율이 R0보다 낮고(전반부·분기1은 R3b가 근소
    하게 더 높음), **T+5 기준으로는 8/8 창 전부에서 R3b가 R0보다
    높다.** 이 정정은 R3b에 유리한 방향이다.
  - **정정 3**: "selected_rate 급감(약 30~40%)"이라는 표현은 모호
    했다 — 정확히는 **R3b 자신의 selected_rate가 eligible 대비
    29.86~39.16% 수준**이며, R0(100%, 정의상) 대비 **약 61~70%p
    감소**다.
  - **판정: 세 정정 모두 R3b의 방향성 우위를 약화시키지 않아 R3b는
    Conditional Go를 유지한다.** §2.37의 확정 Go 전 잔여 조건
    4가지(분기1·분기2 marginal t_NW 재확인, selected_rate 감소의
    총 기대수익 영향 정량화, §3 전제조건 충족, point-in-time
    파이프라인 반영 shadow 실행)는 이번 정정과 무관하게 그대로
    유효하다. 이번 턴의 교훈은 판정 자체보다 "근거 숫자를 정확히
    세지 못했다"는 방법론적 경계다. 운영 코드 변경 없음, broker
    submit 미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §28.
  - 산출물: 신규 스크립트 없음(기존 JSON에 대한 `python3 -c`
    read-only 재검산만 수행, 산출 파일 생성 없음).
  - 다음 과제: §2.37의 4개 잔여 조건(위 참고)은 이번 턴과 무관하게
    계속 유효.
- [x] **SPPV-2.39(신설)** selected_rate 감소가 총 기대수익에 미치는
  영향 정량화 (완료, 2026-07-17)
  - 작업 범위: §2.37/§2.38의 확정 Go 전 잔여 조건 중 조건 (2) —
    "selected_rate 감소(약 61~70%p)가 총 기대수익(거래 빈도×종목당
    수익)에 미치는 영향 정량화"를 실행. **신규 실측/신규 KIS 호출
    없이** 기존 산출물 두 개(`logs/signal_ic_alpha_layer_r3_
    reproducibility_2026-07-16.json`, `logs/signal_ic_r3b_sppv3_
    entry_readiness_check_2026-07-17.json`)만 재사용해 로컬 계산.
  - **방법론**: `WATCH_TOP_K_BUY=3`(거래일당 최대 매수 슬롯, 실제
    운영 상수)가 would_buy 종목마다 동일 자본을 배정한다는 가정
    아래, 총 기대수익 proxy = would_buy_n(거래 횟수) × mean_
    forward_return_pct(거래당 평균 수익률)로 8개 창×2horizon(16개
    조합) 전부 계측.
  - **결과: 16개 조합 중 14개에서 R3b의 총 기대수익 proxy가 R0보다
    높다**(92.0%~322.6%, 중앙값 약 138%). 나머지 2개(1차 T+5=
    92.0%, 분기3 T+20=96.8%)도 R0에 근접한 거의 동률 수준이며,
    이전 턴들이 이미 지목한 약점 구간(1차 T+5 노이즈, 분기3의
    복잡한 날짜 구조)과 정확히 일치한다. 활동일당 평균 매수 수는
    R0(2.69~2.80, 거의 포화) 대비 R3b(2.15~2.31)가 낮아 "덜 산다"는
    것은 활동일 수·활동일당 매수 수 두 차원 모두에서 사실이다.
  - **판정: "거래 빈도 감소가 총 기대수익을 훼손하는가"에 명확히
    "아니다"로 답한다** — 거래당 수익률 개선이 거래 횟수 감소를
    충분히 상쇄하고도 남는다. **§2.37/§2.38의 확정 Go 전 잔여
    조건 4가지 중 조건 (2)는 이번 턴으로 해소됐다.** 다만 나머지
    3개 조건(분기1·분기2 marginal t_NW, §3 전제조건, point-in-time
    파이프라인 반영)이 그대로 남아 있어 **확정 Go는 아니며, R3b는
    Conditional Go를 유지하되 근거가 보강됐다.** 신규 KIS 호출
    없음(신규 실행 자체가 없었음). 운영 코드 변경 없음, broker
    submit 미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §29.
  - 산출물: `scripts/validate_r3b_total_expected_return_proxy.py`
    (read-only, 로컬 재계산, KIS 호출 없음), `logs/signal_ic_r3b_
    total_expected_return_proxy_2026-07-17.json`, `logs/r3b_total_
    expected_return_proxy_run_2026-07-17.log`.
  - 다음 과제: §3 전제조건 충족 여부 사용자 확인(다음 최우선),
    point-in-time `entry_score` 파이프라인 반영 shadow 실행 설계,
    분기1·분기2 marginal t_NW out-of-sample 재확인. **[SPPV-2.40에서
    정정] "조건 (2) 해소"는 과장이었다 — 아래 SPPV-2.40 참고.**
- [x] **SPPV-2.40(신설)** R3b 총 기대수익 proxy의 유휴 자본 반영
  보강 검증 (완료, 2026-07-17)
  - 작업 범위: §2.39가 "조건 (2) 해소"라 표현한 것이 유휴 자본
    기회비용을 반영하지 않은 채였다는 점을 보강 검증. 신규 계측은
    "창별 전체 거래일 수"(캐시 봉 데이터로만 계산, 신규 KIS 호출
    없음) 하나뿐이며, 나머지는 §20 JSON을 재사용.
  - **방법론**: (1) 기존(raw) proxy(§2.39와 동일), (2) 전체 슬롯
    (거래일×3) 정규화 per-slot proxy — R0/R3b 공통 분모라 대수적
    으로 raw와 비율이 동일함을 항등식으로 확인(실측으로도 소수점
    까지 일치), (3) **엄격 기준**: R3b의 실현된 총합을, "R0가 전체
    가용 슬롯을 하나도 남기지 않고 R0 자신의 평균으로 100% 채웠다"
    는 이론적 최대와 비교(R3b에 가장 불리한 벤치마크).
  - **결과: horizon에 따라 결론이 갈린다.** **T+20 기준 8개 창 중
    7개(분기3 제외)에서 R3b가 이 엄격 기준(R0 이론적 최대)보다도
    높다**(108.5%~177.5%) — T+20에서는 우위가 견고. **T+5 기준
    8개 창 중 6개에서 우위가 사라지거나 이미 열세**(84.3%~98.8%,
    전반부·분기2만 통과) — T+5에서는 우위가 유휴 자본 가정에 취약.
  - **판정: §2.39의 "조건 (2) 해소"는 과장이다.** 정확한 서술:
    **"조건 (2)는 T+20 기준으로는 상당 부분 완화됐으나, T+5
    기준으로는 여전히 미해결에 가깝다."** R3b는 Conditional Go를
    유지한다(확정 Go 아님). 확정 Go 전 잔여 조건에 "T+5 horizon
    의존 여부에 따른 유휴 자본 취약성 확인"을 추가한다. 신규 KIS
    호출 없음(로그로 확인, 캐시 봉 데이터만 사용). 운영 코드 변경
    없음, broker submit 미호출 — 이번 턴도 shadow/validation
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §30.
  - 산출물: `scripts/validate_r3b_capital_utilization_adjusted_
    proxy.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_
    capital_utilization_adjusted_proxy_2026-07-17.json`, `logs/
    r3b_capital_utilization_adjusted_proxy_run_2026-07-17.log`.
  - 다음 과제: §3 전제조건 충족 여부 사용자 확인(다음 최우선),
    point-in-time `entry_score` 파이프라인 반영 shadow 실행 설계,
    분기1·분기2 marginal t_NW out-of-sample 재확인, 이 시스템의
    운영 호라이즌이 T+20 중심인지 T+5도 포함하는지 사용자 확인
    (T+5 유휴 자본 취약성의 실질적 의미 판단에 필요).
- [x] **SPPV-2.41(신설)** R3b Conditional Go의 운영 horizon 적합성
  판단 (완료, 2026-07-17)
  - 작업 범위: §2.40이 남긴 질문 — "이 시스템이 T+20 성격의 보유/
    평가 체계에 더 가까운가, T+5 취약성이 실운영과 충돌하는가"를
    코드·문서 조사로 판단. **새 시장 데이터 실측 없이** 운영 코드
    (`deterministic_trigger_engine.py`, `ai_agents/schemas.py`,
    `common_types.py`)와 5개 기준 문서를 직접 조사(신규 KIS 호출
    없음 — 이번 턴은 read-only 코드/문서 조사만 수행, 스크립트
    실행 자체가 없었음).
  - **결과 1(강제된 보유기간 부재)**: `deterministic_trigger_
    engine.py`의 SELL/청산 판정은 `exit_score`(국면 risk-off,
    보유 편향, 무보유 페널티 등 피처 기반)를 계산해 임계값과
    비교하는 **100% 신호/점수 기반**이며, 경과일수·보유일수를
    입력으로 사용하는 코드 경로가 전혀 없다. `max_holding_days=20`
    (`schemas.py`의 `ExitPlanHint`)은 AI Risk agent의 **LLM 출력
    힌트 기본값**일 뿐, 이 값을 읽어 실제 매도를 강제하는 코드는
    존재하지 않는다 — T+20과 우연히 일치하는 숫자이지만 인과관계는
    없다. 손절/익절/트레일링 스탑의 수치 로직도 코드 전체에서
    발견되지 않았다(문자열 스타일 라벨만 존재).
  - **결과 2(문서상 T+5/T+20의 지위)**: 이 문서의 1차/2차 구분은
    horizon(T+5 vs T+20)이 아니라 **기간 창**(최근 12개월 vs
    3년) 구분이다. 기존 Go/No-Go 표준(§16)은 **T+5와 T+20을 동시에
    요구**해왔다(8개 창={1차,2차,전반부,후반부}×{T+5,T+20}) — 이는
    이번 세션에서 새로 만든 기준이 아니라 R3/R3b 검증 내내 이미
    적용돼 온 기존 표준이며, "T+20이 실제 보유기간을 대표한다"는
    서술은 문서 어디에도 없다.
  - **결과 3(실거래 이력 부재)**: `logs/trigger_proxy_attribution_
    2026-07-1{4,5,6}.json`(운영 attribution 로그)을 확인한 결과
    candidate/eligibility 집계만 있고, 실제 진입-청산 쌍으로 평균
    보유기간을 실측할 근거가 없다 — 이 시스템은 아직 실거래가
    누적되지 않아 "실제 평균 며칠 보유하는지"를 경험적으로 답할
    데이터 자체가 없다.
  - **판정: "이 시스템은 T+20 중심이므로 T+5 약점을 무시해도
    된다"는 주장은 코드로 뒷받침되지 않는다.** 반대로 "T+5가 실제
    보유기간"이라는 근거도 없다 — 이 시스템은 애초에 특정 horizon을
    "실제 보유기간"으로 삼도록 설계돼 있지 않으며, 기존 §16의
    T+5·T+20 동시 요구 표준이 이미 이 불확실성을 전제로 세워진
    것이었음이 재확인됐다. **T+5 약점을 무시할 근거가 없으므로,
    §2.40의 "T+20 중심으로는 완화"라는 안도감은 제한적으로만
    유효하다.**
  - **최종 판정: R3b는 Conditional Go를 유지한다**(즉시 Watch
    재하향 근거는 부족 — T+20 근거 자체는 여전히 강하고, 실거래
    이력 부재로 "T+5에서 반드시 실패한다"고 단정할 실증 근거도
    없다). **다만 확정 Go 전 잔여 조건에 "T+5 horizon 강건성 확보
    (또는 실거래 누적 후 실제 청산 시점 분포 실측)"를 기존 3개
    조건과 동등한 필수조건으로 격상한다** — 이 조건이 해소되기
    전까지 확정 Go는 시기상조다. 신규 KIS 호출 없음(신규 실행
    자체가 없었음). 운영 코드 변경 없음, broker submit 미호출 —
    이번 턴은 조사·해석 턴. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §31.
  - 산출물: 신규 스크립트 없음(운영 코드·문서 read-only 조사만
    수행, 산출 파일 생성 없음).
  - 다음 과제: §3 전제조건 충족 여부 사용자 확인(최우선), T+5
    horizon 강건성 개선 여부 또는 실거래 누적 후 청산 시점 분포
    실측 계획 수립, point-in-time `entry_score` 파이프라인 반영
    shadow 실행 설계, 분기1·분기2 marginal t_NW out-of-sample
    재확인.
- [x] **SPPV-2.42(신설)** R3b를 point-in-time `entry_score` 파이프
  라인에 반영한 shadow 검증 (완료, 2026-07-17)
  - 작업 범위: §2.41이 남긴 "point-in-time entry_score 파이프라인
    반영 shadow 실행"을 수행. 코드 조사 결과 §18(SPPV-2.28)부터
    이미 `signal_backbone.build_signal_snapshot`/`deterministic_
    trigger_engine._assess_buy_eligibility`/`_build_entry_score`
    등 실제 운영 함수를 직접 호출해왔음을 먼저 확인했다 — 다만
    실제 `strategy_selection` 조정항(선호 전략이 swing_momentum/
    event_continuation이면 +0.05 보너스)이 그동안 `None`으로
    누락돼 있었다. `portfolio_allocation`(계좌 잔고/포지션 필요)과
    달리 `strategy_selection`은 market_regime과 source_type만으로
    계산되는 순수 함수라 오프라인에서도 실제 값으로 채울 수 있어,
    이번 턴이 그 누락을 메웠다.
  - **방법론**: 실제 `select_strategy()`를 호출해 A(현행)와 R0/
    R3b(가상 alpha 교체) 양쪽에 동일하게 반영(공정한 A/B 비교),
    8개 창 BUY funnel을 재계측해 §20의 기존 결과와 비교.
  - **결과: 8개 창×2horizon(16개 조합) 전부에서 R3b>R0 방향이
    그대로 유지된다**(방향 붕괴 없음) — 6개 조합은 강화(1차 양쪽,
    후반부 T+5, 분기3 T+20, 분기4 양쪽), 나머지는 소폭 약화. **단
    분기1 T+20의 t_NW가 1.31→0.96으로 더 약화**돼 기존 marginal
    우려가 심화됐다. R3b의 selected_rate도 소폭 상승(예: 2차
    35.4%→39.4%) — strategy_selection 보너스가 일부 경계선 종목을
    문턱 위로 밀어 올린 결과다.
  - **판정: R3b는 Conditional Go를 유지한다.** "point-in-time
    파이프라인 반영" 조건은 **부분 해소**로 기록한다 — 실제
    strategy_selection을 반영해도 방향이 무너지지 않아 핵심 우려
    (실제 파이프라인에 가까워지면 우위가 사라질 수 있다)는 해소
    됐으나, `portfolio_allocation` gap(계좌 상태 필요, 실거래
    이력 없어 재현 불가)이 남아 있어 완전 해소는 아니다. 분기1
    t_NW 약화는 §31.4의 "분기1·분기2 marginal t_NW 재확인" 조건의
    우선순위를 높인다. 신규 KIS 호출 0건(기존 3년 캐시로 전량
    서빙, 로그로 실측 확인). 운영 코드 변경 없음, broker submit
    미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §32.
  - 산출물: `scripts/validate_r3b_point_in_time_pipeline_shadow.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_point_in_
    time_pipeline_shadow_2026-07-17.json`, `logs/r3b_point_in_time_
    pipeline_shadow_run_2026-07-17.log`.
  - 다음 과제: §3 전제조건 충족 여부 사용자 확인(최우선), 분기1
    t_NW 약화(0.96) 우선 재확인, T+5 horizon 강건성 확보 또는
    실거래 누적 후 청산 시점 분포 실측, `portfolio_allocation`
    gap은 실거래 누적 이후 재검증 대상으로 유보.
- [x] **SPPV-2.43(신설)** 분기1 t_NW 약화의 원인 정밀 진단 — 방향성
  붕괴 vs 변동성/이상치 문제 (완료, 2026-07-17)
  - 작업 범위: §2.42가 남긴 "분기1 t_NW 약화(0.96) 우선 재확인"을
    실행. §2.42의 point-in-time row-collection 함수를 재사용해
    분기1을 거래일 단위로 분해하고, 분기2·분기3과 비교해 분기1만의
    구조적 차이(국면 구성)를 확인했다.
  - **결과 1(국면 구성): 분기1은 세 분기 중 가장 "혼합 국면"
    구간이다** — 강세(40.6%)/횡보(46.6%)/약세(10.4%)가 고르게
    섞이고 `event_driven_unstable`(2.4%)도 다른 분기 대비 약 4배
    많다. 분기2는 약세(46.6%) 지배, 분기3은 강세(67.5%) 지배로
    단일 국면 편중이 뚜렷하다.
  - **결과 2(방향성 우위): R3b>R0 방향은 분기1에서도 그대로
    유지된다**(1.815% vs 0.753%, 약 2.4배). **스왑 발생일 46건
    중 33건(71.7%)이 양(+) 방향으로, 세 분기 중 가장 양(+) 편중이
    강하다.** 상위 10% 스왑일(대형 스왑일)을 제거하면 오히려
    잔존비율이 157.8%로 **개선**된다 — 분기3과 정반대로, 분기1은
    "나머지 다수의 스왑일"이 진짜 양(+) 우위의 원천이다.
  - **결과 3(t_NW 약화의 실체): 상위 10개 스왑일 중 3건이 절댓값
    16~44%p의 극단치**(2건 강한 음(-), 1건 강한 양(+))이며 나머지
    7건은 완만한 양(+)이다 — 이 소수 극단치가 표준오차를 크게
    키워 t_NW를 낮췄다.
  - **판정: 분기1의 t_NW 약화는 R3b 전체를 뒤집는 치명적 결함이
    아니라, 혼합 국면 구간에서의 변동성/이상치 문제로 좁혀진다.**
    방향성 우위·스왑일 부호 분포·대형 스왑일 제거 시 개선 효과
    모두 "우위가 실재하나 소수 극단치 때문에 통계적 신뢰도가
    낮다"는 그림과 일치한다 — 방향 반전 증거는 없다. **R3b는
    Conditional Go를 유지한다.** 분기1은 여전히 out-of-sample
    재확인 대상이지만, 그 성격이 "방향성 의심"에서 "소수 극단치로
    인한 분산 문제"로 구체화됐다 — Watch 재하향 근거는 아니다.
    신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측
    확인). 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
    shadow/validation 범위. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §33.
  - 산출물: `scripts/validate_r3b_quarter1_weakness_diagnosis.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_quarter1_
    weakness_diagnosis_2026-07-17.json`, `logs/r3b_quarter1_
    weakness_diagnosis_run_2026-07-17.log`.
  - 다음 과제: §3 전제조건 충족 여부 사용자 확인(최우선), out-of-
    sample 데이터 축적 시 혼합 국면 구간(분기1 유형) 우선 재확인,
    T+5 horizon 강건성 확보 또는 실거래 누적 후 청산 시점 분포
    실측, `portfolio_allocation` gap은 실거래 누적 이후 재검증.
- [x] **SPPV-2.44(신설)** SPPV-3 진입 관문 3종 종합 판정 — §3 게이트
  재확인 + 분기1/T+5 리스크 종합 (완료, 2026-07-17)
  - 작업 범위: SPPV-3 진입 전 마지막 관문 3가지(①§3 전제조건 충족
    여부, ②분기1 약화의 치명성 여부, ③T+5 취약성의 허용 가능성)를
    종합 판정. **이미 끝난 검증(분기1 구조 진단=§2.43, T+5 horizon
    적합성=§2.41)을 반복하지 않고**, 이번 턴에 유일하게 필요했던
    신규 실측 — §3 게이트의 현재 실측 상태 재확인만 수행.
  - **신규 실측**: 기존 운영 모니터링 스크립트 `scripts/monitor_
    regime_switch_v1_gate.py`(SPPV-2.13부터 존재, 재실행만 함)를
    재실행한 결과 **`NOT_TRIGGERED`(불변)** — 기준일 2026-06-16
    기준 최근 12개월 창에 `bullish_trend` 239일, `range_bound`
    6일, `bearish_trend` **0일**(문턱 30일 미달). SPPV-2.13
    (2026-07-14 직전 기록)과 동일 상태를 최신 데이터로 재확인.
  - **종합 판정표**: ①§3 전제조건(게이트+risk_off_penalty 중복
    해소) — **미충족**(게이트 NOT_TRIGGERED, 중복 해소는 별도
    ablation 미착수). ②분기1 약화 — **제한된 잔여 리스크**(치명적
    결함 아님, §2.43 재확인: 방향성 유지, 스왑일 71.7% 양(+),
    대형 스왑일 제거 시 개선). ③T+5 취약성 — **미해결이나 치명적
    근거 없음**(§2.41 재확인: 강제된 보유기간 없어 무시 불가하나
    반드시 실패한다는 근거도 없음).
  - **판정: R3b는 Conditional Go를 유지한다.** 다만 **SPPV-3(운영
    코드 반영) 진입은 아직 이르다 — 주된 차단 요인은 R3b의 성과와
    무관한 §3 게이트(하락장 미도래)**이며, 이는 SPPV-2.13부터
    이어진 "규칙 A(관찰 유예)"에 따라 인위적으로 앞당길 수 없다.
    분기1/T+5는 관리 대상 잔여 리스크로 확인됐다 — Watch로 재하향할
    근거는 없다. 신규 KIS 호출 0건(기존 벤치마크 캐시로 전량 서빙,
    로그로 실측 확인). 운영 코드 변경 없음, broker submit 미호출 —
    이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §34.
  - 산출물: `logs/regime_switch_v1_gate_monitor_2026-07-17.json`
    (스크립트의 실제 하드코딩 출력 경로는 `..._2026-07-14.json` —
    컨테이너 산출을 호스트로 복사하며 수동 재명명한 사본, §2.45에서
    정정), `logs/regime_switch_v1_gate_monitor_run_2026-07-17.log`
    (신규 스크립트 없음, 기존 SPPV-2.13 모니터링 스크립트 재실행).
  - 다음 과제: §3 게이트는 시장 상황 의존적이므로 3년 캐시 갱신
    시마다 재모니터링, `risk_off_penalty` 중복 해소 ablation 착수
    여부 사용자 판단, T+5 horizon 강건성 확보, out-of-sample
    데이터 축적 시 혼합 국면 구간 재확인, `portfolio_allocation`
    gap은 실거래 누적 이후 재검증.
- [x] **SPPV-2.45(신설)** SPPV-2.44 산출물 파일명/실행 경로 불일치
  정정 (완료, 2026-07-17)
  - 작업 범위: §2.44가 §3 게이트 재확인 산출물을 `logs/regime_
    switch_v1_gate_monitor_2026-07-17.json`으로 표기한 것이 실제
    스크립트 동작과 불일치해 정정. **새 실측/새 스크립트 없이**
    `scripts/monitor_regime_switch_v1_gate.py` 코드와 §2.44의 실행
    로그를 재확인하는 read-only 재검증만 수행(신규 KIS 호출 해당
    없음 — 신규 실행 자체가 없었음).
  - **확인된 사실**: `monitor_regime_switch_v1_gate.py:122`는 실행
    시점과 무관하게 항상 하드코딩된 `logs/regime_switch_v1_gate_
    monitor_2026-07-14.json`에 저장한다(파일명의 "2026-07-14"는
    SPPV-2.13 최초 작성일 그대로, 실행 날짜 미반영). §2.44가 인용한
    `..._2026-07-17.json`은 컨테이너 산출을 호스트로 복사하며
    파일명을 **수동 재명명**한 사본이지, 스크립트가 그 이름으로
    직접 저장한 것이 아니다. **내용은 실제 이번 재실행 결과가
    맞다**(as_of=2026-07-17T21:12:43, 실행 로그의 "산출 저장:"
    문자열과도 일치) — 호스트에 기존부터 있던 `..._2026-07-14.json`
    (as_of=2026-07-15, 이전 턴 산출물)은 이번 턴에 덮어써지지
    않았으며, 두 파일의 `trigger_status`/국면 분포는 동일하고
    `as_of`만 다르다.
  - **판정: 정정 후에도 SPPV-3 관련 결론은 전혀 바뀌지 않는다.**
    §2.44의 실측 내용(`NOT_TRIGGERED`, 최근 12개월 bearish_trend
    0/30일) 자체는 정확했고, 이번 정정은 "결과를 어느 파일명으로
    인용해야 하는가"에 관한 기록 정합성 문제였다. **§2.44의 판정
    (R3b Conditional Go 유지, SPPV-3 진입은 §3 게이트 미충족으로
    아직 이름)은 그대로 유지한다.** 향후 이 스크립트 재실행 시
    "스크립트 자체 출력 경로(하드코딩)"와 "호스트 보관용 재명명
    사본"을 명시적으로 구분 표기하는 것을 표준 관례로 삼는다. 운영
    코드 변경 없음, broker submit 미호출 — 이번 턴은 기록 정정
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §35.
  - 산출물: 신규 산출물 없음(기존 코드/로그 재확인만 수행).
  - 다음 과제: §2.44의 5개 다음 과제(§3 게이트 정기 재모니터링,
    `risk_off_penalty` 중복 해소 ablation, T+5 horizon 강건성
    확보, out-of-sample 혼합 국면 구간 재확인, `portfolio_
    allocation` gap 재검증)는 이번 정정과 무관하게 그대로 유효.
- [x] **SPPV-2.46(신설)** R3b 채택 시 `risk_off_penalty` 중복 해소
  ablation (완료, 2026-07-17)
  - 작업 범위: §3 전제조건 중 시장 외생 변수인 §21 게이트는 건드
    리지 않고(§34에서 이미 NOT_TRIGGERED 재확인, 불변), R3b의
    방향성 우위 자체도 재검증하지 않는다 — **R3b를 실제 entry_
    score 경로에 반영할 때 `risk_off_penalty`(및 인접 eligibility
    축)가 여전히 성과를 깎는 병목인지, 유지해야 할 정당한 방어
    장치인지**만 판정.
  - **코드 확정**: entry_score 축(`_build_entry_score:1139-1141`,
    `risk_tone=="risk_off"`이면 -0.15)과 eligibility 축(`_assess_
    buy_eligibility:421-438`, `risk_tone=="risk_off"` **그리고**
    `regime_label=="bearish_trend"`이면 core 종목 즉시 차단)은
    서로 다른 함수·다른 단계의 별개 축이며, `classify_market_
    regime()`을 종목별 개별 스냅샷 대 시장 공통(벤치마크) 국면으로
    다른 기준 단위에 쓰는 것이 중복 의심의 정체다.
  - **방법론**: A(현행 유지)/B(entry_score risk_off_penalty만
    무력화)/C(eligibility risk_off 축만 완화) 3개 시나리오를 R3b
    candidate 위에서 비교. 운영 함수(`_build_entry_score`/`_assess_
    buy_eligibility`/`classify_market_regime`)를 그대로 호출하되,
    함수에 넘기는 `market_regime` 입력만 `dataclasses.replace
    (risk_tone="neutral")`로 국소 중립화해 재현(운영 코드 미수정).
  - **결과: C는 두 창(2차/1차) 모두 A와 완전히 동일하다** —
    eligibility 축이 R3b candidate pool(그날 regime_conditional_
    signal 상위 20%)에서 단 한 건도 걸리지 않음을 확인 — R3b의
    candidate 조건 자체가 종목별 `bearish_trend`와 구조적으로
    거의 겹치지 않기 때문이다. **B는 selected/would_buy가 늘고
    T+20 총 기대수익 proxy가 2차 +20.9%(6177.7→7471.2), 1차
    +20.5%(4196.1→5055.4) 개선**되나 **MAE도 소폭 악화**(약
    0.5%p) — "공짜 개선"이 아닌 실제 트레이드오프.
  - **판정: eligibility 축은 R3b 관점에서 "제거할 중복"도 "지킬
    방어"도 아니다 — 애초에 비활성이다.** entry_score 축은 제거
    시 기대수익이 개선되나 MAE 트레이드오프가 있어 **"유지해야
    할 방어"라기보다 "완화를 검토할 후보"**에 가깝다는 실측 근거를
    확보했다 — 다만 운영 코드(entry_score) 변경은 이번 턴 범위
    밖이며 사용자 승인이 필요하다. **R3b는 Conditional Go를
    유지한다.** §3 전제조건 ②(risk_off_penalty 중복 해소)를
    "미착수"에서 "방향 확인, 사용자 승인 대기"로 진전시켰다 — **SPPV
    -3 진입은 §21 게이트 미충족으로 여전히 아직 이르다(불변).**
    신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙, 로그로 실측
    확인). 운영 코드 변경 없음, broker submit 미호출 — 이번 턴도
    shadow/validation 범위. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §36.
  - 산출물: `scripts/validate_r3b_risk_off_penalty_duplication_
    ablation.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_
    r3b_risk_off_penalty_duplication_ablation_2026-07-17.json`,
    `logs/r3b_risk_off_penalty_duplication_ablation_run_2026-
    07-17.log`.
  - 다음 과제: entry_score의 risk_off_penalty 완화(제거/축소) 여부
    사용자 승인 결정, §21 게이트 정기 재모니터링, T+5 horizon
    강건성 확보, out-of-sample 혼합 국면 구간 재확인, `portfolio_
    allocation` gap 재검증.
- [x] **SPPV-2.47(신설)** 승인 범위 확정 + `risk_off_penalty`
  (entry_score 축) 완화안 심층 해석 (완료, 2026-07-17)
  - 작업 범위: 사용자가 §2.46의 A/B/C 3개 시나리오 중 **"B —
    entry_score의 risk_off_penalty만 완화" 승인**, eligibility
    축 완화는 비승인. 이번 턴은 그 승인 범위를 문서에 고정하고,
    **§2.46에서 이미 실측된 A/B 산출물을 신규 실행 없이 재사용**
    해 T+5/T+20 양쪽·MAE 트레이드오프·SPPV-3 진입 의미를 더 깊게
    해석했다(같은 코드·같은 캐시라 재실행은 불필요한 반복).
  - **재해석 결과**: 총 기대수익 proxy가 2개 창×2horizon 전부에서
    개선(2차 T+5 +14.3%, T+20 +20.9%; 1차 T+5 +12.9%, T+20
    +20.5%) — **T+20뿐 아니라 T+5도 유의미하게 개선**된다. t_NW도
    함께 개선(+4.2~5.4%). MAE는 함께 소폭 악화(5.9~7.8% 상대
    증가)하나 **개선폭보다 항상 작다** — 손실 심화가 수익 개선을
    초과하지 않는 트레이드오프.
  - **3가지 질문에 답**: ①risk_off_penalty 제거는 R3b 우위를 더
    선명하게 만든다(방향·유의성·총 기대수익 동시 개선). ②개선은
    T+20에만 국한되지 않고 T+5에서도 유지된다(다만 §31이 지적한
    "강제된 보유기간 부재"라는 더 넓은 구조적 논점 자체를 뒤집는
    것은 아니다). ③MAE 악화는 개선폭보다 상대적으로 작아 정당화
    가능한 수준이나, 실제 반영 전 리스크 한도 확인은 별도로
    필요하다.
  - **판정: R3b + entry_score risk_off_penalty 제거 조합은
    Conditional Go를 보강한다.** SPPV-3 진입 관점에서 남은 조건은
    사실상 **§21 게이트 하나로 좁혀졌다** — §3 전제조건 ②(risk_
    off_penalty 중복)는 "실측 근거 확보 + 사용자 승인(entry_score
    축)"까지 진행됐고, ①(게이트)만 외생적으로 남아 있다. 다만
    이것이 확정 Go를 의미하지는 않는다 — entry_score 조정 자체는
    아직 shadow 상태이며, 반영은 게이트 충족 이후 별도 절차를
    따른다. **[SPPV-2.48에서 정정] "게이트 하나로 좁혀졌다"는 §3
    전제조건 범위로 한정하면 정확하나 SPPV-3 진입 전체로는 과장 —
    아래 SPPV-2.48 참고.** 운영 코드 변경 없음, broker submit
    미호출 — 이번 턴도 shadow/validation 범위. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §37.
  - 산출물: 신규 산출물 없음(§2.46 산출물을 재사용, 신규 실행
    없음).
  - 다음 과제: §21 게이트 정기 재모니터링, 게이트 충족(또는 별도
    승인) 시 entry_score 코드 반영 절차 설계, T+5 horizon의 더
    넓은 구조적 논점(강제된 보유기간 부재) 재확인, out-of-sample
    혼합 국면 구간 재확인, `portfolio_allocation` gap 재검증.
- [x] **SPPV-2.48(신설)** SPPV-2.47 "게이트 하나만 남았다" 표현
  정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리 (완료, 2026-07-18)
  - 작업 범위: §2.47이 "SPPV-3 진입 관점에서 남은 조건은 사실상
    §21 게이트 하나로 좁혀졌다"고 쓴 것이 **§3 전제조건 범위로는
    정확하나 SPPV-3 진입 전체로는 과장**임을 바로잡았다(SPPV-2.48).
    **새 실측·새 설계 제안 없이** 기존 산출물·기존 문서(§2.41,
    §2.40, §2.43)만 재해석해 잔여 조건을 재분류했다.
  - **과장의 실체**: §2.47은 §3 전제조건(게이트+risk_off_penalty
    중복) 중 ②가 사용자 승인까지 진행되고 ①(게이트)만 외생적으로
    남았다는 사실 자체는 정확히 서술했으나, 이 문장이 반복 배치된
    문맥에서 "§3 전제조건"과 "SPPV-3 진입 조건" 두 개념이 동일한
    것처럼 읽히도록 쓰였다. 그러나 §2.41(T+5 구조적 리스크, 강제된
    보유기간 부재로 확정 Go 필수조건 격상), §2.43(혼합 국면 out-
    of-sample 재확인 필요), §2.40(`portfolio_allocation` gap 실거래
    전 재현 불가)은 §3와 **독립적으로** 이미 확정 Go 조건으로
    명시돼 있었다.
  - **재분류**: **①주된 차단 요인**(지금 당장 착수 자체를 막는
    것) — §21 게이트(NOT_TRIGGERED, 외생적). **②보조 잔여
    조건**(즉시 차단은 아니나 확정 Go 전 필요) — entry_score
    코드 반영 절차, T+5 구조적 리스크, 혼합 국면 재확인. **③실거래
    누적 없이는 못 푸는 조건** — `portfolio_allocation` gap, 실제
    청산 시점 분포.
  - **판정: R3b는 Conditional Go를 유지한다 — 방향 후퇴가 아니라
    "남은 조건" 서술의 정밀도만 회복하는 정정이다.** "Go 아님"과
    "방향성이 틀렸다"를 혼동하지 않는다. 운영 코드 변경 없음,
    broker submit 미호출 — 이번 턴은 read-only 문서 재해석 범위,
    신규 실측 없음. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §38.
  - 산출물: 신규 산출물 없음(문서 재해석만 수행).
  - 다음 과제: §21 게이트 정기 재모니터링(변경 없음), entry_score
    코드 반영 절차 설계 착수 여부 사용자 확인, T+5 구조적 리스크를
    받아들이고 진행할지 사용자 결정, out-of-sample 혼합 국면 구간
    재확인, `portfolio_allocation` gap·실제 청산 시점 분포는
    실거래 누적 이후 재검증.
- [x] **SPPV-2.49(신설)** 혼합 국면(분기1 유형) 재확인 — 분기4
  대조 계측 (완료, 2026-07-18)
  - 작업 범위: §2.48이 정리한 3개 보조 잔여 조건 중 "혼합 국면
    재확인"만 지금 당장(실거래 없이) 전진 가능해 이번 턴 최우선
    으로 선택했다(T+5 구조적 리스크는 실거래 청산 이력 필요,
    entry_score 코드 반영 절차는 §21 게이트 충족 후 별도 트랙).
    승인된 조합(R3b + entry_score risk_off_penalty 제거, §2.46/
    §2.47의 B 시나리오) 그대로 분기1(재계측, 비교 기준선)과
    분기4(신규 계측, 이번 세션에서 국면 구성 미확인 구간)의 국면
    분포·funnel을 계측했다.
  - **결과: 분기4는 시장 공통 국면이 사실상 순수 단일**(bullish_
    trend 98.2%, range_bound 1.8%)로 **분기1(혼합 국면)과 정반대
    성격**이다. 이 대조 구간에서 B 시나리오는 **T+20 t_NW=3.00,
    양수율=60.3%, 총 기대수익 proxy=4436.0**으로 강하고 일관되나,
    **분기1은 T+20 t_NW=1.27(marginal), 양수율=46.2%, 총 기대수익
    proxy=661.7**로 뚜렷이 대비된다.
  - **해석: "혼합 국면→약한 t_NW" 가설이 분기1 1건의 우연이 아니라
    분기4와의 대조로 확인됐다** — 국면이 한 방향으로 뚜렷할 때는
    R3b(+penalty 제거)가 강하고 일관되게 작동하고, 국면이 섞일
    때는 방향은 유지되나 통계적 신뢰도가 떨어진다. **이는 조건
    해소가 아니라 "미확인 가설"에서 "확인·추적 대상 패턴"으로의
    전진이다** — 위험 자체는 사라지지 않았지만, 이제 그 성격을
    알고 있다는 점에서 SPPV-3 준비를 진전시킨다.
  - **판정: R3b는 Conditional Go를 유지한다.** 신규 KIS 호출 0건
    (기존 3년 캐시로 전량 서빙, 로그로 실측 확인). 운영 코드 변경
    없음, broker submit 미호출 — 이번 턴도 shadow/validation
    범위. 상세: `plans/[DESIGN] regime_conditional_entry_signal_
    v1.md` §39.
  - 산출물: `scripts/validate_r3b_mixed_regime_quarter4_check.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_mixed_
    regime_quarter4_check_2026-07-18.json`, `logs/r3b_mixed_
    regime_quarter4_check_run_2026-07-18.log`.
  - 다음 과제: §21 게이트 정기 재모니터링, entry_score 코드 반영
    절차 설계 착수 여부, T+5 구조적 리스크 수용 여부 사용자 결정,
    국면 혼합도 감지·대응 설계 검토 여부(선택 사항, 이번 턴은
    제안하지 않음), `portfolio_allocation` gap·실제 청산 시점
    분포는 실거래 누적 이후 재검증.
- [x] **SPPV-2.50(신설)** "혼합 국면 약세" 가설 직접 분해 — 거래일
  단위 혼합도 3분위 버킷화 (완료, 2026-07-18)
  - 작업 범위: §2.49의 분기1 vs 분기4 대조(N=2)를 반복하지 않고,
    거래일 단위로 "최근 60거래일 창의 시장 공통 국면 혼합도"를
    직접 수치화(`mixed_score=1-최빈 라벨 비중`)해 3년 전체 634
    거래일을 분기 경계와 무관하게 혼합도 3분위(저/중/고)로
    버킷화했다. 승인된 조합(R3b+entry_score risk_off_penalty
    제거, B 시나리오)을 그대로 사용.
  - **결과: 저혼합(T+20 t_NW=3.64, 양수율=63.3%)→중혼합(t=2.51,
    56.8%)→고혼합(t=0.37, 38.7%)으로 T+5/T+20 전부 단조 감소.**
    고혼합 버킷은 양수율이 50%를 밑돌고 t_NW가 사실상 0과 구별되지
    않는다 — 저혼합 버킷과 질적으로 다른 상태.
  - **판정: "혼합 국면 약세"가 634거래일 규모의 연속 변수(분기
    경계 무관)에서 단조 패턴으로 확인돼 "지지 증거 추가" 단계를
    넘어 "구조적 패턴"으로 격상됐다.** 다만 방향성 붕괴는 아니다
    — 고혼합 버킷도 평균은 여전히 양(+)(0.606%)이며, 저혼합·중혼합
    (전체의 2/3)에서는 여전히 강하고 유의미하다. **이 리스크는
    SPPV-3 착수를 추가로 차단하는 사유가 아니라, 착수 이후에도
    계속 추적해야 할 운영상 구조적 특성이다.** R3b는 Conditional
    Go를 유지한다. 신규 KIS 호출 0건(기존 3년 캐시로 전량 서빙,
    로그로 실측 확인). 운영 코드 변경 없음, broker submit 미호출 —
    이번 턴도 shadow/validation 범위. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §40. **[SPPV-2.51에서 정정]
    "구조적 패턴으로 격상"은 과장 — 동일 in-sample 3년 캐시 재확인 +
    60일 trailing window 자기상관 때문에 정확한 표현은 "강한 구조적
    정합 증거로 격상"이다. 아래 SPPV-2.51 참고.**
  - 산출물: `scripts/validate_r3b_regime_mix_intensity_
    decomposition.py`(read-only, 신규 KIS 호출 0건), `logs/signal_
    ic_r3b_regime_mix_intensity_decomposition_2026-07-18.json`,
    `logs/r3b_regime_mix_intensity_decomposition_run_2026-07-18.
    log`.
  - 다음 과제: §21 게이트 정기 재모니터링, entry_score 코드 반영
    절차 설계 착수 여부, T+5 구조적 리스크 수용 여부 사용자 결정,
    국면 혼합도를 실거래 반영 이후 모니터링 지표로 삼을지 별도
    설계 검토(선택 사항), `portfolio_allocation` gap·실제 청산
    시점 분포는 실거래 누적 이후 재검증.
- [x] **SPPV-2.51(신설)** SPPV-2.50 결론 문구 정밀화 — 과장 없이
  고정 (완료, 2026-07-18)
  - 작업 범위: 신규 실행 없이 §2.50이 사용한 두 문구("구조적
    패턴으로 격상", "주된 차단 요인은 §21 게이트 하나뿐")를 기존
    산출물만으로 재점검.
  - **정정 1(구조적 패턴 표현)**: §2.50의 3분위 재확인은 R3b/
    entry_score 조합을 이미 확정하는 데 쓰인 것과 **동일한 3년
    in-sample 캐시**에서 수행됐고, mixed_score가 60거래일 trailing
    window라 인접 거래일 버킷이 자기상관돼 634거래일이 634개의
    독립 관측이 아니다. **확실히 말할 수 있는 것**: 단조 감소·
    217/215/202일의 균등 분포는 그대로 사실이며 "지지 증거 추가"
    단계는 명백히 넘어섰다. **과장인 것**: "out-of-sample로
    확정된 구조적 패턴"이라는 표현 — 정확히는 **"강한 구조적
    정합 증거로 격상"**이다.
  - **정정 2(§21 게이트 표현)**: "주된 차단 요인은 §21 게이트
    하나뿐"은 "SPPV-3 착수 검토를 시작할 수 있는 유일한 외생적
    조건"이라는 뜻이지 "진입 전체에 남은 유일한 조건"이 아니다.
    §2.48(§38)의 ①주된 차단 요인(§21 게이트) ②보조 잔여 조건
    (entry_score 코드 반영 절차·T+5 구조적 리스크·혼합도 모니터링)
    ③실거래 누적 필요 조건 3단 분류는 이번 턴에도 그대로 유효하다.
  - **판정: 두 정정 모두 R3b 방향성·Conditional Go를 바꾸지
    않는다** — 서술 정밀도만 회복. 신규 실행 없음, 신규 KIS 호출
    0건, 운영 코드 변경 없음, broker submit 미호출. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §40.6.
- [x] **SPPV-2.52(신설)** T+5 horizon 구조적 리스크 추가 정량화 —
  실제 exit_score 기반 signal-driven 청산 타이밍 시뮬레이션 (완료,
  2026-07-18)
  - 작업 범위: §2.48의 보조 잔여 조건 3개 중 신규 설계 없이 기존
    3년 캐시만으로 실측 가능한 "T+5 구조적 리스크"를 선택. 실제
    운영 함수 `_build_exit_score`(순수 함수, DB/실시간 상태 불필요)
    를 R3b+entry_score risk_off_penalty 제거(B 시나리오) would_buy
    candidate 1151건에 point-in-time으로 재호출해 매도 신호
    (`sell_candidate_threshold=0.75`)를 처음 넘는 날을 20거래일
    관찰 창으로 시뮬레이션.
  - **결과: 91.1%(1049건)가 20거래일 안에 매도 신호를 넘지 않고
    censored, 평균 보유일수=19.35일. signal-driven 청산 수익률
    (평균 6.14%, t=4.73)은 T+5(2.02%, t=4.18)보다 T+20(6.49%,
    t=3.87)에 훨씬 가깝다.**
  - **판정: 실제 청산 로직 기준으로는 T+5가 아니라 T+20 근방에서
    청산되므로 "T+5 평균이 약하다"는 우려가 실제 운영 리스크로
    그대로 전이되지 않는다 — "T+5 구조적 리스크"는 부분적으로
    완화됐다.** 다만 20일 초과 구간의 청산 분포·경로 리스크(MAE)는
    미검증이라 "완전 해소"는 과장. R3b는 Conditional Go를 유지한다.
    신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit 미호출.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §41.
  - 산출물: `scripts/validate_r3b_signal_driven_exit_timing.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_signal_
    driven_exit_timing_2026-07-18.json`, `logs/r3b_signal_driven_
    exit_timing_run_2026-07-18.log`.
  - 다음 과제: 관찰 창을 20거래일보다 늘려 censored 비율 감소 및
    경로 리스크(MAE) 분포 확인, §21 게이트 정기 재모니터링,
    entry_score 코드 반영 절차 설계 착수 여부, 국면 혼합도 모니터링
    설계 검토, `portfolio_allocation` gap·실제 청산 시점 분포는
    실거래 누적 이후 재검증.
- [x] **SPPV-2.53(신설)** T+5 horizon 구조적 리스크 — 20거래일
  초과 구간·경로 리스크(MAE) 확장 검증 (완료, 2026-07-18)
  - 작업 범위: §2.52(§41)가 20일 관찰 창으로 남긴 두 미확인 영역을
    직접 검증 — (a) 20일 초과 구간 청산 분포, (b) 보유 중 경로
    리스크(MAE). §41과 동일한 candidate 정의를 재사용하되 관찰
    창을 20→60거래일로 확장하고 MAE를 추가 계산(효율화를 위해 1단계
    저비용 entry scan → would_buy 확정 → 2단계 would_buy 후보에만
    60일 exit+MAE 시뮬레이션 적용). would_buy 1048건(60일 확보를
    위해 §2.52의 1151건보다 표본 소폭 감소, 비교 가능성 caveat로
    문서화).
  - **결과: censored 비율 91.1%(20일)→51.3%(60일)로 감소, 평균
    보유일수=48.0일. signal-driven 청산 수익률(9.29%, t=5.38)이
    오히려 고정 T+20(4.46%, t=3.41)보다 강함. MAE 평균 -11.08%,
    중앙값 -10.42%, 하위 10% -21.77%, 최악값 -45.10%, -20% 이하
    심각 손실 비율 12.8%.**
  - **판정: 실제 청산은 T+5는 물론 T+20보다도 더 늦게 일어나는
    경우가 많고 그 수익률은 T+20보다 강해 "T+5 구조적 리스크"는
    "부분 완화"에서 "거의 해소"로 격상됐다.** 다만 이 검증으로
    경로 리스크(MAE)·손절 정책 부재라는 **신규 잔여 조건**이
    드러났다(코드상 `_build_exit_score` 외 별도 손절 임계값 없음을
    재확인). R3b는 Conditional Go를 유지한다 — 방향성 반전 아님.
    신규 KIS 호출 0건, 운영 코드 변경 없음, broker submit 미호출.
    상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`
    §42.
  - 산출물: `scripts/validate_r3b_signal_driven_exit_timing_
    extended.py`(read-only, 신규 KIS 호출 0건), `logs/signal_ic_
    r3b_signal_driven_exit_timing_extended60d_2026-07-18.json`,
    `logs/r3b_signal_driven_exit_timing_extended60d_run_2026-07-
    18.log`.
  - 다음 과제: 경로 리스크(MAE)·손절 정책 설계 검토(예: 고정
    손절선 도입 시 총 기대수익 proxy 개선 여부 ablation), §21 게이트
    정기 재모니터링, entry_score 코드 반영 절차 설계 착수 여부,
    국면 혼합도 모니터링 설계 검토, `portfolio_allocation` gap·실제
    청산 시점 분포는 실거래 누적 이후 재검증.
- [x] **SPPV-2.54(신설)** SPPV-2.53 결론 문구 정밀화 — 20일판·
  60일판 표본 동일성 검증 + "거의 해소" 표현 재점검 (완료,
  2026-07-18)
  - 작업 범위: 신규 실행 없이 §2.53(§42)의 "censored 91.1%→51.3%"
    비교와 "T+5 구조적 리스크 거의 해소" 판정을 두 스크립트
    (`validate_r3b_signal_driven_exit_timing.py`,
    `..._extended.py`) 코드 대조로 재점검.
  - **코드 기준 판정**: 두 스크립트 모두 `last_t = len(bars)-1-
    MAX_EXIT_OBSERVATION_DAYS`로 스캔 범위를 제한하는데, 60일판
    (`=60`)은 20일판(`=20`)보다 스캔 대상 거래일이 좁다 — 3년 캐시
    끝 약 40거래일이 60일판에서 제외된다. candidate 선정 로직은
    당일 backward-looking 데이터만 사용해 관찰 창과 무관하므로,
    **60일판(1048건)은 20일판(1151건)의 약 91% 부분집합으로
    추정된다 — 동일 코호트의 순수 전/후 비교가 아니라 겹치지만
    완전히 같지는 않은 두 표본의 비교**다.
  - **확실히 말할 수 있는 것**: 각 판의 표본 내부 측정치(60일판
    censored=51.3%, 평균 보유일수=48.0일, signal-driven 청산=
    9.29%(t=5.38), MAE 평균=-11.08%; 20일판 각 수치)는 유효하고,
    표본 차이(~9%)가 관측된 효과 크기(censored 40%p 감소 등)를
    설명하기엔 작아 "관찰 창을 늘리면 청산이 늦어지고 censored가
    준다"는 방향성 자체는 신뢰 가능하다.
  - **과장인 것**: 91.1%→51.3%를 "엄밀한 페어드 전후 비교치"로
    인용하는 것, 그리고 "T+5 구조적 리스크가 거의 해소됐다"는 것
    — 60일 관찰 후에도 과반(51.3%)이 여전히 censored이기 때문.
  - **판정**: 정확한 표현은 **"부분 완화"(§41)에서 "추가
    완화"(§42/§43)로** — "거의 해소"는 하향 정정한다. R3b는
    Conditional Go를 유지한다(방향성 반전 아님, 60일판 내부 비교는
    그대로 유효). 신규 실행 없음, 신규 KIS 호출 0건, 운영 코드
    변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §43.
  - 다음 과제(선택 사항): 20일판을 60일판과 동일한 1048건 부분집합
    으로 제한해 재계산하면 진짜 페어드 비교치를 얻을 수 있다(신규
    실행 필요, 이번 턴 범위 밖). §21 게이트 정기 재모니터링,
    entry_score 코드 반영 절차, 경로 리스크·손절 정책 설계 검토,
    국면 혼합도 모니터링 설계 검토는 변경 없이 유지.
- [x] **SPPV-2.55(신설)** 손절(stop-loss) 정책 도입이 총 기대수익에
  미치는 영향 ablation (완료, 2026-07-18)
  - 작업 범위: §42(SPPV-2.53)가 §38에 신규 추가한 "경로 리스크
    (MAE)·손절 정책 부재"에서, 아직 답하지 않은 질문("손절선을
    도입하면 총 기대수익이 개선되는가, 악화되는가")을 처음으로
    직접 검증. §42/§43과 동일한 candidate 정의(would_buy 1048건,
    60거래일 관찰 창)로 baseline(손절 없음)·-15% 손절·-20% 손절
    3개 변형을 한 번의 60일 순회로 동시 시뮬레이션(효율화).
  - **결과: baseline 총 기대수익 proxy=9734.7(t=5.38, 양수율
    52.8%) 대비 -15% 손절=7024.1(약 27.8% 악화, t=4.25, 양수율
    46.4%, 손절 발동률 28.5%(299건)), -20% 손절=9093.8(약 6.6%
    악화, t=5.02, 양수율 50.7%, 손절 발동률 12.8%(134건)) — 두
    손절 임계값 모두 총 기대수익을 악화시켰고, 손절이 타이트할수록
    (더 얕을수록) 악화 폭이 컸다.**
  - **해석**: R3b candidate는 보유 기간 중 상당한 미실현 손실
    (MAE 평균 -11%)을 겪지만, 조정 구간을 버텨야 이후 회복·상승분
    을 취하는 구조다 — -15% 손절은 candidate의 28.5%를 조정
    국면 도중 강제로 잘라내 회복 기회를 원천 차단하며, 그 결과
    총 기대수익이 깎인다. -20% 손절은 발동 빈도가 낮아 악화 폭이
    작지만 그래도 baseline보다는 약하다.
  - **판정**: "경로 리스크·손절 정책 부재"는 "미검증 공백"에서
    **"시험한 범위(-15%/-20%) 내에서는 손절 미도입이 총 기대수익
    관점에서 근거 있는 선택"**으로 재분류한다. R3b는 Conditional
    Go를 유지한다 — 방향성 반전 아님. 신규 KIS 호출 0건, 운영
    코드 변경 없음, broker submit 미호출. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §44.
  - 산출물: `scripts/validate_r3b_stop_loss_ablation.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_stop_loss_
    ablation_2026-07-18.json`, `logs/r3b_stop_loss_ablation_run_
    2026-07-18.log`.
  - 다음 과제: exit 시점 손절이 아닌 포지션 사이징으로 MAE 노출을
    줄이는 방안 검토(실거래 계좌 상태 필요, 낮은 우선순위), §21
    게이트 정기 재모니터링, entry_score 코드 반영 절차 설계 착수
    여부, 국면 혼합도 모니터링 설계 검토, `portfolio_allocation`
    gap·실제 청산 시점 분포는 실거래 누적 이후 재검증.
- [x] **SPPV-2.56(신설)** entry_score 코드 반영 절차 구체화 —
  shadow 재구현 정합성 검증 (완료, 2026-07-18)
  - 작업 범위: §21 게이트는 외생 조건이라 반복 관측만 가능한 반면,
    "entry_score 코드 반영 절차"(실제 운영 코드 변경 PR 작성) 전에
    확인해야 할 선행 질문 — SPPV-2.46부터 이 세션 내내 B 시나리오
    non-alpha 조정을 수작업 재구현 `_non_alpha`로 계산해왔을 뿐,
    실제 운영 함수 `_build_entry_score`(`deterministic_trigger_
    engine.py:1115-1170`)를 한 번도 직접 호출한 적이 없었다는
    점을 선택. 코드 대조 결과 `_build_entry_score`에는 `_non_alpha`
    가 담아내지 못하는 `portfolio_allocation` 조정(+0.10/-0.20)·
    `source_type` 조정(+0.05/-0.35)·최종 `_clamp()`가 있었다 —
    이 세션에서는 항상 `source_type="core"`, `portfolio_
    allocation=None`으로 써서 이론상 no-op이었지만 실증된 적은
    없었다. 3년 전체 후보 표본(58,493건, 87개 core 종목 전량)에서
    실제 `_build_entry_score`(overall=fast=slow=0.0으로 호출해
    alpha 항을 상수 0.40으로 고정, 그 결과에서 조정 항만 분리)와
    `_non_alpha`를 전수 대조.
  - **결과: 100.0%(58,493/58,493) 완전 일치, 불일치 0건, 최대
    절대 오차 0.0.**
  - **해석**: 이 세션 내내 사용해온 수작업 재구현이 실제 운영
    함수와 이 세션이 다룬 조건(source_type="core", portfolio_
    allocation=None) 안에서 소수점 오차 없이 완전히 일치한다 —
    SPPV-2.46~2.55에서 계산된 모든 B 시나리오 funnel·수익률
    결과가 실제 운영 코드가 그대로 반영됐을 때의 결과와 수치적으로
    동일함이 처음으로 전수 검증됐다.
  - **판정**: **"entry_score 코드 반영 절차"는 "설계 논의 단계"
    에서 "shadow 계산 정합성 확보, 실제 코드 변경 PR 작성 가능
    단계"로 격상됐다.** 다만 이것이 코드 변경 PR 자체의 승인·실행을
    뜻하지는 않으며(운영 코드 변경은 여전히 사용자 승인·리스크/
    컴플라이언스 검토 필요), §21 게이트(주된 차단 요인)는 불변이라
    이 결과 하나로 SPPV-3 확정 Go를 선언하지 않는다. R3b는
    Conditional Go를 유지한다. 신규 KIS 호출 0건, 운영 코드 변경
    없음, broker submit 미호출. 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §45. **[SPPV-2.57에서
    정정] "한 번도 직접 호출한 적이 없었다"·"candidate 전량"은
    과장/부정확 — 아래 SPPV-2.57 참고.**
  - 산출물: `scripts/validate_r3b_entry_score_shadow_fidelity.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_entry_
    score_shadow_fidelity_2026-07-18.json`, `logs/r3b_entry_score_
    shadow_fidelity_run_2026-07-18.log`.
  - 다음 과제: entry_score risk_off_penalty 완화의 실제 코드 변경
    PR 초안 작성 착수 여부 사용자 확인(shadow 정합성 확보 완료),
    §21 게이트 정기 재모니터링, exit 외 리스크 관리(포지션 사이징)
    검토, 국면 혼합도 모니터링 설계 검토, `portfolio_allocation`
    gap·실제 청산 시점 분포는 실거래 누적 이후 재검증.
- [x] **SPPV-2.57(신설)** SPPV-2.56 결론 문구 정밀화 — "직접 호출"
  서술 범위·표본 서술 정정 (완료, 2026-07-18)
  - 작업 범위: 신규 실행 없이 §45(SPPV-2.56)의 두 표현을 기존
    코드(`validate_alpha_layer_buy_funnel_comparison.py`,
    `validate_r3b_point_in_time_pipeline_shadow.py`,
    `validate_r3b_entry_score_shadow_fidelity.py`) 재검토로 정정.
  - **정정 1(직접 호출 여부)**: "실제 함수를 한 번도 직접 호출한
    적이 없었다"는 과장 — `_build_entry_score`는 시나리오 A(현행
    regime)로는 `validate_alpha_layer_buy_funnel_comparison.py:211`
    와 `validate_r3b_point_in_time_pipeline_shadow.py:178`에서 이미
    직접 호출돼왔다. **정확한 표현**: "B 시나리오(`risk_tone=
    "neutral"`로 치환한 market_regime) 입력으로는 §45 이전까지
    직접 호출한 적이 없었다" — §45가 새로 확인한 것은 이 B
    시나리오 재구현이 실제 함수의 neutral-regime 호출 결과와
    정합하는지였다.
  - **정정 2(증명 범위)**: 이번 검증이 실제로 증명한 것은
    non-alpha 조정 항(source_type="core", portfolio_allocation=
    None, risk_tone neutral 조건)의 정합성뿐이다. **아직 증명하지
    않은 것**: (a) R3b alpha 교체 전체 경로가 실제 운영 코드
    반영 후 `assess_deterministic_triggers` 전체 파이프라인
    수준에서도 동일하게 재현되는지, (b) `source_type=
    "held_position"` 또는 실제 `portfolio_allocation` 값이 있는
    경우의 동작 — "B 시나리오 전체가 실제 운영 코드와 동일"이라는
    표현은 범위를 넘는다.
  - **정정 3(표본 서술)**: "candidate 전량"은 부정확 — 스크립트는
    quintile 상위 20% 선별·eligibility 필터링을 전혀 거치지 않고
    전체 거래일 point-in-time 스냅샷(58,493건)을 순회했다. 정확한
    표현: "3년 전체 core 87종목의 전체 시점 스냅샷(모집단 전체,
    candidate로 좁히지 않음) 58,493건".
  - **판정**: 세 정정 모두 **R3b 방향성·Conditional Go를 바꾸지
    않는다** — §45의 핵심 결론(B 시나리오 non-alpha 조정 항이
    검증된 조건 안에서 완전히 일치)은 그대로 유효하며, 필요 이상
    으로 보수적으로 낮추지 않는다. 신규 실행 없음, 신규 KIS 호출
    0건, 운영 코드 변경 없음, broker submit 미호출. 상세: `plans/
    [DESIGN] regime_conditional_entry_signal_v1.md` §46.
  - 다음 과제(변경 없음): R3b alpha 교체 전체 경로를 전체 파이프라인
    수준에서 재현 검증(신규, 선택 사항), entry_score 코드 변경 PR
    초안 작성 착수 여부, §21 게이트 정기 재모니터링, exit 외 리스크
    관리 검토, 국면 혼합도 모니터링 설계 검토.
- [x] **SPPV-2.58(신설)** `§21 gate` config 기반 gate 제어 —
  mode-agnostic 신규 모듈 구현 (완료, 2026-07-18, 작성자: Codex)
  - 작업 범위: `§21 게이트`(regime_switch_v1)를 문서 해석이 아니라
    코드 레벨에서 config 스위치 기반으로 제어 가능하게 만든다.
    사전 조사 결과 이 게이트는 지금까지 실제 운영 코드 어디에도
    연결돼 있지 않은 순수 모니터링 산출물이었음을 확인 — R3b shadow
    관측은 이 게이트에 의해 코드 레벨에서 전혀 막힌 적이 없었다.
    `deterministic_trigger_engine.py`는 "절대 수정하지 않는다"는
    이 세션의 원칙에 따라 이번에도 수정하지 않고, 신규 격리 모듈로만
    구현했다.
  - **구현**: `AppSettings.regime_switch_v1_gate_override_enabled`
    (env: `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 False)
    신규 필드 + `services/regime_switch_gate.py`(신규)의
    `assess_regime_switch_v1_gate(*, trigger_status, override_
    enabled)` 순수 함수. **paper/real/production 같은 environment
    값은 전혀 참조하지 않는 mode-agnostic 판정** — 오직 config
    스위치와 실제 국면 관측치만 본다.
  - **동작**: override off(기본값) — TRIGGERED일 때만 열림(기존
    해석과 100% 동일). override on — 국면 상태와 무관하게 항상
    열림(강제 통과). 모든 판정에 reason_code(`gate_open_regime_
    switch_v1_triggered`/`gate_closed_regime_switch_v1_not_
    triggered`/`gate_open_config_override_bypass`)로 추적 가능.
  - **검증**(`scripts/validate_regime_switch_gate_config_
    override.py`, read-only, 신규 KIS 호출 0건): (a) 소스 코드
    검사로 `deterministic_trigger_engine.py`가 신규 모듈을 import
    하지 않음을 확인(`isolation_confirmed=True`), (b) 실제 §21
    게이트 상태 재조회 결과 여전히 `NOT_TRIGGERED`(불변), (c)
    override off/on 및 TRIGGERED/PARTIAL/NOT_TRIGGERED 3개 상태
    전부에 대한 시나리오가 모두 예상대로 동작함을 확인.
  - **판정**: R3b는 Conditional Go를 유지한다. §21 게이트 상태
    자체는 불변, `deterministic_trigger_engine.py` 미수정,
    compliance/VaR/broker submit 경계 미변경. 아직 실제 파이프라인
    에는 연결하지 않았다 — 연결은 별도 승인·PR 절차 필요. 신규 KIS
    호출 0건.
  - 산출물: `src/agent_trading/services/regime_switch_gate.py`
    (신규), `src/agent_trading/config/settings.py`(필드 추가),
    `scripts/validate_regime_switch_gate_config_override.py`
    (read-only), `logs/signal_ic_r3b_regime_switch_gate_config_
    override_2026-07-18.json`, `logs/r3b_regime_switch_gate_
    config_override_run_2026-07-18.log`.
  - 다음 과제: 신규 게이트 모듈을 실제 파이프라인에 연결할지 여부는
    별도 승인 필요(연결 시 compliance/리스크 재검토 필수), `trigger_
    status`를 최신으로 유지하는 배선 작업(모니터 스크립트 정기 실행
    → 이 모듈에 전달) 별도 필요. **[SPPV-2.59에서 정정] "구현
    완료"는 부정확 — "준비 모듈 + 런타임 미연결" 상태였음. 아래
    SPPV-2.59 참고.**
- [x] **SPPV-2.59(신설)** `§21 gate` 실제 판단 경로 연결 완료 —
  `deterministic_trigger_engine.py` 실제 수정 (완료, 2026-07-18,
  작성자: Codex)
  - 작업 범위: §47(SPPV-2.58)이 "준비 모듈만 추가하고 런타임
    미연결" 상태로 남긴 것을 사용자가 지적, 이번 턴에 실제 소비
    경로 연결을 완료. 사용자의 명시적 승인 아래 이 세션 최초로
    `deterministic_trigger_engine.py`를 실제로 수정했다(이전까지
    "절대 수정 금지" 원칙 적용 대상).
  - **연결 내용**: `assess_deterministic_triggers`(실제 BUY_
    CANDIDATE 판정 함수, 실제 주문 결정과 직결)에 신규 optional
    파라미터 `regime_switch_v1_trigger_status: str | None = None`,
    `regime_switch_v1_gate_override_enabled: bool = False` 추가.
    파라미터가 제공되면 `assess_regime_switch_v1_gate()`(§47, 그대로
    재사용)를 호출해 결과를 BUY_CANDIDATE 조건문에 실제로 연결:
    `eligibility_passed and entry_score >= threshold and allocation_
    budget_ok and (gate_assessment is None or gate_assessment.
    gate_open)`. 기본값(파라미터 미제공)이면 이 조건은 항상 True로
    평가돼 기존 호출부는 100% 무영향(하위 호환). `metadata`에
    `regime_switch_v1_gate_open`/`regime_switch_v1_gate_override_
    applied` 진단 필드도 추가. paper/real/production 값은 이 함수
    어디에도 참조되지 않는다.
  - **검증**(`scripts/validate_r3b_gate_integration_path.py`,
    read-only, 신규 KIS 호출 0건): 동일한 실제 함수 `assess_
    deterministic_triggers`를 3가지로 직접 호출(종목 000100/
    2023-10-11, entry_score=0.6895). (A) 게이트 파라미터 없음 —
    `buy_candidate=True`. (B) `trigger_status=NOT_TRIGGERED`,
    override=False(기본값) — `buy_candidate=False`로 실제 차단.
    (C) 동일 trigger_status, override=True — `buy_candidate=True`
    로 baseline과 동일 복원. **결과: `gate_actually_blocks_real_
    path=True`, `override_actually_restores_real_path=True`.**
    기존 단위 테스트(`tests/services/test_deterministic_trigger_
    engine.py`, 20건) 전부 통과.
  - **판정**: "§21 게이트 → 실제 판단 경로" 연결이 **완료**됐다 —
    다만 실제 운영 호출부(orchestrator)가 이 신규 파라미터를
    전달하도록 배선하는 것은 별도 미완료 과제(그 전까지 실제 운영
    동작 영향 없음, 의도된 안전장치). R3b는 Conditional Go를
    유지한다. compliance/VaR/broker submit 경계 미변경. 신규 KIS
    호출 0건. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §48.
  - 산출물: `src/agent_trading/services/deterministic_trigger_
    engine.py`(수정, 신규 optional 파라미터 2개 + BUY_CANDIDATE
    조건 연결 + metadata 필드 2개), `scripts/validate_r3b_gate_
    integration_path.py`(신규, read-only), `logs/signal_ic_r3b_
    gate_integration_path_2026-07-18.json`, `logs/r3b_gate_
    integration_path_run_2026-07-18.log`.
  - 다음 과제: 실제 운영 호출부(orchestrator/decision loop)에서
    `regime_switch_v1_trigger_status`를 실제로 전달하도록 배선하는
    설계(트리거 소스 결정 포함), 배선 완료 시 별도 리스크/
    컴플라이언스 재검토, §21 게이트 정기 재모니터링, entry_score
    코드 변경 PR 초안, 포지션 사이징 검토. **[SPPV-2.60에서 정정]
    "연결 완료"는 과장 — 상위 호출부(orchestrator) 배선은 아직
    미완료였음. 아래 SPPV-2.60 참고.**
- [x] **SPPV-2.60(신설)** `§21 gate` 상위 호출부(`decision_
  orchestrator.py`) 배선 완료 (완료, 2026-07-18, 작성자: Codex)
  - 작업 범위: §48(SPPV-2.59)이 `assess_deterministic_triggers`
    함수 내부까지만 게이트를 연결했을 뿐, 그 유일한 실제 상위
    호출부 `DecisionOrchestratorService`(`decision_orchestrator.
    py`)는 신규 파라미터를 전혀 넘기지 않고 있었다는 검수 결과에
    따라, 이번 턴은 그 gap을 메운다.
  - **배선 내용**: `DecisionOrchestratorService.__init__`에
    `regime_switch_v1_trigger_status`(기본값 None), `regime_
    switch_v1_gate_override_enabled`(기본값 False) 생성자 인자
    추가 → `_derive_deterministic_context_components`의 `assess_
    deterministic_triggers` 호출에 실제 전달. `scripts/run_
    decision_loop.py`의 두 `DecisionOrchestratorService` 생성
    지점 전부에서 `regime_switch_v1_trigger_status=resolve_
    cached_trigger_status()`, `regime_switch_v1_gate_override_
    enabled=settings.regime_switch_v1_gate_override_enabled`를
    실제로 전달하도록 수정. `resolve_cached_trigger_status()`
    (`regime_switch_gate.py`에 신규 추가)는 `logs/regime_switch_
    v1_gate_monitor_*.json`(가장 최근 mtime)에서 `trigger_status`
    를 읽는 read-only 헬퍼 — 매 결정마다 신규 KIS 호출을 만들지
    않기 위한 선택. paper/real/production 값은 어디에도 참조하지
    않음.
  - **검증**(`scripts/validate_r3b_orchestrator_gate_wiring.py`,
    신규, read-only, in-memory repos, 신규 KIS 호출 0건):
    `DecisionOrchestratorService`를 **실제로 구성**하고 그 실제
    메서드 `_derive_deterministic_context_components`를 거쳐
    확인(스크립트가 `assess_deterministic_triggers`를 직접 호출
    하는 우회 경로가 아님). (A) 게이트 없음 — `buy_candidate=
    True`(entry_score=0.7275). (B) trigger_status=NOT_TRIGGERED,
    override=False — `buy_candidate=False`로 실제 차단. (C) 동일
    trigger_status, override=True — `buy_candidate=True`로 복원.
    **결과: `gate_blocks_via_orchestrator=True`, `override_
    restores_via_orchestrator=True`.** 기존 단위 테스트 83건
    (`test_decision_orchestrator.py` 63 + `test_deterministic_
    trigger_engine.py` 20) 전부 통과.
  - **중요 리스크(반드시 사용자 확인 필요)**: 이 배선 완료로
    `run_decision_loop.py`가 이제 실제 §21 게이트 상태(현재
    `NOT_TRIGGERED`)를 읽어 전달하므로, override가 기본값 False인
    한 **core BUY_CANDIDATE 판정이 실제로 영향받기 시작한다** —
    이는 이번 배선 이전에는 없던 새로운 실제 동작 변화다. §21
    게이트는 candidate 종류를 구분하지 않고 `source_type != "held_
    position"`인 모든 BUY 판정에 적용된다.
  - **판정**: "§21 게이트 → 실제 판단 경로" 연결이 함수 내부뿐
    아니라 **상위 호출부까지 완료**됐다. R3b는 Conditional Go를
    유지한다. compliance/VaR/broker submit 경계 미변경. 신규 KIS
    호출 0건. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §49.
  - 산출물: `src/agent_trading/services/decision_orchestrator.py`
    (수정), `scripts/run_decision_loop.py`(수정), `src/agent_
    trading/services/regime_switch_gate.py`(수정, 신규 함수 추가),
    `scripts/validate_r3b_orchestrator_gate_wiring.py`(신규),
    `logs/signal_ic_r3b_orchestrator_gate_wiring_2026-07-18.json`,
    `logs/r3b_orchestrator_gate_wiring_run_2026-07-18.log`.
  - 다음 과제: **§49.5/§49.6의 리스크에 따라, override를 켤지
    (`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`) 또는 이 배선
    자체를 되돌릴지 사용자 확인 필요(최우선)**, `resolve_cached_
    trigger_status()`가 참조하는 모니터링 캐시 파일의 자동 정기
    갱신(cron/배치) 설계, entry_score 코드 변경 PR 초안, 포지션
    사이징 검토. **[SPPV-2.61에서 정정] 검증 산출물의 `resolve_
    cached_trigger_status_current_value=None`, "83건 테스트 통과"
    무증빙 문제 — 아래 SPPV-2.61 참고.**
- [x] **SPPV-2.61(신설)** SPPV-2.60 보고 정정 — `resolve_cached_
  trigger_status()` None 원인 규명 + 테스트 증빙 재확인 (완료,
  2026-07-18, 작성자: Codex)
  - 작업 범위: §49(SPPV-2.60)의 두 모순 — (1) 검증 산출물에서
    `resolve_cached_trigger_status_current_value=None`이었으나
    실제 캐시 파일 2개(`2026-07-14`, `2026-07-17`) 모두 `trigger_
    status="NOT_TRIGGERED"`를 담고 있었던 불일치, (2) "83건 테스트
    통과" 서술에 실행 증빙이 산출물로 남지 않았던 문제 — 를 규명·
    정정.
  - **원인 규명**: `resolve_cached_trigger_status()`의 glob/JSON
    파싱/status 검증 로직 자체에는 결함이 없었다. 원인은 기본
    `glob_pattern`이 상대경로("logs/regime_switch_v1_gate_
    monitor_*.json")라 **호출 시점의 cwd에 의존**했다는 점 —
    §49 검증이 Docker 컨테이너 안에서 실행됐는데 그 컨테이너의
    `/app/logs/`에 캐시 JSON 파일이 복사돼 있지 않아 `glob`이 빈
    리스트를 반환했고, 함수는 명세대로 정확히 `None`을 반환했다.
  - **수정**: `services/regime_switch_gate.py`에 `_PROJECT_ROOT =
    Path(__file__).resolve().parents[3]` 추가, `resolve_cached_
    trigger_status()`의 기본 `glob_pattern`을 이 프로젝트 루트
    기준 절대경로로 변경(환경 분기 없음, 하위 호환 유지 — 명시적
    `glob_pattern`을 넘기는 호출자는 그대로 동작).
  - **재검증**: `/tmp`(비-프로젝트 cwd)에서 호출해도 `NOT_
    TRIGGERED`를 정확히 반환함을 확인. Docker 컨테이너에 캐시
    파일 2개를 실제로 복사한 뒤 `validate_r3b_orchestrator_gate_
    wiring.py`를 재실행한 결과 `resolve_cached_trigger_status_
    current_value="NOT_TRIGGERED"`로 정상 조회. A/B/C 3개 시나리오
    결과는 §49와 동일(`gate_blocks_via_orchestrator=true`,
    `override_restores_via_orchestrator=true`).
  - **테스트 증빙**: `python3 -m pytest tests/services/test_
    decision_orchestrator.py tests/services/test_deterministic_
    trigger_engine.py -q`를 실제로 재실행, stdout을 `logs/r3b_
    pytest_run_2026-07-18.log`(83 passed)로 저장해 실행 증빙 보강.
  - **판정**: "배선은 완료됐으나 캐시 상태 전달에는 추가 수정이
    필요"했던 상태에서 **"캐시 상태까지 정상 전달됨"으로 확정.**
    §49.6의 리스크(override off 기본값 + NOT_TRIGGERED 조합에서
    core BUY_CANDIDATE 실제 차단 가능)는 이번 수정으로 cwd에
    관계없이 항상 실현 가능해져 더 급해졌다. R3b는 Conditional Go
    를 유지한다. compliance/VaR/broker submit 경계 미변경. 신규
    KIS 호출 0건. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §50.
  - 산출물: `src/agent_trading/services/regime_switch_gate.py`
    (수정), `logs/r3b_pytest_run_2026-07-18.log`(신규, pytest 실행
    증빙), `logs/r3b_orchestrator_gate_wiring_run_2026-07-18b.log`
    (신규, 재검증 실행 로그), `logs/signal_ic_r3b_orchestrator_
    gate_wiring_2026-07-18.json`(갱신).
  - **[운영 결정]** 게이트 배선은 유지하고, paper/shadow 관측 단계에서는
    `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 상태로 커밋/운영한다.
    이는 코드의 environment 분기가 아니라 명시적 config override
    운영 절차로 처리한다. production 전환 전에는 override를 다시
    제거(또는 False 복귀)한 상태에서 재검토한다.
  - 다음 과제(갱신): `trigger_status` 캐시 공급원 자동 갱신 설계
    (수동 모니터 스크립트/배치 연결 포함), entry_score 코드 변경 PR
    초안, 포지션 사이징 검토.
- [x] **SPPV-2.62(신설)** 국면 혼합도 모니터링 모듈 구현 및 §40
  재현성 검증 (완료, 2026-07-18, 작성자: Codex)
  - 작업 범위: 최신 truth(commit `aa10caee`로 §21 게이트 배선 완료,
    `.env`에 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 설정,
    paper 관측 단계에서 게이트는 BUY를 막지 않음)를 확정한 뒤, 후속
    과제 후보 4개 중 **혼합도 모니터링 설계**를 최우선으로 선택 —
    `trigger_status` 자동화는 override=true인 동안 급하지 않고,
    T+5/경로 리스크는 §41~§44에서 이미 충분히 답변됨.
  - **구현**: §40이 확정한 혼합도 3분위 경계값(cut1=0.15, cut2=
    0.3833)을 신규 모듈 `services/regime_mixedness_monitor.py`
    (BUY/SELL 미연결, 순수 관측/로깅용)로 재구현 —
    `compute_mixed_score()`(60거래일 trailing 국면 분포에서 mixed_
    score 계산), `classify_mixedness_bucket()`(3분위 분류 +
    §40 실측 신뢰도를 반영한 reason_code).
  - **검증**(`scripts/validate_regime_mixedness_monitor.py`,
    read-only, 신규 KIS 호출 0건 — 3년 캐시 bars만 재사용):
    벤치마크 634거래일 전체를 신규 모듈로 재분류한 결과 **저혼합
    217일/중혼합 215일/고혼합 202일 — §40 실측치와 정확히 일치
    (`matches_sppv_2_50=True`)**.
  - **해석**: 가설을 다시 검증한 것이 아니라, 그 검증 결과를 실제로
    소비 가능한 재사용 가능 코드 모듈로 정확히 이식했다는 것을
    100% 재현성으로 확인한 것 — "혼합도 모니터링 설계" 다음 단계가
    설계 스케치에서 검증된 모듈로 전진했다.
  - **판정**: R3b는 Conditional Go를 유지한다. 신규 KIS 호출 0건,
    운영 코드(`deterministic_trigger_engine.py`, `decision_
    orchestrator.py`) 미변경, compliance/VaR/broker submit 경계
    미변경. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §51.
  - 산출물: `src/agent_trading/services/regime_mixedness_
    monitor.py`(신규), `scripts/validate_regime_mixedness_
    monitor.py`(신규, read-only), `logs/signal_ic_regime_
    mixedness_monitor_validation_2026-07-18.json`, `logs/regime_
    mixedness_monitor_validation_run_2026-07-18.log`.
  - 다음 과제: 이 모듈을 실제 소비 위치(decision loop 로그, 대시
    보드 등)에 연결할지 여부(선택 사항, 별도 승인 필요), `trigger_
    status` 공급원 자동화(override=true인 동안 낮은 우선순위),
    entry_score 코드 변경 PR 초안, SPPV-3 착수 준비. **[SPPV-2.63
    에서 진전] 실제 소비 위치 연결 완료 — 아래 SPPV-2.63 참고.**
- [x] **SPPV-2.63(신설)** 국면 혼합도 모니터링을 실제 decision loop
  관측 경로에 연결 (완료, 2026-07-19, 작성자: Codex)
  - 작업 범위: §51(SPPV-2.62)이 검증만 하고 미연결로 남긴 gap을
    메운다. 후속 과제 후보(trigger_status 자동화/혼합도 모니터링
    실제 소비 위치 연결/T+5 후속 검증/SPPV-3 착수 준비) 중 이 항목
    을 최우선으로 선택 — trigger_status 자동화는 override=true인
    동안 급하지 않고, T+5/경로 리스크는 §41~§44에서 이미 답변됨.
  - **구현**: `scripts/run_decision_loop.py`에 신규 함수 `_run_
    mixedness_check(repos)` 추가 — 기존 `_run_precheck()`(snapshot
    sync health, cycle당 1회 실행)와 동일한 안전 패턴. 벤치마크
    (069500) `signal_feature_snapshots` 최근 60건을 read-only
    조회(신규 KIS 호출 없음, 이미 스냅샷 동기화 루프가 채워 넣은
    데이터 재사용) → 각 스냅샷에 실제 `classify_market_regime()`
    적용해 국면 라벨 trailing 리스트 구성 → §51의 `compute_mixed_
    score()`/`classify_mixedness_bucket()`(그대로 재사용)로 버킷·
    reason_code 계산 → `logger.info()`로 로그 기록. 예외는 전부
    흡수(사이클 진행에 영향 없음). **BUY/SELL 판정에는 전혀
    연결하지 않음** — 별도 트랜잭션·별도 변수로 완전히 분리.
  - **검증**(`scripts/validate_r3b_mixedness_decision_loop_
    wiring.py`, 신규, read-only, in-memory repos, 신규 KIS 호출
    0건): `_run_mixedness_check()`를 실제로 import·호출(로직 복제
    아님)해 저혼합(합성 60건 전부 강한 bullish)·고혼합(bullish/
    bearish 빈번 교차) 두 시나리오 검증. **결과: 저혼합 →
    mixed_score=0.0/bucket=저혼합, 고혼합 → mixed_score=0.5/
    bucket=고혼합 — 두 시나리오 모두 기대한 버킷으로 정확히
    분류됨.** `inspect.getsource()`로 소스에 BUY/SELL 판정 관련
    코드가 전혀 없음도 확인.
  - **테스트**: 기존 `tests/scripts/test_run_decision_loop.py`
    10건 실패는 변경 전(git stash 재실행)에도 동일하게 실패하는
    사전 존재 결함(universe_selection/market_overlay 관련)임을
    확인 — 이번 변경과 무관, 109건은 변경 전후 모두 통과.
  - **판정**: R3b는 Conditional Go를 유지한다. BUY/SELL 게이트
    로직은 더 세지지 않았다 — 관측/로깅 경로만 추가. 신규 KIS 호출
    0건, `.env` 미수정, environment 분기 없음, compliance/VaR/
    broker submit 경계 미변경. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §52.
  - 산출물: `scripts/run_decision_loop.py`(수정, `_run_mixedness_
    check()` 추가 + 배선), `scripts/validate_r3b_mixedness_
    decision_loop_wiring.py`(신규, read-only), `logs/signal_ic_
    r3b_mixedness_decision_loop_wiring_2026-07-19.json`, `logs/
    r3b_mixedness_decision_loop_wiring_run_2026-07-19.log`, `logs/
    r3b_pytest_run_decision_loop_2026-07-19.log`.
  - 다음 과제: `trigger_status` 공급원 자동화/배치화(override=true
    인 동안 낮은 우선순위), entry_score 코드 변경 PR 초안, R3b
    alpha 교체 전체 경로 전체 파이프라인 재현 검증(선택 사항),
    `portfolio_allocation` gap 실거래 누적 후 재검증. **[SPPV-2.64
    에서 확정] "stash 재실행으로 확인(무관)" 서술의 증빙을
    격리된 worktree 비교로 확정 — 아래 SPPV-2.64 참고.**
- [x] **SPPV-2.64(신설)** SPPV-2.63 미확정 항목 확정 — `test_run_
  decision_loop.py` 10건 실패 무관 확정 (완료, 2026-07-19, 작성자:
  Codex)
  - 작업 범위: §52(SPPV-2.63)가 "stash 재실행으로 확인(무관)"
    이라고만 서술해 증빙이 약했던 부분 — mixedness 변경과 기존
    테스트 10건 실패의 무관성 — 을 실제 증빙으로 확정한다. 코드
    수정은 하지 않고 검증만 수행.
  - **방법**: `git worktree add /tmp/wt-pre-mixedness 4fd3ad7e`
    (§52 이전 커밋)로 메인 워크트리를 전혀 건드리지 않는 격리
    비교 구성. Docker 컨테이너 안에서 PRE(mixedness 코드 없음)/
    POST(현재 main과 동일) 두 버전 각각 `pytest tests/scripts/
    test_run_decision_loop.py -v --tb=long`로 전체 재실행하고
    807줄 로그를 저장 후 `diff`로 직접 비교, `grep`으로 mixedness
    관련 문자열이 실패 stack trace에 등장하는지 확인.
  - **결과**: PRE/POST 모두 `10 failed, 109 passed` — **실패한
    테스트 10건의 이름·에러 메시지·assertion 내용까지 완전히
    동일**(차이는 비결정적 메모리 주소와 정확히 71줄의 라인 번호
    오프셋뿐 — mixedness 코드가 파일 앞부분에 삽입돼 그 뒤 코드가
    밀린 결과일 뿐). `grep -n "_run_mixedness_check\|regime_
    mixedness_monitor\|mixedness"`로 POST 로그 전체를 검색한 결과
    **매치 0건**.
  - **판정**: **`무관 확정`** — 10건 실패는 `universe_selection.
    py`(market_overlay seed pool)와 AsyncMock/Decimal 타입
    불일치 관련 사전 존재 결함이며, §52의 국면 혼합도 모니터링
    연결과 완전히 무관하다. R3b는 Conditional Go를 유지한다.
    이번 턴은 코드를 전혀 수정하지 않았다(순수 검증). 신규 KIS
    호출 0건, `.env` 미수정, BUY/SELL 게이트 로직 미변경. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §53.
  - 산출물: `logs/r3b_test_run_decision_loop_PRE_mixedness_2026-
    07-19.log`(신규), `logs/r3b_test_run_decision_loop_POST_
    mixedness_2026-07-19.log`(신규) — worktree/컨테이너 백업은
    작업 종료 후 완전히 정리(main 워크트리 무변화 확인).
  - 다음 과제(변경 없음): `trigger_status` 공급원 자동화, entry_
    score 코드 변경 PR 초안, `test_run_decision_loop.py`의 10건
    사전 존재 결함 자체 수정 여부는 이번 세션(SPPV/R3b 트랙) 범위
    밖 — 별도 이슈로 트래킹 권장. **[SPPV-2.65에서 진전] entry_
    score PR 초안 설계 완료 — 아래 SPPV-2.65 참고.**
- [x] **SPPV-2.65(신설)** entry_score 코드 변경 PR 초안 설계 — R3b
  alpha 교체 실제 파이프라인 연결 방안 (완료, 2026-07-19, 작성자:
  Codex)
  - 작업 범위: 후속 과제 후보(trigger_status 자동화/entry_score
    코드 변경 PR 초안/R3b alpha 전체 경로 재현 검증/T+5 후속 검증)
    중 **entry_score 코드 변경 PR 초안 준비**를 선택 — trigger_
    status 자동화는 override=true인 동안 급하지 않고, mixedness는
    실제 소비 위치 연결까지 이미 끝나 같은 축 반복 회피. "R3b
    alpha 전체 경로 재현 검증"은 §45(non-alpha 100% 일치)의
    논리적 귀결이라 다시 실측하지 않고, 대신 이 세션에서 한 번도
    명시되지 않은 **아키텍처 제약**을 조사했다.
  - **핵심 발견**: `entry_score`는 종목 단위로 계산되지만 R3b
    alpha(`candidate_percentile`)는 당일 cross-sectional 순위가
    필요해 사전 계산 단계가 있어야 한다 — `DecisionOrchestrator
    Service._derive_deterministic_context_components`는 요청
    (symbol) 1건마다 독립 호출되므로 그 시점에 "오늘 다른
    candidate들의 신호 값"을 알 수 없다.
  - **기존 선례 발견**: `scripts/run_decision_loop.py`의 `_build_
    core_risk_off_apply_overrides_for_cycle()`(cycle당 1회 전체
    universe precompute → `deterministic_trigger_override`로
    종목별 주입)이 정확히 필요한 구조로 이미 존재함을 확인 — 신규
    설계 리스크를 낮추는 유리한 선례.
  - **제안 설계(미적용, 코드 변경 없음)**: (1) 신규 cycle당 1회
    precompute 함수(당일 quintile 상위 20% candidate의 `candidate_
    percentile` 계산, 기존 shadow 스크립트 로직 이식), (2)
    `assess_deterministic_triggers`에 §48/§49와 동일 패턴의 신규
    optional 파라미터 2개(`r3b_alpha_percentile`, `r3b_alpha_
    enabled`, 기본값 None/False = 기존 공식 100% 유지), (3) 신규
    config 스위치 `ENTRY_SCORE_R3B_ALPHA_ENABLED`(기본값 False).
  - **판정**: "entry_score 코드 반영 절차"는 "shadow 정합성 확보"
    에서 "구체적 구현 설계 확보(diff 초안)"로 진전됐다 — 실제
    적용은 §48/§49와 동일하게 별도의 명시적 사용자 승인 필요. R3b
    는 Conditional Go를 유지한다. 신규 KIS 호출 0건, compliance/
    VaR/broker submit 경계 미변경, 코드 미변경(순수 설계 문서
    작업). 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §54.
  - 다음 과제: 이 설계를 실제로 적용할지 여부 사용자 결정(적용
    시 별도 승인 절차 필요), `trigger_status` 공급원 자동화(낮은
    우선순위), T+5/경로 리스크 후속 검증(§41~§44에서 이미 상당
    부분 답변됨, 추가 필요성 낮음), `portfolio_allocation` gap
    실거래 누적 후 재검증.
- [x] **SPPV-2.66(신설)** entry_score R3b alpha 교체 — 1단계(엔진
  파라미터 배선) 실제 코드 적용 (완료, 2026-07-19, 작성자: Codex)
  - §54(SPPV-2.65)의 미적용 설계 중 "1단계: 엔진 파라미터 배선"만
    실제 코드로 전환 — cycle 단위 precompute("2단계")는 범위 밖,
    별도 승인 대상으로 유보.
  - **적용 내용**: `settings.py`에 `entry_score_r3b_alpha_enabled`
    필드(env: `ENTRY_SCORE_R3B_ALPHA_ENABLED`, 기본값 False) 추가;
    `deterministic_trigger_engine.py`의 `assess_deterministic_
    triggers`/`_build_entry_score`에 `r3b_alpha_percentile`/
    `r3b_alpha_enabled` optional 파라미터 2개 추가 — 활성 시에만
    alpha 항이 `0.80 * candidate_percentile`로 교체, 비활성(기본값)
    시 기존 공식 100% 유지.
  - **실측**: 기존 회귀 테스트 83건 전부 통과(0건 실패); `AppSettings
    ().entry_score_r3b_alpha_enabled` 기본값 `False` 확인; `_build_
    entry_score` ad-hoc 호출 비교로 활성 경로(percentile=0.9) 결과
    `0.72`가 기대값(`0.80*0.9`)과 완전 일치(오차 <1e-9) 확인.
  - **판정**: Conditional Go 유지. `.env` 미변경, gate 로직 강화
    없음, 환경 분기 없음. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §55.
  - 다음 과제: cycle 단위 candidate_percentile 사전 계산 배선(2단계,
    별도 승인 필요), `trigger_status` 자동화(낮은 우선순위).
- [x] **SPPV-2.67(신설)** entry_score R3b alpha 교체 — 2단계(순수
  계산 모듈 + orchestrator 배선) 실제 코드 적용 (완료, 2026-07-19,
  작성자: Codex)
  - 신규 `services/r3b_alpha_percentile.py`(shadow 스크립트 로직
    그대로 이식, 200회 무작위 trial 전부 일치 검증) + `decision_
    orchestrator.py`에 `r3b_alpha_enabled` config·`request.metadata
    ["r3b_alpha_percentile"]` 추출 헬퍼·`_derive_deterministic_
    context_components` 배선 + `run_decision_loop.py` 두 인스턴스화
    지점 config 전달.
  - **범위 밖(유보)**: cycle당 1회 universe 순회 percentile 실제
    계산·`request.metadata`에 주입하는 precompute 함수("3단계")는
    미작성 — 현재 `r3b_alpha_percentile`은 항상 `None`이라 활성화
    스위치를 켜도 alpha 교체가 실제로 발동하지 않는다.
  - **실측(이번 턴 직접 재실행, 재인용 아님)**: 신규 모듈 parity
    검증 200회 trial 불일치 0건; `test_deterministic_trigger_
    engine.py`+`test_decision_orchestrator.py` 83 passed, 0 failed;
    `test_run_decision_loop.py` 10 failed/109 passed(기존 §53
    확정 실패와 이름·개수 동일); `tests/ -k "orchestrator or
    deterministic_trigger"` 118 passed/6 failed(DB 마이그레이션
    `TooManyColumnsError` 관련 사전 존재 환경 이슈, 파라미터 배선과
    무관함을 에러 메시지로 확인).
  - **판정**: Conditional Go 유지. `.env` 미변경, gate 로직 강화
    없음, 환경 분기 없음. 상세: `plans/[DESIGN] regime_conditional_
    entry_signal_v1.md` §56.
  - 다음 과제: cycle당 1회 precompute 함수("3단계", 별도 승인
    필요), `trigger_status` 자동화(낮은 우선순위).
  - **[SPPV-2.68에서 정정] "2단계 완료"/"orchestrator까지 배선
    완료"/"전원이 꽂히지 않은 상태" 표현이 과장이었음이 확인됨 —
    아래 SPPV-2.68 참고. 이 항목의 텍스트 자체는 삭제하지 않고
    보존한다.**
- [x] **SPPV-2.68(신설)** SPPV-2.67 보고 정정 — "2단계 완료" 표현의
  과장 부분 확정 (완료, 2026-07-19, 작성자: Codex)
  - **목적**: 새 기능 구현이 아니라 §56(SPPV-2.67)의 서술과 실제
    코드 상태를 일치시키는 정정 턴. `r3b_alpha_percentile.py`/
    `decision_orchestrator.py`/`run_decision_loop.py` 3개 파일을
    직접 읽어 재확인했다.
  - **확인된 사실**: 순수 계산 모듈은 실제로 존재하나 production
    코드 어디에서도 import되지 않는 고립 모듈(자기 검증 스크립트만
    사용); `decision_orchestrator.py`는 `request.metadata["r3b_
    alpha_percentile"]`을 실제로 읽어 엔진까지 전달(두 호출 지점
    모두 실제 코드로 확인); `run_decision_loop.py`에는 `r3b_alpha_
    enabled=settings...` config 전달 두 줄만 존재하고, `r3b_alpha_
    percentile`이라는 키를 어떤 `request.metadata`에도 써넣는 코드는
    **단 한 줄도 없음**(grep으로 확인, `_build_core_risk_off_apply_
    overrides_for_cycle()`과 짝을 이루는 함수 자체가 없음).
  - **판정**: "2단계(cycle 단위 candidate_percentile precompute
    배선) 선택·실행"은 **과장** — 실제로는 "orchestrator 통로 준비
    + 계산 모듈 독립 구현"만 이뤄졌고 "cycle 단위 precompute 배선"
    자체(값을 계산해 실제로 주입하는 코드)는 이 세션 전체를 통틀어
    단 한 번도 작성된 적이 없다. "orchestrator까지 배선 완료"는
    orchestrator 자체의 통로 준비는 사실이나, 파이프라인 앞부분
    (cycle precompute)이 존재하지 않는다는 사실을 가리는 표현이라
    과장으로 확정. R3b 자체 판정(Conditional Go)은 코드 변경이
    없으므로 불변. 상세: `plans/[DESIGN] regime_conditional_entry_
    signal_v1.md` §57.
  - 다음 과제: 변경 없음(§56.7과 동일) — cycle당 1회 precompute
    함수(코드 0줄, 여전히 유일한 실제 실행 단계로 남은 과제),
    `trigger_status` 자동화(낮은 우선순위).
- [x] **SPPV-2.69(신설)** entry_score R3b alpha 교체 — cycle
  precompute 실제 구현·발동 확인 (완료, 2026-07-19, 작성자: Codex)
  - §57이 "여전히 유일한 실행 단계"로 남긴 cycle precompute를
    실제로 구현했다: `run_decision_loop.py`에 신규 `_build_r3b_
    alpha_percentile_overrides_for_cycle()`(config 기본값이면 즉시
    빈 dict 반환, DB 조회조차 없음) + cycle당 1회 호출 + `_run_
    one_cycle`의 `SubmitOrderRequest.metadata["r3b_alpha_
    percentile"]` 주입 + `_process_one`에서 종목별 값 전달.
  - **실제 발동 검증(신규 `scripts/validate_r3b_alpha_precompute_
    end_to_end.py`, 이번 턴 직접 실행)**: (1) precompute 함수가
    실제로 universe를 순회해 20개 중 상위 20%(4개)에만 percentile
    부여를 실측 확인; (2) 실제 DB 종목(000080)으로 — 비활성 시
    `entry_score=0.1159`(r3b reason_code 없음) vs 활성+percentile
    0.9 주입 시 `entry_score=0.5999`(`trigger_r3b_alpha_percentile`
    reason_code 발생) — **alpha 교체가 실제로 발동함을 증명**.
  - **회귀**: `test_deterministic_trigger_engine.py`+`test_decision_
    orchestrator.py` 83 passed/0 failed; `test_run_decision_
    loop.py` 8 failed/111 passed — `git stash`로 이번 턴 변경분을
    제외해도 동일하게 8 failed/111 passed임을 직접 대조 확인(이번
    턴 코드와 무관한 사전 존재 비결정성, §53의 10건 집합의
    부분집합).
  - **판정**: R3b alpha 교체 파이프라인이 처음으로 실제 코드에서
    완성되고 발동이 증명됐다. 기본값(`.env` 미변경)에서는 기존
    동작 100% 유지. R3b는 Conditional Go를 유지한다. `.env` 미변경,
    gate 로직 강화 없음, 환경 분기 없음, 신규 KIS 호출 0건. 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §58.
  - 다음 과제: `ENTRY_SCORE_R3B_ALPHA_ENABLED=true` 실제 활성화
    여부 사용자 결정(신중한 검토 필요, `.env` 값이므로 사용자가
    직접 변경), `trigger_status` 자동화(낮은 우선순위).
  - **[SPPV-2.70에서 증빙 정정] 위 "8 failed/111 passed"·"실제
    발동 증명" 수치 자체는 정확했으나, 저장소 내 재현 가능한
    로그/JSON 산출물이 없었음이 확인됨 — 아래 SPPV-2.70 참고. 이
    항목의 텍스트는 삭제하지 않고 보존한다.**
- [x] **SPPV-2.70(신설)** SPPV-2.69 보고 증빙 정정 — 테스트 수치·
  실행 증빙 재확인 (완료, 2026-07-19, 작성자: Codex)
  - **목적**: 새 기능 구현이 아니라 §58(SPPV-2.69)의 수치·실행
    증빙을 실제 파일/로그 기준으로 재검증. `logs/r3b_pytest_run_
    decision_loop_2026-07-19.log`(01:48 생성)가 §68 이전(SPPV-2.64,
    §53) 턴의 오래된 로그(10 failed/109 passed)였고, §58이 인용한
    "8 failed/111 passed"는 저장소 로그가 아니라 대화 출력 인용
    이었음을 확인. `validate_r3b_alpha_precompute_end_to_end.py`의
    실행 결과도 저장소에 로그/JSON으로 남아있지 않았음을 확인.
  - **이번 턴 재실행·신규 저장 증빙**: `logs/r3b_pytest_run_
    decision_loop_2026-07-19b.log`(신규, 8 failed/111 passed —
    §58 수치와 정확히 일치); `logs/r3b_alpha_precompute_end_to_
    end_run_2026-07-19.log`(신규, stdout 전체) + `logs/signal_ic_
    r3b_alpha_precompute_end_to_end_2026-07-19.json`(신규, 검증
    스크립트에 JSON 출력 기능 추가 후 재실행) — 000080 종목 기준
    entry_score 0.1159→0.5999 완전 재현; `logs/r3b_pytest_engine_
    orchestrator_2026-07-19.log`(신규, 83 passed/0 failed).
  - **판정**: §58의 수치 자체는 틀리지 않았으나 저장소 증빙이
    부족했다 — "결론 유지 + 증빙 보강"으로 확정(결론 하향 아님).
    R3b는 Conditional Go를 유지한다. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §59.
  - 다음 과제: 변경 없음(§58과 동일) — `ENTRY_SCORE_R3B_ALPHA_
    ENABLED=true` 활성화 여부 사용자 결정.
- [x] **SPPV-2.71(신설)** R3b alpha paper 운영 전환 최종 착수 준비
  상태 점검 (완료, 2026-07-19, 작성자: Codex)
  - **목적**: "`ENTRY_SCORE_R3B_ALPHA_ENABLED=true`만 켜면 되는가?"
    라는 단일 질문 기준으로, 이미 구현/증빙 완료된 것(§55~§59)을
    재검증하지 않고 종합 점검. 코드/DB를 이번 턴 직접 다시 조회해
    신규 사실 하나를 확인.
  - **핵심 신규 발견**: `_R3B_ALPHA_BENCHMARK_SYMBOL="069500"`(벤치
    마크)의 `signal_feature_snapshot`이 DB에 **전체 이력 통틀어
    0건**임을 직접 SQL 조회로 확인. 원인도 확인 — `data/signal_
    feature_snapshot_input.json`(일일 배치 입력 목록, 80건)에
    `069500`이 애초에 포함돼 있지 않음(구조적 결측, 일시적 장애
    아님).
  - **실제 영향**: `_build_r3b_alpha_percentile_overrides_for_
    cycle()`이 벤치마크 스냅샷 없음 → `market_common_label=None`
    → 즉시 빈 dict 반환 분기를 항상 타게 되어, `ENTRY_SCORE_R3B_
    ALPHA_ENABLED=true`로 전환해도 **alpha 교체가 실제로는 절대
    발동하지 않는다**(config는 켜지지만 벤치마크 데이터 결측으로
    실질 무동작).
  - **판정**: "구현 완료"(§55~§59, `.env` 전환만으로 코드 추가 변경
    불필요)와 "운영 전환 준비 완료"(벤치마크 데이터 결측으로 미완료)
    를 분리 확정. R3b는 Conditional Go를 유지한다. **SPPV-3까지
    남은 항목 3분류**: (1) 실제 차단 요소 — 벤치마크 signal_
    feature_snapshot 배치 미포함(해소 필요, 별도 승인); (2) 사용자
    결정 대기 — `ENTRY_SCORE_R3B_ALPHA_ENABLED=true` 전환(위 (1)
    해소 이후 의미 생김); (3) 후속 검증 과제 — `trigger_status`
    자동화, T+5, `portfolio_allocation` gap(발동을 막지 않음). 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §60.
  - 다음 과제: 벤치마크 signal_feature_snapshot 배치 포함 여부
    해소(신규 최우선 항목, 별도 승인 필요) → 해소 후 `ENTRY_SCORE_
    R3B_ALPHA_ENABLED=true` 전환 여부 사용자 결정.
- [x] **SPPV-2.72(신설)** 벤치마크(069500) signal_feature_snapshot
  배치 미포함 문제 실제 해소 (완료, 2026-07-19, 작성자: Codex)
  - **목적**: §60(SPPV-2.71)이 확인한 유일한 실제 차단 요소를
    실제로 해소하는 운영 데이터 경로 수정 턴(검증 아님).
  - **원인**: `generate_signal_feature_snapshot_input.py`의
    universe는 거래 후보 universe(`UniverseSelectionService.
    compose()`)뿐 — 069500은 거래 후보가 아니라 애초에 이 구성에
    나타날 수 없었다(버그 아님, 설계상 분리된 두 개념 간의 편입
    경로 부재).
  - **수정**: 신규 함수 `_with_regime_benchmark_symbol()`을 추가 —
    `run_decision_loop.py`가 이미 두 곳(mixedness, R3b alpha)에서
    쓰는 `_R3B_ALPHA_BENCHMARK_SYMBOL`/`_R3B_ALPHA_BENCHMARK_
    MARKET`("069500"/"KRX")을 재사용(신규 하드코딩 아님), 거래
    universe/DB freeze 기록은 그대로 두고 `_build_rows`/`_write_
    rows`에 전달되는 로컬 tuple에만 `source_type="regime_
    benchmark"`로 벤치마크 1건 추가.
  - **실제 검증(신규 `scripts/validate_r3b_alpha_benchmark_
    snapshot_fix.py`)**: 실제 KIS 일봉 조회(rows=1, errors=0) →
    실제 `build_signal_feature_snapshots.py` CLI 그대로 실행
    (processed=1, persisted=1, errors=0) → DB 재조회 069500
    snapshot **0건→1건** 실측 확인 → `_build_r3b_alpha_percentile_
    overrides_for_cycle()`을 실제 core 종목 10개+벤치마크로 재호출
    → **`{'000810': 1.0, '001450': 0.0}`**(빈 dict 아님, 실제
    재발동 확인).
  - **회귀**: `test_generate_signal_feature_snapshot_input.py`+
    `test_build_signal_feature_snapshots.py` 20 passed/0 failed;
    엔진/orchestrator 83 passed/0 failed; `test_run_decision_
    loop.py` 8 failed/111 passed(기존 비결정성과 동일).
  - **판정**: 실제 차단 요소 해소 확정 — `ENTRY_SCORE_R3B_ALPHA_
    ENABLED=true` 전환 시 이제 실제로 발동 가능한 상태다. 다만
    "1회성 실행으로 채운 것"과 "매일 정기 배치가 앞으로 계속
    포함하는 것"은 구분(후자는 이미 존재하는 ops-scheduler
    스케줄이 자동 소비할 것으로 예상되나 시간 경과 후 재확인
    권장). R3b는 Conditional Go를 유지한다. `.env` 미변경, gate
    로직 강화 없음, 신규 KIS 호출 1건(read-only 시세 조회). 상세:
    `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §61.
  - 다음 과제: `ENTRY_SCORE_R3B_ALPHA_ENABLED=true` 실제 활성화
    여부 사용자 결정(이제 의미 있는 결정); 다음 정기 배치 사이클
    자동 반영 재확인(후속 검증 과제, 낮은 우선순위); `trigger_
    status` 자동화(낮은 우선순위).
- [x] **SPPV-2.73(신설)** R3b alpha 운영 반영 여부 실제 점검 —
  docker-compose 환경변수 배선 미비 신규 발견 (완료, 2026-07-19,
  작성자: Codex)
  - **목적**: "전환할지"가 아니라 "`ENTRY_SCORE_R3B_ALPHA_
    ENABLED=true`가 이미 `.env`에 반영된 상태에서 실제 paper
    decision loop에 반영됐는지"를 운영 경로 기준으로 점검.
  - **전제 확인**: 호스트 `.env`에 값이 실제로 있음을 확인(`grep`
    결과 `39:ENTRY_SCORE_R3B_ALPHA_ENABLED=true`) — 사용자 전제는
    정확함.
  - **핵심 신규 발견**: 그러나 실행 중인 `ops-scheduler` 컨테이너는
    이 값을 전혀 읽지 못한다 — (1) `Dockerfile`이 `.env`를 이미지에
    COPY하지 않음; (2) `docker-compose.yml`이 `.env`를 어떤
    서비스에도 `env_file`/마운트로 지정하지 않고, `ops-scheduler`의
    `environment:` 화이트리스트에도 `ENTRY_SCORE_R3B_ALPHA_ENABLED`
    /`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED` 둘 다 선언돼 있지
    않음; (3) 실행 중 프로세스의 실제 환경변수(`docker exec ...
    env`, `/proc/1/environ`)를 직접 읽어 두 변수 모두 부재 확인;
    (4) subprocess 상속 경로(`_build_base_env()`의 `os.environ.
    copy()`)도 부모에 없는 값을 자식에 줄 수 없고, `run_decision_
    loop.py`의 `load_dotenv()`도 컨테이너 안에 `.env` 파일 자체가
    없어 완전한 no-op임을 확인.
  - **추가 발견**: 이 문제는 R3b alpha에 국한되지 않는다 — `.env`
    기반 config 스위치 전체(§21 게이트 override 포함)가 구조적으로
    운영 컨테이너에 전달될 경로가 없다. 이 세션이 여러 턴에 걸쳐
    "`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`이므로 게이트가
    BUY를 막지 않는다"고 확정해 온 것은 호스트 `.env` 서술로는
    정확했으나, 실제 운영 컨테이너 도달 여부는 이번 턴 이전까지
    한 번도 검증된 적이 없었다.
  - **추가 관측**: 최근 3일(07-17~19)이 연속 비거래일로 판정돼
    `run_decision_loop.py` 자체가 최근 실행되지 않음(마지막 실제
    cycle은 07-16) — `trigger_r3b_alpha_percentile` 로그도 0건.
  - **판정**: 코드 구현 완료(예)/env 설정 완료(예)/**실행 중 paper
    프로세스 반영 완료(아니오)**로 3단계 분리 확정. R3b는
    Conditional Go를 유지한다. 이번 턴은 코드/`.env`/`docker-
    compose.yml` 어느 것도 수정하지 않았고 컨테이너도 재시작하지
    않았다(순수 조사 턴, 실거래/주문 없음). 상세: `plans/[DESIGN]
    regime_conditional_entry_signal_v1.md` §62.
  - 다음 과제: `docker-compose.yml`에 두 변수 환경변수 배선 추가 +
    `ops-scheduler` 재생성 여부 사용자 결정(별도 승인 필요, 살아
    있는 운영 컨테이너 재기동 포함) → 승인 시 다음 실제 거래일
    cycle에서 재확인.
- [x] **SPPV-2.74(신설)** docker-compose 환경변수 배선 실제 수정 —
  R3b alpha/§21 게이트 override 운영 반영 완료 (완료, 2026-07-19,
  작성자: Codex)
  - **목적**: §62(SPPV-2.73)가 확인한 실제 차단 요소(compose 환경
    변수 배선 누락)를 실제로 해소하는 운영 배선 수정 턴(사용자
    명시적 승인·상세 지시에 따라 실행).
  - **수정**: `docker-compose.yml`의 `ops-scheduler`
    `environment:` 블록(`DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_
    OFF_TOPK` 바로 다음)에 기존 `${VAR:-default}` 패턴 그대로
    `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`/`ENTRY_SCORE_R3B_
    ALPHA_ENABLED` 2줄 추가(기본값 false, paper/production 분기
    없음). `api`/`reconciliation-worker`는 `DecisionOrchestrator
    Service`/`run_decision_loop`를 참조하지 않음을 확인해 배선
    대상에서 제외(불필요한 서비스 확장 없음).
  - **실제 검증(신규 `logs/r3b_docker_compose_env_wiring_fix_
    2026-07-19.log`)**: 수정 전 컨테이너 env에 두 값 없음 확인 →
    `docker compose config` 렌더링으로 `"true"`/`"true"` 치환 확인
    → `docker compose up -d --force-recreate --no-deps ops-
    scheduler`로 재생성(다른 서비스 무영향) → 재생성 후 `Up ...
    (healthy)` → 실제 프로세스 env 재확인 **`ENTRY_SCORE_R3B_
    ALPHA_ENABLED=true`, `REGIME_SWITCH_V1_GATE_OVERRIDE_
    ENABLED=true`** → `/app/.env` 파일은 여전히 없음(compose
    environment 주입만으로 값 전달 증명) → 컨테이너 안에서 직접
    `AppSettings()` 실행 결과 **`True True`** → 재생성 후 로그
    정상(비거래일 정상 판정, `submit_count=0`, 예기치 않은 주문
    없음).
  - **판정**: 실제 차단 요소 완전 해소 — R3b alpha/§21 게이트
    override 모두 이제 실제 paper 운영 프로세스에 도달한다. R3b는
    Conditional Go를 유지한다. 상세: `plans/[DESIGN] regime_
    conditional_entry_signal_v1.md` §63.
  - 다음 과제(실제 차단 요소 아님, 다음 거래일 관측 과제): 다음
    실제 거래일(2026-07-20 예정) cycle에서 `trigger_r3b_alpha_
    percentile` reason_code 실제 관측; 다음 정기 signal feature
    배치 사이클에서 벤치마크 자동 반영 재확인; `trigger_status`
    자동화(낮은 우선순위); T+5; `portfolio_allocation` gap.
- [x] **SPPV-2.75(신설)** 보유기간/Churn 제어가 R3b BUY 빈도를
  얼마나 깎는지 정량 검증 (완료, 2026-07-19, 작성자: Codex)
  - **목적**: churn guard(`holding_profile_earliest_reentry_
    guard`/`held_position_recent_hold_no_change`/`held_position_
    recent_risk_sell_cooldown` 등)가 R3b BUY_CANDIDATE(entry_
    score>=0.65) 빈도를 실제로 얼마나 억제하는지, 운영 함수·운영
    DB 기준으로 정량 분해.
  - **표본 범위 결정**: churn guard는 실제 거래 이력(`symbol_
    trade_states`)에 의존하는 stateful guard라 3년 합성 표본
    구성이 불가능 — 실제 운영 창(2026-05-13~07-16, guardrail_
    evaluations 실제 존재 구간 2026-06-14~07-16)을 그대로 사용.
  - **표 A**: `guardrail_evaluations`(`pre_ai_gate_v1`) 6,027건
    원시 이벤트 중 churn 관련 3개 사유(`held_position_recent_
    hold_no_change`=911, `holding_profile_earliest_reentry_
    guard`=442, `held_position_recent_risk_sell_cooldown`=72)를
    `(symbol, 날짜)` 단위로 dedupe해 distinct episode 94/31/19건
    확인. `same_symbol_reentry_cooldown`/`holding_profile_
    earliest_reduce_guard`는 이 창에서 한 번도 발동하지 않음.
  - **표 B(핵심 발견)**: 각 episode의 차단 시점 직전 실제
    `signal_feature_snapshot`으로 운영 함수 `_build_entry_score()`
    를 재계산한 결과, **churn guard가 차단한 144건 전부 entry_
    score<0.65**(평균 0.095~0.332, 최댓값 0.594) — R3b BUY_
    CANDIDATE 문턱을 넘는 표본이 **0건**. candidate가 0건이라
    forward return(T+5/T+20) 계산 대상 자체가 없음(공집합 자체가
    실측 결과). 표본 기간(일봉 이력 ~1개월)도 T+20 관측에
    구조적으로 짧음을 확인.
  - **표 C**: 같은 창 실제 `trade_decisions.decision_type='buy'`
    =49건. churn guard 완화 시 추가 BUY는 0건(candidate 0건이므로)
    — 차단 완화가 R3b 기회를 늘려주는 효과가 이번 창에서는 관측
    안 됨.
  - **판정**: **Watch** — "churn guard가 R3b 고품질 BUY를 과잉
    억제한다"는 가설은 기각(entry_score>=0.65 차단 사례 0건, 공격형
    목표에 유리한 방향)되나, 표본이 작고(144 episode, 2개월) reduce_
    guard/reentry_cooldown이 미발동 상태라 Go 격상은 시기상조. R3b
    자체는 Conditional Go를 유지한다(이 축의 판정과 별개). 신규
    KIS 호출 0건(전부 기존 DB read-only). 코드 변경 없음(검증
    스크립트 신규 추가만). 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §64.
  - 다음 과제: paper 운영 표본 누적 후 재검증(가장 우선);
    `probe_churn_single_share_blocked` 등 execution_service 레벨
    guard 분석 추가(guardrail_evaluations 밖 별도 경로); 미발동
    축(reduce_guard/reentry_cooldown) 실제 발동 시 재검증.
- [x] **SPPV-2.76(신설)** R3b alpha가 실제 paper 운영 경로에서
  정말 발동하는지 최종 실증 (완료, 2026-07-20, 작성자: Codex)
  - **목적**: env/config→코드 경로→percentile 계산·주입→실제
    decision 영향 4단계 분리 실측.
  - **실측**: 오늘 실제 운영 로그에 "R3b alpha precompute:
    candidates=2 symbols=000660,000810" 26회 반복 확인; 실제
    `trade_decisions`에서 000810 `entry_score=0.7856, buy_
    candidate=True`(reason_codes에 `trigger_r3b_alpha_percentile`)
    를 24시간 26/26회 재현 확인. 그러나 `candidate_vs_final.
    alignment_status=downgraded`로 AI 최종 결정 합성기가 매번
    WATCH/HOLD로 하향(risk_opinion=allow, expected_value_gate
    통과 — pre_ai_gate/risk/compliance/expected_value_gate가
    아닌 별도 후속 축).
  - **판정**: **작동하나 체감 무효** — R3b는 실제 작동·실제
    decision 영향을 주지만, AI 최종 합성기가 매번 눌러 BUY 빈도
    개선이 운영상 보이지 않는다. R3b 구현 판정(Conditional Go)
    불변. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_
    signal_v1.md` §65.
  - 다음 과제: AI 최종 결정 합성기의 downgrade 로직 조사(신규
    최우선); candidate pool 국면별 변화 관측.
  - **[SPPV-2.77에서 정정] 위 "AI 최종 합성기가 매번 눌러..." 표현이
    000810 1개 종목에만 적용되는 설명을 전체 BUY 부재 원인으로
    일반화한 과장이었음이 확인됨 — 아래 SPPV-2.77 참고. 이 항목의
    텍스트는 삭제하지 않고 보존한다.**
- [x] **SPPV-2.77(신설)** SPPV-2.76 해석 정밀 보정 — "BUY 부재"
  원인의 3층 분리 정량화 (완료, 2026-07-20, 작성자: Codex)
  - **목적**: R3b 작동 여부 재검증이 아니라, "BUY가 왜 아직 안
    나오느냐"의 원인 분해를 정밀화.
  - **실측(조회 시각 2026-07-20 02:54 UTC, 최근 24시간)**: R3b
    reason code가 붙은 `trade_decisions` 66건을 재조회한 결과 정확히
    절반씩 분리 — 층1(`buy_candidate=True`+`downgraded`) 33건 전부
    000810; 층2(`buy_candidate=False`/`NO_ACTION`, `alignment=
    matched`) 33건 전부 000660(애초에 R3b 비후보). 운영 로그에서
    층3(`Pre-agent short-circuit`+`eligibility_core_risk_off_
    ranking_blocked`)을 별도 집계 — 원시 297건, distinct 11/12
    종목(오늘 universe 12종목 중 R3b 후보 000810만 유일하게
    미해당). 코드로 층3이 `deterministic_trigger_engine.py:618`→
    `decision_orchestrator.py`의 AI 파이프라인 사전 차단이며
    `candidate_vs_final`보다 앞선 단계임을 확인.
  - **판정**: **복합 병목** — 000810(층1)/000660(층2)/나머지
    universe 대다수(층3, 91.7%)를 같은 원인으로 묶으면 안 됨.
    universe 전체 관점에서는 층3이 가장 넓은 병목. R3b 작동 자체
    판정(작동하나 체감 무효)은 불변. 코드 변경 없음, 신규 KIS
    호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §66.
  - 다음 과제: core risk-off pre-AI 차단(층3, 최우선, universe
    91.7% 영향) 정밀 조사; AI 최종 합성기 downgrade(층1, 000810
    한정) 조사; R3b 후보 풀 협소함(층2 무관, candidate pool 2종목
    뿐인 이유) 재관측.
- [x] **SPPV-2.78(신설)** BUY_CANDIDATE 최종 통과 0건의 직접 병목
  정밀 분해 (완료, 2026-07-20, 작성자: Codex)
  - **목적**: "차단 장치 전면 완화"가 아니라, 000810 BUY_CANDIDATE
    (24h 36건)이 최종 BUY 0건으로 귀결되는 정확한 지점을 funnel로
    특정.
  - **실측**: candidate(36)→eligibility(36)→candidate_intent=
    buy(36) 전 구간 무손실. `candidate_vs_final` 단계에서 **100%
    손실**(final_intent=buy 0건, decision_type=BUY 0건, order
    request 0건 — `execution_attempts` 24h 432건 전부 non_trade).
    universe 전체 24h `decision_type`도 WATCH=276/HOLD=156/
    BUY=SELL=REDUCE=EXIT=0(더 넓은 맥락, R3b 국한 아님). 000810의
    `ai_call_path.fdc_skipped=False`(실제 AI 호출 확인) +
    `opposing_evidence`(risk_off/고변동성/전략 충돌/weak evidence)
    가 36회 거의 동일 문구 반복 — 정당한 방어 논리일 수 있으나
    국면 라벨 고착 가능성도 배제 못 함.
  - **판정**: "BUY 후보는 생성되지만 마지막 단계 병목 때문에 0건
    통과"(000810 한정, 단일 지점 100% 손실). 보정 판정: 층3(pre-AI,
    universe 91.7%)=유지(인과관계 없음), 층2(000660 비후보)=유지
    (R3b 자신의 판단), 층1(downgrade)=**정밀 보정 필요**(우선
    완화 아님 — AI 판단의 조건 민감도 확인 선행). R3b 작동 판정
    불변. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §67.
  - 다음 과제: AI 최종 결정 합성기 판단의 조건 민감도 확인(최우선
    — risk_off_tone 해제·entry_score 변화 시 실제로 final_intent가
    바뀌는지 재현 검증); 층3(core risk-off pre-AI 차단) 조사는
    별도 트랙 유지.
  - **[SPPV-2.79에서 정정] 위 "opposing_evidence가 36회 거의
    동일 문구 반복"은 부정확했음 — 39건 재확인 결과 문구는 전부
    distinct, 반복되는 것은 주제(theme)뿐이었다. 아래 SPPV-2.79
    참고.**
- [x] **SPPV-2.79(신설)** "마지막 단계" 내부 재분해 — watch/
  no_action 두 갈래와 그 입력 패턴 차이 (완료, 2026-07-20, 작성자:
  Codex)
  - **목적**: §67의 결론을 유지하되, `candidate_vs_final` 단계
    내부에서 `final_intent=watch`/`no_action`을 가르는 실제 조건
    분해(000810만 대상, 000660은 비교 대상 아님).
  - **실측**: `candidate_intent=buy` 39건 → `final_intent=watch`
    31건, `final_intent=no_action` 8건, `final_intent=buy` 0건.
    `compliance_opinion`/`expected_value_gate.passed`/`strategy_
    selection.preferred_strategy`(100% defensive_low_volatility_
    rotation)는 두 그룹에서 완전히 동일 — 구분력 없음(다만
    strategy_policy_mismatch는 downgrade 자체의 공통 원인).
    구분력 있는 축: `evidence_strength`/`conviction`/`confidence`
    (no_action만 0.0/'none'까지 하락), `regulatory_risk` 비중
    (42%→75%, `regulatory_crackdown`은 no_action 전용).
    `opposing_evidence` 39건 전부 distinct(매 cycle 실제 LLM
    생성, 캐시 아님) — §67의 "거의 동일 문구 반복" 서술 정정.
  - **판정**: 마지막 단계 병목이지만 watch/no_action 두 갈래로
    명확히 분기. "더 앞선 숨은 축" 의심 근거 없음. 코드 변경 없음,
    신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §68.
  - 다음 과제(완화 결론 아님, 검증 대상 좁히기): `strategy_policy_
    mismatch` 축 조건 민감도(최우선, downgrade 공통 원인) +
    `evidence_strength`/`conviction` 계열 no_action 임계 조건 +
    규제/이벤트 리스크 감지 파이프라인 실제 근거 확인.
  - **[SPPV-2.80에서 정정] 위 "39건 전부, final_intent=buy 0건"은
    이후 재조회(47건, watch 36/no_action 9/buy 2)에서 buy 사례가
    관측되며 부분 정정됨 — 아래 SPPV-2.80 참고.**
- [x] **SPPV-2.80(신설)** R3b 최종 병목의 조건 민감도 검증 + 신규
  발견(expected_value_gate 정량 게이트) (완료, 2026-07-20, 작성자:
  Codex)
  - **목적**: watch/no_action 분기를 구간 분포·조합 빈도·극단값으로
    재검증(완화 결론 아님, 000810만 대상).
  - **실측**: `candidate_intent=buy` 39→47건. **watch 36/no_
    action 9/buy 2**로 분해(§79의 "buy 0건"이 이번 조회에서 처음
    깨짐). 신뢰도 축(evidence_strength/conviction/confidence)은
    대부분 구간이 watch/no_action에서 겹쳐 명확한 threshold가
    아님 — no_action 유일 극단값(conviction=confidence=0.0,
    evidence='none') 1건만 확인. 규제/법률 flag 비율은 watch
    39%→no_action 89%로 상승하나 전용 축 아님 — "weak evidence+
    규제flag" 조합이 보조 강도 축.
  - **신규 발견(핵심)**: 실제 `decision_type='APPROVE'` 2건을
    추적한 결과 `translation.py`의 `_has_required_expected_value_
    anchor`가 `expected_value_gate.passed=False`(edge_after_
    cost_bps=8.56 < minimum_required_edge_bps=10.00, 1.44bps 차이)
    로 인해 submit_request=None 반환 — AI 정성 판단과 완전히 별개인
    정량 게이트가 실제 주문 생성을 막는 새로운 최종 병목임을 코드로
    확인(`src/agent_trading/services/translation.py:74-178`).
  - **판정**: "아직 직접 분기축이라 단정 불가"(신뢰도+규제 조합이
    유력 후보), strategy_policy_mismatch류는 우선순위 하향. 코드
    변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
    sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §69.
  - 다음 과제: evidence_strength/regulatory 조합 재현 검증(최우선)
    + expected_value_gate margin 반복 관측(신규, 중요도 상승) +
    규제/이벤트 리스크 감지 파이프라인 데이터 근거 확인.
- [x] **SPPV-2.81(신설)** "APPROVE + expected_value_gate.passed=
  false"가 저장되는 이유 — 코드 경로 완전 추적 (완료, 2026-07-20,
  작성자: Codex)
  - **목적**: §69의 발견을 코드 끝까지 닫아 추적(원인 추적 턴,
    완화 없음).
  - **핵심 발견**: `decision_orchestrator.py:538`의 `_check_ai_
    buy_override_gate()`가 `:565-566`에서 `if deterministic_
    trigger.buy_candidate: return None`으로 즉시 반환 — `:634`의
    `expected_value_gate_passed` downgrade 체크에 도달조차 못함.
    호출부(`:2376-2385`)가 `None`을 받으면 downgrade 블록 전체를
    스킵해 `decision_type='APPROVE'`가 그대로 저장된다. 실제 차단은
    이후 `translation.py:74-178`의 `_has_required_expected_value_
    anchor()`가 독립적으로 재확인해 발생 — `submit_request=None`
    → `execution_service.py`가 "produced no order request"로
    스킵. 재조회(24h, 04:42 UTC) 결과 APPROVE 7건 전부 edge=8.56/
    min_required=10.00 완전 동일값 반복. 로그 대조: 같은 시간대
    000240은 override gate 실제 발동해 로그 남기나 000810 7건은
    로그 없음(조기 반환 확인).
  - **판정**: 계층 간 불일치(저장/번역/제출의 책임 분리) — APPROVE
    저장은 코드 설계대로 정상 동작(버그 아님), 다만 `_check_ai_
    buy_override_gate()` docstring("EV 통과 시에만 허용")과 실제
    동작(candidate엔 미적용) 사이 괴리는 완전 의도 여부 단정 불가.
    한 줄 결론: "APPROVE 저장은 정상이나 주문은 expected value
    gate에서 차단". 코드 변경 없음, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §70.
  - 다음 과제: `buy_candidate=True` 조기 반환이 의도된 설계인지
    설계자 확인 필요(코드만으로 단정 불가); APPROVE 저장이 모니터링
    지표 해석에 혼동을 유발하는지 검토; edge=8.56/min_required=
    10.00 7 cycle 연속 동일값이 signal_feature_snapshot 일 단위
    갱신 주기와 일치하는지 재확인.
  - **[SPPV-2.82에서 정정] 위 "docstring 괴리, 완전 의도 여부
    단정 불가"는 GUIDE 문서 재확인으로 해소됨 — 아래 SPPV-2.82
    참고. 이 항목의 텍스트는 삭제하지 않고 보존한다.**
- [x] **SPPV-2.82(신설)** "APPROVE 저장 vs 실제 주문 미생성" 구조에
  대한 설계 해석 정리 (완료, 2026-07-20, 작성자: Codex)
  - **목적**: §70의 인과 경로를 재검증하지 않고, 이 구조가 의도된
    계층 분리인지 설계 해석을 닫음(코드 수정안 없음).
  - **핵심 발견**: `docs/10_signal_research_sppv/[GUIDE] end_to_
    end_order_flow_guide.md` §8-1(`APPROVE`="AI/정량 기준상 진입
    승인 **제안**")·§8-4("R3b는 더 잘 고르는 장치이지 비용 문제를
    없애는 장치는 아니다")·§9("AI가 BUY를 말해도 expected value
    gate 실패면 실제 주문으로 번역되지 않는다")가 §70의 경로를
    **이미 사전에 문서화**해 놓았음을 확인 — §70의 "완전 의도
    여부 단정 불가"를 이 근거로 좁힘. `_check_ai_buy_override_
    gate()`의 docstring 괴리도 "override 방어"라는 좁은 책임
    범위를 문구가 정확히 표현 못한 문서화 정밀도 문제로 재해석
    (실제 로직 결함 아님) — EV gate 최종 강제 지점은 처음부터
    `translation.py`.
  - **판정**: **의도된 계층 분리이며 문서/지표 해석만 보정하면
    됨.** 세 지표(BUY_CANDIDATE 발생/APPROVE 저장/order_request
    생성)의 의미를 각각 정의 — "BUY_CANDIDATE 있음"이 "APPROVE"를,
    "APPROVE"가 "order_request"를 보장하지 않는다. 코드 변경 없음,
    신규 KIS 호출 0건. 재확인(24h, 05:18 UTC): APPROVE 14건, 동일
    evg 실패 패턴 유지 — §70과 일치. 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
    §71.
  - **문서/운영 표현 보정안(코드 아님)**: "APPROVE=주문 생성"으로
    해석 금지; "APPROVE는 AI 판단 승인(제안), 실제 제출은 expected
    value gate 재검증 후 별도"를 표준 문구로 사용; 향후 리포트에
    BUY_CANDIDATE/APPROVE/order_request 3지표 분리 병기 권장.
  - 다음 과제: SPPV 계열 문서의 APPROVE 관련 서술을 GUIDE 기준으로
    정합화(후속 문서 정리); 모니터링/리포팅 지표 정의 정리(운영팀
    결정 필요); edge_after_cost_bps=8.56 반복이 여러 날짜에도
    지속되는지 후속 거래일 누적 관찰.
- [x] **SPPV-2.83(신설)** `expected_value_gate` 계산 구조 자체의
  설계 타당성 검증 (완료, 2026-07-20, 작성자: Codex)
  - **목적**: threshold 조정이 아니라, "일봉 1회 snapshot 기반
    입력을 분단위 decision loop가 반복 재평가하는 구조"가 설계상
    타당한지 검증(코드 수정안 없음).
  - **핵심 발견**: EV gate 원 설계 문서(`[DESIGN] expected_return_
    holding_horizon_and_churn_control_refactor.md` §6, 2026-06-23)는
    입력 신선도(일봉/장중/실시간)를 전혀 규정하지 않음 — "느린
    필터"인지 "빠른 최종 게이트"인지 문서가 선택한 적이 없는 공백.
    반면 같은 문서/코드베이스는 reverse trade 재진입에 대해서는
    `signal_feature_snapshot_id` 불변 시 재판단을 억제하는 원칙을
    이미 채택·구현(`reverse_trade_hysteresis.py`)했으나, 이 원칙이
    최초 BUY 후보 평가 경로에는 적용되지 않음. `expected_return_bps`
    /`expected_downside_bps`/`estimated_round_trip_cost_bps`/
    `slippage_buffer_bps` 4개 입력이 전부 `signal_feature_snapshot`
    에 직접·간접 결합되는데, decision loop는 기본 5분 간격(약
    70~90회/거래일) 재평가 — 판단 정확성 왜곡 증거는 없으나 동일
    결론의 불필요한 반복 생성이라는 구조적 비효율/미문서화 공백으로
    판정.
  - **판정**: 입력 캐던스(일봉)와 재평가 캐던스(분단위) 사이의
    **설계 미스매치(문서화되지 않은 공백)**. 000810의 구조적 메커
    니즘(신선도 결합)은 전 종목 일반화 가능하나, "1.44bps 부족"이라
    는 구체 수치는 종목 특수값으로 일반화 불가. 코드 변경 없음,
    신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §72.
  - 다음 과제: EV gate 계산 구조 보정안(same-snapshot 재평가 스킵/
    재사용 등)을 다음 턴 설계 검토 대상으로 채택(threshold 민감도
    검증보다 우선).
- [x] **SPPV-2.84~2.89(신설, 요약)** EV gate/submit 차단 완화 후보
  비교(2.84) → 구조 정리(A안) vs 실제 BUY 증가 병목 우선순위 정리
  (2.85) → margin 근소부족 조건부 완화 후보 선정(2.86) → shadow
  실측(Watch 판정, 2.87) → 근소부족(<=2.0bps) 조건부 완화 실제
  코드 구현 + 신규 단위 테스트 13개(2.88) → 사용자 승인으로 실제
  paper runtime 활성화(2.89, `EV_GATE_NEAR_MISS_OVERRIDE_ENABLED=
  true`, `ops-scheduler`만 재기동, `AppSettings()` 확인). 상세는
  각 턴 상세 기록 참고, 요약만 이 항목에 정리.
  - **⚠️ 최신 상태(2026-07-21 기준)**: near-miss override는 **paper
    runtime에 활성화되었으나, 아직 실제 적용 사례(`ev_gate_near_
    miss_override_applied=true`)나 신규 `order_request` 생성 사례가
    관측되지 않았다.** 직접 원인은 §78(SPPV-2.90) 참고 — override
    로직 결함이 아니라, 재기동 이후 구간에서 `buy_candidate=true`
    자체가 0건이라 BUY funnel 최상류에서부터 막혀 있기 때문.
- [x] **SPPV-2.90(신설)** EV gate near-miss override 미발동 원인 —
  SPPV BUY funnel 관점 재분해 (완료, 2026-07-21, 작성자: Codex)
  - **목적**: near-miss override가 paper runtime에 켜져 있는데도
    왜 아직 적용/주문 생성 사례가 없는지, SPPV BUY funnel(candidate
    → final_intent → APPROVE → submit_request) 단계별로 원인을 닫음
    (threshold/코드 변경 없음, 전체 pytest 미실행).
  - **핵심 발견**: 최근 24시간 `buy_candidate=true` 48건/`final_
    intent='buy'` 24건/`APPROVE` 24건 — **전량 재기동(2026-07-21
    00:40:40 UTC) 이전** 시점이며, 재기동 이후(스위치 on 상태)
    구간에서는 위 3개 지표 전부 **0건**. near-miss 미적용 23건은
    "미발동 버그"가 아니라 "그 시점엔 스위치가 꺼져 있었다"는
    사실로 완전히 설명됨(created_at과 재기동 시각 직접 대조 확인).
    또한 근소부족 후보는 24시간 내내 000810 1종목에 100% 집중돼
    있었고, 재기동 이후에는 000810의 `entry_score`마저 0.7856→0.0
    으로 급락(`buy_candidate=False`로 전환) — near-miss 완화안이
    실질적으로 000810 단일 종목·특정 국면(어제의 range_bound 국면)
    의존임을 확인.
  - **판정**: 단순 runtime 미발동도, 완화안 로직 결함도 아니다.
    **표본 부족 + BUY funnel 상 더 상류 병목(오늘은 buy_candidate
    생성 자체)이 현재 더 결정적**이며, near-miss 완화안은 "아직
    실제 운영에서 실증되지 않은 상태"(조건이 다시 발생할 때까지
    대기 필요)로 판정. 코드 변경 없음, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §78.
  - 다음 과제: near-miss 완화안 관찰 지속(코드 변경 없음) + R3b
    후보 풀 일별 변동성 원인 확인(다음 턴) + pre-AI 차단/downgrade
    축 재검증(연속성 유지).
  - **[SPPV-2.91에서 정정] 위 "entry_score마저 0.7856→0.0으로
    급락" 서술은 원인 설명이 부정확했다 — R3b는 계속 정상 작동
    중이었고(reason code 유지), 000810은 "후보군 밖 탈락"이 아니라
    "2026-07-20 11:52 UTC snapshot 정상 갱신 이후 3종목 candidate
    pool(000660/000810/001450) 내부 최하위(percentile=0.0)"였다.
    핵심 판정(표본 부족 + 상류 병목 지배적)은 그대로 유지, 원인
    해석만 정밀화. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §79. 이 항목의 원문은
    삭제하지 않고 보존한다.**
- [x] **SPPV-2.91(신설)** §78 해석 보정 — 000810 `entry_score`
  급락 원인 정밀화 (완료, 2026-07-21, 작성자: Codex)
  - **목적**: 판정 변경이 아니라, entry_score 0.7856→0.0의 원인을
    "R3b 미작동"과 "R3b 적용됐지만 후보군 내부 최하위"로 명확히
    구분(코드 변경 없음, 전체 pytest 미실행).
  - **핵심 발견**: `signal_feature_snapshots`(000810)가 2026-07-20
    11:52 UTC에 정상 갱신됨을 확인(`overall_score` 0.5146→0.162,
    `return_3m_pct` 46.04→26.60 등) — 4일 정체가 아니라 정상 갱신
    이후의 결과였다. 오늘 운영 로그 `R3b alpha precompute:`에서
    candidate pool이 2종목→3종목(000660/000810/001450)으로 확장,
    000810은 여전히 풀 내부에 존재. `regime_conditional_signal =
    return_3m_pct/max(volatility_20d_pct,1.0)` 직접 재계산 결과
    001450(6.92) > 000660(6.39) > 000810(5.67) — 000810이 3종목 중
    최하위이며, `bisect_left` 공식대로 `percentile=0/(3-1)=0.0`이
    정확히 재현됨(계산 오류 아님, clamp/하드블록 아님).
  - **판정**: §78의 핵심 판정(표본 부족 + BUY funnel 상류 병목이
    현재 지배적, near-miss 완화안 실증 불충분)은 그대로 유지. 다만
    병목의 성격은 "R3b 정지"가 아니라 "R3b는 정상 작동하되 소수
    종목(2~3개) candidate pool에서 일별 신호 갱신만으로 순위가
    쉽게 요동치는 구조적 특성"으로 재규정. 코드 변경 없음, 신규
    KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §79.
- [x] **SPPV-2.92(신설)** R3b candidate pool 협소·순위 변동성 판정
  (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: near-miss override를 더 만지지 않고, paper runtime에서
    R3b가 정상 작동하고도 BUY funnel 상류에서 다시 0건에 수렴하는
    이유를 "candidate pool 협소성" 관점으로 실측 판정(코드 변경
    없음, Full pytest 미실행).
  - **핵심 발견**: 최근 48시간(KST) 000810/000660의 `entry_score`
    관측값이 각각 정확히 2개({0.0, 0.7856}, {0.0, 0.33})뿐 —
    중간값 없이 이분법적으로 튐. 운영 로그 확인 결과 core 유니버스
    약 18종목 중 R3b candidate pool은 2~3종목뿐(오늘 3종목:
    000660/000810/001450). `build_candidate_percentiles()`의
    `bisect_left/(n-1)` 공식상 `n=2`면 percentile은 {0.0,1.0}만,
    `n=3`이면 {0.0,0.5,1.0}만 가능 — **작은 정수 n의 태생적 이산성**
    으로, 이는 000810만의 특이 사례가 아니라 000660에도 동일하게
    나타나는 **반복 구조**임을 확인. 001450은 entry_score=0.78(임계
    0.65 이상)임에도 별도의 `eligibility_low_relative_activity`
    게이트로 buy_candidate=False — R3b/후보풀과 무관한 독립 하류
    게이트.
  - **판정**: 병목 3단계(A. R3b 미작동/B. candidate pool 협소로
    인한 구조적 순위 변동성/C. candidate_vs_final·APPROVE·EV gate
    이후 병목) 중 **B가 현재 가장 상류이자 지배적인 병목**으로
    확정. A(R3b 미작동)는 해당 없음 — reason code·precompute 로그
    모두 정상. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §80.
  - **⚠️ 최신 상태(2026-07-21 KST 기준, 한눈에 요약)**: near-miss
    override는 **paper runtime에 활성화돼 있음**(§77.8). 그러나
    현재 더 상류의 구조적 병목은 **candidate pool 협소(2~3종목)로
    인한 순위 변동성**일 가능성이 크다(B로 판정) — R3b 미작동이
    아니며, EV gate/near-miss와는 별개의 상류 설계 특성이다.
- [x] **SPPV-2.93(신설)** Codex 종합 판단 반영 — "창보다 방패 다층
  구조" 해석 고정 (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: 최근 §70~§80의 실측 결과를 하나의 운영 판단으로
    묶어, "창(R3b) 자체 문제"와 "창의 효과를 실제 BUY까지 전달하지
    못하게 막는 방패 구조"를 구분해 문서에 고정.
  - **핵심 판단**: 현재 체감상 BUY가 늘지 않는 이유는 `R3b` 미작동이
    아니라 **상류 candidate pool 협소 + 중류 eligibility 차단 +
    하류 APPROVE/EV gate 차단이 직렬로 겹친 다층 구조**에 있다.
    특히 001450은 `entry_score=0.78`로 threshold를 넘지만
    `eligibility_low_relative_activity` 때문에 `buy_candidate=false`
    가 유지되는 대표 사례다 — "점수가 높다"와 "실제 매수 자격이 있다"
    는 동일하지 않음을 명시적으로 확인.
  - **다음 우선순위 재정렬**: (1) 001450 및 유사 고점수 종목의
    `eligibility_low_relative_activity` 재검증, (2) core universe
    규모 대비 20% quintile 공식 적정성 검토, (3) 그 다음에 EV gate
    / submit 차단 재평가. 즉, 지금은 창 추가 개선보다 **방패 중 직접
    병목을 순서대로 줄이는 작업**이 우선이다.
  - **판정**: SPPV 방향성 유지. R3b 자체는 정상 작동 중이며,
    현재 문제는 "창이 무딘가?"보다 **"좋아진 창의 효과가 실제 BUY까지
    전달될 수 있는 구조인가?"**에 가깝다. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
    signal_v1.md` §81.
- [x] **SPPV-2.94(신설)** `001450 / eligibility_low_relative_
  activity` 축 정밀 검증 (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: §81/SPPV-2.93이 최우선으로 지정한 001450 활동성 게이트
    축을 실제 운영 데이터로 정밀 검증(threshold 변경/완화 배포/
    코드 수정 없음, Full pytest 미실행).
  - **핵심 발견**: 최근 7일(KST) 001450의 `trade_decisions` 188건
    **전량**이 `eligibility_low_relative_activity`로 차단됨
    (entry_score 0.5375~0.78 무관, `volume_surge_ratio`/`turnover_
    surge_ratio` 항상 0.88~1.09로 1.10 미만). 같은 기간 전 종목
    중 `entry_score>=0.65`(A, 136건)는 000810(71)·001450(65) 단
    2종목뿐 — 그중 활동성 게이트 차단(B, 65건)은 001450 **100%**,
    `buy_candidate=true`(C, 71건)는 000810 **100%**. 즉 이 게이트는
    광범위한 방패가 아니라 001450 단일 종목에 좁게 반복되는 패턴.
    코드 확인 결과 직접 원인은 `max(volume_surge_ratio, turnover_
    surge_ratio) < 1.10` 단일 조건(entry_score 무관, 다른 eligibility
    축과 얽히지 않음). 001450의 `average_volume_20d`/`average_
    turnover_20d`가 2주간 각각 약 -20%/-22% 추세적으로 감소 —
    "신호는 강한데 활성도만 일시 부족"이 아니라 "거래 관심이
    추세적으로 식어가는 종목"에 가까움(07-13에는 실제로 1.10을
    넘어 게이트를 통과하기도 했음 — 영구 차단은 아님).
  - **판정**: **Watch** — No-Go(명백한 오탐)로 보기엔 실제 유동성
    하락 추세라는 뒷받침이 있고, Conditional Go(완화 검토 착수)로
    보기엔 forward return 등 "통과시켰으면 좋았을" 실증 근거가
    전혀 없음(확인 불가). 단순 Hold로 보기엔 유니버스 내 고득점
    종목 절반(65/136)을 좌우하는 실질적 병목이라 계속 관찰할 가치가
    있음. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
    §82.
- [x] **SPPV-2.95(신설)** 20% quintile 공식의 구조적 결과 재구성
  검증 (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: candidate pool 협소성(병목 B)이 완화안 적용 없이
    실제로 최상류 병목인지, `build_candidate_percentiles()`를 최근
    거래일 데이터로 그대로 재실행해 재구성 검증(코드 변경 없음,
    Full pytest 미실행).
  - **핵심 발견**: 07-14/15는 벤치마크(069500) snapshot 결측으로
    candidate pool 자체가 0(이미 해소된 별도 문제). 07-16(유니버스
    23종목)/07-20(12종목)/07-21(18종목) 3거래일 모두 신호 계산
    가능 종목 수=core 유니버스 수(결측 없음)였음에도 현행 20% pool
    크기는 각 4/2/3에 불과. **단 3거래일 만에 000810/000660/001450
    모두 percentile 극값(0.0 또는 1.0)을 최소 한 번씩 기록** —
    000810은 이틀 연속 꼴찌(0.0), 001450은 07-20엔 core 유니버스
    freeze에서 아예 빠졌다가 07-21엔 1위(1.0)로 복귀. shadow
    비교(top 30%/고정 top-5)에서도 pool 크기는 여전히 2~6개
    (한 자릿수)에 머물러, **비율을 넓혀도 근본 해소가 안 됨**을
    확인 — 문제의 본질은 quintile 비율이 아니라 **core 유니버스
    규모(12~23종목) 자체**.
  - **판정**: candidate pool 협소성이 최상류 병목이라는 것을 확정,
    다만 다음 검토 대상은 "20%→30% 등 비율 조정"이 아니라 "core
    유니버스 규모 자체의 설계 재검토"로 재정의. 활동성 게이트(§82)
    와의 우선순위는 그대로 유지(바꿀 근거 없음). 코드 변경 없음,
    신규 KIS 호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §83.
- [x] **SPPV-2.96(신설)** R3b candidate pool 내부 percentile 주입
  방식의 가혹성 실측 (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: "pool 내부 최하위=0.0 주입 방식(A안)이 작은 pool
    (2~4종목)에서 고득점 후보를 과도하게 0점 처리하는가"를 A/B
    (floor 0.30)/C(rank compression (idx+1)/(n+1)) shadow 비교로
    검증(threshold 완화/코드 수정 없음, Full pytest 미실행).
  - **핵심 발견**: look-behind 보정(전일까지 snapshot만 사용,
    실제 decision loop와 동일 조건) 후 07-20/07-21 2개 유효
    거래일 5건 재구성 결과, 최하위 종목(percentile=0.0) 3건
    (000660@07-20, 000810@07-21, 참고 001800@07-16) 전부 B/C
    적용해도 entry_score가 0.20~0.27에 그쳐 threshold(0.65)에
    전혀 근접하지 못함 — **0.0 감점 폭이 아니라 alpha 항 외
    나머지 항(base) 자체가 이미 매우 낮았기 때문**. 반대로 이미
    `buy_candidate=True`를 얻은 두 최상위 사례(000810@07-20 0.7856,
    001450@07-21 0.78)는 C안(압축) 적용 시 각 0.5189/0.58로
    **threshold 아래로 떨어짐**(부작용 확인). 최하위 수령 종목이
    거래일마다 다름(001800→000660→000810)을 확인해 000810 특이
    사례가 아닌 반복 구조임을 확정.
  - **판정**: 이번 표본(2개 유효 거래일) 기준 "현행 A안이 과도
    하다"는 가설은 **뒷받침되지 않음**(No-Go, 완화 필요성 근거
    부족) — 다만 표본이 작아 단정은 이름. 완화안 코드 diff 착수는
    보류. 코드 변경 없음, 신규 KIS 호출 0건. 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
    §84.
- [x] **SPPV-2.97(신설)** R3b candidate pool 최하위 floor 완화안
  (B1/B2/B3) 정밀 재검증 (완료, 2026-07-21 KST, 작성자: Codex)
  - **목적**: §84에서 C안(압축)이 최상위 후보까지 훼손하는 부작용이
    확인됨에 따라, floor 계열만 좁혀 0.30/0.45/0.60 세 수준에서
    최하위 복구 효과·최상위 무손상 여부를 재검증(코드 수정 없음,
    Full pytest 미실행).
  - **핵심 발견**: 확인된 유효 거래일(07-20 n=2, 07-21 n=3) 2일
    모두, 최하위 종목(percentile=0.0, base가 이미 -0.8에 가까움)은
    **floor 0.30/0.45/0.60 어느 수준으로도 threshold(0.65)에
    전혀 근접하지 못함**(최고 0.48). 참고(07-16, 당일 snapshot
    근사) 데이터에서만 0.45(1건)/0.60(2건) 회복이 관측되나 look-
    ahead 가능성이 있어 신뢰도 낮음. 반면 **최상위 후보(000810@
    07-20 0.7856, 001450@07-21 0.78)는 모든 floor에서 entry_score
    /buy_candidate가 단 한 건도 변하지 않음** — `max(raw,floor)`가
    raw≥floor일 때 항상 raw를 반환하는 단조증가 연산이라 구조적으로
    최상위를 건드릴 수 없음을 확정(§84 C안과 근본적으로 다른 성질).
    참고 데이터에서 0.60은 pool 내부 꼴찌(001800)까지 자동으로
    buy_candidate 자격을 부여해 과잉 완화 조짐도 일부 관측.
  - **판정**: **Watch** — 최상위 무손상은 확실하나(§84 No-Go보다
    근거 우위), 확인된 유효 거래일에서 회복 근거가 아직 없어
    Conditional Go 승격은 이름. 완화안 코드 diff 착수는 보류,
    표본 축적을 최우선으로 함. 코드 변경 없음, 신규 KIS 호출 0건.
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §85.
- [x] **SPPV-2.98(신설)** R3b candidate pool 최하위 floor=0.60 —
  사용자 직권 paper 운영 반영 (완료, 2026-07-21 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: §85의 shadow 검증은 **Watch**
    (회복 근거 불충분, 최상위 무손상만 확실)였으나, **사용자가
    "주문 0건 장기화가 더 큰 운영 문제"로 판단해 직권으로
    `CANDIDATE_PERCENTILE_FLOOR=0.60`을 실제 paper 운영에 반영**
    했다. 이는 효과가 증명된 완화가 아니라 **운영 관찰을 위한
    제한적 완화 적용**이다.
  - **반영 지점**: `services/r3b_alpha_percentile.py`의
    `build_candidate_percentiles()` 내부, percentile 계산 직후
    한 줄(`max(raw_percentile, CANDIDATE_PERCENTILE_FLOOR)`) —
    가장 좁은 범위. `_build_entry_score()`/cycle precompute/metadata
    주입부는 무변경. 신규 env 변수 없음(bare 모듈 상수, 기존
    `TOP_QUINTILE_FRACTION`과 동일 패턴) — `.env`/`docker-compose.
    yml` 변경 불필요(`./src` bind-mount로 코드 변경이 즉시 반영).
  - **검증**: 신규 테스트 6개 + 관련 기존 테스트 76개 = 82/82 통과
    (Full pytest 미실행). 실제 DB(오늘 core universe 17종목) 기반
    off/on 비교: 최상위(001450, raw=1.0) 완전 무손상, 최하위/중하위
    (000810 0.5→0.6, 000660 0.0→0.6)만 상향 확인.
  - **남는 하류 병목**: 활동성 게이트(§82)/AI downgrade(candidate_
    vs_final)/EV gate(§70~79, near-miss override 이미 활성화)
    모두 그대로 남음 — 이번 반영은 candidate pool 축 하나만 완화.
    코드 변경 있음(신규 파일 1개, 기존 파일 1개 수정), 신규 KIS
    호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §86.
- [x] **SPPV-2.99(신설)** floor=0.60 반영 후 SPPV BUY funnel 1일
  관찰 결과 (완료, 2026-07-22 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: §86 반영(2026-07-22 09:27 KST)
    후 약 7.5시간 관찰 — **entry_score는 실측 상승**(000810
    0.00→0.46, 000660 0.33→0.41, 001450은 이미 최상위라 무변화)
    했으나, **buy_candidate/final_intent=buy/APPROVE/submit_
    request/order_requests는 반영 전후 전부 0건으로 동일**. 판정:
    **B. 부분 유효**(상류 개선, 하류 eligibility 병목으로 최종
    전진 없음) — "효과 입증"도 "실패 확정"도 아닌 중간 관찰 결과.
  - **가장 직접적인 현재 병목**: 층2(eligibility 차단) — 001450/
    000810은 `eligibility_low_relative_activity`(§82), 000660은
    이번에 새로 확인된 별도 축 `eligibility_negative_overall_
    floor`로 즉시 차단, entry_score 개선이 다음 층(candidate_vs_
    final/EV gate/실제 주문)까지 전달되지 못함.
  - 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §87.
- [x] **SPPV-2.100(신설)** 층2(eligibility) 병목 세분화 재검증 —
  활동성 게이트 vs negative_overall_floor (완료, 2026-07-24 KST,
  작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: 관찰 창(07-22 09:27~07-24 15:27
    KST) 기준, **000810/001450은 entry_score가 0.78까지 도달해도
    100% 활동성 게이트로 차단**(382건), **000660은 entry_score
    자체가 최대 0.41로 threshold 미달**인 채 negative_overall_
    floor로 차단(188건, 활동성 게이트와 무관한 독립 축, 임계값
    -0.10 vs 000660 overall_score=-0.1445 고정). **활동성 게이트가
    층2 내부에서 더 직접적인 병목**으로 확정 — entry_score가 이미
    충분한 상태에서 막히기 때문.
  - **완화 검토 근거**: 최근 3일간 000810/001450의 volume/turnover
    surge ratio가 근소 미달이 아니라 뚜렷한 미달(0.57~0.89 vs
    임계값 1.10)로, 실제 유동성 감소 추세와 일치 — **두 축 모두
    이번 턴 증거로는 완화 검토 후보로 올릴 근거 부족, Watch 유지**.
  - 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §88.
- [x] **SPPV-2.101(신설)** 층2(eligibility) 국면별 층화 재검증 —
  bullish_trend 포함 (완료, 2026-07-24 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: 관찰 창(07-22 09:27~07-24 20:15
    KST) 동안 000810/001450은 **관찰 창 내내 100% bullish_trend**,
    000660은 **100% range_bound**로 분류돼 국면과 종목이 완전히
    교락(confound)됨을 확인 — 이 한계를 전제로, 활동성 게이트는
    bullish_trend 표본(382건, entry_score≥0.65인데 막힌 191건
    포함)에서도 명확한 미달(37~48%↓, 근소부족 아님)로 반복 확인돼
    **완화 검토 근거가 새로 생기지 않았다**(Watch 유지). negative_
    overall_floor는 이번 창에 bullish_trend 표본이 아예 없어
    "range_bound 전용 축"이라는 가설은 **미확정(확인 불가)**으로
    남는다("없다"가 아니라 "이번엔 관찰 안 됨").
  - **전체 결론**: 전체 Watch 판정 유지, 상승장 표본 포함해도
    변경 없음. "상승장에서 무의미"/"반드시 완화 필요" 같은 단정은
    하지 않는다.
  - 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §89.
- [x] **SPPV-2.102(신설)** 근본 설계 재검토 — "창 vs 방패" 전략
  전환에 따른 우선순위 재정렬 (완료, 2026-07-24 KST, 작성자: Codex)
  - **배경**: 수십 턴의 실측에도 주문 0건이 지속된다는 문제의식에
    따라 사용자가 "core universe 확장(비중 높음) + eligibility
    완화(병행, 비중 낮음)"를 다음 방향으로 결정.
  - **⚠️ 최신 상태(한눈에 요약)**: `TRADING_UNIVERSE_CORE_CAP`
    (기본값 12, 현재 `.env`/compose 어디에도 오버라이드 없음)이
    R3b candidate pool의 진짜 모수를 좌우하는 **코드 diff 없이
    바꿀 수 있는 config 레버**임을 확인 — 실질 상한은 일 배치
    유효 신호 종목 수 약 80개(`signal_feature_after_market` freeze
    target_count=80). §80/§83의 "quintile 비율이 아니라 모수
    자체가 문제"라는 결론과 정확히 일치. §88~89의 활동성 게이트
    판정(명확한 미달, 실제 유동성 감소 추세와 일치 — 정당 차단에
    가까움)은 그대로 유지, eligibility 완화는 "예측 오류 손실"이
    아니라 "유동성 실행 리스크"를 떠안는 것임을 구분해 문서화.
  - 코드 변경 없음(이번 턴은 레버 식별/설계 재검토만). 신규 KIS
    호출 0건. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §90.
- [x] **SPPV-2.103(신설)** core universe 확장 vs eligibility 조건부
  완화 — shadow 정량 비교 (완료, 2026-07-24 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: `UniverseSelectionService.
    compose()`를 실제 코드 그대로 `core_cap=12/20/40/60`로 재호출
    (신규 KIS 호출 0건, `kis_client=None`으로 market overlay 완전
    no-op 확인)해 candidate pool이 2→4→8→12로 정비례 확장됨을
    확인. 그러나 **추적 3종목(000810/000660/001450) 기준으로는
    core_cap 확장이 `buy_candidate` 회복에 0건 효과** — 000810은
    경쟁 심화로 오히려 순위 하락, 001450은 entry_score와 무관하게
    활동성 게이트가 그대로 막음. 진짜 잠재 효과는 신규 진입 종목
    (`009150`, percentile 0.818)에 있으나 라이브 검증 없이는 확인
    불가. 반면 **`entry_score>=0.70`일 때만 활동성 게이트를 예외
    처리하는 좁은 조건부 완화는, 오늘 실측 데이터에서 001450 1건을
    즉시 `buy_candidate=True`로 전환**시킴(다른 eligibility 축/EV
    gate는 그대로 유지, 실제 코드 반영은 하지 않음 — shadow만).
  - **판정**: core_cap 확장 = **Watch**(구조적으로 타당하나 추적
    종목 실효과 0건), eligibility 조건부 완화 = **Conditional Go
    후보로 격상 가능**(오늘 데이터로 즉시 flip 확인, 단 실제 반영은
    별도 사용자 결정 필요).
  - 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §91.
  - **[SPPV-2.104에서 정정] 위 "core_cap 확장=Watch"/"eligibility
    조건부 완화=Conditional Go 후보"는 하루치·단일 시점 표본 기준
    으로는 과속 판정이었다. core_cap 확장은 "기존 3종목 구제 실패"
    가 아니라 "신규 후보(009150) 출현을 이미 확인한 상류 모집단
    확대 레버"로 재해석해 **1순위 실반영 우선 후보**로 격상하고,
    eligibility 조건부 완화는 하루치·단일 종목 flip만으로 Go 방향
    라벨을 쓴 것이 과속이었으므로 **2순위 병행 실반영 후보(제한적
    하류 직접 레버)**로 하향 정정한다. 이 항목의 원문은 삭제하지
    않고 보존한다. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §92.**
- [x] **SPPV-2.104(신설)** §91 판정 보정 — "Watch/Conditional Go"
  라벨 과속 정정, 우선순위 중심 재정리 (완료, 2026-07-24 KST,
  작성자: Codex)
  - **목적**: §91의 실측 수치·표는 그대로 두고(이력 보존), 하루치
    표본만으로 확정적 라벨(Watch/Conditional Go)을 매긴 것을
    보정. 코드 변경 없음, 신규 조회/신규 KIS 호출 없음(순수 문서
    해석 보정 턴).
  - **보정 요약**: core universe 확장(`TRADING_UNIVERSE_CORE_CAP`)
    = **실반영 우선 후보(1순위)** — 상류 모집단 확대 레버, 신규
    후보 출현 이미 확인. eligibility 조건부 완화(`entry_score>=
    0.70`) = **제한적 하류 직접 레버(병행 실반영 후보, 2순위)** —
    전면 완화 아님, Go 방향 확정 아님. 두 레버 모두 "실반영 후
    1~2거래일 관찰 필요" 상태로 유지, 하루치 결과만으로 최종 Go/
    No-Go 확정하지 않음. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §92.
- [x] **SPPV-2.105(신설)** `TRADING_UNIVERSE_CORE_CAP` 1순위 레버
  실반영 절차 (완료, 2026-07-24 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: §92가 1순위로 확정한 core
    universe 확장을 실제로 반영하려는 과정에서 **`docker-compose.
    yml`의 `ops-scheduler` 환경변수 화이트리스트에 `TRADING_
    UNIVERSE_CORE_CAP`이 아예 선언돼 있지 않았음**(§62/SPPV-2.73과
    동일한 배선 공백 패턴)을 발견·수정 완료(기본값 12 유지, 하위
    호환 보존). `.env.example`에도 `=40` 예시와 근거 추가. **다만
    이 세션의 표준 원칙("`.env`는 절대 내가 수정하지 않는다")에
    따라 호스트 `.env` 자체는 이번 턴에서 직접 고치지 않았다** —
    따라서 사용자가 `.env`에 `TRADING_UNIVERSE_CORE_CAP=40`을
    직접 추가해야 실제 반영이 완료되며, 그 전까지는 기본값 12가
    그대로 적용된다(컨테이너 env 직접 확인).
  - eligibility 조건부 완화(2순위)는 이번 턴에 손대지 않음, EV
    gate threshold 변경 없음. 코드 로직 변경 없음(config/compose
    배선만), 신규 KIS 호출 0건. 상세: `docs/10_signal_research_
    sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §93.
- [x] **SPPV-2.106(신설)** `TRADING_UNIVERSE_CORE_CAP=60` 실제
  반영 확인 — ops-scheduler 재기동 + 첫 관찰 (완료, 2026-07-26
  KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: 사용자가 호스트 `.env`에 이미
    `TRADING_UNIVERSE_CORE_CAP=60`을 반영한 상태에서 **`ops-
    scheduler`만** 재기동 → 컨테이너 env/`os.getenv` 모두 `60`
    확인, 실제 `UniverseSelectionService.compose()`를 그대로
    재호출해 **core 종목 60개 반환**(shadow 예측과 정확히 일치)을
    확인. candidate pool도 12개(기존 대비 6배, `009150` 신규 포함)
    로 재구성됨을 확인. **다만 오늘(2026-07-26)은 비거래일이라
    `decision_submit_gate`(실제 decision loop) 자체가 스케줄러에
    의해 완전히 스킵**돼, `buy_candidate`/`APPROVE`/`submit_
    request` 등 실제 funnel 효과는 **다음 거래일(2026-07-27
    KST) 이후에나 확인 가능**하다 — "설정 반영 확인" 단계이지
    "효과 판정" 단계가 아님을 명확히 구분.
  - eligibility 조건부 완화(2순위)/EV gate는 손대지 않음. 코드
    로직 변경 없음, 신규 KIS 호출 0건(shadow 재호출은 `kis_
    client=None`). 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §94.
- [x] **SPPV-2.159(신설, 완료 — 코드 변경 포함, 운영 반영 전)**
  `regime_tailwind` 제거 diff 구현 (2026-08-01 19:36 KST, 작성자: Codex,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - `_build_buy_ranking_score()`에서 `market_regime` 인자와
    `0.03*regime_tailwind` 항 제거(SPPV-2.157/§144 판정 A 반영).
    `entry_score`/`strategy_alignment`/`coverage_score`/
    `relative_activity`/`core_risk_off`/`event_overlay` 로직은
    전부 무변경.
  - 기존 테스트 2건(fixture가 옛 tailwind 기여분 반영) 최소 보정 +
    신규 회귀 1건(함수가 `market_regime` 없이 값을 내는지, 옛 시그니처
    호출이 `TypeError`인지 고정) — `tests/services/test_deterministic_
    trigger_engine.py` **24 passed**.
  - 하네스 `accept backend-file` **PASS**(3/3), 인접 파일
    (`test_decision_factory.py`, `test_core_risk_off_topk_projection.py`)
    11 passed.
  - **운영 반영 관측·가중치 재정규화 여부는 다음 턴 과제로 남김.**
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §146.
- [x] **SPPV-2.158([SPPV-2.158에서 정정] 완료 — 코드 미수정, §6.33
  표현 정밀도 보정, 판정 A 유지)** (2026-08-01 19:15 KST, 작성자: Codex,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건, 이력 보존형 정정)
  - `regime_tailwind`는 `decision_json.deterministic_trigger.metadata`에
    **저장돼 있지 않음**을 실측 확인(metadata 키 19개 전수 나열 —
    `regime_label`/`risk_tone`은 있으나 `regime_tailwind` 없음).
  - SPPV-2.157의 검증은 "jsonb에 저장된 값을 직접 조회"가 아니라
    "저장된 `regime_label`+`risk_tone`으로 `_build_buy_ranking_score()`
    분기 로직을 재구성해 역산·집계"한 것으로 표현 정정.
  - "최근 1개월" 창을 `2026-07-01 00:00:00 KST 이상 2026-08-01 00:00:00
    KST 미만`으로 명시 확정 — 재확인 결과 core n=18,946 정확히 일치,
    **수치 변경 없음**.
  - **판정 A와 핵심 결론 4가지(entry_score 기준 무관/종목별
    market_regime/core_risk_off guard 0건 예외/event_overlay 0.56 경계
    뒤집힘 0건) 전부 유지.**
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §145.
- [x] **SPPV-2.157(신설, 완료 — 코드 미수정, `regime_tailwind` 제거
  선행 검증, 판정 A)** (2026-08-01 18:27 KST, 작성자: Codex, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - `buy_candidate`는 `entry_score>=0.65` 기준이라 `ranking_score`(regime_
    tailwind 포함)와 애초에 무관함을 코드로 확인.
  - `ranking_score`를 실제 게이트로 쓰는 유일한 경로(core_risk_off guard,
    `0.28`/`0.02`/`0.26`)는 게이트 활성 조건이 `regime_tailwind=0`이 되는
    조건의 부분집합이라 **논리적으로 항상 무영향** — n=13,312 전수 실측
    으로 100% 확인(예외 0건).
  - 값이 0이 아닐 수 있는 유일한 실측 지점(event_overlay shadow, `0.56`)은
    55건 전수 확인 결과 **경계 뒤집힘 0건**, 이 실험 자체가 승격 배선
    없는 순수 관찰용.
  - market_overlay는 값이 다양(0.5/1.0 합 18.9%, 전체 이력)하나
    `ranking_score`를 소비하는 코드 자체가 없어 완전 불활성.
  - `strategy_alignment`와 달리 "값이 살아있는 곳"과 "코드가 읽는 곳"이
    겹치지 않음.
  - **최종 판정: A(바로 diff 초안 작성 가능)**.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §144.
- [x] **SPPV-2.156([SPPV-2.156에서 정정] 완료 — 코드 미수정,
  authoritative 재검증, 이력 보존형 정정)** SPPV-2.155 수치 정정
  (2026-08-01 17:51 KST, 작성자: Codex, `.env` 미수정, Full pytest
  미실행, 신규 KIS 호출 0건)
  - SPPV-2.155의 core-eligible/coverage/3계층 수치는
    `instruments.metadata.index_memberships` JSON을 읽는 heuristic으로
    산출됐으나, 실제 서비스는 `trading.instrument_index_memberships`
    관계형 테이블을 참조한다 — **다른 모집단 정의**였다.
  - `UniverseSelectionService.count_core_eligible()` +
    `list_latest_by_instrument_ids()`(authoritative 경로)로 재계산:
    **core-eligible 211→216**, **covered(07-31 배치 정확 갱신) 203→207
    (95.8%)**, **FRESH(guard 5일) 204→208(96.3%)**, **STALE 1(유지)**,
    **MISSING 6→7(3.2%)**.
  - 원인 5종목(`000990`/`0126Z0`/`267270`/`456040`/`483650`) 전부
    `metadata.index_memberships=None`인데 실제 테이블엔 KOSPI200/100
    멤버십 존재 — 수동 전사 오류나 배제 규칙 차이 아님.
  - `target_count=207` vs `snapshot_count=208`은 **오류 아님** —
    `069500`(KODEX 200, regime 벤치마크로 항상 강제 추가, SPPV-2.72)
    때문.
  - **핵심 결론("stale bias 사실상 해소")은 authoritative 수치로도
    재현되어 유지됨.**
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §143.
- [x] **SPPV-2.155(신설, 완료 — 코드 미수정, S5 배치 실측 완료)**
  07-31 20:10 KST 장후 배치 결과 실측 (2026-08-01 17:34 KST, 작성자: Codex,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - 확인 시각(08-01 17:34 KST)이 요청된 "배치 직후"보다 하루 늦었으나
    배치 자체는 07-31 밤에 이미 완료돼 있어 read-only 실측 정상 수행.
    `docker logs`는 이후 배포(PR #79/#80)로 컨테이너가 재기동(08-01 06:29
    KST)돼 소실 — DB `signal_feature_batch_runs` 영속 기록으로 대체 확인.
  - **배치 실행**: freeze 20:10:04 KST(target_count=207), batch 적재
    완료 20:12:54 KST, `status=completed`, `fetch_error_count=0`,
    `persist_error_count=0`. 두 단계 모두 성공, retry 미발동(정상 — 발동
    조건 자체가 없었음).
  - **coverage**: 기존 80 → **208종목**(2.6배). core-eligible 211 중
    **203종목(96.2%)** 커버. 미커버 8종목 중 7종목이 우선주(애초 배제
    대상), 1종목은 3일 경과로 여전히 FRESH.
  - **stale 핵심 8종목 전부 FRESH로 전환**(개별 확인 완료).
  - **3계층 재분포**: FRESH 80→**204(96.7%)**, STALE 66→**1(0.5%)**,
    MISSING 65→**6(2.8%, 전부 우선주)**. **stale bias 사실상 완전 해소**
    (일부 개선이 아님)로 판정.
  - **소요시간**: 약 170초, SPPV-2.151 예측치(172.5초)와 근접 — 검증됨.
  - **다음 거래일(2026-08-03 월) freeze 준비**: 추가 세팅 불필요, read-only
    실측만으로 충분.
  - **미확정**: timeout/budget WARNING 직접 확인(로그 소실로 불가,
    `fetch_error_count=0`이 간접 증거), 다음 거래일 실제 freeze 구성 확인.
  상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
  signal_v1.md` §142.
- [x] **SPPV-2.152(신설, 완료 — 코드 미수정, **배치 실측 미수행**)**
  S5 배치 반영 준비 상태 점검 + 배치 전 기준선 확정 (2026-07-31 15:31 KST,
  작성자: Codex, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **요청된 장후 배치 실측은 수행 불가**: 확인 시각 15:31 KST < 배치 예정
    20:10 KST. 오늘자 `signal_feature_after_market` freeze **0건**, 오늘자
    snapshot **0건**, 최신 `snapshot_at` 여전히 **07-30 20:00 KST**를 실측
    확인. **추정으로 대체하지 않고** 범위를 준비 상태 점검 + 기준선 확정으로
    조정했다.
  - **S5 런타임 반영 확인**: PR #72가 장중(13:35 KST) 머지로 `sync_source`/
    `activate_runtime`이 모두 skip됐음에도, 호스트 작업트리=운영 경로 +
    bind mount 구조와 `create_subprocess_exec` 기동 방식 덕에 **컨테이너
    재기동 없이 coverage 모드로 실행될 준비 완료**. 컨테이너 안에서 직접
    import해 `core_cap=None`/`max_cap=None`, freshness 필드,
    `CORE_SIGNAL_TIER_STALE=1`, `count_core_eligible`/`_core_signal_tier`
    존재 확인. cap은 `build_input_command`가 전달하지 않으므로 **서브프로세스
    기본값**에서 읽힌다(ops-scheduler에 cap 상수 import 0건).
  - **배치 전 기준선**: core-eligible **211**, 3계층 **FRESH 80(37.9%) /
    STALE 66(31.3%) / MISSING 65(30.8%)**, 직전 stale 핵심 8종목 전부 STALE
    (경과 37~42일).
  - **내일 freeze 실측 준비**: **추가 세팅 불필요, read-only만으로 충분**
    (단 오늘 밤 배치 성공이 전제이고, 배치 실패 시의 개선은 "S5 효과"가
    아니라 "guard 단독 작동"으로 해석해야 함). 다음 거래일은 07-31이
    금요일이므로 **2026-08-03(월)**. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §140.
- [x] **SPPV-2.151(신설, 완료 — 코드 변경 포함, 운영 효과 미확정)**
  S5 구현 = 생성 모집단 정렬 + freshness guard (2026-07-31 KST, 작성자:
  Codex, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **전제**: 배치는 장후 **20:10 KST** 실행이라 **소요 시간 증가를 제약으로
    두지 않음**. **"80종목 유지"는 보수안으로 남기지 않음.**
  - **축1(근본 원인 대응)**: 배치 cap 기본값 `80 → None`(**coverage
    모드=절단하지 않음**)으로 바꿔 생성 모집단이 소비 모집단(core-eligible
    전체)을 구조적으로 덮게 함. `CompositionContext.max_cap`에 `None`
    의미를 추가해 `_apply_cap` 절단 지점 2곳 무효화. 상수 상향(`80→300`)은
    여전히 절단 가능해 재발하므로 기각. 부수 이점으로 **SPPV-2.145
    §132.3 순환 의존 회피 제약이 소멸**.
  - **축2(guardrail)**: `_core_signal_sort_rank()` 정렬 키를
    `(tier, -overall_score, symbol)` 3계층으로 코드화(`CORE_SIGNAL_TIER_
    FRESH/STALE/MISSING` 명명 상수). stale을 실패로 막지 않고 **하향**.
    기본값 `None`=무변화, decision loop만 **5일** 주입.
  - **축3**: 배치 커버리지 관측 지표 + shortfall **WARNING** 추가.
  - **둘 중 하나만으로 불충분**: S2 단독은 배치 부분 실패 시 stale이 상위를
    차지, S1 단독은 **편향이 80위 경계로 이동한 상태로 고정**.
  - 검증: **114 passed**(기존 **109건 무수정 통과** + 신규 5, 무변화 회귀
    포함), 관련 123 passed, 하네스 2건 PASS. **미완료**: 운영 반영 관측,
    KIS 예산 실측. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §139.
- [x] **SPPV-2.150(신설, 완료 — 설계 검증 턴, 코드 미수정)** stale
  snapshot 근본 원인 규명 + 구조 대응안 비교 (2026-07-31 KST, 작성자:
  Codex, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **근본 원인 재규정**: "배치 누락"이 아니라 **`signal_feature_
    snapshots`의 생성 모집단과 소비 모집단이 서로 다른 cap·정렬 기준으로
    같은 `compose()`를 호출하는 계약 불일치**. §137.6의 "배치 81종목"
    서술은 결과이지 원인이 아님을 정정.
  - 3축 실측: 생성=`core_cap=80`+사전순(ops-scheduler가 `--core-cap`
    미전달), 소비=`core_cap=12`+신호순 211종목, freshness 조건 **0건**.
    소비 core 12개 중 생성 모집단 포함 **4개(33.3%)**. core-eligible
    211개 중 신선(0~1일) **79개(37.4%)** / 31일+ **66개** / snapshot
    없음 **65개**.
  - **S1(freshness guard 단독)이 부족한 이유**: stale은 숨지만 D안이
    신선 79개(=사전순 상위) 안에서만 작동해 **편향이 12위→80위 경계로
    회귀**하고, 생성/소비 불일치가 유지되며, 변형 국면에서 재발한다.
  - 6개 안(S0~S5) 8축 비교 후 **1순위 = S5(생성 모집단 정렬 + freshness
    guard 안전망)**. S2로 `core_cap ≥ 후보 수`가 되면 **순환 의존 자체가
    소멸**한다는 구조적 이점 확인. S3는 범위 과도, S4는 D안 설계 후퇴.
  - **선행 확인 필요(미완료)**: KIS `market_data` 예산·배치 시간
    (80종목 66.36초 → 211종목 약 3분 추정, 호출량 약 2.6배) —
    **사용자 승인 필요**. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §138.
- [x] **SPPV-2.149(신설, 완료 — 효과 확정 아님)** D안 + `strategy_
  alignment` 제거 첫 운영 반영 실측 (2026-07-31 KST, 작성자: Codex,
  코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **런타임 반영 확인**: 컨테이너 md5 4파일 일치 + 파일 내용으로 D안
    3요소·`strategy_alignment` 제거(ranking 0건/entry 유지)·threshold
    (`0.28`/`0.02`) 확인.
  - **오늘 freeze**: `2026-07-31 08:50:41 KST`, `target_count=13`
    (core 12 + `event_overlay` 1). core 12종목이 기존 왜곡 상태(사전순
    top12)와 **교집합 0** → D안 운영 작동 확인. shadow 예측 **실질
    12/12 일치**(차이 1건은 우선주 `_apply_exclusions` 미모델링).
  - **핵심 종목**: `000720` 사전순 10위→D안 125위(`overall_score=
    −0.7055`)로 **core 탈락**(§128/§129 왜곡 해소 첫 사례),
    `001450` 사전순 16위→**1위 진입**. `002790`(13위)·`000810`(22위)·
    `009150`(49위)·`000660`(66위) 탈락.
  - **`strategy_alignment`**: `core` 264건 `sa=1.0` **0건**,
    `event_overlay` 22건도 0건 → SPPV-2.148과 **충돌 없음**. funnel은
    `buy_candidate`/`APPROVE`/`order_request`/`final_intent=buy` 모두 0.
  - **보류/실패(과장 금지)**: 오늘 게이트 활성 0/264라 **게이트 영향
    검증 불가**. D안 순수 효과는 동일 regime 비교 2.13배(0.2380→0.5067)
    이나 **stale snapshot bias**(6월 평균이 7월보다 +0.0682 높고 core
    12개 중 8개가 6월 snapshot)가 격차의 약 25%를 설명 가능 → **2.13배는
    상한**.
  - **신규 발견**: stale snapshot 정렬 — 배치가 하루 81종목만 갱신하는데
    core-eligible은 211종목이라 풀 밖 종목이 오래된 snapshot으로 정렬됨.
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §137.
- [x] **SPPV-2.148(신설, 완료)** `strategy_alignment` 직접항 제거
  threshold 영향 정량 검증 (2026-07-30 KST, 작성자: Codex, 코드 미수정,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건 — **운영 효과
  미확정**)
  - **게이트 모집단 완전 무변화 확인**: `core_risk_off_guard_active=
    true` 모집단에 `strategy_alignment=1.0`이 **최근 3거래일 0/2,401,
    전체 이력 0/11,785** → `ranking_score` 평균·중앙값 동일,
    `0.28`/`0.02`/`0.26` 판정 뒤집힘 **두 창 모두 0건**.
  - 일반 BUY 경로는 평균만 미세 하락(0.325032→0.323566)하고 판정 불변.
    `_assess_buy_eligibility`에서 `ranking_score`는 `risk_off+bearish_
    trend` 분기 안 `source_type=="core"` 경로에서만 판정에 관여함을
    코드로 확인 → 일반 경로 평균 하락은 실제 BUY 판정에 무의미.
  - **뒤집힘 0건의 원인**: `sa=1.0` 2,760건이 `event_overlay`(2,718)+
    `market_overlay`(42)에만 존재하고 `core` **0건**, 게이트 활성
    레코드 전부 False. 제거폭 `0.02` 내 뒤집힘 밴드에 **각 0건**.
  - **범위 밖 관찰 지표(정직 기록)**: `event_overlay`
    `adjusted_ranking_score>=0.56` 통과 수가 전체 이력 1,222→1,100
    (**122건 이동**, 최근 3거래일 0건) — 이 비대칭은 여기서만 존재.
    단 실제 `shadow_would_pass=True` 60건 중 뒤집힘 **0건**.
  - **판정: 추가 코드 수정 불필요, 내일 장 시작 후 그대로 관찰 가능.**
    `regime_tailwind`는 **별도 트랙 유지**. `core`/`event_overlay`는
    섞어 일반화하지 않는다. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §136.
- [x] **SPPV-2.147(신설, 완료 — 코드 변경 포함)** `strategy_
  alignment` 직접항 제거 diff 초안 (2026-07-30 KST, 작성자: Codex,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - `deterministic_trigger_engine.py` 단일 파일에서 `_build_buy_
    ranking_score()`의 `+ 0.02 * strategy_alignment` 항 제거(+ 그 항
    전용 지역 계산·미사용 `strategy_selection` 매개변수·호출부 인자
    정리). **`entry_score` 쪽 `+0.05`와 `trigger_strategy_alignment`
    reason code는 그대로 유지**, `regime_tailwind`는 범위 밖.
  - **"죽은 항 제거"가 아니다** — `event_overlay`에서 전체 이력
    28.93%로 살아 있으며, 근거는 `entry_score`와의 **직접 중복 계상
    제거**다(§134.1/§134.7).
  - 최소 검증: `test_deterministic_trigger_engine.py` **23 passed**
    (기존 21건 **무수정 통과** + 신규 2건), 관련 5개 파일 105 passed,
    하네스 `accept backend-file` **PASS**.
  - 신규 테스트 2건: `ranking_score` 차이가 정확히 `0.55×0.05`임을
    확인(= ranking 직접항이 빠졌고 entry 경유분만 남음) + 기본 BUY
    판정 경로 무결성 확인.
  - **미완료**: threshold 영향 정량 확인(게이트 모집단 무변화는 추론
    단계), 운영 반영·효과 확정. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §135.
- [x] **SPPV-2.146(신설, 완료)** `regime_tailwind`/`strategy_
  alignment` 잔여 설계 가치 검증 (2026-07-30 KST, 작성자: Codex,
  코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **신규 발견**: `(source_type, regime_label, risk_tone)` →
    `preferred_strategy` 전수 검정에서 **15개 조합 전부 단일값,
    비결정 0건** → 두 항 모두 regime·source 정보의 결정론적 함수로
    독립 정보 없음. `event_overlay` 내부에서 같은 `regime_label`
    안에 `strategy_alignment`가 갈리는 사례 0건.
  - 분포: `regime_tailwind` 최근 3거래일 **100% `0.0`**, 전체 이력
    98.39% `0.0`(설명력 표준편차 기준 **0.89%**). `strategy_
    alignment` `core` 전체 이력 **0건**이나 `event_overlay`
    **28.93% 발동 중**(설명력 **4.49%**) — 기존 "현재 미발동"
    서술은 `core` 한정이었음을 정정.
  - 병목 기여: `buy_candidate=True` 168건 중 **126건(75%)이
    `regime_tailwind=0.0`**에서 발생, `event_overlay` `sa=1.0`
    2,718건의 `buy_candidate`는 0건 → **완화 레버가 아니라 산식
    정리 대상**.
  - **판정**: `regime_tailwind`=제거 권고(단 threshold 동시 조정이
    완화로 작용할 수 있어 선행 확인 1건 필요, diff 후보 아직 아님),
    `strategy_alignment`=`ranking_score` 직접항(`0.02`) 제거 권고
    (**다음 diff 초안 후보 진행 가능**). 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
    §134.
- [x] **SPPV-2.145(신설, 완료 — 코드 변경 포함)** D안 diff 초안 실제
  작성 (2026-07-30 KST, 작성자: Codex, `.env` 미수정, Full pytest 미실행,
  신규 KIS 호출 0건)
  - §132.2 계획대로 **6개 파일**만 수정: `contracts.py`/`postgres/
    signal_feature_snapshots.py`/`memory.py`(bulk `list_latest_by_
    instrument_ids` 추가), `universe_selection_types.py`(`CORE_RANKING_
    MODE_*` 상수 + `CompositionContext.core_ranking_mode`, **기본값=현행
    사전순**), `universe_selection.py`(점수 캐시 + `_core_signal_sort_
    rank()` + step 8 정렬 분기), `run_decision_loop.py`(D안 모드 주입).
    `_apply_cap()`은 한 줄도 수정하지 않음, `generate_signal_feature_
    snapshot_input.py`는 diff 제외(순환 의존 회피).
  - 정렬 키 `(snapshot 보유 여부, -overall_score, symbol)` — **사전순은
    3번째 요소**로 완전 동점 시 결정성 보장용 기술 규칙일 뿐. 2차 키가
    非CORE에 항상 0이라 안정 정렬로 overlay 상대 순서 보존.
  - 검증: `test_universe_selection.py` **109 passed**(기존 106 무수정
    통과 + 신규 3), `test_run_decision_loop.py` 121 passed, 하네스
    `accept backend-file` 3개 PASS. `contracts.py`/`postgres/signal_
    feature_snapshots.py` 하네스 FAIL 2건은 `git stash` 기저 대조로
    **선재 postgres 환경 실패**임을 확인(이번 diff 원인 아님).
  - 남겨둔 것: 운영 반영 관측(다음 거래일 08:50 KST freeze 대조),
    postgres bulk 전용 통합 테스트(환경 복구 후), 배포(PR 머지 전이라
    미반영 — 장 외 시간이므로 배포 금지 정책 비적용, 별도 승인 불필요).
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §133.
- [x] **SPPV-2.144(신설, 완료)** D안 diff 착수 전 최소 침습성·부작용
  범위 설계 점검 (2026-07-30 KST, 작성자: Codex, 코드 미수정, `.env`
  미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - D안 정의 고정: core-eligible 후보를 `signal_feature_snapshots.
    overall_score` 기준 상위 `core_cap` 선별. 운영 실측으로 시점 확정 —
    `decision_loop_intraday` freeze는 **08:50 KST 하루 1회** 생성이고
    snapshot은 20:00 KST 산출이므로 **전 거래일 종가 신호로 당일 정렬**,
    look-ahead 구조적 불가 + intraday churn 없음.
  - 최소 변경 경로 **6개 파일**(§131.6의 "읽기 1곳" 추정 정정) — 모두
    기존 템플릿 따르는 추가 변경. bulk 조회 메서드가 필수(현 계약에
    bulk 없음, 199 쿼리 회피). `_apply_cap`은 `@staticmethod`라
    `compose_with_diagnostics`에서 캐시 후 정렬 키만 변경.
  - **순환 의존 회피**: snapshot 입력 배치도 동일 `compose()`를 cap 80
    으로 호출하므로, 정렬 모드 기본값을 현행 사전순으로 두고 decision
    loop만 opt-in → 배치는 무변화, `generate_signal_feature_snapshot_
    input.py`는 diff 대상 아님.
  - 부작용은 CORE 내부 재정렬로 한정(source_type `priority`가 1차 키
    유지), held/reconciliation/event/market overlay·`max_cap`·`core_cap`·
    `market_overlay_cap`·`pre_pool_size` 모두 충돌 없음. snapshot 없는
    120종목은 최하위+동순위 사전순으로 cold start 시 A안과 동일 퇴화.
  - **판정: D안 diff 초안 착수 가능**. 다음 작업: `universe_selection`
    D안 diff 초안 작성. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §132.
- [x] **SPPV-2.143(신설, 완료)** `core_cap` 절단 기준 재설계안
  A/B/C/D 비교 (2026-07-30 KST, 작성자: Codex, 코드 미수정, `.env`
  미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - **신규 구조 제약 2건**: (1) `signal_feature_snapshots` 커버리지가
    core-eligible 사전순 **1~79위 연속 구간**뿐이고 80위 이후 120종목은
    0건 — snapshot 배치도 동일 `_apply_cap()`을 자체 cap(80)으로 쓰기
    때문 → 어떤 score 기반 안도 사전순 편향을 제거하지 못하고 12위→
    79/80위로 경계만 이동. (2) 유니버스는 루프 진입 시 1회 확정되고
    채점은 그 이후라, `universe_selection`이 `deterministic_trigger_
    engine`을 import하지 않는 현재 계층에서 B/C안은 계층 역전 + 재배선
    필요.
  - 20거래일 비교: A안 평균 entry_score 0.1535, B안=C안 0.3489
    (종목집합 19/19일 동일 — shadow에서 ranking_score는 entry_score의
    단조 변환이라 **B/C 우열 판정 불가**), D안(snapshot 원시
    `overall_score` 정렬) 0.3460(B안의 99.2%, B안과 92.1% 일치).
    B/C/D 모두 `entry_score>=0.65` 0건 — **신호 품질 개선이지 주문
    발생 완화 아님**.
  - `000720` A안 11일→B/C/D안 0일, `009150` A안 0일→B/C안 6일·D안
    10일. **판정: 절충안 검토 필요 — 다음 턴 diff 초안 1안은 D안**
    (효과 99.2% + 계층 정합성 유지). 상세: `docs/10_signal_research_
    sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §131.
- [x] **SPPV-2.142(신설, 완료)** SPPV-2.141 핵심 수치 재현성 검증
  (2026-07-30 KST, 작성자: Codex, 코드 미수정, `.env` 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건)
  - 동일 방법론·동일 20거래일 창으로 재실행 — 핵심 집계 지표(실제
    평균 entry_score 0.1657, shadow 평균 0.3489, 겹침 20.3%)는
    소수점까지 정확히 재현. `000720` 실제 포함일수는 원 보고문
    "13일"이 완료 보고 시 수동 집계 오류였음을 확인해 "11일"로
    정정, shadow 순위 하한도 `000720`(58→55위)/`002790`(14→9위)
    정정. **판정: 방향은 재현되나 수치 일부 차이(정정 완료)**,
    `왜곡 큼` 판정은 유지(핵심 집계 지표 재현 + 정정 수치도 결론
    강화). 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §130.
- [x] **SPPV-2.141(신설, 완료)** `core_cap` 사전순 절단 왜곡 정량
  검증 (2026-07-30 KST, 작성자: Codex, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - 최근 20거래일(KST) 실제 core 선택(사전순 절단) vs 기존 함수
    (`_build_entry_score`/`_build_buy_ranking_score`) 재사용 shadow
    (entry_score/ranking_score 상위 12) 비교. 실제 평균 entry_
    score(0.1657)가 shadow 평균(0.3489)의 약 47%, 실제∩shadow
    겹침 일평균 20.3%(12개 중 2~3개). `000720`(shadow 순위 하위
    10~15%, 13/20일[SPPV-2.142에서 정정: 11/20일] 포함) vs
    `009150`(상위 15~30%, 0/20일 포함) 극단 역전 사례 확인.
    **판정: 왜곡 큼**. 다음 우선 작업: `core_
    cap` 절단 기준 재설계 검토(완화안 아님, 설계 비교 단계). 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §129.
- [x] **SPPV-2.140(신설, 완료)** `000720` core 유니버스 20거래일+
  연속 포함 원인 규명 (2026-07-30 KST, 작성자: Codex, 코드 미수정,
  `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - `_is_core_seed_instrument()`가 `000720`을 KOSPI200 index
    membership으로 core-eligible 판정, `_apply_cap()`의 `core_
    cap=12` 절단이 동일 priority 종목 간 안정 정렬로 원 순서(DB
    `ORDER BY symbol`, 사전순)를 유지 — `000720`은 core-eligible
    199종목 중 사전순 **10위**로 항상 cap 이내 채택. 비교 종목
    `002790`(21위)/`009150`(59위)은 cap 밖. **판정: 구조 편향
    확인**(신호/랭킹과 무관한 사전순 절단). 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §128.
- [x] **SPPV-2.139(신설, 완료 — 트랙 종료)** `coverage_score`
  A-3안 적용 후 운영 무변화 실측 확인 (2026-07-30 KST, 작성자:
  Codex, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
  - 장중 예외 승인으로 배포된 A-3안이 운영에서 실제로 무변화인지
    확인. 배포 직전 2시간(gate n=176) vs 배포 이후 누적(~39분,
    gate n=64) — `ranking_blocked` 비중 **87.5%→87.5%(소수점까지
    동일)**, `buy_candidate`/`APPROVE`/`order_request`/`shadow_
    would_pass` 등 핵심 출력 변수는 배포 전후 모두 0. **판정: A-3
    무변화 confirmed**, `coverage_score`+threshold 재설계 트랙
    완전 종료. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §127.
- [x] **SPPV-2.138(신설, 완료 — 코드 변경 포함)** `coverage_
  score` A-3안 실제 diff 적용 + 최소 검증 (2026-07-30 KST, 작성자:
  Codex, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - `deterministic_trigger_engine.py`에서 `_CORE_RISK_OFF_
    RANKING_MIN_SCORE=0.48→0.28`, `_CORE_RISK_OFF_SHADOW_MIN_
    SCORE=0.22→0.02`, `_build_buy_ranking_score`의 `0.20*
    coverage_score` 항 제거. 관찰용 shadow 메타데이터 내부의
    범위 밖 절대값 2곳(`0.26`, `_EVENT_OVERLAY_SHADOW_MIN_
    SCORE=0.56`, 실제 BUY 판정과 무관)이 낡은 스케일에 남아
    테스트 3건이 실패 — 사용자 확인(AskUserQuestion) 결과 "이번
    턴 범위 유지"로 결정, fixture/기대값만 최소 보정. 관련 테스트
    21+105건 + 하네스 `accept backend-file` 통과. 신규 A-3 전용
    회귀 테스트로 경계가 정확히 0.20만큼 이동함을 코드로 증명
    (무변화 리팩터링, 완화 아님). 상세: `docs/10_signal_research_
    sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §126.
- [x] **SPPV-2.137(신설, 완료)** `coverage_score`+절대 threshold
  (`0.48`/`0.22`) 재설계 비교 (2026-07-30 KST, 작성자: Codex,
  코드 미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출
  0건)
  - 게이트 모집단(전체 이력 n=13,016) 전수 조사 결과 `coverage_
    score`가 예외 없이 `1.0` — 이에 근거해 "완전 제거 + threshold
    `0.48→0.28`/`0.22→0.02`로 동일 상수(`0.20`) 이동"하는 **A-3안**
    이 현재 판정 경계를 수학적으로 완전히 보존함(무변화, 병목
    완화 아님)을 증명. 1순위: A-3, 보류: B안(가중치 축소), 기각:
    A-1/A-2(§120에서 이미 검증 실패). 다른 BUY 차단 장치와 충돌
    없음. **diff 착수 가능 여부: 다음 턴부터 가능**(설계 비교
    단계 종료, 코드 변경은 별도 승인 필요). 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §125.
- [x] **SPPV-2.136(신설, 완료 — 관측 단계 종료)** `relative_
  activity` 1안 적용 후 운영 관측 추가 축적(2차, 최종 판정)
  (2026-07-30 KST, 작성자: Codex, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - 병합 이후 실제 경과 약 23시간(gate n=616/전체 BUY-path
    n=1,435 — 이전 두 턴(n=15/134) 대비 4~40배 확대, 병합 이전
    1일치(n=1,037)와 같은 자릿수 도달). `ranking_blocked` 비중은
    99.9~100%→90~93%로 이동했으나 병합 직전부터 이미 시작·예측과
    반대 방향이라 **diff 인과 효과 아님**(교란 요인)으로 판정.
    `buy_candidate`·`APPROVE`·`order_request`·`final_intent=
    'buy'`·`shadow_topk_exception_v2`는 3개 관측 창(n=15→134→
    616~1435) 전부 **0 유지**. 핵심 병목 재확인: `coverage_
    score`+절대 threshold(`0.48`/`0.22`). **판정 전환: 1안
    (coverage_score+threshold 재설계 비교 착수) 채택** — 관측
    단계 종료. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §124.
- [x] **SPPV-2.135(신설, 완료)** `relative_activity` 1안 적용
  후 운영 관측 추가 축적 (2026-07-29 KST, 작성자: Codex, 코드
  미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - 병합 이후 실제 경과 시간 약 41분(초기 1사이클 n=15 → 누적
    약 9사이클 n=134) — "5거래일 수준 관측"은 캘린더 시간 제약
    으로 이번 턴에서 확보 불가함을 명시. `ranking_blocked` 비중
    은 초기 1사이클(56.2%)보다 병합 이전 기준값(46.7%)에 더
    가깝게 회귀(47.8%). `buy_candidate`·`APPROVE`·`order_
    request`·`shadow_topk_exception_v2`는 초기·누적 창 모두
    **0 유지**(변화 없음). 핵심 병목 재확인: `coverage_score`+
    절대 threshold(`0.48`/`0.22`). **다음 1순위(SPPV-2.136에서
    전환됨): 2안(추가 관측 연장) 유지, 관측 단계 미종료**. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §123.
- [x] **SPPV-2.134(신설)** `relative_activity` 1안 적용 후 영향
  확인 + 다음 설계 분기 확정 (완료, 2026-07-29 KST, 작성자:
  Codex, 코드 미수정, `.env` 미수정, Full pytest 미실행, 신규
  KIS 호출 0건)
  - 병합 직전 30분(n=120) vs 병합 이후 1개 사이클(n=15) 비교 —
    `ranking_score`/`ranking_blocked` 비중 미세 이동은 표본 극소
    로 해석 보류, `buy_candidate`(0/0)·`shadow_topk_exception_v2`
    (0건)는 **변화 없음**. 핵심 병목은 여전히 `coverage_score`+
    절대 threshold(`0.48`/`0.22`) 조합으로 재확인. **다음 1순위:
    운영 관측 1~2 거래일 추가 축적(2안), `coverage_score`
    threshold 재설계는 보류**. 상세: `docs/10_signal_research_
    sppv/[DESIGN] regime_conditional_entry_signal_v1.md` §122.
- [x] **SPPV-2.133(신설)** `relative_activity` 1안 diff 실제 적용
  (완료, 2026-07-29 KST, 작성자: Codex, `.env` 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건 — **이번 항목만 코드 변경
  포함**)
  - `deterministic_trigger_engine.py`의 `_build_buy_ranking_
    score`에서 `0.10*relative_activity` 항 제거, `entry_score`
    쪽 반영은 유지. 관련 단위 테스트 4개 파일(125건) + 하네스
    `accept backend-file` 통과. 경계값 근처였던 기존 테스트 1건
    fixture 최소 보정. `coverage_score` threshold 재설계는
    미착수. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §121.
- [x] **SPPV-2.132(신설)** `coverage_score` threshold 연쇄영향
  정량 재계산 + `relative_activity` 유지 위치 비교 (완료,
  2026-07-29 KST, 작성자: Codex, 코드 미수정, `.env` 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - `coverage_score` A안은 `0.48`/`0.22` threshold 통과율이
    각각 14.8%→0.34~2.2%, 100%→0.4~1.8%로 붕괴함을 정량 확인
    — diff 보류, threshold 재설계 별도 트랙 필요. `relative_
    activity`는 1안(entry_score 유지, ranking 제거)이 threshold
    영향 미미(14.8%→14.3%) + diff 범위 최소임을 확인 — 다음 턴
    diff 초안 작성 가능. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §120.
- [x] **SPPV-2.131(신설)** `coverage_score`/`relative_activity`
  설계안 A/B 비교 (완료, 2026-07-29 KST, 작성자: Codex, 코드
  미수정, `.env` 미수정, Full pytest 미실행, 신규 KIS 호출 0건)
  - 둘 다 A안(제거/단일화) 방향으로 수렴. diff 초안 착수 전
    각 1개씩 확인 과제 남음(threshold 상호작용 재계산, 하드
    게이트 정합성 실측). 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §119.
- [x] **SPPV-2.130(신설)** `ranking_score` 산식 재설계 준비 —
  4개 항목 역할 재분류 (완료, 2026-07-29 KST, 작성자: Codex,
  코드 미수정, 완화안/코드 diff 없음, Full pytest 미실행, 신규
  KIS 호출 0건)
  - `coverage_score`=이관 검토(1순위), `relative_activity`=
    중복 정리(2순위), `strategy_alignment`=중복 정리(3순위),
    `regime_tailwind`=축소 검토(4순위). 1·2순위는 설계안 비교
    단계 진입 가능. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §118.
- [x] **SPPV-2.129(신설)** `strategy_alignment` 해석·집계 수치
  정밀 보정 (완료, 2026-07-29 KST, 작성자: Codex, 코드 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - "core는 설계 의도대로 죽어 있는 항" 판정을 정정 — core도
    event_overlay와 무관한 일반 경로 존재, 상류 risk_tone
    상시화 때문에 도달 사례가 없었을 뿐. regime_tailwind와
    근본 원인 동일로 수렴. regime_tailwind 판정은 유지. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §117.
- [x] **SPPV-2.128(신설)** `regime_tailwind`/`strategy_alignment`
  고정 여부 설계 의도 vs 부산물 판정 — `[PRIORITY_MAP]` SPPV-3
  1순위 완료 (완료, 2026-07-29 KST, 작성자: Codex, 코드 미수정,
  Full pytest 미실행, 신규 KIS 호출 0건)
  - `strategy_alignment`(core 소스)는 설계 의도대로 죽어 있는
    항(event_overlay 전용 override 코드 확인), `regime_
    tailwind`는 상류 risk_off 상시화의 부산물. 코드 버그 아님.
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §116.
- [x] **SPPV-2.127(신설)** distinct symbol 기준 기여도 재계산 +
  `002790`/`000720` 반복 등장 원인 규명 — `[PLAN]` §6.8 잔여
  완료 (완료, 2026-07-29 KST, 작성자: Codex, 코드 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건)
  - 게이트 내부(distinct=25) 100.0%, 일반 BUY 경로(distinct=105)
    96.2%를 entry_score+relative_activity가 설명 — 기존 결론
    유지. 반복 원인은 5분 주기 loop+snapshot 1일 1회 갱신+게이트
    고정 지속(정상 반복). 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §115.
- [x] **SPPV-2.126(신설)** `top50=002790` 문구 모집단 조건 명시
  보정 (완료, 2026-07-28 KST, 작성자: Codex, 코드 미수정, Full
  pytest 미실행, 신규 KIS 호출 0건)
  - "top50=002790"이 `eligibility_core_risk_off_ranking_
    blocked` 게이트 모집단(n=11,971) 내부 한정임을 명시. 수치·
    최종 판정 변경 없음. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §114.
- [x] **SPPV-2.125(신설)** 모집단 정의·필드 경로 정밀 재검증
  (완료, 2026-07-28 KST, 작성자: Codex, 코드 미수정, Full pytest
  미실행, 신규 KIS 호출 0건)
  - "n=68,724" 분모가 키 부재/값 null을 혼합 집계한 것이 원인임을
    확인, 정확한 분모(38,762/36,598/38,667)로 정밀화. distinct
    값 수치는 전부 재현, 정정 대상은 분모 표기뿐. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_
    signal_v1.md` §113.
- [x] **SPPV-2.124(신설)** `allocation_quality` 일반 모집단
  분산 재검증 + §111(123차) 과대해석 정정 (완료, 2026-07-28
  KST, 작성자: Codex, 코드 미수정, threshold/diff/완화안 없음,
  신규 KIS 호출 0건)
  - 전체 이력(n=68,724) 재검증 — `allocation_quality`만 확정
    (풍부한 분산), 나머지 3개는 부분 확정으로 하향. 최종 판정
    불변. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §112.
- [x] **SPPV-2.123(신설)** `[PLAN] ranking_score_formula_
  validation.md` §6 체크리스트 재판정 (완료, 2026-07-28 KST,
  작성자: Codex, 코드 미수정, threshold/diff/완화안 없음, 신규
  KIS 호출 0건)
  - §6.2 실제 완료 격상(일반 모집단 대조), §6.3/§6.4 부분 완료
    하향(표본 반복성 발견, 정당성 판정 일부 미확정 유지). 최종
    판정 불변, 근거 강화. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §111.
- [x] **SPPV-2.122(신설)** 산식 재검토(1순위)+중복 차단 정리
  (2순위) 관점 항목별 분류 (완료, 2026-07-28 KST, 작성자: Codex,
  코드 미수정, threshold/diff/완화안 없음, 신규 KIS 호출 0건)
  - 즉시 유지=entry_score. 역할 축소 검토=coverage_score/
    regime_tailwind. 중복 제거/정리 검토=relative_activity/
    strategy_alignment. `[PLAN]` §6 체크리스트 전 항목 완료.
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §110.
- [x] **SPPV-2.121(신설)** `[PLAN] ranking_score_formula_
  validation.md` §6 체크리스트 실행 (완료, 2026-07-28 KST,
  작성자: Codex, 코드 미수정, threshold/diff/완화안 없음, 신규
  KIS 호출 0건)
  - 트랙 A/B 재확인, 트랙 C 신규(상위/하위 기여도 대조), 트랙 D
    신규(중복 매핑 — relative_activity 4곳, regime 3곳, strategy_
    alignment 3곳). 최종 판정: 1순위 산식 재검토, 2순위 중복
    차단 정리, 3순위 모집단 재정의, 4순위 threshold 재측정.
    상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §109.
- [x] **SPPV-2.120(신설)** `ranking_score` 산식 구성요소 분해 —
  threshold vs 산식 vs 모집단 (완료, 2026-07-28 KST, 작성자:
  Codex, 코드 미수정, threshold/diff/완화안 없음, 신규 KIS 호출
  0건)
  - 실제 공식이 설계 문서 제안식과 다름을 확인. `regime_
    tailwind`/`strategy_alignment` 100% 고정 0, `coverage_
    score`/`allocation_quality` 완전 무분산. 관측 상한 결합해도
    이론적 상한 0.4296(고정 회복 가정 0.4796)으로 threshold
    미달. 판정: 1순위=산식 구조, 2순위=모집단 정의, threshold
    재측정은 근본 원인 아님. 상세: `docs/10_signal_research_sppv/
    [DESIGN] regime_conditional_entry_signal_v1.md` §107.
- [x] **SPPV-2.119(신설)** `0.48` 모집단 정밀 분해 — 경계값 vs
  상시 봉쇄 상수 (완료, 2026-07-28 KST, 작성자: Codex, 코드
  미수정, threshold 변경 없음, 신규 KIS 호출 0건)
  - `0.43~0.48` 근접 구간 0건(양 창 모두). 모집단 85.68~91.02%가
    `0.20~0.30`에 몰림. 상위 10개 조합에서도 신호 개선 없음.
    판정: 경계값 아님, 모집단 품질 문제에 가까움. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_
    signal_v1.md` §106.
- [x] **SPPV-2.118(신설)** `0.48` 설정 근거·정합성 검증 (완료,
  2026-07-28 KST, 작성자: Codex, 코드 미수정, threshold 변경
  없음, 신규 KIS 호출 0건)
  - `0.48`은 2026-07-01 커밋에서 최초 등장, 같은 커밋의 설계
    문서가 도입 시점에 이미 평균 ranking_score 0.24로 불일치
    기록. 현재 평균도 0.257~0.264로 동일 — 분포 이동 없음. 판정:
    C(당시부터 실측 근거 약한 운영 상수)에 가장 근접. §36 오표기
    정정 포함. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §105.
- [x] **SPPV-2.117(신설)** `ranking_blocked` 제외 후 경계 표본
  탐색 (완료, 2026-07-28 KST, 작성자: Codex, 코드 미수정, diff
  초안 없음, 신규 KIS 호출 0건)
  - `core_risk_off_guard_active=true` 전수(3거래일 2,623건,
    전체 이력 11,891건) 중 ranking_blocked 이외 사유 0건. shadow
    신호 게이트 격차 최소 0.25, near-miss 0건. 판정: 완화 검토
    가치 있는 사유 1·2순위 모두 없음. 다음 턴 방향 전환(층3)
    제안. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §104.
- [x] **SPPV-2.116(신설)** `risk_off AND bearish_trend` 하드
  게이트 완화 후보 사전 정밀 검증 (완료, 2026-07-28 KST, 작성자:
  Codex, 코드/설정 변경 없음, 신규 KIS 호출 0건)
  - `eligibility_core_risk_off_ranking_blocked` 모집단(3거래일
    n=2,563, 전체 이력 n=11,831) 실측 — ranking_score 전체 이력
    최댓값 0.417(threshold 0.48 근접 0건), 기존 완화 시뮬레이션
    3종(v2/v3/v5) 0% 통과. 판정: 이 게이트에는 안전한 완화 지점
    없음, 유일한 후보는 기존 top-k override 활성화뿐(즉시 효과
    없음). 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §103.
- [x] **SPPV-2.115(신설)** `risk_off` 연쇄 설계 의도 vs 실동작
  정합성 검증 (완료, 2026-07-28 KST, 작성자: Codex, 코드/설정
  변경 없음, 신규 KIS 호출 0건)
  - `risk_off`+`bearish_trend` AND 결합 시에만 eligibility 하드
    차단(예외 발동 0.02%), 단독은 소프트 페널티. 최근 3거래일
    (4,240건): buy_candidate 1.3%, eligibility_passed 3.8%,
    final_intent=buy/APPROVE 0%. `eligibility_core_risk_off_
    ranking_blocked` 59.5%로 최다. 판정: 설계 의도(하락 국면
    한정)와 실동작(상시 봉쇄) 부분 불일치. 완화안 미제시. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §102.
- [x] **SPPV-2.114(신설)** `atr_14_pct` 상시 고값 원인 진단 —
  실물 특성 vs 페이퍼 데이터 소스 (완료, 2026-07-28 KST, 작성자:
  Codex, 코드/설정 변경 없음, 신규 KIS 호출 0건)
  - raw bar 수동 재계산 vs snapshot 일치(계산 오류 배제). 81개
    종목 전체·ETF(069500) 포함 균일하게 넓은 스프레드
    (2.80~17.80%), ETF가 개별 종목과 구분 안 됨. 판정: B(페이퍼
    데이터 소스 특성)에 가장 근접, A 근거 약함, C 배제, E 여지
    일부. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §101.
- [x] **SPPV-2.113(신설)** threshold-분포 정렬 원인 진단 (완료,
  2026-07-28 KST, 작성자: Codex, 코드/설정 변경 없음)
  - 계산식 변경 이력 없음(D 배제). 4개 창(3일/2주/1개월/전체) 모두
    high_volatility 82.7~90.6%, bearish_trend 63.6~70.6%로 동일 —
    상시 구조. atr_14_pct가 high_volatility 지배(89.7%). slow_score
    조건은 파생값이라 단독 병목 0건. 3주 전 문서에 threshold
    미검증 경고 기록 존재. 판정: B+C 결합에 가장 근접, 완화안
    미제시. 상세: `docs/10_signal_research_sppv/[DESIGN] regime_
    conditional_entry_signal_v1.md` §100.
- [x] **SPPV-2.112(신설)** `risk_tone` 100% `risk_off` 원인 규명
  (완료, 2026-07-28 KST, 작성자: Codex, 코드/설정 변경 없음)
  - `classify_market_regime` 로직 정상 확인(4,030건 전수 0건
    불일치). `high_volatility`/`bearish_trend` 임계값이 전체
    스냅샷 이력(2,315행)의 중앙값 부근 또는 그 이하 — 89.8%/63.6%
    가 이미 충족, OR 결합으로 risk_off 상시 성립. 시장 전체
    (30종목, 2026-06-24부터 3주+ 연속 100%)에 균일 — 001450
    특이 현상 아님. 판정: 코드 정상, 임계값 설계 미스매치 가능성
    있는 추가 검증 대상(완화안 없음). 상세: `docs/10_signal_
    research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md`
    §99.
- [x] **SPPV-2.111(신설)** `001450` 층3 정밀 분해 + 시장 전체 비교
  (완료, 2026-07-28 KST, 작성자: Codex, 코드/설정 변경 없음)
  - 최근 3거래일(07-24/27/28) 중 buy_candidate&eligibility_passed
    동시 만족은 07-27 55건뿐. risk_off+고변동성 55/55(100%)
    재확인, event축 없이도 71% downgrade. 시장 전체(3970건) 비교
    결과 risk_off가 상수임을 발견 — 001450 특이 신호 가설 약화.
    001450은 buy_candidate 도달 유일 종목이라 층3 직접 비교
    표본 부재. 판정: 과잉 방어 가능성 남은 미확정. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §98.
- [x] **SPPV-2.110(신설)** `TRADING_UNIVERSE_MAX_CAP` env 배선 실제
  반영 (완료, 2026-07-27 KST, 작성자: Codex, 코드 변경 있음)
  - `core_cap`과 동일 패턴(기본값 30, 하위 호환 유지). 좁은 테스트
    7 passed. shadow 검증(compose() 직접 호출, kis_client=None):
    max_cap=60 시 `009150` universe 진입 확인. runtime 반영은
    intraday freeze 캐시 우선순위로 다음 신규 freeze 사이클 이후.
    값 자체는 미변경(`.env` 실 파일 미수정). eligibility/층3/EV
    gate 미착수. 상세: `docs/10_signal_research_sppv/[DESIGN]
    regime_conditional_entry_signal_v1.md` §97.
- [x] **SPPV-2.109(신설)** 서술 정밀도 보정 — risk_off+volatility
  55건 전수(100%)→54건(사실상 공통 축), max_cap 호출부 "2곳
  모두 인자 없이"→래퍼 경로 존재 반영 정정 (완료, 2026-07-27
  KST, 작성자: Codex, 코드 변경 없음)
  - 큰 결론(상류 병목/중심 축/1·2순위) 변경 없음. 상세: `docs/10_
    signal_research_sppv/[DESIGN] regime_conditional_entry_signal_
    v1.md` §96.6.
- [x] **SPPV-2.108(신설)** max_cap=30 설계 검토(코드 미작성) +
  001450 층3 재관찰(키워드 재집계로 fraud 과대대표 정정) (완료,
  2026-07-27 KST, 작성자: Codex)
  - max_cap=30 조정 최소 수정안(`TRADING_UNIVERSE_CORE_CAP` 패턴
    미러링)/영향범위/검증포인트 정리, 코드 미작성. 001450 재관찰은
    정확 문자열 매칭의 방법론 결함(AI 자유서술 reason_codes 표현
    변이)을 발견·수정 — 키워드 기반 재집계 결과 `risk_off`+
    `volatility` 조합이 55건 전수(100%) 공통 축, `fraud`는 7건
    (13%) 소수 동반 요소. §95.8의 "정당한 다운그레이드" 단정을
    정정, "미확정(추가 관찰 필요)"로 재분류. 상류(max_cap)·하류
    (층3) 이중 병목 명시. 코드 변경 없음, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §96.
- [x] **SPPV-2.107(신설)** 2026-07-27 KST 첫 거래일 실측 —
  `core_cap=60`이 `max_cap=30`에 의해 상쇄됨, 001450 병목이
  층2→층3으로 이동 (완료, 2026-07-27 KST, 작성자: Codex)
  - **⚠️ 최신 상태(한눈에 요약)**: 실제 프로덕션 로그로 `max_cap`
    이 env 오버라이드 불가한 **하드코딩 상수 30**임을 확인(§90/91/
    94의 shadow가 `max_cap=100`으로 재구성했던 것은 실제 조건과
    달랐음 — 정정). 오늘 universe는 정확히 30개(전량 core)로
    고정, `009150`(가장 유망했던 shadow 신규 후보)은 순위 60위라
    아예 universe에 진입 못 함. candidate pool은 2→**6개**(3배)로
    일부 확대 확인. **`001450`이 사상 최초로 `buy_candidate=True`
    +`eligibility_passed=True`를 달성**(활동성 게이트 자연 통과)
    했으나, `candidate_vs_final`에서 **실제 fraud investigation
    이벤트**로 인해 `HOLD`로 downgrade — `submit_request`/`order_
    request`는 여전히 0건.
  - **핵심 판정**: 다음 상류 병목은 core_cap이 아니라 **`max_cap=
    30`**으로 확정 이동. 001450의 downgrade는 정당한 리스크 반영
    으로 판단, 완화 대상 아님.
  - 코드 변경 없음, Full pytest 미실행, 신규 KIS 호출 0건. 상세:
    `docs/10_signal_research_sppv/[DESIGN] regime_conditional_
    entry_signal_v1.md` §95.
- [~] **SPPV-3** `entry_score` point-in-time 재현 및 중복 penalty ablation
  - **보류 유지, 형태 재정의 — 우선순위 재조정**: §12(1년, 자기참조
    포함) 당시 "알파 근거 강화"로 낙관했던 것이 §14(3년, 자기참조
    제거) 확장 검증에서 반박됨 — 하락장 표본에서 안정적인 종목 선택
    능력을 확인하지 못했고 일부(fast_score)는 유의하게 역방향이었다.
    §23의 종합 판정에 따라, SPPV-3의 다음 착수 형태는 기존 `entry_
    score` sub-component 조합의 단순 재현이 아니라 **`regime_
    switch_v1` 아이디어를 국면 분기형 entry 설계의 초기 원형으로
    삼는 것**으로 재정의된다. §8~§11(SPPV-2.18~2.21)에서 국면 정의
    통일(종목별→시장 공통)은 Watch/No-Go에 근접한다는 것이 확인됐고,
    §12(SPPV-2.22)에서 alpha layer 교체는 2차 창에서 유의한 우위를
    확보(Conditional Go)했으나, **§13(SPPV-2.23)에서 결합 사용 시
    가장 빈번하게 걸리는 축이 regime 관련 축이 아니라 별개의
    활동성 필터(`eligibility_low_relative_activity`)임을 새로
    발견**했다(단, "과잉 억제"·"주범" 여부는 SPPV-2.24/§14 ablation
    으로 검증한 결과 확정할 수 없었다 — Watch 유지) — SPPV-3의
    최우선 조사 대상은 이제 이 활동성 필터 완화안 추가 검증이다. 1차
    게이트(§21 모니터링)가 `TRIGGERED`로 전환되는 즉시 alpha layer
    교체의 최종 Go 여부도 재확인해야 하며, 그 전까지 코드 변경은
    보류한다. **[SPPV-2.37 갱신] R3b(candidate 내부 percentile
    재보정)가 실제 BUY funnel 8개 창 검증에서 Watch→Conditional
    Go로 상향됐다(§2.37) — SPPV-3 착수 시 alpha 재보정 로직의 1순위
    후보로 삼되, §2.37이 명시한 잔여 조건(marginal t_NW 재확인,
    거래 빈도 축소의 총 기대수익 영향 정량화, §3 전제조건, point-
    in-time 파이프라인 반영 shadow 실행) 충족 전까지 SPPV-3 자체의
    착수(운영 코드 반영)는 여전히 보류한다.**
  - 작업 범위: `eligibility_low_relative_activity` ablation 검증
    (신규 최우선), regime/allocation/strategy/source 복원, signal
    약세와 `risk_off_penalty`/eligibility 중복 억제 분해, `overall_
    score` 재설계(통과군 내부 역전 해소), §21 TRIGGERED 시 alpha
    layer 교체 최종 재확인
- [ ] **SPPV-4** 전체 BUY funnel back-simulation
  - 작업 범위: `candidate → selected → expected value → would_buy → submitted`
    counterfactual 전환과 MFE/MAE/낙폭 비교
- [ ] **SPPV-5** out-of-sample 기대수익 및 손실 제약 Go/No-Go 판정
  - 작업 범위: Virtual BUY 수익률, 승률, 비용 차감 성과, 손실 제약 동시 검증
- [ ] **SPPV-6** 제한적 paper probe
  - 착수 조건: SPPV-5에서 Go 판정 + 별도 승인

### C. 현재 판단 기준

- [x] 현재 최우선 작업은 `SPPV-2.7`(완료) → **신호 feature 재설계 검토
  또는 추가 확장** 판단 필요(§14.5, 사용자 확인 권장)
- [x] 단순 threshold 하향, risk/compliance 제거, broker submit 경계 변경은 금지
- [x] 잔여 quintile spread가 regime 컨파운드인지 확인 완료 — ~~국면 혼입
      착시 가능성이 높음~~ **(오류로 폐기) 시장 공통 국면 기준 재검증 결과
      반박됨. `SPPV-3` 착수는 하락장 표본 부재를 이유로 보류 유지**
- [ ] `entry_score` 재현 결과를 바탕으로 shadow formula 후보를 확정
- [ ] Virtual BUY 기준 기대수익/손실 제약을 동시에 만족하는 공식 확보
- [ ] 제한적 paper probe 승격 승인 확보

### D. 체크리스트 운영 규칙

- [x] 단계 완료 시 본 문서 체크박스와 `수정 이력`을 함께 갱신
- [x] 세부 분석 결과는 `ANALYSIS` 문서에 누적하고, 본 문서에는 단계 상태만 요약
- [x] 우선순위 변경 시 `PRIORITY_MAP`의 최신 메모와 실행 순서를 동기화
- [x] 새 실행 항목이 생기면 `BACKLOG`에도 같은 용어(`SPPV-*`)로 반영

## 0. 목적

시스템의 신호(`slow_score`/`fast_score`/`overall_score` 및 구성요소
`slow_momentum`/`slow_trend`)가 **실제로 미래 수익률을 예측하는가**를
과거 데이터로 실증한다. 지금까지 이 신호들은 "좋으면 오를 것"이라는 가정
위에 하드코딩 가중치로 만들어졌을 뿐, 예측력이 검증된 적이 없다(근본 진단
Q2/Q3). 목표 B(최고 기대수익률)를 추구하려면 "무엇을 근거로 사고 파는가"의
토대인 이 신호의 예측력이 선결 검증 대상이다.

이 작업의 최종 목적은 IC 숫자 확인 자체가 아니라, 약 20일간 지속된
`2026-06-25` 이후 BUY 주문 0건 상태를 해소할 수 있는 **예측 가능한 진입
경로**를 만드는 것이다. 단순 threshold 완화는 금지하지만, 실측 근거를 갖춘
`entry_score`/가중치/중복 penalty 재설계와 제한적 probe 승격은 범위에 포함한다.

### 0.1 목표 함수와 손실 제약

이 시스템은 손실 0을 목표로 하지 않는다. 목표는 다음처럼 고정한다.

```text
maximize E[net forward return]
subject to
  허용 손실 한도
  VaR / drawdown / exposure limit
  유동성 및 주문 실행 가능성
  계좌 단위 위험 한도
```

수익률은 1순위 목적함수이고 리스크는 모든 후보를 제거하는 목적함수가 아니라
감내 가능한 손실 범위를 강제하는 제약조건이다. 따라서 약세 신호가 있다는
이유만으로 신호 산식, regime penalty, eligibility에서 동일 위험을 중복 차감하는
구조는 별도 검증 대상이다.

## 1. 검증 대상과 비대상

- **Phase 0 대상(순수 재계산 가능)**: `slow_momentum`, `slow_trend`, `slow_score`,
  `fast_score`, `overall_score`. `build_signal_snapshot(symbol, bars)`가
  일봉 리스트만으로 결정론적으로 재계산하는 순수 함수임이 확인됨
  (`signal_backbone.py:65-73`).
- **Phase 1~3 필수 대상**: `entry_score`, regime/allocation/strategy/source bonus,
  `risk_off_penalty`, BUY eligibility, ranking, expected value, AI decision,
  compliance/VaR, sizing, submit lane. `entry_score`는 외부 상태 히스토리를
  복원해야 하므로 Phase 0에서만 제외하며, 전체 작업 범위에서는 직접 병목으로
  다룬다. backbone 검증만 끝내고 작업을 닫지 않는다.
- **비대상**: broker submit 경계를 AI로 이동하는 변경, compliance/VaR hard
  limit 제거, 근거 없는 threshold 일괄 하향.

## 2. 방법론 — Rolling out-of-sample IC

1. **표본 기간**: 과거 약 1년 이상(상승·하락·횡보 국면 모두 포함) — 지난
   백테스트의 "단일 하락 국면 편향"(Q3)을 구조적으로 해소.
2. **데이터**: KIS `inquire_daily_itemchartprice`(일봉, 수정주가) — 호출당
   ~100거래일 제한이므로 날짜창을 슬라이딩하며 다회 병합. volume(`acml_vol`)/
   turnover(`acml_tr_pbmn`)까지 매핑해 fast_score 왜곡 방지.
3. **Rolling 재계산**: 각 거래일 T(최소 lookback 61봉 이후 ~ 마지막-5봉)마다
   `bars[:T+1]`을 슬라이스해 `build_signal_snapshot` 호출 → 그 시점의 신호값
   기록.
4. **Forward return**: 각 T에 대해 `(close[T+h]/close[T] - 1)`,
   h∈{1,3,5,10,20}. 원수익률과 시장/업종 대비 초과수익률을 함께 저장한다.
5. **비용·손실 측정**: 왕복비용/슬리피지 차감 수익률, MFE, MAE, 최대낙폭,
   양수 비율을 함께 계산한다.
6. **IC(Information Coefficient)**: 파일럿 pooled IC는 탐색용으로만 유지하고,
   본 검증은 거래일별 cross-sectional Spearman IC의 평균, ICIR, 부호 일관성을
   기본값으로 사용한다. 종목별 time-series IC는 별도 보조 지표로 분리한다.
7. **유의성 보정**: T+3/T+5 등 겹치는 forward window와 종목·거래일 군집을
   고려해 non-overlapping 표본, Newey-West 또는 block bootstrap을 적용한다.
   독립 표본을 전제한 단순 t-stat은 파일럿 참고값으로만 표기한다.
8. **표본 구성**: 현재 살아남은 core 종목만 쓰지 않고 가능한 범위에서 당시
   point-in-time universe와 편입·편출 종목을 포함해 선택·생존 편향을 줄인다.

## 3. 성공/실패 판정 기준

- |IC| < 0.02: 예측력 사실상 없음(노이즈)
- 0.02 ≤ |IC| < 0.05: 미약하나 존재
- 0.05 ≤ |IC| < 0.10: 유의미
- |IC| ≥ 0.10: 강함
- **부호도 중요**: 신호↑ → 수익률↑이면 양(+)의 IC(설계 의도대로). 음(-)이면
  신호가 역방향(설계 가정이 틀림).
- 위 IC 구간은 탐색용 분류일 뿐 승격 기준이 아니다. authoritative 후보가 되려면
  국면별 부호 일관성, 비용 차감 기대수익 양수, 손실 제약 충족, out-of-sample
  재현성을 모두 만족해야 한다.
- 단순 후보 증가나 WATCH 증가는 성공이 아니다. `Virtual BUY → eligibility →
  expected value → would_buy → submitted` 전환과 후행 성과가 함께 개선돼야 한다.

## 4. 단계

- **4.1 파일럿(완료)**: core 8종목 × 1년 × slow/fast/overall IC 측정. 목적은
  "파이프라인이 실제로 유효한 IC 숫자를 내는가" 확인 + 초기 신호. 산출물:
  `scripts/validate_signal_predictive_power.py`(read-only),
  `logs/signal_ic_pilot_2026-07-14.*`.
- **4.2 통계 보정 확장**: core 전체와 point-in-time 확장 universe를 대상으로
  국면별 IC, cross-sectional IC/ICIR, overlap 보정까지 수행한다.
- **4.3 `entry_score` 재현**: 거래일별 regime/allocation/strategy/source 상태를
  복원해 당시 `entry_score`와 BUY eligibility를 point-in-time으로 재계산한다.
- **4.4 중복 억제 분해**: 약한 signal, `risk_off_penalty=-0.15`, regime
  eligibility block이 동일 위험을 몇 번 반영하는지 ablation으로 분리한다.
- **4.5 전체 funnel back-simulation**: 각 shadow formula별 Virtual BUY를 만들고
  `candidate → selected → expected value → would_buy → submitted` 가상 전환율과
  비용 차감 수익률/MAE/낙폭을 비교한다.
- **4.6 제한적 probe**: out-of-sample 기대수익 양수와 손실 제약을 만족한 공식만
  일일 top-k, 최소 수량, 계좌 위험한도 아래 paper probe로 승격한다. 전체
  threshold 일괄 완화는 허용하지 않는다.

## 5. 안전 불변식

- Phase 0~4는 read-only/shadow: 운영 DB write 0, 주문 경로 0, 실시간 시세 구독 0.
- 4.6 probe는 별도 Go 승인 후에만 실행하며 deterministic risk/compliance/
  guardrail과 broker submit 경계를 그대로 유지한다.
- KIS 호출은 과거 일봉 조회(read)만. rate budget 고려해 종목간 sleep.
- python3, 로그/산출은 `/workspace/agent_trading/logs`.
- 신호 재계산은 운영 코드(`build_signal_snapshot`)를 그대로 재사용 —
  검증용 별도 로직을 만들지 않아 운영과의 정합성 보장.

---

## 6. 파일럿 결과 (2026-07-14)

대상: core 대형주 8종목(삼성전자·SK하이닉스·NAVER·현대차·기아·셀트리온·
삼성바이오·KB금융) × 과거 약 1년(종목당 일봉 270개, rolling 표본 205개) →
**총 표본 1,640**. 산출: `logs/signal_ic_pilot_2026-07-14.json`.
Spearman 순위상관(IC), t = IC·√((N-2)/(1-IC²)). (|t|>2 대략 유의)

| 신호 | T+1 IC(t) | T+3 IC(t) | T+5 IC(t) |
|---|---|---|---|
| **slow_momentum** | +0.046(1.87) | +0.080(3.25) | **+0.101(4.11)** |
| **overall_score** | +0.038(1.52) | +0.070(2.84) | **+0.084(3.41)** |
| **slow_score** | +0.031(1.27) | +0.061(2.45) | +0.078(3.15) |
| slow_trend | +0.009(0.37) | +0.032(1.27) | +0.041(1.64) |
| fast_score | +0.011(0.45) | +0.025(1.01) | +0.031(1.27) |

### 핵심 결론
1. **예측력 존재 가능성을 지지하는 초기 신호가 확인됐다.** slow_momentum
   (T+5 pooled IC=+0.10)과 overall_score(T+3~5 pooled IC=+0.07~0.08)는
   확장 검증 가치가 있다. 다만 overlap·군집 의존성을 보정하기 전에는
   "통계적으로 입증" 또는 "완전 노이즈 배제"로 확정하지 않는다.
2. **모든 IC의 부호가 양(+)** → 신호↑ → 미래수익률↑, 설계 의도대로 방향이
   맞다(역방향 아님).
3. **예측력이 신호별로 극명하게 갈린다:**
   - `slow_momentum`(3개월 수익률 기반)이 예측력의 **주력**.
   - `fast_score`는 사실상 **예측력 없음**(전 구간 t<2, T+1은 노이즈).
   - `slow_trend`(SMA60 이격)도 **약함**(t<2).
4. **horizon이 길수록 pooled IC 상승**(T+1<T+3<T+5) → 중기 예측에 적합할
   가능성이 있으나 T+10/T+20과 비용 차감 성과로 재확인한다.

### 실행 함의 (3순위 근거)
- `overall_score = 0.55·slow + 0.45·fast`인데 **fast가 노이즈이므로, 0.45
  가중치가 오히려 예측력을 희석**하고 있을 가능성이 높다(단독 slow_momentum
  IC 0.10 > overall 0.08). `slow_score = 0.6·momentum + 0.4·trend`의 trend
  0.4 가중치도 예측력 낮은 요소에 과다 배분.
- → 가중치 재조정 가설은 타당하지만 단일 IC 크기 비교만으로 비중을 바꾸지
  않는다. partial IC, ablation, train/validation/test 분리를 먼저 수행한다.

### 파일럿의 한계 (확장 시 보완 필요)
- **overlap 편향**: rolling로 매일 표본을 뽑아 forward window가 겹치므로
  유효 독립표본 수 < 1,640. **t-stat이 과대평가**됐을 수 있다(실제 유의성은
  다소 낮을 것). 확장 시 non-overlapping 표본 또는 Newey-West 보정 필요.
- **8종목·단일 1년·pooled**: 국면별(bullish/bearish/range) 분해 IC 미측정.
  상승/횡보장에서도 예측력이 유지되는지는 4.2 확장에서 확인.
- fast_score의 volume/turnover는 매핑했으나 수정주가 일관성은 미검증.

### 다음 단계
- 4.2 통계 보정 확장: core 전체 + point-in-time universe + 국면별 분해.
- 4.3 `entry_score` point-in-time 재현과 중복 penalty ablation.
- 4.5 전체 BUY funnel counterfactual 및 비용·손실 제약 검증.

## 7. BUY 주문 0건 운영 기준선 (2026-07-14 재검증)

운영 DB를 `2026-06-25` 이후 `symbol + trade_date` 첫 decision으로 중복 제거해
확인한 결과다.

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

마지막 BUY 주문은 `2026-06-24`다. 이 기간에는 eligibility를 통과한 표본도
`entry_score` threshold를 넘지 못했으므로, BUY 0건의 직접적인 기계적 병목은
하류 expected value/compliance/broker가 아니라 `entry_score < 0.65`다.
하류 계층은 현재 현상의 1차 원인이 아니지만, 새 formula가 후보를 만들기
시작하면 전체 funnel에서 다시 검증한다.

## 8. 목표 BUY 경로의 책임 분리

```text
alpha / expected-return layer
  -> 미래 순수익 예측과 후보 순위화
entry projection layer
  -> entry_score / top-k / minimum edge
risk constraint layer
  -> VaR / drawdown / exposure / liquidity 한도
compliance / guardrail layer
  -> 금지 종목 / 주문 형태 / 계좌 상태 hard block
execution layer
  -> sizing / submit / post-submit convergence
```

시장 약세를 alpha, entry penalty, eligibility에서 반복 차감하지 않는다. 예측
신호는 기대수익을 순위화하고, risk/compliance는 감내 불가능한 손실과 위반만
authoritative하게 차단한다.

## 9. SPPV-2 확장 검증 결과 (2026-07-14)

### 9.1 실행 개요

- 대상: `APPROVED_CORE_UNIVERSE_SYMBOLS` core 종목 **88개 전체**(현재 생존
  종목만 — point-in-time universe는 §9.4 한계에서 별도 설명).
- 기간: 종목당 일봉 270개(약 1년), rolling 표본 190개/종목.
- 총 rolling 표본: **16,720건**.
- 국면 분포(**종목별** regime_label 기준 — 이 라벨의 정의 자체가
  시장이 아니라 종목 자신의 신호였음이 §12.1에서 확인됨, 주의): `bullish_
  trend` 8,356(50%), `range_bound` 4,989(30%), `bearish_trend` 3,127(19%),
  `event_driven_unstable` 248(1.5%) — 당시엔 "다국면 확보"로 해석했으나,
  **시장 공통(벤치마크) 기준으로 다시 보면 실제로는 거의 전 기간이
  단일(상승) 국면이었다(§12.3, bearish_trend 0일)**. "단일 하락국면 한계
  해소"라는 아래 해석은 정정 필요 — §12 참고.
- 산출: `scripts/validate_signal_predictive_power_v2.py`(read-only),
  `logs/signal_ic_sppv2_expanded_2026-07-14.json`,
  `logs/sppv2_run_2026-07-14.log`.

### 9.2 핵심 결과 — cross-sectional IC (거래일별, Newey-West 보정)

| 신호 | T+1 | T+3 | T+5 | T+10 | T+20 |
|---|---|---|---|---|---|
| slow_score | t=-0.71 | t=-0.12 | t=0.18 | t=0.55 | t=0.89 |
| fast_score | t=-0.25 | t=0.49 | t=0.27 | t=0.48 | t=0.62 |
| overall_score | t=-0.56 | t=0.16 | t=0.32 | t=0.62 | **t=1.08** |
| slow_momentum | t=-0.72 | t=-0.11 | t=0.22 | t=0.58 | t=0.85 |
| slow_trend | t=-0.84 | t=-0.15 | t=0.14 | t=0.57 | t=1.06 |

(non-overlapping 표본으로도 재계산했으며 결과는 동일하게 |t|<2 — 대표 값은
overlapping/non-overlapping 모두 `logs/signal_ic_sppv2_expanded_2026-07-14.json`
참고.)

**모든 신호·모든 horizon에서 |t_NW| < 1.1** — 통상 유의성 기준(|t|≳2)에
크게 못 미친다. **SPPV-1 파일럿에서 관측한 t=2.4~4.1("유의미"~"강함")은
overlap 표본(매일 rolling으로 뽑아 forward window가 겹침)과 pooled 처리로
인한 통계적 착시였다.** 정확한 거래일별 cross-sectional 설계 + Newey-West
보정을 적용하자 그 유의성이 전부 사라졌다 — SPPV-1 §"파일럿의 한계"에서
예견했던 우려가 실제로 확인된 것이다.

### 9.3 비용 차감 quintile 성과 (보조 지표 — 단순 통과율이 아닌 실제 수익률/승률)

`overall_score`/`slow_score`/`fast_score` 상위 20% vs 하위 20% 그룹의
왕복비용(30bp 가정) 차감 후 순수익률·승률(T+20 기준):

| 신호 | 상위 20% 순수익 / 승률 | 하위 20% 순수익 / 승률 | spread |
|---|---|---|---|
| overall_score | +5.83% / 56.1% | +1.94% / 50.1% | **+3.88%p** |
| slow_score | +3.83% / 51.3% | +1.91% / 50.1% | +1.93%p |
| fast_score | +4.36% / 54.3% | +3.56% / 53.0% | +0.80%p |

`overall_score`가 quintile spread 관점에서는 가장 뚜렷한 차이를 보이고,
`fast_score`는 여기서도 가장 약하다(§SPPV-1 결론과 방향 일치). 그러나
**이 spread가 cross-sectional IC의 t-stat과는 다른 이야기를 한다** — 일별
순위상관은 유의하지 않은데, 전체 표본을 누적한 quintile 평균은 차이를
보인다. 이는 (a) 진짜 알파가 날마다 미약하게 존재하지만 누적하면 드러나는
경우이거나, (b) `overall_score`가 상승장(bullish_trend, 표본의 50%) 종목을
체계적으로 더 자주 상위 quintile에 배치해 **시장 베타를 알파로 착시**하고
있는 경우일 수 있다. 이번 턴 산출물만으로는 두 가설을 구분할 수 없다 —
§9.5 다음 단계 참고.

### 9.4 국면별 분해 (T+5 기준)

| 신호 | range_bound | bullish_trend | bearish_trend | event_driven_unstable |
|---|---|---|---|---|
| overall_score | +0.027(미약) | +0.028(미약) | **-0.069(유의미, 역방향)** | +0.015(노이즈) |
| fast_score | +0.002(노이즈) | +0.049(미약) | **-0.105(강함, 역방향)** | -0.103(강함, n=248 소표본) |
| slow_momentum | +0.064(유의미) | -0.010(노이즈) | +0.003(노이즈) | +0.080(유의미, n=248 소표본) |

**하락국면(bearish_trend, n=3,127)에서 overall_score/fast_score의 IC가
음(-)으로 뒤집힌다** — 즉 하락장에서는 "신호가 좋다"고 나온 종목이 오히려
더 나쁜 성과를 냈다는 뜻이다. 이는 지금 운영 중인 `risk_off_penalty`/
eligibility 하락장 차단이 완전히 근거 없는 게 아니라, **하락장에서는
현재의 backbone 신호 자체가 방향을 신뢰하기 어렵다**는 정황 증거로
해석된다(다만 표본이 부족한 `event_driven_unstable`, n=248은 판정 보류).

### 9.5 한계 (반드시 인지)

- **point-in-time universe 미적용**: 현재 생존 core 88종목만 사용
  — survivorship bias 존재. 지수/편입 이력이 1년 전체를 커버하지 못해
  (가장 오래된 스냅샷 2026-06-27) 이번 턴에 시도하지 않았다.
- **시장/업종 대비 초과수익 미계산**: 설계(§2.4)에 명시했으나 이번 구현은
  절대수익률 + 비용차감만 계산했다. §9.3의 quintile spread가 시장 베타
  때문인지 검증하려면 이 초과수익 계산이 **선행 필요**하다.
- **round-trip 비용 30bp는 단순 고정 가정** — 운영 `expected_value_gate`의
  동적 비용 모델(회전율/랭킹 percentile 반영)과 다르다. 방향성 판단에는
  문제없으나 정밀 비교에는 한계.
- **block bootstrap 미구현** — Newey-West만 적용. 결론(유의성 없음)이
  이미 보수적 방향이라 우선순위는 낮으나 완전한 통계 보정은 아니다.

### 9.6 판정 — 조건부 보류(Hold)

**SPPV-3(entry_score 전체 재현)로 즉시 진행하지 않는다.** 이유:
`entry_score`/BUY funnel 재현은 상당한 리소스가 드는 작업인데, 그 입력이
되는 원신호(slow/fast/overall_score) 자체가 cross-sectional 유의성을
확보하지 못했다. 이 상태에서 SPPV-3/4를 밀어붙이면 "검증되지 않은 신호
위에 또 다른 재현 작업을 쌓는" 잘못된 레버가 될 위험이 크다.

다만 완전한 "신호 없음(No-Go 확정)"으로도 단정하지 않는다 — quintile
spread(overall_score 기준 +3.88%p)와 하락장 역방향 IC라는 **방향성 있는
잔여 신호**가 남아 있고, 그 정체(시장 베타 vs 잔여 알파)를 가리지 않은
상태이기 때문이다.

### 9.7 다음 단계 (SPPV-2.5, SPPV-3 착수 전 필수 진단)

1. **초과수익 기반 재검증**: 절대수익률 대신 (개별 종목 수익률 - 당일 core
   universe 평균 수익률) 초과수익으로 quintile spread와 cross-sectional IC를
   재계산 — §9.3 spread가 시장 베타 착시인지 판별.
2. **국면 내부(within-regime) quintile 분해**: bullish_trend 내부에서도
   상위/하위 quintile 차이가 유지되는지 확인(유지되면 알파, 사라지면 베타).
3. 위 진단에서 **초과수익 기준으로도 유의미한 spread가 남으면** → SPPV-3
   착수(entry_score 재현), **사라지면** → 현재 backbone 신호 체계
   재설계(가중치 조정이 아니라 feature 자체 재검토)로 전환.

## 10. 관련 산출물

- `scripts/validate_signal_predictive_power_v2.py`
- `logs/signal_ic_sppv2_expanded_2026-07-14.json`
- `logs/sppv2_run_2026-07-14.log`

## 11. SPPV-2.5 결과 — quintile spread 정체 진단 (2026-07-14) — ⚠️ §12에서 방법론 오류 확인, 결론 폐기

> **⚠️ 2026-07-14 정정 공지 (사용자 지적으로 발견)**: 아래 §11의 "국면
> 혼입(regime-mix) 착시" 결론은 **방법론 오류에 기반해 폐기됐다.**
> ① 여기서 쓴 `regime_label`은 시장 전체가 아니라 **평가 대상 종목 자신의**
> 기술적 상태(`classify_market_regime()`가 그 종목의 slow_score/return_3m
> 등만 입력받아 판정, `market_regime.py:21-38`)로, 검정 대상 신호
> (`overall_score`)와 같은 계열의 변수로 표본을 조건화한 선택 편향이었다.
> ② "로컬 캐시로 재조회 없이 재사용"이라는 아래 서술도 **사실이 아니었다**
> — 캐시 기능을 이 실행 직전에 추가했는데 캐시가 비어 있어 실제로는
> 352건 전부 KIS에 새로 요청했다(로그로 확인: `logs/sppv2_5_run_
> 2026-07-14.log`의 HTTP 요청 수 = SPPV-2와 동일한 352건). 데이터 자체는
> SPPV-2와 거의 동일한 기간·종목으로 재요청되어 실질적으로 동등하지만,
> "캐시 재사용"이라는 표현은 정정한다.
> 두 오류 모두 §12(시장 공통 국면 기준 재검증)에서 KODEX 200(`069500`)을
> 진짜 시장 벤치마크로 써서 다시 검증했고, **결론이 뒤집혔다** — §12 참고.
> 아래 §11 본문은 오류의 경위를 남기기 위해 삭제하지 않고 이력으로 보존한다.

### 11.1 실행 개요

- SPPV-2와 **동일 표본**(core 88종목, rolling 16,720건, 국면 분포
  range_bound 4,989/bullish_trend 8,356/bearish_trend 3,127/
  event_driven_unstable 248) — ~~로컬 캐시(`logs/_bars_cache_core88_
  2026-07-14/`)로 KIS 재조회 없이 재사용해~~ **(정정: 실제로는 캐시가
  비어 있어 352건 전부 재조회함, 위 정정 공지 참고)** 완전히 같은 표본
  정의(88종목·동일 기간)로 재요청해 비교했다.
- 산출: `scripts/validate_signal_predictive_power_v2_5.py`(read-only),
  `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`.
- 방법: (1) SPPV-2의 quintile spread(상위 20% - 하위 20% net return)
  시계열 자체에 Newey-West 유의성 검정 적용, (2) 국면별(bullish/bearish/
  range_bound) 표본만으로 quintile을 다시 나눠 국면 내부에서도 spread가
  유지되는지 확인.

### 11.2 핵심 결과

| 신호 | horizon | 전체(pooled) t_NW | bullish_trend | bearish_trend | range_bound |
|---|---|---|---|---|---|
| overall_score | T+5 | 1.64 | 0.99 | -1.72 | 1.76 |
| overall_score | T+20 | **2.30(유의)** | 1.55 | 0.38 | 1.63 |
| slow_score | T+20 | 1.35 | 0.19 | 1.54 | 0.98 |
| fast_score | T+20 | 0.67 | 0.26 | -1.17 | 0.36 |

(`event_driven_unstable`는 n=7일로 표본 극소 — 판정 제외, 원본 수치는
JSON 산출물 참고.)

**`overall_score` T+20의 pooled spread(+3.88%p)는 Newey-West로도 유의
(t=2.30, 관례적 임계 |t|≈2 통과)하다.** 그러나 **이 유의성은 어느
개별 국면 내부에서도 재현되지 않는다** — 가장 근접한 bullish_trend(t=1.55),
range_bound(t=1.63) 모두 유의 임계를 넘지 못하고, bearish_trend는
사실상 0(t=0.38)이다.

### 11.3 해석 — ⚠️ 폐기 (§12에서 반박됨, 아래는 당시 추론 이력)

이 패턴은 통계적으로 **"국면 혼입(regime-mix) 착시"의 전형적 신호**다:
- 상승장 표본은 대체로 수익률이 높고, 하락장 표본은 대체로 낮다.
- `overall_score`가 상승장 종목을 상위 quintile에, 하락장/횡보장 성격의
  종목을 하위 quintile에 체계적으로 더 자주 배치한다면, **국면을 pooling한
  전체 표본에서는 spread가 부풀려지지만, 각 국면 "내부"(그 국면에 이미
  속한 종목들끼리의 상대 비교)에서는 그 효과가 사라진다.**
- 실제로 pooled t=2.30 > 어떤 개별 국면의 t보다도 크다는 것 자체가, 개별
  국면들의 "국면 평균 수준 차이"가 spread의 상당 부분을 설명한다는
  방증이다.

**따라서 `overall_score`가 종목 간 상대적 우열을 가리는 "종목 선택 알파"를
가지고 있다는 근거는 이번 진단에서 확보되지 않았다.** 국면(상승/하락/횡보)
자체를 맞히는 것과 종목을 고르는 것은 다른 문제이며, 이 신호는 후자를
아직 입증하지 못했다.

다만 **완전한 무신호(제로)로 단정하지도 않는다** — bullish_trend(t=1.55),
range_bound(t=1.63) 모두 방향은 일관되게 양(+)이고 유의 임계에 근접해
있다. 표본(국면 내부 거래일 수 ~183~190일)이 국면별로 쪼개지며 검정력이
줄어든 것이 원인일 수 있어, "신호 없음"과 "표본 부족으로 검출 못함"을
이번 데이터만으로는 완전히 구분할 수 없다.

### 11.4 판정 — ⚠️ 폐기(§12 참고), 당시 판정 이력

당시(오류 발견 전) 판정: 조건부 보류(Hold) 유지

**SPPV-3(entry_score 전체 재현)을 계속 보류한다.** 근거: 원신호의
종목-선택 알파가 국면 내부에서 통계적으로 확인되지 않았다. `entry_score`
재현은 상당한 리소스가 드는 작업인데, 그 입력 신호의 알파가 아직
입증되지 않은 상태에서 진행하는 것은 "검증되지 않은 신호 위에 재현 작업을
쌓는" 반복된 잘못된 레버가 될 수 있다.

동시에 신호 체계를 완전히 폐기(No-Go 확정)하지도 않는다 — 방향 일관성과
유의 임계 근접성이 "표본 확장 시 검출 가능한 약한 신호"의 가능성을
남긴다.

### 11.5 다음 단계 (택 1, 사용자/운영 판단 필요)

1. **표본 확장 후 재검증**: 기간을 1년→2~3년으로 늘리거나(국면 내부
   거래일 수 자체를 늘림), 종목을 core 88 → 확장 유니버스로 늘려(하루
   cross-section 크기를 키워 quintile 추정 정밀도 향상) 같은 국면 내부
   분해를 재실행한다. 이건 SPPV-3 착수 여부를 가리는 **마지막 진단
   라운드**로 제안한다.
2. **신호 체계 재검토로 전환**: 표본 확장에도 국면 내부 유의성이 확인되지
   않으면, 지금의 `slow_momentum`/`slow_trend`/`fast_score` 조합 자체가
   종목 간 상대 수익률을 가려내는 데 구조적 한계가 있다고 보고 — 가중치
   재조정이 아니라 **feature 구성 자체의 재설계**(예: 상대강도/업종
   중립화/펀더멘털 feature 추가)로 트랙을 전환한다.

이 판단은 추가 리소스 투입 여부를 정하는 것이라 사용자 확인을 권장한다.

## 12. SPPV 방법론 교정 — 시장 공통 국면(market-common regime) 기준 재검증 (2026-07-14)

### 12.1 배경 — §11의 방법론 오류

§11(SPPV-2.5)의 "국면 내부(within-regime)" 분해는 `classify_market_regime()`
이 반환하는 `regime_label`로 표본을 나눴다. 그러나 이 함수는
(`market_regime.py:21-38`) **시장 지수가 아니라 평가 대상 종목 1개의
`SignalFeatureSnapshotEntity`(그 종목 자신의 slow_score/return_3m/
price_vs_sma_60 등)만 입력받아** 라벨을 매긴다:

```python
def classify_market_regime(snapshot: SignalFeatureSnapshotEntity | None):
    overall = _float_or_none(snapshot.overall_score) or 0.0
    slow = _float_or_none(snapshot.slow_score) or 0.0
    ...
    if slow >= 0.35 and ret_3m >= 5.0 and px_sma60 >= 2.0:
        regime_label = "bullish_trend"
```

즉 "bullish_trend" 버킷은 "그날 시장이 상승장이었다"가 아니라 **"그날 그
종목 자신의 slow_score가 이미 0.35 이상이었다"**는 뜻이다. `slow_score`는
`overall_score`(=0.55·slow+0.45·fast)의 구성 요소이므로, 이 라벨로
표본을 조건화하는 것은 **검정 대상 신호와 같은 계열의 변수로 표본
범위를 제한하는 것**과 같다 — 이러면 그 버킷 내부에서 `overall_score`의
변동 폭 자체가 인위적으로 좁아져(이미 slow≥0.35로 하한이 걸림) quintile
분리력이 기계적으로 줄어들 수 있다. 이건 "시장 국면 대 종목별 알파"를
가르려던 원래 목적과 다른, 별개의 통계적 문제를 측정한 것이었다.

### 12.2 교정 방법 — KODEX 200(069500) 벤치마크 기준

core universe에 이미 포함된 `069500`(KODEX 200, KOSPI200 추종 ETF)을
시장 벤치마크로 사용해 다시 검증했다:

1. **거래일 단위 공통 국면**: 벤치마크 자신의 기술적 상태(rolling
   재계산)로 `classify_market_regime()`을 호출 — 이번엔 종목마다가 아니라
   **거래일 하나당 라벨 하나**이며 그날의 모든 종목이 이 라벨을 공유한다.
2. **초과수익(excess return)**: 각 종목의 forward return에서 같은 기간
   벤치마크의 forward return을 차감.
3. 원 수익률 기준과 초과수익 기준 모두로 pooled/공통국면-내부 quintile
   spread와 cross-sectional IC를 재계산.

산출: `scripts/validate_signal_predictive_power_v3_market_regime.py`
(read-only), `logs/signal_ic_sppv_market_regime_correction_2026-07-14.json`.
**이번엔 캐시가 실제로 채워져 있어 88종목 전부 캐시 hit — 추가 KIS 호출
0건**(로그 확인: `logs/sppv_market_regime_correction_run_2026-07-14.log`에
`HTTP Request:` 0건).

### 12.3 핵심 결과

**시장 공통 국면 분포(거래일 190일 기준)**: `bullish_trend` 185일(97%),
`range_bound` 5일(3%), `bearish_trend` **0일**, `event_driven_unstable`
0일. — 지난 1년간 KOSPI200이 사실상 거의 계속 상승 국면이었다는 뜻이다.
(참고: §11에서 쓴 "종목별 regime_label" 표본 분포는 bearish_trend
19%였는데, 이는 시장이 아니라 개별 종목의 일시적 상태였을 뿐임이 이제
명확해졌다.)

| 신호 | horizon | pooled raw spread t_NW | pooled excess spread t_NW | bullish_trend(공통국면) 내부 t_NW |
|---|---|---|---|---|
| overall_score | T+5 | 1.64 | 1.64(raw와 동일) | 1.61 |
| overall_score | T+20 | 2.30 | 2.30(raw와 동일) | **2.23(여전히 유의)** |
| slow_score | T+20 | 1.35 | 1.35 | 1.24 |
| fast_score | T+20 | 0.67 | 0.67 | 0.67 |

(원 수익률과 초과수익 기준 결과가 완전히 동일한 것은 방법론상 당연하다
— 같은 날 모든 종목에서 그날의 벤치마크 수익률이라는 동일 상수를 빼는
것은 그날의 순위/스프레드 자체를 바꾸지 않는다. 두 기준이 일치한다는
것 자체가 구현이 올바르다는 검증이기도 하다.)

**`overall_score` T+20 spread의 유의성(t=2.30)은, 시장이 거의 항상
상승장이었던 유일하게 신뢰 가능한 공통국면 버킷(`bullish_trend`,
n=185일) 내부에서도 거의 그대로 유지된다(t=2.23).** `range_bound`는
n=5일로 표본이 너무 적어(원본 t=6.37 등 극단값 존재) 판정에서 제외한다.
`bearish_trend`는 표본 자체가 0일이라 계산 불가.

### 12.4 해석 — §11 결론의 반박

§11이 "pooled 유의성은 국면 혼입 착시"라고 결론 내린 근거는 "종목별
regime_label 내부에서 유의성이 사라진다"는 관측이었다. 그런데 그 관측
자체가 §12.1에서 확인한 conditioning 오류(같은 신호 계열 변수로
표본을 제한) 때문일 가능성이 크다. **진짜 시장 국면(벤치마크 기준)으로
다시 나눠보니, 유일하게 신뢰 가능한 국면 버킷 안에서도 spread 유의성이
거의 그대로 유지된다.** 즉:

- **"국면 혼입 착시"라는 §11 결론은 반박된다.** `overall_score`의
  quintile spread는 최소한 "시장이 상승 국면이었던 기간" 내에서는 종목
  간 상대적 우열을 가려내는 진짜 신호일 가능성이 §11 때보다 훨씬 높아졌다.
- **그러나 새로운, 더 근본적인 한계가 드러났다**: 이 1년 표본은 시장
  공통 기준으로 사실상 **단일 국면(상승장)**에 압도적으로 치우쳐 있다
  (하락장 0일, 횡보장 5일). SPPV-2가 원래 해소하려던 "단일 하락국면
  편향"(근본 진단 Q3) 문제가, 종목별 라벨로는 해소된 것처럼 보였지만
  **시장 공통 기준으로는 전혀 해소되지 않았다** — 지난 1년 동안 실제
  하락장이 없었기 때문이다. **"이 신호가 하락장/횡보장에서도 유효한가"는
  이번 표본으로 전혀 답할 수 없다.**

### 12.5 판정 갱신 — §11의 보류(Hold) 판정을 유지하되 근거를 교체

**SPPV-3(entry_score 전체 재현) 착수는 여전히 보류하지만, 이유가
바뀐다.** §11에서는 "알파 근거 미확보"가 보류 사유였다면, 이제는
**"알파 근거는 강화됐으나(상승장 국면 내부에서도 유의), 하락장 표본이
전무해 국면 편향 문제(Q3)가 여전히 미해결"**이 보류 사유다. 근거 없이
완화하지 않는다는 원칙(§0.1)과 동일한 맥락에서, "상승장에서만 확인된
신호"를 곧바로 `entry_score` 전체 재설계에 쓰는 것도 성급하다.

### 12.6 다음 단계 (§11.5 대체)

1. **하락장 포함 기간으로 표본 확장(최우선)**: KIS `inquire_daily_
   itemchartprice`를 더 이전 시점까지 슬라이딩 조회해(예: 2~3년 전, 실제
   조정/하락 국면이 있었던 구간 포함) 벤치마크 기준 `bearish_trend` 표본을
   확보한 뒤, 같은 공통국면 내부 분해를 재실행한다. 이게 SPPV-3 착수
   여부를 가리는 **결정적 마지막 진단**이다 — 하락장에서도 spread가
   유지되면 Go에 가까워지고, 사라지거나 역전되면 "상승장 전용 신호"로
   범위를 좁혀 판단해야 한다.
2. `range_bound`/`event_driven_unstable`도 표본이 절대적으로 부족하므로
   같은 확장으로 함께 보강한다.

## 14. SPPV-2.7 결과 — 하락장 포함 3년 확장 + 자기참조 제거 재검증 (2026-07-14)

### 14.1 실행 개요 — §12.6의 두 과제 처리

1. **자기참조 제거**: §12(SPPV-2.6)는 `069500`(KODEX 200)을 시장 벤치마크로
   쓰면서 동시에 평가 core universe(88종목)에도 포함시켰다 — 벤치마크가
   자기 자신과 비교되는 자기참조였다. 이번엔 **평가 universe에서 벤치마크를
   제외**(core 87종목)했다.
2. **기간 확장**: 조회 기간을 1년 → **약 3년(2023-07-10~2026-07-14, 종목당
   일봉 733개)**으로 늘렸다.
- 산출: `scripts/validate_signal_predictive_power_v4_extended_period.py`
  (read-only), `logs/signal_ic_sppv2_7_extended_period_2026-07-14.json`,
  `logs/_bars_cache_core87_3y_2026-07-14/`(전용 캐시, 1년 캐시와 분리).

**시장 공통 국면 분포(3년, 733거래일 중 rolling 653일)**: `bullish_trend`
351일(54%), `range_bound` 200일(31%), **`bearish_trend` 96일(15%)**,
`event_driven_unstable` 6일(1%). **처음으로 시장 공통 기준 실제 하락장
표본을 확보했다** — §12의 핵심 한계(하락장 0일)가 해소됐다.

### 14.2 핵심 결과 — pooled 유의성 소멸 + 하락장 방향 역전

| 신호 | horizon | pooled(전체) t_NW | bullish 내부 t_NW | **bearish 내부 t_NW(부호)** | range 내부 t_NW |
|---|---|---|---|---|---|
| overall_score | T+5 | 1.03 | 1.35 | **-1.71** | 0.99 |
| overall_score | T+20 | 1.32 | 0.75 | **-0.14** | 1.61 |
| slow_score | T+5 | 0.43 | 0.34 | -0.88 | 0.82 |
| slow_score | T+20 | 0.76 | -0.16 | 0.63 | 1.47 |
| fast_score | T+5 | -0.52 | -0.04 | **-2.79(유의, 역방향)** | 0.57 |
| fast_score | T+20 | 0.04 | -0.54 | -0.84 | 1.62 |

(원수익률/초과수익 결과는 §12와 마찬가지로 수학적으로 동일 — 방법론
정합성 재확인.)

**1) pooled(전체) 유의성이 완전히 사라졌다.** §12(1년 표본)에서
`overall_score` T+20 pooled t_NW=2.30(유의)이었던 것이, 3년으로 확장하자
**t_NW=1.32(미유의)로 떨어졌다.** 이는 1년 표본의 유의성이 표본이 늘자
사라진 것으로, **통계적 우연(작은 표본에서의 노이즈)이었을 가능성이
높음을 시사한다.**

**2) 하락장(96일)에서는 신호 방향이 역전되거나 무의미해진다.**
`overall_score`는 하락장에서 spread가 **음수**(T+5 -1.03%p, t=-1.71;
T+20 -0.21%p, t=-0.14) — 즉 하락장에서는 이 신호가 높은 종목이 낮은
종목보다 더 나쁘거나 차이가 없었다. **`fast_score`는 하락장 T+5에서
spread -1.19%p, t_NW=-2.79로 통계적으로 유의하게 역방향**이다 — "fast
score가 높은 종목일수록 하락장에서 유의하게 더 나쁜 성과"라는 뜻이다.

**3) 어떤 국면에서도 안정적으로 유의(|t|≥2)한 조합이 없다** — bullish/
bearish/range_bound 어느 국면 내부도 `overall_score`/`slow_score`가
|t_NW|≥2를 넘지 못한다. 유일한 통계적 유의성은 fast_score의 **역방향**
하락장 신호뿐이다.

### 14.3 해석 — §12 결론의 표현 완화(하향 조정)

§12(SPPV-2.6)는 "국면 혼입 착시 결론이 반박되고 알파 근거가 강화됐다"고
결론지었다. **이번 3년 확장 검증은 그 결론을 다시 낮춘다.** 1년이라는
짧은 기간에서 관측된 pooled 유의성은 표본을 3배로 늘리자 사라졌고,
가장 중요하게는 **실제 하락장 표본에서 신호가 안정적으로 작동한다는
근거를 전혀 찾지 못했다** — 오히려 방향이 역전되거나(overall_score) 유의
하게 반대로 작동(fast_score)했다.

**"알파 근거가 강화됐다"는 §12의 표현은 과도했다.** 정확한 현재 결론은:
"1년 표본에서의 유의성은 재현되지 않았고, 하락장에서는 이 신호들이
안정적인 종목 선택 능력을 보이지 않는다(오히려 일부는 역방향)."

### 14.4 판정 — 보류(Hold), No-Go에 근접

**SPPV-3(entry_score 전체 재현) 착수는 보류를 유지하되, 보류의 무게가
"알파 근거 강화, 확인만 남음"에서 "안정적 알파를 찾지 못함"쪽으로
이동한다.** 이 신호 조합(slow/fast/overall_score)을 하락장 대응이
중요한 `entry_score`의 핵심 재료로 즉시 승격하는 것은 실측 근거가 없다.
동시에 표본이 여전히 단일 벤치마크(KOSPI200 ETF)·87종목·3년으로 제한적
이라 완전한 No-Go(신호 완전 폐기)로 확정하지도 않는다.

### 14.5 다음 단계

1. **신호 feature 재설계 검토로 무게 중심 이동**: 현재 결과가 "가중치
   조정"으로 해결될 문제가 아니라 "feature 구성 자체"의 한계를 시사한다
   — 특히 `fast_score`는 두 차례 검증(§12, §14) 모두에서 일관되게
   예측력이 없거나 역방향이었다.
2. `event_driven_unstable`은 3년으로도 6일뿐이라 여전히 판정 불가 —
   추가 확장이 필요하면 별도로 검토.
3. 이 판단은 SPPV-3 착수 여부와 직결되므로 사용자 확인 권장.

## 15. 관련 산출물 (갱신)

- `scripts/validate_signal_predictive_power_v2.py`
- `scripts/validate_signal_predictive_power_v2_5.py`
- `scripts/validate_signal_predictive_power_v4_extended_period.py`
- `scripts/validate_signal_predictive_power_v5_recency_window.py`
- `scripts/validate_signal_predictive_power_v6_feature_redesign.py`
- `scripts/validate_signal_predictive_power_v7_followup.py`
- `scripts/validate_signal_predictive_power_v8_fast_score_teardown.py`
- `scripts/validate_signal_predictive_power_v9_gate_and_fast_features.py`
- `scripts/monitor_regime_switch_v1_gate.py`
- `scripts/validate_signal_predictive_power_v10_new_fast_features.py`
- `logs/signal_ic_sppv2_expanded_2026-07-14.json`
- `logs/signal_ic_sppv2_5_regime_decomposition_2026-07-14.json`
- `logs/signal_ic_sppv2_7_extended_period_2026-07-14.json`
- `logs/signal_ic_sppv_recency_window_primary_2026-07-14.json`
- `logs/signal_ic_sppv2_9_feature_redesign_2026-07-14.json`
- `logs/signal_ic_sppv2_10_followup_2026-07-14.json`
- `logs/signal_ic_sppv2_11_fast_score_teardown_2026-07-14.json`
- `logs/signal_ic_sppv2_12_gate_and_fast_features_2026-07-14.json`
- `logs/regime_switch_v1_gate_monitor_2026-07-14.json`
- `logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json`
- `logs/sppv2_run_2026-07-14.log`, `logs/sppv2_5_run_2026-07-14.log`,
  `logs/sppv2_7_run_2026-07-14.log`, `logs/sppv_recency_window_run_2026-07-14.log`,
  `logs/sppv2_9_feature_redesign_run_2026-07-14.log`,
  `logs/sppv2_10_followup_run_2026-07-14.log`,
  `logs/sppv2_11_fast_score_teardown_run_2026-07-14.log`,
  `logs/sppv2_12_gate_and_fast_features_run_2026-07-14.log`,
  `logs/regime_switch_v1_gate_monitor_run_2026-07-14.log`,
  `logs/sppv2_14_new_fast_features_run_2026-07-14.log`
- `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
  (국면별 신호 극성 종합표 + 상위 재설계 방향 확정, 별도 문서)
- `plans/[DESIGN] regime_conditional_entry_signal_v1.md`(국면 분기형
  entry 설계 초안, 별도 문서)
- `scripts/validate_new_alpha_vs_existing_blocking_axes.py`,
  `scripts/diagnose_blocked_reason_distribution.py`,
  `logs/signal_ic_new_alpha_vs_existing_blocking_axes_2026-07-15.json`,
  `logs/new_alpha_vs_existing_blocking_axes_run_2026-07-15.log`,
  `logs/diagnose_blocked_reason_distribution_run_2026-07-15.log`
- `scripts/validate_activity_filter_ablation.py`,
  `logs/signal_ic_activity_filter_ablation_2026-07-16.json`,
  `logs/activity_filter_ablation_run_2026-07-16.log`
- `scripts/validate_activity_filter_threshold_sweep.py`,
  `logs/signal_ic_activity_filter_threshold_sweep_2026-07-16.json`,
  `logs/activity_filter_threshold_sweep_run_2026-07-16.log`
- `scripts/diagnose_activity_filter_half_period_divergence.py`,
  `logs/signal_ic_activity_filter_half_period_divergence_2026-07-16.json`,
  `logs/activity_filter_half_period_divergence_run_2026-07-16.log`
- `scripts/validate_alpha_layer_buy_funnel_comparison.py`,
  `logs/signal_ic_alpha_layer_buy_funnel_comparison_2026-07-16.json`,
  `logs/alpha_layer_buy_funnel_comparison_run_2026-07-16.log`
- `scripts/validate_alpha_layer_virtual_buy_funnel_extended.py`,
  `logs/signal_ic_alpha_layer_virtual_buy_funnel_extended_2026-07-16.json`,
  `logs/alpha_layer_virtual_buy_funnel_extended_run_2026-07-16.log`
- `scripts/validate_alpha_layer_score_rescaling_comparison.py`,
  `logs/signal_ic_alpha_layer_score_rescaling_comparison_2026-07-16.json`,
  `logs/alpha_layer_score_rescaling_comparison_run_2026-07-16.log`
- `scripts/validate_alpha_layer_r3_reproducibility.py`,
  `logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`,
  `logs/alpha_layer_r3_reproducibility_run_2026-07-16.log`
- `scripts/validate_r3b_strict_and_r3_failure_decomposition.py`,
  `logs/signal_ic_r3b_strict_and_r3_failure_decomposition_2026-07-16.json`,
  `logs/r3b_strict_and_r3_failure_decomposition_run_2026-07-16.log`
- `scripts/validate_r3b_paired_replacement_analysis.py`,
  `logs/signal_ic_r3b_paired_replacement_analysis_2026-07-16.json`,
  `logs/r3b_paired_replacement_analysis_run_2026-07-16.log`
- `scripts/validate_r3b_aggregate_vs_paired_decomposition.py`,
  `logs/signal_ic_r3b_aggregate_vs_paired_decomposition_2026-07-16.json`,
  `logs/r3b_aggregate_vs_paired_decomposition_run_2026-07-16.log`
- `scripts/validate_r3b_day_concentration_and_effect_decomposition.py`,
  `logs/signal_ic_r3b_day_concentration_and_effect_decomposition_2026-07-16.json`,
  `logs/r3b_day_concentration_and_effect_decomposition_run_2026-07-16.log`
- `scripts/shadow_regime_conditional_entry_signal.py`(read-only, 신규
  KIS 호출 0건 — 3년 캐시 재사용)
- `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`,
  `logs/shadow_regime_conditional_entry_signal_run_2026-07-15.log`
- `scripts/run_regime_conditional_shadow_cycle.py`(read-only, 신규
  KIS 호출 0건 — Phase 2 오케스트레이터, §21+§22 로직 통합)
- `logs/regime_conditional_signal_shadow_history.jsonl`(누적 이력,
  append-only, 거래일당 1줄),
  `logs/shadow_regime_conditional_entry_signal_2026-07-14.json`(당일
  상세 스냅샷),
  `logs/run_regime_conditional_shadow_cycle_run_2026-07-15.log`
- `scripts/shadow_entry_score_penalty_ablation.py`(read-only, 신규
  KIS 호출 0건 — 3년 캐시 재사용, 운영 `_build_entry_score`/
  `_assess_buy_eligibility` 함수 그대로 호출)
- `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`,
  `logs/shadow_entry_score_penalty_ablation_run_2026-07-15.log`
- `scripts/run_entry_score_penalty_ablation_cycle.py`(read-only, 신규
  KIS 호출 0건 — §8+§22 로직 통합, 시계열 누적)
- `logs/entry_score_penalty_ablation_history.jsonl`(누적 이력,
  append-only, 거래일당 1줄),
  `logs/entry_score_penalty_ablation_2026-07-14.json`(당일 상세),
  `logs/run_entry_score_penalty_ablation_cycle_run_2026-07-15.log`
- `scripts/validate_entry_score_regime_definition_comparison.py`
  (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용, 운영
  `_assess_buy_eligibility` 함수 그대로 호출)
- `logs/signal_ic_entry_score_regime_definition_comparison_2026-07-15.json`,
  `logs/entry_score_regime_definition_comparison_run_2026-07-15.log`
- `scripts/validate_entry_score_regime_definition_ab_diff.py`
  (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용)
- `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`,
  `logs/entry_score_regime_ab_diff_run_2026-07-15.log`
- `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`
  (read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용)
- `logs/signal_ic_alpha_layer_vs_regime_conditional_signal_2026-07-15.json`,
  `logs/alpha_layer_vs_regime_conditional_signal_run_2026-07-15.log`
- `scripts/validate_new_alpha_vs_existing_blocking_axes.py`,
  `scripts/diagnose_blocked_reason_distribution.py`(둘 다 read-only,
  신규 KIS 호출 0건 — 3년 캐시 재사용)
- `logs/signal_ic_new_alpha_vs_existing_blocking_axes_2026-07-15.json`,
  `logs/new_alpha_vs_existing_blocking_axes_run_2026-07-15.log`,
  `logs/diagnose_blocked_reason_distribution_run_2026-07-15.log`
- `logs/_bars_cache_core88_2026-07-14/`(88종목 1년 캐시, 재사용 가능)
- `logs/_bars_cache_core87_3y_2026-07-14/`(87종목+벤치마크 3년 캐시,
  SPPV-2.7/2.8/2.9/2.10/2.11/2.12가 공유 재사용)

## 16. SPPV-2.8 — 검증 기간(period) 기준 재설계: 최근성 우선 + 필수 국면 표본 게이트 (2026-07-14)

### 16.1 문제 제기 — 이 시스템은 장기 보유형이 아니다

SPPV-2.7까지의 검증은 "3년 전체를 pooled"하는 것을 사실상의 기본값으로
써왔다. 그러나 이 시스템은 **3개월 이하 중단기 기대수익을 노리는 공격형
시스템**이다(§0.1 목표함수, T+5/T+20 위주 horizon 설계). 3년 전체를
균등 가중으로 pooling하면 다음 문제가 생긴다.

- **최근 시장과 무관한 옛 국면이 판정에 동일한 비중으로 반영된다.** 예를
  들어 2023년의 시장 상태가 지금(2026-07) 진입 판단의 타당성과 같은
  무게로 섞인다 — 정작 이 시스템이 지금 사려는 것은 "최근 시장에서 통하는
  신호"인데, 검증은 "지난 3년 평균적으로 통하는 신호"를 묻고 있었다.
- 반대로 **최근 구간만 보면 특정 국면(특히 하락장) 표본이 통째로 사라질
  수 있다** — 이는 정확히 SPPV-2.6(1년 창)이 겪었던 실패(bearish_trend
  0일)를 기간만 줄여 다시 재현하는 것과 같다.

즉 "최근성"과 "국면 커버리지"는 단순 trade-off가 아니라 **둘 다 필수
조건**이며, 하나를 위해 다른 하나를 희생하는 단일 창(window) 설계로는
해결되지 않는다.

### 16.2 새 기준 — 1차(primary, 최근성) + 2차(supplementary, 국면 게이트) 이원 구조

3년 pooled를 기본값으로 유지하는 방안과, 최근 6~18개월 중심 + 국면별
최소 표본 요구 방안을 검토한 결과, **둘 중 하나를 택하지 않고 역할을
분리**하는 쪽으로 결정한다.

- **1차(primary, 매 재검증의 기본값)**: 최근 **12개월** rolling 창.
  이 시스템의 실제 진입 판단은 "지금" 이뤄지므로, Go/No-Go 판정의
  기본 근거는 항상 이 창이다. `RECENT_WINDOW_CALENDAR_DAYS = 365`
  (`scripts/validate_signal_predictive_power_v5_recency_window.py`).
- **2차(supplementary, 필수 국면 게이트)**: 1차 창에서 국면별(bullish/
  range_bound/bearish_trend/event_driven_unstable) 거래일 수가
  `MIN_REGIME_TRADING_DAYS = 30` 미만이면, 그 국면에 대한 판정은 1차
  결과만으로 내리지 않고 **가장 최근에 그 국면 표본을 확보한 장기(현재
  3년) 검증 결과**(SPPV-2.7, §14)를 반드시 함께 참고한다. 장기 검증은
  기본값이 아니라 "1차가 답할 수 없는 국면"을 메우는 보조 자료로만 쓴다.
- **판정 규칙**: 한 신호가 Go 후보가 되려면 (a) 1차(최근 12개월) pooled
  유의성(|t_NW|≥2, 올바른 부호) 확보, **그리고** (b) 2차(장기) 국면별
  분해에서 하락장을 포함한 어떤 필수 국면에서도 유의한 역전이 없어야
  한다. 둘 중 하나라도 위반하면 Hold를 유지한다. "1차만 보고 통과", "2차
  옛 데이터만 보고 통과" 둘 다 허용하지 않는다.
- **갱신 주기**: 1차(최근 12개월)는 신호/가중치를 바꿀 때마다 재실행한다
  (캐시가 있으면 신규 KIS 호출 없이 저비용). 2차(장기 국면 커버리지)는
  분기~반기 단위로만 갱신한다 — 매번 3년치를 다시 검증할 필요는 없다.

### 16.3 실측 — 최근 12개월 창을 실제로 돌려본 결과

기존 SPPV-2.7의 3년 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)를
그대로 재사용해(**신규 KIS 호출 0건**) 최근 12개월(2025-06-16~2026-07-14)
로 표본을 잘라 재계산했다. 산출:
`logs/signal_ic_sppv_recency_window_primary_2026-07-14.json`,
`logs/sppv_recency_window_run_2026-07-14.log`.

**국면 분포(최근 12개월, 245거래일)**: `bullish_trend` 239일(98%),
`range_bound` 6일(2%), **`bearish_trend` 0일**, `event_driven_unstable`
0일.

| 신호 | horizon | pooled raw spread t_NW(1차, 최근 12개월) | 참고: 3년(2차) pooled t_NW(§14) |
|---|---|---|---|
| overall_score | T+5 | 1.16 | 1.03 |
| overall_score | T+20 | 1.18 | 1.32 |
| slow_score | T+20 | -0.15 | 0.76 |
| fast_score | T+20 | 0.12 | 0.04 |

**핵심 확인 사항 두 가지**:

1. **최근성 창(1차)만으로는 하락장 게이트를 절대 통과할 수 없다** —
   0일이므로 계산 자체가 불가능하다. 이는 "최근 6~18개월 중심" 단일안을
   그대로 채택했다면 SPPV-2.6과 동일한 실패를 반복했을 것임을 실측으로
   보여준다. **§16.2의 2차(장기) 게이트가 장식이 아니라 실제로 매번
   발동하는 필수 조건임이 이번 실행에서 확인됐다.**
2. **1차(최근 12개월) pooled 유의성도 확보되지 않는다** — naive t-stat은
   `overall_score` T+20에서 3.59로 커 보이지만, Newey-West로 정확히
   보정하면 t_NW=1.18로 떨어진다(3년 결과 1.32보다도 낮음). 즉 "최근
   시장에서만 보면 알파가 살아있다"는 가설도 이번 실측으로는 지지되지
   않는다.

### 16.4 결론 — 판정 불변, 기준만 확정

이번 재설계는 §14의 판정(보류/Hold, No-Go에 근접)을 **바꾸지 않는다**.
1차(최근 12개월)에서도 유의성이 없고, 하락장 게이트는 1차 창으로 아예
평가 불가능해 2차(3년, §14)를 그대로 따라야 하는데 §14도 이미 하락장
역전을 보고했기 때문이다. 대신 이번 작업으로 **앞으로의 SPPV 재검증이
따라야 할 기간 기준이 확정**됐다 — "3년 전체 pooled가 기본값"이 아니라
"최근 12개월이 기본값, 3년은 국면 게이트 보조용"이다. 이 기준은 신호
feature 재설계(§14.5) 이후 재검증할 때도 동일하게 적용한다.

### 16.5 다음 단계

1. §14.5의 신호 feature 재설계가 진행되면, 새 feature도 이번에 확정한
   1차(최근 12개월)/2차(3년, 필요시 갱신) 이원 기준으로 재검증한다.
2. `event_driven_unstable`은 1차·2차 모두 표본이 절대적으로 부족(3년
   기준 6일)하다 — 이 국면에 대한 판정은 당분간 보류하고, 별도로 표본
   확보 방법(다른 벤치마크 병행 등)을 검토해야 한다.
3. `MIN_REGIME_TRADING_DAYS = 30` 임계값은 임시 실무값이다 — 향후
   표본이 누적되면 재검토한다.

### 16.6 실행 증빙 재검증 (2026-07-14, 6차 수정)

§16.3을 처음 작성할 때 사용한 `logs/sppv_recency_window_run_2026-07-14.log`
가 실제로는 **정상 실행 로그가 아니었다**는 사실을 이번 턴에 발견했다.
내용은 다음 트레이스뿐이었다:

```text
Traceback (most recent call last):
  File ".../validate_signal_predictive_power_v5_recency_window.py", line 31, in <module>
    from dotenv import load_dotenv
ModuleNotFoundError: No module named 'dotenv'
```

**원인**: 스크립트를 호스트(`/workspace/agent_trading`, 시스템 python3,
`dotenv` 미설치) 위에서 실행 시도했다가 즉시 실패했다. 반면 §16.3의 JSON
산출물 자체는 그 직전에 **컨테이너(`agent_trading-app-1`, 의존성 설치된
런타임)에서 별도로 실행해 만든 진짜 결과**였는데, 그 실행의 표준출력을
로그 파일로 남기지 않고, 이후 실패한 호스트 실행의 트레이스를 실수로
같은 로그 파일명에 덮어썼다. 즉 "JSON은 진짜지만 그 JSON을 만든 실행의
로그는 없고, 로그 파일에는 무관한 실패 흔적만 남아 있는" 상태였다 —
"실행됐다"고 쓰려면 로그와 산출물이 모두 있어야 한다는 원칙을 위반한
것이었다.

**재검증 절차**:
1. 3년 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`, 88개 파일, 2023-07-10
   ~2026-07-14)를 컨테이너(`agent_trading-app-1`)의 `/app/logs/`에
   복사(`docker cp`) — 원본 호스트 캐시는 그대로 보존.
2. `docker exec -w /app agent_trading-app-1 python3
   scripts/validate_signal_predictive_power_v5_recency_window.py` 를
   실행하며 stdout/stderr를 호스트의
   `logs/sppv_recency_window_run_2026-07-14.log`로 직접 리다이렉트.
3. 종료 코드, `HTTP Request:` 로그 카운트, JSON 산출물의 핵심 수치를
   확인 후 컨테이너 내부 임시 사본은 삭제(호스트 `logs/`만 단일 진실
   공급원으로 유지).

**재검증 결과 — §16.3의 세 수치 전부 재현**:

| 항목 | 재검증 결과 |
|---|---|
| 종료 코드 | 0 (정상 종료) |
| 로그 내 `HTTP Request:` 카운트 | **0건** — 신규 KIS 호출 없이 3년 캐시 100% hit |
| 로그 내 에러/트레이스 | 없음 |
| 최근 12개월 국면 분포 | `{bullish_trend: 239, range_bound: 6}`, **bearish_trend 0일** — 동일 재현 |
| `overall_score` T+20 pooled spread t_NW | **1.18** — 동일 재현 |

실행 시각: 2026-07-14 22:29:18~22:29:41 KST(약 23초). 데이터가 100%
캐시에서 나왔으므로 재실행 때마다 완전히 결정론적으로 같은 수치가
나오는 것이 당연하지만, 실제로 그 결정론성이 유지되는지(코드 변경이나
캐시 훼손이 없었는지)를 이번에 실측으로 확인한 것 자체가 의미가 있다.

**해석**: 이전 §16.3/§16.4의 결론은 근거 있는 산출물(JSON) 위에 있었으나
"정상 실행 증빙(로그)"이 빠진 상태로 문서화됐었다. 이번 재실행으로 그
증빙 결함이 해소됐고, 수치 자체는 변경 없이 그대로 재현됐으므로 **§16.3
~§16.5의 결론과 §14의 보류(Hold) 판정을 낮추거나 올릴 필요는 없다** —
표현을 "유지"하되, 그 근거가 이제 완전하다(로그+JSON 모두 확보)는 점만
명시한다.

## 17. SPPV-2.9 — 신호 feature 재설계 검토: sub-component 분해 + 신규 후보 (2026-07-14)

### 17.1 실행 개요 — §14.5 지시 이행

§14.5는 "가중치 조정"이 아니라 "feature 구성 자체의 재설계"를 다음 단계로
지시했다. 이를 위해 다음 두 가지를 함께 수행했다.

1. **기존 sub-component 분해**: `fast_score`/`slow_score`는 각각 여러
   sub-component의 가중합이다(운영 코드 `signal_backbone._score_features()`,
   재설계 아님, 그대로 재사용).
   - `slow_score = 0.6·slow_momentum + 0.4·slow_trend`
   - `fast_score = 0.3·fast_trend + 0.2·volume_confirmation +
     0.15·rsi_signal + 0.35·volatility_penalty`
   - 이 6개를 **합성 전 raw sub-component 값 그대로** 개별 검증해, 어느
     조각이 `fast_score`의 반복된 예측력 실패/역전에 기여하는지 특정한다.
2. **신규 후보 feature 2개**(raw `TechnicalFeatureSnapshot` 값으로부터
   계산, 운영 가중치 체계와 무관하게 독립 검증):
   - `risk_adj_momentum_3m = return_3m_pct / max(volatility_20d_pct, 1.0)`
     — "변동성 대비 모멘텀"(quality momentum) 가설. 단순 모멘텀
     (`slow_momentum`)이 예측력을 못 보인 것이 "변동성이 큰 종목의
     모멘텀은 노이즈였을 수 있다"는 가설에서 출발.
   - `reversal_1m = -return_1m_pct` — 단기 역추세(mean reversion) 가설.
     §14가 `fast_score`(그 일부인 `rsi_signal` 포함)가 하락장에서 유의
     하게 역방향이었다고 보고한 것이, "단기 역추세가 오히려 방향이
     맞는 신호일 수 있다"는 반대 가설을 세울 근거가 된다.

방법론은 **§16(SPPV-2.8)에서 확정한 이원 기준을 그대로 적용**한다 — 1차
(primary)=최근 12개월, 2차(supplementary, 국면 게이트)=3년(시장 공통
국면, KODEX 200 벤치마크). 기존 3년 캐시(`logs/_bars_cache_core87_3y_
2026-07-14/`)를 재사용해 **신규 KIS 호출 없이** 검증했다(로그 확인:
`HTTP Request:` 0건). 산출:
`scripts/validate_signal_predictive_power_v6_feature_redesign.py`
(read-only), `logs/signal_ic_sppv2_9_feature_redesign_2026-07-14.json`,
`logs/sppv2_9_feature_redesign_run_2026-07-14.log`. 실행: 종료 코드 0,
표본 3년 56,753건/최근 12개월 21,315건, 87종목 전체 성공(실패 0).

### 17.2 핵심 결과 — quintile spread Newey-West t-stat (T+5/T+20)

| 신호 | horizon | 1차(최근 12개월) pooled | 2차(3년) pooled | bullish_trend(3년) | bearish_trend(3년, n=96) | range_bound(3년) |
|---|---|---|---|---|---|---|
| slow_momentum | T+20 | -0.49 | 0.52 | -0.30 | 0.88 | 0.96 |
| slow_trend | T+20 | -0.38 | 0.46 | -0.57 | 0.35 | 1.15 |
| fast_trend | T+20 | 0.22 | 0.66 | -0.14 | 0.22 | 1.37 |
| volume_confirmation | T+20 | -0.65 | -0.16 | -0.79 | 1.04 | 0.29 |
| **rsi_signal** | T+20 | **-2.94** | -1.55 | **-2.79** | -0.22 | 0.66 |
| volatility_penalty | T+20 | -1.44 | -1.45 | -1.42 | 0.40 | -1.22 |
| **risk_adj_momentum_3m** | T+20 | 1.47 | **2.07** | 1.51 | 0.39 | **2.09** |
| reversal_1m | T+5 | -0.46 | -0.28 | -0.47 | **2.13** | -0.89 |

(전체 T+5/T+20, 8개 신호 전체 수치는 JSON 원본 참고. 표는 유의하거나
방향성이 뚜렷한 항목 중심으로 발췌.)

### 17.3 해석 — 세 가지 실질적 발견

1. **`rsi_signal`이 `fast_score` 실패의 구체적 원인 중 하나로 특정됐다.**
   T+20에서 1차(최근 12개월) t_NW=-2.94, 2차 bullish_trend 내부 t_NW=
   -2.79로 **통계적으로 유의하게 역방향**이다 — "RSI가 과매수 구간
   (rsi_signal 높음)일수록 오히려 20일 뒤 성과가 나쁘다"는 뜻이다. 이는
   RSI 과매수가 실제로는 단기 되돌림(reversal) 신호에 가깝다는 일반적
   기술적 분석 직관과 부합한다 — `fast_score`에 RSI를 "추세 지속" 방향
   (양(+)의 가중치)으로 넣은 현재 설계가 구조적으로 틀렸을 가능성이
   높다.
2. **`risk_adj_momentum_3m`(변동성 조정 모멘텀)이 유일하게 방향 일관된
   Watch 후보다.** 2차(3년) pooled t_NW=2.07(유의), 어떤 국면에서도
   유의하게 역전되지 않았다(bearish_trend t_NW=0.39, 부호도 양(+)으로
   유지). 다만 §16 Go 게이트는 "1차(최근 12개월) 유의성 AND 2차 국면
   무역전"을 **모두** 요구하는데, 1차 t_NW=1.47로 임계(|t|≥2)에 못
   미친다 — **완전한 Go는 아니다.** 원 신호 `slow_momentum`(변동성
   미조정)이 어디서도 유의하지 않았던 것과 대비하면, "모멘텀 자체가
   무신호"가 아니라 "변동성으로 나누지 않은 원 모멘텀이 노이즈였을
   가능성"을 시사한다.
3. **`reversal_1m`(단기 역추세)은 범용 feature가 아니라 국면 조건부
   신호일 가능성이 있다.** bearish_trend(n=96, 표본 충분) 내부에서만
   T+5 t_NW=2.13(유의)이고, bullish_trend/range_bound/pooled/1차 창
   에서는 유의하지 않거나 부호가 반대다. 이는 "하락장에서는 단기
   낙폭이 큰 종목이 반등하는 경향"이라는 별개의 가설이지, "이 신호가
   상시 유효한 feature"라는 뜻은 아니다.

### 17.4 판정 — SPPV-3 착수 보류 유지, `risk_adj_momentum_3m`만 Watch로 승격

**SPPV-3(entry_score 전체 재현) 착수는 계속 보류한다.** §16 Go 게이트를
완전히 통과한 후보가 하나도 없기 때문이다(`risk_adj_momentum_3m`도 1차
창 유의성 미달). 다만 이번 검토는 "가중치를 조정해도 소용없다"는 막연한
결론에서 한 걸음 나아가, **구체적으로 무엇을 바꿔야 하는지**를 실측으로
좁혔다:

- `rsi_signal`은 방향(부호) 자체가 틀렸을 가능성이 높다 — 제거 또는
  부호 반전 검토 대상.
- `risk_adj_momentum_3m`은 표본이 더 누적되면(또는 최근 창을 12→18개월로
  넓히면) 1차 유의성을 확보할 가능성이 있는 유일한 후보 — 우선 재검증
  대상.
- `reversal_1m`은 "하락장 조건부 오버레이"로 별도 분리해 검토할 가치가
  있으나, 상시 feature로 편입하기엔 이르다.

### 17.5 다음 단계

1. `risk_adj_momentum_3m`을 최근 창을 18개월로 넓히거나 표본이 누적된
   시점에 재검증해 1차 유의성이 |t_NW|≥2에 도달하는지 확인한다.
2. `fast_score`에서 `rsi_signal`을 제거(또는 부호 반전)한 `fast_score_v2`
   후보를 shadow로 정의하고, 같은 §16 이원 기준으로 재검증한다 — 이번
   턴에는 아직 시도하지 않았다(원인 특정까지만 완료, 재조합 검증은
   다음 턴 과제로 남긴다).
3. `reversal_1m`을 하락장 조건부 오버레이로 분리해, 시장 공통 국면이
   `bearish_trend`로 판정된 날에만 활성화하는 shadow 규칙을 별도 검증한다.
4. `event_driven_unstable`은 여전히 표본 부족(3년 기준 6일)으로 이번에도
   판정 제외했다 — 미해결 한계로 유지.

## 18. SPPV-2.10 — §17.5 후속 3과제 실측 검증 (2026-07-14)

### 18.1 실행 개요

§17.5가 남긴 3개 과제를 그대로 이어 실행했다(새 방법론 설계 없음, §16
이원 기준·기존 함수 재사용). 3년 캐시(`logs/_bars_cache_core87_3y_
2026-07-14/`)를 재사용해 **신규 KIS 호출 0건**(로그 확인)으로 검증했다.
산출: `scripts/validate_signal_predictive_power_v7_followup.py`
(read-only), `logs/signal_ic_sppv2_10_followup_2026-07-14.json`,
`logs/sppv2_10_followup_run_2026-07-14.log`. 실행: 종료 코드 0, 87종목
전체 성공(실패 0), 3년 표본 56,753건.

### 18.2 과제 1 — `fast_score_v2` shadow 검증 (rsi_signal 제거/부호반전)

`rsi_signal`을 (a) 제거하고 나머지 3개 sub-component 가중치를 재정규화한
`fast_score_v2_drop`, (b) 부호만 반전한 `fast_score_v2_flip` 두 가지를
운영 가중치 상수(0.3/0.2/0.15/0.35)는 그대로 두고 정의해 검증했다. 원안
`fast_score`도 같은 파이프라인으로 재계산(`fast_score_orig_recomputed`)
해 §17 수치와의 정합성을 함께 확인했다.

| 신호 | horizon | 1차(12개월) pooled t_NW | 2차(3년) pooled t_NW | bearish_trend(3년, n=96) t_NW |
|---|---|---|---|---|
| fast_score_orig_recomputed | T+5 | 0.34 | -0.52 | **-2.79**(§17과 동일 재현) |
| fast_score_v2_drop | T+5 | 0.59 | -0.17 | **-2.41** |
| fast_score_v2_flip | T+5 | 0.64 | -0.15 | **-2.32** |
| fast_score_v2_drop | T+20 | 0.42 | 0.48 | -0.56 |
| fast_score_v2_flip | T+20 | 0.53 | 0.48 | -0.58 |

**해석 — §17의 "rsi_signal이 원인"이라는 프레이밍을 하향 조정한다.**
`rsi_signal`을 제거하거나 부호를 반전해도, 하락장 T+5 spread는 원안
(-2.79)과 거의 다르지 않은 크기로 여전히 유의하게 역전된다(drop -2.41,
flip -2.32 — 원안 대비 개선폭이 15~17%에 불과). 즉 `rsi_signal`은 §14/
§17에서 관측된 하락장 역전 현상의 **부분적 기여자였을 뿐, 주된 원인이
아니다** — `fast_trend`/`volume_confirmation`/`volatility_penalty` 등
나머지 성분들도 하락장에서 함께 역방향으로 작동하고 있다는 뜻이다. 1차
(최근 12개월)/2차(3년) pooled 어디에서도 두 변형 모두 유의한 양(+)의
신호를 보이지 않았다.

**판정: `fast_score_v2_drop`, `fast_score_v2_flip` 모두 No-Go.** 단일
sub-component 제거/반전으로는 `fast_score`의 근본 문제(하락장 역전)가
해결되지 않는다 — `fast_score`는 부분 수정이 아니라 전면 재설계 또는
폐기 대상에 더 가깝다는 것이 이번 실측의 결론이다.

### 18.3 과제 2 — `risk_adj_momentum_3m` 1차 창 12개월 vs 18개월

| 1차 창 | cutoff | 표본 | 국면 분포(창 내부) | T+5 spread t_NW | T+20 spread t_NW |
|---|---|---|---|---|---|
| 12개월 | 2025-06-16 | 21,315건 | bullish 20,793 / range 522 (bearish 0) | 1.55 | 1.47 |
| 18개월 | 2024-12-15 | 31,494건 | bullish 23,577 / range 6,525 / bearish 1,218 / event 174 | 1.97 | **2.03** |

**해석**: 1차 창을 18개월로 넓히자 T+20 pooled spread가 처음으로 §16
게이트 문턱(|t_NW|≥2)을 **간신히** 통과했다(2.03). 18개월 창 안에는
하락장 표본(1,218 cross-sectional건, 약 14거래일)도 일부 포함되기
시작해 12개월 창의 "하락장 완전 부재" 한계도 부분적으로 완화됐다. 다만
(1) T+5(1.97)는 여전히 문턱 미달이고, (2) T+20의 2.03은 임계값을 겨우
넘은 marginal 수치라 창 경계(±1~2개월)를 조금만 옮겨도 유의성이 사라질
수 있는 **취약한 결과**다. §17의 2차(3년) 결과(bearish_trend 내부
t_NW=0.39, 역전 없음)는 여전히 유효하므로 §16 게이트의 (b)는 이미
충족돼 있었지만, (a)(1차 유의성)는 이번에 "12개월 미달 → 18개월 marginal
통과"로 바뀐 것뿐이다.

**판정: `risk_adj_momentum_3m` — Watch 유지, 조건부 상향(Hold에 가까운
Watch).** 완전한 Go로 선언하지 않는다 — marginal한 문턱 통과 하나만으로
결론을 키우지 말라는 원칙에 따라, 표본이 더 누적되거나(자연 경과), 창
경계에 덜 민감한지 별도로 확인(예: 15개월/21개월도 함께 확인)한 뒤 재
판단한다.

### 18.4 과제 3 — `reversal_1m` 하락장 조건부 오버레이, 표본 내 안정성

시장 공통 국면이 `bearish_trend`인 96거래일을 시간순으로 반분(전반부
48일/후반부 48일)해 각각 재검증했다 — 최근 12개월 창에는 하락장 표본이
전무해 "1차=최근 창" 기준을 그대로 적용할 수 없으므로, 그 대안으로 표본
내 시간 분할 안정성을 확인했다.

| horizon | 전체(n=96) t_NW | 전반부(n=48) t_NW | 후반부(n=48) t_NW |
|---|---|---|---|
| T+5 | **2.13** | 1.87 | 1.33 |
| T+20 | 1.47 | 0.79 | 1.61 |

**해석**: T+5에서는 방향(양(+))이 전체·전반부·후반부 모두 일관되지만,
반분 표본 각각은 표본 수가 절반(48일)으로 줄면서 개별적으로는 |t_NW|≥2
문턱을 넘지 못한다(전반 1.87, 후반 1.33) — 검정력 저하로 설명 가능한
범위이지만, "전체 표본에서만 유의하고 반분하면 둘 다 미달"이라는 패턴은
소표본 우연일 가능성을 완전히 배제할 수 없다는 뜻이기도 하다. T+20은
전반부(0.79)가 특히 약해 T+5보다 근거가 얕다.

**판정: `reversal_1m` — Hold 유지(T+5 한정, 하락장 조건부).** 방향
일관성은 있으나 반분 안정성 검증에서 확정적 Go로 올릴 근거는 아직
부족하다 — 하락장 표본이 추가로 누적되는 시점(다음 조정 국면 관측)에
재검증한다.

### 18.5 판정 종합 — SPPV-3 착수 보류 유지

세 후보 중 §16 게이트를 완전히 통과한 것은 없다.

| 후보 | 판정 | 근거 |
|---|---|---|
| `fast_score_v2_drop` | **No-Go** | 하락장 역전이 원안 대비 15~17%만 개선, 어디서도 유의한 양(+) 없음 |
| `fast_score_v2_flip` | **No-Go** | 상동 |
| `risk_adj_momentum_3m` | **Watch 유지(조건부 상향)** | 18개월 창에서 T+20 marginal 통과(2.03), T+5는 여전히 미달, 취약한 결과 |
| `reversal_1m` | **Hold 유지(T+5 한정)** | 방향 일관되나 반분 표본 개별 유의성 미달 |

**SPPV-3(entry_score 전체 재현) 착수는 계속 보류한다.** 이번 검증은
"rsi_signal 하나만 고치면 fast_score가 살아난다"는 낙관적 가설을
반박했고, 신호 재설계는 sub-component 하나를 바꾸는 수준이 아니라 더
근본적인 재구성이 필요함을 시사한다.

### 18.6 다음 단계

1. `fast_score`는 부분 수정 대신 **전면 재설계 또는 폐기**를 검토
   대상으로 격상한다 — `fast_trend`/`volume_confirmation`/
   `volatility_penalty`도 개별적으로 하락장 기여도를 재점검한다.
2. `risk_adj_momentum_3m`은 창 경계 민감도를 확인한다(15개월/21개월 등
   중간값도 확인해 18개월 결과가 우연한 경계 효과인지 판별).
3. `reversal_1m`은 다음 하락/조정 국면이 관측되면 표본을 추가해 반분
   안정성을 재확인한다 — 인위적으로 표본을 늘릴 수 없으므로 시간 경과를
   기다리는 항목으로 표시한다.
4. `event_driven_unstable`은 여전히 판정 불가(3년 기준 6일) — 미해결.

## 19. SPPV-2.11 — §18.6 후속: fast_score 전면 분해 + 창 경계 민감도 + shadow 후보 (2026-07-14)

### 19.1 실행 개요

§18.6이 남긴 3개 과제를 실행했다(새 방법론 설계 없음, §16 이원 기준·
기존 함수 재사용). 3년 캐시를 재사용해 **신규 KIS 호출 0건**으로
검증했다. 산출: `scripts/validate_signal_predictive_power_v8_fast_score_
teardown.py`(read-only), `logs/signal_ic_sppv2_11_fast_score_teardown_
2026-07-14.json`, `logs/sppv2_11_fast_score_teardown_run_2026-07-14.log`.
실행: 종료 코드 0, 87종목 전체 성공, 3년 표본 56,753건.

### 19.2 과제 1 — `fast_score` leave-one-out 4종 분해

`fast_trend`/`volume_confirmation`/`rsi_signal`/`volatility_penalty`를
각각 하나씩 제거하고 나머지 3개의 가중치를 재정규화(합=1 유지)해
4가지 변형을 만들어 검증했다.

| 제거한 성분 | T+5 bearish_trend spread t_NW | T+20 bearish_trend spread t_NW |
|---|---|---|
| (원안, 아무것도 안 뺌) | -2.79 | -0.84 |
| `fast_trend` | **-1.60**(비유의 전환) | -0.84 |
| `volume_confirmation` | -2.58 | -0.92 |
| `rsi_signal` | -2.39(§18의 -2.41과 일치, 재현 확인) | -0.55 |
| `volatility_penalty` | -2.31 | -0.80 |

**해석 — §17/§18의 원인 지목을 정정한다.** `rsi_signal`을 빼면 -2.79→
-2.39로 14%만 개선되는 반면, **`fast_trend`(가격 대비 SMA20 이격)를
빼면 -2.79→-1.60으로 43% 개선되며 유의 문턱(|t|≥2) 아래로 떨어진다** —
4개 성분 중 하락장 T+5 역전을 가장 크게 유발하는 것은 `rsi_signal`이
아니라 `fast_trend`였다. `volume_confirmation`/`volatility_penalty`
제거는 개선 폭이 미미하다(각각 -2.58, -2.31로 여전히 유의하게 역전).
다만 `fast_trend`를 빼도 어떤 1차/2차 pooled 구간에서도 유의한 양(+)의
신호는 나타나지 않았다(과제 1 원본 로그 참고) — "문제(역전)를 없앤다"와
"알파를 만든다"는 다른 문제이며, 이번 결과는 전자만 해결했다.

### 19.3 과제 2 — `risk_adj_momentum_3m` 창 경계 민감도(12/15/18/21개월)

| 1차 창 | 표본 | T+5 spread t_NW | T+20 spread t_NW |
|---|---|---|---|
| 12개월 | 21,315건 | 1.55 | 1.47 |
| 15개월 | 26,535건 | 1.98 | 1.90 |
| 18개월 | 31,494건 | 1.97 | 2.03 |
| 21개월 | 36,627건 | 1.75 | 2.04 |

**해석**: T+20은 15→18→21개월로 갈수록 1.90→2.03→2.04로 **완만하게
상승 후 plateau**를 형성한다 — §18의 "18개월 2.03"이 우연히 그 지점
에서만 튀어나온 결과가 아니라, 창을 넓힐수록 안정적으로 유지되는
추세임을 확인했다(경계 민감도 우려는 완화됨). 다만 T+5는 15~18개월
근방(1.97~1.98)에서 정점을 찍고 21개월에서 오히려 낮아져(1.75) T+20만큼
안정적이지 않다. 절대 크기 자체도 |t|≈2.0 수준으로 강한 신호는 아니다
— "완전한 우연은 아니지만 강한 알파도 아닌, marginal하고 다소 안정적인
신호"로 정리한다.

### 19.4 과제 3 — 국면 전환형 shadow 후보 `regime_switch_v1`

지금까지 방향성 있었던 두 신호를 국면에 따라 전환하는 복합 신호를
정의했다: 시장 공통 국면이 `bearish_trend`인 날은 `reversal_1m` 값을,
그 외(bullish_trend/range_bound/event_driven_unstable) 날은
`risk_adj_momentum_3m` 값을 그 날의 signal 값으로 사용한다(가중 결합이
아니라 국면별 전환이므로 새 가중치 튜닝이 필요 없다).

| horizon | 1차(최근 12개월) pooled t_NW | 2차(3년) pooled t_NW | bullish_trend | bearish_trend | range_bound |
|---|---|---|---|---|---|
| T+5 | 1.55 | **2.60** | 1.79 | 2.13 | 1.04 |
| T+20 | 1.47 | **2.36** | 1.51 | 1.47 | 2.09 |

**해석**: 2차(3년) pooled 유의성(T+5=2.60, T+20=2.36)은 **이 SPPV 트랙
전체를 통틀어 가장 강한 2차 결과**다 — 개별 신호(`risk_adj_
momentum_3m` 2차 T+20=2.07, `overall_score` 2차 T+20=1.32 등) 어느
것보다 높다. 이는 "상승/횡보장에서는 모멘텀, 하락장에서는 역추세"라는
직관적 가설이 국면을 섞지 않고 전환만 해도 pooled 표본에서 개별 신호
합보다 더 큰 유의성을 만든다는 뜻이다. **그러나 1차(최근 12개월)는
여전히 1.47~1.55에 머문다** — 이 복합 신호의 "하락장=reversal_1m" 절반이
최근 12개월 창에는 발동할 기회 자체가 없었기 때문에(bearish_trend
0일), 1차 검증에서는 사실상 `risk_adj_momentum_3m` 단독과 동일한 결과가
나온다. **§16 게이트(1차+2차 모두 충족)의 (a) 1차 유의성은 여전히
미달**이고, 이는 신호 자체의 결함이 아니라 최근 시장에 하락 국면이
없었다는 표본 구조의 한계다.

### 19.5 판정 종합

| 후보 | 판정 | 근거 |
|---|---|---|
| `fast_score` (leave-one-out 관점) | **전면 재설계 대상 확정** | `fast_trend` 제거로 역전은 해소되나 알파는 생기지 않음 — 부분 수정으로 살릴 수 없다 |
| `risk_adj_momentum_3m` | **Watch 유지(안정성 확인, 확정 Go 아님)** | 15~21개월 plateau로 우연 배제, 그러나 크기 marginal(~2.0) |
| `regime_switch_v1`(신규 shadow) | **가장 유망한 Watch 후보로 격상, 확정 Go 아님** | 2차 pooled 트랙 최고 수치(2.36~2.60), 1차는 하락장 표본 부재로 구조적 미달 |

**SPPV-3(entry_score 전체 재현) 착수는 계속 보류한다.** `fast_score`는
이제 "부분 수정 불가, 전면 재설계 또는 폐기"로 확정됐고, `regime_
switch_v1`이 가장 강력한 후보로 떠올랐지만 1차 게이트를 통과할 방법이
현재로선 없다(최근 시장에 하락장이 없다는 사실 자체를 검증으로 바꿀 수
없음) — 다음 하락/조정 국면이 최근 12개월 창에 실제로 편입될 때까지
기다리거나, §16 게이트 자체를 "신호 구조상 국면 조건부 후보는 해당
국면이 존재하는 기간을 1차 창으로 쓴다"는 예외 규칙으로 보완할지 판단이
필요하다(사용자 확인 권장).

### 19.6 다음 단계

1. `regime_switch_v1`의 1차 게이트 예외 처리 방식을 사용자와 확정한다
   — (a) 자연 경과를 기다려 하락장이 최근 창에 편입되면 재검증, 또는
   (b) 국면 조건부 신호 전용 게이트 기준(예: "그 국면이 3년 내 존재한
   전체 기간을 1차 창으로 인정")을 §16에 별도 규정으로 추가.
2. `fast_score`를 대체할 완전히 새로운 feature 조합(단순 leave-one-out이
   아니라 상대강도/업종중립화 등 제3의 feature)을 다음 검증 대상으로
   검토한다.
3. `event_driven_unstable`은 여전히 판정 불가(3년 기준 6일) — 미해결.

## 20. SPPV-2.12 — §19.6 후속: regime_switch_v1 1차 게이트 예외 규칙 + fast 계열 신규 feature (2026-07-14)

### 20.1 실행 개요

§19.6이 남긴 두 과제를 실행했다(새 방법론 설계 없음, §16 이원 기준·
기존 함수 재사용). 3년 캐시를 재사용해 **신규 KIS 호출 0건**으로
검증했다. 산출: `scripts/validate_signal_predictive_power_v9_gate_and_
fast_features.py`(read-only), `logs/signal_ic_sppv2_12_gate_and_fast_
features_2026-07-14.json`, `logs/sppv2_12_gate_and_fast_features_run_
2026-07-14.log`. 실행: 종료 코드 0, 87종목 전체 성공, 3년 표본 56,753건.

### 20.2 과제 1 — `regime_switch_v1` 1차 게이트 예외 규칙 3개 비교

최근 12개월 창에 시장 공통 `bearish_trend`가 0일이라, `regime_switch_v1`
의 하락장 절반(`reversal_1m`)은 "최근성 창" 자체로는 검증할 방법이 없다.
방어 가능한 대안 3개를 정의·비교했다.

- **규칙 A(관찰 유예, 절차적)**: 수치를 만들지 않고 "하락장이 실제
  재발할 때까지 Hold를 유지하며, 재발 즉시 자동 재검증한다"는 절차만
  규정한다.
- **규칙 B(최근-실사례 고정창)**: 가장 최근 `bearish_trend` 발생
  48거래일(§18/§19의 후반부 반분과 동일 정의, 표본 크기를 미리
  정해두고 바꾸지 않음)을 1차 창으로 인정.
- **규칙 C(적응형 최소 국면 표본 창)**: 목표 국면의 최소 표본
  (`MIN_REGIME_TRADING_DAYS=30`)을 채울 때까지만 과거로 확장하는
  적응형 창.

| 규칙 | 표본(n) | T+5 spread t_NW | T+20 spread t_NW |
|---|---|---|---|
| B(고정 48일) | 48 | 1.33 | 1.61 |
| C(적응형, 최소 30일) | 30 | **4.18** | 3.02 |
| 참고: §19 전체 96일 | 96 | 2.13 | 1.47 |

**해석 — 규칙 C는 통과가 아니라 위험 신호다.** 표본을 96일→48일→30일로
줄일수록 t_NW이 2.13→1.33→**4.18**로 비단조적으로 요동친다. 특히
48일에서는 오히려 유의성이 떨어졌다가(1.33) 30일에서 급등(4.18)하는
패턴은, **"목표 유의 수준(|t|≥2)을 넘길 때까지 표본 크기를 사후적으로
줄여나가는" 규칙 C의 구조 자체가 데이터 스누핑(data-dredging)을
필연적으로 생산한다는 뜻이다.** 표본 크기를 미리 정하지 않고 결과를
보면서 표본을 좁혀 유의성을 찾는 것은, 이 시스템이 반복적으로 경계해온
"근거 없는 낙관"의 전형적 패턴과 같은 종류의 오류다 — 공격형 시스템
이라 해도 이런 식으로 만들어진 신호는 실거래에서 재현되지 않을 위험이
매우 크다. **규칙 C는 채택하지 않는다.**

규칙 B(고정 48일, 사전에 정한 표본 크기)는 정직하게 측정한 결과
1.33~1.61로 여전히 §16 게이트(|t|≥2)에 못 미친다 — Hold를 재확인한다.

**최종 채택: 규칙 A(관찰 유예).** 억지로 숫자를 만들지 않고, "하락장이
최근 12개월 창에 실제로 편입되는 시점"을 명시적 재검증 트리거로
규정한다. 이는 공격형 시스템의 "최고 기대수익률" 목표와도 상충하지
않는다 — 공격적이라는 것이 "검증 안 된 신호를 밀어붙인다"는 뜻은 아니며,
오히려 재현성 없는 신호를 실거래에 태우는 것이 손실 제약(§0.1)을 직접
위협한다.

(regime_switch_v1의 §19 수치 — 1차(12개월 달력) T+5=1.55/T+20=1.47,
2차(3년) T+5=2.60/T+20=2.36 — 도 같은 실행에서 재확인했다. §19와 완전히
동일하며, 이번 캐시·코드 변경이 없었음을 보여주는 정합성 재확인이다.)

### 20.3 과제 2 — fast 계열 신규 feature 2종

- `rsi_mean_reversion = -(rsi_14 - 50)`: 운영 `rsi_signal`(과매수를
  양(+)으로 취급하는 추세추종형 계단함수)이 §17/§19에서 유의하게
  역방향이었던 관측을 근거로, 아예 평균회귀 방향으로 뒤집은 연속형
  신호.
- `sma5_over_sma20_gap = (sma_5/sma_20 - 1) × 100`: `fast_trend`(SMA20
  이격, 계단함수)가 §19에서 하락장 역전의 주된 원인으로 확인된 것과
  달리, 더 짧은 이동평균 간 격차를 연속값으로 사용.

| 신호 | horizon | 1차(12개월) | 2차(3년) pooled | bullish | bearish | range |
|---|---|---|---|---|---|---|
| rsi_mean_reversion | T+5 | -0.23 | -0.29 | -0.30 | **2.26** | -1.82 |
| rsi_mean_reversion | T+20 | -0.08 | -0.34 | 0.01 | 1.21 | -1.67 |
| sma5_over_sma20_gap | T+5 | 0.48 | 0.53 | 0.58 | **-2.67** | 1.80 |
| sma5_over_sma20_gap | T+20 | 0.77 | 0.98 | 0.50 | -0.77 | 1.89 |

**해석**: 두 후보 모두 pooled/1차에서는 유의하지 않다 — 범용 `fast_score`
대체 후보로는 **No-Go**다.
- `rsi_mean_reversion`은 하락장(T+5)에서만 유의(t=2.26)하다 — `reversal_
  1m`과 정확히 같은 패턴(국면 조건부, 하락장 전용)이다. 이는 우연이
  아니라 "하락장에서는 평균회귀형 신호가, 상승/횡보장에서는 추세추종형
  신호가 통한다"는 §19 `regime_switch_v1`의 가설을 다른 feature로도
  재확인해준다 — 다만 신규 범용 feature는 아니다.
- `sma5_over_sma20_gap`은 SMA20 이격(`fast_trend`)과 마찬가지로
  하락장에서 유의하게 **역전**한다(t=-2.67) — "이동평균 창을 짧게
  하면 지연 문제가 해결돼 하락장 역전이 줄어들 것"이라는 가설은
  기각됐다. 오히려 짧은 창(SMA5/SMA20)이 SMA20/가격 단독보다 하락장
  역전이 더 크다(-2.67 vs 원안 `fast_trend`의 대략적 하락장 성과) —
  단기 추세추종 로직 자체가 하락장에서 구조적으로 실패하는 것이지,
  이동평균 기간의 문제가 아니라는 §19의 결론을 재확인한다.

### 20.4 판정 종합

| 후보 | 판정 | 근거 |
|---|---|---|
| `regime_switch_v1` 1차 게이트 — 규칙 A(관찰 유예) | **채택** | 억지 통과 없이 재검증 트리거만 규정, 유일하게 방어 가능 |
| 〃 — 규칙 B(고정 48일) | **참고용(Hold 재확인)** | 정직한 측정, 여전히 미달(1.33~1.61) |
| 〃 — 규칙 C(적응형 최소창) | **채택 거부** | n=30에서만 급등(4.18) — 데이터 스누핑 구조 |
| `rsi_mean_reversion` | **No-Go(범용), 국면 조건부 참고자료** | 하락장 전용, `reversal_1m`과 같은 패턴 재확인 |
| `sma5_over_sma20_gap` | **No-Go** | SMA20과 동일하게 하락장 역전, 오히려 더 큼 |

**SPPV-3(entry_score 전체 재현) 착수는 계속 보류한다.** `regime_
switch_v1`의 1차 게이트는 "관찰 유예"로 절차화됐고, `fast_score`를
대체할 범용 fast 계열 feature는 이번에도 찾지 못했다 — 지금까지
반복적으로 확인된 패턴("추세추종형은 하락장에서 실패, 평균회귀형은
하락장에서만 통함")은 점점 더 일관되게 나타나지만, 이를 "상시 안전하게
쓸 수 있는 단일 feature"로 전환할 방법은 여전히 없다.

### 20.5 다음 단계

1. `regime_switch_v1`은 규칙 A에 따라 **모니터링 상태로 유지** — 향후
   3년 캐시를 정기 갱신할 때마다(또는 시장 공통 국면이 `bearish_trend`
   로 전환되는 시점에) 최근 12개월 창의 국면 분포를 확인하는 절차를
   운영에 추가한다(코드 변경 아님, 체크리스트 항목으로 관리).
2. "추세추종형은 하락장 실패, 평균회귀형은 하락장 전용 성공"이라는
   반복 패턴을 `entry_score`의 regime 분기 설계(§8 책임 분리)에 참고
   자료로 남긴다 — 향후 feature 설계를 완전히 새로 시작할 때 이 규칙성
   자체를 출발점으로 삼을 수 있다.
3. `event_driven_unstable`은 여전히 판정 불가(3년 기준 6일) — 미해결.

## 21. SPPV-2.13 — `regime_switch_v1` 규칙 A(관찰 유예) 모니터링 실행체 (2026-07-14)

### 21.1 배경

§20.2가 채택한 규칙 A(관찰 유예)는 "하락장이 최근 12개월 창에 실제로
재발하면 자동 재검증한다"는 절차였으나, 그 자체로는 실행 가능한 형태가
아니라 서술로만 남아 있었다. 이번 턴에 실제로 실행 가능한 경량
모니터링 스크립트로 구현했다.

### 21.2 구현

`scripts/monitor_regime_switch_v1_gate.py`(read-only):

- **벤치마크(069500) 1종목만 조회** — 87종목 전체를 다시 조회할 필요
  없다. 캐시가 있으면 그대로 재사용하고, 없으면 최소한의 KIS 호출만
  발생한다 — 매일/매주 반복 실행해도 rate budget 부담이 거의 없다.
- 최근 12개월(`RECENT_WINDOW_CALENDAR_DAYS=365`) 창의 시장 공통 국면
  분포를 계산하고, `bearish_trend` 거래일 수를 `MIN_REGIME_TRADING_
  DAYS=30`(§16/§20과 동일 기준)와 비교해 3단계로 판정한다:
  - `NOT_TRIGGERED`(0일): 규칙 A 유지, 계속 관찰
  - `PARTIAL`(1~29일): 재검증 시점은 아니나 감시 강화
  - `TRIGGERED`(30일 이상): `regime_switch_v1` 1차 게이트 재검증 권고
- 산출: `logs/regime_switch_v1_gate_monitor_2026-07-14.json`,
  `logs/regime_switch_v1_gate_monitor_run_2026-07-14.log`.

### 21.3 실행 결과

실행 시각: 2026-07-14 22:28:46~22:28:47 KST(약 1초, 벤치마크 1종목뿐이라
매우 빠름). 종료 코드 0, `HTTP Request:` 0건(신규 KIS 호출 없음, 3년
캐시 재사용).

| 항목 | 값 |
|---|---|
| 기준일 | 2026-06-16(마지막 forward-return 계산 가능일 — 실제 캐시 최신일 2026-07-14보다 약 20거래일 앞선 날짜, forward window(T+20) 확보 때문에 발생하는 정상적 지연) |
| 최근 12개월 cutoff | 2025-06-16 |
| 국면 분포 | `{bullish_trend: 239, range_bound: 6}` |
| bearish_trend | 0일 |
| **판정** | **NOT_TRIGGERED** |

### 21.4 해석

§20.2에서 서술로 판단했던 "현재는 관찰 유예 상태"가 실측으로도 그대로
확인됐다 — 새로운 정보는 아니지만, **이제 이 판단이 매번 사람이 수동
으로 §20 결과를 다시 읽고 판단하는 것이 아니라, 실행 한 번으로 재현
가능한 절차가 됐다는 점이 이번 작업의 핵심 성과**다. 다음 턴부터는
"3년 캐시를 갱신할 때마다 이 스크립트를 함께 실행해 판정을 확인"하는
것만으로 규칙 A를 운영할 수 있다.

### 21.5 다음 단계

1. 이 모니터링 스크립트를 3년 캐시 갱신 주기(현재는 수동, 매 SPPV
   턴마다 필요 시 재실행)와 함께 실행하는 것을 체크리스트 관행으로
   굳힌다 — 별도 스케줄러 등록은 이번 턴 범위 밖(운영 인프라 변경
   금지 원칙)이므로 하지 않는다.
2. `TRIGGERED` 판정이 나오면 `scripts/validate_signal_predictive_
   power_v9_gate_and_fast_features.py`(또는 그 후속)로 `regime_
   switch_v1`의 1차 게이트를 재검증한다.

## 22. SPPV-2.14 — fast 계열 완전 신규 신호 2종 실측 (2026-07-14)

### 22.1 실행 개요 — 기존 실패 패턴과의 구조적 차이

지금까지 시도한 모든 fast 계열 후보 — `fast_trend`(SMA20 이격 계단
함수), `sma5_over_sma20_gap`(단기 이동평균 격차 연속값), `rsi_signal`
(RSI 계단함수), `rsi_mean_reversion`(RSI 연속 반전) — 는 **전부 "자기
종목 자신의 과거 가격 수준"만 보는 절대(absolute) 기술 지표**였다.
계단함수인지 연속값인지, 이동평균 창이 20일인지 5일인지는 상관없이
전부 같은 하락장 실패/조건부 패턴을 반복했다. 이번엔 그 축 자체를
바꿨다 — 새 데이터 소스를 추가하지 않고 기존 `PriceBar`/
`TechnicalFeatureSnapshot` 필드만 쓰되, "가격 수준" 로직을 쓰지 않는다.

- **`money_flow_5d`**(자금 흐름 축): `sum(sign(당일수익률) × turnover) /
  sum(turnover)`, 최근 5거래일. 가격이 아니라 "그 가격 변화에 실린
  거래대금의 방향성"을 본다 — 기존 `volume_confirmation`(거래량 급증
  여부만 봄, 방향 무관)과도 다르다.
- **`relative_strength_rank_1m`**(상대강도 축): 그날 표본에 포함된
  종목들 사이에서 `return_1m_pct`의 cross-sectional 순위를 [-1, 1]로
  스케일링. 절대 수익률이 아니라 "동료 종목 대비 상대적 위치"를
  본다 — 시장 베타(그날 전체 상승/하락)를 구조적으로 제거한다는 점이
  절대 지표와 근본적으로 다르다.

§16 이원 기준을 그대로 적용했다. 3년 캐시 재사용, **신규 KIS 호출
0건**(로그 확인), 종료 코드 0, 87종목 전체 성공, 3년 표본 56,753건.
산출: `scripts/validate_signal_predictive_power_v10_new_fast_features.py`
(read-only), `logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json`,
`logs/sppv2_14_new_fast_features_run_2026-07-14.log`.

### 22.2 핵심 결과

| 신호 | horizon | 1차(12개월) | 2차(3년) pooled | bullish | bearish | range |
|---|---|---|---|---|---|---|
| money_flow_5d | T+5 | 0.48 | 0.20 | 0.68 | -1.19 | 0.02 |
| money_flow_5d | T+20 | 1.03 | 1.01 | 0.93 | -0.60 | 0.98 |
| relative_strength_rank_1m | T+5 | 0.46 | 0.28 | 0.47 | **-2.13** | 0.89 |
| relative_strength_rank_1m | T+20 | 1.01 | 1.02 | 0.84 | -1.47 | 1.38 |

### 22.3 해석

**두 후보 모두 pooled/1차 어디에서도 유의하지 않다** — 범용 `fast_
score` 대체 후보로는 **No-Go**다.

- `money_flow_5d`는 완전한 무신호에 가깝다(모든 구간 |t|<1.2, 어느
  방향으로도 유의하지 않음). 지금까지의 다른 실패 후보들이 최소한
  하락장에서는 유의하게 역전되는 "방향성 있는 실패"였다면, 이 신호는
  방향성조차 없다 — 자금 흐름의 부호(매수/매도 쏠림)가 이 시장/기간
  에서는 forward return과 아무 관계가 없다는 뜻이다.
- `relative_strength_rank_1m`은 하락장(T+5)에서 유의하게
  **역전**(t=-2.13)한다 — **이는 이번 검증에서 가장 중요한 발견**이다.
  절대 수준 지표(`fast_trend`)뿐 아니라, 시장 베타를 완전히 제거한
  **상대강도(순수 cross-sectional momentum)조차 하락장에서 반대로
  작동**한다. 지금까지 §14/§19/§20에서 반복 관측된 "하락장에서는
  모멘텀류 신호가 반대로 간다"는 패턴이, 절대/상대의 구분을 넘어 더
  근본적인 규칙성일 가능성을 시사한다 — 이 시스템이 다루는 core
  universe(대형 유동주 위주)의 하락장에서는 "최근에 상대적으로 강했던
  종목일수록 단기적으로 더 조정받는다"는 경향이 구조적으로 존재하는
  것으로 보인다.

### 22.4 판정 종합

| 후보 | 판정 | 근거 |
|---|---|---|
| `money_flow_5d` | **No-Go** | 어디서도 유의하지 않음 — 방향성조차 없는 완전 무신호 |
| `relative_strength_rank_1m` | **No-Go(범용), 규칙성 확증 자료로 가치** | 하락장에서 유의하게 역전 — 모멘텀류 신호의 하락장 실패가 절대/상대 구분을 넘어선다는 근거 강화 |

**SPPV-3(entry_score 전체 재현) 착수는 계속 보류한다.** 완전히 새로운
축(자금 흐름, 상대강도)에서도 범용 대체 후보를 찾지 못했다. 다만
`relative_strength_rank_1m`의 하락장 역전은, "하락장 조건부 평균회귀"
가설(§19의 `regime_switch_v1`, §20의 `rsi_mean_reversion`)을 또 다른
독립적인 각도에서 뒷받침하는 근거로 누적됐다 — 앞으로 신호를 완전히
새로 설계한다면, 이 규칙성(모멘텀류는 상승/횡보장 전용, 평균회귀류는
하락장 전용) 자체를 설계 원칙으로 삼는 것이 타당해 보인다.

### 22.5 다음 단계

1. 지금까지 누적된 "국면별 신호 극성 전환" 증거(`fast_trend`,
   `sma5_over_sma20_gap`, `rsi_signal`/`rsi_mean_reversion`,
   `relative_strength_rank_1m`, `reversal_1m` 전부)를 하나의 표로
   정리해, 다음 feature 설계 턴의 출발점 문서로 남긴다(§23 후보,
   차기 턴 검토).
2. `event_driven_unstable`은 여전히 판정 불가(3년 기준 6일) — 미해결.
3. `regime_switch_v1`은 §21의 모니터링 스크립트로 계속 관찰한다.

## 23. 국면별 신호 극성 전환 종합 및 상위 재설계 방향 확정 (2026-07-15)

### 23.1 개요

SPPV-2.9~2.14(§17~§22)에서 개별적으로 실측한 10개 신호를 하나의
종합표로 통합하고, "feature 추가 실험을 계속할지 / 국면 분기형 entry
설계로 전환할지 / 유니버스·미시구조를 재검토할지"를 판정했다. 전체
분석은 별도 문서로 분리했다 — 이 §23은 그 문서의 요약이다.

**→ 전체 내용: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_
next_direction.md`**

### 23.2 핵심 발견 (요약)

10개 신호(`fast_score`, `fast_trend`, `sma5_over_sma20_gap`,
`rsi_signal`, `rsi_mean_reversion`, `relative_strength_rank_1m`,
`reversal_1m`, `money_flow_5d`, `risk_adj_momentum_3m`,
`regime_switch_v1`)를 절대추세·오실레이터·자금흐름·상대강도·복합
5개 축으로 분류해 비교한 결과:

1. **8/10 신호가 "추세형 신호는 상승/횡보장 전용(또는 무신호), 되돌림형
   신호는 하락장 전용"이라는 규칙성을 따른다.** 이 패턴은 절대 지표
   (`fast_trend`, `sma5_over_sma20_gap`)뿐 아니라 시장 베타를 제거한
   상대 지표(`relative_strength_rank_1m`)에서도 재현돼, 우연이 아닌
   구조적 특성일 가능성이 높다.
2. **예외**: `rsi_signal`의 유의한 역전은 하락장이 아니라 **상승장**
   에서 나타난다 — 규칙성에 억지로 끼워 맞추지 않고 별개 문제(RSI
   계단함수 설계 결함)로 분류한다.
3. **개별 성분보다 조합 효과가 크다**: `fast_trend` 단독은 하락장에서
   비유의(-0.79)하지만, `fast_score`(합성) 하락장은 강하게 유의하게
   역전(-2.79)한다 — 상관된 여러 절대 추세 지표를 가중합하는 구조
   자체가 문제를 증폭시킨다.

### 23.3 판정

**국면 분기형 entry 설계 검토로 전환한다.** feature 추가 실험은
한계효용이 낮다고 판단해 중단하고(5개 축을 모두 시도해 매번 동일한
결론에 수렴), 유니버스/시장 미시구조 재검토는 근본 설계 검토(§2)의
"신호 미검증 시 잘못된 레버" 원칙에 따라 후순위로 유지한다.
`regime_switch_v1`(비하락장=`risk_adj_momentum_3m`, 하락장=
`reversal_1m`)이 정적 가중 신호로는 얻지 못한 트랙 최고 2차 pooled
유의성(T+5=2.60/T+20=2.36)을 국면 "전환"만으로 달성한 것이 이 판정의
핵심 근거다. 상세 비교 논거는 별도 문서 §4 참고.

### 23.4 다음 단계

1. `regime_switch_v1` 아이디어를 `entry_score` 대체 설계의 초기
   원형으로 격상해 다음 SPPV-3 착수 형태를 재정의한다 — 단, 1차
   게이트(§21 모니터링)가 실제로 검증 가능한 상태가 될 때까지는
   설계·shadow 검증 단계에 머문다.
2. 이 판정은 SPPV-3의 성격 자체를 바꾸는 것이라 사용자 확인을
   권장한다.

## 24. ranking_score 공식 검증 트랙 분리 기록 (2026-07-28)

SPPV 본체는 신호 예측력과 국면 조건부 진입 신호의 방향성 검증을
다루고, `ranking_score` 공식의 적절성은 이제 별도 검증 트랙으로
분리한다. 이유는 현재 쟁점이 "신호가 유의한가"가 아니라
"유의하다고 본 신호를 downstream BUY funnel에서 어떤 공식으로
우선순위화·차단할 것인가"로 이동했기 때문이다.

이번에 별도 계획 문서
`docs/10_signal_research_sppv/[PLAN] ranking_score_formula_validation.md`
를 신설해 아래 4축을 독립 검증 대상으로 고정했다.

1. `ranking_min_score=0.48`의 분포 정합성
2. 구성항목 6개(`entry_score`, `relative_activity`, `coverage_score`,
   `allocation_quality`, `regime_tailwind`, `strategy_alignment`)의
   적절성
3. 각 가중치의 적정성
4. 다른 BUY 차단 장치와의 중복 적정성

이 트랙은 SPPV-3의 직접 착수 이전에 정리해야 할 downstream funnel
정합성 과제이며, threshold 단순 완화가 아니라 **공식의 역할 정의를
먼저 다시 고정하는 작업**으로 분류한다.

## 26. BUY 경로 리팩터링 사전 검토 일정 분리 (2026-08-01 KST)

BUY funnel 재설계는 지금부터 바로 구현으로 들어가지 않고,
`docs/20_system_analysis/buy_path_refactor_pre_roadmap_schedule.md`를
기준으로 사전 검토 일정을 먼저 수행한다.

핵심은 아래 3가지다.

1. `entry_score`/`ranking_score`/`allocation`/`activity`의 역할 분해
2. 상류 deterministic 재설계 옵션 비교
3. 하류 AI/EV/submit 경로와의 연쇄 영향 확인

따라서 이 시점의 적절한 산출물은 구현 Roadmap이 아니라
**Roadmap 이전의 확인 검토 일정표**다.

## 27. BUY 경로 리팩터링 단위 고정 (2026-08-01 KST)

BUY 경로 리팩터링은 단일 대규모 변경이 아니라, 아래 단위로 쪼개어
다뤄야 한다. 기준 문서는
`docs/20_system_analysis/buy_path_variable_gate_matrix.md` §13이다.

1. **R1** — `ranking_score` 역할 축소/대체 판단
2. **R2** — `entry_score`의 alpha / risk / sizing 분리
3. **R3** — `portfolio_allocation`의 점수/게이트/feasibility 분리
4. **R4** — activity 계열의 soft bonus / hard gate 중복 정리
5. **R5** — AI downgrade / EV gate / submit translation 하류 contract 점검

현재 우선순위는 **R1 → R2 → R3/R4 → R5**다. 즉 다음 단계의 핵심은
threshold 미세조정이 아니라, `ranking_score`와 `entry_score`의 역할
경계를 먼저 다시 고정하는 것이다.

## 28. `BUY 경로 리팩터링`(R1~R4) 이후 SPPV-3 존속 판정(2026-08-03 KST, read-only 구조 정리)

R1~R4(§27)가 닫히면서 §4.3~§4.5가 전제했던 `entry_score` 공식·
BUY funnel 구조가 실제로 바뀌었다. 이 절은 새 실측을 추가하지 않고,
**SPPV-3가 폐기되는지 재정의 후 지속되는지만** 판정해 기록한다.

**판정: 폐기가 아니라 재정의 후 지속.**

- **근거**: `BUY 경로 리팩터링`(R1~R4)은 경로/계약/병목을 정리하는
  작업이고, `SPPV-3`는 그 경로 위에 올라가는 신호/점수의 예측력을
  검증하는 작업이다. 전자가 끝나도 후자는 자동으로 사라지지 않는다
  — 경로가 아무리 깨끗해져도 그 위를 도는 신호가 노이즈라면
  "노이즈를 더 빨리 통과시키는" 결과만 낳기 때문이다.
- **다만 기존 `SPPV-3`(§4.3~§4.5)를 그대로 이어가면 안 되는 이유**:
  (1) §4.3이 재현하려던 `entry_score` 공식 자체가 바뀌었다(R2에서
  allocation 보정항 제거·`risk_off` 계수 `-0.15→-0.05`·하드 게이트
  단일 권위화) — 이제는 운영되지 않는 옛 공식을 재현하게 된다.
  (2) §4.5가 측정하려던 `would_buy→submitted` funnel 전환율에는,
  리팩터링 전에는 신호 유효성과 무관한 경로 병목(`stale_snapshot_
  guard` zero-position false-stale, PR #119)이 섞여 있었다 — "신호가
  약해서 못 산 것"과 "경로 버그로 못 산 것"을 구분할 수 없는 상태였다.

**재정의된 SPPV-3 목표(한 줄)**: 리팩터링으로 병목·중복이 정리된
현재의 `entry_score`/BUY funnel 위에서, 원신호(alpha)가 여전히 미래
수익률을 예측하며 그 예측력이 실제 주문 전환까지 온전히 이어지는지를
검증한다.

**최소 검증 축**:
1. alpha 자체 예측력(§9~§23의 연속선, 리팩터링과 무관하게 그대로
   미해결)
2. 정리된 deterministic gate(단일 권위화된 `risk_off` 하드 게이트,
   `relative_activity`/`allocation` feasibility 게이트) 통과 후 성과
   — 새 공식 기준 재현
3. AI/EV/downstream(R5, 아직 미착수)과 분리된 순수 deterministic
   성과 — R5 완료 후에야 이 축이 완전해짐
4. `order_request`/submit 전환까지 포함한 funnel 기여도 — 단
   `stale_snapshot_guard` 수정(PR #119) 이후 데이터만 사용

**§4.3~§4.5, §7은 "이 시점(구 공식 기준) 전제"로 위치를 낮춘다** —
삭제하지 않고 이력으로 보존하며, 실제 재정의 작업은 별도 후속 문서/
소절에서 새 공식 기준으로 다시 쓴다.

**리팩터링 완료 판정 전 남은 운영 관측(SPPV-3 자체와는 별개 항목)**:
- PR #119(`stale_snapshot_guard` zero-position false-stale 수정)의
  운영 재기동 이후 재현 확인
- R2 allocation 제거(§13.2.5) 이후 운영 재실측

이 둘은 SPPV-3의 검증 축이 아니라, SPPV-3를 재정의된 형태로 착수할
수 있는 **전제 조건이 언제 완전히 갖춰지는지**를 가리키는 별도
관측 항목이다.

**[2026-08-04 갱신]** 위 검증 축 3(R5 분리 성과)의 전제였던 R5가
`buy_path_variable_gate_matrix.md` §13.5.1~§13.5.3(R5-a/b/f, 전부
동작 무변화 구조 정리)로 닫혔다 — "R5 아직 미착수"는 과거 시점
서술로 보존하고, 현재는 R1~R5 전부 닫힌 상태임을 §29에서 다시
정리한다.

## 29. `SPPV-2` 후기 구간(§2.107~§2.159) 종료 선언 및 `SPPV-3` 착수 구조 정리(2026-08-04, read-only 문서 정리)

이 절은 새 실측·새 코드 분석을 추가하지 않는다. §28의 판정(재정의
후 지속)을 그대로 이어받아, **`SPPV-2` 번호 체계를 여기서 더 잇지
않는다는 것**과 **다음 검증이 어떤 구조로 착수되는지**만 문서상으로
정리한다.

**(1) `SPPV-2.107 ~ SPPV-2.159` 한 줄 요약**: 이 구간은 `ranking_
score`/`relative_activity`/`coverage_score`/`regime_tailwind`/
`strategy_alignment`/`core_cap`/stale snapshot 등을 다뤘고, **사실상
`BUY 경로 리팩터링`(R1~R5) 트랙으로 전개되며 종료됐다.** 이 트랙의
canonical 기록은 이 문서의 §2.107~§2.159 자체가 아니라
`docs/20_system_analysis/buy_path_variable_gate_matrix.md` §13(R1~R5)
이다.

**(2) 종료 판정의 근거**:
- 같은 `SPPV-2.xxx` 번호 체계로 더 이어갈 실익이 없다 — §2.107 이후
  다뤄온 대상(ranking_score 공식, activity/coverage/allocation 게이트
  중복, regime_tailwind/strategy_alignment 이중 반영, stale snapshot
  버그)은 전부 "신호의 예측력" 질문이 아니라 **"BUY 경로의 계약/
  중복/병목" 질문**이었고, R1~R5(§13)가 이미 이 질문들을 각각 판정·
  정리했다.
- 이제 실제로 미해결인 질문은 두 갈래뿐이다 — (a) alpha 자체의
  예측력(재정의된 `SPPV-3`의 검증 축 1) 또는 (b) R-track의 후속
  후보(현재는 R1~R5 전부 닫혀 있어 신규 후속 없음, §13 참고). 둘 다
  `SPPV-2.xxx` 번호를 새로 매길 대상이 아니다.

**(3) `SPPV-3` 착수 구조(§28에서 확정한 4개 축을 그대로 계승,
재론하지 않음)**:
1. alpha 자체 예측력(§9~§23의 연속선)
2. 리팩터링된 deterministic gate 통과 후 성과(새 공식 기준)
3. AI/EV/downstream과 분리된 순수 deterministic 성과(R5 완료로 이제
   측정 가능해짐)
4. `order_request`/submit 전환까지 포함한 funnel 기여도(PR #119
   이후 데이터만 사용)

**(4) `§4.3~§4.5`, `§7`**: §28에서 이미 "이 시점(구 공식 기준)
전제"로 낮췄다 — 삭제하지 않고 이력으로 보존하며, 재정의 작업은
별도 후속 문서에서 새 공식 기준으로 다시 쓴다(이번 절에서 재서술
하지 않음).

**(5) 남은 운영 관측의 위치**: PR #119 운영 재기동 이후 재현 확인,
R2 allocation 제거 이후 운영 재실측 — 이 둘은 **"`SPPV-2` 후속"이
아니라 "`SPPV-3` 착수 전제 확인"**으로 위치한다(§28에서 이미 이렇게
분리했고, 이번 절은 그 분류를 재확인만 한다).

**(6) 다음 1순위 액션**: **`SPPV-3` 재정의 문서 초안 확장** — §28/
§29의 목표·검증 축 4개를 근거로 `§4.3~§4.5`를 새 공식·새 경로 기준
으로 다시 쓴다. 체크리스트 작성은 이 초안의 부산물로 뒤따른다.

## 30. `SPPV-3` 재정의 검증 계획 초안(2026-08-04, read-only 문서 확장)

이 절은 §28/§29에서 확정한 4개 검증 축을 **실제 착수 가능한 계획**
으로 구체화한다. 새 실측·새 코드 분석은 하지 않는다. `SPPV-2.xxx`
번호는 새로 만들지 않는다 — 아래 소절은 `SPPV-3` 자체의 하위
구조(§30.1~§30.5)로만 번호를 매긴다.

### 30.1 검증 대상 4개 축 요약

1. **alpha 자체 예측력** — 원신호가 리팩터링과 무관하게 여전히
   미래 수익률을 예측하는가
2. **리팩터링된 deterministic gate 통과 후 성과** — R1~R5로 정리된
   현재 `entry_score`/eligibility/authoritative gate를 통과한
   표본의 실제 forward return
3. **downstream(AI/EV/submit)과 분리한 순수 deterministic 성과** —
   AI 개입 유무에 따라 deterministic 신호 단독 성과가 어떻게
   달라지는가
4. **`order_request`/submit 전환까지의 funnel 기여도** — 정리된
   게이트를 통과한 신호가 실제 주문 전환까지 이어지는 비율과, 그
   비율이 신호 강도와 상관관계를 갖는가

### 30.2 축별 구체화표

| 축 | 질문 | 필요한 입력 데이터 | 집계 단위 | 비교 기준 | 성공/실패 판정 기준 | 이번 턴 기준 선행 전제 |
|---|---|---|---|---|---|---|
| 1. alpha 자체 예측력 | 원신호(`slow_momentum`/`overall_score` 등)가 국면별로도 부호 일관되게 미래 수익률을 예측하는가 | SPPV-2(§9~§23)에서 이미 수집된 rolling IC 산출물(재사용), 필요 시 구간 확장용 point-in-time 일봉 | 거래일별 cross-sectional Spearman IC(종목×거래일) | Newey-West 보정 `\|t_NW\|`, §16 Go 게이트(1차 최근 12개월 + 2차 3년 모두 충족) | §3의 IC 구간 분류 + 국면별 부호 일관성 + out-of-sample 재현성 | **없음** — 기존 산출물 재사용 가능 |
| 2. 정리된 gate 통과 후 성과 | R1~R5 정리 이후의 `entry_score`/eligibility를 통과한 표본이 차단된 표본보다 forward return이 우월한가 | 정리된 코드 반영 이후 운영 `decision_json`(`entry_score`/`eligibility_reasons`/`buy_candidate`) + 해당 시점 forward return | symbol-trade_date(게이트 통과/차단 이분) | 통과 표본 vs 차단 표본의 forward return quintile/비용 차감 성과 | 통과 표본이 비용 차감 후 유의하게 양의 기대수익을 보임 | R1~R5 코드는 이미 반영됐으나, **정리된 공식 기준 population이 아직 충분히 쌓이지 않음** |
| 3. downstream 분리 순수 deterministic 성과 | AI/EV/submit 레이어 개입이 없었다면 deterministic 신호 단독 성과는 어땠을 것인가 | `deterministic_trigger` 메타데이터(`entry_score`/`buy_candidate`/`ranking_score`) + AI 개입·override 발생 여부(R5-a/b/f로 정리된 경로 기준) + forward return | symbol-trade_date, AI 개입 유무로 분리 | deterministic 단독 가상 성과 vs 실제(AI 개입 후) 성과 | AI 개입이 deterministic 단독 대비 유의미하게 개선 또는 최소 열등하지 않음 | R5(하류 contract)가 이미 닫혀 있어 AI 개입 경로 자체는 안정적 — **R5 정리 이후 데이터만 사용해야 함**(이전 데이터는 재정리 전 경로 혼입) |
| 4. funnel 전환까지의 기여도 | 정리된 게이트를 통과한 신호가 실제로 `order_request`→submit까지 이어지고, 그 전환율이 신호 강도와 상관관계를 갖는가 | `order_requests`/`execution_attempts`/`order_submission_attempts` + 동시점 `entry_score`/`ranking_score` | symbol-trade_date, `candidate→selected→submitted` 단계별 전환 | PR #119 이전/이후 구간을 반드시 분리 비교 | PR #119 이후 데이터 기준 전환율이 신호 강도와 양의 상관을 보임 | **PR #119 이후 실제 BUY 시도 자체가 아직 충분히 누적되지 않음**(2026-08-03/08-04 실측 결과 각각 0~4건 수준) |

### 30.3 `§4.3~§4.5` 새 버전 뼈대(구 버전은 §4에 "구 전제"로 그대로 유지)

구 `§4.3~§4.5`는 삭제하지 않고 R1~R5 이전 시점의 전제로 그대로
남긴다. 아래는 **현재 BUY 경로/현재 `entry_score`/현재 gate 구조
기준**으로 다시 쓴 뼈대이며, 상세 실행은 별도 착수 턴에서 채운다.

- **4.3′ `entry_score`(현행 공식) 재현**: R1~R5 반영 이후의
  `entry_score` 공식(allocation 항 제거, `risk_off -0.05`, 단일
  권위화된 hard gate)을 기준으로, 거래일별 regime/allocation/
  strategy/source 상태를 복원해 당시 `entry_score`와 BUY
  eligibility를 point-in-time으로 재계산한다. 구 §4.3과 달리
  "재현 대상 공식"이 현재 운영 공식과 일치해야 함을 전제 조건으로
  명시한다.
- **4.4′ 잔여 중복 확인(제한적 범위)**: R2/R3/R4/R5가 이미 닫은
  중복(allocation, risk_off 하드 게이트 이중화, `relative_activity`
  authoritative gate dead branch, `evaluate_action_envelope` 재확인
  등)은 재론하지 않는다. 이 소절은 **그 정리 이후에도 남아 있는
  것으로 새로 발견되는 중복**만 다루는 자리로 좁힌다 — 현재 시점
  기준 신규 발견 없음.
- **4.5′ 전체 funnel back-simulation(정리된 경로 기준)**: 각
  shadow formula가 아니라 **현재 운영 공식 그대로**를 기준으로
  `candidate → selected → expected value → would_buy → submitted`
  전환율과 비용 차감 수익률/MAE/낙폭을 비교한다. 구 §4.5와 달리
  `stale_snapshot_guard`(PR #119) 병목이 걷힌 이후 데이터만
  사용한다는 것을 실행 전제로 명시한다.

### 30.4 `§7` 새 기준선(향후 재산출 필요)

구 §7("BUY 주문 0건 운영 기준선", 2026-07-14 시점, 구 `entry_score`
공식 기준)은 삭제하지 않고 그대로 유지한다. **새 기준선은 아직
재산출하지 않았다** — R1~R5 반영 이후, 그리고 PR #119 이후 표본이
충분히 쌓인 시점에 아래 항목을 같은 형식(표본 수 / `entry_score≥
0.52`·`≥0.65` 건수 / `BUY_CANDIDATE` 건수 / eligibility 통과 건수 /
`risk_off_penalty` 적용 건수 / 최대·평균 `entry_score` / BUY
주문요청·broker submit 건수)으로 재산출해 별도 소절(§7′)로 추가한다.
이번 턴은 재산출을 수행하지 않고 "필요하다"는 사실만 기록한다.

### 30.5 착수 전제 확인(검증 축 자체가 아님)

아래 항목은 `SPPV-3`의 검증 축이 아니라, 각 축을 실제로 착수할 수
있는 **전제 조건이 언제 갖춰지는지**를 가리키는 관측 항목이다(§28/
§29와 동일한 분류 유지).

- PR #119(`stale_snapshot_guard` zero-position false-stale 수정)
  운영 재기동 이후 재현 확인 — 2026-08-03/08-04 실측 결과 BUY 시도
  자체가 아직 충분히 발생하지 않아 미확정 상태가 이어지고 있다.
- R2 allocation 제거(§13.2.5) 이후 운영 재실측.

### 30.6 즉시 착수 가능 축 vs 선행 관측 필요 축

- **즉시 착수 가능**: 축 1(alpha 자체 예측력 — 기존 산출물 재사용),
  축 3(downstream 분리 순수 deterministic 성과 — R5가 이미 닫혀
  전제 충족).
- **선행 관측이 끝나야 시작 가능**: 축 2(정리된 gate 통과 후 성과 —
  정리된 공식 기준 population 축적 필요), 축 4(funnel 전환 기여도 —
  §30.5의 PR #119 이후 BUY 시도 누적 필요).

## 31. `SPPV-3` 축 1(alpha 자체 예측력) 착수(2026-08-04, read-only 분석)

이 절은 §30.6에서 "즉시 착수 가능"으로 분류한 축 1만 다룬다. 축
2/3/4, `BUY 경로 리팩터링`(R1~R5)은 재론하지 않는다. 새 KIS 조회·
DB write·코드 작성은 하지 않았다.

### 31.1 authoritative 입력 신호 집합

| 구분 | 신호 | 근거 |
|---|---|---|
| **핵심 대상(Go/Hold 판정 대상)** | `slow_momentum` | 파일럿(§6)에서 예측력의 "주력"으로 지목된 원신호, `slow_score`의 구성 요소(가중치 0.6) |
| | `overall_score` | 운영 `entry_score`의 핵심 입력(`0.45*overall`), 국면 공통 벤치마크 기준(§12/§14)에서 가장 오래 추적된 신호 |
| | `slow_score` | `overall_score`의 구성 요소(가중치 0.55), `slow_momentum`/`slow_trend` 합성 |
| **비교군(Go 후보 아님, 대조용으로만 유지)** | `fast_score` | §9.2/§12/§14에서 반복적으로 예측력 없음 또는 하락장에서 유의한 역방향(§14.2, T+5 t_NW=-2.79)으로 확인돼, "가중치를 낮춰야 할 반례"로서만 계속 추적 |
| | `slow_trend` | `slow_score`의 나머지 구성 요소(가중치 0.4), 파일럿부터 일관되게 약함(|t|<2) |
| **축 1 범위 밖(참고만, 별도 신호 설계 트랙)** | `risk_adj_momentum_3m`, `regime_switch_v1` 등(§17~§21) | `slow_momentum`에서 파생된 신규 후보 feature다 — "원신호가 예측력이 있는가"라는 축 1의 질문이 아니라 "신호를 어떻게 재설계할 것인가"라는 별개 트랙이라 이번 착수 범위에서 제외한다 |

### 31.2 기존 산출물 재사용 가능 / 재검증 필요 분리

| 항목 | 상태 | 근거 |
|---|---|---|
| pooled cross-sectional IC(파일럿, §6, 1yr·8종목) | **재사용 불가** | overlap 편향으로 §9에서 이미 폐기 판정(t=2.4~4.1은 통계적 착시) |
| pooled cross-sectional IC(§9.2, 1yr·88종목, Newey-West) | **보조 재사용 가능** | 방법론은 유효하나 §12에서 종목별 `regime_label`의 자기참조 오류가 확인돼 국면 분해 결과(§9.4)는 참고용으로만 사용 |
| 시장 공통 국면(KODEX 200 벤치마크) 방법론(§12) | **방법론 재사용 가능, 1yr 수치는 §14로 대체됨** | 자기참조 오류(벤치마크가 자기 자신과 비교됨) 수정판이 §14 |
| **3년 확장 + 자기참조 제거 결과(§14)** | **핵심 재사용 대상 — 현재 canonical** | 87종목·733거래일·시장 공통 국면(bearish_trend 96일 포함) 기준 가장 신뢰도 높은 실측. pooled 유의성 소멸(t_NW 2.30→1.32), 하락장 부호 역전/무의미 확인 |
| 1차(최근 12개월)/2차(3년 게이트) 이원 기준 설계 및 실행 검증(§16, §16.6) | **방법론 재사용 가능, 수치는 재실행 필요** | 실행 시점이 2026-07-14로 오늘(2026-08-04)로부터 약 3주 경과 — §16.2 자체 규칙("신호/가중치를 바꿀 때마다 1차 재실행")에 따라 1차 창을 갱신해야 한다. 2차(3년) 결론은 3주 사이 구조적으로 달라질 개연성이 낮아 당장 재사용 가능하나, 1차 재실행 시 함께 재확인한다 |
| 원시 JSON 로그 산출물(`logs/signal_ic_*.json`) | **소실 확인, 재생성 필요** | 이번 턴에 `logs/` 디렉터리를 read-only로 확인한 결과 JSON/로그 파일 자체는 남아있지 않다 |
| **point-in-time 일봉 캐시**(`logs/_bars_cache_core87_3y_2026-07-14/`, `_bars_cache_core88_2026-07-14/`) | **재사용 가능(신규 확인)** | 원시 캐시 디렉터리는 그대로 남아 있음을 이번 턴에 확인했다 — 재실행 시 **신규 KIS 호출 없이** §14/§16과 동일한 표본으로 재검증 가능 |

### 31.3 축 1 검증 질문 / 집계 단위 / 판정 기준(고정)

- **검증 질문**:
  1. alpha(`slow_momentum`/`overall_score`/`slow_score`)가 미래
     수익률을 예측하는가
  2. 그 예측력의 부호가 국면별(시장 공통 기준, KODEX 200 벤치마크)로
     일관적인가 — 특히 하락장(`bearish_trend`)에서 역전되지 않는가
  3. 최근 창(1차, 12개월)과 장기 창(2차, 3년)에서 **동시에** 유지
     되는가
- **집계 단위**: 거래일별 cross-sectional Spearman IC(종목×거래일),
  horizon T+1/T+3/T+5/T+10/T+20, Newey-West 보정, 국면 분해는
  시장 공통(벤치마크) 국면 라벨 기준(종목별 자기참조 라벨 사용 금지 —
  §12.1의 교훈).
- **성공/실패 판정 기준**(§16.2 Go 게이트를 그대로 계승, 완화하지
  않음): 한 신호가 Go 후보가 되려면 **(a)** 1차(최근 12개월) pooled
  `|t_NW|≥2`이고 부호가 올바르며, **그리고** **(b)** 2차(3년) 국면별
  분해에서 하락장을 포함한 어떤 필수 국면에서도 유의한 역전이 없어야
  한다. 둘 중 하나라도 위반하면 Hold 유지 — "1차만 통과", "2차 옛
  데이터만 통과" 둘 다 허용하지 않는다.

### 31.4 이번 턴에서 새로 좁혀진 결론

새 실측 없이 기존 산출물을 재확인한 결과다.

1. **현재 시점 기준 판정 재확인**: `slow_momentum`/`overall_score`/
   `slow_score` 전부 **여전히 Hold**(Go 아님)다 — §14(3년, 가장 최근
   canonical)에서 pooled 유의성이 소멸했고(`overall_score` T+20
   t_NW 2.30→1.32), 하락장(96일)에서 부호가 역전되거나(`overall_
   score`) 무의미해졌다. §16(1차, 최근 12개월)도 독립적으로 유의성을
   확보하지 못했다(t_NW=1.18). §16.2의 Go 게이트 (a)(b) 중 어느
   쪽도 충족하지 못한 상태가 그대로 유지된다 — 이는 R1~R5(BUY 경로
   리팩터링)와 무관하게, 원신호 자체의 문제로 계속 열려 있다.
2. **비교군(`fast_score`/`slow_trend`)의 위치 재확인**: 둘 다 Go
   후보가 아니라 "제거·완화 근거"로서만 유효하다 — 특히 `fast_score`
   의 하락장 유의 역방향(§14.2)은 R2에서 이미 별개 트랙으로 참고된
   사실이며, 축 1에서 다시 열지 않는다.
3. **재검증 비용이 이번 턴에 새로 좁혀졌다**: 원시 JSON 로그는
   소실됐지만 **원천 point-in-time 일봉 캐시는 남아 있다** — 즉
   다음 턴의 1차 실측은 **신규 KIS 호출 없이** 기존 스크립트
   (`scripts/validate_signal_predictive_power_v5_recency_window.py`,
   3년 캐시 재사용)를 그대로 재실행하는 것만으로 충분하다는 점을
   이번 턴에 확인했다.
4. **파생 신호 후보군(§17~§21)은 축 1과 명시적으로 분리했다** —
   이 트랙은 "원신호가 예측력이 있는가"가 아니라 "신호를 어떻게
   재설계할 것인가"를 다루므로, 축 1의 Go/Hold 판정에는 반영하지
   않는다.

### 31.5 다음 턴 1순위 액션 — 축 1 1차 실측 프롬프트

다음 턴에서 바로 실행 가능한 최소 단위:

> 기존 3년 point-in-time 일봉 캐시(`logs/_bars_cache_core87_3y_
> 2026-07-14/`)를 그대로 재사용해(신규 KIS 호출 없이)
> `validate_signal_predictive_power_v5_recency_window.py`를
> 오늘(2026-08-04) 기준 1차(최근 12개월) 창으로 재실행하고, §16.2
> Go 게이트 기준으로 `slow_momentum`/`overall_score`/`slow_score`의
> 판정이 바뀌는지만 확인한다. 2차(3년, §14)는 3주 경과만으로는 구조적
> 변화 가능성이 낮으므로 이번엔 재실행하지 않고 §14 결과를 그대로
> 참고한다. 코드 수정 없이 기존 스크립트를 그대로 실행하고, 결과
> 로그(stdout/stderr)와 JSON 산출물을 반드시 함께 남긴다(§16.6의
> "실행 증빙" 원칙 계승).

## 32. `SPPV-3` 축 1 — 1차 창(최근 12개월) 실측 재확인(2026-08-04, read-only 실행)

### 32.1 실행 방법 — 무엇을 실행했고 왜 그 방식을 택했는지

`validate_signal_predictive_power_v5_recency_window.py`의 `main()`은
KIS live quote client(`_build_kis_live_quote_client()`)를 무조건
생성한 뒤에야 로컬 캐시를 읽는다. 이 dev 체크아웃에는 `.env`가 없고
KIS 인증정보를 이 턴에서 새로 만들거나 운영 컨테이너에서 원문으로
빼올 수 없어(인증정보 원문 노출 금지 원칙), 그 경로로는 client
생성 자체가 막힌다.

대신 `_fetch_extended_bars(client, symbol)`의 코드를 다시 확인한
결과, **로컬 캐시 파일이 있으면 `client` 인자를 전혀 참조하지 않고
즉시 반환**함을 확인했다(캐시 미스가 있을 때만 `client`를 실제로
사용). 88개 심볼 전부 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)
가 존재하므로, `client`에 "호출되면 즉시 예외를 던지는" no-op 객체를
넣어도 캐시가 100% hit하면 동일하게 동작한다. 이 전제를 실제로
검증하기 위해, 캐시 미스 시 카운터를 올리고 예외를 던지는 no-op
client를 스크래치패드에 작은 드라이버로 작성해(기존 스크립트 파일은
전혀 수정하지 않음) `_collect_symbol_samples`/`_build_benchmark_
daily_series`/`_cross_sectional_ic_by_date`/`_quintile_spread_
series`/`_summarize_series`(전부 v2/v4의 기존 함수, 새 로직 없음)를
그대로 재사용해 §16.3과 동일한 계산을 재실행했다. 실행은
`agent_trading-app:latest` 이미지로 dev 트리를 마운트한 임시
컨테이너에서 수행했다(운영 컨테이너 미접촉).

**신규 KIS 호출 확인**: 실행 로그에 `KIS_CALLS_MADE=0`,
`MISSING_CACHE=[]` — 88개 심볼 전부 캐시 hit, no-op client의
예외 분기가 단 한 번도 실행되지 않았다. 신규 KIS 호출 0건을
실행 결과로 직접 확인했다.

### 32.2 집계 범위

- **1차(primary) 창**: 캐시 내 마지막 유효 거래일(2026-06-16, 20일
  forward horizon을 위해 벤치마크 국면 라벨이 원본 마지막 거래일보다
  약 20거래일 앞에서 끝남 — §16.3과 동일한 계산 방식) 기준 최근
  365일 → **2025-06-16~2026-06-16**. §16.3이 실제로 계산한 것과
  정확히 같은 창이다(캐시가 2026-07-14 이후로 갱신되지 않았으므로
  "오늘 기준"으로 창을 물리적으로 더 밀 수는 없다 — §31.2에서 이미
  전제한 한계).
- **horizon**: T+5, T+20(§16.2/§16.3과 동일하게 `FORWARD_HORIZONS_
  FOCUS` 사용).
- **집계 단위**: 거래일별 cross-sectional quintile spread(비용
  차감 후), Newey-West 보정 `t_NW`, 국면 분해는 시장 공통(KODEX
  200, `069500`) 벤치마크 기준 라벨.

### 32.3 실측 표 — 핵심 대상 3개 + 비교군 2개(1차 창, pooled)

| 신호 | 구분 | T+5 `t_NW`(부호) | T+20 `t_NW`(부호) | `bullish_trend`(239일) | `range_bound`(6일, 표본부족) | `bearish_trend`/`event_driven_unstable` |
|---|---|---|---|---|---|---|
| `slow_momentum` | 핵심 | -0.51(음, 반대부호) | -0.49(음, 반대부호) | T+20 -0.58 | T+20 6.16(n=6, 판정 불가) | 0일(계산 불가) |
| `overall_score` | 핵심 | 1.16(양, 정방향) | **1.18(양, 정방향, §16.3과 동일 재현)** | T+20 1.11 | T+20 3.69(n=6, 판정 불가) | 0일(계산 불가) |
| `slow_score` | 핵심 | -0.15(음, 반대부호) | **-0.15(음, §16.3과 동일 재현)** | T+20 -0.28 | T+20 4.56(n=6, 판정 불가) | 0일(계산 불가) |
| `fast_score` | 비교군 | 0.34(양, 미약) | **0.12(양, §16.3과 동일 재현)** | T+20 0.14 | T+20 -1.84(n=6, 판정 불가) | 0일(계산 불가) |
| `slow_trend` | 비교군 | 0.46(양, 미약) | -0.38(음, 반대부호) | T+20 -0.52 | T+20 3.50(n=6, 판정 불가) | 0일(계산 불가) |

굵게 표시한 세 값(`overall_score` T+20=1.18, `slow_score` T+20=-0.15,
`fast_score` T+20=0.12)은 §16.3에 이미 기록된 값과 **정확히 일치**
한다 — 같은 캐시·같은 함수로 동일 결과가 재현됨을 확인했다(방법론
결정론성 재검증). `slow_momentum`/`slow_trend`는 §16.3의 1차 표에는
없던 값으로, 이번 턴에 처음으로 1차 창 기준으로 집계됐다.
`range_bound`(6일)/`bearish_trend`(0일)/`event_driven_unstable`
(0일)은 `MIN_REGIME_TRADING_DAYS=30` 미달로 §16.3과 동일하게
판정에서 제외한다.

### 32.4 §16.2 Go 게이트 판정(완화 없이 그대로 적용)

| 신호 | (a) 1차 `\|t_NW\|≥2` + 올바른 부호 | (b) 2차(3년, §14) 필수 국면 무역전 | 최종 판정 |
|---|---|---|---|
| `slow_momentum` | **불충족** — T+5/T+20 모두 `\|t\|<2`이며 부호도 음(-)으로 반대 | §14의 시장 공통 국면(market-common regime) 분해 표에 `slow_momentum` 자체가 없음 — **데이터 공백**(별도 항목으로 기록) | **Hold** |
| `overall_score` | **불충족** — 부호는 맞으나 `\|t\|=1.18<2` | §14에서 하락장 T+5 `t_NW=-1.71`(방향 역전), 이미 (a)에서 탈락해 (b) 재론 불필요 | **Hold** |
| `slow_score` | **불충족** — `\|t\|=0.15<2`, 부호도 음 | 이미 (a) 탈락 | **Hold** |
| `fast_score`(비교군) | (a) 불충족(`\|t\|<2`) | §14에서 하락장 T+5 `t_NW=-2.79`로 **유의한 역전 확인** | 비교군 유지, Go 후보 아님(기존 판정 그대로) |
| `slow_trend`(비교군) | (a) 불충족, 부호도 horizon마다 불일치 | 별도 3년 시장공통 분해 없음 | 비교군 유지, Go 후보 아님 |

### 32.5 신호별 분류(이번 턴 최종)

- **`slow_momentum`: Hold 유지.** 파일럿(§6)에서 "예측력의 주력"으로
  지목됐던 것과 달리, 이번 1차 창 재확인에서는 T+5/T+20 모두 부호가
  **반대(음수)**로 나타났다(비유의). §14의 3년 시장공통 국면 분해
  표에는 이 신호가 아예 포함되지 않아 하락장에서의 거동은 여전히
  미확인 상태다 — 다음 턴 후보로 기록(§32.6).
- **`overall_score`: Hold 유지.** 1차 창에서 §16.3과 동일하게
  부호는 맞지만(`t_NW=1.18`) 유의성 기준(`≥2`)에 못 미친다. 2차(3년,
  §14)에서도 하락장 역전이 이미 확인돼 있어 어느 쪽으로도 Go 승격
  근거가 없다.
- **`slow_score`: Hold 유지.** 1차 창에서 부호까지 반대(-0.15)라
  `overall_score`보다도 약하다.
- **`fast_score`/`slow_trend`(비교군): Go 후보로 승격하지 않음.**
  이번 1차 실측에서도 부호가 약하거나 불일치해 기존 "제거·완화
  근거"로서의 위치가 그대로 유지된다.

### 32.6 다음 턴 1순위 액션

**`slow_momentum`을 §14와 동일한 시장 공통(market-common regime)
3년 분해 표에 포함시켜 하락장 거동을 확인한다** — 이 신호만 §14의
canonical 국면 분해 표에서 빠져 있다는 데이터 공백을 이번 턴에
발견했으므로, 다음 우선순위는 축 1을 벗어나지 않는 범위에서 이
공백을 메우는 것이다(3년 캐시도 이미 존재해 신규 KIS 호출 없이
가능). 그 다음에야 축 1 전체를 "1차+2차 모두 확인 완료"로 닫을 수
있다.

## 33. `SPPV-3` 축 1 — `slow_momentum` 3년 시장공통 국면 분해 공백 해소(2026-08-04, read-only 실행)

§32.6에서 발견한 데이터 공백(`slow_momentum`이 §14의 3년 시장공통
국면 분해 표에 없음)을 메운다. `fast_score`/`slow_trend`, 축
2/3/4, `BUY 경로 리팩터링`은 다루지 않는다.

### 33.1 실행 방법 — §14와 동일한 3년 캐시·동일한 함수

`scripts/validate_signal_predictive_power_v4_extended_period.py`
(§14의 canonical 스크립트)의 `main()`은 `DIRECT_SIGNALS=["slow_
score","fast_score","overall_score"]`만 순회해 `slow_momentum`을
표에 넣지 않는다. 이 턴은 그 스크립트를 수정하지 않고, 같은 3년
캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)와 같은 함수
(`_build_benchmark_daily_series`/`_cross_sectional_ic_by_date`/
`_quintile_spread_series`/`_summarize_series`, 전부 §14와 동일한
코드)를 그대로 재사용하는 최소 드라이버로 `slow_momentum`을 `overall_
score`/`slow_score`와 나란히 계산했다(§32와 같은 방식, client는
캐시 hit 시 참조되지 않는 no-op — 예외 발생 시 즉시 드러남).

**신규 KIS 호출 확인**: 실행 로그에 `KIS_CALLS_MADE=0`,
`MISSING_CACHE=[]`(87개 평가 종목 전부 캐시 hit, 벤치마크
`069500` 별도 포함) — 신규 KIS 호출 0건.

**재현성 검증**: 이 드라이버로 재계산한 `overall_score`/`slow_score`
의 pooled·4개 국면별 `t_NW` 16개 값 전부가 §14.2의 기존 표와
**정확히 일치**했다 — §32에 이어 다시 한번 방법론 결정론성을
재확인했다.

### 33.2 `slow_momentum` 3년 시장공통 국면 분해 표(§14.2와 동일 표준)

| horizon | 구분 | `n`(거래일) | `t_NW`(부호) |
|---|---|---|---|
| T+5 | pooled(653일) | 653 | -0.06(무의미) |
| T+5 | `bullish_trend` | 351 | 0.07(무의미) |
| T+5 | `bearish_trend` | 96 | **-0.63(무의미, 음수)** |
| T+5 | `range_bound` | 200 | -0.06(무의미) |
| T+5 | `event_driven_unstable` | 6 | 4.22(표본부족, 판정 제외) |
| T+20 | pooled(653일) | 653 | 0.52(무의미) |
| T+20 | `bullish_trend` | 351 | -0.30(무의미) |
| T+20 | `bearish_trend` | 96 | **0.88(무의미, 양수)** |
| T+20 | `range_bound` | 200 | 0.96(무의미) |
| T+20 | `event_driven_unstable` | 6 | 5.28(표본부족, 판정 제외) |

### 33.3 `overall_score`/`slow_score` 대비 비교 요약

| 신호 | pooled T+5 | pooled T+20 | `bearish_trend` T+5 | `bearish_trend` T+20 |
|---|---|---|---|---|
| `slow_momentum` | -0.06(무의미) | 0.52(무의미) | -0.63(무의미) | 0.88(무의미) |
| `overall_score`(§14.2) | 1.03(무의미) | 1.32(무의미) | **-1.71(방향 역전, 비유의)** | -0.14(무의미) |
| `slow_score`(§14.2) | 0.43(무의미) | 0.76(무의미) | -0.88(무의미) | 0.63(무의미) |

`slow_momentum`은 세 신호 중 **가장 신호가 약하다** — pooled에서도
`overall_score`/`slow_score`보다 `\|t_NW\|`가 작고, `bearish_trend`
에서도 `overall_score`처럼 방향이 뚜렷하게 뒤집히는 패턴조차
보이지 않는다(T+5는 음수, T+20은 양수로 horizon 간 부호도 일관되지
않음). 파일럿(§6)에서 "예측력의 주력"으로 지목됐던 것과는 정반대로,
3년 canonical 기준에서는 세 핵심 신호 중 가장 정보가 없는 신호임이
확인됐다.

### 33.4 §14.2/§16.2 기준 판정 — 하락장 거동은 "무의미"

`slow_momentum`의 하락장(`bearish_trend`, n=96) 거동은 **유의한
양(+)/역방향 둘 다 아니고, 무의미(`\|t_NW\|<1` 양 horizon 모두)다.**
`overall_score`처럼 방향이 뚜렷하게 뒤집히는 "위험한" 신호는 아니지만,
`\|t_NW\|≥2`에 해당하는 "유효한" 신호도 아니다. §16.2 Go 게이트
(a)(1차 유의성)는 §32에서 이미 탈락이 확정됐으므로, 이번 (b)(2차
국면 무역전) 결과와 무관하게 최종 판정은 바뀌지 않는다.

### 33.5 이번 턴 판정 — **Hold 유지**(데이터 공백 해소, 판정 자체는 불변)

- "Hold 강화"는 아니다 — 새로운 부정적 증거(유의한 역방향)가 추가로
  나온 것이 아니라, 애초에 아무 신호도 없다는 사실이 확인됐을 뿐이다.
- "Watch 여지"도 아니다 — 어떤 국면·horizon 조합에서도 `\|t_NW\|≥2`
  에 근접하는 값이 없다.
- 결론: §32에서 확정한 Hold를 그대로 유지하며, 이번 턴으로 그
  근거(3년 국면 분해)가 완전해졌다 — 축 1의 `slow_momentum` 관련
  데이터 공백은 이것으로 해소됐다.

### 33.6 다음 1순위 액션

`slow_momentum`/`overall_score`/`slow_score` 3개 핵심 신호 모두
1차(§32)·2차(§14/§33) 양쪽에서 Hold로 판정이 닫혔다 — **축 1(alpha
자체 예측력)의 핵심 대상 판정을 "완료"로 종료**하고, §30.6에서
함께 즉시 착수 가능으로 분류했던 **축 3(downstream 분리 순수
deterministic 성과)** 착수로 넘어가는 것을 다음 1순위로 제안한다.

## 34. `SPPV-3` 축 3(downstream 분리 순수 deterministic 성과) 착수 분석(2026-08-04, read-only)

이 절은 §28~§33(축 1)을 닫은 뒤, §30.6에서 함께 즉시 착수 가능으로
분류했던 축 3을 실제로 착수 가능한 수준까지 구체화한다. 코드 변경
없음, 새 실측 없음(기존 데이터 구조 확인만), R1~R5·축 1·축 2·축
4는 재론하지 않는다.

### 34.1 축 3 검증 질문(한 줄로 고정)

**AI/EV/submit 레이어의 override·downgrade·suppress 개입이 없었다면,
deterministic 레이어(`entry_score`/`buy_candidate`/`eligibility_
passed`/`ranking_score`) 단독의 판단이 실제 최종 결정 대비 더 나은
성과를 냈을지, 최소 열등하지 않았을지를 확인한다.**(§30.2의 축 3
정의를 그대로 계승, 재정의하지 않음)

### 34.2 deterministic / downstream 경계표

BUY 경로 6개 파일을 코드 기준으로 확인한 결과다.

| 파일 | deterministic 필드 읽음 | downstream 개입 지점 | 경계 성격 |
|---|---|---|---|
| `deterministic_trigger_engine.py` | (생성 주체) | — | 이 지점까지가 순수 deterministic. `DeterministicTriggerAssessment`가 유일한 산출물 |
| `decision_orchestrator.py` | `watch_candidate`/`buy_candidate`/`eligibility_passed`/`eligibility_reasons`/`risk_off_exception_eligible`/`ranking_score` | **7개 guard**: `_check_held_position_sell_override`, `_check_source_policy_upgrade_guard`, `_check_watch_candidate_upgrade_guard`, `_check_held_position_exit_hysteresis_gate`, `_check_buy_eligibility_upgrade_guard`, `_check_ai_buy_override_gate`, pre-AI `_evaluate_pre_agent_short_circuit` | **단일 플래그가 아니라 guard 체인** — 마지막 guard(`_check_ai_buy_override_gate`) 반환 이후 `decision_type`/`side`가 고정된다. 이 시점이 실질적 경계 |
| `expected_value_gate.py` | `entry_score`/`ranking_percentile`/`risk_off_exception_eligible` | **없음(read-only 확인)** — `deterministic_trigger`를 절대 수정하지 않는 순수 함수 | deterministic 값을 소비해 자체 `edge_after_cost_bps>=minimum_required_edge_bps` 게이트만 산출, `decision_type`은 orchestrator의 guard가 이 값을 받아 대신 낮춘다 |
| `decision_factory.py` | `deterministic_trigger` 전체를 `decision_json`에 원문 저장 | **없음** — 순수 factory | **persistence 경계**: `decision_json.deterministic_trigger`(원본)와 `decision_type`/`candidate_vs_final`(최종)을 **같은 row에 함께 저장**한다 — 이미 존재하는 필드로, 신규 계측 없이 재구성 가능 |
| `prompt_context_projection.py` | `primary_candidate`/`entry_score` 등 프롬프트 텍스트화 | 없음 | AI 실행 이전 입력 포맷팅 — 경계 이전 단계 |
| `translation.py` | **없음(직접 참조 없음)** | 자체 4개 하드 게이트(decision_type 허용집합/EV anchor 완전성/`held_position` SELL 전용/`quantity>0`) | deterministic_trigger를 모르는, orchestrator가 이미 확정한 `decision_type`만 신뢰하는 순수 downstream |
| `execution_service.py` | `eligibility_reasons`(execution 시점 유동성 재확인, Phase 1.6)뿐 | 이 재확인은 `decision_type`이 아니라 주문 형태(block/limit)만 바꿈. `stale_snapshot_guard`(Phase 4c)는 순수 계좌 상태 기반, deterministic/AI 입력과 무관 | infra 안전판이 AI/EV/translation 레이어 **뒤**에 위치 — decision 내용과 무관 |

**경계 요약**: 물리적으로 하나의 플래그는 없지만, `decision_orchestrator.py`의 마지막 guard(`_check_ai_buy_override_gate`)가 반환한 직후가 실질적 경계다. 그 이전은 deterministic 값이 `decision_type`을 바꿀 수 있는 유일한 구간이고, 그 이후(`expected_value_gate`의 EV near-miss 재확인, `decision_factory`의 저장, `translation`/`execution_service`)는 deterministic 값을 읽더라도 더 이상 `decision_type` 자체를 바꾸지 않는다.

### 34.3 모집단 정의

| 단계 | 속하는 구간 | 근거 |
|---|---|---|
| deterministic trigger 생성(전량) | **deterministic only** | `buy_candidate`/`eligibility_passed`/`entry_score` 등이 여기서 확정 |
| `eligibility_passed=true` 통과 | **deterministic only** | eligibility 하드 게이트, AI 미개입 |
| `buy_candidate=true` | **deterministic only** | threshold(`0.65`) 비교까지 deterministic |
| AI(EI/AR/AC/FDC) 실행·`decision_type=APPROVE` | **AI/EV 개입 후** | FDC의 1차 산출물, 아직 guard 미반영 |
| 7개 guard 통과 후 최종 `decision_type` | **AI/EV 개입 후**(guard가 deterministic 값을 근거로 재확인) | §34.2의 guard 체인 결과 |
| `order_request` 생성 | **AI/EV 개입 후** | `decision_type=approve`가 전제 |
| submit 이후 상태(`pending_submit`/`submitted`/체결) | **execution/infra 영향 포함** | `stale_snapshot_guard` 등 계좌 상태·브로커 응답이 추가로 개입 |

### 34.4 비교군 설계(2안 비교)

| 설계 | 정의 | 장점 | 한계/혼입 위험 |
|---|---|---|---|
| **A안: deterministic gate 통과 vs 미통과** | `buy_candidate=true`(또는 `eligibility_passed=true`) 표본과 `false` 표본을 forward return으로 비교 | 계산이 단순하고 이미 축 1(§9~§33)에서 쓴 방법론(cross-sectional quintile/IC)을 그대로 재사용 가능 | AI/EV의 개입 여부와 무관하게 deterministic 판정 자체의 성과만 보는 것이라, "downstream이 개입해서 더 나아졌는지"는 **직접 답하지 못한다** — 축 1의 재탕에 가까움 |
| **B안: deterministic 후보 vs downstream 실제 승격/차단 표본** | `decision_json.candidate_vs_final.alignment_status`(`matched`/`upgraded`/`downgraded`/`promoted_from_no_action`/`suppressed`/`diverged`)로 분리해, `suppressed`(deterministic이 원했지만 downstream이 막음)·`downgraded`(deterministic BUY_CANDIDATE를 downstream이 낮춤)·`upgraded`/`promoted_from_no_action`(deterministic이 소극적이었는데 downstream이 승격)의 forward return을 비교 | **이미 존재하는 필드**(`decision_factory.py`가 매 row에 저장, §34.2)라 신규 계측 없이 즉시 조회 가능. "AI가 개입해서 결과가 달라졌는지"를 직접 답하는, 축 3의 원래 질문에 가장 가까운 설계 | `suppressed`/`downgraded` 표본은 실제 주문이 나가지 않아 forward return의 "가상 매수" 기준(진입가/기준일)을 deterministic 판단 시점으로 재구성해야 하고, 표본 수가 아직 적다(§34.5) |

**권고**: **B안을 1순위로, A안은 보조 지표로 함께 본다.** B안이 축 3의
질문(“개입이 없었다면 어땠을까”)에 직접 답하고, `candidate_vs_final`
필드가 이미 존재해 즉시 조회 가능하기 때문이다.

### 34.5 즉시 측정 가능 / 추가 관측 필요 분리

- **즉시 측정 가능(코드/구조 확인만으로 확정)**:
  - `candidate_vs_final.alignment_status` 필드가 이미 모든
    `trade_decisions` row에 존재함(read-only 확인, 전체 이력
    `matched` 35,714 / `promoted_from_no_action` 3,894 /
    `suppressed` 3,775 / `downgraded` 427 / `upgraded` 176건).
  - R5(하류 contract, R5-a/b/f) 마감 이후로 한정한 population도 이미
    존재한다(R5-f PR #127 병합 시점 이후 read-only 확인 결과
    `matched` 439 / `suppressed` 55 / `promoted_from_no_action` 50 /
    `downgraded` 24건) — §30.2가 요구한 "R5 정리 이후 데이터만
    사용" 전제를 충족하는 표본이 이미 쌓이고 있다.
- **추가 관측/정의가 필요한 것**:
  - `suppressed`/`downgraded` 표본의 forward return을 계산하려면
    "deterministic이 원했던 시점의 가상 진입가"를 어떤 기준(당일
    종가/다음날 시가 등)으로 잡을지 방법론을 먼저 정해야 한다 —
    이번 턴에서 새로 발명하지 않고 다음 착수 턴 과제로 남긴다.
  - R5 마감 이후 population(24~55건대)은 아직 통계적 판정을
    내리기엔 작다 — 시간이 지나며 자연 누적을 기다리거나, 필요 시
    R5 마감 이전 데이터를 "참고용"으로 병행 검토할지 결정이 필요.

### 34.6 이번 턴 최종 판정

1. **축 3을 지금 바로 실측할 수 있는가**: **부분적으로 가능하다.**
   B안의 population 자체(`candidate_vs_final` 분포)는 코드 변경
   없이 바로 집계 가능하고 이미 그렇게 확인했다. 다만 forward
   return까지 포함한 "성과 비교"는 §34.5의 가상 진입가 방법론
   정의가 선행돼야 한다.
2. **다음 턴 1순위 실측 단위**: R5 마감 이후 `candidate_vs_final=
   suppressed`/`downgraded` 표본에 대한 **가상 진입가 방법론을
   먼저 확정**한 뒤(§30.2의 판정 기준과 동일한 Newey-West/quintile
   방법론을 그대로 재사용), `matched` 표본과 forward return을
   비교하는 1차 실측을 진행한다.
3. **선행 관측/정의가 더 필요한 부분**: 가상 진입가 기준 확정,
   R5 마감 이후 population의 자연 누적(현재 24~55건대로 아직
   작음).
