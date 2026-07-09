# 장후 실측 작업 점검 체크리스트

## 목적

- `signal_feature_snapshot` 장후 배치와 `trigger_proxy_attribution` 실측 체인이 정상 작동하는지
  운영 직후 빠르게 확인하기 위한 점검 문서다.
- 특히 아래 항목을 확인한다.
  - 장후 스케줄러 실행 여부
  - `signal_feature_batch_runs` 적재 완료 여부
  - `signal_feature_batch_run_items` item-level metadata 적재 여부
  - `trigger_proxy_attribution` 로그 생성 여부
  - `shadow v2` 및 품질 진단 필드 적재 여부

## 적용 시점

- 기준 시각: 거래일 `20:10 KST` 장후 배치 이후
- 권장 점검 시각: `20:12 KST ~ 20:20 KST`
- 기준 거래일 예시:
  - `2026-07-08` 장후 배치 실행 시각은 `2026-07-08 20:11 KST`
  - UTC 저장 시각은 `2026-07-08 11:11 UTC`

## 점검 대상 체인

1. `ops-scheduler`
2. `scripts.generate_signal_feature_snapshot_input`
3. `scripts.build_signal_feature_snapshots`
4. `logs/trigger_proxy_attribution_<YYYY-MM-DD>.json`
5. `trading.signal_feature_batch_runs`
6. `trading.signal_feature_batch_run_items`

## 정상 판정 기준

- `ops-scheduler` 컨테이너가 `healthy`
- 해당 거래일 `signal_feature_batch_runs` row가 `dry_run=false`, `status=completed`
- `persist_success_count > 0`
- `final_missing_count = 0` 또는 허용 가능한 소수의 결측만 존재
- `summary_json.snapshot_quality` 존재
- item-level `metadata_json`에 실측용 필드 존재
- `trigger_proxy_attribution_<YYYY-MM-DD>.json` 파일 존재
- `proxy_availability.t1_ready_count` 또는 `t3_ready_count`가 누적 관측 가능 상태

## 1차 점검 체크리스트

- [ ] `ops-scheduler`가 실행 중이며 `healthy` 상태다
- [ ] 해당 거래일 장후 `signal_feature_batch_runs`가 1건 이상 생성되었다
- [ ] 최근 run의 `trigger_type=after_market_scheduler`다
- [ ] 최근 run의 `status=completed`다
- [ ] 최근 run의 `dry_run=false`다
- [ ] 최근 run의 `persist_success_count`가 0보다 크다
- [ ] 최근 run의 `summary_json.snapshot_quality`가 존재한다
- [ ] 최근 run item의 `metadata_json`이 비어 있지 않다
- [ ] `logs/trigger_proxy_attribution_<YYYY-MM-DD>.json` 파일이 생성되었다
- [ ] attribution 로그에 `core_risk_off_floor_v3_report`가 존재한다

## 2차 점검 체크리스트

### A. Feature 품질 점검

- [ ] `snapshot_quality.snapshot_count`가 기대 Universe 규모와 대체로 일치한다
- [ ] `overall_missing_count = 0` 또는 사전 허용 범위 이내다
- [ ] `short_history_count`가 비정상적으로 급증하지 않았다
- [ ] `turnover_feature_missing_count`가 비정상적으로 급증하지 않았다
- [ ] `missing_feature_flag_counts`가 공란 또는 안정 범위다
- [ ] `input_quality_flag_counts`가 공란 또는 안정 범위다

### B. Trigger 실측 점검

- [ ] `overall_bucket_counts`가 생성되었다
- [ ] `reason_code_counts`가 생성되었다
- [ ] `core_risk_off_floor_v3_report.proxy_availability`가 생성되었다
- [ ] `t1_ready_count`가 전일 대비 급감하지 않았다
- [ ] `t3_ready_count`가 전일 대비 급감하지 않았다

### C. Shadow v2 실측 점검

- [ ] `summary_json.snapshot_quality.shadow_overall_bucket_counts_v2`가 생성되었다
- [ ] `summary_json.snapshot_quality.shadow_reason_code_counts_v2`가 생성되었다
- [ ] item metadata에 `shadow_signal_backbone_variant`가 존재한다
- [ ] item metadata에 `shadow_overall_score_v2`가 존재한다
- [ ] item metadata에 `shadow_overall_bucket_v2`가 존재한다

## 점검 명령 예시

### 1. 스케줄러 상태 확인

```bash
docker compose ps ops-scheduler
```

정상 예시:

- `Up`
- `healthy`

### 2. 최근 장후 batch run 확인

```bash
docker compose exec -T ops-scheduler python3 - <<'PY'
import asyncio, os, asyncpg

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows = await conn.fetch(
        """
        SELECT business_date, trigger_type, dry_run, status,
               persist_success_count, final_missing_count, started_at
        FROM trading.signal_feature_batch_runs
        WHERE dry_run = false
        ORDER BY started_at DESC
        LIMIT 3
        """
    )
    for row in rows:
        print(
            row["business_date"],
            row["trigger_type"],
            row["dry_run"],
            row["status"],
            row["persist_success_count"],
            row["final_missing_count"],
            row["started_at"],
        )
    await conn.close()

asyncio.run(main())
PY
```

정상 기준:

- 최신 row가 당일 거래일
- `after_market_scheduler`
- `False`
- `completed`

### 3. 최근 run의 품질 summary 확인

