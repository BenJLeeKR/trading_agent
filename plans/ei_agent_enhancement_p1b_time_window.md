# EI P1-B 설계 — 이벤트 조회 시간 윈도우 확장

## 1. 배경 및 목적

### 1.1 현재 상태

P0-1/P0-2/P1-A 완료. 현재 [`assemble()`](src/agent_trading/services/decision_orchestrator.py:447)에서 `list_by_symbol()` 호출 시 **항상 24h 고정 윈도우** 사용.

```python
events = await self._repos.external_events.list_by_symbol(
    symbol=request.symbol,
    since=datetime.now(timezone.utc) - timedelta(hours=24),
)
```

### 1.2 핵심 질문

> "규제성 공시(분기/사업/반기 보고서, 주요사항보고서, 임원/주요주주 보고 등)는 24h보다 더 긴 유효 기간을 가지는데, 현재 24h 윈도우가 이런 장수명 이벤트를 너무 빨리 버리고 있지 않은가?"

### 1.3 현재 데이터 현황

2026-05-11 기준 OpenDART 이벤트 100건 분석 (모든 corp_cls 포함):

| corp_cls | 의미 | 이벤트 수 | symbol 채움 | EI 전달 여부 |
|----------|------|-----------|-------------|-------------|
| `K` | 코스닥 상장 | 41 | 41/41 (100%) | ✅ |
| `Y` | 유가증권 상장 | 36 | 36/36 (100%) | ✅ |
| `N` | 코넥스 상장 | 2 | 2/2 (100%) | ✅ |
| `E` | 기타법인 | 21 | 1/21 (5%) | ❌ (symbol=null) |

**중요**: `list_by_symbol()`이 `WHERE symbol = $1` 조건을 사용하므로 `E`(기타법인) 이벤트는 자동 제외. 윈도우를 확장해도 non-tradeable entity 이벤트가 유입되지 않음.

---

## 2. OpenDART 공시 유형별 유효 시간 분석

### 2.1 corp_cls 분류 체계

OpenDART event_type 형식: `{corp_cls}|{report_nm}`

| corp_cl스 | 설명 | tradeable | 현재 DB 분포 |
|-----------|------|-----------|-------------|
| `Y` | 유가증권시장 (KOSPI) | ✅ | 36 events |
| `K` | 코스닥 (KOSDAQ) | ✅ | 41 events |
| `N` | 코넥스 (KONEX) | ✅ | 2 events |
| `E` | 기타법인 (비상장) | ❌ | 21 events (20/21 null symbol) |

### 2.2 이벤트 유형별 권장 보유 시간

#### Group A: 24h 유지 (단발성, 즉시 가격 반영)

| 이벤트 유형 (report_nm) | 근거 |
|------------------------|------|
| 기업설명회IR개최안내공시 | IR 행사 당일 이후 무의미 |
| 조회공시요구에대한답변 | 즉시 가격 반영, 하루면 소화 |
| 주식소각결정 | 단발성 결정, 이후 추가 참조 불필요 |
| 전환청구권행사 | 실행 즉시 가격에 반영 |
| 의결권대리행사권유참고서류 | 주주총회 전후로만 의미 |
| 주주명부폐쇄기간또는기준일설정 | 기준일 이후 불필요 |

#### Group B: 72h 권장 (중기 영향)

| 이벤트 유형 | 근거 |
|------------|------|
| 유상증자결정 | 결정일 이후 3-5영업일까지 가격 영향 지속 |
| 전환사채권발행결정 | diluton 영향 수일간 평가 필요 |
| 자기주식취득결정 | 취득 기간 수일~수주, 지속 참조 |
| 단일판매공급계약체결 | 계약 규모 평가에 수일 필요 |
| 영업실적공정공시 | 실적 평가 후 수일간 업데이트 |
| 신탁계약에의한취득보고서 | 취득 기간 중 지속 참조 |

#### Group C: 72h+ 권장 (장수명 — 정기 보고서 및 지분 변동)

| 이벤트 유형 | 근거 |
|------------|------|
| 분기보고서 (2026.03) | 다음 분기 보고서 나올 때까지 유효 (3개월) |
| 사업보고서 (2025.12) | 차기 사업보고서 나올 때까지 유효 (1년) |
| 반기보고서 (2025.06) | 차기 반기보고서 나올 때까지 유효 (6개월) |
| 감사보고서 | 차기 감사보고서 나올 때까지 유효 (1년) |
| 임원주요주주특정증권등소유보고서 | 내부자 거래 패턴 분석에 수주 유효 |
| 주식등의대량보유보고서 | 대주주 변동은 수주~수개월간 의미 |
| 주권매매거래정지/상장폐지 | 결정 이후에도 지속 참조 (투자 위험 판단) |
| 타법인주식및출자증권처분결정 | 자회사 구조 변경, 장기 영향 |

