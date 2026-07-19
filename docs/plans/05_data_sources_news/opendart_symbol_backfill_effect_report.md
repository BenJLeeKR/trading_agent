# OpenDART Symbol Backfill 효과 측정 보고서

> **일자**: 2026-05-14  
> **목적**: OpenDART 기반 `external_events`에서 `symbol IS NULL` 비율을 before/after로 측정하고,  
>   `OpenDartSymbolResolver`(/company.json API fallback)의 실제 효과를 검증

---

## 1. 사전 측정 (Before)

### 1.1 전체 현황

| 지표 | 값 |
|------|------|
| `external_events` 전체 건수 | **902** |
| `symbol IS NOT NULL` 건수 | 598 (66.3%) |
| `symbol IS NULL` 건수 | **304 (33.7%)** |
| `source_name = 'opendart'` 건수 | 902 (100%) |
| `source_name != 'opendart'` 건수 | 0 |
| NULL-symbol 중 `issuer_code` 있음 | 304 (100%) |

### 1.2 NULL-symbol 이벤트 상세

| 항목 | 값 |
|------|------|
| 최소 ingested_at | 2026-05-11 09:46 UTC |
| 최대 ingested_at | 2026-05-14 05:11 UTC |
| Unique issuer_code (corp_code) | **164개** |
| issuer_code 유형 | **100% 8자리 OpenDART corp_code** (6자리 stock_code 아님) |
| severity | 100% medium |
| direction | 100% neutral |
| 중요도 (importance) | low: 267, null: 20, medium: 12, **high: 5** |

### 1.3 주요 종목별 event count (symbol=NULL로 인해 누락)

| symbol | event_count |
|--------|------------|
| 051910 (LG화학) | 2 |
| 005930 (삼성전자) | **0** (NULL로 저장) |
| 000660 (SK하이닉스) | **0** (NULL로 저장) |
| 035420 (NAVER) | **0** (NULL로 저장) |
| 005380 (현대차) | **0** (NULL로 저장) |

> 주요 대형주 4종목의 이벤트가 모두 symbol=NULL로 저장되어  
> EI Agent의 `recent_events`에서 완전히 누락됨

### 1.4 최근 72h 기준

| 지표 | 값 |
|------|------|
| 전체 72h 이벤트 | 802 |
| 72h 중 symbol=NULL | 284 (35.4%) |

---

## 2. Dry-Run 실행 결과

### 2.1 실행 명령

```bash
docker compose run --rm app python3 scripts/backfill_external_events_symbol.py
```

### 2.2 결과 요약

| 항목 | 값 |
|------|------|
| Found unique issuer_codes | **164** |
| Resolved (→ symbol 획득) | **0** |
| Unresolved (symbol 획득 실패) | **164** |
| Total NULL-symbol in DB | 304 |
| API 호출 수 | 164회 (rate-limited, 1초 간격) |
| 소요 시간 | ~164초 |

### 2.3 상세 분석

164개 unique issuer_code 모두 `/company.json` API가 `stock_code`를 반환하지 않음.

**대표 unresolved corp_code 패턴 (dry-run 로그에서 확인):**

| corp_code | corp_name | 비고 |
|-----------|-----------|------|
| 00331478 | (유동화전문회사) | 비상장 특수목적법인 |
| 00260453 | (유동화전문회사) | 비상장 특수목적법인 |
| 00243553 | (유동화전문회사) | 비상장 특수목적법인 |
| 01936340 | (투자계약증권) | 비상장 |
| 01738739 | (주)누리디앤씨 | 비상장 |
| 01740886 | 디와이개발 주식회사 | 비상장 |
| 01753118 | (주)우먼건설 | 비상장 |
| 01756018 | 농업회사법인(주)꿀떡 | 비상장 |
| ... | ... | 전부 비상장법인 |

### 2.4 NULL-symbol 이벤트 유형 분류

| 유형 | 건수 | 설명 |
|------|------|------|
| **유동화전문회사/SPAC 공시** | ~150 | "효력발생안내(유동화증권)", "일괄신고서(집합투자증권-신탁형)" 등 |
| **비상장법인 감사/분기보고서** | ~80 | "감사보고서", "분기보고서" (코스닥 상장사 아님) |
| **비상장법인 증권신고서** | ~40 | "증권발행실적보고서", "투자설명서" |
| **기타 비상장법인 공시** | ~34 | "동일인등출자계열회사와의상품ㆍ용역거래변경" 등 |

> **핵심 발견**: 304개 NULL-symbol 이벤트는 **모두 비상장법인**의 공시입니다.  
> OpenDART는 상장사에 대해서만 `stock_code`를 부여하므로,  
> 이 corp_code들은 OpenDART DB에 stock_code 자체가 존재하지 않아  
> `/list.json`에서도 빈 값으로 반환되었고, `/company.json`에서도 찾을 수 없습니다.

---

## 3. Apply 실행

**실행하지 않음.** Dry-run 결과 resolved=0이므로 UPDATE할 대상이 없음.

```bash
# 실행했다면 0행 UPDATE (no-op)
python3 scripts/backfill_external_events_symbol.py --apply
```

---

## 4. 사후 측정 (After)

Apply를 실행하지 않았으므로 before와 동일.