```bash
docker compose exec -T ops-scheduler python3 - <<'PY'
import asyncio, os, asyncpg, json

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    row = await conn.fetchrow(
        """
        SELECT signal_feature_batch_run_id, summary_json
        FROM trading.signal_feature_batch_runs
        WHERE dry_run = false
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    summary = row["summary_json"]
    if isinstance(summary, str):
        summary = json.loads(summary)
    print(json.dumps(summary.get("snapshot_quality", {}), ensure_ascii=False, indent=2))
    await conn.close()

asyncio.run(main())
PY
```

확인 포인트:

- `snapshot_count`
- `overall_missing_count`
- `overall_bucket_counts`
- `shadow_overall_bucket_counts_v2`

### 4. 최근 run item metadata 확인

```bash
docker compose exec -T ops-scheduler python3 - <<'PY'
import asyncio, os, asyncpg, json

async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    row = await conn.fetchrow(
        """
        SELECT i.metadata_json
        FROM trading.signal_feature_batch_run_items i
        JOIN trading.signal_feature_batch_runs r
          ON r.signal_feature_batch_run_id = i.signal_feature_batch_run_id
        WHERE r.dry_run = false
        ORDER BY r.started_at DESC, i.created_at DESC
        LIMIT 1
        """
    )
    metadata = row["metadata_json"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    await conn.close()

asyncio.run(main())
PY
```

확인 포인트:

- `shadow_signal_backbone_variant`
- `shadow_overall_score_v2`
- `shadow_overall_bucket_v2`

### 5. Attribution 로그 존재 여부 확인

```bash
python3 - <<'PY'
from pathlib import Path
import json

path = Path("logs/trigger_proxy_attribution_2026-07-08.json")
print(path.exists())
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
    print(sorted(data.keys()))
    print(data.get("core_risk_off_floor_v3_report", {}).get("proxy_availability"))
PY
```

확인 포인트:

- 파일 존재 여부
- `core_risk_off_floor_v3_report`
- `proxy_availability`

## 장애 분기 가이드

### 1. 스케줄러는 정상인데 batch run이 없음

가능 원인:

- 장후 시각 이전 조회
- 스케줄러 내부 command 실패
- 거래일 판정/phase 진입 실패

우선 확인:

- `ops-scheduler` 로그
- 해당 거래일 `operations_day_runs`
- `signal_feature_batch_runtime` 호출 로그

### 2. batch run은 있으나 `summary_json.snapshot_quality`가 없음

가능 원인:

- 운영 컨테이너가 최신 코드로 재기동되지 않음
- 장후 배치는 돌았지만 신규 필드 반영 전 이미지로 실행됨

우선 확인:

- 실행 중 `ops-scheduler` 컨테이너 내부 파일에
  - `shadow_overall_bucket_counts_v2`
  - `shadow_reason_code_counts_v2`
  문자열이 존재하는지 확인

### 3. summary는 있으나 item metadata에 `shadow_*_v2`가 없음

가능 원인:

- `signal_backbone.py`는 최신이지만 item metadata 저장 경로가 구버전
- `build_signal_feature_snapshots.py`가 최신 코드로 반영되지 않음

우선 확인:

- `/app/scripts/build_signal_feature_snapshots.py`
- `/app/src/agent_trading/services/signal_backbone.py`

### 4. attribution 로그가 없음

가능 원인:

- 장후 feature batch는 성공했지만 attribution 후속 실행 실패
- 로그 경로/파일명 mismatch
- DB pool 초기화 또는 후속 스크립트 오류

우선 확인:

- `logs/trigger_proxy_attribution_<YYYY-MM-DD>.json`
- `analyze_trigger_proxy_attribution.py` 실행 로그

## 현재 알려진 해석 기준

- `summary_json.snapshot_quality`는 있되 `shadow_*_v2`가 없으면
  - 기존 실측 체인은 정상
  - 신규 실측 필드는 아직 운영 배치 미반영 상태로 판단한다
- `trigger_proxy_attribution` 로그가 있고
  `core_risk_off_floor_v3_report.proxy_availability`가 채워지면
  - 후행 수익률 proxy 적재 경로는 정상으로 본다
- `t5_ready_count=0`은 관측 기간 부족일 수 있으므로 단독 장애로 보지 않는다

## 점검 결과 기록 템플릿

```text
거래일:
점검 시각:

1. 스케줄러
- 상태:

2. signal_feature_batch_runs
- business_date:
- status:
- persist_success_count:
- final_missing_count:

3. snapshot_quality
- snapshot_count:
- overall_missing_count:
- overall_bucket_counts:
- shadow_overall_bucket_counts_v2:

4. item metadata
- shadow_signal_backbone_variant:
- shadow_overall_score_v2 존재 여부:
- shadow_overall_bucket_v2:

5. attribution
- 로그 파일 존재 여부:
- proxy_availability:

판정:
- 정상 / 부분 정상 / 장애

후속 조치:
```

## 후속 연계 문서

- [`plans/[PRIORITY_MAP] remaining_work_priority_map.md`](./[PRIORITY_MAP]%20remaining_work_priority_map.md)
- [`plans/[PLAN] core_risk_off_ranking_relaxation_phase1.md`](./[PLAN]%20core_risk_off_ranking_relaxation_phase1.md)
- [`plans/[DESIGN] performance_attribution_for_trigger_and_override.md`](./[DESIGN]%20performance_attribution_for_trigger_and_override.md)
- [`plans/[GUIDE] end_to_end_order_flow_guide.md`](./[GUIDE]%20end_to_end_order_flow_guide.md)