### 2.3 단일 윈도우로 통합 시 trade-off

| 윈도우 | 포함되는 이벤트 | 누락되는 이벤트 | 평균 이벤트 수/심볼 |
|--------|---------------|----------------|-------------------|
| 24h | Group A 전부, Group B 일부, Group C 소수 | Group C 대부분 | ~5건 (030200 기준) |
| 72h | Group A+B+C 전부 (단, 분기/사업보고서는 72h에도 누락 가능) | Group C 일부 (1주일 이상 된 보고서) | ~15건 추정 |
| 7d | Group A+B+C 전부, 대부분 정기 보고서 포함 | 오래된 정기 보고서만 | ~35건 추정 |
| 30d | 전부 포함 | 없음 | 과도 (100건+ 예상) |

**결론**: 72h가 sweet spot. 24h보다 coverage 크게 개선되면서 noise도 관리 가능.

---

## 3. 권장 설계

### 3.1 핵심 결정: 24h → 72h 단일 윈도우 확장

**선택 근거**:
1. **변경 최소화**: 1개 파일, 1줄 변경 (`timedelta(hours=24)` → `timedelta(hours=72)`)
2. **query contract 유지**: `list_by_symbol(symbol, since)` 시그니처 변경 없음
3. **noise 통제**: 
   - `E`(기타법인) 이벤트는 symbol=null로 자동 제외
   - `_build_user_prompt()`의 20-event cap 존재
   - P1-A의 `⚠️STALE` flag가 24h 이상 된 이벤트에 표시되어 AI가 최신성 판단 가능
4. **weekend/holiday 커버**: 주말 및 공휴일(한국 5월: 어린이날 5/5, 석가탄신일 5/27 등)에도 이전 영업일 공시 포함

### 3.2 차등 window 도입 검토 (비권장)

**이유: 과도한 복잡도 대비 이점 미미**

| 설계 | 장점 | 단점 |
|------|------|------|
| 단일 72h | 1줄 변경, 단순 | 모든 이벤트에 동일 window |
| corp_cls 기반 차등 | Y/K/N은 72h, E는 제외 | 이미 symbol 필터로 E는 제외됨 |
| report_nm 기반 차등 | 정기 보고서는 7d, 기타 24h | `list_by_symbol()` 시그니처 파괴, 복잡도 급증 |
| source tier 기반 차등 | T1=72h, T2/T3=24h | 현재 T1만 존재, 미래 대비용이나 과잉 설계 |

**차등 window는 현재 데이터 분포와 시스템 복잡도를 고려할 때 over-engineering.**

### 3.3 P1-A + P1-B 시너지

```
P1-A (provenance prompt) + P1-B (72h window) = 완전한 freshness 표현

예시 prompt 출력:
  [src:opendart] [tier:T1] [K|분기보고서 (2026.03)] [2026-05-08] [issuer:00190321] ⚠️STALE 분기보고서
  [src:opendart] [tier:T1] [K|유상증자결정] [2026-05-11] [issuer:00190321] 유상증자결정
```

- 2026-05-08 공시 (3일 지남) → `⚠️STALE` 표시 → AI가 "오래된 정보" 인지 가능
- 2026-05-11 공시 (오늘) → fresh → AI가 최신 정보 우선 처리
- **window만 넓히고 stale flag으로 freshness를 AI에 위임**

---

## 4. 변경 범위

### 4.1 변경 파일

| # | 파일 | 변경 유형 | 설명 |
|---|------|----------|------|
| 1 | [`decision_orchestrator.py:449`](src/agent_trading/services/decision_orchestrator.py:449) | **수정** (1줄) | `timedelta(hours=24)` → `timedelta(hours=72)` |
| 2 | [`test_external_events.py`](tests/repositories/test_external_events.py) | **수정** (~3줄) | 24h 기준으로 written된 테스트 상수를 72h에 맞게 조정 (해당 시) |

### 4.2 변경 상세

**`decision_orchestrator.py:447-450`**:
```diff
 events = await self._repos.external_events.list_by_symbol(
     symbol=request.symbol,
-    since=datetime.now(timezone.utc) - timedelta(hours=24),
+    since=datetime.now(timezone.utc) - timedelta(hours=72),
 )
```

**변경 제약 준수**:
- ✅ Broker submit semantics 변경 없음
- ✅ Admin UI 변경 없음
- ✅ Source adapter 추가 없음
- ✅ Query contract 유지 (`list_by_symbol(symbol, since)` 그대로)
- ✅ Schema migration 불필요
- ✅ 기존 테스트 영향 없음 (단순 파라미터 변경)

