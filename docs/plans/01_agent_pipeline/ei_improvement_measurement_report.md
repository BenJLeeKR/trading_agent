# EI 입력 품질 및 전파 경로 계측 보고서

## 1. 생성한 측정 스크립트/문서

| 파일 | 설명 |
|------|------|
| [`scripts/ei_improvement_measurement.py`](scripts/ei_improvement_measurement.py) | Read-only 계측 스크립트. 3개 symbol old/new EI prompt 비교, AR/FDC downstream gap 분석, AR Symbol line BUG 재현 |
| [`plans/ei_improvement_measurement_plan.md`](plans/ei_improvement_measurement_plan.md) | 계측 계획 문서 (표현 규칙 4건, 계측 항목 7종 포함) |

**실행 명령**:
```bash
cd /workspace/agent_trading && . /workspace/agent_trading/.env && python3 -m scripts.ei_improvement_measurement
```

**Exit code**: `0` ✅

---

## 2. 사용한 symbol 3개와 선택 근거

| Symbol | Event 수 | Event 유형 | Issuer | 선택 이유 |
|--------|----------|------------|--------|----------|
| `030200` | 5건 | `Y\|임원ㆍ주요주주특정증권등소유상황보고서` (5x 동일) | `00190321` | 동일 유형 5회 반복 → 중복/반복 처리 평가 최적 |
| `327260` | 4건 | `K\|[기재정정]주요사항보고서(유상증자결정)`, `K\|[발행조건확정]증권신고서(지분증권)`, `K\|권리락(유상증자)`, `K\|투자설명서` | `01343665` | 유상증자 관련 다양한 이벤트 → 해석 다양성 평가 최적 |
| `090150` | 4건 | `K\|전환가액의조정` (2x), `K\|주주명부폐쇄기간또는기준일설정`, `K\|주주총회소집결의` | `00365624` | 채권/주총 관련 이벤트 → impact 방향성 평가 최적 |

**모든 event `published_at=2026-05-11`로 동일** → P1-B(72h) 효과는 구조적으로 분명하나 현재 데이터 분포상 직접 계측은 제한적.

---

## 3. Old vs new EI prompt 차이 요약

### 3.1 Token 증가량

| Symbol | Old tokens (est) | New tokens (est) | 증가율 |
|--------|-----------------|-----------------|--------|
| `030200` | 87 | 155 | **+78.2%** |
| `327260` | 71 | 125 | **+76.1%** |
| `090150` | 84 | 138 | **+64.3%** |

### 3.2 Provenance tag 포함

| Tag | 030200 | 327260 | 090150 |
|-----|--------|--------|--------|
| `[src:opendart]` | ✅ 5x | ✅ 4x | ✅ 4x |
| `[tier:T1]` | ✅ 5x | ✅ 4x | ✅ 4x |
| `[issuer:...]` | ✅ 5x | ✅ 4x | ✅ 4x |
| `[YYYY-MM-DD]` | ✅ 5x | ✅ 4x | ✅ 4x |
| `[event_type]` | ✅ 5x | ✅ 4x | ✅ 4x |

### 3.3 Default 생략 규칙

| 규칙 | 결과 |
|------|------|
| `severity=medium` (default) 생략 | ✅ 모든 symbol에서 미포함 |
| `direction=neutral` (default) 생략 | ✅ 모든 symbol에서 미포함 |
| `⚠️STALE` (ingested_at < 24h) 미표시 | ✅ 모든 symbol에서 미포함 (fresh events) |

### 3.4 Format 차이 (실제 excerpt)

**New-style (P1-A 적용)**:
```
  [src:opendart] [tier:T1] [Y|임원ㆍ주요주주특정증권등소유상황보고서] [2026-05-11] [issuer:00190321] 임원ㆍ주요주주특정증권등소유상황보고서
```

**Old-style (P1-A 이전)**:
```
  - [Y|임원ㆍ주요주주특정증권등소유상황보고서] 임원ㆍ주요주주특정증권등소유상황보고서
```

**차이점**:
1. New-style: `[src:opendart] [tier:T1]` — 출처 및 신뢰도 정보 추가
2. New-style: `[2026-05-11]` — 공시 날짜 명시
3. New-style: `[issuer:00190321]` — 발행사 코드 명시
4. New-style: dash prefix(`  -`) 제거 → `  ` space prefix로 변경
5. New-style: event당 ~30 chars 증가 (provenance tags)

---

## 4. AR/FDC downstream gap 요약

### 4.1 Raw provenance 전파 상태

| 경로 | 상태 | 근거 |
|------|------|------|
| EI prompt → AR prompt (raw events) | ❌ **단절** | AR `_build_user_prompt()` line 391-398: `  - [{event_type}] {headline}` — provenance tag count = 0 |
| EI prompt → FDC prompt (raw events) | ❌ **단절** | FDC `_build_user_prompt()` line 324-332: `  - [{event_type}] {headline}` — provenance tag count = 0 |
| EI prompt → AR prompt (no EI output) | ❌ **단절** | EI output이 없어도 raw events는 old format으로 표시 |

### 4.2 EI structured field continuity (간접 전파)

