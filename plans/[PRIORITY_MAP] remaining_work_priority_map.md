# 남은 작업 우선순위 정리

## 목적

- `plans/[BACKLOG] backlog.md`와 2026-06-01 ~ 2026-06-03 사이의 최근 작업 문서를 함께 기준으로 삼아,
  지금 시점에서 **실제로 남은 작업**을 우선순위별로 재정리한다.
- 추가로 `plan_docs/agents/`의 agent 설계 문서
  - `01_agent_inventory_and_status.md`
  - `02_agent_target_shapes.md`
  - `03_risk_role_boundaries.md`
  도 함께 반영한다.
- 이미 해결된 장애성 이슈와, 아직 구조적으로 남아 있는 과제를 구분한다.
- 사용자가 요청한 방향에 맞춰 **Admin UI 추가 고도화는 후순위**로 내리고, 백엔드/운영 안정화 과제를 앞에 둔다.

## 수정 이력

- 작성자: Codex
- 수정일자: 2026-07-14
- 수정내용: 최고 기대수익률을 손실 제약 아래의 목적함수로 고정하고,
  `2026-06-25` 이후 BUY 0건의 `entry_score` 직접 병목 실측을 반영했다. 신호
  통계 보정 → `entry_score` 재현 → 전체 BUY funnel back-simulation → 제한적
  probe를 새 최우선 순서로 올리고 소싱 트랙은 차후 보류로 정렬했다.

- 작성자: Claude
- 수정일자: 2026-07-14
- 수정내용: SPPV-2 완료 결과(core 88종목, cross-sectional IC 유의성 없음)를
  반영해 SPPV-2를 완료로 갱신하고, SPPV-2.5(quintile spread 진단)를 다음
  작업으로, SPPV-3을 조건부 보류로 재정렬했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (2차)
- 수정내용: SPPV-2.5 완료 결과(quintile spread pooled 유의하나 국면 내부
  미재현 — 국면 혼입 착시 가능성)를 반영해 SPPV-2.5를 완료로 갱신하고,
  SPPV-3 착수 조건을 "표본 확장 후 국면 내부 유의성 재확인 또는 신호
  feature 재설계"로 구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (3차, 사용자 지적 반영)
- 수정내용: SPPV-2.5의 "국면 혼입 착시" 결론을 방법론 오류(`regime_label`이
  종목별 신호였음)로 폐기하고, KODEX 200 시장 벤치마크 기준 재검증
  (SPPV-2.6)으로 대체했다. 결과: 결론이 반박되어 알파 근거가 강화됐으나,
  하락장 표본이 전무한 새 한계가 확인돼 SPPV-3 보류 사유를 교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (4차)
- 수정내용: SPPV-2.6의 "알파 근거 강화" 결론을 다시 하향 조정했다.
  벤치마크 자기참조 제거 + 3년 확장 검증(SPPV-2.7)에서 pooled 유의성이
  소멸하고 하락장에서 신호가 역전/역방향으로 나타났다. SPPV-3 보류 사유를
  "신호 feature 재설계 검토 필요"로 재교체했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (5차, 검증 기간 재설계)
- 수정내용: 이 시스템이 3개월 이하 중단기 공격형이라는 전제 아래 SPPV
  검증의 **기간(period) 기준 자체를 재설계**했다(SPPV-2.8). 3년 pooled를
  기본값으로 두지 않고 최근 12개월을 1차(primary), 3년(SPPV-2.7 재사용)을
  국면 커버리지 2차(supplementary) 게이트로 분리했다. 최근 12개월 실측
  결과 하락장 거래일이 0일이라 1차만으로는 필수 국면 검증이 불가능함을
  실증했고, 1차 pooled 유의성도 확보되지 않았다. §14의 보류 판정은 유지.

- 작성자: Claude
- 수정일자: 2026-07-14 (6차, 실행 증빙 재검증)
- 수정내용: SPPV-2.8의 최초 실행 로그가 실제로는 실패 트레이스(호스트
  `dotenv` 미설치)였던 증빙 결함을 발견하고, 컨테이너에서 재실행해 정상
  로그를 재확보했다. 종료 코드 0/KIS 호출 0건/bearish_trend 0일/
  `overall_score` T+20 t_NW=1.18 전부 재현 — 결론·판정 변경 없음.

- 작성자: Claude
- 수정일자: 2026-07-14 (7차, 신호 feature 재설계 검토 — SPPV-2.9)
- 수정내용: §14.5가 지시한 신호 feature 재설계 검토를 실행했다.
  `fast_score`/`slow_score`의 6개 sub-component 분해 + 신규 후보
  feature(`risk_adj_momentum_3m`, `reversal_1m`) 검증 결과, `rsi_signal`
  이 T+20에서 유의하게 역방향(t_NW=-2.94)임을 특정했고, `risk_adj_
  momentum_3m`이 3년 pooled 유의(t_NW=2.07) + 하락장 역전 없음으로
  유일한 Watch 후보로 확인됐으나 1차 창 유의성 미달로 완전한 Go는
  아니다. SPPV-3 착수는 계속 보류, 다음 과제(`fast_score_v2` 검증 등)를
  구체화했다.

- 작성자: Claude
- 수정일자: 2026-07-14 (8차, §17.5 후속 3과제 — SPPV-2.10)
- 수정내용: §17.5가 지시한 후속 3과제(`fast_score_v2` shadow 2종,
  `risk_adj_momentum_3m` 18개월 창 재검증, `reversal_1m` 하락장 반분
  안정성)를 실행했다. `fast_score_v2` 2종 모두 No-Go(하락장 역전이
  원안과 거의 동일) — `rsi_signal`이 부분 원인일 뿐이었음을 재확인.
  `risk_adj_momentum_3m`은 18개월 창에서 T+20 t_NW=2.03으로 marginal
  통과 — Watch 유지, 조건부 상향. `reversal_1m`은 반분 표본 개별 유의
  미달로 Hold 유지. SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (9차, §18.6 후속 — SPPV-2.11)
- 수정내용: §18.6이 지시한 세 과제(`fast_score` leave-one-out 4종,
  `risk_adj_momentum_3m` 창 경계 민감도 12~21개월, 국면 전환형 shadow
  `regime_switch_v1`)를 실행했다. `fast_trend` 제거 시 하락장 T+5
  spread가 -2.79→-1.60으로 가장 크게 개선 — `rsi_signal`이 아니라
  `fast_trend`가 주된 원인이었음을 정정. `risk_adj_momentum_3m`은
  15~21개월에서 안정적 plateau(우연 아님, marginal). `regime_switch_v1`
  은 2차(3년) pooled 트랙 최고 수치(T+5=2.60/T+20=2.36)를 냈으나 1차는
  하락장 표본 부재로 미달 — 가장 유망한 Watch 후보로 격상. SPPV-3
  착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (10차, §19.6 후속 — SPPV-2.12)
- 수정내용: `regime_switch_v1` 1차 게이트 예외 규칙 3개(A 관찰 유예/B
  최근-실사례 고정창/C 적응형 최소 국면 표본 창)를 비교했다. 규칙 C가
  n=30에서 t_NW=4.18로 급등하지만 n=48(규칙 B)에서는 1.33에 불과 —
  데이터 스누핑으로 판정, 채택 거부. 규칙 B는 정직한 재검증에서도
  미달 — 규칙 A(관찰 유예)를 유일하게 채택. fast 계열 신규 feature 2종
  (`rsi_mean_reversion`, `sma5_over_sma20_gap`)도 범용 대체 후보로
  No-Go(각각 하락장 전용/하락장 역전). SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-14 (11차, §20.5 후속 — SPPV-2.13/2.14)
- 수정내용: `regime_switch_v1` 규칙 A(관찰 유예)를 실행 가능한 모니터링
  스크립트로 구현(벤치마크 1종목만 조회) — 실행 결과 현재
  NOT_TRIGGERED(bearish_trend 0일). "절대 가격 수준" 미의존 신규 fast
  계열 2종(`money_flow_5d`, `relative_strength_rank_1m`)을 실측 — 둘 다
  범용 대체 후보로 No-Go. `relative_strength_rank_1m`은 하락장에서
  유의하게 역전(t=-2.13) — 시장 베타 제거 상대강도조차 하락장에서
  반대로 작동한다는 규칙성 재확인. SPPV-3 착수는 계속 보류.

- 작성자: Claude
- 수정일자: 2026-07-15 (12차, 국면별 신호 극성 종합 및 상위 방향 확정)
- 수정내용: SPPV-2.9~2.14의 10개 신호를 종합표로 통합(별도 문서
  `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`)
  — 8/10이 "추세형=상승/횡보 전용, 되돌림형=하락장 전용" 규칙성을
  따름(`rsi_signal`만 상승장 역전 예외). 5개 축 모두 시도 후 동일 결론
  수렴을 근거로 feature 추가 실험을 중단하고 **국면 분기형 entry 설계
  검토로 전환**을 확정. 유니버스/미시구조 재검토는 후순위 유지.

- 작성자: Claude
- 수정일자: 2026-07-15 (13차, 국면 분기형 entry 설계 초안 + shadow 계산기)
- 수정내용: 12차 판정을 실제 설계 문서(`plans/[DESIGN] regime_
  conditional_entry_signal_v1.md`)로 구체화했다 — 국면별 신호 선택
  매트릭스, `entry_score` alpha layer 교체 제안(미적용), shadow 검증
  Phase 1/2 계획. shadow 계산기 실행(2026-07-14 기준, 시장 공통 국면
  `range_bound`) — 87/87종목 `risk_adj_momentum_3m` 분기 사용, 하락장
  분기는 미발동(§21 모니터링과 정합). `entry_score` 코드/운영 변경 없음.

- 작성자: Claude
- 수정일자: 2026-07-15 (14차, regime_conditional_signal Phase 2
  shadow 누적 사이클 구축)
- 수정내용: Phase 2를 실제 실행 가능한 오케스트레이터(`scripts/run_
  regime_conditional_shadow_cycle.py`)로 구현했다 — 게이트 판정(§21)과
  신호 계산(§22)을 벤치마크 1회 조회로 통합, 누적 이력 파일(JSONL,
  중복 거래일 자동 skip) 구축, `TRIGGERED` 전환 시 재검증 runbook
  출력. 실행 결과: 게이트 NOT_TRIGGERED, 신호 2026-07-14 기준
  `range_bound`로 87/87종목 `risk_adj_momentum_3m` 분기 — 이력에 1줄
  추가, 재실행 중복 방지 확인. `entry_score` 코드/운영 변경 없음.

- 작성자: Claude
- 수정일자: 2026-07-15 (15차, entry_score 중복 penalty ablation 실측)
- 수정내용: SPPV-3 착수 전제를 실측으로 구체화 — 운영 함수를 그대로
  호출해 세 penalty 축(entry_score regime penalty/eligibility regime
  차단/eligibility signal floor)을 오늘(87종목) 기준 독립 평가. B(60건)
  발동 종목은 예외 없이 A·C도 함께 발동(A∩B∩C=60=B 전체) — "삼중
  중복"이 오늘 데이터로 100% 재현됨. 종목별 regime_label(bearish_trend
  69%)이 시장 공통 국면(range_bound)과 전혀 다름을 재확인. entry_score
  통합 시 국면 정의 통일이 새로운 전제로 필요함을 발견.

- 작성자: Claude
- 수정일자: 2026-07-15 (16차, 중복 억제 시계열 누적 + 국면 정의 비교
  체계 구축)
- 수정내용: 하루치 관찰을 시계열 누적 절차로 승격 — 신규 오케스트레이터
  가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행에서 계산해 누적
  이력에 기록. 실행 결과: 이전 실측과 동일한 수치(A=85/B=60/C=75/
  A∩B∩C=60)로 교차 검증, 국면 일치 18건/불일치 69건(79%) — "시장
  비하락장인데 종목별 하락장" 60건. SPPV-3 본작업용 비교 실험(현행
  종목별 정의 vs 시장 공통 정렬) 설계 완료.

- 작성자: Claude
- 수정일자: 2026-07-15 (17차, §9.6 비교 실험 실측)
- 수정내용: 종목별 vs 시장 공통 regime 정의 비교 실험을 실행 — 변형
  B(시장 공통)가 통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의
  forward return은 더 높음(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%,
  둘 다 유의). A-B 차이 직접 유의성 미검정, 통과군 내부 quintile
  spread 여전히 역전 — 판정 Watch(조건부 유리). 실행 로그로 KIS 호출
  0건 확인.

- 작성자: Claude
- 수정일자: 2026-07-15 (18차, A/B 판정 불일치 표본 direct 비교 + 1차
  창 재확인)
- 수정내용: 같은 종목-거래일 표본을 A_only/B_only/both/neither 4개
  집합으로 분해 — B_only가 3년·1차 창 모두 0건임을 확인, 시장 공통
  정의는 종목별 정의의 진부분집합일 뿐임을 구조적으로 확인. A_only의
  forward return은 방향상 음수이나 유의하지 않음. 최근 12개월은 A-B
  차이 자체가 없음. 판정 Watch 유지(No-Go에 근접), 확정 전환 기각.

- 작성자: Claude
- 수정일자: 2026-07-15 (19차, alpha layer vs regime_conditional_signal
  직접 비교)
- 수정내용: 무게중심을 국면 정의 통일(차단)에서 alpha layer 교체
  (선별)로 이동 — 현행 alpha layer와 regime_conditional_signal을
  같은 3년 표본에서 직접 비교. 2차(3년) 창에서 regime_conditional_
  signal이 T+5/T+20 둘 다 유의(t_NW 2.52/2.33), 현행 alpha layer는
  어디서도 비유의(1.02~1.39) — 4개 관측치 전부 일관되게 우세. 1차
  창은 미달이나 §21 구조적 이유(하락장 부재) 때문. 판정 Conditional
  Go(2차 검증 통과, 1차 게이트 전환 대기).

## 최근 메모

> **📌 2026-07-14 BUY 주문경로 근본 복구 기준 확정 (최신, 최우선 반영)**:
> 목표는 손실 0이 아니라 **허용 손실 제약 아래 비용 차감 기대수익 최대화**다.
> `2026-06-25` 이후 `symbol + trade_date` 첫 decision 297건을 재검증한 결과
> `entry_score >= 0.65=0`, `BUY_CANDIDATE=0`, eligibility 통과 21건,
> `risk_off_penalty=294`, 최대/평균 entry score `0.6086/0.1699`, BUY
> 주문요청/submit 0건이었다. 따라서 이 기간 BUY 0건의 직접 병목은 하류
> compliance/broker가 아니라 `entry_score < 0.65`다.
>
> 새 최우선 순서는 ① 신호 IC 통계 보정 확장 ② `entry_score` point-in-time
> 재현과 중복 penalty ablation ③ 전체 BUY funnel counterfactual ④ 비용 차감
> 기대수익·MFE/MAE·손실 제약 검증 ⑤ 별도 승인된 제한적 paper probe다.
> threshold 일괄 완화와 risk/compliance/guardrail 제거는 금지한다. 상세는
> [`plans/[DESIGN] signal_predictive_power_validation.md`](./%5BDESIGN%5D%20signal_predictive_power_validation.md)
> 참고.
>
> **📌 2026-07-14 SPPV-2 완료 — 결과 갱신 (최신)**: core 88종목 전체로
> 확장해 거래일별 cross-sectional IC + Newey-West 보정 + 국면별 분해를
> 수행한 결과, **①의 "신호 IC 통계 보정 확장"이 완료됐고 결과는 부정적이다**
> — SPPV-1 파일럿의 t=2.4~4.1("유의미"~"강함")은 overlap 편향의 산물이었고,
> 정확히 보정하면 전 신호·전 horizon에서 |t_NW|<1.1로 통계적 유의성이
> 없다. 다만 `overall_score` 비용 차감 quintile spread(T+20 기준 +3.88%p)는
> 방향성 있게 남아 있어 "완전 무신호"로 단정하지 않는다. **②(entry_score
> 재현)로 바로 넘어가지 않는다** — 그 spread가 시장 베타 착시인지 잔여
> 알파인지 먼저 가리는 진단(SPPV-2.5, 초과수익 기반 재검증)이 선행돼야
> 한다. 상세: `plans/[DESIGN] signal_predictive_power_validation.md` §9.
>
> **📌 2026-07-14 SPPV-2.5 완료 — 정체 판정 (이력, 아래 SPPV-2.6으로 정정)**:
> `overall_score` quintile spread 자체를 Newey-West로 재검정(pooled T+20
> t=2.30, 유의)한 뒤 국면 내부(bullish/bearish/range_bound)로 다시 나눠
> 재확인했다. ~~어느 국면 내부에서도 유의성이 재현되지 않는다(최고
> bullish_trend t=1.55) — pooled 유의성이 국면 혼입(regime-mix) 착시일
> 가능성이 높다는 뜻이다.~~ **→ 오류였음, 아래 SPPV-2.6 참고.**
>
> **📌 2026-07-14 SPPV-2.6 완료 — 시장 공통 국면 기준 정정 (최신)**:
> 사용자 지적으로 위 SPPV-2.5의 `regime_label`이 시장이 아니라 **종목
> 자신의 신호**(`market_regime.py:21-38`)로 판정되는 라벨이었음이 코드로
> 확인됐다 — 검정 대상(`overall_score`)과 같은 계열 변수로 표본을
> 조건화한 선택 편향. **KODEX 200(069500, 이미 core universe 구성원)을
> 시장 벤치마크로 써서 거래일 단위 공통 국면 + 초과수익으로 재검증**한
> 결과: (1) 시장 공통 국면은 190거래일 중 185일(97%)이 bullish_trend,
> bearish_trend는 0일 — 이 1년 표본은 시장 기준으로는 사실상 단일
> (상승) 국면이었다. (2) 그런데 `overall_score` T+20 spread의 유의성
> (pooled t_NW=2.30)은 이 유일한 신뢰 가능 버킷 내부에서도 거의 그대로
> ~~유지된다(t_NW=2.23) — "국면 혼입 착시" 결론은 반박되고, 알파 근거는
> 오히려 강화됐다.~~ **→ 아래 SPPV-2.7에서 다시 반박됨(자기참조 문제
> 잔존 + 1년 표본 한계).** 하락장 표본이 전무해 근본 진단 Q3(단일국면
> 편향)가 여전히 미해결이라는 한계가 있었다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §12(이력).
>
> **📌 2026-07-14 SPPV-2.7 완료 — 하락장 포함 3년 확장 재검증 (최신)**:
> SPPV-2.6이 벤치마크(069500)를 평가 universe에도 포함시킨 자기참조
> 문제를 제거(core 87종목)하고, 조회 기간을 1년→**3년**(733일봉)으로
> 확장해 실제 시장 공통 하락장 표본(96거래일, 15%)을 처음으로 확보했다.
> **결과: `overall_score` pooled spread 유의성이 소멸했다(t_NW 2.30→
> 1.32). 하락장 내부에서는 spread가 음수로 역전(T+5 t_NW=-1.71)하거나,
> `fast_score`는 하락장에서 통계적으로 유의하게 역방향(T+5 t_NW=-2.79)
> 이었다.** **SPPV-2.6의 "알파 근거 강화" 결론은 과도했다 — 하향
> 조정한다.** 안정적인 종목 선택 알파를 확인하지 못했으며, `entry_score`
> 재현(SPPV-3)보다 **신호 feature 재설계 검토**로 무게 중심이 이동한다.
> 이 판단은 사용자 확인이 필요하다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §14(최신
> canonical 결론).
>
> **📌 2026-07-14 SPPV-2.8 완료 — 검증 기간(period) 기준 재설계 (최신)**:
> 이 시스템은 장기 보유형이 아니라 3개월 이하 중단기 공격형이므로, 검증의
> 핵심은 짧은 horizon(T+5/T+20) 신호가 **최근 시장**과 **필수 국면**
> 모두에서 유효한지다. 3년 전체 pooled를 기본값으로 유지하지 않고 **최근
> 12개월을 1차(primary) 기본 창, 3년(SPPV-2.7 재사용)을 국면 커버리지
> 확인용 2차(supplementary) 게이트**로 분리했다. 기존 3년 캐시를
> 재사용해(신규 KIS 호출 0건) 최근 12개월(2025-06-16~2026-07-14, 245
> 거래일)을 실측한 결과 **하락장(bearish_trend) 거래일이 0일** —
> "최근성 창"만으로는 필수 국면 게이트를 절대 통과할 수 없음을 실증했다.
> 1차 pooled 유의성도 Newey-West 보정 시 확보되지 않았다(`overall_score`
> T+20 t_NW=1.18, 3년 결과 1.32보다도 낮음). §14의 보류(Hold) 판정은
> 변경하지 않으며, 이번 작업은 **앞으로의 재검증이 따를 기간 기준을
> 확정**한 것이다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §16.
>
> **📌 2026-07-14 SPPV-2.8 실행 증빙 재검증 (최신)**: 최초 저장된 실행
> 로그가 실제로는 호스트 python 환경의 `dotenv` 미설치로 즉시 실패한
> 트레이스였음을 발견했다 — JSON 산출물은 컨테이너에서 만든 진짜
> 결과였으나 정상 로그가 없었다("실행됐다"고 쓰려면 로그+산출물이
> 모두 있어야 한다는 원칙 위반). `agent_trading-app-1` 컨테이너에서
> 재실행해 stdout을 로그로 캡처, 재검증한 결과 **종료 코드 0, `HTTP
> Request:` 0건(신규 KIS 호출 없음), bearish_trend 0일, `overall_score`
> T+20 t_NW=1.18 전부 동일 재현**됐다. 위 SPPV-2.8 결론·판정은 변경 없이
> 증빙만 보강했다. 상세: `plans/[DESIGN] signal_predictive_power_
> validation.md` §16.6.
>
> **📌 2026-07-14 SPPV-2.9 완료 — 신호 feature 재설계 검토 (최신)**:
> §14.5가 지시한 신호 feature 재설계 검토를 실제로 수행했다. `fast_
> score`/`slow_score`를 구성하는 6개 sub-component(`slow_momentum`/
> `slow_trend`/`fast_trend`/`volume_confirmation`/`rsi_signal`/
> `volatility_penalty`)를 운영 코드 그대로 분해 실측하고, 신규 후보
> feature 2개(`risk_adj_momentum_3m`=변동성 조정 모멘텀, `reversal_1m`=
> 단기 역추세)를 §16 이원 기준(1차 최근 12개월/2차 3년 국면 게이트)으로
> 검증했다(3년 캐시 재사용, 신규 KIS 호출 0건). **결과: `rsi_signal`이
> T+20에서 유의하게 역방향(1차 t_NW=-2.94, bullish_trend 내부 -2.79) —
> `fast_score` 예측력 실패의 구체적 원인 중 하나로 특정됨.** 신규 후보
> `risk_adj_momentum_3m`은 2차(3년) pooled 유의(t_NW=2.07)하고 어떤
> 국면에서도 유의하게 역전되지 않은 **유일한 Watch 후보**이나, 1차(최근
> 12개월) 유의성(t_NW=1.47)이 §16 게이트(|t|≥2) 미달로 완전한 Go는
> 아니다. `reversal_1m`은 하락장에서만 유의(T+5 t_NW=2.13)해 국면 조건부
> 후보로 분리 검토가 필요하다. **SPPV-3 착수는 계속 보류**하되, 다음
> 과제(`rsi_signal` 제거/반전한 `fast_score_v2` shadow 검증, `risk_adj_
> momentum_3m` 재검증, `reversal_1m` 하락장 조건부 오버레이 분리 검증)를
> 구체화했다. 상세: `plans/[DESIGN] signal_predictive_power_validation.md`
> §17.

> **📌 2026-07-14 SPPV-2.10 완료 — §17.5 후속 3과제 실측 (최신)**: §17.5가
> 지시한 후속 3과제를 실제로 수행했다. **`fast_score_v2`(rsi_signal
> 제거/부호반전) shadow 2종 모두 No-Go** — 하락장 T+5 spread가 원안
> (t_NW=-2.79)과 거의 동일하게 역전(drop -2.41, flip -2.32) —
> `rsi_signal`이 부분 원인일 뿐 주된 원인이 아니었음을 재확인, §2.9의
> 낙관적 프레이밍을 하향 조정한다. `risk_adj_momentum_3m`의 1차 창을
> 12→18개월로 넓히자 T+20 pooled spread t_NW이 1.47→**2.03**으로 §16
> 게이트 문턱을 겨우 통과했으나 T+5(1.97)는 여전히 미달인 marginal
> 결과라 **"Watch 유지, 조건부 상향"**에 그친다. `reversal_1m`은 하락장
> 96거래일을 시간순 반분해 안정성을 확인 — 방향은 전체/전반부/후반부
> 모두 일관되나(전반 1.87/후반 1.33) 반분 표본 각각은 개별 유의 문턱을
> 넘지 못해 **Hold 유지**. **SPPV-3 착수는 계속 보류**한다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §18.

> **📌 2026-07-14 SPPV-2.11 완료 — fast_score 전면 분해 + 창 경계 민감도
> + shadow 후보 (최신)**: §18.6이 지시한 세 과제를 실제로 수행했다.
> **`fast_score` leave-one-out 4종(성분 각 1개씩 제거) 분해 결과,
> `fast_trend`(SMA20 이격) 제거 시 하락장 T+5 spread가 -2.79→**-1.60(비
> 유의 전환)**으로 가장 크게 개선됨 — §17/§18에서 `rsi_signal`을 원인으로
> 지목한 것을 정정한다. 실제 주된 원인은 `fast_trend`였다.** (drop_
> volume_confirmation -2.58, drop_rsi_signal -2.39, drop_volatility_
> penalty -2.31 — 모두 여전히 유의하게 역전.) `risk_adj_momentum_3m`을
> 12/15/18/21개월 창으로 재검증한 결과 T+20 t_NW이 1.47→1.90→2.03→2.04로
> **안정적 plateau**를 보여 18개월 결과가 단발성 우연이 아님을 확인했으나
> 절대 크기는 여전히 marginal(~2.0)이다. 국면 전환형 shadow 후보 `regime_
> switch_v1`(비하락장=`risk_adj_momentum_3m`, 하락장=`reversal_1m`)을
> 신설해 검증 — **2차(3년) pooled가 T+5 t_NW=2.60, T+20 t_NW=2.36으로
> 이 트랙 전체에서 가장 강한 2차 결과**를 냈으나, 1차(최근 12개월)는
> 하락장 표본 부재로 여전히 risk_adj_momentum_3m 수준(1.47~1.55)에
> 머물러 §16 게이트를 완전히 통과하지 못한다 — **가장 유망한 Watch
> 후보로 격상하되 확정 Go는 아니다.** `fast_score`는 이번 결과로 부분
> 수정이 아닌 **전면 재설계 대상으로 확정**됐다. **SPPV-3 착수는 계속
> 보류**한다. 상세: `plans/[DESIGN] signal_predictive_power_
> validation.md` §19.

> **📌 2026-07-14 SPPV-2.12 완료 — regime_switch_v1 게이트 예외 규칙 +
> fast 계열 신규 feature (최신)**: §19.6이 지시한 두 과제를 수행했다.
> `regime_switch_v1`의 1차 게이트 예외 규칙 3개를 정의·비교했다 —
> **규칙 A(관찰 유예, 하락장 재발 시 자동 재검증, 절차적)**, **규칙
> B(최근-실사례 고정창, 가장 최근 bearish_trend 48거래일)**, **규칙
> C(적응형 최소 국면 표본 창, 최소 30거래일 확보까지 확장)**. 규칙 C는
> n=30에서 T+5 t_NW=**4.18**로 급등했지만 n=48(규칙 B)에서는 **1.33**에
> 불과해, **"목표 유의 수준을 넘길 때까지 표본을 사후적으로 줄이는"
> 구조 자체가 데이터 스누핑을 만든다고 판정하고 채택을 거부**한다 —
> 공격형 시스템이라도 이런 자기선택적 표본 축소는 실거래 재현성을
> 보장하지 못한다. 규칙 B(고정 표본, 정직한 측정)는 1.33~1.61로
> 여전히 §16 게이트 미달 — **규칙 A(관찰 유예)를 유일하게 채택**한다.
> fast 계열 신규 feature 2종(`rsi_mean_reversion`=연속형 평균회귀
> RSI, `sma5_over_sma20_gap`=단기 이동평균 격차)도 실측 — 둘 다 범용
> `fast_score` 대체 후보로는 **No-Go**다. `rsi_mean_reversion`은
> 하락장(T+5)에서만 유의(t=2.26, `reversal_1m`과 동일한 국면 조건부
> 패턴), `sma5_over_sma20_gap`은 SMA20 이격과 마찬가지로 하락장에서
> 유의하게 역전(t=-2.67) — "이동평균 창을 짧게 하면 해결된다"는 가설도
> 기각됐다. **SPPV-3 착수는 계속 보류**한다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §20.

> **📌 2026-07-14 SPPV-2.13/2.14 완료 — regime_switch_v1 모니터링 실행체
> + 완전 신규 fast 계열 feature (최신)**: §20.5가 지시한 두 과제를
> 수행했다. `regime_switch_v1`의 규칙 A(관찰 유예)를 **실제 실행 가능한
> 경량 모니터링 스크립트**(`scripts/monitor_regime_switch_v1_gate.py`)로
> 구현했다 — 벤치마크(069500) 1종목만 조회(신규 KIS 호출 0건)해 최근
> 12개월 창의 국면 분포를 확인하고, `bearish_trend` 거래일이 30일
> 이상이면 `TRIGGERED`, 1~29일이면 `PARTIAL`, 0일이면 `NOT_TRIGGERED`
> 로 자동 판정한다. 실행 결과: **`NOT_TRIGGERED`(최근 12개월
> bearish_trend 0일)** — §20 판단과 일치, 재검증 시점 아님을 실측으로
> 재확인했다. 이어서 "절대 가격 수준"에 전혀 의존하지 않는 완전 신규
> fast 계열 feature 2종을 실측했다 — **`money_flow_5d`**(최근 5거래일
> 상승/하락일 거래대금 비대칭, 자금 흐름 축)와 **`relative_strength_
> rank_1m`**(cross-sectional 상대강도 순위, 시장 베타 제거). **결과:
> 둘 다 pooled/1차 유의성 없이 범용 대체 후보로 No-Go.** `money_
> flow_5d`는 모든 구간 |t|<1.2로 방향성조차 없는 완전 무신호다.
> `relative_strength_rank_1m`은 하락장(T+5)에서 유의하게 **역전**
> (t=-2.13) — **시장 베타를 완전히 제거한 상대강도조차 하락장에서는
> 반대로 작동한다**는, 절대/상대 지표 구분을 넘어선 더 강력한 규칙성을
> 재확인했다. **SPPV-3 착수는 계속 보류**한다. 상세:
> `plans/[DESIGN] signal_predictive_power_validation.md` §21, §22.

> **📌 2026-07-15 국면별 신호 극성 종합 및 상위 방향 확정 (최신,
> 최우선 반영)**: SPPV-2.9~2.14(§17~§22)에서 산출된 10개 신호
> (`fast_score`, `fast_trend`, `sma5_over_sma20_gap`, `rsi_signal`,
> `rsi_mean_reversion`, `relative_strength_rank_1m`, `reversal_1m`,
> `money_flow_5d`, `risk_adj_momentum_3m`, `regime_switch_v1`)를 절대
> 추세·오실레이터·자금흐름·상대강도·복합 5개 축으로 분류해 하나의
> 종합표로 정리했다(별도 문서 `plans/[ANALYSIS] sppv_regime_polarity_
> synthesis_and_next_direction.md`). **핵심 발견: 8/10 신호가 "추세형
> 신호는 상승/횡보장 전용(또는 무신호), 되돌림형 신호는 하락장 전용"
> 규칙성을 따른다** — 절대 지표뿐 아니라 시장 베타를 제거한 상대
> 지표(`relative_strength_rank_1m`)에서도 재현돼 구조적 특성으로
> 판단된다. **예외: `rsi_signal`은 하락장이 아니라 상승장에서 역전** —
> 규칙성에 억지로 끼워 맞추지 않고 별개 문제(RSI 계단함수 설계 결함)로
> 분류했다. `fast_trend` 단독은 하락장에서 비유의(-0.79)하지만 `fast_
> score`(합성) 하락장은 강하게 유의하게 역전(-2.79)한다는 점도 확인 —
> 개별 성분보다 상관된 조합 효과가 더 크다.
>
> **판정: feature 추가 실험을 중단하고 국면 분기형 entry 설계 검토로
> 전환한다.** 절대·상대·오실레이터·거래량·복합 5개 축을 모두 시도해
> 매번 같은 결론에 수렴했다는 것이 근거다 — 11번째 새 feature를
> 시도해도 같은 결론이 반복될 가능성이 높고, "결론이 나올 때까지 새
> feature를 계속 시도"하는 것 자체가 §20에서 경계한 데이터 스누핑과
> 같은 위험을 반복한다. `regime_switch_v1`이 단일 정적 가중치로는
> 얻지 못한 트랙 최고 2차 pooled 유의성(T+5=2.60/T+20=2.36)을 국면
> "전환"만으로 달성한 것이 이 판정의 직접 증거다. **유니버스/시장
> 미시구조 재검토는 후순위로 유지**한다 — 근본 설계 검토(§2)의 "신호
> 미검증 시 소싱 개선은 잘못된 레버" 원칙이, 지금은 "이미 검증된
> 국면 조건부 신호를 먼저 entry 설계에 활용하라"는 방향으로 이어진다.
> **SPPV-3의 다음 착수 형태는 `entry_score` sub-component의 단순
> 재현이 아니라 `regime_switch_v1` 아이디어를 국면 분기형 entry 설계
> 원형으로 삼는 것으로 재정의된다.** 이 판정은 사용자 확인을 권장한다.
> 상세: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
> direction.md`.

> **📌 2026-07-15 국면 분기형 entry 설계 초안 + shadow 계산기 (최신)**:
> 위 판정을 실제 설계 문서로 구체화했다 — 신규 문서
> `plans/[DESIGN] regime_conditional_entry_signal_v1.md`에 **국면별
> 신호 선택 매트릭스**(비하락장=`risk_adj_momentum_3m`, 하락장=
> `reversal_1m`, 판정불가=신호 미산출), **`entry_score` 통합 방안**
> (alpha layer 0.80 가중치 블록 교체 제안, 아직 미적용 — `entry_score`
> 코드는 손대지 않았다), **shadow 검증 계획**(Phase 1=1회 스냅샷,
> Phase 2=반복 로깅+out-of-sample 누적, Go/No-Go는 §16 기준 그대로
> 재사용)을 작성했다. `scripts/shadow_regime_conditional_entry_
> signal.py`(read-only, 신규 KIS 호출 0건 — 3년 캐시 재사용)로 실시간
> 스냅샷을 1회 실행 — 기준일 2026-07-14, 시장 공통 국면 `range_bound`,
> 87/87종목이 `risk_adj_momentum_3m` 분기 신호 산출(하락장 분기는
> 미발동, §21 모니터링 NOT_TRIGGERED와 정합). 이번 실행은 신호 유의성을
> 다시 검증한 것이 아니라 **설계가 실제로 동작하는지 확인한 연결성
> 테스트**다. 상세: `plans/[DESIGN] regime_conditional_entry_
> signal_v1.md`.

> **📌 2026-07-15 regime_conditional_signal Phase 2 shadow 누적
> 사이클 구축 (최신)**: Phase 2(반복 shadow 로깅)를 실제 실행 가능한
> 오케스트레이터로 구현했다 — 신규
> `scripts/run_regime_conditional_shadow_cycle.py`가 §21(monitor_
> regime_switch_v1_gate.py)의 게이트 판정 로직과 §22(shadow_regime_
> conditional_entry_signal.py)의 신호 계산 로직을 **벤치마크 bars를
> 1회만 조회해** 함께 실행하고, 그 결과를 누적 이력 파일
> `logs/regime_conditional_signal_shadow_history.jsonl`(append-only,
> 거래일당 1줄, 중복 거래일 자동 skip)에 추가한다. 게이트가
> TRIGGERED/PARTIAL로 전환되면 재검증 절차(runbook)를 화면에 출력
> 한다(자동 재검증은 하지 않음 — 3년 캐시 재구축은 신중한 판단이
> 필요한 별도 작업). **실행 결과: 게이트 NOT_TRIGGERED(2026-06-16
> 기준, bearish_trend 0일), 신호 계산 2026-07-14 기준 `range_bound`로
> 87/87종목 `risk_adj_momentum_3m` 분기 — 이력에 1줄 추가.** 즉시
> 재실행해 **중복 방지 로직이 실제로 발동**(같은 거래일 재추가 skip)
> 함을 확인했다. `entry_score` 코드/운영 변경 없음. 상세:
> `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §6.

