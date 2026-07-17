import asyncio

import pytest

from vsl_core.conformance.protocol import CompiledGate, VSLAdapter
from vsl_core.conformance.reference_adapter import PlainPythonReferenceAdapter
from vsl_core.conformance.suite import run_conformance_suite
from vsl_core.constructs import Invariant, PreNode, TerminalState
from vsl_core.exceptions import AutomationDeniedException, ConformanceError, InvariantViolation
from vsl_core.metrics import AssuranceBasis, F2Modification, GammaEstimate

_HIGH_ASSURANCE_BASIS = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)


def test_reference_adapter_passes_full_conformance_suite():
    failures = run_conformance_suite(PlainPythonReferenceAdapter())
    assert failures == []


def test_reference_adapter_pre_node_blocks_before_side_effect_mechanically():
    # Lower-level test, not through the suite: construct a PreNode with a
    # below-threshold monitor, compile it directly, and prove F1
    # pre-commitment via a side-effect counter that would only increment
    # after a *successful* gate call.
    counter = [0]

    async def insufficient_monitor(_candidate_input):
        return GammaEstimate(gamma_hat=0.1)

    pre_node = PreNode(
        name="test-blocking",
        description="d",
        monitor=insufficient_monitor,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        gamma_threshold=1.1,
    )
    adapter = PlainPythonReferenceAdapter()
    gate = adapter.compile_pre_node(pre_node)

    async def run():
        try:
            await gate("candidate")
            counter[0] += 1
        except AutomationDeniedException:
            pass

    asyncio.run(run())
    assert counter[0] == 0


def test_reference_adapter_invariant_violation_is_specific_type():
    async def failing_rule(_candidate_input):
        return False

    invariant = Invariant(name="test-invariant", description="d", rule=failing_rule)
    adapter = PlainPythonReferenceAdapter()
    gate = adapter.compile_invariant(invariant)

    async def run():
        with pytest.raises(InvariantViolation):
            await gate("candidate")

    asyncio.run(run())


def test_reference_adapter_gate_reusable_no_state_leak():
    async def conditional_monitor(candidate_input):
        return GammaEstimate(gamma_hat=5.0 if candidate_input == "good" else 0.1)

    pre_node = PreNode(
        name="test-reusable",
        description="d",
        monitor=conditional_monitor,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        gamma_threshold=1.1,
    )
    adapter = PlainPythonReferenceAdapter()
    gate = adapter.compile_pre_node(pre_node)

    async def run():
        await gate("good")  # should not raise
        with pytest.raises(AutomationDeniedException):
            await gate("bad")
        await gate("good")  # should not raise again -- no leaked state

    asyncio.run(run())


def test_conformance_error_on_adapter_returning_non_callable_gate():
    class BrokenAdapter:
        def compile_pre_node(self, pre_node):
            return None

        def compile_invariant(self, invariant):
            return None

    with pytest.raises(ConformanceError):
        run_conformance_suite(BrokenAdapter())


def test_suite_catches_an_adapter_that_never_raises():
    class AlwaysPassAdapter:
        def compile_pre_node(self, pre_node):
            async def gate(candidate_input):
                return None

            return gate

        def compile_invariant(self, invariant):
            async def gate(candidate_input):
                return None

            return gate

    failures = run_conformance_suite(AlwaysPassAdapter())
    assert failures  # must report at least the blocking-check and invariant-violation-check failures
    assert any("Check 1" in f for f in failures)
    assert any("Check 3" in f for f in failures)


def test_reference_adapter_invariant_reason_includes_terminal_state_when_set():
    async def failing_rule(_candidate_input):
        return False

    terminal = TerminalState(name="governance_failure_terminal", description="d")
    invariant = Invariant(name="test-invariant-linked", description="d", rule=failing_rule, on_violation=terminal)
    adapter = PlainPythonReferenceAdapter()
    gate = adapter.compile_invariant(invariant)

    async def run():
        with pytest.raises(InvariantViolation) as excinfo:
            await gate("candidate")
        assert "governance_failure_terminal" in str(excinfo.value)

    asyncio.run(run())


def test_reference_adapter_invariant_reason_unchanged_when_on_violation_unset():
    async def failing_rule(_candidate_input):
        return False

    invariant = Invariant(name="test-invariant-unlinked", description="d", rule=failing_rule)
    adapter = PlainPythonReferenceAdapter()
    gate = adapter.compile_invariant(invariant)

    async def run():
        with pytest.raises(InvariantViolation) as excinfo:
            await gate("candidate")
        assert "entering terminal state" not in str(excinfo.value)

    asyncio.run(run())


def test_suite_catches_an_adapter_that_always_raises():
    class AlwaysDenyAdapter:
        def compile_pre_node(self, pre_node):
            async def gate(candidate_input):
                raise AutomationDeniedException(reason="always deny", identity_key="x")

            return gate

        def compile_invariant(self, invariant):
            async def gate(candidate_input):
                raise AutomationDeniedException(reason="always deny", identity_key="x")

            return gate

    failures = run_conformance_suite(AlwaysDenyAdapter())
    assert failures
    # Check 2 (pass-through) and Check 4 (invariant pass) should fail.
    assert any("Check 2" in f for f in failures)
    assert any("Check 4" in f for f in failures)
    # Check 3 should also fail: raising AutomationDeniedException instead
    # of the more specific InvariantViolation.
    assert any("Check 3" in f for f in failures)
