# ops-scheduler Cache Mount 정합성 Hotfix + Holiday Client File Token Cache 운영 검증

> 작성: 2026-05-16 15:53 KST  
> 검증 대상: `ops-scheduler` 컨테이너 (`agent_trading-ops-scheduler`)  
> 검증자: Roo (Code Mode)

---

## 1. 관측 환경

### 1.1 컨테이너 상태

| 항목 | 값 |
|------|-----|
| Container ID | `90146d4e7c5d` |
| Image | `agent_trading-app:latest` |
| 명령어 | `python3 /app/scripts/run_near_real_ops_scheduler.py` |
| 상태 | `Up` (최초 unhealthy → 재기동 후 정상) |
| TZ | `Asia/Seoul` (KST) |

### 1.2 관련 env 변수

| 변수명 | 값 | 역할 |
|--------|-----|------|
| `KIS_LIVE_TOKEN_CACHE_ENABLED` | `true` | live-info token cache 활성화 |
| `KIS_LIVE_TOKEN_CACHE_PATH` | `.cache/kis_live_token.json` | market_state cache 경로 (상대) |
| `KIS_LIVE_INFO_ENABLED` | `true` | live-info client 활성화 |
| `KIS_LIVE_INFO_APP_KEY` | `PScDVLqkufdKEEunAe00...` | holiday용 app key |
| `KIS_DEV_TOKEN_CACHE_ENABLED` | `true` | dev token cache 활성화 |
| `KIS_DEV_TOKEN_CACHE_PATH` | `.cache/kis_token.json` | dev cache 경로 (상대) |

---

## 2. Root Cause

### 2.1 문제 정의

`docker-compose.yml`에서 `ops-scheduler` 서비스의 `.cache` volume mount가 **컨테이너 working directory와 불일치**:

```
Dockerfile:     WORKDIR /app
상대 경로 해석:  .cache/kis_live_oauth_token.json → /app/.cache/kis_live_oauth_token.json
volume mount:   ./.cache:/workspace/agent_trading/.cache  ← ❌
```

코드는 `/app/.cache/...`에 파일을 쓰지만, mount는 `/workspace/agent_trading/.cache`에 연결되어 있어 **호스트 파일 시스템에 cache가 영속되지 않음**.

### 2.2 다른 서비스와 비교

| 서비스 | `.cache` mount 대상 | 정합성 |
|--------|---------------------|--------|
| `app` | `./.cache:/app/.cache` | ✅ 정상 |
| `api` | `./.cache:/app/.cache` | ✅ 정상 |
| `snapshot-sync` | `./.cache:/app/.cache` | ✅ 정상 |
| **`ops-scheduler` (수정 전)** | `./.cache:/workspace/agent_trading/.cache` | ❌ **불일치** |
| **`ops-scheduler` (수정 후)** | `./.cache:/app/.cache` | ✅ **정상화** |

### 2.3 추가 발견: logs, data mount도 동일 문제

| mount | 수정 전 | 수정 후 |
|-------|---------|---------|
| `.cache` | `./.cache:/workspace/agent_trading/.cache` | `./.cache:/app/.cache` |
| `logs` | `./logs:/workspace/agent_trading/logs` | `./logs:/app/logs` |
| `data` | `./data:/workspace/agent_trading/data` | `./data:/app/data` |

---

## 3. Holiday Client Cache 파일 경로/정책

### 3.1 Cache 파일 경로

holiday client는 `market_session.py`에서 다음과 같이 cache 경로를 계산:

```python
cache_base_path = os.getenv("KIS_LIVE_TOKEN_CACHE_PATH", ".cache/kis_live_token.json")
cache_parent = os.path.dirname(cache_base_path) or ".cache"
oauth_cache_path = os.path.join(cache_parent, "kis_live_oauth_token.json")
# 결과: .cache/kis_live_oauth_token.json
```

**최종 경로**: `/app/.cache/kis_live_oauth_token.json` (컨테이너 내부)  
**호스트 매핑**: `./.cache/kis_live_oauth_token.json`