> **📌 2026-07-15 entry_score 중복 penalty ablation 실측 (최신)**:
> SPPV-3 착수 전제인 "중복 억제 구조를 point-in-time 기준으로 재현하고
> 분해할 준비"를 실제 실측으로 구체화했다(`plans/[DESIGN] regime_
> conditional_entry_signal_v1.md` §8). 신규
> `scripts/shadow_entry_score_penalty_ablation.py`가 Phase 0(재구성
> 가능 구간)만으로 운영 함수(`_build_entry_score`, `_assess_buy_
> eligibility`)를 그대로 호출해, 오늘(87종목) 기준 세 penalty 축을
> 독립 평가했다 — **축 A(entry_score regime penalty, -0.15) 85건**,
> **축 B(eligibility의 bearish+risk_off 차단) 60건**, **축
> C(eligibility signal floor, overall<-0.10 또는 slow<-0.15) 75건**.
> **핵심 발견: B가 발동한 60건은 예외 없이 A·C도 함께 발동한다
> (A∩B∩C=60=B 전체)** — `plans/[ANALYSIS] foundational_design_review_
> objective_alignment.md` §2의 "삼중 중복" 지적이 추상적 우려가 아니라
> 오늘 데이터로 **100% 재현되는 사실**임을 확인했다. 운영 `_assess_
> buy_eligibility` 함수를 그대로 호출한 결과도 통과 6/87(≈6.9%)로
> 과거 DB 기준선(21/297≈7%)과 대략 일치한다. **부가 발견**: `entry_
> score`가 실제로 쓰는 **종목별(per-symbol)** `regime_label` 분포는
> bearish_trend 60/87(69%)인데, 시장 공통(KODEX 200 벤치마크) 국면은
> `range_bound`다 — §12.1(SPPV-2.6)에서 코드로 확인했던 "종목별
> regime_label은 시장이 아니라 종목 자신의 신호" 문제가 운영 코드에
> 여전히 남아있고 오늘도 실제로 시장 판단과 크게 어긋난다. **따라서
> `entry_score`에 `regime_conditional_signal`(시장 공통 국면 기준)을
> 통합하려면, regime penalty/eligibility의 국면 정의(종목별 vs 시장
> 공통)를 먼저 통일해야 한다**는 새로운 착수 전제가 추가됐다. 운영
> DB(`trade_decisions`) 직접 조회는 자동 승인 경계 밖 프로덕션 읽기로
> 판단돼 이번 턴에 시도하지 않았다. 상세:
> `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §8.

> **📌 2026-07-15 중복 억제 시계열 누적 + 국면 정의 비교 체계 구축
> (최신)**: 위 §8의 하루치 관찰을 §6(Phase 2)이 확립한 누적 패턴에
> 맞춰 시계열 절차로 승격했다. 신규
> `scripts/run_entry_score_penalty_ablation_cycle.py`가 `shadow_
> entry_score_penalty_ablation.py`(penalty 축 A/B/C)와 `shadow_regime_
> conditional_entry_signal.py`(시장 공통 국면)의 함수를 그대로
> 재사용해, 종목별 국면과 시장 공통 국면을 같은 실행에서 나란히
> 계산하고 누적 이력(`logs/entry_score_penalty_ablation_history.jsonl`,
> 중복 거래일 자동 skip)에 기록한다. **실행 결과: §8과 완전히 동일한
> 수치(A=85/B=60/C=75/A∩B∩C=60)로 교차 검증됐고, 국면 일치 18건/
> 불일치 69건(79%)** — 그중 "시장 비하락장인데 종목별 하락장" 60건,
> "시장 하락장인데 종목별 비하락장" 0건. 즉시 재실행해 중복 방지
> 로직이 정상 발동함을 확인했다. **SPPV-3 본작업용 비교 실험**을
> 설계 문서 §9.6에 구체화했다 — 기존 3년 rolling 표본에 대해 (a)
> 현행 종목별 국면 정의와 (b) 시장 공통 국면 정의로 `_assess_buy_
> eligibility`를 각각 재계산해, 두 정의 아래 통과 종목의 forward
> return을 §16 이원 기준(quintile spread + Newey-West)으로 비교한다
> — 새 KIS 호출 없이 기존 3년 캐시로 수행 가능하다. `entry_score`
> 코드/운영 변경 없음. 상세: `plans/[DESIGN] regime_conditional_
> entry_signal_v1.md` §9.

> **📌 2026-07-15 §9.6 비교 실험 실측 — 종목별 vs 시장 공통 regime
> 정의 (최신)**: 위 §9.6에서 설계한 실험을 실제로 실행했다(신규
> `scripts/validate_entry_score_regime_definition_comparison.py`).
> 3년 rolling 표본(87종목, 56,753건)에 운영 함수 `_assess_buy_
> eligibility()`를 그대로 호출해 **변형 A(종목별 regime)**와 **변형
> B(시장 공통 regime)** 각각의 통과군 T+5/T+20 forward return을 §16
> 이원 검증 도구로 비교했다. **핵심 결과: 변형 B가 변형 A보다 통과율은
> 더 낮으면서(18.75% < 20.64%) 통과 종목의 forward return은 더 높다
> (T+5 +1.0357%>+0.9254%, T+20 +3.5780%>+3.1861%, 둘 다 baseline
> 대비 통계적으로 유의, t_NW 7.3~7.7).** "더 많이 통과시켜서 좋아
> 보이는 착시"가 아니라 "더 적게, 더 좋은 것만" 통과시키는 방향이라
> 과잉 억제가 아니라 정밀한 억제일 가능성을 뒷받침한다. **다만 A-B
> 차이 자체의 통계적 유의성은 이번에 검정하지 않았고**, 통과군 내부
> 에서도 `overall_score` quintile spread가 여전히 유의하게 역전
> (T+20 t_NW=-2.84~-3.06)해 `overall_score` 재순위화 자체의 문제는
> 별개로 남아있다. **판정: Watch(조건부 유리, 확정 Go 아님)** — 단순
> 통과율 증가만으로 긍정 판단하지 않는다는 원칙에 따라 임계값/정의
> 변경을 밀어붙이지 않는다. **이번 턴 실행의 실제 KIS 호출 여부는
> 가정하지 않고 로그로 확인** — `HTTP Request:` **0건**(3년 캐시
> 완전 재사용, 종료 코드 0). 상세: `plans/[DESIGN] regime_conditional_
> entry_signal_v1.md` §10.

> **📌 2026-07-15 A/B 판정 불일치 표본 direct 비교 + 1차 창 재확인
> (최신)**: 위 §10.5가 지시한 두 과제를 실행했다(신규
> `scripts/validate_entry_score_regime_definition_ab_diff.py`).
> 같은 종목-거래일 표본을 `A_only`(A만 통과)/`B_only`(B만 통과)/
> `both`(둘 다 통과)/`neither`(둘 다 탈락) 4개 배타적 집합으로
> 분해했다. **가장 중요한 발견: `B_only`가 3년(56,753건)·최근
> 12개월(21,315건) 모두에서 정확히 0건이다.** 이는 우연이 아니라
> 구조적 사실이다 — B의 eligibility 차단 조건(`regime_label==
> 'bearish_trend' and risk_tone=='risk_off'`)은 A가 이미 통과시킨
> 표본을 "추가로" 차단하는 방향으로만 작동할 수 있어, **B는 A의
> 진부분집합(strict subset)일 뿐 새로운 종목을 발굴하는 효과가
> 없다.** 시장 공통 정의로 전환한다는 것은 "다르게 고른다"가 아니라
> "A가 고른 것 중 일부(`A_only`, 3년간 1,072건)를 추가로 빼는 것"
> 뿐이다. `A_only`의 forward return은 방향상 음수(T+5 -0.1694%,
> T+20 -0.7028%)이고 `both`(+1.04%/+3.58%)·`neither`(+0.60%/+2.44%)
> 보다도 낮아 §10의 "B가 A보다 낫다"는 결론의 메커니즘을 설명해주지만,
> **t_NW가 T+5 -0.62/T+20 -0.79로 |t|<1 — 통계적으로 전혀 유의하지
> 않다.** 원래 계획한 "일별 짝비교(day-matched paired diff)"는
> `B_only=0`이라 정의상 계산 불가함을 확인했고, 그 대신 `A_only`
> 자체의 유의성 검정이 실질적으로 동등한 검증임을 확인했다. **최근
> 12개월 창은 `A_only=B_only=0`으로 A-B 차이 자체가 존재하지
> 않는다**(§21 모니터링의 bearish_trend 0일과 정합) — "재현되지
> 않았다"가 아니라 "검증 기회 자체가 아직 없다"가 정확한 해석이다.
> **판정: Watch 유지(No-Go에 근접), 시장 공통 정의로의 확정 전환
> (Go)은 기각한다** — B가 새 기회를 만들지 못하고, 추가 차단의
> 유의성도 확인되지 않았기 때문이다. 이번 실행의 KIS 호출 여부도
> 가정 없이 로그로 확인 — `HTTP Request:` 0건. 상세:
> `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §11.

> **📌 2026-07-15 alpha layer vs regime_conditional_signal 직접 비교 —
> 무게중심을 차단에서 선별로 이동 (최신, 최우선 반영)**: §11.8의 지시에
> 따라 "국면 정의 통일"(누구를 걸러낼지, 차단 축)에서 "alpha layer
> 교체"(누구를 위로 올릴지, 선별 축)로 검증 무게중심을 옮겼다. 신규
> `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`가
> 현행 `entry_score`의 alpha layer(`_normalize_signed_score`의
> 선형성으로 순위상 `0.45·overall+0.20·fast+0.15·slow`와 동일함을
> 코드로 확인)와 `regime_conditional_signal`을 같은 3년 rolling
> 표본(87종목, 56,753건)에서 §16 이원 검증 도구(quintile spread +
> Newey-West)로 직접 비교했다. **핵심 결과: 2차(3년) 창에서 `regime_
> conditional_signal`이 T+5(t_NW=2.52)/T+20(t_NW=2.33) 둘 다 유의
> 임계(|t|≥2)를 통과하는 반면, 현행 alpha layer는 같은 표본에서
> 어디서도 유의하지 않다(1.02~1.39).** spread 크기·t값·양수 비율
> 4개 관측치(2개 창×2개 horizon) 전부에서 `regime_conditional_
> signal`이 일관되게 우세했다(1차 창 포함, T+20에서 격차가 특히
> 큼: 2.082%p vs 1.043%p). 이는 "더 막는 방법"이 아니라 "더 공격적
> 으로 좋은 종목을 위에 올리는" 관점에서 실제 우위가 있다는 뜻이다.
> 1차(최근 12개월) 게이트는 두 신호 모두 미달이나, 원인은 §21에서
> 이미 확인된 구조적 사실(최근 12개월 시장 공통 하락장 0일)이지
> 신호 결함이 아니다. **판정을 지나치게 보수적으로 눌러 Watch로
> 부르지 않고 "Conditional Go"(2차 검증 통과, 1차 게이트 전환 대기)
> 로 명시한다** — 동시에 §16 이원 기준을 자의로 낮춰 억지로 완전한
> Go를 선언하지도 않는다. 실행의 실제 KIS 호출 여부도 가정 없이
> 로그로 확인 — `HTTP Request:` **0건**. `entry_score` 코드/운영
> 변경 없음 — 이번 턴은 shadow/validation 범위에 머문다. 상세:
> `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §12.

> **📌 2026-07-12 방향 전환 (이력, 2026-07-14 결론으로 대체)**:
> 지난 6주(2026-06-01~07-12) 매수 0건은 시스템 오류가 아니라 **하락장에서
> 자본을 지켜낸 올바른 방어 작동**이었음이 실측으로 증명됐다
> (deep_negative T+3 -5.39% < inactive -3.17%, 게이트 해제 역-시뮬레이션
> SF1~SF12 전부 No-Go/Shadow-Watch).
> **따라서 `core_risk_off` 완화·`entry_score` 조작 시도는 이 시점부로 전면
> 영구 중단한다.** 아래 최근 메모의 shadow 완화 관측 이력은 역사적 기록으로
> 유지하되, 후속 작업으로 승격하지 않는다.
> 새로운 최우선 작업은 **소싱(후보 공급) 단계 복구**다 — 근본 원인은 모멘텀
> 포착 레이어(`_add_market_overlay`)가 `KIS_ENV=paper` 이중 게이트로 6주 내내
> 완전 비활성이었고, core universe는 가격 무관·회전 없음 + 지수 편입 데이터
> stale(2026-06-24 수동 스냅샷)이었다는 점이다. 설계/작업 순서/백로그는
> [`plans/[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`](./%5BDESIGN%5D%20universe_sourcing_momentum_overlay_enablement_v1.md)
> 참고 (UNIV-1: 라이브 read-only client 주입으로 overlay 활성화가 1순위).

- (이하는 2026-07-12 방향 전환 이전의 shadow 완화 관측 이력이다 — 역사적
  기록으로만 유지)
- `core_risk_off slow floor shadow` 후속 실측에서
  `2026-07-01 ~ 2026-07-10` active `trend_moderate_candidate` 4건을 확보했다.
- 후행 proxy는
  `T+1 평균 +2.1376%`,
  `T+3 평균 +4.3830%`,
  `T+3 양수 비율 100%`로
  `inactive` / `deep_negative` 대비 우위다.
- 그러나 4건 모두
  `candidate_count=4`, `selected_count=0`, `would_buy_count=0`,
  `submitted_count=0`이다.
- 개별 분해 기준 직접 병목은
  `shadow_topk_candidate_miss`이며,
  더 앞단 원인은
  `shadow_topk_candidate_gate_reason=signal_both_floor_miss`다.
- strict floor 상세 분해 기준으로는
  `overall_near_slow_deep=3`,
  `overall_deep_slow_near=1`이다.
- 추가 `slow floor shadow` 경로 분해 기준으로는
  `slow_floor_relax_ready=1`,
  `slow_floor_relax_activity_blocked=2`,
  `overall_floor_first=1`이다.
- 날짜 단위로 보면
  `slow_floor_relax_ready`는 현재 `2026-07-03` 1건뿐이고,
  그 1건도 `candidate=1`, `selected=0`, `would_buy=0`, `submitted=0`이다.
- 직접 원인 집계 기준으로는
  `projection_block_reason=shadow_topk_candidate_miss`,
  `gate_reason=signal_both_floor_miss`,
  `watch_reason=core_watch_path_only`다.
- 전환 단계 집계 기준으로도
  현재 ready 코호트는 `watch_only_core_path=1`이다.
- 날짜별로는
  `2026-07-03|watch_only_core_path=1`이다.
- 따라서 다음 우선 작업은
  `ranking top-k 완화`가 아니라
  `slow_floor_relax_ready` 코호트의
  `WATCH -> BUY candidate` 전환 가능성 장후 누적 관측이다.
- 이를 위해 `ops-scheduler` 장후 요약에도
  `slow_floor_relax_ready_count`,
  `slow_floor_relax_activity_blocked_count`,
  `slow_floor_relax_watch_only_core_path_count`
  를 노출하도록 보강했다.
- `2026-07-11` 현재 DB 기준 재집계에서는
  같은 기간 `trend_moderate_candidate_count=13`,
  `slow_floor_relax_ready_count=0`으로 다시 산출됐다.
  따라서 다음 우선 작업은
  기존 메모와 현재 재집계 diff 원인을 먼저 분해하는 것이다.
- diff 원인 분해 결과,
  이 값은 generic `core_risk_off_floor_diagnostics`를 읽은 결과였고,
  실제 후속 작업 기준인 `core_risk_off_floor_v5_diagnostics`와는 다르다.
- 따라서 운영 요약과 후속 shadow 관측은
  `core_risk_off_floor_v5_report / core_risk_off_floor_v5_diagnostics`
  를 우선 사용하도록 정렬했다.
- 이어서 ready 코호트 sample 자체를 별도 노출하는
  `active_slow_floor_relax_ready_samples`도 추가했다.
  최신 기준 ready sample은
  `2026-07-03 / 002790` 1건이며,
  `WATCH -> BUY candidate` 전환이 아직 열리지 않았음을
  sample row 기준으로 직접 추적할 수 있다.
- 최신 gap 계측 결과
  이 sample은
  `deterministic_buy_shape_block_reason=watch_from_exit_setup`,
  `buy_candidate_threshold_gap=0.4021`,
  `core_risk_off_ranking_min_gap=0.0634`로 나타났다.
  따라서 다음 우선 작업은
  `watch_from_exit_setup`가 core 신규 진입 관찰군에서
  얼마나 반복되는지와,
  그 pattern이 실제 기대수익률 관점에서 유효한지 분해하는 것이다.
- 후속 재집계 결과,
  `2026-07-01 ~ 2026-07-10` active `trend_moderate_candidate` 4건은
  전부 `watch_from_exit_setup`으로 집계됐다.
  후행 proxy는
  `T+1 평균 +2.1376%`,
  `T+3 평균 +4.3830%`,
  `T+3 양수 비율 100%`로 우수하지만,
  `selected=0`, `would_buy=0`, `submitted=0`은 그대로다.
- 같은 구간 `slow_floor_relax_ready` 1건도
  `watch_from_exit_setup + core_watch_path_only + shadow_topk_candidate_miss`
  조합으로 남아 있다.
  따라서 다음 우선 작업은
  `watch_from_exit_setup`와 `watch_from_entry_setup` 및
  `core_watch_path_only`의 코호트별 후행 proxy / 전환 경로 비교다.
- 추가 교차 실측 기준으로는
  active 전체 `watch_from_exit_setup=21건`의 `T+3 평균`이 `-1.4168%`로 약해졌고,
  그 안에서도
  `core_watch_path_only|watch_from_exit_setup=8건`은 `T+3 평균 +2.8953%`,
  `watch_with_eligibility_block|watch_from_exit_setup=13건`은 `T+3 평균 -3.5729%`로 갈렸다.
- 따라서 다음 우선 작업은
  `watch_from_exit_setup` 전체 완화가 아니라
  `core_watch_path_only|watch_from_exit_setup` 제한 코호트만 별도로 shadow 추적하고,
  `selected=0` 직접 병목을 그 좁은 코호트 기준으로 더 분해하는 것이다.
- 전용 병목 분해 결과,
  `core_watch_path_only|watch_from_exit_setup` 8건은
  전부 `signal_both_floor_miss + eligibility_core_risk_off_ranking_blocked`였고,
  `projection_block_reason`은
  `shadow_topk_candidate_miss=3`,
  `trend_outside_target=4`,
  `momentum_deep_negative_guard=1`로 갈렸다.
- 따라서 다음 우선 작업은
  이 8건 전체가 아니라
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건만 별도 코호트로 묶어
  `selected=0` 직접 병목과 후행 proxy를 계속 shadow 관측하는 것이다.
- 3건 제한 코호트 실측 결과,
  이 3건은 전부
  `shadow_topk_candidate_miss + signal_both_floor_miss + eligibility_core_risk_off_ranking_blocked`
  조합으로 동일했다.
  후행 proxy는
  `T+1 평균 +2.1376%`,
  `T+3 평균 +4.3830%`,
  `T+3 양수 비율 100%`로 유지된다.
- 따라서 다음 우선 작업은
  이 3건 코호트의 `signal_both_floor_miss` 내부를
  `overall floor 우선 병목`과 `slow floor 우선 병목`으로 더 세분화해,
  `ranking_blocked`가 독립 1차 병목인지 후행 2차 병목인지 분리하는 것이다.
- 추가 분해 결과
  `overall_near_slow_deep=2`,
  `overall_deep_slow_near=1`로 나타났다.
  즉 다수 표본의 직접 병목은 `overall`보다 `slow floor` 쪽이다.
- 따라서 다음 우선 작업은
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건 코호트에 한정한
  `slow floor` shadow 제한 완화 설계와 후행 실측이다.
- `slow_floor_shadow_relax_path` 직접 집계 기준으로는
  `slow_floor_relax_ready=1`,
  `slow_floor_relax_activity_blocked=1`,
  `overall_floor_first=1`로 갈린다.
- 따라서 다음 우선 작업은
  `002790` 2건에 해당하는
  `overall_near_slow_deep + (ready 또는 activity_blocked)` 코호트만 대상으로
  `slow floor` shadow 제한 완화안을 설계하고,
  `000240 overall_floor_first`는 이번 대상에서 제외하는 것이다.
- 이어서 제한 shadow 다음 병목을 직접 보기 위해
  `limited_slow_floor_shadow_path / limited_slow_floor_transition_stage`
  계측을 추가했다.
  다음 실측에서는
  `candidate_ready -> buy_shape -> would_buy`
  전환이 실제로 열리는지,
  아니면 여전히 `watch_only_core_path`에 머무는지를 우선 확인한다.
- 최신 재집계 결과,
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  3건은
  `candidate_ready=1`,
  `activity_blocked=1`,
  `overall_floor_first=1`로 분해됐다.
  이 중 유일한 `candidate_ready` 1건도
  `candidate_ready_watch_only_core_path`에 머물러
  아직 `BUY candidate`로 이어지지 않았다.
- 따라서 현재 후속 우선 작업은
  `slow floor` 추가 완화가 아니라
  `candidate_ready_watch_only_core_path`
  코호트의 `WATCH -> BUY shape` 전환 조건을
  shadow 계측으로 분해하는 것이다.
- 후속 분해 결과,
  유일한 `candidate_ready_watch_only_core_path` 표본은
  `exit_setup_large_entry_gap`으로 나타났다.
  즉 현재 1차 병목은 `ranking`보다
  `BUY threshold`까지의 큰 `entry gap`이다.
- 따라서 다음 우선 작업은
  `candidate_ready_watch_only_core_path`
  코호트의 `entry gap` 분포를 누적 관측하고,
  `large entry gap`과 `moderate entry gap`의
  후행 proxy 차이를 분리하는 것이다.
- 이를 위한 운영 계측으로
  `watch_only_core_path_entry_gap_band`
  및
  `trade_date|entry_gap_band`
  집계를 추가했다.
- 같은 집계는 `ops-scheduler` 장후 summary에서도
  `watch_only_core_path_*_entry_gap_count`로 바로 확인 가능하게 반영했다.
- 추가로 `entry_gap_band`별
  `candidate/select/would_buy/submitted`
  projection 집계도 붙여,
  표본 누적 시 band별 전환력 비교가 가능하게 했다.
- 동일 전환 카운트는 `ops-scheduler` 장후 summary에서도
  `watch_only_core_path_*_entry_gap_candidate_count / would_buy_count / submitted_count`
  형태로 바로 확인 가능하게 반영했다.
- 이후 `2026-07-01 ~ 2026-07-10` 구간을
  최신 코드 기준으로 다시 재집계한
  `trigger_proxy_attribution_2026-07-01_2026-07-10_v12_entry_gap_recheck.json`
  에서도
  `candidate_ready_watch_only_core_path`의 `entry_gap_band`는
  `2026-07-03|large_entry_gap=1`만 재확인됐다.
  - `moderate_entry_gap=0`
  - `small_entry_gap=0`
  - `entry_ready=0`
- 따라서 현재 상태는
  `후행 proxy 누락` 문제가 아니라
  **현행 shadow 조건과 과거 원자료 기준으로
  해당 band 표본 자체가 아직 발생하지 않는 상태**로 해석하는 것이 맞다.
- 즉 다음 우선 작업은
  신규 거래일 누적 관측만 기다리는 것이 아니라,
  과거 재집계 기준 `large`만 남는 구조가
  `BUY threshold gap` / `entry gap band` 경계 문제인지
  upstream score 분포 문제인지 추가 분해하는 것이다.
- authoritative 완화는
  `moderate/small/entry_ready` 중 실제 전환력이 확인되는 band가 생기기 전까지
  계속 금지 유지한다.
- 추가 `v13` 진단 기준으로
  같은 상위 target 코호트
  `core_watch_path_only|watch_from_exit_setup|trend_moderate_candidate`
  전체를 다시 보면
  `buy_candidate_threshold_gap_band`는
  `large_entry_gap=2`, `buy_gap_missing=1`이며
  `moderate/small/entry_ready=0`이다.
- 단계 교차 기준으로는
  `candidate_ready_watch_only_core_path|large_entry_gap=1`,
  `activity_blocked|large_entry_gap=1`,
  `overall_floor_first|buy_gap_missing=1`만 존재한다.
- 즉 현재는
  `candidate_ready_watch_only_core_path` 내부 band 표본 부족 문제를 넘어,
  상위 target 코호트 전체에서도
  `non-null buy gap`이 전부 `large`라는 점이 확인됐다.
- 따라서 다음 우선 작업은
  신규 거래일 대기보다 먼저
  `watch_from_exit_setup` target 코호트의
  `shadow_entry_score / buy gap / ranking gap` 분포를
  authoritative BUY 경로와 직접 비교해서,
  `moderate/small/entry_ready` 부재가
  실제 `entry_score` 하방 편향 때문인지 검증하는 것이다.
- 후속 strict 비교 재집계 결과,
  `2026-06-01 ~ 2026-07-10` 전체에서도
  strict `authoritative core BUY path`
  (`buy_candidate=true` 또는 `candidate_intent=buy` 또는 `primary_candidate=buy_candidate`)
  표본은 `0건`이었다.
- 따라서 현재 다음 우선 작업은
  strict BUY baseline과의 직접 비교가 아니라,
  `watch_from_entry_setup` / `entry_score >= 0.52` /
  `0.55 <= entry_score < 0.65`
  같은 `pre-BUY staging cohort`를 비교군으로 재정의해
  target 코호트의 `entry_score` 병목을 계속 분해하는 것이다.
- `2026-07-01 ~ 2026-07-10` 재집계 결과,
  `pre-BUY staging cohort`는 실제로 존재하지만
  전부 `inactive / watch_setup_but_ineligible / eligibility_low_relative_activity`
  경로에 머물렀고,
  `candidate=0`, `selected=0`, `would_buy=0`, `submitted=0`이었다.
- 따라서 현재 다음 우선 작업은
  `slow floor` 추가 완화가 아니라
  `pre-BUY staging` 표본의
  `activity / eligibility` 병목을 shadow로 더 세분화해,
  진짜 1차 병목이 `entry_score`인지 `low_relative_activity`인지 분리하는 것이다.
- 후속 `activity_detail` 재집계 결과,
  `pre-BUY staging`의 `low_relative_activity` 표본은
  단일 군이 아니라
  `max(volume_surge_ratio, turnover_surge_ratio) < 0.80`
  심층 부족 표본과
  `0.95 <= max_ratio < 1.10`
  경계 근접 표본으로 갈렸다.
- 특히 `0.55 <= entry_score < 0.65`의 가장 강한 pre-BUY 표본도
  `low_relative_activity_max_0_95_to_1_10`으로 확인됐다.
  즉 이 구간은 `entry_score`보다
  `activity hard block`이 먼저 막는 구조가 유지된다.
- 따라서 현재 후속 우선 작업은
  `slow floor`나 `entry_score` 전체 완화가 아니라,
  `pre-BUY staging + low_relative_activity_max_0_95_to_1_10`
  경계 코호트만 별도 shadow 관측해
  후행 proxy와 `candidate -> selected -> would_buy -> submitted`
  전환력을 확인하는 것이다.
- 이후 `2026-06-01 ~ 2026-07-10` 장기 재집계까지 확인한 결과,
  위 경계 코호트는
  `2026-07-08 / 001450`,
  `2026-07-09 / 001450`
  두 건뿐이며,
  둘 다 `candidate=0`, `selected=0`, `would_buy=0`, `submitted=0`으로 유지됐다.
- 따라서 다음 우선 작업은
  단순 기간 확대 관측이 아니라
  이 경계 코호트의 `activity hard block`이
  실제 1차 병목인지,
  아니면 `entry/ranking gap`보다 뒤의 병목인지
  추가 분해하는 것이다.
- 후속 `v21` 재집계 기준,
  `low_relative_activity_max_0_95_to_1_10` 경계 코호트 2건은
  각각
  `activity_first_moderate_entry_gap`,
  `activity_first_small_entry_gap`
  으로 분류됐다.
- 특히 `2026-07-09 / 001450`는
  `small_entry_gap + small_ranking_gap`인데도
  `candidate=0`으로 남아 있어,
  현재 계측 기준 1차 병목은 `ranking`보다 `activity hard block` 쪽으로 해석하는 것이 맞다.
- 따라서 다음 우선 작업은
  `activity`를 counterfactual로 통과시켰을 때
  다음 병목이 `top-k candidate`, `top-k selected`, `buy shape` 중 어디로 이동하는지
  shadow 순서 계측을 추가하는 것이다.
- 후속 `v23` 재집계 기준,
  위 2건은 `activity` 해제 이후
  각각
  `buy_shape_after_activity_moderate_entry_gap`,
  `buy_shape_after_activity_small_entry_gap`
  으로 이동했다.
- 추가 `buy_shape` 세부 분해 기준으로는
  둘 다
  `watch_from_entry_setup|moderate_entry_gap`,
  `watch_from_entry_setup|small_entry_gap`
  으로 집계됐고,
  `candidate=0`, `selected=0`, `would_buy=0`, `submitted=0`이다.
- 따라서 현재 다음 우선 작업은
  `activity`나 `top-k` 완화가 아니라
  `watch_from_entry_setup` 내부의
  `entry gap / entry score` 분포를 더 세분화하여,
  어떤 band에서만 제한 완화 검증을 계속할지 shadow로 누적 관측하는 것이다.
- 전용 `v24` 재집계 기준,
  `watch_from_entry_setup|small_entry_gap` 1건은
  `T+1 +5.8252%`,
  `candidate/select/would_buy/submitted = 0/0/0/0` 이고,
  `watch_from_entry_setup|moderate_entry_gap` 1건은
  `T+1 -5.0066%`,
  `candidate/select/would_buy/submitted = 0/0/0/0` 이다.
- 즉 현재 초기 관측만 보면
  `small_entry_gap`이 `moderate_entry_gap`보다 유리하지만,
  둘 다 실제 주문 전환력은 아직 0이므로
  authoritative 완화는 여전히 금지 유지가 맞다.
- 위 결론은 `2026-07-08`, `2026-07-09` 두 날짜만 따로 떼어 본 것이 아니라,
  `2026-07-01 ~ 2026-07-10` 전체 재집계 결과에서
  해당 코호트에 실제로 걸린 표본을 추출해 확인한 것이다.
- 따라서 다음 우선 작업은
  `watch_from_entry_setup|small_entry_gap`
  코호트의 `T+3 / MFE / MAE`가 채워질 때까지 누적 관측하고,
  동시에 `candidate -> selected -> would_buy -> submitted`
  전환이 열리는지 추가 검증하는 것이다.
- 운영 관측 편의를 위해
  `ops-scheduler` 장후 summary에도
  `pre_buy_boundary_entry_setup_small_gap_*`,
  `pre_buy_boundary_entry_setup_moderate_gap_*`
  metric을 추가했다.
  따라서 다음 거래일부터는
  `operations_day_runs.summary_json.trigger_proxy_attribution`
  기준으로도 두 코호트의 누적 전환 상태를 바로 확인할 수 있다.
- `2026-07-12` 기준 방향 전환 메모:
  - `core_risk_off` v5 hydration 누락은 분석 경로에서 해소됐다.
    `2026-07-01 ~ 2026-07-10` 구간 `core` 97건 중
    `shadow_overall_score_v5 / shadow_slow_score_v5`가 `97/97`,
    active core `49/49`로 채워진다.
  - 따라서 당분간 `core_risk_off` threshold 완화는 중단한다.
  - 같은 구간 `core entry_score 평균`은 `0.1578`로 매우 낮고,
    `watch_from_entry_setup` 또는 `entry_score >= 0.52` 근접군은 `27건`,
    `0.52 <= entry_score < 0.65`는 `10건`뿐이다.
  - 현재 매수 부재의 1차 병목은 `risk_off` guard보다
    `entry_score` 하방 편향에 더 가깝다.
  - 자동화된 `entry_score_bias_report` 재집계 기준으로
    `near_buy_floor(0.52<=entry_score<0.65)` 10건은
    `risk_off_penalty=-0.15` 제거 시 `10/10`이 BUY floor `0.65`를 넘고,
    `strategy_alignment(+0.05)`만으로는 `0/10`,
    `relative_activity_bonus` 최대치로는 `5/10`만 넘는다.
  - 따라서 현재 `entry_score` 하방 편향의 직접 구조는
    `risk_off_penalty`가 1차 억제,
    `strategy / activity`가 2차 억제로 해석하는 것이 맞다.
    단, 현 세션 원칙상 이는 즉시 완화 근거가 아니라
    관측/분해용 근거로만 사용한다.
  - 추가 분해 결과
    `watch_from_entry_setup_or_ge_052` 27건 중
    `high_volatility`는 `26건`,
    `fast_score < -0.20`은 `14건`,
    `fast_score >= 0`은 `3건`뿐이었다.
    `top_core_samples` 상위권도
    `high_volatility`가 사실상 상수이고
    대부분 `fast_score`가 음수였다.
  - 따라서 `entry_score`의 2차 병목은
    `fast_score` 약세와 `high_volatility`의 동시 발생으로 보는 쪽이 맞다.
  - 추가 back-simulation 결과,
    `2026-06-01 ~ 2026-07-10` 기준
    `SF1_broad_remove_risk_off_near_buy_floor`는
    `T+1=-1.4160%`, `T+3=-5.2937%`, `T+5=-8.4620%`로
    명확한 `No-Go`다.
  - `core` 한정 축소안(`SF2/SF3`)도
    표본 `4건`, `T+3=-8.4906%`, `T+5=-16.9434%`로
    아직 `Go` 근거가 없다.
  - 따라서 다음 shadow formula는
    `risk_off_penalty` 단독 완화가 아니라
    `fast_score`와 `high_volatility`를 함께 제어하는
    더 좁은 구조로 설계해야 한다.
  - 참고로 `fast_score >= -0.12`라는
    단일 협소 필터만 추가해도
    표본 `17건`, `T+1=+0.0883%`, `T+3=-3.1981%`, `T+5=-3.9202%`로
    아직 `No-Go`다.
    즉 다음 단계는 `fast` 단일 필터가 아니라
    `fast + volatility` joint shadow formula 설계다.
  - 추가 joint shadow formula 실측 결과,
    `SF7_market_high_vol_fast_ge_-0.12_no_rel_bonus`
    (`market_overlay + high_volatility + fast_score >= -0.12 + relative_activity_bonus 없음`)
    은 `count=4`, `T+1=+2.0353%`, `T+3=+0.8455%`, `T+5=+3.4324%`로
    broad `No-Go` 대비 확실히 개선됐다.
  - 다만 이 결과는 `000660` 2건, `000810` 1건, `009150` 1건의
    소표본에 집중돼 있으므로
    아직 authoritative `Go`는 아니다.
    현 시점 판정은 `Shadow-Watch`다.
  - leave-one-symbol-out 기준으로도
    `000660`을 제외하면
    `SF7/SF8`의 `T+3`는 `+0.8455% -> -3.7818%`로 다시 음수다.
    즉 아직 일반화 가능한 구조 신호가 아니라
    특정 심볼 기여가 큰 국소 표본으로 봐야 한다.
  - 심볼당 1건만 남기는 중복 제거 기준에서도
    `SF7`은 earliest 선택 시 `T+3=+2.7413%`,
    latest 선택 시 `T+3=-4.1351%`로 부호가 뒤집혔다.
    즉 현재 신호는 관측 시점 선택에도 민감하다.
  - 추가 전환 점검에서도
    `SF7/SF8` 표본은 전부 `watch_candidate=true`지만
    `buy_candidate=0`, `submission_accepted=0`이었다.
    즉 아직 수익률이 좋아 보이는 협소 band가 있어도
    실제 매수 실행 경로는 전혀 열리지 않았다.
  - 코드상 이 다음 병목은 사실상
    `buy_candidate_threshold = 0.65`다.
    다만 `eligibility_passed=True`였지만
    `buy_candidate=False`였던 2건(`000660`, `000810`, 2026-06-18)은
    gap 평균이 `0.0667`이었음에도
    가상 BUY 시 `T+3 평균 -6.2780%`, hit rate `0%`였다.
    즉 threshold만 낮추는 완화는 여전히 `No-Go`다.
  - 추가 분해에서도
    `ranking_score >= 0.60` 근접군 2건의 `T+3 평균`이 동일하게 `-6.2780%`였고,
    `entry_score >= 0.58` 구간 8건은 `T+3 평균 -7.5000%`였다.
    즉 지금은 상단 근접군을 더 빨리 BUY로 승격하는 쪽도 근거가 없다.
  - 추가 `source_type / relative_activity / fast_band` 교차 집계에서는
    유일하게 플러스가 나온 구간이
    `market_overlay + no_rel_bonus + fast_score -0.12~-0.05`
    4건뿐이었다.
    반면 같은 `market_overlay`라도
    `fast < -0.12` 또는 `rel_bonus=true`로 가면 다시 명확한 음수였다.
    즉 현재 분리축은 threshold 숫자보다
    `source lane + fast band + activity state` 조합에 가깝다.
  - 이 협소 lane 내부 추가 분해에서는
    `ranking_score`보다
    `return_3m_pct`와 `price_vs_sma_60_pct`가 더 나은 분리축이었다.
    `return_3m_pct >= 100` 및 `price_vs_sma_60_pct >= 50` 3건은
    `T+3 평균 +3.6988%`, `T+5 평균 +6.9099%`였고,
    반대편 1건(`000810`)은 음수였다.
  - 이를 고정한 `SF10/SF11/SF12`
    (`market_overlay + no_rel_bonus + fast -0.12~-0.05`
    + `return_3m_pct >= 100` / `price_vs_sma_60_pct >= 50`)
    는 모두 같은 3건으로 수렴했고,
    `T+3 평균 +3.6988%`, `T+5 평균 +6.9099%`였다.
    다만 여전히 표본이 3건뿐이라 authoritative `Go`는 불가하다.
  - 따라서 다음 우선 작업은
    `SF10/SF11/SF12`와 `SF7/SF8` 계열을
    장후 배치에서 shadow-only로 누적 관측해
    추가 `T+3/T+5` 표본을 쌓고,
    `candidate -> selected -> would_buy -> submitted` 전환이
    실제로 열리는지까지 같이 확인한 뒤,
    결과가 재현될 때만 승격 여부를 다시 판단하는 것이다.
