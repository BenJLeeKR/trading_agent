"""KIS Paper + AI Layer Combined Runtime Smoke Verification (Plan 36).

Verifies that:

* **Scenario A** — ``build_default_runtime()`` returns a fully wired dict
  containing both the KIS broker adapter and all three AI agent slots.
* **Scenario B** — ``assemble()`` produces an ``OrderIntent`` whose
  ``SubmitOrderRequest`` is AI-field-free and passes KIS adapter
  pre-validation.
* **Scenario C** — **Pre-submit compatibility only** (no actual submit).
  ``TestPreSubmitCompatibility`` runs in any environment — no KIS
  credentials required.  ``TestGuardedPaperSubmit`` (C3) is gated
  behind an explicit opt-in for guarded paper submit.

Safety guards
-------------
* ``_no_submit_guard`` (``TestPreSubmitCompatibility``) permanently blocks
  ``submit_order`` — if any test accidentally calls it, ``pytest.fail()``.
  This is a **compile-time-style guarantee** that C1/C2 never touch
  the network.
* ``_read_only_guard`` (``TestGuardedPaperSubmit``) blocks write
  operations by default; opt-in lifts the block for guarded submit.
* ``_check_paper_env()`` fails immediately when ``KIS_ENV`` is not
  ``paper`` (used only by C3 opt-in guard).
* Actual paper submit (C3) requires 3 conditions:
  1. KIS paper credentials configured.
  2. ``KIS_ENV=paper`` (or unset, defaulting to ``paper``).
  3. ``ENABLE_KIS_PAPER_SUBMIT_SMOKE=true``.

Usage
-----
    # Always-run tests (Scenario A + B + C1, C2):
    pytest tests/smoke/test_kis_paper_ai_runtime_smoke.py -v

    # With real provider (adds B3):
    pytest tests/smoke/test_kis_paper_ai_runtime_smoke.py -v -m smoke

    # With KIS paper + opt-in (adds C3 actual submit):
    ENABLE_KIS_PAPER_SUBMIT_SMOKE=true \\
        pytest tests/smoke/test_kis_paper_ai_runtime_smoke.py -v
"""

from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import AccountEntity, InstrumentEntity
from agent_trading.domain.enums import (
    BrokerName,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup
from agent_trading.runtime.bootstrap import build_default_runtime
from agent_trading.services.ai_agents import (
    AIRiskAgent,
    EventInterpretationAgent,
    FinalDecisionComposerAgent,
)
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    DecisionOrchestratorService,
    OrderIntent,
)
from agent_trading.services.order_manager import OrderManager

# =========================================================================
# Constants
# =========================================================================

_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "KIS_API_KEY",
    "KIS_API_SECRET",
    "KIS_ACCOUNT_NUMBER",
)

# =========================================================================
# Skip / fail guards
# =========================================================================


def _credentials_configured() -> bool:
    """Return True only when *all* required KIS env vars are set."""
    return all(bool(os.getenv(v)) for v in _REQUIRED_ENV_VARS)


def _check_paper_env() -> None:
    """Fail immediately if KIS_ENV is not 'paper'."""
    env = os.getenv("KIS_ENV", "paper")
    if env != "paper":
        pytest.fail(
            f"Live KIS environment detected: KIS_ENV={env!r}. "
            f"Smoke tests must run against paper/sandbox only. "
            f"Set KIS_ENV=paper (or unset it) to proceed."
        )


def _have_real_provider_config() -> bool:
    """Check whether the environment has a fully configured LLM provider."""
    s = AppSettings()
    return bool(
        s.llm_provider
        and s.provider_api_key
        and s.provider_base_url
        and s.provider_model_id
    )


_SKIP_REASON = (
    "LLM provider not fully configured — skipping real-agent test. "
    "Set LLM_PROVIDER and the corresponding DEEPSEEK_* or OPENAI_* "
    "environment variables (API key, base URL, model ID)."
)


