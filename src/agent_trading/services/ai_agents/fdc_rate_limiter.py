"""FDC(final_decision_composer) provider 호출 전용 공유 rate limiter.

배경(2026-08-18)
----------------
``scripts/run_decision_loop.py``는 종목마다 독립 OS subprocess
(``scripts/run_agent_subprocess.py``)를 스폰하고, 각 subprocess가 각자
FDC provider(Gemini)를 호출한다. ``asyncio.Semaphore``를 부모 프로세스나
subprocess 어디에 두든, 그건 **단일 프로세스의 이벤트 루프 내에서만
유효**하다 — 서로 다른 OS 프로세스 사이에서는 전혀 공유되지 않는
"가짜 shared limiter"다.

PR #286에서는 이 한계를 우회하려고 부모 프로세스의 종목 동시 처리 상한
(symbol-level concurrency)을 5→3으로 낮추는 방식을 썼으나, 실측 결과
429 발생 건수는 줄지 않고 cycle 전체 소요 시간만 거의 2배로 늘었다
(``docs/30_work_log/2026-08-18_fdc_429_fallback_observability_and_
concurrency.md`` 참고). 이번 모듈은 그 rollback과 함께, **실제로
프로세스 간에 공유되는** rate limiter를 파일 기반 sliding-window
방식으로 구현한다.

설계
----
- 모든 subprocess가 같은 상태 파일(기본: OS 임시 디렉터리 아래)을
  ``fcntl.flock``으로 직렬화해 읽고 쓴다 — 같은 호스트/컨테이너
  파일시스템을 공유하는 한 프로세스 경계와 무관하게 실제로 공유된다.
- 최근 ``window_seconds`` 이내에 기록된 호출 타임스탬프 수가
  ``max_calls`` 이상이면, 가장 오래된 타임스탬프가 윈도우를 벗어날
  때까지 짧게 대기(polling)한 뒤 재시도한다.
- ``max_wait_seconds``를 넘도록 슬롯을 못 얻으면 — subprocess 전체
  timeout(기본 90초) 예산을 침범하지 않도록 — 대기를 포기하고 즉시
  통과시킨다(fail-open, 단 경고 로그를 남긴다. 조용한 bypass가 아니다).
  이 대기는 FDC 호출 자체의 30초 per-agent timeout 블록 **앞에서**
  별도로 일어나므로 그 30초 예산과는 별개다(``DEFAULT_MAX_WAIT_
  SECONDS`` 상수 주석 참고).
- 상태 파일 접근 자체가 실패하면(파일시스템 오류 등) 마찬가지로
  경고 로그를 남기고 즉시 통과시킨다.
- **import-time 부작용 없음** — 모듈을 import하는 것만으로는 파일이나
  디렉터리를 만들지 않는다. 상태 파일은 ``wait_for_fdc_slot()``을
  실제로 호출한 시점에만 lazy하게 생성된다. 이는 이 harness의
  dev-validation 컨테이너처럼 ``/workspace`` 하위가 read-only인
  환경에서도 이 모듈 자체는 안전하게 import/단위 테스트할 수 있게
  하기 위함이다(``subprocess_io.py``와 동일한 설계 원칙).

Gemini RPM 정책
---------------
운영 계약상 정확한 RPM 한도는 ``.env`` 열람 없이는 확인할 수 없으나,
운영자가 Gemini 콘솔에서 직접 확인한 값(limit=15, 관측 RPM 19)을
근거로 기본값을 그보다 충분히 낮게(``DEFAULT_MAX_CALLS_PER_WINDOW=10``
/ 60초, 즉 분당 최대 10회) 설정했다. 이 값은 이 모듈을 호출하는 쪽에서
파라미터로 얼마든지 조정할 수 있다.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_CALLS_PER_WINDOW = 10
DEFAULT_WINDOW_SECONDS = 60.0
# 2026-08-18 조정(15.0 → 20.0): `wait_for_fdc_slot()`은
# `scripts/run_agent_subprocess.py`에서 `asyncio.wait_for(fdc_agent.run(...),
# timeout=_PER_AGENT_TIMEOUT)`(30초) 블록 **앞에서** 별도로 호출된다 —
# 즉 이 대기 시간은 FDC의 30초 per-agent timeout에 포함되지 않고, 대신
# subprocess 전체 timeout(``DecisionAgentRunner.subprocess_timeout``,
# 기본 90초 — EI/AR/AC는 수 ms로 사실상 무시 가능)의 여유분을 쓴다.
# 20초 + FDC 최악 소요(30초 timeout 상한) = 50초로 여전히 90초 예산 안에서
# 충분한 여유(40초)가 남는다.
#
# 실측 근거(2026-08-18 13:28~13:29 KST, 36개 종목 1개 사이클): 실제로
# 대기 후 슬롯을 확보한 3건이 각각 13.0s/14.0s/13.0s를 기다렸다 — 기존
# 상한(15.0s)에 바짝 붙어 있어, 조금만 더 여유를 주면 그 경계에 걸려
# bypass됐을 호출 중 일부가 정상 대기로 전환될 가능성이 있다(반대로
# bypass된 16건은 15.0s를 다 채우고 포기한 것이므로, 그중 실제로 몇 초를
# 더 기다리면 슬롯을 얻었을지는 이 로그만으로는 알 수 없다 — 미확인).
# 25초 이상으로 더 키우지 않은 이유: 관측된 성공 대기가 13~14초 구간에
# 몰려 있어 20초로도 그 경계값을 충분히 덮고, 그 이상은 bypass되는
# 호출들의 대기만 늘릴 뿐 추가 효과가 검증되지 않은 추측성 비용이기
# 때문이다.
DEFAULT_MAX_WAIT_SECONDS = 20.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_STATE_FILENAME = "agent_trading_fdc_rate_limiter_state.json"


def default_state_path() -> str:
    """상태 파일의 기본 경로(OS 임시 디렉터리)를 반환한다.

    ``tempfile.gettempdir()``는 운영 컨테이너와 이 harness의
    dev-validation 컨테이너 양쪽 모두에서 항상 쓰기 가능한 경로다
    (``/workspace/agent_trading/logs``와 달리 read-only 제약이 없다).
    """
    return str(Path(tempfile.gettempdir()) / _STATE_FILENAME)


@dataclass(slots=True, frozen=True)
class FdcRateLimitResult:
    """rate limiter 판정 결과(관측용).

    Attributes
    ----------
    allowed:
        항상 ``True`` — 이 limiter는 호출을 영구히 거부하지 않는다
        (fail-open 설계). 대기 후 허용되거나, 대기 상한/오류 시
        bypass로 즉시 허용된다.
    waited_seconds:
        실제로 대기한 시간(초). 슬롯을 즉시 확보했으면 ``0.0``.
    bypassed:
        ``True``이면 rate limit을 실제로 강제하지 못하고 그냥
        통과시켰다는 뜻(대기 상한 초과 또는 상태 파일 오류).
    bypass_reason:
        ``bypassed=True``일 때만 설정 — ``"max_wait_exceeded"`` 또는
        ``"file_error:<ExceptionType>"``.
    """

    allowed: bool
    waited_seconds: float
    bypassed: bool
    bypass_reason: str | None = None


def _read_and_trim_timestamps(
    fh: object, *, now: float, window_seconds: float
) -> list[float]:
    fh.seek(0)  # type: ignore[attr-defined]
    raw = fh.read()  # type: ignore[attr-defined]
    try:
        timestamps = json.loads(raw) if raw.strip() else []
    except (json.JSONDecodeError, ValueError):
        timestamps = []
    if not isinstance(timestamps, list):
        timestamps = []
    cutoff = now - window_seconds
    return [ts for ts in timestamps if isinstance(ts, (int, float)) and ts >= cutoff]


def _write_timestamps(fh: object, timestamps: list[float]) -> None:
    fh.seek(0)  # type: ignore[attr-defined]
    fh.truncate()  # type: ignore[attr-defined]
    fh.write(json.dumps(timestamps))  # type: ignore[attr-defined]
    fh.flush()  # type: ignore[attr-defined]


def _try_acquire_slot(
    state_path: str, *, max_calls: int, window_seconds: float
) -> bool:
    """상태 파일을 잠그고 슬롯 확보를 시도한다(동기 함수, 파일 I/O).

    Returns
    -------
    bool
        ``True``면 슬롯을 확보(타임스탬프 기록 완료), ``False``면
        현재 윈도우가 가득 차 있어 대기가 필요함.

    Raises
    ------
    OSError
        상태 파일을 열거나 잠그는 데 실패한 경우 — 호출자가 이를
        bypass 신호로 처리한다.
    """
    directory = os.path.dirname(state_path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(state_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            now = time.time()
            timestamps = _read_and_trim_timestamps(fh, now=now, window_seconds=window_seconds)
            if len(timestamps) >= max_calls:
                # 가득 참 — 트림된 상태만 저장하고 대기 필요를 알린다.
                _write_timestamps(fh, timestamps)
                return False
            timestamps.append(now)
            _write_timestamps(fh, timestamps)
            return True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


async def wait_for_fdc_slot(
    *,
    max_calls: int = DEFAULT_MAX_CALLS_PER_WINDOW,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    state_path: str | None = None,
) -> FdcRateLimitResult:
    """FDC provider 호출 전 공유 rate limit 슬롯을 확보할 때까지 대기한다.

    여러 독립 프로세스가 같은 상태 파일을 파일 락으로 직렬화해
    sliding-window 호출 횟수를 실제로 공유한다. 슬롯을 확보하지
    못해도 이 함수는 예외를 던지지 않고 항상 ``allowed=True``인
    결과를 반환한다(호출자가 FDC를 아예 못 부르게 막지 않음) — 다만
    대기 상한 초과나 파일 오류 시 ``bypassed=True``로 표시하고 경고
    로그를 남긴다.
    """
    resolved_path = state_path or default_state_path()
    start = time.monotonic()
    waited_total = 0.0

    while True:
        try:
            got_slot = await asyncio.to_thread(
                _try_acquire_slot,
                resolved_path,
                max_calls=max_calls,
                window_seconds=window_seconds,
            )
        except OSError as exc:
            logger.warning(
                "FDC rate limiter: 상태 파일(%s) 접근 실패 — 제한 없이 통과시킴"
                "(bypass). %s",
                resolved_path,
                exc,
            )
            return FdcRateLimitResult(
                allowed=True,
                waited_seconds=waited_total,
                bypassed=True,
                bypass_reason=f"file_error:{type(exc).__name__}",
            )

        if got_slot:
            if waited_total > 0:
                logger.info(
                    "FDC rate limiter: %.1fs 대기 후 호출 허용"
                    "(max_calls=%d/%.0fs).",
                    waited_total,
                    max_calls,
                    window_seconds,
                )
            return FdcRateLimitResult(
                allowed=True, waited_seconds=waited_total, bypassed=False,
            )

        waited_total = time.monotonic() - start
        if waited_total >= max_wait_seconds:
            logger.warning(
                "FDC rate limiter: %.1fs 대기해도 슬롯을 못 얻어 제한 없이 "
                "통과시킴(bypass, max_wait_seconds=%.1f 초과).",
                waited_total,
                max_wait_seconds,
            )
            return FdcRateLimitResult(
                allowed=True,
                waited_seconds=waited_total,
                bypassed=True,
                bypass_reason="max_wait_exceeded",
            )

        sleep_for = min(poll_interval_seconds, max_wait_seconds - waited_total)
        await asyncio.sleep(max(0.0, sleep_for))
        waited_total = time.monotonic() - start
