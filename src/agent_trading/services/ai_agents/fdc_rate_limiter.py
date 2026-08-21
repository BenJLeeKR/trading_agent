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

설계(2026-08-18, strict 전환 2026-08-21)
-----------------------------------------
- 모든 subprocess가 같은 상태 파일(기본: OS 임시 디렉터리 아래)을
  ``fcntl.flock``으로 직렬화해 읽고 쓴다 — 같은 호스트/컨테이너
  파일시스템을 공유하는 한 프로세스 경계와 무관하게 실제로 공유된다.
- 최근 ``window_seconds`` 이내에 실제로 permit이 발급된 시각(``grants``)
  수가 ``max_calls`` 이상이면, 가장 오래된 grant가 윈도우를 벗어날
  때까지 짧게 대기(polling)한 뒤 재시도한다.
- ``max_wait_seconds``를 넘도록 슬롯을 못 얻으면 — **더 이상 통과시키지
  않는다.** ``granted=False, queue_timeout=True``를 반환하고, 호출자는
  이 경우 절대로 실제 Gemini HTTP 요청을 보내지 않는다(2026-08-21
  strict queue 전환 — 이전의 fail-open bypass 설계를 완전히 제거했다.
  이 변경의 배경은 ``docs/30_work_log/2026-08-21_fdc_strict_rate_
  limiter_and_retry_permit.md`` 참고).
- 상태 파일 접근 자체가 실패하면(파일시스템 오류 등)도 마찬가지로
  ``granted=False, state_file_error=True``를 반환한다 — 더 이상
  fail-open으로 통과시키지 않는다. 호출자는 이 경우 안전하게
  ``provider_limiter_unavailable`` fallback으로 HOLD를 반환해야 한다.
- **import-time 부작용 없음** — 모듈을 import하는 것만으로는 파일이나
  디렉터리를 만들지 않는다. 상태 파일은 ``wait_for_fdc_slot()``을
  실제로 호출한 시점에만 lazy하게 생성된다. 이는 이 harness의
  dev-validation 컨테이너처럼 ``/workspace`` 하위가 read-only인
  환경에서도 이 모듈 자체는 안전하게 import/단위 테스트할 수 있게
  하기 위함이다(``subprocess_io.py``와 동일한 설계 원칙).

설계(2026-08-21, in-cycle FIFO 재대기열 도입)
------------------------------------------------
운영 실측(``docs/30_work_log/2026-08-21_fdc_strict_rate_limiter_and_
retry_permit.md`` 및 그 이후 다회 사이클 조사)에서, 기존 구조는 진짜
FIFO 큐가 아니라 **"폴링 기반 경쟁(polling race)"**임이 확인됐다 —
``list[float]`` 타임스탬프만 저장하고, 대기 중인 호출자 간 순번을
전혀 기억하지 않는다. 이번 개정은 상태 파일 내부 구조를
``{"version": 1, "grants": [...], "pending": [...]}``로 분리해 진짜
FIFO ticket queue를 구현한다.

- ``grants``: 실제 permit이 발급된 시각만 담는다(기존 ``list[float]``와
  동일한 의미). ``window_seconds``(60초)가 지난 grant만 트림한다.
- ``pending``: FIFO ticket 목록. 각 ticket은
  ``ticket_id``/``lane``/``enqueued_at``/``last_heartbeat_at``/
  ``lease_expires_at``/``requeue_count``를 담는다. **head(맨 앞) ticket만
  grant를 받을 수 있다.** grant되면 그 ticket을 ``pending``에서 제거하고
  ``grants``에 현재 시각을 추가한다.
- **1회 재대기(tail 재등록)**: 최초 HTTP 요청을 위한 permit 획득
  (``allow_requeue=True``)에 한해, 1차 대기 상한(``max_wait_seconds``,
  기본 18초)을 넘기면 해당 ticket을 제거하고 **새 ticket으로 FIFO의
  맨 뒤에 1회만 재등록**한다. 2차 대기도 동일하게 최대 18초이며, 그래도
  실패하면 ``queue_timeout=True``로 확정 종료한다(bypass 없음).
  ``provider_client.py``의 429/5xx 재시도 permit 획득
  (``allow_requeue=False``)은 재대기를 허용하지 않는다 — 재시도마다
  18+18초씩 재대기를 허용하면 ``_FDC_PER_AGENT_TIMEOUT``(70초) 예산을
  초과할 수 있기 때문이다(자세한 계산은
  ``scripts/run_agent_subprocess.py``의 ``_FdcPermitAccumulator`` 참고).