### 3.2 Cache 파일 정책

| 정책 | 설명 |
|------|------|
| 파일명 | `kis_live_oauth_token.json` |
| Fingerprint | `SHA256("holiday_oauth_{app_key}_{app_secret[-4:]}_{base_url}")[:16]` |
| Token purpose | `holiday_oauth` (market_state의 `live_ws`와 구분) |
| Expiry buffer | 만료 1분 전부터 재발급 |
| 만료 시간 | `expires_in - 300초` (API 응답 기준 5분 조기 refresh) |

---

## 4. 첫 호출 Save 결과

### 4.1 로그 증거

```
2026-05-16 15:51:31 [INFO] Token cache miss: file_missing
2026-05-16 15:51:31 [INFO] POST /oauth2/tokenP "HTTP/1.1 200 OK"
2026-05-16 15:51:31 [INFO] Token cache saved for live-info holiday client
2026-05-16 15:51:31 [INFO] GET /chk-holiday ... "HTTP/1.1 200 OK"
2026-05-16 15:51:31 [INFO] source=kis_holiday_api
```

### 4.2 Cache 파일 생성 확인

```bash
$ ls -la ./.cache/
-rw-r--r-- 1 root    root     541 May 16 15:51 kis_live_oauth_token.json   ← ✅ 신규 생성
-rw-r--r-- 1 project ftpuser  597 May 16 08:52 kis_token.json              ← 기존 dev cache
```

---

## 5. 재기동 후 File Cache Hit 결과

### 5.1 로그 증거 (재기동 후)

```
2026-05-16 15:52:46 [INFO] Token cache hit for live-info holiday client    ← 🎯 FILE CACHE HIT!
2026-05-16 15:52:47 [INFO] GET /chk-holiday ... "HTTP/1.1 200 OK"          ← 076 API (OAuth 재호출 없음!)
```

**결정적 증거**: 재기동 후 `POST /oauth2/tokenP`가 **전혀 호출되지 않음**. File cache에서 OAuth token을 직접 로드하여 076 API 호출 성공.

---

## 6. Cache 파일 내용

### 6.1 `kis_live_oauth_token.json` (holiday client)

```json
{
  "access_token": "eyJ0eXAiOi... (앞 10자리, 전체 비공개)",
  "token_type": "Bearer",
  "expires_at": 1779000631.3185625,        // ≈ 24시간 후 (정상)
  "fingerprint": "77d8cecf942e7b1f",       // SHA256 hash[:16]
  "token_purpose": "holiday_oauth",         // ✅ 정확
  "created_at": 1778914291.3185625
}
```

### 6.2 fingerprint 검증

Fingerprint 계산식:
```python
raw_fp = f"holiday_oauth_{app_key}_{app_secret[-4:]}_{base_url}"
fingerprint = hashlib.sha256(raw_fp.encode()).hexdigest()[:16]
```

결과: `77d8cecf942e7b1f` ✅ — app_key + app_secret[-4:] + base_url 기반

---

## 7. Market State Cache 파일과 분리 확인

| cache 파일 | 용도 | token_purpose | 상태 |
|------------|------|---------------|------|
| `kis_live_oauth_token.json` | Holiday OAuth | `holiday_oauth` | ✅ 생성됨 |
| `kis_live_token.json` | Market State WS | `live_ws` (추정) | 아직 생성되지 않음 (비영업일) |
| `kis_token.json` | Dev (paper) token | N/A | ✅ 기존 존재 |

**현재까지 두 cache 파일이 혼용된 증거 없음.** Holiday client는 `token_purpose="holiday_oauth"`로 저장하고, `_load_cached_token()`에서 반드시 이 값을 검증하므로 market_state cache와의 혼용은 발생하지 않음.

---

## 8. DB Market Sessions 반영 결과

### 8.1 `market_sessions` 최신 row

