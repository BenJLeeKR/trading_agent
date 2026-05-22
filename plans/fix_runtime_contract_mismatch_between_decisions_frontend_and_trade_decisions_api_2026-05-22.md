# 보고서: 의사결정 페이지 `/trade-decisions` 프론트/백엔드 계약 불일치 복구

## 1. 문제 상황

의사결정(Decisions) 페이지에서 `Uncaught TypeError: can't access property "filter", f is undefined` 오류 발생.

### 크래시 체인

1. 프론트 JS 번들 (`index-D21YLCJ3.js`)이 `getTradeDecisions()` 호출 후 `resp.items`와 `resp.total`을 기대
2. 실행 중인 API 컨테이너가 **구버전 코드**로 `list[TradeDecisionDetail]` (plain JSON array) 반환
3. `resp.items === undefined` → `setDecisions(undefined)` → `decisions.filter(...)` 에서 크래시

## 2. 근본 원인: API 컨테이너 재빌드 누락

| 계층 | 로컬 소스 (최신) | 실행 중 컨테이너 (구버전) | 일치? |
|------|-----------------|------------------------|:----:|
| 백엔드 routes/decisions.py | `response_model=PaginatedTradeDecisionsResponse` | `response_model=list[TradeDecisionDetail]` | ❌ |
| 백엔드 schemas.py | `PaginatedTradeDecisionsResponse {items, total, limit, offset}` | (이미지 내부에도 최신 파일) | ✅ |
| 프론트 client.ts | `PaginatedTradeDecisionsResponse` 기대 | N/A (브라우저에서 실행) | ✅ |
| 프론트 DecisionsView.tsx | `resp.items`, `resp.total` 사용 | N/A (브라우저에서 실행) | ✅ |
| 프론트 dist JS | `index-D21YLCJ3.js` (최신, 429.77 kB) | 동일 (bind mount) | ✅ |

### 원인 상세

- `docker-compose.yml`에서 `api` 서비스는 `./src`를 bind mount하지 않음
- Python 소스 변경사항 적용을 위해 `docker compose build api` 필요
- 이전 세션에서 `decisions.py`를 paginated response로 수정했지만, 컨테이너 이미지 재빌드 없이 `docker compose up -d`만 실행
- 따라서 컨테이너 내부는 계속 구버전 코드 (`list[TradeDecisionDetail]`) 유지

## 3. 수행한 복구 조치

### 조치 1: 프론트 dist 재빌드

```bash
cd /workspace/agent_trading/admin_ui && npm run build
```

- `dist/assets/index-D21YLCJ3.js` (429.77 kB) 생성 확인
- `dist/assets/index-DRgey5Z_.css` (26.91 kB) 생성 확인

### 조치 2: API 컨테이너 재빌드

```bash
cd /workspace/agent_trading && docker compose build api
```

- 새 이미지 `sha256:51431956db96` (`agent_trading-api:latest`) 빌드 완료
- 컨테이너 내부 `decisions.py`에 `PaginatedTradeDecisionsResponse` 적용 확인

### 조치 3: API 컨테이너 재기동

```bash
cd /workspace/agent_trading && docker compose up -d api
```

- `agent_trading-api-1` 재생성 및 시작 완료
- `/health` 엔드포인트: `status: "ok"`, `database: "connected"`

### 조치 4: 방어 코드 적용

[`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx:91):

```typescript
// 변경 전
setDecisions(resp.items);
setTotalCount(resp.total);

// 변경 후
setDecisions(resp.items ?? []);
setTotalCount(resp.total ?? 0);
```

API가 정상적으로 paginated object를 반환하므로 `??` fallback이 필수는 아니지만, 예기치 않은 응답 변형에 대비한 fail-safe 차원에서 적용.

### 조치 5: 기존 백엔드 테스트 paginated shape에 맞게 수정

| 파일 | 변경 내용 |
|------|---------|
| [`tests/api/test_auth.py`](tests/api/test_auth.py:122) | `assert resp.json() == []` → paginated shape 검증으로 변경 |
| [`tests/api/test_inspection.py`](tests/api/test_inspection.py:177) | `data[0]` → `body["items"][0]`로 변경 |
| [`tests/api/test_inspection.py`](tests/api/test_inspection.py:221) | `data` → `body["items"]`로 변경 |

## 4. 검증 결과

### API 응답 Shape

```
PAGINATED OBJECT (dict) - FIXED!
Keys: ['items', 'total', 'limit', 'offset']
items count: 2
total: 8352
limit: 2
offset: 0
```

→ `Authorization: Bearer dev-token-123` 인증 성공

### 테스트 결과

| 테스트 범위 | 결과 |
|------------|:----:|
| 백엔드 `tests/api/test_postgres_inspection.py` | ✅ 17 passed |
| 백엔드 trade-decisions 관련 테스트 | ✅ 16 passed |
| 프론트엔드 전체 테스트 (16개 파일) | ✅ **259 passed** |

## 5. 수정된 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|---------|------|
| [`admin_ui/src/components/DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx) | 방어 코드 | `resp.items ?? []`, `resp.total ?? 0` fail-safe 추가 |
| [`tests/api/test_auth.py`](tests/api/test_auth.py) | 테스트 수정 | paginated response shape 검증으로 변경 |
| [`tests/api/test_inspection.py`](tests/api/test_inspection.py) | 테스트 수정 | paginated response items 접근으로 변경 |
| `admin_ui/dist/` | 재빌드 | 최신 JS 번들 생성 |
| `agent_trading-api` Docker 이미지 | 재빌드 | 최신 Python 코드 포함 |

## 6. 타임라인

| 시각 (UTC+9) | 조치 |
|-------------|------|
| 2026-05-22 15:53 | 프론트 dist 최종 빌드 (이전 세션) |
| 2026-05-22 15:59 | API 컨테이너 내부 구버전 코드 확인 🐛 |
| 2026-05-22 16:00 | 프론트 dist 재빌드 + API 컨테이너 재빌드/재기동 🔧 |
| 2026-05-22 16:01 | `/health` 정상 확인 |
| 2026-05-22 16:02 | `/trade-decisions` paginated response 정상 확인 ✅ |
| 2026-05-22 16:02 | 방어 코드 적용 |
| 2026-05-22 16:05 | 백엔드 테스트 실패 확인 → 테스트 수정 |
| 2026-05-22 16:07 | 백엔드 테스트 16 + 17 passed ✅ |
| 2026-05-22 16:08 | 프론트엔드 테스트 259 passed ✅ |

## 7. 결론

- **직접 원인**: API 컨테이너 (`agent_trading-api-1`)가 구버전 코드로 실행 중이었음
- **재빌드 누락 사유**: `api` 서비스는 `./src`를 bind mount하지 않아, `docker compose build api`가 필요했으나 누락됨
- **복구**: API 이미지 재빌드 + 재기동 + 프론트 dist 재빌드로 해결
- **현재 상태**: 프론트 · 백엔드 · dist · 컨테이너 모두 동일한 최신 버전으로 일치
- **의사결정 페이지**: 정상 렌더링 확인 (API 응답 `{items, total, limit, offset}`)

## 8. 운영 참고사항

- `api` 서비스의 Python 소스 변경 시 반드시 `docker compose build api && docker compose up -d api` 실행 필요
- `admin_ui/dist`는 bind mount되므로 프론트 소스 변경 시 `npm run build`만으로 컨테이너에 반영됨
