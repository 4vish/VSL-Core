"""The VSLAdapter/CompiledGate contract every framework adapter must
satisfy.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..constructs import Invariant, PreNode


class CompiledGate(Protocol):
    """A compiled, callable gate for a single PreNode or Invariant.

    Must raise vsl_core.exceptions.AutomationDeniedException (or the more
    specific InvariantViolation) if the check fails. Must return/complete
    normally if it passes. MUST complete (raise or return) strictly before
    any side effect the gate guards is allowed to occur -- this is the F1
    pre-commitment property from the source spec, and it is the one
    property run_conformance_suite exists to verify mechanically, not just
    document.
    """

    async def __call__(self, candidate_input: Any) -> None: ...


class VSLAdapter(Protocol):
    """What a framework adapter must implement to be VSL-conformant."""

    def compile_pre_node(self, pre_node: PreNode) -> CompiledGate: ...

    def compile_invariant(self, invariant: Invariant) -> CompiledGate: ...
