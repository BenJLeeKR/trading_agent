# OpenDART Symbol Mapping 개선 구현 계획

## 1. 현재 상태 분석

### 현재 매핑 로직 (`opendart_adapter.py:260`)
```python
symbol=item.get("stock_code") or None,
```

### NULL 발생 원인
- OpenDART `/list.json`가 `stock_code`를 빈 값으로 반환하는 경우
  - 비상장법인 (corp_cls="E" = 기타법인)
  - 상장폐지 종목
  - 일부 특수목적법인
- `corp_code`(8자리 고유번호)는 항상 존재하지만 symbol lookup에 사용되지 않음
- 현재 DB `instruments` 테이블에는 `issuer_code` 컬럼이 없음

### 해결 전략
1. **1차 (즉시)**: OpenDART `/company.json` API로 `corp_code → stock_code` 실시간 조회
2. **2차 (fallback)**: 수집된 `corp_code`-`stock_code` 매핑 캐시
3. **3차 (backfill)**: 기존 `symbol=NULL` 데이터 업데이트 경로

---

## 2. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `src/agent_trading/brokers/opendart_adapter.py` | 수정 | OpenDartSymbolResolver 통합, fallback 로직 |
| `src/agent_trading/services/symbol_resolver.py` | **신규** | OpenDART 전용 corp_code → symbol 매핑 서비스 |
| `tests/brokers/test_opendart_adapter.py` | 수정 | 신규 매핑 경로 테스트 추가 |
| `tests/services/test_symbol_resolver.py` | **신규** | OpenDartSymbolResolver 단위 테스트 |
| `scripts/backfill_external_events_symbol.py` | **신규** | 기존 NULL symbol backfill |

---

## 3. 상세 설계

### 3.1 `OpenDartSymbolResolver` (신규)

- **OpenDART 전용** — 범용 resolver로 오해되지 않도록 클래스명 명시
- **인메모리 캐시**: `corp_code → str | None` — 성공/실패 모두 캐싱 (negative cache)
- **동일 batch 내 중복 corp_code → 1회만 API 호출**
- 실패한 corp_code도 캐시에 기록하여 재조회 방지

```python
class OpenDartSymbolResolver:
    """OpenDART 전용 corp_code → stock_code resolver.
    
    OpenDART /company.json API를 사용하여 corp_code(8자리 고유번호)를
    stock_code(6자리 종목코드)로 매핑한다.
    
    - 성공/실패 모두 인메모리 캐싱 (negative cache 포함)
    - 동일 batch 내 중복 corp_code는 1회만 API 호출
    - 이 클래스는 OpenDART 전용이며, KIS/기타 소스의 symbol 매핑은 담당하지 않는다.
    """
    
    def __init__(self, api_key: str, base_url: str = OPENDART_BASE_URL):
        self._api_key = api_key
        self._base_url = base_url
        self._cache: dict[str, str | None] = {}  # corp_code → symbol (None = negative cache)
        self._client: httpx.AsyncClient | None = None
    
    async def resolve(self, corp_code: str) -> str | None:
        """corp_code → stock_code. 캐시 히트 시 API 호출 없음."""
        if corp_code in self._cache:
            return self._cache[corp_code]
        
        symbol = await self._fetch_symbol(corp_code)
        self._cache[corp_code] = symbol  # negative cache 포함
        return symbol
    
    async def _fetch_symbol(self, corp_code: str) -> str | None:
        """/company.json API 호출."""
        ...
```

### 3.2 `OpenDartSourceAdapter` 변경

**`__init__`에 `symbol_resolver` 파라미터 추가:**
```python
def __init__(
    self,
    api_key: str,
    base_url: str = OPENDART_BASE_URL,
    request_timeout: int = 30,
    symbol_resolver: SymbolResolver | None = None,
) -> None:
```

**`_raw_from_item()`에 fallback 경로 추가:**
```python
symbol = item.get("stock_code") or None
if symbol is None and self._symbol_resolver is not None:
    corp_code = item.get("corp_code")
    if corp_code:
        symbol = await self._symbol_resolver.resolve(corp_code)
        if symbol:
            logger.debug(
                "Resolved symbol via corp_code=%s → %s for rcept_no=%s",
                corp_code, symbol, item.get("rcept_no"),
            )
        else:
            logger.debug(
                "Failed to resolve symbol for corp_code=%s corp_name=%s rcept_no=%s",
                corp_code, item.get("corp_name"), item.get("rcept_no"),
            )
```

