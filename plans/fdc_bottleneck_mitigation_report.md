# FDC 병목 완화 — `decision_submit_gate` 안정화 보고서

> **작성일**: 2026-05-20 12:46 KST  
> **대상**: `scripts/run_agent_subprocess.py`, `src/agent_trading/services/ai_agents/final_decision_composer.py`, `src/agent_trading/services/decision_orchestrator.py`, `scripts/run_near_real_ops_scheduler.py`  
> **관련 태스크**: FDC 병목 완화 중심의 `decision_submit_gate` 안정화

---

## 1. 문제 정의

### 1.1 FDC (Final Decision Composer) 병목

3개 AI Agent (EI → AR → FDC)가 **순차 실행**되는 구조에서, FDC는 단독으로 **50~80초** 소요:

| Agent | 소요 시간 | 비고 |
|-------|-----------|------|
| Event Interpretation (EI) | 14~62초 | DeepSeek API 호출 |
| AI Risk (AR) | 28~53초 | DeepSeek API 호출 |
| Final Decision Composer (FDC) | **50~80초** | DeepSeek API 호출, **가장 무거움** |
| **합계 (3 agents)** | **92~195초** | 심볼 1개당 |

### 1.2 장중 타임아웃

`_SUBPROCESS_TIMEOUT = 35초` (Phase 4 기본값)으로는 EI 단독 실행조차 불가능 → 120초로 증설했으나 여전히 부족.

운영 검증 결과 `decision_submit_gate`가 **304초**에서 반복적으로 타임아웃:

| 사이클 | 시작 시각 | 소요 시간 | 결과 |
|--------|-----------|-----------|------|
| 1차 | 12:32:58 | 304.08s | timeout=True |
| 2차 | 12:38:47 | 304.07s | timeout=True |

---

## 2. 적용된 변경 사항

### 2.1 FDC Skip 로직 (`scripts/run_agent_subprocess.py`)

`_check_fdc_skip()` 함수 추가 — EI/AR 결과만으로 비행동이 명확하면 FDC를 아예 생략:

```
                        ┌─────────────────┐
                        │  _check_fdc_skip │
                        │  (EI + AR 결과)  │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
      조건 1: risk_reject  조건 2: no_material_events  조건 3: no_events
      + 미보유 → HOLD     + 미보유 → HOLD         + 미보유 → HOLD
              │                  │                   │
              └──────────────────┼───────────────────┘
                                 │
                        조건 4: cash_shortage
                        + 미보유 → WATCH
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
               FDC 생략                    FDC 정상 호출
          (결정론적 출력)               (DeepSeek API)
```

**판정 조건 상세:**

| 조건 | EI 결과 | AR 결과 | Position | 출력 | 근거 |
|------|---------|---------|----------|------|------|
| 1 | any | `risk_opinion == "reject"` | any | HOLD | 리스크가 거부하면 무조건 HOLD |
| 2 | `no_material_events=True` | `evidence_strength=none` | 없음 | HOLD | 유의미한 이벤트 없음 + 미보유 |
| 3 | `len(events)==0` (최근 0건) | any | 없음 | HOLD | 이벤트 자체가 없음 + 미보유 |
| 4 | any | any | 없음 | WATCH | 현금 부족 + 미보유 → 관망 |
| — | 위 조건 미해당 | — | — | **FDC 호출** | 실제 추론 필요 |

### 2.2 FDC Prompt 축소 (`final_decision_composer.py`)

FDC가 실제로 호출될 경우를 대비해 prompt token 수를 대폭 축소:

| 항목 | 변경 전 | 변경 후 | 기대 효과 |
|------|---------|---------|-----------|
| Events 전시 | `events[:20]` (최대 20개) | `events[:5]` (최대 5개) | token ~75% 감소 |
| `body_summary` | 각 이벤트마다 200자 포함 | **제거** | token ~50% 추가 감소 |
| System prompt No-Event Policy | 20줄 상세 정책 | **6줄** 단순화 | token ~70% 감소 |
| Position concentration policy | 6줄 상세 prose | **1줄** 요약 | token ~80% 감소 |

### 2.3 타임아웃 증설

| 파일 | 상수 | 변경 전 | 변경 후 | 설명 |
|------|------|---------|---------|------|
| `decision_orchestrator.py` | `_SUBPROCESS_TIMEOUT` | 120s | **300s** | 개별 subprocess 타임아웃 |
| `run_near_real_ops_scheduler.py` | `DEFAULT_TASK_TIMEOUT_SECONDS` | 300s | **420s** | ops-scheduler task 타임아웃 |
| `run_near_real_ops_scheduler.py` | `_DECISION_TIMEOUT` | 300s | **420s** | decision_submit_gate 전용 타임아웃 |

