# 휴장일 KIS Reject Live Smoke Test — EI/Sizing/Submit Path 검증

> **목적**: 리팩토링(Phase 2 Final Cleanup) 후, 휴장일 조건에서 KIS reject까지 포함한 end-to-end smoke test
> **일시**: 2026-05-25 (월) KST — 한국 시장 휴장일 (DB `market_sessions` 확인 완료)
> **방법**: `run_orchestrator_once.py` — assemble-only 우선, 이후 --submit 1회
> **위험**: 체결 위험 0% (휴장일)

---

## 1. 검증 범위

| 단계 | 검증 항목 | 방법 |
|------|----------|------|
| 1 | EI Agent 실행 및 판단 결과 생성 | assemble-only 출력 확인 |
| 2 | AR/FDC Agent 실행 및 decision assembly | assemble-only 출력 확인 |
| 3 | Sizing engine 정상 동작 | submit 시 sizing 로그 확인 |
| 4 | Translation → ExecutionService → OrderManager 경계 | submit 로그 확인 |
| 5 | KIS submit API 호출 시도 | submit 로그 확인 |
| 6 | 휴장일 BrokerError → ERROR status 처리 | submit 결과 status 확인 |
| 7 | DB persist 정상 동작 (TradeDecision, AgentRun 등) | DB 조회 |

## 2. 실행 계획

### Phase 1: Assemble-only (안전)

```bash
cd /workspace/agent_trading
python -m scripts.run_orchestrator_once --output json
```

- AI Agent (EI/AR/FDC) 실행
- TradeDecisionEntity DB persist
- Broker API 호출 없음
- 출력: decision_context_id, order_intent_id, decision_type, reason_codes, config_version_id

### Phase 2: Submit 1회 (휴장일 reject 예상)

```bash
cd /workspace/agent_trading
python -m scripts.run_orchestrator_once --submit --output json
```

- Phase 1 assemble 실행
- Phase 1.5 Sizing engine 실행
- Phase 2-4 Translation/Create/Submit
- Phase 5 KIS API 호출 → 휴장일 BrokerError
- SubmitResult(status="ERROR", error_phase="order_submit") 예상

### Phase 3: DB/API 검증

```bash
# TradeDecision 확인
psql "$DATABASE_URL" -c "SELECT decision_id, status, decision_type, created_at FROM trading.trade_decisions ORDER BY created_at DESC LIMIT 3;"

# AgentRun 확인
psql "$DATABASE_URL" -c "SELECT agent_run_id, agent_type, status, started_at FROM trading.agent_runs ORDER BY started_at DESC LIMIT 10;"

# ExecutionAttempt 확인
psql "$DATABASE_URL" -c "SELECT attempt_id, order_id, status, error_message, started_at FROM trading.execution_attempts ORDER BY started_at DESC LIMIT 3;"
```

## 3. 예상 결과

| 항목 | Assemble-only | Submit |
|------|--------------|--------|
| EI 판단 결과 | 생성됨 (decision_type, reason_codes) | 동일 |
| Sizing 결과 | N/A | 계산됨 (로그에서 확인) |
| TradeDecision DB 저장 | ✅ | ✅ |
| AgentRun DB 저장 | ✅ | ✅ |
| ExecutionAttempt DB 저장 | N/A | ✅ (실패 상태) |
| KIS API 호출 | 없음 | ✅ (시도) |
| BrokerError 발생 | 없음 | ✅ (OPR00001) |
| 최종 status | assemble-only (별도) | **ERROR** (error_phase="order_submit") |

## 4. 리스크 체크리스트

- [x] 오늘 휴장일 확인 (DB market_sessions)
- [x] Symbol: 005930 (삼성전자, 가장 안전)
- [x] 단발 실행 보장 (run_orchestrator_once는 단일 실행 전용)
- [x] 체결 위험 0% (휴장일)
- [x] LLM API key 필요 (assemble-only에서 AI agent 실행)
- [x] KIS credential 선택사항 (submit에서만 필요)