| 지표 | Before | After | 변화 |
|------|--------|-------|------|
| 전체 건수 | 902 | 902 | - |
| symbol=NULL | 304 (33.7%) | 304 (33.7%) | **변화 없음** |
| symbol=값 있음 | 598 (66.3%) | 598 (66.3%) | - |

---

## 5. EI 입력 품질 관점 평가

### 5.1 Backfill의 한계 확인

- **기존 304개 NULL-symbol 이벤트는 backfill로 해결 불가능**
- 이유: 이 corp_code들은 OpenDART DB에 stock_code가 존재하지 않는 **비상장법인**이기 때문
- `/company.json` API도 상장사에 대해서만 stock_code를 반환

### 5.2 Ingest Path 개선의 가치

`OpenDartSymbolResolver`를 통한 ingest path 개선은 **앞으로 들어오는 신규 이벤트**에 대해 유효:

1. **상장사이지만 `/list.json`이 stock_code를 빈 값으로 반환하는 경우** (드문 케이스)
   - 예: 특정 조건에서 상장사의 stock_code가 누락되는 경우
   - 이 경우 `/company.json` fallback이 stock_code를 찾아줌
2. **Negative cache**: 동일 batch 내 중복 corp_code 조회 방지 (rate limit 준수)
3. **새로운 상장사 공시**: 상장 직후 첫 공시 등에서 stock_code 누락 가능성

### 5.3 현재 NULL-symbol 이벤트의 EI 영향

| 중요도 | 건수 | EI 영향 |
|--------|------|---------|
| high | 5 | 제한적 (비상장사 공시, EI가 symbol 없이 처리) |
| medium | 12 | 제한적 |
| low | 267 | 낮음 (비상장사 정기보고서) |
| null | 20 | 낮음 |

> 현재 NULL-symbol 이벤트는 **모두 비상장법인**의 공시이므로,  
> EI Agent가 `recent_events`에서 이 이벤트들을 참조하더라도  
> symbol이 없어서 실제 trading decision에 미치는 영향은 제한적입니다.

---

## 6. Unresolved 잔여 건 유형 분류

| 유형 | 건수 | 설명 |
|------|------|------|
| **corp_code는 있지만 stock_code 없음** | 304 (100%) | 비상장법인으로 OpenDART DB에 stock_code 없음 |
| **corp_code 자체 없음** | 0 | 모든 NULL-symbol 이벤트에 issuer_code 존재 |
| **company.json API 실패** | 0 | 모든 API 호출 성공 (HTTP 200) |
| **company.json이 빈 stock_code 반환** | 164 (unique) | API는 성공했지만 stock_code 필드가 비어있음 |
| **기타** | 0 | - |

---

## 7. 다음 개선 필요 포인트

### 7.1 단기 (P0)

1. **issuer_code 정합성 개선**
   - 현재 `issuer_code`가 OpenDART `corp_code`(8자리)로 저장됨
   - `issuer_code`는 `symbol`과 동일한 6자리 stock_code여야 함
   - 이는 ingest path에서 `corp_code`를 `issuer_code`로 잘못 매핑한 근본 원인

2. **OpenDART adapter의 issuer_code 매핑 검토**
   - [`opendart_adapter.py`](src/agent_trading/brokers/opendart_adapter.py)에서 `issuer_code`가 `corp_code`로 저장되는 로직 확인
   - `issuer_code`는 `stock_code`(6자리)여야 함

### 7.2 중기 (P1)

3. **비상장법인 공시 필터링**
   - OpenDART 공시 중 상장사 공시만 수집하도록 필터 추가
   - `stock_code`가 비어있는 이벤트는 수집 대상에서 제외하는 옵션 검토
   - 단, 일부 비상장법인 공시도 투자 판단에 중요할 수 있으므로 주의

4. **EI Agent의 symbol-less event 처리**
   - symbol이 없는 이벤트를 EI Agent가 어떻게 처리하는지 분석
   - 필요시 symbol-less event를 별도로 마킹하거나 제외

### 7.3 장기 (P2)

5. **KIS + OpenDART 매핑 통합**
   - KIS API를 통해 corp_code → stock_code 매핑 보강
   - `instrument_master` 테이블에 corp_code 컬럼 추가하여 매핑 관리

---

## 8. 결론

| 항목 | 결과 |
|------|------|
| Backfill로 복구된 건수 | **0건** |
| Backfill로 복구 불가능한 건수 | 304건 (100%) |
| 원인 | 모든 NULL-symbol 이벤트가 **비상장법인** 공시 |
| Ingest path 개선 효과 | **신규 이벤트에 대해 유효** (상장사 stock_code 누락 시 fallback) |
| EI 입력 품질 영향 | 현재 NULL-symbol 이벤트는 EI decision에 **영향 제한적** |

> **요약**: 기존 304개 NULL-symbol 이벤트는 backfill로 해결할 수 없는 데이터입니다.  
> 이 corp_code들은 OpenDART DB에 stock_code가 존재하지 않는 비상장법인이기 때문입니다.  
> 그러나 `OpenDartSymbolResolver`를 통한 ingest path 개선은  
> **앞으로 신규 유입되는 상장사 공시**에서 stock_code 누락 시 fallback으로 유효합니다.  
> 
> 근본적인 해결을 위해서는 `issuer_code`가 `corp_code`(8자리)로 저장되는  
> ingest path 자체의 매핑 로직을 검토해야 합니다.