def _paper_submit_enabled() -> bool:
    """Return True only when all 3 conditions are met for paper submit:

    1. KIS paper credentials fully configured.
    2. KIS_ENV is 'paper' (or unset, which defaults to paper).
    3. Explicit opt-in ``ENABLE_KIS_PAPER_SUBMIT_SMOKE=true``.

    Without opt-in, Scenario C tests only verify pre-submit compatibility
    (no actual broker calls).
    """
    if not _credentials_configured():
        return False

    env = os.getenv("KIS_ENV", "paper")
    if env != "paper":
        return False

    opt_in = os.getenv("ENABLE_KIS_PAPER_SUBMIT_SMOKE", "").lower()
    return opt_in in ("true", "1", "yes")


def _paper_submit_skip_reason() -> str:
    """Return a human-readable explanation of why paper submit is disabled."""
    if not _credentials_configured():
        missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
        return (
            f"KIS paper submit disabled: missing env vars: {', '.join(missing)}. "
            f"Set all {len(_REQUIRED_ENV_VARS)} vars + ENABLE_KIS_PAPER_SUBMIT_SMOKE=true"
        )
    env = os.getenv("KIS_ENV", "paper")
    if env != "paper":
        return (
            f"KIS paper submit disabled: KIS_ENV={env!r} (must be 'paper'). "
            f"Set KIS_ENV=paper + ENABLE_KIS_PAPER_SUBMIT_SMOKE=true"
        )
    return (
        "KIS paper submit disabled: ENABLE_KIS_PAPER_SUBMIT_SMOKE not set to 'true'. "
        "Set ENABLE_KIS_PAPER_SUBMIT_SMOKE=true to enable guarded paper submit"
    )


# =========================================================================
# Shared helpers
# =========================================================================


def _sample_request(
    *,
    quantity: Decimal = Decimal("10"),
    order_type: str = "limit",
    max_slippage_bps: int | None = None,
    account_ref: str = "smoke-test",
) -> SubmitOrderRequest:
    """Return a minimal ``SubmitOrderRequest`` for smoke tests.

    Parameters
    ----------
    quantity : Decimal
        Override quantity (used by B4 for intentional failure).
    order_type : str
        Override order type (used by B4 for market-order validation).
    max_slippage_bps : int | None
        Override max slippage (used by B4 for validation error).
    account_ref : str
        Account reference for the request.
    """
    return SubmitOrderRequest(
        client_order_id=f"smoke-kis-ai-{uuid4()}",
        correlation_id="kis-ai-smoke-001",
        account_ref=account_ref,
        strategy_id="strat-kis-ai-smoke",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=order_type,
        time_in_force=TimeInForce.DAY,
        quantity=quantity,
        price=Decimal("50000"),
        idempotency_key=f"idem-kis-ai-{uuid4()}",
        max_slippage_bps=max_slippage_bps,
    )


# =========================================================================
# Shared repo seeding (Scenario C)
# =========================================================================


async def _seed_repos(repos: RepositoryContainer) -> None:
    """Seed in-memory repos with minimum required data for
    ``OrderManager.create_order()``.

    ``create_order()`` needs:
    - ``AccountEntity`` (resolved via ``account_ref``)
    - ``InstrumentEntity`` (resolved via ``symbol`` + ``market``)

    This is a module-level helper shared by ``TestPreSubmitCompatibility``
    (C1, C2) and ``TestGuardedPaperSubmit`` (C3).
    """
    account_id = uuid4()
    client_id = uuid4()
    instrument_id = uuid4()

    account = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="smoke-test-acc",
        account_masked="****1234",
        status="active",
    )
    instrument = InstrumentEntity(
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="Samsung Electronics",
        is_active=True,
    )

    await repos.accounts.add(account)
    await repos.instruments.add(instrument)


# =========================================================================
# Scenario A — Runtime Wiring Smoke
# =========================================================================


