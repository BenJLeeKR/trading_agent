# BUY 경로 리팩터링 사전 검토 일정

작성일: 2026-08-01 KST
상태: 사전 검토 일정 확정

## 1. 목적

이 문서는 `BUY` 경로 대대적 리팩터링에 바로 착수하지 않고,
`docs/20_system_analysis/buy_path_variable_gate_matrix.md`를 기준으로
사전 확인·검토 작업을 어떤 순서와 일정으로 닫을지 정리한다.

이번 문서의 범위는 **Roadmap 이전 단계**다.

- 지금 하는 것: 확인 검토 일정 고정
- 나중에 하는 것: 구현 순서/배포 순서/관측 순서를 포함한 Roadmap 작성

## 2. 일정 운영 원칙

1. 개별 threshold 조정보다 변수 역할 분리를 먼저 닫는다.
2. 코드 변경보다 계약 정리를 먼저 닫는다.
3. 상류 deterministic 경로를 먼저 정리하고, AI/EV gate/submit 하류는
   그 다음에 본다.
4. 한 번에 전면 교체하지 않고, 단계별로 "분석 완료 → 설계 확정 →
   최소 diff" 순서를 지킨다.

## 3. 사전 검토 범위

이번 사전 검토는 아래 5개 축만 다룬다.

1. `entry_score` 내부 보정항 역할 분해
2. `ranking_score`의 존치/축소/대체 판단
3. `portfolio_allocation`의 score/gate/feasibility 역할 분리
4. `relative_activity`의 soft bonus vs hard gate 분리
5. AI downgrade / EV gate / submit translation과 상류 deterministic 변수의
   중복 주입 여부 점검

## 4. 권장 일정

**일정 성격에 대한 전제**: 아래 날짜는 고정 캘린더가 아니라, 선행 검증
단계를 해석 가능한 크기로 쪼개기 위한 **예시적 권장 순서**다. 특히
`docs/10_signal_research_sppv/` 트랙의 canonical 마일스톤(예:
**2026-08-03(월) KST** 08:50 KST freeze 실측)과 날짜가 겹치거나
충돌하면, 이 일정이 우선한다고 단정하지 않고 **후행 조정 가능**하다.
이 일정은 SPPV 트랙보다 상위이거나 대체하는 캘린더가 아니다.

### 4.1 1단계 — 변수/계약 고정 검토

기간: **2026-08-02(일) ~ 2026-08-03(월) KST**

목적:

- 변수별 "본래 역할"을 한 줄로 고정
- 현재 코드에서 같은 변수가 몇 단계에 들어가는지 재확인
- 리팩터링 대상/비대상 경계를 확정

완료 조건:

1. `entry_score`, `ranking_score`, `market_regime`, `portfolio_allocation`,
   `relative_activity`, `preferred_strategy`에 대해
   - alpha
   - risk
   - sizing
   - execution feasibility
   중 어느 역할인지 1차 분류가 끝날 것
2. "정당한 중복"과 "과잉 중복"을 분리한 표가 있을 것
3. 이번 리팩터링에서 건드리지 않을 축이 명시될 것

### 4.2 2단계 — 상류 deterministic 재설계 검토

기간: **2026-08-04(화) ~ 2026-08-06(목) KST**

목적:

- `BUY` 경로 상류를 "alpha / risk / sizing / feasibility" 네 레이어로
  나눌 수 있는지 검토
- `ranking_score`를 독립 공식으로 남길지, 축소할지, 대체할지 결정 준비

핵심 질문:

1. `entry_score`에서 제거해야 할 비-alpha 보정항이 무엇인가
2. `ranking_score`는 유지 가치가 있는가 — **[2026-08-01 KST 갱신]
   판정 C(제거/대체)로 닫힘.** `buy_path_variable_gate_matrix.md`
   §13.1.1 참고. 이 질문은 2단계를 기다리지 않고 먼저 닫혔으며, 남은
   2~4번 질문과 R2~R4는 이 일정대로 진행한다(날짜 변경 없음).
3. `portfolio_allocation`은 후보 점수에 남아야 하는가
4. `relative_activity`는 soft bonus로 둘 이유가 남아 있는가

완료 조건:

1. 최소 2개 이상의 재설계 옵션이 비교될 것
2. 옵션별 blast radius가 정리될 것
3. 어떤 옵션이 1차 diff 후보인지 좁혀질 것

### 4.3 3단계 — 하류 연쇄 영향 검토

기간: **2026-08-07(금) ~ 2026-08-08(토) KST**

목적:

- 상류 리팩터링이 AI downgrade / EV gate / submit translation에 어떤
  파급을 주는지 확인
