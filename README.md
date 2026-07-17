# vsl-core

The framework-agnostic and model-agnostic foundation of **VSL** (VERBA Specification Language) — a governance vocabulary for deciding whether an automated system's next action is allowed to happen, and proving that decision was made.

Zero third-party runtime dependencies. MIT licensed.

## What this is — and isn't

**Is:**
- The agnostic template: `Invariant`, `PreNode`, `TerminalState`, `Cluster`, the hash-chained `VerbaLedger`, plus a Drift Class / Stabilisation Operator catalog.
- A conformance contract (`vsl_core.conformance`) so a third party can build an adapter for a framework this package has never heard of, and know mechanically whether they built it correctly.

**Is not:**
- A framework adapter. This package ships no OpenAI Agents SDK, LangGraph, or LangChain integration. Those live in separate `vsl-<framework>` packages, out of scope here.
- A model integration of any kind. It never imports `openai`, `anthropic`, or any other model-provider SDK.
- A finished, validated detection system. See the catalog section below — most of what it contains is explicitly unvalidated.

If you're building an adapter for a specific framework, see [Building an adapter](#building-an-adapter).

## The F1/F2 assurance distinction (read this before trusting any Assurance Level)

Every claim this package (or anything built on it) makes about how trustworthy a governance mechanism is reduces to one test:

- **F1 (pre-commitment)** — does the check run *before* the system commits to an action, with no side effect yet fired?
- **F2 (energy-landscape modification)** — does the intervention actually touch the mechanism that produces the output (logits, weights, activations), or does it only touch the prompt or sampling parameters?

A mechanism satisfying F1 but only *partial* F2 caps at **MEDIUM** assurance, never HIGH. Concretely: a `PreNode` blocking a call to a hosted LLM API satisfies F1 (it runs before the call), but can only rewrite the prompt or adjust sampling parameters — it cannot touch logits or weights behind an API. That caps it at MEDIUM. Nothing in this package, in any README, or in any client-facing material built on it should blur this distinction.

**This is structurally enforced, not just a convention.** `AllowedState.assurance_level`/`PreNode.assurance_level` are *derived*, read-only properties — you can't set them directly. What you provide instead is an `AssuranceBasis`: the F1 (bool) and F2 (`F2Modification`: `FULL`/`PARTIAL`/`INDIRECT`/`NONE`) facts themselves. `AssuranceBasis.derived_level` computes the level from those facts, so a `PreNode` claiming HIGH has to actually state "yes F1, and F2 is FULL" — it can't just default into HIGH:

```python
from vsl_core.metrics import AssuranceBasis, F2Modification

# A hosted-LLM-API guardrail: runs before the call (F1=True), but can only
# touch the prompt, not logits/weights behind the API (F2=PARTIAL).
basis = AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.PARTIAL)
basis.derived_level  # AssuranceLevel.MEDIUM -- not HIGH, even if you wanted it to be
```

The full derivation table (`F1=False` always → LOW regardless of F2; `F1=True`+`FULL` → HIGH; `F1=True`+`PARTIAL`/`INDIRECT` → MEDIUM; `F1=True`+`NONE` → LOW) is implemented and tested exhaustively in `vsl_core.metrics`. The last row (F1 satisfied, but zero claimed energy-landscape effect) isn't in the source paper's table — it's a deliberate interpretive extension, documented as such in the code, not a spec fact.

This is a distinct axis from **model-agnostic vs. model-specific** and **framework-agnostic vs. framework-specific** — see the module docstrings in `constructs.py` and `ledger.py` for why conflating those two axes was a real mistake worth avoiding structurally, not just documenting.

## VSL construct → vsl_core object