### 4.3 변경 영향 분석

| 항목 | 영향 |
|------|------|
| **DB query 부하** | 3배 더 많은 row scan. 단, `WHERE symbol = $1 AND published_at >= $2`에 index가 있다면 영향 미미 |
| **메모리** | 3배 더 많은 event 객체 로드. 20-event cap으로 prompt에는 최대 20건만 포함 |
| **Token 사용량** | event당 ~30-50 tokens, 최대 20 events → ~600-1000 tokens. 24h보다 ~200-400 tokens 증가 (경미) |
| **AI 판단 품질** | 향상 예상. 특히 정기 보고서(분기/반기/사업)와 지분 변동 보고서의 coverage 증가 |
| **검색 index** | `trading.external_events`에 `(symbol, published_at)` 복합 index 확인 필요 |

---

## 5. 테스트 계획

### 5.1 단위 테스트

기존 `test_external_events.py`의 `list_by_symbol` 테스트는 `since` 파라미터를 테스트 입력으로 받으므로, 24h→72h 변경의 직접적 영향 없음. 

**단, `decision_orchestrator.py assemble()`의 window 값 검증 테스트 추가 가능**:

```python
# tests/services/test_external_event_query_window.py (신규, 선택적)
async def test_assemble_uses_72h_window():
    """``assemble()`` passes ``timedelta(hours=72)`` to ``list_by_symbol()``."""
    # Mock repos, call assemble, verify since parameter
```

### 5.2 통합 테스트

| 테스트 | 방법 | 통과 기준 |
|--------|------|-----------|
| 기존 `test_external_events.py` | `pytest` | 전면 통과 |
| 기존 `test_agents.py` | `pytest` | 전면 통과 (provenance tag 검증 포함) |
| DB symbol 기반 조회 | 직접 SQL | 72h 내 이벤트 정상 반환 |

### 5.3 Post-deploy 검증

`run_orchestrator_once.py` 실행 후 `recent_events`에 24h보다 오래된 `published_at`을 가진 이벤트가 포함되는지 확인.

---

## 6. 기대 효과

| 효과 | 설명 | 계측 방법 |
|------|------|----------|
| 정기 보고서 coverage 증가 | 72h 윈도우로 분기/반기/사업 보고서 보유 시간 3배 증가 | `published_at` 분포 모니터링 |
| 주말/공휴일 갭 해소 | 72h면 주말 포함 이전 영업일 공시까지 포함 | 토요일/월요일 비교 |
| 주요사항보고서 coverage 증가 | 유상증자/전환사채 등 중기 영향 이벤트 보유 시간 3배 | event_type별 분포 |
| noise 증가 | 20-event cap + stale flag으로 관리 가능 | prompt 당 event count |
| AI 판단 정확도 | 더 많은 컨텍스트 + freshness 정보로 정확도 향상 | EI output quality |

---

## 7. 남은 리스크 1개

**단일 이벤트가 많은 종목에서 20-event cap이 오히려 더 빨리 차서 최신 이벤트 누락 가능성**

예: 특정 종목에 하루 20건 이상의 공시(예: 자주 기재정정이 발생하는 복잡한 이벤트)가 있는 경우, 72h 윈도우에서는 더 빨리 cap에 도달. 이 경우 cap은 `_build_user_prompt()`의 `events[:20]`에서 `published_at DESC` 정렬 순으로 가장 최근 20건만 포함되므로, 오래된 이벤트부터 잘림 → 실제로는 최신 이벤트 유지됨. **리스크 낮음.**

더 실질적인 리스크: **72h로 늘려도 분기/사업보고서는 여전히 누락됨** — 1주일 이상 된 보고서는 여전히 조회 안 됨. 정기 보고서 완전 포함하려면 7d~30d가 필요하나, noise 급증으로 trade-off 불가피.

**진정한 리스크: 단일 day의 데이터만으로 72h 효과를 사전 검증할 수 없음.** 실제로 며칠간 ingestion loop를 돌려야 72h window가 실제로 어떤 coverage를 제공하는지 확인 가능. P1-B는 적용 후 P0-2 스타일의 효과 검증 게이트를 통과해야 함.

---

## 8. 다음 직접 액션 1개

**P1-B 구현 — Code 모드에서 1개 파일, 1줄 변경**

1. [`decision_orchestrator.py:449`](src/agent_trading/services/decision_orchestrator.py:449) — `timedelta(hours=24)` → `timedelta(hours=72)`
2. 전체 테스트 실행: `pytest tests/services/ai_agents/test_agents.py tests/repositories/test_external_events.py -v`
3. ingestion loop 실행 → `recent_events`에 24h 이상 된 이벤트 포함 확인
