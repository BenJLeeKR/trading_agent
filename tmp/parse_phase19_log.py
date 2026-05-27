#!/usr/bin/env python3
"""
Phase 19b submit 로그 독립 재파싱 스크립트

raw 로그 파일(logs/phase19_submit_measurement_20260526_151711.json)에서
다음 정보를 추출하여 재검산:
  - 총 소요 시간 (duration_seconds)
  - 시작/종료 시간 (첫/마지막 타임스탬프)
  - 각 symbol 처리 결과 (SUBMITTED, REJECTED, SKIPPED, DRY_RUN, ERROR)
  - Naver 429, KIS 500, EGW00201, timeout, subprocess timeout 카운트
  - AI assemble 완료 시간 (각 symbol별)
  - broker_submit 호출 및 소요 시간
"""

import json
import os
import re
from datetime import datetime
from statistics import median

LOG_FILE = "logs/phase19_submit_measurement_20260526_151711.json"
OUTPUT_FILE = "logs/phase19_recalculated_metrics.json"

# ── 타임스탬프 파싱 ──────────────────────────────────────────
# 로그 라인: "2026-05-26 15:17:12 [INFO] paper-decision-loop: ..."
LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)\s+\[")
LOG_TS_FMT = "%Y-%m-%d %H:%M:%S"

# subprocess stderr 타임스탬프: "2026-05-26 15:19:08,974 [INFO] __main__: ..."
SUB_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+\[")

def parse_ts(text: str) -> datetime | None:
    """로그 라인에서 타임스탬프 추출"""
    m = LOG_TS_RE.match(text)
    if m:
        ts_str = m.group(1).split(",")[0]  # 밀리초 제거
        return datetime.strptime(ts_str, LOG_TS_FMT)
    m = SUB_TS_RE.match(text)
    if m:
        ts_str = m.group(1).split(",")[0]
        return datetime.strptime(ts_str, LOG_TS_FMT)
    return None


def main():
    # ── 파일 읽기 ──────────────────────────────────────────────
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print(f"[INFO] 로그 파일: {LOG_FILE} ({len(lines)} lines)")

    # ── 1. 시작/종료 타임스탬프 ────────────────────────────────
    timestamps: list[datetime] = []
    for line in lines:
        ts = parse_ts(line)
        if ts:
            timestamps.append(ts)

    first_ts = timestamps[0] if timestamps else None
    last_ts = timestamps[-1] if timestamps else None
    duration_from_ts = None
    if first_ts and last_ts:
        duration_from_ts = (last_ts - first_ts).total_seconds()
        print(f"[INFO] 첫 타임스탬프: {first_ts}")
        print(f"[INFO] 마지막 타임스탬프: {last_ts}")
        print(f"[INFO] 타임스탬프 기반 소요 시간: {duration_from_ts:.3f}s")

    # ── 2. summary JSON (마지막 줄) ────────────────────────────
    summary_data = {}
    total_duration = None
    total_symbols = None
    for line in reversed(lines):
        line_stripped = line.strip()
        if line_stripped.startswith("{") and line_stripped.endswith("}"):
            try:
                obj = json.loads(line_stripped)
                if obj.get("mode") == "summary":
                    summary_data = obj
                    total_duration = obj.get("total_duration_seconds")
                    total_symbols = obj.get("total_cycles")
                    print(f"[INFO] summary JSON 발견: total_duration={total_duration}s, total_symbols={total_symbols}")
                    break
            except json.JSONDecodeError:
                continue

    # ── 3. JSON 라인에서 각 symbol 결과 추출 ──────────────────
    json_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
                if "symbol" in obj and "cycle" in obj:
                    json_lines.append(obj)
            except json.JSONDecodeError:
                continue

    print(f"[INFO] JSON symbol 결과 라인 수: {len(json_lines)}")

    # 상태 카운트
    status_counts = {"submitted": 0, "rejected": 0, "skipped": 0, "dry_run": 0, "error": 0}
    status_map = {
        "SUBMITTED": "submitted",
        "REJECTED": "rejected",
        "SKIPPED": "skipped",
        "DRY_RUN": "dry_run",
        "ERROR": "error",
    }

    # assemble 시간 수집
    assemble_times: list[float] = []

    # broker_submit 정보
    broker_submit_success = 0
    broker_submit_failure = 0
    broker_submit_symbols_success: list[str] = []
    broker_submit_times: list[float] = []

    for obj in json_lines:
        status = obj.get("status", "")
        key = status_map.get(status)
        if key:
            status_counts[key] += 1

        # assemble 시간: phase_trace에서 ai_assemble phase 추출
        phase_trace = obj.get("phase_trace", [])
        if phase_trace:
            for phase in phase_trace:
                pname = phase.get("phase", "")
                if pname == "ai_assemble" and phase.get("status") == "ok":
                    elapsed_ms = phase.get("elapsed_ms", 0)
                    if elapsed_ms > 0:
                        assemble_times.append(elapsed_ms / 1000.0)

                # broker_submit phase
                if pname.startswith("broker_submit/"):
                    if phase.get("status") == "ok":
                        broker_submit_success += 1
                        broker_submit_symbols_success.append(obj.get("symbol", ""))
                        broker_submit_times.append(phase.get("elapsed_ms", 0))
                    elif phase.get("status") == "error":
                        broker_submit_failure += 1

    # ── 4. 에러 패턴 카운트 (raw 텍스트) ──────────────────────
    naver_429_count = 0
    kis_500_count = 0
    egw00201_count = 0
    timeout_total = 0
    subprocess_timeout_count = 0
    max_retries_exceeded = 0
    broker_quote_timeout_count = 0

    for line in lines:
        # Naver 429 — "NAVER 429:" 패턴만 카운트 (중복 방지)
        if "NAVER 429:" in line:
            naver_429_count += 1

        # KIS 500 — "500 Internal Server Error" 패턴만 카운트
        if "500 Internal Server Error" in line:
            kis_500_count += 1

        # EGW00201
        if "EGW00201" in line:
            egw00201_count += 1

        # broker quote timeout — 실제 timeout 이벤트
        if "broker quote timeout" in line.lower():
            broker_quote_timeout_count += 1

        # timeout (의미 있는 이벤트만) — HTTP 헤더 keep-alive: timeout=5 제외
        # "timeout=120" (OpenAI client 생성) 제외
        # "broker quote timeout"은 위에서 별도 카운트
        if re.search(r"(?i)\btimeout\b|\btimed\s*out\b", line):
            # HTTP 헤더/설정값 제외
            if "keep-alive: timeout=" in line.lower():
                continue
            if "timeout=120" in line or "timeout=5" in line:
                continue
            if "broker quote timeout" in line.lower():
                continue
            timeout_total += 1

        # subprocess timeout — PER_AGENT_HARD_TIMEOUT 만 카운트
        if "PER_AGENT_HARD_TIMEOUT" in line:
            subprocess_timeout_count += 1

        # max retries exceeded
        if "max retr" in line.lower() and "exceed" in line.lower():
            max_retries_exceeded += 1

    # ── 4b. timeout_total 재검증 ──────────────────────────────
    # timeout_total 이 0이면 broker_quote_timeout_count를 timeout_total로 사용
    if timeout_total == 0 and broker_quote_timeout_count > 0:
        timeout_total = broker_quote_timeout_count

    # ── 5. assemble 통계 ──────────────────────────────────────
    assemble_stats = {}
    if assemble_times:
        assemble_stats = {
            "min_seconds": round(min(assemble_times), 3),
            "max_seconds": round(max(assemble_times), 3),
            "avg_seconds": round(sum(assemble_times) / len(assemble_times), 3),
            "median_seconds": round(median(assemble_times), 3),
            "total_count": len(assemble_times),
        }
        print(f"[INFO] assemble 통계: count={len(assemble_times)}, "
              f"min={assemble_stats['min_seconds']}s, "
              f"max={assemble_stats['max_seconds']}s, "
              f"avg={assemble_stats['avg_seconds']}s, "
              f"median={assemble_stats['median_seconds']}s")

    # ── 6. broker_submit 통계 ─────────────────────────────────
    broker_submit_stats = {}
    if broker_submit_times:
        broker_submit_stats = {
            "success_count": broker_submit_success,
            "failure_count": broker_submit_failure,
            "success_symbols": broker_submit_symbols_success,
            "avg_submit_time_ms": round(sum(broker_submit_times) / len(broker_submit_times)),
        }
        print(f"[INFO] broker_submit: success={broker_submit_success}, "
              f"failure={broker_submit_failure}, "
              f"avg_time={broker_submit_stats['avg_submit_time_ms']}ms, "
              f"symbols={broker_submit_symbols_success}")

    # ── 7. bottleneck ranking (추정) ──────────────────────────
    # Naver 429 영향 추정: 각 429마다 평균 2~3초 재시도 대기
    naver_impact = round(naver_429_count * 0.5, 1)  # 보수적 추정: 0.5s per 429 event
    # KIS 500 영향: 각 500마다 약 0.3초 (실패한 quote 재요청)
    kis_impact = round(kis_500_count * 0.3, 1)
    # AI assemble: 총 assemble 시간 합계
    total_assemble_time = round(sum(assemble_times), 1) if assemble_times else 0

    bottleneck_ranking = [
        {"rank": 1, "name": "Naver API 429 Rate Limit", "estimated_impact_seconds": naver_impact},
        {"rank": 2, "name": "KIS Quote 500 errors", "estimated_impact_seconds": kis_impact},
        {"rank": 3, "name": "AI assemble (Deepseek LLM)", "estimated_impact_seconds": total_assemble_time},
    ]

    # ── 8. 결과 JSON 구성 ─────────────────────────────────────
    result = {
        "source_file": LOG_FILE,
        "total_symbols": total_symbols or len(json_lines),
        "total_duration_seconds": total_duration,
        "duration_from_timestamps_seconds": round(duration_from_ts, 1) if duration_from_ts else None,
        "status_counts": status_counts,
        "error_counts": {
            "naver_429": naver_429_count,
            "kis_500": kis_500_count,
            "egw00201": egw00201_count,
            "broker_quote_timeout": broker_quote_timeout_count,
            "timeout_total": timeout_total,
            "subprocess_timeout": subprocess_timeout_count,
            "max_retries_exceeded": max_retries_exceeded,
        },
        "assemble_stats": assemble_stats,
        "broker_submit": broker_submit_stats,
        "bottleneck_ranking": bottleneck_ranking,
    }

    # ── 9. 출력 및 저장 ───────────────────────────────────────
    print("\n" + "=" * 60)
    print("재검산 결과:")
    print("=" * 60)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n[INFO] 결과 저장 완료: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
