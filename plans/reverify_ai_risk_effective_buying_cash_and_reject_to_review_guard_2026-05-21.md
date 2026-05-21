# AR 2계층 방어 실제 운영 반영 검증 보고서

**검증 일시**: 2026-05-21 20:50 KST (11:50 UTC)  
**검증자**: Roo (Debug mode)  
**대상 코드**: [`src/agent_trading/services/ai_agents/ai_risk.py`](/workspace/agent_trading/src/agent_trading/services/ai_agents/ai_risk.py)

---

## 1. 검증 개요

### 방어 구조

| 계층 | 위치 | 내용 |
|------|------|--------|
| **Layer 1 (Prompt)** | [`_build_user_prompt()`](src/agent_trading/services/ai_agents/ai_risk.py:315) L411–433 | `effective_buying_cash = orderable_amount` 우선, `available_cash`는 회계 참조용 |
| **Layer 2 (Guard)** | [`run()`](src/agent_trading/services/ai_agents/ai_risk.py:197) L197–235 | `orderable_amount > 0`인데 LLM이 `reject` 출력 → `review`로 완화 |

### 코드 배포 상태

- **파일 최종 수정**: 2026-05-21 **20:41:55 KST** (11:41:55 UTC) — **현재 검증 시점 기준 약 10분 전**
- **Docker 이미지**: 빌드 완료 (`sha256:37cea1d16bad`)
- **ops-scheduler 컨테이너**: 재시작 완료 (20:44 KST), 컨테이너 내 코드 확인 완료 — Layer 1 + Layer 2 모두 존재

### 중요 발견

**DB에 존재하는 모든 AR run (6,243건)은 Layer 2 guard 미적용 상태**입니다.  
코드가 20:41 KST에야 수정되었고, 그 이전 run은 OLD 코드로 생성되었습니다.

---

## 2. 최신 AR agent_runs 비교표 (15건)

모든 run이 동일한 cash_balance_snapshot 사용:
- `available_cash = -6,629,580` (음수)
- `orderable_amount = 9,050,070` (양수)

| # | Symbol | Time (UTC) | available_cash | orderable_amount | risk_opinion | Layer 2 적용? | Summary 핵심 |
|---|--------|-----------|---------------|-----------------|-------------|-------------|-------------|
| 1 | 001680 | 06:33:41 | -6,629,580 | 9,050,070 | **reject** | ❌ (OLD code) | "현금이 -6,629,580원으로 부족" |
| 2 | 001230 | 06:33:37 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 잔고가 음수" |
| 3 | 001440 | 06:33:36 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 잔고가 심각한 마이너스" |
| 4 | 001040 | 06:33:34 | -6,629,580 | 9,050,070 | **review** | ❌ | "가용 현금이 음수... 검토 필요" |
| 5 | 000990 | 06:32:20 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 잔고가 심각한 마이너스" |
| 6 | 000100 | 06:32:05 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 및 예수금이 모두 마이너스" |
| 7 | 000210 | 06:32:00 | -6,629,580 | 9,050,070 | **reject** | ❌ | "가용 현금이 -6,629,580원으로 부족" |
| 8 | 000670 | 06:31:19 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 잔고가 마이너스" |
| 9 | 000660 | 06:31:04 | -6,629,580 | 9,050,070 | **review** | ❌ | "현금 잔고가 마이너스... 검토" |
| 10 | 000880 | 06:30:59 | -6,629,580 | 9,050,070 | **reject** | ❌ | "사용 가능한 현금이 음수 상태" |
| 11 | 000270 | 06:29:48 | -6,629,580 | 9,050,070 | **review** | ❌ | "현금 잔고가 마이너스... 검토 필요" |
| 12 | 000720 | 06:28:51 | -6,629,580 | 9,050,070 | **review** | ❌ | "현금 잔고가 음수... 검토 필요" |
| 13 | 000810 | 06:28:14 | -6,629,580 | 9,050,070 | **reject** | ❌ | "포지션 집중도 20.3% 초과" |
| 14 | 000030 | 06:28:04 | -6,629,580 | 9,050,070 | **reject** | ❌ | "현금 잔고가 음수" |
| 15 | 000150 | 06:27:51 | -6,629,580 | 9,050,070 | **reject** | ❌ | "포지션 집중도 40.0%... 마이너스" |

### 관찰