- 상류를 바꿨을 때 하류가 그대로 병목인지, 아니면 새 충돌이 생기는지
  판단

완료 조건:

1. candidate_vs_final, EV gate, submit translation 각각에 대해
   상류 변수 재사용 여부가 정리될 것
2. "상류 먼저"로 충분한지, 하류 동시 개편이 필요한지 결정될 것
3. 리팩터링 범위가 상류 한정인지, 상류+하류 병행인지 정리될 것

### 4.4 4단계 — Roadmap 작성 전 착수 판정

기간: **2026-08-09(일) KST**

목적:

- 앞선 3단계 검토를 바탕으로 실제 리팩터링 Roadmap 작성 가능 상태인지
  판정

완료 조건:

1. 1차 구현 범위가 1~2개 diff 단위로 축소될 것
2. 관측 포인트와 무변화 회귀 포인트가 정리될 것
3. Roadmap 문서로 넘길 입력이 준비될 것

## 5. 왜 이 일정이 적절한가

이 일정은 바로 코드를 뜯는 대신 아래 위험을 먼저 피하려는 목적이다.

1. `entry_score`와 `ranking_score`를 동시에 건드려 해석 불가능해지는 위험
2. 상류를 바꿨는데 하류 병목 때문에 효과가 가려지는 위험
3. 역할 분리 없이 threshold만 다시 만지는 위험
4. alpha/risk/sizing/feasibility를 한 레이어에서 계속 섞는 위험

즉 이 일정은 구현 지연이 아니라 **리팩터링 단위를 해석 가능한 크기로
쪼개기 위한 일정**이다.

## 6. 현재 기준 즉시 시작할 작업

지금 바로 시작할 수 있는 것은 아래 3개다.

1. `entry_score` 내부 보정항 전수 표 작성
2. `portfolio_allocation` 관련 값이 BUY 경로에서 몇 번 재사용되는지 전수 표 작성
3. candidate_vs_final / EV gate / submit translation이 상류 변수와 어디서 다시
   만나는지 경로도 작성

이 3개가 닫히면 2단계 재설계 검토로 넘어갈 수 있다.

## 7. Roadmap 작성 시점

Roadmap은 **1단계와 2단계가 끝난 뒤** 쓰는 것이 맞다.

이유는 아직 아래가 확정되지 않았기 때문이다.

1. 무엇을 alpha 레이어에 남길지
2. `ranking_score`를 유지할지 축소할지
3. `portfolio_allocation`을 점수에서 제거할지
4. 상류만 바꾸면 되는지, 하류도 같이 손대야 하는지

따라서 지금 시점의 적절한 산출물은 Roadmap이 아니라
**Roadmap 이전의 확인 검토 일정표**다.

## 8. 리팩터링 단위별 착수 순서

`buy_path_variable_gate_matrix.md`의 R1~R5 단위를 기준으로 하면,
사전 검토 일정의 실제 작업 순서는 아래처럼 읽는 것이 맞다.

### 8.1 1차 묶음 — R1

- 대상: `ranking_score`
- 목표:
  - 독립 공식 존치 여부
  - `entry_score` 재사용 구조 해소 여부
  - guard 보조 입력으로의 축소 가능성

이 묶음이 먼저 닫혀야 이후 `entry_score`와 allocation/activity의 역할을
어디까지 남길지 결정할 수 있다.

### 8.2 2차 묶음 — R2

- 대상: `entry_score`
- 목표:
  - alpha 전용화 가능성 검토
  - risk/sizing/activity/strategy 보정항 이관 후보 분류

R1 없이 R2를 먼저 건드리면 `ranking_score`와 `entry_score`를 동시에
재해석하게 되어 변경 효과를 분리하기 어렵다.

### 8.3 3차 묶음 — R3 + R4

- 대상:
  - `portfolio_allocation`
  - activity 계열
- 목표:
  - selection vs sizing vs feasibility 경계 재설정
  - soft bonus vs hard gate 중복 축소

이 두 축은 성격이 비슷하다. 둘 다 "좋은 종목인가"보다
"지금 들어갈 수 있는가" 쪽 의미가 더 강하기 때문이다.

### 8.4 4차 묶음 — R5

- 대상:
  - AI downgrade
  - EV gate
  - submit translation
- 목표:
  - 상류 리팩터링이 하류 contract를 깨지 않는지 확인
  - 필요 시 하류 contract 정리 범위를 따로 떼어낸다

### 8.5 현재 착수 판정

지금 바로 Roadmap으로 넘어가기보다, **R1 정의 고정 → R2 경계 확인**까지를
이번 사전 검토의 최소 완료선으로 보는 것이 적절하다.