| 필드 | AR 포함 | FDC 포함 | 전파 상태 |
|------|---------|---------|-----------|
| `aggregate_view.overall_bias` | ✅ | ✅ | ✅ 전파됨 |
| `aggregate_view.event_conflict` | ✅ | ✅ | ✅ 전파됨 |
| `aggregate_view.top_reason_codes` | ✅ | ✅ | ✅ 전파됨 |
| `events[].summary` (해석 요약) | ✅ | ✅ | ✅ 전파됨 (10개 cap) |
| `events[].impact_direction` | ✅ | ✅ | ✅ 전파됨 |
| `events[].confidence` | ✅ | ✅ | ✅ 전파됨 |
| AR → FDC: `risk_opinion` | — | ✅ | ✅ 전파됨 |

### 4.3 AR Symbol line BUG 관찰 결과

**예상**: `Symbol: 030200`
**실제**: `Symbol: (not available)`

`request.context.decision_context`가 `None`인 경우 `"(not available)"`로 fallback.
`DecisionContextEntity` 객체가 설정된 경우에는 객체 `__repr__()`이 출력됨.

→ **조건부 BUG**: `decision_context=None`이면 단순 fallback, `decision_context`가 설정되면 객체 repr 누출.

---

## 5. 4개 핵심 질문 최종 판정

### Q1. Provenance tag로 EI 해석에 필요한 입력 정보가 유의미하게 풍부해졌는가?

**판정**: ✅ **유의미함**

| 근거 | 수치 |
|------|------|
| 모든 symbol에서 `[src:]`, `[tier:]`, `[issuer:]` tag 정상 포함 | 3/3 symbol ✅ |
| Event당 token 약 60-78% 증가 | 평균 **+72.9%** |
| Default severity/direction 생략 규칙 정상 작동 | 3/3 symbol ✅ |
| Stale mark 정확성 (fresh event에 미표시) | 3/3 symbol ✅ |

**단, '해석력 직접 향상'은 provider 호출 검증 필요** — 본 계측은 입력 정보 풍부화 수준까지 확인.

### Q2. 72h retention 효과는?

**판정**: ⚠️ **구조적으로 분명하나, 현재 데이터 분포상 직접 계측은 제한적**

- `decision_orchestrator.py:449` — `timedelta(hours=72)` 정상 적용 완료
- `ei_realpath_verification.py` — SQL `WHERE published_at >= $2` 조건 정상 작동 확인
- 현재 모든 event `published_at=2026-05-11`로 24h/72h 결과 동일
- 향후 ingestion loop가 며칠간 돌아 다양한 `published_at` 데이터가 쌓이면 재계측 필요

### Q3. EI local improvement vs system-wide realized improvement?

**판정**: 🟡 **EI local improvement는 강함, system-wide realized improvement는 제한적**

| 영역 | 수준 | 근거 |
|------|------|------|
| **EI local** (P1-A prompt) | ✅ **강함** | 5종 provenance tag + stale + default 생략 → LLM context quality 대폭 향상 |
| **EI output → AR** | 🟡 **간접 전파** | `aggregate_view` + interpreted events summaries 전달되나, raw provenance 없음 |
| **EI output → FDC** | 🟡 **간접 전파** | 동일하게 EI aggregate + summaries 전달 |
| **Raw events → AR/FDC** | ❌ **미전파** | AR/FDC events 섹션은 provenance tag 없이 old format |

### Q4. Downstream 전파 상태?

**판정**: 🔴 **raw provenance downstream 전파는 단절, EI structured summary를 통한 간접 전파는 일부 존재**

| 경로 | 상태 |
|------|------|
| Raw provenance direct 전파 (AR) | ❌ **단절** |
| Raw provenance direct 전파 (FDC) | ❌ **단절** |
| EI structured summary 간접 전파 | ✅ **일부 존재** (overall_bias, event_conflict, top_reason_codes, interpreted summaries) |
| AR Symbol line | 🟡 조건부 BUG (decision_context=None이면 fallback, 설정되면 객체 repr) |

---

## 6. 남은 리스크 1개

**AR/FDC events 섹션에 provenance tag 미전파 (구조적 gap)**

```
EI prompt:     [src:opendart] [tier:T1] [Y|임원...] [2026-05-11] [issuer:00190321] 임원...
AR/FDC prompt:   - [Y|임원...] 임원...  ← provenance tag 모두 소실
```

- 영향: downstream agent(AR, FDC)가 event의 source/신뢰도/날짜/발행사 정보 없이 판단
- 심각도: **High** — P1-A의 개선이 EI에만 머물고 AR/FDC로 전파되지 않음
- AR Symbol line: `decision_context=None`이면 `"(not available)"` fallback, 설정되면 객체 repr 누출

---

## 7. 다음 직접 액션 1개

**AR `_build_user_prompt()` events 섹션에 provenance tag 전파**

대상 파일 및 변경 범위:

| 파일 | 위치 | 변경 내용 |
|------|------|----------|
| [`src/agent_trading/services/ai_agents/ai_risk.py`](src/agent_trading/services/ai_agents/ai_risk.py:391-398) | `_build_user_prompt()` events 루프 | `  - [{event_type}] {headline}` → `[src:...] [tier:...] [{event_type}] [date] [issuer:...] {headline}` |
| [`src/agent_trading/services/ai_agents/final_decision_composer.py`](src/agent_trading/services/ai_agents/final_decision_composer.py:324-332) | `_build_user_prompt()` events 루프 | 동일 변경 |
| [`src/agent_trading/services/ai_agents/ai_risk.py`](src/agent_trading/services/ai_agents/ai_risk.py:291) | `Symbol:` line | `request.context.decision_context` → `request.context.decision_context.symbol if request.context.decision_context else '(not available)'` |

변경 전/후 prompt diff를 `scripts/ei_improvement_measurement.py`로 재검증 가능.