- 15건 중 **11건(73%)이 `reject`**, **4건(27%)이 `review`**
- `review` 4건(001040, 000660, 000270, 000720)은 LLM이 자발적으로 review를 선택 (Layer 2 guard 없이)
- LLM이 **음수 `available_cash`에 집중**하여 `effective_buying_cash`(9,050,070)를 무시하는 패턴

---

## 3. 수정 전후 비교 (Before / After)

### BEFORE (2026-05-21 02:40 UTC 이전, OLD code)

| Symbol | Time | available_cash | orderable_amount | risk_opinion | Summary |
|--------|------|---------------|-----------------|-------------|---------|
| 000990 | 02:39:31 | -6,629,580 | **None** | reject | "현금이 심각한 마이너스" |
| 000660 | 02:39:07 | -6,629,580 | **None** | reduce | "집중도 67.1%... 포지션 축소" |
| 000210 | 02:38:39 | -6,629,580 | **None** | reject | "현금 잔고 심각한 마이너스" |
| 000270 | 02:37:44 | -6,629,580 | **None** | reject | "가용 현금 마이너스" |
| 000150 | 02:37:32 | -6,629,580 | **None** | reject | "집중도 40.2% 초과, 가용 현금 마이너스" |

### AFTER (2026-05-21 02:40 UTC 이후, Layer 1 Prompt 적용됨)

| Symbol | Time | available_cash | orderable_amount | risk_opinion | Summary |
|--------|------|---------------|-----------------|-------------|---------|
| 001680 | 06:33:41 | -6,629,580 | **9,050,070** | reject | "현금이 -6,629,580원으로 부족" |
| 001230 | 06:33:37 | -6,629,580 | **9,050,070** | reject | "현금 잔고가 음수" |
| 001440 | 06:33:36 | -6,629,580 | **9,050,070** | reject | "현금 잔고가 심각한 마이너스" |
| 001040 | 06:33:34 | -6,629,580 | **9,050,070** | **review** | "가용 현금이 음수... 검토 필요" |
| 000990 | 06:32:20 | -6,629,580 | **9,050,070** | reject | "현금 잔고가 심각한 마이너스" |

### 비교 분석

| 항목 | BEFORE | AFTER |
|------|--------|-------|
| `orderable_amount` | `None` (미활용) | `9,050,070` (조회 가능) |
| Layer 1 Prompt | `available_cash`만 표시 | `effective_buying_cash=9,050,070` + 가이드 |
| Layer 2 Guard | **없음** | **있음** (단, 아직 실행 안 됨) |
| `reject` 비율 | 4/5 (80%) | 4/5 (80%) — **개선 없음** |
| `review` 비율 | 0/5 (0%) | 1/5 (20%) — LLM 자발적 |
| Summary 문구 | "available_cash 부족" 중심 | "available_cash 부족" 중심 — **개선 없음** |

**Layer 1 (Prompt) 효과**: LLM이 prompt의 `effective_buying_cash` 가이드를 무시하고 여전히 `available_cash`(음수)에 집중.  
**Layer 2 (Guard)**: 아직 실행 안 됨 (OLD 코드로 생성된 run).

---

## 4. Layer 2 Guard 로그 확인 결과

| 확인 대상 | 결과 |
|-----------|-------|
| ops-scheduler 컨테이너 로그 (`docker compose logs`) | `"Layer2 Guard applied"` 패턴 **없음** |
| `/workspace/agent_trading/logs/` 디렉토리 | 해당 패턴 **없음** |
| `grep`으로 전체 로그 검색 | **미발견** |

**원인**: Layer 2 guard 코드가 20:41 KST에 배포되었으며, 이후 스케줄러가 아직 AR 에이전트를 실행하지 않음 (장 마감).

---

## 5. FDC Downstream 영향

### FDC 최신 5건 (AR run 직후)

| Symbol | AR risk_opinion | FDC decision_type | FDC summary |
|--------|----------------|-------------------|-------------|
| 001680 | reject | **HOLD** | "리스크 평가 'reject'. FDC 생략." |
| 001230 | reject | **HOLD** | "리스크 평가 'reject'. FDC 생략." |
| 001440 | reject | **HOLD** | "리스크 평가 'reject'. FDC 생략." |
| 001040 | **review** | **HOLD** | "유의미한 이벤트 없음. FDC 생략." |
| 000990 | reject | **HOLD** | "리스크 평가 'reject'. FDC 생략." |

### FDC 전체 분포 (6,243건)

| decision_type | 건수 | 비율 |
|--------------|------|------|
| HOLD | 5,794 | 92.8% |
| REDUCE | 179 | 2.9% |
| WATCH | 135 | 2.2% |
| APPROVE | 104 | 1.7% |
| BUY | 29 | 0.5% |
| EXIT | 2 | 0.03% |