- `2026-07-12` 기준으로
  `2026-07-01 ~ 2026-07-11` 재집계(`v25`)까지 확장해도
  두 코호트의 `T+3 / MFE / MAE`는 아직 비어 있다.
  이는 `2026-07-11`이 `토요일`이라
  `2026-07-08`, `2026-07-09` 표본 뒤의 추가 거래일이 아직 충분히 열리지 않았기 때문이다.
  따라서 현재 blocker는 정책/코드가 아니라
  **후속 거래일 미도래**이며,
  다음 실측은 다음 거래일 장후 배치 이후 다시 확인하는 것이 맞다.

## 현재 기준선

최근 완료된 핵심 작업:

1. `VTTC0081R` 체결내역 화면 Phase 1
   - [`plans/2026-06-02_vttc0081r_fill_history_screen_phase1.md`](./2026-06-02_vttc0081r_fill_history_screen_phase1.md)
2. fill snapshot ↔ order_request 직접 연결 + order sync truth source 전환 (Phase 2)
   - [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
3. fill sync budget retry 및 retry observability
   - [`plans/2026-06-03_fill_sync_budget_retry.md`](./2026-06-03_fill_sync_budget_retry.md)
   - [`plans/2026-06-03_fill_sync_retry_summary_json.md`](./2026-06-03_fill_sync_retry_summary_json.md)
4. fill-history API 서버 필터 추가
   - [`plans/2026-06-03_fill_history_server_filters.md`](./2026-06-03_fill_history_server_filters.md)
5. BUY/SELL 제출 경로, after-hours recovery, false expired 복구, shared budget, scheduler submit gate 관련 긴급 장애 다수 정리
   - 2026-06-01 ~ 2026-06-02 문서군 참조
6. 일반 submit cap 의미를 `일반 BUY cap`으로 명확화
   - [`plans/2026-06-04_general_buy_cap_split.md`](./2026-06-04_general_buy_cap_split.md)

즉, 현재는 “기본 기능이 아예 없는 상태”가 아니라:

- 체결내역은 수집/조회 가능
- 체결 snapshot은 주문과 연결 가능
- 주문 상태 복구는 fill snapshot을 truth source로 일부 사용 가능
- fill sync budget retry와 health summary도 있음

상태다.

따라서 다음 우선순위는 **운영 진실(source of truth) 강화**, **동기화 안정화**, **장중 운영 검증**, **구조적 기술부채 정리** 순서로 잡는 것이 맞다.

## 상태 표기

- `완료`: 문서에 적은 세부 작업이 현재 범위에서 모두 반영됨
- `진행중`: 핵심 구조는 들어갔지만 실측/잔여 세부 작업이 남음
- `미완료`: 아직 본격 구현 전
- `보류`: 의도적으로 후순위로 미룸

---

## Agent 설계 문서 반영 기준

`plan_docs/agents/` 문서를 반영하면, 남은 작업의 성격을 다음처럼 더 명확히 볼 수 있다.

### 1. 모든 Agent가 LLM일 필요는 없다

`Agent`는 책임 단위이지, 모두가 provider LLM 호출 단위는 아니다.

- `Data Collector`, `Data Quality`, `Execution`, `Performance`, `Model Monitor`는
  상당 부분이 deterministic service/worker로 구현되는 것이 맞다.
- 반대로 AI는
  - Event Interpretation
  - AI Risk
  - 향후 일부 Compliance/정책 해석
  같은 해석 계층에 우선 배치되어야 한다.

### 2. Execution / Guardrail / Compliance 집행은 deterministic이 우선이다

`03_risk_role_boundaries.md` 기준 현재 가장 중요한 원칙:

- `AI Risk Agent`는 **리스크 해석기**
- `Sizing Engine`은 **결정적 수량 계산기**
- `Hard Guardrail`은 **최종 강제 차단기**
- `AI Compliance Agent`가 생기더라도 **authoritative enforcement는 deterministic validator**

즉, 남은 작업 우선순위도 “AI를 더 붙이는 것”보다
“execution truth / guardrail / sync / reconciliation을 deterministic하게 더 닫는 것”이 먼저여야 한다.

### 3. 현재 진짜 미구현인 Agent 축은 전략/신호/포트폴리오 계층이다

`01_agent_inventory_and_status.md` 기준:

- 이미 일부 구현/운영 중인 축
  - Data Collector: 부분 구현
  - Data Quality: 부분 구현
  - News/RAG(Event Interpretation): 부분 구현
  - AI Risk: 구현
  - Execution: 부분 구현
- 아직 미구현인 핵심 축
  - Market Regime
  - Universe Selection
  - Strategy Selection
  - Signal
  - Portfolio
  - AI Compliance
  - Model Monitor

따라서 P2 이후 구조화 작업은 단순 backlog가 아니라,
**현재 v1에서 Final Decision Composer에 임시 흡수된 책임을 분리하는 과정**으로 해석해야 한다.

### 4. 현재 P0/P1 우선순위가 왜 agent 분해보다 앞서는가

agent 설계 문서 기준으로도 순서는 다음이 맞다.

1. 체결/주문/정합성 진실원 안정화
2. guardrail / snapshot / reconciliation / fill sync 안정화
3. 그 다음에 Market/Universe/Strategy/Signal/Portfolio 계층 분리

이 순서가 맞는 이유는, 상위 전략 계층을 세분화하더라도
하위 execution truth와 state convergence가 불안정하면 운영 가치가 떨어지기 때문이다.

---

## P0 — 즉시 진행할 백엔드/운영 과제

### 1. Fill History Phase 3 — `완료`

### 목표
- `fill snapshot`을 단순 조회 데이터가 아니라 **주문/정합성 복구의 1급 진실원**으로 끌어올린다.

### 세부 작업 상태
- [x] `order_request_id → trade_decision_id`까지 API/조회 경로 확장
- [x] 주문 상세 API에 linked fill snapshot 요약 추가
- [x] `order_sync_service`의 부분체결 판정을 `position_delta`보다 `fill snapshot` 우선으로 더 확대
- [x] 같은 `ODNO`의 다회 조회/누적 체결 표현 차이를 흡수하는 규칙 정리

### 근거 문서
- [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 우선순위 이유
- 현재 시스템의 가장 중요한 남은 리스크는 “실제 체결 진실을 얼마나 직접적으로 아느냐”다.
- 이 축이 안정돼야 `submitted/reconcile_required/partially_filled` 판단이 더 이상 snapshot 추론에 과하게 의존하지 않게 된다.
- agent 설계 문서 기준으로도 이것은 `Execution Agent`와 `Data Quality Agent`의 미완성 영역에 해당한다.

---

### 2. 부분체결 자동 판정 고도화 — `완료`

### 목표
- 현재 보수적으로 남겨둔 `partially_filled`/`submitted` 복구 케이스를 더 정확하게 자동 판정한다.

### 세부 작업 상태
- [x] fill snapshot의 `filled_quantity` 변화 패턴을 이용한 누적/증분 해석 규칙 추가
- [x] 같은 종목 연속 주문 cohort에서 `fill snapshot + order_time` 기준 안전한 매핑 규칙 정리
- [x] `position_delta` fallback은 마지막 수단으로만 사용하도록 축소
- [x] 부분체결 잔여 수량 계산과 후속 상태 전이(`partially_filled` 유지 vs `filled`) 테스트/수렴 보강
  - [`plans/2026-06-04_fill_snapshot_partial_progress_convergence.md`](./2026-06-04_fill_snapshot_partial_progress_convergence.md)

### 근거 문서
- [`plans/2026-06-03_vttc0081r_fill_history_phase2_order_link.md`](./2026-06-03_vttc0081r_fill_history_phase2_order_link.md)
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 의 reconciliation / partially filled 관련 항목
- `plan_docs/agents/03_risk_role_boundaries.md`

### 우선순위 이유
- false expired는 상당 부분 복구됐지만, 부분체결은 아직 가장 보수적인 영역이다.
- 이 부분이 해결돼야 operator 개입 없이 상태 수렴 품질이 올라간다.
- 또한 부분체결 판정은 AI가 아니라 deterministic truth/reflection 계층이 맡아야 하는 대표 영역이다.

---

### 3. 다음 거래일 장중 실운영 검증 — `완료`

### 목표
- 최근 수정들이 실제 장중 흐름에서 정상 작동하는지 **실측**한다.

### 현재 상태
- 장중 검증용 CLI 추가 완료:
  - [`plans/2026-06-04_intraday_operational_validation_cli.md`](./2026-06-04_intraday_operational_validation_cli.md)
- `operations_day_runs.summary_json`에 최근 `decision_submit_gate` / `decision_dry_run` 결과를 저장하도록 보강
- 현재는 아래를 한 번에 평가 가능
  - 거래일 판정
  - `operations_day_runs` heartbeat / phase
  - 최근 decision loop 결과
  - 오늘 BUY submit lane 상태
  - 차단성 미해결 주문
  - `truth_probe_fill_snapshot_incomplete`
  - snapshot/fill sync freshness

### 확인 포인트
1. `decision_submit_gate`가 `timeout=False`로 끝나는지
2. 일반 BUY lane이 실제로 열리는지
3. held-position SELL이 일반 BUY budget을 잠그지 않는지
4. fill sync가 budget retry 후 정상 completed 되는지
5. 주문이 다시 `expired`로 잘못 닫히지 않는지
6. `order_submission_attempts`, `fill snapshots`, `order sync`가 같은 주문에 대해 일관된지

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8a`
- [`plans/2026-06-01_paper_order_stability_measurement.md`](./2026-06-01_paper_order_stability_measurement.md)

### 우선순위 이유
- 최근 수정의 상당수는 장후/비거래일 기준 검증까지는 끝났지만, 장중 실측이 아직 남아 있다.
- 운영 시스템은 결국 장중 실동작이 최종 기준이다.

### 세부 작업 상태
- [x] 장중 첫 `decision_submit_gate` 이후 `decision_loop` summary 자동 적재 재확인
  - [`plans/2026-06-04_intraday_decision_loop_immediate_persist.md`](./2026-06-04_intraday_decision_loop_immediate_persist.md)
- [x] BUY submit 이후 추가 cycle에서 `submit_budget_consumed_*` 편향 감지 자동화
  - [`plans/2026-06-04_intraday_buy_lane_bias_check.md`](./2026-06-04_intraday_buy_lane_bias_check.md)
- [x] command별 최근 성공/실패 카운터를 `operations_day_runs.summary_json`에 구조화

---

### 4. Fill 발생 후 position/cash refresh 자동화 — `완료`

### 목표
- fill 확인 직후 계좌 snapshot이 더 빨리 최신화되도록 연결한다.

### 세부 작업 상태
- [x] fill snapshot 또는 post-submit sync 성공 시 snapshot refresh 직접 연결
  - [`plans/2026-06-04_partial_fill_snapshot_refresh.md`](./2026-06-04_partial_fill_snapshot_refresh.md)
- [x] cash / positions / orderable amount 갱신 우선순위 1차 정리
- [x] refresh 중 quota 소진 시 degraded 처리 기준 1차 명확화
- [x] 장중 실측 기준 수렴 속도 재검증
  - [`plans/2026-06-05_fill_refresh_convergence_measurement.md`](./2026-06-05_fill_refresh_convergence_measurement.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `14`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 우선순위 이유
- 주문 truth와 계좌 truth가 더 빨리 수렴해야 다음 주문 sizing/guard도 안정화된다.
- 이는 `Data Collector` / `Data Quality` / `Execution` 경계가 실제 운영에서 닫히는 작업이다.

---

## P1 — 높은 우선순위의 운영/플랫폼 과제

### 5. KIS 실계정/실운영 smoke 검증 — `완료`

### 목표
- paper에서 정리한 제출/동기화 경로를 실제 KIS credential 환경에서도 검증한다.

### 세부 작업 상태
- [x] KIS real credential + operator 승인 하의 실제 combined submit smoke 실행
  - 실제 KIS 응답 확인: `KIOK0320 / 장운영시간이 아닙니다`
- [x] live-info read-only smoke(`auth / approval / quote`) 경로 추가
  - [`plans/2026-06-05_kis_live_readonly_smoke_phase1.md`](./2026-06-05_kis_live_readonly_smoke_phase1.md)
- [x] live submit preflight(read-only)
  - [`plans/2026-06-05_kis_live_submit_preflight_phase3.md`](./2026-06-05_kis_live_submit_preflight_phase3.md)
- [x] guarded combined submit smoke runner
  - [`plans/2026-06-05_kis_live_combined_submit_smoke_runner.md`](./2026-06-05_kis_live_combined_submit_smoke_runner.md)
- [x] guarded combined submit dry-run smoke 검증
  - `status=READY`, `submitted=False`
- [x] live info / paper submit 경로의 budget 분리 1차 정리
  - live quote client 전용 live budget manager 주입
- [x] fill sync와의 실제 budget 경쟁 실측
  - [`plans/2026-06-05_kis_budget_isolation_smoke_phase2.md`](./2026-06-05_kis_budget_isolation_smoke_phase2.md)
- [x] paper 전용 우회 정책이 live에도 불필요하게 남아 있지 않은지 확인
  - [`plans/2026-06-05_kis_budget_isolation_smoke_phase2.md`](./2026-06-05_kis_budget_isolation_smoke_phase2.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8`

---

### 6. KIS token/approval cache 공통 모듈화 — `완료`

### 목표
- paper/live/disclosure/holiday/approval key 경로에 흩어진 토큰 캐시 로직을 정리한다.

### 세부 작업 상태
- [x] 공통 cache contract 1차 정리
- [x] cache purpose 표준화 1차 정리
- [x] expiry/fingerprint/validator helper 추출
- [x] rest/holiday/market_state client 통합 적용
- [x] approval key를 REST client 쪽에서도 파일 cache까지 확장
  - [`plans/2026-06-08_kis_rest_approval_key_file_cache.md`](./2026-06-08_kis_rest_approval_key_file_cache.md)
- [x] token cache health를 운영 관측값에 직접 노출
  - [`plans/2026-06-08_kis_token_cache_health_observability.md`](./2026-06-08_kis_token_cache_health_observability.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `34`
- [`plans/2026-06-05_kis_token_cache_common_module_phase1.md`](./2026-06-05_kis_token_cache_common_module_phase1.md)

### 우선순위 이유
- 지금 당장 장애는 아니지만, KIS 관련 운영 안정성의 중기 핵심 기술부채다.

---

### 7. 운영일 상태 관리(`operations_day_runs`) — `완료`

### 목표
- 운영 대시보드가 “추정 상태”가 아니라 DB 기반 운영일 상태를 보여주게 만든다.

### 현재 상태
- 1차 저장 경로는 완료
- latest 조회 API도 완료
- `summary_json`에 snapshot/fill-sync/recovery health 구조화도 완료
- 운영 대시보드 `Scheduler Status` 카드 연결도 완료
- `by-date` / `history` 조회 API도 완료
- 관련 문서:
  - [`plans/2026-06-03_operations_day_runs_phase1.md`](./2026-06-03_operations_day_runs_phase1.md)
  - [`plans/2026-06-03_operations_day_runs_api_phase1.md`](./2026-06-03_operations_day_runs_api_phase1.md)
  - [`plans/2026-06-03_operations_day_runs_summary_json_health.md`](./2026-06-03_operations_day_runs_summary_json_health.md)
  - [`plans/2026-06-03_operations_day_runs_dashboard_status_card.md`](./2026-06-03_operations_day_runs_dashboard_status_card.md)
  - [`plans/2026-06-04_operations_day_runs_history_api.md`](./2026-06-04_operations_day_runs_history_api.md)

### 세부 작업 상태
- [x] `summary_json` 내부 command health 세분화 완료
  - [`plans/2026-06-04_operations_day_runs_command_health_granularity.md`](./2026-06-04_operations_day_runs_command_health_granularity.md)
- [x] readiness / 장중 검증 결과와 `operations_day_runs history`를 직접 연결 완료
  - [`plans/2026-06-04_operations_day_runs_validation_summary_link.md`](./2026-06-04_operations_day_runs_validation_summary_link.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `10`

### 우선순위 이유
- 비거래일/장종료/운영중 상태를 더 명확히 표시할 수 있어 operator 혼선을 줄인다.

---

### 8. 장 운영 세션 정보 수집/저장 — `완료`

### 목표
- 휴장/조기종료/특수 세션 정보를 정식 데이터로 보유하고 운영 정책에 반영한다.

### 현재 상태
- `market_sessions` latest 조회 API는 이미 있음
- `market_sessions` 날짜별 단건 조회 / 기간 history 조회도 완료
- `market_sessions.reason_code` 구조화 저장도 완료
- `market_sessions.reason_metadata` 구조화 저장도 완료
- `session_events`도 `run_date` 기준 drill-down 가능
- 관련 문서:
  - [`plans/2026-06-03_market_sessions_history_api.md`](./2026-06-03_market_sessions_history_api.md)
  - [`plans/2026-06-03_market_sessions_reason_code_structuring.md`](./2026-06-03_market_sessions_reason_code_structuring.md)
  - [`plans/2026-06-03_session_events_run_date_drilldown.md`](./2026-06-03_session_events_run_date_drilldown.md)
  - [`plans/2026-06-08_market_sessions_reason_metadata_structuring.md`](./2026-06-08_market_sessions_reason_metadata_structuring.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `7`

### 세부 작업 상태
- [x] `market_sessions` latest / by-date / history API 정비 완료
- [x] `reason_code` 구조화 저장 완료
- [x] `reason_metadata` 구조화 저장 완료
- [x] `session_events` run-date drill-down 완료
- [x] `market_sessions`와 readiness / next-trading-day 상태 직접 연결 완료

---

### 9. KIS 기본종목정보 instrument master 적재/갱신 — `완료`

### 목표
- 종목 메타데이터를 KIS 기준으로 더 안정적으로 관리한다.

### 세부 작업 상태
- [x] 정규화된 KIS master CSV 기반 기본종목정보 수집 파이프라인 1차 완료
  - [`plans/2026-06-08_kis_instrument_master_sync_pipeline_phase1.md`](./2026-06-08_kis_instrument_master_sync_pipeline_phase1.md)
- [x] instrument master 갱신 정책
  - [`plans/[POLICY] kis_instrument_master_update_policy.md`](./[POLICY]%20kis_instrument_master_update_policy.md)
  - KOSDAQ 종목은 `instrument master`에 적재되기 전에는
    Universe Selection에서 `unknown_instrument`로 제외되므로,
    시장 확장 전제 조건을 문서/코드에 명시했다.
- [x] snapshot/event mapping과의 정합성 확보
  - [x] recent `external_events` / `broker_fill_snapshots` unmapped symbol audit CLI
    - [`plans/2026-06-08_instrument_mapping_consistency_audit.md`](./2026-06-08_instrument_mapping_consistency_audit.md)
  - [x] unmapped symbol summary inspection API
    - [`plans/2026-06-08_instrument_mapping_consistency_summary_api.md`](./2026-06-08_instrument_mapping_consistency_summary_api.md)
  - [x] snapshot sync unknown-instrument 오류를 mapping summary와 연결
    - [`plans/2026-06-11_instrument_mapping_snapshot_sync_error_link.md`](./2026-06-11_instrument_mapping_snapshot_sync_error_link.md)
  - [x] unmapped symbol auto-seed / placeholder instrument 생성 정책
    - [`plans/2026-06-11_placeholder_instrument_policy.md`](./2026-06-11_placeholder_instrument_policy.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8`

### 우선순위 이유
- symbol / market / 이름 / 활성상태의 authoritative source가 강화되면 universe, fill history, event mapping 품질이 같이 올라간다.

### KOSDAQ 확장 후속 우선순위

현재 판단 기준:

- `instrument master` 미등록 종목이 `unknown_instrument`로 제외되는 경계는 유지하는 것이 맞다.
- `core universe가 active KRX 전체를 그대로 먹는다`는 과거 문제 제기는 현재 구현 기준으로는 상당 부분 완화됐다.
  - 현재는 `approved core universe seed` 기반으로 축소되어 있다.
- `market overlay가 항상 알파벳 순 50개만 본다`는 진단도 현재 기준으로는 일부만 유효하다.
  - 현재는 KIS ranking seed 우선, fallback pre-pool 보조 구조다.
- 따라서 KOSDAQ 확장의 실제 선결과제는 `시장 구분이 보존된 instrument master 적재`와
  `적재 이후 운영 경로 실측`이다.

#### 9-a. KOSPI/KOSDAQ 통합 instrument master CSV 확보 및 장전 배치 연결 — `최우선`

- 목표
  - 장이 열리는 날 장전 시점에 KOSPI/KOSDAQ 구분이 보존된 CSV로
    `instrument master`를 자동 갱신한다.
- 이유
  - master가 비어 있으면 Universe Selection 단계에서 그대로 탈락하므로,
    이 단계가 없으면 이후 KOSDAQ 확장은 모두 무의미하다.
- 완료 기준
  - scheduler에서 거래일 `07:50 KST`에 instrument master sync가 1회 실행된다.
  - 입력 CSV가 실제로 KOSDAQ row를 포함하고, `market_code`가 `KOSDAQ`로 보존된다.
- 현재 진행 상태
  - [x] `sync_kis_instrument_master.py`가 `market_code=KOSDAQ`를 보존하는 적재 경로를 가진다.
  - [x] `ops-scheduler`에 거래일 `07:50 KST` 1회 실행 경로를 연결했다.
  - [x] 원본 CSV 여러 개를 `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`로 합치는
    정규화 전처리 스크립트와 scheduler 선행 실행 경로를 추가했다.
  - [x] 운영 원본 CSV 입력 경로와 보관 경로를 코드로 고정했다.
    - 입력: `data/instrument_master/source/kospi_master.csv`
    - 입력: `data/instrument_master/source/kosdaq_master.csv`
    - 정규화 출력: `data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv`
    - 원본 보관: `data/instrument_master/archive/<YYYY-MM-DD>/...`
  - [x] csv 미존재 / sync 실패 시에는 `done` 처리하지 않고 다음 tick에 재시도하도록 보정했다.
  - [x] scheduler summary/runtime에 `instrument_master_sync` 상태와 기본 CSV 경로를 노출한다.

#### 9-b. KOSDAQ master 적재 후 universe/feature 경로 실측 — `상`

- 목표
  - KOSDAQ row가 적재된 뒤 실제 운영 경로가 깨지지 않는지 확인한다.
- 점검 범위
  - Universe Selection에서 등록된 KOSDAQ 종목이 `unknown_instrument`로 잘못 차단되지 않는지
  - `signal_feature_snapshot_input` 생성이 `KOSDAQ` market을 수용하는지
  - decision loop / preview API / coverage summary에서 시장 코드가 일관되게 보이는지
- 이유
  - instrument master 적재만 되고 후속 배치/판단 경로가 `KRX` 고정이면
    운영상 부분 실패가 발생한다.
- 현재 진행 상태
  - [x] Universe Selection에서 등록된 `KOSDAQ` 종목이 `unknown_instrument`로 잘못 차단되지 않는
    경로를 테스트로 재확인했다.
  - [x] `generate_signal_feature_snapshot_input.py`가 `market=KOSDAQ` universe row를
    그대로 수용하는 경로를 테스트로 고정했다.
  - [x] `run_decision_loop._read_trading_universe()`의 DB fallback이
    `KOSDAQ` market_code를 유지하는 경로를 테스트로 고정했다.
  - [x] `/instruments/trading-universe/preview` 응답이 `market=KOSDAQ`를 그대로 노출하는
    경로를 테스트로 고정했다.
  - [x] `/instruments/trading-universe/coverage-summary`에 `market_counts`를 추가해
    최근 판단 시장 분포(`KOSPI/KOSDAQ/KRX`)를 운영에서 직접 확인할 수 있게 했다.

#### 9-c. KOSDAQ 탐색 대상과 주문 가능 대상을 분리한 단계적 편입 — `상`

- 목표
  - KOSDAQ을 바로 `core universe`로 넣지 않고,
    `market discovery seed pool` 또는 `event overlay` 쪽부터 단계적으로 편입한다.
- 원칙
  - `탐색 풀`과 `주문 가능 풀`을 동일시하지 않는다.
  - KOSDAQ 확장은 우선 `탐색/랭킹/계측` 계층에서 시작하고,
    execution 안정성 검증 후 주문 가능 풀로 승격한다.
- 이유
  - 기대수익률 확대 기회는 크지만,
    현재 단계에서 즉시 주문 universe까지 넓히면 체결 리스크가 먼저 커진다.
- 현재 진행 상태
  - [x] `APPROVED_CORE_UNIVERSE_SYMBOLS`에서 KOSDAQ `090150` 직접 core 편입을 제거했다.
  - [x] `APPROVED_DISCOVERY_UNIVERSE_SYMBOLS`를 추가해 KOSDAQ 시범 종목은
    `market overlay fallback seed`로만 진입하도록 분리했다.
  - [x] 명시적 `core_universe=true`가 없으면 KOSDAQ discovery seed가
    `compose()` 결과의 주문 core에 포함되지 않는 테스트를 고정했다.
  - [x] KOSDAQ discovery seed가 `compose_with_diagnostics()`의
    `market overlay fallback seed`에는 포함되는 테스트를 고정했다.

#### 9-d. instrument master의 KOSPI/KOSDAQ/segment authoritative source화 — `중`

- 목표
  - `KRX`는 `exchange_code` 역할로 유지하되,
    `market_segment=KOSPI|KOSDAQ`와 `index_memberships`를 별도 기준 데이터로 승격한다.
  - `market_segment`, `segment`, `universe_segment`, 필요 시 `exchange_code`까지
    instrument master의 정식 기준 데이터로 고정한다.
- 이유
  - 현재 일부 로직은 allowlist와 metadata fallback에 의존한다.
  - 장기적으로는 `KOSPI100`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH`
    같은 segment 기준으로 탐색 풀과 core seed를 더 정교하게 분리해야 한다.
  - `KRX`를 바로 제거하면 기존 `position/order/snapshot/replay` FK와
    과거 운영 데이터 정합성이 깨질 수 있으므로,
    삭제보다 `역할 분리`가 먼저다.
- 현재 진행 상태
  - [x] `build_kis_instrument_master_sync_csv.py`가 normalized CSV에
    `exchange_code`, `metadata_market_segment`, `metadata_segment`,
    `metadata_universe_segment`, `metadata_index_memberships`를 함께 기록하도록 확장했다.
  - [x] source CSV의 `market_segment/segment/universe_segment` 별칭과
    `is_kospi200` / `is_kosdaq150` 플래그를
    `KOSPI100`, `KOSPI200`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH` 형태의
    membership metadata로 정규화하는 경로를 추가했다.
  - [x] 현재 원본 CSV에는 `KOSPI100`, `KOSDAQ50` 직접 플래그가 없으므로
    별도 원천 데이터 전까지는 자동 생성하지 않는 정책을 문서화했다.
  - [x] `sync_kis_instrument_master.py`가 위 필드들을 instrument metadata의
    authoritative source로 적재하는 테스트를 고정했다.
  - [x] `trading.instruments`에 `exchange_code`, `market_segment`
    정식 컬럼 추가 여부를 확정한다.
  - [x] `index_memberships`는
    `metadata 배열` fallback을 유지하되,
    `instrument_index_memberships` 별도 테이블을 authoritative history로 승격한다.
  - [x] universe / sell_guard / snapshot sync에서
    `market_code` 대신 `exchange_code + market_segment`를 우선 참조하는
    점진 이행 계획을 문서화한다.
    - UniverseSelection은 `instrument_index_memberships` 우선 / metadata fallback으로 전환
    - sell_guard, snapshot sync는 canonical instrument lookup 유지 상태에서 후속 전환
  - [x] 과거 `market_code='KRX'` row와 신규 `market_segment='KOSPI|KOSDAQ'`
    row를 중복 생성하지 않도록 canonical instrument 정책을 확정한다.

#### 9-f. 국내주식 instrument canonical model 정규화 — `상`

- 목표
  - `trading.instruments`에서
    `exchange_code`, `market_segment`, `index_memberships`의 역할을 분리해
    국내주식 canonical model을 정립한다.
- 원칙
  - `KRX`는 삭제하지 않고 `exchange_code` 의미로 유지한다.
  - `KOSPI`, `KOSDAQ`는 `market_segment`로 분리한다.
  - `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`은
    단일 bool 컬럼 난립 대신
    `index_memberships` authoritative source로 관리한다.
  - 기존 `position/order/snapshot` FK를 깨지 않는
    backward-compatible migration 순서를 유지한다.
- 권장 구현 순서
  - [x] 1차: `instruments`에 `exchange_code`, `market_segment` nullable 정식 컬럼 추가
  - [x] 1차: sync pipeline이 위 컬럼을 metadata가 아니라 정식 컬럼에도 적재
  - [x] 1차: `index_memberships`는 `metadata.index_memberships` 배열로 우선 적재
  - [x] 2차: UniverseSelectionService가
    allowlist보다 `market_segment + index_memberships + metadata flag`를 우선 사용
    - `core_universe` explicit flag를 최우선으로 유지
    - 그 다음 `index_memberships`와 `market_segment`로
      `KOSPI100/KOSPI200/KOSDAQ50/KOSDAQ150` seed를 판정
    - 코드 allowlist는 fallback 경로로만 유지
  - [x] 2차: `get_by_symbol_any_market()`류 조회는
    `exchange_code='KRX'` + canonical precedence를 사용하도록 정리
  - [x] 3차: `instrument_index_memberships` 시계열 테이블로 승격
  - [x] 3차: 그 이후에만 `market_code='KRX'` legacy 경로 축소 여부를 재검토
    - `sell_guard`는 이미 `get_by_symbol_any_market()` 기반 canonical lookup 사용
    - `kis_snapshot_sync`도 `get_by_symbol_any_market()`로 전환
    - 저장 canonical row는 `market_code='KRX'`를 유지하고,
      read path에서만 `exchange_code + market_segment` 우선 해석을 적용
  - [x] 3차: `trade_decisions.instrument_id`도
    canonical instrument row와 연결되도록 저장 경로를 보강
    - `DecisionOrchestratorService`가 `symbol + market` 우선,
      실패 시 `get_by_symbol_any_market()` fallback으로
      canonical instrument를 조회한 뒤
      `TradeDecisionEntity.instrument_id`를 채우도록 수정했다.
    - 기존 누적 데이터는 backfill을 수행해
      instrument master에 존재하는 건은 대부분 연결 완료했다.
    - 남은 `instrument_id IS NULL` 건은
      당시 `trading.instruments`에 row가 없던 종목(`000030`, `003410`, test symbol) 위주다.
  - [x] 4차 리팩토링 검토:
    `market_code='KRX'` canonical 저장 모델을 유지할지,
    아니면 `market_code='KOSPI'|'KOSDAQ'` + `exchange_code='KRX'`로
    더 직관적인 저장 모델로 재정의할지 결정한다.
    - 결론:
      현재 단계에서는 `market_code='KRX'` canonical 저장 모델을 유지한다.
    - 이유:
      `market_segment`와 `instrument_index_memberships`가
      이미 `KOSPI/KOSDAQ/지수편입` 의미를 분리하고 있고,
      반대로 저장 모델 전환은
      FK, replay, snapshot, order history, 테스트 fixture 수정 범위가 크다.
    - 근거 문서:
      [`plans/[DESIGN] instrument_market_code_canonical_model_decision.md`](./[DESIGN]%20instrument_market_code_canonical_model_decision.md)
    - 재검토는
      authoritative membership source 안정화와
      read path 전환이 충분히 끝난 뒤
      별도 migration/reconciliation 계획이 있을 때만 수행한다.
  - [x] 4차 리팩토링 검토:
    `KOSPI100`, `KOSDAQ50`, `KOSDAQ150` membership authoritative source를
    KIS 기본종목정보 CSV 외 별도 원천으로 보강한다.
    - 현재 원본 CSV는 `is_kospi200=True/False`, `is_kosdaq150=False`만 제공해
      `KOSPI200`만 직접 생성 가능하다.
    - [x] KIS `FHPUP02140000` 연동 경로를 추가해
      `KOSPI100`, `KOSPI200` 등 지수/업종 코드 카탈로그를
      KIS 기준으로 조회/덤프할 수 있게 했다.
      - 메서드:
        `KISRestClient.get_index_category_quotes()`
      - 보조 스크립트:
        `scripts/export_kis_index_category_catalog.py`
      - 단, 이 TR은 `구성종목 목록`이 아니라 `지수/업종 전체시세 목록`이므로
        membership authoritative source로 직접 사용하지 않는다.
    - [x] `FHPUP02140000` dump를
      `index_membership_seed` 운영 검증 자료로 연결하는
      보조 절차를 추가했다.
      - `scripts/validate_kis_index_membership_catalog.py`가
        export 결과(`json/csv`)를 읽어
        seed CSV의 membership code가
        `코스피 100`, `코스피 200`, `코스닥 50`, `코스닥150`
        alias와 매칭되는지 자동 점검한다.
      - 이 절차는 구성종목 authoritative source를 생성하는 것이 아니라,
        seed 파일 provenance와 코드 오기입을
        운영자가 장전/장후에 빠르게 검증하기 위한
        보조 안전장치다.
    - `KOSPI100`, 실제 `KOSDAQ150` 구성종목은
      별도 지수 구성종목 원천 파일 또는 승인 리스트 확보가 필요하다.
    - 2026-06-24 운영 업로드 원천
      (`kospi100_constituents.csv`, `kospi200_constituents.csv`,
      `kosdaq150_constituents.csv`)을
      `index_membership_source_manifest.json`로 묶어
      실제 authoritative source package 반영을 완료했다.
    - 반영 경로는
      `scripts/run_index_membership_source_package_pipeline.py`
      + `--replace-membership-code-snapshot` 플래그를 사용해
      membership code 단위 stale active row까지 함께 종료한다.
    - 실측 결과 현재 active membership은
      `KOSPI100=100`, `KOSPI200=200`, `KOSDAQ150=150`이다.
    - `KOSDAQ50`은 현재 운영 원천 파일이 없으므로
      지원 코드만 유지하고 실제 active set은 비워둔다.
    - [x] 중첩 membership 해석 규칙을 추가했다.
      - 원본 membership 집합은 삭제하지 않고 유지한다.
      - 대신 Universe/Decision/AI 프롬프트에서 공통으로
        `primary_index_membership`을 파생해 사용한다.
      - 현재 우선순위는
        `KOSPI100 > KOSDAQ50 > KOSPI200 > KOSDAQ150 > 기타`
        순이다.
    - [x] 외부 authoritative source package 수용 경로를 추가했다.
      - `scripts/build_index_membership_seed_from_source_package.py`
      - `data/instrument_master/source/index_membership_source_manifest.example.json`
      - 외부 원천은 membership별 `symbol` CSV 묶음 + manifest로 받고,
        이를 seed CSV로 정규화한 뒤
        기존 import/validation 절차로 연결하도록 운영 경로를 고정했다.
    - [x] import 전 instrument master 해상도 검증과 runbook을 추가했다.
      - `scripts/validate_index_membership_seed_resolution.py`
      - `plans/[RUNBOOK] index_membership_source_package_apply.md`
      - 실제 반영 순서를
        `source package build -> catalog validation -> resolution validation -> import`
        로 고정하고,
        unresolved symbol / placeholder symbol을
        import 전에 차단할 수 있게 했다.
    - [x] 통합 파이프라인 실행기를 추가했다.
      - `scripts/run_index_membership_source_package_pipeline.py`
      - 외부 원천 반영 시
        `source package build -> catalog validation -> resolution validation -> import`
        4단계를 하나의 명령으로 순차 실행하고,
        어느 단계에서 실패했는지 바로 식별할 수 있게 했다.
    - [x] 운영 보조 경로로
      `index_membership_seed.csv` import 스크립트와 템플릿을 추가했다.
      - 스크립트: `scripts/import_instrument_index_membership_seed.py`
      - 템플릿: `data/instrument_master/source/index_membership_seed.example.csv`
      - 기본 동작은 기존 active membership과 `merge`,
        `--replace-listed-symbols` 지정 시 listed symbol만 authoritative overwrite
      - import contract를 강화해
        허용 membership code를
        `KOSPI100`, `KOSPI200`, `KOSDAQ50`, `KOSDAQ150`
        로 고정하고,
        `source_name`, `source_ref`, `as_of_date`, `note`
        provenance 컬럼을 함께 저장하도록 보강했다.
      - 같은 symbol에 대해 provenance가 다르거나
        지원하지 않는 membership code가 들어오면
        import를 즉시 실패시켜
        잘못된 운영 seed 파일이 조용히 적재되지 않게 했다.
  - [x] 4차 운영 정리:
    `trade_decisions.instrument_id`가 비어 있던 잔여 종목
    (`000030`, `003410`, `TEST` 등)은
    canonical placeholder row 보강 + backfill로 정리했다.
    - `seed_placeholder_instruments_from_mapping_gaps.py`가
      `trade_decisions.instrument_id IS NULL` 심볼도
      mapping gap source로 인식하도록 확장했다.
    - placeholder row는 `exchange_code`, `market_segment`,
      `metadata.index_memberships`를 함께 가질 수 있도록 보강했다.
    - 운영 DB 기준 `trade_decisions.instrument_id IS NULL`은 `0건`까지 정리됐다.
  - [x] 후속 운영 정리:
    placeholder canonical row로 남아 있는 심볼을
    실제 instrument master row로 언제/어떻게 치환할지
    별도 정리한다.
    - [x] app 컨테이너에도 `./data:/app/data` 마운트를 추가해
      `index_membership_seed.csv` 같은 원천 파일을
      수동 배치/운영 스크립트가 컨테이너 내부에서 직접 읽을 수 있게 보완했다.
    - `sync_kis_instrument_master.py`가
      동일 `symbol + market_code='KRX'` canonical row를
      authoritative KIS master 데이터로 **승격(promote)** 하도록
      정책을 확정했다.
    - 이 승격 경로는 `instrument_id`를 유지하므로
      기존 `trade_decisions`, `signal_feature_snapshots`,
      `order_requests` 등 FK 참조를 깨지 않는다.
    - placeholder metadata
      (`placeholder`, `placeholder_source`, `canonical_master_pending`)는
      authoritative master metadata로 교체되고,
      같은 sync cycle에서
      `instrument_index_memberships` active row도 함께 동기화된다.
    - 관련 테스트로
      placeholder row가 실제 master row로 승격되며
      membership table까지 함께 갱신되는 케이스를 고정했다.
- 우선순위 이유
  - universe selection, sell guard, snapshot sync가
    동일 symbol의 다중 market row에 흔들리지 않게 만드는 기반 작업이다.
  - `최대 기대수익률`을 위해 KOSDAQ/segment 확장을 하더라도
    먼저 canonical instrument model이 안정돼야 한다.

#### 9-e. market overlay seed 품질의 장중 실측 및 보정 — `중`

- 목표
  - 현재의 `KIS ranking seed 우선 + fallback pre-pool` 구조가
    실제 장중에 KOSDAQ 하이알파 후보를 충분히 포착하는지 실측한다.
- 점검 항목
  - seed source별 후보 수
  - quotes requested / received
  - filtered out 수
  - 최종 overlay capture rate
- 이유
  - 현재 구조는 과거의 “알파벳 순 고정” 문제를 일부 해소했지만,
    seed 품질이 낮으면 기대수익률 확대 효과가 제한될 수 있다.
- 현재 진행 상태
  - [x] `GET /instruments/trading-universe/preview`의
    `market_overlay_diagnostics`에 기본 count 계측
    (`seed_pool_source`, `seed_pool_count`, `quotes_requested_count`,
    `quotes_received_count`, `filtered_out_count`,
    `scored_candidate_count`, `added_count`)이 노출되도록 유지했다.
  - [x] 장중 실측용 비율 지표
    (`quote_success_rate`, `filter_pass_rate`, `scored_capture_rate`)를 추가해
    운영자가 raw count를 직접 계산하지 않고도 seed 품질을 즉시 판단할 수 있게 했다.
  - [x] preview API와 `UniverseSelectionService.compose_with_diagnostics()` 테스트에
    위 계측 필드를 고정했다.

---

## P2 — 정책/전략 계층의 구조화 작업

이 범주는 당장 운영 장애보다 덜 급하지만, 시스템을 “작동하는 도구”에서 “확장 가능한 트레이딩 엔진”으로 끌어올리려면 반드시 필요하다.

이 영역은 `plan_docs/agents/01_agent_inventory_and_status.md`에서
**Planned**로 남아 있는 agent 축을 실제 구현 단위로 옮기는 작업이다.

### P2 공통 원칙

`plan_docs/agents/02_agent_target_shapes.md` 기준:

- `Market Regime`, `Strategy Selection`은 hybrid 가능
- `Universe Selection`, `Signal`, `Portfolio`, `Order Construction`은 deterministic backbone이 우선
- `AI Compliance`는 해석 보조일 수 있지만 최종 차단은 deterministic validator가 맡아야 함
- `Model Monitor`는 운영 모니터링/오프라인 평가 서비스로 보는 것이 맞음

### 10. Universe Selection Agent 분해 — `진행중`

### 핵심
- instrument master와 trading universe 분리
- core / held_position / event_overlay / market_overlay 합성
- liquidity filter와 market-driven overlay 정식화

### 세부 작업 상태
- [x] `UniverseSelectionService` 기반 deterministic composition 경로 정착
- [x] `source_type` / `inclusion_reason`를 포함한 trading universe preview inspection API 추가
  - [`plans/2026-06-12_trading_universe_preview_api.md`](./2026-06-12_trading_universe_preview_api.md)
- [x] `source_type`별 decision → order 전환 현황 coverage summary API 추가
  - [`plans/2026-06-13_trading_universe_coverage_summary_api.md`](./2026-06-13_trading_universe_coverage_summary_api.md)
- [x] trading universe preview에 `market_overlay` 진단 정보 추가
  - `enabled/skipped_reason/quotes_requested_count/quotes_received_count/added_count` 등 운영 확인용 수치 노출
- [x] `market_overlay` 전용 funnel inspection API 추가
  - 최근 판단 건수 / 주문 전환 건수 / decision_type 분포 / order_status 분포 / 최근 샘플 확인 가능
  - [`plans/2026-06-14_market_overlay_funnel_api.md`](./2026-06-14_market_overlay_funnel_api.md)
- [x] market_overlay 실운영 편입/효과 장중 실측
  - `evaluate_market_overlay_runtime_validation.py`로 preview/decision/order/bottleneck stage를 1회 평가 가능
  - 결과를 `operations_day_runs.summary_json.market_overlay_runtime_validation`에 적재 가능
  - [`plans/2026-06-14_market_overlay_runtime_validation_cli.md`](./2026-06-14_market_overlay_runtime_validation_cli.md)
- [x] universe selection 결과의 운영 UI 연계
  - 운영 대시보드에 `Universe Selection / Market Overlay` 패널 추가
  - [`plans/2026-06-14_universe_selection_ops_dashboard_panel.md`](./2026-06-14_universe_selection_ops_dashboard_panel.md)
- [x] manual watchlist/override 계층의 운영 정책 확정
  - `manual`은 기본 비활성 / watchlist 용도 / cap·filter·submit gate 우회 없음
  - preview query + decision loop env 기반의 최소 입력 경로 추가
  - [`plans/2026-06-14_manual_watchlist_override_policy.md`](./2026-06-14_manual_watchlist_override_policy.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `28`
- [`plans/[POLICY] trading_universe_policy_v1.md`](./[POLICY]%20trading_universe_policy_v1.md)
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

### 정책 대비 현재 불일치 요약

- 현재 `core universe`는 정책 권고인 `KOSPI100` / 내부 승인 대형주 리스트가 아니라
  `active KRX 전체`를 그대로 사용하고 있다.
- `Operational Eligibility Filter`는 정책 요구 대비 약하다.
  - 현재 공통 필터는 사실상 `unknown/inactive/tick_size` 위주다.
  - `iscd_stat_cls_code`, `low volume`, 운영 금지 리스트, 브로커 미지원, 정보 불완전 차단이
    공통 계층으로 닫혀 있지 않다.
- 정책상 강제 포함 대상인
  `미체결/정합성 확인 필요 주문`, `reconcile_required`, `recent_order_context`
  계층이 아직 universe composition에 반영되지 않았다.
- `market_overlay`는 정책상 “core 밖의 장중 강한 흐름 종목 탐지” 역할이어야 하나,
  현재 구현은 `core pre-pool` 내부 quote 평가에 가깝다.
- `inclusion_reason=kospi200_core`는 실제 구현(`KRX active core`)과 불일치한다.

### 우선순위별 수정안

#### 10-a. Core Universe 정의를 정책 기준으로 축소/명시화 — `완료`

- 목표
  - `core universe`를 `KRX active 전체`에서 분리한다.
  - v1 정책대로 `KOSPI100` 또는 `내부 승인 대형주 리스트`를 authoritative source로 만든다.
- 수정 방향
  - instrument master 적재 시 `KOSPI/KOSDAQ/segment` 구분값을 보존한다.
  - `UniverseSelectionService._add_core_universe()`는
    `market_code='KRX'` 전체 조회 대신
    `core watchlist` 또는 `segment + 시가총액/유동성 기준` 조회로 교체한다.
  - `INCLUSION_REASON_CORE`는 실제 구현과 일치하는 명칭으로 정리한다.
- 이번 작업 반영
  - `active KRX 전체` 대신 코드 관리형 `approved core universe seed` allowlist를 도입했다.
  - `INCLUSION_REASON_CORE`를 `approved_core_universe`로 변경했다.
  - `market_overlay` pre-pool도 동일한 core seed 기준으로만 구성되도록 맞췄다.
- 잔여 보완
  - 현재는 `segment`/`index_memberships` 정식 컬럼 또는 membership table이 없어
    allowlist 기반 운영 구현이다.
  - 후속으로 instrument master에
    `exchange_code`, `market_segment`, `index_memberships`
    authoritative source를 정식 적재해
    정책 테이블/DB authoritative source로 대체해야 한다.
- 우선순위 이유
  - 현재 `000227` 같은 저유동성/우선주가 `core`로 들어오는 가장 근본 원인이다.
  - universe 상류를 먼저 좁혀야 downstream trigger / AI / execution이 불필요하게 소모되지 않는다.

#### 10-b. 공통 Operational Eligibility Filter 강화 — `완료`

- 목표
  - 정책의 Layer 2를 universe 공통 deterministic pre-gate로 승격한다.
- 수정 방향
  - `core/event/manual/market` 전 계층에 동일하게 적용되는 공통 eligibility 필터 추가
  - 포함 항목
    - 거래정지/관리/감리/투자경고 계열 상태 차단
    - 내부 운영 금지 리스트 차단
    - 브로커 미지원/주문 불가 상품 차단
    - 종목 메타데이터 불완전 차단
    - 초저유동성/우선주/특수 share class 차단 여부를 정책으로 명시
  - 현재 `market_overlay` 전용인 `F4/F5` 중 공통화 가능한 부분은 universe 공통 계층으로 이동
- 이번 작업 반영
  - 공통 eligibility에 다음 항목을 추가했다.
    - `market != KRX` 차단
    - `asset_class != kr_stock` 차단
    - `exclude_from_trading_universe=true` metadata 차단
    - `broker_supported=false` metadata 차단
    - `instrument_complete=false` metadata 차단
    - `6자리 숫자 symbol`이 아닌 비표준 symbol 차단
    - 우선주/특수주 명칭 패턴 차단
  - 다만 `held_position`은 관리 대상 강제 포함 원칙 때문에 공통 필터를 우회하도록 유지했다.
- 잔여 보완
  - `iscd_stat_cls_code` 등 브로커 상태값의 공통 적격성 계층 승격은
    snapshot/quote 기반 데이터 결합 설계와 함께 추가 정리 필요하다.
- 우선순위 이유
  - `core`를 바로 못 바꾸더라도, execution 부적합 종목을 universe 단계에서 먼저 제거할 수 있다.
  - 저유동성 종목이 판단/주문까지 내려오는 구조적 누수를 줄이는 데 가장 즉효다.

#### 10-c. 정합성/미체결 관리 대상 강제 포함 계층 추가 — `완료`

- 목표
  - 정책상 강제 포함 대상인 `reconcile_required`, 미체결 관리, lineage 점검 종목을
    universe authoritative source에 포함한다.
- 수정 방향
  - 신규 source_type 후보
    - `order_context`
    - 또는 `reconciliation_overlay`
  - 포함 대상
    - open order 존재 종목
    - `reconcile_required` 주문 종목
    - 최근 체결/취소/실패 후 후속 상태 확인이 필요한 종목
  - cap 정책
    - held_position과 동일하게 일반 cap보다 우선 또는 별도 reserve를 둔다.
- 이번 작업 반영
  - `reconciliation_overlay` source type을 추가했다.
  - 다음 대상이 universe에 강제 포함되도록 연결했다.
    - `pending_submit/submitted/acknowledged/partially_filled/cancel_pending/reconcile_required` 등 활성 주문 종목
    - 진행 중 reconciliation run에 링크된 주문 종목
    - active blocking lock이 걸린 symbol
  - `reconciliation_overlay`는 held_position과 동일하게 일반 `max_cap`에서 제외되도록 처리했다.
  - deterministic trigger에서는 `reconciliation_overlay`를 신규 BUY eligibility에서 차단해
    “관리/상태확인 대상”이 신규 진입 후보로 오인되지 않게 했다.
- 잔여 보완
  - `recent_order_context`의 시간창/상태 범위는 아직 최소 구현 수준이다.
  - 후속으로 `최근 취소/실패 후 재확인 대상`, `broker truth pending` 같은 세분 source reason을
    추가 계측하는 작업이 필요하다.
- 우선순위 이유
  - 현재 정책 문서상 필수인데 구현 누락 상태다.
  - unknown state / reconciliation 우선 원칙과 직접 연결된다.

#### 10-d. Event Overlay 확장 및 중요도 정책 정합화 — `완료`

- 목표
  - 현재 `disclosure + severity=high` 단일 경로를 정책 수준으로 확장한다.
- 수정 방향
  - 최근 1~3영업일 의미 있는 공시 범위 반영
  - 내부 이벤트 정책상 우선 관찰 대상 타입 반영
  - `event_type`별 inclusion reason 표준화
  - 필요 시 OpenDART 외 이벤트 source와의 병합 우선순위 정리
- 이번 작업 반영
  - 기존 `disclosure + severity=high` 단일 경로를 확장해,
    정책상 의미 있는 event type taxonomy를 event overlay 승격 기준으로 반영했다.
  - 현재 반영된 주요 type:
    - `disclosure_material`
    - `disclosure_correction`
    - `earnings`
    - `capital_change`
    - `governance`
    - `trading_halt`
    - `investment_warning`
    - `management_issue`
    - `macro_release`
    - `sector_policy`
    - `broker_report_change`
    - `news_breaking`
  - legacy 저장값도 같이 흡수하도록 alias를 추가했다.
    - `disclosure`, `Y|disclosure`, `K|disclosure`, `N|disclosure`
      → `disclosure_material`
    - `seeded_news`, `Y|seeded_news`, `N|seeded_news`
      → `news_breaking`
  - severity만 보지 않고 `metadata.importance`도 함께 반영해,
    seeded news처럼 기본 severity가 `medium`인 소스도 중요도 승격 시
    event overlay에 편입될 수 있도록 맞췄다.
  - inclusion reason은 `high_importance_event:<normalized_event_type>` 형식으로 표준화했다.
- 잔여 보완
  - 현재는 repository contract 제약상 `list_by_type()` exact match 기반 구현이다.
  - 후속으로 `external_events` recent scan/query contract를 추가하면
    더 다양한 공시 subtype과 source를 한 번에 흡수하는 방향으로 개선할 수 있다.
- 우선순위 이유
  - 현재 event overlay가 지나치게 좁아 정책 문서의 전략 relevance filter 역할을 충분히 못 한다.

#### 10-e. Market Overlay를 “core pre-pool scoring”에서 “시장 발굴 overlay”로 재정의 — `완료`

- 목표
  - 정책의 Layer 4 의도대로, core 밖의 장중 강한 흐름 종목을 동적으로 편입한다.
- 수정 방향
  - KIS 순위분석/동급 랭킹 기반 seed pool 확보
  - 현재의 `core pre-pool -> quote batch` 경로는 보조 경로로 격하하거나 fallback으로 유지
  - `quotes_requested_count / received_count / filtered_out_count` 외에
    `seed_pool_source`, `seed_pool_count`, `overlay_capture_rate`를 추가 계측
- 이번 작업 반영
  - KIS REST client에 실전 전용 랭킹 seed helper를 추가했다.
    - `ranking_volume` (`FHPST01710000`)
    - `ranking_volume_power` (`FHPST01680000`)
  - `market_overlay`는 우선 `KIS ranking`에서 seed symbol을 수집하고,
    seed가 비었을 때만 `approved core universe` fallback pre-pool을 사용하도록 변경했다.
  - ranking/core 어느 경로로 오더라도 quote batch 전 단계에서
    universe 공통 eligibility를 다시 적용해 비표준/비지원/운영제외 종목을 미리 제거하도록 맞췄다.
  - trading universe preview 진단 정보에 다음 필드를 추가했다.
    - `seed_pool_source`
    - `seed_pool_count`
    - `overlay_capture_rate`
- 잔여 보완
  - 현재 ranking seed는 `거래대금 상위 + 체결강도 상위` 2개 소스만 사용한다.
  - 후속으로 `등락률 순위`, 시간대별 pacing, seed cache, overlay source별 품질 실측을 추가해
    실제 alpha discovery 품질을 더 정교화해야 한다.
- 우선순위 이유
  - 현재 구조는 정책 문서의 “market-driven alpha 후보 발굴”과 다르다.
  - 기대수익률 최대화 관점에서도 `market overlay`는 core 내부 재정렬이 아니라
    별도 alpha discovery lane이어야 한다.

#### 10-f. Universe 우선순위와 cap 정책의 source별 reserve 정교화 — `완료`

- 목표
  - held / reconciliation / event / market / manual / core 간 예산 충돌을 줄인다.
- 수정 방향
  - `core_cap` 외에
    - `event_overlay_cap`
    - `market_overlay_cap`
    - `reconciliation_overlay_reserve`
    같은 source별 reserve 검토
  - 시장 과열 구간에서 `market_overlay`가 `core/event`를 과도하게 침범하지 않도록 명시적 상한 정리
- 이번 작업 반영
  - `CompositionContext`에 다음 source-aware cap/reserve 필드를 추가했다.
    - `event_overlay_cap`
    - `reconciliation_overlay_reserve`
  - `market_overlay_cap`은 이미 overlay 생성 단계에서 적용되고 있으므로,
    이번 작업에서는 universe 최종 cap 단계와 충돌하지 않도록 현행 구조를 유지했다.
  - `UniverseSelectionService._apply_cap()`에 다음 규칙을 반영했다.
    - `held_position`은 계속 일반 `max_cap`에서 제외
    - `reconciliation_overlay`는 `reconciliation_overlay_reserve` 범위까지는
      일반 `max_cap`에서 제외
    - reserve를 초과한 `reconciliation_overlay`부터는 일반 `max_cap`을 소비
    - `event_overlay_cap`이 설정되면 event source가 해당 상한을 넘지 않도록 제한
    - 기존 `core_cap`은 그대로 유지
- 잔여 보완
  - 현재 `seen` 구조는 symbol당 최고 우선순위 source 하나만 유지하므로,
    `event_overlay_cap`에 의해 제외된 symbol이 자동으로 `core`로 복귀하지는 않는다.
  - 후속으로 “동일 symbol의 fallback source 복원”이 필요하면
    단일 `seen` 맵이 아니라 multi-candidate staging 구조로 바꿔야 한다.
- 우선순위 이유
  - 현재는 `core_cap`만 있고 나머지는 상대적으로 느슨하다.
  - source별 목표 역할을 유지하려면 cap도 source-aware 해야 한다.

#### 10-g. Instrument Status Snapshot 계층 도입 — `대기`

- 목표
  - `관리종목`, `거래정지`, `투자유의` 같은 종목 상태 fact를
    `instrument master`와 분리된 별도 snapshot 계층으로 정리한다.
- 핵심 판단
  - 오전 `instrument master sync`는 계속 CSV 기반 canonical source로 유지한다.
  - KIS `CTPF1002R`는 `trading.instruments` 대체 source가 아니라
    별도 `instrument_status_snapshots` fact source로 붙이는 것이 맞다.
  - universe exclusion과 submit 직전 compliance가
    같은 status fact를 읽도록 공통화해야 한다.
- 설계 문서
  - [`plans/[PLAN] instrument_status_snapshot_phase1.md`](./[PLAN]%20instrument_status_snapshot_phase1.md)
- 다음 구현 체크리스트
  - [x] `trading.instrument_status_snapshots` DDL / entity / repository 추가
  - [x] `rest_client.py`에 `CTPF1002R` (`search-stock-info`) client method 추가
  - [x] 장전 status snapshot batch script 추가
  - [x] `ops-scheduler`에 `instrument_master_sync` 후속 phase로 연결
  - [x] `UniverseSelectionService` 공통 eligibility가 status snapshot 우선 조회로 읽도록 전환
  - [x] `compliance_validator_v1`가 `blocked_reason_codes` fallback 대신
        status snapshot 기반 `관리종목/거래정지` hard block을 읽도록 확장
- 우선순위 이유
  - 현재 `restricted symbol` 차단은 프레임만 있고,
    실제 `관리종목` / `거래정지` authoritative 입력은 비어 있는 경우가 많다.
  - `10-b 공통 eligibility`의 잔여 보완과
    `11-c compliance validator`의 실전성 보강을
    동시에 닫는 연결 작업이다.

### 권장 구현 순서

1. `10-a` core universe 재정의
2. `10-b` 공통 eligibility filter 강화
3. `10-g` instrument status snapshot 계층 도입
4. `10-c` 정합성/미체결 강제 포함 계층 추가
5. `10-e` market overlay sourcing 재정의
6. `10-d` event overlay 확장
7. `10-f` source별 reserve/cap 정교화

### 구현 메모

- `10-a`와 `10-b`는 별도 작업으로 분리하지 말고 함께 설계하는 것이 좋다.
  - core를 좁히는 기준 자체가 eligibility 정책과 맞물리기 때문이다.
- `10-c`는 execution/reconciliation 경계와 직접 연결되므로
  universe selection 단독 작업이 아니라 order/reconciliation 문맥과 같이 검증해야 한다.
- `10-g`는 `instrument master`와 `status snapshot`의 역할을 분리하는 작업이다.
  - master는 CSV 기반 canonical source 유지
  - status는 `CTPF1002R` / 시세 응답 기반 fact snapshot으로 분리
  - 구현 순서는 `DB -> batch -> universe -> compliance`가 맞다.
- `10-e`는 KIS rate limit / market data budget 제약과 함께 설계해야 하며,
  paper 환경에서는 pacing/seed pool 축소/캐시 전략을 반드시 동반해야 한다.

### 11. Deterministic Risk / Compliance / Guardrail 계층 정리 — `진행중`

### 핵심 판단

- `AI Risk Agent`는 계속 **리스크 해석기**로 유지한다.
- `VaR`, exposure hard limit, daily loss hard limit는
  **전용 deterministic risk engine**이 계산/집행해야 한다.
- `AI Compliance Agent`는 **정책/규정 해석기**로 두되,
  최종 금지 집행은 deterministic validator가 맡아야 한다.
- 현재 여러 곳에 흩어진 hard stop 로직은
  장기적으로 **통합 Validator 계층**으로 일원화하는 것이 맞다.

### 현재 상태

- `risk_limit_snapshot`, `kill_switch_active`, `blocked_reason_codes`,
  `guardrail_evaluations` 저장 경로는 이미 존재한다.
- stale snapshot, duplicate buy/sell, low-liquidity, reconciliation lock 등
  실전 차단 로직도 이미 일부 구현돼 있다.
- 그러나 아래 3개는 아직 비어 있거나 분산 상태다.
  - 전용 deterministic VaR 엔진
  - 전용 AI Compliance Agent
  - Guardrail / Compliance Validator 일원화

### 권장 구현 순서

#### 11-a. Guardrail / Validator 일원화 — `완료`

- 목표
  - 현재 `decision_orchestrator`, `execution_service`, 기타 후단에 분산된 차단 로직을
    공통 validator 체계로 정리한다.
- 권장 방향
  - `ValidationContext`
  - `ValidationRule`
  - `ValidationResult`
  - `rule_set_version`
  - `blocking_rule_codes`
  - `rule_results`
  중심의 공통 계약을 만든다.
  - 규칙 묶음은
    `risk_validator`, `compliance_validator`, `execution_validator`
    식으로 분리한다.
- 이유
  - 이 정리가 먼저 없으면 VaR와 AI Compliance를 붙일 때
    새 fact와 새 의견이 또 다른 분산 차단 경로를 만들 가능성이 높다.
- 현재 진행 상태
  - [x] 공통 계약 1차 추가
    - `services.validators`
    - `ValidationContext`
    - `ValidationResult`
  - [x] `guardrail_audit`가
    legacy blocking guardrail helper를 유지한 채
    공통 validation result 저장 경로를 사용하도록 정리
  - [x] `execution_service`의 blocking guardrail 기록 경로가
    공통 validation contract를 사용하도록 연결
  - [x] 공통 contract와 legacy 호환 경로에 대한 서비스 테스트 추가
    - `tests/services/test_validators.py`
  - [x] `ValidationRule` / `RuleOutcome` / rule bundle 실행기 1차 추가
    - `run_validation_rules()`
  - [x] `submit_lane_gate`를 공통 validator bundle 기반으로 전환
    - `submit_lane_gate_v1`
    - scheduler submit lane 결과에 `validation_result` 부착
  - [x] scheduler gate guardrail 기록 경로를
    공통 `ValidationResult` 저장 흐름으로 정리
  - [x] `pre_ai_gate`를 공통 validation result 기반으로 승격
    - 기존 `(stop_reason, details)` 호환 API 유지
    - 내부 authoritative 결과는 `pre_ai_gate_v1 ValidationResult`로 생성
  - [x] pre-AI guardrail 기록 경로를
    공통 `ValidationResult` 저장 흐름으로 정리
  - [x] `decision_orchestrator` deterministic policy 경로에
    공통 validator 메타데이터 부착
    - `pre_ai_short_circuit`
    - `watch_candidate_guard`
    - `buy_eligibility_guard`
    - `source_policy_guard`
    - `ai_override_gate`
    - `OrderIntent.ai_backend_inputs`에
      `decision_policy_validator_v1` 메타데이터 누적
  - [x] 공통 `ValidationContext` 조립 helper 추가 및 적용
    - `build_validation_context()`
    - `guardrail_audit`
    - `run_decision_loop`
    - `execution_service`
  - [x] `execution_service` 주요 차단 경로에
    `risk_validator_v1` / `execution_validator_v1` bundle 메타데이터 명시
    - `buy_execution_liquidity_v1` → `risk_validator_v1`
    - `stale_snapshot_guard_v1` → `risk_validator_v1`
    - `sell_guard_v1` / `buy_duplicate_guard_v1`
      / `execution_probe_churn_guard_v1`
      / `broker_submit_outcome_v1`
      → `execution_validator_v1`
  - [x] `execution_service`의 일부 차단 경로를
    실제 `ValidationRule` 실행 bundle로 승격
    - `sell_guard_v1`
    - `buy_duplicate_guard_v1`
    - guardrail row에 `rule_outcomes` 저장
  - [x] `execution_service`의 추가 차단 경로를
    실제 `ValidationRule` 실행 bundle로 승격
    - `buy_execution_liquidity_v1`
    - `execution_probe_churn_guard_v1`
    - `stale_snapshot_guard_v1`
    - guardrail row에 `rule_outcomes` 저장
  - [x] `broker_submit_outcome_v1`도
    실제 `ValidationRule` 실행 bundle로 승격
    - guardrail row에 `rule_outcomes` 저장
  - [x] `execution_service` 내부 legacy guardrail 기록 wrapper 제거
    - execution 계층은 공통 `ValidationResult` 저장 흐름만 사용
- 잔여 보완
  - validator bundle 명칭은 도입됐지만
    `compliance_validator_v1`은 아직 미구현이다.
  - `risk_validator_v1` / `execution_validator_v1`은
    1차 적용이 끝났으므로,
    다음 단계부터는 `11-c`에서 compliance 축을 닫아야 한다.

#### 11-b. 전용 deterministic VaR 엔진 — `상`

- 목표
  - 현재 exposure 중심의 `risk_limit_snapshot`을
    실제 risk analytics fact 저장 계층으로 끌어올린다.
- v1 권장 범위
  - 계좌 총 VaR
  - 종목별 marginal risk contribution
  - concentration penalty
  - open order exposure 반영
- 연결 원칙
  - `AI Risk Agent`는 VaR를 직접 계산하지 않고 읽기만 한다.
  - validator는 VaR threshold를 authoritative하게 집행한다.
- Phase 1 설계 문서
  - [`plans/[PLAN] deterministic_var_engine_phase1.md`](./[PLAN]%20deterministic_var_engine_phase1.md)
- 체크리스트
  - [x] `risk_limit_snapshot` Phase 1 VaR 필드 확장
    - migration / entity / repository / API view 반영
    - `var_confidence_level`
    - `var_horizon_days`
    - `var_lookback_days`
    - `portfolio_var_1d`
    - `portfolio_var_1d_adjusted`
    - `largest_var_symbol`
    - `largest_var_contribution_pct`
    - `concentration_penalty_pct`
    - `var_status`
    - `var_reason_codes`
    - `symbol_var_json`
    - `symbol_marginal_contribution_json`
  - [x] `deterministic_var_engine.py` 구현
  - [x] 장전 snapshot/risk batch에 VaR 계산 연결
  - [x] `AI Risk Agent` read-only projection 연결
  - [x] `risk_validator_v1` VaR threshold 집행 연결
- 이유
  - `최대 기대수익률`을 추구하더라도
    tail risk와 concentration risk를 숫자로 닫는 기반이 먼저 필요하다.

#### 11-c. deterministic compliance validator 명시화 — `완료`

- 목표
  - AI가 없어도 반드시 차단해야 하는 compliance hard rule을
    문서와 코드에서 명확히 분리한다.
- v1 hard rule 예시
  - 금지 시장 / 금지 자산
  - 브로커 capability 미지원
  - 계좌 권한 불일치
  - 시장 세션상 주문 불가
  - 필수 필드 누락
  - restricted / blocked symbol
- 이유
  - 현재 일부는 구현돼 있으나,
    어디까지가 compliance hard rule인지 구조적으로 흐린 상태다.
- 현재 진행 준비 상태
  - [x] 선행 조건인 `11-a Guardrail / Validator 일원화` 완료
  - [x] Phase 1 설계 문서 추가
    - [`plans/[PLAN] deterministic_compliance_validator_phase1.md`](./[PLAN]%20deterministic_compliance_validator_phase1.md)
- 다음 구현 체크리스트
  - [x] `services/compliance_validator.py` 추가
  - [x] `compliance_validator_v1` rule set 초안 구현
  - [x] `source_policy_buy_blocked` / `policy_reconciliation_overlay_flat_buy_blocked`
        를 compliance bundle로 분리
  - [x] `execution_service` submit 직전 compliance hard rule 호출 지점 추가
  - [x] restricted symbol / invalid order shape / broker capability rule 1차 연결
  - [x] guardrail row에 `validator_bundle=compliance_validator_v1` 검증 추가
- 완료 메모
  - `decision_orchestrator`의 source policy 단락 경로와
    `execution_service`의 submit 직전 경로가
    동일한 `compliance_validator_v1` contract를 공유하도록 정리했다.
  - restricted symbol / invalid order shape / broker capability 차단은
    guardrail row의 `rule_outcomes`까지 포함해 테스트로 고정했다.

#### 11-d. AI Compliance Agent — `완료`

- 목표
  - deterministic validator가 닫지 못하는
    애매한 정책/규정/이벤트 맥락을 해석하는 AI 계층을 추가한다.
- 역할
  - `compliance_opinion`
  - `policy_flags`
  - `reason_codes`
  - `summary`
  - `opposing_evidence`
  형태의 structured output 생성
- 제약
  - 최종 금지/허용 authoritative 집행은 맡지 않는다.
  - hard validator보다 앞설 수 없다.
- 이유
  - 설명력과 정책 해석 품질은 높일 수 있지만,
    deterministic 경계가 닫히기 전에는 우선순위가 더 높지 않다.
- 체크리스트
  - [x] `AIComplianceOutput` schema 및 `Stub/Real AIComplianceAgent` 구현
  - [x] `DecisionAgentRunner`를 `EI -> AR -> AC -> FDC` 4-agent chain으로 확장
  - [x] `FDC` prompt에 `AI Compliance` read-only section 투영
  - [x] `trade_decision.decision_json` / `compliance_check_passed` projection 연결
  - [x] `execution_service` submit 직전 `compliance_validator_v1` 결과와 `AI Compliance` 의견의 합본 inspection view 정리
  - [x] `AI Compliance` 의견과 deterministic validator 결과의 불일치 계측 추가
  - [x] `AI Compliance` prompt / runtime smoke / 실운영 로그 기준선 문서화
    - [`plans/[RUNBOOK] ai_compliance_runtime_baseline.md`](./[RUNBOOK]%20ai_compliance_runtime_baseline.md)
- 완료 메모
  - `docker compose exec -T app python3 -B -m pytest -q tests/services/ai_agents/test_ai_compliance_prompt.py`
    기준 프롬프트 계약 테스트 `2 passed`
  - `docker compose exec -T app python3 -B -m pytest -q tests/api/test_inspection.py tests/services/test_decision_submit_pipeline.py -k 'compliance_inspection or ai_compliance_alignment or compliance_validator_v1'`
    기준 inspection / submit-time validator 회귀 `1 passed`
  - `2026-07-01` 기준 `KIS_LIVE_INFO_APP_KEY` 수정 후
    `.cache/kis_live_oauth_token.json`,
    `.cache/kis_disclosure_token.json` 재생성 및
    `KisHolidayProvider` / live disclosure 인증 복구를 실운영 로그로 확인했다.

### 권장 roadmap 배치

1. `11-a` Guardrail / Validator 일원화
2. `11-c` deterministic compliance validator 명시화
3. `11-b` deterministic VaR 엔진
4. `11-d` AI Compliance Agent

### 근거 문서

- `plan_docs/agents/03_risk_role_boundaries.md`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/detailed_design/01_system_architecture.md`
- `plans/[ANALYSIS] var_compliance_guardrail_implementation_path.md`

---

### 12. Signal Agent 분해 — `진행중`

### 핵심
- 기술/수급/모멘텀/변동성 점수의 deterministic backbone 구축
- fast/slow layer score 분리
- 최근 `n개월` 시세를 기반으로 한 기술지표/추세 feature를 장전 판단 입력으로 정착

### 추가 구현 메모
- 장중에 원시 시세를 길게 AI에 넣는 대신, 새벽 또는 장후 배치로 최근 `n개월` 시세를 수치 feature로 미리 계산해 DB에 저장한다.
- 예시 feature:
  - 이동평균(5/20/60/120)
  - 이격도
  - RSI
  - ATR
  - 변동성 percentile
  - 기간 수익률(`1M/3M/6M`)
  - 거래량/거래대금 급증률
- 장 시작 전 decision loop / AI 판단은 이 구조화 수치를 읽어서 사용하도록 한다.
- 목적:
  - AI prompt 토큰 사용량 절감
  - 장중 계산 부하 감소
  - replay/backtest 가능한 deterministic signal backbone 강화
- 구조 리팩토링 관점에서 남은 핵심은
  `feature를 prompt input으로만 쓰는 상태`에서
  `deterministic trigger / candidate 생성 계층`으로 승격하는 것이다.
  관련 분석은
  [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)
  를 기준 문서로 사용한다.
- 다음 설계/구현 기준은
  [`plans/[DESIGN] deterministic_trigger_engine_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_engine_v1.md)
  이다.

### 추가 우선 반영 항목

#### 12-a. 상대 거래량/거래대금 급증률 feature의 deterministic 승격 — `완료`

- 배경
  - 절대 거래대금 상위만으로는 이미 큰 종목 위주로 후보가 고정되기 쉽고,
    장중에 새로 강해지는 종목을 늦게 포착한다.
- 반영 방향
  - 기존 `거래량 급증률`을 단순 참고 feature가 아니라
    `WATCH / BUY_CANDIDATE` 생성의 핵심 deterministic backbone으로 승격한다.
  - 우선 도입 대상
    - `당일 거래량 / 최근 20일 평균 거래량`
    - `당일 거래대금 / 최근 20일 평균 거래대금`
    - 필요 시 `체결강도`, `단기 수익률`, `변동성 조정 점수`와 결합
  - 적용 위치
    - `signal_feature_snapshot` 장후/새벽 배치 계산
    - `deterministic_trigger_engine`의 eligibility / ranking / top-k candidate projection
- 이번 작업 반영
  - `signal_feature_snapshot`에 다음 필드를 추가했다.
    - `average_turnover_20d`
    - `turnover_surge_ratio`
  - signal backbone 계산 시
    - `최근 20일 평균 거래대금`
    - `당일 거래대금 / 최근 20일 평균 거래대금`
    을 함께 계산하도록 보강했다.
  - `volume_confirmation` 점수는 이제
    `volume_surge_ratio`와 `turnover_surge_ratio`를 함께 반영한다.
  - `deterministic_trigger_engine`의 BUY eligibility에
    `eligibility_low_relative_activity` 차단을 추가해
    상대 활동성이 너무 낮은 종목은 신규 진입 후보에서 제외하도록 했다.
  - `deterministic_trigger_engine`의 entry/ranking score에
    relative activity bonus를 추가해
    거래량/거래대금 급증 종목이 `WATCH / BUY_CANDIDATE` 상단으로 더 빨리 올라오도록 맞췄다.
  - inspection/API에도 신규 필드를 노출하도록 연결했다.
- 잔여 보완
  - 현재는 일봉 배치 기준의 상대 급증률만 반영했다.
  - 후속으로 live quote의 `acml_vol`, `acml_tr_pbmn`과 결합한
    장중 intraday relative activity 계측/랭킹으로 확장할 필요가 있다.
- 우선순위 이유
  - 기대수익률 관점에서 가장 직접적인 개선축이며,
    universe를 무리하게 넓히지 않고도 “새로 주도주가 되는 종목”을 조기 포착할 수 있다.
  - 현재 진행 중인 `Signal Agent 분해` 및 `feature 기반 deterministic trigger` 강화와
    정확히 같은 방향의 작업이다.

#### 12-b. Market Discovery Pool의 조건부 확장 준비 — `완료`

- 배경
  - 정책 문서상 `market-driven overlay`는 core 밖의 하이알파 후보 탐지가 목적이며,
    장기적으로는 KOSDAQ/중소형 성장주까지 탐색 범위를 넓힐 필요가 있다.
- 반영 방향
  - 즉시 주문 universe를 넓히는 것이 아니라,
    `탐색 풀`과 `주문 가능 풀`을 분리하는 구조를 우선 유지한다.
  - 후속으로 instrument master에 `KOSPI/KOSDAQ/segment`를 정식 적재한 뒤,
    `market discovery seed pool`에 한해 다음 후보군을 단계적으로 편입 검토한다.
    - `KOSDAQ 150`
    - `거래대금 상위 후보군`
  - 단, 편입 조건은 공통 eligibility와 별도 liquidity gate를 통과하는 경우로 제한한다.
- 이번 작업 반영
  - `UniverseSelectionService`에 `market discovery seed pool` 판단 helper를 추가했다.
  - 현재는 다음 metadata가 있는 경우에 한해
    core seed 외 종목도 `market_overlay` fallback seed 후보로 편입될 수 있도록 준비했다.
    - `market_discovery_pool=true`
    - `market_segment` / `segment` / `universe_segment` in
      `KOSPI100`, `KOSDAQ150`, `KOSPI_LARGE`, `KOSDAQ_GROWTH`
  - 이 경로는 `market_overlay`의 fallback seed pool에만 적용되며,
    `core universe`나 즉시 주문 가능 풀을 직접 넓히지는 않는다.
  - 즉, 현재 단계에서는 “탐색 범위 확장 준비”만 반영하고,
    주문/판단 안정성 경계는 유지했다.
- 우선순위 이유
  - KOSDAQ/중소형 탐색 자체는 기대수익률 확대 여지가 있지만,
    현재 단계에서 곧바로 주문 universe까지 넓히면 체결 리스크와 운영 복잡도가 더 빨리 커진다.
  - 따라서 `feature 기반 ranking backbone` 정교화 이후의 차상위 과제로 두는 것이 합리적이다.

#### 12-c. 기대수익률 중심 보유기간 / Churn 제어 리팩토링 — `완료`

- 배경
  - 장중 실측 기준 일부 종목에서
    `BUY -> REDUCE/SELL -> BUY -> REDUCE/SELL`이
    짧은 간격으로 반복되는 churn 패턴이 확인됐다.
  - 특히 `reconciliation_overlay`와 `held_position`이
    동일 종목에서 번갈아 진입/축소를 정당화하는 구조는
    `최고 기대수익률`보다 거래비용과 노이즈를 키울 가능성이 높다.
- 설계 기준 문서
  - [`plans/[DESIGN] expected_return_holding_horizon_and_churn_control_refactor.md`](./%5BDESIGN%5D%20expected_return_holding_horizon_and_churn_control_refactor.md)
- 핵심 방향
  - `source_type`를 단순 label이 아니라
    `허용 action envelope`로 승격한다.
  - `reconciliation_overlay`는
    flat 상태 신규 BUY source가 아니라
    상태 관리/관찰 source로 제한한다.
  - actionable decision은
    `expected_return_bps`, `net_expected_value_bps`,
    `final_trade_score`, `minimum_required_edge_bps`
    를 갖는 `expected value anchor`를 필수로 한다.
  - 동일 종목의 `SELL/REDUCE -> BUY`,
    `BUY -> REDUCE/SELL`에는
    `cooldown + feature/event 변화 + edge 개선`을 함께 요구하는
    hysteresis를 도입한다.
  - `1주 시장가 probe`가 churn을 만드는 조합은
    submit 전 hard guard로 차단한다.
- 세부 작업 상태
  - [x] `reconciliation_overlay` flat 신규 BUY 전면 차단
  - [x] pre-submit 잔존 주문이 `reconciliation_overlay`로 오인 편입되는 경로 차단
    - `DRAFT`, `VALIDATED`, `PENDING_SUBMIT` 상태는
      장중 active overlay source에서 제외했다.
    - prior-day `DAY + PARTIALLY_FILLED + SELL` 잔존은
      현재 보유 수량이 0이면
      universe compose 단계에서 stale residual로 건너뛴다.
    - after-hours post-submit sync에서
      위 residual 주문을 `expired`로 terminalize 하는 경로를 추가했다.
  - [x] `services.source_policy` action envelope helper 추가
  - [x] actionable decision의 expected value 필수 anchor 강제
    - `services.expected_value_gate`를 추가해
      actionable decision에 대한
      `expected_return_bps`, `expected_downside_bps`,
      `net_expected_value_bps`, `final_trade_score`,
      `minimum_required_edge_bps` 1차 anchor를 공통 계산하도록 정리했다.
    - `AIDecisionInputs`에 expected value 필드와
      `expected_value_gate_passed`, `expected_value_gate_reason_codes`
      계약을 추가했다.
    - `decision_factory`가 위 필드를
      `trade_decisions` row와 `decision_json.expected_value_gate`
      에 함께 저장하도록 반영했다.
    - `build_submit_order_request_from_decision()`는
      actionable decision이라도 expected value anchor가 비어 있거나
      gate가 false이면 submit request를 만들지 않도록 강제했다.
  - [x] `edge_after_cost_bps` 계산/저장 경로 추가
    - `services.expected_value_gate`가
      `estimated_round_trip_cost_bps`,
      `slippage_buffer_bps`,
      `edge_after_cost_bps`
      를 1차 deterministic 규칙으로 계산하고,
      `edge_after_cost_bps < minimum_required_edge_bps`
      인 actionable decision은 gate를 false로 내리도록 연결했다.
    - `AIDecisionInputs`와 pre-AI short-circuit / subprocess fallback 경로에도
      위 세 필드를 함께 주입해,
      AI 경로와 deterministic fallback 경로의 contract를 맞췄다.
    - `decision_json.expected_value_gate`에
      after-cost edge와 비용 추정 필드를 저장하고,
      submit translation은 해당 필드가 비어 있으면
      actionable request를 생성하지 않도록 강화했다.
  - [x] same-symbol reentry cooldown 1차 추가
    - `pre_ai_gate`에
      `same_symbol_reentry_cooldown`을 추가해,
      `core/event_overlay/market_overlay`의
      no-position 신규 BUY 후보가
      최근 `SELL/REDUCE/EXIT` 주문 직후에는
      AI 호출 전 deterministic하게 차단되도록 반영했다.
    - 최근 sell order 수,
      직전 held-position sell decision type/시각,
      직전 anchored position quantity,
      직전 `signal_feature_snapshot_id`
      를 details로 함께 남겨
      이후 `signal_feature_snapshot_id` 변화 기반 hysteresis 확장에
      바로 이어질 수 있게 했다.
  - [x] BUY 직후 SELL/REDUCE cooldown 1차 추가
    - `services.pre_ai_gate.evaluate_held_position_skip_reason()`에
      최근 same-symbol BUY order + 최근 same-symbol BUY/APPROVE 판단 +
      보유수량 감소 없음 조건을 추가해,
      조기 `held_position` 위험축소 SELL 경로를
      `held_position_recent_buy_sell_cooldown`으로 pre-AI skip 하도록 반영했다.
    - 최근 buy order 수,
      직전 buy decision type/시각,
      직전 anchored position quantity,
      직전 `signal_feature_snapshot_id`
      를 details에 함께 남겨,
      다음 단계의 `signal_feature_snapshot_id` 불변 reverse-trade 차단과
      자연스럽게 이어지도록 정리했다.
  - [x] `signal_feature_snapshot_id` 불변 상태 reverse trade 차단
    - `services.pre_ai_gate`가 현재 종목의 최신
      `signal_feature_snapshot_id`를 조회해,
      직전 BUY/SELL 판단에 앵커된
      `signal_feature_snapshot_id`와 동일하면
      일반 cooldown 대신
      `reverse_trade_same_signal_feature_snapshot`
      reason code로 pre-AI 차단하도록 반영했다.
    - `BUY -> SELL/REDUCE`와
      `SELL/REDUCE -> BUY`
      두 방향 모두에 대해
      `current_signal_feature_snapshot_id`,
      직전 anchor id,
      unchanged 여부를 details에 남겨
      이후 `event novelty` / `edge_after_cost_bps` 개선 조건 추가 시
      그대로 재사용할 수 있게 정리했다.
  - [x] `quantity=1` 신규 BUY probe churn guard 추가
    - `services.execution_service`에
      `execution_probe_churn_guard_v1`를 추가해,
      최종 submit 직전
      `quantity=1` 신규 BUY를
      일반 규칙이 아니라 예외 규칙으로만 허용하도록 반영했다.
    - `reconciliation_overlay + BUY + quantity=1`은
      `overlay_single_share_buy_blocked`,
      최근 same-symbol SELL 직후 1주 BUY는
      `reverse_trade_single_share_blocked`,
      저가치/고변동 risk-off 1주 BUY는
      `probe_churn_single_share_blocked`
      으로 guardrail audit까지 남기도록 정리했다.
    - `core/event_overlay`의
      `edge_after_cost_bps >= 35`
      는 1차 high-edge 예외 규칙으로 허용해
      핵심 기대수익률 기회까지 같이 막지 않도록 했다.
  - [x] `symbol_trade_states` 테이블 설계/도입
    - 신규 migration
      `db/migrations/0044_add_symbol_trade_states.sql`
      를 추가해,
      `account_id + instrument_id` 기준
      심볼 단위 authoritative 상태 캐시 테이블을 도입했다.
    - 저장 컬럼은
      `state`, `holding_profile`, `position_quantity`,
      `last_entry/exit/reduce_at`,
      `minimum_hold_until`,
      `reentry_cooldown_until`,
      `sell_cooldown_until`,
      `last_signal_feature_snapshot_id`,
      `last_decision_context_id`,
      `last_reason_codes`,
      `thesis_state_hash`,
      `metadata_json`
      까지 포함해
      다음 단계의 holding-profile 저장 경로를 바로 연결할 수 있게 준비했다.
    - repository 계층에도
      `SymbolTradeStateEntity`,
      `SymbolTradeStateRepository`,
      in-memory / postgres 구현,
      repository container wiring을 반영했다.
  - [x] `holding_profile`, `minimum_hold_until`,
    `reentry_cooldown_until` 저장 경로 추가
    - 신규 helper
      `services/holding_profile_policy.py`
      를 추가해
      `source_type + decision_type + time_horizon`
      기준으로
      `event_probe / event_swing / core_swing / position_trade / risk_reduction_only`
      프로필과
      `minimum_hold_until`,
      `sell_cooldown_until`,
      `reentry_cooldown_until`,
      `thesis_state_hash`
      를 결정론적으로 계산하도록 반영했다.
    - `build_trade_decision_entity()`가
      `decision_json.holding_profile_policy`
      에 해당 정책을 저장하도록 보강해
      replay / audit 시
      당시 보유기간 의도와 cooldown anchor를 같이 추적할 수 있게 했다.
    - `DecisionOrchestratorService._ensure_trade_decision()` 이후
      `symbol_trade_states`
      에
      `holding_profile`,
      `minimum_hold_until`,
      `reentry_cooldown_until`,
      `sell_cooldown_until`
      및 `entry_pending / reduce_pending / exit_pending`
      상태를 저장하도록 연결했다.
    - `assemble()`가
      `SubmitOrderRequest.metadata.holding_profile_policy`
      를 함께 실어 보내고,
      `ExecutionService`는 주문 생성 후
      `last_entry_order_request_id / last_exit_order_request_id`
      까지 `symbol_trade_states`에 연결하도록 반영했다.
  - [x] AI override 허용 범위를
    `eligibility + expected value + symbol state` 통과 시로 축소
    - `DecisionOrchestratorService._check_ai_buy_override_gate()`를 추가해
      deterministic trigger가 `buy_candidate=False`인 상황에서
      AI가 `APPROVE/BUY`로 승격하려면
      `eligibility_passed=True`,
      `expected_value_gate_passed=True`,
      `source_type` action envelope 허용,
      `symbol_trade_states`의 pending state 부재,
      `reentry_cooldown_until` 만료
      조건을 모두 통과하도록 강제했다.
    - 실행 infeasible 성격의 eligibility reason
      (`eligibility_low_average_volume`,
      `eligibility_low_turnover`,
      `eligibility_participation_rate_blocked`)
      이 남아 있으면
      AI override를 `WATCH/HOLD`로 강등하도록 연결했다.
    - 관련 테스트로
      `market_overlay`의 정상 override 허용 케이스와
      `symbol_trade_state reentry cooldown` 차단 케이스를 추가해
      override가 기대수익률 anchor와 상태기계 제약을 동시에 따르도록 고정했다.
- 남은 후속 범위
  - [x] `holding_profile`별 `earliest_reduce_at` / `earliest_reentry_at`를
        `symbol_trade_states`와 `decision_json.holding_profile_policy`에 함께 저장하고,
        실제 pre-AI / pre-submit 차단 규칙에서 authoritative하게 사용
    - `holding_profile_policy`에
      `earliest_reduce_at`, `earliest_reentry_at`를 명시적으로 추가했고,
      `pre_ai_gate`에서
      `holding_profile_earliest_reduce_guard`,
      `holding_profile_earliest_reentry_guard`
      로 먼저 차단한다.
    - submit 직전 `compliance_validator`에도
      같은 시각창 차단을 연결해
      조기 `SELL/REDUCE`와 조기 재진입 `BUY`를
      hard guardrail로 막도록 수렴했다.
  - [x] `SELL/REDUCE -> BUY` 재진입 조건을
        단순 cooldown이 아니라
        `signal_feature_snapshot_id 변화 + event novelty + edge_after_cost_bps 개선`
        3축 hysteresis로 승격
    - `pre_ai_gate`에서
      same-snapshot은 즉시 차단하되,
      신규 진입 이벤트 novelty가 있으면
      단순 reentry cooldown만으로는 막지 않고
      AI 단계까지 통과시킬 수 있게 완화했다.
    - `DecisionOrchestratorService`의
      `ai_override_gate`는
      `signal_feature_snapshot_id 변화`,
      `event novelty`,
      `edge_after_cost_bps`의
      세 축을 모두 통과해야만
      `WATCH -> BUY/APPROVE` 재진입 승격을 허용하도록 바꿨다.
    - 직전 `SELL/REDUCE`의
      `edge_after_cost_bps`를
      `symbol_trade_states.metadata_json`와
      `holding_profile_policy`에 같이 저장해
      이후 재진입 시 기대값 개선폭을 비교할 수 있게 했다.
  - [x] `BUY -> SELL/REDUCE` 축소 조건을
        `risk_off` 단독 허용이 아니라
        `thesis invalidation / edge collapse / downside shock / holding_profile breach`
        기반의 비대칭 문턱으로 재정의
    - `held_position`의 조기 `REDUCE/EXIT`는
      `earliest_reduce_at` 창이 살아있는 동안
      `edge collapse`,
      `downside shock`,
      `thesis invalidation`,
      `holding_profile breach`
      중 하나가 없으면 `WATCH`로 강등하도록
      `DecisionOrchestratorService`에
      `held_position_exit_hysteresis_gate`를 추가했다.
    - `symbol_trade_states.metadata_json`의
      직전 entry `edge_after_cost_bps`와
      최근 이벤트/리스크 신호를 같이 평가해
      단순 `risk_off` 또는 약한 노이즈만으로
      진입 직후 뒤집지 못하도록 정리했다.
  - [x] `symbol_trade_states.state`를
        `FLAT -> ENTRY_PENDING -> HELD_ACTIVE -> REDUCE_PENDING -> FLAT_COOLDOWN`
        상태기계로 승격하고,
        주문/체결/리컨실 결과를 기준으로 authoritative transition 정리
    - `services.symbol_trade_state_machine`를 추가해
      최신 보유수량 snapshot과 최신 주문 상태를 함께 읽어
      `held_active / reduce_pending / exit_pending / flat_cooldown / flat`
      으로 수렴시키는 deterministic 전이 규칙을 분리했다.
    - `snapshot_sync` 직후
      `symbol_trade_states` authoritative reconciliation을 실행해,
      의사결정/submit 시점에 남겨진 pending state가
      실제 포지션/주문 결과와 어긋난 채 장시간 잔존하지 않도록 정리했다.
    - 스크립트 경로(`sync_snapshots`, `run_snapshot_sync_loop`,
      `run_post_submit_sync_loop`)에도 같은 전이 경로를 연결해
      실운영 batch와 수동 sync가 동일한 상태기계를 타도록 맞췄다.
  - [x] `reverse_trade_hysteresis` 전용 service를 추가해
        orchestrator / pre_ai_gate / execution_service에 흩어진
        same-symbol reverse 판단을 하나의 deterministic contract로 수렴
    - `services.reverse_trade_hysteresis`를 추가해
      `signal_feature_snapshot_id 불변 차단`,
      `reentry cooldown`,
      `single-share reverse probe 차단`
      판단을 공통 계약으로 모았다.
  - [x] `expected value anchor`를
        신규 BUY뿐 아니라
        `REDUCE / EXIT`에도 강제하고,
        직전 exit 시점 대비 `edge_after_cost_bps` 개선 여부까지 비교 저장
    - `assemble()`가
      `SubmitOrderRequest.metadata.expected_value_anchor`
      에 현재/직전 entry·reduce·exit edge와 delta를 함께 싣고,
      `decision_factory`와 `symbol_trade_states.metadata_json`
      에 같은 anchor를 저장하도록 연결했다.
    - `build_submit_order_request_from_decision()`는
      `SELL / EXIT / REDUCE` actionable path에서
      `expected_value_anchor.anchor_passed=false`이면
      submit request를 만들지 않도록 강화했다.
    - 테스트로
      `held_position REDUCE submit 차단`,
      `decision_json expected_value_anchor 저장`,
      `reentry edge improvement delta 보존`
      을 고정했다.
  - [x] `holding_profile` / `reverse trade` / `probe churn` 결과를
        inspection API와 운영 대시보드에서 바로 볼 수 있게
        drill-down / attribution 노출 추가
    - `GET /trade-decisions` 응답에
      `decision_inspection` payload를 추가해
      `holding_profile`,
      `expected_value_anchor`,
      `reverse_trade`,
      `probe_churn`,
      `guardrail_attribution`
      을 운영용 요약으로 바로 노출한다.
    - 운영 대시보드의
      `Universe Selection / Market Overlay`
      freeze 표는
      오늘자 `trade-decisions`를 함께 조회해
      종목별 `최근 판단`,
      `holding profile`,
      `차단/가드레일 사유`
      를 같이 보이도록 확장했다.
    - 백엔드 inspection 테스트와
      프런트 production build까지 통과시켜
      응답 계약과 UI 연결을 검증했다.
  - [x] `holding_profile`별 성과,
        reverse-trade 차단 전후 churn 빈도,
        `edge_after_cost_bps` 대비 실제 보유기간/성과를 비교하는
        attribution 리포트 추가
    - `GET /performance-holding-profile-attribution`를 추가해
      `holding_profile`별
      decision / order / fill 전환,
      평균 `edge_after_cost_bps`,
      close-out 기준 평균 보유시간과 평균 수익률 proxy를 집계한다.
    - 같은 리포트에서
      `reverse_trade`,
      `probe_churn`,
      `holding_profile_guard`
      차단 빈도와
      계좌 기준 `opposite fill` churn 빈도를 함께 비교한다.
    - `edge_after_cost_bps`는
      `lt_0 / 0_10 / 10_20 / 20_35 / ge_35`
      bucket으로 나눠
      실제 close-out 보유시간/수익률 proxy와 비교 가능하게 만들었다.
    - API 계약 테스트와
      컨테이너 기준 `py_compile`
      검증까지 통과시켰다.
- 우선순위 이유
  - 현재의 짧은 보유기간은
    의도된 단기 전략 결과라기보다
    `심볼 상태 기억 부재`와 `충돌하는 source`의 결과일 가능성이 높다.
  - 이 항목은 단순 threshold 조정보다
    기대수익률 개선에 직접적인 리팩토링 축이다.

#### 12-d. Signal / Trigger 임계값 실증 검증 기반 재설계 — `완료`

- 배경
  - 2026-06-23 ~ 2026-07-01 실제 decision 데이터와
    KIS 일봉 후행 수익률을 결합해
    현재 `signal_feature` / `deterministic_trigger` 임계값을 검증했다.
  - 중복 cycle 왜곡을 줄이기 위해
    `symbol + trade_date`별 첫 decision만 평가했고,
    후행 수익률 계산이 가능한 2026-06-23 ~ 2026-06-30 표본을 사용했다.
  - 표본은 57개 symbol, 186개 symbol-day다.
- 실증 요약
  - `BUY_CANDIDATE`와 `entry_score >= 0.65`는 0건이었다.
  - `entry_score`와 T+3 수익률 상관은 약 `-0.21`로,
    현재 entry score가 후행 기대수익률을 충분히 설명하지 못했다.
  - `0.55 <= entry_score < 0.65` 구간은
    T+3 평균 수익률이 약 `-3.56%`로 나빠,
    `buy threshold`를 단순 하향하는 것은 적절하지 않다.
  - `eligibility_low_relative_activity` 차단군은
    T+3 평균 약 `-2.85%`로 현재 필터 유지가 타당하다.
  - `eligibility_source_type_blocked` 차단군은
    T+3 평균 약 `-4.36%`로 현재 차단 유지가 타당하다.
  - `eligibility_core_risk_off_ranking_blocked` 차단군은
    T+3 평균 약 `+3.16%`, hit rate 약 `72.7%`로
    과도 차단 가능성이 높다.
  - `event_overlay`는
    T+1 평균 약 `+3.40%`, T+3 평균 약 `+2.38%`,
    hit rate 약 `73.7%`로
    후보 전환 비중을 높일 근거가 있다.
- 설계 반영 원칙
  - `buy_candidate_threshold=0.65`는 즉시 낮추지 않는다.
  - `watch_candidate_threshold=0.45`는 상향 또는 top-k 후보화로 재설계한다.
  - `eligibility_core_risk_off_ranking_blocked`는 hard block보다
    penalty + 제한적 top-k 방식으로 완화 실험한다.
  - `event_overlay`는 별도 source bonus 또는 event top-k lane을 둔다.
- 다음 구현 체크리스트
  - [x] trigger proxy attribution용 repeatable script 또는 API 추가
    - `symbol + trade_date` 첫 decision 기준
    - T+1 / T+3 / T+5 후행 수익률
    - MFE / MAE
    - candidate / source_type / eligibility reason별 집계
    - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
  - [x] `watch_candidate_threshold=0.45`의 단순 threshold 방식을
        `WATCH top-k + minimum floor`로 대체하는 설계 확정
    - 확정 규칙
      - `top_k_buy = 3`
      - `buy_min_ranking_score = 0.55`
      - `top_k_watch = 8`
      - `watch_min_ranking_score = 0.50`
      - `watch_min_entry_score = 0.52`
      - `watch_min_percentile = 0.60`
    - 구현 책임
      - 단일 종목 score 계산은 `deterministic_trigger_engine`
      - batch top-k projection은 orchestrator 상위 helper
    - 기준 문서
      - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
  - [x] `eligibility_core_risk_off_ranking_blocked`를
        hard block에서 penalty 방식으로 바꾸는 실험 플래그 설계
    - authoritative mode
      - `hard_block_v1` 유지
    - shadow mode
      - `shadow_penalty_v1`
      - `adjusted_ranking_score = ranking_score - 0.08`
      - `shadow_min_score = 0.40`
      - `shadow_top_k_cap = 2`
    - metadata
      - `core_risk_off_experiment`
      - `shadow_would_pass`
      - `adjusted_ranking_score`
      - `shadow_signal_pass`
      - `shadow_activity_pass`
      - `shadow_strategy_pass`
    - 현재 반영 범위
      - `deterministic_trigger_engine.metadata`에 shadow experiment payload 추가
      - authoritative eligibility 동작은 변경하지 않음
    - 기준 문서
      - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
      - [`tests/services/test_deterministic_trigger_engine.py`](../tests/services/test_deterministic_trigger_engine.py)
    - 2026-07-01 실측 보정
      - `2026-06-01 ~ 2026-07-01` `symbol + trade_date` 첫 decision 기준
        `core_risk_off_ranking_blocked`는
        `T+3 평균 약 +8.29%`, `hit rate 100%`로
        완화 우선순위가 높다고 재확인되었다.
      - 반면 `risk_off_block` 전체와 `low_relative_activity`는
        유지가 타당했다.
      - 따라서 다음 구현은
        `shadow_penalty_v1` 유지가 아니라
        `shadow_topk_exception_v2`로 전환하는 것이 기준안이다.
      - 상세 설계:
        [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
  - [x] `core_risk_off_ranking_blocked` 완화 실험을
        `shadow_topk_exception_v2`로 재정의
    - `penalty-only` 대신
      `cycle-level top-k allow` 구조 채택
    - 전제조건
      - `core`
      - `risk_off + bearish_trend`
      - `overall >= 0.0`
      - `slow >= -0.05`
      - 허용 strategy
      - `max(volume_surge_ratio, turnover_surge_ratio) >= 1.10`
      - `ranking_score >= 0.22`
    - 상위 helper가 같은 cycle 내
      `top 2`만 `shadow_topk_selected=true`로 표시
    - 1차는 metadata/shadow만 반영
    - 기준 문서
      - [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
  - [x] `core_risk_off_topk_projection` batch helper 추가
    - 신규 권장 파일:
      `src/agent_trading/services/core_risk_off_topk_projection.py`
    - 정렬:
      `ranking_score DESC -> entry_score DESC -> symbol ASC`
    - output:
      `shadow_group_size`, `shadow_rank`, `shadow_topk_selected`
  - [x] cycle integration
    - `run_decision_loop.py` 또는 상위 orchestrator에서
      per-symbol deterministic trigger 계산 후
      batch projector 적용
    - 현재 반영:
      cycle 종료 후 `trade_decisions.decision_json`의
      `deterministic_trigger.metadata.core_risk_off_experiment`에
      `shadow_group_size`, `shadow_rank`, `shadow_topk_selected`를
      patch하는 shadow-only 후처리 경로 추가
    - shadow 단계에서는
      BUY eligibility를 바로 바꾸지 않음
  - [x] `shadow_topk_selected` attribution bucket 집계 추가
    - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
      출력 payload에 `core_risk_off_topk_items` 추가
    - bucket:
      `shadow_topk_selected / shadow_topk_candidate_only / shadow_not_candidate / inactive`
    - 기준 테스트:
      [`tests/services/test_trigger_proxy_attribution.py`](../tests/services/test_trigger_proxy_attribution.py)
  - [x] apply flag 단계 설계
    - `apply_core_risk_off_topk_v1`
    - `shadow_topk_selected=true` 후보만
      제한적으로 `risk_off_exception_eligible=true` 승격 검토
    - 기본값:
      disabled
    - 유지 원칙:
      `low_relative_activity`, `participation_rate`, `buy_threshold`는
      그대로 유지
    - 구현 위치 기준:
      cycle 종료 후 DB patch가 아니라
      deterministic prepass 경로에서 authoritative 적용
    - 상세 설계:
      [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
  - [x] `apply_core_risk_off_topk_v1` authoritative deterministic prepass 구현
    - `run_decision_loop.py`가 cycle 시작 시
      `core` symbol의 baseline deterministic trigger를 미리 계산
    - `project_core_risk_off_topk_exceptions(...)` 결과에서
      `shadow_topk_selected=true` symbol만
      same-cycle override 대상으로 선정
    - `SubmitOrderRequest.metadata.deterministic_trigger_override`를 통해
      `DecisionOrchestratorService.assemble()`에 주입
    - orchestrator는 override를 읽어
      deterministic trigger를 authoritative 재평가
    - 단, 완화 범위는 `core_risk_off_ranking_blocked`에 한정하며
      `low_average_volume / low_turnover / low_relative_activity / participation_rate`
      hard block은 그대로 유지
  - [x] `overall/slow floor` shadow 완화안 설계 고정
    - 기준 문서:
      [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md)
    - 목적:
      `top-k cap`이 아니라
      `shadow_signal_pass` 병목인
      `overall/slow floor`를
      bucket 단위로 실측 가능하게 분해
    - shadow bucket
      - `mild_relax`
        - `overall >= -0.10`
        - `slow >= -0.15`
      - `moderate_relax`
        - `overall >= -0.25`
        - `slow >= -0.25`
        - `entry_score >= 0.12`
        - `ranking_score >= 0.26`
      - `deep_negative`
        - 상기 미충족 구간
    - metadata 확장안
      - `shadow_floor_bucket`
      - `shadow_floor_relax_pass`
      - `shadow_floor_relax_reason_codes`
      - `shadow_floor_relax_entry_min`
      - `shadow_floor_relax_ranking_min`
    - 유지 원칙
      - authoritative `risk_off_exception_eligible` 경로는
        즉시 변경하지 않음
      - bucket A/B 분류만 먼저 저장
      - 후행 수익률 proxy와 churn 확인 후
        다음 단계 apply 검토
    - 현재 반영:
      - `deterministic_trigger.metadata.core_risk_off_experiment`에
        `shadow_floor_bucket`,
        `shadow_floor_relax_pass`,
        `shadow_floor_relax_reason_codes`,
        `shadow_floor_relax_entry_min`,
        `shadow_floor_relax_ranking_min` 저장
      - 장후 `analyze_trigger_proxy_attribution.py` 결과에
        `core_risk_off_floor_items` bucket 집계 추가
  - [x] `event_overlay` source bonus 또는 별도 `event_top_k` 후보 lane 설계
    - authoritative mode
      - `no_bonus_v1` 유지
    - shadow mode
      - `shadow_event_lane_v1`
      - `adjusted_ranking_score = ranking_score + 0.06`
      - `shadow_min_score = 0.56`
      - `shadow_entry_min_score = 0.54`
      - `shadow_top_k_cap = 2`
    - metadata
      - `event_overlay_experiment`
      - `base_eligibility_passed`
      - `adjusted_ranking_score`
      - `shadow_signal_pass`
      - `shadow_activity_pass`
      - `shadow_strategy_pass`
      - `shadow_would_pass`
    - 현재 반영 범위
      - `deterministic_trigger_engine.metadata`에 shadow event lane payload 추가
      - `risk_off` regime gate와 authoritative BUY eligibility 동작은 변경하지 않음
    - 기준 문서
      - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
      - [`tests/services/test_deterministic_trigger_engine.py`](../tests/services/test_deterministic_trigger_engine.py)
  - [x] 위 3개 변경안을 shadow mode로 먼저 돌려
        실제 BUY 후보 증가와 후행 proxy 개선 여부를 비교
    - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)에
      아래 shadow 비교 섹션을 추가했다.
      - `watch_projection_items`
      - `core_risk_off_shadow_items`
      - `event_overlay_shadow_items`
    - `WATCH top-k + minimum floor`는
      일자별 `ranking_score` 재정렬로
      `legacy_watch_only / legacy_and_shadow_watch / shadow_watch_only / neither_watch`
      bucket을 재구성한다.
    - `core_risk_off_experiment`, `event_overlay_experiment`는
      `shadow_would_pass / shadow_blocked / inactive` bucket으로
      후행 수익률 proxy를 비교한다.
    - 기준 문서
      - [`plans/[DESIGN] performance_attribution_for_trigger_and_override.md`](./%5BDESIGN%5D%20performance_attribution_for_trigger_and_override.md)
      - [`tests/services/test_trigger_proxy_attribution.py`](../tests/services/test_trigger_proxy_attribution.py)
    - 운영 반영
      - `ops-scheduler`가 장후 `signal_feature_batch` 완료 직후
        `after_market_trigger_proxy_attribution` 배치를 자동 실행한다.
      - 결과는
        `logs/trigger_proxy_attribution_YYYY-MM-DD.json`과
        `operations_day_runs.summary_json.trigger_proxy_attribution`에 남긴다.
  - [x] `core_risk_off_floor_diagnostics` 추가
    - 목적
      - `mild_relax / moderate_relax` 표본이 왜 0인지
        score 분포와 gate별 탈락 사유를 실측한다.
    - 출력 추가 대상
      - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
      - `core_risk_off_floor_diagnostics`
      - `overall_band_items`
      - `slow_band_items`
      - `moderate_gate_items`
      - `blocking_reason_items`
      - `bucket_path_items`
      - `samples`
    - row 단위 파생 필드
      - `shadow_overall_score`
      - `shadow_slow_score`
      - `shadow_entry_score`
      - `shadow_ranking_score`
      - `shadow_activity_pass`
      - `shadow_strategy_pass`
      - `overall_band`
      - `slow_band`
      - `moderate_gate_bucket`
      - `blocking_reason`
      - `bucket_path`
    - 코드 수정 기준
      - [`src/agent_trading/services/trigger_proxy_attribution.py`](../src/agent_trading/services/trigger_proxy_attribution.py)에
        diagnostic row / report helper 추가
      - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)에
        payload 적재 추가
      - [`tests/services/test_trigger_proxy_attribution.py`](../tests/services/test_trigger_proxy_attribution.py)에
        band / gate / blocking reason 경계 테스트 추가
      - [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py)에
        핵심 diagnostic count parser 보강
    - 현재 실측 결과
      - `2026-07-06`: `active_sample_count=21`, active 전부 `signal_window_miss`
      - `2026-07-07`: `active_sample_count=28`, active 전부 `signal_window_miss`
      - `blocking_reason` 주원인:
        `overall_below_mild_floor`
      - 결론:
        `entry / ranking / activity / strategy`보다
        `overall / slow` floor가 선행 병목
    - 판단 기준
      - `overall_band=mild_window` 표본은 있는데
        `mild_relax=0`이면 slow floor 또는 row 저장 누락 문제
      - `moderate_window` 표본은 있는데
        `moderate_gate_bucket`이
        `entry_below_0_12 / ranking_below_0_26 / activity_blocked / strategy_blocked`
        중 어디에 몰리는지로 다음 완화 순서를 결정
  - [x] `overall / slow floor shadow 완화안` v2 계측 추가
    - 목적
      - 현재 병목인 `overall_below_mild_floor`를
        소폭 완화했을 때
        `mild_relax / moderate_relax` 표본이 실제로 생기는지 관측
    - 적용 범위
      - authoritative 규칙은 유지
      - shadow diagnostics 전용 v2 bucket 추가
    - 기준안
      - `mild_relax_v2`
        - `overall >= -0.15`
        - `slow >= -0.15`
      - `moderate_relax_v2`
        - `overall >= -0.20`
        - `slow >= -0.25`
        - `entry_score >= 0.12`
        - `ranking_score >= 0.26`
        - `activity_pass = true`
        - `strategy_pass = true`
    - 보류 원칙
      - `slow` floor 동시 완화 금지
      - `entry / ranking / activity / strategy` 완화 선행 금지
    - 구현 기준
      - [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)
        metadata에 `shadow_floor_relax_v2_*` 추가
      - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
        v1 / v2 비교 섹션 추가
      - 실측 결과
        - `2026-07-06`: `v2` active `21건`, `mild_relax=0`, `moderate_relax=0`
        - `2026-07-07`: `v2` active `28건`, `mild_relax=0`, `moderate_relax=0`
        - historical row backfill을 적용해도
          `overall_below_mild_floor` 및 `overall_missing`이 주 병목으로 유지
  - [x] `overall floor shadow 완화안` v3 구현 및 장후 배치 반영
    - 목적
      - `slow`는 유지한 채 `overall`만 한 단계 더 완화했을 때
        `mild_relax / moderate_relax` 표본이 실제로 생기는지 추가 관측
    - 적용 범위
      - authoritative 규칙은 유지
      - shadow diagnostics 전용 v3 bucket 추가
    - 기준안
      - `mild_relax_v3`
        - `overall >= -0.20`
        - `slow >= -0.15`
      - `moderate_relax_v3`
        - `overall >= -0.25`
        - `slow >= -0.25`
        - `entry_score >= 0.12`
        - `ranking_score >= 0.26`
        - `activity_pass = true`
        - `strategy_pass = true`
    - 구현 기준
      - [`src/agent_trading/services/deterministic_trigger_engine.py`](../src/agent_trading/services/deterministic_trigger_engine.py)
        metadata에 `shadow_floor_relax_v3_*` 추가
      - [`src/agent_trading/services/trigger_proxy_attribution.py`](../src/agent_trading/services/trigger_proxy_attribution.py)
        `v3` bucket / diagnostics / backfill helper 추가
      - [`scripts/analyze_trigger_proxy_attribution.py`](../scripts/analyze_trigger_proxy_attribution.py)
        `v3` report / diagnostics payload 추가
    - 실측 결과
      - `2026-07-06`: `v3` active `21건`, `mild_relax=0`, `moderate_relax=0`
      - `2026-07-07`: `v3` active `28건`, `mild_relax=0`, `moderate_relax=0`
      - 활성 row 다수는 `overall_missing` 또는 `overall <= -0.25`에 머물러
        `v3` 완화만으로는 아직 표본 확장이 발생하지 않음
    - 다음 판단 기준
      - `2026-07-08` 이후 장후 데이터에서 `shadow_floor_relax_v3_bucket`이
        실제로 채워지는지 먼저 확인
      - 계속 `0건`이면 다음 병목은 floor 값 자체보다
        `feature snapshot missing` 또는 upstream score 생성 품질로 간주
  - [x] `signal_backbone_v1` 하방 편향 shadow 보정안 추가 — **`v2`(안 A+B)까지 진행,
        `v3`/`v4`는 후속 대기**
    - `2026-07-08` 기준 `v2`(momentum_3m_negative + below_sma60 완화) 코드/테스트
      마감 완료 → **관측 시작 상태**로 전환
      ([`[PLAN] core_risk_off_ranking_relaxation_phase1.md` §9.10 관측 1회차 기록](./%5BPLAN%5D%20core_risk_off_ranking_relaxation_phase1.md))
    - 회귀 테스트 107개 통과, 실제 `trading_db` 대상 `--dry-run` 산출물 검증 완료
    - 승격 기준 4개 항목은 아직 미충족 — 정규 장후 배치로 최소 1거래일 이상
      `shadow_overall_bucket_counts_v2` 관측 축적 필요
    - `v3`(변동성 패널티 완화), `v4`(weight 보정)는 `v2` 관측 결과 확인 전까지 미착수
    - `v5` 경계 구간 재분배 설계안 작성 완료
      - 근거 문서
        - [`[ANALYSIS] signal_backbone_slow_score_threshold_tuning_2026-07-09.md`](./%5BANALYSIS%5D%20signal_backbone_slow_score_threshold_tuning_2026-07-09.md)
      - 핵심안
        - `slow_momentum`
          - `<= -20% -> -0.8`
          - `(-20,-10] -> -0.55`
          - `(-10,-5] -> -0.30`
          - `(-5,-2] -> -0.15`
        - `slow_trend`
          - `<= -12% -> -0.8`
          - `(-12,-6] -> -0.50`
          - `(-6,-2.5] -> -0.25`
          - `(-2.5,-0.5] -> -0.10`
      - 실측 결론
        - `2026-07-08` 80건 기준 `deep_negative 54 -> 53`, `mild_negative 5 -> 13`
        - `2026-07-06 ~ 2026-07-08` active `core_risk_off` 20건은
          `moderate_negative` 이상으로 이동한 건수 `0건`
      - 다음 구현
        - `shadow_component_scores_v5` / `core_risk_off_floor_v5_report` 추가 후
          최소 3거래일 추가 관측
    - 목적
      - `feature snapshot` 입력 품질 문제가 아니라
        `score formula` 자체의 하방 편향이 병목인지 실측 기반으로 검증
    - 실측 근거
      - `2026-07-08` 장후 `80`종목 기준
      - `avg_overall_score ≈ -0.3847`
      - `avg_slow_score ≈ -0.4030`
      - `momentum_3m_negative`
        - `45건`
        - `overall` 직접 기여 평균 약 `-0.264`
      - `below_sma60`
        - `65건`
        - `overall` 직접 기여 평균 약 `-0.1665`
      - `volatility_elevated`
        - `33건`
        - `overall` 직접 기여 평균 약 `-0.1556`
      - `atr_expanded`
        - `51건`
        - `overall` 직접 기여 평균 약 `-0.1473`
    - 1차 적용 범위
      - authoritative score는 유지
      - shadow backbone variant만 추가
    - 구현 순서
      - `v2`
        - `momentum_3m_negative` 임계값/패널티 완화
        - `below_sma60` 임계값/패널티 완화
      - `v3`
        - `volatility_penalty` 완화 추가
      - `v4`
        - `slow / overall` weight 보정 추가
    - 세부 기준안
      - `momentum_3m_negative`
        - 현행 `<= -10% -> -0.8`
        - shadow `<= -15% -> -0.8`, `<= -5% -> -0.45`, `<= -2% -> -0.20`
      - `below_sma60`
        - 현행 `<= -5% -> -0.8`
        - shadow `<= -8% -> -0.8`, `<= -3% -> -0.45`, `<= -1% -> -0.20`
      - `volatility_penalty`
        - 현행 `vol>=4.5 -> -0.7`, `atr>=6.0 -> -0.5`
        - shadow `vol>=5.5 -> -0.55`, `atr>=7.5 -> -0.35`
      - weight
        - 현행 `slow=0.6/0.4`, `overall=0.55/0.45`
        - shadow `slow=0.5/0.5`, `overall=0.50/0.50`
    - 계측 필드
      - `shadow_signal_backbone_variant`
      - `shadow_slow_score_v2`
      - `shadow_fast_score_v2`
      - `shadow_overall_score_v2`
      - `shadow_component_scores_v2`
      - `shadow_reason_codes_v2`
    - 승격 기준
      - `non_negative + mild_negative` 표본 증가
      - `core_risk_off_floor_v3`의 `mild_relax / moderate_relax` 표본 생성
      - `T+1 / T+3` proxy 악화 없음
      - churn / low-liquidity 부작용 없음
    - 후속 우선순위 요약
      - `overall_missing`은
        구형 snapshot 참조 + 구형 component payload 문제로 확인되었고,
        snapshot feature 기반 `shadow v5` 재구성 fallback으로 분석 경로에서는 해소됐다.
      - 현재 실질 병목은
        active `core_risk_off` 표본이 전부 `deep_negative`로 남는
        `slow_score_v5` 하방 편향이다.
      - `deep_negative` 전체 완화는
        `inactive` 대비 후행 proxy가 더 나쁜 군을 허용하게 되므로
        `최고 기대수익률` 목표와 맞지 않는다.
      - 다음 단계는
        `slow_trend` 경계 구간만 shadow 완화 후보로 분리 계측하고,
        `slow_momentum`은 관측 유지 후 완화 여부를 뒤로 미루는 것이다.
      - `2026-07-06 ~ 2026-07-10` 재실측에서
        `shadow_relax_projection_candidate=5`, `selected=0`, `would_buy=0`, `submitted=0`으로 확인됐다.
        즉 현 시점 병목은 `submit` 이후가 아니라
        `shadow_topk_candidate` 진입 이전이며,
        후보 표본도 모두 `WATCH` 성격으로 남아 있었다.
      - 따라서 다음 우선 분석은
        `shadow_topk_candidate_miss` 하위 조건과
        `primary_candidate=WATCH` 고착 경로 분해다.
      - 후속 계측 결과
        active `core_risk_off` 35건의 `shadow_topk_candidate_gate_reason`은
        전부 `signal_both_floor_miss`로 집계됐다.
        즉 현재 미진입의 직접 원인은
        `ranking/activity/strategy`보다
        strict `overall/slow` 동시 미통과다.
      - `watch_primary_candidate_reason`은
        `watch_with_eligibility_block=35`,
        `watch_setup_but_ineligible=15`,
        `core_watch_path_only=5`로 나타났다.
        따라서 다음 단계는
        `overall/slow strict miss`와
        `buy eligibility 차단축`을 직접 연결해
        실제 `WATCH → BUY` 전환 가능성이 있는 좁은 구간만 추려야 한다.
      - 후속 계측 추가 후
        `eligibility_block_reason_primary_items`는
        `eligibility_core_risk_off_ranking_blocked=35`,
        `eligibility_risk_off_block=24`,
        `eligibility_low_relative_activity=20`,
        `eligibility_negative_overall_floor=13` 순으로 나타났다.
      - `shadow_signal_floor_block_path_items`는
        active 표본이 대부분
        `overall_fail|slow_fail|deep_negative|deep_negative|...`
        경로에 집중됨을 보여줬다.
        즉 다음 완화 검증은
        `ranking/activity` 일반 완화가 아니라
        `slow_trend` 경계 완화 shadow가
        실제 어떤 eligibility 차단축 감소로 이어지는지
        추적하는 방향이어야 한다.
      - `ops-scheduler` 운영 요약에도 이제
        `trend_moderate_candidate_count`,
        `trend_edge_deep_count`,
        `trend_deep_tail_count`,
        `shadow_relax_projection_selected_count`
        가 함께 남도록 보강했다.
      - active `core_risk_off` 재실측 기준
        `trend_moderate_candidate`는 2건 모두 `2026-07-10` 표본이라
        아직 `T+1 / T+3` 후행 proxy가 비어 있다.
        반면 `trend_edge_deep`는
        `trend_deep_tail` 대비 훨씬 덜 나쁜 수익률/MAE를 보였지만,
        현재 Task의 승격 대상은 `trend_moderate_candidate`이므로
        지금 바로 완화 판단을 내리면 안 된다.
      - 후속 장후 판단을 쉽게 하기 위해
        `active_slow_trend_relax_candidate_report`,
        `active_slow_trend_projection_items`
        를 diagnostics에 추가했다.
        이제 active 기준으로
        `trend_moderate_candidate`의
        `sample_count / T+1 / T+3 / candidate_count / selected_count`
        를 바로 확인할 수 있다.
      - 추가로
        `active_slow_trend_trade_date_band_items`,
        `active_slow_trend_trade_date_projection_items`
        를 붙여
        `2026-07-10|trend_moderate_candidate`
        코호트를 한 줄 bucket으로 직접 추적할 수 있게 했다.
      - 상세 후속 백로그:
        [`plans/[BACKLOG] core_risk_off_slow_floor_shadow_relaxation.md`](./%5BBACKLOG%5D%20core_risk_off_slow_floor_shadow_relaxation.md)
- 근거 문서
  - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
  - [`plans/[DESIGN] performance_attribution_for_trigger_and_override.md`](./%5BDESIGN%5D%20performance_attribution_for_trigger_and_override.md)
  - [`tests/services/test_trigger_proxy_attribution.py`](../tests/services/test_trigger_proxy_attribution.py)

### 세부 작업 상태
- [x] 순수 helper 기반 deterministic signal backbone 1차 추가
  - `services.signal_backbone`에 `PriceBar` / `TechnicalFeatureSnapshot` / `SignalScoreCard` 추가
  - 최근 일봉 기준 `SMA(5/20/60)`, `1M/3M 수익률`, `RSI(14)`, `ATR(14)%`, `20일 변동성`, `거래량 급증률` 계산
  - fast/slow layer 분리 score(`fast_score`, `slow_score`, `overall_score`)와 reason code 1차 규칙 추가
- [x] feature snapshot DB 저장 기반 1차 추가
  - `trading.signal_feature_snapshots` 테이블 migration 추가
  - `SignalFeatureSnapshotEntity` / repository contract / in-memory / Postgres 저장소 추가
  - 최신 snapshot 조회(`get_latest_by_instrument`) 및 이력 조회(`list_by_instrument`) 경로 추가
- [x] signal feature snapshot inspection API 추가
  - `GET /signal-feature-snapshots`
  - `GET /signal-feature-snapshots/latest`
  - 종목(`symbol + market + timeframe`) 기준으로 최신/이력 snapshot 조회 가능
- [x] 새벽/장후 배치 계산 경로
  - `SignalFeaturePipelineService` 추가
  - `build_signal_feature_snapshots.py` CLI로 JSON 일봉 입력 기반 계산/적재 가능
- [x] decision loop / AI prompt read-only 주입 경로
  - `DecisionOrchestratorService.assemble()`가 최신 `signal_feature_snapshot`을 로드
  - AI Risk / FDC prompt에 fast/slow/overall score, RSI, ATR, 수익률, reason code를 read-only로 주입
- [x] deterministic trigger / candidate 계층 1차 추가
  - `services.deterministic_trigger_engine`에 `DeterministicTriggerAssessment`,
    `assess_deterministic_triggers()` 추가
  - `signal_feature_snapshot + market_regime + strategy_selection + portfolio_allocation`
    기반으로 `WATCH / BUY_CANDIDATE / SELL_CANDIDATE / REDUCE_CANDIDATE`
    후보를 deterministic하게 생성
  - `AssembledContext.deterministic_trigger`에 주입하고
    AI Risk / FDC prompt에 read-only로 노출
  - `TradeDecisionEntity.decision_json.deterministic_trigger`에 1차 반영
- [x] candidate vs final decision 분리 저장 1차 추가
  - `TradeDecisionEntity.decision_json.candidate_vs_final`에
    `candidate_intent`, `final_intent`, `alignment_status`, `override_applied`
    를 기록해 deterministic candidate와 AI 최종 판단의 차이를 구조화
  - 향후 `override 효과 측정`, `candidate 분포 대비 최종 decision 분포 비교`의
    최소 분석 기반 확보
- [x] deterministic derivation stage 분리 1차 추가
  - `DecisionOrchestratorService` 내부에서
    `signal_feature_snapshot → market_regime → strategy_selection → portfolio_allocation → deterministic_trigger`
    계산을 `_derive_deterministic_context_components()` helper로 분리
  - 향후 `Context Assembly Stage` / `Deterministic Derivation Stage` /
    `AI Policy Stage` 분리의 첫 단계 구조 정리
- [x] prompt context projection 공통화 1차 추가
  - `services.ai_agents.prompt_context_projection`에
    signal / regime / strategy / portfolio / trigger 공통 렌더링 helper 추가
  - `Final Decision Composer`는 전체 deterministic context section을 공통 helper로 재사용
  - `AI Risk`는 별도 concentration 문맥을 유지하기 위해
    portfolio section만 제외한 공통 projection 경로를 사용
- [x] AI policy context view 분리 1차 추가
  - `AIPolicyContextView`를 추가해
    내부 조립용 `AssembledContext`와 AI 입력용 읽기 전용 뷰를 분리
  - `DecisionOrchestratorService`가
    `_build_ai_policy_context_view()`로 AI 입력 뷰를 명시적으로 조립한 뒤
    in-process / subprocess agent runner에 동일하게 전달
  - 향후 `policy input schema versioning`, `attribution`, `prompt contract 고정`
    작업의 최소 구조 경계 확보
- [x] after-market signal feature batch 자동화 1차 추가
  - `ops-scheduler`가 장 마감 후 배치 시각인 `20:10 KST` 이후
    `signal feature input 생성 → snapshot batch 적재`를 순차 실행
  - `generate_signal_feature_snapshot_input.py`가
    trading universe 기준 KIS 일봉을 조회해
    `data/signal_feature_snapshot_input.json`을 생성
  - `build_signal_feature_snapshots.py`가 같은 입력 파일을 읽어
    `signal_feature_snapshots` 테이블 적재를 수행
- [x] signal feature batch 운영 요약 노출 1차 추가
  - `operations_day_runs.summary_json`에
    `signal_feature_input` / `signal_feature_batch`의
    `last_error`, 입력 생성 집계(`universe_count`, `generated_count`, `error_count`)를 기록
  - `/market-sessions/operations-day/*` API에서 기존 `summary_json` 경로만으로
    장후 feature 배치 실패 원인을 바로 확인할 수 있게 정리
- [x] ops-scheduler runtime 식별 정보 노출 1차 추가
  - `operations_day_runs.summary_json.scheduler_runtime`에
    `script_path`, `python_bin`, `pid`,
    `signal_feature_batch_supported`, `signal_feature_batch_time`를 기록
  - 운영 중인 scheduler 프로세스가
    실제로 signal feature batch 지원 코드를 로드했는지
    DB 요약만으로 즉시 식별할 수 있게 정리
- [x] signal feature batch 적재 runtime bug 수정 및 전일 누락분 수동 적재
  - `build_signal_feature_snapshots.py`가
    `postgres_runtime()`의 `repositories` 경로를 직접 사용하도록 수정해
    운영 컨테이너에서 `db_pool` KeyError로 실패하던 문제를 제거
  - 전일(`2026-06-16`) 장후 누락분은
    `generate_signal_feature_snapshot_input.py` 수동 실행 후
    `signal_feature_snapshots`에 47건 적재까지 완료
  - 자동 배치 정상 동작 여부는
    오늘 `20:10 KST` 이후 `operations_day_runs.summary_json`과
    `signal_feature_snapshots` 적재 건수로 재확인 필요
- [x] signal feature after-market 배치 운영 안정화 / 리팩토링 2차
  - 배경
    - 2026-06-18~2026-06-19 실측 기준
      `signal_feature_snapshot` 장후 배치는
      `input import 실패`, `schema drift`, `거래대금 overflow`,
      `개별 row 실패가 batch 전체 transaction을 오염시키는 구조`
      문제를 순차적으로 드러냈다.
    - 현재는 hotfix와 수동 검증으로
      `배치 전체 붕괴` 가능성은 낮아졌지만,
      외부 KIS live 시세/일봉 API의 rate limit / 5xx 때문에
      일부 종목 누락 가능성은 여전히 남아 있다.
  - 권장 방향
    - 단순 retry 증설보다
      `universe freeze -> fetch stage -> persist stage -> failed-symbol tail-retry`
      구조로 리팩토링해
      운영 안정성, audit, replay, manual recovery를 함께 확보한다.
  - `P0`
    - [x] 장후 `20:10 KST` 배치의 대상 유니버스를 먼저 freeze 하고,
      이후 재시도/재실행 중에도 같은 대상 집합을 유지하도록 만든다.
      - `generate_signal_feature_snapshot_input.py`가
        `universe_freeze_runs` / `universe_freeze_run_items`를 우선 조회해
        기존 freeze가 있으면 재사용하고,
        없으면 새 freeze를 materialize 하도록 반영
    - [x] `universe freeze` PostgreSQL 스키마를 먼저 확정한다.
      - [x] `trading.universe_freeze_runs` 테이블 설계
      - [x] `trading.universe_freeze_run_items` 테이블 설계
      - [x] `signal_feature_batch_runs.universe_freeze_run_id` FK 연결 설계 및 구현
      - [x] `(business_date, freeze_purpose, freeze_sequence)` unique 정책 확정
      - [x] `(freeze_run_id, instrument_id)` unique 정책 확정
      - [x] `business_date`, `freeze_purpose`, `frozen_at`, `selection_version`,
        `selection_params_json`, `target_count`, `status` 필수 컬럼 확정
      - [x] item row의 `instrument_id`, `symbol`, `market_code`,
        `source_type`, `inclusion_reason`, `priority_score`, `rank`,
        `cap_bucket`, `metadata_json` 필수 컬럼 확정
      - [x] replay / manual rerun 시
        `same freeze run reuse`와 `new freeze run create` 기준 확정
    - [x] `signal_feature_snapshot_input` 생성 경로를
      `fetch 성공 row / fetch 실패 row / 대상 universe metadata`로 분리 기록한다.
      - 입력 JSON을 `signal_feature_input.v2` 구조로 확장해
        `universe_metadata`, `fetch_success_rows`, `fetch_error_rows`를 분리 저장
      - `build_signal_feature_snapshots.py`는
        신구 포맷을 모두 읽을 수 있게 backward-compatible 유지
    - [x] `generate_signal_feature_snapshot_input.py`에
      `rate limit`, `5xx`, `timeout`을 구분한 재시도 정책을 추가한다.
    - [x] 1차 본배치 후 실패 종목만 재시도하는
      `tail-retry` 실행 경로를 추가한다.
      - `generate_signal_feature_snapshot_input.py`에
        `--retry-from-input` 경로를 추가해
        기존 `signal_feature_input.v2`의 `fetch_error_rows`만 다시 조회하도록 반영
      - `run_ops_scheduler.py`가
        1차 `after_market_signal_feature_input` 완료 후
        `fetch_error_count > 0`이면
        `after_market_signal_feature_input_tail_retry` →
        `after_market_signal_feature_batch_tail_retry`
        순서로 동일 거래일 tail-retry를 자동 실행
      - 운영 요약은 primary + tail-retry 누적 기준으로
        `fetch_success_count`, `persist_success_count`, `final_missing_count`
        집계를 보도록 보강
    - [x] `operations_day_runs.summary_json`에
      `target_count`, `fetch_success_count`, `fetch_error_count`,
      `persist_success_count`, `persist_error_count`,
      `final_missing_count`, `failed_symbols_sample`
      를 남기도록 확장한다.
  - [x] 장후 실행 후
      `summary_json`과 `signal_feature_snapshots` 적재 건수를 대조하는
      운영 검증 절차를 문서화한다.
      - [`plans/[RUNBOOK] signal_feature_after_market_batch_validation.md`](./%5BRUNBOOK%5D%20signal_feature_after_market_batch_validation.md)
        문서에
        `operations_day_runs.summary_json` →
        `signal_feature_batch_runs` →
        `signal_feature_batch_run_items` →
        `signal_feature_snapshots`
        순서의 운영 판정 절차를 정리했다.
  - `P0-추가`
    - [x] decision loop도 `feature freeze`와 별개로 실시간 compose만 하지 않고,
      `intraday universe freeze`를 우선 anchor로 읽도록 확장한다.
      - 배경:
        현재는 `signal_feature` 장후 배치만
        `universe_freeze_runs` / `universe_freeze_run_items`를 사용하고,
        장중 `run_decision_loop`는 매 cycle마다
        `UniverseSelectionService.compose()`를 다시 호출한다.
        이 구조는 feature/audit/replay 경로와
        실제 장중 판단 경로의 universe 기준이 분리되는 문제가 있다.
      - 목표:
        `decision loop`, `feature batch`, `운영 진단`이
        가능한 한 동일한 universe anchor 개념을 공유하게 만든다.
      - [x] 1차:
        `decision loop intraday freeze` 목적값과 생성 시점을 확정한다.
        - 권장 `freeze_purpose`:
          `decision_loop_intraday`
        - 확정 생성 시점:
          scheduler가 장중 due 상태의 첫 `decision` task를 실행하기 직전
          1회 materialize / reuse
        - 같은 거래일/같은 목적 내에서는
          기존 freeze run 재사용을 기본값으로 한다.
      - [x] 1차:
        `run_decision_loop.py`에
        `latest freeze run 우선 -> compose fallback` read path를 추가한다.
        - `TRADING_UNIVERSE_SYMBOLS` env override는 여전히 최우선 유지
        - 그 다음 `universe_freeze_run_items(decision_loop_intraday)` 조회
        - 마지막 fallback만 `UniverseSelectionService.compose()`
      - [x] 1차:
        freeze 미존재 시 새 freeze를 materialize 할지,
        아니면 compose 결과를 1회성으로만 사용할지 정책을 고정한다.
        - 확정:
          freeze가 없으면 먼저 materialize 한 뒤
          그 결과를 decision loop가 읽는다.
        - 구현:
          `ops-scheduler`가 `decision_submit_gate` 직전에
          기존 freeze reuse를 먼저 시도하고,
          없으면 `UniverseSelectionService.compose()` 결과를
          `universe_freeze_runs` / `universe_freeze_run_items`에 저장한 뒤
          같은 거래일 anchor로 사용한다.
      - [x] 1차:
        decision cycle 요약과 audit 메타데이터에
        `universe_freeze_run_id`, `freeze_purpose`, `freeze_reused`
        를 남긴다.
        - 최소 범위:
          decision loop summary JSON
        - 추가 반영:
          per-symbol cycle JSON에도 같은 anchor를 남긴다.
        - 권장 확장:
          `decision_context` 또는 `trade_decisions.decision_json`
          에도 anchor 기록
        - 구현:
          `run_decision_loop.py`가
          `universe_anchor_source`, `universe_freeze_run_id`,
          `freeze_purpose`, `freeze_reused`를
          cycle result / aggregate summary metrics에 기록하고,
          `SubmitOrderRequest.metadata["universe_anchor"]`를 통해
          `trade_decisions.decision_json.universe_anchor`까지 전파한다.
      - [x] 2차:
        preview/ops API가
        현재 live compose 결과와
        현재 active intraday freeze 결과를 구분해서 보여주도록 확장한다.
        - 구현:
          `GET /instruments/trading-universe/preview` 응답에
          `active_intraday_freeze`,
          `active_intraday_freeze_comparison`를 추가해
          live compose 결과와 같은 거래일의
          `decision_loop_intraday` freeze 결과를 한 번에 비교할 수 있게 한다.
      - [x] 2차:
        재시작/장애 복구 시
        기존 intraday freeze 재사용,
        수동 새 freeze 생성,
        stale freeze 감지 기준을 runbook에 정리한다.
      - 구현:
        [`plans/[RUNBOOK] decision_loop_intraday_freeze_operations.md`](./%5BRUNBOOK%5D%20decision_loop_intraday_freeze_operations.md)
          문서에
          상태 확인 API,
          재기동 후 reuse 절차,
          수동 `ensure`,
          수동 `force-new`,
          hard stale / soft drift 판정 기준을 고정했다.
      - [x] 운영 버그 수정:
        재기동 후 stale `run_date`를 들고 있는 scheduler가
        잘못된 거래일 freeze를 재사용/생성하지 않도록
        intraday freeze materialize 시점에
        현재 `KST` 날짜로 run date를 재결정하게 수정했다.
      - [x] 실운영 검증:
        2026-06-25 장중 기준
        `decision_loop_intraday` freeze를 수동 materialize 한 뒤
        `ops-scheduler` 로그와
        `operations_day_runs.summary_json.decision_loop.metrics`
        에서
        `universe_anchor_source='intraday_freeze'`,
        `freeze_reused=true`,
        `universe_freeze_run_id` 반영까지 확인했다.
      - 구현 범위 고정:
        이번 후속 작업은
        `universe schema 추가`가 아니라
        기존 `universe_freeze_runs` / `universe_freeze_run_items`
        재사용을 전제로 한다.
        신규 핵심 범위는
        `decision loop read path`, `scheduler freeze materialization`,
        `audit anchor propagation`, `ops visibility` 4가지다.
  - `P1`
    - [x] `signal_feature_batch_runs`
      실행 단위 테이블 도입 여부를 확정하고 구현했다.
      - 실행 메타데이터:
        `business_date`, `universe_freeze_run_id`, `trigger_type`,
        `timeframe`, `feature_set_version`, `input_uri`,
        `target_count`, `fetch_success_count`, `fetch_error_count`,
        `persist_success_count`, `persist_error_count`,
        `skipped_count`, `final_missing_count`, `status`, `summary_json`
    - [x] `signal_feature_batch_run_items`
      종목 단위 상태 테이블 도입 여부를 확정하고 구현했다.
      - 종목별 상태:
        `persisted`, `computed`, `error`, `fetch_error`,
        `skipped_instrument_not_found`
      - `signal_feature_snapshot_id`, `snapshot_at`, `error_code`,
        `error_message`, `metadata_json`를 함께 저장
    - [x] file 기반 중간 산출물과 DB run-state 중
      어느 쪽을 authoritative source로 둘지 결정한다.
      - [x] freeze 이후의 authoritative source는
        file이 아니라 `universe_freeze_run_items`를 기본값으로 둔다.
      - [x] 실행 메타데이터 authoritative source는
        `signal_feature_batch_runs` /
        `signal_feature_batch_run_items`로 고정한다.
      - [x] 최종 feature payload authoritative source는
        `signal_feature_snapshots`로 고정한다.
      - [x] JSON 입력 파일은
        transport / tail-retry / 수동 재실행 artifact로만 취급하고
        audit 기준 source로 사용하지 않도록 정책 문서와 runbook에 반영했다.
    - [x] 동일 `(instrument_id, timeframe, snapshot_at, feature_set_version)` 기준
      idempotent re-run / upsert 정책을 확정하고 구현했다.
      - `signal_feature_snapshots`에 natural key unique index를 추가했다.
      - 재실행 시 duplicate insert 대신 동일 natural key row를 update 하도록
        repository `add()`를 upsert로 전환했다.
      - 기존 `signal_feature_snapshot_id`는 유지되고,
        feature payload만 최신 계산값으로 갱신된다.
    - [x] 장중 intraday relative activity 확장 시에도
      같은 batch runtime을 재사용하도록
      공통 orchestration 계층으로 정리한다.
      - `services.signal_feature_batch_runtime`에
        `SignalFeatureBatchRuntimeSpec`와
        tail-retry 판정 helper를 추가해
        `input -> batch -> tail-retry input -> tail-retry batch`
        흐름을 재사용 가능한 runtime spec으로 추출했다.
      - `run_ops_scheduler.py`는
        장후 전용 하드코딩 대신
        `_run_signal_feature_batch_runtime(...)` 공통 실행 경로를 사용하도록 정리했다.
      - `generate_signal_feature_snapshot_input.py`,
        `build_signal_feature_snapshots.py`는
        `freeze_purpose`, `trigger_type`를 명시적으로 주고받아
        향후 intraday relative activity 배치도
        같은 저장 경로와 run-state를 재사용할 수 있게 맞췄다.
  - 선행 완료 항목
    - [x] signal feature input / batch 실행 경로를
      `python3 -m scripts....` 구조로 통일
    - [x] `average_turnover_20d`, `turnover_surge_ratio` schema 반영
    - [x] 대형 거래대금 수용을 위한 DB precision 완화
    - [x] `signal_feature_snapshots.add()` savepoint 적용
    - [x] 수동 실반영 기준 `processed=96`, `persisted=96`, `errors=[]` 검증
- [x] decision context ↔ signal feature snapshot point-in-time anchor 1차 추가
  - `trading.decision_contexts.signal_feature_snapshot_id` nullable FK를 추가해
    실제 판단에 사용한 `signal_feature_snapshot` 식별자를 context에 고정
  - `DecisionOrchestratorService.assemble()`가
    최신 signal snapshot을 로드한 뒤 해당 `decision_context`에
    `signal_feature_snapshot_id`를 attach하도록 보강
  - `GET /decision-contexts/{id}` 응답에
    `signal_feature_snapshot_id`를 노출해
    replay / 운영 점검 시 사용 snapshot 추적 경로를 확보
- [x] signal feature anchor coverage 진단 API 1차 추가
  - `GET /signal-feature-snapshots/decision-context-coverage` 추가
  - 최근 `decision_contexts` 기준
    `recent_context_count`, `anchored_context_count`,
    `missing_context_count`, `coverage_rate`를 집계
  - `sampled_missing_context_ids`를 함께 노출해
    장후 batch 이후 어떤 판단 컨텍스트가 아직 anchor 없이 생성됐는지
    운영 기준으로 즉시 확인 가능하게 정리
- [x] trade decision read-path에 signal feature anchor 노출 1차 추가
  - `GET /trade-decisions` 응답에
    `signal_feature_snapshot_id`를 포함해
    각 판단 row에서 참조한 signal feature snapshot을 직접 확인 가능하게 정리
  - 운영자가 `decision_context` 상세를 별도로 다시 조회하지 않아도
    판단 단위에서 point-in-time feature anchor 추적이 가능하도록 보강
- [x] deterministic candidate vs final decision 진단 API 1차 추가
  - `GET /trade-decisions/candidate-alignment-diagnostics` 추가
  - 최근 의사결정의 `candidate_tracked_count`, `override_applied_count`,
    `matched_count`, `candidate_coverage_rate`, `match_rate`를 집계
  - `alignment_status`, `candidate_intent`, `final_intent` 분포와
    최근 misaligned sample을 함께 노출해
    deterministic trigger가 실제 final decision에서 어떻게 override되는지
    운영 기준으로 즉시 점검 가능하게 정리
- [x] trigger / override execution attribution API 1차 추가
  - `GET /performance-trigger-attribution` 추가
  - 계좌 기준 최근 의사결정의
    `tracked_decision_count`, `actionable_decision_count`,
    `ordered_decision_count`, `filled_decision_count`,
    `decision_to_order_rate`, `decision_to_fill_rate`를 집계
  - `alignment_status` / `candidate_intent` bucket별로
    주문 전환율과 체결 전환율을 함께 노출해
    deterministic trigger와 override가 실제 실행으로 얼마나 이어지는지
    최소 성과 attribution 기반을 마련
- [x] trigger / override performance attribution 설계 문서 1차 추가
  - [`plans/[DESIGN] performance_attribution_for_trigger_and_override.md`](./%5BDESIGN%5D%20performance_attribution_for_trigger_and_override.md)
    문서 추가
  - 현재 구조에서 가능한 `execution attribution`과
    아직 별도 설계가 필요한 `realized pnl attribution`의 경계를 명시
  - 다음 구현 단위를
    `post-decision return proxy attribution`으로 정의해
    복잡한 포지션 close 귀속 이전에 deterministic 성과 관찰 경로를 먼저 여는 방향으로 정리
- [x] deterministic trigger 계측 필드 1차 추가
  - `coverage_score`, `eligibility_passed`, `eligibility_reasons`,
    `ranking_score`, `candidate_mode`를
    `DeterministicTriggerAssessment`와 `decision_json.deterministic_trigger`에 추가
  - projection 변경 전 단계에서
    `WATCH 급증 / BUY_CANDIDATE 부족`이
    eligibility 병목인지 ranking 병목인지 분해 관측 가능한 최소 계측 기반 확보
- [x] decision loop `core_cap` 도입으로 저우선순위 core LLM 부하 완화 1차 적용
  - `max_cap`은 유지하되 `source_type=core`에만 별도 상한(`core_cap`)을 추가해
    held / event / market / manual 우선순위는 유지하면서
    비행동성 core 종목의 장중 assemble 부하를 줄이는 경로를 추가
  - decision loop 기본값은 `core_cap=12`, feature 장후 배치는 별도 `core_cap=80`으로 분리
  - [`plans/[IMPLEMENTATION] 2026-06-18_decision_loop_core_cap.md`](./%5BIMPLEMENTATION%5D%202026-06-18_decision_loop_core_cap.md)
- [x] pre-AI short-circuit 2차 리팩토링
  - 목적
    - 이미 계산된 `deterministic_trigger`와 `recent_events`를 이용해
      `EI -> AR -> FDC` 전부를 호출할 필요가 없는 신규 진입 후보를
      AI 호출 전단에서 더 많이 잘라낸다.
    - 토큰 절감 자체가 목적이 아니라,
      `명백한 비적격 BUY 후보에 대한 불필요한 AI 해석`을 줄여
      기대수익률과 장중 latency를 동시에 개선하는 것이 목적이다.
  - 우선순위
    - [x] `P1-1`: `core` 등 신규 BUY 후보 경로에서
      `eligibility_low_average_volume`, `eligibility_low_turnover`,
      `eligibility_allocation_blocked`, `eligibility_risk_off_block`,
      `eligibility_participation_rate_blocked`가 있는 경우
      EI/AR/FDC 호출 전 `HOLD` 또는 `WATCH`로 조기 종료
    - [x] `P1-2`: `recent_events == 0`이면 EI를 생략하고
      empty structured output으로 downstream을 계속 진행
    - [x] `P1-3`: `primary_candidate == NO_ACTION` 이고 `recent_events == 0`인
      신규 진입 후보에 한해 AR/FDC까지 생략하는 cut-out 적용
    - [x] `P1-4`: AR 결과가 `reject` 또는 고위험 점수면
      FDC 호출을 조건부 생략
  - 이번 반영
    - `DecisionOrchestratorService`에 pre-agent short-circuit을 추가했다.
    - 적용 범위는 우선 `source_type=core` + `실보유 없음` 경로로 제한했다.
    - `P1-1`, `P1-3` 조건에 해당하면 subprocess/in-process 경로에 들어가기 전에
      synthetic `HOLD/WATCH` bundle을 조립해 AI 호출 자체를 생략한다.
    - `DecisionAgentRunner`에 EI conditional skip을 추가했다.
    - `source_type=core` + `실보유 없음` + `deterministic_trigger 존재` + `recent_events=0`
      인 경우 EI provider 호출은 생략하고,
      default structured EI output만 recorder/AR/FDC downstream에 전달한다.
    - `DecisionAgentRunner`에 FDC conditional skip을 추가했다.
    - `source_type=core` + `실보유 없음` 경로에서
      AR 결과가 `risk_opinion=reject` 또는 `risk_score >= 0.85`이면
      FDC provider 호출은 생략하고 synthetic `HOLD/WATCH` 결과로 종료한다.
    - `TradeDecisionEntity.decision_json.ai_call_path`를 추가했다.
    - `ei_skipped`, `ar_skipped`, `fdc_skipped`, `skip_reason_codes`를 저장해
      short-circuit 적용 결과를 DB 조회만으로 바로 실측할 수 있게 했다.
    - `run_decision_loop` 결과 직렬화와 운영 요약 집계에도
      동일한 `ai_call_path` 계측을 반영했다.
    - cycle result 단위로 `ei_skipped`, `ar_skipped`, `fdc_skipped`,
      `skip_reason_codes`가 포함되며,
      summary metrics에는 tracked count / 단계별 skip count /
      skip reason 분포가 함께 기록된다.
    - 기존 `WATCH guard` / `BUY eligibility guard`도
      `core + 기존 보유 종목`에는 적용하지 않도록 보정해
      신규 진입 제한과 보유종목 관리 경계를 분리했다.
  - 적용 범위 제약
    - 위 short-circuit은 우선 `source_type=core` 등
      `신규 BUY 검토 경로`에만 적용한다.
    - `held_position`, `reconciliation_overlay`,
      상태 복구/정합성 확인 경로에는 동일 규칙을 적용하지 않는다.
    - 이유:
      보유종목의 `REDUCE/EXIT` 기회나
      정합성 복구 우선 원칙을 토큰 절감 논리로 잘라내면
      핵심 목표인 기대수익률 최대화와 운영 안전성을 함께 훼손할 수 있다.
  - 선행 작업
    - [x] skip/reject 사유를 `decision_json`에 구조화해
      어떤 단계에서 EI/AR/FDC가 생략됐는지 실측 가능하게 만들 것
    - [x] 운영 요약에도 같은 skip 계측을 반영할 것
    - 계측 없이 `60~80% 절감` 같은 정성 기대치로 바로 고정하지 않을 것
  - 기준 문서
    - [`plans/[ADVICE] ai_token_optimization.md`](./%5BADVICE%5D%20ai_token_optimization.md)
    - [`plans/2026-06-05_pre_ai_decision_skip_gate.md`](./2026-06-05_pre_ai_decision_skip_gate.md)
    - [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)
- [x] `core 신규 진입 비적격` risk-off 차단 완화 1차 보정
  - 실측 배경
    - `2026-06-24` decision:
      총 `2529`건 중 `eligibility_risk_off_block` `838`건,
      `source_policy_buy_blocked` `1203`건
    - `2026-06-25` decision:
      총 `1759`건 중 `eligibility_risk_off_block` `726`건,
      `source_policy_buy_blocked` `614`건
    - `2026-06-24` 실제 주문:
      `BUY 1건`, `SELL 7건`
      - 유일한 BUY는 `core`가 아니라 `event_overlay` 경로였음
    - `2026-06-25` 실제 주문:
      `order_requests=0`
    - 결론:
      현재 `core` 신규 진입 차단은
      “버그성 오차”보다 “정책 과도”에 가까우며,
      특히 `risk_off + bearish_trend`일 때
      core BUY가 AI 이전 단계에서 과도하게 잘리는 상태다.
  - 현재 코드 진단
    - `DecisionOrchestratorService`는
      `pre_ai_short_circuit + eligibility_risk_off_block`이면
      AI 호출 없이 `HOLD/WATCH`로 종료한다.
    - `DeterministicTriggerEngine`의 BUY eligibility는
      `market_regime.risk_tone == risk_off`
      그리고 `regime_label == bearish_trend`이면
      즉시 탈락시킨다.
    - 이 규칙은
      `range_bound`나 `bullish_trend + high_volatility`가 아니라
      `bearish_trend + risk_off`에만 적용되지만,
      실제 장중에서는 이 조합 비중이 높아
      core BUY path가 사실상 마비될 수 있다.
  - 수정 원칙
    - 전면 해제는 하지 않는다.
      `risk_off` 구간의 execution risk와 churn 증가는
      여전히 deterministic하게 억제해야 한다.
    - 다만 `core`의 기대수익률 상단 후보까지
      AI 이전 단계에서 일괄 차단하는 것은
      핵심 목표인 `최고 기대수익률`에 부합하지 않는다.
    - 따라서 `blanket block`을
      `ranked exception + WATCH 우선` 구조로 바꾼다.
  - 권장 수정안
    - [x] `P1`:
      `eligibility_risk_off_block`을
      “전면 BUY 탈락”에서
      “일반 core BUY 탈락 + 예외 후보만 AI 통과”로 변경
      - 기본값:
        기존처럼 `HOLD/WATCH` short-circuit 유지
      - 예외 허용 조건:
        아래를 모두 만족하는 상위 core 후보만
        AI 호출 경로로 통과
        - `source_type == core`
        - `watch_candidate == true` 또는 `entry_score >= buy_threshold * 0.85`
        - `ranking_score >= 0.55` 또는 `ranking_percentile <= 0.15`
        - `overall_score >= 0`
        - `slow_score >= -0.05`
        - `volume_surge_ratio >= 1.2` 또는
          `turnover_surge_ratio >= 1.2`
        - `recommended_max_order_value > 0`
        - `eligibility_low_average_volume`,
          `eligibility_low_turnover`,
          `eligibility_participation_rate_blocked`
          는 없어야 함
    - [x] `P1`:
      `risk_off + bearish_trend`에서도
      예외 통과 후보는
      즉시 `BUY_CANDIDATE`가 아니라
      `WATCH/AI reassessment` 우선으로 제한
      - FDC가 최종 `APPROVE`로 올리더라도
        `minimum_required_edge_bps`를 평시보다 높게 적용
      - 권장:
        `minimum_required_edge_bps`
        `+5 ~ +10bps` 가산
    - [x] `P1`:
      `event_overlay`는
      `core risk_off exception` 경로에 태우지 않고
      기존 regime gate 경로를 유지
      - 실측상 `2026-06-24` 실제 BUY `1건`은
        `event_overlay`에서 발생했으므로
        `core` 완화와 `event` 완화는 분리해야 한다.
      - 회귀 방지:
        `tests/services/test_deterministic_trigger_engine.py`에
        `event_overlay`가 `risk_off_exception_eligible`로
        승격되지 않는 테스트를 추가했다.
    - [x] `P2`:
      `market_regime`의 `risk_off` 판정과
      `core BUY eligibility`를 완전히 동일시하지 않도록 분리
      - `risk_tone`은 portfolio de-risk 용도로 유지
      - BUY eligibility는
        `regime + ranking + feature + execution feasibility`
        조합으로 별도 판정
      - 구현 반영:
        `core + bearish_trend + risk_off`에서는
        기존 blanket block 대신
        `core_risk_off_guard`를 적용한다.
      - 현재 guard 기준:
        `ranking_score >= 0.48`
        + `overall >= 0`
        + `slow >= -0.05`
        + `max(volume_surge_ratio, turnover_surge_ratio) >= 1.20`
        + 허용 전략
        (`defensive_low_volatility_rotation`,
        `mean_reversion_bounce`,
        `event_continuation`)
      - guard 실패 시에는
        `eligibility_core_risk_off_*_blocked`
        세부 사유를 남기고
        pre-AI short-circuit 대상에 포함한다.
      - 회귀 방지:
        `tests/services/test_deterministic_trigger_engine.py`,
        `tests/services/test_decision_orchestrator.py`,
        `tests/services/test_expected_value_gate.py`
        기준으로 검증한다.
  - 기대 효과
    - `core` 신규 진입 후보가
      전부 AI 이전 단계에서 사라지는 현상 완화
    - `risk_off` 구간에서도
      상위 극소수 후보는 재평가 가능
    - `event_overlay`와 `held_position`의 기존 운영 안정성은 유지
    - 무차별 BUY 재개가 아니라
      `top-ranked exception`만 허용하므로
      churn 및 저유동성 오진입 리스크를 제한 가능
  - 구현 순서
    - [x] `DeterministicTriggerResult`에
      `risk_off_exception_eligible` 필드 추가
    - [x] `deterministic_trigger_engine.py`에서
      위 예외 판정 helper 추가
    - [x] `decision_orchestrator.py`의
      `pre_ai_short_circuit` 분기에서
      `eligibility_risk_off_block`이어도
      `risk_off_exception_eligible=true`면
      AI 호출 경로로 통과
    - [x] `expected_value_gate`에서
      `risk_off_exception_path`에 대한
      추가 edge 요구치 적용
    - [x] 운영 계측:
      `risk_off_exception_eligible_count`,
      `risk_off_exception_ai_pass_count`,
      `risk_off_exception_submit_count`
      집계 추가
- [x] 초저유동성 `core` BUY 실행 구멍 보완
  - 기대수익률 관점에서 부합하는 범위만 우선 반영:
    - [x] `core` BUY eligibility에도 저유동성 / execution feasibility gate 1차 추가
      - `signal_feature_snapshot.average_volume_20d`
      - `portfolio_allocation.recommended_max_order_value`
      를 이용해 `eligibility_low_average_volume`, `eligibility_low_turnover`,
      `eligibility_participation_rate_blocked`를 판단하도록 반영
    - [x] `eligibility 실패`, 특히 execution infeasible 상태에서는
      `NO_ACTION -> AI APPROVE` 승격 금지 1차 반영
      - `buy_eligibility_guard`로 `core` BUY 승격을 `HOLD/WATCH`로 제한
    - [x] 전면 `MARKET` 정책은 유지하지 않고,
      저유동성 구간은 `LIMIT 강제` 또는 `submit 금지`로 1차 분기
      - `ExecutionService`에서 `buy_execution_liquidity_v1` 적용
      - 중간 저유동성: `quote.ask` / `reference_price` 기반 `LIMIT` 강제
      - 심각 저유동성 또는 trigger execution infeasible: submit 차단
    - [x] sizing에 participation cap 1차 추가
      - live quote의 `acml_vol`, `acml_tr_pbmn`
      - feature의 `average_volume_20d`
      를 이용해 `intraday_volume_participation_cap`,
      `intraday_turnover_participation_cap`,
      `average_daily_volume_participation_cap` 적용
  - blanket `NO_ACTION override 금지`는
    기대수익률 저해 가능성이 있어 채택하지 않음
  - 검증 상태
    - 관련 회귀 테스트로 아래 경로를 재확인했다.
      - deterministic trigger의 `low_average_volume`, `participation_rate_blocked`
      - orchestrator의 `buy_eligibility_guard`, pre-agent short-circuit
      - execution 단계의 `LIMIT 강제` / `submit 차단`
      - sizing 단계의 participation cap 3종
  - 기준 문서:
    - [`plans/[DESIGN] deterministic_trigger_eligibility_and_ranking_v1.md`](./%5BDESIGN%5D%20deterministic_trigger_eligibility_and_ranking_v1.md)
    - [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30`
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `30a`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 13. Market Regime / Strategy Selection / Portfolio Agent 분해 — `완료`

### 핵심
- 시장 국면, 전략 선택, 포트폴리오 배분 책임을 명시적 계층으로 분리

### 세부 작업 상태
- [x] Market Regime deterministic backbone 1차 추가
  - `services.market_regime`에 `MarketRegimeAssessment`, `classify_market_regime()` 추가
  - `signal_feature_snapshot` 기반 `bullish_trend` / `bearish_trend` / `range_bound` / `event_driven_unstable`
    및 `high_volatility` / `risk_on` / `risk_off` 분류 규칙 1차 구현
  - 전략군 가중치(`strategy_weights`), `confidence`, `half_life_hours`, `reason_codes` 산출
- [x] decision pipeline 입력 연결 1차 완료
  - `DecisionOrchestratorService.assemble()`가 최신 signal snapshot에서 market regime를 계산해
    `AssembledContext.market_regime`에 주입
  - AI Risk / FDC prompt에 regime label / volatility regime / risk tone / strategy weights를 read-only로 노출
  - 생성되는 `TradeDecisionEntity.regime_label`에 1차 반영
- [x] Strategy Selection deterministic registry / selector 1차 추가
  - `services.strategy_selection`에 `StrategySelectionAssessment`, `select_strategy()` 추가
  - `market_regime + source_type` 기반으로 `preferred_strategy`, `allowed_strategies`,
    `preferred_entry_style`, `preferred_time_horizon`, `confidence`, `reason_codes` 산출
  - `AssembledContext.strategy_selection`에 주입하고 AI Risk / FDC prompt에 read-only로 노출
  - `TradeDecisionEntity.strategy_fit_score` 및 `decision_json.strategy_selection`에 1차 반영
- [x] Portfolio allocation / concentration budget 계층 분리
  - `services.portfolio_allocation`에 `PortfolioAllocationAssessment`,
    `assess_portfolio_allocation()` 추가
  - `DecisionOrchestratorService.assemble()`가 `config + snapshot + regime + strategy`
    입력을 이용해 종목별 `target_weight_pct`, `remaining_concentration_pct`,
    `remaining_gross_budget_pct`, `max_new_capital_pct`,
    `recommended_max_order_value`를 계산해
    `AssembledContext.portfolio_allocation`에 주입
  - AI Risk / FDC prompt가 포트폴리오 배분 결과를 read-only로 노출하고,
    `TradeDecisionEntity.decision_json.portfolio_allocation`에 1차 반영

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `27`, `29`, `31`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`

---

### 14. AI Compliance / Model Monitor 분해 — `미완료`

### 핵심
- ambiguous policy risk와 deterministic hard validation 분리
- provider drift / fallback / replay divergence 모니터링 체계 구축

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `32`, `33`
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`
- `plan_docs/agents/03_risk_role_boundaries.md`

---

### 15. Data Quality / Hard Guardrail 일원화 — `완료`

### 핵심
- stale snapshot, blocked reason, kill switch, risk check, submit/reconcile 차단 규칙을
  명시적 deterministic 계층으로 더 정리
- 현재 orchestrator / sizing / sync / snapshot 계층에 분산된 hard guardrail 책임을 수렴

### 세부 작업 상태
- [x] decision loop의 `pre-AI skip` 규칙을 공용 서비스 계층으로 승격
  - `held_position` 무보유 skip
  - 일반 BUY `orderable_amount` / general BUY budget 기반 skip
  - late-session / recent-event / recent-order 기반 held-position stable-hold skip
- [x] `pre-AI gate` / `execution_service` 공통 `PipelineStopReason` 코드 집합 1차 정리
  - `stop_reason`를 `SubmitResult`/cycle serialization에도 직접 노출
- [x] scheduler `dry_run_reason` / general submit gate 사유도 canonical helper로 정리
  - dry-run 결과에도 `stop_reason` 동시 노출
- [x] `pre-AI deterministic gate` 차단 결과를 `guardrail_evaluations`에 저장
  - `rule_set_version=pre_ai_gate_v1`
  - `symbol/account/source_type/skip_details` audit trail 보존
- [x] `scheduler gate` dry-run 차단 결과도 `guardrail_evaluations`에 저장
  - `rule_set_version=scheduler_gate_v1`
  - `submit_budget_consumed_*` / `general_submit_disabled_*` 류 사유 audit trail 보존
- [x] execution `sell_guard` / `buy_duplicate_guard` 차단 결과도 `guardrail_evaluations`에 저장
  - `rule_set_version=sell_guard_v1`, `buy_duplicate_guard_v1`
- [x] execution `stale_snapshot_guard` 차단 결과도 공통 helper로 수렴
  - `rule_set_version=stale_snapshot_guard_v1`
  - account-level / run-level stale 차단 모두 `_record_blocking_guardrail_evaluation()` 경유
- [x] execution 최종 broker outcome도 canonical `stop_reason`으로 수렴
  - `SUBMITTED → order_submitted`
  - `RECONCILE_REQUIRED → order_reconcile_required`
  - `REJECTED → order_rejected`
- [x] stale snapshot guardrail blocking code도 canonical 소문자 코드로 수렴
  - `STALE_SNAPSHOT_ACCOUNT → stale_snapshot_account`
  - `STALE_SNAPSHOT → stale_snapshot_run`
- [x] scheduler submit lane gate를 공통 helper로 추출해 중복 계산 제거
  - `scripts/run_decision_loop.py`의 submit/dry-run/reason 계산을
    `services.submit_lane_gate.evaluate_symbol_submit_lane()`로 수렴
- [x] execution의 `RECONCILE_REQUIRED` / `REJECTED` broker outcome도 guardrail audit로 저장
  - `rule_set_version=broker_submit_outcome_v1`
  - `order_reconcile_required`, `order_rejected`를 `guardrail_evaluations`에서 직접 추적 가능
- [x] guardrail evaluation 저장 스키마를 공통 helper로 수렴
  - `services.guardrail_audit.persist_blocking_guardrail_evaluation()`
  - pre-AI / scheduler / execution 경로가 동일한 저장 함수 사용
- [x] `held_position` 위험축소 SELL 경계를 공통 helper로 수렴
  - `services.held_position_policy.is_held_position_sell_path()`
  - scheduler와 execution, ops scheduler가 동일하게 `held_position + REDUCE/EXIT + SELL`만
    quote/stale bypass 및 전용 lane 대상으로 취급
- [x] held-position 전용 submit lane의 cycle cap 차단 제거
  - `services.submit_lane_gate.evaluate_symbol_submit_lane()`에서
    `source_type=held_position`만으로 `held_position_sell_cycle_cap`을
    선적용하던 경로를 제거
  - held-position 종목은 같은 cycle 내 동일 symbol 중복만 차단하고,
    위험축소 SELL submit은 cycle count와 무관하게 진행되도록 정리
- [x] held-position 반복 `REDUCE/EXIT` 판단 suppression 1차 추가
  - `services.pre_ai_gate.evaluate_held_position_skip_reason()`가
    최근 same-symbol SELL order + 최근 held-position `REDUCE/EXIT/SELL` 판단 +
    포지션 증가 없음 조건에서
    `held_position_recent_risk_sell_cooldown`으로 pre-AI skip
  - 최근 이벤트가 있거나 장 마감 임박 이후에는 suppression을 적용하지 않음
  - 후속 운영 검증:
    `2거래일` 정도 장중 모니터링으로
    `held_position_recent_risk_sell_cooldown` 분포,
    동일 종목 반복 `REDUCE/EXIT` 감소율,
    위험축소 SELL 지연/누락 부작용 유무를 먼저 실측한 뒤
    `signal_feature_snapshot_id` 동일 여부까지 포함한 stricter duplicate policy 검토 진행
- [x] stale snapshot / submit cap / sell guard / reconcile gate의 공통 reason code 체계 수렴
  - `PipelineStopReason` + `general_submit_disabled_reason()` +
    `submit_budget_consumed_reason()` 기준으로 canonical code 정리
  - `stale_snapshot_account`, `stale_snapshot_run`,
    `order_reconcile_required`, `order_rejected`까지 수렴 완료
- [x] scheduler / decision loop / execution_service 간 중복 gate 제거
  - pre-AI skip은 `services.pre_ai_gate`
  - submit lane gate는 `services.submit_lane_gate`
  - held-position risk-reducing SELL 판별은 `services.held_position_policy`
  - ops scheduler도 동일 helper 사용
- [x] execution/scheduler 전 구간의 guardrail evaluation 저장 정책 최종 수렴
  - `services.guardrail_audit.persist_blocking_guardrail_evaluation()`로 저장 경로 통일
  - pre-AI / scheduler / execution / broker submit outcome이 동일 audit 축으로 기록

### 근거 문서
- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/02_agent_target_shapes.md`
- `plan_docs/agents/03_risk_role_boundaries.md`

### 비고
- 본 항목은 구현 관점에서는 닫힌 상태다.
- 이후 추가 변경이 생기면 새 guardrail이 위 공통 helper/enum 체계를 따르는지만 검토하면 된다.
- 이 항목은 AI agent 추가가 아니라 execution safety 계층 정리이므로,
  전략/신호 agent 분해와 병렬로 보는 것이 아니라 오히려 일부 선행 과제로 해석할 수 있다.

---

## P3 — 후순위 또는 보류할 작업

### 16. Admin UI 추가 고도화 — `보류`

현재 상태:
- 최근 BUY 차단, 체결내역, 드릴다운 관련 UI 보강이 많이 들어갔다.
- 사용자가 별도로 “지금은 admin ui보다 다른 급한 우선순위를 먼저 하자”고 명시했다.

따라서 아래는 당분간 후순위로 둔다.

- [ ] `fill-sync-runs/summary` retry 정보의 UI 뱃지화
- [ ] 주문 상세 ↔ 체결내역 교차 링크 UI polish
- [ ] 계좌/대시보드 freshness indicator 추가 확장
- [ ] 에이전트 판단근거 UI 추가 노출
- [ ] 수동 배치 Admin UI
  - instrument master sync / placeholder seed 같은 운영 배치를
    `dry-run → apply → 실행 이력 조회` 구조로 다룰 수 있는 UI
  - 장중 override 권한 / 실행자 / 파라미터 / 결과 로그를 함께 남기는
    job 기반 실행 contract 선행 필요

### 근거 문서
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `8d`, `10`, `11`, `12`, `13`
- `plan_docs/agents/01_agent_inventory_and_status.md`

---

### 17. 멀티 사용자 공용 Plane / 개인 Credential Plane 분리 리팩토링 — `보류`

### 목표
- 사용자별 KIS / AI / NAVER credential은 분리하되,
  공통으로 공유 가능한 정책/데이터/계산 계층은 재사용하는
  멀티 사용자 운영 구조를 설계하고 후속 구현한다.

### 공용으로 유지할 대상
- [ ] instrument master
- [ ] market session / 휴장일 / 장상태 수집
- [ ] universe selection 정책과 freeze 생성 로직
- [ ] signal / feature 계산식과 deterministic backend math engine
- [ ] broker adapter 구현체와 오류 정규화 규칙
- [ ] audit / replay / reconciliation 프레임워크
- [ ] 운영 대시보드 공통 집계 로직

### 개인별로 반드시 분리할 대상
- [ ] KIS App Key / App Secret / 계좌번호 / 상품코드
- [ ] AI provider key / model override / provider 선택
- [ ] NAVER 등 외부 API credential
- [ ] 사용자별 live/paper 활성 상태
- [ ] 사용자별 계좌 매핑과 주문 권한
- [ ] 사용자별 리스크 / execution override

### 설계/개발 작업 범위
- [ ] secret manager 또는 동등 구조를 전제로 한 `credential profile` 데이터 모델 설계
- [ ] `AppSettings()` 전역 env 의존 경로를 `client runtime config + secret resolver` 구조로 전환하는 설계
- [ ] account별 broker adapter / AI agent / news adapter 동적 조립 경로 설계
- [ ] `ops-scheduler`가 account fan-out 실행을 하되
  rate limit budget / reconciliation lock / snapshot truth를 계좌 단위로 분리하는 실행 설계
- [ ] Admin UI의 사용자별 credential 등록/검증/회전 화면 설계
- [ ] 사용자 인증 / RBAC / client-account 권한 매핑 설계

### 선행 조건
- universe / feature / decision / reconciliation / scheduler 핵심 운영 구조가 더 이상 크게 흔들리지 않을 것
- 현재 P0 ~ P2의 운영 안정화와 정책 구조화가 충분히 마무리될 것

### 근거 문서
- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/06_config_schema.md`
- `plan_docs/ENTERPRISE_TRADING_SYSTEM_DESIGN.md`

### 보류 이유
- 현재 단계에서 바로 멀티 사용자화에 들어가면
  execution truth, scheduler, decision runtime 안정화보다
  런타임 주입 구조 변경이 먼저 커져 운영 리스크가 커진다.
- 따라서 이 항목은 **모든 중요 개발 완료 후 P3 리팩토링 과제**로 유지하는 것이 맞다.

---

## P3 — 개발 완료 후 문서화 과제

### 18. 운영/업무자용 주문 흐름 문서 패키지 — `보류`

### 목표
- 핵심 백엔드/운영 안정화 개발이 모두 끝난 뒤, 비개발 업무자도 바로 읽을 수 있는 운영 문서 세트를 만든다.

### 작성 대상
- [ ] **매수 경로만 따로 분리한 요약본**
- [ ] **매도/체결/재조회 경로만 따로 분리한 운영 매뉴얼**
- [ ] **장애 대응 체크리스트 버전**

### 선행 조건
- 현재 남아 있는 핵심 개발 과제가 모두 마무리될 것
- 주문 생성 / 제출 / 체결 / 재조회 / recovery 정책이 더 이상 크게 바뀌지 않을 것

### 근거 문서
- [`plans/[GUIDE] end_to_end_order_flow_guide.md`](./[GUIDE]%20end_to_end_order_flow_guide.md)
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `13a`

### 보류 이유
- 지금 작성하면 이후 개발 변경으로 문서가 빠르게 낡을 가능성이 높다.
- 따라서 **모든 주요 개발 종료 후 최종 운영 매뉴얼 패키지로 작성**하는 것이 맞다.

### 우선순위 이유
- 이번 임시공휴일처럼 시장 캘린더 변동이 있을 때 운영 판단을 더 신뢰성 있게 할 수 있다.

### 세부 작업 상태
- [x] 조기종료/특수세션 reason 근거를 `reason_metadata`로 더 구조적으로 저장 완료
  - [`plans/2026-06-08_market_sessions_reason_metadata_structuring.md`](./2026-06-08_market_sessions_reason_metadata_structuring.md)
- [x] 비거래일 readiness / next-trading-day readiness와 session history를 더 직접 연결 완료
  - [`plans/2026-06-04_market_sessions_history_readiness_link.md`](./2026-06-04_market_sessions_history_readiness_link.md)

---


## P1/P2 후보 (신규) — 운영 가시성 강화

### 19. KIS WebSocket 기반 실시간 현재가 조회 운영 화면 — `Phase 1~4 완료`

### 목표
- Admin UI "기본 운영" 메뉴 아래 신규 read-only 화면을 추가해, 운영자가 선택한 종목의
  실시간 현재가/등락/체결 시각/연결 상태를 빠르게 확인할 수 있게 한다.
- 이 항목은 트레이딩 판단(주문 제출, 자동매매, universe 편입, signal 계산)과는
  분리된 순수 운영 편의 도구다.

### 우선순위 판단 근거
- **주문/체결 truth 안정화(P0, 위 1~4번)보다는 명확히 후순위다.** 이 화면은 트레이딩
  경로에 관여하지 않으므로, 체결 진실원 강화나 정합성 수렴 작업을 밀어내면서까지
  먼저 할 이유가 없다.
- **다만 P3 "16. Admin UI 추가 고도화"(보류) 항목들보다는 우선순위가 높을 수 있다.**
  16번 항목의 보류 사유는 "지금은 admin ui보다 다른 급한 우선순위를 먼저 하자"는
  사용자 지시였으나, 그 항목들(fill-sync 뱃지, 드릴다운 UI polish, freshness indicator
  확장 등)은 **기존 데이터를 더 보기 좋게 다듬는 편의 개선**인 반면, 이 항목은 지금까지
  Admin UI에 **전혀 노출되지 않던 새로운 운영 가시성**(실시간 시세 확인)을 제공한다는
  점에서 차이가 있다. 따라서 P1/P2 후보로 별도 분리했다.
- 별도 계좌/앱키 발급 등 행정적 선행 조건은 이미 해결된 상태이므로, 착수 여부는
  순수하게 다른 P0/P2 작업과의 우선순위 경합 문제로 남는다.

### 현재 상태
- 사전 조사(계좌/세션/rate-limit 스코프 분석, TR ID 선택, fan-out 아키텍처 검토)를
  거쳐 상세 설계 문서로 정리되었다.
- 이 항목은 [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `37`과
  1:1로 대응한다.
- **2026-07-08 기준 Phase 1~3 구현 완료** — 설계 문서의 단계 구분
  (`11_kis_realtime_quote_operations_screen.md` §8) 기준으로 보면, 현재 상태는
  "문서/API contract/UI mock(Phase 1) → 전용 KIS WebSocket-backed quote source(Phase 2)
  → Admin UI polling 화면/딥링크/프레임 유지 UX(Phase 3)" 까지 반영된 상태다.
  Phase 2에 포함되는 **Step 4(REST Fallback 연동)는 2026-07-10 구현 완료** —
  `data_source`에 `"rest_fallback"`이 실제로 산출된다(아래 2026-07-10 블록 참고).
  - Backend: 전용 `KisRealtimeQuoteSource` + 별도 계좌/앱키 전용
    `build_realtime_quote_source()` 경로 + startup failure cleanup 보정 완료 —
    [`kis_realtime_quote_source.py`](../src/agent_trading/services/kis_realtime_quote_source.py),
    [`bootstrap.py`](../src/agent_trading/runtime/bootstrap.py)
  - API: `GET /realtime-quotes/bootstrap`, `POST/DELETE/GET .../subscriptions`,
    `GET .../snapshot` 실연동 완료 — [`routes/realtime_quotes.py`](../src/agent_trading/api/routes/realtime_quotes.py)
  - Admin UI: `/operations/realtime-quotes` polling 화면, `?symbol=` 딥링크,
    단일 종목 상세 뷰, 10호가 프레임 유지 UX, Orders/FillHistory 진입 딥링크 완료 —
    [`RealtimeQuoteView.tsx`](../admin_ui/src/components/RealtimeQuoteView.tsx)
  - Codex 검수 후 보정 반영:
    ① backend 구독 semantics를 ref-count에서 **idempotent set**으로 정리,
    ② symbol 검증을 6자리 숫자로 제한,
    ③ startup failure cleanup 보정,
    ④ UI `?symbol=` 동기화/프레임 유지/기존 화면 딥링크 연결 보정.
- **✅ 2026-07-09 Phase 4 완료** — SSE(Server-Sent Events) 채택, app 프로세스
  내부 fan-out 계층 `QuoteBroadcaster` 추가([`realtime_quote_broadcaster.py`](../src/agent_trading/services/realtime_quote_broadcaster.py)).
  `KisRealtimeQuoteSource.add_listener()`로 WS tick을 즉시 push(폴링 없음),
  `InMemoryMockQuoteSource`처럼 push를 지원하지 않는 source는 자동으로 짧은
  주기 poll-fallback으로 동작(구독자는 구분할 필요 없음). 신규
  `GET /realtime-quotes/stream?symbol=...`([`routes/realtime_quotes.py`](../src/agent_trading/api/routes/realtime_quotes.py)).
  `RealtimeQuoteView.tsx`는 이제 이 스트림을 기본 데이터 경로로 쓰고,
  스트림 자체가 끊기면(재연결 시도 중) 기존 3초 REST polling으로 자동 전환된다
  (Phase 1-3 polling 코드는 제거하지 않고 degraded fallback으로 유지).
  Phase 1-3 REST contract(bootstrap/subscribe/snapshot)는 변경 없음.
  - **후속 검토(별도 항목)**: 아래 20번 "credential/appkey 통합 재검토"는 Phase 4
    완료를 트리거 조건으로 뒀었다 — 이제 재평가 가능한 시점이나, 이번 작업
    범위에서는 통합을 진행하지 않았다(명시적 범위 제외).
  - **알려진 제한**: single-process 가정 유지(`uvicorn --workers 1`), 여러
    운영자가 동시에 다른 종목을 볼 경우의 multi-worker/cross-process fan-out은
    검토 대상으로 남음(Redis 등 외부 pub/sub 필요 — 지금은 불필요).
- **✅ 2026-07-09 장마감 후 리소스 비효율 개선(변경 감지/dedup)** — 장 마감 후에도
  KIS가 동일한 마지막 호가/체결 프레임을 계속 반복 전송하는 것이 실측됐고, 기존
  코드는 이를 매번 새 값으로 취급해 push listener(`QuoteBroadcaster`)에 불필요하게
  재통보했다. `KisRealtimeQuoteSource`에 종목별 "마지막 notify 내용 signature" 캐시를
  추가해, 실제로 내용이 바뀐 프레임만 notify하도록 수정(구독 직후 첫 프레임/재구독
  시에는 항상 최소 1회 notify 보장). 상세는
  [`11_kis_realtime_quote_operations_screen.md`](../plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md)
  §5.5의 2026-07-09 추가 블록 참고.
- **✅ 2026-07-10 자정 경과 구독의 `prev_close` stale 버그 수정** — `000660`에서
  "호가"의 대비율과 "실시간 체결가"의 대비율이 다르게 표시되는 문제가 보고돼
  실측한 결과, 자정을 넘겨 계속 유지된 구독(자동 unsubscribe 없음)의 `prev_close`가
  `subscribe()` 시점에 REST로 1회만 가져온 뒤 갱신되지 않아 stale해진 것이 원인이었다.
  종목별 `reference_date`를 추적해 날짜가 바뀌면 자동으로 REST 재조회하도록 수정.
  상세는 위 문서 §5.5의 2026-07-10 추가 블록 참고.
- **✅ 2026-07-10 Step 4(REST Fallback 연동) 구현 완료** — 항목 #37/이 문서에서
  유일하게 남아 있던 미구현 항목이었다. `KisRealtimeQuoteSource`에 헬스 모니터
  루프를 추가해, KIS WS 연결이 끊기거나 재연결 중인 상태가 10초 이상 지속되면
  구독 중인 종목의 snapshot을 REST 현재가 조회(`FHKST01010100`)로 보정하고
  `data_source`를 `"rest_fallback"`으로 노출한다. 종목별 10초 쿨다운으로 과호출을
  방지하고, WS가 회복되면 다음 실제 tick에서 자동으로 `"websocket"`으로 복귀한다.
  Phase 4의 SSE push relay/브로드캐스터 구조, API contract는 변경하지 않았다 —
  fallback으로 갱신된 snapshot도 기존 push 경로를 그대로 타고 SSE 구독자에게도
  전달된다. 상세는 `11_kis_realtime_quote_operations_screen.md` §4.7의 2026-07-10
  블록 참고. **이로써 이 항목(#19/#37)의 알려진 미구현 항목은 모두 해소됐다** —
  남은 건 §5.5에 언급된 single-process 가정/multi-worker fan-out(범위 외로 유지)뿐.

### 기존 항목과의 구분
- **`plans/[BACKLOG] backlog.md` 항목 `#19`("WebSocket 기반 실시간 order event 수신")와는
  다른 작업이다.** `#19`는 체결통보(`H0STCNI0`) 기반 post-submit sync 자동화이며 이미
  `✅ 승격됨` 상태로 구현 완료되어 있다. 이 항목(우선순위표 19번)은 시세(현재가/호가)
  조회 화면이며 TR 채널도 다르다(`H0STCNT0`/`H0STASP0`).
- **`### 8. 장 운영 세션 정보 수집/저장`(163 장운영정보, `KIS_LIVE_INFO_*`)와의 관계**:
  ~~완전히 별도의 신규 Live 계좌·앱키를 전제로 하며, 기존 트레이딩 계좌/공시 계좌의
  세션·rate-limit budget과 공유하지 않는다.~~ **[2026-07-08 당시 설계 — 2026-07-10
  credential 통합 구현으로 대체됨]** 163 WS가 `ops-scheduler`에서 제거되면서, 이제
  이 화면은 `### 8`과 **동일한 `KIS_LIVE_INFO_*` credential을 공유**한다(신규 전용
  계좌는 더 이상 쓰지 않음) — 트레이딩 계좌(`KIS_APP_KEY`)와는 여전히 분리되어 있다.
  상세는 항목 20 "✅ 2026-07-10 credential 통합 구현 완료" 참고.


### 근거 문서
- [`plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`](../plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md)
- [`plans/[BACKLOG] backlog.md`](./[BACKLOG]%20backlog.md) 항목 `37`

---

## P3 - Phase 4 후단 아키텍처 재검토

### 20. KIS 실시간 현재가 credential/appkey 통합 재검토 - ✅ 통합 구현 완료(2026-07-10): 최종 authoritative key = KIS_LIVE_INFO_*

> **📌 현재 최종 상태(2026-07-10)**: credential 통합 구현이 완료되었다.
> 실시간 현재가 화면(`api` 프로세스)과 076 REST 홀리데이 조회(`ops-scheduler`)가
> 이제 **동일한 `KIS_LIVE_INFO_*`를 authoritative credential로 공유**한다
> (`KIS_REALTIME_QUOTE_*`는 deprecated fallback으로만 코드에 남음). 트레이딩
> 계좌(`KIS_APP_KEY`)와는 여전히 완전히 분리되어 있다. 아래 "목표"/"재검토 결론"
> 절은 **이 결론에 도달하기까지의 당일(2026-07-10) 중간 판단 이력**이다 — 순서대로
> 읽으면 "분리 유지" 중간 결론 → 163 WS 제거 → 통합 구현 완료로 이어진다. 상세는
> 이 항목 맨 아래 "✅ 2026-07-10 credential 통합 구현 완료" 섹션 참고.

### 목표 [2026-07-09 당시 질문 — 아래 결론들을 거쳐 2026-07-10에 통합으로 최종 확정됨]
- 당시 KIS_REALTIME_QUOTE_*와 KIS_LIVE_INFO_*를 완전 분리한 구조를
  그대로 영구 유지할지, 아니면 Phase 4 후단에서
  단일 live market-data credential 체계로 통합할지
  운영 비용까지 포함해 다시 판단한다.

### ✅ 2026-07-10 재검토 결론 [당일 중간 결론 — 같은 날 뒤이어 통합 구현으로 대체됨]
- **[당시 결론] 지금 통합 구현에 착수하지 않는다. 당분간 분리 구조를 유지한다.**
  **→ 이후 163 WS 제거로 이 결론의 핵심 근거가 사라져, 같은 날 통합 구현으로
  대체되었다(아래 "✅ 2026-07-10 credential 통합 구현 완료" 참고).**
- 이번 재검토는 구현이 아니라 판단 문서화다 — 실제 credential 통합/코드 변경은
  진행하지 않았다.
- 재검토 과정에서 기존 판단보다 더 강한 근거가 새로 확인됐다: 두 credential은
  **같은 `api` 프로세스 안의 문제가 아니라, 서로 다른 두 컨테이너 프로세스**
  (`KisRealtimeQuoteSource`는 `api` 전용, `KisMarketStateClient`는
  `ops-scheduler` 전용 — `run_ops_scheduler.py::_init_market_state_provider()`)
  간의 문제였다. `api/app.py`의 lifespan에는 `KisMarketStateClient`가 아예
  등장하지 않는다. 즉 통합은 "같은 프로세스 안의 session manager 설계"가 아니라
  **서비스 토폴로지(어느 컨테이너가 credential을 소유하는가) 재설계**다.
- 상세 근거(코드 확인 범위, 비교표, 통합 시 필요한 구조 변경 6가지, 후속 선행
  조사 체크리스트)는 `11_kis_realtime_quote_operations_screen.md`의
  "Credential 분리/통합 판단 메모"(2026-07-10 갱신) 참고.

### [2026-07-10 재검토 당시] 분리 유지의 핵심 근거(요약) — 163 WS 제거로 무효화됨
> 이 소제목은 원래 "현재 시점 분리 유지의 핵심 근거"였으나, 같은 날 뒤이은 163 WS
> 제거로 아래 근거들이 무효화되어 통합을 구현했다 — 지금은 역사적 기록이다.
- `§4.2 WebSocket Session 1개 원칙`("같은 appkey로 두 번째 연결을 여는 코드
  경로를 만들지 않는다")이 이미 명시적 설계 불변식으로 존재 — 통합 시 이걸
  프로세스 경계 너머로 지켜야 해서 난이도가 더 크다.
- registration budget(41건 상한)은 프로세스 내 인메모리 상태(`SubscriptionBudget`)라
  프로세스 간 공유가 안 됨 — 통합하려면 Redis 등 외부 상태 저장소가 필요(기존에
  이미 "multi-worker fan-out은 범위 외"로 명시한 것과 동일 클래스의 비용).
- 통합의 실익(별도 계좌/appkey 운영·행정 비용 절감)은 실재하지만 순수 운영
  비용이지 기술적 필요는 아니다 — 지금도 각 credential의 41건 한도에 여유가
  있어 통합하지 않아도 registration budget 문제는 없다.
- dormant credential(거래 없는 별도 계좌의 장기 존속 리스크)은 여전히 유효한
  우려이지만, 이는 기술 통합으로 해결할 문제가 아니라 계좌/앱키 관리를 담당하는
  운영 조직의 행정적 결정 사항으로 분리해서 다뤄야 한다.

### 후속 액션(선행 조사 체크리스트 — 통합 착수 조건이 아니라 준비 조건)
- [x] **2026-07-09: Phase 4 relay/fan-out 구조(`QuoteBroadcaster`) 완료** — 이
      항목의 재검토 트리거 조건이 충족됐다.
- [x] **2026-07-10: 재검토 완료** — 결론 "당분간 분리 유지"로 확정. 비교표/구조
      변경 범위는 `11_...md` 참고.
- [x] **2026-07-10: 선행 조건 "163 WS 제거 가능성" 검토 완료** — 결론
      "제거 가능성 높음, 장기 shadow 검증 없이 진행 가능"(아래 상세 참고).
      163을 아예 없앨 수 있다면 credential 통합 문제가 "두 프로세스 소유권
      재설계"에서 "`api`의 credential만 남기고 `KIS_LIVE_INFO_*`를 폐기"하는
      훨씬 단순한 문제로 축소된다 — 그래서 credential 통합보다 이 검증을
      먼저 진행했다.
- [x] **2026-07-10: 163 WS 제거 구현 완료** — 위 검토 결론에 따라
      `ops-scheduler`에서 163 WebSocket(`KisMarketStateClient`)/
      `CombinedSessionProvider` 의존을 실제로 제거했다(`scripts/run_ops_scheduler.py`).
      `_init_market_state_provider()`/`_session_phase_monitor()`/
      `_handle_phase_change()`/`_insert_session_event()` 삭제, `_init_session_provider()`는
      항상 `create_session_provider()`(076 REST + fallback-only) 결과만 반환하도록
      단순화했다. `SchedulerState.market_phase`/`last_phase_change` 필드와
      `trading.market_sessions`/`operations_day_runs`의 동일 컬럼은 스키마 변경 없이
      그대로 남겨두되, 앞으로는 항상 `NULL`로 기록된다(로깅/헬스체크는 이미 "N/A"/
      heartbeat-fallback 경로를 갖추고 있어 별도 수정 불필요). `core_risk_off` 장후
      검증 배치(`signal_feature_batch`/`trigger_proxy_attribution`)는 애초에
      `state.market_phase`가 아니라 고정 시계 상수(`_run_end_of_day`의
      `after_hours_mode` 진입, `DEFAULT_SIGNAL_FEATURE_BATCH_TIME` 트리거)로만
      게이팅되어 영향 없음을 코드 확인 + 테스트(148 passed)로 검증했다. 이제
      credential 통합은 "`api`의 `KIS_REALTIME_QUOTE_*`만 남기고 `KIS_LIVE_INFO_*`를
      정리할지"의 훨씬 단순한 문제로 축소된 상태다 — credential 통합 자체는
      이번 작업 범위 밖.
- [ ] KIS에 appkey당 동시 WS 세션 허용 여부를 공식 문의/실측으로 확인(2개
      프로세스가 같은 approval key로 동시 연결 시 실제로 무슨 일이 일어나는지).
- [ ] "credential은 공유하되 프로세스는 분리 유지"하는 절충안이 가능한지 검토.
- [ ] 별도 계좌/appkey의 실제 회수·재발급 정책을 운영 조직에 확인해 시한을 구체화.
- [ ] 위 조사 결과가 나오면 "분리 유지" 결론을 재확인하거나 통합 설계 착수 여부를 재판단.

### ✅ 2026-07-10 선행 조건 검토 — 163 WS(장운영정보) 제거 가능성
- **결론: 제거 가능성 높음 — 별도의 장기 shadow 검증 없이 진행 가능.**
  `ops-scheduler`의 163 의존도를 코드 기준으로 분해한 결과, 실질적 게이팅
  효과(076이 놓칠 수 있는 장중 `HALT`/`UNKNOWN` 안전모드)는 **그날 최초
  세션 게이트 호출 시점** 한 순간으로 이미 제한적이며(`_session_gate()`가
  `session_info`를 하루 1회만 캐시), phase 전이 자체는 애초부터 163과
  무관한 고정 시계 상수(`PRE_MARKET_START` 등)로 결정된다.
- **결정적 실측 사실**: 현재 실제 배포 설정(`.env`)이 `KIS_ENV=paper`라서,
  `KisMarketStateClient.connect()`가 이미 매번 스킵되고 있다(paper 환경
  분기). 즉 `KIS_LIVE_INFO_ENABLED=true`로 credential이 설정돼 있음에도
  **현재 이 시스템은 이미 매일 163 없이(076-only 경로) 운영되고 있다** — 이건
  가정이 아니라 코드 로직으로 확정되는 사실이며, 076-only 경로의 안정성이
  이미 실증되고 있다는 뜻이다.
- **✅ 2026-07-10 추가 확인(사용자 판단) — 장기 관찰이 필요 없는 결정적 이유**:
  실제 주문 판단/제출이 5분 간격 배치(`DEFAULT_DECISION_INTERVAL_SECONDS=300`,
  `run_decision_loop.py`)로만 이뤄져 즉시 반응이 필요한 실시간 주문 경로가
  없다. 163이 막으려던 VI/거래정지 같은 tail 이벤트는, 설령 감지하지
  못해도 개별 주문의 안전성은 브로커(KIS) 응답 처리 레벨에서 별도로
  걸러진다 — 163은 그 위에 얹힌 "5분 배치를 하루 단위로 좀 더 보수적으로
  거르는 부가 필터"였을 뿐이다. 이 필터가 막던 리스크 자체가 이 시스템의
  실행 모델(저빈도 배치)과 애초에 맞지 않으므로, 장기 관찰(shadow 검증)
  없이도 제거 가능하다는 결론에 도달한다.
- 상세 근거(163의 정확한 역할 3가지, 검증 체크리스트, 참고용 shadow 비교
  방법론)는 `11_kis_realtime_quote_operations_screen.md`의 "163 WS(장운영정보,
  `ops-scheduler`) 제거 가능성 검토 메모"(2026-07-10 신설/갱신) 참고.

### ✅ 2026-07-10 credential 통합 구현 완료 — 최종 authoritative key = `KIS_LIVE_INFO_*`
- 163 WS 제거로 "당분간 분리 유지" 결론의 핵심 근거(프로세스 경계를 넘는 WS 세션
  소유권 문제)가 사라져, 같은 날 실제로 통합을 구현했다. **`KIS_REALTIME_QUOTE_*`가
  아니라 `KIS_LIVE_INFO_*`가 최종 authoritative credential이다** — 사용자 지시에
  따른 확정.
- `src/agent_trading/runtime/bootstrap.py::build_realtime_quote_source()`가
  `settings.kis_live_app_key`/`kis_live_app_secret`/`kis_live_info_base_url`/
  `kis_live_info_ws_url`(+ 신규 `kis_live_info_approval_cache_path`,
  env `KIS_LIVE_INFO_APPROVAL_CACHE_PATH`)을 authoritative credential로 쓰도록
  변경했다. 짧은 하위 호환을 위해 이 값들이 비어 있으면 legacy
  `KIS_REALTIME_QUOTE_*`로 fallback(경고 로그 포함)하되, `docker-compose.yml`/
  `.env.example`의 표준 설정에서는 `KIS_REALTIME_QUOTE_*`를 제거했다.
- `KisRealtimeQuoteSource`/`QuoteBroadcaster`/REST fallback 로직 자체는 수정하지
  않았다 — 순수 credential 초기화 경로 변경이며 기능 축소가 아니다.
- 검증: `tests/services/test_kis_realtime_quote_source.py`(legacy fallback
  신규 테스트 포함) + 실시간 현재가/scheduler/session 관련 테스트 283개를 DB
  없이 통과 확인, `docker compose config` 정합성 확인.
- 상세는 `11_kis_realtime_quote_operations_screen.md`의 "Credential 분리/통합
  판단 메모"(2026-07-10 통합 구현 상세 섹션 추가) 참고.

### 근거 문서
- [plans/[BACKLOG] backlog.md](./[BACKLOG]%20backlog.md) 항목 37
- [plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md](../plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md) — "Credential 분리/통합 판단 메모", "163 WS 제거 가능성 검토 메모"(둘 다 2026-07-10 갱신/신설, 통합 구현 상세 포함)
- [plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md](./[DESIGN]_kis_realtime_quote_operations_screen_plan.md)
- [plans/[DESIGN]_kis_realtime_quote_screen_ui_layout.md](./[DESIGN]_kis_realtime_quote_screen_ui_layout.md)

### 우선순위 이유
- 163 WS 제거에 이어 credential 통합까지 완료되어, 이 항목은 **완료 상태**다 —
  더 이상 P3 우선순위 판단 대상이 아니며 능동적으로 착수할 후속 작업이 없다.
- 남은 후속 조사(KIS appkey당 동시 세션 허용 여부 공식 확인 등)는 급하지 않은
  배경 조사 성격이라, 별도 일정 압박 없이 여유 있을 때 진행한다.
---

## 권장 실행 순서

> **📌 2026-07-14 근본 재정렬 (최신, 상위 우선)**: 근본 설계 검토 결과,
> "주문 0건"의 진짜 뿌리는 소싱이 아니라 **①목표-설계 불일치(방어 시스템에
> 공격을 기대) ②신호 예측력 미검증**임이 확인됐다. 이에 따라:
> - **종목 소싱 개선(UNIV-1~5) 트랙은 "차후 보류"로 강등** — 현 국면에서
>   소싱을 넓혀도 신규 종목이 같은 미검증 entry_score에 동일하게 억눌려
>   주문 발생에 영향 없음(2026-07-14 실측: 편입 19종목 전체가 buy threshold
>   0.65 미근접).
> - **목표 확정(2026-07-14): 목표 B(최고 기대수익률) — 사용자 결정.**
>   "손실 0이 목적이 아니라, 손실 최소화하며 리스크 감내 후 기대수익 추구"
>   = 허용 손실 제약 아래 net expected return 극대화. "주문 0건"은 성공이
>   아니라 실패(기회비용 + 실집행 검증 불가)다.
> - **새 1순위 = 신호 예측력 + `entry_score` + 전체 BUY funnel 검증** — 8종목
>   파일럿은 가설 생성으로만 인정하고, 통계 보정 확장 후 entry 산식과 중복
>   penalty를 재현해 Virtual BUY의 비용 차감 성과까지 검증한다.
> - 상세: `plans/[ANALYSIS] foundational_design_review_objective_alignment.md`
>   (undated canonical).
>
> **📌 2026-07-12 (이력)**: `core_risk_off`/`entry_score` 완화 전면 영구
> 중단 확정에 따라 소싱 개선(UNIV-1~5)을 1순위로 올렸으나, 위 07-14
> 재정렬로 강등됨. 소싱 트랙 상세는
> [`plans/[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`](./%5BDESIGN%5D%20universe_sourcing_momentum_overlay_enablement_v1.md) 참고.

### 1순위 묶음
0. **BUY 주문 0건 근본 복구 (2026-07-14 신설, 최우선)**
   - **SPPV-1(완료/결론 보류)**: core 8종목 pooled IC 파일럿. 예측 가능성
     가설은 확보했으나 overlap·군집 의존성 보정 전이라 입증으로 확정하지 않음.
   - **SPPV-2(완료, 2026-07-14)**: core 88종목 전체 × cross-sectional
     거래일별 IC/ICIR × Newey-West 보정 × 국면별 분해 × 비용 차감 quintile
     완료. **결과: SPPV-1의 낙관적 t-stat(2.4~4.1)은 overlap 편향이었음이
     확인됨 — 정확 보정 시 전 신호·전 horizon |t_NW|<1.1로 유의성 없음.**
     단 quintile spread(overall_score +3.88%p)는 방향성 있게 잔존.
   - **SPPV-2.5(완료, 2026-07-14) — ⚠️ 방법론 오류로 결론 폐기**: quintile
     spread 자체의 Newey-West 유의성 검정 + 국면 내부(within-regime) 분해
     시도. ~~결과: pooled spread(T+20 t_NW=2.30)는 유의하나 국면 내부
     어디서도 재현되지 않음 — 국면 혼입 착시~~ **→ 오류: `regime_label`이
     시장이 아니라 종목 자신의 신호(`market_regime.py:21-38`)로 판정되는
     라벨이었다(선택 편향). SPPV-2.6에서 정정.**
   - **SPPV-2.6(완료, 2026-07-14, 방법론 교정) — ⚠️ SPPV-2.7에서 표현
     하향 조정**: KODEX 200(069500) 시장 벤치마크 기준으로 거래일 단위
     공통 국면 + 초과수익 재검증. ~~결과: 국면 혼입 착시 결론 반박, 알파
     근거 강화~~ **→ 벤치마크를 평가 universe에도 포함시킨 자기참조 문제와
     1년(하락장 0일) 표본 한계가 있었다. 아래 SPPV-2.7에서 교정.**
   - **SPPV-2.7(완료, 2026-07-14, 자기참조 제거 + 3년 확장)**: 평가
     universe에서 벤치마크 제외(core 87종목) + 조회 기간 3년(733일봉)
     확장 — 시장 공통 하락장 96거래일(15%) 최초 확보. **결과:
     `overall_score` pooled spread 유의성 소멸(t_NW 2.30→1.32), 하락장
     내부 spread 음수 역전(T+5 t_NW=-1.71), `fast_score`는 하락장에서
     유의하게 역방향(T+5 t_NW=-2.79).** SPPV-2.6의 "알파 근거 강화"
     결론은 과도했음 — 하향 조정. 안정적 알파 미확인.
   - **SPPV-2.8(완료, 2026-07-14, 검증 기간 기준 재설계)**: 3개월 이하
     중단기 공격형 시스템 전제로 검증 기간 기준을 "3년 pooled 기본값"에서
     **최근 12개월(1차) + 3년(2차, 국면 게이트)** 이원 구조로 재설계.
     3년 캐시 재사용(신규 KIS 호출 0건)으로 최근 12개월 실측 —
     bearish_trend 0일(1차 창으로는 필수 국면 검증 불가), pooled 유의성도
     미확보(`overall_score` T+20 t_NW=1.18). §14 보류 판정 유지, 이후
     재검증부터는 이 이원 기준을 적용. 상세:
     `plans/[DESIGN] signal_predictive_power_validation.md` §16.
   - **SPPV-2.9(완료, 2026-07-14, 신호 feature 재설계 검토)**: `fast_
     score`/`slow_score`의 6개 sub-component 분해 + 신규 후보 feature
     (`risk_adj_momentum_3m`, `reversal_1m`) 검증. **결과: `rsi_signal`
     이 T+20에서 유의하게 역방향(t_NW=-2.94) — `fast_score` 실패 원인
     특정.** `risk_adj_momentum_3m`은 3년 pooled 유의(t_NW=2.07) +
     하락장 역전 없음으로 유일한 Watch 후보이나 1차 창 유의성 미달로
     완전한 Go는 아니다. `reversal_1m`은 하락장 조건부 후보로 분리
     검토 필요. SPPV-3 착수는 계속 보류. 상세:
     `plans/[DESIGN] signal_predictive_power_validation.md` §17.
   - **SPPV-2.10(완료, 2026-07-14, §17.5 후속 3과제)**: `fast_score_v2`
     (rsi_signal 제거/부호반전) shadow 2종, `risk_adj_momentum_3m` 1차
     창 18개월 확장, `reversal_1m` 하락장 반분 안정성을 실측. **결과:
     `fast_score_v2` 2종 모두 No-Go** — 하락장 T+5 spread가 원안과 거의
     동일하게 역전(drop -2.41/flip -2.32, 원안 -2.79) — `rsi_signal`은
     부분 원인일 뿐이었음. `risk_adj_momentum_3m`은 18개월 창 T+20
     t_NW=2.03으로 marginal 통과 — Watch 유지, 조건부 상향. `reversal_
     1m`은 반분 표본 개별 유의 미달 — Hold 유지. SPPV-3 착수는 계속
     보류. 상세: `plans/[DESIGN] signal_predictive_power_validation.md`
     §18.
   - **SPPV-2.11(완료, 2026-07-14, §18.6 후속)**: `fast_score`
     leave-one-out 4종 분해 + `risk_adj_momentum_3m` 창 경계 민감도
     (12~21개월) + 국면 전환형 shadow `regime_switch_v1` 검증. **결과:
     `fast_trend` 제거 시 하락장 T+5 spread가 -2.79→-1.60(비유의
     전환)으로 가장 크게 개선 — 주된 원인은 `rsi_signal`이 아니라
     `fast_trend`였음을 정정.** `risk_adj_momentum_3m`은 15~21개월
     창에서 T+20 t_NW 1.90→2.03→2.04로 안정적 plateau(우연 아님,
     marginal). `regime_switch_v1`(비하락장=risk_adj_momentum_3m,
     하락장=reversal_1m)은 2차(3년) pooled 트랙 최고 수치
     (T+5=2.60/T+20=2.36)를 냈으나 1차(최근 12개월)는 하락장 표본
     부재로 미달 — 가장 유망한 Watch 후보로 격상하되 확정 Go는 아니다.
     `fast_score`는 전면 재설계 대상으로 확정. SPPV-3 착수는 계속
     보류. 상세: `plans/[DESIGN] signal_predictive_power_validation.md`
     §19.
   - **SPPV-2.12(완료, 2026-07-14, §19.6 후속)**: `regime_switch_v1`의
     1차 게이트 예외 규칙 3개(A 관찰 유예/B 최근-실사례 고정창(n=48)/
     C 적응형 최소 국면 표본 창(최소 30일))를 정의·비교하고, fast 계열
     신규 feature 2종(`rsi_mean_reversion`, `sma5_over_sma20_gap`)을
     실측. **결과: 규칙 C가 n=30에서 t_NW=4.18로 급등하지만 n=48(규칙
     B)에서는 1.33에 불과 — "문턱을 넘을 때까지 창을 줄이는" 데이터
     스누핑으로 판정, 채택 거부.** 규칙 B는 정직한 재검증에서도 미달 —
     **규칙 A(관찰 유예, 하락장 재발 시 자동 재검증)를 유일하게
     채택**. fast 계열 신규 feature 2종 모두 범용 대체 후보로 No-Go —
     `rsi_mean_reversion`은 하락장 전용(t=2.26, `reversal_1m`과 동일
     패턴), `sma5_over_sma20_gap`은 SMA20과 동일하게 하락장에서 유의
     하게 역전(t=-2.67). SPPV-3 착수는 계속 보류. 상세:
     `plans/[DESIGN] signal_predictive_power_validation.md` §20.
   - **SPPV-2.13/2.14(완료, 2026-07-14, §20.5 후속)**: `regime_
     switch_v1` 규칙 A(관찰 유예)를 실행 가능한 모니터링 스크립트로
     구현(벤치마크 1종목만 조회, 신규 KIS 호출 0건) + 완전 신규 fast
     계열 feature 2종(`money_flow_5d`=자금 흐름 축, `relative_
     strength_rank_1m`=cross-sectional 상대강도 축) 실측. **결과:
     모니터링 판정 NOT_TRIGGERED(bearish_trend 0일, §20과 일치).** fast
     계열 신규 feature 2종 모두 범용 대체 후보로 No-Go — `money_
     flow_5d`는 방향성조차 없는 완전 무신호(|t|<1.2), `relative_
     strength_rank_1m`은 하락장에서 유의하게 역전(t=-2.13) — 시장 베타
     제거 상대강도조차 하락장에서는 반대로 작동한다는 규칙성 재확인.
     SPPV-3 착수는 계속 보류. 산출:
     `scripts/monitor_regime_switch_v1_gate.py`,
     `scripts/validate_signal_predictive_power_v10_new_fast_features.py`
     (둘 다 read-only, 신규 KIS 호출 0건),
     `logs/regime_switch_v1_gate_monitor_2026-07-14.json`,
     `logs/signal_ic_sppv2_14_new_fast_features_2026-07-14.json`. 상세:
     `plans/[DESIGN] signal_predictive_power_validation.md` §21, §22.
   - **SPPV-2.15(완료, 2026-07-15, 국면별 신호 극성 종합 및 상위 방향
     확정)**: SPPV-2.9~2.14의 10개 신호를 절대추세/오실레이터/자금흐름/
     상대강도/복합 5개 축으로 분류해 종합표로 정리(별도 문서
     `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_
     direction.md`). **결과: 8/10이 "추세형=상승/횡보 전용, 되돌림형=
     하락장 전용" 규칙성을 따름(`rsi_signal`만 상승장 역전 예외).**
     5개 축 모두 시도 후 동일 결론 수렴 + `regime_switch_v1`이 정적
     신호로는 얻지 못한 트랙 최고 2차 유의성을 국면 전환만으로 달성한
     것을 근거로 **feature 추가 실험을 중단하고 국면 분기형 entry
     설계 검토로 전환**을 확정했다. 유니버스/미시구조 재검토는 후순위
     유지. 상세: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_
     next_direction.md`.
   - **SPPV-2.16(완료, 2026-07-15, 국면 분기형 entry 설계 초안 +
     shadow 계산기)**: SPPV-2.15의 판정을 실제 설계 문서
     (`plans/[DESIGN] regime_conditional_entry_signal_v1.md`)로
     구체화 — 국면별 신호 선택 매트릭스, `entry_score` alpha layer
     교체 제안(미적용), shadow 검증 Phase 1/2 계획. **결과: shadow
     계산기 실행(2026-07-14 기준) — 시장 공통 국면 `range_bound`로
     87/87종목이 `risk_adj_momentum_3m` 분기 사용, 하락장 분기는
     미발동(§21 모니터링과 정합). `entry_score` 코드/운영 변경 없음.**
     산출: `scripts/shadow_regime_conditional_entry_signal.py`
     (read-only, 신규 KIS 호출 0건),
     `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`.
     상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md`.
   - **SPPV-2.17(완료, 2026-07-15, Phase 2 shadow 누적 사이클
     구축)**: Phase 2를 실행 가능한 오케스트레이터
     (`scripts/run_regime_conditional_shadow_cycle.py`)로 구현 —
     게이트 판정(§21)과 신호 계산(§22)을 벤치마크 1회 조회로 통합,
     누적 이력 파일(JSONL, 중복 거래일 자동 skip) 구축, `TRIGGERED`
     전환 시 재검증 runbook 출력. **결과: 게이트 NOT_TRIGGERED, 신호
     2026-07-14 기준 `range_bound`로 87/87종목 `risk_adj_momentum_3m`
     분기 — 이력에 1줄 추가, 재실행 중복 방지 확인.** `entry_score`
     코드/운영 변경 없음. 산출:
     `logs/regime_conditional_signal_shadow_history.jsonl`. 상세:
     `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §6.
   - **SPPV-2.18(완료, 2026-07-15, entry_score 중복 penalty ablation
     실측)**: SPPV-3 착수 전제("중복 억제 구조 재현·분해")를 실측으로
     구체화 — 운영 함수(`_build_entry_score`, `_assess_buy_
     eligibility`)를 그대로 호출해 오늘(87종목) 기준 세 penalty 축을
     독립 평가. **결과: 축 A(entry_score regime penalty) 85건, 축
     B(eligibility regime 차단) 60건, 축 C(eligibility signal floor)
     75건 — B가 발동한 60건은 예외 없이 A·C도 함께 발동
     (A∩B∩C=60=B 전체)** — §2의 "삼중 중복"이 오늘 데이터로 100%
     재현됨. 종목별 regime_label(bearish_trend 69%)이 시장 공통
     국면(`range_bound`)과 전혀 다름을 재확인 — `entry_score` 통합
     시 국면 정의(종목별 vs 시장 공통) 통일이 새로운 전제로 필요함을
     발견. 운영 DB 직접 조회는 자동 승인 경계 밖으로 판단돼 시도하지
     않았다. 산출: `scripts/shadow_entry_score_penalty_ablation.py`
     (read-only, 신규 KIS 호출 0건),
     `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`.
     상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §8.
   - **SPPV-2.19(완료, 2026-07-15, 중복 억제 시계열 누적 + 국면 정의
     비교 체계 구축)**: §8의 하루치 관찰을 시계열 누적 절차로 승격 —
     신규 오케스트레이터(`scripts/run_entry_score_penalty_ablation_
     cycle.py`)가 penalty 축 A/B/C와 시장 공통 국면을 같은 실행에서
     계산해 누적 이력(`logs/entry_score_penalty_ablation_history.
     jsonl`, 중복 거래일 자동 skip)에 기록. **결과: §8과 동일한
     수치(A=85/B=60/C=75/A∩B∩C=60)로 교차 검증, 국면 일치 18건/
     불일치 69건(79%)** — "시장 비하락장인데 종목별 하락장" 60건.
     재실행으로 중복 방지 정상 발동 확인. SPPV-3 본작업용 비교
     실험(현행 종목별 정의 vs 시장 공통 정렬, §16 이원 기준 재사용,
     기존 3년 캐시로 신규 KIS 호출 없이 수행 가능)을 §9.6에 설계.
     상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §9.
   - **SPPV-2.20(완료, 2026-07-15, §9.6 비교 실험 실측)**: 종목별 vs
     시장 공통 regime 정의 비교 실험을 실제로 실행 — 운영 `_assess_
     buy_eligibility()`를 그대로 호출해 변형 A/B 각각의 통과군
     T+5/T+20 forward return을 §16 이원 검증 도구로 비교. **결과:
     변형 B가 통과율은 더 낮으면서(18.75%<20.64%) 통과 종목의
     forward return은 더 높음(T+5 +1.04%>+0.93%, T+20 +3.58%>+3.19%,
     둘 다 baseline 대비 유의, t_NW 7.3~7.7)** — 과잉 억제가 아니라
     정밀한 억제 가능성. A-B 차이 직접 유의성 미검정, 통과군 내부
     quintile spread 여전히 유의하게 역전(T+20 t_NW=-2.84~-3.06) —
     **판정 Watch(조건부 유리, 확정 Go 아님)**. 실행 로그 확인 결과
     `HTTP Request:` 0건(가정 아닌 실측 확인). 산출:
     `scripts/validate_entry_score_regime_definition_comparison.py`
     (read-only, 신규 KIS 호출 0건),
     `logs/signal_ic_entry_score_regime_definition_comparison_
     2026-07-15.json`. 상세: `plans/[DESIGN] regime_conditional_
     entry_signal_v1.md` §10.
   - **SPPV-2.21(완료, 2026-07-15, A/B 판정 불일치 표본 direct 비교 +
     1차 창 재확인)**: 같은 종목-거래일 표본을 A_only/B_only/both/
     neither 4개 배타적 집합으로 분해. **결과: B_only가 3년·1차 창
     모두 0건 — 시장 공통 정의(B)는 종목별 정의(A)의 진부분집합일
     뿐, 새 종목을 발굴하지 않고 A 통과분 일부(A_only, 1,072건)를
     추가 차단만 함을 구조적으로 확인.** A_only의 forward return은
     방향상 음수(T+5 -0.17%, T+20 -0.70%)이나 유의하지 않음
     (|t_NW|<1). 최근 12개월은 A-B 차이 자체가 없음(§21 모니터링과
     정합). **판정: Watch 유지(No-Go에 근접), 확정 전환 기각.** 실행
     로그로 KIS 호출 0건 확인(가정 없이 실측). 산출:
     `scripts/validate_entry_score_regime_definition_ab_diff.py`
     (read-only, 신규 KIS 호출 0건),
     `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`.
     상세: `plans/[DESIGN] regime_conditional_entry_signal_v1.md` §11.
   - **SPPV-2.22(완료, 2026-07-15, alpha layer vs regime_conditional_
     signal 직접 비교)**: 무게중심을 국면 정의 통일(차단)에서 alpha
     layer 교체(선별)로 이동. 현행 alpha layer와 regime_conditional_
     signal을 같은 3년 표본에서 직접 비교. **결과: 2차(3년) 창에서
     regime_conditional_signal이 T+5(t_NW=2.52)/T+20(t_NW=2.33) 둘
     다 유의, 현행 alpha layer는 어디서도 비유의(1.02~1.39) — 4개
     관측치 전부 일관되게 우세.** 1차 창은 미달이나 §21 구조적
     이유(하락장 부재) 때문. **판정 Conditional Go(2차 검증 통과,
     1차 게이트 전환 대기).** 실행 로그로 KIS 호출 0건 확인. 산출:
     `scripts/validate_alpha_layer_vs_regime_conditional_signal.py`
     (read-only, 신규 KIS 호출 0건),
     `logs/signal_ic_alpha_layer_vs_regime_conditional_signal_
     2026-07-15.json`. 상세: `plans/[DESIGN] regime_conditional_
     entry_signal_v1.md` §12.
   - **SPPV-3(보류 유지, 형태 재정의)**: §2.16~§2.21에서 국면 정의
     통일(차단 축)은 Watch/No-Go에 근접한다는 것이 확인됐으나,
     **§2.22에서 alpha layer 교체(선별 축)는 2차 창에서 유의한 우위를
     확보(Conditional Go)했다.** 다음 착수 형태는 이 설계 문서를
     기반으로 regime/allocation/strategy/source를 복원한 `entry_score`
     point-in-time 재현과 signal/risk-off/regime eligibility 중복
     억제 ablation이며, 우선순위는 "국면 정의 통일"이 아니라 "`regime_
     conditional_signal`을 alpha layer에 직접 통합"하는 쪽이다. 착수
     전제(1차 게이트 `TRIGGERED` 전환 관측)는 사용자
     확인 필요(§14.5, §17.5, §18.6, §19.6, §20.5, §23).
   - **SPPV-4**: Virtual BUY의 `candidate → selected → expected value → would_buy
     → submitted`, MFE/MAE/낙폭/비용 차감 기대수익 비교.
   - **SPPV-5**: out-of-sample 기대수익 양수와 손실 제약을 모두 만족한 공식만
     shadow 유지. 후보 수 증가만으로 Go 금지.
   - **SPPV-6**: 별도 승인 후 일일 top-k·최소 수량·계좌 위험한도 아래 제한적
     paper probe. risk/compliance/guardrail/broker 경계 유지.
   - 기준 문서: `plans/[DESIGN] signal_predictive_power_validation.md`.

0.1. **종목 소싱 구조 개선 (2026-07-12 신설, 07-14 기준 차후 보류)**
   - UNIV-1(완료): market_overlay용 라이브 read-only client 주입 배선 실측 —
     **배선은 이미 존재·정상 동작**함을 확인(원래 "paper 게이트로 비활성"
     가설은 틀렸음). 3개 silent debug 로그를 warning으로 격상 완료.
   - UNIV-2(완료): 실측 결과 진짜 원인은 intraday freeze materialize 시각
     (08:50, 장 시작 전)과 F5 누적거래대금 필터의 경합 — 08:50 freeze 시
     당일 누적거래대금 0으로 전 후보 탈락. 09:00 이후 freeze된 날(07-03)은
     정상 동작(5건 편입) 확인.
   - **UNIV-1-fix 범위 조사(완료)**: freeze 시각 이동은 8개+ 문서에 하드코딩된
     08:50 경계 때문에 blast radius 과다로 부적합, threshold 완화는 금지
     원칙 위배 → 전일 거래대금 fallback을 채택하되 **UNIV-3에 통합**하기로
     결정(중복 API 연동 방지).
   - **UNIV-3(1순위) 구현 완료(2026-07-12)**: F5 pre-market fallback shadow +
     멀티데이 모멘텀 shadow(상대 거래량 급증/5·20일 수익률/반등 플래그)
     모두 구현 완료 — 둘 다 실제 선정/스코어링에는 미반영(shadow-first),
     테스트 106건 통과. 라이브 검증 중 `get_daily_price()` dict/객체 응답
     형태 불일치 버그 발견·수정.
   - **UNIV-3 다음 단계**: 코드 작업이 아니라 **수일 관측 후 승격 판단**
     (F5 fallback/모멘텀 신호 shadow 로그의 후행 proxy 개선 여부 확인).
   - **UNIV-4(2순위) 완료(2026-07-12)**: KIS 지수 구성종목 API 부재 확인 →
     staleness 감시 축소안 구현(`get_latest_effective_from()` +
     `evaluate_index_membership_staleness()`) + 운영 대시보드 노출까지 완료
     (`GET /instruments/index-membership/staleness` + `OperationsDashboardView`
     WarningBanner). 실측: age=15일(threshold 21일) → 정상.
   - **다음 착수 대상**: UNIV-5(core 장기 하락 종목 후순위화) 착수 여부
     재검토 — 단, UNIV-3 관측(수일 누적) 완료 후 판단.
0.5. **KIS 토큰 캐시 통합(appkey당 1개) (2026-07-13 신설, universe sourcing과
     무관한 별도 트랙)** — 상세: `plans/[BACKLOG] backlog.md`
   - 같은 `KIS_LIVE_INFO_APP_KEY`가 076 holiday client와 공시/시세
     client에서 서로 다른 캐시 파일(`kis_live_oauth_token.json` vs
     `kis_disclosure_token.json`)로 분산돼 있어, cold start 시 동일
     appkey로 `oauth2/tokenP`가 중복 발급될 위험(`EGW00133`) 확인.
   - 정책 확정: (1) 트레이딩 계좌 live는 기본 비활성화 유지(paper 기준),
     (2) `KIS_LIVE_INFO_*` 정보성 credential은 live 활성화 유지, (3) 같은
     appkey에는 캐시 파일 1개만 사용하도록 통합.
   - 관련 문서 갱신 완료: `plans/kis_dev_token_cache.md`,
     `plans/kis_oauth_cache_centralization_2026-05-17.md`,
     `plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`.
   - **구현 완료(2026-07-13)**: `KISHolidayClient`에 `share_rest_access_token_cache`
     옵션 추가 — 076 client가 disclosure/시세 client와 동일한 cache_purpose
     (`LIVE_DISCLOSURE_ACCESS_TOKEN`)/fingerprint 스킴으로 `kis_disclosure_token.json`
     을 공유하도록 `market_session.py` 수정. `run_ops_scheduler.py`의 진단
     summary도 갱신. **cold start 실측 검증 완료** — 캐시 삭제 후 076
     client가 토큰 발급+저장 → 곧바로 disclosure client가 같은 파일에서
     캐시 hit(추가 `oauth2/tokenP` 호출 없음) 확인
     (`logs/token_cache_unification_verify_2026-07-13.log`). 테스트 242건
     통과(회귀 없음).
1. Fill History Phase 3
2. 부분체결 자동 판정 고도화
3. fill 발생 후 snapshot refresh 자동화

### 2순위 묶음
4. 다음 거래일 장중 실운영 검증
5. KIS real credential smoke
6. 운영일 상태 관리

### 3순위 묶음
7. KIS token cache 공통 모듈화
8. 장 운영 세션 정보 저장
9. KIS 기본종목정보 적재/갱신

### 4순위 묶음
10. Data Quality / Hard Guardrail 일원화
11. Universe / Signal / Strategy / Portfolio / Compliance / Monitor 구조화
   - 단, 다음 단계는 단순 agent 추가가 아니라
     `deterministic trigger / candidate / attribution` 구조를 세우는 방향이어야 한다.
   - 기준 문서:
     [`plans/[ANALYSIS] expected_return_architecture_refactor_analysis.md`](./%5BANALYSIS%5D%20expected_return_architecture_refactor_analysis.md)

---

## 정리

현재 가장 중요한 남은 일은 UI가 아니라 다음 세 가지다.

1. **체결 진실을 더 직접적으로 쓰는 구조 완성**
   - fill snapshot을 주문 상태 수렴의 주 진실원으로 강화
2. **장중 운영 검증**
   - 최근 수정이 실제 다음 거래일에도 정상 동작하는지 실측
3. **운영 기반 데이터 정리**
   - 운영일 상태, 세션 정보, 종목 master, KIS token/config 기술부채 정리
4. **Agent 책임 분리**
   - 다만 이것은 AI agent 추가가 아니라, deterministic 계층과 hybrid 해석 계층을 올바르게 나누는 작업이어야 한다

즉, 앞으로의 우선순위는 다음 한 줄로 요약된다.

> **체결 진실 강화 → 장중 실운영 검증 → 운영 메타데이터 정리 → deterministic guardrail 정리 → 전략/에이전트 구조화**
