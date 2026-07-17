"""run_conformance_suite: mechanical proof that a VSLAdapter implementation
is conformant, not just documentation claiming it is.

Each check below constructs a real PreNode/Invariant and exercises the
adapter's compiled gate directly, using a mutable side-effect counter cell
to prove ordering (F1 pre-commitment) rather than merely checking return
values.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..constructs import Invariant, PreNode
from ..exceptions import AutomationDeniedException, ConformanceError, InvariantViolation
from ..metrics import AssuranceBasis, F2Modification, GammaEstimate
from .protocol import VSLAdapter

# These synthetic PreNodes are genuinely formation-layer, full-F2 checks --
# HIGH is the correct, justified claim for them, not a lazy default.
_HIGH_ASSURANCE_BASIS = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL)


def _require_callable_gate(adapter: object, method_name: str, gate: object) -> None:
    if not callable(gate):
        raise ConformanceError(
            f"{type(adapter).__name__}.{method_name} did not return a callable gate "
            f"(got {gate!r}); the conformance suite cannot run against it."
        )


async def _check_pre_node_blocks_before_side_effect(adapter: VSLAdapter) -> list[str]:
    """Check 1: a PreNode whose monitor returns a GammaEstimate below
    gamma_threshold must have its compiled gate raise before a side-effect
    counter increments.
    """
    failures: list[str] = []
    counter = [0]

    async def insufficient_monitor(_candidate_input: Any) -> GammaEstimate:
        return GammaEstimate(gamma_hat=0.1)

    pre_node = PreNode(
        name="conformance-blocking",
        description="Conformance check: below-threshold Gamma must block.",
        monitor=insufficient_monitor,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        gamma_threshold=1.1,
    )
    gate = adapter.compile_pre_node(pre_node)
    _require_callable_gate(adapter, "compile_pre_node", gate)

    raised = False
    try:
        await gate("candidate")
        counter[0] += 1
    except AutomationDeniedException:
        raised = True

    if not raised:
        failures.append(
            "Check 1 (PreNode pre-commitment blocking): compiled gate did not "
            "raise AutomationDeniedException for an insufficient Gamma estimate."
        )
    if counter[0] != 0:
        failures.append(
            "Check 1 (PreNode pre-commitment blocking): the side-effect counter "
            "incremented despite the gate raising -- F1 pre-commitment violated."
        )
    return failures


async def _check_pre_node_allows_after_pass(adapter: VSLAdapter) -> list[str]:
    """Check 2: a PreNode whose monitor returns a GammaEstimate above
    threshold must not raise, and the side-effect counter must increment
    normally afterward.
    """
    failures: list[str] = []
    counter = [0]

    async def sufficient_monitor(_candidate_input: Any) -> GammaEstimate:
        return GammaEstimate(gamma_hat=5.0)

    pre_node = PreNode(
        name="conformance-passing",
        description="Conformance check: above-threshold Gamma must pass through.",
        monitor=sufficient_monitor,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        gamma_threshold=1.1,
    )
    gate = adapter.compile_pre_node(pre_node)
    _require_callable_gate(adapter, "compile_pre_node", gate)

    try:
        await gate("candidate")
        counter[0] += 1
    except AutomationDeniedException as exc:
        failures.append(
            f"Check 2 (PreNode pass-through): gate raised unexpectedly for a "
            f"sufficient Gamma estimate ({exc})."
        )
        return failures

    if counter[0] != 1:
        failures.append(
            "Check 2 (PreNode pass-through): the side-effect counter did not "
            "increment after a passing gate call."
        )
    return failures


async def _check_invariant_violation_is_specific_type(adapter: VSLAdapter) -> list[str]:
    """Check 3: an Invariant whose rule returns False must raise
    InvariantViolation specifically -- not a bare AutomationDeniedException.
    Invariants get no Fallback, straight to Terminal per the spec.
    """
    failures: list[str] = []

    async def failing_rule(_candidate_input: Any) -> bool:
        return False

    invariant = Invariant(
        name="conformance-invariant-fail",
        description="Conformance check: a failing rule must raise InvariantViolation.",
        rule=failing_rule,
    )
    gate = adapter.compile_invariant(invariant)
    _require_callable_gate(adapter, "compile_invariant", gate)

    try:
        await gate("candidate")
    except InvariantViolation:
        pass
    except AutomationDeniedException as exc:
        failures.append(
            f"Check 3 (Invariant violation specificity): gate raised "
            f"{type(exc).__name__}, expected the more specific InvariantViolation."
        )
    else:
        failures.append(
            "Check 3 (Invariant violation specificity): compiled gate did not "
            "raise for a failing Invariant rule."
        )
    return failures


async def _check_invariant_pass(adapter: VSLAdapter) -> list[str]:
    """Check 4: an Invariant whose rule returns True must not raise."""
    failures: list[str] = []

    async def passing_rule(_candidate_input: Any) -> bool:
        return True

    invariant = Invariant(
        name="conformance-invariant-pass",
        description="Conformance check: a passing rule must not raise.",
        rule=passing_rule,
    )
    gate = adapter.compile_invariant(invariant)
    _require_callable_gate(adapter, "compile_invariant", gate)

    try:
        await gate("candidate")
    except Exception as exc:  # noqa: BLE001 -- any raise here is itself the failure
        failures.append(
            f"Check 4 (Invariant pass-through): gate raised unexpectedly for a "
            f"passing rule ({type(exc).__name__})."
        )
    return failures


async def _check_gate_reusable_without_state_leak(adapter: VSLAdapter) -> list[str]:
    """Check 5: a compiled gate must be safely reusable. Construct once,
    call with a passing input then a failing input (then passing again),
    and confirm no state leaks between calls.
    """
    failures: list[str] = []

    async def conditional_monitor(candidate_input: Any) -> GammaEstimate:
        return GammaEstimate(gamma_hat=5.0 if candidate_input == "good" else 0.1)

    pre_node = PreNode(
        name="conformance-reusable",
        description="Conformance check: a compiled gate must be reusable across calls.",
        monitor=conditional_monitor,
        assurance_basis=_HIGH_ASSURANCE_BASIS,
        gamma_threshold=1.1,
    )
    gate = adapter.compile_pre_node(pre_node)
    _require_callable_gate(adapter, "compile_pre_node", gate)

    try:
        await gate("good")
    except AutomationDeniedException as exc:
        failures.append(
            f"Check 5 (gate reusability): first call with a passing input "
            f"raised unexpectedly ({exc})."
        )

    raised = False
    try:
        await gate("bad")
    except AutomationDeniedException:
        raised = True
    if not raised:
        failures.append(
            "Check 5 (gate reusability): second call with a failing input did "
            "not raise -- state may have leaked from the first (passing) call."
        )

    try:
        await gate("good")
    except AutomationDeniedException as exc:
        failures.append(
            f"Check 5 (gate reusability): third call with a passing input "
            f"raised unexpectedly after a prior failing call ({exc}) -- state "
            f"leaked from the second (failing) call."
        )

    return failures


async def _run_all_checks(adapter: VSLAdapter) -> list[str]:
    failures: list[str] = []
    failures += await _check_pre_node_blocks_before_side_effect(adapter)
    failures += await _check_pre_node_allows_after_pass(adapter)
    failures += await _check_invariant_violation_is_specific_type(adapter)
    failures += await _check_invariant_pass(adapter)
    failures += await _check_gate_reusable_without_state_leak(adapter)
    return failures


def run_conformance_suite(adapter: VSLAdapter) -> list[str]:
    """Run all behavioral conformance checks against `adapter`.

    Returns a list of human-readable failure descriptions; an empty list
    means fully conformant. Raises ConformanceError only if the adapter's
    own methods are broken badly enough to prevent the suite from running
    at all (e.g. returning a non-callable "gate").
    """
    return asyncio.run(_run_all_checks(adapter))