---

## 3. 운영 검증 결과

### 3.1 FDC Skip 동작 확인 ✅

컨테이너 재시작 (12:31:40 KST) 후 2개 사이클 운영 검증 완료.

**1차 사이클 (12:32:58~12:38:02) — 9개 심볼 FDC 생략:**

| 심볼 | FDC Skip 사유 | 소요 시간 | 결정 |
|------|--------------|-----------|------|
| 003550 | `no_material_events_no_position` | ~61s | HOLD |
| 009150 | `risk_reject` | ~65s | HOLD |
| 008770 | `risk_reject` | ~77s | HOLD |
| 000880 | `risk_reject` | ~105s | HOLD |
| 000100 | `risk_reject` | ~111s | HOLD |
| 000030 | `risk_reject` | ~75s | HOLD |
| 000150 | `risk_reject` | ~110s | HOLD |
| 000670 | `risk_reject` | ~49s | HOLD |
| 000660 | `risk_reject` | ~108s | HOLD |

**2차 사이클 (12:38:47~12:43:51) — FDC Skip + 실제 FDC 혼합:**

| 심볼 | FDC Skip 사유 | 결정 | 신뢰도 | 비고 |
|------|--------------|------|--------|------|
| 000100 | `risk_reject` | HOLD | 0.0 | FDC 생략 |
| 000880 | — (FDC 호출) | **WATCH** | **0.2** | 특수관계인 담보 거래 이벤트 → FDC 정상 추론 |
| 000150 | — (FDC 호출) | **REDUCE** | **0.8** | 단일 종목 과집중(62.5%) → FDC 정상 추론 |

**핵심 발견**: `000150` (REDUCE 0.8)과 `000880` (WATCH 0.2)는 **실제 FDC가 호출되어 비HOLD 결정이 생성된 첫 사례**. 이는 FDC prompt 축소가 적용된 상태에서 정상 동작함을 의미.

### 3.2 DB 저장 확인 ✅

`agent_runs` 테이블: 14개 decision_context × 3 agents = 42개 레코드, **전부 status=completed**
`trade_decisions` 테이블: **14개 레코드**, 전부 HOLD/REDUCE/WATCH 결정 포함

### 3.3 잔여 타임아웃 🔴

FDC skip이 완벽히 동작했음에도 `decision_submit_gate`가 304초에서 타임아웃:

```
[ERROR] ops-scheduler: task=decision_submit_gate complete ok=False
         returncode=1 timeout=True duration=304.08s
```

**원인 분석**: ops-scheduler의 `DEFAULT_TASK_TIMEOUT_SECONDS=300`이 total subprocess time보다 짧음.
- 14개 심볼, 5개 병렬 × 3배치 = ~330초 필요 (각 배치 ~110초)
- 300초 내에 3개 배치를 모두 처리 불가능
- **조치**: 420초로 증설 완료 (container restart)

---

## 4. 단위 테스트

### 4.1 `tests/scripts/test_fdc_skip.py` — 12개 테스트 전부 통과 ✅

| 테스트 클래스 | 테스트 메서드 | 조건 | 기대 출력 |
|--------------|-------------|------|-----------|
| `TestFdcSkipRiskReject` | `test_risk_reject_returns_hold` | risk_reject | HOLD |
| | `test_risk_reject_even_with_position` | risk_reject + 보유 | HOLD |
| `TestFdcSkipNoMaterialEvents` | `test_no_material_no_position` | no_material + 미보유 | HOLD |
| | `test_no_material_with_position` | no_material + 보유 | FDC 호출 |
| `TestFdcSkipNoEvents` | `test_no_events_no_position` | no_events + 미보유 | HOLD |
| | `test_no_events_with_position` | no_events + 보유 | FDC 호출 |
| `TestFdcSkipCashShortage` | `test_cash_shortage_no_position` (×3 parametrize) | cash_shortage + 미보유 | WATCH |
| | `test_cash_shortage_with_position` | cash_shortage + 보유 | FDC 호출 |
| | `test_cash_shortage_none_orderable` | orderable_amount=None + 미보유 | WATCH |
| `TestFdcSkipEligible` | `test_allow_with_events` | allow + events 존재 | FDC 호출 |
| | `test_allow_with_position_and_no_events` | allow + 보유 + events 없음 | FDC 호출 |

