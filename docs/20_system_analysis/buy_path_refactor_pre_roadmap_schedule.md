# BUY 경로 리팩터링 사전 검토 일정

작성일: 2026-08-01 KST
상태: 체크리스트 운영 중

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

## 4. 권장 일정 체크리스트

**일정 성격에 대한 전제**: 아래 날짜는 고정 캘린더가 아니라, 선행 검증
단계를 해석 가능한 크기로 쪼개기 위한 **예시적 권장 순서**다. 특히
`docs/10_signal_research_sppv/` 트랙의 canonical 마일스톤(예:
**2026-08-03(월) KST** 08:50 KST freeze 실측)과 날짜가 겹치거나
충돌하면, 이 일정이 우선한다고 단정하지 않고 **후행 조정 가능**하다.
이 일정은 SPPV 트랙보다 상위이거나 대체하는 캘린더가 아니다.

### 4.1 1단계 — 변수/계약 고정 검토

기간: **2026-08-02(일) ~ 2026-08-03(월) KST**

현재 상태: **진행 중**

목적:

- 변수별 "본래 역할"을 한 줄로 고정
- 현재 코드에서 같은 변수가 몇 단계에 들어가는지 재확인
- 리팩터링 대상/비대상 경계를 확정

체크리스트:

- [x] `entry_score` 역할 1차 분류 완료
- [x] `ranking_score` 역할 1차 분류 완료
- [x] `market_regime` 역할 1차 분류 완료
- [ ] `portfolio_allocation` 역할 1차 분류 완료
- [ ] `relative_activity` 역할 1차 분류 완료
- [x] `preferred_strategy` 역할 1차 분류 완료
- [x] "정당한 중복"과 "과잉 중복"을 분리한 표 작성
- [x] 이번 리팩터링에서 당장 건드리지 않을 축 명시

판정 메모:

- `entry_score`/`ranking_score`/`market_regime`/`preferred_strategy`는
  `buy_path_variable_gate_matrix.md`의 R1~R2 분석으로 역할 경계가 상당 부분
  닫혔다.
- `portfolio_allocation`과 `relative_activity`는 각각 R3/R4 트랙에서 별도로
  더 닫아야 하므로 1단계 전체 완료로 보기는 이르다.

### 4.2 2단계 — 상류 deterministic 재설계 검토

기간: **2026-08-04(화) ~ 2026-08-06(목) KST**

현재 상태: **진행 중**

목적:

- `BUY` 경로 상류를 "alpha / risk / sizing / feasibility" 네 레이어로
  나눌 수 있는지 검토
- `ranking_score`를 독립 공식으로 남길지, 축소할지, 대체할지 결정 준비

핵심 질문 체크리스트:

