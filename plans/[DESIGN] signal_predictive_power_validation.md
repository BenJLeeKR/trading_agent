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
    regime_conditional_entry_signal_v1.md` §45.
  - 산출물: `scripts/validate_r3b_entry_score_shadow_fidelity.py`
    (read-only, 신규 KIS 호출 0건), `logs/signal_ic_r3b_entry_
    score_shadow_fidelity_2026-07-18.json`, `logs/r3b_entry_score_
    shadow_fidelity_run_2026-07-18.log`.
  - 다음 과제: entry_score risk_off_penalty 완화의 실제 코드 변경
    PR 초안 작성 착수 여부 사용자 확인(shadow 정합성 확보 완료),
    §21 게이트 정기 재모니터링, exit 외 리스크 관리(포지션 사이징)
    검토, 국면 혼합도 모니터링 설계 검토, `portfolio_allocation`
    gap·실제 청산 시점 분포는 실거래 누적 이후 재검증.
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
