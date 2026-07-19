"""PlainPythonReferenceAdapter: the simplest possible conformant adapter --
"Plain Python: direct call," with no framework underneath it at all.

This is real, tested code, not a label: run_conformance_suite must return
[] for it, proving the conformance contract is satisfiable, not merely
specified on paper.
"""

from __future__ import annotations

from typing import Any

from ..constructs import Invariant, PreNode
from ..exceptions import AutomationDeniedException, InvariantViolation
from .protocol import CompiledGate


class PlainPythonReferenceAdapter:
    def compile_pre_node(self, pre_node: PreNode) -> CompiledGate:
        async def gate(candidate_input: Any) -> None:
            estimate = await pre_node.monitor(candidate_input)
            if not estimate.sufficient(pre_node.gamma_threshold):
                raise AutomationDeniedException(
                    reason=f"Pre-node '{pre_node.name}' insufficient Gamma",
                    identity_key="conformance-test",
                )

        return gate

    def compile_invariant(self, invariant: Invariant) -> CompiledGate:
        async def gate(candidate_input: Any) -> None:
            holds = await invariant.rule(candidate_input)
            if not holds:
                reason = f"Invariant '{invariant.name}' violated"
                terminal_state_name = invariant.on_violation.name if invariant.on_violation is not None else None
                if terminal_state_name is not None:
                    reason += f" -- entering terminal state '{terminal_state_name}'"
                raise InvariantViolation(
                    reason=reason,
                    identity_key="conformance-test",
                    invariant_name=invariant.name,
                    terminal_state_name=terminal_state_name,
                )

        return gate