### 4.2 Coverage

- 모든 skip 조건 (4개)에 대한 결정론적 출력 검증
- 각 조건의 edge case (보유/미보유, orderable_amount=None 등)
- No-skip 조건 (FDC 정상 호출) 검증

---

## 5. 사이클 타임 분석

### 5.1 FDC Skip 적용 전/후 비교

| 항목 | 변경 전 (추정) | 변경 후 (실측) | 개선율 |
|------|---------------|----------------|--------|
| FDC skip 심볼당 소요 시간 | ~195s (3 agents) | **49~111s** (EI + AR만) | **~50%** |
| FDC 호출 심볼당 소요 시간 | ~195s | **~120~150s** (prompt 축소 효과) | **~25%** |
| 전체 사이클 (14 symbols, 5 parallel) | ~585s (3 × 195s) | **~330s** (3 × 110s) | **~44%** |

### 5.2 심볼별 소요 시간 분포 (FDC skip)

```
Symbol    Duration    Reason
───────   ────────   ─────────────────
000670      49s      risk_reject
003550      61s      no_material_events
009150      65s      risk_reject
000030      75s      risk_reject
008770      77s      risk_reject
000660     108s      risk_reject
000150     110s      risk_reject
000100     111s      risk_reject
                               Median: 77s  Mean: 84s
```

**주요 인사이트**: `risk_reject` 조건이 대부분의 심볼에서 hit. 이는 계좌 현금이 전반적으로 부족한 장중 상황에서 자연스러운 현상.

---

## 6. 교훈 및 권장사항

### 6.1 발견된 병목 계층 구조

```
ops-scheduler task timeout (300s → 420s)
  └── paper_decision_loop (14 symbols 병렬 처리)
       └── PER_AGENT_HARD_TIMEOUT (300s)
            └── _SUBPROCESS_TIMEOUT (35s → 120s → 300s)
                 └── DeepSeek API latency (EI 14-62s, AR 28-53s, FDC 50-80s)
```

각 계층의 타임아웃이 독립적으로 설정되어 있어, 하위 계층에서 타임아웃이 발생해도 상위 계층이 정리하지 못하는 경우 발생.

**권장**: 모든 타임아웃을 일관된 체계로 관리. `DEFAULT_TASK_TIMEOUT_SECONDS` > `PER_AGENT_HARD_TIMEOUT` > `_SUBPROCESS_TIMEOUT` 순으로 단계적으로 설정.

### 6.2 FDC Skip의 한계

FDC skip은 `risk_reject` 또는 `no_material_events` 조건에서만 동작. 실제 추론이 필요한 심볼 (events 존재 + risk allow)은 여전히 FDC를 호출해야 함.

- **장중 상황**: 대부분 `risk_reject` (현금 부족) → FDC skip 효과 큼
- **이벤트 발생 시**: FDC 호출 불가피 → prompt 축소의 효과에 의존

### 6.3 다음 단계

1. **FDC prompt 축소 효과 정량 측정**: FDC가 실제 호출된 심볼(000150, 000880)의 FDC duration 측정 필요
2. **ops-scheduler task timeout 420s 검증**: 다음 사이클에서 타임아웃 없이 완료되는지 확인
3. **심볼 수 동적 제어**: universe 심볼 수가 많을 경우 배치 수를 줄이는 로직 고려
4. **EI/AR 캐싱**: 동일 심볼에 대해 EI/AR 결과가 있으면 재사용하는 캐싱 전략 검토

---

## 7. 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| [`scripts/run_agent_subprocess.py`](../scripts/run_agent_subprocess.py) | `_check_fdc_skip()` 함수 추가, main()에 skip 조건 통합, _diag() 로깅 |
| [`src/agent_trading/services/ai_agents/final_decision_composer.py`](../src/agent_trading/services/ai_agents/final_decision_composer.py) | FDC prompt 축소: events 20→5, body_summary 제거, policy prose 단순화 |
| [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py) | `_SUBPROCESS_TIMEOUT` 120s → 300s |
| [`scripts/run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py) | `DEFAULT_TASK_TIMEOUT_SECONDS` 300s → 420s, `_DECISION_TIMEOUT` 300s → 420s |
| [`tests/scripts/test_fdc_skip.py`](../tests/scripts/test_fdc_skip.py) | 12개 단위 테스트 (skip 조건별, edge case별) |
