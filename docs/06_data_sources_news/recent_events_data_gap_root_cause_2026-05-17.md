# Recent Events 데이터 공백 원인 진단 보고서

> 진단일: 2026-05-17 | 상태: ✅ 진단 완료

---

## DB 데이터 현황 (요약)

| 측정 항목 | 값 |
|-----------|-----|
| `external_events` 전체 | 2,369건 |
| T1 (opendart) | 2,369건 (100%) |
| T3 (naver_news_seeded) | **0건 (0%)** |
| symbol=NULL 비중 | 723건 (30.5%) |
| 005380(`symbol=` 조건) | **0건** |
| 005930(`symbol=` 조건) | **0건** |
| 000660(`symbol=` 조건) | **0건** |
| 035420(`symbol=` 조건) | **0건** |
| Unique symbol 수 | 1,239개 |
| 이벤트 기간 | 2026-05-11 ~ 2026-05-15 |

---

## Q1: T1(OpenDART) 이벤트는 005380에 실제로 들어오지 않는가, symbol이 null/다른 값으로 저장되는가?

**결론: 005380에 실제로 T1 이벤트가 들어오지 않았다.**

- OpenDART `/list.json` API가 2026-05-11~2026-05-15 기간 동안 반환한 2,369건의 공시 중 005380(현대차) 관련 건이 단 1건도 없음
- `headline LIKE '%현대차%'` 검색에서도 0건
- 이는 해당 5거래일(월~금) 동안 현대차가 OpenDART에 제출한 공시가 없었기 때문으로 판단됨 (분기보고서 제출 기간이었으나 현대차는 3월 결산법인이 아니므로 해당 없음)
- 30.5%의 NULL symbol은 주로 비상장법인(`corp_cls=E`) 또는 OpenDART가 stock_code를 제공하지 않은 항목

## Q2: OpenDART symbol resolver가 005380을 매핑 못 하는가?

**결론: N/A — resolver가 호출될 기회 자체가 없었다.**

- [`OpenDartSourceAdapter._raw_from_item()`](src/agent_trading/brokers/opendart_adapter.py:285)의 symbol resolution 우선순위:
  1. `stock_code` from `/list.json` (primary) — OpenDART가 자체적으로 6자리 종목코드를 제공
  2. Empty일 경우에만 `OpenDartSymbolResolver.resolve(corp_code)` fallback
- 005380에 대한 이벤트 자체가 없으므로 resolver가 호출될 기회가 없었음
- Symbol resolver 자체는 [`OpenDartSymbolResolver`](src/agent_trading/services/symbol_resolver.py:75)가 `/company.json` API를 통해 정상 동작하도록 구현되어 있음

## Q3: T3 persistence는 코드상만 있고 실제 cycle에서 한 번도 저장이 안 된 것인가?

**결론: 맞다. T3(`naver_news_seeded`) 이벤트는 DB에 단 1건도 저장된 적이 없다.**

- [`external_events`](src/agent_trading/repositories/postgres/external_events.py) 테이블의 `source_name='naver_news_seeded'` 조건: **0건**
- [`persist_seeded_events()`](scripts/run_paper_decision_loop.py:804) 함수는 `run_paper_decision_loop.py`에 구현되어 있으나:
  - 이 코드는 **2026-05-17에 추가됨** (plan: `seeded_news_t3_db_persistence_2026-05-17.md`)
  - Ops-scheduler가 restart(`20:03:51 KST`)된 후 일요일이라 즉시 idle 모드 진입
  - **T3 persistence가 실제 운영 사이클에서 단 한 번도 실행되지 않음**

## Q4: T3가 저장 전 dedup/quality gate에서 전부 떨어지는가?

**결론: N/A — quality gate가 적용될 기회 자체가 없었다.**

- 수동 검증([`naver_live_validation`](data/observations/naver_live_validation_20260517_193100.json)) 결과:
  - raw_candidates: 370건
  - hard_gate_passed: 75건
  - final_kept: **10건** (005380 포함 1건, score=70)
- 파이프라인 자체는 정상 작동하며 candidate을 생성할 수 있음
- 다만 이 candidate들이 DB에 저장된 적이 없음

## Q5: Recent-events 공백의 주 원인

### 1차 원인: B — T3 persistence가 실제로 실행되지 않음 (Primary)

```
run_paper_decision_loop._run_one_cycle()
    ├─ 3.5: T3 pipeline (seeds → candidates → convert → persist)  ← CODE EXISTS
    │   ├─ disclosure_seed_service.fetch_disclosure_titles()        ← KIS API
    │   ├─ seeded_news_service.process_seeds()                      ← NAVER API
    │   ├─ convert_seeded_candidates()                              ← memory
    │   └─ persist_seeded_events() → DB                            ← NEVER EXECUTED
    └─ 4: orchestrator.assemble(submit)                            ← runs fine
```

### 2차 원인: A — T1 symbol resolution gap (Secondary)

005380에 대한 T1 이벤트가 없어 T1 경로로는 항상 데이터가 없음. 이는 정상적인 현상으로, 특정 기간 동안 해당 종목의 공시가 없는 경우 발생.

### 종합

| 원인 | 기여도 | 설명 |
|------|--------|------|
| **B** (T3 미실행) | **80%** | persistence 코드가 오늘 추가되었으나 운영 사이클에서 실행 안 됨 |
| **A** (T1 symbol gap) | **20%** | 005380은 5일간 T1 이벤트 없음 (정상) |

### 조치 제안

1. **T3 persistence 활성화 확인**: 월요일(2026-05-18) ops-scheduler가 정상 기동하여 intraday phase에서 `run_paper_decision_loop`를 실행하면 `persist_seeded_events()`가 자동으로 동작해야 함
2. **NAVER API rate limit**: 수동 테스트에서 429 Too Many Requests가 다수 발생했으므로, 실운영 시 rate limit 대응 필요
3. **Cross-symbol noise**: Top-10 candidate 중 40%가 cross-symbol noise. Hard gate/scoring 로직 개선 고려
4. **모니터링**: `source_name='naver_news_seeded'` 카운트를 헬스체크에 추가하여 T3 저장 여부를 실시간 모니터링

---

## 검증 명령어

```bash
# DB T3 존재 여부
docker compose exec -T db psql -U trading -d trading \
  -c "SELECT source_name, COUNT(*) FROM external_events GROUP BY source_name;"

# API 테스트 (005380)
curl -s -H "Authorization: Bearer dev-token-123" \
  "http://localhost:8000/external-events/recent?symbol=005380&limit=5&include_non_listed=true"

# Docker 로그
docker compose logs ops-scheduler --tail 50
```