- **orphan ticket 정리**: 정상 완료·예외·취소 시에는 ``finally``에서
  자기 ticket을 즉시 제거한다(best-effort). 그렇게 되지 않은(예:
  프로세스가 SIGKILL로 강제 종료된) ticket만, 다른 참여자가 폴링하며
  ``flock`` 안에서 ``last_heartbeat_at`` 기준 lease(``30초``) 초과 여부로
  판별해 정리한다. lease는 poll 주기(1초)보다 훨씬 길게(30초) 잡아
  일시적 스케줄링 지연만으로 살아있는 ticket이 삭제되지 않게 한다.

설계(2026-08-21, 3차 — 손상 상태 파일 fail-closed 보정)
---------------------------------------------------------
코드 검토에서 ``_read_state()``가 JSON 파싱 실패/최상위 구조 이상/
``version`` 불일치/``grants``·``pending`` 타입 이상을 **전부 조용히
빈 상태(``_empty_state()``)로 대체**하고 있었음이 확인됐다 — 이는
strict no-bypass 원칙의 허점이다: 상태 파일이 어떤 이유로든 손상되면
최근 60초 ``grants`` 기록이 통째로 사라지고, 다음 폴러가 "윈도우가
비어 있다"고 오판해 ``DEFAULT_MAX_CALLS_PER_WINDOW`` 한도를 무시한
채 새 permit을 계속 발급할 수 있었다(사실상 fail-open으로 되돌아가는
구멍). 이번 개정은 이 구분을 명확히 한다:

- **정상 신규 파일**(``open(path, "a+")``가 방금 새로 만든, 내용이
  완전히 비어 있는 파일)만 빈 v1 상태로 초기화한다.
- 그 외 **읽을 수 없거나 해석할 수 없는 모든 내용**(JSON 파싱 실패,
  최상위가 dict/list가 아님, 지원하지 않는 ``version``, ``grants``/
  ``pending``이 list가 아님)은 ``_CorruptStateFileError``(``OSError``
  서브클래스)를 발생시켜 ``wait_for_fdc_slot()``의 기존
  ``state_file_error=True`` 경로로 확정 실패시킨다 — HTTP 요청을
  절대 보내지 않는다(호출자는 ``provider_limiter_unavailable``로
  처리).