### 영향 분석

- **현재**: AR이 `reject` → FDC "리스크 평가 'reject'. FDC 생략." → **HOLD**
- **Layer 2 적용 시**: AR `reject → review` → FDC가 실제 판단 수행 → APPROVE/REDUCE/HOLD 등 다양한 결정 가능
- **주의**: `review`여도 이벤트가 없으면 ("유의미한 이벤트 없음") FDC가 여전히 HOLD

---

## 6. 최종 판정: ⚠️ **부분 개선 (Pending)**

### 6.1 질문별 답변

| # | 질문 | 답변 | 근거 |
|---|------|------|------|
| 1 | 최신 AR output이 `effective_buying_cash` 기준으로 바뀌었는가? | **❌ 미개선** | LLM이 prompt 가이드를 무시하고 `available_cash`(음수)에 집중. summary도 "현금 부족" 위주. Layer 1 개선이 LLM 행동에 반영되지 않음. |
| 2 | `orderable_amount > 0`인데 `reject`가 남아 있는가? | **✅ 남아 있음** | 15건 중 11건(73%)이 `orderable_amount=9,050,070`인데도 `reject` |
| 3 | `reject → review` 완화가 DB/로그에 관측되는가? | **❌ 관측 안 됨** | Layer 2 guard 코드가 20:41 KST에 배포되었고 아직 실행 안 됨. 기존 run들은 OLD 코드로 생성. |
| 4 | summary/rationale 문구도 개선되었는가? | **❌ 미개선** | AFTER run들의 summary도 "available_cash 부족"만 언급, `effective_buying_cash` 언급 없음 |
| 5 | 최종 판정 | **⚠️ 부분 개선** | • Layer 1: 코드 배포됨, 컨테이너 확인 완료, **실행 검증은 차기 장중 필요**<br>• Layer 2: 코드 배포됨, 컨테이너 확인 완료, **실행 검증은 차기 장중 필요**<br>• 현재 DB 데이터: 모두 OLD 코드 |

### 6.2 핵심 리스크

**LLM이 prompt 가이드를 무시하는 문제**는 Layer 1만으로 해결되지 않습니다.  
Layer 2 guard가 반드시 필요하며, 이 guard가 `reject → review`로 변환해야만 FDC가 실제 판단을 수행합니다.

---

## 7. Follow-up TODO

- [ ] **2026-05-22 장중 검증**: ops-scheduler가 다음 장중 AR run을 생성한 후, 아래 항목 재확인 필요
  - [ ] Layer 2 guard 로그 (`"Layer2 Guard applied: orderable_amount=... > 0 but risk_opinion='reject' → downgraded to 'review'"`) 출력 확인
  - [ ] DB에서 `orderable_amount > 0`인 run의 `risk_opinion`이 `review`로 저장되는지 확인
  - [ ] FDC가 `review`에 대해 실제 판단(APPROVE/REDUCE 등)을 수행하는지 확인
  - [ ] LLM summary에 `effective_buying_cash` 언급이 나타나는지 확인 (Layer 1 장기 효과)
- [ ] **Layer 1 보강 검토**: LLM이 계속 `available_cash`(음수)에 집중한다면, prompt에 더 강력한 지시 필요
- [ ] **Layer 2 로그 모니터링**: `"Layer2 Guard applied"` 발생 횟수/추이 대시보드 추가 고려

---

## 부록: 검증 명령어 히스토리

```bash
# 1. 최신 AR runs + cash_balance 매핑 조회
docker compose run --rm app python3 -c "(SQL: trading.agent_runs + decision_contexts + cash_balance_snapshots JOIN)"

# 2. Before/After 비교 (cutoff: 2026-05-21 02:40 UTC)
docker compose run --rm app python3 -c "(SQL: created_at < 02:40 UTC vs >= 02:40 UTC)"

# 3. Layer 2 guard 로그 검색
docker compose logs ops-scheduler 2>&1 | grep -i "layer2\|guard"
grep -r "Layer2 Guard applied" /workspace/agent_trading/logs/

# 4. FDC downstream 확인
docker compose run --rm app python3 -c "(SQL: trading.agent_runs WHERE agent_type='final_decision_composer')"

# 5. 코드 배포 확인
docker compose exec ops-scheduler grep -n "Layer2 Guard\|effective_buying_cash" /app/src/agent_trading/services/ai_agents/ai_risk.py
```