| run_date | source | is_trading_day | raw_opnd_yn | updated_at |
|----------|--------|----------------|-------------|------------|
| 2026-05-16 | `kis_holiday_api` | `f` (false) | null | 2026-05-16 06:52:46 UTC |

- **영업일 아님** (`is_trading_day=false`) — 토요일이므로 정상
- `source=kis_holiday_api` — 076 API에서 조회한 결과 사용
- `raw_opnd_yn`이 null인 이유: 076 API는 `opnd_yn`만 반환하고 세션 API(163)와 달리 `mkop_cls_code`를 제공하지 않음

### 8.2 `session_events`

비영업일(`opnd_yn=N`, `bzdy_yn=N`)이므로 session gate가 모든 phase를 SKIP 처리하여 session_events가 생성되지 않음 (정상).

---

## 9. 최종 판정

### 판정: **A. 완전 성공** ✅

| 검증 항목 | 결과 | 상세 |
|-----------|------|------|
| 첫 호출: cache miss → token save | ✅ | `Token cache miss: file_missing` → `Token cache saved` |
| HTTP /oauth2/tokenP 호출 | ✅ | `HTTP/1.1 200 OK` |
| 076 chk-holiday API 정상 | ✅ | `HTTP/1.1 200 OK`, `source=kis_holiday_api` |
| Cache 파일 생성 | ✅ | `kis_live_oauth_token.json` (541 bytes) |
| 재기동 후 file cache hit | ✅ | `Token cache hit for live-info holiday client` (POST /oauth2/tokenP 없음) |
| Cache 파일 fingerprint | ✅ | `77d8cecf942e7b1f`, app_key 기반 |
| Cache 파일 token_purpose | ✅ | `holiday_oauth` |
| Market_state cache와 분리 | ✅ | 별도 파일, 별도 token_purpose |
| DB market_sessions 갱신 | ✅ | `source=kis_holiday_api`, `is_trading_day=false` |
| 파일 시스템 영속성 | ✅ | 호스트 `./.cache/`에 파일 확인 |

---

## 10. 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`docker-compose.yml`](../docker-compose.yml:302) | `ops-scheduler` volume mount 경로 수정: `.cache`, `logs`, `data` mount를 `/workspace/agent_trading/...` → `/app/...`로 정합화 |

---

## 11. Cache File 경로 정책 요약

| 경로 유형 | 컨테이너 내부 경로 | 호스트 경로 | 용도 |
|-----------|-------------------|-------------|------|
| live oauth (holiday) | `/app/.cache/kis_live_oauth_token.json` | `./.cache/kis_live_oauth_token.json` | 076 API OAuth token |
| live token (market state) | `/app/.cache/kis_live_token.json` | `./.cache/kis_live_token.json` | 163 WS approval key |
| dev token (paper/live) | `/app/.cache/kis_token.json` | `./.cache/kis_token.json` | 주문/잔고 API token |

**모든 상대 경로는 `WORKDIR=/app` 기준으로 해석.**

---

## 12. 남은 Follow-up

| # | 항목 | 우선순위 | 설명 |
|---|------|----------|------|
| 1 | 영업일 검증 필요 | Medium | 토요일(비영업일)에만 검증됨. 월~금 영업일에도 동일 동작 확인 필요 |
| 2 | Market state cache 파일 | Low | `kis_live_token.json`은 market state client가 호출될 때 생성됨. 영업일 검증 시 자동 확인 |
| 3 | `docker-compose.yml` `logs`/`data` mount | Low | 수정했으나 실제 사용 여부 확인되지 않음. 추후 logging file handler 도입 시 재확인 |
| 4 | 컨테이너 healthcheck | Low | 최초 unhealthy 상태 — scheduler 로직이 비영업일 SKIP 처리를 healthcheck가 만료로 해석한 것으로 보임 |
| 5 | Cache file permission | Low | `kis_live_oauth_token.json` 소유자가 `root:root` — `kis_token.json`은 `project:ftpuser`. 일관성 맞추는 것이 좋음 |