- **PR #311 이전의 legacy ``list[float]`` 포맷**(순수 숫자 리스트,
  예: ``[1755, 1758.2]``)만 예외적으로 허용해
  ``{"version": 1, "grants": <그 리스트>, "pending": []}``로 flock
  안에서 1회 변환하고, 같은 폴링 호출이 끝나기 전에 v1 구조로 다시
  저장한다 — 배포 직후 기존 60초 grant 기록을 잃지 않기 위함이다.
  리스트에 숫자가 아닌 값이 섞여 있으면(혼합/손상) 마이그레이션하지
  않고 손상으로 취급한다. legacy grant도 기존 ``_trim_grants()``가
  그대로 60초 기준 트림한다(별도 로직 불필요).

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
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_CALLS_PER_WINDOW = 10
DEFAULT_WINDOW_SECONDS = 60.0
# 2026-08-21 재계산(20.0 → 18.0, strict queue + retry-inclusive 전환).
#
# 구조 변화: 기존에는 이 대기가 `scripts/run_agent_subprocess.py`에서
# FDC 30초 per-agent timeout 블록 **앞에서** 단 1회만 일어났다. 이번
# 전환으로 permit 획득이 `provider_client.py`의 재시도 루프 **안으로**
# 들어가면서, 최초 요청 + 매 재시도(`MAX_RETRIES=3`)마다 각각 permit을
# 다시 획득한다 — 즉 이 대기가 이제는 FDC per-agent timeout **예산
# 안에서** 최대 3회 반복될 수 있다.
#
# 예산 재계산 근거(``_FDC_PER_AGENT_TIMEOUT=70``, run_agent_subprocess.py):
#   subprocess 전체 timeout 90초 - 그 외 오버헤드/안전마진 20초 = 70초.
#
# 2026-08-21 표현 수정(PR #311 코드 검토): 아래 계산은 "최악의 경우
# 시간을 보장한다"는 뜻이 **아니다** — Gemini HTTP 왕복 시간을 통상
# 관측치인 약 3초/회로 가정한 **설계 목표치**일 뿐이며, 실제 요청이 이
# 가정보다 오래 걸리는 경우까지 상한을 강제하지는 못한다. 70초라는
# 상한 자체는 strict queue 대기(permit 획득)와 provider 실행 시간을
# 합친 총 예산이며, 이 예산을 넘으면(느린 HTTP 응답 등으로) 아래
# `max_wait_seconds` 계산과 무관하게 `_FDC_PER_AGENT_TIMEOUT` 자체가
# `asyncio.wait_for()`로 강제 종료돼 `provider_timeout` fallback으로
# 귀결된다(``run_agent_subprocess.py`` 참고) — 즉 실제 시간 상한 보장은
# 이 permit 대기 계산이 아니라 그 바깥의 `_FDC_PER_AGENT_TIMEOUT`이
# 담당한다.
#
# 설계 목표치 산출(3초/회 HTTP 왕복 가정, 최악 3회 모두 429로 재시도):
#   3 x max_wait_seconds(permit 대기) + 3 x 가정 HTTP 왕복(약 3초/회)
#   + 2회 재시도 사이 backoff(RETRY_DELAY 기반, 약 1초+2초=3초)
#   <= 70초
#   => 3 x max_wait_seconds <= 70 - 9 - 3 = 58
#   => max_wait_seconds <= 19.33초
# 18.0초로 설정해 이 가정 위에서 약 4초의 여유를 남긴다
# (3x18 + 9 + 3 = 66 <= 70, 단 HTTP 왕복이 가정보다 느리면 이 여유는
# 줄어들거나 소진될 수 있다 — 그 경우의 확정적 종료는
# `_FDC_PER_AGENT_TIMEOUT`이 담당).
# 큐 대기 자체는 항상 유한 시간 안에 종료되며(무한 대기 금지), 상한
# 초과 시 `queue_timeout=True`로 확정 종료한다(더 이상 bypass하지
# 않음 — 상단 모듈 docstring 참고).
#
# 2026-08-21(2차) in-cycle FIFO 재대기 도입 후 주의: 이 값(18.0초)은
# "1회 대기 상한"이며, 최초 HTTP 요청의 permit 획득은 최대 1회
# 재대기(FIFO tail 재등록)가 허용돼 **최악 36초**(18+18)까지 걸릴 수
# 있다. 이는 위 66초 설계 목표치 계산의 전제(모든 attempt가 각각
# 18초 이하)를 깨뜨린다 — 즉 "최초 요청 permit 대기(최악 36초) + 재시도
# 2회(각 18초, 재대기 없음) + HTTP/backoff(약 12초)" 최악 시나리오는
# 이론상 84초로 70초 예산을 초과할 수 있다. 이 경우 시스템은 멈추거나
# 예산을 무한정 넘기지 않는다 — `_FDC_PER_AGENT_TIMEOUT`의
# `asyncio.wait_for()`가 70초에서 확정적으로 강제 종료해
# `provider_timeout` fallback으로 귀결된다(기존에 이미 검증된 안전
# 경로). 즉 "재대기 + 최대 재시도 동시 발생"이라는 드문 복합 케이스는
# `provider_queue_timeout` 대신 `provider_timeout`으로 관측될 수 있다는
# 뜻이며, 이는 결함이 아니라 기존 안전판이 정상 작동한 것이다(자세한
# 근거는 work log 참고). `_FDC_PER_AGENT_TIMEOUT`/`_SUBPROCESS_TIMEOUT`
# 자체는 이번 변경에서 올리지 않았다(요청 범위 밖).
DEFAULT_MAX_WAIT_SECONDS = 18.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
# 2026-08-21(2차) 신설: pending ticket의 lease 기간. 폴링 주기(1초)보다
# 훨씬 길게 잡아, 일시적 스케줄링 지연이나 GC pause만으로 살아있는
# ticket이 orphan으로 오인돼 삭제되지 않게 한다. 3~5초처럼 짧게 잡지
#않는다(요청사항) — 정상적으로 살아있는 프로세스는 매 poll_interval
# (1초)마다 heartbeat를 갱신하므로, 30초 무갱신은 사실상 프로세스
# 사망/취소를 의미한다고 봐도 안전하다.
DEFAULT_TICKET_LEASE_SECONDS = 30.0
# 최초 HTTP 요청의 permit 획득에서 허용하는 최대 재대기(FIFO tail
# 재등록) 횟수. provider 재시도(429/5xx) permit 획득은 항상
# `allow_requeue=False`로 호출해 이 상수와 무관하게 재대기하지 않는다.
DEFAULT_MAX_REQUEUE_COUNT = 1
_STATE_FILENAME = "agent_trading_fdc_rate_limiter_state.json"
_STATE_VERSION = 1