**`_raw_from_item()`을 async로 변경** (현재 sync → async):
- `fetch()`가 이미 async이므로 체인에는 영향 없음
- `_raw_from_item()` 호출 부분에서 `await` 추가

### 3.3 Symbol Resolver를 OpenDartSourceAdapter에 주입하는 연결

`run_event_ingestion_loop.py` 또는 polling worker 생성 부분에서:
```python
symbol_resolver = SymbolResolver(api_key=settings.opendart_api_key)
adapter = OpenDartSourceAdapter(
    api_key=settings.opendart_api_key,
    symbol_resolver=symbol_resolver,
)
```

### 3.4 Backfill 스크립트 (보수적 기본값)

```sql
-- 1. 고유 issuer_code 추출 (source_name='opendart'로 제한)
SELECT DISTINCT issuer_code FROM trading.external_events
WHERE symbol IS NULL AND issuer_code IS NOT NULL AND source_name = 'opendart';

-- 2. 각 issuer_code에 대해 /company.json 호출
-- 3. 매핑 성공 시 UPDATE
UPDATE trading.external_events
SET symbol = $resolved_symbol
WHERE issuer_code = $corp_code AND symbol IS NULL AND source_name = 'opendart';
```

보수적 기본값:
- **`--dry-run`이 기본값** — `--apply` 명시 시에만 실제 UPDATE 실행
- `WHERE symbol IS NULL AND source_name = 'opendart'` 이중 보호
- 트랜잭션 단위 실행
- 업데이트 건수 + unresolved 건수 모두 보고

---

## 4. 매핑 우선순위

```
stock_code from /list.json
  │
  ├── 있음 → 그대로 사용 (현재와 동일, 598건/66%)
  │
  └── 없음(NULL)
        │
        ├── corp_code 있음?
        │     ├── 예 → OpenDartSymbolResolver.resolve(corp_code)
        │     │         ├── 캐시 히트 → 즉시 반환
        │     │         ├── /company.json OK → symbol 반환 + 캐시 저장
        │     │         └── /company.json 실패/없음 → None (negative cache)
        │     │
        │     └── 아니오 → None (매핑 불가)
        │
        └── symbol=None 유지 (매핑 불가능한 이벤트만 남음)
```

**예상 결과:**
- 현재: 598/902 = 66.3% 매핑
- 개선 후: ~800-850/902 = 88-94% 매핑
- 잔여 NULL: 비상장사/기타법인 이벤트 (corp_code가 있어도 stock_code 자체가 없는 경우)

---

## 5. 테스트 케이스

### 5.1 OpenDartSymbolResolver 단위 테스트
- `stock_code` 있으면 정상 매핑
- `stock_code` 없고 corp_code로 `/company.json` 성공 → symbol 반환
- `stock_code` 없고 `/company.json` 실패 → None 반환 (negative cache)
- 캐시 히트 시 중복 API 호출 없음
- 동일 batch 내 중복 corp_code → 1회만 API 호출
- Negative cache: 실패한 corp_code 재조회 시 캐시 반환 (API 호출 없음)

### 5.2 OpenDartSourceAdapter 통합 테스트
- `stock_code` 있는 기존 경로 회귀 없음
- `stock_code` 없고 OpenDartSymbolResolver 주입 시 corp_code로 fallback
- OpenDartSymbolResolver 미주입 시 기존 동작 유지 (None 유지)
- 중요도 분류 회귀 없음
- dedup key 회귀 없음

### 5.3 Importance classification 회귀 테스트
- 기존 `_classify_importance()` 호출 유지
- 중요도 결과 변경 없음

---

## 6. 위험 및 주의사항

| 위험 | 대응 |
|------|------|
| `/company.json` API rate limit | OpenDartSymbolResolver에 1초 간격 rate limiter 추가 |
| `/company.json` API key 추가 소진 | 동일 api_key 사용, 추가 quota 불필요 |
| 동일 corp_code 반복 호출 | negative cache 포함 인메모리 캐시로 1회만 호출 |
| 캐시 무한 증가 | batch 단위 Lifecycle (최대 1000개) |
| dedup key 변경 | `issuer_code` 기반이므로 stock_code만 추가되어 영향 없음 |
| 기존 데이터 훼손 | `WHERE symbol IS NULL AND source_name='opendart'` 이중 보호, `--dry-run` 기본값 |
