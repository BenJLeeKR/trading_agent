# 국면 분기형 진입 신호 설계 (regime_conditional_entry_signal v1)

작성일: 2026-07-15
상태: **설계 초안 + shadow 계산기 1차 실행 완료 + Phase 2 누적 사이클
구축·실행 완료(§6) + entry_score 중복 penalty ablation 실측 완료(§8) +
중복 억제 시계열 누적·국면 정의 비교 체계 구축(§9) + §9.6 비교 실험
실측 완료(§10) + A/B 불일치 표본 direct 비교·1차 창 재확인 완료(§11) +
**alpha layer vs regime_conditional_signal 직접 비교 완료(§12,
2차 창에서 유의한 우위 확인 — Conditional Go)** + **새 alpha 상위군과
기존 차단 축 결합 효과 검증 완료(§13, 당시 해석은 §14로 보정됨) —
가장 빈번한 차단 사유는 regime 축이 아니라 별개의 활동성(activity)
필터임을 신규 발견, 결합 판정 Watch(추가 검증 필요)** + **활동성
필터 정밀 ablation 완료(§14, 2026-07-16
해석 보정 반영) — 완전 제거는 No-Go(기대수익률 개선 근거 없음)로
확정, 임계값 1.10→1.00 완화는 방향은 유력하나 Watch(추가 검증
필요, "주범 확정"·"과잉 억제 확정"·"제거 시 개선" 결론은 보류)** +
**threshold sweep + 기간 분할 재현성 검증 완료(§15, 2026-07-16) —
완화 효과가 3년의 전반부에서는 재현되지 않고 정반대로 나타나
Watch 유지(격상 근거 없음, 오히려 신중론 강화)** + **반전 원인
분해 완료(§16, 2026-07-16) — 국면 구성 차이(전반부 혼합/약세 편중
vs 후반부 강세장 82.9% 편중)와 유동성 구조 확대(거래대금 중앙값
약 1.9배)가 결합된 결과로 판단, 정적 완화안은 여전히 Watch 유지** +
**alpha layer 교체 BUY funnel(candidate→eligible→would_buy→blocked)
검증 완료(§17, 2026-07-16) — would_buy 단계 forward return이 4개
창·2개 horizon 전부에서 새 alpha가 우세(방향 반전 없음, 활동성
필터 완화와 대비됨), Conditional Go 유지·보강되나 3년 전반부
비유의라 확정 Go는 아님** + **virtual BUY funnel 확장 검증 완료
(§18, 2026-07-16, candidate→eligible→selected(운영 0.65 문턱)→
would_buy) — 방향 우위는 재확인됐으나, 새 alpha는 이 0.65 문턱이
4개 창 전부에서 100% 통과(사실상 무력화)되는 계측 caveat 발견,
MAE(하방 이탈)도 일관되게 더 큼 — Conditional Go 유지, 확정 Go는
아님** + **entry_score 스케일 재보정 shadow 검증 완료(§19,
2026-07-16) — percentile 기반 재보정(R3)이 문턱 회복(100%→
93.7~96.5%)과 forward return 개선(8/8 창·horizon)을 동시에 만족,
가중치 축소(R1)·z-score(R2)는 기각, R3는 유력 후보로 격상되나
확정 Go는 아님** + **R3 재현성 검증 완료(§20, 2026-07-16) — 분기
4분할로 재검증하자 R3가 2/4분기에서 오히려 R0보다 못함을 발견,
"8/8 재현" 주장은 거친 분할에서만 성립하는 착시로 판명 — R3 판정을
다시 Watch로 하향, candidate 내부 percentile 변형(R3b)이 8/8
재현되지만 선택률 급감으로 별도 검증 필요한 신규 관찰 대상으로
등록** + **R3b 엄격 재검증 + R3 실패 원인 분해 완료(§21,
2026-07-16) — R3b가 R1이 실패한 엄격 기준(8개 창 전부 개선)을
통과하고 overlap 진단(R0와 47~61%만 겹침)으로 표본 축소 착시가
아닌 실제 재선별 효과로 잠정 판단, R3b를 유력 후보로 신규 격상
(Watch→Conditional Go 경계, 확정 Go는 아님); R3 실패는 국면/유동성
분포로 설명되지 않고 R0와 77~85% 겹치는 "미세 재조정"이라는
구조적 취약성으로 잠정 판단, R3는 Watch 유지** + **R3b 대응표본
(paired) 검증 완료(§22, 2026-07-16) — 같은 거래일 대체 종목쌍의
forward return을 직접 비교하자 분기3에서 대체 효과가 음수로
뒤집히고 다수 창에서 t_NW가 marginal함을 확인, §21의 overlap만으로
"재선별 효과 증명"한 것은 근거 부족이었음을 정정 — R3b를 다시
Watch로 하향, R3는 Watch 유지(오히려 근거 강화)** + **R3b
aggregate 우위 원인 3분해 완료(§23, 2026-07-16) — common_kept/
dropped_only/added_only로 분해한 결과 aggregate 우위는 added_only의
실제 우수성과 R0 자신의 저품질 dropped_only 비중이 큰 구성 효과가
함께 기여함을 확인, 분기3에서 pooled와 paired 지표의 부호가
정반대로 갈려 효과가 특정 스왑 밀집일에 집중된 비대칭 구조임을
시사, 원인 규명에 집중하고 재격상 없이 R3b/R3 Watch 판정 유지;
§22의 "t_NW≥1.96 창 2개" 서술도 3개(분기1 누락)로 정정** + **날짜
집중도 검증 + 교체효과/구성효과 정량 분리 완료(§24, 2026-07-16) —
스왑 상위 10% 거래일 제거해도 8개 창 중 7개는 우위가 80~120%
수준으로 유지(집중형 아님), 정확한 항등식 분해로 §23의 "구성효과
기여" 서술이 방향 오류였음을 정정(구성효과는 오히려 음(-)으로
우위를 상쇄, 우위 전체는 순수 replacement_effect에서 옴), 분기3만
유일하게 소수 거래일 집중형(잔존비율 30~65%)임을 확인 — 재격상
없이 R3b/R3 Watch 판정 유지** + **분기3 스왑 집중일 세부 진단 +
SPPV-2.34 문구 정밀 보정 완료(§25, 2026-07-16) — composition_effect
"8개 창 중 6개 음(-)" 표현을 horizon 구분(T+20 8/8 음(-), T+5
5/8 음(-))으로 정정, 분기3 거래일별 세부 진단 결과 "소수 날짜에
몰린 착시"가 아니라 **대형 스왑일(상위 10%, 약 8일)은 순기여
양(+)이고 나머지 다수(약 75일)의 소규모 스왑일에서 완만한 음(-)
효과가 누적**되는 구조로 정밀화, 이벤트/실적 연관은 2025-02-12~13
연속 악재일에 한해 정황(가설) 수준 — 재격상/재하향 없이 R3b/R3
Watch 판정 유지** + **분기3 대형/소규모 스왑 구조 정밀 확정 완료
(§26, 2026-07-17) — 5분위 구간화 결과 "대형=양(+)/소규모=음(-)"은
양극단(Q1·Q5)에서만 성립하고 중간(Q2~Q4)은 혼재(Q4는 소규모인데도
양(+)), "대형 스왑일 전적 의존"은 과장으로 정정(aggregate 순
기여는 T+5 70%/T+20 35%로 상당하나 총 양(+) 합계의 15%에 불과 —
독점 아님), 2025-02-12~13 제거는 분기3 음(-) paired 평균의 약
39%만 설명 — 재격상/재하향 없이 R3b/R3 Watch 판정 유지** +
**R3b의 SPPV-3 진입 후보 여부 최소 검증 완료(§27, 2026-07-17) —
실제 BUY funnel(candidate→eligible→selected→would_buy) 8개 창
재확인 결과 T+20 평균 우위 8/8 일관, t_NW 6/8 유의(2개 marginal),
**신규**: would_buy 모집단의 거래일 편중도 계측 결과 거래일 집중
의존은 R3b 고유 문제가 아니라 R0(현행 기준선) 자체가 8개 창 중
3개(전반부/분기1/분기2)에서 상위 10%일 제거 시 평균이 마이너스로
뒤집히는 alpha 신호 계열 전반의 특성이며, R3b는 8/8 창에서 R0보다
그 의존도가 더 낮음(더 견고) 확인 — **R3b를 Watch에서 Conditional
Go로 상향(조건부: selected_rate 급감의 총 기대수익 영향 정량화,
§3 전제조건 충족, point-in-time 파이프라인 반영 shadow 실행 등
확정 Go 전 잔여 검증 필요)** + **SPPV-2.37 수치 정정 + Conditional
Go 재평가 완료(§28, 2026-07-17) — R0 음(-) 반전 창 수 3개→4개
(2차 포함), 양수 비율 열세 창 수 3/8→1/8(T+20)·0/8(T+5), selected_
rate 표현("급감 30~40%"→"R3b 자신의 비율 29.9~39.2%, R0 대비
약 61~70%p 감소") 정정 — 세 정정 모두 R3b의 방향성 우위를 약화
시키지 않아 **Conditional Go 유지**(잔여 조건 불변) + **selected_
rate 감소의 총 기대수익 영향 정량화 완료(§29, 2026-07-17) — 거래
빈도×종목당 평균수익 총 기대수익 proxy를 8개 창×2horizon(16개
조합) 전부 계측한 결과 **14/16 조합에서 R3b 총proxy가 R0보다
높음**(92.0%~322.6%, 나머지 2개도 거의 동률) — "거래 빈도 감소가
총 기대수익을 훼손하는가"에 명확히 "아니다"로 답해 **Conditional
Go 유지 + 확정 Go 전 잔여 조건 4개 중 1개(조건 2) 해소** +
**유휴 자본 반영 보강 검증 완료(§30, 2026-07-17) — 전체 거래일
수×3슬롯을 R0 평균으로 100% 채웠다고 가정하는 엄격 기준으로
재검증한 결과 **T+20은 8개 창 중 7개에서 여전히 R3b가 우위**(견고)
이나 **T+5는 8개 창 중 6개에서 우위가 사라지거나 이미 열세**(취약)
— §29의 "조건 (2) 해소"는 과장이며 정확히는 **"T+20 중심으로는
완화, T+5는 여전히 미해결"** 수준으로 재조정, **Conditional Go
유지**(확정 Go는 아님) + **R3b Conditional Go의 운영 horizon 적합성
판단 완료(§31, 2026-07-17) — 코드 조사 결과 `deterministic_
trigger_engine.py`의 SELL/청산은 100% `exit_score`(신호/점수)
기반이고 경과일수를 전혀 참조하지 않으며, `max_holding_days=20`은
AI Risk agent의 LLM 출력 힌트 기본값일 뿐 실제로 20일 뒤 매도를
강제하는 코드 경로가 없음을 확인 — **"이 시스템이 T+20 중심이라
T+5 약점을 무시해도 된다"는 주장은 코드로 뒷받침되지 않는다**,
기존 §16 Go/No-Go 표준(T+5·T+20 동시 요구)이 이미 타당했음을
재확인 — **R3b는 Conditional Go 유지, 단 T+5 강건성 확보(또는
실제 청산 시점 분포 실측)를 확정 Go의 필수조건으로 격상** +
**R3b를 point-in-time `entry_score` 파이프라인에 반영한 shadow
검증 완료(§32, 2026-07-17) — 기존 검증이 이미 `build_signal_
snapshot`/`_assess_buy_eligibility`/`_build_entry_score` 등 실제
운영 함수를 호출해왔음을 확인, 다만 실제 `strategy_selection`
조정항(+0.05 보너스)이 그동안 `None`으로 누락돼 있었던 것을 실제
`select_strategy()` 호출로 채워 A/B 양쪽에 공정하게 반영 — 8개
창×2horizon(16개 조합) 전부에서 R3b>R0 방향 유지(방향 붕괴 없음),
다만 **분기1 T+20의 t_NW가 1.31→0.96으로 더 약화**돼 기존 marginal
우려가 심화됨 — **Conditional Go 유지, "point-in-time 파이프라인
반영" 조건은 부분 해소(portfolio_allocation gap은 여전히 미해결)** +
**분기1 t_NW 약화 원인 정밀 진단 완료(§33, 2026-07-17) — 분기1은
세 분기 중 가장 "혼합 국면"(강세/횡보/약세 고른 분포 + event_
driven_unstable 최다) 구간이며, R3b>R0 방향은 그대로 유지(스왑일
71.7%가 양(+), 세 분기 중 최다)되나 상위 스왑일 10건 중 3건이
±16~44%p의 극단치라 표준오차가 커져 t_NW가 낮아진 것으로 확인 —
**방향성 붕괴가 아니라 소수 극단치로 인한 분산 문제로 좁혀짐,
Conditional Go 유지(Watch 하향 근거 없음, 잔여 리스크 성격만
구체화)** + **SPPV-3 진입 관문 3종 종합 판정 완료(§34, 2026-07-17)
— §3 게이트(`regime_switch_v1` 1차 게이트) 재실행 결과 `NOT_
TRIGGERED` 재확인(최근 12개월 bearish_trend 0/30일), 분기1 약화는
관리 가능한 잔여 리스크(§33), T+5 취약성은 미해결이나 치명적
근거도 없음(§31) — **Conditional Go 유지, 다만 SPPV-3(운영 코드
반영) 진입은 아직 이르다 — 주된 차단 요인은 R3b 성과와 무관한
§3 게이트(시장에 하락장 미도래)이며, 이는 규칙 A(관찰 유예)에
따라 인위적으로 앞당길 수 없다** + **SPPV-2.44 산출물 파일명/
실행 경로 불일치 정정 완료(§35, 2026-07-17) — `monitor_regime_
switch_v1_gate.py`는 실행 시점과 무관하게 항상 하드코딩된
`..._2026-07-14.json`에 저장하며, §34가 인용한 `..._2026-07-17.
json`은 그 결과를 호스트로 복사하며 수동 재명명한 사본(내용은
이번 재실행 결과 그대로, 결론 영향 없음) — **결론 유지, 기록만
정정** + **R3b 채택 시 `risk_off_penalty` 중복 해소 ablation 완료
(§36, 2026-07-17) — A(현행)/B(entry_score risk_off_penalty 제거)/
C(eligibility risk_off 축 완화) 3개 시나리오 실측 결과, **C는 A와
완전 동일**(eligibility 축이 R3b candidate pool에서 단 한 건도
걸리지 않는 비활성 축임을 확인) — 중복 우려는 애초에 발생하지
않음. **B는 T+20 총 기대수익 proxy가 2차 +20.9%/1차 +20.5% 개선**
되나 MAE도 소폭 악화(약 0.5%p) — "공짜 개선"이 아닌 실제
트레이드오프. §3 조건 ②를 "미착수"→"방향 확인, 사용자 승인 대기"
로 진전 — **Conditional Go 유지, SPPV-3 진입은 §21 게이트
미충족으로 여전히 이름(불변)** + **승인 범위 확정(entry_score
축만, eligibility 축 제외) + risk_off_penalty 완화안 심층 해석
완료(§37, 2026-07-17) — §36의 A/B 산출물을 재사용(신규 실행 없음)
해 T+5/T+20 양쪽에서 총 기대수익 proxy가 12.9~20.9% 개선되고
t_NW도 함께 개선되며, MAE 악화(5.9~7.8% 상대)는 개선폭보다 작아
정당화 가능한 트레이드오프임을 확인 — **Conditional Go 보강**
(entry_score 코드 반영은 게이트 충족 후 별도 절차) + **SPPV-2.47
"게이트 하나만 남았다" 표현 정밀화 완료(§38, 2026-07-18) — §3
전제조건(게이트+risk_off_penalty 중복) 자체는 게이트만 남았다는
서술이 정확하나, "SPPV-3 진입"을 위해서는 §3 외에도 T+5 구조적
리스크(§31)·혼합 국면 재확인(§33)·`portfolio_allocation` gap(§32)
등 별도 조건이 여전히 열려 있어 "사실상 게이트 하나"는 과장 —
**주된 차단 요인(§21 게이트)과 보조 잔여 조건을 분리해 재정리**,
Conditional Go 유지(방향 후퇴 아님) + **혼합 국면(분기1 유형)
재확인 완료(§39, 2026-07-18) — 분기1(혼합 국면)과 대조되는
분기4(시장 공통 국면 사실상 순수 bullish 98.2%)를 승인된 B
시나리오(R3b+risk_off_penalty 제거)로 계측한 결과, 분기4는 T+20
t_NW 3.00·양수율 60.3%로 강하고 일관되나 분기1은 t_NW 1.27·
양수율 46.2%로 marginal — "혼합 국면→약한 t_NW" 가설이 표본 1개의
우연이 아니라 대조쌍으로 확인됨 — **조건 해소는 아니나 "미확인
가설"에서 "확인·추적 대상 패턴"으로 전진, Conditional Go 유지** +
**"혼합 국면 약세" 가설 직접 분해 완료(§40, 2026-07-18) — 거래일
단위 60일 trailing 혼합도를 3분위 버킷화(634거래일)한 결과 저혼합
(t=3.64,양수율63.3%)→중혼합(t=2.51,56.8%)→고혼합(t=0.37,38.7%)
으로 T+5/T+20 전부 단조 감소 — 분기 경계와 무관한 연속 변수
자체가 성과와 연동돼 **"지지 증거"에서 "구조적 패턴"으로 격상**,
다만 방향성 붕괴는 아님(고혼합도 평균은 여전히 양(+)) — SPPV-3
착수를 추가로 차단하는 사유는 아니며 착수 후 모니터링 대상,
Conditional Go 유지 —
실거래/`entry_score` 반영 없음.** **[SPPV-2.51에서 정정, §40.6]**
**"구조적 패턴으로 확정"은 과장 — 같은 in-sample 3년 캐시 재확인
+ 60일 trailing window 자기상관 때문에 정확한 표현은 "강한 구조적
정합 증거로 격상"이다. 또한 "§21 게이트 하나뿐"은 "SPPV-3 착수
검토의 유일한 주된 차단 요인"이라는 뜻이지 "진입 전체의 유일한
남은 조건"이 아니다(§38의 ①②③ 분류 불변) — 두 정정 모두 R3b
방향성·Conditional Go는 바꾸지 않는다. +
**T+5 구조적 리스크 부분 완화(§41, SPPV-2.52, 2026-07-18) — 실제
운영 함수 `_build_exit_score`를
point-in-time으로 재호출해 would_buy candidate 1151건의
signal-driven 청산 타이밍을 시뮬레이션한 결과, 91.1%가 20거래일
안에 매도 신호(0.75)를 넘지 않고 평균 보유일수=19.35일 — 즉 실제
청산 로직 기준으로는 T+5가 아니라 T+20 근방에서 청산되며, 그
수익률(평균 6.14%, t=4.73)은 T+5(2.02%, t=4.18)보다 T+20(6.49%,
t=3.87)에 훨씬 가깝다. "T+5 평균이 약하다"는 우려는 실제 운영
리스크로 그대로 전이되지 않는다 — 다만 20일 초과 구간의 청산
분포·경로 리스크(MAE)는 미검증이라 "완전 해소"는 과장, 정확히는
"부분 완화". Conditional Go 유지, 실거래/운영 코드 변경 없음.** +
**T+5 리스크 확장 검증(§42, SPPV-2.53, 2026-07-18) — 관찰 창을
20→60거래일로 늘려 would_buy 1048건을 재시뮬레이션한 결과,
censored 비율 91.1%→51.3%로 감소, 평균 보유일수=48.0일, signal-
driven 청산 수익률(9.29%, t=5.38)이 오히려 고정 T+20(4.46%, t=3.41)
보다 강함. 다만 이 검증으로 MAE(경로 리스크) 평균 -11.08%, 심각
손실(-20% 이하) 비율 12.8%, 강제 손절 임계값 부재가 새로 드러나
§38 보조 잔여 조건에 "경로 리스크·손절 정책 부재"를 신규 추가.
Conditional Go 유지, 방향성 반전 아님, 운영 코드 변경 없음.** +
**[SPPV-2.54에서 정정, §43] "거의 해소"는 과장 — 20일판(1151건)과
60일판(1048건)은 코드 대조 결과 완전히 동일한 표본이 아니다(60일판
이 20일판의 약 91% 부분집합으로 추정, 끝부분 약 40거래일이 60일판
스캔에서 제외됨) — 엄밀한 페어드 전/후 비교가 아니다. 또한 60일
관찰 후에도 과반(51.3%)이 여전히 censored라 "거의 해소"라고
부르기엔 이르다. 정확한 표현은 **"추가 완화"**(§41의 부분 완화보다
한 단계 더 나아갔으나 완전 해소는 아님). 60일판 표본 내부 비교
(signal-driven 청산이 T+20보다 강하다는 것, MAE 분포)는 그대로
유효 — R3b 방향성·Conditional Go는 바꾸지 않는다.** +
**손절 정책 ablation(§44, SPPV-2.55, 2026-07-18) — §42가 신규
추가한 "경로 리스크(MAE)·손절 정책 부재"에 대해, "-15%"·"-20%"
손절선을 실제 도입하면 총 기대수익이 개선되는지 직접 검증했다.
**결과: 두 손절 임계값 모두 총 기대수익 proxy를 악화시켰다**
(baseline 9734.7 → -15% 손절 7024.1(약 27.8% 악화) → -20% 손절
9093.8(약 6.6% 악화), 손절이 타이트할수록 악화 폭이 큼) — R3b
candidate는 조정 구간을 버텨야 이후 회복분을 취하는 구조이기
때문이다. "손절 정책 부재"는 "미검증 공백"에서 **"시험한 범위
내에서는 손절 미도입이 총 기대수익 관점에서 근거 있는 선택"**
으로 재분류. Conditional Go 유지, 방향성 반전 아님, 운영 코드
변경 없음.** +
**entry_score 코드 반영 절차 shadow 정합성 검증(§45, SPPV-2.56,
2026-07-18) — 이 세션 내내(SPPV-2.46~2.55) B 시나리오 계산에 써온
수작업 재구현 `_non_alpha`가 실제 운영 함수 `_build_entry_score`
와 정확히 일치하는지 전체 시점 스냅샷(58,493건, candidate로 좁히지
않은 모집단 전체)에서 전수 검증했다. **결과: 100.0% 완전 일치,
불일치 0건, 최대 오차 0.0** — B 시나리오 non-alpha 조정 항 계산이
실제 운영 코드 동작(source_type="core", portfolio_allocation=None
조건)을 정확히 대표한다는 것이 확인됐다. "entry_score 코드 반영
절차"는 "설계 논의 단계"에서 "B 시나리오 조정 항 shadow 계산 정합성
확보, 실제 코드 변경 PR 작성 착수 검토 가능 단계"로 격상 — 다만
§21 게이트(주된 차단 요인)는 불변이며, 이것이 SPPV-3 확정 Go를
뜻하지는 않는다. Conditional Go 유지, 운영 코드 변경 없음.** +
**[SPPV-2.57에서 정정, §46] "실제 함수를 한 번도 직접 호출한 적이
없었다"는 과장 — `_build_entry_score`는 시나리오 A(현행 regime)로는
이미 이전 스크립트에서 직접 호출돼왔다. 이번에 처음 채운 것은
"B 시나리오(risk_tone neutral 치환) 입력으로 직접 호출한 적이
없었다"는 좁은 간극이다. 또한 이번 검증은 non-alpha 조정 항만
증명했을 뿐, R3b alpha 교체 전체 경로의 실제 코드 반영 후 재현성과
held_position/실제 portfolio_allocation 케이스는 여전히 미검증
이다 — "B 시나리오 전체가 실제 운영 코드와 동일"이라는 표현은
범위를 넘는다. Conditional Go는 그대로 유지, 판정 변경 없음.** +
**`§21 게이트` config 기반 gate 제어 신규 모듈(§47, SPPV-2.58,
2026-07-18) — 코드베이스 조사 결과 §21 게이트는 지금까지 실제
운영 코드(`assess_deterministic_triggers`) 어디에도 연결돼 있지
않은 순수 모니터링 산출물이었음을 확인. `deterministic_trigger_
engine.py`는 이번에도 수정하지 않는다는 원칙을 지키며, config
스위치(`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 False)로만
동작하는 신규 격리 모듈(`services/regime_switch_gate.py`)을 구현·
검증했다 — paper/real 같은 environment 값은 전혀 참조하지 않는
mode-agnostic 판정. override off 시 기존 §21 해석과 100% 동일
(TRIGGERED일 때만 열림), override on 시 국면 상태와 무관하게 항상
열림(강제 통과), 모든 판정에 reason_code로 추적 가능. 실제 §21
게이트 상태는 여전히 NOT_TRIGGERED(불변). 아직 실제 파이프라인에는
연결되지 않았다 — 연결은 별도 승인 필요. Conditional Go 유지,
`deterministic_trigger_engine.py` 미수정, broker submit 미호출.** +
**[SPPV-2.59에서 정정, §48] "구현 완료"는 부정확 — 정확히는 "준비
모듈 + 런타임 미연결"이었다. 이번 턴에 사용자 명시 승인 아래
`deterministic_trigger_engine.py`를 실제로 수정해 `assess_
deterministic_triggers`(실제 BUY_CANDIDATE 판정 함수)에 신규
optional 파라미터(`regime_switch_v1_trigger_status`/`regime_
switch_v1_gate_override_enabled`, 기본값 둘 다 비활성 = 기존 호출부
100% 무영향)로 실제 연결했다. 동일한 실제 함수를 게이트 파라미터
없이/override off/override on 3가지로 직접 호출한 결과, 게이트가
실제로 `buy_candidate`를 차단(`True`→`False`)했고 override가 실제로
그 차단을 해제(baseline과 동일하게 복원)함을 확인 —
`gate_actually_blocks_real_path=True`, `override_actually_
restores_real_path=True`. 기존 단위 테스트 20건 전부 통과(하위
호환 확인). 다만 실제 운영 호출부(orchestrator)가 이 신규 파라미터
를 전달하도록 배선하는 작업은 아직 미완료 — 그 전까지는 이 변경이
실제 운영 동작에 영향을 주지 않는다(의도된 안전장치). Conditional
Go 유지, compliance/VaR/broker submit 경계 미변경, 신규 KIS 호출
0건.** +
**[SPPV-2.60에서 정정, §49] "실제 판단 경로 연결 완료"는 과장 —
`assess_deterministic_triggers` 함수 내부는 연결됐으나 그 유일한
실제 상위 호출부 `DecisionOrchestratorService`(`decision_
orchestrator.py`)는 신규 파라미터를 전혀 넘기지 않고 있었다. 이번
턴에 `DecisionOrchestratorService.__init__`에 동일 파라미터 2개를
추가하고, `scripts/run_decision_loop.py`의 두 생성 지점 전부에서
실제로 전달하도록 배선했다(`trigger_status`는 신규 read-only 헬퍼
`resolve_cached_trigger_status()`로 `logs/regime_switch_v1_gate_
monitor_*.json` 캐시에서 조회, 신규 KIS 호출 없음). `validate_r3b_
orchestrator_gate_wiring.py`로 **`DecisionOrchestratorService`를
실제로 구성**해 검증: 게이트가 실제로 buy_candidate를 차단하고
override가 실제로 그 차단을 해제함을 확인
(`gate_blocks_via_orchestrator=True`, `override_restores_via_
orchestrator=True`). 기존 단위 테스트 83건(63+20) 전부 통과. **중요
리스크**: 이 배선 완료로 `run_decision_loop.py`가 이제 실제 §21
게이트 상태(`NOT_TRIGGERED`)를 읽어 전달하므로, override가 기본값
False인 한 core BUY_CANDIDATE 판정이 실제로 영향받기 시작한다 —
이는 사용자 확인이 필요한 새로운 실제 동작 변화다(§49.6). Conditional
Go 유지, compliance/VaR/broker submit 경계 미변경.** +
**[SPPV-2.61에서 정정, §50] §49의 검증 산출물에서 `resolve_cached_
trigger_status_current_value=None`이었던 원인을 규명 — 코드 결함
(glob/JSON파싱/status검증)이 아니라 기본 `glob_pattern`이 **cwd
의존 상대경로**였기 때문(§49 검증이 Docker 컨테이너에서 실행됐는데
그 컨테이너 `/app/logs/`에 캐시 JSON 파일 2개가 복사돼 있지
않았다). 프로젝트 루트 기준 절대경로로 앵커링해 수정, 재검증 결과
`resolve_cached_trigger_status_current_value="NOT_TRIGGERED"`로
정상 조회 확인(cwd 무관, `/tmp`에서도 동일 확인). "83건 테스트
통과"는 사실이었으나 실행 로그가 산출물로 남아있지 않았던 문제도
이번에 `logs/r3b_pytest_run_2026-07-18.log`로 실제 실행 증빙을
보강(83 passed 재확인). "배선은 완료됐으나 캐시 상태 전달에는
추가 수정이 필요"했던 상태에서 **"캐시 상태까지 정상 전달됨"**
으로 확정 — §49.6의 리스크(override off 기본값 + NOT_TRIGGERED
조합에서 core BUY_CANDIDATE 실제 차단 가능)는 이번 수정으로 cwd에
관계없이 항상 실현 가능해져 더 급해졌다. Conditional Go 유지.** +
**최신 truth 갱신(2026-07-18): commit `aa10caee`로 §21 게이트 배선
완료·푸시 확정, 현재 `.env`에 `REGIME_SWITCH_V1_GATE_OVERRIDE_
ENABLED=true` 설정 — paper 관측 단계에서 게이트는 BUY를 막지 않는다.
paper/production 코드 분기·배선 원복은 더 이상 검토 대상 아님.** +
**국면 혼합도 모니터링 모듈 구현(§51, SPPV-2.62, 2026-07-18) — §40
이 확정한 혼합도 3분위 경계값을 `services/regime_mixedness_
monitor.py`(신규, BUY/SELL 미연결 순수 관측용)로 재구현하고, 3년
캐시 bars만으로(신규 KIS 호출 0건) 634거래일 전체를 재분류한 결과
§40 실측치(저혼합 217일/중혼합 215일/고혼합 202일)와 정확히 일치
(`matches_sppv_2_50=True`) — "혼합도 모니터링 설계" 다음 단계를
실제 검증된 재사용 가능 모듈로 완료. Conditional Go 유지, 운영
코드 미변경.** +
**혼합도 모니터링 실제 소비 위치 연결(§52, SPPV-2.63, 2026-07-19) —
`scripts/run_decision_loop.py`에 신규 `_run_mixedness_check()`를
추가해 cycle당 1회 §51 모듈로 벤치마크 국면 혼합도를 계산·로그에
남기도록 배선(기존 `_run_precheck()`와 동일한 안전 패턴, 신규 KIS
호출 없음, BUY/SELL 판정과 완전히 분리). in-memory repos로 저혼합/
고혼합 두 시나리오를 실제로 `_run_mixedness_check()`를 호출해
검증한 결과 둘 다 정확히 분류됨을 확인, 소스 검사로 BUY/SELL 판정
코드가 전혀 없음도 확인. 기존 단위 테스트 10건 실패는 변경 전에도
동일하게 실패하는 사전 존재 결함임을 stash 재실행으로 확인(무관).
Conditional Go 유지, 운영 게이트 로직 미변경.** +
**[SPPV-2.64에서 확정, §53] 위 "stash 재실행으로 확인(무관)"은
증빙이 약했다 — `git worktree`로 §52 이전 커밋(`4fd3ad7e`)을
메인 워크트리와 분리해 체크아웃한 뒤 Docker 컨테이너 안에서
PRE/POST 두 버전을 각각 `pytest -v --tb=long`으로 전체 재실행,
807줄 로그를 `diff`로 직접 비교했다. 실패 10건·에러 메시지·
assertion 내용까지 완전히 동일(차이는 비결정적 메모리 주소와
71줄 오프셋뿐), `grep`으로 mixedness 관련 문자열이 실패 stack
trace 어디에도 없음을 확인 — **"무관 확정".** 코드 변경 없음,
Conditional Go 유지.** +
**entry_score PR 초안 설계(§54, SPPV-2.65, 2026-07-19) — "R3b
alpha 교체 전체 경로 재현"을 다시 실측하는 대신(§45의 non-alpha
100% 일치의 논리적 귀결이라 반복 검증 불필요), **새로 발견한
아키텍처 제약**을 정리했다: entry_score는 종목 단위 계산이지만
R3b alpha(candidate_percentile)는 당일 cross-sectional 순위가
필요해 사전 계산 단계가 있어야 한다 — `run_decision_loop.py`의
기존 `_build_core_risk_off_apply_overrides_for_cycle()`(cycle당
1회 전체 universe precompute → override 주입)이 정확히 필요한
선례로 이미 존재함을 확인. 이를 근거로 실제 코드 diff 초안(신규
precompute 함수 1개 + `assess_deterministic_triggers` optional
파라미터 2개 + config 스위치 1개, 전부 §48/§49와 동일한 기본값-
비활성 패턴)을 설계했다 — **미적용, 코드 변경 없음.** "entry_score
코드 반영 절차"는 "shadow 정합성 확보"에서 "구체적 구현 설계
확보(diff 초안)"로 진전. 적용은 별도 승인 필요. Conditional Go
유지, 신규 KIS 호출 0건.**
상위 문서: `plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
(§4 판정 — "국면 분기형 entry 설계로 전환"), `plans/[DESIGN] signal_
predictive_power_validation.md`(§16 이원 기준, §19/§20/§21 근거 실측),
`plans/[ANALYSIS] foundational_design_review_objective_alignment.md`
§8(책임 분리).

## 0. 이 문서의 위치와 경계

이 문서는 SPPV-2.15(종합 판정)가 지시한 **다음 착수 형태**를 실제
설계 문서로 구체화한 것이다. 아래는 **설계 초안**이며 다음 세 가지를
아직 하지 않는다(작업 원칙 준수):

- **운영 `entry_score` 코드를 변경하지 않는다.** 이 문서와 shadow
  스크립트는 read-only 계산기이며 `deterministic_trigger_engine.py`의
  `_build_entry_score()`를 호출/수정하지 않는다.
- **broker submit 경계를 넘지 않는다.** shadow 계산 결과는 로그 파일로만
  남으며 주문 경로에 어떤 영향도 주지 않는다.
- **deterministic risk/compliance/guardrail 경계를 바꾸지 않는다.**
  아래 §3의 통합 방안은 "제안"이며, 실제 코드 변경은 이 문서가 Go
  판정을 받고 사용자가 승인한 뒤 별도 턴에서 진행한다.

## 1. 왜 이 설계가 필요한가 — 실측 근거 요약

`plans/[ANALYSIS] sppv_regime_polarity_synthesis_and_next_direction.md`
§1의 종합표(SPPV-2.9~2.14, 87종목×3년×56,753표본)가 이 설계의 유일한
근거다. 핵심 3가지:

1. **정적(static) 단일 가중 신호는 상승/횡보장에서도 안정적 알파를
   내지 못한다** — `overall_score`/`slow_score`/`fast_score` 전부
   §14(3년 확장)에서 pooled 유의성을 잃었고(§14 참고), 가장 근접한
   `risk_adj_momentum_3m`도 marginal(t≈2.0)이다.
2. **하락장에서는 방향이 통째로 바뀐다** — 추세추종형 신호(`fast_
   trend`, `sma5_over_sma20_gap`, `relative_strength_rank_1m` 등)는
   하락장에서 무신호이거나 유의하게 역전하고, 되돌림형 신호(`reversal_
   1m`, `rsi_mean_reversion`)는 **하락장에서만** 유의하다(종합표 §2.1).
3. **국면에 따라 신호를 "전환"하는 것만으로 트랙 최고 성과가
   났다** — `regime_switch_v1`(비하락장=`risk_adj_momentum_3m`,
   하락장=`reversal_1m`)의 2차(3년) pooled 유의성은 T+5=2.60/
   T+20=2.36으로, 이 트랙에서 시도한 모든 정적 신호를 통틀어 가장
   높다(§19.4, §20.2). 다만 1차(최근 12개월) 게이트는 하락장 표본
   부재로 구조적으로 미달이다.

이 세 사실을 종합하면, **가중치를 더 튜닝하거나 새 feature를 하나 더
추가하는 것보다, "국면에 따라 다른 신호를 쓴다"는 구조 자체를 entry
설계에 명시적으로 반영하는 것이 실측으로 뒷받침되는 다음 단계**다.

## 2. 설계 — 국면별 신호 선택 매트릭스

### 2.1 국면 판정 기준(재사용, 신규 로직 없음)

시장 공통 국면은 기존 SPPV-2.6 이후 확립된 방법 그대로 사용한다 —
**KODEX 200(069500, core universe 구성원이지만 평가 대상에서는 제외)의
자기 자신의 rolling 기술적 상태**를 운영 코드 `classify_market_regime()`
(`market_regime.py`)에 입력해, 그날 하나의 라벨을 만든다. 이 라벨을
그날의 모든 개별 종목이 공유한다(§12.2, SPPV-2.6에서 확립).

### 2.2 국면별 채택/폐기 신호

| 국면 | 채택 신호 | 폐기(사용 안 함) | 근거 |
|---|---|---|---|
| **비하락장**(`bullish_trend`, `range_bound`) | `risk_adj_momentum_3m` = `return_3m_pct / max(volatility_20d_pct, 1.0)` | `fast_trend`, `sma5_over_sma20_gap`, `rsi_signal`, `relative_strength_rank_1m`, `money_flow_5d`(전부 무신호 또는 marginal 이하) | §17.2: `risk_adj_momentum_3m` bullish t_NW=1.51, range t_NW=2.09 — 유일하게 두 비하락장 국면 모두에서 방향 일관된 양(+) |
| **하락장**(`bearish_trend`) | `reversal_1m` = `-return_1m_pct` | 위와 동일 + `risk_adj_momentum_3m` 자체(하락장 t_NW=0.39로 무의미) | §17.2/§18.4: `reversal_1m` bearish T+5 t_NW=2.13(유일하게 하락장에서 유의한 후보) |
| **판정 불가**(`event_driven_unstable`, 표본 3년 기준 6일뿐) | **신호 미산출(neutral/보류)** | 전부 | 표본이 `MIN_REGIME_TRADING_DAYS=30` 미달 — 어떤 신호도 이 국면에서 검증된 바 없음(§16.6, §17.5, §20.5 반복 확인). 근거 없이 아무 신호나 대입하지 않는다 |

이 매트릭스는 §19.4에서 검증한 `regime_switch_v1`과 **동일한 정의**다
— 이번 문서는 그것을 "shadow feature 하나"에서 "entry 설계의 명시적
분기 규칙"으로 격상한 것이지, 새 로직을 발명한 것이 아니다.

### 2.3 통합 스코어 정의

```text
regime_conditional_signal(symbol, date) =
    risk_adj_momentum_3m(symbol, date)   if common_market_regime(date) in {bullish_trend, range_bound}
    reversal_1m(symbol, date)            if common_market_regime(date) == bearish_trend
    None (신호 미산출)                    if common_market_regime(date) == event_driven_unstable 또는 판정 불가
```

`risk_adj_momentum_3m`과 `reversal_1m`은 서로 스케일이 다르므로(전자는
"수익률/변동성" 비율, 후자는 "-1개월 수익률 %") **직접 비교하지
않는다** — 국면이 배타적으로 하나만 선택되므로 스케일 정합성 문제
자체가 발생하지 않는다(그날 그날 종목 간 cross-sectional quintile
비교에만 쓰이기 때문).

## 3. 기존 `entry_score`와의 연결 방안 (제안, 아직 미적용)

`_build_entry_score()`(`deterministic_trigger_engine.py:1115-1170`)의
현재 구조:

```python
score = 0.0
score += 0.45 * _normalize_signed_score(overall)   # ← alpha layer
score += 0.20 * _normalize_signed_score(fast)       # ← alpha layer
score += 0.15 * _normalize_signed_score(slow)        # ← alpha layer
# 이하 regime bonus/penalty, allocation, strategy, source, activity — risk/제약 layer
```

**제안**: `foundational_design_review...md` §8의 책임 분리(alpha /
entry projection / risk constraint / compliance / execution)를 그대로
유지하면서, **alpha layer(0.45+0.20+0.15=0.80 가중치 블록)만** 아래로
교체를 검토한다:

```python
# 제안 (미적용) — alpha layer만 교체
score += 0.80 * _normalize_signed_score(regime_conditional_signal)
# regime bonus/penalty, allocation, strategy, source, activity는 그대로 유지
```

**이 교체를 지금 적용하지 않는 이유**:
1. `regime_conditional_signal`의 하락장 절반(`reversal_1m`)은 §16
   1차 게이트를 아직 통과하지 못했다(§21 모니터링, 현재
   `NOT_TRIGGERED`) — 실거래 반영 전 반드시 통과해야 하는 전제조건이
   아직 충족되지 않았다.
2. 현재 `risk_off_penalty`(-0.15, market_regime.risk_tone=='risk_off'
   일 때)와 `regime_conditional_signal`의 하락장 분기가 **의미상
   중복될 위험**이 있다 — 둘 다 "하락장이면 무언가를 조정한다"는
   로직이기 때문이다. 이 중복을 해소하는 것은 SPPV-3(entry_score
   재현 + 중복 penalty ablation)의 원래 범위이며, 이 문서 하나로
   결론 내지 않는다.
3. `entry_score`의 나머지 0.20(allocation/strategy/source/activity)은
   `regime_conditional_signal`과 무관한 독립 축이라 그대로 둔다 — §8의
   책임 분리 원칙(risk/compliance는 alpha가 아니라 제약조건)을 지킨다.

## 4. shadow 검증 계획

### 4.1 Phase 1(이번 턴 — 완료): 정의 확정 + 1회성 shadow 스냅샷

이번 턴에 `scripts/shadow_regime_conditional_entry_signal.py`(read-only)
를 작성해 **"오늘(가장 최근 캐시 일자) 기준으로 이 신호가 core
universe 각 종목에 대해 어떤 값을 내는가"**를 1회 계산·기록했다.
DB write 없음, 주문 경로 없음. §5에 실행 결과 기록.

### 4.2 Phase 2(이번 턴부터 실행 가능 — §6에서 구현·실행 완료)

- 이 스크립트를 향후 3년 캐시를 갱신할 때마다(또는 별도 주기로) 함께
  실행해, **매번 다른 날짜의 스냅샷을 시계열로 누적**한다. 이는 새로운
  KIS 호출을 반복 발생시키지 않도록 캐시 우선 재사용을 유지한다.
- 충분한 관측치가 쌓이면(특히 하락장이 실제로 재발하면), §16 이원
  기준을 그대로 적용해 `regime_conditional_signal`을 **점수 하나의
  shadow feature가 아니라 entry 후보로서** 재검증한다 — 이는 §21
  모니터링 스크립트의 `TRIGGERED` 신호와 연동된다.
- 구체적 실행체와 누적 형식은 §6(Phase 2 shadow 누적 사이클 — 2026-07-15
  구현 완료)에 기록한다.

### 4.3 Go/No-Go 판정 기준(§16 그대로 재사용, 신규 기준 없음)

- **1차(최근 12개월) 유의성**: `regime_conditional_signal`의 pooled
  quintile spread가 |t_NW|≥2를 만족해야 한다.
- **2차(3년) 국면 무역전**: 국면별 분해에서 어떤 국면도 유의하게
  반대 부호가 나오면 안 된다.
- **추가(이 설계 고유)**: 하락장 분기(`reversal_1m`)가 실제로 발동한
  기간이 §16의 `MIN_REGIME_TRADING_DAYS`(30일) 이상 최근 12개월 창에
  존재해야 한다 — 이는 §21 모니터링 스크립트의 `TRIGGERED` 판정과
  동일하다.

이 세 조건을 모두 만족하기 전까지는 `entry_score` 반영을 시도하지
않는다.

## 5. Shadow 계산기 실행 결과 (2026-07-15, Phase 1)

`scripts/shadow_regime_conditional_entry_signal.py`(read-only)를
실행했다. 3년 캐시(`logs/_bars_cache_core87_3y_2026-07-14/`)를
재사용해 **신규 KIS 호출 0건**으로, 캐시에 있는 가장 최근 거래일(각
종목의 forward-return 계산 없이 raw feature만 필요하므로 실제 마지막
봉 날짜까지 사용 가능) 기준 87종목 전체의 `regime_conditional_signal`
값을 계산·기록했다.

**실행 결과** (종료 코드 0, `HTTP Request:` 0건, 87/87종목 성공):

| 항목 | 값 |
|---|---|
| 기준일 | 2026-07-14 |
| 시장 공통 국면 | `range_bound` |
| 사용된 신호 | `risk_adj_momentum_3m`(비하락장 분기, 87종목 전체) |
| 신호 산출 종목 | 87/87(판정불가 0종목) |
| 상위 5종목(신호값) | 009150(14.91), 011070(14.56), 066570(11.77), 402340(10.41), 000810(9.39) |
| 하위 5종목(신호값) | 010130(-12.25), 120110(-10.74), 298020(-10.73), 051915(-10.45), 251270(-9.78) |

**해석**: 오늘(2026-07-14)은 시장 공통 국면이 `range_bound`이므로 87
종목 전체가 `risk_adj_momentum_3m` 분기를 사용했다 — `reversal_1m`
분기(하락장 전용)는 이번 스냅샷에서는 한 번도 발동하지 않았다. 이는
§21 모니터링(최근 12개월 창에 `bearish_trend` 0일, `NOT_TRIGGERED`)과
정합적이다 — **이번 실행 자체는 "설계가 실제로 동작하는가"를 검증한
것이지, "신호가 유의한가"를 다시 검증한 것이 아니다.** 유의성 검증은
이미 §17.2/§19.4에서 3년치로 완료됐고, 이번 실행은 그 정의를 실시간
(현재 시점) 데이터에 1회 적용해본 **연결성 확인(smoke test)**이다.
산출: `logs/shadow_regime_conditional_entry_signal_2026-07-15.json`,
`logs/shadow_regime_conditional_entry_signal_run_2026-07-15.log`.

## 6. Phase 2 — shadow 누적 사이클 구축·실행 (2026-07-15)

### 6.1 왜 별도 오케스트레이터가 필요한가

Phase 1의 `scripts/shadow_regime_conditional_entry_signal.py`는 "실행할
때마다 그날의 스냅샷 JSON 하나"만 남긴다 — 반복 실행해도 이전 결과와
연결되지 않고, `scripts/monitor_regime_switch_v1_gate.py`의 게이트
판정과 별개로 돌아간다. Phase 2가 실제로 "누적"이 되려면 (1) 게이트
판정과 신호 계산을 **한 번의 실행으로 묶고**, (2) 그 결과를 **시계열
이력 파일에 추가(append)**하며, (3) 같은 거래일을 중복 기록하지 않아야
한다. 이 세 가지를 위해 새 로직을 짜지 않고 기존 두 스크립트의 계산
함수를 그대로 import해 재사용하는 오케스트레이터를 만들었다.

### 6.2 구현 — `scripts/run_regime_conditional_shadow_cycle.py`

- **벤치마크(069500) bars를 1회만 조회**해 (a) 게이트 판정(§21 로직,
  `_build_benchmark_daily_series` 재사용)과 (b) 오늘 신호 계산(§22
  로직, `_build_benchmark_regime_by_date`/`_latest_regime_and_signal`
  재사용) 양쪽에 함께 쓴다 — 중복 KIS 호출이 생기지 않는다.
- **누적 이력**: `logs/regime_conditional_signal_shadow_history.jsonl`
  (append-only, JSON Lines, 거래일당 1줄). 각 줄은 `trade_date`,
  `common_market_regime`, `gate_status`,
  `gate_bearish_days_recent_12m`, `symbol_count_with_signal`,
  `signal_source_distribution`(신호 산출 종목이 몇 개나 `risk_adj_
  momentum_3m`/`reversal_1m`을 썼는지 집계)을 담는다 — 87종목 전체의
  개별 값까지는 담지 않아(상세는 별도 당일자 JSON 참고) 파일이 시간이
  지나도 가볍게 유지된다.
- **중복 방지**: 실행 전 이력 파일을 읽어 이미 기록된 `trade_date`
  집합을 만들고, 오늘 날짜가 이미 있으면 새 줄을 추가하지 않는다 —
  같은 날 여러 번 실행해도 이력이 부풀지 않는다(재실행으로 실제
  검증했다 — §6.3).
- **당일 상세 스냅샷도 함께 저장**: Phase 1과 동일한 포맷으로
  `logs/shadow_regime_conditional_entry_signal_<날짜>.json`(87종목
  개별 값 전체)을 남긴다 — 이력 파일은 "요약", 이 파일은 "상세"로
  역할을 분리한다.
- **게이트 상태에 따른 안내**: 게이트가 `TRIGGERED`/`PARTIAL`이면
  화면에 §4.3 재검증 절차(runbook)를 그대로 출력한다 — 자동 재검증은
  하지 않는다(3년 캐시 재구축은 비용이 크고 신중한 판단이 필요하므로
  사람이 다음 턴에 명시적으로 착수한다).

### 6.3 실행 결과 (2026-07-15)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0.

| 실행 | 결과 |
|---|---|
| 1차 실행 | 게이트: 기준일 2026-06-16, 국면분포 `{bullish_trend: 239, range_bound: 6}`, 판정 `NOT_TRIGGERED`. 신호: 기준일 2026-07-14, 국면 `range_bound`, 87/87종목 `risk_adj_momentum_3m` 분기. 이력에 1줄 추가(누적 거래일 1개). |
| 2차 실행(즉시 재실행, 중복 방지 검증) | 동일 결과 계산됐으나 **"2026-07-14는 이미 이력에 존재 — 중복 추가 skip"** 정상 출력, 이력 줄 수 그대로 1개 유지 |

**해석**: 게이트(2026-06-16 기준)와 신호 계산(2026-07-14 기준)의
기준일이 다른 것은 §21.3에서 이미 설명한 정상적 지연이다 — 게이트
판정은 forward-return 계산이 가능한 날짜까지만 국면을 라벨링하는
`_build_benchmark_daily_series`(T+20 확보 필요)를 재사용하기 때문에
약 20거래일 지연이 생기고, 신호 계산은 forward-return이 필요 없는
`_build_benchmark_regime_by_date`를 써서 최신 봉 날짜까지 라벨링한다.
이 둘은 서로 다른 목적(게이트=과거 12개월 분포 판정, 신호=오늘 값
계산)에 맞게 각기 다른 기존 함수를 정확히 재사용한 결과이지 오류가
아니다. 중복 방지 로직이 실제로 두 번째 실행에서 발동해, 반복 실행
시에도 이력 파일이 부풀지 않음을 확인했다.

산출: `scripts/run_regime_conditional_shadow_cycle.py`(read-only),
`logs/regime_conditional_signal_shadow_history.jsonl`,
`logs/shadow_regime_conditional_entry_signal_2026-07-14.json`,
`logs/run_regime_conditional_shadow_cycle_run_2026-07-15.log`.

## 7. 다음 단계

1. `scripts/run_regime_conditional_shadow_cycle.py`를 향후 SPPV 턴
   또는 3년 캐시 갱신 시마다 함께 실행해 이력을 계속 쌓는다 — 별도
   스케줄러 등록은 운영 인프라 변경 금지 원칙에 따라 이번 턴에는
   하지 않는다(수동/다음 턴 관행으로 유지).
2. 게이트가 `TRIGGERED`로 전환되면, §6.2의 runbook(오케스트레이터가
   화면에 출력하는 절차)을 그대로 따라 §4.3의 Go/No-Go 기준으로
   `regime_conditional_signal`을 정식 재검증한다.
3. §3의 `entry_score` 통합안은 제안 단계에 머문다 — `risk_off_
   penalty`와의 중복 여부는 SPPV-3(중복 penalty ablation) 착수 시
   함께 정리한다.
4. `event_driven_unstable` 국면은 여전히 신호 미산출 상태로 둔다 —
   표본이 쌓이기 전까지 임의로 채우지 않는다.
5. 이력 파일(`logs/regime_conditional_signal_shadow_history.jsonl`)이
   충분히 쌓이면(예: 국면 분포가 실제로 변화하는 시점), 이 파일
   자체를 §16 이원 기준 재검증의 "실시간 1차 표본"으로 활용하는 방안을
   검토한다 — 지금은 3년 과거 재구축 캐시에 의존하지만, 누적이 쌓이면
   실제 shadow 관측치로 1차 유의성을 확인할 수 있게 된다.

## 8. `entry_score` 중복 penalty ablation — Phase 0 shadow 실측 (2026-07-15)

### 8.1 배경 — SPPV-3 착수 전제

§3에서 언급한 대로, `entry_score`에 `regime_conditional_signal`을
반영하지 않는 이유 중 하나는 현재 `entry_score`/`_assess_buy_
eligibility`의 "국면이면 무언가를 차감/차단한다"는 로직이 여러 곳에
중복돼 있고(`plans/[ANALYSIS] foundational_design_review_objective_
alignment.md` §2 근본 진단), 이 중복을 해소하지 않은 채 새 신호를
얹으면 또 다른 중복을 만들 위험이 있기 때문이다. 이번 턴에 이 중복을
**말로만 지적하지 않고 오늘 시점 실제 데이터로 정량화**했다.

**중요한 경계**: 운영 DB(`trade_decisions`)를 직접 조회하는 것은
자동 승인 경계 밖의 프로덕션 읽기로 판단돼 이번 턴에 시도하지
않았다(harness가 차단). 대신 SPPV 트랙 전체가 지금까지 해온 방식 —
운영 코드(`build_signal_snapshot`, `classify_market_regime`,
`_build_entry_score`, `_assess_buy_eligibility`)를 그대로 재사용하는
read-only 재계산 — 을 동일하게 적용했다. 이는 실제 DB 데이터가 아니라
**오늘 시점 실시간 시세로 재구성한 shadow 값**이라는 한계가 있지만,
코드 경로 자체는 운영 함수를 직접 호출한 것이라 신뢰도가 높다.

### 8.2 실행 개요

`scripts/shadow_entry_score_penalty_ablation.py`(read-only)가 core
87종목(벤치마크 제외) × 오늘(3년 캐시 최신 봉) 기준으로, Phase
0(재구성 가능 — signal_backbone 순수 함수 + **종목별(per-symbol)**
`classify_market_regime`)만으로 아래 세 개의 독립적인 penalty/차단
축을 평가했다. Phase 1~3(allocation/strategy/실제 실행 이력)은
재구성 불가로 `None`을 그대로 전달했다(운영 함수가 이 경우 해당
가산/차감 항을 자연스럽게 건너뛴다 — 새 로직을 만들지 않았다).

- **축 A**: `entry_score`의 regime penalty(`risk_tone=='risk_off'`
  일 때 -0.15, `_build_entry_score` 그대로 호출)
- **축 B**: `_assess_buy_eligibility`의 regime 차단(`risk_tone==
  'risk_off' and regime_label=='bearish_trend'`, core 심볼은 예외
  없이 차단)
- **축 C**: `_assess_buy_eligibility`의 signal floor 차단
  (`overall<-0.10` 또는 `slow<-0.15`)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0, 87/87종목 성공.
산출: `logs/shadow_entry_score_penalty_ablation_2026-07-15.json`,
`logs/shadow_entry_score_penalty_ablation_run_2026-07-15.log`.

### 8.3 실측 결과

| 항목 | 값 |
|---|---|
| 축 A(entry_score regime penalty 적용) | 85/87 |
| 축 B(eligibility regime 차단) | 60/87 |
| 축 C(eligibility signal floor 차단) | 75/87 |
| A∩B | 60 |
| A∩C | 74 |
| B∩C | 60 |
| A∩B∩C | 60 |
| 아무 축도 안 걸림 | 1/87 |
| 운영 `_assess_buy_eligibility` 그대로 호출 — 통과 | 6/87 |
| 〃 — 차단 | 81/87 |
| 종목별(per-symbol) `regime_label` 분포 | bearish_trend 60 / range_bound 18 / bullish_trend 7 / event_driven_unstable 2 |
| 종목별 `risk_tone` 분포 | risk_off 85 / neutral 2 |

### 8.4 해석 — 중복은 "이론"이 아니라 오늘 "정확히" 재현된다

1. **B∩A/B∩C가 모두 60 = B(60) 전체와 일치한다.** 즉 eligibility의
   regime 차단이 발동한 60개 종목은 **예외 없이 전부** entry_score의
   regime penalty와 signal floor 차단도 동시에 걸린다 — 근본 진단
   §2가 "약한 signal이 이미 반영된 뒤 risk_off_penalty가 다시
   차감되고, eligibility가 동일한 조건을 다시 차단한다"고 서술한
   것이 추상적 우려가 아니라 **오늘 데이터로 100% 재현되는 사실**임을
   확인했다.
2. **종목별(per-symbol) 국면이 시장 공통(market-common) 국면과
   완전히 다르다.** 오늘 시장 공통 국면(§6, KODEX 200 벤치마크
   기준)은 `range_bound`인데, `entry_score`가 실제로 쓰는 **종목별**
   `classify_market_regime()` 기준으로는 87종목 중 60개(69%)가
   `bearish_trend`로 판정된다. 이는 §12.1(SPPV-2.6)에서 코드로
   확인했던 "종목별 regime_label은 시장이 아니라 그 종목 자신의
   신호"라는 문제가 여전히 운영 코드에 살아있고, 오늘도 실제로
   시장 판단과 크게 어긋난 결과를 내고 있음을 보여준다.
3. **eligibility 통과율(6/87≈6.9%)은 과거 DB 기준선(2026-06-25~,
   21/297≈7%)과 크게 다르지 않다** — 오늘 실시간 재구성 값이 과거
   실측 패턴과 대략 일치해, 이 ablation이 특이한 하루의 우연이
   아니라 상시적인 구조적 패턴일 가능성을 시사한다(다만 표본이
   하루치뿐이라 결론으로 확정하지는 않는다 — §8.6 다음 단계 참고).

### 8.5 `regime_conditional_signal` 설계와의 연결

이 결과는 §2/§3에서 이미 제기한 우려를 강화한다. `regime_conditional_
signal`이 쓰는 국면 정의는 **시장 공통(market-common, KODEX 200
벤치마크 기준)**인 반면, `entry_score`의 regime penalty/eligibility
차단이 쓰는 국면 정의는 **종목별(per-symbol)**이다 — 이 둘은 오늘
데이터에서 이미 크게 다른 결과(시장 공통=range_bound vs 종목별
69%가 bearish_trend)를 낸다. 따라서 `entry_score`에 `regime_
conditional_signal`을 반영하려면 **regime penalty/eligibility의
국면 정의도 시장 공통 기준으로 함께 맞출지, 아니면 종목별 정의를
유지한 채 신호만 교체할지**를 먼저 결정해야 한다 — 이 결정 없이
신호만 바꾸면 "새 신호는 시장 공통 국면을 보는데 risk_off_penalty는
여전히 종목별 국면을 본다"는 **네 번째 불일치**가 추가될 위험이 있다.

### 8.6 다음 단계 — SPPV-3 착수를 위해 남은 것

1. **국면 정의 통일 여부 결정**: `regime_conditional_signal` 통합
   시 entry_score의 regime penalty/eligibility도 시장 공통 국면
   기준으로 바꿀지 사용자 확인이 필요하다 — 이는 코드 변경 범위를
   크게 좌우한다.
2. **표본 확장**: 이번 실측은 오늘 하루치(87종목)뿐이다. §6의 Phase 2
   누적 사이클을 이 ablation에도 연결해, 매일 한 번씩 세 축의
   교집합을 누적하면 "오늘의 우연"인지 "상시 구조"인지 판별할 수
   있다 — 다음 턴 후보로 남긴다.
3. **DB 실측과의 교차검증(보류)**: 이번 턴은 운영 DB 접근 없이
   진행했다 — 실제 `trade_decisions.decision_json`과 대조하는 것은
   사용자가 명시적으로 그 DB 조회를 승인한 뒤 별도로 진행한다.
4. 위 결정들이 정리되면 SPPV-3(entry_score point-in-time 재현 및
   중복 penalty ablation 본작업)에 정식 착수할 수 있다 — 이번 §8은
   그 "준비" 단계다.

## 9. 중복 억제 시계열 누적 + 국면 정의 비교 체계 (2026-07-15)

### 9.1 왜 하루치 관찰로 끝내면 안 되는가

§8은 오늘 하루치(87종목)로 "A∩B∩C=60=B 전체"와 "종목별 국면이 시장
공통 국면과 전혀 다르다"는 두 가지를 확인했다. 그러나 §8.6에서 이미
인정했듯, 하루치 표본만으로는 "오늘의 우연"과 "상시 구조"를 구분할 수
없다. §6(Phase 2)이 `regime_conditional_signal`에 대해 이미 확립한
"반복 실행 → 누적 이력" 패턴을 이 ablation에도 그대로 적용해야
같은 문제를 겪지 않는다.

### 9.2 구현 — `scripts/run_entry_score_penalty_ablation_cycle.py`

새 계산 로직을 만들지 않고 두 기존 함수를 그대로 재사용했다:

- `scripts/shadow_entry_score_penalty_ablation.py`의
  `_reconstruct_symbol_state()`(§8의 penalty 축 A/B/C 계산, 종목별
  `classify_market_regime` 재사용)
- `scripts/shadow_regime_conditional_entry_signal.py`의
  `_build_benchmark_regime_by_date()`(§22의 시장 공통 국면 계산)

이 둘을 합쳐 종목마다 **"종목별 regime_label"과 "시장 공통 국면"을
같은 실행에서 나란히 계산**하고, 다음을 누적 이력 파일
(`logs/entry_score_penalty_ablation_history.jsonl`, append-only,
거래일당 1줄, 같은 거래일 재실행 시 중복 skip — §6이 확립한 것과
동일한 이력 패턴)에 기록한다:

- A/B/C 각 축의 발동 건수와 A∩B∩C
- 종목별 `regime_label` 분포 vs 시장 공통 국면
- **국면 일치/불일치 건수**, 그중 "시장은 비하락장인데 종목별로는
  하락장" 방향과 "시장은 하락장인데 종목별로는 비하락장" 방향을
  분리 집계(divergence의 방향성까지 구분)

당일 상세(87종목 개별 값)는 별도 파일(`logs/entry_score_penalty_
ablation_<날짜>.json`)로 남겨 이력 파일은 가볍게 유지한다 — §6과
동일한 "요약 이력 vs 당일 상세" 역할 분리.

### 9.3 실행 결과 (2026-07-15)

3년 캐시 재사용, **신규 KIS 호출 0건**, 종료 코드 0, 87/87종목 성공.

| 실행 | 결과 |
|---|---|
| 1차 실행 | 시장 공통 국면(2026-07-14)=`range_bound`. A=85/B=60/C=75/A∩B∩C=60(§8과 완전히 일치, 정합성 재확인). 종목별 분포: bearish_trend 60/range_bound 18/bullish_trend 7/event_driven_unstable 2. **국면 일치 18건, 불일치 69건(79%)** — 그중 "시장 비하락장인데 종목별 하락장" 60건, "시장 하락장인데 종목별 비하락장" 0건(애초에 시장이 하락장이 아니므로 당연히 0). 이력에 1줄 추가(누적 거래일 1개). |
| 2차 실행(즉시 재실행, 중복 방지 검증) | 동일 결과 계산됐으나 "2026-07-14는 이미 이력에 존재 — 중복 추가 skip" 정상 출력, 이력 줄 수 그대로 1개 유지 |

### 9.4 해석(쉬운 설명)

- **entry_score 세 겹 차단은 우연이 아니다.** 오늘 실측에서도 §8과
  정확히 같은 숫자(A=85, B=60, C=75, 교집합=60)가 나왔다 — 같은
  날짜의 같은 데이터를 다시 계산한 것이므로 당연한 재현이지만, 두
  스크립트(§8과 §9)가 서로 다른 코드 경로로도 동일한 결과를 낸다는
  **교차 검증**이 됐다.
- **종목별 국면과 시장 국면은 5개 중 4개꼴로 다르다(79%).** 오늘
  시장은 "옆으로 횡보"(`range_bound`)로 판단됐는데, 실제 entry_score
  계산에 쓰이는 개별 종목 판정은 87개 중 60개(69%)가 "하락 추세"로
  나온다 — 즉 지금 운영 코드는 **시장이 하락장이 아닌 날에도** 개별
  종목 다수를 "하락장"으로 잘못(?) 분류해 risk_off_penalty와
  eligibility 차단을 발동시키고 있을 가능성이 있다. "잘못"이라고
  단정하지 않는 이유는, 종목별 판정이 그 종목 고유의 약세(개별
  기업 이슈 등)를 반영하는 것일 수도 있어서다 — 이 구분은 §9.6의
  비교 실험으로 가려야 한다.

### 9.5 종목별 국면 vs 시장 공통 국면 — 정리

| 구분 | 종목별(per-symbol) 국면 | 시장 공통(market-common) 국면 |
|---|---|---|
| 정의 | 그 종목 자신의 `overall_score`/`return_3m_pct`/`price_vs_sma_60_pct` 등을 `classify_market_regime()`에 입력 | KODEX 200(069500) 벤치마크의 rolling 기술적 상태를 같은 함수에 입력, 하루에 라벨 1개를 전 종목이 공유 |
| 현재 쓰이는 곳 | `entry_score`의 regime bonus/penalty, `_assess_buy_eligibility`의 regime 차단(운영 코드, 지금도 실사용 중) | `regime_conditional_signal`(§2, 아직 shadow 단계, 미적용) |
| 오늘 실측(2026-07-14) | bearish_trend 60/range_bound 18/bullish_trend 7/event 2 | range_bound 1개(전 종목 공유) |
| 알려진 문제 | §12.1(SPPV-2.6)에서 이미 "검정 대상 신호와 같은 계열 변수로 조건화한 선택 편향"으로 지적됨 — 그런데도 운영 코드는 여전히 이 정의를 쓴다 | SPPV 전체 트랙(§16 이하)이 검증에 사용한 정의 — 시장 전체 방향을 반영 |

**핵심 쟁점**: 지금 운영 중인 `entry_score`/eligibility는 "문제가 있다고
이미 알려진" 종목별 정의를 쓰고 있고, 검증된 `regime_conditional_
signal`은 "올바르다고 확인된" 시장 공통 정의를 쓴다 — 이 둘을 통합
하려면 반드시 하나로 맞춰야 하며, 그 결정은 실측 비교 없이 내릴 수
없다(§9.6).

### 9.6 SPPV-3 본작업용 비교 실험 설계

SPPV-3(entry_score point-in-time 재현) 착수 시, 다음 실험을 **반드시
포함**해야 한다 — 새 방법론이 아니라 이미 SPPV 트랙이 확립한 §16
이원 기준·3년 캐시·cross-sectional quintile spread를 그대로 재사용한다.

**실험 설계**:

1. 기존 3년 rolling 표본(87종목×56,753건, 이미 확보됨)에 대해, 각
   거래일·종목마다 **두 가지 eligibility 판정**을 병렬로 계산한다:
   - **변형 A(현행 유지)**: `_assess_buy_eligibility`를 그대로 호출 —
     regime 차단 조건에 **종목별** `regime_label`을 사용.
   - **변형 B(시장 공통 정렬)**: 동일한 `_assess_buy_eligibility`를
     호출하되, regime 차단 조건에 **시장 공통** 국면(벤치마크 기준,
     그날 전 종목 공유)을 대입.
2. 두 변형 각각에 대해 "eligibility 통과 종목의 T+5/T+20 forward
   return"을 quintile spread + Newey-West로 비교한다(§16과 동일한
   통계 방법) — **어느 정의가 실제로 좋은 종목을 통과시키는지**를
   가린다.
3. 두 변형의 **통과율 자체**도 비교한다 — 변형 B가 변형 A보다 통과율이
   높아지는지 낮아지는지(§8.4에서 종목별 정의가 시장보다 훨씬 자주
   "하락장"으로 판정하는 경향이 확인됐으므로, 변형 B는 통과율이
   높아질 가능성이 있다 — 다만 이것이 "더 정확한 판단"인지 "위험
   완화 약화"인지는 1번의 forward return 비교로만 판단한다).
4. **Go/No-Go**: 변형 B가 (a) 변형 A보다 통과 종목의 forward return이
   유의하게 낫거나 최소한 나쁘지 않고, (b) 하락장(§16 2차 기준)에서
   위험 신호를 놓치지 않는다는 것이 함께 확인돼야 "시장 공통 정렬"로
   전환한다. 둘 중 하나라도 실패하면 종목별 정의를 유지하되, `regime_
   conditional_signal` 쪽을 종목별 정의에 맞추는 대안도 함께 검토한다.

이 실험은 새 KIS 호출이 필요 없다 — 기존 3년 캐시와 이미 만들어둔
`_reconstruct_symbol_state`류 함수를 T+5/T+20 forward return과 결합
하기만 하면 된다. 다음 SPPV-3 착수 시 우선 수행 항목으로 지정한다.

### 9.7 다음 단계

1. `scripts/run_entry_score_penalty_ablation_cycle.py`를 `scripts/
   run_regime_conditional_shadow_cycle.py`와 함께 주기적으로(3년 캐시
   갱신 시 또는 매 SPPV 턴) 실행해 이력을 계속 쌓는다.
2. §9.6의 비교 실험을 SPPV-3 착수 시 최우선으로 수행한다 — 이 실험
   결과 없이 `regime_conditional_signal`을 `entry_score`에 통합하지
   않는다.
3. 두 이력 파일(`regime_conditional_signal_shadow_history.jsonl`,
   `entry_score_penalty_ablation_history.jsonl`)이 충분히 쌓이면,
   "국면 불일치 비율(79%)"과 "삼중 중복 비율" 자체가 시간에 따라
   안정적인지(오늘만의 우연이 아닌지) 재확인한다.

## 10. §9.6 비교 실험 실측 — 종목별 regime vs 시장 공통 regime의 forward return (2026-07-15)

### 10.1 실행 개요

`scripts/validate_entry_score_regime_definition_comparison.py`
(read-only)가 §9.6에서 설계한 실험을 그대로 실행했다 — 새 방법론이
아니라 §16 이원 검증이 확립한 cross-sectional quintile spread +
Newey-West 통계와 운영 함수 `_assess_buy_eligibility()`를 그대로
재사용한다. 3년 rolling 표본(87종목, 56,753건)에 대해 거래일·종목마다
**변형 A(현행, 종목별 `regime_label`)**와 **변형 B(시장 공통 국면,
KODEX 200 벤치마크 기준)**로 eligibility를 각각 재계산해, 통과 종목의
T+5/T+20 forward return을 비교했다.

**실행 결과(가정 없이 로그로 확인)**: 종료 코드 0, 87/87종목 성공,
**로그 내 `HTTP Request:` 카운트 0건** — 이번 실행도 3년 캐시가
완전히 재사용돼 신규 KIS 호출이 발생하지 않았음을 실제로 확인했다
(가정이 아니라 로그 기준 사실). 실행 시각 2026-07-15 11:18:30~
11:18:51(약 21초). 산출: `logs/signal_ic_entry_score_regime_
definition_comparison_2026-07-15.json`, `logs/entry_score_regime_
definition_comparison_run_2026-07-15.log`.

### 10.2 핵심 결과

| 항목 | 변형 A(종목별) | 변형 B(시장 공통) |
|---|---|---|
| eligibility 통과 표본 수 | 11,711/56,753(20.64%) | 10,639/56,752(18.75%) |
| T+5 통과군 평균 forward return | +0.9254%(t_NW=7.40) | **+1.0357%**(t_NW=7.70) |
| T+20 통과군 평균 forward return | +3.1861%(t_NW=7.31) | **+3.5780%**(t_NW=7.69) |
| (참고) baseline(전체 표본, eligibility 무관) | T+5 +0.6706%(t_NW=12.82) / T+20 +2.5912%(t_NW=11.82) | 〃 |
| 통과군 내부 quintile spread(T+20) | -1.5137%p(t_NW=**-2.84**, 유의 역전) | -1.8443%p(t_NW=**-3.06**, 유의 역전) |

### 10.3 해석(쉬운 설명)

1. **eligibility 필터 자체는 유효하다.** A/B 어느 정의를 쓰든,
   통과한 종목들의 평균 forward return(T+5/T+20)이 baseline(전체
   표본 평균)보다 높고 통계적으로 유의(t_NW 7.3~7.7, |t|≥2를 크게
   상회)하다 — "위험한 국면/약한 신호를 걸러낸다"는 eligibility의
   설계 의도가 실제로 작동하고 있다는 뜻이다.
2. **시장 공통 정의(B)가 종목별 정의(A)보다 두 지표 모두에서 낫다.**
   통과율은 더 낮으면서(18.75% < 20.64%, 더 엄격하게 걸러냄) 통과
   종목의 forward return은 더 높다(T+5: +1.04% > +0.93%, T+20:
   +3.58% > +3.19%). "더 많이 통과시켜서 좋아 보이는 착시"가 아니라
   "더 적게, 더 좋은 것만 통과"시킨다는 뜻이므로 **과잉 억제가 아니라
   더 정밀한 억제**로 해석된다.
3. **단, A와 B 차이 자체의 통계적 유의성은 이번 실행에서 검정하지
   않았다.** 두 정의 각각의 통과군이 baseline보다 유의하다는 것은
   확인했지만, "A의 평균과 B의 평균이 서로 유의하게 다른가"는 별도의
   대응표본(paired) 검정이 필요하다 — 두 통과군이 상당 부분 겹칠
   것이기 때문이다. 이 검정 없이 "B가 A보다 확실히 낫다"고 단정하지
   않는다.
4. **통과군 내부에서도 `overall_score` 기반 quintile spread는 여전히
   유의하게 역전(T+20 t_NW=-2.84~-3.06)한다.** 이는 §14의 3년 전체
   결론("`overall_score`가 안정적 알파를 못 낸다")이 eligibility를
   통과한 부분집합 안에서도 그대로 재현된다는 뜻이다 — eligibility
   필터는 유효하지만, 그 필터를 통과한 뒤 `overall_score`로 다시
   순위를 매기는 것은 여전히 실패한다. 이는 SPPV-3에서 반드시 별도로
   다뤄야 할 문제로 남긴다.

### 10.4 판정 — Watch(조건부 유리), 확정 Go 아님

**변형 B(시장 공통 정의)로의 전환은 §9.6의 Go 기준 (a)("통과 종목
forward return이 유의하게 낫거나 최소한 나쁘지 않음")를 방향상
충족한다** — 실측으로 더 나은 수치가 나왔다. 기준 (b)("하락장에서
위험 신호를 놓치지 않음")도 통과율이 더 낮아졌다는 사실 자체가
간접적으로 뒷받침한다(더 보수적으로 걸렀다).

**그러나 확정 Go로 선언하지 않는다** — ① A-B 차이 자체의 통계적
유의성 검정이 아직 없고, ② 표본이 3년 전체 pooled이며 최근 12개월
1차 게이트(§16)로는 아직 재확인하지 않았고, ③ 통과군 내부 quintile
spread가 여전히 역전된다는 문제가 남아있다. **"단순 통과율 증가만
보고 판단하지 말라"는 원칙에 따라, 판정은 Watch(조건부 유리, 시장
공통 정의가 더 나을 가능성이 실측으로 뒷받침됨)로 유지**하고, 다음
단계에서 A-B 차이의 직접 유의성 검정을 수행한 뒤 최종 판정한다.

### 10.5 다음 단계

1. A-B 차이(같은 종목·거래일 쌍에서 eligibility 판정이 갈린 표본만
   따로 추출)에 대한 대응표본 검정을 수행해 "시장 공통 정의가 통계적
   으로 유의하게 더 나은지"를 직접 확인한다.
2. §16 1차(최근 12개월) 창으로도 동일 비교를 반복해, 3년 pooled
   결과가 최근 시장에서도 재현되는지 확인한다.
3. 통과군 내부 quintile spread 역전 문제(§10.3-4)는 SPPV-3에서
   `overall_score` 자체의 재설계(§19 이하 feature 재설계 트랙과 연결)
   범위로 별도 다룬다.
4. 이 결과를 `entry_score`에 실제로 반영하는 결정은 위 1~2번 완료
   후 사용자 확인을 거쳐 진행한다 — 이번 턴은 shadow/validation
   범위에 머문다.

## 11. A/B 판정 불일치 표본 direct 비교 + 1차 창 재확인 (2026-07-15)

### 11.1 배경 — §10.5의 두 과제

§10(SPPV-2.20)의 비교는 "A 통과군 평균 vs B 통과군 평균"을 독립적으로
비교했다 — 그러나 두 통과군은 대부분(A 11,711건 중 10,639건, B
10,639건 중 10,639건 전부)이 겹치는 표본이라, "A와 B가 서로 다르게
판단한 표본"에서 어느 쪽이 옳았는지를 직접 보여주지 못했다. 이번 턴은
같은 종목-거래일 표본을 4개 배타적 집합(`A_only`/`B_only`/`both`/
`neither`)으로 분해하고, 최근 12개월(1차) 창에서도 같은 비교를
반복했다.

### 11.2 실행 개요

`scripts/validate_entry_score_regime_definition_ab_diff.py`
(read-only)가 §10의 표본 수집 함수(`_collect_symbol_rows`)를 그대로
재사용해 4개 집합을 분해했다. 3년 캐시 재사용, 종료 코드 0, 87/87종목
성공. **실제 KIS 호출 여부는 가정하지 않고 로그로 확인** — `HTTP
Request:` **0건**. 실행 시각 2026-07-15 22:19:22~22:19:45(약 23초).
산출: `logs/signal_ic_entry_score_regime_ab_diff_2026-07-15.json`,
`logs/entry_score_regime_ab_diff_run_2026-07-15.log`.

### 11.3 핵심 결과 — 예상 밖의 구조적 발견

**2차(3년, 56,753건)**:

| 집합 | 표본 수 | T+5 평균(t_NW) | T+20 평균(t_NW) |
|---|---|---|---|
| `A_only`(A만 통과, B는 차단) | 1,072 | -0.1694%(-0.62) | -0.7028%(-0.79) |
| `B_only`(B만 통과, A는 차단) | **0** | — | — |
| `both`(둘 다 통과) | 10,639 | +1.0357%(7.70) | +3.5780%(7.69) |
| `neither`(둘 다 탈락) | 45,042 | +0.6047%(11.80) | +2.4371%(11.63) |

**1차(최근 12개월, 21,315건)**:

| 집합 | 표본 수 |
|---|---|
| `A_only` | **0** |
| `B_only` | **0** |
| `both` | 5,468 |
| `neither` | 15,847 |

**가장 중요한 발견 — `B_only`가 3년·1차 창 모두에서 정확히 0건이다.**
이는 우연이 아니라 **구조적 사실**이다: 시장 공통 정의(B)의 eligibility
차단 조건은 `regime_label=='bearish_trend' and risk_tone=='risk_off'`
일 때만 발동하는데, 이 조건은 종목별 정의(A)가 이미 차단하지 않은
표본을 B가 "추가로" 차단하는 방향으로만 작동할 수 있다 — **B가 A를
포함하는 진부분집합(strict subset) 관계이지, A와 B가 서로 반대
방향으로 엇갈리는 관계가 아니다.** 즉 시장 공통 정의로 바꾼다는 것은
"통과 종목을 다르게 고르는 것"이 아니라 **"A가 통과시킨 것 중 일부
(`A_only`, 3년간 1,072건)를 추가로 걸러내는 것"**뿐이다.

### 11.4 A_only(=B가 추가로 차단하는 표본)의 품질

`A_only`(1,072건)의 forward return은 T+5 -0.17%/T+20 -0.70%로
**음수**이고, `both`(+1.04%/+3.58%)나 `neither`(+0.60%/+2.44%)보다도
낮다 — **방향은 "B가 추가로 차단하는 것이 맞다"는 §10의 결론과
일치**한다. 그러나 t_NW는 T+5 -0.62, T+20 -0.79로 **|t|<1, 통계적으로
전혀 유의하지 않다** — 표본이 1,072건으로 작지 않은데도 유의성이
나오지 않는다는 것은, 이 차이가 확실한 것이 아니라 노이즈에 가까울
수 있음을 뜻한다.

### 11.5 "일별 짝비교(day-matched paired diff)" 방법론이 이 데이터 구조에서
성립하지 않음을 확인

원래 §10.5는 "그날 `A_only`/`B_only` 둘 다 있는 날의 평균차를 모아
Newey-West로 검정"하는 방법을 계획했다. 그러나 `B_only`가 0건이므로
이 짝비교는 **정의상 계산할 표본이 없다**(n_days=0) — 이는 스크립트
결함이 아니라, §11.3에서 밝혀진 부분집합 구조의 직접적 귀결이다.
따라서 "A-B 차이의 유의성"을 검정하는 올바른 방법은 애초 계획했던
날짜-매칭 짝검정이 아니라, **`A_only`(B가 추가로 차단하는 유일한
표본군) 자체의 평균이 0과 다른지를 검정하는 것**으로 자연스럽게
단순화된다 — 이미 §11.4에서 그 검정을 수행했고, 결과는 유의하지 않다.

### 11.6 1차(최근 12개월) 창 — 재현 여부를 판단할 표본 자체가 없다

최근 12개월 창에서는 `A_only=0`, `B_only=0`이다 — A와 B가 **완전히
동일한 판정**을 내린다(both=5,468=A 통과 전체=B 통과 전체). 이는
§21 모니터링이 이미 확인한 사실(최근 12개월 창에 시장 공통
`bearish_trend`가 0일)과 정확히 정합적이다 — B의 차단 조건은 시장이
`bearish_trend`일 때만 발동하는데, 최근 12개월에는 그 조건이 발동할
기회 자체가 없었기 때문에 A와 B가 다를 수가 없다.

**따라서 "최근 12개월에서도 같은 방향성이 재현되는가"라는 질문에는
"재현 여부를 판단할 표본 자체가 존재하지 않는다"가 정확한 답이다.**
이는 "재현되지 않았다"(No-Go 근거)와는 다르다 — 검증 기회 자체가
아직 주어지지 않았을 뿐이다. §21 게이트가 `TRIGGERED`로 전환되기
전까지는 이 비교를 1차 창에서 반복해도 항상 같은(공집합) 결과가
나올 것이다.

### 11.7 판정 — Watch 유지(No-Go에 근접), 확정 Go 아님

공격형 시스템 관점에서 재확인한 결론:

1. **B로 전환해도 "더 좋은 종목을 새로 발굴"하는 효과는 없다** —
   `B_only`가 0이므로, B는 A가 이미 찾은 종목 집합에서 일부를 **빼는
   것**만 한다. 이는 "국면 정의를 바꾸면 기회가 늘어난다"는 가설을
   기각한다 — 공격형 목표(최고 기대수익률) 관점에서는 긍정적 신호가
   아니다(기회를 늘리지 않고 줄이기만 함).
2. **B가 추가로 빼는 종목(`A_only`)의 품질은 방향상 나쁘지만(-0.17%/
   -0.70%) 통계적으로 확실하지 않다(|t|<1).** §10에서 관측된 "B
   통과군이 A 통과군보다 forward return이 높다"는 결과의 메커니즘이
   이제 명확해졌다 — B가 나쁜 부분집합(`A_only`)을 빼기 때문에 남은
   평균이 올라가는 것인데, 그 나쁜 부분집합 자체가 유의하게 나쁜지는
   확인되지 않았다.
3. **최근 12개월(1차 게이트)에서는 이 차이 자체가 존재하지 않는다** —
   전환의 효과를 검증할 기회가 아직 없다.

**종합 판정: Watch 유지(No-Go에 근접), 시장 공통 정의로의 확정 전환
(Go)은 기각한다.** §9.6에서 세운 Go 기준("변형 B가 변형 A보다 통과
종목 forward return이 유의하게 낫거나 최소한 나쁘지 않음")은 이번
정밀 분해로 재검토하면 "B가 추가로 배제하는 부분의 품질이 유의하게
나쁘다"는 것이 확인돼야 충족되는데, 그 유의성이 나오지 않았다. 단순
통과율 감소나 "B 통과군 평균이 더 높다"는 집계 결과만으로 Go를
선언하지 않는다.

### 11.8 다음 단계

1. `A_only`(1,072건)의 표본을 국면별로 더 세밀하게 나눠(예: 실제
   하락폭 정도별) 유의성이 특정 하위구간에서만 나타나는지 확인한다 —
   지금은 하나로 뭉쳐 검정해 유의성이 희석됐을 가능성이 있다.
2. §21 게이트가 `TRIGGERED`로 전환되면(다음 하락장이 최근 12개월
   창에 들어오면) 이 비교를 반드시 재실행한다 — 지금은 표본 자체가
   없어 판단을 유보할 수밖에 없다.
3. "국면 정의 통일"이라는 방향 자체는 §10~11의 실측으로 근거가
   약해졌다 — SPPV-3의 우선순위를 "국면 정의 통일"에서 "`regime_
   conditional_signal`을 alpha layer에 직접 통합"(§3 제안)하는 쪽으로
   재조정할지 사용자와 논의한다.

## 12. alpha layer vs regime_conditional_signal 직접 비교 (2026-07-15)

### 12.1 배경 — 무게중심을 "차단(risk)"에서 "선별(alpha)"로 이동

§10~§11(SPPV-2.20/2.21)은 "국면 정의(종목별 vs 시장 공통) 자체를
바꾸는 것"을 검증했고, 그 결론은 명확히 Watch/No-Go에 근접했다 — 시장
공통 정의는 종목별 정의의 부분집합일 뿐 새로운 종목을 발굴하지
못했다(§11.3). 이는 **차단 축(누구를 걸러낼지)의 개선이 아니었다.**
이번 실험은 무게중심을 옮겨 **alpha 축(누구를 위로 올릴지)**을 직접
비교한다 — `entry_score`의 alpha layer(`overall_score`/`fast_score`/
`slow_score`를 0.45/0.20/0.15로 가중합) 자체를 `regime_conditional_
signal`(§2의 국면별 전환 신호)과 같은 3년 표본에서 맞대결시킨다.

### 12.2 현행 alpha layer의 코드 기준 정리

`_build_entry_score()`(`deterministic_trigger_engine.py:1128-1130`):

```python
score += 0.45 * _normalize_signed_score(overall)
score += 0.20 * _normalize_signed_score(fast)
score += 0.15 * _normalize_signed_score(slow)
```

`_normalize_signed_score(x) = clamp((x+1)/2)`(`:1252-1255`)는 모든
성분에 **동일한 선형 변환**(기울기 0.5, 절편 0.5)을 적용하므로, 위 식은

```text
alpha_layer = 0.4 + 0.5·(0.45·overall + 0.20·fast + 0.15·slow)
```

로 대수적으로 정리된다 — **순위(ranking)만 보면** 원 가중치 그대로의
`current_alpha_composite = 0.45·overall + 0.20·fast + 0.15·slow`와
완전히 같은 순서를 만든다(코드의 수학적 귀결, 근사가 아니다). 이번
실험은 `current_alpha_composite`를 그대로 계산해 비교 대상으로 삼았다
— 새 alpha layer를 발명한 것이 아니라 **현재 코드가 실제로 만드는
순위 그대로**를 재현했다.

### 12.3 실행 개요

`scripts/validate_alpha_layer_vs_regime_conditional_signal.py`
(read-only)가 3년 rolling 표본(87종목, 56,753건)에 대해 거래일마다
`current_alpha_composite`와 `regime_conditional_signal`을 함께
계산하고, §16 이원 검증 도구(cross-sectional quintile spread +
Newey-West)로 비교했다. 공정 비교를 위해 `regime_conditional_signal`
이 산출 가능한 표본(판정불가 국면 제외, 3년 56,235건/최근 12개월
21,315건)에서 `current_alpha_composite`도 별도로 재계산해 나란히
제시한다.

3년 캐시 재사용, 종료 코드 0, 87/87종목 성공. **실제 KIS 호출 여부는
가정하지 않고 로그로 확인** — `HTTP Request:` **0건**. 실행 시각
2026-07-15 23:10:51~23:11:13(약 22초). 산출: `logs/signal_ic_alpha_
layer_vs_regime_conditional_signal_2026-07-15.json`,
`logs/alpha_layer_vs_regime_conditional_signal_run_2026-07-15.log`.

### 12.4 핵심 결과

| 창 | horizon | 신호 | spread 평균 | t_NW | 양수 비율 |
|---|---|---|---|---|---|
| 2차(3년) | T+5 | `current_alpha_composite` | +0.275%p | 1.02 | 53.2% |
| 2차(3년) | T+5 | `regime_conditional_signal` | **+0.666%p** | **2.52** | **61.2%** |
| 2차(3년) | T+20 | `current_alpha_composite` | +1.043%p | 1.32 | 52.1% |
| 2차(3년) | T+20 | `regime_conditional_signal` | **+2.082%p** | **2.33** | **62.9%** |
| 1차(최근 12개월) | T+5 | `current_alpha_composite` | +0.716%p | 1.29 | 55.9% |
| 1차(최근 12개월) | T+5 | `regime_conditional_signal` | **+0.859%p** | 1.55 | **60.0%** |
| 1차(최근 12개월) | T+20 | `current_alpha_composite` | +1.952%p | 1.26 | 58.0% |
| 1차(최근 12개월) | T+20 | `regime_conditional_signal` | **+3.010%p** | 1.47 | **64.5%** |

### 12.5 해석 — "더 잘 고르는가"에 대한 답

1. **2차(3년) 창에서 `regime_conditional_signal`이 T+5/T+20 둘 다
   §16 유의 임계(|t_NW|≥2)를 통과한다(2.52, 2.33)** — 반면 현행
   alpha layer(`current_alpha_composite`)는 같은 표본, 같은 기간에서
   어디서도 유의하지 않다(1.02~1.39). 이는 §19/§20에서 이미 확인된
   `regime_conditional_signal`의 유의성이, 현재 실제로 운영 중인
   alpha layer와의 **직접 대결에서도 재현·재확인**됐다는 뜻이다.
2. **spread 크기, t값, 양수 비율 — 4개 관측치(2개 창×2개 horizon)
   전부에서 `regime_conditional_signal`이 `current_alpha_composite`
   보다 일관되게 우세하다.** 특히 T+20(더 긴 보유 기간)에서 격차가
   더 벌어진다(3년: 2.082%p vs 1.043%p, 거의 2배). 이는 "더 막는
   방법"이 아니라 **"더 공격적으로 좋은 종목을 위에 올리는" 관점에서
   실제로 우위가 있다**는 것을 뒷받침한다 — 방어적 차단 강화가 아니라
   선별 품질 개선으로 해석해야 한다.
3. **1차(최근 12개월)에서는 두 신호 모두 §16 임계를 통과하지
   못한다**(1.26~1.55) — 그러나 `regime_conditional_signal`은 여기
   서도 4개 지표 모두에서 `current_alpha_composite`보다 우세하다.
   1차 미달의 원인은 이미 §21에서 확인된 구조적 사실(최근 12개월에
   시장 공통 하락장이 0일이라 `reversal_1m` 분기가 전혀 발동하지
   못함)이지, `regime_conditional_signal` 자체의 결함이 아니다.

### 12.6 판정 — Conditional Go(2차 검증 통과, 1차 게이트 대기)

**단순 통과율 비교가 아니라 forward return 품질로 판단한 결과,
`regime_conditional_signal`이 현행 alpha layer보다 일관되게 우수하다
— 이 결과를 지나치게 보수적으로 눌러 해석하지 않는다.** 2차(3년)
창에서는 두 horizon 모두 통계적으로 유의한 우위를 확보했다. 다만
1차(최근 12개월) 게이트는 여전히 미달인데, 그 원인이 신호 자체의
결함이 아니라 최근 시장에 검증 기회(하락장)가 없었다는 §21의 구조적
사실에 있으므로, **Watch로 낮춰 부르지 않고 "Conditional Go"로
명시한다** — §21 모니터링이 `TRIGGERED`로 전환되는 즉시 1차 게이트를
재확인해 최종 Go 여부를 확정한다는 뜻이다.

**억지로 완전한 Go를 선언하지도 않는다** — §16의 이원 기준(1차+2차
모두 충족)을 자의로 낮추지 않고, 1차 게이트가 실제로 통과할 때까지는
`entry_score` 코드 변경을 보류한다.

### 12.7 다음 단계

1. §21 게이트가 `TRIGGERED`로 전환되면 이 비교를 최우선으로
   재실행한다 — 1차 창에서도 유의성이 확인되면 SPPV-3
   `entry_score` alpha layer 교체(§3 제안)를 정식 착수 후보로
   올린다.
2. `current_alpha_composite`가 3년 전체에서 유의성을 전혀 확보하지
   못했다는 사실은 §14(SPPV-2.7)의 "정적 단일 가중 신호는 안정적
   알파를 못 낸다"는 결론을 alpha layer 자체 수준에서 재확인한
   것이다 — `regime_conditional_signal`로의 교체가 단순 대안이
   아니라 필요한 개선이라는 근거가 더 쌓였다.
3. 이 비교 결과를 근거로 SPPV-3의 우선순위를 "국면 정의 통일"(§11,
   Watch/No-Go)에서 "alpha layer 교체"(§12, Conditional Go)로
   공식 재조정할지 사용자 확인을 받는다.

## 13. 새 alpha 상위군과 기존 차단 축 결합 효과 (2026-07-15)

> **[2026-07-16 §14 보정 안내]** 아래 §13.4~§13.6은 **활동성 필터
> ablation(§14)을 실행하기 전, 2026-07-15 당시의 1차 해석**이다.
> 당시에는 "차단된 표본도 forward return이 플러스"라는 사실만으로
> "과잉 억제의 강력한 증거"·"진짜 병목"·"주범" 같은 단정적 표현을
> 썼으나, 이는 옳은 판단 기준(=차단을 실제로 제거/완화했을 때
> 기대수익률이 개선되는가)으로 검증한 것이 아니었다. §14에서 실제로
> ablation한 결과, 완전 제거는 오히려 생존군 평균을 낮췄고(No-Go),
> 완화(1.10→1.00)도 방향만 확인됐을 뿐 확정 근거는 아니다(Watch).
> **이 문서를 읽는 사람은 §13.4~§13.6의 단정적 표현이 아니라 §14의
> 보정된 결론을 최종 판단 기준으로 삼아야 한다.** 아래 원문은
> 조사가 어떻게 활동성 필터를 발견하게 됐는지의 이력으로만 보존한다.

### 13.1 배경 — "더 잘 고르는 alpha"를 찾은 뒤에도 기존 차단이 그 효과를 죽이는가

§12(SPPV-2.22)는 `regime_conditional_signal`이 alpha layer로서 현행보다
유의하게 낫다는 것을 확인했다(Conditional Go). 그러나 그 확인은 "이
신호로 순위를 매기면 상위/하위 quintile 차이가 유의하다"는 것이었지,
**"실제로 이 신호를 alpha layer에 넣고 기존 차단 로직(§8에서 정량화한
세 축)을 그대로 두면 상위권 종목들이 살아남는지"**는 아직 확인하지
않았다. 이번 실험은 그 질문에 답한다 — 방어 강화가 아니라 "새 alpha가
찾은 좋은 종목이 기존 차단 때문에 다시 사라지는가"를 실측한다.

### 13.2 실행 개요

`scripts/validate_new_alpha_vs_existing_blocking_axes.py`(read-only)가
3년 rolling 표본(87종목)에서 거래일별 cross-sectional 상위 20%를
`regime_conditional_signal` 기준으로 뽑고, 그 상위군에 **운영 함수
`_build_entry_score()`/`_assess_buy_eligibility()`를 그대로 호출**해
(종목별 regime 기준, 현재 실제로 도는 로직) 생존/차단 여부와 forward
return을 비교했다. 3년 캐시 재사용, 종료 코드 0, 87/87종목 성공.
**실제 KIS 호출 여부는 가정하지 않고 로그로 확인** — `HTTP Request:`
**0건**. 산출: `logs/signal_ic_new_alpha_vs_existing_blocking_axes_
2026-07-15.json`, `logs/new_alpha_vs_existing_blocking_axes_run_
2026-07-15.log`.

### 13.3 핵심 결과 — 상위군의 60~68%가 차단된다

| 창 | 상위 20% 표본 | 생존 | 차단됨 |
|---|---|---|---|
| 2차(3년) | 10,999건 | 3,491건(31.7%) | **7,508건(68.3%)** |
| 1차(최근 12개월) | 4,165건 | 1,621건(38.9%) | **2,544건(61.1%)** |

| 창 | horizon | 상위군 전체(차단 없다고 가정) | 생존(현재 운영 로직) | 차단됨 |
|---|---|---|---|---|
| 2차(3년) | T+5 | +1.008%(t_NW=9.06) | +1.422%(t_NW=5.89) | +0.815%(t_NW=**6.86**) |
| 2차(3년) | T+20 | +3.554%(t_NW=10.35) | +4.381%(t_NW=5.78) | +3.170%(t_NW=**8.35**) |
| 1차(최근 12개월) | T+5 | +1.711%(t_NW=7.52) | +1.972%(t_NW=4.50) | +1.544%(t_NW=**6.29**) |
| 1차(최근 12개월) | T+20 | +5.721%(t_NW=8.16) | +5.871%(t_NW=4.54) | +5.626%(t_NW=**6.71**) |

**차단된 표본도 forward return이 강하게 유의하게 양(+)으로
관찰됐다** — 심지어 1차 창 T+20에서는 생존군(+5.87%)과 차단군
(+5.63%)의 차이가 거의 없었다. **이 시점(§14 검증 전)에는** 이를
"차단이 나쁜 종목을 걸러낸다"는 가정과 달리 "차단된 표본의 절대
다수가 손실이 아니라 플러스 수익을 내고 있었다"는 관찰로만 받아
들였다 — **다만 이 관찰은 "차단을 제거했을 때 기대수익률이 실제로
개선되는가"를 검증한 것은 아니었다.** 그 질문은 §14에서 별도
ablation으로만 답할 수 있었고, 실제로 §14에서는 완전 제거 시
생존군 평균이 오히려 낮아지는 결과가 나와(No-Go), "차단된 표본이
플러스였다"는 사실만으로 제거/완화가 유리하다고 단정할 수 없음이
드러났다.

### 13.4 (당시 해석, §14 보정 전) 차단 사유 재발견 — regime 축이 아니라 "활동성 필터"가 가장 빈번함

§8/§9/§11에서 계속 조사해온 세 축(entry_score regime penalty,
eligibility regime block, eligibility negative floor)이 이 차단의
가장 큰 원인일 것이라 예상했으나, `scripts/diagnose_blocked_reason_
distribution.py`(read-only, 신규 KIS 호출 0건, 종료 코드 0)로 실제
`_assess_buy_eligibility()`의 최종 실패 사유를 집계한 결과 **예상과
다른 분포가 나왔다**(아래는 "가장 빈번한 차단 사유"를 보여줄 뿐,
그 사유가 과잉 억제인지는 §13.5에서 보듯 이 시점엔 아직 검증되지
않았고, §14에서 별도로 ablation해야 판단할 수 있었다):

| 실패 사유 | 3년(7,508건 중) | 최근 12개월(2,544건 중) |
|---|---|---|
| `eligibility_low_relative_activity` | **5,983건(79.7%)** | **2,533건(99.6%)** |
| `eligibility_core_risk_off_guard_blocked`(§8의 축B) | 1,270건(16.9%) | 0건 |
| `eligibility_negative_overall_floor`(§8의 축C) | 253건(3.4%) | 11건(0.4%) |
| `eligibility_negative_slow_floor` | 2건(0.0%) | 0건 |

**`eligibility_low_relative_activity`가 차단의 압도적 대부분(3년
79.7%, 최근 12개월 99.6%)을 차지한다.** 이 조건은 코드
(`deterministic_trigger_engine.py:493-499`)에서 다음과 같이 정의된다:

```python
if (
    volume_surge_ratio is not None
    and turnover_surge_ratio is not None
    and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
):
    reasons.append("eligibility_low_relative_activity")
    return False, tuple(reasons)
```

즉 **"거래량 급증 비율과 거래대금 급증 비율 중 큰 쪽이 평소 대비
10% 이상 늘지 않으면 차단"**하는 조건이다 — 국면(regime)이나 신호
강도(overall/slow)와 **전혀 무관한, 순수 유동성/활동성 게이트**다.
§8/§9/§11이 지금까지 조사한 "regime 관련 삼중 중복"은, 새 alpha
(`regime_conditional_signal`) 상위군의 차단 사유 중에서는 상대적으로
드물었다(3년 16.9%+3.4%=20.3%, 최근 12개월 0.4%) — **차단 빈도
기준으로는 완전히 별개의 네 번째 축(활동성 필터)이 가장 크게
나타났다.** (주의: "차단 빈도가 크다"는 그 자체로 "병목"이나
"과잉 억제"를 뜻하지 않는다 — 이는 §14에서 실제 ablation으로
검증해야 하는 별개의 질문이며, §13.5는 그 검증 이전의 추정임을
아래에서 밝힌다.)

### 13.5 (당시 해석, §14 보정 전) 과잉 억제 가능성에 대한 추정 — §14에서 대부분 반박·수정됨

1. **활동성 필터가 걸러낸 종목(3년 5,983건, 최근 12개월 2,533건)의
   forward return이 나쁘지 않다** — 이 필터가 알파와 무관하게
   작동하므로, "alpha가 찾은 좋은 종목"과 "최근 거래가 조용했던
   종목"이 상당 부분 겹칠 뿐, 실제 수익성과는 관계가 약할 수
   있다는 **추정**이 가능했다. 다만 이 추정은 "차단된 표본이
   플러스"라는 사실에만 근거했고, "제거했을 때 실제로 기대수익률이
   개선되는가"는 검증하지 않은 것이었다 — §14 ablation에서 완전
   제거는 오히려 생존군 평균을 낮추는 것으로 확인되어(No-Go), 이
   추정은 **반박됐다**.
2. "regime_conditional_signal을 넣어도 기존 차단 축이 그대로면
   효과가 상쇄되는가?"에 대한 답은 여전히 유효하다(60~68% 차단).
   그러나 그 상쇄의 **가장 빈번한 원인**은 §8/§9/§11이 조사한
   regime 관련 축이 아니라 활동성 필터(threshold 1.10)라는 것 —
   이는 SPPV-3의 조사 범위를 재조정할 근거가 됐다. **다만 당시
   "활동성 필터의 임계값(1.10)이 과도한지가 훨씬 더 큰 병목"이라고
   쓴 것은 앞질러 간 표현이었다 — "병목"인지 여부는 §14 ablation
   으로만 답할 수 있고, 그 결과는 완화 방향만 Watch(추가 검증
   필요)로 남았을 뿐 "병목 확정"은 아니다.**
3. 이 시점에는 활동성 필터를 제거했을 때의 forward return을 직접
   ablation하지 않았다(상위군 전체=차단 없음 가정 값을 근사치로만
   사용). **이 한계는 §14에서 실제로 해소됐다** — §14의 3개
   시나리오(현행/완화/완전 제거) 정밀 비교 결과를 최종 기준으로
   삼는다.

### 13.6 (당시 판정, §14로 갱신됨) Watch — alpha 자체는 Conditional Go 유지

**`regime_conditional_signal`의 alpha layer 대체 가치(§12)는 이번
실험으로 훼손되지 않았다** — 여전히 Conditional Go다(이 부분은
§14 이후에도 유효). **"결합 사용 시나리오"(새 alpha + 기존 차단
로직 그대로)는 확정 Go로 선언하지 않는다** — 이 시점엔 활동성
필터가 과잉 억제인지 아직 검증 전이었기 때문이다. **당시 판정:
Watch(추가 검증 필요).** §14에서 실제 ablation을 수행한 결과도
**결합 시나리오는 여전히 Watch로 유지**된다(완전 제거는 No-Go,
완화는 방향만 확인된 Watch) — 즉 이 판정 자체는 §14 이후에도
바뀌지 않았지만, 그 근거는 "필터가 과잉 억제라서"가 아니라
"완화가 개선을 보이는 방향이되 아직 확정 근거가 부족해서"로
바뀌었다는 점이 중요하다.

### 13.7 다음 단계 — 우선순위 재조정

1. **`eligibility_low_relative_activity` ablation 실험을 다음
   최우선으로 지정한다** — 이 필터를 제거(또는 임계값 완화)했을 때
   전체 BUY 후보 표본의 forward return이 개선되는지/악화되는지
   직접 검증한다. §8/§9/§11의 regime 축 조사보다 이 실험의 영향력이
   훨씬 크다는 것이 이번 턴에 확인됐다.
2. SPPV-3의 우선순위를 "국면 정의 통일"(§11) → "alpha layer
   교체"(§12) → **"활동성 필터 재검토"(§13, 신규 최우선)**로
   재조정할지 사용자 확인을 받는다.
3. §21 게이트가 `TRIGGERED`로 전환되는 시점과 별개로, 활동성 필터
   ablation은 지금 당장(신규 KIS 호출 없이) 수행 가능하다 — 다음
   턴 착수 후보로 남긴다.

## 14. `eligibility_low_relative_activity` 활동성 필터 정밀 ablation (SPPV-2.24)

§13.7에서 신규 최우선으로 지정한 활동성 필터 ablation을 실행했다.
스크립트: `scripts/validate_activity_filter_ablation.py`. 산출:
`logs/signal_ic_activity_filter_ablation_2026-07-16.json`, 실행 로그
`logs/activity_filter_ablation_run_2026-07-16.log` (신규 KIS 호출
0건 — `grep -c "HTTP Request:"` 확인, 기존 3년 캐시 88개 파일로
전량 서빙됨).

### 14.1 현행 코드 재확인

`deterministic_trigger_engine.py:493-499`:
```python
if (
    volume_surge_ratio is not None
    and turnover_surge_ratio is not None
    and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
):
    reasons.append("eligibility_low_relative_activity")
    return False, tuple(reasons)
```
이 체크 직후의 참여율 체크 2개는 `portfolio_allocation.
recommended_max_order_value is not None`을 전제로 하는데, 이번
shadow 재구성(모든 SPPV 실험 공통)에서는 배분 상태를 시점 복원할 수
없어 `portfolio_allocation=None`을 그대로 사용한다 — 즉 이 체크
직후 항상 `eligibility_execution_feasibility_pass=True`로 낙하한다.
따라서 "활동성 필터 제거"는 곧 "그 사유로만 탈락한 표본을 즉시
통과 처리"와 동치이며, 별도 로직 재구현 없이 안전하게 시뮬레이션할
수 있음을 코드로 확인했다.

### 14.2 실험 설계

`regime_conditional_signal` 상위 20% 표본(§12/§13과 동일 정의) 중
활동성 필터를 제외한 다른 모든 체크를 이미 통과한 행을 대상으로,
활동성 비율 `max(volume_surge_ratio, turnover_surge_ratio)`의 임계값만
바꿔가며 3개 시나리오를 비교:

| 시나리오 | threshold |
|---|---|
| 현행 유지 | 1.10 |
| 완화 | 1.00 |
| 완전 제거 | 없음(필터 자체를 스킵) |

2차(3년, 56,753건 중 상위 10,999건)와 1차(최근 12개월, 21,315건 중
상위 4,165건) 두 창 모두에서 동일하게 산출.

### 14.3 실측 결과

**2차(3년, 상위 10,999건):**

| 시나리오 | 생존 n(%) | T+5 평균 | T+5 t_NW | T+5 양수율 | T+20 평균 | T+20 t_NW | T+20 양수율 |
|---|---|---|---|---|---|---|---|
| 현행(1.10) | 3,491(31.7%) | +1.4218% | 5.89 | 52.39% | +4.3809% | 5.78 | 51.76% |
| 완화(1.00) | 4,148(37.7%) | **+1.4894%** | **6.85** | **52.82%** | **+4.5601%** | **6.58** | 52.10% |
| 제거 | 9,474(86.1%) | +0.9833% | 8.02 | 50.74% | +3.8823% | 10.16 | **52.73%** |
| (참고)상위군 전체·무차단 | 10,999(100%) | +1.0079% | 9.06 | 51.20% | +3.5544% | 10.35 | 52.45% |

**1차(최근 12개월, 상위 4,165건):**

| 시나리오 | 생존 n(%) | T+5 평균 | T+5 t_NW | T+5 양수율 | T+20 평균 | T+20 t_NW | T+20 양수율 |
|---|---|---|---|---|---|---|---|
| 현행(1.10) | 1,621(38.9%) | +1.9724% | 4.50 | 53.92% | +5.8709% | 4.54 | 53.12% |
| 완화(1.00) | 1,931(46.4%) | **+2.1445%** | 5.48 | **55.15%** | **+6.4317%** | 5.44 | **54.17%** |
| 제거 | 4,154(99.7%) | +1.7090% | 7.48 | 53.61% | +5.7532% | 8.18 | 54.57% |
| (참고)상위군 전체·무차단 | 4,165(100%) | +1.7108% | 7.52 | 53.66% | +5.7210% | 8.16 | 54.48% |

두 창 모두 동일한 정성적 패턴: **평균 수익률·양수율 기준으로는
"완화(1.00)"가 최고점**이고, "완전 제거"는 오히려 "현행 유지"보다
낮아져 사실상 무차단 전체 평균에 수렴한다(2차 T+20 제거=3.8823%
vs 무차단 전체=3.5544% — 거의 동일). t_NW는 표본이 늘수록
표준오차가 줄어 제거 시나리오에서 가장 높게 나오지만, 이는 "표본이
많아서 통계적으로 유의해 보이는 것"일 뿐 평균 수익률 자체는
오히려 낮다 — 표본수 증가가 곧 품질 개선을 의미하지 않는다는
점을 데이터로 확인했다(사용자 지시사항 "통과율이 늘었다고 긍정
판단하지 말 것"과 정확히 일치하는 사례).

### 14.4 질문에 대한 답 (해석 보정판 — 2026-07-16 2차 검토 반영)

**보정 배경**: 최초 작성본은 "차단된 표본도 forward return이
플러스"라는 사실과 "완전 제거는 무차단 전체 수준으로 회귀한다"는
사실을 근거로 "필터는 주범이 아니다/과잉 억제가 아니다"라고 확정
서술했다. 그러나 이 판단 기준 자체가 틀렸다는 지적을 받았다 —
**옳은 비교 기준은 "차단된 표본이 플러스냐"가 아니라 "차단을
제거/완화했을 때 기대수익률이 실제로 개선되는가"다.** 아래는 이
기준으로 다시 정리한 결과다.

- **활동성 필터 제거가 기대수익률을 개선하는가?** → **아니오,
  개선된다는 근거는 없다.** 완전 제거 시 생존군의 평균 forward
  return과 양수율이 무차단 상위군 전체 수준으로 회귀(수렴)하며,
  현행(1.10) 유지 시의 생존군 평균보다도 낮다(2차 T+20 현행
  +4.381% vs 제거 +3.882% vs 무차단 전체 +3.554%). 즉 **현재
  실측상으로는 필터를 유지했을 때의 생존군 평균이 무차단 전체보다
  높다** — 이 하나의 사실만으로 필터를 "완전히 해롭다"고 볼 근거는
  없다.
- **임계값 완화(1.00)는 개선하는가?** → **방향성은 있으나 확정할
  수준은 아니다.** 생존 종목 수가 31.7%→37.7%(2차), 38.9%→
  46.4%(1차)로 늘면서 T+5/T+20 평균 수익률·t_NW·양수율이 현행보다
  소폭(0.07~0.18%p 수준) 높게 나왔고 두 창에서 방향이 일관됐다.
  다만 (a) 검증한 shadow threshold가 1.00 단 하나뿐이고, (b)
  개선폭이 크지 않으며, (c) 동일 표본·동일 window에서의 단일
  실험이라 out-of-sample 재확인이 없다는 점에서, 이를 "완화가
  기대수익률을 개선한다"는 확정 결론으로 쓰기에는 근거가 아직
  부족하다. **"완화 방향이 유력해 보이나, 확정 짓기 위해서는 추가
  검증(다른 threshold, 다른 기간)이 필요하다"는 수준으로만 기록한다.**
- **활동성 필터가 BUY 0건의 주범인가 / 과잉 억제인가?** →
  **이번 실측만으로는 확정할 수 없다.** §13에서 확인한 "차단
  사유의 79.7~99.6%를 차지"라는 사실은 이 필터가 가장 빈번하게
  작동하는 차단 축이라는 것을 보여줄 뿐, 그 자체로 "과잉 억제"나
  "주범"을 증명하지 않는다. 오히려 이번 실측은 (제거 시나리오가
  현행보다 낮은 평균을 보인다는 점에서) **필터를 완전히 없애는
  것이 정답이 아니라는 근거**는 제공했지만, 반대로 필터가
  "정당함/불필요함" 어느 쪽인지를 확정할 만큼 강한 근거는 아니다.
  **결론: "재검토가 필요한 후보"로 남기되, "주범 확정" 또는
  "과잉 억제 확정"이라는 표현은 쓰지 않는다.**

### 14.5 판정 — Watch(추가 검증 필요), 완전 제거만 No-Go로 확정

**활동성 필터 자체를 제거하는 안은 No-Go로 확정** — 데이터가
일관되게 기대수익률(평균 forward return)이 개선되지 않음을
보여준다(현행 유지보다도 낮음). **임계값을 1.10 → 1.00으로
완화하는 안은 Watch(방향은 유력, 확정 아님)** — 1차·2차 두 창
모두에서 생존 종목 수 증가와 함께 평균 수익률·t_NW·양수율이 소폭
개선되는 방향은 일관되게 관측됐으나, 개선폭이 작고 단일 threshold
실험이라 "Conditional Go"로 올리기에는 근거가 이르다. **필터
자체의 존폐(주범 여부/과잉 억제 여부) 판정도 Watch** — 확정하지
않는다. 이번 턴은 shadow 검증 범위이며, 실제
`deterministic_trigger_engine.py`의 threshold 상수는 이 문서가
더 강한 Go 판정을 확보하기 전까지 변경하지 않는다.

### 14.6 다음 단계

1. threshold를 1.00 외에도 추가로(예 0.95, 0.90) 스윕하여 완화
   방향의 개선이 재현되는지, 개선-정체/역전 지점(sweet spot)이
   있는지 확인하는 추가 shadow 실험 — 이것이 완화안을 Conditional
   Go로 올리기 위한 선행 조건이다.
2. 가능하면 표본 기간을 다르게 쪼개(예: 최근 6개월 vs 그 이전
   6개월) out-of-sample 재현성을 확인 — 현재는 동일 창 내 단일
   비교라 재현성 검증이 없다.
3. §13에서 남았던 "결합 사용 시나리오"의 Watch 판정은 이번 결과로도
   **Watch로 유지**한다 — 완화 방향이 유력하다는 정황은 늘었으나,
   확정 Go로 상향할 근거는 아직 없다.
4. threshold 상수를 실제 운영 코드에 반영하는 것은 위 1~2가
   Conditional Go 이상으로 확정된 뒤, 별도 턴에서 사용자 승인을
   받아 진행한다.

## 15. 활동성 필터 threshold sweep + 기간 분할 재현성 검증 (SPPV-2.25, 2026-07-16)

§14.6이 지시한 후속 검증 두 가지(threshold 추가 스윕, 기간 분할
재현성 확인)를 실행했다. 스크립트: `scripts/validate_activity_
filter_threshold_sweep.py`(read-only, §14의 `validate_activity_
filter_ablation.py`에서 `_collect_symbol_rows`/`_eligible_under_
threshold`/`_summarize`/`_top_quintile_rows`를 그대로 재사용). 산출:
`logs/signal_ic_activity_filter_threshold_sweep_2026-07-16.json`,
실행 로그 `logs/activity_filter_threshold_sweep_run_2026-07-16.log`
(신규 KIS 호출 0건 — `grep -c "HTTP Request:"` 확인, 기존 3년 캐시
88개 파일로 전량 서빙됨).

### 15.1 실험 설계

`regime_conditional_signal` 상위 20% 표본(§13/§14와 동일 정의)을
대상으로, 활동성 비율 `max(volume_surge_ratio, turnover_surge_
ratio)` threshold를 **1.10(현행)/1.05/1.00/0.95/0.90** 5단계로
스윕했다. 추가로 3년 rolling 표본을 거래일 기준 **전반부/후반부로
양분**해(2023-10-10~2025-02-11 vs 2025-02-12~2026-06-16, 각각
약 28,300건 규모), 완화 효과가 특정 시기의 우연이 아닌지 확인했다.
2차(3년 전체)/1차(최근 12개월)/전반부/후반부 4개 창 모두에서 동일한
sweep을 반복했다.

### 15.2 실측 결과

**2차(3년, 상위 10,999건) — threshold별 생존군 T+5/T+20 평균, 현행(1.10) 대비 delta:**

| threshold | 생존(%) | T+5 평균 | Δvs현행 | T+20 평균 | Δvs현행 |
|---|---|---|---|---|---|
| 1.10(현행) | 31.7% | +1.4218% | — | +4.3809% | — |
| 1.05 | 34.4% | +1.4551% | +0.033%p | +4.5474% | +0.167%p |
| 1.00 | 37.7% | +1.4894% | +0.068%p | +4.5601% | +0.179%p |
| 0.95 | 41.1% | +1.5452% | +0.123%p | +4.6615% | +0.281%p |
| 0.90 | 44.7% | +1.5105% | +0.089%p | +4.6569% | +0.276%p |

2차(3년) 전체에서는 1.10→0.95까지 단조 개선, 0.90에서 T+5는 소폭
꺾이지만(1.5105<1.5452) 여전히 현행보다 높다.

**1차(최근 12개월, 상위 4,165건):** 1.10→0.90까지 T+5/T+20 모두 단조
개선(현행 +1.9724%/+5.8709% → 0.90 +2.2788%/+6.7785%, Δ최대
+0.31%p/+0.91%p).

**3년 전반부(2023-10-10~2025-02-11, 상위 5,457건) — 정반대 패턴:**

| threshold | 생존(%) | T+5 평균 | Δvs현행 | T+20 평균 | Δvs현행 |
|---|---|---|---|---|---|
| 1.10(현행) | 24.9% | +0.7394% | — | +1.7865% | — |
| 1.05 | 27.1% | +0.6945% | **-0.045%p** | +1.7406% | **-0.046%p** |
| 1.00 | 29.8% | +0.7103% | **-0.029%p** | +1.6748% | **-0.112%p** |
| 0.95 | 32.5% | +0.6615% | **-0.078%p** | +1.6553% | **-0.131%p** |
| 0.90 | 35.7% | +0.5728% | **-0.167%p** | +1.6290% | **-0.157%p** |

**전반부에서는 threshold를 완화할수록 평균 수익률이 단조로
"악화"된다** — 2차 전체/1차/후반부에서 관찰된 "완화=개선" 패턴과
정반대다.

**3년 후반부(2025-02-12~2026-06-16, 상위 5,542건):** 1.10→0.90까지
T+5/T+20 모두 단조 개선(현행 +1.8568%/+6.0346% → 0.90
+2.1277%/+6.6496%) — 1차(최근 12개월)와 거의 동일한 패턴(후반부와
최근 12개월 표본이 크게 겹치기 때문).

### 15.3 해석 — 완화 효과는 재현되지 않는다

2차(3년) 전체와 1차(최근 12개월)만 보면 "완화가 일관되게 개선"으로
보이지만, **이는 사실상 후반부(=최근 12개월과 거의 동일한 시기)
효과가 3년 pooled 평균을 끌어올린 것**이었다. **3년의 전반부만
따로 떼어 보면 완화 방향이 정반대로 나타난다** — 즉 threshold
1.10→1.00(또는 그 이하) 완화가 "가져오는 개선"은 **특정 시기(최근
12~18개월)에 국한된 현상일 가능성이 높고, 3년 전체를 대표하는
일관된 규칙성이 아니다.**

이는 §14가 이미 경계했던 "표본 증가로 t값이 커지는 것과 품질
개선을 혼동하지 말 것"이라는 원칙의 연장선에 있는 발견이다 — 이번
sweep도 마찬가지로 "여러 threshold에서 평균이 계속 개선되는 것처럼
보인다"고 해서 그 자체가 강한 근거가 되지 않으며, **기간을 쪼개
보았을 때 정반대 방향이 나온다면 그 개선은 재현성이 없는 것으로
간주해야 한다.**

### 15.4 질문에 대한 답

- **1.00 완화가 재현성 있는 개선인가?** → **아니오.** 2차(3년
  전체)·1차(최근 12개월)·3년 후반부에서는 개선 방향이 나타나지만,
  3년 전반부에서는 정반대(악화) 방향이 나타난다. 두 반기 중 하나가
  반대 방향을 보이는 이상, "재현성 있는 개선"이라고 결론 내릴 수
  없다.
- **0.95/0.90으로 더 완화하면 품질이 꺾이는가?** → 창마다 다르다.
  2차(3년) 전체에서는 0.90에서 T+5가 소폭 꺾이고(0.95 대비), 1차·
  후반부에서는 0.90까지 계속 개선되며, 전반부에서는 0.90까지 계속
  악화된다. **일관된 sweet spot은 발견되지 않았다** — 창마다 최적
  threshold가 다르게 나타나는 것 자체가 이 완화 효과가 불안정하다는
  근거다.
- **지금 시점에서 1.00 완화를 Watch에서 Conditional Go 이상으로
  올릴 근거가 생겼는가?** → **아니오, 오히려 근거가 약해졌다.**
  기간 분할 검증은 원래 "재현성을 확인해 Go로 올릴 수 있는지" 보려는
  목적이었으나, 실제로는 **정반대 방향(전반부 악화)을 발견해
  완화안의 신뢰도를 낮추는 결과**가 나왔다. 이 결과를 근거로 완화안을
  상향 조정하지 않는다.

### 15.5 판정 — Watch 유지(격상 근거 없음, 오히려 신중론 강화)

**활동성 필터 임계값 완화(1.10→1.00 또는 그 이하)는 여전히 Watch**
다. 이번 threshold sweep + 기간 분할 검증은 완화안을 Conditional
Go로 올리기 위해 수행했으나, 결과는 반대로 **완화 효과가 3년의
절반(전반부)에서는 재현되지 않고 정반대로 나타난다는 것을 확인**
했다. "여러 threshold에서 평균이 계속 개선된다"는 사실만으로
성급하게 격상하지 않으며, **완전 제거는 여전히 No-Go**(§14
결론 유지)다. `entry_score`/`_assess_buy_eligibility` 운영 코드
변경 없음 — 이번 턴도 shadow/validation 범위.

### 15.6 다음 단계

1. **전반부와 후반부가 왜 반대 방향을 보이는지 원인 규명이 필요**
   하다 — 예: 두 기간의 시장 국면 분포(bullish/range_bound/
   bearish 비중), 거래대금 레벨 자체의 구조적 변화(예: 2025년 이후
   유동성 전반 확대) 등을 국면·유동성 지표로 나눠 대조하는 후속
   진단이 우선 과제다.
2. 원인이 규명되기 전까지는 threshold 상수를 운영 코드에 반영하지
   않는다 — 완화안이 특정 시기 효과일 경우, 그 시기가 지나면 다시
   손해가 될 위험이 있다.
3. §13의 "결합 사용 시나리오" 판정은 계속 Watch로 유지한다.

## 16. 활동성 필터 완화 효과 전반부/후반부 반전 — 원인 분해 (SPPV-2.26, 2026-07-16)

§15.6이 지시한 원인 규명을 실행했다. 스크립트: `scripts/diagnose_
activity_filter_half_period_divergence.py`(read-only, §14/§15의
표본 수집·threshold 판정·요약 로직을 그대로 재사용하고, 원인 분해에
필요한 원시값 volatility_20d_pct/average_turnover_20d/price_vs_
sma_60_pct만 추가로 수집). 산출: `logs/signal_ic_activity_filter_
half_period_divergence_2026-07-16.json`, 실행 로그 `logs/activity_
filter_half_period_divergence_run_2026-07-16.log`(신규 KIS 호출
0건 — `grep -c "HTTP Request:"` 확인, 기존 3년 캐시로 전량 서빙).

### 16.1 실험 설계

§15와 동일한 전반부(2023-10-10~2025-02-11)/후반부(2025-02-12~
2026-06-16) 표본을 그대로 재사용해, 각 반기의 상위 20% quintile을
대상으로 (1) 시장 공통 regime 분포, (2) activity_ratio 분포, (3)
무차단 기본 수익률 레벨, (4) volatility/turnover/trend 보조 축
분포를 비교했다. 추가로 threshold를 1.10→1.00/0.95/0.90으로 낮췄을
때 **새로 통과하는 표본만 분리**해 그 표본의 forward return과
activity_ratio/volatility/turnover/trend 특성이 반기별로 어떻게
다른지 비교했다 — 이것이 "완화 시 살아나는 종목의 품질 자체가
반기마다 다른가"를 직접 확인하는 핵심 비교다.

### 16.2 실측 결과

**(1) 시장 공통 regime 분포(거래일 기준):**

| 반기 | bullish_trend | range_bound | bearish_trend | event_driven |
|---|---|---|---|---|
| 전반부(2023-10~2025-02) | 24.5%(80일) | 45.4%(148일) | **28.5%(93일)** | 1.5% |
| 후반부(2025-02~2026-06) | **82.9%(271일)** | 15.9%(52일) | 0.9%(3일) | 0.3% |

전반부는 range_bound가 절반 가까이(45.4%)를 차지하고 하락장도
28.5%나 섞여 있는 **혼합 국면**이었던 반면, 후반부는 **강세장
(bullish_trend)이 82.9%를 지배**하는 매우 편중된 국면이었다.

**(2) 상위 20% quintile 무차단 기본 수익률 레벨:**

| 반기 | T+5 평균 | T+5 t_NW | T+20 평균 | T+20 t_NW |
|---|---|---|---|---|
| 전반부 | +0.4675% | 3.80(marginal) | +1.5995% | 5.26 |
| 후반부 | **+1.5399%** | 8.41 | **+5.4793%** | 9.29 |

후반부의 기본 수익률 레벨이 전반부보다 **T+5는 약 3.3배, T+20은
약 3.4배 높다** — 이는 활동성 필터와 무관하게, 상위 20% 후보군
전체의 베타/알파 수준이 규제국면 구성 차이(강세장 편중)로 인해
근본적으로 다르다는 뜻이다.

**(3) 보조 축(volatility / turnover / trend strength):**

| 반기 | volatility_20d_pct 평균 | average_turnover_20d 중앙값 | trend_strength 중앙값 |
|---|---|---|---|
| 전반부 | 2.75% | 약 378억원 | +6.93% |
| 후반부 | 3.35% | **약 706억원(약 1.9배)** | **+16.67%(약 2.4배)** |

거래대금(turnover) 중앙값이 후반부에 **약 1.9배로 구조적으로
확대**됐고, trend_strength(60일 이평 대비 괴리율)도 약 2.4배 강한
추세를 보였다 — 후반부는 유동성 레벨 자체가 높아지고 추세가 훨씬
강했던 시기다.

**(4) 결정적 비교 — threshold=1.00 완화 시 "새로 통과하는 표본"의
품질(전반부 vs 후반부):**

| 반기 | 기존 통과군(1.10) T+5 평균 | 신규 통과 표본(1.00) T+5 평균 | 방향 |
|---|---|---|---|
| 전반부 | +0.7394%(§15) | **+0.5606%**(n=265, t_NW=0.99, 비유의) | **신규 표본이 더 낮음** |
| 후반부 | +1.8568%(§15) | **+2.7185%**(n=392, t_NW=4.18, 유의) | **신규 표본이 더 높음** |

**이것이 원인의 핵심이다.** 전반부에서는 threshold를 낮췄을 때 새로
들어오는 종목들의 forward return이 기존 통과군보다 **낮아서**(0.56%
< 0.74%) 완화가 전체 평균을 끌어내렸다. 후반부에서는 반대로 새로
들어오는 종목들의 forward return이 기존 통과군보다 **높아서**
(2.72% > 1.86%) 완화가 전체 평균을 끌어올렸다. threshold=0.95/0.90
에서도 동일한 방향성이 반복됐다(전반부는 신규 표본 품질이 계속
낮거나 비유의, 후반부는 계속 높고 유의).

### 16.3 해석 — 어느 축이 더 유력한 원인인가

**규명 결과: 이 반전은 활동성 필터 로직 자체의 결함이 아니라, 두
반기의 "시장 국면 + 유동성 레벨"이 구조적으로 달랐기 때문에 발생한
것으로 판단한다.** 세 후보 축을 아래처럼 비교했다:

1. **시장 국면 차이인가?** → **예, 강하게 관련됨.** 전반부는 혼합/
   약세 편중(range_bound 45%+bearish 29%), 후반부는 강세장 편중
   (83%). 후반부의 기본 수익률 레벨이 전반부의 3배 이상인 것은
   거의 전적으로 이 국면 구성 차이로 설명된다.
2. **유동성 구조 변화인가?** → **예, 함께 관련됨.** 거래대금
   중앙값이 후반부에 약 1.9배로 커졌다 — 활동성 비율(현재/평소
   거래대금의 상대비)을 고정 threshold(1.10)로 판정하는 방식은,
   전체 유동성 레벨이 구조적으로 높아진 시기에는 상대적으로 더
   엄격하게 작동해(모두가 "평소보다 늘었다"고 판정받기 쉬워지므로
   임계값 근방 종목의 구성이 달라짐) 이전이라면 통과했을 법한
   종목까지 걸러낼 가능성이 있다.
3. **entry 후보군 자체의 질 변화인가?** → 이는 위 두 축의
   **결과**로 보인다 — 국면과 유동성이 강세·확장 국면일 때는
   활동성 임계값 근방에 있는 한계 종목들도 실제로 상승 흐름에
   올라타 있을 확률이 높아 품질이 좋고, 혼합·약세 국면일 때는
   그 한계 종목들이 대부분 "일시적으로 거래가 튄" 저품질 종목일
   확률이 높다는 것으로 설명된다. 즉 후보군 품질 차이는 독립적인
   원인이 아니라 국면·유동성 구조 차이가 만들어낸 결과다.

**결론: 국면 차이와 유동성 구조 변화가 사실상 하나의 현상(강세장에서
유동성도 함께 확대)으로 얽혀 있으며, 이 둘이 활동성 필터 완화
효과의 반전을 설명하는 가장 유력한 원인이다.** 활동성 필터 자체의
설계(고정 threshold 1.10)는 국면에 따라 "얼마나 엄격하게 작동하는지"
가 달라지는 국면 의존적(regime-dependent) 특성을 갖고 있다는
뜻이다.

### 16.4 함의 — 완화안이 아니라 "국면 조건부 임계값" 방향일 가능성

이번 분해로, §15에서 관찰한 "최근에는 완화가 좋아 보인다"는 결과가
**"최근 시장이 강세장 편중이었다"는 특정 국면 조건에 의존한 결과**
였을 가능성이 높다는 것이 확인됐다. 이는 두 가지를 시사한다:

1. **정적 threshold 완화(1.10→1.00처럼 항상 낮은 값 고정)는
   위험하다** — 시장이 다시 혼합/약세 국면으로 전환되면 §15
   전반부와 같은 역효과가 재현될 수 있다.
2. **향후 검토 방향은 "완화"가 아니라 "국면 조건부 threshold"일
   가능성이 있다** — 예: 강세장에서는 완화, 혼합/약세장에서는
   현행 유지. 다만 이는 새로운 설계 제안이며, 이번 턴은 원인 규명과
   shadow 검증까지만 수행한다 — 새 설계 채택 여부는 **별도 턴에서
   사용자 승인 후** 진행한다.

### 16.5 판정 — Watch 유지, 완화안 단독 채택은 여전히 근거 부족

**활동성 필터 임계값 완화(정적, 국면 무관)는 여전히 Watch(격상
근거 없음)** — §15의 결론을 그대로 유지한다. 이번 §16은 그 이유를
"시장 국면·유동성 구조의 반기별 차이"로 명확히 설명했을 뿐, 완화안
자체의 신뢰도를 올리거나 내리지 않는다. **완전 제거는 여전히
No-Go.** `entry_score`/`_assess_buy_eligibility` 운영 코드 변경
없음 — 이번 턴도 shadow/validation 범위, threshold 상수는 손대지
않았다.

### 16.6 다음 단계

1. "국면 조건부 활동성 threshold"(예: 강세장=완화, 혼합/약세장=
   현행 유지) 아이디어를 별도 설계 문서로 구체화할지 사용자 확인을
   받는다 — 이번 턴에서는 제안만 하고 설계·구현하지 않는다.
2. 유동성 레벨의 절대적 구조 변화(거래대금 중앙값 약 1.9배 확대)가
   일시적(최근 상승장 특유)인지 영구적(시장 전체의 구조 변화)인지
   장기 모니터링이 필요하다 — 이는 활동성 필터뿐 아니라 다른
   유동성 기반 임계값(§8의 avg_daily_volume/average_turnover 하한
   등)에도 영향을 줄 수 있다.
3. §13/§15의 "결합 사용 시나리오" Watch 판정은 계속 유지한다.

## 17. alpha layer 교체 — BUY funnel(candidate→eligible→would_buy→blocked) 관점 검증 (SPPV-2.27, 2026-07-16)

지금까지의 §14~§16은 "얼마나 덜 막을까"(활동성 필터 threshold)에
집중했다. 이번 턴은 무게중심을 원래의 핵심 레버인 **alpha 교체**로
되돌려, "무엇을 앞에 세우면 실제로 더 잘 고르는가"를 candidate→
eligible→would_buy→blocked **4단계 BUY funnel**로 직접 검증한다.
스크립트: `scripts/validate_alpha_layer_buy_funnel_comparison.py`
(read-only). 산출: `logs/signal_ic_alpha_layer_buy_funnel_comparison_
2026-07-16.json`, 실행 로그 `logs/alpha_layer_buy_funnel_comparison_
run_2026-07-16.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

### 17.1 시나리오 정의(운영 코드 재사용, 새 로직 없음)

- **시나리오 A(현행)**: alpha = `current_alpha_composite`(§12에서
  entry_score의 alpha 항과 순위 동치임이 코드로 증명된 값). entry_
  score는 운영 함수 `_build_entry_score()`를 그대로 호출.
- **시나리오 B(제안)**: alpha = `regime_conditional_signal`(§2).
  entry_score는 §3이 제안한 공식(`score += 0.80 *
  _normalize_signed_score(regime_conditional_signal)`)대로 alpha
  항만 교체하고, 국면 bonus/penalty·relative-activity bonus는
  `_build_entry_score()`와 동일한 공식으로 재구성했다(운영 함수
  미수정, allocation/strategy는 이 세션 전체의 shadow 관례대로
  `None`이라 두 시나리오 모두 기여 0).

funnel 4단계: **candidate**(그날 cross-sectional 상위 20%, 시나리오별
alpha 기준) → **eligible**(운영 함수 `_assess_buy_eligibility()`
그대로 — 이 판정 자체는 alpha와 무관하므로 두 시나리오 공통 로직,
이번 턴은 이 축을 바꾸지 않고 보조 지표로만 관찰) → **would_buy**
(eligible 중 그날 entry_score 상위 `WATCH_TOP_K_BUY=3`, 이 상수는
`trigger_proxy_attribution.py:38`에서 실제 운영 중인 하루 매수 후보
top-K를 그대로 재사용, 임의로 새로 정하지 않음) → **blocked**
(candidate이지만 eligible이 아닌 표본).

### 17.2 실측 결과 — funnel 전환율 + would_buy(최종 매수 후보) forward return

| 창 | 시나리오 | candidate | eligible(%) | would_buy | blocked |
|---|---|---|---|---|---|
| 2차(3년) | A(현행) | 11,101 | 5,462(49.2%) | 1,920 | 5,639 |
| 2차(3년) | B(신규) | 10,999 | 3,491(31.7%) | 1,543 | 7,508 |
| 1차(최근 12개월) | A(현행) | 4,165 | 2,322(55.8%) | 722 | 1,843 |
| 1차(최근 12개월) | B(신규) | 4,165 | 1,621(38.9%) | 673 | 2,544 |
| 3년 전반부 | A(현행) | 5,542 | 2,448(44.2%) | 959 | 3,094 |
| 3년 전반부 | B(신규) | 5,457 | 1,359(24.9%) | 657 | 4,098 |
| 3년 후반부 | A(현행) | 5,559 | 3,014(54.2%) | 961 | 2,545 |
| 3년 후반부 | B(신규) | 5,542 | 2,132(38.5%) | 886 | 3,410 |

**would_buy(최종 매수 후보 top-3/일) forward return 비교:**

| 창 | 시나리오 | T+5 평균 | T+5 t_NW | T+20 평균 | T+20 t_NW |
|---|---|---|---|---|---|
| 2차(3년) | A | +0.6796% | 2.46 | +1.9041% | 2.38 |
| 2차(3년) | B | **+1.0893%** | **3.04** | **+2.8177%** | **2.90** |
| 1차(최근 12개월) | A | +1.1985% | 2.09 | +3.1516% | 2.09 |
| 1차(최근 12개월) | B | **+2.0577%** | **3.11** | **+4.3066%** | **2.59** |
| 3년 전반부 | A | +0.3533% | 1.20(비유의) | +0.3667% | 0.50(비유의) |
| 3년 전반부 | B | +0.4424%(비유의) | 1.03(비유의) | +0.9782%(비유의) | 0.94(비유의) |
| 3년 후반부 | A | +1.0053% | 2.15 | +3.4383% | 2.48 |
| 3년 후반부 | B | **+1.5691%** | **2.93** | **+4.1818%** | **2.84** |

### 17.3 해석

**핵심 발견 — 방향의 완전한 일관성**: `would_buy` 단계에서 시나리오
B(새 alpha)의 평균 forward return이 **4개 창(2차/1차/전반부/후반부)
전부, T+5/T+20 두 horizon 전부에서 시나리오 A(현행)보다 높다** —
예외 없이 8/8 관측치가 같은 방향이다. 이는 §15에서 발견한 활동성
필터 완화 효과(전반부에서 방향이 반전됨)와 뚜렷이 대비된다 — **alpha
교체 효과는 기간을 쪼개도 방향이 뒤집히지 않는다.**

다만 유의성은 창마다 다르다:
- 2차(3년)·1차(최근 12개월)·3년 후반부: t_NW 2.15~3.11로 **모두
  유의**(두 시나리오 공통, B가 A보다 항상 더 유의).
- 3년 전반부: A(t_NW 1.20/0.50)·B(t_NW 1.03/0.94) 모두 **비유의**
  — 이 구간 자체가 §16에서 확인했듯 시장 전체가 혼합/약세 편중이라
  기본 수익률 레벨이 낮은 시기였기 때문이다. **B가 A보다 평균은
  높지만(+0.44%>+0.35%, +0.98%>+0.37%) 통계적으로 확정할 수준은
  아니다.**

**funnel 전환율 측면의 트레이드오프**: 시나리오 B는 eligible
전환율이 A보다 낮다(2차 기준 31.7% vs 49.2%, 약 17%p 낮음) — §13이
이미 확인한 활동성 필터 등 기존 차단 축이 새 alpha 상위군에서 더
많이 걸리기 때문이다(이번 턴은 이 축을 바꾸지 않았다 — 작업 지시
6항에 따라 "얼마나 막느냐"는 보조 지표로만 관찰). 그 결과 최종
`would_buy` 표본 수도 B가 A보다 약간 적다(2차 1,543 vs 1,920,
약 20% 감소). **그러나 표본당 평균 수익률이 그보다 더 크게
개선되어(2차 T+20 기준 +2.82% vs +1.90%, 약 48% 개선), 표본
수×평균 수익률의 총합(누적 기대 성과의 근사)으로 보면 B가
A보다 여전히 크다**(2차 T+20: A 1,920×1.9041%=36.6 vs B
1,543×2.8177%=43.5 — 합산 기준 약 19% 개선). 즉 **거래 횟수는
줄지만 총 기대수익 관점에서는 손해가 아니다.**

### 17.4 판정 — Conditional Go 유지(funnel 레벨에서 보강), 확정 Go는 아님

**§12의 Conditional Go 판정이 funnel의 실제 매수 후보(would_buy)
단계까지 내려가서도 방향이 일관됨을 확인했다** — alpha 교체는
"차단 축을 그대로 둔 채로도" 실제 최종 매수 후보 표본의 forward
return을 4개 창 모두에서 개선하는 방향으로 작동한다. 이는 §15에서
활동성 필터 완화가 보인 재현성 부재(방향 자체 반전)와 질적으로
다른, **더 강한 근거**다.

그럼에도 **확정 Go로 올리지 않는다** — 이유:
1. 3년 전반부에서는 두 시나리오 모두 통계적으로 비유의하다(방향은
   B가 우세하나 확정할 수 없음).
2. §16에서 규명했듯 최근 시장(후반부, 최근 12개월)이 강세장·유동성
   확대로 유난히 우호적이었을 가능성이 있어, 이 funnel 비교도
   같은 국면 편향의 영향을 받을 수 있다 — "새 alpha가 특히 강세장에서
   잘 작동한다"는 것인지 "새 alpha가 국면 무관하게 항상 낫다"는
   것인지는 이번 실험만으로 완전히 분리되지 않는다.
3. would_buy 표본 수 자체가 줄어드는 트레이드오프가 있다(§17.3) —
   "표본당 품질 개선"과 "총 기대수익 개선"은 함께 확인됐지만,
   실거래에서 회전율(거래 빈도) 자체가 낮아지는 것이 다른 운영
   지표(예: 자본 회전 속도)에 미치는 영향은 이번 검증 범위 밖이다.
4. §3에서 이미 명시된 전제조건(§21 1차 게이트 `TRIGGERED` 전환,
   risk_off_penalty와의 중복 해소)이 여전히 미충족이다.

**결론: alpha 교체(§12 Conditional Go)는 이번 funnel 레벨 검증으로
근거가 보강됐다** — 활동성 필터 완화(§15, Watch, 재현성 없음)와는
분명히 구분되는 더 견고한 신호다. 다만 완전한 Go로 격상하려면 위
1~4의 잔여 조건이 해소되어야 한다.

### 17.5 다음 단계

1. §3의 전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_penalty
   중복 해소)이 충족되는 시점에 이 funnel 비교를 재실행해 결론이
   유지되는지 재확인한다.
2. "새 alpha가 강세장에서만 특히 유리한가"를 분리하기 위해, §16과
   동일하게 시장 공통 regime 자체로 층화(bullish_trend만/range_
   bound만/bearish_trend만)한 would_buy 비교를 후속 과제로 남긴다.
3. would_buy 표본 수 감소(약 20%)가 실제 운영에서 자본 회전·기회
   비용에 미치는 영향은 이번 검증 범위 밖이며, 별도 과제로 남긴다.
4. 활동성 필터(§14~§16)와 이번 alpha 교체(§17)는 서로 다른 두 축
   이다 — 하나를 해결한다고 다른 하나가 자동으로 해결되지 않는다는
   것이 이번 턴으로 다시 확인됐다. 두 축 모두 별도로 Conditional
   Go 이상을 확보해야 실거래 반영을 검토할 수 있다.

## 18. alpha layer 교체 — virtual BUY funnel 확장 검증 (SPPV-2.28, 2026-07-16)

§17.5가 지시한 다음 단계를 실행했다 — `would_buy`를 실제 운영 판단
경로에 한 단계 더 가깝게 확장한다. 스크립트: `scripts/validate_
alpha_layer_virtual_buy_funnel_extended.py`(read-only). 산출:
`logs/signal_ic_alpha_layer_virtual_buy_funnel_extended_2026-07-16.
json`, 실행 로그 `logs/alpha_layer_virtual_buy_funnel_extended_run_
2026-07-16.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

### 18.1 확장된 funnel 정의(운영 코드/상수 재사용, 새 로직 없음)

§17의 4단계(candidate→eligible→would_buy→blocked)에 **selected**
단계를 추가해 5단계로 확장했다:

1. **candidate**: 그날 cross-sectional 상위 20%(§12/§13/§17과 동일).
2. **eligible**: 운영 함수 `_assess_buy_eligibility()` 그대로.
3. **selected(buy_candidate)**: `assess_deterministic_triggers()`가
   실제로 쓰는 조건 그대로 재현 — `eligible AND entry_score >=
   0.65(운영 상수 buy_candidate_threshold, `deterministic_trigger_
   engine.py:89`) AND allocation_budget_ok(=True, 세션 전체의
   shadow 관례)`. 이는 **결정론적 엔진이 실제로 "매수 후보"로
   표시하는 시점** — §17의 `would_buy`보다 한 단계 더 운영 경로에
   가깝다.
4. **would_buy(virtual submitted proxy)**: selected 중 그날 entry_
   score 상위 `WATCH_TOP_K_BUY=3`(운영 상수 재사용) — 이 지점이
   과거 데이터만으로 재현 가능한 **최종 지점**이다. 이후 단계
   (FDC AI 판단, compliance/guardrail, broker submit)는 실시간
   상태·LLM 판단을 요구해 재현할 수 없다(Phase 0/1-3 경계, 이
   세션 전체에서 일관 적용) — broker submit 경계를 넘지 않는다.
5. **blocked**: `blocked_by_eligibility`(candidate이지만 eligible
   아님)와 `blocked_by_score_threshold`(eligible이지만 entry_
   score<0.65)로 세분화했다.

MFE/MAE(각 horizon 내 고가/저가 기준 최대 유리·불리 이탈폭)도
`validate_signal_predictive_power_v2.py`의 기존 계산 패턴을 그대로
재사용해 추가 계측했다.

### 18.2 실측 결과 — 5단계 funnel + would_buy MFE/MAE

| 창 | 시나리오 | candidate | eligible(%) | selected(%of elig.) | would_buy | blocked_elig. | blocked_score |
|---|---|---|---|---|---|---|---|
| 2차(3년) | A(현행) | 11,101 | 5,462(49.2%) | 3,804(69.6%) | 1,672 | 5,639 | 1,658 |
| 2차(3년) | B(신규) | 10,999 | 3,491(31.7%) | **3,491(100.0%)** | 1,543 | 7,508 | **0** |
| 1차(최근12개월) | A | 4,165 | 2,322(55.8%) | 1,540(66.3%) | 585 | 1,843 | 782 |
| 1차(최근12개월) | B | 4,165 | 1,621(38.9%) | **1,621(100.0%)** | 673 | 2,544 | **0** |
| 전반부 | A | 5,542 | 2,448(44.2%) | 1,768(72.2%) | 874 | 3,094 | 680 |
| 전반부 | B | 5,457 | 1,359(24.9%) | **1,359(100.0%)** | 657 | 4,098 | **0** |
| 후반부 | A | 5,559 | 3,014(54.2%) | 2,036(67.6%) | 798 | 2,545 | 978 |
| 후반부 | B | 5,542 | 2,132(38.5%) | **2,132(100.0%)** | 886 | 3,410 | **0** |

**would_buy(최종 virtual 매수 후보) forward return + MFE/MAE:**

| 창 | 시나리오 | T+5 평균 | T+5 t_NW | T+20 평균 | T+20 t_NW | T+20 MFE | T+20 MAE |
|---|---|---|---|---|---|---|---|
| 2차(3년) | A | +0.708% | 2.79 | +1.937% | 2.49 | +11.91% | -7.94% |
| 2차(3년) | B | **+1.089%** | **3.04** | **+2.818%** | **2.90** | **+15.14%** | -9.01% |
| 1차(12M) | A | +1.393% | 2.68 | +3.491% | 2.51 | +15.37% | -8.16% |
| 1차(12M) | B | **+2.058%** | **3.11** | **+4.307%** | **2.59** | **+20.07%** | -9.68% |
| 전반부 | A | +0.187%(비유의) | 0.64 | +0.291%(비유의) | 0.38 | +9.07% | -7.81% |
| 전반부 | B | +0.442%(비유의) | 1.03 | +0.978%(비유의) | 0.94 | +10.75% | -8.48% |
| 후반부 | A | +1.279% | 3.03 | +3.741% | 2.79 | +15.02% | -8.09% |
| 후반부 | B | **+1.569%** | **2.93** | **+4.182%** | **2.84** | **+18.39%** | -9.41% |

### 18.3 해석 — 중요한 계측 발견(중립적으로 보고)

1. **§17 결론의 재확인 — 방향 일관성 유지**: `selected` 단계를
   추가한 뒤에도 `would_buy`의 forward return 우위는 4개 창
   전부에서 그대로 유지된다(8/8 여전히 B>A). A의 would_buy 표본
   구성이 §17보다 소폭 달라졌다(0.65 문턱을 먼저 거치므로) — 예:
   2차 A 표본 1,672건(§17은 1,920건) — 이는 0.65 문턱이 A에게는
   **실제로 작동하는 필터**임을 보여준다(eligible의 30~34%가 이
   단계에서 추가로 걸러짐).
2. **결정적 계측 발견 — B는 이 문턱이 사실상 무력화된다**: 시나리오
   B는 **4개 창 전부에서 selected 비율이 정확히 100.0%**다(`blocked_
   by_score_threshold=0`, 예외 없음). 이는 candidate 정의 자체가
   이미 "그날 `regime_conditional_signal` 상위 20%"이기 때문에,
   그 신호를 `_normalize_signed_score`로 변환한 뒤 0.80 가중치를
   곱한 값이 이미 대부분 0.65 문턱을 넘기 때문이다 — **"상위 20%로
   뽑은 뒤 그 알파로 다시 0.65 문턱을 매기면, 사실상 같은 신호를
   두 번 거르는 것과 같아 두 번째 문턱이 실질적으로 무력화된다."**
   이는 §3이 제안한 원 공식(`score += 0.80 *
   _normalize_signed_score(regime_conditional_signal)`)을 그대로
   적용했을 때 나타나는 **계측된 부작용**이다 — 오류는 아니지만,
   "이 alpha를 쓰면 0.65 문턱이 사실상 사라지고, 최종 필터링 부담이
   전적으로 eligibility(활동성 필터 등, §14~§16)로 넘어간다"는
   뜻이다. 이는 새로 발견한 사실이며, §3의 실제 적용 전에 반드시
   고려해야 할 캘리브레이션 이슈로 기록한다.
3. **MFE/MAE — B는 상방·하방 진폭이 모두 크다**: would_buy 단계의
   MFE/MAE를 비교하면, **B는 4개 창 전부에서 MFE(최대 유리 이탈)도
   A보다 크고, MAE(최대 불리 이탈)의 절댓값도 A보다 크다** — 예:
   2차 T+20 MFE A +11.91%/B +15.14%(B가 27% 더 큼), MAE A -7.94%/
   B -9.01%(B가 13% 더 큼, 절댓값 기준). MFE/|MAE| 비율로 보면
   B가 4개 창 전부에서 A보다 높다(2차 1.50→1.68, 1차 1.88→2.07,
   전반부 1.16→1.27, 후반부 1.86→1.95) — **B는 평균 수익률뿐 아니라
   "상방 잠재력 대비 하방 위험" 비율도 일관되게 낫다.** 다만 절대
   MAE 자체가 더 크다는 것은 보유 기간 중 중간 낙폭(interim
   drawdown)이 더 클 수 있다는 뜻이므로, 실제 사이징/손절 기준
   설계 시 고려해야 한다 — 이는 "일정 부분의 손실을 감내하며
   기대수익을 높인다"는 공격형 목표와 방향은 일치하지만, 리스크
   관리 설계와는 별도로 다뤄야 한다.

### 18.4 강세장 편향 재점검

§16/§17에서 이미 제기한 우려(최근 시장이 강세장·유동성 확대로
유난히 우호적이었을 가능성)를 이번 확장 검증에서도 재확인했다 —
전반부는 이번에도 두 시나리오 모두 비유의(t_NW < 1.1)했고, 후반부·
최근 12개월은 강하게 유의했다. **다만 방향(B>A)은 이번에도 전반부
에서조차 뒤집히지 않았다** — 활동성 필터 완화(§15)와는 질적으로
다른 결과다. 강세장 편향 자체를 완전히 배제할 수는 없으나("특히
강세장에서 더 크게 이긴다"는 가능성은 남아 있음), "혼합/약세장에서
오히려 손해"라는 반증은 이번에도 나오지 않았다.

### 18.5 판정 — Conditional Go 유지(계측 caveat 포함), 확정 Go는 아님

**§17의 Conditional Go 판정을 다시 한번 확인했다** — funnel을
5단계로 확장(0.65 실제 운영 문턱 추가)해도 would_buy 우위 방향은
전혀 흔들리지 않았다. 그러나 이번 턴에서 새로 계측된 사실 두 가지를
판정에 명시적으로 반영한다:

1. **B는 0.65 문턱이 사실상 무력화된다는 계측 사실** — §3의 공식을
   문자 그대로 적용할 경우, "최종 품질 게이트"로서의 0.65 문턱이
   새 alpha에는 작동하지 않게 된다는 것을 뜻한다. 이는 §3 제안
   자체의 재보정이 필요할 수 있다는 신호다(예: `regime_conditional_
   signal`을 0.65 문턱과 호환되도록 다시 스케일링하는 방안 검토) —
   이번 턴은 이 계측만 하고 재보정 설계는 하지 않는다.
2. **MAE(하방 이탈)가 A보다 일관되게 크다** — 공격형 목표와 방향은
   맞지만, 실제 사이징/손절 설계와 별도로 검토해야 할 리스크 요소로
   명시한다.

**결론: Conditional Go 유지, 이번 계측으로 보강됐지만 확정 Go로
올리지 않는다** — §17의 잔여 조건(§3 전제조건 미충족, 국면 편향
가능성, 거래 빈도 감소)에 더해 위 두 caveat이 추가됐다.

### 18.6 다음 단계

1. §3의 원 공식(`0.80 * _normalize_signed_score(regime_conditional_
   signal)`)이 0.65 문턱을 사실상 무력화한다는 계측 결과를 반영해,
   실제 적용 전 재보정(예: `regime_conditional_signal`을 z-score
   또는 [-1,1] clip 후 정규화) 설계 여부를 사용자에게 확인받는다 —
   이번 턴은 설계·구현하지 않는다.
2. §17.5와 동일하게 §3 전제조건(§21 1차 게이트 TRIGGERED 전환,
   risk_off_penalty 중복 해소) 충족 후 재검증, regime별 층화 비교로
   강세장 편향 여부를 분리 확인하는 과제를 유지한다.
3. MAE가 큰 것이 실제 사이징/손절 설계에 미치는 영향은 별도 과제로
   남긴다(이번 턴은 계측만, 설계 변경 없음).

## 19. 새 alpha entry_score 스케일 재보정 shadow 검증 (SPPV-2.29, 2026-07-16)

§18.6이 지시한 다음 단계 1(§3 공식 재보정 설계 검토)을 실행했다.
스크립트: `scripts/validate_alpha_layer_score_rescaling_comparison.py`
(read-only, 운영 코드 미수정, broker submit 미호출). 산출:
`logs/signal_ic_alpha_layer_score_rescaling_comparison_2026-07-16.
json`, 실행 로그 `logs/alpha_layer_score_rescaling_comparison_run_
2026-07-16.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

### 19.1 원인 분해 — 왜 0.65 문턱이 무력화되는가

`overall_score`/`fast_score`/`slow_score`는 `signal_backbone`이 이미
대략 [-1, 1] 범위로 정규화해 산출하지만, `regime_conditional_signal`
(`risk_adj_momentum_3m = return_3m_pct / max(volatility_20d_pct,
1.0)`, 또는 `reversal_1m = -return_1m_pct`)은 **퍼센트 단위
비율/차분값**으로 스케일이 전혀 다르다(예: 3개월 수익률 12%/변동성
2% = 6.0). `_normalize_signed_score(x) = clamp((x+1)/2)`를 이 값에
그대로 적용하면 x>=1인 경우 전부 1.0으로 saturate되는데, 상위 20%
quintile(강한 양의 모멘텀 종목군)에서는 이 조건이 거의 항상 성립해
alpha 항이 사실상 상수(0.80)가 된다 — 이것이 §18에서 관측된
selected_rate=100.0%의 원인이다.

### 19.2 재보정 shadow 시나리오 3종(+기준선)

candidate 정의(그날 `regime_conditional_signal` 상위 20%)는 그대로
두고, **entry_score 계산에만** 재보정을 적용했다(운영 코드 미수정):

- **R0(기준선)**: 재보정 없음 — §18과 동일, `0.80 * normalize
  (signal_raw)`.
- **R1(가중치 축소)**: alpha 가중치 0.80 → 0.50, normalize는 그대로.
- **R2(cross-sectional z-score 재정규화)**: 그날 신호 산출 가능한
  전체 universe(quintile 컷 이전) 기준 `z=(signal-day_mean)/day_
  std`를 구해 normalize에 통과 — `0.80 * normalize(z)`.
- **R3(cross-sectional percentile 스케일링)**: 그날 전체 universe
  기준 백분위(0~1)를 그대로 alpha 항에 사용 — `0.80 * day_
  percentile_rank(signal)`(이미 유계라 normalize 불필요).

### 19.3 실측 결과

**selected_rate_of_eligible(0.65 문턱 통과율) — 100%에서 얼마나
내려오는가:**

| 창 | R0(기준선) | R1(가중치↓) | R2(z-score) | R3(percentile) |
|---|---|---|---|---|
| 2차(3년) | 100.0% | 57.2% | 98.17% | **95.13%** |
| 1차(최근12개월) | 100.0% | 46.6% | 96.92% | **93.71%** |
| 전반부 | 100.0% | 67.8% | 99.34% | **96.54%** |
| 후반부 | 100.0% | 50.4% | 97.42% | **94.23%** |

**would_buy 표본 수(§18과 동일 top-3/일 정의):**

| 창 | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| 2차(3년) | 1,543 | 1,187(-23%) | 1,539(-0.3%) | 1,516(-1.8%) |
| 1차(12M) | 673 | 456(-32%) | 671(-0.3%) | 657(-2.4%) |
| 전반부 | 657 | 549(-16%) | 655(-0.3%) | 649(-1.2%) |
| 후반부 | 886 | 638(-28%) | 884(-0.2%) | 867(-2.1%) |

**would_buy T+20 평균 forward return(R0 대비 변화):**

| 창 | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| 2차(3년) | +2.818% | +2.762%(↓) | +3.287%(↑) | **+3.591%(↑↑)** |
| 1차(12M) | +4.307% | +4.603%(↑) | +5.312%(↑) | **+6.050%(↑↑↑)** |
| 전반부 | +0.978% | +0.861%(↓) | +0.871%(↓) | **+1.023%(↑, 비유의)** |
| 후반부 | +4.182% | +4.398%(↑) | +5.077%(↑) | **+5.514%(↑↑)** |

**T+5도 동일한 패턴** — R3는 4개 창 전부에서 R0보다 평균 수익률이
높다(2차 +1.089%→+1.149%, 1차 +2.058%→+2.098%, 전반부 +0.442%→
+0.494%, 후반부 +1.569%→+1.640%). **MFE/MAE는 R3가 R0와 거의
동일하거나 MAE(하방) 절댓값이 근소하게 작다**(예: 2차 T+20 MAE
R0=-9.01% vs R3=-8.97%, 1차 R0=-9.68% vs R3=-9.47%, 후반부
R0=-9.41% vs R3=-9.29% — 3개 창에서 R3가 MAE를 오히려 근소하게
줄였고, 전반부만 -8.48%→-8.54%로 거의 변화 없음).

### 19.4 해석 — R3(percentile 스케일링)가 유력한 후보, R1/R2는 기각

1. **R1(가중치 축소)은 기각한다** — selected_rate를 가장 크게
   낮췄지만(46.6~67.8%), forward return이 4개 창 중 3개에서 R0보다
   낮아졌다(2차/전반부 T+20 하락, T+5는 2차/전반부/1차 3개 창 하락).
   **"문턱을 되살렸다"는 사실만으로 성공으로 보지 않는다는 원칙**
   그대로 — 표본도 최대 32% 줄고 품질도 대체로 나빠져 이중으로
   손해다.
2. **R2(z-score 재정규화)는 문제를 충분히 해결하지 못한다** —
   selected_rate가 96.9~99.3%로 R0(100%)와 큰 차이가 없다. 상위
   20% quintile 멤버는 정의상 그날 평균보다 이미 충분히 높은 값을
   가지므로, z-score로 바꿔도 여전히 saturate 경계(z>=1) 근처에
   많이 몰린다 — 스케일 문제의 근본 원인(정규화 함수와 신호 분포의
   불일치)을 완전히 해소하지 못했다. 다만 forward return은 3/4
   창에서 R0보다 개선됐다(전반부만 근소 하락) — "문턱 회복"
   목적에는 미흡하지만 순수 성과 측면에서는 나쁘지 않다.
3. **R3(percentile 스케일링)가 가장 균형 잡힌 결과를 보였다** —
   - selected_rate가 93.7~96.5%로 의미 있게 내려와(R0=100% 대비)
     문턱이 다시 어느 정도 실질적인 필터로 작동한다.
   - forward return이 **4개 창·2개 horizon 전부(8/8)**에서 R0보다
     개선됐다 — 이번 세션에서 시도한 어떤 재보정안보다 일관성이
     높다.
   - would_buy 표본 수 감소가 1.2~2.4%로 미미해, "필터를
     되살리는 대가로 표본이 급감"하는 트레이드오프가 사실상 없다.
   - MAE(하방 절댓값)가 커지지 않고 오히려 3개 창에서 근소하게
     작아졌다 — §18에서 우려했던 "MAE 확대" caveat도 이 재보정
     에서는 완화되는 방향으로 나타났다.
   - 전반부는 이번에도 비유의(t_NW=0.97)했지만, 이는 §16에서 이미
     확인한 "그 구간 자체가 약한 시기"라는 구조적 이유 때문이며,
     R3의 방향은 여기서도 R0보다 낫다(+0.978%→+1.023%).

### 19.5 판정 — R3를 유력한 재보정 방향으로 채택 검토(Watch→Conditional Go 경계), 확정 Go는 아님

**R3(percentile 기반 스케일링)는 "필터 복원"과 "기대수익률 유지·
개선"을 동시에 만족하는 유일한 재보정안이었다** — 8/8 forward
return 개선, 문턱의 유의미한 회복(100%→93.7~96.5%), 표본 감소 미미
(1.2~2.4%), MAE 확대 없음(오히려 근소 개선). 이는 §18에서 제기한
"0.65 문턱 사실상 무력화" caveat에 대한 **효과적인 shadow 해법
후보**로 판단한다.

**다만 확정 Go로 올리지 않는다** — 이유:
1. 이번이 단일 실험(1회 실행)이며, 재현성(다른 기간 분할, 다른
   percentile 계산 방식)을 추가로 확인하지 않았다.
2. §17/§18에서 이미 지적한 잔여 조건(§3 전제조건 미충족, 국면
   편향 가능성, 거래 빈도 감소)이 여전히 남아 있다 — R3가 이
   조건들을 해소한 것은 아니다.
3. R3의 percentile 계산 자체가 "그날 신호 산출 가능한 전체 universe"
   를 기준으로 하므로, 실제 운영에서 이 universe 구성(87종목 core
   universe 고정)이 바뀌면 percentile 분포도 달라질 수 있다 — 이
   민감도는 검증하지 않았다.

**결론: R1/R2는 기각, R3는 "가장 유력한 후보"로 격상하되, alpha
교체 자체의 판정(§17/§18의 Conditional Go)과 마찬가지로 확정 Go는
아니다.** `entry_score` 운영 코드는 변경하지 않았다 — 이번 턴도
shadow/validation 범위.

### 19.6 다음 단계

1. R3(percentile 스케일링)를 §3의 공식 제안에 정식으로 반영할지
   사용자 확인을 받는다 — 이번 턴은 shadow 검증까지만 수행했다.
2. R3의 재현성을 다른 기간 분할(예: 분기별 4분할)로 추가 확인한다.
3. percentile 계산에 쓰이는 universe 구성이 바뀔 때의 민감도를
   점검하는 후속 과제를 남긴다.
4. §17/§18에서 남은 잔여 조건(§3 전제조건, 국면 편향 분리, 거래
   빈도 트레이드오프)은 R3 채택 여부와 무관하게 계속 유효하다.

## 20. R3(percentile 재보정) 재현성 검증 + percentile 계산 민감도 점검 (SPPV-2.30, 2026-07-16)

§19.6이 지시한 다음 단계를 실행했다 — R3를 더 잘게 쪼갠 기간
분할(분기 4분할)로 재검증하고, percentile 계산 기준(base universe)
민감도를 점검했다. 스크립트: `scripts/validate_alpha_layer_r3_
reproducibility.py`(read-only, 운영 코드 미수정, broker submit
미호출). 산출: `logs/signal_ic_alpha_layer_r3_reproducibility_
2026-07-16.json`, 실행 로그 `logs/alpha_layer_r3_reproducibility_
run_2026-07-16.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

### 20.1 검증 설계

비교 대상 3개(+민감도 변형 1개): **A(현행 alpha layer)**, **B_R0
(재보정 없음)**, **B_R3(percentile, 그날 전체 universe 기준 —
§19가 채택한 안)**, **B_R3b(percentile, candidate 컷 이후 상위
20% 내부에서만 재계산 — 민감도 점검용 신규 변형)**. funnel/MFE·MAE
계측은 §18/§19와 동일하다. 검증 창은 기존 4개(2차·1차·전반부·
후반부)에 **분기 4분할**(3년 표본을 거래일 기준 4등분)을 추가했다.

### 20.2 실측 결과 — 분기별 R0 vs R3 vs R3b(T+20 평균, %)

| 창 | A(현행) | R0(재보정 없음) | R3(전체 universe) | R3b(candidate 내부) |
|---|---|---|---|---|
| 2차(3년) | +1.937 | +2.818 | **+3.591** | **+6.134** |
| 1차(12M) | +3.491 | +4.307 | **+6.050** | **+9.160** |
| 전반부 | +0.291(비유의) | +0.978 | **+1.023** | **+2.830** |
| 후반부 | +3.741 | +4.182 | **+5.514** | **+8.478** |
| **분기1**(2023-10~2024-06) | +0.873(비유의) | +1.208 | **+1.041(하락)** | **+2.616** |
| **분기2**(2024-06~2025-02) | -0.314(비유의,음수) | +0.647 | **+0.996** | **+3.122** |
| **분기3**(2025-02~2025-10) | +4.151 | +3.648 | **+3.402(하락)** | **+4.932** |
| **분기4**(2025-10~2026-06) | +3.227(비유의) | +4.685 | **+7.545** | **+12.231** |

**T+5도 동일한 패턴**(생략, JSON 산출물 참고) — R3(전체 universe)는
**분기1·분기3에서 R0보다 오히려 낮다**(분기1 T+20 R0 +1.208%→R3
+1.041%, 분기3 T+20 R0 +3.648%→R3 +3.402%). R3b(candidate 내부
재계산)는 **8개 창 전부에서 R0보다 높다**(분기1·분기3 포함).

### 20.3 해석 — 핵심 발견: R3의 "8/8 우위"는 거친 분할에서만 성립한다

**§19(SPPV-2.29)가 보고한 "R3가 4개 창 전부에서 R0보다 낫다"는
결과는 사실이었지만, 그 4개 창(2차/1차/전반부/후반부)은 서로 크게
겹치는 넓은 구간이었다** — 특히 "후반부"는 "1차(최근 12개월)"와
거의 같은 기간이었다. **이번에 더 잘게(분기 단위로) 쪼개자, R3는
분기1과 분기3에서 R0보다 오히려 낮은 평균 수익률을 보였다** — 즉
**"4개 창 전부"라는 재현성 주장은 분할 해상도가 낮았을 때만
성립하는 착시였을 가능성이 있다.** 이는 §16에서 이미 학습한
교훈("기간을 쪼개면 방향이 달라질 수 있다")이 R3에도 그대로
적용된다는 뜻이며, §19의 "유력한 후보로 격상" 판정은 이 새로운
증거로 인해 **한 단계 낮춰야 한다.**

**percentile 계산 기준(base universe) 민감도는 실제로 컸다** — R3
(그날 전체 universe 기준)와 R3b(candidate 컷 이후 상위 20% 내부
기준)는 결과가 상당히 다르다. R3b는 **8개 창 전부에서 R0보다
일관되게 높은 평균 수익률**을 보였다(분기1·분기3 포함, R3가 실패한
바로 그 구간에서도 R3b는 성공). 다만 R3b는 selected_rate가
29.9~39.2%로 R0(100%) 대비 크게 낮아지고 would_buy 표본도
R0 대비 최대 40% 가까이 줄어든다(예: 3년 후반부 R0 would_buy=886건
vs R3b=599건) — **이는 §19에서 기각한 R1(가중치 축소)과 유사한
"극단적 선별" 패턴**이라, 표본이 줄어든 만큼 개선이 진짜인지 잡음
인지 이번 실험만으로 확정할 수 없다.

### 20.4 질문에 대한 답

- **R3 우위가 특정 최근 강세 구간에만 몰린 것인가?** → **부분적으로
  그렇다.** R3(전체 universe 기준)의 우위는 분기4(2025-10~2026-06,
  가장 최근·가장 강한 상승 구간)에서 압도적으로 크고(+7.545% vs R0
  +4.685%), 분기1·분기3에서는 오히려 R0보다 못하다. "8/8 전 구간
  일관"이라는 §19의 결론은 분기 단위로는 성립하지 않는다.
- **R3가 전반적으로 재현되는가?** → **아니오, 완전히 재현되지는
  않는다.** 분기 8개(4분할×2 horizon 관점에서 보면 실질적으로 더
  촘촘한 관측치) 중 2개 분기(1, 3)에서 방향이 뒤집힌다. §19에서
  "재현성 있는 개선"이라고 부르기엔 근거가 약해졌다.
- **R3가 R0 대비 문턱 복원과 수익률 개선을 동시에 유지하는가?** →
  **문턱 복원(selected_rate 93.7~97.4%)은 8개 창 모두에서 일관되게
  나타나지만, 수익률 개선은 6/8만 유지된다.** "동시 만족"이라는
  §19의 결론은 절반만 맞다.
- **R3가 현행 alpha 대비 실제 공격형 대안으로 충분히 일관적인가?**
  → 현행(A) 대비해서는 8개 창 대부분에서 R3가 여전히 우세하다(A는
  분기2에서 평균 수익률이 음수(-0.314%)이기까지 하다). **다만 이는
  "현행보다 낫다"는 것이지 "R3 자체가 안정적으로 재현된다"는 것과는
  다른 질문**이다 — 후자는 이번 검증으로 약화됐다.
- **percentile 계산 민감도**: base universe를 "그날 전체"에서
  "candidate 내부"로 바꾸면(R3b) 결과가 크게 달라진다 — 오히려 더
  일관된 우위(8/8)를 보이지만, 이는 selected_rate를 30%대까지
  낮추는 훨씬 공격적인 선별이라 §19에서 기각한 R1과 같은 우려
  (극단적 선별 = 표본 급감 + 검증 안 된 개선)가 그대로 적용된다.

### 20.5 판정 — R3를 다시 Watch로 하향, R3b는 별도 검토 대상으로 신규 등록

**§19의 "R3 유력한 후보로 격상(Watch→Conditional Go 경계)" 판정을
철회하고 Watch로 되돌린다.** 근거: 분기 단위 재현성 검증에서 2/4
분기(50%)가 방향을 뒤집었다 — 이는 "일부 분할 창에서 흔들리면
Watch 또는 Hold로 남긴다"는 판정 원칙에 정확히 해당한다. R3가 R0
보다 완전히 나쁘다는 뜻은 아니다(문턱 복원 효과는 여전히 유효하고,
현행 alpha보다는 대체로 우세) — 다만 "재현성 있는 개선"이라고
단정할 근거가 이번 검증으로 약해졌다.

**R3b(candidate 내부 percentile)는 새로운 관찰 대상으로 등록한다**
— 8/8 일관된 우위를 보였으나, R1과 유사한 "선택률 급감" 패턴이라
그 개선이 진짜인지 별도 검증이 필요하다. 이번 턴에서 R3b를 새로운
"유력 후보"로 올리지 않는다 — 이는 이번 실험의 부산물로 발견된
것이지 이번 턴의 검증 대상이 아니었으므로, 다음 턴에 별도로
검증해야 한다.

**활동성 필터(§14~§16)의 Watch 판정과 완전 제거 No-Go 판정은
이번 턴과 무관하게 그대로 유지된다.**

### 20.6 다음 단계

1. R3b(candidate 내부 percentile)를 새로운 재보정 후보로 별도
   검증한다 — R1과 동일한 우려(선택률 급감에 따른 표본 축소·잡음
   가능성)를 동일한 엄격도로 점검해야 한다.
2. 분기1·분기3에서 R3가 R0보다 못한 이유(어떤 국면·유동성 구조
   차이 때문인지)를 §16과 같은 방식으로 원인 분해하는 것을 후속
   과제로 남긴다 — 이 원인을 알아야 "R3가 언제 유리하고 언제
   불리한지" 조건부로 판단할 수 있다.
3. §17/§18/§19에서 남은 잔여 조건(§3 전제조건, 국면 편향 분리,
   거래 빈도 트레이드오프)은 이번 턴과 무관하게 계속 유효하다.
4. 향후 재보정 검증은 이번처럼 반드시 분기 단위 이상의 세분화된
   기간 분할로 재현성을 확인한 뒤에만 "유력 후보"로 격상하는 것을
   표준 절차로 삼는다 — 4분할(2차/1차/전후반)만으로는 재현성을
   과신할 위험이 있음을 이번 턴이 보여줬다.

## 21. R3b 엄격 재검증 + R3 실패 구간(분기1/분기3) 원인 분해 (SPPV-2.31, 2026-07-16)

§20.6이 지시한 두 후속 과제를 실행했다. 스크립트: `scripts/
validate_r3b_strict_and_r3_failure_decomposition.py`(read-only,
운영 코드 미수정, broker submit 미호출). 산출: `logs/signal_ic_
r3b_strict_and_r3_failure_decomposition_2026-07-16.json`, 실행
로그 `logs/r3b_strict_and_r3_failure_decomposition_run_2026-07-16.
log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

**문서 정정**: §20/SPPV-2.30 관련 서술에서 "분기 25%가 방향을
뒤집었다"는 표현은 계산 오류였다 — 분기 4개 중 2개는 **2/4=50%**
이며 25%가 아니다(5개 정본 문서 전체에서 정정 완료). 결론(R3를
Watch로 하향)에는 영향이 없으나, 절반의 분기에서 방향이 뒤집혔다는
사실은 25%보다 훨씬 더 심각한 재현성 결여를 뜻한다.

### 21.1 작업 1 — R3b(candidate 내부 percentile) 엄격 재검증

§19에서 R1(가중치 축소)을 기각한 기준(4개 창 중 하나라도 forward
return이 악화되면 기각)을 R3b에도 동일하게 적용했다. 8개 창
(2차/1차/전반부/후반부/분기1~4) 전부에서 R0 대비 R3b의 T+20 평균을
비교한 결과:

| 창 | R0 | R3(전체 universe) | R3b(candidate 내부) |
|---|---|---|---|
| 2차(3년) | +2.818% | +3.591% | **+6.134%** |
| 1차(12M) | +4.307% | +6.050% | **+9.160%** |
| 전반부 | +0.978% | +1.023% | **+2.830%** |
| 후반부 | +4.182% | +5.514% | **+8.478%** |
| 분기1 | +1.208% | +1.041%(하락) | **+2.616%** |
| 분기2 | +0.647% | +0.996% | **+3.122%** |
| 분기3 | +3.648% | +3.402%(하락) | **+4.932%** |
| 분기4 | +4.685% | +7.545% | **+12.231%** |

**R3b는 8개 창 전부(R3가 실패한 분기1·분기3 포함)에서 R0보다
높다** — R1이 실패한 바로 그 기준(단 하나라도 악화되면 기각)을
R3b는 통과한다.

**표본 감소·선택률**: R3b의 selected_rate는 29.86~39.16%로 R0
(100%)는 물론 R1(46.6~67.8%)보다도 낮다 — 이 자체는 우려 요인이다.
would_buy 표본도 R0 대비 최대 약 36% 줄어든다(3년 2차: R0 1,543건
→ R3b 1,024건).

**"진짜 선별 품질 개선인가, 표본 급감 착시인가?" — overlap 진단으로
분리**: R3b의 would_buy 종목 집합이 R0의 것과 얼마나 겹치는지
계측했다.

| 창 | R3∩R0 겹침률 | R3b∩R0 겹침률 | R3b∩R3 겹침률 |
|---|---|---|---|
| 2차(3년) | 79.82% | **55.27%** | 76.17% |
| 1차(12M) | 78.54% | **52.82%** | 75.40% |
| 전반부 | 82.28% | **58.35%** | 75.53% |
| 후반부 | 77.97% | **53.09%** | 76.63% |
| 분기1 | 84.68% | **61.22%** | 74.69% |
| 분기2 | 78.79% | **54.44%** | 76.67% |
| 분기3 | 79.06% | **58.44%** | 81.17% |
| 분기4 | 76.92% | **47.42%** | 71.82% |

**핵심 발견: R3(전체 universe 기준)는 R0와 77~85%가 같은 종목을
고른다** — 즉 R3의 "개선"은 R0가 고른 것과 대부분 같은 종목군
안에서의 미세한 순서 재조정에 불과하다. 반면 **R3b(candidate 내부
기준)는 R0와 47~61%만 겹친다** — 즉 R0가 고르지 않았을 종목의
40~53%를 새로 골라 넣는, **질적으로 다른 선별**이다. 이것이 R3b가
"단순히 표본을 줄여서 평균을 끌어올린 착시"가 아니라 **실제로 다른
종목을 고르는 재선별 효과**라는 근거다 — 순수 표본 축소 착시라면
선별된 종목이 R0의 부분집합(겹침률 100%에 가까움)이어야 하는데,
실제로는 절반 가까이가 다른 종목이다.

### 21.2 작업 2 — R3가 분기1·분기3에서 R0보다 밀린 원인 분해

§16과 동일한 방법(국면 분포, activity_ratio/volatility 분포)에
saturation 비율(원시 신호가 1.0을 넘어 normalize에서 포화되는
비율)을 추가해 분기별로 비교했다.

| 창 | saturation_rate | 국면 분포(주요) | activity_ratio 중앙값 | volatility 평균 |
|---|---|---|---|---|
| 분기1(R3 실패) | **100.0%** | range_bound 46.6%+bullish 40.5%+bearish 10.4%(혼합) | 0.885 | 2.67% |
| 분기2(R3 성공) | **100.0%** | bearish 46.6%+range_bound 44.2%(약세 편중) | 0.883 | 2.83% |
| 분기3(R3 실패) | **100.0%** | bullish 67.5%+range_bound 30.1%(강세 편중) | 0.888 | 2.74% |
| 분기4(R3 성공) | **100.0%** | bullish 98.2%(극단적 강세 편중) | 1.002 | 3.95% |

**결정적이고 예상외의 발견: saturation_rate가 4개 분기 모두
100.0%로 동일하다** — 즉 상위 20% quintile로 뽑힌 candidate는
예외 없이 전부 원시 신호가 1.0을 넘어 `_normalize_signed_score`가
포화된다. 이는 §19가 지적한 스케일 불일치가 국면과 무관하게 **항상
100% 발생**한다는 뜻이다 — 이 사실 자체는 분기1/분기3 실패의
직접적 원인이 아니다(모든 분기에서 동일하므로 분기간 차이를
설명하지 못한다).

**국면 분포도 분기1/분기3 실패를 깔끔하게 설명하지 못한다** —
분기3은 강세장이 67.5%로 지배적인데도 R3가 실패했고, 분기2는 약세
+횡보가 90.8%로 지배적인데도 R3가 성공했다 — "강세장이면 R3가
이긴다"는 단순 가설과 정확히 반대되는 사례가 존재한다. activity_
ratio·volatility 분포도 분기1~3 사이에 뚜렷한 차이가 없다(중앙값
0.88~0.89, 평균 변동성 2.67~2.83%로 거의 동일) — 오직 분기4만
확연히 다르다(activity 중앙값 1.00, 변동성 3.95%).

**결론: 국면 구성·유동성 레벨 같은 거친 분포 지표만으로는 R3가
왜 특정 분기에서 실패하는지 설명되지 않는다.** 대신 §21.1의 overlap
분석이 더 설득력 있는 메커니즘을 제공한다 — **R3는 R0와 77~85%가
겹치는 "미세 재조정"에 불과해 효과 크기 자체가 작다.** 효과가 작은
개입은 분기 단위의 표본 잡음만으로도 부호가 뒤집힐 수 있다 — 이는
특정 국면·유동성 조건 때문이 아니라, **R3라는 재보정 방식 자체가
선택 구성을 충분히 바꾸지 못해 재현성이 취약하다는 구조적 한계**로
해석하는 것이 더 정확하다. (참고: 국면/유동성 축의 완전한 배제를
위해서는 percentile 순위와 forward return의 상관관계(IC)를 분기별로
직접 계산하는 추가 분석이 필요하나, 이는 이번 턴 범위를 넘는다 —
§21.4에 후속 과제로 남긴다.)

### 21.3 판정 — R3b를 유력한 후보로 신규 격상(Watch→Conditional Go 경계), R3는 Watch 유지

**R3b(candidate 내부 percentile)는 R1이 실패한 엄격한 기준(모든
분할 창에서 개선 유지)을 통과한 첫 번째 재보정안이다** — 8개 창
전부에서 R0보다 forward return이 높고, overlap 분석으로 이 개선이
표본 축소 착시가 아니라 실제 재선별 효과임을 확인했다. **R3b를
새로운 유력 후보로 격상한다(Watch→Conditional Go 경계)** — §19에서
R3에 붙였던 것과 같은 위상이지만, 이번에는 분기 단위 재현성 검증을
이미 통과한 상태에서 격상한다는 점에서 R3보다 근거가 견고하다.

**다만 확정 Go는 아니다**:
1. selected_rate가 29.86~39.16%로 매우 낮다 — 거래 빈도가 R0 대비
   최대 36% 줄어드는 트레이드오프가 있다(§17/§18에서 이미 지적한
   거래 빈도 감소 우려의 연장선).
2. 이번 검증도 동일한 3년 표본 내부의 분할일 뿐, 진정한 out-of-
   sample(예: 이 3년 데이터에 전혀 없던 미래 기간) 검증은 아니다.
3. §3의 기존 전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_
   penalty 중복 해소)은 여전히 미충족이다.
4. 분기별 t_NW가 일부 구간(분기1 T+20 t_NW=1.31, 분기2 t_NW=1.68)
   에서는 개별적으로 marginal하다 — 방향은 일관되지만 개별 분기
   단위로는 통계적으로 완전히 확정적이지 않다.

**R3(전체 universe 기준)는 Watch를 그대로 유지한다** — §20의
하향 판정은 이번 원인 분해로도 번복되지 않는다. R3의 근본적 한계는
특정 국면 조건이 아니라 "R0와 너무 비슷한 선택을 해서 효과 크기가
작다"는 구조적 성질이므로, 향후 R3를 그대로 밀어붙이기보다는
R3b 계열(candidate 내부 기준)을 우선 검토 대상으로 삼는다.

**활동성 필터(§14~§16)의 Watch/No-Go 판정은 이번 턴과 무관하게
그대로 유지된다.**

### 21.4 다음 단계

1. R3b를 실제 §3 공식에 반영할지 사용자 확인을 받는다 — 이번 턴은
   shadow 검증까지만 수행했다.
2. R3b의 거래 빈도 감소(최대 36%)가 실제 운영 자본 회전에 미치는
   영향을 별도로 검토한다(§17.5/§18.6에서 이미 남겨둔 과제와 통합).
3. percentile 순위와 forward return의 상관관계(IC)를 분기별로 직접
   계산해, R3/R3b의 효과가 국면과 완전히 무관한지 더 정밀하게
   검증하는 것을 후속 과제로 남긴다.
4. 이 3년 표본을 벗어난 진정한 out-of-sample 기간(향후 신규 거래일
   누적)에서 R3b가 재현되는지 장기 모니터링한다.
5. §3의 기존 전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_
   penalty 중복 해소)과 활동성 필터 관련 잔여 과제(§14~§16)는
   이번 턴과 무관하게 계속 유효하다.

## 22. R3b 대응표본(paired-sample) 검증 — overlap 근거 보정 (SPPV-2.32, 2026-07-16)

§21에서 "R3b는 R0와 47~61%만 겹쳐 질적으로 다른 선별"이라는
**overlap(간접) 근거**만으로 "표본 축소 착시가 아닌 실제 재선별
효과"라고 결론 냈다. 이번 턴은 그 결론을 **직접(대응표본)** 근거로
재검증한다 — 겹치지 않는 40~53%가 정말 R0보다 나은 종목인지를,
같은 거래일에 R0가 버리고 R3b가 새로 고른 "대체 종목쌍"의 forward
return 차이로 직접 측정한다. 스크립트: `scripts/validate_r3b_
paired_replacement_analysis.py`(read-only, 운영 코드 미수정,
broker submit 미호출). 산출: `logs/signal_ic_r3b_paired_
replacement_analysis_2026-07-16.json`, 실행 로그 `logs/r3b_paired_
replacement_analysis_run_2026-07-16.log`(신규 KIS 호출 0건 — 기존
3년 캐시로 전량 서빙).

### 22.1 방법론 — 일별 대체쌍(dropped vs added) 차이의 시계열화

거래일마다 candidate(그날 상위 20%, 시나리오 무관 고정)에서 R0의
그날 `would_buy`(top-3)와 R3b의 그날 `would_buy`(top-3)를 각각
구하고, `dropped = R0에만 있음`, `added = R3b에만 있음`을 계산한다.
dropped·added가 모두 있는 날에 한해 그날의
`mean(added의 forward return) - mean(dropped의 forward return)`
을 "그날의 대체 효과"로 기록하고, 이 일별 시계열을 창별로 집계해
평균·Newey-West t값·양수 비율·경험적 95% 구간을 계산한다. R0 vs
R3(전체 universe)에도 동일하게 적용했다.

### 22.2 실측 결과 — R0 vs R3b 대체쌍(added−dropped), T+20 기준

| 창 | 교체 발생일수 | 평균 차이 | t_naive | t_NW | 대체 우위일 비율 |
|---|---|---|---|---|---|
| 2차(3년) | 302 | +5.70%p | 4.40 | **1.96** | 57.3% |
| 1차(12M) | 133 | +8.20%p | 3.44 | 1.30 | 59.4% |
| 전반부 | 123 | +3.66%p | 2.20 | **2.07** | 56.9% |
| 후반부 | 179 | +7.11%p | 3.82 | 1.50 | 57.5% |
| 분기1 | 69 | +3.40%p | 1.47 | 2.02 | 53.6% |
| 분기2 | 54 | +3.99%p | 1.67 | 1.07 | 61.1% |
| **분기3** | 83 | **-0.47%p(음수)** | -0.24 | -0.21 | **45.8%(절반 미만)** |
| 분기4 | 96 | +13.66%p | 4.72 | 1.87 | 67.7% |

**T+5는 더 약하고 더 불안정하다**(생략, JSON 참고) — 예: 분기3
T+5도 -1.10%p(음수, t_NW=-1.30)로 T+20과 같은 방향.

**R0 vs R3(전체 universe) 대체쌍, T+20**: 2차 +3.73%p(t_NW=1.37),
1차 +7.17%p(t_NW=1.23), 전반부 +0.71%p(t_NW=0.74), 후반부
+5.83%p(t_NW=1.32), 분기1 **-0.44%p(음수)**, 분기2 +2.02%p
(t_NW=2.00), 분기3 **-0.04%p(사실상 0)**, 분기4 +11.08%p(t_NW=1.56).

### 22.3 해석 — overlap 결론을 정정한다

**핵심 정정: "R3b는 R0와 겹치지 않아 질적으로 다른 선별"(§21)이라는
문장은 사실이지만, "그 다른 선별이 더 나은 선별"이라는 함의까지는
이번 대응표본 검증이 뒷받침하지 못한다.**

1. **분기3에서 대체 효과가 음수로 뒤집힌다** — R3b가 새로 고른
   종목(added)이 R0가 버린 종목(dropped)보다 T+5·T+20 둘 다에서
   **더 나쁜 forward return**을 보였다(대체 우위일 비율도 45.8%로
   절반 미만). 그런데 §21의 aggregate 비교에서는 분기3에서도
   R3b(+4.932%)가 R0(+3.648%)보다 높았다 — **이 aggregate 우위는
   "대체 종목이 더 좋아서"가 아니라 다른 경로(예: R3b와 R0가
   공통으로 유지한 종목들의 성과 차이, 또는 selected_rate 차이에
   따른 모집단 구성 변화)로 발생했을 가능성이 크다.** 이번 턴은
   그 정확한 경로까지는 규명하지 못했다 — §22.5 다음 단계로 남긴다.
2. **유의성이 대체로 약하다** — R0 vs R3b의 t_NW는 8개 창 중
   2개(2차, 전반부)만 1.96 이상이고, 나머지는 1.0~1.9 사이의
   marginal한 값이다. "대체 효과가 통계적으로 확정적으로 양(+)"
   이라고 말할 수 있는 창은 절반에 못 미친다.
3. **R3(전체 universe)의 대체 효과는 R3b보다 더 약하고 더 자주
   음수/0에 가깝다** — 분기1(-0.44%p), 분기3(-0.04%p)는 사실상
   대체 효과가 없거나 음수다. 이는 §21의 "R3는 R0와 77~85%가
   겹쳐 미세 재조정에 불과해 효과 크기가 작다"는 가설을 **직접
   증거로 재확인**한다 — 겹침률(간접)뿐 아니라 실제 교체쌍의 성과
   차이(직접)로도 R3의 효과가 작고 불안정함이 확인됐다.
4. **방향성 자체는 대체로 양(+)이지만 "증명"이라 부르기엔 이르다**
   — 8개 창 중 6개(R3b)/6개(R3)에서 대체 효과가 양(+)이지만,
   그중 다수가 t_NW<2로 marginal하고, 분기3(R3b·R3 둘 다)과
   분기1(R3)에서는 음수 또는 0에 가깝다. **"R3b는 다른 종목을
   고른다"는 확인됐지만, "R3b는 더 좋은 종목으로 대체한다"는
   부분적으로만 확인됐고 전 구간에서 확정적이지 않다.**

### 22.4 판정 — R3b를 다시 Watch로 하향(§21의 "유력 후보 격상"을 재정정), R3는 Watch 유지

**§21에서 R3b를 "유력한 재보정 후보로 신규 격상(Watch→Conditional
Go 경계)"한 판정을 이번 대응표본 검증 결과로 다시 하향한다 —
plain Watch로 되돌린다.** 근거:
- overlap(간접) 증거만으로 "표본 축소 착시 배제"를 결론지은 것이
  §21의 방법론적 한계였다 — 이번 턴이 그 한계를 스스로 지적하고
  보정한다.
- 대응표본(직접) 검증에서 대체 효과가 분기3(R3b·R3 공통)에서
  음수로 뒤집히고, 나머지 창에서도 t_NW가 marginal한 경우가
  많다 — "일부 분할 창에서 흔들리면 Watch/Hold"라는 이 세션의
  판정 원칙이 R3b에도 그대로 적용된다.
- §21의 aggregate 우위(8/8 창) 자체는 부정되지 않는다 — 다만 그
  우위가 "대체 종목의 우수성"에서 오는 것인지는 확인되지 않았고,
  오히려 분기3에서는 반대 증거가 나왔다.

**R3는 Watch를 유지한다** — 이번 대응표본 검증이 오히려 R3의
Watch 판정 근거를 더 직접적으로 강화했다(효과 크기가 작고 여러
구간에서 음수/0에 가깝다는 것을 간접이 아닌 직접 증거로 확인).

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 22.5 다음 단계

1. R3b의 aggregate 우위(8/8)와 대체쌍 성과(분기3 음수)가 왜
   불일치하는지 — 공통 유지 종목의 기여도, selected_rate 차이에
   따른 모집단 구성 변화 등 — 원인을 규명하는 후속 분석이 필요하다.
2. R3b/R3 모두 확정 Go는커녕 이번 턴 기준으로는 Conditional Go
   경계에도 미치지 못한다 — 추가로 유의한 대응표본 증거(더 긴
   표본, 더 많은 교체 발생일)를 축적한 뒤 재평가한다.
3. §3의 기존 전제조건(§21 1차 게이트 TRIGGERED 전환, risk_off_
   penalty 중복 해소)과 활동성 필터 관련 잔여 과제(§14~§16)는
   이번 턴과 무관하게 계속 유효하다.
4. 향후 "겹침률/overlap만으로 재선별 품질을 증명"하는 방법론은
   이 세션에서 더 이상 충분한 근거로 쓰지 않는다 — 반드시 대응
   표본(교체쌍) 직접 비교를 병행하는 것을 표준 절차로 삼는다.

## 23. R3b aggregate 우위 vs 대응표본 음수 구간 3분해 (SPPV-2.33, 2026-07-16)

§22.5(다음 단계 1)가 지시한 "aggregate 우위와 대체쌍 성과 불일치
원인 규명"을 실행했다. 스크립트: `scripts/validate_r3b_aggregate_
vs_paired_decomposition.py`(read-only, 운영 코드 미수정, broker
submit 미호출). 산출: `logs/signal_ic_r3b_aggregate_vs_paired_
decomposition_2026-07-16.json`, 실행 로그 `logs/r3b_aggregate_vs_
paired_decomposition_run_2026-07-16.log`(신규 KIS 호출 0건 — 기존
3년 캐시로 전량 서빙).

### 23.1 문서 정정 — §22의 "t_NW≥1.96인 창은 2개"는 계산 오류였다

§22가 "R0 vs R3b T+20 대체쌍의 t_NW가 1.96 이상인 창은 2차·전반부
2개"라고 서술한 것을 산출 JSON 원본으로 재확인한 결과, 실제 값은
**2차=1.96(경계값, 포함), 전반부=2.07, 분기1=2.02로 3개 창**이
`|t_NW|>=1.96` 기준을 충족한다 — §22 서술은 분기1(2.02)을 누락한
계산 오류였다. 판정 기준은 명확히 **"근사 양측 95% 유의 수준
t_NW>=1.96(경계값 포함)"**으로 이 문서에 고정한다(`>2.0`처럼 더
엄격한 기준을 쓰면 전반부·분기1 2개만 해당— 이 경우 기준을
명시하지 않으면 "2개"와 "3개"가 둘 다 나올 수 있어 혼동을
유발한다는 점도 함께 기록한다). §21/§22의 결론(R3b Watch 하향,
R3 Watch 유지) 자체에는 영향이 없다.

### 23.2 방법론 — common_kept/dropped_only/added_only 3분해 항등식

그날 R0의 `would_buy`와 R3b(또는 R3)의 `would_buy`는 다음 3개
그룹으로 완전히 분해된다: **common_kept**(둘 다 고름),
**dropped_only**(R0만 고름), **added_only**(신규안만 고름). 이때
다음이 정확히 성립한다(근사가 아닌 항등식):

```
mean(R0_would_buy)  = (n_common·mean_common + n_dropped·mean_dropped) / (n_common+n_dropped)
mean(new_would_buy) = (n_common·mean_common + n_added·mean_added)     / (n_common+n_added)
```

### 23.3 실측 결과 — R0 vs R3b 3분해(T+20 기준)

| 창 | n_common | n_dropped | n_added | common평균 | dropped평균 | added평균 | 재구성 R0평균 | 재구성 R3b평균 | aggregate차이 |
|---|---|---|---|---|---|---|---|---|---|
| 2차(3년) | 566 | 977 | 458 | +3.83% | +2.23% | **+8.98%** | +2.82% | +6.13% | +3.32%p |
| 1차(12M) | 234 | 439 | 209 | +5.16% | +3.85% | **+13.64%** | +4.31% | +9.16% | +4.85%p |
| 전반부 | 248 | 409 | 177 | +1.85% | +0.45% | **+4.20%** | +0.98% | +2.83% | +1.85%p |
| 후반부 | 318 | 568 | 281 | +5.37% | +3.52% | **+11.99%** | +4.18% | +8.48% | +4.30%p |
| 분기1 | 150 | 238 | 95 | +1.57% | +0.98% | **+4.26%** | +1.21% | +2.62% | +1.41%p |
| 분기2 | 98 | 171 | 82 | +2.27% | -0.28%(음수) | **+4.14%** | +0.65% | +3.12% | +2.47%p |
| **분기3** | 180 | 250 | 128 | +4.37% | +3.13% | **+5.72%** | +3.65% | +4.93% | +1.28%p |
| 분기4 | 138 | 318 | 153 | +6.68% | +3.82% | **+17.24%** | +4.69% | +12.23% | +7.55%p |

**R0 vs R3(전체 universe)도 같은 3분해를 적용했다(요약)**: added가
dropped보다 낮은 경우가 실제로 존재한다 — **분기1**(dropped
+3.78% vs added +2.83%, 교체효과 -0.96%p), **분기3**(dropped
+6.53% vs added +5.52%, 교체효과 -1.01%p) — 이는 R3의 "미세
재조정" 가설과 정확히 부합한다(신규 alpha가 고른 대체 종목이
기존보다 못한 경우가 실제로 존재).

### 23.4 해석 — 왜 §22의 "paired 음수"와 이번 "pooled 양수"가 동시에 가능한가

**핵심 발견 1 — R3b의 aggregate 우위는 대부분 `added_only`에서
온다**: 8개 창 전부에서 `added_only`의 평균이 `common_kept`·
`dropped_only`보다 뚜렷이 높다(예: 2차 added +8.98% vs common
+3.83% vs dropped +2.23%). 즉 R3b가 새로 골라 넣은 종목들이 실제로
고수익을 낸 것은 사실이다 — **이 부분은 §22의 우려(표본 급감
착시)를 상당 부분 반박한다.**

**핵심 발견 2 — 그러나 "구성/표본수 효과"도 상당하다**: R0의
`would_buy` 구성은 `dropped_only`(63.3%, 2차 기준)가 `common_kept`
(36.7%)보다 훨씬 큰 비중을 차지하는 반면, R3b의 구성은 `added_
only`(44.7%)와 `common_kept`(55.3%)가 비교적 균형 잡혀 있다. R0의
`dropped_only`가 `common_kept`보다 평균이 낮으므로(2.23%<3.83%),
**R0 자신의 집합이 "저품질 다수"에 더 크게 끌려 내려간다** — R3b가
"더 나은 종목을 더 많이 골라서"만이 아니라 **"R0가 스스로 저품질
종목을 더 많이 포함하는 구조"때문에도** aggregate 차이가 벌어진다.

**핵심 발견 3(가장 중요한 정합성 문제) — 분기3에서 pooled와 paired의
부호가 정반대다**: 이번 pooled 계산은 분기3 R0 vs R3b의 교체효과를
**+2.594%p(양)**로 보여주지만, §22의 일별 대응표본(paired, 날짜를
동일 가중치로 평균) 계산은 같은 비교를 **-0.4666%p(음)**로 보여줬다.
**이 두 지표는 가중 방식이 다르다** — pooled는 "종목-일" 단위를
동일 가중(스왑이 많이 일어난 날의 영향력이 커짐), paired는 "거래일"
단위를 동일 가중(그날 스왑 규모와 무관하게 하루하루를 동등하게
취급)한다. **두 지표의 부호가 갈린다는 것 자체가, R3b의 교체 효과가
"거의 매일 조금씩 좋다"가 아니라 "소수의 스왑이 많이 일어난 날에
크게 좋고, 나머지 평범한 날에는 오히려 나쁘다"는 비대칭 구조임을
시사한다.** 이는 안정적으로 재현 가능한 일상적 edge라기보다,
특정 이벤트/구간에 몰린 효과일 가능성을 뒷받침한다.

### 23.5 질문에 대한 답

- **R3b의 aggregate 우위는 실제 교체 종목의 우수성에서 오는가,
  공통 유지 종목/모집단 구성 변화에서 오는가?** → **둘 다다.**
  `added_only`가 실제로 `dropped_only`보다 나은 것은 8개 창 대부분
  에서 사실이지만(대체 종목 자체의 우수성), 동시에 R0가 스스로
  많은 저품질 `dropped_only`를 포함하는 구조 때문에 R0의 자체
  평균이 낮아지는 "구성 효과"도 상당 부분 기여한다. 어느 한쪽만의
  설명은 불완전하다.
- **R3는 왜 항상 약한가? 정말 "미세 재조정"으로 설명되는가?** →
  **그렇다, 이번 분해로 더 명확히 확인됐다.** R3의 교체효과는
  분기1·분기3에서 실제로 **음수**였다(dropped>added) — R3가
  고른 대체 종목이 기존보다 못한 경우가 실제로 발생했다. §21의
  "미세 재조정" 가설(R0와 77~85% 겹쳐 효과가 작다)은 이번 pooled
  직접 계측으로도 다시 확인됐다.
- **aggregate와 paired가 왜 동시에 가능한가?** → 가중 방식이
  다르기 때문이다(§23.4 핵심 발견 3). 이는 R3b의 개선 효과가
  "안정적이고 매일 조금씩"이 아니라 "특정 고변동 스왑일에 크게"
  나타나는 비대칭 구조라는 뜻이며, 이 자체가 재현성에 대한 추가
  경고 신호다.

### 23.6 판정 — 원인 규명이 우선, 재격상하지 않음(Watch 유지)

**이번 턴은 §22의 하향 판정을 재격상하기 위한 턴이 아니다** — 지시된
대로 원인 분해를 우선했다. 결과적으로:
- R3b의 aggregate 우위는 부분적으로 실체가 있다(added_only의
  실제 우수성) — 완전한 착시는 아니다.
- 그러나 그 우위가 pooled/paired 가중 방식에 따라 부호가 갈릴 만큼
  비대칭적이고 소수 구간에 집중된 것으로 보여, "안정적으로 재현
  가능한 alpha 개선"이라고 단정하기엔 여전히 이르다.
- **R3b/R3 모두 §22의 Watch 판정을 그대로 유지한다** — 이번 턴은
  판정을 바꾸지 않고 원인만 설명했다.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 23.7 다음 단계

1. 분기3처럼 pooled/paired 부호가 갈리는 구간이 왜 발생하는지 —
   스왑이 몰린 특정 거래일(예: 이벤트/실적 발표 밀집일)이 있는지
   날짜 단위로 더 세밀하게 확인하는 후속 진단.
2. R3b의 "구성 효과"(R0 자신의 저품질 dropped_only 비중이 큰
   현상)가 활동성 필터(§14~§16)나 다른 차단 축과 상호작용하는지
   확인 — 이번 턴은 alpha 재보정에만 집중해 다루지 않았다.
3. §22.5에 남은 과제(더 긴 표본·더 많은 교체 발생일 축적, R3b의
   §3 공식 반영 여부 사용자 확인, §3 전제조건 충족 후 재검증)는
   이번 턴과 무관하게 계속 유효하다.

## 24. R3b pooled 우위의 날짜 집중도 검증 + 교체효과/구성효과 정량 분리 (SPPV-2.34, 2026-07-16)

§23.7(다음 단계 1)이 지시한 "분기3처럼 pooled/paired 부호가 갈리는
구간의 거래일 단위 세밀 진단"을 실행했다. 스크립트: `scripts/
validate_r3b_day_concentration_and_effect_decomposition.py`
(read-only, 운영 코드 미수정, broker submit 미호출). 산출:
`logs/signal_ic_r3b_day_concentration_and_effect_decomposition_
2026-07-16.json`, 실행 로그 `logs/r3b_day_concentration_and_
effect_decomposition_run_2026-07-16.log`(신규 KIS 호출 0건 — 기존
3년 캐시로 전량 서빙).

### 24.1 방법론

**작업 1(날짜 집중도)**: 거래일마다 스왑 개수(added+dropped)를
계산하고, 스왑 개수 상위 10%(top-decile) 거래일을 제거한 뒤
pooled aggregate 우위가 얼마나 남는지(잔존비율) 재계산했다.

**작업 2(교체효과/구성효과 정확한 항등식 분해)**: §23의 3분해
항등식에서 출발해 다음 정확한 분해식을 유도했다(근사 아님):

```
aggregate_diff = replacement_effect + composition_effect
replacement_effect = w0'·(mean_added - mean_dropped)
composition_effect = (w1' - w0')·(mean_added - mean_common)

w0' = n_dropped/(n_common+n_dropped)   (R0 자신의 dropped 비중)
w1' = n_added/(n_common+n_added)        (신규안 자신의 added 비중)
```

`replacement_effect`는 순수하게 "교체된 종목 자체의 품질 차이"만,
`composition_effect`는 순수하게 "두 시나리오의 표본 구성 비율
차이"만 반영한다.

### 24.2 실측 결과 — R0 vs R3b, T+20 기준

| 창 | aggregate차이 | 교체효과 | 구성효과 | 스왑상위10%일 제외 후 잔존비율 |
|---|---|---|---|---|
| 2차(3년) | +3.32%p | **+4.27%p** | **-0.96%p** | 80.1% |
| 1차(12M) | +4.85%p | **+6.38%p** | **-1.53%p** | 91.2% |
| 전반부 | +1.85%p | **+2.34%p** | **-0.48%p** | 111.0% |
| 후반부 | +4.30%p | **+5.43%p** | **-1.14%p** | 98.3% |
| 분기1 | +1.41%p | **+2.02%p** | **-0.61%p** | 93.2% |
| 분기2 | +2.47%p | **+2.81%p** | -0.34%p | 120.6% |
| **분기3** | +1.28%p | **+1.51%p** | -0.22%p | **65.2%** |
| 분기4 | +7.55%p | **+9.36%p** | **-1.81%p** | 92.1% |

**R0 vs R3(전체 universe)도 같은 패턴**: 8개 창 대부분에서
`replacement_effect`가 aggregate 차이보다 크고 `composition_
effect`가 이를 소폭 상쇄한다(예: 2차 T+20 aggregate=+0.77%p,
replacement=+0.83%p, composition=-0.06%p). 분기1·분기3은 R3의
replacement_effect 자체가 음수(-0.15%p, -0.22%p)다.

### 24.3 해석 — 두 가지 핵심 정정

**정정 1(중요) — §23의 "구성효과도 상당히 기여한다"는 서술은
방향이 틀렸다.** §23은 "R0 자신의 저품질 dropped_only 비중이
커서 구성 효과도 aggregate 차이에 상당히 기여한다"고 서술했으나,
이번 정확한 항등식 분해 결과 **`composition_effect`는 8개 창 중
6개에서 음(-)이다** — 즉 구성 효과는 R3b의 우위를 만드는 것이
아니라 오히려 **깎아내리는 방향**으로 작용한다. **aggregate 우위
전체는 사실상 `replacement_effect`(교체 종목 자체의 품질 차이)
하나에서 나오며, `composition_effect`는 그 우위를 부분적으로
상쇄하는 역할**이다. §23의 서술을 이 결과에 맞게 정정한다.
**[SPPV-2.35에서 추가 보정] "8개 창 중 6개" 서술은 T+5/T+20
horizon을 구분하지 않아 부정확했다 — 실제로는 **T+20 기준
8개 창 전부(8/8)에서 음(-)이고, T+5 기준으로는 8개 창 중
5개에서만 음(-)이다**(전반부·분기1·분기2는 T+5에서 오히려
양(+)). 상세 수치는 §25.1 참고.**

**정정 2 — 날짜 집중도는 창마다 다르며, 분기3만 뚜렷한 예외다.**
스왑 상위 10% 거래일을 제거해도 대부분의 창(2차/1차/전반부/후반부/
분기1/분기2/분기4)에서 aggregate 우위가 80~120% 수준으로 거의
그대로 남거나 오히려 커진다 — **이 창들에서는 "소수 거래일에
효과가 집중됐다"는 가설이 기각된다.** 그러나 **분기3만은 예외로,
상위 10% 거래일을 제거하면 잔존비율이 T+5=29.7%, T+20=65.2%로
크게 줄어든다** — 분기3의 (이미 §22~§23에서 발견한) pooled·paired
부호 불일치는 실제로 소수의 스왑 밀집일이 만든 아티팩트일
가능성이 높다는 것이 이번에 직접 확인됐다. **[SPPV-2.35에서 정정]
"소수 날짜에 몰린 착시"라는 이때의 잠정 해석은 방향이 과했다 —
§25의 거래일별 세부 진단 결과, 정작 스왑 상위 10% 거래일(대형
스왑일) 자체는 순기여가 양(+)이고, 문제는 오히려 그 밖의 다수
소규모 스왑일에서 완만한 음(-) 효과가 누적된 데서 온다. 상세는
§25 참고.**

### 24.4 질문에 대한 답

- **R3b 우위가 소수 거래일 집중형인가?** → **대체로 아니다,
  분기3만 예외다.** 8개 창 중 7개는 상위 10% 거래일을 제거해도
  우위가 유지되거나 오히려 커진다 — 넓게 분산된 효과다. 분기3만
  소수 거래일에 의존하는 것으로 확인됐다.
- **replacement effect와 composition effect의 실제 비중은?** →
  **replacement_effect가 지배적이고 항상 aggregate_diff보다 크며,
  composition_effect는 거의 항상 음(-)으로 그 일부를 상쇄한다.**
  §23의 "구성효과가 우위에 기여" 서술은 정정 대상이다.
- **`added_only` 우수성을 "실제 선별 우수성"이라 부를 수 있는가?**
  → **분기3을 제외한 7개 창에서는 그렇게 부를 근거가 이전보다
  강해졌다** — 날짜 집중도 검증을 통과했고(소수 날짜 의존이 아님),
  정확한 replacement_effect도 일관되게 크고 양(+)이다. 다만
  **완전히 "증명됐다"고 단정하지는 않는다** — (1) 분기3이라는
  명백한 반례가 여전히 존재하고, (2) 이 모든 검증이 여전히 동일
  3년 표본 내부에서 이뤄졌으며, (3) 분기1·분기2 개별 t_NW는
  여전히 marginal(1.0~2.0)하다.

### 24.5 판정 — 재격상하지 않음, 원인 확정을 우선(Watch 유지)

**이번 턴도 재격상보다 원인 확정을 우선했다(지시에 따름).**
결과적으로 R3b의 aggregate 우위에 대한 근거가 이전보다 명확해졌다
(구성효과가 아니라 순수 교체효과이며, 날짜 집중형도 아니다) —
그러나:
- 분기3이라는 명백한 반례가 여전히 남아 있고, 그 반례는 실제로
  소수 거래일 집중형(잔존비율 30~65%)임이 확인됐다 — R3b가
  "모든 조건에서 안정적"이지는 않다는 뜻이다.
- 이번 검증도 여전히 동일 3년 표본 내부에서만 이뤄졌다.

**R3b/R3 모두 §22~§23의 Watch 판정을 그대로 유지한다.** `entry_
score` 운영 코드는 변경하지 않았다 — 이번 턴도 shadow/validation
범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 24.6 다음 단계

1. 분기3에서 실제로 어떤 종목·거래일이 스왑 상위 10%를 구성하는지
   구체적으로 나열해, 이벤트/실적 발표 등 특정 사유가 있는지
   확인하는 후속 진단(§23.7에서 이미 지시된 과제, 이번 턴으로
   방향이 더 구체화됐다 — "분기3만" 집중 조사하면 된다).
2. R3b를 §3 공식에 정식 반영할지 여부는 §22~§24에서 축적된 근거
   (부분적 실체 확인 + 명백한 반례 1개)를 종합해 사용자가 판단할
   수 있도록 이번 문서들에 정리해 둔다 — 이번 턴 자체는 확정 Go를
   선언하지 않는다.
3. §22.5/§23.7에 남은 과제(더 긴 표본 축적, §3 전제조건 충족 후
   재검증)는 이번 턴과 무관하게 계속 유효하다.

## 25. 분기3 스왑 집중일 세부 진단 + SPPV-2.34 해석 문구 정밀 보정 (SPPV-2.35, 2026-07-16)

§24.6(다음 단계 1)이 지시한 "분기3에서 실제로 어떤 거래일이 스왑
상위 10%를 구성하는지 구체적으로 나열"하는 후속 진단을 실행했다.
스크립트: `scripts/validate_r3b_q3_day_level_diagnostics.py`
(read-only, 운영 코드 미수정, broker submit 미호출). 산출:
`logs/signal_ic_r3b_q3_day_level_diagnostics_2026-07-16.json`,
실행 로그 `logs/r3b_q3_day_level_diagnostics_run_2026-07-16.log`
(신규 KIS 호출 0건 — `grep -c "HTTP Request:"`로 실측 확인, 기존
3년 캐시로 전량 서빙).

### 25.1 SPPV-2.34 문구 정밀 보정 — horizon(T+5/T+20) 구분

SPPV-2.34는 "`composition_effect`는 8개 창 중 6개에서 음(-)이다"
라고 서술했으나, 이는 T+5/T+20을 뒤섞은 부정확한 표현이었다.
§23~§24의 원본 JSON(`logs/signal_ic_r3b_day_concentration_and_
effect_decomposition_2026-07-16.json`)을 horizon별로 재확인한
정확한 수치:

| 창 | T+5 구성효과 | T+20 구성효과 |
|---|---|---|
| 2차(3년) | -0.0967%p | -0.958%p |
| 1차(12M) | -0.2988%p | -1.5308%p |
| 전반부 | **+0.1593%p** | -0.4849%p |
| 후반부 | -0.225%p | -1.1384%p |
| 분기1 | **+0.2828%p** | -0.6066%p |
| 분기2 | **+0.0604%p** | -0.3355%p |
| 분기3 | -0.0135%p | -0.2245%p |
| 분기4 | -0.3244%p | -1.8113%p |

**정정된 표현: `composition_effect`는 T+20 기준 8개 창 전부
(8/8)에서 음(-)이고, T+5 기준으로는 8개 창 중 5개에서만 음(-)이다
(전반부·분기1·분기2는 T+5에서 오히려 양(+)).** "8개 창 중 6개"는
두 horizon을 평균 내듯 뭉뚱그린 표현이었고, 정확히는 **단기(T+5)
일수록 구성효과가 상쇄되거나 오히려 소폭 보탬이 되고, 장기(T+20)
일수록 구성효과가 예외 없이 우위를 깎아내리는 방향**이라는 것이
정확한 서술이다.

### 25.2 방법론 — 분기3 거래일별 세부 진단

R0와 R3b의 `would_buy` 집합이 다른 거래일(스왑 발생일)을 스왑
개수(added+dropped) 기준 내림차순 정렬하고, 상위 15건(83개 스왑
발생일 중 상위 약 18%, "상위 10%"인 약 8일보다 여유 있게 포함)에
대해 다음을 계측했다: (a) 스왑 개수, (b) 그날의 common_kept/
dropped_only/added_only 평균 수익률(T+5/T+20), (c) 그날의 교체
효과(added_only 평균 - dropped_only 평균 — 단일 거래일이므로
pooled/paired 구분이 무의미하고 값이 동일하다), (d) 그 거래일
하나를 제외했을 때 분기3 전체의 aggregate_diff와 paired 평균이
어떻게 바뀌는지(leave-one-day-out).

### 25.3 실측 결과 — 분기3 상위 스왑일 표(T+20 기준)

분기3: 2025-02-12~2025-10-14, 83개 스왑 발생일, 전체 aggregate_
diff(T+20)=+1.2837%p(replacement +1.5081%p, composition
-0.2245%p), 전체 paired 평균(T+20)=**-0.4666%p**.

| 순위 | 날짜 | 스왑개수 | 그날 교체효과(T+20) | 제거 시 aggregate 변화 | 해석 |
|---|---|---|---|---|---|
| 1 | 2025-02-12 | 6 | **-10.257%p** | 1.2837→1.3955(↑, 이 날이 우위를 깎음) | 연속 악재일 시작 |
| 2 | 2025-02-13 | 6 | **-5.5549%p** | 1.2837→1.3604(↑) | #1과 연속 거래일, 함께 초기 악재 군집 |
| 3 | 2025-03-21 | 6 | +14.0132%p | 1.2837→1.1944(↓, 이 날이 우위를 만듦) | 대형 스왑일 중 강한 순기여 |
| 4 | 2025-04-22 | 6 | -5.6809%p | 1.2837→1.3237(↑) | 소폭 악재 |
| 5 | 2025-05-07 | 6 | +18.223%p | 1.2837→1.1219(↓) | 강한 순기여 |
| 6 | 2025-05-27 | 6 | **+28.4353%p**(added=41.23%) | 1.2837→0.9909(↓, 단일 최대 기여) | 최대 순기여일 |
| 7 | 2025-06-10 | 6 | +15.1483%p | 1.2837→1.1587(↓) | 강한 순기여 |
| 8 | 2025-07-10 | 6 | +1.9993%p | 1.2837→1.3063(↑, 근소) | 중립에 가까움 |
| 9 | 2025-09-19 | 6 | +4.3774%p | 1.2837→1.244(↓, 근소) | 약한 순기여 |
| 10 | 2025-09-22 | 6 | +17.3887%p | 1.2837→1.1243(↓) | 강한 순기여 |
| 11 | 2025-09-24 | 6 | +5.0081%p | 1.2837→1.2231(↓) | 약한 순기여 |
| 12 | 2025-03-13 | 5 | +4.1204%p | 1.2837→1.2554(↓) | 약한 순기여 |
| 13 | 2025-04-28 | 5 | +24.4624%p | 1.2837→1.1341(↓) | 강한 순기여 |
| 14 | 2025-02-20 | 4 | -9.7016%p | 1.2837→1.3622(↑) | 소수 종목(n=2) 악재 |
| 15 | 2025-02-26 | 4 | -0.2571%p | 1.2837→1.3233(↑, 근소) | 중립에 가까움 |

(T+5 기준 값과 leave-one-out 상세는 `logs/signal_ic_r3b_q3_day_
level_diagnostics_2026-07-16.json`에 전량 보존.)

### 25.4 핵심 발견 — "소수 날짜 집중"이 아니라 "대형 스왑일은 순기여 양(+), 문제는 다수의 소규모 스왑일"

상위 스왑개수(=6, 완전 3-for-3 교체) 11개 거래일의 T+20 교체효과
단순평균은 **+7.04%p로 뚜렷한 양(+)**이다(음(-)은 2025-02-12,
02-13, 04-22 3건뿐이고 나머지 8건은 양(+), 그중 다수가 두 자릿수
%p). 그런데 분기3 전체 83개 스왑일의 paired 평균은 **-0.4666%p로
음(-)**이다. 두 수치를 정합시키는 항등식(가중평균 분해)으로 역산
하면:

```
전체 평균(-0.4666%p) = (상위8일 평균×8 + 나머지75일 평균×75) / 83
⇒ 나머지 75일(소규모 스왑일) 평균 ≈ -1.267%p
```

즉 **스왑 상위 10%(대형 스왑일, 8일)는 오히려 순기여가 강하게
양(+)이고, 분기3 paired 평균을 음(-)으로 끌어내리는 진짜 원인은
나머지 약 75개의 소규모(스왑 1~3개) 거래일에서 평균 약 -1.27%p
수준의 완만하지만 지속적인 음(-) 효과가 누적된 것**이다. 이는
§24가 "스왑 상위 10%일을 제거하면 분기3만 잔존비율이 크게
줄어든다"는 관찰로부터 잠정 도출했던 "소수 날짜에 몰린 착시"라는
해석과는 방향이 다르다 — 상위 10%일 제거가 분기3의 aggregate
우위를 크게 줄이는 것은 사실이지만(§24의 관찰 자체는 틀리지
않았다), 그 이유는 "상위 10%일이 나쁘기 때문"이 아니라 **"상위
10%일이 유일하게 강한 양(+)의 원천이고, 그것을 빼면 남는 것은
다수의 완만한 음(-) 거래일뿐이기 때문"**이다. **[SPPV-2.36에서
정정] "유일하게 강한 양(+)의 원천"이라는 표현은 과장이었다 — §26의
5분위 구간화·부호별 총합 분해 결과, 대형 스왑일(상위 10%)은 분기3
전체 양(+) 합계의 15% 수준만 차지하며, 스왑 규모가 작은 Q4 구간
(스왑 2~3개)도 T+20 기준 +4.38%p의 뚜렷한 양(+) 평균을 보였다 —
"대형=양(+)/소규모=음(-)"이라는 단조적 구조가 아니라, 스왑 규모의
양극단(최대=Q1, 최소=Q5)이 각각 강한 양(+)/강한 음(-)을 보이고
중간 구간(Q2~Q4)은 혼재하는 비단조적 구조다. 상세는 §26 참고.**

### 25.5 3가지 질문에 대한 답

- **분기3은 정말 "착시"인가, 아니면 "우위는 있으나 일부 날짜
  의존도가 높은 비대칭 구조"인가?** → **후자에 더 가깝다.** 완전한
  착시(즉 "원래 우위가 없는데 계산 방식 때문에 있어 보이는 것")는
  아니다 — 대형 스왑일 8일은 실제로 강한 양(+)의 성과를 냈다.
  다만 그 우위는 **극소수의 대형 스왑일에 전적으로 의존**하며,
  나머지 다수의 평범한 거래일에서는 오히려 완만한 음(-)이 지속돼
  이를 상당 부분 상쇄한다 — "우위가 실재하지만 소수 날짜(대형
  스왑일)에 편중돼 있고, 그 편중을 제거하면 남는 기저 흐름은
  약한 음(-)"이라는 비대칭 구조가 정확한 서술이다. **[SPPV-2.36
  에서 정정] "전적으로 의존"은 과장이었다 — §26 참고, 정확히는
  "대형 스왑일은 가장 강한 개별 평균 효과를 보이고 aggregate(pooled)
  우위의 상당 부분(T+20 약 35%, T+5 약 70%)을 차지하지만, 총 양(+)
  합계의 15%만 차지해 '유일한 원천'은 아니다."**
- **분기3의 문제는 특정 소수 날짜 때문인가, 넓게 퍼진 불안정성
  인가?** → **양쪽 다이지만 방향이 다르다.** "양(+)의 원천"은 
  극소수(8일 내외)의 대형 스왑일에 집중돼 있고, "음(-)의 문제"는
  오히려 넓게 퍼진 다수(약 75일)의 소규모 스왑일에서 완만하게
  누적된 것이다 — 흔히 예상하는 "몇몇 나쁜 날 때문"이 아니라
  "몇몇 좋은 날을 빼면 넓게 퍼진 약한 마이너스만 남는다"는 구조다.
  **[SPPV-2.36에서 정정] "양(+)의 원천이 극소수 대형 스왑일에
  집중"이라는 서술도 과장이었다 — §26의 5분위 분해 결과 Q4(스왑
  2~3개, 소규모에 가까움)도 T+20 기준 +4.38%p의 뚜렷한 양(+)이라
  "양(+)=대형 전용"이 아니다. 정확히는 스왑 규모의 양극단(Q1
  최대·Q5 최소)에서 방향이 갈리고 중간 구간은 혼재한다.**
- **`R3b`의 분기3 반례가 이벤트성/실적발표성 집중일과 연결되는
  정황이 있는가?** → **부분적 정황만 있고, 확정할 근거는 없다.**
  가장 나쁜 두 날(2025-02-12, 02-13)이 연속 거래일이라는 점은
  짧은 이벤트/뉴스 군집 가능성을 시사하지만, 이 분석은 실적 캘린더
  ·뉴스 데이터를 조회하지 않았으므로 이는 **가설 수준의 관찰**일
  뿐 인과관계로 단정할 수 없다. 반대로 가장 좋은 날들(03-21,
  04-28, 05-07, 05-27, 06-10, 09-19, 09-22, 09-24)은 2월 이후
  거의 매달 흩어져 있어 뚜렷한 군집 패턴이 없다 — 즉 "이벤트
  집중일 가설"은 초기 2일(02-12~13)에 한해서만 정황상 성립 가능
  하고, 분기3 전체의 구조를 설명하지는 못한다.

### 25.6 판정 — 원인 확정을 우선, 재격상/재하향 없음(Watch 유지)

**이번 턴은 판정을 바꾸는 턴이 아니라 §24의 "소수 날짜 집중"
해석을 더 정밀하게(대형 스왑일=순기여 양(+), 다수 소규모
스왑일=완만한 음(-)) 다듬는 턴이다.** 결과적으로:
- 분기3이라는 반례는 여전히 남아 있고, 오히려 그 구조가 더
  복잡하다는 것이 확인됐다(단순 "나쁜 날 제거하면 해결"이 아니라
  "좋은 날을 빼면 기저가 약한 음(-)"인 구조).
- 이 발견은 R3b가 "분기3에서도 안정적"이라는 근거가 되지 못하며,
  오히려 분기3의 우위가 극소수 대형 스왑일에 크게 의존한다는
  점에서 재현성 우려를 강화한다.

**R3b/R3 모두 §22~§24의 Watch 판정을 그대로 유지한다.** `entry_
score` 운영 코드는 변경하지 않았다 — 이번 턴도 shadow/validation
범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 25.7 다음 단계

1. 2025-02-12~02-13의 실제 종목/뉴스/실적 발표 여부를 확인할 수
   있는 외부 데이터원이 확보되면 이벤트 연관성 가설을 검증한다
   (이번 턴은 read-only 셀프 데이터만 사용해 확인 불가).
2. 다수 소규모 스왑일(75일)의 완만한 음(-) 효과 자체가 다른 분기
   에서도 재현되는지(즉 "대형 스왑일=양, 소규모 스왑일=음"이라는
   패턴이 분기3만의 특이 현상인지, 다른 창에서도 약하게 존재하는지)
   확인하는 후속 진단.
3. §22.5/§23.7/§24.6에 남은 과제(더 긴 표본 축적, R3b의 §3 공식
   반영 여부 사용자 확인, §3 전제조건 충족 후 재검증)는 이번
   턴과 무관하게 계속 유효하다.

## 26. 분기3 반례의 대형/소규모 스왑 구조 정밀 확정 + "전적으로 의존" 문구 보수화 (SPPV-2.36, 2026-07-17)

§25.7(다음 단계 2)이 지시한 "대형 스왑일=양(+)/소규모 스왑일=음(-)"
패턴의 정량 확정을 실행했다. 스크립트: `scripts/validate_r3b_q3_
swap_size_bucket_decomposition.py`(read-only, 운영 코드 미수정,
broker submit 미호출). 산출: `logs/signal_ic_r3b_q3_swap_size_
bucket_decomposition_2026-07-17.json`, 실행 로그 `logs/r3b_q3_
swap_size_bucket_decomposition_run_2026-07-17.log`(신규 KIS 호출
0건 — `grep -c "HTTP Request:"`로 실측 확인, 기존 3년 캐시로 전량
서빙).

### 26.1 방법론

분기3 스왑 발생일 83건 전부를 스왑 개수(added+dropped) 내림차순
정렬해 **5분위(quintile, Q1=최대~Q5=최소, 각 16~17일)**로
구간화하고, 각 구간에 대해 (a) 거래일 수·스왑개수 범위, (b) paired
평균(구간 내 거래일들의 일별 교체효과 단순평균), (c) 구간 자체의
pooled 교체효과(구간 내 added 행 전체 - dropped 행 전체를 풀링한
평균차), (d) 그 구간을 통째로 제거했을 때 분기3 전체 aggregate_diff
와 paired 평균이 어떻게 바뀌는지를 계측했다. 별도로 상위 10%(대형,
§24/§25와 동일 정의, n=8)를 분리 보고하고, leave-top-k-days-out
(k=1,3,5,8)과 부호별 총합 분해(전체 양(+) 합계/음(-) 합계 및 그중
대형 10%의 비중), 2025-02-12/02-13 동시 제거 효과도 함께 계측했다.

### 26.2 실측 결과 — quintile 분해(T+5/T+20)

| 구간 | n일 | 스왑개수 | T+5 paired평균 | T+5 구간제거후 paired | T+20 paired평균 | T+20 구간제거후 paired |
|---|---|---|---|---|---|---|
| Q1(최대) | 17 | 4~6 | +3.34%p | -2.25%p | **+6.29%p** | -2.21%p |
| Q2 | 17 | 4 | -1.41%p | -1.02%p | -3.04%p | +0.20%p |
| Q3 | 16 | 3~4 | -4.87%p | -0.20%p | -2.96%p | +0.13%p |
| Q4 | 17 | 2~3 | -1.38%p | -1.03%p | **+4.38%p** | -1.71%p |
| Q5(최소) | 16 | 2 | -1.43%p | -1.02%p | **-7.57%p** | +1.23%p |

**T+20 기준, Q1(최대)과 Q4가 뚜렷한 양(+)이고 Q2·Q3·Q5는 음(-)이며
그중 Q5(최소, 스왑=2)가 가장 강한 음(-)(-7.57%p)이다.** 즉
"대형=양(+), 소규모=음(-)"이라는 단조적 그래디언트는 **양극단
(Q1 vs Q5)에서는 성립하지만 중간 구간(Q2~Q4)은 혼재**한다 — Q4는
스왑 규모가 작은데도(2~3개) 뚜렷한 양(+)이다.

### 26.3 상위 10%(대형) vs 전체 — aggregate 관점 vs 총합(gross) 관점

**aggregate(pooled, 순 기여) 관점 — leave-top-decile-out**:
- T+5: 원본 aggregate=0.3171%p → 대형 8일 제거 후 0.0942%p(원본
  대비 **29.7%** 잔존, 즉 대형이 **약 70.3%**를 담당)
- T+20: 원본 aggregate=1.2837%p → 대형 8일 제거 후 0.837%p(원본
  대비 **65.2%** 잔존, 즉 대형이 **약 34.8%**를 담당)

**총합(gross positive/negative 합계) 관점 — 부호별 분해**:
- T+5: 전체 양(+) 합계=+210.74%p 중 대형 비중=**15.6%**, 전체
  음(-) 합계=-302.33%p 중 대형 비중=**2.0%**
- T+20: 전체 양(+) 합계=+517.78%p 중 대형 비중=**15.0%**, 전체
  음(-) 합계=-556.50%p 중 대형 비중=**3.9%**

**두 관점이 다른 결론을 준다 — 이것이 이번 턴의 핵심 발견이다.**
aggregate(순 기여) 관점에서는 대형 스왑일이 우위의 상당 부분(T+5
약 70%, T+20 약 35%)을 담당해 "중요한 기여자"임은 맞다. 그러나
총합(gross) 관점에서는 대형 스왑일이 전체 양(+) 합계의 **15%
수준에 불과**하다 — 나머지 85%의 양(+)는 Q1 밖의 다른 날들(특히
Q4)에서도 상당히 나온다. 즉 **"대형 스왑일이 유일한 양(+)의
원천"이라는 서술은 과장이었다.** 정확한 서술은 "대형 스왑일은
개별 평균 효과가 가장 강하고 aggregate 우위에 대한 순 기여도가
크지만(스왑 규모가 커서 표본당 가중치가 큰 것도 한 요인), 총
양(+) 발생 자체를 독점하지는 않는다"이다.

### 26.4 leave-top-k-days-out 민감도 (T+20)

| k | 제거 후 aggregate | 원본 대비 | 제거 후 paired평균 |
|---|---|---|---|
| 1 | 1.3955%p | 108.7% | -0.3472%p |
| 3 | 1.3855%p | 107.9% | -0.4616%p |
| 5 | 1.2607%p | 98.2% | -0.6343%p |
| 8 | 0.8370%p | 65.2% | -1.2674%p |

k=1~3에서는 오히려 aggregate가 원본보다 커진다(2025-02-12/13처럼
초반 악재일이 상위 스왑개수에 섞여 있어, 소수만 제거하면 그 악재일
비중이 함께 빠지는 효과). k=8(상위 10%)에서 비로소 잔존비율이
65.2%로 크게 줄어든다 — "소수 거래일 집중"은 **k=8 근방에서만
뚜렷**하며 k=1~5 범위에서는 오히려 반대 방향으로 움직인다.

### 26.5 2025-02-12/02-13 동시 제거 효과

| horizon | 제거 전 aggregate | 제거 후 aggregate | 제거 전 paired | 제거 후 paired |
|---|---|---|---|---|
| T+5 | 0.3171%p | 0.3525%p | -1.1035%p | -1.091%p |
| T+20 | 1.2837%p | 1.4741%p | -0.4666%p | -0.2829%p |

T+20 기준 이 2일을 제거하면 paired 평균의 음(-) 갭이 -0.4666%p→
-0.2829%p로 **약 39.4% 줄어든다** — 유의미하지만 부분적인 설명력
이다(과반 미만). "초기 연속 악재일" 가설은 **분기3 음(-) paired
평균의 약 39%만 설명**하며, 나머지 약 61%는 다른(2월 이후 산발적)
소규모 스왑일들의 누적에서 온다.

### 26.6 해석 — "전적으로 의존" 표현의 보수화

1. **"전적으로 의존"은 과장이다.** aggregate 관점에서 대형 스왑일의
   순 기여 비중(T+5 70%, T+20 35%)은 상당하지만 100%가 아니고,
   총합(gross) 관점에서는 15% 수준에 불과하다 — "유일한 원천"이라는
   표현은 정정 대상이다. 정확한 표현: **"대형 스왑일은 개별 평균
   효과가 가장 강하고 aggregate 우위에 대한 순 기여 비중이 크지만
   (특히 T+5), 총 양(+) 발생을 독점하지는 않는다."**
2. **"완전한 착시가 아니다"는 여전히 유효하다.** Q1(대형)의 강한
   양(+)과 replacement_effect의 순수 양(+) 기여(§24)는 실제
   존재하며, 계산 방식만으로 만들어진 허상이 아니다.
3. **"대형=양(+)/소규모=음(-)"은 양극단에서만 성립한다.** Q1(최대)과
   Q5(최소)는 방향이 뚜렷이 갈리지만, Q4(스왑 2~3개)가 강한 양(+)
   이라는 것은 이 그래디언트가 단조적이지 않음을 보여준다 — 스왑
   규모만으로 방향을 예측할 수 없다.
4. **2025-02-12/13 "연속 악재일" 가설은 부분적으로만 유효하다** —
   분기3 음(-) paired 평균의 약 39%(T+20)만 설명하며, 나머지는
   여러 소규모 스왑일에 넓게 분산돼 있다.

### 26.7 판정 — 문구 정밀화·구조 확정, 재격상/재하향 없음(Watch 유지)

**이번 턴도 판정 변경이 아니라 §25의 "전적으로 의존"·"양(+)의
원천 집중" 표현을 실측 비중으로 보수화하는 턴이다.** 결과적으로:
- 분기3 반례는 여전히 실재하며(완전한 착시 아님), 대형 스왑일이
  aggregate 우위에 상당히 기여하는 것도 사실이다.
- 다만 "전적으로", "유일한" 같은 절대적 표현은 총합 관점 수치
  (대형 비중 15%)와 맞지 않아 정정했다 — 정확히는 "상당한 순
  기여, 그러나 독점은 아님"이다.
- 스왑 규모와 효과 방향의 관계는 단조적이지 않다(Q4 예외) — 이는
  "규모가 크면 좋다"는 단순 가설도 함께 기각한다.

**R3b/R3 모두 §22~§25의 Watch 판정을 그대로 유지한다.** `entry_
score` 운영 코드는 변경하지 않았다 — 이번 턴도 shadow/validation
범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 26.8 다음 단계

1. Q4(스왑 2~3개)가 왜 뚜렷한 양(+)인지, Q2·Q3(스왑 3~4개)는 왜
   음(-)인지 — 스왑 개수만으로 설명되지 않는 추가 변수(예: 종목별
   유동성, 국면 구성)가 있는지 확인하는 후속 진단.
2. 2025-02-12~13 실제 이벤트/실적 발표 연관성은 외부 데이터원
   확보 후 검증(가설 수준 유지).
3. §22.5/§23.7/§24.6/§25.7에 남은 과제(더 긴 표본 축적, R3b의 §3
   공식 반영 여부 사용자 확인)는 이번 턴과 무관하게 계속 유효하다.

## 27. R3b의 SPPV-3 진입 후보 여부 판단 — 실제 BUY funnel 최소 검증 (SPPV-2.37, 2026-07-17)

§26까지의 미세 해부(분기3 스왑 구조)를 멈추고, **"R3b를 SPPV-3
(창 교체 본작업) 착수 후보로 올릴 수 있는가"**를 판단하는 데
필요한 최소 검증을 실행했다. 기존 §20(SPPV-2.30)의 실제 BUY
funnel(candidate→eligible→selected→would_buy) 계측 결과(`logs/
signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`)를
재실행 없이 그대로 재사용하고, 이번 턴은 **would_buy 모집단 전체의
거래일 단위 편중도(top-decile-day leave-out)**만 8개 창 전부에
대해 신규 계측했다. 스크립트: `scripts/validate_r3b_sppv3_entry_
readiness_check.py`(read-only, 운영 코드 미수정, broker submit
미호출). 산출: `logs/signal_ic_r3b_sppv3_entry_readiness_check_
2026-07-17.json`, 실행 로그 `logs/r3b_sppv3_entry_readiness_check_
run_2026-07-17.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량 서빙).

### 27.1 질문 1 — R3b가 R0 대비 실제 BUY funnel에서 더 나은 후보를 고르는가?

§20의 기존 실측(재사용, 재실행 없음)을 표로 정리하면(T+20 기준):

| 창 | R0 평균 | R0 t_NW | R0 양수율 | R3b 평균 | R3b t_NW | R3b 양수율 | R3b selected_rate |
|---|---|---|---|---|---|---|---|
| 2차(3년) | +2.818% | 2.90 | 49.3% | **+6.134%** | **3.78** | 53.7% | 35.4% |
| 1차(12M) | +4.307% | 2.59 | 51.7% | **+9.160%** | **2.90** | 59.1% | 33.1% |
| 전반부 | +0.978% | 0.94 | 46.3% | **+2.830%** | **2.03** | 46.4% | 37.5% |
| 후반부 | +4.182% | 2.84 | 51.6% | **+8.478%** | **3.40** | 58.9% | 34.0% |
| 분기1 | +1.208% | 0.78 | 44.3% | **+2.616%** | 1.31 | 45.7% | 37.0% |
| 분기2 | +0.647% | 0.53 | 49.1% | **+3.122%** | 1.68 | 47.2% | 38.1% |
| 분기3 | +3.648% | 1.92 | 51.2% | **+4.932%** | 2.11 | 55.2% | 39.2% |
| 분기4 | +4.685% | 2.13 | 52.0% | **+12.231%** | **2.86** | 62.9% | 29.9% |

**8개 창 전부에서 R3b의 T+20 평균이 R0보다 높다**(§20에서 이미
확인된 사실의 재확인). **t_NW는 6/8 창에서 통상 유의 수준(≥1.96)
이상**이고, 나머지 2개 창(분기1=1.31, 분기2=1.68)은 marginal이나
방향은 일관되게 양(+)이다. **양수 비율은 혼재**한다 — 2차/1차/
후반부/분기3/분기4는 R0보다 높지만, 전반부·분기1·분기2는 R3b가
R0보다 오히려 낮거나 비슷하다(예: 분기2 R0 49.1% vs R3b 47.2%) —
즉 이 3개 창에서 R3b의 개선은 "적중률(hit rate)이 아니라 승리 폭
(MFE, §26)이 커서" 나타나는 개선이다.

### 27.2 질문 2 — 그 우위가 특정 일부 구간(거래일)에 과도하게 의존하는가?

**신규 계측 — would_buy 모집단의 top-decile-day(스왑개수 아닌
수익률 상위 10% 거래일) leave-out, T+20 기준:**

| 창 | R0 잔존비율 | R3b 잔존비율 |
|---|---|---|
| 2차(3년) | **-0.1%** | **41.9%** |
| 1차(12M) | 27.7% | **48.9%** |
| 전반부 | **-119.2%** | **17.5%** |
| 후반부 | 28.8% | **49.1%** |
| 분기1 | **-91.9%** | **10.7%** |
| 분기2 | **-173.3%** | **35.2%** |
| 분기3 | 35.1% | **52.2%** |
| 분기4 | 29.5% | **59.0%** |

**핵심 발견(이번 턴의 결정적 근거): R0(현행 재보정 없음 기준선)
자체가 8개 창 중 3개(전반부/분기1/분기2)에서 상위 10% 거래일을
제거하면 T+20 평균이 아예 마이너스로 뒤집힌다** — 즉 "거래일
집중 의존"은 R3b만의 문제가 아니라 **이 alpha 신호 계열(regime_
conditional_signal 기반 BUY funnel) 전반의 특성**이다. 그리고
**R3b는 8개 창 전부(8/8)에서 R0보다 잔존비율이 더 높다** — R3b가
R0보다 상위 10% 거래일에 **덜** 의존한다는 뜻이다. T+5는 전반적으로
더 노이즈가 크고(양쪽 모두 여러 창에서 음(-) 잔존비율), 여기서도
R3b가 R0보다 매 창 일관되게 덜 취약하다(JSON 참고). **[SPPV-2.38
에서 정정] "8개 창 중 3개"는 계산 오류였다 — 위 표를 다시 보면
2차(3년, -0.1%)도 음(-)이므로 정확히는 **8개 창 중 4개(2차·
전반부·분기1·분기2)**에서 R0의 T+20 평균이 마이너스로 뒤집힌다.
이 정정은 R3b의 상대적 우위를 오히려 더 강화한다 — R0가 더 많은
창(4/8, 절반)에서 상위 10% 거래일에 의존하는 반면 R3b는 8개 창
어디서도 음(-)으로 뒤집히지 않는다. 상세는 §28 참고.**

**분기1(T+20 잔존 10.7%)은 8개 창 중 R3b가 여전히 가장 취약한
구간**이며, 이는 §20에서 이미 R3b의 t_NW가 가장 낮은(1.31) 창과
일치한다 — 분기1은 R3b에게도 여전히 상대적 약점 구간이다.

### 27.3 해석 — SPPV-3 착수 후보로서의 R3b

1. **방향성 우위는 8/8 창에서 일관되고, 재현성 훼손 흔적이 없다**
   (§20 재확인 + 이번 턴의 day-concentration 신규 검증 통과).
2. **거래일 집중 의존은 R3b 고유 리스크가 아니라 alpha 신호 계열
   전체의 특성이며, R3b는 오히려 그 의존도를 완화하는 방향**이다
   — 이는 §24~§26이 발견한 "분기3에서만 예외적으로 나쁘다"는
   서술을 한 단계 더 정확하게 만든다: 거래일 집중은 R0에도 있고,
   R3b가 이를 악화시키지 않는다.
3. **남은 약점은 (a) 분기1·분기2 T+20 t_NW가 marginal(<1.96),
   (b) selected_rate 급감(약 30~40%, R0의 100% 대비 최대 70% 감소)
   으로 실거래 빈도가 크게 줄어드는 운영 트레이드오프, (c) T+5
   호라이즌은 전반적으로 더 취약, (d) 이 모든 검증이 여전히 shadow
   계산(entry_score 실제 point-in-time 파이프라인 통합 미검증)
   이라는 점**이다. **[SPPV-2.38에서 정정] (b)의 "selected_rate
   급감(약 30~40%)"은 표현이 모호했다 — 정확히는 **R3b의 selected_
   rate 자체가 eligible 대비 29.9~39.2% 수준**이고, 이는 R0의
   100% 대비 **약 61~70%p 감소**를 뜻한다("30~40%"는 감소폭이
   아니라 R3b 자신의 비율 수준). 상세는 §28 참고.**

### 27.4 판정 — Watch → Conditional Go로 상향(제한적 조건부)

**이번 턴은 SPPV-2.31에서 한 번 격상됐다가 SPPV-2.32에서 하향된
이력이 있으므로, 같은 실수를 반복하지 않도록 근거를 명시한다.**
이번 격상은 §2.31 당시(overlap 간접 근거 1개)와 달리:
- 8개 창(2차/1차/전반부/후반부/분기1~4) 전부에서 T+20 평균 우위
  방향 일관(재확인)
- 6/8 창에서 t_NW≥1.96(통상 유의), 나머지 2개도 방향은 일관
- **신규**: 거래일 단위 편중도가 R0보다 8/8 창에서 더 낮음(R3b가
  더 견고) — 이는 "소수 거래일 착시"라는 반대 가설을 8개 창
  전부에서 직접 반박한다
- 다만 양수 비율(적중률)은 3/8 창에서 R0보다 낮아 "승리 폭 확대형
  개선"이라는 한계가 있고, selected_rate 급감(거래 빈도 축소)의
  운영 영향은 아직 정량화하지 않았다 **[SPPV-2.38에서 정정: "3/8
  창"은 계산 오류였다 — 실제로는 T+20 기준 1/8 창(분기2)에서만
  R3b 양수 비율이 R0보다 낮고, 전반부·분기1은 R3b가 R0보다 근소
  하게 더 높다. T+5 기준으로는 8/8 창 전부에서 R3b 양수 비율이
  R0보다 높다 — "승리 폭 확대형 개선"이라는 한계 서술 자체를
  재검토해야 한다. 상세는 §28 참고.]**

**판정: R3b를 Watch에서 Conditional Go로 상향한다.** 단, 다음
조건을 명시한다 — **확정 Go로 가기 전에 반드시 확인해야 할 것**:
1. 분기1·분기2의 t_NW가 marginal한 이유(§20에서 이미 "미세 재조정
   유사 패턴" 논의됨)를 완전히 배제할 수 없으므로, 최소 1개 이상의
   out-of-sample 구간(3년 표본 밖) 축적 후 재확인.
2. selected_rate 급감(29.9~39.2%)에 따른 실거래 빈도 축소가 총
   기대수익(포트폴리오 단위, 종목당이 아닌)에 미치는 영향 정량화
   — 종목당 수익률이 커도 거래 횟수가 줄면 총 기대수익은 다를 수
   있다(§14~§16 활동성 필터 논의와 유사한 관점, 이번 턴 범위 밖).
3. §3 전제조건(§21 1차 게이트 `TRIGGERED` 전환, risk_off_penalty
   중복 해소) 충족 확인 — 아직 미충족.
4. 실제 point-in-time `entry_score` 파이프라인에 R3b 재보정 로직을
   반영한 shadow 실행(현재까지는 오프라인 rolling 재계산 방식) —
   운영 코드 반영 전 마지막 단계.

**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
변경하지 않았다** — 이번 턴도 shadow/validation 범위, broker submit
미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 27.5 다음 단계

1. selected_rate 급감이 총 기대수익(거래 빈도×종목당 수익)에
   미치는 영향을 정량화하는 후속 검증(위 조건 2).
2. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인.
3. 실제 point-in-time `entry_score` 파이프라인 반영 shadow 실행
   설계(운영 코드 반영 전 마지막 검증 단계).
4. 분기1·분기2의 marginal t_NW는 §22.5/§23.7 이후 누적된 표본으로
   재확인 — out-of-sample 데이터 축적 시 우선 재검증.

## 28. SPPV-2.37 수치 정정 + Conditional Go 재평가 (SPPV-2.38, 2026-07-17)

§27(SPPV-2.37)의 세 가지 수치 서술에 계산 오류가 있어 정정하고,
정정 후에도 `R3b: Watch→Conditional Go` 판정이 유지되는지 재평가
했다. **새 실험 없이** 기존 산출물(`logs/signal_ic_alpha_layer_r3_
reproducibility_2026-07-16.json`, `logs/signal_ic_r3b_sppv3_entry_
readiness_check_2026-07-17.json`)을 `python3 -c` read-only
재검산만으로 다시 읽어 확인했다(신규 KIS 호출 없음 — 신규 실행
자체가 없었으므로 해당 없음).

### 28.1 정정 1 — R0의 top-decile-day 음(-) 반전 창 수: 3개 → 4개

§27.2가 "R0 자체가 8개 창 중 3개(전반부/분기1/분기2)에서 T+20
평균이 마이너스로 뒤집힌다"고 서술했으나, §27.2 자신이 제시한
표를 다시 확인하면 **2차(3년, 잔존비율 -0.1%)도 음(-)이다** —
정확히는 **8개 창 중 4개(2차·전반부·분기1·분기2)**에서 R0가
음(-)으로 뒤집힌다. **이 정정은 R3b의 상대적 우위 논거를 약화시키지
않는다 — 오히려 R0가 절반(4/8)의 창에서 상위 10% 거래일에
의존한다는 것은 R0가 이전에 서술한 것보다 더 취약하다는 뜻이고,
R3b는 여전히 8개 창 어디서도 음(-)으로 뒤집히지 않는다.**

### 28.2 정정 2 — 양수 비율(적중률) 열세 창 수: 3/8 → 1/8(T+20), 0/8(T+5)

§27.2/§27.4가 "R3b의 양수 비율이 3/8 창(전반부·분기1·분기2)에서
R0보다 낮다"고 서술했으나, 재검산 결과 이는 틀렸다:

| 창 | T+20 R0 양수율 | T+20 R3b 양수율 | R3b<R0 | T+5 R0 양수율 | T+5 R3b 양수율 | R3b<R0 |
|---|---|---|---|---|---|---|
| 2차 | 49.32% | 53.71% | 아니오 | 49.51% | 54.69% | 아니오 |
| 1차 | 51.71% | 59.14% | 아니오 | 53.19% | 57.56% | 아니오 |
| 전반부 | 46.27% | **46.35%** | **아니오(근소하게 높음)** | 46.12% | 51.29% | 아니오 |
| 후반부 | 51.58% | 58.93% | 아니오 | 52.03% | 57.10% | 아니오 |
| 분기1 | 44.33% | **45.71%** | **아니오(근소하게 높음)** | 45.10% | 49.39% | 아니오 |
| 분기2 | 49.07% | **47.22%** | **예(유일)** | 47.58% | 53.89% | 아니오 |
| 분기3 | 51.16% | 55.19% | 아니오 | 48.84% | 54.87% | 아니오 |
| 분기4 | 51.97% | 62.89% | 아니오 | 55.04% | 59.45% | 아니오 |

**정확한 서술: T+20 기준 8개 창 중 1개(분기2)에서만 R3b의 양수
비율이 R0보다 낮다. T+5 기준으로는 8개 창 전부(8/8)에서 R3b의
양수 비율이 R0보다 높다.** 전반부·분기1은 §2.37이 "R0보다 낮다"고
분류한 것과 반대로 R3b가 (근소하지만) 더 높다. **이 정정은 R3b에
유리한 방향이다 — "승리 폭만 커지고 적중률은 개선되지 않는다"는
§27의 우려는 대부분 근거가 약했다. 다만 분기2(T+20, R0 49.1% vs
R3b 47.2%)는 실제로 적중률이 낮아지는 유일한 창이며, §27이 이미
지적한 분기2 t_NW marginal(1.68)과 결합해 분기2는 여전히 R3b의
상대적 약점 구간으로 남는다.**

### 28.3 정정 3 — "selected_rate 급감(약 30~40%)" 표현 명확화

§27.3/§27.4의 "selected_rate 급감(약 30~40%)"이라는 표현은 **감소
폭인지 R3b 자신의 비율 수준인지 모호**했다. 정확한 수치:
- R3b의 `selected_rate_of_eligible`는 8개 창에서 **29.86%~39.16%**
  이다 — 이것은 **R3b 자신의 통과율 수준**이지 R0 대비 감소폭이
  아니다.
- R0의 `selected_rate_of_eligible`는 정의상 **100%**다(문턱
  재보정 없이 eligible 전원이 selected로 간주됨).
- 따라서 R3b는 R0 대비 **약 61~70%p 감소**한 통과율을 보인다
  (100% - 29.86~39.16% = 60.84~70.14%p 감소).

**정정된 표현: "R3b의 selected_rate는 eligible 대비 29.9~39.2%
수준이며, 이는 R0(100%) 대비 약 61~70%p의 큰 감소다."**

### 28.4 재평가 — 정정 후에도 Conditional Go 상향이 유지되는가?

**유지된다.** 세 정정 중 어느 것도 R3b의 방향성 우위를 약화시키지
않는다:
- 정정 1(R0 음(-) 반전 4/8, 3/8 아님)은 R0의 취약성을 더 크게
  보여줘 R3b의 상대적 견고함 논거를 오히려 강화한다.
- 정정 2(양수 비율 열세 1/8, 3/8 아님)는 R3b에 유리한 방향이다 —
  §27이 우려한 "적중률 미개선"은 대부분(전반부·분기1) 근거가
  약했고, 분기2 1개 창만 실제로 해당한다.
- 정정 3(selected_rate 표현 명확화)은 숫자 자체를 바꾸지 않고
  해석만 정확히 한 것으로, 원래 §27이 인지하고 있던 "거래 빈도
  축소"라는 리스크의 실체(약 61~70%p 감소)는 그대로 유효하다.

**다만 이번 정정으로 드러난 것은 §2.37이 R3b에 유리한 방향으로도,
불리한 방향으로도 부정확했다는 사실이다** — 판정 자체보다 "근거를
정확히 세지 못했다"는 방법론적 경계가 필요하다는 교훈이 더
중요하다. 이번 정정 이후에도 남은 진짜 리스크는 §27.4가 이미
명시한 4개 조건(분기1·분기2 marginal t_NW, selected_rate 감소의
총 기대수익 영향, §3 전제조건, point-in-time 파이프라인 반영)
그대로다 — 이번 턴은 근거 숫자를 바로잡았을 뿐 새로운 리스크를
추가하거나 제거하지 않는다.

### 28.5 판정 — R3b: Conditional Go 유지(수치 정정 반영, 조건 불변)

**R3b는 Conditional Go를 유지한다.** §27.4의 확정 Go 전 잔여 조건
4가지(분기1·분기2 marginal t_NW out-of-sample 재확인, selected_
rate 감소의 총 기대수익 영향 정량화, §3 전제조건 충족, point-in-
time 파이프라인 반영 shadow 실행)는 이번 정정과 무관하게 그대로
유효하다. **운영 코드(`entry_score`, `deterministic_trigger_
engine.py`)는 변경하지 않았다** — 이번 턴도 shadow/validation
범위, broker submit 미호출. 신규 KIS 호출 없음(신규 실행 자체가
없었음 — 기존 JSON 재검산만 수행).

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 28.6 다음 단계

§27.5의 4개 항목(selected_rate 감소의 총 기대수익 영향 정량화,
§3 전제조건 충족 여부 확인, point-in-time 파이프라인 반영 shadow
실행 설계, 분기1·분기2 marginal t_NW out-of-sample 재확인)이
이번 턴과 무관하게 그대로 다음 우선순위다 — 이번 턴은 새 과제를
추가하지 않는다.

## 29. selected_rate 감소가 총 기대수익에 미치는 영향 정량화 (SPPV-2.39, 2026-07-17)

§27.4/§28.5가 명시한 Conditional Go 확정 전 4개 잔여 조건 중
**조건 (2) — selected_rate 감소(약 61~70%p)가 총 기대수익(거래
빈도×종목당 수익)에 미치는 영향 정량화**를 실행했다. **신규
실측/신규 KIS 호출 없이** 기존 산출물 두 개만 재사용해 계산한다:
`logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`
(§20, 8개 창 funnel), `logs/signal_ic_r3b_sppv3_entry_readiness_
check_2026-07-17.json`(§27, would_buy 거래일 수). 스크립트:
`scripts/validate_r3b_total_expected_return_proxy.py`(read-only,
로컬 재계산, KIS 호출 자체가 없음 — 로그로 확인, `grep -c "HTTP
Request:"` 결과 0건). 산출: `logs/signal_ic_r3b_total_expected_
return_proxy_2026-07-17.json`, 실행 로그 `logs/r3b_total_expected_
return_proxy_run_2026-07-17.log`.

### 29.1 방법론 — 총 기대수익 proxy

`WATCH_TOP_K_BUY=3`(거래일당 최대 매수 슬롯, `trigger_proxy_
attribution.py`의 실제 운영 상수)가 would_buy 종목마다 동일한
자본을 배정한다는 표준 가정 아래, 창별 **총 기대수익 proxy**를
다음과 같이 정의한다(신규 로직 아님, 단순 재구성):

```
총 기대수익 proxy = would_buy_n(거래 횟수) × mean_forward_return_pct(거래당 평균 수익률)
```

이는 "거래 횟수가 줄어도 거래당 품질이 충분히 좋으면 총합이 커질
수 있는가"를 직접 답한다. 함께 `n_days`(모집단 내 활동 거래일 수)
와 `would_buy_n/n_days`(활동일당 평균 매수 수, 최대 3)도 계산해
"덜 사서 평균이 높아 보이는 착시"인지 "실제 활동일당·거래당 품질
개선"인지 분리한다. **캐비어트**: 이 proxy는 매수하지 않은 날의
유휴 자본에 대한 기회비용(예: 현금/벤치마크 수익률)을 반영하지
않는다 — 순수하게 "실행된 거래"만의 총합 비교다.

### 29.2 실측 결과 — R0 vs R3b 총 기대수익 proxy (8개 창 × 2 horizon)

| 창 | horizon | R0 총proxy | R3b 총proxy | R3b/R0 |
|---|---|---|---|---|
| 2차(3년) | T+5 | 1680.8 | 2006.7 | **119.4%** |
| 2차(3년) | T+20 | 4347.7 | 6280.9 | **144.5%** |
| 1차(12M) | T+5 | 1384.8 | 1274.6 | **92.0%** |
| 1차(12M) | T+20 | 2898.3 | 4058.0 | **140.0%** |
| 전반부 | T+5 | 290.7 | 521.6 | **179.4%** |
| 전반부 | T+20 | 642.7 | 1202.8 | **187.1%** |
| 후반부 | T+5 | 1390.2 | 1485.1 | **106.8%** |
| 후반부 | T+20 | 3705.1 | 5078.1 | **137.1%** |
| 분기1 | T+5 | 164.7 | 182.2 | **110.6%** |
| 분기1 | T+20 | 468.5 | 640.9 | **136.8%** |
| 분기2 | T+5 | 125.9 | 339.4 | **269.6%** |
| 분기2 | T+20 | 174.2 | 561.9 | **322.6%** |
| 분기3 | T+5 | 272.0 | 292.5 | **107.5%** |
| 분기3 | T+20 | 1568.6 | 1518.9 | **96.8%** |
| 분기4 | T+5 | 1118.2 | 1192.6 | **106.7%** |
| 분기4 | T+20 | 2136.5 | 3559.2 | **166.6%** |

활동일당 평균 매수 수(3 만점): R0는 8개 창 전부에서 2.69~2.80(거의
포화), **R3b는 2.15~2.31로 R0보다 낮다** — R3b는 활동일 수도
적고(예: 2차 R0 560일 vs R3b 464일) 활동일당 매수 수도 적다. 즉
"덜 산다"는 것은 두 차원(활동일 수 감소 + 활동일당 매수 수 감소)
모두에서 사실이다.

### 29.3 해석 — "덜 사지만 총합도 더 많다"는 결론이 지배적이다

**16개(8개 창×2 horizon) 중 14개에서 R3b의 총 기대수익 proxy가
R0보다 높다**(92.0%~322.6%, 중앙값 약 138%). **2개만 R0에 근접하거나
근소하게 낮다**(1차 T+5=92.0%, 분기3 T+20=96.8%) — 둘 다 100%에서
크게 벗어나지 않는 "거의 동률" 수준이며, 이전 턴들이 이미 지목한
약점 구간(1차의 T+5 노이즈, 분기3의 복잡한 날짜 구조)과 정확히
일치한다.

**이는 §27~§28이 미해결로 남겨둔 "거래 빈도 감소가 총 기대수익을
훼손하는가"라는 질문에 명확한 답을 준다 — 아니다.** 거래당 수익률
개선(R3b의 mean_pct가 R0보다 항상 큼, §20/§27 재확인)이 거래
횟수 감소(-40%~-64%, 활동일 수·활동일당 매수 수 동시 감소)를
충분히 상쇄하고도 남는다. "덜 사니까 평균이 높아 보이는 착시"가
아니라, **실제로 거래 횟수 감소를 넘어서는 품질 개선**이라는 것이
14/16 조합에서 확인된다.

### 29.4 판정 — Conditional Go 유지·조건 (2) 해소

**§27.4/§28.5의 확정 Go 전 잔여 조건 4가지 중 조건 (2)(selected_
rate 감소의 총 기대수익 영향 정량화)는 이번 턴으로 해소됐다** —
답은 "거래 빈도 감소가 총 기대수익을 훼손하지 않는다"이며, 14/16
조합에서 명확히 확인됐고 나머지 2개도 심각한 훼손이 아니라 거의
동률 수준이다.

**다만 이것으로 확정 Go를 선언하지는 않는다** — 나머지 3개 조건이
그대로 남아 있기 때문이다:
1. 분기1·분기2의 t_NW가 marginal(<1.96)한 것은 이번 계측과 무관한
   별개 통계적 유의성 문제다 — 총 기대수익 proxy가 커도(분기2는
   오히려 R3b가 322.6%로 가장 크게 앞서는 창이다) 개별 평균의
   통계적 신뢰도는 여전히 낮다는 점은 변하지 않는다.
2. §3 전제조건(1차 게이트 TRIGGERED 전환) 미충족.
3. 실제 point-in-time `entry_score` 파이프라인 반영 shadow 실행
   미실시(현재까지는 오프라인 rolling 재계산 방식).
4. 이 proxy는 유휴 자본의 기회비용을 반영하지 않는다는 캐비어트도
   남아 있다(§29.1).

**판정: R3b는 Conditional Go를 유지하며, 4개 잔여 조건 중 1개
(조건 2)가 해소돼 근거가 보강됐다.** 확정 Go로 가려면 남은 3개
조건(분기1·분기2 marginal t_NW, §3 전제조건, point-in-time
파이프라인 반영)이 여전히 필요하다. **운영 코드(`entry_score`,
`deterministic_trigger_engine.py`)는 변경하지 않았다** — 이번
턴도 shadow/validation 범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 29.5 다음 단계

1. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인
   — 남은 조건 중 가장 명확한 다음 우선순위.
2. 실제 point-in-time `entry_score` 파이프라인 반영 shadow 실행
   설계(운영 코드 반영 전 마지막 검증 단계).
3. 분기1·분기2의 marginal t_NW는 out-of-sample 데이터 축적 시
   재확인(이번 턴과 무관하게 계속 유효).
4. (선택) 유휴 자본 기회비용을 반영한 총 기대수익 proxy 정교화는
   §3 전제조건 충족 이후 우선순위가 낮은 후속 과제로 남긴다.

## 30. R3b 총 기대수익 proxy의 유휴 자본 반영 보강 검증 (SPPV-2.40, 2026-07-17)

§29.5(다음 단계 4)가 남긴 "유휴 자본 기회비용을 반영한 총 기대수익
proxy 정교화"를 실행했다. **이번 턴이 답해야 할 정확한 질문**:
"§29의 `would_buy_n × mean_forward_return_pct` proxy가 활동하지
않은 거래일·미사용 매수 슬롯의 기회비용을 반영하지 않는데, 이를
반영해도 R3b의 총 기대수익 우위가 유지되는가, 아니면 상당 부분
사라지는가?" 스크립트: `scripts/validate_r3b_capital_utilization_
adjusted_proxy.py`(read-only, 운영 코드 미수정, broker submit
미호출). 이번 스크립트가 유일하게 신규 계측한 값은 **창별 전체
거래일 수**(기존 3년 캐시 봉 데이터로만 계산, 신규 KIS 호출 없음
— `grep -c "HTTP Request:"` 결과 0건)이며, 나머지는 기존 §20 JSON
(`logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`)
을 그대로 재사용했다. 산출: `logs/signal_ic_r3b_capital_
utilization_adjusted_proxy_2026-07-17.json`, 실행 로그 `logs/r3b_
capital_utilization_adjusted_proxy_run_2026-07-17.log`.

### 30.1 방법론 — 3가지 proxy

1. **기존(raw) proxy(§29와 동일)**: `would_buy_n × mean_pct` —
   미사용 슬롯을 암묵적으로 0%(유휴 현금)로 가정.
2. **보강 A(전체 슬롯 정규화, per-slot)**: `전체 거래일 수 × 3
   (WATCH_TOP_K_BUY)`을 "전체 가용 슬롯"으로 두고, raw proxy를 이
   값으로 나눈다. **R0/R3b가 같은 창의 같은 분모로 나뉘므로, 이
   정규화는 대수적으로 R3b/R0 비율을 전혀 바꾸지 않는다(항등식)**
   — 실측으로도 그대로 확인됐다(아래 표의 "raw"·"per-slot" 두
   비율이 소수점 이하까지 100% 일치). 이는 §29의 결론이 "거래
   횟수 단위"였든 "전체 자본 단위"였든 동일하게 성립한다는 것을
   추가로 확인해주지만, 그 자체로 새로운 정보를 주지는 않는다.
3. **보강 B(엄격한 기회비용 상한 테스트)**: R3b의 **실현된**
   총합(raw, 미사용=0%로 가정 — R3b 입장에서 이미 보수적)을, "R0가
   전체 가용 슬롯을 하나도 남기지 않고 R0 자신의 평균 수익률로
   100% 채웠다면 얻었을 이론적 최대"(`전체 슬롯 × R0 평균`)와
   비교한다. 이는 R0의 §29 **실현된** 총합(항상 이론적 최대보다
   작거나 같음)보다 더 큰, R3b에게 가장 불리한 벤치마크다.

### 30.2 실측 결과 — 창별 전체 거래일 수 및 엄격 기준 비교

| 창 | 거래일 | horizon | raw(§29) R3b/R0 | 엄격기준(R0 이론적 최대 대비) R3b | 판정 뒤집힘 |
|---|---|---|---|---|---|
| 2차 | 653일 | T+5 | 119.4% | **94.0%** | 예 |
| 2차 | 653일 | T+20 | 144.5% | **113.8%** | 아니오 |
| 1차 | 245일 | T+5 | 92.0% | **84.3%** | 아니오 |
| 1차 | 245일 | T+20 | 140.0% | **128.2%** | 아니오 |
| 전반부 | 326일 | T+5 | 179.4% | **120.5%** | 아니오 |
| 전반부 | 326일 | T+20 | 187.1% | **125.7%** | 아니오 |
| 후반부 | 327일 | T+5 | 106.8% | **96.5%** | 예 |
| 후반부 | 327일 | T+20 | 137.1% | **123.8%** | 아니오 |
| 분기1 | 163일 | T+5 | 110.6% | **87.8%** | 예 |
| 분기1 | 163일 | T+20 | 136.8% | **108.5%** | 아니오 |
| 분기2 | 163일 | T+5 | 269.6% | **148.3%** | 아니오 |
| 분기2 | 163일 | T+20 | 322.6% | **177.5%** | 아니오 |
| 분기3 | 163일 | T+5 | 107.5% | **94.6%** | 예 |
| 분기3 | 163일 | T+20 | 96.8% | **85.1%** | 아니오(이미 raw도 열세) |
| 분기4 | 164일 | T+5 | 106.7% | **98.8%** | 예 |
| 분기4 | 164일 | T+20 | 166.6% | **154.4%** | 아니오 |

### 30.3 해석 — horizon에 따라 결론이 갈린다: T+20은 견고, T+5는 취약

**T+20 기준: 8개 창 중 7개(2차/1차/전반부/후반부/분기1/분기2/분기4)
에서 R3b가 R0의 이론적 최대 자본 활용 시나리오보다도 여전히
높다**(108.5%~177.5%) — 분기3만 예외(85.1%, 이미 raw 기준으로도
96.8%로 열세였던 창). **이는 T+20 horizon에서는 R3b의 총 기대수익
우위가 "가장 관대하게 R0를 가정해도" 견고하다는 강한 증거다.**

**T+5 기준: 8개 창 중 6개(2차/후반부/분기1/분기3/분기4 + 1차)가
엄격 기준에서 100% 미만으로 뒤집히거나 이미 열세다** — 오직
전반부(120.5%)와 분기2(148.3%) 2개 창만 엄격 기준을 통과한다.
**즉 T+5에서는 "유휴 자본을 R0 자신의 평균 수익률로 100% 채웠다면"
이라는 가정 아래 R3b의 총 기대수익 우위가 대부분 사라진다.**

이 horizon별 비대칭은 새로운 발견이 아니라 §20/§27~§29에서
반복적으로 확인된 패턴("T+5는 노이즈가 크고 T+20이 더 신뢰할
근거")과 일치한다 — 이번 검증은 그 패턴이 "총 기대수익" 관점에서도
동일하게 나타남을 추가로 확인했다.

### 30.4 판정 — 조건 (2) "해소"가 아니라 "완화/축소"로 재조정

**§29가 "조건 (2)가 해소됐다"고 표현한 것은 이번 보강 검증
기준으로는 과장이다.** 정확한 서술: **조건 (2)는 T+20 기준으로는
상당 부분 완화됐으나(엄격 기준 통과 7/8), T+5 기준으로는 여전히
미해결에 가깝다(엄격 기준 통과 2/8).** "거래 빈도 감소가 총
기대수익을 훼손하는가"라는 질문에 대한 정확한 답은 "T+20에서는
아니다(견고), T+5에서는 유휴 자본을 관대하게 가정하면 그렇다고
볼 여지가 있다"이다.

**R3b/R0의 raw proxy와 per-slot proxy는 완전히 동일한 비율을
보였다(항등식 확인)** — 이는 §29의 계산 방식이 "거래당" 단위였든
"전체 자본" 단위였든 결론이 달라지지 않는다는 것을 재확인하지만,
이 자체가 "조건 (2) 해소"의 근거가 되지는 못한다(같은 계산을
다른 단위로 표현한 것뿐이므로).

**판정: R3b는 Conditional Go를 유지한다.** §29가 "해소"라고
표현했던 조건 (2)는 이번 턴으로 **"완화/축소"** 수준으로 재조정
한다 — T+20 horizon에서는 엄격한 기회비용 가정 아래서도 견고하지만,
T+5 horizon에서는 여전히 유휴 자본을 관대하게 채웠다고 가정하면
우위가 대부분 사라진다. 확정 Go 전 잔여 조건은 다음과 같이
갱신한다:
1. 분기1·분기2의 marginal t_NW out-of-sample 재확인(불변).
2. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 확인(불변).
3. 실제 point-in-time `entry_score` 파이프라인 반영 shadow
   실행(불변).
4. **[갱신] T+5 horizon에서의 총 기대수익 우위가 유휴 자본 가정에
   취약하다는 점 — T+5 의존 운영 판단(단기 회전 전략 등)이 있다면
   추가 검증 필요, T+20 중심 운영이라면 이 리스크의 영향은 제한적.**

**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
변경하지 않았다** — 이번 턴도 shadow/validation 범위, broker
submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 30.5 다음 단계

1. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인
   — 여전히 가장 명확한 다음 우선순위.
2. 실제 point-in-time `entry_score` 파이프라인 반영 shadow 실행
   설계.
3. 분기1·분기2의 marginal t_NW는 out-of-sample 데이터 축적 시
   재확인.
4. T+5 horizon에서의 유휴 자본 취약성이 실제 운영 결정(단기
   회전율 요구 여부)에 어떤 의미를 갖는지 사용자 확인 — 이 시스템의
   운영 호라이즌이 T+20 중심인지 T+5도 포함하는지에 따라 우선순위가
   달라진다.

## 31. R3b Conditional Go의 운영 horizon 적합성 판단 (SPPV-2.41, 2026-07-17)

§30.5(다음 단계 4)가 남긴 질문 — "이 시스템이 실제로 T+20 성격의
보유/평가 체계에 더 가까운가, 아니면 T+5 취약성이 실운영에서도
문제가 되는가" — 를 코드·문서 근거로 판단했다. **새 시장 데이터
실측 없이** 운영 코드(`deterministic_trigger_engine.py`, `schemas.
py`, `common_types.py`)와 5개 기준 문서를 직접 조사했다(신규 KIS
호출 없음 — 이번 턴은 코드/문서 read만 수행, 스크립트 실행
자체가 없었음).

### 31.1 조사 결과 — 이 시스템에는 강제된 보유기간이 존재하지 않는다

1. **`deterministic_trigger_engine.py`**: `buy_candidate_threshold
   =0.65`, `watch_candidate_threshold=0.45`, `reduce_candidate_
   threshold=0.60`, `sell_candidate_threshold=0.75`(89~92행)는
   모두 **점수 크기 기준**이며 날짜/경과일 기준이 아니다. 매도/청산
   판정은 `exit_score`(국면 risk-off, 보유 편향, 무보유 페널티 등
   피처 기반으로 산출, `_build_exit_score` 근처 1173행)를 계산해
   `_assess_exit_eligibility`(1014행, exit_score≤0.30이면 탈락)와
   `_build_exit_ranking_score`(1106행)로 순위를 매기는 방식이다.
   **이 계산 어디에도 경과일수·보유일수가 입력으로 들어가지
   않는다** — 즉 SELL 트리거는 100% 신호/점수 기반이지 시간 기반이
   아니다.
2. **`schemas.py`의 `max_holding_days=20`(552~558행 `ExitPlanHint`),
   `max_holding_horizon="swing"`(441행)**: 이들은 **AI Risk agent가
   생성하는 LLM 출력 힌트 필드**이며, `ai_risk.py`(239, 282, 309행)
   를 통해 그대로 통과(pass-through)만 될 뿐, **이 값을 다시 읽어
   실제 매도를 강제하는 코드는 존재하지 않는다.** `common_types.
   py:335`의 `position_age_seconds`도 정의만 있을 뿐 임계값 비교
   로직이 없다. **`max_holding_days=20`이 T+20과 우연히 일치하는
   숫자이지만, 이 값이 실제로 20일 뒤 매도를 강제하는 어떤 코드
   경로도 발견되지 않았다** — T+20을 "의도된 보유기간"으로 해석할
   코드적 근거가 없다.
3. **손절/익절/트레일링 스탑**: 코드 전체에서 숫자 기반 stop-loss/
   take-profit/trailing 임계값을 찾지 못했다. `schemas.py`의
   `stop_style="volatility_based"`, `take_profit_style="partial_
   scale_out"`은 문자열 스타일 라벨일 뿐 실제 수치 로직이 아니다.
   `reverse_trade_hysteresis.py:445`의 `"stop_loss"`는 사유 코드
   문자열로만 등장한다.
4. **`plans/[DESIGN] signal_predictive_power_validation.md`의 실제
   1차/2차 구분**: 이 구분은 **horizon(T+5 vs T+20)이 아니라
   기간 창(최근 12개월 vs 3년 전체)**에 대한 것이다 — "최근 12개월
   창을 1차(primary) 기본값으로 확정, 3년 전체는 국면 커버리지
   확인용 2차(supplementary)로 격하"(문서 초반부). Go/No-Go 기준
   (§16)은 **T+5와 T+20을 동시에, 병렬적으로** 요구해왔다(예:
   "8개 창 중 하나라도 악화되면" 기준의 "8개 창"= {1차,2차,전반부,
   후반부}×{T+5,T+20}) — 이는 이번 세션에서 새로 만든 기준이 아니라
   R3/R3b 검증 내내 **이미 적용돼 온 기존 표준**이다. 문서 어디에도
   "T+20이 실제 보유기간을 대표한다"는 서술은 없다 — T+5/T+20은
   대등한 두 개의 강건성 체크포인트로 취급돼 왔다.
5. **`FORWARD_HORIZONS_FOCUS=[5,20]`**(`validate_signal_
   predictive_power_v4_extended_period.py:61`): 왜 5와 20을
   선택했는지 설명하는 주석이 없다 — 단기(약 1주)/중기(약 1개월)
   체크포인트로 v2 스크립트에서 그대로 계승된 값으로 보인다.
6. **실거래 이력 부재**: `logs/trigger_proxy_attribution_2026-07-
   1{4,5,6}.json`(운영 attribution 로그, 검증 산출물 아님)을 확인한
   결과 candidate/eligibility 집계만 있고 실제 진입-청산 쌍으로
   실측 평균 보유기간을 계산할 근거가 없다 — 이 시스템은 아직
   실거래(BUY 0건 문제, [foundational-design-review-2026-07-14]
   메모리 참고)가 누적되지 않아 "실제로 평균 며칠 보유하는지"를
   경험적으로 답할 데이터 자체가 없다.

### 31.2 판정 — "T+20 중심"이라는 근거는 코드상 존재하지 않는다

**결론: 이 시스템은 강제된 보유기간이 전혀 없는 순수 신호/점수
기반 청산 구조다.** 포지션은 `exit_score`가 임계값을 넘는 즉시
청산될 수 있으며, 그 시점이 진입 후 5일일 수도 20일일 수도 그
이상일 수도 있다 — 코드가 이를 결정하지 않는다. 따라서:

- **"이 시스템은 T+20 중심이므로 T+5 취약성은 무시해도 된다"는
  주장은 코드로 뒷받침되지 않는다.** `max_holding_days=20`은
  집행되지 않는 LLM 힌트 기본값일 뿐이다.
- 반대로 "T+5가 실제 보유기간이다"라는 근거도 없다 — 이 시스템은
  애초에 특정 horizon을 "실제 보유기간"으로 삼도록 설계돼 있지
  않다.
- **§16의 기존 Go/No-Go 표준(T+5·T+20 동시 요구)이 이미 정답에
  가깝다** — 이 표준 자체가 "어느 한 horizon만으로는 불충분하다"는
  것을 전제로 세워진 것이며, 이번 조사는 그 전제가 옳았음을
  재확인한다.

**따라서 §30이 발견한 "T+5는 엄격 기준에서 6/8 창이 열세"라는
사실은 무시할 수 없다.** 이 시스템에 T+20 보유가 보장된다는 코드적
근거가 없는 이상, T+5에서의 약점은 T+20에서의 강점과 **대등하게**
취급해야 한다.

### 31.3 판정 — R3b: Conditional Go 유지, 단 T+5 강건성을 확정 Go의 필수조건으로 격상

**세 가지 선택지 중: "T+5 취약성이 실운영과 충돌하므로 재검토가
필요하다"에 가장 가깝다 — 다만 즉시 Watch로 재하향할 근거는 아직
부족하다.** 이유:
- T+20 근거는 여전히 강하다(§27~§30에서 8개 창 중 7~8개 일관 우위,
  엄격 기준도 7/8 통과) — 완전한 근거 상실은 아니다.
- 실거래 이력이 없어 "실제 평균 보유기간"을 경험적으로 검증할
  방법이 아직 없다 — "T+5에서 반드시 실패한다"고 단정할 근거도
  없다(코드가 특정 horizon을 강제하지 않으므로 실제 청산 시점
  분포는 이 시스템이 운영되기 전까지 알 수 없다).
- 다만 "T+5는 덜 중요하니 무시해도 된다"는 판단은 이번 조사로
  명백히 기각된다.

**R3b는 Conditional Go를 유지한다.** 그러나 확정 Go 전 잔여 조건을
다음과 같이 재구성한다 — **T+5 강건성 확보(또는 실제 청산 시점
분포 실측)를 기존 4개 조건과 동등한 필수조건으로 승격**한다:
1. 분기1·분기2의 marginal t_NW out-of-sample 재확인(불변).
2. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 확인(불변).
3. 실제 point-in-time `entry_score` 파이프라인 반영 shadow
   실행(불변).
4. **[격상] T+5 horizon에서의 유휴 자본 취약성(§30, 엄격 기준
   6/8 창 열세) 해소 — R3b가 T+5에서도 견고해지도록 추가 보정하거나,
   실거래 누적 후 실제 청산 시점 분포를 측정해 T+5 비중이 낮음을
   실증해야 한다.** 이 조건이 해소되기 전까지 **확정 Go는 시기상조**
   이다.

**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
변경하지 않았다** — 이번 턴은 조사·해석 턴으로 코드 실행 자체가
없었다, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 31.4 다음 단계

1. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인
   — 여전히 최우선.
2. T+5 horizon에서 R3b의 강건성을 개선할 수 있는지(신규 재보정안
   설계는 이번 턴 범위 밖 — 사용자 지시 시 별도 턴에서 진행) 또는
   실거래 누적 후 실제 청산 시점 분포를 측정하는 계획 수립.
3. 실제 point-in-time `entry_score` 파이프라인 반영 shadow 실행
   설계.
4. 분기1·분기2의 marginal t_NW out-of-sample 재확인.

## 32. R3b를 point-in-time `entry_score` 파이프라인에 반영한 shadow 검증 (SPPV-2.42, 2026-07-17)

§31.4(다음 단계 3)가 남긴 "실제 point-in-time `entry_score` 파이프
라인 반영 shadow 실행"을 수행했다. **이번 턴에서 소거하려는 조건**:
Conditional Go 확정 전 잔여 4개 조건 중 **"오프라인 rolling
재계산에서 한 단계 더 나아가 실제 운영 판단 경로에 가까운 구조
에서도 R3b가 창 교체 후보로 유효한지"**를 확인하는 것.

### 32.1 사전 확인 — 기존 검증은 이미 상당 부분 실제 함수를 호출해왔다

코드 조사 결과, §18(SPPV-2.28)부터 이어져 온 검증 스크립트들
(`validate_alpha_layer_score_rescaling_comparison.py` 등)은 **이미
운영 함수를 직접 import해 호출해왔다** — `signal_backbone.build_
signal_snapshot`(실제 피처/스코어 계산), `deterministic_trigger_
engine._assess_buy_eligibility`(실제 eligibility 판정), `deterministic_
trigger_engine._build_entry_score`(실제 entry_score 계산 함수)가
그것이다. 즉 "오프라인 재구현"이 아니라 실제 함수 호출이었다 —
이 부분은 이번 턴에 새로 확인한 사실이다.

**다만 실제 `_build_entry_score()`가 받는 조정항 중 `strategy_
selection`(선호 전략이 `swing_momentum`/`event_continuation`이면
entry_score에 **+0.05** 보너스, `deterministic_trigger_engine.py`
실측)이 기존 검증 전부에서 항상 `None`으로 넘겨져 누락돼
있었다.** `portfolio_allocation`(계좌 잔고/포지션 필요, 실거래
이력이 없어 재구성 불가 — §18부터 이어진 관례, 이번 턴도 동일하게
`None` 유지)과 달리, `strategy_selection`은 **market_regime과
source_type만으로 계산되는 순수 함수**(`select_strategy()`)라
오프라인에서도 실제 값으로 채울 수 있다 — 이번 턴이 신규로 채운
유일한 실제 조정항이다.

### 32.2 방법론

스크립트: `scripts/validate_r3b_point_in_time_pipeline_shadow.py`
(read-only, 운영 코드 미수정, broker submit 미호출). 기존 row
수집 로직에 `select_strategy(market_regime=..., source_type=
"core")`를 실제로 호출해 `entry_score_a`(A, 현행 alpha)와 R0/R3b
(가상 alpha 교체)의 non-alpha 재구성 항 양쪽에 동일하게 반영했다
— A/B 모두 같은 시장국면·같은 종목·같은 날짜에 대해 동일한
`strategy_selection`을 쓰므로 공정한 비교다. 8개 창(2차/1차/전반부/
후반부/분기1~4) BUY funnel(candidate→eligible→selected→would_buy)
을 재계측했다. 산출: `logs/signal_ic_r3b_point_in_time_pipeline_
shadow_2026-07-17.json`, 실행 로그 `logs/r3b_point_in_time_
pipeline_shadow_run_2026-07-17.log`(신규 KIS 호출 0건 — 기존 3년
캐시로 전량 서빙, `grep -c "HTTP Request:"` 결과 0건).

### 32.3 실측 결과 — OLD(§20, strategy_selection 없음) vs NEW(이번 턴, strategy_selection 반영)

| 창 | horizon | OLD R3b 평균 | NEW R3b 평균 | OLD t_NW | NEW t_NW | 방향 유지 |
|---|---|---|---|---|---|---|
| 2차 | T+5 | 1.960% | 1.887% | 4.00 | 3.99 | 예 |
| 2차 | T+20 | 6.134% | 5.725% | 3.78 | 3.67 | 예 |
| 1차 | T+5 | 2.877% | 3.031% | 3.04 | 3.32 | 예(강화) |
| 1차 | T+20 | 9.160% | 9.043% | 2.90 | 2.99 | 예(강화) |
| 전반부 | T+5 | 1.227% | 0.994% | 2.16 | 1.81 | 예 |
| 전반부 | T+20 | 2.830% | 2.186% | 2.03 | 1.62 | 예(약화) |
| 후반부 | T+5 | 2.479% | 2.533% | 3.39 | 3.59 | 예(강화) |
| 후반부 | T+20 | 8.478% | 8.287% | 3.40 | 3.45 | 예 |
| 분기1 | T+5 | 0.744% | 0.563% | 1.13 | 0.88 | 예(약화) |
| 분기1 | T+20 | 2.616% | 1.815% | 1.31 | **0.96** | 예(약화) |
| 분기2 | T+5 | 1.886% | 1.614% | 1.91 | 1.68 | 예(약화) |
| 분기2 | T+20 | 3.122% | 2.717% | 1.68 | 1.48 | 예(약화) |
| 분기3 | T+5 | 0.950% | 0.875% | 1.66 | 1.61 | 예 |
| 분기3 | T+20 | 4.932% | 5.008% | 2.11 | 2.16 | 예(강화) |
| 분기4 | T+5 | 4.098% | 4.301% | 3.05 | 3.30 | 예(강화) |
| 분기4 | T+20 | 12.231% | 11.783% | 2.86 | 2.87 | 예 |

**모든 16개(8개 창×2horizon) 조합에서 R3b>R0 방향이 그대로
유지된다** — strategy_selection을 실제로 반영해도 방향이 뒤집히는
창은 하나도 없다. 다만 효과 크기는 창마다 갈린다: 6개 조합은
강화(1차 양쪽, 후반부 T+5, 분기3 T+20, 분기4 양쪽), 나머지는 소폭
약화 — 특히 **분기1 T+20의 t_NW가 1.31→0.96으로 더 낮아져,
이미 marginal이던 문제가 이번 검증으로 더 뚜렷해졌다.**

R3b의 `selected_rate`도 함께 상승했다(예: 2차 35.4%→39.4%, 후반부
34.0%→37.7%, 분기4 29.9%→32.5%) — strategy_selection 보너스가
일부 경계선 종목을 0.65 문턱 위로 밀어 올린 결과다. 이는 §29~§30의
"selected_rate 감소" 우려를 소폭 완화하는 방향이다.

### 32.4 해석 — 왜 이 검증이 기존 rolling 검증보다 한 단계 더 강한 근거인가

1. **실제 함수 재사용 범위가 넓어졌다**: 기존 검증도 `build_signal_
   snapshot`/`_assess_buy_eligibility`/`_build_entry_score`를 실제
   함수로 호출해왔지만, 그중 한 개의 실제 조정항(`strategy_
   selection`)이 항상 `None`으로 누락돼 있었다 — entry_score_a
   조차 완전한 실제값이 아니었다. 이번 턴은 이 누락을 실제
   `select_strategy()` 호출로 메워, **A/B 양쪽 모두 이전보다 실제
   운영 point-in-time 계산에 더 가까운 entry_score**를 사용했다.
2. **A/B 공정성은 유지된다**: strategy_selection은 시장국면과
   source_type에만 의존해 A(현행)와 B(R3b 등) 양쪽에 동일하게
   적용되므로, 이 보정이 어느 한쪽에 유리하게 편향되지 않는다 —
   순수하게 "더 완전한 entry_score"로 재측정한 것이다.
3. **여전히 남은 gap**: `portfolio_allocation`(계좌 잔고/포지션
   기반 조정, 최대 ±0.20)은 실거래 이력이 없어 이번에도 재현하지
   못했다 — 이는 §18부터 이어진 관례적 한계이며, 실거래 계좌 상태
   없이는 shadow로 채울 수 없다. 따라서 "완전한 실제 파이프라인"은
   아니지만, 이번 턴으로 그 gap이 하나 줄었다.

### 32.5 판정 — Conditional Go 유지, 방향성은 재확인되나 분기1 약점은 심화

**16/16 조합에서 방향이 유지된다는 것은 R3b의 우위가 이번에 새로
반영한 실제 조정항(strategy_selection) 앞에서도 무너지지 않는다는
뜻이다** — 이는 §27~§31에서 쌓아온 근거를 한 단계 더 강화한다.
다만:
- **분기1의 marginal t_NW 문제는 이번 검증으로 완화되지 않고 오히려
  심화됐다**(T+20 t_NW 1.31→0.96) — §31.4가 이미 지목한 "분기1·
  분기2 marginal t_NW out-of-sample 재확인" 조건은 여전히, 오히려
  더 강하게 유효하다.
- **T+5 강건성(§30~§31의 조건)은 이번 검증 범위 밖이다** — 이번
  턴은 방향/유의성 재확인에 집중했고 유휴 자본 반영 강건성 재검증은
  하지 않았다(이미 §30에서 별도로 다뤘고, 이번 실측 결과가 그
  결론을 바꿀 근거는 없다 — R3b의 T+5 평균/표본수 자체가 대체로
  비슷한 수준으로 유지됨).
- **§3 전제조건은 이번 턴과 무관하게 여전히 미충족.**

**판정: R3b는 Conditional Go를 유지한다.** 이번 턴은 "point-in-time
파이프라인 반영 shadow 실행" 조건을 부분적으로 소거했다 —
`strategy_selection`을 실제로 반영한 결과 방향성이 무너지지 않아
이 조건의 핵심 우려(실제 파이프라인에 가까워지면 우위가 사라질
수 있다)는 해소됐으나, `portfolio_allocation` gap이 남아 있어
**완전히 해소됐다고는 할 수 없다** — "부분 해소"로 기록한다.
**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
변경하지 않았다** — 이번 턴도 shadow/validation 범위, broker
submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 32.6 다음 단계

1. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인
   — 여전히 최우선.
2. **분기1의 t_NW 약화(0.96)를 우선순위를 높여 재확인** — out-of-
   sample 데이터 축적 또는 분기1 구간의 구조적 원인 재점검.
3. T+5 horizon 강건성 확보(또는 실거래 누적 후 청산 시점 분포
   실측) — §31의 조건 그대로 유효.
4. `portfolio_allocation` gap은 실거래 계좌 상태 없이는 메울 수
   없다 — 실거래 누적 이후 재검증 대상으로 남긴다.

## 33. 분기1 t_NW 약화의 원인 정밀 진단 — 방향성 붕괴 vs 변동성/이상치 문제 (SPPV-2.43, 2026-07-17)

§32.6(다음 단계 2)이 지시한 "분기1 t_NW 약화(0.96)를 우선순위를
높여 재확인"을 실행했다. **이번 턴이 검증한 정확한 질문**: 분기1의
t_NW 약화가 (a) R3b의 방향성 우위 자체 붕괴인지, (b) 표본 수·분산·
특정 하위 일자 편중 문제인지, (c) 분기1만의 구조적(국면 구성) 차이
때문인지를 분기2·분기3과 비교해 확인한다.

스크립트: `scripts/validate_r3b_quarter1_weakness_diagnosis.py`
(read-only, §32의 point-in-time row-collection 함수를 재사용,
신규 실측은 분기1~3의 거래일 단위 분해뿐). 산출: `logs/signal_ic_
r3b_quarter1_weakness_diagnosis_2026-07-17.json`, 실행 로그 `logs/
r3b_quarter1_weakness_diagnosis_run_2026-07-17.log`(신규 KIS 호출
0건 — 기존 3년 캐시로 전량 서빙).

### 33.1 실측 결과 1 — 분기1/2/3 국면 구성 비교

| 분기 | bullish_trend | range_bound | bearish_trend | event_driven_unstable |
|---|---|---|---|---|
| 분기1(2023-10~2024-06) | 40.6% | 46.6% | 10.4% | **2.4%** |
| 분기2(2024-06~2025-02) | 8.6% | 44.2% | **46.6%** | 0.6% |
| 분기3(2025-02~2025-10) | 67.5% | 30.1% | 1.8% | 0.6% |

**분기1은 세 분기 중 가장 "혼합 국면"에 가깝다** — 분기2는
약세장(46.6%)이 지배적이고 분기3은 강세장(67.5%)이 지배적인 반면,
분기1은 강세/횡보/약세가 비교적 고르게 섞여 있고 `event_driven_
unstable`(2.4%, 다른 분기 대비 약 4배) 비중도 가장 높다. `regime_
conditional_signal`은 국면에 따라 정의 자체가 바뀐다(강세·횡보=
`risk_adj_momentum_3m`, 약세=`reversal_1m`) — 분기1은 이 정의
전환이 가장 빈번한 구간이다.

### 33.2 실측 결과 2 — 방향성은 유지, 스왑일 부호 분포도 우호적

| 분기 | R0 T+20 평균 | R3b T+20 평균 | R3b T+20 양수율 | 스왑일(양/음) | 상위10%일 제거 후 잔존 |
|---|---|---|---|---|---|
| 분기1 | 0.753% | **1.815%** | 43.1% | **33양/13음(71.7%)** | **157.8%**(제거 시 개선) |
| 분기2 | 0.590% | 2.717% | 46.2% | 20양/9음(69.0%) | 92.9%(거의 불변) |
| 분기3 | 4.274% | 5.008% | 55.7% | 17양/20음(45.9%) | 104.7%(거의 불변) |

**R3b > R0 방향은 분기1에서도 그대로 유지된다**(1.815% vs
0.753%, 거의 2.4배). **스왑 발생일 46건 중 33건(71.7%)이 양(+)
방향으로, 세 분기 중 가장 양(+) 편중이 강하다** — 방향성 우위가
붕괴된 것이 아니라 오히려 세 분기 중 가장 일관되게 유지된다.
**상위 10% 스왑일(대형 스왑일)을 제거하면 오히려 잔존비율이
157.8%로 증가한다** — 이는 분기1의 대형 스왑일 그룹이 아니라
"나머지 다수의 스왑일"이 진짜 양(+) 우위의 원천이라는 뜻이며,
§24~§26이 분기3에서 발견한 패턴("대형 스왑일이 유일한 양(+)
원천")과 정반대 구조다.

### 33.3 실측 결과 3 — 상위 스왑일 상세: 극단적 이상치 소수가 분산을 키운다

분기1 상위 10개 스왑일의 T+20 교체효과: **-21.88%, -16.11%,
+28.70%, -44.36%**, +9.61%, +5.17%, +1.49%, +8.92%, +10.24%,
+5.95%. **10건 중 3건이 절댓값 16~44%p에 달하는 극단치**(2건은
강한 음(-), 1건은 강한 양(+))이며 나머지 7건은 완만한 양(+)이다.
**이 소수의 극단치가 표준오차를 크게 키워 t_NW를 낮춘다** — 평균
자체(1.815%)는 R0(0.753%)보다 여전히 높지만, 변동성이 커서
"통계적으로 유의하다"고 말하기엔 부족한 상태가 된 것이다.

### 33.4 해석 — 방향성 붕괴가 아니라 변동성/이상치 문제, 국면 혼합이 배경

1. **(a) 방향성 우위 자체는 붕괴하지 않았다.** R3b 평균은 R0보다
   여전히 높고(2.4배), 스왑일의 71.7%가 양(+) 방향이다 — 세 분기
   중 가장 양(+) 편중이 강한 분기다.
2. **(b) 약화의 실체는 표본 수/분산 문제다.** 소수(10건 중 3건)의
   극단적 이상치(±16~44%p)가 표준오차를 부풀려 t_NW를 낮췄다 —
   대형 스왑일을 제거하면 오히려 결과가 개선된다(157.8%)는 것이
   이를 직접 뒷받침한다.
3. **(c) 분기1은 구조적으로 "혼합 국면" 구간이다** — 강세/횡보/
   약세가 고르게 섞이고 event_driven_unstable 비중도 가장 높아,
   `regime_conditional_signal`의 정의 전환이 가장 빈번하게 일어나는
   구간이다. 이는 왜 분기1이 세 분기 중 가장 변동성이 큰 결과를
   보이는지에 대한 구조적 설명이 된다(다만 이를 "완화안"으로
   다루는 것은 이번 턴 범위 밖 — 방어 로직 재검토 금지 지시에
   따름, 순수 원인 설명으로만 기록한다).

### 33.5 판정 — Conditional Go 유지, 분기1은 "잔여 리스크 관리 수준"

**분기1의 t_NW 약화는 R3b 전체를 뒤집는 치명적 결함이 아니라,
제한된 특정 구간(혼합 국면 구간)에서의 변동성/이상치 문제로
좁혀진다.** 방향성 우위·스왑일 부호 분포·대형 스왑일 제거 시
개선 효과 모두 "우위가 실재하나 소수 극단치 때문에 통계적 신뢰도가
낮다"는 그림과 일치한다 — "우위가 없다"거나 "방향이 반전됐다"는
증거는 어디에도 없다.

**판정: R3b는 Conditional Go를 유지한다.** 분기1은 §31~§32가 이미
지목한 "확정 Go 전 잔여 조건"(out-of-sample 재확인)에 그대로
남되, 이번 진단으로 그 성격이 "방향성 의심"에서 **"소수 극단치로
인한 분산 문제, out-of-sample 데이터 축적으로 자연 해소될 가능성이
있는 잔여 리스크"**로 구체화됐다. 이는 Watch로 재하향할 근거가
아니라, 기존 Conditional Go 조건의 정밀도를 높인 것이다. **운영
코드(`entry_score`, `deterministic_trigger_engine.py`)는 변경하지
않았다** — 이번 턴도 shadow/validation 범위, broker submit
미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 33.6 다음 단계

1. §3 전제조건(1차 게이트 TRIGGERED 전환) 충족 여부 사용자 확인
   — 여전히 최우선.
2. out-of-sample 데이터(3년 표본 밖) 축적 시 분기1 유형의 혼합
   국면 구간을 우선 재확인 — 극단치 의존도가 줄어드는지 확인.
3. T+5 horizon 강건성 확보(또는 실거래 누적 후 청산 시점 분포
   실측) — §31의 조건 그대로 유효.
4. `portfolio_allocation` gap은 실거래 계좌 상태 없이는 메울 수
   없다 — 실거래 누적 이후 재검증 대상으로 남긴다.

## 34. SPPV-3 진입 관문 3종 종합 판정 — §3 게이트 재확인 + 분기1/T+5 리스크 종합 (SPPV-2.44, 2026-07-17)

이번 턴은 SPPV-3 진입 전 마지막 관문 3가지(①§3 전제조건 충족 여부,
②분기1 약화의 치명성 여부, ③T+5 취약성의 허용 가능성)를 종합
판정하는 턴이다. **이미 끝난 검증(분기1 구조 진단은 §33, T+5
horizon 적합성은 §31)을 반복하지 않고**, 이번 턴에 유일하게 신규로
필요했던 검증 — **§3 게이트의 현재 실측 상태 재확인**만 수행한 뒤
세 조건을 종합한다.

### 34.1 신규 실측 — §3 게이트(`regime_switch_v1` 1차 게이트) 현재 상태

스크립트: `scripts/monitor_regime_switch_v1_gate.py`(기존 운영
모니터링 스크립트, SPPV-2.13부터 존재 — 신규 스크립트 아님, 이번
턴은 재실행만 함). 판정 로직: 최근 12개월 창에서 시장 공통 국면이
`bearish_trend`로 분류된 거래일이 30일 이상이면 `TRIGGERED`. **[SPPV
-2.45에서 정정] 이 스크립트는 실행 시점과 무관하게 항상 하드코딩된
`logs/regime_switch_v1_gate_monitor_2026-07-14.json`에 저장한다
(`monitor_regime_switch_v1_gate.py:122`, 실행 로그의 "산출 저장:"
줄로도 확인됨) — 파일명의 "2026-07-14"는 최초 작성일(SPPV-2.13)
그대로이며 실행 날짜를 반영하지 않는다.** 이번 턴은 컨테이너 내부
에서 그 하드코딩 경로로 저장된 결과를 호스트로 복사하며 파일명을
`logs/regime_switch_v1_gate_monitor_2026-07-17.json`으로 **수동
변경**했다(스크립트가 그 이름으로 직접 저장한 것이 아니다) — 내용
(as_of=2026-07-17T21:12:43, 국면 분포·판정 동일)은 이번 재실행의
결과가 맞다. 호스트에 기존부터 있던 `logs/regime_switch_v1_gate_
monitor_2026-07-14.json`(as_of=2026-07-15, 이전 턴의 산출물)은
이번 턴에 **덮어써지지 않았다** — 즉 해당 파일명은 이번 재실행을
반영하지 않은 이전 스냅샷이다(다만 결론은 동일하게 NOT_TRIGGERED).
실행 로그: `logs/regime_switch_v1_gate_monitor_run_2026-07-17.log`
(신규 KIS 호출 0건 — 벤치마크 KODEX 200 캐시로 전량 서빙).

**결과: `NOT_TRIGGERED`(불변)** — 기준일 2026-06-16 기준 최근 12개월
창에 `bullish_trend` 239일, `range_bound` 6일뿐이고 `bearish_trend`
는 **0일**이다(문턱 30일에 크게 못 미침). 이는 SPPV-2.13(2026-07-14
직전 기록)과 동일한 상태이며, 이번 재확인으로 **§3 게이트는 여전히
미충족임이 최신 데이터로 재확인됐다.**

**§3의 두 번째 하위 조건(`risk_off_penalty`와 `regime_conditional_
signal`의 하락장 분기 로직 간 중복 해소, §8 ablation 대상)도 별도
분석(중복 penalty ablation)이 필요해 여전히 미충족이다** — 이번
턴은 이 조건에 새로운 실측을 추가하지 않는다(방어 로직 재검토
금지 지시에 따라 범위 밖으로 유지).

### 34.2 종합 — SPPV-3 진입 관문 3종 판정표

| 관문 | 상태 | 근거 |
|---|---|---|
| ① §3 전제조건(게이트+중복 해소) | **미충족** | 게이트 `NOT_TRIGGERED`(bearish_trend 0/30일, 이번 턴 재확인) + `risk_off_penalty` 중복 해소 미착수(§8) |
| ② 분기1 약화 | **제한된 잔여 리스크**(치명적 결함 아님) | §33: 방향성 우위 유지(1.815% vs 0.753%), 스왑일 71.7% 양(+, 최다), 대형 스왑일 제거 시 오히려 개선(157.8%) — 약화는 상위 10건 중 3건의 극단치(±16~44%p)로 인한 분산 문제 |
| ③ T+5 취약성 | **미해결, 무시 불가**(제거 리스크 아님) | §31: SELL/청산이 100% 신호 기반이고 강제된 보유기간이 없어 "T+20 중심이라 T+5 무시 가능"이라는 주장은 코드로 뒷받침되지 않음 |

**세 관문 중 어느 것도 R3b의 방향성 우위 자체를 부정하지 않는다.**
①은 R3b의 품질과 무관한 **시장 상황(하락장 미도래) 의존 관문**이고,
②는 이미 "제한된 구간의 분산 문제"로 좁혀졌으며, ③은 "확실히
무시해도 된다"는 근거가 없을 뿐 "반드시 실패한다"는 근거도 없는
**미해결 상태**다.

### 34.3 판정 — Conditional Go 유지, SPPV-3 진입은 아직 이르다(주된 차단 요인은 §3 게이트)

**R3b는 Conditional Go를 유지한다.** 다만 **SPPV-3(창 교체 본작업/
운영 코드 반영) 진입은 이번 턴 기준으로 아직 이르다** — 그 이유는
R3b 자체의 결함이 아니라:
1. **§3 게이트가 여전히 `NOT_TRIGGERED`다** — 이는 R3b의 성과와
   무관하게 "하락장이 아직 도래하지 않았다"는 시장 조건 문제이며,
   SPPV-2.13부터 이어진 "규칙 A(관찰 유예)"에 따라 인위적으로
   앞당길 수 없다. 이것이 **SPPV-3 진입의 가장 명확하고 유일하게
   "R3b 성과와 무관한" 차단 요인**이다.
2. **분기1 약화는 관리 가능한 잔여 리스크로 확인됐다**(§33) — 이는
   Conditional Go를 흔들 근거가 아니라 out-of-sample 데이터 축적
   시 우선 확인할 항목으로 남긴다.
3. **T+5 취약성은 여전히 미해결이지만 "치명적"이라는 근거도 없다**
   (§31) — 확정 Go 전 반드시 확인해야 할 조건으로 유지한다.

**요약 판정: `Conditional Go 유지 + 분기1/T+5 리스크는 관리 대상으로
확인 + §3 게이트가 SPPV-3 진입의 실질적 유일 차단 요인`.** Watch로
재하향할 근거는 없다 — R3b의 방향성 우위는 8개 창, point-in-time
파이프라인, 총 기대수익 proxy, 분기1 구조 진단까지 일관되게
재확인됐다. **운영 코드(`entry_score`, `deterministic_trigger_
engine.py`)는 변경하지 않았다** — 이번 턴도 shadow/validation
범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 34.4 다음 단계

1. **§3 게이트(`regime_switch_v1` 1차 게이트)는 시장 상황 의존적
   이므로 정기 모니터링 대상으로 유지**한다 — `scripts/monitor_
   regime_switch_v1_gate.py`를 3년 캐시 갱신 시마다 재실행해
   `TRIGGERED` 전환 여부를 계속 확인한다.
2. `risk_off_penalty` 중복 해소 ablation(§8 범위)은 별도 턴에서
   진행 여부를 사용자가 판단한다 — 이번 턴은 착수하지 않는다.
3. T+5 horizon 강건성 확보(또는 실거래 누적 후 청산 시점 분포
   실측) — §31의 조건 그대로 유효.
4. out-of-sample 데이터 축적 시 분기1 유형의 혼합 국면 구간을
   우선 재확인.
5. `portfolio_allocation` gap은 실거래 계좌 상태 없이는 메울 수
   없다 — 실거래 누적 이후 재검증 대상으로 남긴다.

## 35. SPPV-2.44 산출물 파일명/실행 경로 불일치 정정 (SPPV-2.45, 2026-07-17)

§34(SPPV-2.44)가 §3 게이트 재확인 산출물을 `logs/regime_switch_v1_
gate_monitor_2026-07-17.json`로 표기한 것이 실제 스크립트 동작과
불일치했다 — 이번 턴은 그 불일치를 정정한다. **새 실측/새 스크립트
없이** `scripts/monitor_regime_switch_v1_gate.py` 코드와 §34.1의
실행 로그를 다시 확인하는 read-only 재검증만 수행했다(신규 KIS
호출 해당 없음 — 신규 실행 자체가 없었음).

### 35.1 확인된 사실

1. **`monitor_regime_switch_v1_gate.py:122`는 실행 시점과 무관하게
   항상 `logs/regime_switch_v1_gate_monitor_2026-07-14.json`에
   저장하도록 하드코딩돼 있다** — 파일명의 "2026-07-14"는 SPPV-2.13
   최초 작성일 그대로이며, 실행할 때마다 갱신되지 않는다. §34.1의
   실행 로그(`logs/regime_switch_v1_gate_monitor_run_2026-07-17.
   log`)에도 "산출 저장: logs/regime_switch_v1_gate_monitor_2026-
   07-14.json"이라는 문자열이 그대로 남아 있어 이 사실을 직접
   뒷받침한다.
2. **§34에서 "`logs/regime_switch_v1_gate_monitor_2026-07-17.json`
   산출"이라고 쓴 것은, 컨테이너 내부에서 하드코딩 경로로 저장된
   결과를 호스트로 복사하며 파일명을 수동으로 바꾼 것**이지,
   스크립트가 그 이름으로 직접 저장한 것이 아니다 — 별도의
   "복제/재명명 절차"가 실제로 있었던 것은 맞으나(사용자가 제시한
   두 선택지 중 후자), 문서에 그 절차를 명시하지 않아 마치 스크립트
   자체가 날짜별 파일을 생성하는 것처럼 읽힐 수 있었다.
3. **내용은 실제로 이번 재실행 결과가 맞다** — `2026-07-17.json`의
   `as_of=2026-07-17T21:12:43`은 §34.1에서 실제 재실행한 시각과
   일치하며, `2026-07-14.json`(호스트에 기존부터 있던, SPPV-2.13
   계열 파일, `as_of=2026-07-15T07:28:47`)과 내용을 대조한 결과
   `trigger_status`/국면 분포는 완전히 동일하고 `as_of` 타임스탬프
   만 다르다 — 결론에 영향을 주는 불일치는 없다.
4. **호스트에 기존부터 있던 `logs/regime_switch_v1_gate_monitor_
   2026-07-14.json`은 이번 턴(§34)에 의해 덮어써지지 않았다** — 그
   파일은 여전히 이전 턴(SPPV-2.13/2.14 계열, as_of 2026-07-15)의
   스냅샷이다. 이번 재실행의 실제 산출물은 `2026-07-17.json`(수동
   재명명본)이며, 이 두 파일을 같은 것으로 혼동해서는 안 된다.

### 35.2 판정 — 결론 유지, 기록만 정정

**정정 후에도 SPPV-3 진입 관련 결론은 전혀 바뀌지 않는다** —
§34.1의 실측 내용(`NOT_TRIGGERED`, 최근 12개월 bearish_trend
0/30일) 자체는 정확했고, 이번 정정은 오직 "그 결과를 어느 파일명
으로 인용해야 하는가"에 관한 기록 정합성 문제였다. **§34의 판정
("R3b는 Conditional Go 유지, SPPV-3 진입은 §3 게이트 미충족으로
아직 이르다")은 그대로 유지한다.**

향후 이 스크립트를 다시 실행할 때는 산출물을 인용할 때 **"스크립트
자체 출력 경로(`..._2026-07-14.json`, 하드코딩)"와 "호스트 보관용
재명명 사본(`..._<실행일>.json`)"을 명시적으로 구분해 표기**하는
것을 표준 관례로 삼는다. `entry_score`/운영 코드는 이번 턴에도
변경하지 않았다 — 이번 턴은 shadow/validation 기록 정정 범위,
broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 35.3 다음 단계

§34.4의 5개 항목(§3 게이트 정기 재모니터링, `risk_off_penalty`
중복 해소 ablation 착수 여부 사용자 판단, T+5 horizon 강건성 확보,
out-of-sample 데이터 축적 시 혼합 국면 구간 재확인, `portfolio_
allocation` gap 실거래 누적 후 재검증)은 이번 정정과 무관하게 그대로
유효하다 — 이번 턴은 새 과제를 추가하지 않는다.

## 36. R3b 채택 시 `risk_off_penalty` 중복 해소 ablation (SPPV-2.46, 2026-07-17)

§34.4가 남긴 "`risk_off_penalty` 중복 해소 ablation"을 실행했다.
**이번 턴의 범위**: §3 전제조건 중 시장 외생 변수인 §21 게이트는
건드리지 않고(§34에서 이미 NOT_TRIGGERED 재확인, 불변), R3b의
방향성 우위 자체도 재검증하지 않는다 — **오직 "R3b를 실제
entry_score 경로에 반영할 때 `risk_off_penalty`(및 인접 eligibility
축)가 여전히 성과를 깎는 진짜 병목인지, 유지해야 할 정당한 방어
장치인지"만 판정한다.**

### 36.1 코드 기준 사실 확정 — 중복 축은 2개, 서로 다른 단계에 있다

1. **entry_score 축**: `deterministic_trigger_engine._build_entry_
   score:1139-1141` — `market_regime.risk_tone=="risk_off"`이면
   `score -= 0.15`(reason `trigger_risk_off_penalty`). 이것이 문서가
   "risk_off_penalty"라 불러온 축이다.
2. **eligibility 축(별개)**: 같은 파일 `_assess_buy_eligibility:
   421-438` — `risk_tone=="risk_off"` **그리고** `regime_label==
   "bearish_trend"`이면 core 종목은 예외 없이 즉시 차단
   (`eligibility_risk_off_block`/`eligibility_core_risk_off_guard_
   blocked`). entry_score의 -0.15와는 다른 함수, 다른 단계(eligible
   자체를 막음)다.
3. **중복의 정확한 성격**: 두 축 모두 `classify_market_regime()`을
   쓰지만, entry_score/eligibility는 **종목별 개별 스냅샷**으로
   호출하고, `regime_conditional_signal`의 하락장 분기(`reversal_
   1m`)는 **시장 공통(벤치마크) 국면**으로 갈린다 — "같은 판정
   로직, 다른 기준 단위"가 중복 의심의 정체다.

### 36.2 방법론 — A/B/C 3개 시나리오, R3b 후보 위에서 비교

스크립트: `scripts/validate_r3b_risk_off_penalty_duplication_
ablation.py`(read-only, 운영 코드 미수정 — 실제 `_build_entry_
score`/`_assess_buy_eligibility`/`classify_market_regime`를 그대로
호출하되, **함수에 넘기는 `market_regime` 입력만** `dataclasses.
replace(risk_tone="neutral")`로 국소적으로 바꿔 재현한다, 이 세션
전체의 일관된 shadow 관례):

- **A(현행 유지)**: 두 축 모두 실제 로직 그대로.
- **B(entry_score risk_off_penalty만 무력화)**: eligibility는
  그대로, entry_score 계산에만 중립화된 market_regime을 넘겨
  -0.15 조정항이 걸리지 않게 한다.
- **C(eligibility risk_off 축만 완화)**: entry_score는 그대로
  (risk_off_penalty 유지), eligibility 판정에만 중립화된 market_
  regime을 넘겨 `eligibility_risk_off_block`이 걸리지 않게 한다.

candidate(R3b 상위 20% quintile) → eligible → selected(entry_score
>=0.65) → would_buy(top-3) funnel을 2차(3년)/1차(최근 12개월) 두
창에서 계측. 산출: `logs/signal_ic_r3b_risk_off_penalty_
duplication_ablation_2026-07-17.json`, 실행 로그 `logs/r3b_risk_
off_penalty_duplication_ablation_run_2026-07-17.log`(신규 KIS
호출 0건 — 기존 3년 캐시로 전량 서빙).

### 36.3 실측 결과

| 창 | 시나리오 | eligible | selected(rate) | would_buy | T+20 평균 | T+20 t_NW | T+20 양수율 | T+20 MAE | T+20 총proxy |
|---|---|---|---|---|---|---|---|---|---|
| 2차 | A(현행) | 3491 | 1376(39.42%) | 1079 | 5.725% | 3.67 | 52.83% | -8.97% | 6177.7 |
| 2차 | B(entry_score 축 제거) | 3491 | **1505(43.11%)** | **1151** | **6.491%** | 3.87 | 53.34% | -9.52% | **7471.2** |
| 2차 | C(eligibility 축 완화) | 3491 | 1376(39.42%) | 1079 | 5.725% | 3.67 | 52.83% | -8.97% | 6177.7 |
| 1차 | A(현행) | 1621 | 592(36.52%) | 464 | 9.043% | 2.99 | 59.48% | -9.18% | 4196.1 |
| 1차 | B(entry_score 축 제거) | 1621 | **700(43.18%)** | **511** | **9.893%** | 3.13 | 57.93% | -9.72% | **5055.4** |
| 1차 | C(eligibility 축 완화) | 1621 | 592(36.52%) | 464 | 9.043% | 2.99 | 59.48% | -9.18% | 4196.1 |

**핵심 발견 1 — 시나리오 C는 두 창 모두 A와 완전히 동일하다**
(candidate/eligible/selected/would_buy/모든 지표가 소수점까지
일치). 이는 **eligibility 축(`eligibility_risk_off_block`)이
R3b의 candidate pool에서는 단 한 건도 실제로 걸리지 않는다**는
뜻이다 — R3b의 candidate는 그날 `regime_conditional_signal`(모멘텀/
반전 강도) 상위 20%로 뽑히는데, 이 조건 자체가 종목별 `bearish_
trend`(개별 3개월 수익률·추세 급락)와 구조적으로 거의 겹치지 않기
때문이다. **즉 eligibility 축은 R3b 후보군에 대해 "충돌하는 중복"이
아니라 "애초에 적용되지 않는 비활성 축"이다.**

**핵심 발견 2 — 시나리오 B(entry_score의 risk_off_penalty만 제거)
는 두 창 모두 selected/would_buy가 늘고, 동시에 T+20 평균·t_NW·
총 기대수익 proxy가 함께 개선된다.** 총 기대수익 proxy는 T+20
기준 2차 +20.9%(6177.7→7471.2), 1차 +20.5%(4196.1→5055.4) 개선
된다. 다만 **MAE(하방 이탈)도 함께 소폭 악화**된다(2차 -8.97%→
-9.52%p, 1차 -9.18%→-9.72%p, 약 0.5%p) — "공짜 개선"이 아니라
**수익 확대와 하방 노출 확대가 함께 오는 실제 트레이드오프**다.
양수 비율은 혼재(2차 소폭 개선, 1차 소폭 악화)한다.

### 36.4 해석 — 병목인가, 정당한 방어인가

1. **eligibility 축(C)은 R3b 관점에서 "제거해야 할 중복"도 "지켜야
   할 방어"도 아니다 — 애초에 개입하지 않는다.** 이 축을 둘러싼
   "중복 우려"는 R3b의 candidate 구성 방식(모멘텀/반전 상위 20%)
   자체가 이미 개별 약세장 신호와 상호배타적이기 때문에 실전에서는
   발생하지 않는 이론적 우려였다.
2. **entry_score 축(B)은 R3b 후보군에 대해 실제로 성과를 깎는
   병목 쪽에 더 가깝다.** 제거 시 거래량·평균수익률·총 기대수익이
   함께 늘고 t_NW도 유지되거나 개선된다 — "최고 기대수익률" 목표
   관점에서는 유리한 방향이다. 다만 MAE 악화가 함께 나타나 **완전한
   무비용 개선은 아니다** — 손실 허용 범위 내에서의 트레이드오프로
   해석해야 한다(이 시스템의 목표가 "손실 0"이 아니라 "허용 손실
   아래 기대수익 최대화"임을 상기하면, 이 트레이드오프는 목표에
   부합하는 방향이다).
3. **이 결과는 §3 전제조건 ②("의미 중복 해소")에 대한 실측 기반
   1차 답을 제공하지만, "완전 해소"로 선언하기엔 이르다** — 단일
   shadow 계측 1회이며, out-of-sample 재확인과 사용자의 최종 승인
   (엔트리 스코어 조정 로직 변경은 운영 코드 변경 사안이므로)이
   필요하다.

### 36.5 판정 — Conditional Go 유지, §3 조건 ②는 "유력한 방향 확인"으로 구체화

**R3b는 Conditional Go를 유지한다.** 이번 턴은 §3 전제조건 중
② ("risk_off_penalty 중복 해소")에 대해 다음과 같이 구체화한다:
- eligibility 축은 R3b 후보군에서 비활성 — 우려 해소(단, "제거"가
  아니라 "애초에 무관"이라는 형태로 해소).
- entry_score 축은 제거 시 기대수익이 개선되나 MAE 트레이드오프가
  있다 — **"유지해야 할 방어"라기보다 "완화를 검토할 후보"에 가깝다**
  는 실측 근거를 확보했으나, 운영 코드(entry_score) 변경은 이번
  턴 범위 밖이다(사용자 승인 및 §21 게이트와 별개로 진행 여부
  결정 필요).

**SPPV-3(운영 코드 반영) 진입은 여전히 아직 이르다** — 주된 차단
요인은 §34에서 이미 확인한 §21 게이트(NOT_TRIGGERED, 이번 턴
무관)이며, 이번 턴의 발견은 §3 조건 ②를 "미착수"에서 "방향 확인,
사용자 승인 대기"로 진전시킨 것이다. **운영 코드(`entry_score`,
`deterministic_trigger_engine.py`)는 변경하지 않았다** — 이번 턴도
shadow/validation 범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정은 이번 턴과 무관하게 그대로
유지된다.**

### 36.6 다음 단계

1. §21 게이트는 시장 상황 의존적이므로 정기 재모니터링 대상으로
   유지(§34와 동일).
2. entry_score의 risk_off_penalty 완화(제거 또는 축소)를 실제
   운영 코드에 반영할지 여부는 **사용자 승인이 필요한 별도 결정
   사안**이다 — 이번 턴은 실측 근거만 제공했다.
3. T+5 horizon 강건성 확보(§31의 조건 그대로 유효).
4. out-of-sample 데이터 축적 시 혼합 국면 구간(분기1 유형) 재확인.
5. `portfolio_allocation` gap은 실거래 계좌 상태 없이는 메울 수
   없다 — 실거래 누적 이후 재검증 대상으로 남긴다.

## 37. 승인 범위 확정 + `risk_off_penalty`(entry_score 축) 완화안 심층 해석 (SPPV-2.47, 2026-07-17)

사용자가 §36(SPPV-2.46)의 A/B/C 3개 시나리오 중 **"B — entry_score
의 `risk_off_penalty`(-0.15) 축 완화/제거"만 승인**했다. 이번 턴은
그 승인 범위를 문서에 명확히 고정하고, **§36에서 이미 실측된
A(현행)/B(entry_score 축 제거) 데이터를 재사용해**(신규 실행
없음 — 같은 코드·같은 캐시로 결과가 결정론적이므로 재실행은
불필요한 반복이다) T+5/T+20 양쪽·MAE 트레이드오프·SPPV-3 진입
의미를 더 깊게 해석한다.

### 37.1 승인 범위 고정

- **승인**: `entry_score`의 `risk_off_penalty`(-0.15, `_build_
  entry_score:1139-1141`, `market_regime.risk_tone=="risk_off"`
  일 때 적용) 축의 완화/제거 후보로 전진.
- **비승인(이번 턴 범위 제외)**: eligibility 축(`_assess_buy_
  eligibility:421-438`의 `eligibility_risk_off_block`)의 완화 —
  §36에서 이미 이 축은 R3b candidate pool에서 **비활성**(C≡A)임이
  확인돼 애초에 완화할 대상이 아니었다. 이번 턴은 이 결론을
  재검증하지 않고 그대로 승계한다.
- 이 구분에 따라 이번 턴의 비교군은 **A(R3b + 현행 risk_off_
  penalty 유지) vs B(R3b + entry_score risk_off_penalty만 제거,
  eligibility는 A와 동일하게 유지)** 2개로 좁힌다 — §36의 시나리오
  정의와 완전히 동일하며, **신규 재실행 없이 그 산출물(`logs/
  signal_ic_r3b_risk_off_penalty_duplication_ablation_2026-07-
  17.json`)을 그대로 재해석**한다.

### 37.2 실측 재해석 — T+5/T+20 동시 개선, MAE는 상대적으로 작은 대가

| 창 | horizon | 지표 | A | B | 변화율 |
|---|---|---|---|---|---|
| 2차 | T+5 | 총 기대수익 proxy | 2036.4 | 2327.4 | **+14.3%** |
| 2차 | T+5 | 평균 수익률 | 1.887% | 2.022% | +7.1% |
| 2차 | T+5 | t_NW | 3.99 | 4.18 | +4.8% |
| 2차 | T+5 | MAE | -4.847% | -5.226% | 악화 7.8%(상대) |
| 2차 | T+20 | 총 기대수익 proxy | 6177.7 | 7471.2 | **+20.9%** |
| 2차 | T+20 | 평균 수익률 | 5.725% | 6.491% | +13.4% |
| 2차 | T+20 | t_NW | 3.67 | 3.87 | +5.4% |
| 2차 | T+20 | MAE | -8.973% | -9.518% | 악화 6.1%(상대) |
| 1차 | T+5 | 총 기대수익 proxy | 1406.2 | 1587.2 | **+12.9%** |
| 1차 | T+5 | 평균 수익률 | 3.031% | 3.106% | +2.5% |
| 1차 | T+5 | t_NW | 3.32 | 3.46 | +4.2% |
| 1차 | T+5 | MAE | -5.213% | -5.536% | 악화 6.2%(상대) |
| 1차 | T+20 | 총 기대수익 proxy | 4196.1 | 5055.4 | **+20.5%** |
| 1차 | T+20 | 평균 수익률 | 9.043% | 9.893% | +9.4% |
| 1차 | T+20 | t_NW | 2.99 | 3.13 | +4.7% |
| 1차 | T+20 | MAE | -9.183% | -9.720% | 악화 5.9%(상대) |

**질문 1 — risk_off_penalty 제거가 R3b의 우위를 실제 운영 경로에서
더 선명하게 만드는가?** → **그렇다.** 2개 창 모두, would_buy
표본수가 늘고(2차 1079→1151, 1차 464→511), 평균 수익률·t_NW·총
기대수익 proxy가 함께 개선된다 — 표본이 늘면서 우연히 통계가
좋아 보이는 것이 아니라 t_NW(통계적 유의성)도 함께 개선된다는
점이 중요하다.

**질문 2 — 개선이 T+20에만 있는가, T+5도 유지되는가?** → **양쪽
horizon 모두에서 개선이 유지된다.** T+20의 총 기대수익 proxy
개선폭(+20.5~20.9%)이 T+5(+12.9~14.3%)보다는 크지만, T+5도
방향과 크기 모두 유의미하게 개선된다 — "T+20에서만 좋아 보이고
T+5는 여전히 취약하다"는 §30~§31의 우려가 **이 특정 비교(R3b
내에서 risk_off_penalty 유무)에 한해서는 완화**된다. 다만 이는
§30/§31이 지적한 "이 시스템 전반에 강제된 보유기간이 없다"는
더 넓은 구조적 논점 자체를 뒤집는 것은 아니다 — R3b가 risk_off_
penalty를 제거했을 때 T+5에서도 좋아진다는 것과, 실제 청산이
언제 일어날지 모른다는 것은 별개의 질문이다.

**질문 3 — MAE 악화가 기대수익 개선을 정당화하는가?** → **상대적
크기로 보면 정당화 가능한 수준이다.** 총 기대수익 proxy 개선폭
(T+5 12.9~14.3%, T+20 20.5~20.9%)이 MAE 악화폭(5.9~7.8%의
상대적 증가)보다 일관되게 크다 — 손실 심화가 수익 개선을
초과하지 않는다. 다만 이는 "상대적으로 정당화 가능"이라는 것이지
"손실이 늘지 않는다"는 뜻은 아니다 — 이 시스템의 목표가 "손실
최소화"가 아니라 "허용 손실 아래 기대수익 최대화"임을 감안하면
이 트레이드오프는 목표에 부합하는 방향으로 해석되나, 실제 반영
전 리스크 한도(허용 가능한 최대 MAE 수준)에 대한 사용자 확인은
여전히 필요하다.

### 37.3 판정 — Conditional Go 보강, SPPV-3 진입은 여전히 §21 게이트가 유일한 실질 차단 요인

**R3b + entry_score risk_off_penalty 제거 조합은 Conditional Go를
보강한다.** 근거:
- T+5/T+20 양쪽에서 방향·유의성·총 기대수익이 함께 개선(§37.2).
- MAE 악화는 개선폭보다 상대적으로 작다.
- eligibility 축은 비활성이 재확인돼(§36 승계) 추가 검토가 필요
  없다.

**SPPV-3(운영 코드 반영) 진입 관점에서 남은 조건은 사실상 §21
게이트(시장 하락장 도래 여부, §34에서 NOT_TRIGGERED 확인, 이번
턴과 무관)뿐으로 좁혀졌다** — §3 전제조건의 두 축(①게이트, ②
risk_off_penalty 중복) 중 ②는 이번 턴으로 "실측 근거 확보 +
사용자 승인(entry_score 축)"까지 진행됐고, ①만 외생적으로 남아
있다. **다만 이것이 "확정 Go"를 의미하지는 않는다** — entry_score
조정 자체는 아직 운영 코드에 반영되지 않은 shadow 상태이며, 반영
시점은 ①게이트 충족 이후로 §3의 표준 절차(§21 참고)를 따른다.
**[SPPV-2.48에서 정정] "남은 조건은 사실상 게이트 하나"라는 서술은
**§3 전제조건**(게이트+risk_off_penalty 중복) 범위로만 한정하면
정확하지만, **SPPV-3 진입 전체**를 놓고 보면 과장이다 — T+5 구조적
리스크(§31), 혼합 국면 재확인(§33), `portfolio_allocation` gap
(§32) 등 §3와 별개로 이미 문서화된 조건들이 여전히 열려 있다.
정확한 분류는 §38 참고.**

**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
이번 턴에도 변경하지 않았다** — shadow/validation 범위, broker
submit 미호출. **활동성 필터(§14~§16)의 판정과 eligibility 축
관련 결론(§36)은 이번 턴과 무관하게 그대로 유지된다.**

### 37.4 다음 단계

1. §21 게이트는 시장 상황 의존적이므로 정기 재모니터링 대상으로
   유지(§34와 동일, 이번 턴 갱신 없음).
2. §21 게이트가 `TRIGGERED`(또는 사용자가 별도 승인)로 전환되면,
   `entry_score`의 risk_off_penalty 완화를 **실제 운영 코드에
   반영하는 절차**(코드 변경 PR, 컴플라이언스/리스크 검토 등)를
   별도 턴에서 설계한다 — 이번 턴은 여전히 shadow 범위다.
3. T+5 horizon의 더 넓은 구조적 논점(강제된 보유기간 부재, §31)은
   이번 턴으로 완전히 해소되지 않았다 — 실거래 누적 후 청산 시점
   분포 실측이 여전히 유효한 다음 과제다.
4. out-of-sample 데이터 축적 시 혼합 국면 구간(분기1 유형) 재확인.
5. `portfolio_allocation` gap은 실거래 계좌 상태 없이는 메울 수
   없다 — 실거래 누적 이후 재검증 대상으로 남긴다.

## 38. SPPV-2.47 "게이트 하나만 남았다" 표현 정밀화 — 주된 차단 요인 vs 보조 잔여 조건 분리 (SPPV-2.48, 2026-07-18)

§37(SPPV-2.47)이 "SPPV-3 진입 관점에서 남은 조건은 사실상 §21
게이트 하나로 좁혀졌다"고 쓴 것은 **§3 전제조건(게이트+risk_off_
penalty 중복) 범위로 한정하면 정확하지만, "SPPV-3 진입" 전체를
가리키는 문장으로는 과장이다.** 이번 턴은 **새 실측·새 설계
제안 없이** 기존 산출물·기존 문서(§30~§33)만 재해석해 이 표현을
정밀화하고, 잔여 조건을 3개 층위로 재분류한다.

### 38.1 무엇이 과장이었나

§37은 "§3 전제조건 ②(risk_off_penalty 중복)가 사용자 승인까지
진행됐고, ①(게이트)만 외생적으로 남았다"는 사실 자체는 정확하게
서술했다. 문제는 이 문장이 배치된 문맥과 반복된 요약(문서 상단
배너, 체크리스트 항목, 우선순위 문서의 "다음 착수" 항목 등)에서
**"§3 전제조건"과 "SPPV-3 진입 조건" 두 개념이 사실상 동일한
것처럼 읽히도록 쓰였다는 점**이다. 그러나 이 세션 전체의 기존
기록만 봐도 §3와 별개로 이미 다음이 문서화돼 있었다:

- **§31(SPPV-2.41)**: 이 시스템에는 강제된 보유기간이 없어 "T+20
  중심이라 T+5를 무시해도 된다"는 주장은 코드로 뒷받침되지 않는다
  — T+5 horizon 강건성 확보(또는 실거래 청산 시점 분포 실측)를
  **확정 Go의 필수조건**으로 명시적으로 격상한 바 있다.
- **§33(SPPV-2.43)**: 분기1 t_NW 약화는 혼합 국면 구간의 변동성/
  이상치 문제로 좁혀졌으나, "out-of-sample 데이터 축적 시 혼합
  국면 구간 우선 재확인"이 다음 단계로 명시돼 있다.
- **§32(SPPV-2.40)**: `portfolio_allocation` gap(계좌 잔고/포지션
  기반 조정, 최대 ±0.20)은 실거래 계좌 상태 없이는 shadow로
  재현 불가능하다고 반복적으로 명시돼왔다.

이 세 가지는 §3 전제조건(§21/§8 범위)의 하위 항목이 아니라
**독립적으로 확정 Go의 조건으로 명시된 별도 항목**이다. §37이
이들을 "다음 단계" 목록에는 정확히 남겨두면서도, 요약 문장에서는
"게이트 하나"라고 써서 이 별도 항목들이 이미 해소된 것처럼
보이는 모순이 생겼다 — **이번 턴이 바로잡는 지점이다.**

### 38.2 잔여 조건 재분류 — 3개 층위

**① 주된 차단 요인(지금 당장 SPPV-3 착수 자체를 막는 것)**
- **§21 게이트(`regime_switch_v1` 1차 게이트) — `NOT_TRIGGERED`**
  (§34에서 최신 재확인, 최근 12개월 bearish_trend 0/30일). 시장
  하락장 도래라는 순수 외생 변수이며, 사용자 승인이나 추가 분석
  으로 앞당길 수 없다. **이것이 유일하게 "지금 당장 SPPV-3 착수
  자체를 원천 차단"하는 조건이다** — §3의 "규칙 A(관찰 유예)"가
  이 게이트가 트리거되기 전까지는 운영 코드 반영을 시작하지 않는
  것을 표준 절차로 못박아뒀기 때문이다.

**② 보조 잔여 조건(즉시 차단은 아니나, 게이트가 트리거된 뒤
확정 Go로 가기 전 반드시 마무리해야 하는 것)**
- entry_score의 `risk_off_penalty` 완화를 **실제 운영 코드에
  반영하는 절차**(코드 변경 PR, 컴플라이언스/리스크 재검토) —
  사용자 승인은 됐으나(§37) 코드 반영 자체는 미착수.
- **T+5 horizon 구조적 리스크**(§31) — §37이 보여준 T+5 개선은
  "R3b 내부에서 risk_off_penalty 유무를 비교했을 때"의 개선이지,
  §31이 지적한 "이 시스템에 강제된 보유기간이 없다"는 더 근본적인
  구조적 논점 자체를 해소한 것이 아니다. 이 조건은 여전히 열려
  있다.
- **혼합 국면(분기1 유형) 재확인**(§33) — out-of-sample 데이터가
  축적되기 전까지는 재확인이 불가능하다는 성격상 "게이트 충족과
  무관하게 별도로 남는" 조건이다.

**③ 실거래/실시간 누적 없이는 근본적으로 풀 수 없는 조건**
- **`portfolio_allocation` gap**(§32) — 계좌 잔고·포지션 상태가
  필요해 shadow로는 원천적으로 재현 불가능하다. 실거래가 시작된
  뒤에야 검증할 수 있다.
- T+5 horizon의 "실제 청산 시점 분포"(§31) — 마찬가지로 실거래
  이력이 쌓여야 경험적으로 답할 수 있다.

### 38.3 "게이트 하나만 남았다"가 §3와 SPPV-3 전체를 혼동한 것임을 확정

**정정된 서술**: "§3 전제조건(게이트+risk_off_penalty 중복)만
놓고 보면 남은 것은 게이트 하나다"는 정확하다. 그러나 **"SPPV-3
진입"에는 §3 통과 이후에도 ②·③ 층위의 조건들이 이어진다** — 즉
"게이트가 트리거되는 순간 SPPV-3에 착수할 수 있다"는 뜻이 아니라,
"게이트가 트리거돼야 §3 관문을 넘고, 그 다음에도 ②(T+5·분기1)와
③(portfolio_allocation·실제 청산 분포)이 남는다"는 것이 정확한
그림이다.

### 38.4 판정 — Conditional Go 유지(방향 후퇴 아님), 판정 문구만 정밀화

**이번 정정은 R3b의 방향성이나 Conditional Go 판정 자체를 바꾸지
않는다** — §27~§37에서 쌓아온 8개 창 방향 일관성, point-in-time
파이프라인 반영, 총 기대수익 proxy 개선, risk_off_penalty 완화
효과는 모두 실측된 사실 그대로 유효하다. **바뀌는 것은 오직
"SPPV-3 진입까지 남은 조건이 몇 개인가"에 대한 문구뿐이다** —
"게이트 하나"가 아니라 **"주된 차단 요인 1개(§21 게이트) + 보조
잔여 조건 3개(entry_score 코드 반영 절차, T+5 구조적 리스크,
혼합 국면 재확인) + 실거래 이후에만 풀리는 조건 2개(portfolio_
allocation gap, 실제 청산 시점 분포)"가 정확한 그림이다.

**R3b는 Conditional Go를 유지한다.** "Go 아님"과 "방향성이
틀렸다"를 혼동하지 않는다 — 이번 턴은 판정 강도를 낮추는 턴이
아니라, 판정에 딸린 "남은 조건" 서술의 정밀도를 회복하는 턴이다.
**운영 코드(`entry_score`, `deterministic_trigger_engine.py`)는
변경하지 않았다** — 이번 턴은 read-only 문서 재해석 범위, broker
submit 미호출, 신규 실측 없음.

**활동성 필터(§14~§16)의 판정과 eligibility 축 관련 결론(§36)은
이번 턴과 무관하게 그대로 유지된다.**

### 38.5 SPPV-3 착수 프롬프트로 넘어갈 수 있는 조건 (명확화)

다음 중 **①이 충족되고, ②의 항목들이 별도 턴에서 마무리된
뒤에야** SPPV-3(운영 코드 반영) 착수를 다음 턴의 정식 목표로
프롬프트할 수 있다:
1. §21 게이트가 `TRIGGERED`(또는 사용자가 예외적으로 별도 승인)로
   전환.
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   완료(리스크/컴플라이언스 검토 포함).
3. T+5 horizon 구조적 리스크에 대한 최소한의 추가 확인(강제된
   보유기간을 도입할지, 아니면 이 리스크를 받아들이고 진행할지
   사용자 결정).
4. (선택, 착수 자체를 막지는 않음) 혼합 국면 재확인, `portfolio_
   allocation` gap, 실제 청산 시점 분포는 실거래 시작 이후에도
   계속 추적 가능한 항목으로 별도 관리한다.

**[SPPV-2.58에서 추가 — §21 gate 환경별 적용 범위 정밀화]** 위
조건은 **실운영(Production) 자본이 실제로 움직이는 SPPV-3** 기준의
잠금 규칙이다. 따라서 §21 게이트의 정확한 목적은 **실운영 승격 전
잠금**이지, 현재의 **Paper Probe / shadow 관측 단계**에서 실측
데이터 수집 자체를 영구 보류하라는 뜻이 아니다. 앞으로의 canonical
해석은 다음과 같다.

- **production**: §21 게이트를 엄격 유지한다. `TRIGGERED`(또는
  사용자 별도 승인) 전에는 R3b를 실제 주문 경로에 반영하지 않는다.
- **paper / shadow**: 환경 인지형 우회(config 스위치) 구현 시,
  §21 게이트는 **실운영 승격 잠금선**으로만 해석한다. 즉 compliance /
  VaR / broker submit 경계는 유지하되, R3b 진입 신호의 shadow·paper
  유출과 데이터 수집은 별도 허용될 수 있다.

이번 정정은 **문구와 적용 범위의 수정**이지, 현재 코드가 이미 그렇게
구현돼 있다는 뜻은 아니다. 코드상 환경별 우회는 별도 구현 턴에서
반영해야 한다.

### 38.6 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음, 여전히 최우선 관찰
   대상).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   여부 사용자 확인 — 게이트 충족 전에 미리 설계해둘지 여부도
   사용자 판단 사항.
3. T+5 horizon 구조적 리스크를 받아들이고 진행할지, 추가 완화를
   모색할지 사용자 결정.
4. out-of-sample 데이터 축적 시 혼합 국면 구간(분기1 유형) 재확인
   — 변경 없음.
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

**[SPPV-2.58에서 추가]** 따라서 `§21 게이트 정기 재모니터링`은
**production 잠금 해제 조건**을 계속 추적하는 작업으로 남기되,
paper/shadow 실측 누적 자체를 멈추는 해석으로 확대하지 않는다.
paper/shadow 쪽은 환경별 gate 우회 코드가 마련되면 그 즉시 별도
실측 트랙으로 전진 가능하다.

## 39. 혼합 국면(분기1 유형) 재확인 — 분기4 대조 계측 (SPPV-2.49, 2026-07-18)

§38.6(다음 단계 4)이 남긴 "혼합 국면 재확인"을 실행했다. **이번
턴에 이 항목을 고른 이유**: §38이 정리한 3개 보조 잔여 조건 중
T+5 구조적 리스크는 실거래 청산 이력이 있어야 답할 수 있어
"실거래 누적 없이는 못 푸는 조건"에 더 가깝고, entry_score 코드
반영 절차는 §21 게이트 충족 이후 별도 트랙이라 지금 전진시켜도
실익이 작다. **혼합 국면 재확인만 유일하게 "진짜 미래 데이터"가
아니라 이미 3년 캐시 안에 있지만 아직 들여다보지 않은 분기4로
지금 당장 검증 가능했다** — §33(SPPV-2.43)은 분기1만 혼합 국면
임을 확인했을 뿐, 분기4(2025-10~2026-06)의 국면 구성은 이번
세션에서 아직 계측한 적이 없었다.

### 39.1 방법론

스크립트: `scripts/validate_r3b_mixed_regime_quarter4_check.py`
(read-only, 운영 코드 미수정). **승인된 조합(R3b alpha + entry_
score risk_off_penalty 제거, §46/§47의 B 시나리오, eligibility
축은 불변)** 그대로를 대상으로, 분기1(재계측, B 시나리오 기준
비교 기준선 확보)과 분기4(신규 계측)의 시장 공통 국면 분포·종목별
개별 국면 분포·candidate→eligible→selected→would_buy funnel을
계측했다. 산출: `logs/signal_ic_r3b_mixed_regime_quarter4_check_
2026-07-18.json`, 실행 로그 `logs/r3b_mixed_regime_quarter4_check_
run_2026-07-18.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량
서빙).

### 39.2 실측 결과

| 항목 | 분기1 | 분기4 |
|---|---|---|
| 시장 공통 국면 분포 | bearish 8.6%/range 48.1%/event 2.4%/bullish 40.8% | **bullish 98.2%/range 1.8%**(사실상 단일 국면) |
| would_buy 표본 | 273 | 345 |
| T+5 평균 | 0.585% | **4.323%** |
| T+5 t_NW | 0.87 | **3.48** |
| T+5 양수율 | 49.5% | **59.7%** |
| T+20 평균 | 2.424% | **12.858%** |
| T+20 t_NW | **1.27**(marginal) | **3.00**(유의) |
| T+20 양수율 | 46.2% | **60.3%** |
| T+20 MAE | -9.31% | -10.55% |
| T+20 총 기대수익 proxy | 661.7 | **4436.0** |

**분기4는 시장 공통 국면이 사실상 순수 단일(bullish_trend 98.2%)
이며, 분기1과 정반대로 "혼합되지 않은" 구간이다.** 이 대조 구간
에서 B 시나리오는 T+5/T+20 양쪽 모두 강한 평균·높은 t_NW(3.0
이상)·높은 양수율(60% 안팎)을 보인다 — 분기1의 marginal한 결과
(t_NW 1.27, 양수율 46.2%)와 뚜렷이 대비된다.

### 39.3 해석 — 가설이 표본 1개의 우연이 아니라 대조쌍으로 확인됨

§33이 분기1(혼합) 하나만으로 잠정 제기했던 "혼합 국면 → 변동성
확대/약한 t_NW" 가설이, 이번 턴으로 **정반대 성격의 분기4(단일
국면 지배)와의 대조를 통해 하나의 데이터 포인트가 아니라 일관된
패턴으로 확인됐다** — 국면이 섞이지 않고 한 방향으로 뚜렷할 때는
R3b(+risk_off_penalty 제거)가 강하고 일관되게 작동하고, 국면이
섞일 때는 방향은 유지되나 통계적 신뢰도가 떨어진다.

**이것이 "혼합 국면 재확인" 조건을 해소한다는 뜻은 아니다** —
오히려 그 반대로, 이 패턴이 우연이 아니라 실제 구조적 특성일
가능성을 높였다. 다만 "미확인 가설"에서 "확인된, 성격이 파악된
패턴"으로 바뀐 것 자체가 SPPV-3 준비 관점에서 유의미한 전진이다
— 향후 혼합 국면 구간이 다시 오더라도 "왜 이 구간에서 유의성이
낮아지는지"를 이미 알고 대응할 수 있기 때문이다.

### 39.4 판정 — Conditional Go 유지, "혼합 국면 재확인" 조건은 "미확인"에서 "확인·추적 대상"으로 전진

**R3b는 Conditional Go를 유지한다.** §38이 정리한 보조 잔여 조건
중 "혼합 국면(분기1 유형) 재확인"은 이번 턴으로 **"unconfirmed
단일 사례" → "2개 대조 분기로 확인된 패턴"**으로 전진했다 — 다만
이 패턴 자체가 사라지거나 완화된 것은 아니므로, "조건 해소"가
아니라 "조건의 성격이 명확해짐"으로 기록한다. **운영 코드(`entry_
score`, `deterministic_trigger_engine.py`)는 변경하지 않았다** —
이번 턴도 shadow/validation 범위, broker submit 미호출.

**활동성 필터(§14~§16)의 판정과 §21 게이트 상태(§34)는 이번 턴과
무관하게 그대로 유지된다.**

### 39.5 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. T+5 horizon 구조적 리스크를 받아들이고 진행할지 사용자 결정
   (변경 없음).
4. **혼합 국면 패턴이 확인됨에 따라, "국면 혼합도"를 사전에 감지해
   해당 구간에서는 신뢰 구간을 넓게 잡거나 포지션 크기를 조정하는
   등의 운영상 대응이 필요한지는 별도 설계 검토 대상**(이번 턴은
   설계 제안을 하지 않음 — 방어 로직 재검토 금지 지시에 따름).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 40. "혼합 국면 약세" 가설 직접 분해 — 거래일 단위 혼합도 3분위 버킷화 (SPPV-2.50, 2026-07-18)

§39.5(다음 단계 4)가 남긴 "국면 혼합도" 검토를 실행했다. **이번
턴이 고른 분해 축**: 분기1 vs 분기4 대조(§39, N=2)를 반복하지
않고, **거래일 단위로 "최근 60거래일(약 1분기) 창의 시장 공통
국면 혼합도"를 직접 수치화**해 3년 전체 표본을 분기 경계와
무관하게 혼합도 상/중/하 3분위로 버킷화했다. 이는 "분기1이라서
나쁘다"가 아니라 "혼합도가 높은 날일수록 나쁜가"를 연속 변수로
직접 검증하는 가장 직접적인 방법이며, 특정 분기 하나에 결과가
묶여 있는지 아니면 혼합도 자체와 상관관계가 있는지를 구분해낸다.

### 40.1 방법론

**혼합도 정의**: 거래일 d마다 최근 60거래일(d 포함) 구간의 시장
공통 국면 라벨 분포에서 `mixed_score = 1 - (최빈 라벨 비중)`을
계산한다(0=완전 단일 국면, 1에 가까울수록 여러 국면이 고르게
섞임). 전체 634거래일의 혼합도 분포를 3분위로 나눠 저혼합/중혼합/
고혼합 버킷을 구성했다(3분위 경계: 0.1500, 0.3833).

**대상 candidate**: §39와 동일하게 승인된 조합(R3b alpha +
entry_score risk_off_penalty 제거, eligibility 축 불변)을 그대로
사용했다. 스크립트: `scripts/validate_r3b_regime_mix_intensity_
decomposition.py`(read-only, 운영 코드 미수정). 산출: `logs/
signal_ic_r3b_regime_mix_intensity_decomposition_2026-07-18.
json`, 실행 로그 `logs/r3b_regime_mix_intensity_decomposition_
run_2026-07-18.log`(신규 KIS 호출 0건 — 기존 3년 캐시로 전량
서빙).

### 40.2 실측 결과 — 3분위 단조 감소

| 버킷 | 평균 혼합도 | 거래일수 | would_buy | T+20 평균 | T+20 t_NW | T+20 양수율 | T+20 총proxy |
|---|---|---|---|---|---|---|---|
| 저혼합(단일 국면 지배) | 0.037 | 217 | 441 | **12.247%** | **3.64** | **63.3%** | **5400.8** |
| 중혼합 | 0.305 | 215 | 345 | 5.443% | 2.51 | 56.8% | 1877.7 |
| 고혼합 | 0.453 | 202 | 357 | **0.606%** | **0.37** | **38.7%** | **216.2** |

(T+5도 동일한 단조 패턴: 저혼합 t=3.89/mean=3.86%, 중혼합 t=2.33/
mean=1.71%, 고혼합 t=0.34/mean=0.19%.)

**혼합도가 높아질수록 T+5/T+20 평균 수익률·t_NW·양수율·총 기대수익
proxy가 예외 없이 단조 감소한다.** 특히 **고혼합 버킷의 T+20
양수율은 38.7%로 50%를 밑돌고, t_NW=0.37로 통계적으로 0과 구별
되지 않는다** — 저혼합 버킷(t=3.64, 양수율 63.3%)과는 질적으로
다른 상태다.

### 40.3 해석 — "지지 증거 추가"에서 "구조적 패턴"으로 격상, 그러나 방향성 붕괴는 아니다

**질문 1: 혼합 국면 약세가 진짜 구조적 패턴인가?** → **[SPPV-2.51
에서 정정] "그렇다, 구조적 패턴으로 격상됐다"는 과장이다 — 정확히는
"강한 구조적 정합 증거로 격상됐다"가 맞다.** §39는 분기1·분기4
2개 사례의 대조였다(N=2, 분기 경계에 묶인 결과일 가능성이 남아
있었다). 이번 턴은 **634거래일 전체를 대상으로 분기 경계와 무관한
연속 변수(혼합도)로 3분위 단조 감소**를 확인했다 — 이는 "우연히
분기1이 나빴다"는 설명으로는 재현되지 않는 패턴이다. **"지지 증거
추가" 단계를 넘어선 것은 맞다.** 다만 아래 두 가지 이유로 "확정된
구조적 패턴"이라고 부르는 것은 과장이다: ① 이 3분위 분해는 R3b·
entry_score risk_off_penalty 조합을 이미 확정한 것과 **동일한
3년 캐시(2023-07~2026-06)**에서 산출됐다 — out-of-sample(향후
새 구간) 검증이 아니라 in-sample 재확인이다. ② mixed_score가
거래일마다 **60거래일 trailing window**로 계산되므로, 인접한
거래일들은 window가 대부분 겹쳐 mixed_score가 서로 강하게 자기
상관돼 있다 — 634거래일은 634개의 독립 관측치가 아니라 사실상
소수의 "국면 전환 에피소드"가 반복 카운트된 것에 가깝다(예:
저혼합 버킷 217일도 실제로는 몇 개의 연속된 저혼합 구간이 이어진
것일 가능성이 높다). 따라서 정확한 표현은 **"강한 구조적 정합
증거(strong structural coherence evidence)로 격상됐다"**이며,
"out-of-sample로 확정된 구조적 패턴"이라고 부를 단계는 아직 아니다.

**질문 2: 특정 분기/날짜에 묶인 현상인가?** → **아니다.** 저혼합/
중혼합/고혼합 버킷 각각이 217/215/202 거래일로 거의 균등하게
분포하고(3년 전체에 걸쳐 골고루 나타남), 각 버킷의 국면 분포를
봐도 특정 분기 하나가 한 버킷에 몰려 있지 않다(예: 고혼합 버킷도
range_bound 44%/bullish 41%/bearish 15%로 여러 분기에서 나타날
수 있는 혼합 패턴). 분기 단위가 아니라 혼합도라는 연속 변수
자체가 성과와 연동된다.

**질문 3: 이 리스크가 SPPV-3 진입을 실제로 늦춰야 할 정도인가?**
→ **아니다.** 저혼합·중혼합 버킷(전체의 약 2/3)에서는 R3b(+
entry_score risk_off_penalty 제거)가 여전히 강하고 유의미하게
작동한다(t=3.64, t=2.51 모두 통상 유의 수준 이상). 고혼합
버킷에서도 **평균은 여전히 양(+)**이며(0.606%), 방향이 반전되거나
음(-)으로 뒤집힌 것은 아니다 — 다만 그 구간에서는 통계적 신뢰도가
사실상 사라진다는 것이 이번에 확정됐다. 이는 §21 게이트(주된
차단 요인)와는 별개의 문제이며, "국면 혼합도가 높은 시기에는
이 창 교체의 실효성이 줄어들 수 있다"는 **운영상 인지해야 할
구조적 특성**으로 자리잡는다 — SPPV-3 착수 자체를 추가로 늦출
근거는 아니지만, 착수 이후에도 계속 추적해야 할 항목이다.

### 40.4 판정 — Conditional Go 유지, 혼합 국면 리스크는 "구조적 패턴"으로 재분류(SPPV-3 착수 차단 사유는 아님)

**R3b는 Conditional Go를 유지한다.** §38이 분류한 보조 잔여
조건 중 "혼합 국면 재확인"은 이번 턴으로 **"확인·추적 대상
패턴"에서 한 단계 더 나아가 [SPPV-2.51에서 정정] "634거래일
규모로 확정된 구조적 패턴"이 된 것이 아니라 "634거래일 규모의
강한 구조적 정합 증거로 격상"된 것**이다 — 같은 in-sample 캐시
재확인이라는 한계와 60일 trailing window의 자기상관 때문에
"out-of-sample 확정"으로 부르기는 이르다(§40.6 참고). 다만 이는
R3b의 방향성 우위 자체를 부정하지 않는다(저혼합·중혼합 2/3 구간에서
여전히 강함, 고혼합 구간도 평균은 양(+) 유지). **이 발견은 SPPV-3
착수를 추가로 차단하는 사유가 아니라, 착수 이후에도 국면 혼합도를
계속 모니터링해야 한다는 운영상 시사점으로 기록한다.** **운영
코드(`entry_score`, `deterministic_trigger_engine.py`)는 변경
하지 않았다** — 이번 턴도 shadow/validation 범위, broker submit
미호출.

**§21 게이트 상태(§34)와 활동성 필터(§14~§16)의 판정은 이번
턴과 무관하게 그대로 유지된다.**

**[SPPV-2.51에서 추가 — §21 게이트 표현 정밀화]** 위 문단 및
§38/§39/§40 여러 곳에서 쓰인 "주된 차단 요인은 §21 게이트 하나뿐"
이라는 표현은 **"§21 게이트가 SPPV-3 착수 자체를 막는 유일하고
외생적인 주된 차단 요인"이라는 뜻이지, "§21 게이트만 충족되면
SPPV-3 진입에 남은 조건이 전혀 없다"는 뜻이 아니다.** §38에서
이미 확립한 3단 분류(①주된 차단 요인=§21 게이트 ②보조 잔여
조건=entry_score 코드 반영 절차·T+5 구조적 리스크·혼합도 모니터링
③실거래 누적 필요 조건=portfolio_allocation gap·실제 청산 분포)는
이번 턴에도 그대로 유효하다 — §21 게이트는 "①의 유일한 항목"일
뿐, "SPPV-3 진입 전체의 유일한 남은 조건"은 아니다. 즉 §21 게이트
TRIGGERED는 SPPV-3 **착수 검토를 시작할 수 있는** 필요조건이지,
착수 검토가 즉시 확정 Go로 이어진다는 충분조건은 아니다(②의
항목들은 착수 검토 단계에서 별도로 사용자 결정이 필요하다).

### 40.5 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음, 여전히 주된 차단 요인).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. T+5 horizon 구조적 리스크를 받아들이고 진행할지 사용자 결정
   (변경 없음).
4. **[SPPV-2.51에서 정정] 국면 혼합도가 "확정된 구조적 패턴"이
   아니라 "강한 구조적 정합 증거"로 격상됨에 따라, 이를 실거래
   반영 이후 모니터링 지표로 삼을지(예: 혼합도가 높은 구간에서는
   신뢰 구간을 넓게 보거나 별도로 추적) 여부는 별도 설계 검토
   대상**(이번 턴도 설계 제안은 하지 않음).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

### 40.6 SPPV-2.51 — SPPV-2.50 결론 문구 정밀화(과장 없이 고정)

**목적**: SPPV-2.50이 사용한 두 문구 — "구조적 패턴으로 격상",
"주된 차단 요인은 여전히 §21 게이트 하나뿐" — 을 신규 실측 없이
기존 산출물만 근거로 재점검한다. `R3b` 방향성·`Conditional Go`는
그대로 유지하며, 아래는 오직 **서술 정밀도**만 다룬다.

**정리 1 — "구조적 패턴으로 격상"은 과장이다, 정확한 표현은
"강한 구조적 정합 증거로 격상"이다.**
- **지금 데이터로 확실히 말할 수 있는 것**: (a) 634거래일 전체에서
  혼합도 3분위별 T+5/T+20 평균수익률·t_NW·양수율·총 기대수익
  proxy가 예외 없이 단조 감소한다. (b) 이 단조성은 217/215/202일이
  3년 전체에 걸쳐 고르게 분포한 상태에서 나타나 특정 분기 하나에
  묶인 우연이 아니다. (c) 이는 §39(N=2 분기 대조)보다 훨씬 강한
  근거이며 "지지 증거 추가" 단계는 명백히 넘어섰다.
- **아직 말하면 과장인 것**: (a) 이 재확인은 R3b/entry_score
  조합을 이미 선택·확정하는 데 쓰인 것과 **동일한 2023-07~2026-06
  3년 캐시**에서 수행됐다 — 신규·미래 구간(out-of-sample)에서의
  재현은 아직 검증되지 않았다. (b) mixed_score가 60거래일 trailing
  window로 계산되므로 인접 거래일들의 버킷 소속은 서로 강하게
  자기상관돼 있다 — "634개의 독립 관측"이 아니라 "소수의 국면
  전환 에피소드가 반복 표집된 것"에 가까워 유효 표본 수는 634보다
  훨씬 작을 수 있다. 이 두 가지 때문에 "구조적 패턴으로 확정됐다"
  (as if out-of-sample로 검증된 사실)라고 부르는 것은 증거보다
  센 표현이다. **정확한 표현: "강한 구조적 정합 증거(same-sample
  dose-response consistency)로 격상됐다."**

**정리 2 — `§21` 게이트는 "주된 차단 요인"이지 "유일한 남은
조건"은 아니다.**
- **지금 데이터로 확실히 말할 수 있는 것**: `§21` 게이트는 SPPV-3
  **착수 검토 자체를 시작할 수 있는지**를 결정하는 유일한 순수
  외생적 조건이며(시장이 실제로 하락국면에 진입해야 함, 어떤 분석·
  승인으로도 앞당길 수 없음), 이 성격은 이번 턴에도 불변이다.
- **아직 말하면 과장인 것**: "§21 게이트 하나만 남았다"를 "§21
  게이트가 충족되면 SPPV-3 진입에 더 이상 검토할 것이 없다"는
  뜻으로 읽는 것 — 이는 §38(SPPV-2.48)에서 이미 한 차례 바로잡은
  과장과 동일한 패턴이다. §38의 3단 분류(①주된 차단 요인=§21
  게이트 ②보조 잔여 조건=entry_score 코드 반영 절차·T+5 구조적
  리스크·혼합도 모니터링(이번 턴 §40.3에서 재확인) ③실거래 누적
  필요 조건=portfolio_allocation gap·실제 청산 분포)는 이번 턴도
  그대로 유효하다. **정확한 표현: "§21 게이트는 SPPV-3 착수
  검토의 유일한 주된(외생적) 차단 요인이다" — "SPPV-3 진입 전체의
  유일한 남은 조건"이 아니다.**

**판정에 대한 영향**: 위 두 정정은 모두 **표현의 정밀도** 문제이며,
`R3b` 방향성이나 `Conditional Go` 판정을 바꾸지 않는다. 증거를
약화시키는 정정도 아니다(단조 감소 자체는 그대로 확인된 사실) —
다만 "in-sample 재확인"과 "out-of-sample 확정"을 구분하고,
"주된 차단 요인"과 "유일한 남은 조건"을 구분해 향후 SPPV-3 착수
검토 시 과소·과대평가 양쪽을 모두 피한다. 신규 실행 없음(§40의
기존 산출물만 재해석), 신규 KIS 호출 0건, 운영 코드 변경 없음,
broker submit 미호출.

## 41. T+5 horizon 구조적 리스크 추가 정량화 — 실제 exit_score 기반 signal-driven 청산 타이밍 shadow 시뮬레이션 (SPPV-2.52, 2026-07-18)

### 41.1 왜 이 항목을 골랐는가

§38(SPPV-2.48)이 정리한 보조 잔여 조건 3개(entry_score 코드 반영
절차 / T+5 구조적 리스크 / 혼합도 모니터링) 중, 지금 당장 신규
설계 없이 **기존 3년 캐시만으로 직접 실측 가능한** 것은 "T+5
구조적 리스크"뿐이다. entry_score 코드 반영 절차는 실제 운영 코드
변경 PR과 리스크·컴플라이언스 검토가 전제라 이번 턴 범위를 넘고,
혼합도 모니터링은 "어떻게 운영에 반영할지"의 설계 문제라 신규
계량치보다 설계 검토가 먼저 필요하다.

T+5 리스크는 §31/§41(이전 세션 표기, 이 문서의 §29~§30 부근)에서
"강제된 보유기간이 없다"는 사실이 확인된 이후 줄곧 "고정 시계
(T+5/T+20)만으로 성과를 재는 것이 실제 운영과 맞는가"라는 의문으로
남아 있었다. `_build_exit_score`(`deterministic_trigger_engine.py`)
가 실제 SELL 여부를 100% 결정하는 **순수 함수**(DB/실시간 상태 없이
오프라인 호출 가능)라는 점을 이번에 확인했고, 이는 R3b candidate의
실제 청산 시점을 직접 시뮬레이션할 수 있는 조건이 이미 갖춰져
있었다는 뜻이다 — 그동안 아무도 이 시뮬레이션을 돌리지 않았을 뿐이다.
이것이 이번 턴 가장 직접적인 전진 지점이다.

### 41.2 방법론

R3b + entry_score risk_off_penalty 제거(B 시나리오, §37 이후 승인된
조합과 동일)의 would_buy candidate 각각에 대해:

1. 매수일(t) 이후 t+1~t+20 각 거래일에서 **실제 운영 함수
   `_build_exit_score`**를 point-in-time으로 재호출(그날까지의
   bars window로 `build_signal_snapshot`·`classify_market_regime`을
   다시 계산해 overall/fast/slow·market_regime을 그 시점 값으로
   갱신).
2. `exit_score >= sell_candidate_threshold(0.75)`(운영 코드에 이미
   존재하는 실제 임계값)를 처음 넘는 날을 "signal-driven 청산일"로
   기록. 20거래일 안에 한 번도 넘지 않으면 T+20 시점에서 censored
   처리(청산 못 함 → T+20 값을 대리로 사용).
3. 가정(전부 문서화): `position_snapshot`은 보유 중(quantity=1)으로
   고정, `portfolio_allocation=None`(§32 gap, 기존과 동일 가정),
   `source_type="held_position"`(매수 이후 보유 포지션 모니터링
   관례 반영). `market_regime`은 각 시점 실제
   `classify_market_regime` 결과를 그대로 사용 — **운영 코드
   자체는 전혀 변경하지 않았다**(입력만 point-in-time으로 새로
   구성해 실제 함수에 전달, 지난 턴들과 동일한 shadow 기법).

### 41.3 실측 결과

| 구분 | 표본 | 평균수익률 | t_NW | 양수율 | 총 기대수익 proxy |
|---|---|---|---|---|---|
| T+5(고정) | 1151 | 2.022% | 4.18 | 55.0% | 2327.4 |
| T+20(고정) | 1151 | 6.491% | 3.87 | 53.3% | 7471.2 |
| **signal-driven 청산(실제 exit_score 기반)** | 1151 | **6.141%** | **4.73** | 52.5% | 7067.7 |

**청산 시점 분포(20거래일 관찰 기준)**: 1~5일=10건(0.9%), 6~10일=
18건(1.6%), 11~15일=45건(3.9%), 16~20일=29건(2.5%), **censored
(20일 내 미청산)=1049건(91.1%)**. 평균 보유일수=19.35일(20일 상한에
근접).

### 41.4 해석

**핵심 발견: 실제 exit_score 로직 기준으로는 would_buy candidate의
91.1%가 20거래일 안에 단 한 번도 매도 신호(0.75)를 넘지 않는다.**
즉 "T+5에 강제로 청산된다"는 걱정은 실제 청산 로직과 맞지 않는다 —
실제 운영에서는 대부분의 포지션이 계속 보유되며, 그 결과
signal-driven 청산 수익률(평균 6.14%, t=4.73)은 T+5(2.02%, t=4.18)
보다 T+20(6.49%, t=3.87)에 훨씬 가깝다. 오히려 signal-driven
청산의 t_NW(4.73)가 고정 T+20의 t_NW(3.87)보다 높다 — 이는 8.9%의
"조기 청산" 건들이 실제로는 하락 신호가 뜬 뒤에 빠져나오는 것이라
평균을 깎기보다 분산을 줄이는 방향으로 작용했을 가능성을 시사한다
(예비적 관찰, 별도 분해는 하지 않음).

**지금 데이터로 확실히 말할 수 있는 것**: (a) 실제 exit_score 로직
하에서 R3b candidate 대부분은 T+5가 아니라 T+20 근방(또는 그 이상)
까지 보유된다. (b) 이 실제 청산 시뮬레이션 기준 수익률은 T+20 고정
시계와 방향·크기 모두 일치하며 T+5보다 강하다. (c) 따라서 "T+5
평균이 약하다"는 이전 관찰(§2.7 등)은 실제 운영 리스크로 그대로
전이되지 않는다 — 실제 시스템은 T+5에 청산하지 않기 때문이다.

**아직 말하면 과장인 것**: (a) 91.1%가 censored라는 것은 20거래일
관찰 창의 한계이지, "장기 보유가 항상 안전하다"는 증거가 아니다 —
20일을 넘는 구간의 실제 청산 시점 분포는 이번 시뮬레이션이 다루지
않았다(관찰 기간을 늘리는 후속 검증 대상). (b) 이 시뮬레이션은
동일 3년 in-sample 캐시에서 수행됐고, MAE(보유 기간 중 최대 손실
구간)를 반영하지 않아 "보유 중 한때 크게 손실을 봤다가 회복"하는
경로 리스크는 측정하지 못했다 — 총 수익률만으로는 이 리스크가
없다고 말할 수 없다. (c) `portfolio_allocation=None` 가정은 여전히
§32 gap과 동일한 한계이며 실거래 누적 전까지 해소되지 않는다.

### 41.5 판정 — Conditional Go 유지, "T+5 구조적 리스크"는 부분 완화(완전 해소 아님)

**R3b는 Conditional Go를 유지한다.** §38의 보조 잔여 조건 중 "T+5
구조적 리스크"는 이번 턴으로 **"실제 청산 로직 기준으로는 T+5가
아니라 T+20 근방에서 청산되며, 그 수익률은 T+20과 일치·강함"**이
확인돼 **리스크의 상당 부분이 완화됐다** — 그러나 20일을 넘는 보유
구간의 청산 분포와 경로 리스크(MAE)는 이번 턴에도 다루지 않았으므로
"완전 해소"라고 부르는 것은 과장이다. **정확한 표현: "T+5 구조적
리스크는 부분적으로 완화됐다(실제 청산은 T+5가 아닌 T+20 근방에서
발생) — 20일 초과 구간·경로 리스크는 여전히 미해결."** 운영
코드(`deterministic_trigger_engine.py`)는 변경하지 않았다. 신규 KIS
호출 0건, broker submit 미호출 — 이번 턴도 shadow/validation 범위.

### 41.6 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. **관찰 창을 20거래일보다 늘려(예: 40~60거래일) censored 비율이
   실제로 줄어드는지, 그리고 그 구간에서 경로 리스크(MAE)가 어떤
   분포를 보이는지 추가 검증 — T+5 리스크의 완전 해소 여부를
   가리는 다음 실측 후보.**
4. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 42. T+5 horizon 구조적 리스크 — 20거래일 초과 구간·경로 리스크(MAE) 확장 검증 (SPPV-2.53, 2026-07-18)

### 42.1 왜 이 검증을 골랐는가

§41(SPPV-2.52)은 20거래일 관찰 창 안에서 signal-driven 청산을
시뮬레이션해 "T+5 평균이 약하다"는 우려가 부분적으로 완화됨을
보였으나, 두 가지를 미확인 상태로 남겼다: (a) 20일을 넘겨도 청산이
안 되는 91.1% 구간에서 실제로는 무슨 일이 일어나는가, (b) 총수익률
관점만 봤을 뿐 보유 기간 중 경로 리스크(MAE)를 전혀 재지 않았다는
것. 사용자가 이번 턴에 정확히 이 두 가지를 지목했고, §41의 스크립트
를 그대로 재사용해 관찰 창만 60거래일로 늘리고 MAE 계산만 추가하면
바로 실측 가능했다 — 신규 설계 없이 최소 확장만으로 가장 직접적으로
답할 수 있는 항목이었다.

### 42.2 방법론

§41과 완전히 동일한 candidate 정의(R3b + entry_score
risk_off_penalty 제거, B 시나리오, would_buy 후보)를 재사용하되:

1. **효율화를 위한 2단계 분리**: 1단계(저비용)에서 매수일 후보만
   스캔해 candidate·eligibility·score를 계산하고 would_buy 집합을
   확정한 뒤, 2단계(고비용)에서 **would_buy 후보에 대해서만** 60
   거래일 관찰 창으로 signal-driven 청산 시뮬레이션과 MAE 계산을
   수행했다(§41은 전체 5.6만 행에 대해 20일 시뮬레이션을 돌렸으나,
   이번 턴은 관찰 창이 3배로 늘어나 연산량이 커지므로 would_buy
   1048건에만 60일 시뮬레이션을 적용 — 결과는 §41과 동일한 후보
   정의·동일한 청산 로직이므로 비교 가능성은 유지된다).
2. **MAE(경로 리스크)**: 매수일부터 청산일(또는 60일 관찰 창 끝)
   까지 매일 저가(low_price) 기준 미실현 수익률의 최저값을 추적 —
   "보유 중 최악의 순간에 얼마나 손실을 봤는가"를 나타낸다.
3. 청산 로직(`_build_exit_score`, `sell_candidate_threshold=0.75`)
   과 candidate 선정 로직은 §41과 동일 — 운영 코드 변경 없음.

**주의(비교 가능성 caveat)**: 60일 관찰 창을 확보하려면 매수일
이후 60거래일치 bars가 더 필요해, would_buy 표본이 §41의 1151건
에서 1048건으로 줄었다(3년 캐시 끝부분 약 40거래일이 제외됨) — 두
턴의 표본이 완전히 동일하지 않다는 점을 감안해 해석해야 한다.

### 42.3 실측 결과

| 구분 | 표본 | 평균수익률 | t_NW | 양수율 | 총 기대수익 proxy |
|---|---|---|---|---|---|
| T+5(고정) | 1048 | 1.210% | 3.07 | 53.3% | 1268.3 |
| T+20(고정) | 1048 | 4.464% | 3.41 | 51.6% | 4677.9 |
| **signal-driven 청산(60일 관찰)** | 1048 | **9.289%** | **5.38** | 52.8% | 9734.7 |

**청산 시점 분포(60거래일 관찰 기준)**: 1~5일=10건(1.0%), 6~10일=
18건(1.7%), 11~20일=65건(6.2%), 21~40일=216건(20.6%), 41~60일=
201건(19.2%), **censored(60일 내 미청산)=538건(51.3%)**. 평균
보유일수=48.0일(§41의 20일 관찰 대비 91.1%→51.3%로 censored 비율이
크게 낮아짐 — 관찰 창을 늘리면 실제로 더 많은 청산이 관측된다).

**MAE(보유 구간 중 최대 미실현 손실)**: 평균 -11.08%, 중앙값
-10.42%, 하위 10%(더 나쁜 쪽) -21.77%, 최악값 -45.10%, **-20% 이하
심각 손실을 겪은 비율 12.8%**.

### 42.4 해석

**질문 1: 20일 이후에도 실제 청산은 여전히 늦게 일어나는가?** →
**그렇다, 오히려 더 늦어진다.** 관찰 창을 60일로 늘리자 censored
비율이 91.1%→51.3%로 줄어 "더 기다리면 실제로 더 많이 청산된다"는
것은 확인됐지만, 평균 보유일수가 19.35일→48.0일로 늘어 실제 청산은
T+20보다도 훨씬 뒤에 일어나는 경우가 많다(21~40일 구간 20.6%,
41~60일 구간 19.2%). 즉 실제 운영에서 포지션은 T+5는 물론 T+20보다도
오래 보유되는 경우가 상당하다.

**질문 2: 20일 초과 구간까지 포함하면 signal-driven 실현 수익률은
T+20과 여전히 가까운가?** → **아니다, 오히려 T+20보다 더 강해졌다.**
60일 관찰 기준 signal-driven 청산 평균수익률(9.29%, t=5.38)은
고정 T+20(4.46%, t=3.41)보다 크고 통계적으로도 더 유의하다 — 이는
"더 오래 보유할수록 평균적으로 더 유리하다"는 이 3년 표본(대체로
상승 우위 구간)의 성격과 일치한다. §41의 결론("T+5보다 T+20에
가깝다")은 이번 턴으로 더 강화됐다: 실제 청산 로직 기준 수익률은
T+20보다도 강하다.

**질문 3: 보유 중 MAE가 커져서 Conditional Go 해석을 약화시킬
정도인가?** → **완전히 무시할 수는 없으나, Conditional Go를
뒤집을 정도는 아니다.** 평균 MAE -11.08%, 심각 손실(-20% 이하)
비율 12.8%는 무시할 수 없는 경로 리스크다 — 최종 수익률이 좋아도
그 과정에서 상당수 포지션이 한때 두 자릿수 손실을 겪는다는 뜻이다.
그러나 최종 실현 수익률(9.29%, t=5.38, 양수율 52.8%)은 여전히
강하고 방향이 일관되며, MAE가 "이 창 교체가 방향적으로 틀렸다"는
증거는 아니다 — 오히려 "이 전략은 변동성을 견뎌야 최종 수익을
얻는 구조"라는 별도의 운영 리스크(포지션 사이징·손절 정책)로
분류하는 것이 맞다.

**질문 4: T+5 구조적 리스크는 어디까지 줄었고, 무엇이 아직
남는가?** → §41에서 "20일 관찰 기준 T+5보다 T+20에 가깝다"였던
결론이 이번 턴으로 **"60일 관찰 기준으로는 T+20보다도 강하다"**로
한 단계 더 명확해졌다 — **T+5 구조적 리스크(고정 시계가 실제
운영과 안 맞는다는 우려)는 이제 상당 부분 해소됐다고 볼 수 있다.**
그러나 이 검증으로 **새로운 잔여 리스크가 명시적으로 드러났다**:
경로 리스크(MAE) — 평균 -11%, 심각 손실 12.8% — 는 이번까지 어떤
턴에서도 다루지 않았던 축이며, 현재 코드에는 `_build_exit_score`
외에 별도의 손절(stop-loss) 임계값이 없다는 것도 이번 조사에서
재확인됐다(§31/§41 계열에서 확인한 "강제 보유기간 없음"과 마찬가지로
"강제 손절 없음"도 사실). 따라서 T+5 리스크는 **"거의 해소"**로
격상하되, 경로 리스크·손절 정책 부재는 **별도의 신규 잔여 조건**
으로 §38의 분류에 추가한다.

### 42.5 판정 — Conditional Go 유지, T+5 리스크는 "거의 해소"로 격상, 경로 리스크(MAE)는 신규 잔여 조건으로 편입

**R3b는 Conditional Go를 유지한다.** §41이 "부분 완화"로 판정한
T+5 구조적 리스크는 이번 60일 확장 검증으로 **"실제 청산 로직
기준 수익률이 T+20보다도 강하다"**는 것이 확인돼 **"거의 해소"**
로 격상한다 — 다만 100% 해소라고 부르는 것은 여전히 과장이다(60일
관찰도 유한하며, 51.3%가 여전히 censored). 대신 이번 검증으로
드러난 **경로 리스크(MAE 평균 -11%, 심각 손실 12.8%, 손절 임계값
부재)**를 §38의 보조 잔여 조건 목록에 **신규 항목으로 추가**한다 —
이는 R3b의 방향성이나 Conditional Go를 뒤집는 근거가 아니라,
실거래 반영 시 포지션 사이징·손절 정책 설계가 필요하다는 운영상
시사점이다. 운영 코드(`deterministic_trigger_engine.py`)는 변경하지
않았다. 신규 KIS 호출 0건, broker submit 미호출.

### 42.6 §38 보조 잔여 조건 재분류(갱신)

- ①**주된 차단 요인**: §21 게이트(불변).
- ②**보조 잔여 조건**: entry_score 코드 반영 절차(불변), **T+5
  구조적 리스크(§41→§42로 "부분 완화"에서 "거의 해소"로 격상,
  100% 해소는 아님)**, 혼합도 모니터링 설계(강한 구조적 정합 증거,
  §40), **경로 리스크(MAE)·손절 정책 부재(§42 신규 추가)**.
- ③**실거래 누적 필요 조건**: `portfolio_allocation` gap, 실제
  청산 시점 분포(§42로 일부 shadow 근사됐으나 실거래 검증은 여전히
  별도).

### 42.7 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. **경로 리스크(MAE)·손절 정책 설계 검토를 신규 우선순위로 추가**
   — 예: 고정 손절선(-15%~-20%) 도입 시 총 기대수익 proxy가
   개선되는지 별도 ablation 실측(다음 실측 후보).
4. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 43. SPPV-2.53 결론 문구 정밀화 — 20일판·60일판 표본 동일성 검증 + "거의 해소" 표현 재점검 (SPPV-2.54, 2026-07-18)

### 43.1 왜 이 검증을 골랐는가

§42(SPPV-2.53)는 "censored 91.1%→51.3%, 평균 보유일수 19.35일→
48.0일"을 마치 **동일한 후보 집단을 더 오래 관찰한 결과**처럼
서술했다. 그러나 §42.2에 이미 "would_buy 표본이 §41의 1151건에서
1048건으로 줄었다"는 caveat을 적어두고도, 이후 해석 문단에서는
이 차이를 반영하지 않은 채 "부분 완화 → 거의 해소"로 격상했다 —
이는 "같은 코호트의 전/후 비교"와 "표본이 달라진 비교"를 섞어서
서술한 것일 수 있다. 신규 실행 없이 두 스크립트의 코드를 직접
대조해 이 의문에 명확히 답하는 것이 이번 턴 최우선 과제다.

### 43.2 코드 기준 판정 — 두 표본은 동일하지 않다(60일판 ⊆ 20일판, 부분집합 관계로 추정)

`scripts/validate_r3b_signal_driven_exit_timing.py`(20일판)와
`scripts/validate_r3b_signal_driven_exit_timing_extended.py`(60일판)
를 대조한 결과:

- 두 스크립트 모두 매수일 후보 스캔 범위를 `last_t = len(bars) - 1
  - MAX_EXIT_OBSERVATION_DAYS`로 제한한다(20일판:
  `MAX_EXIT_OBSERVATION_DAYS=20`, 60일판: `=60`). 즉 **60일판은
  3년 캐시 끝에서 60거래일을 남겨야 스캔에 포함시키는 반면, 20일판
  은 20거래일만 남기면 포함**시킨다 — 60일판의 스캔 대상 거래일
  집합은 20일판보다 항상 좁다(끝부분 약 40거래일이 60일판에서는
  아예 스캔되지 않는다).
- candidate 선정 로직(같은 날 상위 20% quintile → eligibility →
  B 시나리오 score 상위 3 would_buy)은 **그날의 backward-looking
  데이터만 사용**하며 `MAX_EXIT_OBSERVATION_DAYS`와 무관하다 —
  따라서 두 스크립트에서 **공통으로 스캔되는 거래일**에 대해서는
  같은 candidate가 같은 순서로 선정될 것으로 코드상 예상된다
  (결정론적 계산, 무작위성 없음).
- **결론(코드 기준 추정, 재실행으로 실측 재확인은 하지 않음)**:
  60일판의 would_buy 1048건은 20일판의 1151건 중 "3년 캐시 끝에서
  60거래일 이전에 매수한" 부분집합에 해당할 가능성이 매우 높다 —
  20일판에만 있는 103건(1151-1048)은 3년 캐시 마지막 약 40거래일
  구간에서 매수한 candidate로, 60거래일 forward 데이터가 부족해
  60일판 스캔에서 원천적으로 제외된 것이다. **즉 두 결과는 "같은
  1151건을 더 오래 관찰한 것"이 아니라 "겹치지만 완전히 같지는
  않은 두 표본(1151건 vs 그 중 약 91%인 1048건)"의 비교다.**

### 43.3 지금 데이터로 확실히 말할 수 있는 것 / 아직 말하면 과장인 것

**확실히 말할 수 있는 것**:
- 60일판(1048건) 자체의 측정치는 유효하다: censored=51.3%, 평균
  보유일수=48.0일, signal-driven 청산 수익률=9.29%(t=5.38), MAE
  평균=-11.08%.
- 20일판(1151건) 자체의 측정치도 유효하다: censored=91.1%, 평균
  보유일수=19.35일, signal-driven 청산 수익률=6.14%(t=4.73).
- 두 표본은 완전히 다른 모집단이 아니라 **약 91%가 겹치는(60일판
  ⊆ 20일판으로 추정) 고도로 중첩된 표본**이며, 표본 차이의 크기
  (약 9%)는 관측된 효과 크기(censored 40%p 감소, 평균 보유일수
  2.5배 증가)에 비해 작다 — 따라서 "관찰 창을 늘리면 censored가
  줄고 실제 청산은 더 오래 걸린다"는 **방향성 자체**는 표본 차이
  만으로 설명되지 않을 만큼 크다.

**아직 말하면 과장인 것**:
- "censored 91.1%→51.3%"를 **동일 코호트의 순수 전/후(before/
  after) 비교**라고 부르는 것 — 20일판에만 있는 103건(약 9%)이
  섞여 있어 엄밀한 페어드(paired) 비교가 아니다. 두 표본을
  정확히 맞춰 비교하려면 20일판을 1048건 부분집합으로 제한해
  재계산해야 하는데, 이는 이번 턴에서 신규 실행 없이는 할 수
  없다(다음 실측 후보로 남긴다).
- "T+5 구조적 리스크는 거의 해소됐다"— 60일 관찰 후에도 **51.3%가
  여전히 censored**(과반)라는 것은 "청산 타이밍의 절반 이상이
  여전히 미확인"이라는 뜻이다. 대부분이 해소됐다고 말하기엔
  이르다 — 정확한 표현은 **"§41의 '부분 완화'에서 한 단계 더
  나아간 '추가 완화'"**이지, "거의 해소"는 증거보다 센 표현이다.
- 두 시뮬레이션 모두 동일한 3년 in-sample 캐시에서 수행됐다는
  기존 한계(§40.6에서 이미 정정한 것과 동일한 종류)도 여전히
  유효하다 — out-of-sample 재현은 검증되지 않았다.

### 43.4 질문별 답변

**Q1. 20일판과 60일판은 직접 비교 가능한가?** → **부분적으로만
가능하다.** 완전히 같은 코호트의 전/후 비교는 아니다(60일판이
20일판의 약 91% 부분집합으로 추정). 그러나 표본 차이가 작고
효과 크기가 커서, "관찰 창을 늘리면 청산이 더 늦게·더 많이
관측된다"는 **방향성**은 신뢰할 수 있다 — 다만 정확한 %p·배수
수치(91.1%→51.3%, 19.35일→48.0일)를 "같은 표본의 엄밀한 전후
비교치"로 인용하는 것은 과장이다.

**Q2. 직접 비교가 아니라면 SPPV-2.53에서 무엇을 확실히 얻었는가?**
→ (a) 60일 관찰 시 signal-driven 청산 수익률(9.29%, t=5.38)이
고정 T+20(4.46%, t=3.41)보다 강하다는 것 — 이는 60일판 표본
내부의 비교이므로 코호트 문제와 무관하게 유효하다. (b) 60일
관찰에서도 여전히 51.3%가 미청산이라는 것 — "강제 보유기간
없음"이 만드는 장기 보유 경향이 60일을 넘어서도 이어진다는
확실한 증거. (c) MAE(경로 리스크) 분포 — 평균 -11.08%, 심각
손실 12.8% — 는 60일판 자체 내부 계산이므로 그대로 유효하다.

**Q3. `T+5 구조적 리스크`는 지금 단계에서 `부분 완화`, `추가
완화`, `거의 해소` 중 어디까지가 맞는가?** → **"추가 완화"가
정확하다.** §41에서 "부분 완화"로 판정한 것을, §42가 "거의
해소"로 격상한 것은 과장이었다 — 60일을 넘겨도 과반(51.3%)이
미청산이고, 20일판·60일판 비교가 엄밀한 페어드 비교도 아니기
때문이다. 정확한 3단계 표현: **①§41 = 부분 완화(20일 관찰) →
②§42/§43 = 추가 완화(60일 관찰, 표본 caveat 포함) → ③아직
"거의 해소"·"완전 해소" 단계는 아니다.**

### 43.5 판정 — Conditional Go 유지, "거의 해소" 표현은 "추가 완화"로 하향 정정(방향 반전 아님)

**R3b는 Conditional Go를 유지한다.** §42가 사용한 "T+5 구조적
리스크는 거의 해소됐다"는 표현은 **[SPPV-2.54에서 정정] "추가
완화됐다"가 정확하다** — 근거: (1) 20일판·60일판 표본이 완전히
동일하지 않다(60일판이 20일판의 약 91% 부분집합으로 추정, 엄밀한
페어드 비교 아님), (2) 60일 관찰 후에도 51.3%(과반)가 여전히
censored — "거의 해소"라고 부르기엔 미확인 비중이 너무 크다. 이
정정은 R3b의 방향성이나 Conditional Go를 바꾸지 않는다 — 60일판
자체 내부 비교(signal-driven 청산이 T+20보다 강하다는 것, MAE
분포)는 여전히 유효한 증거이며, 방향은 그대로 지지된다. 경로
리스크(MAE)·손절 정책 부재는 §38 보조 잔여 조건 목록에 계속
유지한다(§42에서 신규 추가한 그대로, 변경 없음). 신규 실행 없음
(§41·§42 기존 산출물 재해석 + 코드 대조만 수행), 신규 KIS 호출
0건, 운영 코드 변경 없음, broker submit 미호출.

### 43.6 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. 경로 리스크(MAE)·손절 정책 설계 검토(변경 없음, §42에서 이미
   추가된 항목).
4. **(신규, 선택 사항) 20일판을 60일판과 동일한 1048건 부분집합
   으로 제한해 재계산 — censored·평균 보유일수 delta를 진짜
   페어드 비교치로 확정하고 싶다면 이 재계산이 필요하다(신규
   실행 필요, 이번 턴 범위 밖).**
5. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
6. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 44. 손절(stop-loss) 정책 도입이 총 기대수익에 미치는 영향 ablation (SPPV-2.55, 2026-07-18)

### 44.1 왜 이 실측을 이번 턴 최우선으로 골랐는가

§42(SPPV-2.53)는 §38 보조 잔여 조건에 "경로 리스크(MAE)·손절
정책 부재"를 신규 추가했지만, 확인한 것은 **리스크의 존재**뿐이었다
(MAE 평균 -11.08%, 심각 손실 12.8%). "손절선을 도입하면 총 기대
수익이 개선되는가, 악화되는가"는 아직 답하지 않은 질문이며, 이는
단순한 방어 논리 점검이 아니라 **SPPV-3 설계에 손절 로직을 포함
시켜야 하는지 여부를 가르는 실제 의사결정 정보**다 — 이번 턴이
선택한 이유는 (1) SPPV-3 착수 준비에 직접 영향, (2) 지금까지
어느 턴에서도 측정하지 않은 신규 정보, (3) 기존 60일 캐시·스크립트
구조를 그대로 재사용해 지금 당장 실측 가능, (4) "창 교체(R3b)가
경로 리스크를 감내할 만큼 실효적인가"를 손절 유무 비교로 더 선명
하게 보여준다는 4가지 기준을 모두 충족하기 때문이다. 이미 결론이
난 §21 게이트·문구 정정(§40.6/§43)은 반복하지 않는다.

### 44.2 방법론

§42/§43과 완전히 동일한 candidate 정의(R3b + entry_score
risk_off_penalty 제거, B 시나리오, would_buy 1048건, 60거래일
관찰 창)를 재사용하되, 한 번의 60일 순회 안에서 3개 청산 정책
변형을 동시에 시뮬레이션했다:

- **A(baseline, 손절 없음)**: §42와 동일 — 실제 운영 함수
  `_build_exit_score`(임계값 0.75)가 발동할 때만 청산.
- **B(손절 -15%)**: 보유 중 어느 날이든 그날 저가 기준 미실현
  수익률이 -15% 이하면 그날 즉시 -15% 가격에 청산(그 이후 관찰
  중단), 손절 체크가 그날의 exit_score 체크보다 우선.
- **C(손절 -20%)**: 동일하되 임계값 -20%.

손절 로직은 스크립트 안에서만 시뮬레이션되는 shadow 계산이며,
운영 코드(`deterministic_trigger_engine.py`)에는 어떤 손절
임계값도 추가하지 않았다.

### 44.3 실측 결과

| 변형 | 표본 | 평균수익률 | t_NW | 양수율 | 총 기대수익 proxy | 손절 발동률 | 평균 보유일수 |
|---|---|---|---|---|---|---|---|
| **A(손절 없음)** | 1048 | **9.289%** | **5.38** | **52.8%** | **9734.7** | 0% | 48.0일 |
| B(손절 -15%) | 1048 | 6.702% | 4.25 | 46.4% | 7024.1 | 28.5%(299건) | 41.5일 |
| C(손절 -20%) | 1048 | 8.677% | 5.02 | 50.7% | 9093.8 | 12.8%(134건) | 45.7일 |

### 44.4 해석

**핵심 발견: 손절선을 도입하면 총 기대수익 proxy가 오히려
악화된다 — 손절이 얕을수록(더 타이트할수록) 악화 폭이 크다.**
baseline(A)=9734.7 대비 -15% 손절(B)=7024.1은 **약 27.8% 악화**,
-20% 손절(C)=9093.8은 **약 6.6% 악화**다. 양수율도 A(52.8%)→
B(46.4%)→C(50.7%) 순으로 손절이 타이트할수록 더 나빠진다.

이는 §42/§43에서 확인한 구조와 정확히 일치한다: R3b candidate는
보유 기간 중 상당한 미실현 손실(MAE 평균 -11%)을 겪지만, 실제
운영 로직상 대부분 강제 청산 없이 오래 보유되며(§42의 signal-
driven 청산이 T+20보다 강했던 것과 동일한 메커니즘), **그 조정
구간을 버텨야 이후의 회복·상승분을 온전히 취할 수 있는 구조**다.
-15% 손절은 candidate의 28.5%를 조정 국면 도중에 강제로 잘라내
회복 기회를 원천 차단하며, 그 결과 이 28.5% 구간의 손실이 확정
손실로 굳어져 총 기대수익을 깎는다. -20% 손절은 발동 빈도가
낮아(12.8%) 악화 폭이 작지만, 그래도 baseline보다는 약하다 —
"손절을 도입해서 나아지는 지점"은 이번 두 임계값(-15%/-20%)
범위 안에서는 확인되지 않았다.

**지금 데이터로 확실히 말할 수 있는 것**: (a) 이번에 시험한 두
손절 임계값(-15%, -20%) 모두 총 기대수익 proxy를 악화시켰다.
(b) 손절이 타이트할수록(더 얕을수록) 악화 폭이 컸다(-15%가
-20%보다 나쁨) — 방향이 일관된다. (c) R3b의 우위는 "조정 구간을
버티고 회복분을 취하는" 구조에 상당 부분 의존한다는 것이 이번
ablation으로 뒷받침됐다.

**아직 말하면 과장인 것**: (a) 이번 결과가 "어떤 손절 임계값도
항상 나쁘다"는 뜻은 아니다 — -15%/-20% 두 지점만 시험했고, 더
넓은 손절(-30% 등)이나 시간 기반 손절(예: N일 이상 미회복 시
청산) 등 다른 정책은 검증하지 않았다. (b) 동일한 3년 in-sample
캐시(§40.6/§43에서 이미 정정한 것과 같은 한계)에서 나온 결과이며
out-of-sample 재현은 검증되지 않았다. (c) 60일 관찰 창 기준
would_buy 1048건 표본(§43에서 정리한 20일판·60일판 표본 차이
caveat과 동일한 성격)에 대한 결과다.

### 44.5 판정 — Conditional Go 유지, "손절 정책 부재"는 잔여 조건에서 "손절 미도입이 근거 있는 선택"으로 재분류

**R3b는 Conditional Go를 유지한다.** §42가 §38에 추가한 "경로
리스크(MAE)·손절 정책 부재"는 이번 ablation으로 **"부재가 방치된
공백"이 아니라 "시험한 범위 내에서는 손절을 도입하지 않는 편이
총 기대수익 관점에서 더 낫다는 근거가 있는 선택"**으로 재분류
한다 — 이는 방향성을 뒤집는 것이 아니라, "손절이 없다"는 사실을
"손절을 만들어야 한다"는 미결 과제에서 "이 범위에서는 손절을
만들지 않는 것이 최고 기대수익 관점에서 맞다"는 **근거 있는
설계 결정**으로 격상하는 것이다. 다만 MAE(경로 리스크) 자체가
사라진 것은 아니므로(평균 -11%는 여전히 실재), 포지션 사이징
등 exit 시점 개입이 아닌 다른 방식의 리스크 관리는 여전히 검토
대상으로 남긴다. 운영 코드는 변경하지 않았다. 신규 KIS 호출
0건, broker submit 미호출.

### 44.6 §38 보조 잔여 조건 재분류(갱신)

- ①**주된 차단 요인**: §21 게이트(불변).
- ②**보조 잔여 조건**: entry_score 코드 반영 절차(불변), T+5
  구조적 리스크("추가 완화" 단계, §43, 변경 없음), 혼합도 모니터링
  설계(강한 구조적 정합 증거, §40, 변경 없음). **경로 리스크(MAE)·
  손절 정책 부재는 "미검증 공백"에서 "-15%/-20% 손절은 총 기대
  수익을 악화시킨다는 근거 확보"로 갱신** — 남은 것은 포지션
  사이징 등 exit 외 리스크 관리 수단 검토(신규, 낮은 우선순위).
- ③**실거래 누적 필요 조건**: `portfolio_allocation` gap, 실제
  청산 시점 분포(불변).

### 44.7 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 반영 절차 설계
   착수 여부 사용자 확인(변경 없음).
3. **(신규, 낮은 우선순위) exit 시점 손절이 아닌 포지션 사이징
   (예: candidate당 배분 비중 축소)이 MAE 노출을 줄이면서 총
   기대수익을 보존할 수 있는지 별도 검토 — 실거래 계좌 상태가
   필요해 §32 gap과 함께 실거래 누적 이후 재검증 대상.**
4. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 45. entry_score 코드 반영 절차 구체화 — shadow 재구현 정합성 검증 (SPPV-2.56, 2026-07-18)

### 45.1 왜 이 항목을 이번 턴 최우선으로 골랐는가

§21 게이트는 외생 조건이라 반복 관측 외에 전진시킬 수 없다. 반면
"entry_score 코드 반영 절차"는 §38 이래 줄곧 **보조 잔여 조건**으로
남아 있었지만, "실제 운영 코드 변경 PR 작성" 전에 반드시 확인해야
할 선행 질문이 있었다 — **SPPV-2.46부터 지금까지 이 세션 내내
R3b+entry_score risk_off_penalty 제거(B 시나리오)의 non-alpha
조정 부분을 계산할 때, 검증 스크립트마다 `_non_alpha`라는 이름의
수작업 재구현 함수를 썼을 뿐, 실제 운영 함수 `_build_entry_score`
(`deterministic_trigger_engine.py:1115-1170`)를 한 번도 직접
호출한 적이 없었다.** 코드 대조 결과 `_build_entry_score`에는
`_non_alpha`가 구조적으로 담아내지 못하는 항목이 있었다:
`portfolio_allocation` 예산 보너스/차단 패널티(+0.10/-0.20,
1143-1149행), `source_type` 조정(market_overlay +0.05 / held_
position -0.35, 1158-1163행), 최종 `_clamp()`(1170행). 이 세션
에서는 항상 `source_type="core"`, `portfolio_allocation=None`으로
써서 이론상 앞의 두 항목은 no-op이었지만, **이것이 실제로 그런지는
검증된 적이 없었다** — 만약 여기서 불일치가 발견됐다면 이번 세션이
쌓아온 SPPV-2.46~2.55의 모든 B 시나리오 funnel·수익률 결과 전체를
재검토해야 했을 것이다. 이는 (1) SPPV-3(entry_score 코드 반영)
착수의 직접 전제조건이고, (2) 지금까지 어느 턴에서도 확인하지 않은
신규 검증이며, (3) 기존 3년 캐시·기존 코드만으로 지금 당장 실측
가능하고, (4) 방어 논리가 아니라 "창 교체를 실제 운영 코드 경로에
연결할 준비"를 직접 진전시킨다는 4가지 선택 기준을 모두 충족한다.

### 45.2 방법론

3년 전체 후보 표본(87개 core 종목, `_MIN_LOOKBACK`부터 각 종목의
마지막 거래일까지)에 대해 각 행마다:

1. 실제 `_build_entry_score`를 `overall=fast=slow=0.0`으로 호출한다
   — `_normalize_signed_score(0) = clamp((0+1)/2) = 0.5`이므로 alpha
   항은 정확히 `0.45*0.5+0.20*0.5+0.15*0.5=0.40`(상수)이 되고, 그
   결과에서 이 상수를 빼면 **조정 항(regime/strategy/activity/
   portfolio_allocation/source_type)만 순수하게 분리**된다.
2. 같은 행에서 이 세션 내내 써온 수작업 재구현 `_non_alpha(neutral_
   regime, strategy_selection, snapshot)`을 그대로 계산한다(입력은
   B 시나리오와 동일 — `dataclasses.replace(risk_tone="neutral")`
   적용, `source_type="core"`, `portfolio_allocation=None`).
3. 두 값의 차이를 부동소수점 오차(1e-9) 이내에서 비교한다.

운영 코드는 이번 검증에서도 전혀 수정하지 않았다 — `_build_entry_
score`를 있는 그대로 import해서 호출했을 뿐이다.

### 45.3 실측 결과

**검사 표본: 58,493건. 완전 일치: 58,493건(100.0%). 불일치:
0건. 최대 절대 오차: 0.0.** **[SPPV-2.57에서 정정]** "candidate
전량"이라는 표현은 부정확하다 — 이 스크립트는 quintile 상위 20%
candidate 선별이나 eligibility 필터링을 전혀 거치지 않고 `_MIN_
LOOKBACK`부터 각 종목의 마지막 거래일까지 **모든 거래일의 point-
in-time 스냅샷을 예외 없이** 순회한다. 정확한 표현은 "3년 전체
core 87종목의 전체 시점 스냅샷(모집단 전체, candidate로 좁히지
않음) 58,493건"이다.

### 45.4 해석

**이 세션 내내 사용해온 수작업 재구현(`_non_alpha`)은 실제 운영
함수(`_build_entry_score`)와 이 검증 조건(source_type="core",
portfolio_allocation=None) 하에서 소수점 오차 없이 완전히 일치
한다.** 이는 다음 두 가지를 동시에 확인한 것이다: (a) 코드 대조로
지적된 `portfolio_allocation`·`source_type` 조정 항이 실제로도
정확히 no-op이었다(이론적 추정이 아니라 5.8만 건 전수 실측으로
확인). (b) 최종 `_clamp()`가 이 세션의 조정 항 범위(대략
-0.15~+0.20 사이)에서는 한 번도 [0,1] 경계에 걸리지 않아, clamp
누락이 수치적으로 문제된 적이 없었다.

**지금 데이터로 확실히 말할 수 있는 것**: SPPV-2.46~2.55에서 계산된
모든 B 시나리오 funnel·수익률 결과는 실제 운영 함수를 그대로
호출했을 때와 **수치적으로 동일**하다 — 이 세션의 shadow 작업이
"실제 운영 코드가 반영됐을 때의 결과"를 정확하게 대표한다는 것이
처음으로 전수 검증됐다.

**아직 말하면 과장인 것**: 이 검증은 `source_type="core"`,
`portfolio_allocation=None`이라는 이 세션 전체에서 고정해온 조건
안에서의 일치를 확인한 것이다 — 실제 운영에서는 `source_type`이
"held_position"(보유 중 재평가)이거나 `portfolio_allocation`이
실제 값을 가질 수 있어, 그 경우의 `_build_entry_score` 동작은
이번 검증 범위 밖이다(다만 그 경우는 애초에 이 세션의 B 시나리오
funnel 대상이 아니었으므로, "이 세션이 다룬 범위 안에서"의
정합성 확인으로는 충분하다).

### 45.5 판정 — Conditional Go 유지, "entry_score 코드 반영 절차" 전제조건 충족(착수 준비도 격상, 확정 Go 아님)

**R3b는 Conditional Go를 유지한다.** 이번 검증으로 "entry_score
코드 반영 절차"의 핵심 전제조건 하나 — **"지금까지의 shadow 계산이
실제 운영 코드 동작을 정확히 대표하는가"** — 가 5.8만 건 전수
일치로 확인됐다. 이는 §38이 정리한 보조 잔여 조건 중 "entry_score
코드 반영 절차"를 **"설계 논의 단계"에서 "실제 코드 변경 PR을
작성해도 되는 근거가 확보된 단계"로 격상**시킨다 — 다만 이것이
곧 코드 변경 PR 자체를 승인·실행한다는 뜻은 아니다(운영 코드
변경은 여전히 사용자 승인·리스크/컴플라이언스 검토 절차를 거쳐야
하며, 이번 턴에도 운영 코드는 전혀 건드리지 않았다). "SPPV-3
착수 준비"가 실질적으로 한 단계 더 앞당겨졌다는 것이 이번 턴의
핵심 결론이며, 단일 지표(100% 일치)만으로 SPPV-3 확정 Go를
선언하지는 않는다 — §21 게이트(주된 차단 요인)는 여전히 불변이다.

### 45.6 §38 보조 잔여 조건 재분류(갱신)

- ①**주된 차단 요인**: §21 게이트(불변).
- ②**보조 잔여 조건**: **entry_score 코드 반영 절차 — "설계 논의
  단계"에서 "shadow 계산 정합성 확보, 실제 코드 변경 PR 작성 가능
  단계"로 격상(§45, 신규)**. T+5 구조적 리스크("추가 완화" 단계,
  §43, 변경 없음), 혼합도 모니터링 설계(강한 구조적 정합 증거,
  §40, 변경 없음), 경로 리스크(MAE)·포지션 사이징 검토(§44, 변경
  없음).
- ③**실거래 누적 필요 조건**: `portfolio_allocation` gap, 실제
  청산 시점 분포(불변).

### 45.7 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. **(격상) entry_score risk_off_penalty 완화의 실제 코드 변경
   PR 초안 작성 착수 여부를 사용자에게 확인 — shadow 정합성은
   확보됐으므로, 착수 시 리스크/컴플라이언스 검토 절차와 병행
   가능.**
3. exit 시점 손절이 아닌 포지션 사이징 검토(변경 없음, §44).
4. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
5. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 46. SPPV-2.56 결론 문구 정밀화 — "직접 호출" 서술 범위·표본 서술 정정 (SPPV-2.57, 2026-07-18)

### 46.1 왜 이 정정이 필요한가

§45(SPPV-2.56)는 "R3b+entry_score risk_off_penalty 제거(B
시나리오)의 non-alpha 조정 부분을 계산할 때 실제 운영 함수
`_build_entry_score`를 한 번도 직접 호출한 적이 없었다"고 서술
했다 — 이는 **범위를 좁히지 않은 채 일반화된 과장**이다. 실제로는
`scripts/validate_alpha_layer_buy_funnel_comparison.py:211`과
`scripts/validate_r3b_point_in_time_pipeline_shadow.py:178`에서
이미 `_build_entry_score`를 직접 호출해왔다 — **다만 그 호출은
항상 시나리오 A(현행, `per_symbol_regime`을 그대로 전달)에
대해서였고, 시나리오 B(제안, `risk_tone="neutral"`로 치환한
regime)는 `_entry_score_non_alpha_terms`/`_non_alpha`라는 별도의
수작업 재구현 함수로만 계산해왔다.** 즉 "실제 함수를 직접 호출한
적이 없다"가 아니라 **"B 시나리오(neutral 치환) 입력으로는 직접
호출한 적이 없었다"**가 정확한 서술이다 — §45/§45.2가 처음으로
채운 것은 바로 이 좁은 간극이다.

### 46.2 정정 1 — "직접 호출 여부"와 "B 시나리오 조정항 정합성 검증"의 구분

- **[SPPV-2.57에서 정정]** §45.1의 "실제 운영 함수를 한 번도 직접
  호출한 적이 없었다"는 문장은 **부정확**하다. `_build_entry_score`
  는 시나리오 A(현행 regime)에 대해서는 이 세션의 여러 스크립트
  (`validate_alpha_layer_buy_funnel_comparison.py`,
  `validate_r3b_point_in_time_pipeline_shadow.py`)에서 이미 직접
  호출돼왔다.
- **정확한 표현**: "R3b+entry_score risk_off_penalty 제거(B
  시나리오, `risk_tone="neutral"`로 치환한 market_regime)를 실제
  `_build_entry_score`에 직접 전달해 호출한 적은 §45(SPPV-2.56)
  이전까지 없었다 — B 시나리오는 항상 별도의 수작업 재구현
  (`_entry_score_non_alpha_terms`/`_non_alpha`)으로만 근사돼왔다."
  §45가 새로 확인한 것은 이 B 시나리오 재구현이 실제 함수의
  neutral-regime 호출 결과와 정합하는지였다.

### 46.3 정정 2 — 이번 검증이 증명한 범위와 증명하지 않은 범위

**이번 SPPV-2.56 fidelity 검증이 실제로 증명한 것**: `source_type=
"core"`, `portfolio_allocation=None`, `risk_tone` neutral 치환
조건 아래에서, 수작업 재구현(non-alpha 조정 항: regime bonus/
penalty, strategy alignment bonus, relative-activity bonus)이
`_build_entry_score`의 동일 조건 조정 항 합계와 100.0%(58,493건
전체 시점 스냅샷 기준) 일치한다는 것.

**이번 검증이 아직 증명하지 않은 것**:
- **R3b alpha 교체 전체 경로**가 실제 운영 코드에 반영된 뒤에도
  entry_score 전체(alpha+조정 항 합, threshold 비교, funnel 선정
  까지)가 동일하게 재현되는지 — §45는 조정 항(non-alpha)만 분리해
  검증했고, R3b의 alpha 항(`candidate_percentile(regime_
  conditional_signal)` 기반) 자체가 실제 운영 코드 경로(예:
  `assess_deterministic_triggers` 전체 파이프라인, DB 기록, ranking
  로직과의 상호작용)에 삽입됐을 때 동일하게 동작하는지는 검증
  범위 밖이다.
- `source_type="held_position"`(보유 중 재평가) 또는 실제 `portfolio_
  allocation` 값이 있는 경우의 `_build_entry_score` 동작 — 이
  세션 전체가 `source_type="core"`, `portfolio_allocation=None`
  으로만 검증해왔으므로 이 두 조건에서 조정 항이 실제로 no-op이
  아닌 상황(held_position은 -0.35 패널티가 실제로 적용됨)은 이번
  검증에도, 이 세션의 다른 어떤 검증에도 포함되지 않았다.

**"B 시나리오 전체가 실제 운영 코드와 동일하다"는 표현은 위 두
가지 이유로 범위를 넘는다 — 정확한 표현은 "B 시나리오의 non-alpha
조정 항 계산은 실제 운영 함수와 검증된 조건 안에서 정합한다"이다.**

### 46.4 정정 3 — 검사 표본 서술

§45.3에서 "3년 전체 core 87종목 candidate 전량"이라고 쓴 표현은
부정확하다. `validate_r3b_entry_score_shadow_fidelity.py`의 루프는
quintile 상위 20% 선별이나 eligibility 필터링을 전혀 거치지 않고
`_MIN_LOOKBACK`부터 각 종목의 마지막 거래일까지 **모든 거래일**을
순회한다. 정확한 표현은 "3년 전체 core 87종목의 전체 시점 스냅샷
(모집단 전체, candidate로 좁히지 않음) 58,493건"이다. §45.3
본문은 이미 이번 턴에 정정했다(§45.3 참고).

### 46.5 판정에 대한 영향 — 표현 정정만, 판정 변경 없음

**R3b는 Conditional Go를 유지한다.** 위 세 가지 정정은 모두
**서술의 범위를 정확히 좁히는 것**이며, §45의 핵심 결론(B 시나리오
non-alpha 조정 항 계산이 실제 함수와 검증된 조건 안에서 완전히
일치한다는 것) 자체를 뒤집지 않는다 — 오히려 "정확히 무엇이
검증됐는지"를 명확히 함으로써 "entry_score 코드 반영 절차"가
"shadow 계산 정합성 확보" 단계에 있다는 §45.5의 판정을 그대로
지지한다. 필요 이상으로 보수적으로 낮추지 않는다 — §45가 실제로
검증한 좁은 범위(B 시나리오 조정 항, core/None 조건) 안에서는
100% 정합이 확인된 사실 그대로 유효하다. 신규 실행 없음(기존
코드·산출물 재검토만 수행), 신규 KIS 호출 0건, 운영 코드 변경
없음, broker submit 미호출.

### 46.6 §38 보조 잔여 조건 — 변경 없음(서술만 정밀화)

②보조 잔여 조건의 "entry_score 코드 반영 절차" 항목은 §45가 격상한
그대로 유지한다("설계 논의 단계"→"B 시나리오 non-alpha 조정 항의
shadow 계산 정합성 확보, 실제 코드 변경 PR 착수 검토 가능 단계") —
다만 남은 검증 범위(R3b alpha 교체 전체 경로의 실제 코드 반영 후
재현성, held_position/실제 portfolio_allocation 케이스)는 §46.3에서
명시한 대로 여전히 미검증 상태로 명확히 구분해 기록한다.

### 46.7 다음 단계

1. §21 게이트 정기 재모니터링(변경 없음).
2. entry_score risk_off_penalty 완화의 실제 코드 변경 PR 초안
   작성 착수 여부 사용자 확인(변경 없음, §45).
3. **(신규, 선택 사항) R3b alpha 교체 항까지 포함한 전체 entry_
   score 경로를 `assess_deterministic_triggers` 전체 파이프라인
   수준에서 재현 검증 — §45/§46이 다루지 않은 다음 확인 지점.**
4. exit 시점 손절이 아닌 포지션 사이징 검토(변경 없음, §44).
5. 국면 혼합도 강한 정합 증거를 실거래 반영 이후 모니터링 지표로
   삼을지 별도 설계 검토(변경 없음).
6. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 47. `§21 게이트`(regime_switch_v1) config 기반 gate 제어 — mode-agnostic 신규 모듈 구현 (SPPV-2.58, 2026-07-18)

- 작성자: Codex
- 수정일자: 2026-07-18

### 47.1 배경 — 코드베이스 확인 결과

작업 착수 전 코드베이스를 전수 조사한 결과, **`§21 게이트`(regime_
switch_v1)는 지금까지 실제 운영 코드 어디에도 연결돼 있지 않은
순수 모니터링 산출물**이었다. `scripts/monitor_regime_switch_v1_
gate.py`는 벤치마크 국면 분포를 계산해 TRIGGERED/PARTIAL/NOT_
TRIGGERED를 판정하고 JSON을 저장할 뿐(read-only), `deterministic_
trigger_engine.py`의 실제 운영 함수 `assess_deterministic_triggers`
에는 `regime_switch_v1`/게이트 관련 코드가 전혀 없다 — 즉 R3b
shadow/paper 관측은 이 게이트에 의해 지금까지 코드 레벨에서 전혀
막힌 적이 없다(이 세션 내내 실행된 §40~§46의 모든 검증 스크립트가
그 증거다). "§21 게이트가 주된 차단 요인"이라는 이 세션의 서술은
**정책·문서 해석**(SPPV-3 확정 반영 여부를 판단하는 기준)이었지,
코드가 무언가를 막고 있었던 것이 아니다.

이 사실을 사용자에게 확인한 뒤, 진행 방식을 좁혀 합의했다:
**`deterministic_trigger_engine.py`는 이 세션 내내 "절대 수정하지
않는다 — shadow/read-only만"이라는 원칙이 반복 확립된 파일이므로
이번 턴에도 건드리지 않는다.** 대신 config 기반 gate 판정 로직을
**신규 격리 모듈**로 구현하고, 실제 운영 파이프라인에는 아직 연결
하지 않은 채 shadow 스크립트로 동작을 검증한다. 향후 이 모듈을
실제 파이프라인에 연결하는 것은 별도의 명시적 승인·PR 절차를
거친다.

### 47.2 구현 내용

1. **`src/agent_trading/config/settings.py`**: `AppSettings`에 신규
   필드 `regime_switch_v1_gate_override_enabled: bool`(env:
   `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED`, 기본값 `False`) 추가.
   기존 코드베이스의 boolean 플래그 관례(`os.getenv(...,"false")` +
   `.strip().lower()=="true"`)를 그대로 따랐다. **`.env` 파일 자체는
   수정하지 않았다** — 미설정 시 기본값 `False`가 적용되므로 기존
   동작에 영향이 없다.
2. **`src/agent_trading/services/regime_switch_gate.py`**(신규 파일):
   `assess_regime_switch_v1_gate(*, trigger_status, override_enabled)`
   순수 함수. **paper/real/production 같은 environment 값은 이
   함수의 인자로도 로직으로도 전혀 등장하지 않는다** — 오직
   `override_enabled`(config 스위치)와 `trigger_status`(실제 국면
   관측치)만 본다. `override_enabled=False`(기본값)면 기존 §21
   게이트 해석과 완전히 동일하게 동작(TRIGGERED일 때만 열림).
   `override_enabled=True`면 실제 국면 상태와 무관하게 항상 열림
   (강제 통과) — 어느 경로든 `reason_code`(`gate_open_regime_
   switch_v1_triggered` / `gate_closed_regime_switch_v1_not_
   triggered` / `gate_open_config_override_bypass`)로 왜 이 판정이
   나왔는지 추적 가능하다.
3. **`deterministic_trigger_engine.py`는 전혀 수정하지 않았다** —
   신규 모듈은 그 파일에서 import되지 않으며, 이는 이번 검증
   스크립트에서 소스 코드 검사로 직접 확인했다(§47.4).

### 47.3 config 스위치 기반 동작 방식

| 조건 | `override_enabled` | 판정 방식 | 기존 동작과의 관계 |
|---|---|---|---|
| **기본값(미설정)** | `False` | `trigger_status == "TRIGGERED"`일 때만 `gate_open=True` | 기존 §21 게이트 해석과 100% 동일 |
| **명시적 override** | `True`(`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`) | `trigger_status`와 무관하게 항상 `gate_open=True` | 강제 통과, `reason_code`로 항상 추적 가능 |

paper/real 같은 실행 모드 값은 이 표 어디에도 등장하지 않는다 —
같은 `AppSettings`를 사용하는 두 실행(예: 오늘의 paper 검증, 향후
real 전환)에서 이 config 값을 동일하게 두면 게이트 동작도 동일
하다. 이것이 이번 구현의 핵심 — **environment-aware gating이
아니라 mode-agnostic config-aware gating**이다.

### 47.4 검증 내용 및 결과

`scripts/validate_regime_switch_gate_config_override.py`(신규,
read-only)로 4가지를 확인했다:

1. **운영 코드 격리**: `deterministic_trigger_engine.py`의 소스를
   직접 검사(`inspect.getsource`)해 `regime_switch_gate` 문자열이
   전혀 등장하지 않음을 확인 — **결과: `isolation_confirmed=True`**
   (그 파일을 실제로 수정하지 않았다는 코드 레벨 증거).
2. **실제 §21 게이트 상태 조회**(벤치마크 1종목, 캐시 재사용, 신규
   KIS 호출 0건): **`trigger_status=NOT_TRIGGERED`**(최근 12개월
   bearish_trend 0일 — §21 게이트 상태 자체는 이전 턴들과 동일하게
   불변).
3. **override off/on 시나리오**(실제 관측치 `NOT_TRIGGERED` 기준):
   - override off: `gate_open=False`, `reason_code=gate_closed_
     regime_switch_v1_not_triggered` — 기존 해석과 동일(게이트
     닫힘).
   - override on: `gate_open=True`, `reason_code=gate_open_config_
     override_bypass` — config만으로 강제 통과.
4. **3개 trigger_status 전부에 대한 합성 시나리오**: override off일
   때는 `TRIGGERED`만 `gate_open=True`(PARTIAL/NOT_TRIGGERED는
   `False`) — 기존 해석과 완전히 일치. override on일 때는 3개
   상태 전부 `gate_open=True` — override가 국면 상태를 완전히
   무시함을 확인.

### 47.5 해석 — operational 의미

**단순 통과율 상승이 아니라, "게이트를 어떻게 다룰지"를 코드로
명시적으로 통제 가능하게 만든 것**이 이번 변경의 의미다. §21 게이트
자체는 이번에도 여전히 코드 레벨에서 아무것도 막고 있지 않았다는
사실이 재확인됐다(§47.1) — 따라서 "R3b 신호가 이제 막히지 않고
통과할 수 있게 됐다"는 것은 **이번 변경 때문이 아니라 애초부터
그랬다.** 이번 변경이 실질적으로 만든 것은 (a) 향후 이 게이트를
실제 파이프라인에 연결하기로 결정했을 때, environment 분기 없이
config 하나로 안전하게 켜고 끌 수 있는 **준비된 격리 모듈**, (b)
그 판정 근거(reason_code)를 로그/diagnostics로 추적할 수 있는
구조다. R3b shadow/paper 관측 자체의 가능 여부는 이번 변경 전후로
바뀌지 않았다(원래도 가능했다) — 다만 **"게이트를 실제로 켠 뒤에도
override로 통과시킬 수 있는 안전장치"가 최초로 코드에 준비됐다**는
점이 새로운 진전이다.

### 47.6 판정 — Conditional Go 유지, "entry_score 코드 반영 절차"와 별개로 "§21 게이트 코드화 준비" 신규 항목 완료

**R3b는 Conditional Go를 유지한다.** 이번 턴은 §38의 보조 잔여
조건도, §21 게이트(주된 차단 요인) 상태 자체도 바꾸지 않는다 — §21
게이트는 여전히 `NOT_TRIGGERED`다. 다만 "§21 게이트를 코드 레벨
에서 config로 통제 가능하게 만드는 준비"라는 **신규 인프라 작업**
이 완료됐다 — 이는 향후 게이트가 TRIGGERED되거나, 사용자가 명시
적으로 override를 승인하는 시점에 environment 분기 없이 안전하게
전환할 수 있는 기반이다. compliance/VaR/broker submit 경계는
전혀 건드리지 않았고, `deterministic_trigger_engine.py`도 수정
하지 않았다. 신규 KIS 호출 0건.

### 47.7 남은 리스크·제약

- 이 모듈은 아직 실제 파이프라인에 연결되지 않았다 — 연결 자체는
  `deterministic_trigger_engine.py` 수정을 필요로 하며, 이는 이
  세션의 shadow-only 원칙을 깨는 별도의 명시적 결정을 요한다.
- override가 켜진 상태로 실제 파이프라인에 연결될 경우, §21 게이트
  가 실제로 의미했던 "하락장 검증 미비 상태에서의 진입 보류"라는
  안전장치가 무력화된다는 점을 사용자가 명확히 인지해야 한다 —
  이 스위치는 강력한 안전핀이므로, 연결 시점에는 반드시 별도의
  리스크/컴플라이언스 검토를 거쳐야 한다.
- `trigger_status`를 최신 값으로 유지하려면 `monitor_regime_switch_
  v1_gate.py`를 정기 실행해 그 결과를 이 신규 모듈에 전달하는 배선
  작업이 별도로 필요하다(이번 턴은 그 배선 자체는 만들지 않았다 —
  파이프라인 연결 전 단계이므로).

## 48. `§21 게이트` 실제 판단 경로 연결 완료 — `deterministic_trigger_engine.py` 실제 수정 (SPPV-2.59, 2026-07-18)

- 작성자: Codex
- 수정일자: 2026-07-18

### 48.1 직전 SPPV-2.58 보고 정정 — "구현 완료"가 아니라 "준비 모듈 + 런타임 미연결"

**[SPPV-2.59에서 정정]** §47(SPPV-2.58)의 결론 "판정: R3b는
Conditional Go를 유지한다" 자체는 틀리지 않았으나, 그 turn을 "§21
게이트 코드 반영 완료"로 서술한 것은 부정확했다 — 정확히는 **"config
스위치와 순수 판정 함수(`services/regime_switch_gate.py`)를 준비
했을 뿐, 실제 소비 경로(`assess_deterministic_triggers`)에는 연결
하지 않은 상태"**였다. §47.4의 검증(`validate_regime_switch_gate_
config_override.py`)도 고립된 함수 호출만 확인했을 뿐, 실제 BUY
판정 경로에서 override가 소비되는지는 증명하지 못했다. 이번 턴이
그 미완 지점을 메운다.

### 48.2 이번 턴에서 실제로 연결한 경로

**`src/agent_trading/services/deterministic_trigger_engine.py`를
실제로 수정했다** — 이 세션 전체에서 가장 무거운 제약("절대 수정
금지")을 사용자의 명시적 승인 아래 이번 턴에 한해 해제했다(코드
확인 결과 R3b는 이 세션 내내 실제 운영 코드에 한 번도 반영된 적이
없었고, "§21 게이트가 실제로 막는 R3b 경로" 자체가 지금까지
존재하지 않았다는 사실을 사용자에게 재확인시킨 뒤 진행).

1. `assess_deterministic_triggers`(BUY_CANDIDATE를 실제로 결정하는
   운영 함수, 실제 주문 결정과 직결)에 신규 optional 파라미터 2개
   추가:
   - `regime_switch_v1_trigger_status: str | None = None`
   - `regime_switch_v1_gate_override_enabled: bool = False`
   **기본값이 둘 다 "게이트 체크 비활성화"에 해당** — 이 파라미터를
   모르는 기존 호출부는 100% 이전과 동일하게 동작한다(하위 호환
   보장).
2. `regime_switch_v1_trigger_status`가 명시적으로 제공되면,
   `assess_regime_switch_v1_gate(trigger_status=..., override_
   enabled=...)`(§47의 순수 함수, 그대로 재사용)를 호출해 결과를
   `regime_switch_v1_gate_assessment`에 담고, 그 `reason_code`를
   `reason_codes`에 추가한다.
3. **BUY_CANDIDATE 판정 조건문(240행대)에 실제로 게이트를 연결**:
   ```python
   if (
       eligibility_passed
       and entry_score >= thresholds["buy_candidate_threshold"]
       and allocation_budget_ok
       and (
           regime_switch_v1_gate_assessment is None
           or regime_switch_v1_gate_assessment.gate_open
       )
   ):
       buy_candidate = True
   ```
   `regime_switch_v1_trigger_status=None`(파라미터 미제공)이면 이
   조건은 항상 `True`로 평가돼(변경 전과 동일) 아무 영향이 없다.
   파라미터가 제공되고 게이트가 닫혀 있으면(override 없이 NOT_
   TRIGGERED) `buy_candidate`가 실제로 `False`로 강제된다.
4. `metadata` 딕셔너리에 `regime_switch_v1_gate_open`,
   `regime_switch_v1_gate_override_applied` 진단 필드 추가 — 어느
   경로로 판정됐는지 항상 추적 가능.
5. `paper`/`real`/`production` 같은 environment 값은 이 함수 어디
   에도 참조되지 않는다 — 오직 호출자가 전달한 `regime_switch_v1_
   gate_override_enabled`(config 값) 하나만 본다(mode-agnostic).

### 48.3 override off/on에서 실제 판단 경로가 어떻게 달라지는가

`scripts/validate_r3b_gate_integration_path.py`(신규, read-only)로
**동일한 실제 함수 `assess_deterministic_triggers`**를 3가지 방식
으로 직접 호출해 확인했다:

| 호출 | 파라미터 | 결과 |
|---|---|---|
| **A(baseline)** | 게이트 파라미터 없음(기존 호출부와 동일한 방식) | `buy_candidate=True`, `entry_score=0.6895` |
| **B(게이트 활성, override off)** | `trigger_status="NOT_TRIGGERED"`, `override_enabled=False`(기본값) | `buy_candidate=False`(BUY_CANDIDATE 태그 사라짐), `regime_switch_v1_gate_open=False`, reason_codes에 `gate_closed_regime_switch_v1_not_triggered` 추가 |
| **C(게이트 활성, override on)** | 동일 trigger_status, `override_enabled=True` | `buy_candidate=True`(baseline과 동일하게 복원), `regime_switch_v1_gate_open=True`, reason_codes에 `gate_open_config_override_bypass` 추가 |

실제 발견된 candidate: `000100 / 2023-10-11`(3년 캐시 재사용, 신규
KIS 호출 0건). B에서 `entry_score`(0.6895)와 `eligibility_passed`
는 A와 완전히 동일하게 유지되면서도 **오직 게이트 조건 하나 때문에**
`buy_candidate`가 뒤집혔다 — 이는 게이트가 (a) entry_score/
eligibility 계산 자체는 건드리지 않고, (b) 최종 BUY_CANDIDATE
결정 단계에서만 별도의 독립적인 관문으로 작동한다는 것을 보여준다.

### 48.4 실측 결과 해석

- **`gate_actually_blocks_real_path = True`**: 실제 운영 함수가,
  실제로 존재하는 코드 조건문을 통해, 실제로 BUY_CANDIDATE 판정을
  차단했다 — §47까지는 이것이 증명되지 않았다(고립된 순수 함수
  호출만 확인했었다). 이번에는 `assess_deterministic_triggers`
  자체를 호출해 그 반환값(`DeterministicTriggerAssessment.
  buy_candidate`)이 바뀌는 것을 직접 확인했다.
- **`override_actually_restores_real_path = True`**: 같은 실제
  함수에서, config 스위치 하나(`override_enabled=True`)만 바꿔
  다시 호출하니 baseline과 완전히 동일한 결과(`buy_candidate=
  True`)로 복원됐다 — environment 값은 이 과정에서 전혀 등장하지
  않았다(mode-agnostic이 실제 코드 레벨에서 검증됨).
- **operational 의미**: 이는 단순 통과율 상승이 아니라, **"§21
  게이트를 실제로 켰을 때, R3b(또는 다른 candidate)의 진입 판단이
  게이트에 의해 실제로 살아나거나 죽는 스위치가 실제 코드에
  생겼다"**는 뜻이다. 기존 호출부(현재 운영에서 실제로 쓰이는
  모든 호출 지점)는 이 파라미터를 전달하지 않으므로 **지금 당장
  실제 운영 동작은 전혀 바뀌지 않는다** — 이 스위치가 실제 효과를
  내려면 향후 호출부(예: 실제 BUY 판정을 만드는 상위 orchestrator)
  에서 `regime_switch_v1_trigger_status`를 명시적으로 전달하도록
  별도 배선해야 한다(§48.6).

### 48.5 판정 — Conditional Go 유지, "실제 경로 연결" 완료(단, 실제 운영 호출부 배선은 별도)

**R3b는 Conditional Go를 유지한다.** 이번 턴으로 "§21 게이트 →
실제 판단 경로" 연결이 **완료**됐다 — §47의 "준비 모듈"에서 §48의
"실제 함수에 실제로 연결되고, 실제 함수 호출로 그 효과가 검증된
상태"로 격상됐다. 다만 **완전한 연결**은 두 층위로 나뉜다: (1)
`assess_deterministic_triggers` 함수 자체의 게이트 로직 — **완료**.
(2) 실제 운영에서 이 함수를 호출하는 상위 계층(orchestrator/
decision loop)이 `regime_switch_v1_trigger_status`를 실제로
전달하도록 배선하는 것 — **아직 미완료**(§48.6). (2)가 완료되기
전까지는 이번 변경이 실제 운영 동작에 영향을 주지 않는다(기존
호출부가 신규 파라미터를 모르기 때문) — 이는 의도된 안전장치다.
compliance/VaR/broker submit 경계는 전혀 건드리지 않았다. 신규 KIS
호출 0건. 기존 단위 테스트(`tests/services/test_deterministic_
trigger_engine.py`, 20건)는 수정 후에도 전부 통과했다(하위 호환
확인).

### 48.6 남은 리스크·제약

- **실제 운영 호출부 배선 미완료**: `assess_deterministic_triggers`
  를 실제로 호출하는 상위 코드(예: `run_decision_loop.py` 등)가
  `regime_switch_v1_trigger_status`를 전달하지 않으면, 이번 변경은
  실제 운영에서 **아무 효과도 내지 않는다**(파라미터 기본값 None →
  게이트 체크 완전 비활성화). 이는 되돌릴 수 있는 안전한 상태이지만,
  "완전히 연결됐다"고 보려면 이 배선까지 마쳐야 한다 — 이번 턴
  범위 밖으로 남긴다(그 배선 자체가 실시간 국면 관측치 소스를
  결정하는 별도의 설계 결정을 요하기 때문).
- **`trigger_status` 소스 미정**: 이번 검증은 `trigger_status`를
  스크립트가 직접 문자열로 전달했다 — 실제 운영에서는 이 값을 어디
  서(정적 캐시 vs 매 호출 실시간 계산 vs 별도 백그라운드 잡) 가져올
  지 결정해야 한다.
- override가 실제 파이프라인에 연결되고 켜진 상태에서는, §21 게이트
  가 의도했던 "하락장 검증 미비 상태에서의 진입 보류" 안전장치가
  무력화된다는 점은 §47.7과 동일하게 유효하다 — 배선 완료 시점에는
  반드시 별도의 리스크/컴플라이언스 재검토가 필요하다.
- `deterministic_trigger_engine.py`를 실제로 수정한 것은 이 세션
  전체에서 최초의 예외이며, 이후 이 파일에 대한 추가 변경은 매번
  별도로 명시적 승인을 받아야 한다(이번 승인이 일반화된 상시
  허가로 확대 해석되지 않는다).

## 49. `§21 게이트` 상위 호출부(`decision_orchestrator.py`) 배선 완료 (SPPV-2.60, 2026-07-18)

- 작성자: Codex
- 수정일자: 2026-07-18

### 49.1 직전 SPPV-2.59 보고 정정 — "실제 판단 경로 연결 완료"는 과장

**[SPPV-2.60에서 정정]** §48(SPPV-2.59)의 결론 "§21 게이트 → 실제
판단 경로 연결이 완료됐다"는 부정확했다. 검수 결과 정확한 상태는:

1. `deterministic_trigger_engine.py`의 `assess_deterministic_
   triggers` **함수 내부**에는 게이트 파라미터·분기 로직이 이미
   들어가 있었다(§48에서 완료) — 이는 맞다.
2. 그러나 이 함수를 실제로 호출하는 **유일한 상위 호출부**
   `src/agent_trading/services/decision_orchestrator.py`의
   `DecisionOrchestratorService._derive_deterministic_context_
   components`(`assess_deterministic_triggers` 호출부)는 신규
   파라미터(`regime_switch_v1_trigger_status`/`regime_switch_v1_
   gate_override_enabled`)를 **전혀 넘기지 않고 있었다** —
   `DecisionOrchestratorService.__init__`도 이 값을 받는 생성자
   인자가 없었다.

즉 §48 시점에는 "함수는 게이트를 이해하지만, 실제로 그 함수를 부르는
운영 코드는 그 사실을 몰랐다"는 상태였다 — "실제 판단 경로 연결
완료"라고 부르기엔 이르다. 이번 턴이 그 gap을 메운다.

### 49.2 실제 상위 호출 경로 배선 수정 내용

1. **`src/agent_trading/services/decision_orchestrator.py`**:
   - `DecisionOrchestratorService.__init__`에 신규 keyword-only
     생성자 인자 2개 추가: `regime_switch_v1_trigger_status: str |
     None = None`, `regime_switch_v1_gate_override_enabled: bool =
     False`(둘 다 기본값 그대로면 게이트 체크 완전 비활성화 —
     기존 생성 코드는 100% 무영향).
   - `self._regime_switch_v1_trigger_status`, `self._regime_
     switch_v1_gate_override_enabled`로 저장.
   - `_derive_deterministic_context_components`의 `assess_
     deterministic_triggers(...)` 호출에 이 두 값을 실제로 전달하는
     코드 추가(유일한 호출부, 다른 곳에서 이 함수를 부르는 코드는
     `src/agent_trading/**` 전체에 없음을 사전 조사로 확인).
2. **`scripts/run_decision_loop.py`**(실제 운영 decision loop, 실제
   주문 경로로 이어지는 스크립트): `DecisionOrchestratorService`를
   생성하는 **두 지점 전부**(core risk-off top-k 사전계산 헬퍼,
   메인 per-symbol 결정 루프)에서 새 인자를 실제로 전달하도록 수정:
   ```python
   orchestrator = DecisionOrchestratorService(
       repos=repos,
       ...,
       regime_switch_v1_trigger_status=resolve_cached_trigger_status(),
       regime_switch_v1_gate_override_enabled=(
           settings.regime_switch_v1_gate_override_enabled
       ),
   )
   ```
3. **`src/agent_trading/services/regime_switch_gate.py`**: 신규
   함수 `resolve_cached_trigger_status()` 추가 — `scripts/monitor_
   regime_switch_v1_gate.py`가 이미 저장해온 `logs/regime_switch_
   v1_gate_monitor_*.json`(가장 최근 mtime) 산출물에서 `trigger_
   status`를 읽는 **read-only 파일 접근 헬퍼**다. 매 결정마다
   신규 KIS 호출을 만들지 않기 위한 선택 — 파일이 없거나 파싱
   실패 시 `None`을 반환해 게이트 체크를 안전하게 건너뛴다(=기존
   동작과 동일).
4. paper/real/production 같은 environment 값은 이번에도 어디에도
   참조하지 않았다(`decision_orchestrator.py`, `run_decision_loop.
   py`, `regime_switch_gate.py` 모두) — 오직 `settings.regime_
   switch_v1_gate_override_enabled`(config)와 파일에서 읽은
   `trigger_status`(실측)만 사용한다.

### 49.3 override off/on에서 상위 호출 경로 결과가 어떻게 달라지는가

`scripts/validate_r3b_orchestrator_gate_wiring.py`(신규, read-only,
in-memory repos, 신규 KIS 호출 0건)로 **`DecisionOrchestratorService`
를 실제로 구성**하고 그 실제 메서드 `_derive_deterministic_context_
components`(`assess_deterministic_triggers`가 아니라 이 메서드를
호출 — 즉 `decision_orchestrator.py`를 실제로 거친 경로)를 통해
검증했다:

| 호출 | `DecisionOrchestratorService` 생성 시 전달값 | 결과(같은 강한 bullish 시나리오, entry_score=0.7275) |
|---|---|---|
| **A(baseline)** | 게이트 인자 없음(기존 생성 코드와 동일) | `buy_candidate=True`, `regime_switch_v1_gate_open=None` |
| **B(게이트 활성, override off)** | `trigger_status="NOT_TRIGGERED"`, `override_enabled=False`(기본값) | `buy_candidate=False`(실제 차단), `gate_open=False`, reason_codes에 `gate_closed_regime_switch_v1_not_triggered` |
| **C(게이트 활성, override on)** | 동일 trigger_status, `override_enabled=True` | `buy_candidate=True`(baseline과 동일 복원), `gate_open=True`, reason_codes에 `gate_open_config_override_bypass` |

`gate_blocks_via_orchestrator=True`, `override_restores_via_
orchestrator=True` — §48이 스크립트에서 `assess_deterministic_
triggers`를 직접 호출해 확인한 것과 동일한 효과가, **이번에는
`DecisionOrchestratorService`(실제 상위 호출부)를 실제로 구성하고
그 인스턴스 메서드를 거쳐서도** 재현됨을 확인했다.

### 49.4 실측 결과 해석

- 이는 §48의 "함수 단독 테스트"와 질적으로 다르다 — 이번에는
  **실제 생성자(`__init__`)에 파라미터가 실제로 전달되고, 그 값이
  인스턴스 속성에 저장되고, 실제 인스턴스 메서드가 그 속성을 실제로
  읽어 하위 함수에 전달하는 전체 배선**이 검증됐다. `assess_
  deterministic_triggers`를 스크립트가 직접 호출하는 우회 경로가
  전혀 아니다.
- `resolve_cached_trigger_status()`는 호스트 저장소 기준 실제로
  `NOT_TRIGGERED`를 반환한다(§45.3~§47.4에서 반복 확인된 실제 §21
  게이트 상태와 일치) — 즉 `run_decision_loop.py`가 지금 이 순간
  실행된다면(실제로는 override가 기본값 False이므로) 이 게이트
  로직 자체는 **아직 아무것도 새로 차단하지 않는다** — 왜냐하면
  `run_decision_loop.py`의 실제 호출에서 `regime_switch_v1_
  gate_override_enabled=settings.regime_switch_v1_gate_override_
  enabled`가 기본값(`False`)이고, `regime_switch_v1_trigger_
  status`가 채워지긴 하지만(NOT_TRIGGERED), **이 조합에서 게이트는
  닫힌다**(TRIGGERED가 아니므로) — 이 부분은 §49.5에서 명확히
  다룬다.

### 49.5 판정 — Conditional Go 유지, **이번 변경 자체는 실제 BUY_CANDIDATE에 영향을 준다는 점을 명확히 인지해야 함**

**중요**: §48까지는 게이트 파라미터가 기본값(`None`/`False`)이라
실제 운영에 전혀 영향이 없었다. **그러나 이번 §49의 배선 완료로
상황이 바뀌었다** — `run_decision_loop.py`가 이제 `resolve_cached_
trigger_status()`를 통해 **실제로 `"NOT_TRIGGERED"`를 읽어 `assess_
deterministic_triggers`에 전달**하고, `override_enabled`은 여전히
기본값 `False`이므로, **`assess_regime_switch_v1_gate`가 게이트를
닫힌 것으로 판정하게 된다(TRIGGERED가 아니므로)** — 이는 §21
게이트가 **이제 실제로 core BUY_CANDIDATE 판정에 영향을 미치기
시작했다는 뜻**이다(단, 정확히는 "닫는" 것이 원래의 "혼합 국면에서도
R3b를 계속 관측"하려던 의도와 어긋날 수 있다 — 이는 §49.6에서 남긴
리스크로 명시한다). **판정을 되돌리지 않고, 대신 이 사실을 명확히
기록한다.** R3b 자체는 여전히 운영 entry_score 코드에 반영되지
않았으므로(§45~§47) 이 게이트가 실제로 막는 것은 R3b가 아니라
"core BUY_CANDIDATE 판정 전반"이라는 점도 함께 유의해야 한다 — §21
게이트는 candidate 종류를 구분하지 않고 `source_type != "held_
position"`인 모든 BUY 판정에 적용된다(§48.2의 조건문 위치 참고).
compliance/VaR/broker submit 경계는 전혀 건드리지 않았다. 신규 KIS
호출 0건. 기존 단위 테스트(`test_decision_orchestrator.py` 63건 +
`test_deterministic_trigger_engine.py` 20건, 총 83건) 전부 통과.

### 49.6 남은 리스크·제약 — 반드시 확인 필요

- **이번 배선 완료로 인한 실제 동작 변화 가능성**: §49.4/§49.5에서
  확인했듯, `run_decision_loop.py`를 다음에 실행하면 `resolve_
  cached_trigger_status()`가 캐시 파일이 있는 한 실제 `NOT_
  TRIGGERED`를 반환하고, `override_enabled`는 기본값 `False`이므로
  **게이트가 닫힌 것으로 판정돼 core BUY_CANDIDATE가 차단될 수
  있다** — 이는 이번 배선 이전에는 없던 새로운 실제 동작 변화다.
  사용자가 이를 원치 않는다면 `REGIME_SWITCH_V1_GATE_OVERRIDE_
  ENABLED=true`로 설정하거나, 이 배선 자체를 되돌리는 결정이
  필요하다 — **이 판단은 다음 턴/사용자 확인 사항으로 명시적으로
  남긴다.**
- **`resolve_cached_trigger_status()`의 파일 의존성**: 이 함수는
  `logs/regime_switch_v1_gate_monitor_*.json`이 존재해야 값을
  반환한다 — 이 파일은 `scripts/monitor_regime_switch_v1_gate.py`
  를 수동/배치로 실행해야 갱신된다. 자동 갱신 스케줄은 이번 턴
  범위 밖이다(정기 실행 cron/배치는 별도 설계 필요).
- `deterministic_trigger_engine.py`에 이어 `decision_orchestrator.
  py`/`run_decision_loop.py`도 이번에 실제로 수정했다 — 이 세션
  전체에서 "절대 수정 금지" 원칙의 두 번째·세 번째 예외이며, 이후
  추가 변경은 매번 별도 승인이 필요하다.

## 50. SPPV-2.60 보고 정정 — `resolve_cached_trigger_status()` None 원인 규명 + 테스트 증빙 재확인 (SPPV-2.61, 2026-07-18)

- 작성자: Codex
- 수정일자: 2026-07-18

### 50.1 정정 대상 — 직전 SPPV-2.60 보고의 두 모순

**[SPPV-2.61에서 정정]** §49(SPPV-2.60)의 검증 산출물
(`logs/signal_ic_r3b_orchestrator_gate_wiring_2026-07-18.json`)에서
`resolve_cached_trigger_status_current_value`가 `None`으로 기록돼
있었다 — 그러나 그 시점에도 이미 `logs/regime_switch_v1_gate_
monitor_2026-07-14.json`, `logs/regime_switch_v1_gate_monitor_
2026-07-17.json` 두 파일 모두 `trigger_status="NOT_TRIGGERED"`를
담고 있었다. 또한 §49는 "기존 단위 테스트 83건 전부 통과"라고
서술했으나, 그 turn에서 실행 로그를 별도로 저장하지 않아 산출물
만으로는 그 실행 증거가 남아있지 않았다. 이번 턴은 이 두 지점을
규명·정정한다.

### 50.2 원인 규명 — `None`의 실제 원인은 코드 결함이 아니라 cwd 의존 경로

코드를 직접 재검토한 결과, `resolve_cached_trigger_status()`의
`glob`/JSON 파싱/status 검증 로직 자체에는 결함이 없었다 — **원인은
기본 `glob_pattern`이 상대경로("logs/regime_switch_v1_gate_
monitor_*.json")였고, 이 상대경로가 호출 시점의 현재 작업 디렉터리
(cwd)를 기준으로 해석된다는 점**이었다. §49의 검증 스크립트는
Docker 컨테이너 안에서 실행됐는데, 그 컨테이너의 `/app/logs/`
디렉터리에는 이 두 모니터링 JSON 파일이 복사돼 있지 않았다(스크립트
실행 전 `_bars_cache_core87_3y_2026-07-14` 캐시만 복사했을 뿐, 이
두 파일은 별도로 복사하지 않았다) — 그래서 `glob.glob(pattern)`이
빈 리스트를 반환했고, 함수는 정확히 설계된 대로 `None`을 반환했다.
**즉 함수 자체는 "파일이 없으면 None"이라는 명세대로 정확히
동작했다 — 문제는 그 실행 환경(cwd/파일 배치)이었다.**

다섯 후보(glob 경로, cwd 의존성, 파일 선택 로직, JSON 파싱, status
validation) 중 **cwd 의존성**이 정확한 원인이었다: 파일 선택 로직
(`max(matches, key=os.path.getmtime)`)과 JSON 파싱, status
validation은 모두 정상이었고, glob 패턴 문자열 자체도 오타가 없었다
— 다만 상대경로였기 때문에 실행 위치에 따라 결과가 달라질 수
있었다.

### 50.3 수정 내용

`src/agent_trading/services/regime_switch_gate.py`의
`resolve_cached_trigger_status()`를 최소 침습으로 수정했다:

- 모듈 상단에 `_PROJECT_ROOT = Path(__file__).resolve().parents[3]`
  추가 — 이 파일 위치(`<root>/src/agent_trading/services/regime_
  switch_gate.py`) 기준으로 프로젝트 루트를 고정한다(코드베이스의
  기존 관례, `db/migrations/run.py`와 동일한 패턴).
- `glob_pattern` 파라미터의 기본값을 `None`으로 바꾸고, `None`이면
  `_PROJECT_ROOT / "logs" / "regime_switch_v1_gate_monitor_*.json"`
  (절대경로)을 사용하도록 변경 — **cwd와 무관하게 항상 프로젝트
  루트의 `logs/` 디렉터리를 본다.** 명시적으로 `glob_pattern`을
  넘기는 호출자는(하위 호환) 그 값을 그대로 사용한다.
- `paper`/`real`/`production` 분기는 추가하지 않았다 — 이 수정은
  순수하게 "상대경로를 절대경로로 바꾼 것"뿐이며 config 스위치
  기반 게이트 제어 원칙은 그대로 유지된다.

### 50.4 재검증 — 수정 후 실제 결과

1. **`resolve_cached_trigger_status()` 단독 검증**: 수정 전에는
   `/tmp`(비-프로젝트 cwd)에서 호출하면 `None`을 반환했다. 수정
   후에는 `/tmp`에서 호출해도 **`NOT_TRIGGERED`**를 정확히
   반환한다(프로젝트 루트 기준 절대경로이므로 cwd와 무관). 프로젝트
   루트 cwd에서도 동일하게 `NOT_TRIGGERED`.
2. **Docker 컨테이너 안에서 재검증**: 두 모니터링 JSON 파일을
   컨테이너의 `/app/logs/`에 실제로 복사한 뒤 `scripts/validate_
   r3b_orchestrator_gate_wiring.py`를 재실행한 결과, `resolve_
   cached_trigger_status_current_value`가 **`"NOT_TRIGGERED"`**
   로 정확히 기록됐다(이전 §49 실행 시의 `None`과 대비). A/B/C
   3개 시나리오(게이트 없음/override off/override on) 결과는
   §49와 동일 — `gate_blocks_via_orchestrator=true`, `override_
   restores_via_orchestrator=true`.
3. **테스트 증빙**: `python3 -m pytest tests/services/test_
   decision_orchestrator.py tests/services/test_deterministic_
   trigger_engine.py -q`를 Docker 컨테이너 안에서 실제로 실행하고
   그 stdout을 `logs/r3b_pytest_run_2026-07-18.log`로 저장했다 —
   **`83 passed`**(63+20)를 실제 실행 로그로 확인. §49의 "83건
   전부 통과"라는 서술 자체는 사실과 일치했으나(현재 재실행으로
   재확인됨), 그 turn 안에서는 실행 로그가 산출물로 남아있지 않아
   문구만으로는 검증 불가능한 상태였다 — 이번 턴에 그 증빙을
   보강했다.

### 50.5 판정 — Conditional Go 유지, "캐시 상태까지 정상 전달됨"으로 확정

**R3b는 Conditional Go를 유지한다.** §49의 배선 자체(코드 구조)는
정확했다 — 실제 결함은 `resolve_cached_trigger_status()`의 기본
경로가 cwd 의존적이었다는 점 하나였고, 이번 턴에 그 결함을 최소
수정으로 고쳐 **"캐시 상태까지 정상 전달됨"**을 확정했다(이전에는
"배선은 완료됐으나 캐시 상태 전달에는 추가 수정이 필요"한 상태
였다). 이는 §49.5/§49.6에서 이미 명시한 리스크(override 기본값
False + trigger_status="NOT_TRIGGERED" 조합에서 core BUY_CANDIDATE
가 실제로 차단될 수 있다는 것)를 약화시키지 않는다 — 오히려 이번
수정으로 그 리스크가 **cwd에 관계없이 항상 실현 가능**해졌다는
뜻이므로, §49.6의 "override를 켤지 또는 배선을 되돌릴지 사용자
확인" 요구는 이번 턴으로 더 급해졌다. compliance/VaR/broker
submit 경계는 전혀 건드리지 않았다. 신규 KIS 호출 0건.

### 50.6 남은 리스크·제약

- §49.6에서 이미 명시한 리스크(override 기본값 상태에서 core
  BUY_CANDIDATE가 실제로 차단되기 시작함)는 이번 턴으로 **더 확실히
  실현 가능**해졌다 — cwd 의존 버그가 고쳐졌기 때문에, 이제
  `run_decision_loop.py`를 어떤 작업 디렉터리에서 실행하더라도 캐시
  된 게이트 상태가 정확히 전달된다. **사용자가 override를 켤지
  (`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`) 또는 이 배선
  자체를 되돌릴지 결정하는 것이 여전히 최우선 미결 사항이다.**
- `logs/regime_switch_v1_gate_monitor_*.json` 캐시의 정기 자동
  갱신(cron/배치)은 여전히 이번 턴 범위 밖이다 — 수동으로
  `scripts/monitor_regime_switch_v1_gate.py`를 재실행해야 최신
  상태로 갱신된다.

### 50.7 운영 결정 고정

사용자 결정에 따라 **게이트 배선은 유지하고, paper/shadow 관측
단계에서는 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true` 상태로
커밋/운영**한다. 이는 code path를 paper/production으로 분기하는 것이
아니라, 동일한 코드에 대해 명시적 config override만 적용하는 방식이다.
production 전환 전에는 override를 제거(또는 False 복귀)한 상태에서
§21 게이트를 다시 잠그고 재검토한다.

`trigger_status`를 어디서 공급할지(정적 파일/배치 갱신/실시간 연결)는
이번 턴에서 닫지 않는다. 이는 **후속 과제**로 남기며, 현재는 기존
캐시 JSON을 read-only로 읽는 경로를 유지한다.

## 51. 국면 혼합도 모니터링 모듈 구현 및 §40 재현성 검증 (SPPV-2.62, 2026-07-18)

- 작성자: Codex
- 수정일자: 2026-07-18

### 51.1 왜 이 항목을 골랐는가

commit `aa10caee`로 `§21 게이트` 배선이 완료됐고, 현재 `.env`에는
`REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`가 설정돼 있어 paper
관측 단계에서 게이트는 BUY를 막지 않는다. 이 상태를 최신 truth로
확정한 뒤, "이미 답이 나온 질문을 반복하지 않고, 창 교체 이후 실제
운영 전진에 직접 기여하는" 다음 항목을 선택했다.

후속 과제 후보 4개(`trigger_status` 공급원 자동화, 혼합도 모니터링
설계, T+5/경로 리스크 후속 검증, SPPV-3 착수 준비) 중 **혼합도
모니터링 설계**를 골랐다 — 이유: (1) `trigger_status` 자동화는
현재 override=true라 당장 급하지 않다(게이트가 이미 열려 있어
trigger_status 값 자체가 실질적 영향을 안 준다). (2) T+5/경로
리스크는 §41~§44에서 이미 충분히 답이 나온 질문이라 반복이 될
위험이 있다. (3) 혼합도 모니터링은 §40.5/§40.7이 "다음 단계"로
명시했으나 지금까지 **설계 스케치만 있었을 뿐 실제 소비 가능한
코드가 없었다** — 이번 턴에 그 gap을 메우면 창 교체(R3b)의 실제
운영 전진에 직접 기여하는 신규 산출물이 생긴다. (4) 기존 3년 bars
캐시(`logs/_bars_cache_core87_3y_2026-07-14/069500.json`)만으로
100% read-only 검증 가능해 신규 KIS 호출이 전혀 필요 없었다.

### 51.2 구현 내용

**신규 모듈 `src/agent_trading/services/regime_mixedness_
monitor.py`**: §40(SPPV-2.50)이 3년 634거래일에서 확정한 혼합도
3분위 경계값(`MIXEDNESS_TERCILE_CUT1=0.1500`, `MIXEDNESS_TERCILE_
CUT2=0.3833`)을 그대로 상수화하고, 두 개의 순수 함수를 제공한다:

- `compute_mixed_score(trailing_labels, min_window=20)`: 최근
  60거래일(§40과 동일 window) 시장 공통 국면 라벨의 `mixed_score =
  1 - (최빈 라벨 비중)`을 계산.
- `classify_mixedness_bucket(mixed_score)`: 저혼합/중혼합/고혼합
  3분위로 분류하고, 각 버킷의 §40 실측 신뢰도(저혼합 t_NW=3.64 강한
  유의성 / 중혼합 t_NW=2.51 통상 유의 / 고혼합 t_NW=0.37 0과 구분
  불가)를 반영한 `reason_code`를 남긴다.

**중요 설계 원칙**: 이 모듈은 `regime_switch_gate.py`와 달리 **BUY/
SELL 판정에 연결하지 않는다** — §40.5가 이미 "이 발견은 SPPV-3
착수를 추가로 차단하는 사유가 아니라 운영상 모니터링 지표"라고
명시했으므로, 파이프라인에 게이트로 연결하는 것 자체가 범위를
넘는 확장이다. 순수 관측/로깅용 분류기로만 구현했다 — 불필요한
구조 확장을 피했다.

### 51.3 검증 방법 및 결과

`scripts/validate_regime_mixedness_monitor.py`(신규, read-only)로
벤치마크(KODEX 200)의 3년 캐시된 일봉에서 시장 공통 국면 라벨
시계열을 재계산하고, 신규 모듈로 634거래일 전부를 재분류해 §40의
실측치와 정확히 일치하는지 확인했다(`_fetch_extended_bars(None,
...)` — 캐시 히트 시 KIS client를 전혀 참조하지 않는 기존 함수
구조를 그대로 이용해 **신규 KIS 호출 0건**으로 완전히 로컬에서
검증).

**결과**: 전체 653거래일 중 634거래일 분류(19일은 §40과 동일하게
20일 미만 이력으로 skip). **버킷별 거래일 수: 저혼합 217일, 중혼합
215일, 고혼합 202일 — §40의 실측치(217/215/202)와 정확히 일치
(`matches_sppv_2_50=True`).**

### 51.4 결과 해석

이는 "혼합 국면 약세" 가설을 다시 검증한 것이 아니다(§40에서 이미
확정) — 대신 그 검증 결과를 **실제로 소비 가능한 재사용 가능한
코드 모듈로 정확히 이식했다**는 것을 100% 재현성으로 확인한 것이다.
이전에는 이 분석이 일회성 검증 스크립트(`validate_r3b_regime_mix_
intensity_decomposition.py`)에만 존재했고, 재사용 가능한 서비스
모듈이 없었다 — 이번 구현으로 향후 실거래 파이프라인 어디서든
(예: 일일 모니터링 로그, 관측 대시보드) `classify_mixedness_
bucket()`을 호출해 그날의 신뢰도 caveat을 즉시 얻을 수 있는 상태가
됐다. 이는 "창 교체(R3b) 검증"에서 "창 교체 이후 실제 운영 관측
도구"로의 전진이다 — 방패 보강이 아니라, 이미 확인된 리스크
(고혼합 구간에서 신호 신뢰도 저하)를 실제로 인지 가능하게 만드는
관측 인프라다.

### 51.5 판정 — Conditional Go 유지, "혼합도 모니터링 설계" 다음 단계를 실제 코드로 완료

**R3b는 Conditional Go를 유지한다.** §40.5/§40.7의 "다음 단계"
항목 중 "혼합도 모니터링 설계"는 이번 턴으로 **설계 스케치에서
실제 검증된 재사용 가능 모듈로 전진**했다 — §21 게이트(주된 차단
요인)나 override 설정은 이번 턴과 무관하게 불변이다. 이 모듈은
아직 실제 파이프라인(decision loop, 대시보드 등)에 연결되지
않았다 — 순수 함수로 존재할 뿐이며, 연결 여부는 별도 결정 사항
으로 남긴다(§51.6). 신규 KIS 호출 0건, 운영 코드
(`deterministic_trigger_engine.py`, `decision_orchestrator.py`)는
전혀 건드리지 않았다.

### 51.6 다음 단계

1. 이 모듈을 실제로 소비할 위치 결정(선택 사항, 별도 승인 필요) —
   예: 일일 decision loop 실행 시 그날의 혼합도 버킷을 로그에
   남기거나, 운영 대시보드에 "오늘의 신호 신뢰도" 지표로 노출.
2. `trigger_status` 공급원 자동화/배치화(cron/배치 설계, override
   =true인 동안은 낮은 우선순위).
3. T+5/경로 리스크 후속 검증(이미 §41~§44에서 상당 부분 답변됨,
   추가 필요성 낮음).
4. SPPV-3(entry_score 코드 반영) 착수 준비 — §45~§46에서 shadow
   정합성은 확보됨, 실제 코드 변경 PR 초안 작성 착수 여부는 여전히
   사용자 결정 사항.

## 52. 국면 혼합도 모니터링을 실제 decision loop 관측 경로에 연결 (SPPV-2.63, 2026-07-19)

- 작성자: Codex
- 수정일자: 2026-07-19

### 52.1 최신 truth 재확인

commit `aa10caee`("wire §21 gate and lock paper ops to config
override")로 §21 게이트는 실제 판단 경로에 완전히 연결·커밋·푸시
됐고, 현재 `.env`에는 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=true`
가 설정돼 있다 — paper 관측 단계에서 게이트는 BUY를 막지 않는다.
commit `4fd3ad7e`("SPPV-2.62")로 `services/regime_mixedness_
monitor.py`가 구현되고 §40의 217/215/202 버킷 재현성이 확인됐으나,
그 turn까지는 decision loop나 대시보드 어디에도 연결되지 않은
상태였다. 이번 턴이 그 마지막 gap을 메운다.

### 52.2 왜 이 항목을 골랐는가

후속 과제 후보 4개(trigger_status 자동화, 혼합도 모니터링의 실제
소비 위치 연결, T+5/경로 리스크 후속 검증, SPPV-3 착수 준비) 중
**혼합도 모니터링의 실제 소비 위치 연결**을 선택했다 — trigger_
status 자동화는 override=true인 동안 실질적 영향이 없어 급하지
않고, T+5/경로 리스크는 §41~§44에서 이미 답이 나온 반복 질문이기
때문이다. §51에서 만든 순수 모듈은 검증만 됐을 뿐 실제로 관측
루프에서 쓰이지 않아 "창 교체 이후 실제 운영 전진"에 아직 기여하지
못하고 있었다 — 이를 실제 decision loop 로그에 연결하는 것이
가장 직접적인 다음 전진이었다.

### 52.3 구현 내용

**`scripts/run_decision_loop.py`에 신규 함수 `_run_mixedness_
check(repos)` 추가** — cycle당 1회 실행되는 기존 pre-check 블록
(`_run_precheck()`, snapshot sync health 체크)과 완전히 동일한
안전 패턴을 그대로 재사용했다:

1. 벤치마크(KODEX 200, 069500)의 instrument를 조회.
2. `signal_feature_snapshots.list_by_instrument(limit=60)`로 최근
   60건의 스냅샷을 read-only로 조회(**신규 KIS 호출 없음** — 이미
   별도 스냅샷 동기화 루프가 채워 넣은 데이터를 재사용).
3. 각 스냅샷에 실제 운영 함수 `classify_market_regime()`을 적용해
   국면 라벨 trailing 리스트를 만들고, §51의 `compute_mixed_
   score()`/`classify_mixedness_bucket()`(순수 함수, 그대로 재사용)
   으로 버킷·reason_code를 계산.
4. `logger.info(...)`로 결과를 로그에 남긴다.
5. 예외는 전부 흡수(`_run_precheck`와 동일) — 실패해도 사이클 진행
   에 영향 없음.

이 함수를 cycle당 1회 실행되는 기존 pre-check 트랜잭션 블록 바로
다음에 별도 트랜잭션으로 호출하도록 배선했다.

**핵심 설계 원칙(반드시 지켜짐)**:
- **BUY/SELL 판정에 전혀 연결하지 않았다** — `cycle_precheck`처럼
  판정 로직에 전달되는 변수와 완전히 분리된, 호출하고 로그만 남기는
  독립 블록이다. `assess_deterministic_triggers`/`buy_candidate`/
  `sell_candidate` 어디에도 이 결과가 전달되지 않는다.
- **environment 분기 코드를 추가하지 않았다** — paper/real 값을
  참조하지 않는다.
- **`.env`는 수정하지 않았다.**
- **신규 KIS 호출이 없다** — 이미 존재하는 `signal_feature_
  snapshots` 테이블만 read-only로 조회한다.

### 52.4 검증 방법 및 결과

`scripts/validate_r3b_mixedness_decision_loop_wiring.py`(신규,
read-only, in-memory repos, 신규 KIS 호출 0건)로 `run_decision_
loop.py`에 실제로 배선된 `_run_mixedness_check()`를 **그대로
import해 직접 호출**했다(로직 복제가 아님) — 두 시나리오:

| 시나리오 | 벤치마크 합성 스냅샷 | 결과 |
|---|---|---|
| 저혼합(단일 bullish 지배) | 60건 전부 강한 양수(overall=0.70 고정) | `mixed_score=0.0`, `bucket=저혼합(단일 국면 지배)` |
| 고혼합(bullish/bearish 빈번 교차) | 60건이 +0.60/-0.60을 번갈아 교차 | `mixed_score=0.5`, `bucket=고혼합` |

**두 시나리오 모두 기대한 버킷으로 정확히 분류됨을 확인
(`low_bucket_correct=True`, `high_bucket_correct=True`).** 추가로
`inspect.getsource()`로 `_run_mixedness_check()`의 소스를 직접
검사해 `buy_candidate`/`sell_candidate`/`assess_deterministic_
triggers` 문자열이 전혀 등장하지 않음을 확인
(`no_buy_sell_reference_in_mixedness_check=True`) — BUY/SELL
판정과의 분리를 코드 레벨로 재확인.

기존 단위 테스트(`tests/scripts/test_run_decision_loop.py`)도 함께
재확인했다: 119건 중 10건이 실패했으나, **이 변경 전(git stash로
원복) 동일 테스트를 재실행한 결과 동일한 10건이 동일하게
실패**함을 확인 — universe_selection/market_overlay 관련 기존
결함으로, 이번 변경과 무관한 사전 존재 실패임을 확인했다(109건은
변경 전후 모두 통과).

### 52.5 결과 해석

이는 §51에서 검증한 순수 모듈을 **실제 운영 루프 안에서 실제로
실행되는 코드**로 전환한 것이다 — "창 교체(R3b) 검증"에서 "창
교체 이후 실제 운영 관측"으로의 마지막 단계다. 이제 `run_decision_
loop.py`가 실제로 실행될 때마다(cycle당 1회) 그 순간의 국면 혼합도
버킷이 로그에 남는다 — 사람이 로그를 보고 "오늘은 고혼합 구간이라
신호 신뢰도가 낮다"는 것을 즉시 인지할 수 있다. BUY/SELL 판정
자체는 이 정보와 무관하게 그대로 동작한다(§40.5의 "모니터링 지표,
차단 사유 아님" 원칙이 코드 레벨에서도 그대로 지켜짐).

### 52.6 판정 — Conditional Go 유지, "혼합도 모니터링 실제 소비 위치 연결" 완료

**R3b는 Conditional Go를 유지한다.** §21 게이트(주된 차단 요인)나
override 설정은 이번 턴과 무관하게 불변이다(override=true 유지).
BUY/SELL 게이트 로직은 전혀 더 세지지 않았다 — 오직 관측/로깅
경로만 추가됐다. compliance/VaR/broker submit 경계는 전혀 건드리지
않았다. 신규 KIS 호출 0건.

### 52.7 남은 다음 우선 작업

1. `trigger_status` 공급원 자동화/배치화(cron/배치 설계, override
   =true인 동안 낮은 우선순위).
2. entry_score 코드 변경 PR 초안 작성 착수 여부(shadow 정합성
   확보 완료, §45~§46).
3. R3b alpha 교체 전체 경로를 전체 파이프라인 수준에서 재현 검증
   (선택 사항).
4. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 53. SPPV-2.63 미확정 항목 확정 — `test_run_decision_loop.py` 10건 실패 무관 확정 (SPPV-2.64, 2026-07-19)

- 작성자: Codex
- 수정일자: 2026-07-19

### 53.1 최신 truth 재확인

commit `aa10caee`(§21 게이트 배선 완료), `.env`의 `REGIME_SWITCH_
V1_GATE_OVERRIDE_ENABLED=true`(paper 관측 단계에서 BUY 미차단),
commit `4fd3ad7e`(§51 혼합도 모듈 검증), commit `bcec9d03`(§52
혼합도 모니터링을 decision loop에 연결) — 모두 확인했다. §52
(SPPV-2.63) 보고에서 "`test_run_decision_loop.py` 10건 실패는
변경 전에도 동일하게 실패하는 사전 존재 결함"이라고 서술했으나,
그 근거가 `git stash`로 임시 원복 후 재실행한 것뿐이라 **증빙으로
확정하기엔 부족**했다는 지적을 받아들여, 이번 턴에 실제 증빙으로
확정한다.

### 53.2 검증 방법 — main 워크트리를 더럽히지 않는 격리 비교

`git worktree add /tmp/wt-pre-mixedness 4fd3ad7e`로 §52 변경 직전
커밋을 별도 디렉터리에 체크아웃(메인 워크트리는 전혀 건드리지 않음
— `git status`로 작업 전후 무변화 확인). Docker 컨테이너 안에서:

1. 컨테이너의 `scripts/run_decision_loop.py`를 백업(`.bak_post`).
2. `/tmp/wt-pre-mixedness`(§52 이전, mixedness 코드 없음)의
   `run_decision_loop.py`로 교체 → `pytest -v --tb=long` 전체
   실행, 로그 저장(`logs/r3b_test_run_decision_loop_PRE_
   mixedness_2026-07-19.log`).
3. 백업(§52 이후, 현재 main과 동일)으로 복원 → 동일하게 `pytest -v
   --tb=long` 재실행, 로그 저장(`logs/r3b_test_run_decision_loop_
   POST_mixedness_2026-07-19.log`).
4. 두 로그의 `FAILED` 목록·전체 stdout을 `diff`로 직접 비교.
5. `_run_mixedness_check`/`regime_mixedness_monitor`/`mixedness`
   문자열이 POST 로그(전체 stack trace 포함)에 등장하는지 `grep`.
6. 컨테이너 백업 파일과 worktree를 작업 종료 후 완전히 정리.

### 53.3 실측 결과

- **PRE(§52 이전) 실행**: `10 failed, 109 passed in 2.34s`.
- **POST(§52 이후, 현재 main과 동일) 실행**: `10 failed, 109
  passed in 2.34s`.
- **실패한 테스트 10건 이름을 `diff`로 비교한 결과 완전히 동일**
  (`TestRunOneCycle::test_dry_run_with_held_position_source_
  type`, `test_held_position_can_trigger_t3_live_pipeline_when_
  not_fresh`, `test_pre_ai_skip_when_orderable_amount_below_
  threshold`, `test_pre_ai_same_symbol_reentry_cooldown_skips_
  core_cycle`, `test_pre_ai_recent_buy_sell_cooldown_skips_held_
  position_cycle`, `test_pre_ai_reverse_trade_same_snapshot_
  skips_cycle`, `TestTradingUniverse::test_universe_selection_
  service_fallback`, `test_universe_selection_service_fallback_
  preserves_kosdaq_market`, `test_universe_selection_service_
  with_kis_market_overlay`, `test_universe_selection_service_
  with_kis_quotes_returned`).
- **두 로그(807줄씩) 전체를 `diff`한 결과**, 차이는 오직 (a)
  Python 객체 메모리 주소(`0xe7b2b7...` vs `0xf813ba...`, 비결정적
  — 실행마다 항상 다름)와 (b) 소스 파일 내 절대 라인 번호(예:
  `run_decision_loop.py:1896`→`:1967`, `:1550`→`:1621`, 항상
  정확히 71줄 차이)뿐이었다 — 이는 §52가 파일 앞부분(842행 부근)
  에 71줄을 추가해 그 뒤의 모든 코드가 그만큼 밀린 결과이지,
  실패 원인이나 에러 메시지·assertion 내용의 변화가 아니다. 실제
  에러 메시지(`decimal.ConversionSyntax`, `'>' not supported
  between instances of 'AsyncMock' and 'int'`, `assert 'core' ==
  'market_overlay'` 등)와 실패 사유는 PRE/POST 완전히 동일.
- **`grep -n "_run_mixedness_check\|regime_mixedness_monitor\|
  mixedness" logs/r3b_test_run_decision_loop_POST_mixedness_
  2026-07-19.log` → 매치 0건.** mixedness 관련 코드는 실패한
  10건의 stack trace 어디에도 등장하지 않는다.

### 53.4 결과 해석

10건의 실패는 모두 `universe_selection.py`(market_overlay seed
pool 관련)와 `AsyncMock`/`Decimal` 타입 불일치(테스트 fixture의
mock 설정 문제로 보이는 기존 결함)에서 발생한다 — §52가 추가한
`_run_mixedness_check()`나 그 호출 코드는 이 실패들의 원인 경로에
전혀 등장하지 않는다. PRE/POST 실행이 실패 건수·실패 테스트 이름·
에러 메시지·assertion 내용까지 바이트 단위로 동일하며, 유일한
차이(메모리 주소·라인 번호 오프셋)는 기능과 무관한 부수 효과다.
이는 "말로 추정"이 아니라 **격리된 worktree에서의 직접 재현
비교**로 확인된 사실이다.

### 53.5 최종 판정

**`무관 확정`** — `test_run_decision_loop.py`의 10건 실패는 §52
(SPPV-2.63)의 국면 혼합도 모니터링 연결과 완전히 무관한 사전 존재
결함이다. §52(SPPV-2.63)의 이전 서술("변경 전에도 동일하게
실패하는 사전 존재 결함")은 결론 자체는 맞았으나 `git stash`
재실행만으로는 증빙이 약했다 — 이번 턴의 격리된 worktree 비교로
그 결론이 **증빙으로 확정**됐다.

### 53.6 판정 — Conditional Go 유지, 코드/문서 변경 없음(순수 검증 확정)

**R3b는 Conditional Go를 유지한다.** 이번 턴은 §51/§52의 어떤
코드도 수정하지 않았다 — `regime_mixedness_monitor.py`,
`run_decision_loop.py`의 `_run_mixedness_check()`는 그대로다.
BUY/SELL 게이트 로직도, `.env`도 건드리지 않았다. §21 게이트
(주된 차단 요인)와 override 설정은 이번 턴과 무관하게 불변이다.
신규 KIS 호출 0건(순수 pytest 실행, in-memory/mock 기반).

### 53.7 다음 우선 작업

1. `trigger_status` 공급원 자동화/배치화(override=true인 동안
   낮은 우선순위).
2. entry_score 코드 변경 PR 초안 작성 착수 여부(shadow 정합성
   확보 완료, 사용자 결정 대기).
3. `test_run_decision_loop.py`의 10건 사전 존재 결함 자체를
   수정할지 여부는 이번 턴 범위 밖(별도 이슈로 트래킹 권장 — 이
   세션은 SPPV/R3b 트랙이며 이 결함은 market_overlay/AsyncMock
   fixture 문제로 별개 영역).
4. R3b alpha 교체 전체 경로를 전체 파이프라인 수준에서 재현 검증
   (선택 사항).

## 54. entry_score 코드 변경 PR 초안 설계 — R3b alpha 교체 실제 파이프라인 연결 방안 (SPPV-2.65, 2026-07-19)

- 작성자: Codex
- 수정일자: 2026-07-19

### 54.1 최신 truth 재확인

commit `aa10caee`(§21 게이트 배선), `.env`의 override=true(paper
관측 단계 BUY 미차단), commit `4fd3ad7e`/`bcec9d03`(§51/§52 혼합도
모니터링 구현·연결), commit `5c977017`(§53 테스트 실패 무관 확정)
— 모두 확인. 후속 과제 후보(trigger_status 자동화, entry_score
코드 변경 PR 초안 준비, R3b alpha 전체 경로 재현 검증, T+5/경로
리스크 후속 검증) 중 **entry_score 코드 변경 PR 초안 준비**를
선택했다 — trigger_status 자동화는 override=true인 동안 실질
영향이 없어 여전히 급하지 않고, mixedness는 이미 실제 소비 위치
연결까지 끝나 같은 축 반복은 피한다.

### 54.2 왜 "재검증"이 아니라 "설계"인가

§45(SPPV-2.56)가 이미 확인한 것: B 시나리오의 non-alpha 조정 항은
실제 `_build_entry_score`와 100% 일치(58,493건 전수). 이 세션 내내
쓰인 `_score_b(row) = clamp01(0.80 * candidate_percentile +
non_alpha)` 공식은 그 자체가 정의상 "실제 non-alpha(§45 확인) +
R3b alpha(0.80*candidate_percentile)"의 합이므로, **이 조합이
실제 함수와 수치적으로 일치한다는 것을 다시 실측으로 확인하는
것은 §45의 논리적 귀결을 반복 검증하는 것**이다 — 새로운 정보가
없다. 대신 이번 턴에 진짜 남아 있던 gap을 조사했다: **"R3b alpha
항을 실제 운영 파이프라인에 넣으려면 어떤 구조 변경이 필요한가"**
는 이 세션 전체에서 한 번도 명시적으로 설계되지 않았었다.

### 54.3 핵심 발견 — 아키텍처 제약: entry_score는 종목 단위로 계산되지만 R3b alpha는 당일 cross-sectional 순위가 필요하다

코드 조사 결과, `DecisionOrchestratorService._derive_deterministic_
context_components`(§48/§49에서 실제로 연결·검증한 그 메서드)는
**요청(symbol) 1건마다 독립적으로 호출**되며, `assess_
deterministic_triggers`도 마찬가지로 **종목 단위**로 `entry_score`
를 계산한다 — 그 시점에 "오늘 다른 candidate들의 `regime_
conditional_signal` 값"은 알 수 없다. 그런데 R3b의 alpha 항
(`candidate_percentile(regime_conditional_signal)`)은 **당일 quintile
후보 집합 안에서의 상대 순위**로 정의된다 — 이는 종목 단위 계산
만으로는 얻을 수 없고, **하루치 전체 후보를 먼저 훑어 순위를
매기는 cross-sectional 사전 계산 단계**가 있어야 한다.

**이는 이 세션에서 지금까지 명시적으로 다뤄지지 않은 새로운
architectural 제약이다** — 모든 R3b shadow 검증 스크립트는 이
사전 계산을 스크립트 안에서 (`_attach_candidate_percentile()`류
함수로) 이미 수행해왔지만, 그 사실 자체가 "실제 코드에 반영하려면
단순 공식 교체가 아니라 파이프라인 단계 추가가 필요하다"는 것을
뜻한다는 점은 별도로 정리된 적이 없었다.

### 54.4 이미 존재하는 정확한 선례 — 새 코드를 짜지 않고 재사용 가능

다행히 이 세션이 §21 게이트/혼합도 모니터링에서 쓴 것과 **완전히
동일한 패턴**이 이미 운영 코드에 두 번 구현돼 있다:

1. **`scripts/run_decision_loop.py`의 `_build_core_risk_off_apply_
   overrides_for_cycle(universe)`**(1247행) — cycle당 1회, 그날의
   `universe`(전체 후보 종목) 전부를 순회해 core risk-off top-k
   예외 승격 대상을 **미리 계산**하고, 그 결과를 `deterministic_
   trigger_override`(dict)로 `assess_deterministic_triggers`에
   전달한다. **이것이 정확히 R3b alpha percentile에 필요한 것과
   동일한 구조**(cross-sectional 사전 계산 → 종목별 override 주입)
   다.
2. **§48/§49의 `regime_switch_v1_trigger_status`/`regime_switch_
   v1_gate_override_enabled`** — 이미 검증된 "config 스위치로
   보호된 optional 파라미터, 기본값 비활성=기존 동작 100% 유지"
   패턴.

### 54.5 제안 설계(미적용 — 실제 코드 변경 아님, 검토용 초안)

**1) 신규 cycle당 1회 precompute 함수**(`run_decision_loop.py`에
   `_build_core_risk_off_apply_overrides_for_cycle`와 나란히
   추가하는 형태로 설계):
```python
async def _build_r3b_alpha_percentile_overrides_for_cycle(
    *, universe: tuple[UniverseSymbol, ...],
) -> dict[str, float]:
    """당일 universe 전체에서 regime_conditional_signal의 quintile
    상위 20% candidate만 골라 candidate_percentile을 계산한다
    (이 세션의 _attach_candidate_percentile()과 동일 로직 — 신규
    로직이 아니라 기존 shadow 스크립트 로직을 운영 코드로 이식).
    기본적으로 이 함수 자체가 호출되지 않으면(config 스위치 off)
    아무 영향이 없다.
    """
    ...  # 신규 로직 없음 — 기존 shadow 스크립트의 순위 계산을 그대로 이식
```

**2) `_build_entry_score`/`assess_deterministic_triggers`에 §48과
   동일한 패턴의 신규 optional 파라미터 추가**:
```python
def assess_deterministic_triggers(
    ...,
    r3b_alpha_percentile: float | None = None,
    r3b_alpha_enabled: bool = False,
) -> DeterministicTriggerAssessment | None:
    ...
    if r3b_alpha_enabled and r3b_alpha_percentile is not None:
        alpha_term = 0.80 * r3b_alpha_percentile  # R3b 공식 그대로
    else:
        alpha_term = 0.45*norm(overall) + 0.20*norm(fast) + 0.15*norm(slow)  # 기존 공식 그대로 유지
```

**3) 신규 config 스위치**(§21 게이트와 동일 패턴):
   `AppSettings.entry_score_r3b_alpha_enabled`(env:
   `ENTRY_SCORE_R3B_ALPHA_ENABLED`, 기본값 `False`) — 켜지지
   않으면 위 조건문이 항상 기존 공식을 쓰므로 기존 호출부는 100%
   무영향.

### 54.6 이 설계로 명확해진 것

- **기존 결론 유지**: §45의 non-alpha 100% 일치 결과는 이 설계
  에서도 그대로 재사용된다(조정 항 공식은 그대로).
- **새로 명확해진 것**: R3b alpha 항을 실제로 반영하려면 (a) cycle
  당 1회 cross-sectional precompute 함수 1개, (b) 종목별 override
  주입 파라미터 2개, (c) config 스위치 1개 — 총 3가지 신규 요소가
  필요하며, **이 세 요소 모두 이 세션에서 이미 검증된 기존 패턴의
  재사용**이라 새로운 설계 리스크는 낮다.
- **아직 실측하지 않은 것**: 이 설계를 실제로 적용했을 때 cycle당
  precompute 연산 비용(당일 universe 크기에 비례, `_build_core_
  risk_off_apply_overrides_for_cycle`가 이미 매 cycle 수행하는
  것과 동일한 크기의 부담이라 추가 비용은 미미할 것으로 예상되나
  실측은 안 됨).

### 54.7 판정 — Conditional Go 유지, "entry_score PR 초안" 준비도 격상(설계 완료, 코드 미적용)

**R3b는 Conditional Go를 유지한다.** 이번 턴은 코드를 전혀
수정하지 않았다 — 순수 설계 문서 작업이다. "entry_score 코드
변경 PR 초안 작성 착수"는 §45~§46의 "shadow 계산 정합성 확보"
단계에서 **"구체적 구현 설계 확보(실제 코드 diff 초안, 미적용)"
단계로 진전**했다 — 다만 이 설계를 실제로 코드에 적용하는 것은
`deterministic_trigger_engine.py`/`run_decision_loop.py`를 다시
수정하는 것이므로, 이전 §48/§49와 마찬가지로 **별도의 명시적
사용자 승인이 필요**하다. compliance/VaR/broker submit 경계는
전혀 건드리지 않았다. 신규 KIS 호출 0건(코드 조사만 수행).

### 54.8 다음 우선 작업

1. 이 설계(§54.5)를 실제로 적용할지 여부 사용자 결정(적용 시
   §48/§49와 동일한 승인 절차 필요).
2. `trigger_status` 공급원 자동화/배치화(override=true인 동안
   낮은 우선순위).
3. T+5/경로 리스크 후속 검증(§41~§44에서 이미 상당 부분 답변됨,
   추가 필요성 낮음).
4. `portfolio_allocation` gap·실제 청산 시점 분포는 실거래 누적
   이후 재검증 대상으로 계속 유보.

## 55. entry_score R3b alpha 교체 — 1단계(엔진 파라미터 배선) 실제 코드 적용 (SPPV-2.66, 2026-07-19)

### 55.1 최신 truth 재확인

`aa10caee`(§21 gate 배선)~`220ca785`(SPPV-2.65, §54 설계)까지 모두
`origin/main`에 push 완료 상태를 재확인했다(`git log origin/main..
HEAD` 결과 없음). §54는 "미적용, 코드 변경 없음"으로 명시된 순수
설계 문서였다. 이번 턴은 그 설계 중 **"1단계: 엔진 파라미터 배선"**
만을 실제로 적용한다 — cycle 단위 candidate_percentile 사전 계산
배선("2단계")은 이번 턴 범위 밖이며 이후 별도 승인 대상으로 유보한다.

### 55.2 선택 근거

"방패 보강"(trigger_status 자동화)보다 "창 교체 이후 실전진"에
직접 기여하는 쪽을 선택했다. §54.5에서 이미 설계된 3-part 중
가장 낮은 리스크·최고 backward-compat 검증 가능성을 가진 부분
(엔진 파라미터 2개 + config 스위치 1개)만 이번 턴에 적용하고,
cycle 단위 precompute(§54.5의 2단계, `run_decision_loop.py`/
`decision_orchestrator.py` 수정 필요·리스크 더 큼)는 별도 턴으로
분리했다 — §48→§49가 "엔진 내부"와 "호출부 배선"을 두 턴으로
나눠 진행한 선례와 동일한 단계적 접근이다.

### 55.3 실제 적용 내용

- `src/agent_trading/config/settings.py`: `_resolve_entry_score_r3b_
  alpha_enabled()` 신규 함수 + `AppSettings.entry_score_r3b_alpha_
  enabled: bool` 필드 추가(env: `ENTRY_SCORE_R3B_ALPHA_ENABLED`,
  기본값 `False`) — `regime_switch_v1_gate_override_enabled`와
  100% 동일한 패턴.
- `src/agent_trading/services/deterministic_trigger_engine.py`:
  - `assess_deterministic_triggers()`에 `r3b_alpha_percentile:
    float | None = None`, `r3b_alpha_enabled: bool = False` 신규
    optional 파라미터 추가, `_build_entry_score` 호출부에 그대로
    전달.
  - `_build_entry_score()`에 동일 파라미터 2개 추가. `r3b_alpha_
    enabled and r3b_alpha_percentile is not None`인 경우에만
    alpha 항(0.80 가중치)이 `0.80 * clamp(r3b_alpha_percentile)`로
    교체되고, 그 외(기본값 포함) 기존 `0.45*norm(overall) +
    0.20*norm(fast) + 0.15*norm(slow)` 공식이 100% 그대로 유지된다.
- `.env`는 전혀 수정하지 않았다 — `ENTRY_SCORE_R3B_ALPHA_ENABLED`는
  설정되지 않아 기본값 `False`로 동작한다.

### 55.4 실측 결과(수치 + 해석)

1. **기존 회귀 테스트**: `tests/services/test_deterministic_trigger_
   engine.py` 20건, `tests/services/test_decision_orchestrator.py`
   포함 총 83건 — **전부 통과(83 passed)**, 실패 0건. → 신규
   optional 파라미터 추가가 기존 호출부(파라미터를 모르는 모든
   지점)의 동작에 전혀 영향을 주지 않음을 확인.
2. **`AppSettings().entry_score_r3b_alpha_enabled` 기본값 직접
   조회**: `False` 반환 확인. → `.env` 미변경 상태에서 신규 스위치가
   완전히 비활성 상태로 존재함을 실측 확인.
3. **`_build_entry_score` 직접 호출 비교(ad-hoc, overall=fast=slow=
   0.5 고정)**:
   - 파라미터 미전달(default) 경로: `entry_score = 0.6000...`,
     `reason_codes=[]` — 기존 공식(0.45*0.5+0.20*0.5+0.15*0.5=0.40의
     정규화 결과)과 일치.
   - `r3b_alpha_enabled=True, r3b_alpha_percentile=0.9` 경로:
     `entry_score = 0.7200...`, `reason_codes=['trigger_r3b_alpha_
     percentile']` — 기대값 `0.80*0.9=0.72`와 **완전 일치**(오차
     `<1e-9`).
   → alpha 교체 로직이 설계(§54.5) 그대로 정확히 동작하며, 활성화
   시에만 reason_code가 남아 추적 가능함을 확인.

### 55.5 결과 해석

§54에서 "미적용, 설계만"이었던 3-part 중 엔진 파라미터/config
스위치 부분이 실제 코드로 전환되었고, 83건 회귀 테스트와 3건의
직접 수치 검증으로 backward-compat과 alpha 교체 정확성을 모두
확인했다. 남은 것은 cycle 단위 candidate_percentile 사전 계산
(§54.5의 precompute 함수, `run_decision_loop.py`/`decision_
orchestrator.py` 수정 필요)뿐이며, 이는 §48→§49와 동일하게 별도
승인이 필요한 다음 단계로 명확히 좁혀졌다.

### 55.6 판정 — Conditional Go 유지, entry_score PR 초안이 "설계 완료" → "1단계 코드 적용·검증 완료" 단계로 진전

**R3b는 Conditional Go를 유지한다.** BUY/SELL gate 로직은 전혀
더 세게 만들지 않았고(신규 스위치는 기본 비활성), 환경 분기 코드도
추가하지 않았다. `.env` 값 미변경. compliance/VaR/broker submit
경계 미변경. 신규 KIS 호출 0건.

### 55.7 다음 우선 작업

1. cycle 단위 candidate_percentile 사전 계산 배선(§54.5의 2단계) —
   `run_decision_loop.py`에 `_build_r3b_alpha_percentile_overrides_
   for_cycle(universe)` 신규 함수 추가 + `decision_orchestrator.py`
   경유 배선. 이 작업은 §48/§49와 동일하게 별도 명시적 사용자 승인
   필요(operational 코드 수정이므로 커밋 시 classifier 차단 가능성
   있음).
2. `trigger_status` 공급원 자동화/배치화(override=true인 동안 낮은
   우선순위).
3. T+5/경로 리스크 후속 검증 — 추가 필요성 낮음(유보 유지).
4. `portfolio_allocation` gap — 실거래 누적 이후 재검증 대상으로
   계속 유보.

## 56. entry_score R3b alpha 교체 — 2단계(순수 계산 모듈 + orchestrator 배선) 실제 코드 적용 (SPPV-2.67, 2026-07-19)

### 56.1 최신 truth 재확인

`aa10caee`~`1f6e3875`(SPPV-2.66, 1단계 엔진 파라미터 배선)까지 모두
`origin/main`에 push 완료 상태를 재확인했다(`git log origin/main..
HEAD` 결과 없음). SPPV-2.66은 "83건 테스트 전부 통과"를 보고했으나
이번 턴 지시에 따라 그 수치를 재인용하지 않고, 이번 턴 자체에서
직접 재실행한 결과만을 아래 §56.4에 근거로 삼는다.

### 56.2 선택 근거

`trigger_status` 자동화(override=true인 동안 실질 영향 없음, "방패
보강")보다 R3b alpha 교체 2단계(cycle 단위 candidate_percentile
precompute 배선)가 창 교체 이후 실전진에 직접 기여하고 SPPV-3
착수 준비를 실제로 줄인다고 판단해 선택했다. mixedness 축 반복
작업은 하지 않았다.

### 56.3 실제 적용 내용

1. **신규 순수 계산 모듈** `src/agent_trading/services/r3b_alpha_
   percentile.py`: 이 세션의 모든 R3b shadow 스크립트가 반복
   사용해 온 `_attach_candidate_only_percentile` 로직을 그대로
   이식 — `compute_regime_conditional_signal()`(시장 공통 국면
   라벨에 따라 risk-adjusted 3개월 모멘텀/1개월 역추세 계산),
   `build_candidate_percentiles()`(당일 상위 20% quintile
   candidate pool 내부에서만 0~1 percentile 부여). 신규 알고리즘
   없음 — 순수 이식.
2. **`decision_orchestrator.py` 배선**: `DecisionOrchestratorService.
   __init__`에 `r3b_alpha_enabled: bool = False`(mode-agnostic
   config, `AppSettings.entry_score_r3b_alpha_enabled` 그대로
   보존) 추가; 신규 `_extract_r3b_alpha_percentile(request)` static
   helper(`request.metadata["r3b_alpha_percentile"]`를 읽음 —
   `deterministic_trigger_override`의 metadata 채널과 동일 패턴);
   `_derive_deterministic_context_components`에 `r3b_alpha_
   percentile: float | None = None` 파라미터 추가, `assess_
   deterministic_triggers` 호출부에 `r3b_alpha_percentile`/
   `r3b_alpha_enabled=self._r3b_alpha_enabled` 그대로 전달. 두
   호출 지점(`derive_deterministic_trigger_for_request`, 실제
   주문 조립 경로) 모두 동일하게 배선.
3. **`run_decision_loop.py` config 전달**: 두 `DecisionOrchestrator
   Service(...)` 인스턴스화 지점 모두에 `r3b_alpha_enabled=settings.
   entry_score_r3b_alpha_enabled` 추가.

**이번 턴에 하지 않은 것(범위 밖, 명확히 유보)**: cycle당 1회
`universe` 전체를 순회해 실제 `r3b_alpha_percentile` 값을 계산하고
`request.metadata["r3b_alpha_percentile"]`에 주입하는 precompute
함수(§54.5가 원래 지목한 "신규 cycle당 1회 precompute 함수") 자체는
아직 작성하지 않았다 — `_extract_r3b_alpha_percentile`은 지금 항상
metadata가 비어 있어 `None`을 반환한다. 즉 이번 턴은 "엔진→
orchestrator→config 전달"까지의 배선을 완성했을 뿐, 실제 percentile
계산·주입 파이프라인("3단계")은 여전히 다음 과제다.

### 56.4 실측 결과(수치 + 해석, 전부 이번 턴 직접 재실행)

1. **신규 모듈 parity 검증**(`scripts/validate_r3b_alpha_percentile_
   precompute.py`, 신규 작성): 무작위 종목 수(3~40) 200회 trial 전부
   기존 shadow 스크립트의 `_attach_candidate_only_percentile`과
   candidate pool 구성·percentile 값이 정확히 일치(오차 <1e-9) —
   **총 200회 trial 중 불일치: 0**. → 이식이 정확함을 확인.
2. **핵심 회귀 테스트**(이번 턴 직접 재실행): `tests/services/
   test_deterministic_trigger_engine.py`(20건) + `test_decision_
   orchestrator.py` 포함 **83 passed, 0 failed**. → orchestrator
   생성자/헬퍼 추가가 기존 호출부에 영향 없음을 확인.
3. **`tests/scripts/test_run_decision_loop.py`**(이번 턴 직접
   재실행): **10 failed, 109 passed** — 실패 이름·개수가 §53에서
   확정한 기존 10건과 동일(`universe_selection.py`/AsyncMock 타입
   불일치 관련 사전 존재 결함). 재논의 없이 참고만 함.
4. **`AppSettings().entry_score_r3b_alpha_enabled`** 직접 조회 →
   `False` — `.env` 미변경 상태에서 기본 비활성 확인.
5. **`tests/ -k "orchestrator or deterministic_trigger"`**(이번 턴
   직접 재실행): 118 passed, 6 failed(`test_orchestrator_
   entrypoint.py`/`test_runtime_event_interpretation_smoke.py`) —
   실패 stack trace가 `asyncpg.exceptions.InvalidColumnReferenceError`
   /`TooManyColumnsError: tables can have at most 1600 columns`로,
   DB 마이그레이션 상태 문제임이 에러 메시지 자체로 확인됨(파라미터
   배선과 무관한 사전 존재 환경 이슈).

### 56.5 결과 해석

R3b alpha 교체 파이프라인은 "1단계(엔진 내부 공식 교체)"에서
"2단계(orchestrator까지 배선 완료, config로 활성화 가능)"로
진전했다. 다만 실제 percentile 값을 계산해 주입하는 cycle
precompute("3단계")가 없는 한 `r3b_alpha_enabled=True`로 설정해도
`r3b_alpha_percentile`은 항상 `None`이라 alpha 교체가 실제로
발동하지 않는다 — 즉 현재 상태는 "배선은 됐지만 아직 전원이
꽂히지 않은" 상태다.

### 56.6 판정 — Conditional Go 유지, entry_score R3b alpha 배선이 "1단계" → "2단계(orchestrator 배선 완료)"로 진전

**R3b는 Conditional Go를 유지한다.** `.env` 미변경, BUY/SELL gate
로직 강화 없음, 환경 분기 코드 없음, compliance/VaR/broker submit
경계 미변경, 신규 KIS 호출 0건.

### 56.7 다음 우선 작업

1. cycle당 1회 precompute 함수("3단계") — `run_decision_loop.py`에
   신규 함수(당일 universe 전체 순회, 벤치마크 시장 공통 국면
   라벨 산출 + 종목별 `signal_feature_snapshot`에서 `return_1m_
   pct`/`return_3m_pct`/`volatility_20d_pct` 조회 → `r3b_alpha_
   percentile.build_candidate_percentiles()` 호출 → 결과를 각
   `SubmitOrderRequest.metadata["r3b_alpha_percentile"]`에 주입)
   작성 — `_build_core_risk_off_apply_overrides_for_cycle`과 거의
   동일한 구조. 별도 명시적 사용자 승인 필요(operational 코드
   추가 수정).
2. `trigger_status` 공급원 자동화/배치화(낮은 우선순위).
3. T+5/경로 리스크 후속 검증 — 추가 필요성 낮음(유보 유지).
4. `portfolio_allocation` gap — 실거래 누적 이후 재검증 대상으로
   계속 유보.