def default_state_path() -> str:
    """상태 파일의 기본 경로(OS 임시 디렉터리)를 반환한다.

    ``tempfile.gettempdir()``는 운영 컨테이너와 이 harness의
    dev-validation 컨테이너 양쪽 모두에서 항상 쓰기 가능한 경로다
    (``/workspace/agent_trading/logs``와 달리 read-only 제약이 없다).
    """
    return str(Path(tempfile.gettempdir()) / _STATE_FILENAME)


@dataclass(slots=True, frozen=True)
class FdcRateLimitResult:
    """rate limiter 판정 결과(strict, no-bypass, FIFO 재대기 포함).

    Attributes
    ----------
    granted:
        ``True``면 슬롯을 확보해 실제 HTTP 요청을 진행해도 된다.
        ``False``면 절대 HTTP 요청을 보내면 안 된다 — 아래
        ``queue_timeout``/``state_file_error`` 중 정확히 하나가
        ``True``다.
    waited_seconds:
        이번 호출 동안 **누적** 대기한 시간(초) — 재대기가 발생했으면
        1차+2차 대기를 합산한 값이다. 슬롯을 즉시 확보했으면 ``0.0``.
    queue_timeout:
        ``True``면 정상적인 slot 대기 큐에서 (재대기까지 포함해도)
        슬롯을 못 얻어 포기했다는 뜻(``provider_queue_timeout``).
    state_file_error:
        ``True``면 상태 파일 접근 자체가 실패했다는 뜻
        (``provider_limiter_unavailable``).
    queue_ticket:
        이번 호출에서 마지막으로 사용한 ticket id. 재대기가 발생하면
        1차와 2차의 ticket id가 다르다(새 ticket으로 재등록하므로) —
        이 필드는 항상 **마지막(최종 결과에 관여한)** ticket만 담는다.
    queue_position_at_first_wait:
        처음으로 슬롯을 못 얻어 대기가 필요했던 순간, 내 ticket 앞에
        대기 중이던 ticket 수(0-based position). 슬롯을 즉시 확보했으면
        ``None``.
    requeue_count:
        이번 호출에서 실제로 재대기(FIFO tail 재등록)가 일어난 횟수
        (``0`` 또는 ``1`` — ``DEFAULT_MAX_REQUEUE_COUNT`` 상한).
    final_waited_seconds:
        마지막 attempt(성공했거나 최종적으로 실패한 attempt) **단독**의
        대기 시간. 재대기가 없었으면 ``waited_seconds``와 같다.
    queue_deadline_exceeded:
        ``True``면 재대기까지 전부 사용했는데도(``requeue_count>=1``)
        여전히 슬롯을 못 얻어 확정 실패했다는 뜻 — ``queue_timeout``의
        세부 원인을 구분하기 위한 관측 전용 플래그.
    """

    granted: bool
    waited_seconds: float
    queue_timeout: bool = False
    state_file_error: bool = False
    queue_ticket: str | None = None
    queue_position_at_first_wait: int | None = None
    requeue_count: int = 0
    final_waited_seconds: float = 0.0
    queue_deadline_exceeded: bool = False


def _empty_state() -> dict:
    return {"version": _STATE_VERSION, "grants": [], "pending": []}


