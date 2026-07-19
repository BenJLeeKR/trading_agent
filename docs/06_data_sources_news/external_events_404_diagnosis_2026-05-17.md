# `/external-events/recent` 404 진단 보고서

**진단 일시**: 2026-05-17 20:28 KST
**진단자**: Debug Mode
**상태**: ✅ 원인 확정 (코드 수정 불필요 — 재빌드 필요)

---

## Q1: 404의 직접 원인은 무엇인가?

**Docker 이미지(`agent_trading-api`)가 `external_events.py` 추가 전에 빌드되어, 컨테이너에 해당 파일과 라우트 등록 코드가 없음.**

| 항목 | 호스트 (소스) | 컨테이너 (런타임) |
|------|--------------|-------------------|
| [`external_events.py`](src/agent_trading/api/routes/external_events.py) | 존재 ✅ | **없음** ❌ |
| [`app.py`](src/agent_trading/api/app.py:244) `external_events_router` import | Line 245 ✅ | **없음** ❌ |
| [`app.py`](src/agent_trading/api/app.py:247) `protected_routers.append()` | Line 247 ✅ | **없음** ❌ |
| `routes/__init__.py` export | Line 2 ✅ | — |
| OpenAPI `/external-events/recent` | — | **없음** ❌ (40개 paths 중 누락) |

### 타임라인

| 시간 (KST) | 이벤트 |
|-----------|--------|
| `2026-05-17 18:34:30` | `agent_trading-api` Docker 이미지 빌드 (external_events.py **없음**) |
| `2026-05-17 20:15:43` | `external_events.py` 파일 생성 및 `app.py`에 등록 코드 추가 |
| `2026-05-17 20:25+` | 현재 — 이미지가 이전 버전으로 실행 중 |

### 상세 증거

1. **컨테이너 내부 파일 확인**:
   ```
   $ docker compose exec api ls /app/src/agent_trading/api/routes/ | grep external
   # (출력 없음)
   ```

2. **컨테이너 `app.py` 라인 수**: **365라인** — `external_events` 관련 코드 없음
   ```python
   # 컨테이너 (Line 240-250): sessions_router 이후 바로 auth 체크
   protected_routers.append(sessions_router)
   if auth_enabled: ...
   ```

3. **호스트 `app.py` 라인 수**: **370라인** — `external_events` 등록 코드 포함
   ```python
   # 호스트 (Line 244-247):
   # Phase L — External Events inspection (recent events panel)
   from agent_trading.api.routes.external_events import router as external_events_router
   protected_routers.append(external_events_router)
   ```

4. **OpenAPI 스키마**: `/external-events/recent` missing from 40 registered paths

5. **`__pycache__`**: `external_events.cpython-3*.pyc` 파일 없음 — 한 번도 컴파일된 적 없음

---

## Q2: 실제 실행 중 프로세스가 최신 소스를 보고 있는가?

**아니오.** `api` 서비스는 최신 소스를 보고 있지 않습니다.

- `api` 서비스의 [`docker-compose.yml`](docker-compose.yml:168-171) 볼륨 마운트:
  ```yaml
  volumes:
    - ./admin_ui/dist:/app/admin_ui/dist
    - ./.cache:/app/.cache
  ```
  **`./src:/app/src` 마운트가 없음** — 호스트의 소스 변경사항이 컨테이너에 반영되지 않음.

- 반면, `app` 서비스(dev shell)는 [`./src:/app/src`를 마운트](docker-compose.yml:97)하므로 실시간 반영됨.

---

## Q3: `external_events_router`가 openapi/route table에 실제 올라와 있는가?

**아니오.** OpenAPI 스키마 응답 (/openapi.json) 및 컨테이너 내부 `app.routes` 목록 모두에서 `/external-events/recent`가 확인되지 않음. 라우트 등록 자체가 되지 않은 상태.

---

## Q4: auth가 걸린 경우라면 401이어야 하는데 왜 404인가?

**라우트 자체가 FastAPI 라우팅 테이블에 등록되지 않았기 때문.**

FastAPI의 요청 처리 순서:
1. 라우트 매칭 → 일치하는 라우트가 없으면 **즉시 404 반환** (Auth 미들웨어 실행 전)
2. 라우트 매칭 성공 → `dependencies=[Depends(require_viewer)]` 실행 → 토큰 없으면 401

`external_events_router`가 `protected_routers`에 추가되지 않았으므로, `include_router()`가 호출되지 않아 라우트가 존재하지 않음. 따라서 FastAPI는 404를 반환하며 Auth 레이어까지 도달하지 않음.

---

## Q5: 복구를 위해 필요한 조치는 무엇인가?

### 즉시 조치 (택 1)

| 방법 | 명령어 | 비고 |
|------|--------|------|
| **A. 이미지 재빌드 + 컨테이너 재시작** (권장) | `docker compose build api && docker compose up -d api` | 정식 복구 방법 |
| **B. 컨테이너 재시작만** (이미지 변경 없음) | `docker compose restart api` | 효과 없음 (동일 이미지 사용) |
| **C. api 서비스에 src 볼륨 마운트 추가** | `docker-compose.yml`에 `- ./src:/app/src` 추가 후 `up -d` | 개발 편의성 + 이미지 불일치 방지 |

**권장: A번 + C번 병행**

```bash
# 1. docker-compose.yml에 src 볼륨 마운트 추가 (선택사항)
# 2. 이미지 재빌드 및 컨테이너 재시작
cd /workspace/agent_trading && docker compose build api --no-cache && docker compose up -d api

# 3. 확인
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(sorted(d['paths'].keys())))" | grep external
# → /external-events/recent 가 출력되어야 함

curl -s "http://localhost:8000/external-events/recent?symbol=005380&limit=5&include_non_listed=true"
# → 200 OK + JSON 응답
```

### 사전 예방

`api` 서비스의 [`docker-compose.yml`](docker-compose.yml:168-171) `volumes`에 `./src:/app/src`를 추가하여 호스트 소스 변경사항이 실시간 반영되도록 설정:

```yaml
volumes:
  - ./admin_ui/dist:/app/admin_ui/dist
  - ./src:/app/src           # ← 추가 (개발 환경 한정)
  - ./.cache:/app/.cache
```

---

## 부록: 가능한 원인 분석 (6가지)

| # | 가능 원인 | 결과 |
|---|----------|------|
| 1 | **API 컨테이너 미재빌드** ✅ | **확정.** 이미지 생성(18:34) < 파일 생성(20:15) |
| 2 | 다른 app factory/entrypoint 사용 | ❌ `create_app_from_env()` → `create_app()` 정상 사용 |
| 3 | `include_router()` 등록 위치 문제 | ❌ 소스 코드는 정상, 컨테이너 코드가 미달 |
| 4 | path prefix mismatch | ❌ `/external-events/recent` 정확함 (source 확인) |
| 5 | auth 미들웨어가 404 반환 | ❌ 404는 라우트 미등록 → FastAPI 내부 404, auth 미도달 |
| 6 | route 파일이 `__init__.py`에 미등록 | ❌ `__init__.py:2` 정상 export |
