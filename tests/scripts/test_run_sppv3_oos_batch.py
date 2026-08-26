"""단위 테스트 — SPPV-3 OOS 일봉 cache 배치 wrapper(DB/네트워크 미사용).

전부 인메모리 값·임시 디렉터리·주입된 가짜(fake) 의존성만으로 검증한다.
실제 KIS API, DB, 외부 네트워크는 전혀 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time as dtime, timedelta, timezone

import pytest

from scripts.run_sppv3_oos_batch import (
    CACHE_DIR_PREFIX,
    EARLIEST_RUN_TIME_KST,
    FORBIDDEN_SOURCE_SUBSTRINGS,
    CacheDirState,
    LockAcquisitionError,
    MarketCalendarUnavailableError,
    acquire_batch_lock,
    build_authoritative_holiday_provider,
    build_batch_summary,
    decide_batch_action,
    inspect_cache_dir_state,
    is_time_gate_open,
    run_batch,
)

KST = timezone(timedelta(hours=9))


def _kst(hour: int, minute: int = 0, day: int = 25) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=KST)


# ── 시간 가드 ────────────────────────────────────────────────────────────


class TestIsTimeGateOpen:
    def test_before_2100_is_closed(self):
        assert is_time_gate_open(_kst(20, 59)) is False

    def test_exactly_2100_is_open(self):
        assert is_time_gate_open(_kst(21, 0)) is True

    def test_after_2100_is_open(self):
        assert is_time_gate_open(_kst(23, 30)) is True

    def test_custom_earliest_boundary(self):
        assert is_time_gate_open(_kst(19, 59), earliest=dtime(20, 0)) is False
        assert is_time_gate_open(_kst(20, 0), earliest=dtime(20, 0)) is True


# ── cache 디렉터리 상태 조사 ─────────────────────────────────────────────


class TestInspectCacheDirState:
    def test_missing_dir(self, tmp_path):
        state = inspect_cache_dir_state(str(tmp_path / "nope"))
        assert state == CacheDirState(exists=False, manifest_exists=False, ready_for_oos=None)

    def test_dir_without_manifest(self, tmp_path):
        d = tmp_path / "cache"
        d.mkdir()
        state = inspect_cache_dir_state(str(d))
        assert state == CacheDirState(exists=True, manifest_exists=False, ready_for_oos=None)

    def test_manifest_ready_true(self, tmp_path):
        d = tmp_path / "cache"
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"ready_for_oos": True}))
        state = inspect_cache_dir_state(str(d))
        assert state.ready_for_oos is True

    def test_manifest_ready_false(self, tmp_path):
        d = tmp_path / "cache"
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"ready_for_oos": False}))
        state = inspect_cache_dir_state(str(d))
        assert state.ready_for_oos is False

    def test_manifest_corrupt_json_is_treated_as_unavailable(self, tmp_path):
        d = tmp_path / "cache"
        d.mkdir()
        (d / "manifest.json").write_text("{not valid json")
        state = inspect_cache_dir_state(str(d))
        assert state.manifest_exists is True
        assert state.ready_for_oos is None


# ── 행동 판정(순수 함수) ────────────────────────────────────────────────


class TestDecideBatchAction:
    def test_non_trading_day_skips_regardless_of_cache_state(self):
        action, _ = decide_batch_action(
            is_trading_day=False,
            cache_state=CacheDirState(exists=False, manifest_exists=False, ready_for_oos=None),
        )
        assert action == "skip_non_trading_day"

    def test_already_ready_cache_skips(self):
        action, _ = decide_batch_action(
            is_trading_day=True,
            cache_state=CacheDirState(exists=True, manifest_exists=True, ready_for_oos=True),
        )
        assert action == "skip_already_ready"

    def test_ready_false_manifest_allows_retry(self):
        action, reason = decide_batch_action(
            is_trading_day=True,
            cache_state=CacheDirState(exists=True, manifest_exists=True, ready_for_oos=False),
        )
        assert action == "collect"
        assert "재시도" in reason

    def test_missing_manifest_but_dir_exists_allows_retry(self):
        action, reason = decide_batch_action(
            is_trading_day=True,
            cache_state=CacheDirState(exists=True, manifest_exists=False, ready_for_oos=None),
        )
        assert action == "collect"
        assert "재시도" in reason

    def test_fresh_trading_day_collects(self):
        action, _ = decide_batch_action(
            is_trading_day=True,
            cache_state=CacheDirState(exists=False, manifest_exists=False, ready_for_oos=None),
        )
        assert action == "collect"


# ── lock ────────────────────────────────────────────────────────────────


class TestAcquireBatchLock:
    def test_second_concurrent_acquire_raises(self, tmp_path):
        lock_path = str(tmp_path / "sub" / "batch.lock")
        with acquire_batch_lock(lock_path):
            with pytest.raises(LockAcquisitionError):
                with acquire_batch_lock(lock_path):
                    pass  # pragma: no cover

    def test_lock_is_reacquirable_after_release(self, tmp_path):
        lock_path = str(tmp_path / "batch.lock")
        with acquire_batch_lock(lock_path):
            pass
        with acquire_batch_lock(lock_path):
            pass  # 예외 없이 재획득되면 정상 해제된 것

    def test_lock_file_contains_pid(self, tmp_path):
        lock_path = str(tmp_path / "batch.lock")
        with acquire_batch_lock(lock_path):
            content = open(lock_path, encoding="utf-8").read().strip()
            assert content == str(os.getpid())


# ── 076 국내휴장일조회 provider 구성(weekday fallback 금지) ──────────────


class TestBuildAuthoritativeHolidayProvider:
    @pytest.mark.asyncio
    async def test_disabled_flag_raises_without_calling_network(self, monkeypatch):
        monkeypatch.setenv("KIS_LIVE_INFO_ENABLED", "false")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "dummy")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "dummy")
        with pytest.raises(MarketCalendarUnavailableError):
            await build_authoritative_holiday_provider()

    @pytest.mark.asyncio
    async def test_missing_app_key_raises(self, monkeypatch):
        monkeypatch.setenv("KIS_LIVE_INFO_ENABLED", "true")
        monkeypatch.delenv("KIS_LIVE_INFO_APP_KEY", raising=False)
        monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "dummy")
        with pytest.raises(MarketCalendarUnavailableError):
            await build_authoritative_holiday_provider()

    @pytest.mark.asyncio
    async def test_missing_app_secret_raises(self, monkeypatch):
        monkeypatch.setenv("KIS_LIVE_INFO_ENABLED", "true")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "dummy")
        monkeypatch.delenv("KIS_LIVE_INFO_APP_SECRET", raising=False)
        with pytest.raises(MarketCalendarUnavailableError):
            await build_authoritative_holiday_provider()

    @pytest.mark.asyncio
    async def test_configured_env_constructs_kis_holiday_provider_without_network_call(self, monkeypatch):
        monkeypatch.setenv("KIS_LIVE_INFO_ENABLED", "true")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "dummy-key")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "dummy-secret")
        monkeypatch.setenv("KIS_LIVE_INFO_BASE_URL", "https://example.invalid")
        monkeypatch.setenv("KIS_DISCLOSURE_TOKEN_CACHE_ENABLED", "false")

        from agent_trading.services.market_session import KisHolidayProvider

        provider = await build_authoritative_holiday_provider()
        assert isinstance(provider, KisHolidayProvider)


# ── 요약 로그(민감정보 미노출) ───────────────────────────────────────────


class TestBuildBatchSummary:
    _FORBIDDEN_KEY_FRAGMENTS = ("APP_KEY", "APP_SECRET", "PASSWORD", "TOKEN", "ACCOUNT", "DATABASE_URL")

    def test_no_forbidden_keys_or_values_with_full_manifest(self):
        manifest = {
            "cache_id": "sppv3_oos_bar_cache_2026-08-25",
            "ready_for_oos": True,
            "universe_symbol_count": 88,
            "oos_collection_window": {"start_date": "20260715", "end_date": "20260825"},
            "symbols": [
                {"symbol": "005930", "fetch_status": "ok"},
                {"symbol": "000660", "fetch_status": "failed"},
            ],
        }
        summary = build_batch_summary(
            run_at_kst_iso=_kst(21, 5).isoformat(),
            target_trade_date="2026-08-25",
            action="collect",
            action_reason="신규 수집",
            manifest=manifest,
            analyzer_status_by_candidate={"low_volatility_rank_20d": "PENDING_INSUFFICIENT_OOS_SAMPLE"},
            exit_code=0,
        )
        flattened = json.dumps(summary, ensure_ascii=False)
        for fragment in self._FORBIDDEN_KEY_FRAGMENTS:
            assert fragment not in flattened.upper()

    def test_derives_fetch_counts_from_manifest_symbols(self):
        manifest = {
            "cache_id": "x",
            "ready_for_oos": False,
            "universe_symbol_count": 3,
            "oos_collection_window": {"start_date": "20260715", "end_date": "20260825"},
            "symbols": [
                {"symbol": "A", "fetch_status": "ok"},
                {"symbol": "B", "fetch_status": "ok"},
                {"symbol": "C", "fetch_status": "failed"},
            ],
        }
        summary = build_batch_summary(
            run_at_kst_iso=_kst(21, 5).isoformat(),
            target_trade_date="2026-08-25",
            action="collect",
            action_reason="신규 수집",
            manifest=manifest,
            analyzer_status_by_candidate=None,
            exit_code=1,
        )
        assert summary["fetch_success_count"] == 2
        assert summary["fetch_failed_symbols"] == ["C"]
        assert summary["oos_analysis_run"] is False

    def test_none_manifest_produces_null_fields_not_error(self):
        summary = build_batch_summary(
            run_at_kst_iso=_kst(21, 5).isoformat(),
            target_trade_date="2026-08-25",
            action="skip_non_trading_day",
            action_reason="휴장일",
            manifest=None,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        assert summary["cache_id"] is None
        assert summary["ready_for_oos"] is None
        assert summary["fetch_failed_symbols"] == []


# ── 금지된 client/DB 경로 미사용(정적 회귀 검사) ─────────────────────────


class TestForbiddenSourceReferences:
    def test_wrapper_source_has_no_forbidden_substrings(self):
        wrapper_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts",
            "run_sppv3_oos_batch.py",
        )
        source = open(wrapper_path, encoding="utf-8").read()
        # 각 금지 식별자는 FORBIDDEN_SOURCE_SUBSTRINGS 튜플 리터럴 안에
        # "정의"로 정확히 1번만 등장해야 한다 — 그 외 실제 코드 어디에서도
        # (import·호출·문자열 조합 등) 등장하면 안 된다.
        for forbidden in FORBIDDEN_SOURCE_SUBSTRINGS:
            occurrences = source.count(forbidden)
            assert occurrences == 1, (
                f"금지된 식별자 '{forbidden}'가 {occurrences}번 등장 — "
                "FORBIDDEN_SOURCE_SUBSTRINGS 정의 안에서만 1번 등장해야 한다"
            )


# ── 전체 오케스트레이션(의존성 주입, DB/네트워크 미사용) ─────────────────


class _FakeSessionProvider:
    def __init__(self, is_trading: bool):
        self._is_trading = is_trading

    async def is_trading_day(self, target_date: date) -> bool:
        return self._is_trading


def _make_fake_session_provider_factory(is_trading: bool):
    async def factory():
        return _FakeSessionProvider(is_trading)

    return factory


class TestRunBatchOrchestration:
    async def _run(self, tmp_path, *, is_trading, collector_main, analyzer_main, now_kst=None):
        return await run_batch(
            now_kst=now_kst or _kst(21, 5),
            repo_root=str(tmp_path),
            session_provider_factory=_make_fake_session_provider_factory(is_trading),
            collector_main=collector_main,
            analyzer_main=analyzer_main,
        )

    @pytest.mark.asyncio
    async def test_time_gate_closed_calls_neither_collector_nor_analyzer(self, tmp_path, capsys):
        calls = {"collector": 0, "analyzer": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await self._run(
            tmp_path,
            is_trading=True,
            collector_main=collector_main,
            analyzer_main=analyzer_main,
            now_kst=_kst(20, 0),
        )
        assert exit_code == 0
        assert calls == {"collector": 0, "analyzer": 0}
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["action"] == "skip_time_gate_not_open"

    @pytest.mark.asyncio
    async def test_non_trading_day_calls_neither(self, tmp_path, capsys):
        calls = {"collector": 0, "analyzer": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=False, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 0
        assert calls == {"collector": 0, "analyzer": 0}
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["action"] == "skip_non_trading_day"

    @pytest.mark.asyncio
    async def test_already_ready_cache_calls_neither(self, tmp_path, capsys):
        cache_dir = tmp_path / "logs" / f"{CACHE_DIR_PREFIX}2026-08-25"
        cache_dir.mkdir(parents=True)
        (cache_dir / "manifest.json").write_text(json.dumps({"ready_for_oos": True, "cache_id": "x"}))
        calls = {"collector": 0, "analyzer": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 0
        assert calls == {"collector": 0, "analyzer": 0}
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["action"] == "skip_already_ready"

    @pytest.mark.asyncio
    async def test_collector_failure_prevents_analyzer_call(self, tmp_path, capsys):
        calls = {"collector": 0, "analyzer": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 1  # 실패

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 1
        assert calls["collector"] == 1
        assert calls["analyzer"] == 0

    @pytest.mark.asyncio
    async def test_collector_success_triggers_analyzer_and_pending_status_is_normal(self, tmp_path, capsys):
        cache_dir = tmp_path / "logs" / f"{CACHE_DIR_PREFIX}2026-08-25"

        async def collector_main(argv):
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "cache_id": "sppv3_oos_bar_cache_2026-08-25",
                        "ready_for_oos": True,
                        "universe_symbol_count": 2,
                        "oos_collection_window": {"start_date": "20260715", "end_date": "20260825"},
                        "symbols": [
                            {"symbol": "A", "fetch_status": "ok"},
                            {"symbol": "B", "fetch_status": "ok"},
                        ],
                    }
                )
            )
            return 0

        async def analyzer_main(argv):
            output_path = argv[argv.index("--output-json") + 1]
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "candidates": {
                            "low_volatility_rank_20d": {
                                "status": {"status": "PENDING_INSUFFICIENT_OOS_SAMPLE", "reasons": ["x"]}
                            }
                        }
                    },
                    f,
                )
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 0
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["ready_for_oos"] is True
        assert summary["oos_analysis_run"] is True
        assert (
            summary["oos_analysis_status_by_candidate"]["low_volatility_rank_20d"]
            == "PENDING_INSUFFICIENT_OOS_SAMPLE"
        )
        assert summary["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_collector_success_but_ready_false_skips_analyzer(self, tmp_path):
        cache_dir = tmp_path / "logs" / f"{CACHE_DIR_PREFIX}2026-08-25"
        calls = {"analyzer": 0}

        async def collector_main(argv):
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "manifest.json").write_text(
                json.dumps({"cache_id": "x", "ready_for_oos": False, "symbols": []})
            )
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 0
        assert calls["analyzer"] == 0

    @pytest.mark.asyncio
    async def test_ready_false_manifest_permits_retry_collection(self, tmp_path):
        cache_dir = tmp_path / "logs" / f"{CACHE_DIR_PREFIX}2026-08-25"
        cache_dir.mkdir(parents=True)
        (cache_dir / "manifest.json").write_text(json.dumps({"ready_for_oos": False, "symbols": []}))
        calls = {"collector": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            return 0

        await self._run(tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main)
        assert calls["collector"] == 1

    @pytest.mark.asyncio
    async def test_market_calendar_unavailable_from_provider_construction_skips_before_collector(
        self, tmp_path, capsys
    ):
        calls = {"collector": 0, "analyzer": 0}

        async def failing_factory():
            raise MarketCalendarUnavailableError("076 자격증명 미설정")

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await run_batch(
            now_kst=_kst(21, 5),
            repo_root=str(tmp_path),
            session_provider_factory=failing_factory,
            collector_main=collector_main,
            analyzer_main=analyzer_main,
        )
        assert exit_code == 0
        assert calls == {"collector": 0, "analyzer": 0}
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["action"] == "skip_market_calendar_unavailable"

    @pytest.mark.asyncio
    async def test_076_failure_on_is_trading_day_never_falls_back_to_weekday_heuristic(self, tmp_path, capsys):
        """076 provider가 구성은 됐지만 is_trading_day() 호출이 실패(인증 오류/timeout
        시뮬레이션)하면, weekday heuristic으로 넘어가지 않고 즉시 안전 skip해야 한다."""

        class _ProviderThatFailsOnCall:
            async def is_trading_day(self, target_date):
                raise TimeoutError("076 API timeout(시뮬레이션)")

        async def factory():
            return _ProviderThatFailsOnCall()

        calls = {"collector": 0, "analyzer": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            calls["analyzer"] += 1
            return 0

        exit_code = await run_batch(
            now_kst=_kst(21, 5),  # 화요일 21:05 — weekday heuristic이었다면 거래일로 통과했을 시각
            repo_root=str(tmp_path),
            session_provider_factory=factory,
            collector_main=collector_main,
            analyzer_main=analyzer_main,
        )
        assert exit_code == 0
        assert calls == {"collector": 0, "analyzer": 0}, "076 실패 시 weekday fallback으로 수집기가 호출되면 안 된다"
        summary = json.loads(capsys.readouterr().out.strip())
        assert summary["action"] == "skip_market_calendar_unavailable"

    @pytest.mark.asyncio
    async def test_holiday_provider_success_path_still_reaches_collector(self, tmp_path):
        """076 provider가 정상 응답하면(거래일=True) 기존 흐름 그대로 수집기까지 도달해야 한다."""
        calls = {"collector": 0}

        async def collector_main(argv):
            calls["collector"] += 1
            return 0

        async def analyzer_main(argv):
            return 0

        exit_code = await self._run(
            tmp_path, is_trading=True, collector_main=collector_main, analyzer_main=analyzer_main
        )
        assert exit_code == 0
        assert calls["collector"] == 1