class _CorruptStateFileError(OSError):
    """상태 파일 내용이 손상됐거나 지원하지 않는 형식이다.

    ``OSError``의 서브클래스로 만들어 ``wait_for_fdc_slot()``의 기존
    ``except OSError`` 처리 경로(``state_file_error=True``, HTTP 요청
    금지, ``provider_limiter_unavailable``로 귀결)를 그대로 재사용한다.
    이 예외를 빈 상태로 조용히 삼키면(과거 결함) 최근 60초 ``grants``
    기록을 잃어 strict RPM 한도를 우회하게 되므로, 반드시 fail-closed
    경로로 전파돼야 한다.
    """


def _read_state(fh: object) -> dict:
    """상태 파일 내용을 읽어 ``{"version", "grants", "pending"}`` 구조로
    반환한다.

    - 파일이 **완전히 비어 있으면**(``open(path, "a+")``가 방금 새로
      만든 신규 파일) 정상적인 빈 v1 상태로 취급한다.
    - **PR #311 이전 legacy ``list[float]`` 포맷**(순수 숫자로만 구성된
      리스트, 빈 리스트 포함)은 ``{"version": 1, "grants": <그 값>,
      "pending": []}``로 1회 변환해 반환한다 — 호출자(``_poll_ticket``)
      가 이 반환값을 그대로 다시 저장하므로 다음 호출부터는 v1
      구조다. 숫자가 아닌 값이 섞여 있으면 마이그레이션하지 않는다.
    - 그 외 JSON 파싱 실패, 최상위가 dict/list가 아님, 지원하지 않는
      ``version``, ``grants``/``pending``이 list가 아닌 모든 경우는
      **손상으로 간주**해 ``_CorruptStateFileError``를 던진다 — 빈
      상태로 조용히 대체하지 않는다(strict no-bypass 보장의 핵심).
    """
    fh.seek(0)  # type: ignore[attr-defined]
    raw = fh.read()  # type: ignore[attr-defined]
    if not raw.strip():
        # 방금 생성된 신규 파일(또는 명시적으로 비워진 파일) — 정상
        # 초기 상태로 취급한다. 손상 상태와 구분되는 유일한 "안전하게
        # 빈 상태로 봐도 되는" 경우다.
        return _empty_state()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _CorruptStateFileError(
            f"상태 파일 JSON 파싱 실패(빈 상태로 대체하지 않음): {exc}"
        ) from exc

    if isinstance(data, list):
        # legacy 포맷(PR #311 이전, 순수 list[float] 타임스탬프).
        if all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in data
        ):
            logger.info(
                "FDC rate limiter: legacy list[float] 상태 파일을 v1 "
                "구조로 마이그레이션함(grants=%d건 보존).",
                len(data),
            )
            return {"version": _STATE_VERSION, "grants": list(data), "pending": []}
        raise _CorruptStateFileError(
            "legacy list 상태에 숫자가 아닌 항목이 섞여 있어 "
            "마이그레이션할 수 없음(빈 상태로 대체하지 않음)"
        )

    if not isinstance(data, dict):
        raise _CorruptStateFileError(
            f"상태 파일 최상위 구조가 dict/list가 아님: {type(data).__name__}"
        )

    version = data.get("version")
    if version != _STATE_VERSION:
        raise _CorruptStateFileError(
            f"지원하지 않는 상태 파일 version={version!r}"
            f"(기대값={_STATE_VERSION!r})"
        )

    grants = data.get("grants")
    pending = data.get("pending")
    if not isinstance(grants, list):
        raise _CorruptStateFileError(
            f"grants가 list가 아님: {type(grants).__name__}"
        )
    if not isinstance(pending, list):
        raise _CorruptStateFileError(
            f"pending이 list가 아님: {type(pending).__name__}"
        )

    return {"version": _STATE_VERSION, "grants": grants, "pending": pending}


def _write_state(fh: object, state: dict) -> None:
    fh.seek(0)  # type: ignore[attr-defined]
    fh.truncate()  # type: ignore[attr-defined]
    fh.write(json.dumps(state))  # type: ignore[attr-defined]
    fh.flush()  # type: ignore[attr-defined]


def _trim_grants(grants: list, *, now: float, window_seconds: float) -> list[float]:
    """``window_seconds``가 지난 grant만 제거한다. pending ticket은 이
    함수의 대상이 아니다(요청사항 — grant와 pending의 수명 규칙은
    완전히 분리된다)."""
    cutoff = now - window_seconds
    return [g for g in grants if isinstance(g, (int, float)) and g >= cutoff]


