# 손실률 기반 Loss-cut 정책/설정 경로 도입 — 실행 계획

> **문서 성격**: 설계·실행 계획 문서다. 이 문서 자체는 어떤 코드도 변경하지 않는다. 구현 지시가 아니라 "무엇을, 왜, 어떤 순서로, 어떻게 검증할지"를 확정하는 계획이다.
> **상세 설계**: [`14_loss_cut_policy_specification_and_config_path_design.md`](../00_foundational_design/detailed_design/14_loss_cut_policy_specification_and_config_path_design.md)
> **선행 조사**: [`13_loss_cut_policy_investigation.md`](../00_foundational_design/detailed_design/13_loss_cut_policy_investigation.md)
> **연관 선례**: `risk.max_single_position_pct`의 `config_versions` + Admin API/CLI 관리 경로(PR #216 계열, [`06_config_schema.md`](../00_foundational_design/detailed_design/06_config_schema.md) §9)

## 1. 문제 배경

현재 운영 코드에는 매수가(평균단가) 대비 손실률 기준의 정량 손절
(Loss-cut) 규칙이 없다. 보유 포지션 청산은 전부 신호 기반(AI
risk_opinion/risk_score, thesis invalidation, edge collapse,
downside shock, holding_profile 만료)이다. 이 사실은
`13_loss_cut_policy_investigation.md`에서 소스 기준으로 확인했고,
이번 문서가 다루는 것은 그 다음 단계 — **정책 명세를 구현 직전
수준까지 구체화**하는 것이다. 아직 기존 held_position 청산 경로에
실제로 연결하는 구현(B단계)은 하지 않는다.

## 2. 왜 지금 필요한가

- `max_single_position_pct=10→5`를 실제로 config_versions 경로로
  적용한 직후, 같은 계열의 다음 정책값(loss-cut)에 대해서도 같은
  질문(어떤 규칙? 어떤 설정 경로?)이 제기됐다 — 하나의 선례가 있을
  때 다음 정책값을 설계하는 것이 가장 저렴하다(이미 검증된 API/CLI
  패턴을 그대로 재사용 가능).
- "손절이 필요해 보인다"는 정성적 판단만으로 구현에 들어가면, 이
  저장소가 반복적으로 지켜온 원칙(기대값 개선 여부를 사후 성과로
  검증한 뒤에만 정책화, `[PRIORITY_MAP]` 공통 판단 원칙)을 어기게
  된다. 이번 계획은 **구현 전 shadow 검증 단계를 필수 관문으로
  명시**해 그 원칙을 지킨다.

## 3. 단계별 계획

### 0단계 — 정책 조사(완료)

- 산출물: `13_loss_cut_policy_investigation.md` — 현재 코드에
  손실률 기반 loss-cut 없음을 확인, 정책안 3종(A/B/C) 1차 비교,
  설정 경로가 `env`가 아니라 `config_versions`여야 하는 1차 근거.
- 상태: **완료**(2026-08-11, PR #226).

### 1단계 — 정책 명세 + 설정 경로 설계 초안(이번 턴, 완료)

- 왜: 0단계의 비교표만으로는 구현 착수가 불가능하다 — 실제
  threshold 구조, source_type 차등 여부, 기존 로직과의 합성/우선순위
  규칙, 기준 가격, cooldown, config 스키마, API/CLI 계약까지
  구체화해야 B단계 착수가 가능하다.
- 산출물: `14_loss_cut_policy_specification_and_config_path_
  design.md` — 2단계(soft/hard) 정책 구조 추천, guard 삽입 위치
  구체 지정(`_check_held_position_sell_override`와
  `_check_held_position_exit_hysteresis_gate` 사이), 기존
  hysteresis escape-hatch 키워드(`"stop_loss"`/`"drawdown"`) 재사용
  설계, `risk.loss_cut` config_json 스키마 초안, Admin API/CLI 계약
  초안(`reason` 필수화 등 기존 계약과의 명시적 차이 포함).
- **이번 단계에서 하지 않은 것**: 코드 구현, 마이그레이션, API 추가,
  런타임 변경 — 전부 문서/설계로만 진행했다.
- 검증 명령: `bash scripts/harness/run.sh accept docs`.
- 상태: **완료**(2026-08-11, 이번 PR).

### 2단계 — Shadow 계산기 구현(미착수, 다음 후보)

- 왜: 실제 거래 결정을 바꾸지 않고, "loss-cut이 있었다면 어떤
  성과였을까"를 먼저 관측해야 §5(정책 확정)로 넘어갈 근거가 생긴다.
- 산출물(예정): `scripts/validate_r3b_stop_loss_ablation.py` 패턴을
  상시 관측 스크립트/서비스로 승격. `LOSS_CUT_SHADOW_ENABLED` env로
  게이팅(설계 문서 §4.3 — 이 플래그는 로그 여부만 제어, 실거래
  결정에는 개입하지 않음). `decision_orchestrator.py`의 실제 guard
  체인은 건드리지 않는다.
- 착수 전 확인: 사용자 승인(별도 턴), shadow 관측 표본 크기 기준
  확정.
- 상태: **미착수**.

### 3단계 — Shadow 누적 실측(미착수)

- 왜: 표본이 쌓여야 "발동 표본 vs 미발동 표본" 사후 성과 비교가
  가능하다.
- 산출물(예정): 누적 이력(JSONL 또는 유사 구조, 기존
  `regime_conditional_signal_shadow_history.jsonl`류 관례 재사용),
  주기적 실측 보고.
- 상태: **미착수**.

### 4단계 — 정책 확정(미착수)

- 왜: 설계 문서 §3.1의 soft/hard 임계치, §3.5의 cooldown 시간 등
  구체 숫자는 실측 없이 정할 수 없다(이 저장소의 "빈도가 아니라
  기대값 개선으로 판단" 원칙).
- 산출물(예정): 확정된 임계치/cooldown 값, 사용자 최종 승인.
- 상태: **미착수**.

### 5단계 — Admin API/CLI 구현(미착수)

- 왜: 정책이 확정된 뒤에야 그 정책을 발행할 관리 경로가 의미를
  갖는다 — 값이 정해지지 않은 상태에서 API부터 만들면 스키마
  재작업 위험이 있다.
- 산출물(예정): `services/config_version_admin.py`에
  `publish_loss_cut_policy()` 추가(설계 문서 §4.4 계약),
  `POST /config-versions/risk/loss-cut-policy`,
  `scripts/publish_loss_cut_policy.py`, 대응 테스트(기존
  `max_single_position_pct` PR들과 동일한 검증 절차: `py-compile`,
  `accept style`, `accept no-bypass`, `accept architecture`,
  컨테이너 대체 pytest).
- 상태: **미착수**.

### 6단계 — `decision_orchestrator.py` 연결(미착수)

- 왜: 이 단계에서 비로소 실제 거래 결정에 영향을 준다 — 가장 신중해야
  하는 단계.
- 산출물(예정): 설계 문서 §3.3의 `_check_loss_cut_override` guard
  삽입, `_check_held_position_sell_override` 시그니처에
  `position_snapshot` 전달 추가, `SymbolTradeStateEntity.metadata_
  json`에 cooldown 필드 추가(마이그레이션 불필요 — 기존 자유 형식
  필드 재사용).
- 안전 원칙: `src/AGENTS.md`의 "매매 의미론, 리스크 정책, 주문
  크기 산정, 주문 제출, 정합성 상태 전이는 명시적 근거와 검증 없이
  바꾸지 않는다" 원칙에 따라, 회귀 테스트 없이 이 단계를 진행하지
  않는다.
- 상태: **미착수**.

### 7단계 — 운영 전환(미착수)

- 왜: 실제로 `risk.loss_cut.enabled=true`를 발행하는 단계 —
  장중 배포 금지 원칙을 그대로 적용한다(이 저장소의 반복 관례,
  submit budget 2단계 분리 작업 등에서 이미 확립됨).
- 상태: **미착수**.

## 4. 검증 기준(이번 1단계 한정)

- `bash scripts/harness/run.sh accept docs` — PASS 필요.
- 코드/스키마 변경이 없으므로 `accept architecture`/`accept style`/
  `accept no-bypass`는 이번 단계에서 필수로 요구하지 않는다(실행
  시 이유를 완료 보고에 남긴다).

## 5. 남은 리스크 / 후속 확인 필요 사항

`14_loss_cut_policy_specification_and_config_path_design.md` §6과
동일 — 이 문서에서 중복 나열하지 않는다. 핵심만 재인용:

- soft/hard 임계치 구체 숫자 미확정(shadow 실측 필요).
- loss-cut과 기존 hysteresis gate의 우선순위 설계(부분적 우선,
  완전 우회 아님)에 대한 사용자 명시 확인 필요.
- held_position에 대한 더 타이트한 override 여부는 데이터 없이
  판단 불가.

## 6. `[PRIORITY_MAP]` / `[BACKLOG]` 반영

- `[PRIORITY_MAP] remaining_work_priority_map.md`: 이번 1단계
  완료를 append. 다음 주력 작업이 `SPPV-3`임은 2026-08-11 이전
  항목에서 이미 명시했고, 이번 항목은 그 우선순위를 바꾸지 않는다 —
  Loss-cut 2단계(shadow) 착수는 여전히 "정책 결정 대기" 상태다.
- `[BACKLOG] backlog.md`: 이번 설계 초안으로 답한 질문(정책 구조,
  합성 규칙, 설정 경로)과 여전히 열려 있는 질문(임계치 숫자,
  우선순위 최종 확인, held_position 차등 여부)을 구분해 갱신한다.