| VSL construct | vsl_core object |
|---|---|
| Signal / Tendency / Constraint | not separately modeled — expressed through `PreNode`/`Invariant` |
| State / Allowed State | `vsl_core.constructs.AllowedState` |
| Inadmissible State / Drift Node | `vsl_core.constructs.InadmissibleState` |
| Pre-Node | `vsl_core.constructs.PreNode` |
| Invariant | `vsl_core.constructs.Invariant` (optional `on_violation: TerminalState` names which Terminal State a violation enters) |
| Terminal State | `vsl_core.constructs.TerminalState` |
| Cluster | `vsl_core.cluster.Cluster` |
| Fallback | `vsl_core.constructs.Fallback` |
| Identity Key / Cluster Key | `vsl_core.identity.IdentityKey` / `ClusterKey` |
| Instance / Re-Enablement | `vsl_core.identity.Instance` (`.new()` / `.re_enable()`) |
| Automation-Denied | `vsl_core.exceptions.AutomationDeniedException` |
| Human-Authorised Transition | `vsl_core.governance.HumanAuthorisedTransition` / `request_re_enablement()` |
| Governance Authority | `vsl_core.governance.GovernanceAuthority` |
| VERBA Ledger | `vsl_core.ledger.VerbaLedger` |
| VERBA Certificate | `vsl_core.ledger.VerbaCertificate` |
| Delta / Gamma / GES / EEF | `vsl_core.metrics.Delta` / `GammaEstimate` / `GES` / `EEF` |
| Beta (inverse temperature) | `vsl_core.metrics.Beta` |
| Threshold | `vsl_core.metrics.Threshold` + `GAMMA_MONITORING_THRESHOLD` / `JACOBIAN_RED_FLAG_THRESHOLD` / `KL_MONITORING_THRESHOLD` |
| Policy-as-Code | `vsl_core.governance.Specification` |
| Proofing | `vsl_core.governance.Proofing` |
| Binding | `vsl_core.governance.Binding` |
| Drift | not its own type — see [the Drift payload-key note](#drift-has-no-dedicated-type-by-design) below |
| Node / Drift Node / Tendency | not modeled as vsl-core types — see [the scoping note](#node-drift-node-and-tendency-are-deliberately-out-of-scope) below |

**Ledger entry-type count note**: the source spec's prose describes "six entry types" but then enumerates seven (`MONITOR`, `PRE_NODE`, `VERIFICATION`, `TERMINAL`, `SPECIFICATION_UPDATE`, `HUMAN_AUTHORISED_TRANSITION`, `RE_ENABLEMENT`). This is a stale count in the source document itself. All seven are implemented in `vsl_core.ledger.LedgerEntryType`; the count discrepancy is intentionally not silently resolved.

**Beta note**: the source spec describes Beta only qualitatively (higher Beta → lower volatility → stronger concentration on energy minima; systems tuned at normal Beta may fail at crisis Beta) — it gives no closed-form formula relating Beta to Delta or Gamma. `Beta` is a bare value holder for exactly this reason: naming and logging the quantity without fabricating a computation the source paper doesn't provide.

**Threshold note**: only Gamma's default threshold (1.1) was previously represented anywhere in this package. The spec also names a Jacobian "red flag" (`lambda_min(J_gov) < 0.05`) and a default KL monitoring threshold (0.15 nats) — both are now reference constants too, so a `DriftMonitor` implementer has the spec's own defaults available instead of re-deriving or mistyping them. Jacobian/KL computation itself stays out of core, same as Gamma estimation — these are just named numbers.

### Drift has no dedicated type, by design

`VerbaLedger.audit()`'s checks read two payload keys: `DRIFT_DETECTED_KEY` (`"drift_detected"`, a `MONITOR` entry's payload) and `VERIFICATION_RESULT_KEY` (`"result"`, a `VERIFICATION` entry's payload, compared against `VerificationResult.INSUFFICIENT`). These are exported constants, not magic strings you need to remember — use `VerbaLedger.write_monitor(identity_key=..., drift_detected=...)` and `VerbaLedger.write_verification(identity_key=..., result=VerificationResult.INSUFFICIENT)` instead of hand-building the payload dict, and the audit checks can never silently miss a differently-spelled key.

### Node, Drift Node, and Tendency are deliberately out of scope

The source spec's Layer 0/1 vocabulary includes `Node` (a stabilised, repeatable pattern of behaviour, classified as an Allowed Node or Drift Node) and `Tendency` (a directional bias detected via KL-divergence comparison, before any output is generated). vsl-core does not model either as its own type. This is a deliberate scoping decision, not an oversight: Node classification is an *inference* concern — it requires observing a real system's behaviour over time and classifying the pattern that emerges — which belongs to analysis tooling built on top of vsl-core, not to something a spec author instantiates directly the way they instantiate a `PreNode` or `Invariant`. vsl-core models the State layer (`AllowedState`/`InadmissibleState`) and the Gamma-based sufficiency judgment (`GammaEstimate.sufficient()`) that a Tendency's KL comparison would ultimately feed into, and stops there.

### Re-Enablement: the one sanctioned path out of a Terminal State

`Instance.re_enable()` is a mechanism, not a policy gate — it's directly callable with just an `Evidence` object and has no concept of a `GovernanceAuthority`. The sanctioned, audited path is `governance.request_re_enablement()`, which pairs the new `Instance` with the `HumanAuthorisedTransition` record that authorises it, so you can't get one without the other:

```python
from vsl_core.identity import Instance, Evidence
from vsl_core.governance import GovernanceAuthority, request_re_enablement

terminated_instance = Instance.new()
authority = GovernanceAuthority(name="safety-board", escalation_contact="oncall@example.com")
evidence = Evidence(
    root_cause_analysis="alarm software infinite loop",
    specification_update_proposal="add heartbeat invariant",
)

new_instance, transition = request_re_enablement(
    terminated_instance,
    authority,
    authorised_by="jane.doe",
    evidence=evidence,
)
# new_instance -> write a RE_ENABLEMENT ledger entry
# transition   -> write a HUMAN_AUTHORISED_TRANSITION ledger entry
```

Like `AutomationDeniedException`'s "cannot be silently caught," this is a convention, not a language-enforced guarantee: nothing stops a caller from calling `Instance.re_enable()` directly and skipping the authority/evidence trail. Adapters and client code that need the audited path should always go through `request_re_enablement()`.

## The Drift Class / Stabilisation Operator catalog (`vsl_core.catalog`)

Loads two real data files (Paper 5, "Toward a Basis Representation of Drift Forensics"): 45 Drift Classes across five categories (external, internal, systemic, linguistic, authority) tagged by evidence tier (A = well evidenced, B = theoretically grounded, C = hypothesised, D = a limit class possibly unfixable by any operator), and 10 Stabilisation Operators.

**This catalog is explicitly not a finished, validated detection system.** Of the 113 Legion detection heuristics in `legion_patterns.json`, **106 (94%) are self-labeled `SPECULATIVE`**, with the stated caveat that "no verified detection signature exists yet — treat matches as a prompt for manual review, not a confirmed finding." Only **7 heuristics carry real confidence** (4 HIGH, 3 MEDIUM), concentrated in `DC-E13` (3), `DC-I11` (2), and the orphan `CLUSTER-HANDOVER` entry (2). Call `catalog.loader.only_validated_heuristics()` if you want only those seven — do not treat the other 106 as ready to act on automatically.

Known data-quality findings, surfaced by `catalog.loader.validate()` and never silently fixed:

1. `drift_classes.json`'s own `metadata.total_drift_classes` claims **36**; the real, computed count across all five categories is **45** (external=15, internal=19, systemic=7, linguistic=3, authority=1). Do not trust the metadata field.
2. `legion_patterns.json` contains a `CLUSTER-HANDOVER` entry with no corresponding Drift Class anywhere in `drift_classes.json`.
3. **10 Drift Classes have zero Legion detection heuristics at all** (`legions: {}`): `DC-S1, DC-S2, DC-S3, DC-S4, DC-S5, DC-S6, DC-L1, DC-L2, DC-L3, DC-A1` — all of the systemic and linguistic tiers, plus the sole authority-tier class. This is a coverage gap (mostly tier B/C/D theoretical/limit classes with no heuristic proposed yet), not a data error, and is worded accordingly in `validate()`'s output.

## Building an adapter

A framework adapter must implement `vsl_core.conformance.protocol.VSLAdapter` (`compile_pre_node`, `compile_invariant`) and pass `vsl_core.conformance.suite.run_conformance_suite(your_adapter)` with an empty result before calling itself VSL-conformant. The suite mechanically proves — using a real `PreNode`/`Invariant` and a mutable side-effect counter, not just return-value checks — that your compiled gates:

1. Block before any side effect when a `PreNode`'s Gamma estimate is insufficient (the F1 property, checked mechanically).
2. Pass through normally when Gamma is sufficient.
3. Raise `InvariantViolation` specifically (not a bare `AutomationDeniedException`) when an `Invariant` fails.
4. Don't raise when an `Invariant` holds.
5. Are safely reusable — no state leaks between calls on the same compiled gate.

`vsl_core.conformance.reference_adapter.PlainPythonReferenceAdapter` is the minimal reference implementation — proof the contract is satisfiable at all, not merely specified on paper.

## Install

```
pip install git+https://github.com/4vish/VSL-Core.git
```

For local development:

```
git clone https://github.com/4vish/VSL-Core.git
cd VSL-Core
pip install -e .
```

Not yet on PyPI — installing from GitHub is the current path.

## Package layout

```
src/vsl_core/
├── exceptions.py       exception hierarchy
├── metrics.py          Delta, Gamma, GES, EEF, Beta, Threshold, AssuranceBasis
├── identity.py         IdentityKey, ClusterKey, Instance, Evidence
├── ledger.py           VerbaLedger, hash-chained LedgerEntry, audit checks
├── constructs.py       AllowedState, PreNode, Invariant, TerminalState
├── cluster.py          Cluster, ClusterPreNode
├── governance.py       GovernanceAuthority, HumanAuthorisedTransition, Proofing, Binding, Specification
├── catalog/            Drift Class / Stabilisation Operator / Legion data + loader
└── conformance/        VSLAdapter protocol, run_conformance_suite, reference adapter
```

## Verifying the zero-dependency / framework-agnostic guarantee

```
grep -rn "^from agents\|^import agents\|^from langgraph\|^import langgraph\|^from langchain\|^import langchain\|^from openai\|^import openai\|^from anthropic\|^import anthropic\|RunContextWrapper\|InputGuardrail\|GuardrailFunctionOutput" src/vsl_core/
```

should return nothing. A fresh virtual environment containing only `vsl-core` and `pytest` should install and pass the full test suite with no other packages pulled in.

## What a VerbaCertificate does *not* claim

`VerbaLedger.issue_certificate()` only returns a certificate if all five audit checks pass, and even then: **it does not guarantee no Inadmissible State was ever reached.** It certifies that every *detected* Drift event was addressed, Terminal States were properly escalated, and governance was continuously monitored — it certifies the governance *process*, not the underlying system, model, or domain. This disclaimer is embedded in `VerbaCertificate.NOTE` and surfaced in its `__str__`, not just documented here.

## License

MIT — see [LICENSE](LICENSE). Copyright Super Semantics.