def _clean_orphan_pending(
    pending: list, *, my_ticket_id: str, now: float, lease_seconds: float
) -> list[dict]:
    """``lease_seconds``만큼 heartbeat가 갱신되지 않은 **남의** ticket만
    제거한다. 내 ticket은 이 시점에 아직 상태 파일에 없을 수도 있으므로
    (최초 등록 전) 이 함수의 정리 대상에서 무조건 제외한다. 형식이
    깨진 항목(``ticket_id`` 없음 등)도 방어적으로 제거한다 — 이 상태
    파일은 신뢰 경계 내부(같은 컨테이너의 자체 프로세스들)이므로 이런
    항목은 버그의 흔적일 뿐 공격 벡터가 아니다.
    """
    cleaned: list[dict] = []
    for ticket in pending:
        if not isinstance(ticket, dict) or "ticket_id" not in ticket:
            continue
        if ticket["ticket_id"] == my_ticket_id:
            cleaned.append(ticket)
            continue
        last_heartbeat = ticket.get("last_heartbeat_at")
        if not isinstance(last_heartbeat, (int, float)) or (now - last_heartbeat) > lease_seconds:
            logger.warning(
                "FDC rate limiter: orphan ticket 정리(ticket_id=%s lane=%s "
                "requeue_count=%s) — heartbeat 경과=%.1fs > lease=%.1fs.",
                ticket.get("ticket_id"),
                ticket.get("lane"),
                ticket.get("requeue_count"),
                now - last_heartbeat if isinstance(last_heartbeat, (int, float)) else -1.0,
                lease_seconds,
            )
            continue
        cleaned.append(ticket)
    return cleaned


@dataclass(slots=True, frozen=True)
class _TicketPollOutcome:
    """``_poll_ticket()`` 1회 호출의 결과(모듈 내부 전용)."""

    granted: bool
    queue_position: int