class TestCombinedRuntimeWiring:
    """Verify that ``build_default_runtime()`` returns a fully wired dict
    containing KIS adapter + all AI agent slots.

    All tests are synchronous and require no environment variables.
    """

    def test_runtime_dict_keys(self) -> None:
        """A1: Runtime dict contains all expected keys."""
        runtime = build_default_runtime()
        expected_keys = {
            "settings",
            "primary_broker_adapter",
            "repositories",
            "polling_workers",
            "orchestrator",
            "event_interpretation_agent",
            "ai_risk_agent",
            "final_decision_agent",
        }
        actual = set(runtime.keys())
        assert actual == expected_keys, (
            f"Runtime keys mismatch. "
            f"Extra: {actual - expected_keys}. "
            f"Missing: {expected_keys - actual}"
        )

    def test_kis_adapter_type_and_mode(self) -> None:
        """A2: KIS adapter is ``KoreaInvestmentAdapter`` with paper mode."""
        runtime = build_default_runtime()
        adapter = runtime["primary_broker_adapter"]
        assert isinstance(adapter, KoreaInvestmentAdapter), (
            f"Expected KoreaInvestmentAdapter, got {type(adapter).__name__}"
        )
        assert adapter.broker_name == BrokerName.KOREA_INVESTMENT

        # Verify paper env
        env = os.getenv("KIS_ENV", "paper")
        assert env == "paper", (
            f"KIS_ENV must be 'paper' for smoke tests, got {env!r}"
        )

    def test_agent_types_coexist_with_kis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A3: Without provider credentials, KIS adapter exists but AI
        agent slots are ``None`` (stub fallback)."""
        # Strip all provider env vars
        for var in (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL_ID",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL_ID",
            "LLM_PROVIDER",
        ):
            monkeypatch.delenv(var, raising=False)

        runtime = build_default_runtime()

        # KIS adapter is env-independent
        adapter = runtime["primary_broker_adapter"]
        assert isinstance(adapter, KoreaInvestmentAdapter)

        # All AI agent slots are None (stub fallback)
        assert runtime["event_interpretation_agent"] is None, (
            "Expected None (stub) for event_interpretation_agent "
            "when no provider credential is set"
        )
        assert runtime["ai_risk_agent"] is None, (
            "Expected None (stub) for ai_risk_agent "
            "when no provider credential is set"
        )
        assert runtime["final_decision_agent"] is None, (
            "Expected None (stub) for final_decision_agent "
            "when no provider credential is set"
        )

        # Orchestrator is a valid service regardless
        orchestrator = runtime["orchestrator"]
        assert isinstance(orchestrator, DecisionOrchestratorService)


# =========================================================================
# Scenario B — Assemble Shape Compatibility (강화)
# =========================================================================


class TestAssembleShapeCompatibility:
    """Verify that ``assemble()`` output is KIS-adapter-safe.

    Key assertions:
    1. ``OrderIntent.ai_backend_inputs`` is populated (default or real).
    2. ``SubmitOrderRequest`` contains **zero** AI fields (pure broker input).
    3. The assembled request passes KIS adapter ``_validate_order_request()``.
    4. Missing / invalid fields are handled gracefully (no crash).
    """

    @pytest.mark.asyncio
    async def test_assemble_intent_purity(self) -> None:
        """B1: ``OrderIntent.ai_backend_inputs`` is populated but
        ``SubmitOrderRequest`` is AI-field-free.

        검증 구성 (분리된 assertion 블록):
        ─ [Block 1] SubmitOrderRequest에 **없어야 할** AI 필드
        ─ [Block 2] OrderIntent.ai_backend_inputs에 **있어야 할** AI metadata
        ─ [Block 3] 모든 원본 주문 필드가 보존됨
        """
        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]

        intent = await orchestrator.assemble(_sample_request())

        # ── Block 1: SubmitOrderRequest must NOT have AI fields ──
        ai_field_names_should_not_exist = [
            "ai_backend_inputs",
            "source_agent_names",
            "schema_versions",
            "decision_type",
            "risk_opinion",
            "event_bias",
            "ai_risk_output",
            "event_interpretation_output",
            "composer_output",
            "risk_score",
            "risk_confidence",
            "conviction",
            "confidence",
            "execution_preferences",
            "sizing_hint",
            "event_conflict",
        ]
        for field in ai_field_names_should_not_exist:
            assert not hasattr(intent.request, field), (
                f"SubmitOrderRequest must not contain AI field: {field!r}"
            )

        # ── Block 2: OrderIntent.ai_backend_inputs must have AI metadata ──
        ai = intent.ai_backend_inputs
        assert ai is not None
        assert isinstance(ai, AIDecisionInputs)

        # Core decision fields (FDC-derived)
        assert hasattr(ai, "decision_type")
        assert hasattr(ai, "confidence")
        assert hasattr(ai, "conviction")
        assert hasattr(ai, "reason_codes")
        assert hasattr(ai, "opposing_evidence")

        # Risk fields (AR-derived)
        assert hasattr(ai, "risk_opinion")
        assert hasattr(ai, "risk_score")
        assert hasattr(ai, "risk_confidence")
        assert hasattr(ai, "size_adjustment_factor")
        assert hasattr(ai, "risk_reason_codes")
        assert hasattr(ai, "risk_flags")

        # Event fields (EI-derived)
        assert hasattr(ai, "event_bias")
        assert hasattr(ai, "event_conflict")
        assert hasattr(ai, "event_reason_codes")

        # Metadata fields
        assert hasattr(ai, "source_agent_names")
        assert hasattr(ai, "schema_versions")

        # ── Block 3: All original order fields preserved ──
        req = intent.request
        assert req.client_order_id is not None
        assert req.symbol == "005930"
        assert req.market == "KRX"
        assert req.side == OrderSide.BUY
        assert req.quantity == Decimal("10")
        assert req.price == Decimal("50000")
        assert req.account_ref is not None
        assert req.time_in_force == TimeInForce.DAY
        assert req.idempotency_key is not None

    @pytest.mark.asyncio
    async def test_assemble_request_passes_kis_validation(self) -> None:
        """B2: Assembled ``SubmitOrderRequest`` passes KIS adapter
        ``_validate_order_request()``.

        This verifies shape compatibility at the broker-adapter level:
        no price-band violation, no slippage conflict, no partial-fill
        policy violation.
        """
        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]

        intent = await orchestrator.assemble(_sample_request())
        submit_request = intent.request

        # KIS adapter pre-validation: errors list must be empty
        validation_errors = adapter._validate_order_request(submit_request)
        assert len(validation_errors) == 0, (
            f"SubmitOrderRequest has KIS validation errors: {validation_errors}"
        )

        # All KIS-required fields are non-None
        required_fields = [
            "client_order_id",
            "symbol",
            "market",
            "side",
            "order_type",
            "quantity",
            "account_ref",
            "price",
            "time_in_force",
        ]
        for field in required_fields:
            value = getattr(submit_request, field, None)
            assert value is not None, (
                f"Required field {field!r} is None in SubmitOrderRequest"
            )

    @pytest.mark.smoke
    @pytest.mark.skipif(
        not _have_real_provider_config(),
        reason=_SKIP_REASON,
    )
    @pytest.mark.asyncio
    async def test_real_agent_assemble_shape_with_kis(self) -> None:
        """B3 (conditional): Real provider credential이 설정된 환경에서만 실행.

        세 가지 검증:
        1. ``ai_backend_inputs``에 real agent 데이터 존재 (3 source agents).
        2. ``SubmitOrderRequest``는 여전히 AI 필드가 없음.
        3. KIS adapter validation 통과 + duck-typing attribute 존재.
        """
        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]

        intent = await orchestrator.assemble(_sample_request())
        submit_request = intent.request

        # 1. ai_backend_inputs has real agent data
        ai = intent.ai_backend_inputs
        assert ai.source_agent_names is not None
        assert len(ai.source_agent_names) == 3, (
            f"Expected 3 source agents, got {ai.source_agent_names}"
        )

        # 2. SubmitOrderRequest is still AI-field-free
        assert not hasattr(submit_request, "ai_backend_inputs")

        # 3. KIS adapter validation passes
        validation_errors = adapter._validate_order_request(submit_request)
        assert len(validation_errors) == 0

        # Duck-typing: submit_order() expected attributes exist
        assert hasattr(submit_request, "price_band_lower")
        assert hasattr(submit_request, "price_band_upper")
        assert hasattr(submit_request, "max_slippage_bps")
        assert hasattr(submit_request, "allow_partial_fill")

    @pytest.mark.asyncio
    async def test_assemble_request_missing_fields_handled_gracefully(
        self,
    ) -> None:
        """B4 (robustness): 의도적으로 KIS adapter validation을 실패시키는
        request로 assemble() → validation → submit_order() 경로에서
        crash 없이 ``accepted=False``가 반환되는지 검증.

        Failure case 선택 이유:
        - ``max_slippage_bps=0`` + market order
          → KIS adapter ``_validate_order_request()``에서
            ``"max_slippage_bps must be positive, got 0"`` 오류 발생
          → 이는 **adapter validation failure** (API 호출 전 차단)
          → transport failure(네트워크/타임아웃)와 명확히 구분됨
        - ``quantity=0``은 ``OrderManager.create_order()``에서
          ``ValueError("order quantity must be positive")``로 차단되므로
          여기서는 사용하지 않음
        """
        runtime = build_default_runtime()
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]

        # Market order with max_slippage_bps=0 → adapter validation failure
        bad_request = _sample_request(
            order_type="market",
            max_slippage_bps=0,
        )

        # assemble() handles bad request without crashing
        intent = await orchestrator.assemble(bad_request)

        # _validate_order_request() catches the slippage issue
        # This is an ADAPTER-LEVEL validation failure (not transport failure).
        errors = adapter._validate_order_request(intent.request)
        assert len(errors) > 0, (
            "Expected validation errors for max_slippage_bps=0 market order"
        )
        assert any("max_slippage_bps" in e for e in errors), (
            f"Expected slippage-related error, got: {errors}"
        )

        # submit_order() returns accepted=False WITHOUT making an API call
        # (validation failure is caught before transport).
        result = await adapter.submit_order(intent.request)
        assert result.accepted is False
        assert result.raw_code == "VALIDATION_ERROR"
        assert not result.uncertain
        assert not result.requires_reconciliation


# =========================================================================
# Scenario C1/C2 — Pre-Submit Compatibility (env-independent, always-run)
# =========================================================================


class TestPreSubmitCompatibility:
    """Pre-submit compatibility — **no API calls, no network, no broker
    side-effect**.

    This class verifies that the AI layer + KIS adapter coexistence does
    not break the order creation path.  It runs in **any** environment —
    no KIS credentials required, no opt-in, no ``KIS_ENV`` constraint.

    Why this is safe to run without credentials
    --------------------------------------------
    - ``build_default_runtime()`` creates a ``KISRestClient`` with whatever
      env vars are available (empty strings are valid for a ``@dataclass``).
    - ``adapter._validate_order_request()`` is a **pure Python method** that
      performs local validation — no HTTP calls.
    - ``OrderManager.create_order()`` and ``transition_to()`` operate on
      in-memory repositories — no I/O beyond Python data structures.

    No-submit guarantee
    -------------------
    The ``_no_submit_guard`` fixture permanently monkeypatches
    ``KISRestClient.submit_order`` and ``KoreaInvestmentAdapter.submit_order``
    to call ``pytest.fail()``.  If any code path in C1 or C2 accidentally
    triggers an actual submit, the test fails immediately.
    """

    @pytest.fixture(autouse=True)
    def _no_submit_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Permanently block any attempt to call ``submit_order``.

        Unlike ``_read_only_guard`` (used by C3), this fixture has **no
        opt-in escape hatch** — C1/C2 never submit, in any environment.
        """
        async def _block(*args: object, **kwargs: object) -> None:
            pytest.fail(
                "Submit called during pre-submit compatibility test. "
                "C1/C2 must NEVER call submit_order — this is a pre-submit "
                "compatibility check only, not an actual submit test."
            )

        monkeypatch.setattr(KISRestClient, "submit_order", _block)
        monkeypatch.setattr(KoreaInvestmentAdapter, "submit_order", _block)

    # ------------------------------------------------------------------
    # C1: Pre-submit compatibility safe path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_pre_submit_compatibility_safe_path(self) -> None:
        """C1: Pre-submit path 안전성 검증 (no network, no submit).

        ``assemble()`` → ``create_order()`` → ``transition_to(PENDING_SUBMIT)``
        경로가 KIS credential 없이도 정상 동작하는지 확인.

        **이 테스트는 actual submit을 절대 수행하지 않음:**
        - ``build_default_runtime()`` — KIS credential 없이도 adapter 생성 가능
        - ``orchestrator.assemble()`` — stub AI agent로 동작 (network 없음)
        - ``OrderManager.create_order()`` — in-memory repos만 사용
        - ``adapter._validate_order_request()`` — 순수 Python 메서드 (HTTP 없음)
        - ``_no_submit_guard``가 submit 호출 시 ``pytest.fail()``로 즉시 차단

        검증:
        1. ``assemble()`` 정상 완료 (KIS adapter + AI layer 공존 확인).
        2. ``create_order()`` → DRAFT.
        3. ``transition_to(PENDING_SUBMIT)`` 성공.
        4. Audit trail에 state event 기록됨.
        5. KIS adapter validation 통과.
        """
        runtime = build_default_runtime()
        repos: RepositoryContainer = runtime["repositories"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]

        await _seed_repos(repos)

        request = _sample_request(account_ref="smoke-test-acc")
        intent = await orchestrator.assemble(request)

        manager = OrderManager(repos=repos)
        order = await manager.create_order(intent.request)
        assert order.status == OrderStatus.DRAFT

        # DRAFT → VALIDATED → PENDING_SUBMIT
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        assert order.status == OrderStatus.VALIDATED
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)
        assert order.status == OrderStatus.PENDING_SUBMIT

        events = await repos.order_state_events.list_by_order_request(
            order.order_request_id
        )
        assert len(events) >= 2, "Expected at least two state events (DRAFT→VALIDATED→PENDING_SUBMIT)"
        assert events[-1].new_status == OrderStatus.PENDING_SUBMIT

        errors = adapter._validate_order_request(intent.request)
        assert len(errors) == 0, (
            f"SubmitOrderRequest has KIS validation errors: {errors}"
        )

    # ------------------------------------------------------------------
    # C2: Pre-submit request shape integrity
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_pre_submit_request_shape_integrity(self) -> None:
        """C2: SubmitOrderRequest shape integrity (no network, no submit).

        PENDING_SUBMIT 상태의 order와 ``intent.request``가 KIS adapter
        submit path와 shape 충돌 없음을 검증.

        **이 테스트는 actual submit을 절대 수행하지 않음:**
        - ``build_default_runtime()`` — KIS credential 없이도 동작
        - 모든 검증은 pure Python assertion + ``_validate_order_request()``
        - ``_no_submit_guard``가 submit 시도 시 ``pytest.fail()``로 차단

        검증:
        1. ``SubmitOrderRequest`` 모든 필드 접근 가능.
        2. Extended fields (price_band, slippage, partial fill)가
           ``None``/기본값일 때도 KIS adapter validation 통과.
        3. ``_no_submit_guard``가 submit 호출을 영구 차단.
        """
        runtime = build_default_runtime()
        repos: RepositoryContainer = runtime["repositories"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]

        await _seed_repos(repos)

        intent = await orchestrator.assemble(
            _sample_request(account_ref="smoke-test-acc")
        )
        manager = OrderManager(repos=repos)
        order = await manager.create_order(intent.request)
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        req = intent.request

        # Core fields
        assert req.client_order_id is not None
        assert req.symbol == "005930"
        assert req.side == OrderSide.BUY
        assert req.quantity == Decimal("10")

        # Extended fields may be None — KIS adapter handles gracefully
        _ = req.price_band_lower       # None is valid
        _ = req.price_band_upper       # None is valid
        _ = req.max_slippage_bps       # None is valid
        _ = req.allow_partial_fill     # True is default

        errors = adapter._validate_order_request(req)
        assert len(errors) == 0, (
            f"Shape integrity failed: validation errors: {errors}"
        )


