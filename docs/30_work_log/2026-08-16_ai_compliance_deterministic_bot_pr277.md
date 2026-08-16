# AI Compliance Deterministic Bot 전환 검증 기록

## 목적

PR #277은 `ai_compliance`를 LLM 호출 기반 Agent에서 deterministic bot으로
전환하고, subprocess rehydrate에서 `ai_compliance` `agent_runs` 기록이
누락되던 문제를 수정한다. AR(`ai_risk`)과 EI(`event_interpretation`)는
이번 PR에서 대체하지 않고 후속 shadow bot 대상으로 남긴다.

## 변경 요약

- `DeterministicAIComplianceAgent`를 추가해 기존 `AIComplianceOutput`
  스키마를 그대로 반환한다.
- in-process wiring(`runtime/bootstrap.py`)과 subprocess wiring
  (`scripts/run_agent_subprocess.py`) 모두에서 AC 경로가 provider 설정과
  무관하게 deterministic bot을 사용한다.
- 기존 `agent_type`/`agent_name`은 `ai_compliance`로 유지한다. API/UI와
  기존 분석 쿼리 호환을 위한 선택이며, deterministic 판단 여부는
  `reason_codes`의 `compliance_rule_set:*`와 `summary`로 구분한다.
- subprocess rehydrate 로직을 `_rehydrate_subprocess_agent_runs()`로
  분리하고 EI/AR/AC/FDC 4개를 모두 기록하도록 수정했다.
- AR/EI shadow bot은 후속 PR로 분리했다.

## 검증 결과

Codex 재검증 기준:

- 브랜치: `feature/ai-compliance-deterministic-bot-2026-08-16`
- HEAD: `9726c62d`
- PR: #277
- PR 상태 확인 시점: 2026-08-16 UTC

직접 재실행한 검증:

| 명령 | 결과 |
| --- | --- |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_ai_compliance_deterministic.py` | 10 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` | 20 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` | 70 passed |

GitHub PR check 상태:

- `Deployment change detector`: SUCCESS
- `Safe harness contracts`: SUCCESS
- heavy/deploy 계열 check: SKIPPED
- `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`

## 판정

PR #277은 코드와 테스트 기준으로 머지 가능하다. 단, "정책 영향 없음"은
"새로운 hard block 또는 submit gate 추가 없음"으로 좁게 해석해야 한다.
AC output이 FDC 입력으로 들어가므로, 기존의 항상 default `allow` 신호가
deterministic `warn`/`review` 신호로 바뀌는 경우 FDC 판단에는 간접 영향이
생길 수 있다.

## 배포 후 확인할 항목

- 다음 거래일 실제 decision cycle 이후 `agent_runs`에 `ai_compliance` row가
  EI/AR/FDC와 함께 쌓이는지 확인한다.
- `trade_decisions.decision_json.compliance_*`가 더 이상 전부 default
  (`allow`, `0.0`, `[]`)로만 남지 않는지 확인한다.
- `guardrail_evaluations.rule_results.ai_compliance_alignment`가 의미 있는
  alignment telemetry를 남기는지 확인한다.

## 후속 작업

- AR shadow bot: `risk_opinion`, `risk_score` bucket, held_position
  override, FDC skip, execution risk-off 일치율을 기록한다.
- EI shadow bot: 정형 이벤트 detection, event bias, reason code,
  no-material-event 판정 일치율을 기록한다.
- AR/EI shadow output은 실제 `decision_type`, 주문 생성, 주문 수량에 영향을
  주지 않는 관측 전용으로 시작한다.