def _poll_ticket(
    state_path: str,
    *,
    ticket_id: str,
    lane: str,
    requeue_count: int,
    max_calls: int,
    window_seconds: float,
    lease_seconds: float,
    now: float,
) -> _TicketPollOutcome:
    """상태 파일을 잠그고 ticket을 (최초라면)등록/(이미 있다면)heartbeat
    갱신하며, head ticket이고 윈도우에 여유가 있으면 즉시 grant한다
    (동기 함수, 파일 I/O — ``asyncio.to_thread``로 호출됨).

    이 함수 1회 호출이 "등록 또는 heartbeat 갱신"과 "grant 판정"을
    ``flock`` 하나의 임계 구역 안에서 원자적으로 수행한다 — 두 단계로
    나누면 그 사이에 다른 프로세스가 끼어들어 순서를 어길 수 있다.

    Raises
    ------
    OSError
        상태 파일을 열거나 잠그는 데 실패한 경우 — 호출자가
        ``state_file_error``로 처리한다(기존과 동일한 계약, strict —
        더 이상 fail-open bypass 아님).
    _CorruptStateFileError
        (``OSError`` 서브클래스) 상태 파일 내용이 손상됐거나 지원하지
        않는 형식인 경우 — ``_read_state()``가 던진다. 이 경우도
        위와 동일하게 ``state_file_error``로 처리되며, 절대 빈 상태로
        조용히 대체되지 않는다(2026-08-21 3차 수정).
    """
    directory = os.path.dirname(state_path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(state_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            state = _read_state(fh)
            grants = _trim_grants(state["grants"], now=now, window_seconds=window_seconds)
            pending = _clean_orphan_pending(
                state["pending"], my_ticket_id=ticket_id, now=now, lease_seconds=lease_seconds,
            )

            my_index = next(
                (i for i, t in enumerate(pending) if t.get("ticket_id") == ticket_id), None,
            )
            if my_index is None:
                pending.append({
                    "ticket_id": ticket_id,
                    "lane": lane,
                    "enqueued_at": now,
                    "last_heartbeat_at": now,
                    "lease_expires_at": now + lease_seconds,
                    "requeue_count": requeue_count,
                })
                my_index = len(pending) - 1
            else:
                pending[my_index]["last_heartbeat_at"] = now
                pending[my_index]["lease_expires_at"] = now + lease_seconds

            if my_index == 0 and len(grants) < max_calls:
                # head이고 윈도우에 여유 있음 — 즉시 grant.
                pending.pop(0)
                grants.append(now)
                _write_state(fh, {"version": _STATE_VERSION, "grants": grants, "pending": pending})
                return _TicketPollOutcome(granted=True, queue_position=0)

            _write_state(fh, {"version": _STATE_VERSION, "grants": grants, "pending": pending})
            return _TicketPollOutcome(granted=False, queue_position=my_index)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _remove_ticket(state_path: str, ticket_id: str) -> None:
    """내 ticket을 ``pending``에서 즉시 제거한다.

    ``wait_for_fdc_slot()``의 ``finally``에서 항상 호출된다(정상 종료·
    예외·취소 무관) — 이미 grant돼 pending에서 빠졌거나(성공 경로),
    애초에 등록되지 않았으면(파일 오류로 한 번도 폴링 못한 경우 등)
    안전한 no-op이다. 이 함수 자체가 실패해도(상태 파일 접근 불가 등)
    예외를 삼킨다 — best-effort 정리이며, 호출자의 주 반환값에 영향을
    주면 안 되기 때문이다(이미 grant/queue_timeout/state_file_error
    판정이 끝난 뒤에 호출되므로).
    """
    try:
        directory = os.path.dirname(state_path) or "."
        os.makedirs(directory, exist_ok=True)
        with open(state_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                state = _read_state(fh)
                original_pending = state["pending"]
                pending = [
                    t for t in original_pending
                    if not (isinstance(t, dict) and t.get("ticket_id") == ticket_id)
                ]
                if len(pending) != len(original_pending):
                    _write_state(
                        fh,
                        {"version": _STATE_VERSION, "grants": state["grants"], "pending": pending},
                    )
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        logger.warning(
            "FDC rate limiter: ticket(%s) 정리 중 상태 파일 접근 실패"
            "(best-effort 정리이므로 무시 — lease 만료 후 다른 참여자가 정리함).",
            ticket_id,
        )


async def wait_for_fdc_slot(
    *,
    max_calls: int = DEFAULT_MAX_CALLS_PER_WINDOW,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    state_path: str | None = None,
    lease_seconds: float = DEFAULT_TICKET_LEASE_SECONDS,
    allow_requeue: bool = True,
    lane: str = "unknown",
) -> FdcRateLimitResult:
    """FDC provider 호출 전 공유 rate limit 슬롯을 확보할 때까지 대기한다.

    여러 독립 프로세스가 같은 상태 파일을 파일 락으로 직렬화해
    sliding-window 호출 횟수와 FIFO ticket 대기열을 실제로 공유한다.

    2026-08-21(2차) in-cycle FIFO 재대기: ``allow_requeue=True``(기본값,
    최초 HTTP 요청용)이면 1차 대기 상한(``max_wait_seconds``)을
    넘겨도 즉시 포기하지 않고, 새 ticket으로 FIFO 맨 뒤에 **1회만**
    재등록해 2차 대기(최대 ``max_wait_seconds``)를 한 번 더 시도한다.
    ``allow_requeue=False``(provider 429/5xx 재시도 permit 획득용)이면
    1차 대기 상한 초과 즉시 확정 실패한다 — 재시도마다 재대기를 허용하면
    FDC per-agent timeout 예산을 초과할 수 있기 때문이다(모듈 docstring
    "2026-08-21(2차)" 절 참고).

    2026-08-21 strict 전환: 슬롯을 확보하지 못하면(대기+재대기 상한 초과
    또는 상태 파일 오류) 더 이상 통과시키지 않는다 — ``granted=False``를
    반환하며, 호출자는 이 경우 반드시 실제 HTTP 요청을 생략해야 한다.
    이 함수 자체는 무한정 기다리지 않는다 — 항상 확정적으로 종료된다
    (최악의 경우 ``2 x max_wait_seconds``, 재대기 미허용이면
    ``max_wait_seconds``).
    """
    resolved_path = state_path or default_state_path()
    ticket_id = uuid.uuid4().hex
    total_waited = 0.0
    queue_position_at_first_wait: int | None = None
    requeue_count = 0
    attempt_waited = 0.0

    try:
        while True:
            attempt_start = time.monotonic()
            attempt_waited = 0.0

            while True:
                now = time.time()
                try:
                    outcome = await asyncio.to_thread(
                        _poll_ticket,
                        resolved_path,
                        ticket_id=ticket_id,
                        lane=lane,
                        requeue_count=requeue_count,
                        max_calls=max_calls,
                        window_seconds=window_seconds,
                        lease_seconds=lease_seconds,
                        now=now,
                    )
                except OSError as exc:
                    logger.warning(
                        "FDC rate limiter: 상태 파일(%s) 접근 실패 — HTTP 요청을 "
                        "허용하지 않고 즉시 거부함(state_file_error). ticket=%s %s",
                        resolved_path,
                        ticket_id,
                        exc,
                    )
                    return FdcRateLimitResult(
                        granted=False,
                        waited_seconds=total_waited,
                        state_file_error=True,
                        queue_ticket=ticket_id,
                        queue_position_at_first_wait=queue_position_at_first_wait,
                        requeue_count=requeue_count,
                        final_waited_seconds=attempt_waited,
                    )

                if outcome.granted:
                    attempt_waited = time.monotonic() - attempt_start
                    total_waited += attempt_waited
                    if total_waited > 0:
                        logger.info(
                            "FDC rate limiter: ticket=%s %.1fs 대기(requeue_count=%d) "
                            "후 호출 허용(max_calls=%d/%.0fs).",
                            ticket_id, total_waited, requeue_count, max_calls, window_seconds,
                        )
                    return FdcRateLimitResult(
                        granted=True,
                        waited_seconds=total_waited,
                        queue_ticket=ticket_id,
                        queue_position_at_first_wait=queue_position_at_first_wait,
                        requeue_count=requeue_count,
                        final_waited_seconds=attempt_waited,
                    )

                if queue_position_at_first_wait is None:
                    queue_position_at_first_wait = outcome.queue_position

                attempt_waited = time.monotonic() - attempt_start
                if attempt_waited >= max_wait_seconds:
                    break  # 이번 attempt(1차 또는 재대기) 대기 소진

                sleep_for = min(poll_interval_seconds, max_wait_seconds - attempt_waited)
                await asyncio.sleep(max(0.0, sleep_for))
                attempt_waited = time.monotonic() - attempt_start

            # 이번 attempt의 대기 상한 소진 — 재대기 여부를 결정한다.
            total_waited += attempt_waited
            await asyncio.to_thread(_remove_ticket, resolved_path, ticket_id)

            if allow_requeue and requeue_count < DEFAULT_MAX_REQUEUE_COUNT:
                requeue_count += 1
                logger.warning(
                    "FDC rate limiter: ticket=%s %.1fs 대기해도 슬롯을 못 얻어 "
                    "새 ticket으로 FIFO 맨 뒤에 재등록함(requeue_count=%d).",
                    ticket_id, attempt_waited, requeue_count,
                )
                ticket_id = uuid.uuid4().hex  # 새 ticket으로 재등록(FIFO tail)
                continue

            logger.warning(
                "FDC rate limiter: ticket=%s 총 %.1fs 대기(requeue_count=%d) 후에도 "
                "슬롯을 못 얻어 큐 대기를 포기함(queue_timeout, allow_requeue=%s) — "
                "HTTP 요청을 보내지 않음.",
                ticket_id, total_waited, requeue_count, allow_requeue,
            )
            return FdcRateLimitResult(
                granted=False,
                waited_seconds=total_waited,
                queue_timeout=True,
                queue_ticket=ticket_id,
                queue_position_at_first_wait=queue_position_at_first_wait,
                requeue_count=requeue_count,
                final_waited_seconds=attempt_waited,
                queue_deadline_exceeded=requeue_count >= 1,
            )
    finally:
        # 성공/실패/예외/취소 어느 경로든 마지막으로 남아있을 수 있는
        # 내 ticket을 즉시 정리한다. 성공 경로나 위에서 이미 명시적으로
        # 제거한 경로에서는 안전한 no-op이다 — 정상 완료 시에도 반드시
        # 호출해 "정상 완료 시 finally에서 즉시 제거" 요구사항을
        # 충족한다.
        await asyncio.to_thread(_remove_ticket, resolved_path, ticket_id)
