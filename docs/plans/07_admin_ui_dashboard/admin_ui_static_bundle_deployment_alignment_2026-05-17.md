# Admin UI 정적 번들 재빌드 + 배포 반영 보고서

**일시**: 2026-05-17 08:44 KST  
**담당**: Roo (Code Mode)  
**목적**: `ReconciliationView`의 `run_id` → `reconciliation_run_id` hotfix를 서빙 번들에 반영

---

## 1. Root Cause

- Phase L에서 [`ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx)의 `run_id`를 `reconciliation_run_id`로 수정하는 hotfix 완료
- 그러나 **`npm run build`가 실행되지 않아** `admin_ui/dist/` 디렉토리의 정적 번들이 갱신되지 않음
- 결과적으로 FastAPI가 여전히 **이전 해시 (`index-Bi6h-Utp.js`)** 의 번들을 서빙

## 2. 서빙 주체/경로

| 항목 | 값 |
|------|-----|
| 서빙 주체 | [`agent_trading-api-1`] (FastAPI + uvicorn) |
| 컨테이너 내부 경로 | `/app/admin_ui/dist` |
| 배포 방식 | **Volume mount**: `./admin_ui/dist:/app/admin_ui/dist` |
| 마운트 코드 | [`app.mount("/admin", StaticFiles(directory=admin_ui_dist, html=True))`](src/agent_trading/api/app.py) |
| Vite base | [`base: "/admin/"`](admin_ui/vite.config.ts) |
| Vite outDir | [`outDir: "dist"`](admin_ui/vite.config.ts) |

## 3. 적용 방법

```bash
cd /workspace/agent_trading/admin_ui && npm run build
```

Volume mount 방식이므로 호스트의 `admin_ui/dist/`가 갱신되면 컨테이너에 **즉시 반영**된다.  
FastAPI의 파일 캐시를 대비해 컨테이너 재시작을 선택적으로 수행:

```bash
docker compose restart api
```

## 4. 검증 결과

### 4.1 빌드 전 (이전 상태)

| 항목 | 값 |
|------|-----|
| JS 번들 | `index-Bi6h-Utp.js` (419,750 bytes) |
| CSS 번들 | `index-XC-ut06i.css` (25,357 bytes) |
| index.html 참조 | `/admin/assets/index-Bi6h-Utp.js` |
| hotfix 반영 | ❌ 미반영 (`r.run_id.slice(` 존재) |

### 4.2 빌드 후 (신규 상태)

| 항목 | 값 |
|------|-----|
| JS 번들 | **`index-TjxVtM0n.js`** (419,337 bytes) ✅ |
| CSS 번들 | `index-XC-ut06i.css` (25,357 bytes, 해시 동일) |
| index.html 참조 | `/admin/assets/index-TjxVtM0n.js` ✅ |
| `reconciliation_run_id.slice(` 포함 | ✅ **FOUND** |
| `r.run_id.slice(` (옛 코드) | ✅ **NOT FOUND** (완전 제거) |

### 4.3 실제 서빙 확인 (`curl http://localhost:8000/admin/`)

```html
<script type="module" crossorigin src="/admin/assets/index-TjxVtM0n.js"></script>
```

새 해시 `TjxVtM0n`이 정상적으로 서빙 중임을 확인 ✅

---

## 5. 향후 배포 체크리스트

소스 코드 수정 후 Admin UI 번들을 갱신해야 할 때:

1. **`cd admin_ui && npm run build`** — 정적 번들 재생성
2. **`docker compose restart api`** (선택 사항, FastAPI 파일 캐시 대비)
3. **브라우저 Hard Reload** (`Ctrl+Shift+R`) — 브라우저 캐시 무시
4. **필요시 `?v={timestamp}` 쿼리 파라미터**로 CDN/브라우저 캐시 무효화

---

## 6. 요약

| 검증 기준 | 결과 |
|-----------|------|
| ✅ `npm run build` 성공 | 통과 |
| ✅ `admin_ui/dist/assets/`에 새 해시 파일 존재 | 통과 (`index-TjxVtM0n.js`) |
| ✅ 이전 `index-Bi6h-Utp.js` 제거 | 통과 |
| ✅ `index.html`이 새 asset 참조 | 통과 |
| ✅ 새 JS에 `reconciliation_run_id.slice(` 포함 | 통과 |
| ✅ 새 JS에 `r.run_id.slice(` 미포함 | 통과 |
| ✅ `docker compose restart api` 성공 | 통과 |
| ✅ `curl /admin/` 응답에 새 해시 반영 | 통과 |