- [x] `entry_score`에서 제거해야 할 비-alpha 보정항이 무엇인가 —
   **[2026-08-02 KST 갱신]** R1을 정리된 것으로 두고 R2 착수 준비를
   마쳤다(`buy_path_variable_gate_matrix.md` §13.2.1). `entry_score`
   내부 6개 항목(alpha/regime·risk/allocation/strategy/source-type/
   activity)을 전수 분해해 BUY 경로 재사용을 매핑한 결과, alpha·
   strategy(R1에서 이미 유지로 확정)·source-type은 **유지**, regime/
   risk·activity는 **점수 밖 이관 검토**, allocation은 **중복 제거
   최우선 후보**로 판정했다. 다음 1순위 코드 수정 단위로 "`entry_
   score`의 allocation 보정항을 지역 변수로 명시적으로 분리하는
   무변화 리팩터링"을 권고하며, 다음 턴 바로 코드 수정 초안 작성이
   가능한 수준이다. **[2026-08-02 KST 재갱신] R2 1차 단위 적용 완료**
   (`buy_path_variable_gate_matrix.md` §13.2.2) — `_build_entry_
   score()`의 allocation 블록을 `entry_score_allocation_adjustment`
   지역 변수로 분리했다. 수치·`buy_candidate_threshold(0.65)`·
   `ranking_score`·shadow·reporting·authoritative 게이트 전부
   무변화이며, dev tree를 직접 mount한 검증에서 25 passed를 확인했다.
   제거/이관 여부 판단은 운영 데이터 실측 후 다음 턴으로 넘긴다.
   **[2026-08-02 KST 3차 갱신] 기여도 실측 완료**(`buy_path_variable_
   gate_matrix.md` §13.2.3) — `entry_score_allocation_adjustment`
   덕분에만 `buy_candidate_threshold(0.65)`를 넘긴 표본(C 집합)은
   최근 3거래일/1개월/전체 이력 모두 **0건**이었다. 가장 여유가
   좁았던 표본조차 보정항 없이 `0.65`를 넘겼고(최소 margin
   `0.0038`), `decision_type=approve`까지 간 유일한 표본도 보정항과
   무관하게 여유가 컸다. **판정 A(제거해도 영향 미미)**를 권고하며,
   제거 vs 하드 게이트 전용 이관의 구체적 코드 설계는 다음 턴 과제로
   남긴다. **[2026-08-02 KST 4차 갱신] 자본 보너스 점수 구조 분리
   완료**(`buy_path_variable_gate_matrix.md` §13.2.4) — 인라인
   블록을 `_build_entry_score_allocation_adjustment()` helper로
   추출해 entry_score 본체와 함수 경계로 명확히 나눴다. threshold·
   gate 기준값·shadow 기준값·reporting 값은 전혀 바꾸지 않았고(동작
   무변화), dev tree 직접 mount 검증에서 25 passed를 확인했다. 다음
   턴은 이 helper를 대상으로 제거 vs 하드 게이트 전용 이관을
   결정한다. **[2026-08-02 KST 5차 갱신] entry_score에서 자본 보너스
   점수 제거 적용 완료**(`buy_path_variable_gate_matrix.md` §13.2.5)
   — `_build_entry_score_allocation_adjustment()` 호출·helper를 함께
   제거했다. authoritative 게이트(§13.1.6)의 `allocation_bonus_like`
   코드는 무변화이나, `entry_score`가 게이트의 입력이라 관련 fixture
   5건의 경계값을 최소 범위로 재실측·보정했다(게이트 threshold `0.28`
   자체는 무변화). dev tree 직접 mount 검증 25 passed. 운영 데이터로
   재실측하는 것은 다음 턴 과제로 남긴다. **[2026-08-02 KST 6차 갱신,
   R2 다음 후보 = regime/risk 항 정리 여부 판정]** `buy_path_variable_
   gate_matrix.md` §13.2.6 — regime/risk 블록을 `bullish_trend`
   (+0.10)/`risk_on`(+0.05)/`risk_off`(-0.15) 3개 서브조건으로 분해해
   BUY 경로 재사용을 매핑했다. `risk_off` 서브조건만 `core_risk_off_
   guard_active`·eligibility 하드 게이트와 같은 원신호를 중복
   반영(population 39,500건)하고, 나머지 두 서브조건은 대응 하드
   게이트가 없어 "유지"에 가깝다. 다음 코드 수정 단위는 **B(read-
   only 실측 먼저)**로 좁혔다 — `risk_off` 서브조건에 §13.2.3과 같은
   C 집합 실측을 다음 턴에 적용한다. **[2026-08-03 KST 7차 갱신,
   R2 상태: `risk_off -0.15` 기여도 실측 완료]** `buy_path_variable_
   gate_matrix.md` §13.2.7 — allocation(§13.2.3, C=0건)과 달리
   **`risk_off` 패널티는 C 집합이 0건이 아니다**(전체 이력 3,692건/
   27종목/89 symbol+거래일 조합, 최근 1개월 1,733건, 최근 3거래일
   472건). `decision_type=approve`이자 `order_requests` 체결까지
   간 실제 사례(`011070`, 2026-06-19 KST)도 1건 확인됐다. **판정
   C(실제 BUY 경로에 유의미)**로 판정해, allocation 때처럼 곧바로
   제거하지 않고 A/B/C 설계 비교(§13.1.2 패턴)부터 다음 턴에 진행할
   것을 권고한다. R2는 이 설계 비교가 끝나야 다음 코드 수정 단계로
   넘어간다. **[2026-08-03 KST 8차 갱신, R2 상태: A/B/C 설계 비교
   완료]** `buy_path_variable_gate_matrix.md` §13.2.8 — C 집합
   3,692건 중 `bullish_trend`가 3,616건(97.9%)으로, 하드 게이트는
   `bearish_trend`+`risk_off` 조합에서만 발동해 이 population의
   98.6%를 전혀 커버하지 못함을 확인했다. **C안(제거)은 권고하지
   않는다** — allocation과 달리 하드 게이트가 안전망 역할을 하지
   못한다. **1순위 권고안은 B안(계수 완화, 후보 `-0.10`/`-0.05`)**
   이며, 다음 코드 수정 단위는 **B(추가 실측 1건 필요)** — 후보
   계수별 C 집합 축소 규모를 다음 턴에 실측한 뒤 계수를 확정한다.
- [x] `ranking_score`는 유지 가치가 있는가 — **[2026-08-01 KST 갱신]
   판정 C(제거/대체)로 닫힘.** `buy_path_variable_gate_matrix.md`
   §13.1.1 참고. **[2026-08-02 KST 갱신]** 대체 contract 설계 비교
   (A/B/C안, §13.1.2)까지 마쳤고 **C안(authoritative만 교체 + 관찰용
   잔존)을 권고**한다. **[2026-08-02 KST 재갱신]** 착수 전 마지막
   read-only 실측(§13.1.3)도 마쳤다 — `ranking_score ∈ [0.28, 0.38]`
   구간(core_risk_off_guard_active=true, n=2,455건/13종목, 전체 이력)
   에서 `threshold ÷ 0.55` 단순 재정규화 후보를 적용하면 최근
   3거래일/1개월/전체 이력 모두 **표본 전량(100%)이 뒤집힌다**. C안
   자체의 구조적 우위는 유지되나, **threshold 재산정 방법을 먼저
   정하기 전에는 diff에 착수하지 않는다.** **[2026-08-02 KST 3차
   갱신]** 새 threshold 산정안 비교(A/B/C, §13.1.4)까지 마쳤고,
   **보조 조건 병행안(기존 산식을 인라인으로 그대로 재현)을 권고**한다
   — 근사가 없어 과완화/과차단 위험이 없고, 다음 턴 바로 코드 수정
   초안 작성이 가능한 수준으로 좁혀졌다. 다만 `allocation_quality`
   이중 반영 구조 자체는 이 안으로도 완전히 해소되지 않으며, 이는
   R2에서 다룰 사안으로 남긴다. **[2026-08-02 KST 4차 갱신] C안 코드
   수정 초안 적용 완료** — `_assess_core_risk_off_buy_guard()`가
   `ranking_score` 대신 `entry_score`+`portfolio_allocation`을 받아
   authoritative 게이트 점수를 그 자리에서 재계산하도록 변경했다
   (`buy_path_variable_gate_matrix.md` §13.1.5). 좁은 범위 검증
   (`accept backend-file`, 단위 테스트 24건, lint) 전부 통과했고,
   `ranking_score` 필드·shadow·reporting 경로는 무변화다. **[2026-08-02
   KST 5차 갱신] authoritative 게이트 명시식 2차 수정 완료**
   (`buy_path_variable_gate_matrix.md` §13.1.6) — `_build_buy_ranking_
   score()` 재호출을 제거하고 게이트 안에서 `entry_score`+`allocation_
   bonus_like`를 직접 계산하도록 바꿨다. 신규 회귀 테스트로 두 산식의
   일치를 고정했고, dev tree를 직접 mount한 임시 컨테이너에서 25
   passed 확인(로컬 harness 표준 명령은 별도 production 체크아웃을
   테스트하므로 병행 실행). **[2026-08-02 KST 재검증]** Codex 지적으로
   이 환경 설명을 다시 검증한 결과, 핵심 사실(별도 production 체크아웃
   mount)은 유지되나 "병합 전"이라는 시점 조건을 더 분명히 하는 정정을
   반영했다 — 머지·동기화가 끝나면 표준 명령도 즉시 정상 반영됨을
   원본 `run.sh`로 재확인(25 passed). 코드/테스트 결론에는 영향 없음.
   상세: `buy_path_variable_gate_matrix.md` §13.1.6 "검증 환경 설명
   재확인/정정". 이 질문은 2단계를 기다리지 않고 먼저 닫혔으며, 남은
   2~4번 질문과 R2~R4는 이 일정대로 진행한다(날짜 변경 없음).
- [ ] `portfolio_allocation`은 후보 점수에 남아야 하는가
- [ ] `relative_activity`는 soft bonus로 둘 이유가 남아 있는가

완료 조건 체크리스트:

- [x] 최소 2개 이상의 재설계 옵션 비교 완료
- [x] 옵션별 영향 범위 정리 완료
- [ ] 어떤 옵션이 1차 수정 후보인지 전체 상류 축 기준으로 최종 축소

판정 메모:

- R1은 사실상 종료됐다.
- R2는 allocation 제거까지 진행됐지만 운영 실측이 남아 있다.
- R3/R4가 아직 열려 있으므로 2단계 전체 완료로 닫지 않는다.

### 4.3 3단계 — 하류 연쇄 영향 검토

기간: **2026-08-07(금) ~ 2026-08-08(토) KST**

현재 상태: **미착수**

목적:

- 상류 리팩터링이 AI downgrade / EV gate / submit translation에 어떤
  파급을 주는지 확인
- 상류를 바꿨을 때 하류가 그대로 병목인지, 아니면 새 충돌이 생기는지
  판단

체크리스트:

- [ ] `candidate_vs_final`의 상류 변수 재사용 여부 정리
- [ ] EV gate의 상류 변수 재사용 여부 정리
- [ ] submit translation의 상류 변수 재사용 여부 정리
- [ ] "상류 먼저"로 충분한지 판정
- [ ] 하류 동시 개편 필요 여부 판정
- [ ] 리팩터링 범위를 상류 한정/상류+하류 병행으로 확정

### 4.4 4단계 — Roadmap 작성 전 착수 판정

기간: **2026-08-09(일) KST**

현재 상태: **미착수**

목적:

- 앞선 3단계 검토를 바탕으로 실제 리팩터링 Roadmap 작성 가능 상태인지
  판정

체크리스트:

- [ ] 1차 구현 범위를 1~2개 수정 단위로 축소
- [ ] 관측 포인트 정리
- [ ] 무변화 회귀 포인트 정리
- [ ] Roadmap 문서 입력 준비 완료

## 5. 왜 이 일정이 적절한가

이 일정은 바로 코드를 뜯는 대신 아래 위험을 먼저 피하려는 목적이다.

1. `entry_score`와 `ranking_score`를 동시에 건드려 해석 불가능해지는 위험
2. 상류를 바꿨는데 하류 병목 때문에 효과가 가려지는 위험
3. 역할 분리 없이 threshold만 다시 만지는 위험
4. alpha/risk/sizing/feasibility를 한 레이어에서 계속 섞는 위험

즉 이 일정은 구현 지연이 아니라 **리팩터링 단위를 해석 가능한 크기로
쪼개기 위한 일정**이다.

## 6. 현재 기준 체크리스트

즉시 시작 후보:

- [x] `entry_score` 내부 보정항 전수 표 작성
- [ ] `portfolio_allocation` 관련 값이 BUY 경로에서 몇 번 재사용되는지 전수 표 작성
- [ ] `candidate_vs_final` / EV gate / submit translation이 상류 변수와 어디서 다시
  만나는지 경로도 작성

현재 해석:

- 첫 번째 항목은 R2에서 이미 닫혔다.
- 두 번째 항목은 R3의 실질 시작점이다.
- 세 번째 항목은 R5의 실질 시작점이다.

## 7. Roadmap 작성 시점

Roadmap은 **1단계와 2단계가 끝난 뒤** 쓰는 것이 맞다.

이유는 아직 아래가 확정되지 않았기 때문이다.

1. 무엇을 alpha 레이어에 남길지
2. `ranking_score`를 유지할지 축소할지
3. `portfolio_allocation`을 점수에서 제거할지
4. 상류만 바꾸면 되는지, 하류도 같이 손대야 하는지

따라서 지금 시점의 적절한 산출물은 Roadmap이 아니라
**Roadmap 이전의 확인 검토 일정표**다.

## 8. 리팩터링 단위별 착수 순서 체크리스트

`buy_path_variable_gate_matrix.md`의 R1~R5 단위를 기준으로 하면,
사전 검토 일정의 실제 작업 순서는 아래처럼 읽는 것이 맞다.

### 8.1 1차 묶음 — R1

- 대상: `ranking_score`
- 목표:
  - 독립 공식 존치 여부
  - `entry_score` 재사용 구조 해소 여부
  - guard 보조 입력으로의 축소 가능성

체크리스트:

- [x] 독립 공식 존치 여부 판단 완료
- [x] `entry_score` 재사용 구조 해소 방향 결정 완료
- [x] guard 보조 입력 축소 가능성 검토 완료

판정:

- R1은 **완료**로 본다.

### 8.2 2차 묶음 — R2

- 대상: `entry_score`
- 목표:
  - alpha 전용화 가능성 검토
  - risk/sizing/activity/strategy 보정항 이관 후보 분류

체크리스트:

- [x] alpha/risk/sizing/activity/strategy 항목 분해 완료
- [x] allocation 보정항 구조 분리 완료
- [x] allocation 보정항 기여도 실측 완료
- [x] allocation 보정항 제거 적용 완료
- [ ] 제거 후 운영 데이터 재실측 완료
- [ ] authoritative 게이트 판정 이동폭 운영 재집계 완료

판정:

- R2는 **진행 중**으로 본다.
- 구현은 앞서갔지만 운영 실측과 후속 해석이 남아 있다.

**[2026-08-02 KST 갱신, R1 정리 후 착수 준비 완료]** `entry_score`
내부 6개 항목 전수 분해와 BUY 경로 재사용 매핑을 마쳤다(`buy_path_
variable_gate_matrix.md` §13.2.1). alpha·strategy·source-type은
유지, regime/risk·activity는 점수 밖 이관 검토, allocation은 중복
제거 최우선 후보로 판정했다 — `entry_score`를 alpha 전용으로 전면
재정의할 필요는 없고, 항목별 선택적 이관이 맞다는 결론이다. 다음
1순위 코드 수정 단위는 "`entry_score`의 allocation 보정항을 지역
변수로 명시적으로 분리하는 무변화 리팩터링"이며, 다음 턴 바로 코드
수정 초안 작성이 가능하다.

**[2026-08-02 KST 재갱신] R2 1차 단위 적용 완료**(`buy_path_variable_
gate_matrix.md` §13.2.2) — 위 1순위 단위를 실제로 적용해 `entry_
score_allocation_adjustment` 지역 변수로 분리했다. 무변화 리팩터링
이라 수치·threshold·shadow·reporting 전부 그대로이며, 제거/이관
여부 판단(2단계 나머지 목표)은 운영 실측 후 다음 턴으로 넘긴다.

**[2026-08-02 KST 3차 갱신] 기여도 실측 완료**(`buy_path_variable_
gate_matrix.md` §13.2.3) — `entry_score_allocation_adjustment` 덕분에만
`0.65`를 넘긴 표본(C 집합)이 최근 3거래일/1개월/전체 이력 모두 0건임을
확인했다. **판정 A(제거해도 영향 미미)**를 권고하며, 제거 vs 하드
게이트 전용 이관의 구체적 설계는 다음 턴 과제로 남긴다.

**[2026-08-02 KST 4차 갱신] 자본 보너스 점수 구조 분리 완료**
(`buy_path_variable_gate_matrix.md` §13.2.4) — `_build_entry_score_
allocation_adjustment()` helper로 추출해 entry_score 본체와 함수
경계로 나눴다. 동작 무변화(threshold·gate·shadow·reporting 전부
그대로)이며, 다음 턴은 이 helper를 대상으로 제거 vs 하드 게이트
전용 이관을 결정한다.

**[2026-08-02 KST 5차 갱신] entry_score에서 자본 보너스 점수 제거
적용 완료**(`buy_path_variable_gate_matrix.md` §13.2.5) — 위 helper
호출과 helper 자체를 entry_score 경로에서 제거했다. authoritative
게이트 쪽 로직은 유지했으나, entry_score가 게이트 입력이라 관련
fixture 5건의 경계값을 최소 범위로 재실측·보정했다(게이트 코드/
threshold는 무변화).

### 8.3 3차 묶음 — R3 + R4

- 대상:
  - `portfolio_allocation`
  - activity 계열
- 목표:
  - selection vs sizing vs feasibility 경계 재설정
  - soft bonus vs hard gate 중복 축소

이 두 축은 성격이 비슷하다. 둘 다 "좋은 종목인가"보다
"지금 들어갈 수 있는가" 쪽 의미가 더 강하기 때문이다.

체크리스트:

- [ ] R3 `portfolio_allocation` 역할 분리 검토 시작
- [ ] R4 activity 계열 soft/hard 중복 정리 시작
- [ ] selection vs sizing vs feasibility 경계 재설정
- [ ] soft bonus vs hard gate 중복 축소안 비교

### 8.4 4차 묶음 — R5

- 대상:
  - AI downgrade
  - EV gate
  - submit translation
- 목표:
  - 상류 리팩터링이 하류 contract를 깨지 않는지 확인
  - 필요 시 하류 contract 정리 범위를 따로 떼어낸다

체크리스트:

- [ ] AI downgrade 경로 점검
- [ ] EV gate 경로 점검
- [ ] submit translation 경로 점검
- [ ] 하류 contract 독립 정리 필요 여부 판정

### 8.5 현재 착수 판정

지금 바로 Roadmap으로 넘어가기보다, **R1 정의 고정 → R2 경계 확인**까지를
이번 사전 검토의 최소 완료선으로 보는 것이 적절하다.

현재 체크:

- [x] R1 정의 고정
- [ ] R2 경계 확인(운영 재실측 포함)
- [ ] Roadmap 작성 착수