# =========================================================================
# Scenario C3 — Guarded Actual Paper Submit (opt-in only)
# =========================================================================


class TestGuardedPaperSubmit:
    """Guarded actual paper submit — requires opt-in.

    Read-only guard behavior
    -------------------------
    By default (opt-in=false), the ``_read_only_guard`` blocks all write
    operations on ``KISRestClient`` and ``KoreaInvestmentAdapter``.

    When ``ENABLE_KIS_PAPER_SUBMIT_SMOKE=true`` AND all safety conditions
    are met, submit_order is NOT blocked (guarded actual submit).
    """

    @pytest.fixture(autouse=True)
    def _read_only_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Block write operations on KISRestClient and KoreaInvestmentAdapter.

        When ``_paper_submit_enabled()`` returns True (all 3 safety
        conditions met), submit_order is NOT blocked — allowing guarded
        actual paper submit.

        Otherwise, all write operations are blocked and any attempt to
        call them will raise ``pytest.fail()``.

        Note
        ----
        ``KISRestClient`` only has ``submit_order`` and ``cancel_order``
        (no ``amend_order``).  ``KoreaInvestmentAdapter`` has all three.
        Each class is patched only for methods it actually defines.
        """
        if _paper_submit_enabled():
            return  # Allow guarded actual submit

        async def _block(*args: object, **kwargs: object) -> None:
            pytest.fail(
                "Read-only violation: submit_order/cancel_order/amend_order "
                "called during smoke test. "
                "Set ENABLE_KIS_PAPER_SUBMIT_SMOKE=true to enable guarded "
                "paper submit."
            )

        # KISRestClient: submit_order, cancel_order (no amend_order)
        for op in ("submit_order", "cancel_order"):
            monkeypatch.setattr(KISRestClient, op, _block)
        # KoreaInvestmentAdapter: submit_order, cancel_order, amend_order
        for op in ("submit_order", "cancel_order", "amend_order"):
            monkeypatch.setattr(KoreaInvestmentAdapter, op, _block)

    # ------------------------------------------------------------------
    # C3: Guarded actual paper submit (opt-in only)
    # ------------------------------------------------------------------

    @pytest.mark.skipif(
        not _paper_submit_enabled(),
        reason=_paper_submit_skip_reason(),
    )
    @pytest.mark.asyncio
    async def test_guarded_paper_submit_with_read_only_guard(self) -> None:
        """C3 (opt-in only): Guarded actual paper submit via real KIS adapter.

        실행 조건 (모두 만족 필요):
        1. KIS paper credential 완료 (KIS_API_KEY, KIS_API_SECRET, KIS_ACCOUNT_NUMBER).
        2. KIS_ENV=paper (또는 미설정, 기본값 paper).
        3. ``ENABLE_KIS_PAPER_SUBMIT_SMOKE=true``.

        이 테스트는 실제 KIS paper API를 호출하여 submit path를 검증.
        ``_read_only_guard``가 opt-in 시에는 submit_order를 차단하지 않음.

        모든 broker outcome (SUBMITTED / RECONCILE_REQUIRED / REJECTED) 을 허용
        — paper env 응답에 따라 달라질 수 있음.
        """
        runtime = build_default_runtime()
        repos: RepositoryContainer = runtime["repositories"]
        adapter: KoreaInvestmentAdapter = runtime["primary_broker_adapter"]
        orchestrator: DecisionOrchestratorService = runtime["orchestrator"]

        await _seed_repos(repos)

        request = _sample_request(account_ref="smoke-test-acc")
        intent = await orchestrator.assemble(request)

        manager = OrderManager(repos=repos)
        order = await manager.create_order(intent.request)
        # DRAFT → VALIDATED → PENDING_SUBMIT
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        order = await manager.submit_order_to_broker(
            order,
            adapter,
            intent.request,
        )

        assert order.status in (
            OrderStatus.SUBMITTED,
            OrderStatus.RECONCILE_REQUIRED,
            OrderStatus.REJECTED,
        ), (
            f"Unexpected order status after submit: {order.status}"
        )
