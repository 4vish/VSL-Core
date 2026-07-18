# vsl-core and Governance Requirements: How We Try to Address Them

## What this document is, and what it deliberately is not

**vsl-core does not establish compliance.** It provides structural primitives through which a developer may attempt to implement parts of a governance process — subject, always, to deployment-specific assessment by an auditor or compliance professional looking at a real system. This document does **not** claim that vsl-core satisfies, maps to, or complies with any clause, article, function, or control in any framework below, and it does not certify anything. Nothing in it should be read as "vsl-core = compliant with X."

What it does instead: for nine governance frameworks that keep showing up in agentic-AI conversations, it takes each framework's own stated goal in its own words, and shows **an example of how a developer might attempt to address that goal using vsl-core's primitives** — real, working code, not a citation. Where vsl-core has nothing relevant to offer, that's stated plainly as "we don't attempt to address this" rather than papered over or stretched into a citation that doesn't hold up.

The relationship between a primitive and a requirement is implicit in the example, not asserted as an equivalence. Whether any particular implementation built this way actually satisfies a particular framework's requirements, for a particular deployment, is a question for a qualified auditor, security engineer, or compliance professional reviewing that real deployment — not something this document, or vsl-core itself, can settle in advance. This document is closer to a cookbook than a certificate.

A related point worth stating plainly: several of the frameworks below (SOC 2, ISO 42001 in particular) don't certify a library at all — they audit or certify a real, implemented system, or an organisation's management processes, over a real period of time. vsl-core being "relevant" to one of their requirements is not the same claim as vsl-core (or anything built with it) being SOC 2-audited or ISO 42001-certified; only an accredited party looking at an actual deployment or organisation can make that determination.

The framework text quoted below is drawn from each framework's own primary source and checked against it wherever that source is publicly available (OWASP, NIST, the EU AI Act, CSA MAESTRO, Singapore's IMDA framework). The one exception is noted where it applies: ISO 42001's Annex A is a paywalled commercial document, so nothing below quotes it, and even the main-body clause structure cited is drawn from public secondary summaries rather than the primary standard itself.

---

## The primitives this document draws on

These are real, tested vsl-core constructs (137 tests passing, `run_conformance_suite() == []`). What follows is what each one structurally does — not a claim about which regulation it satisfies.

| Primitive | What it structurally does |
|---|---|
| **PreNode** (`constructs.py`) | Gates a single transition behind a `monitor` callback that returns a `GammaEstimate`, checked against a `gamma_threshold`, with a `Fallback` (retry, then escalate) on insufficiency. The action cannot proceed without the gate returning normally. |
| **Invariant** (`constructs.py`) | An always-on hard constraint, independent of `PreNode`. Raises `InvariantViolation` — not a bare exception — on failure, and can optionally name a `TerminalState` to enter immediately. |
| **AllowedState / InadmissibleState** (`constructs.py`) | Every outcome resolves to one of these two classifications. `AllowedState` carries an `AssuranceBasis`; `InadmissibleState` carries a `signature` and an optional `energy_gap_proxy` instead — nothing executes unclassified. |
| **AssuranceBasis** (`metrics.py`) | A derived, read-only grade (HIGH/MEDIUM/LOW) computed from two facts you supply: was this checked *before* commitment (F1), and how completely does the check modify the outcome (F2: FULL/PARTIAL/INDIRECT/NONE). You can't just assert HIGH — you have to state what makes it HIGH, and the grade is recomputed from those facts every time. |
| **Cluster** (`cluster.py`) | Aggregates constituent systems by `IdentityKey` (not by process `Instance`), with construction-time validation that every declared constituent is actually covered by the cluster's own key. An attempt at "a cluster can't silently omit one of its own members" — not a claim that multi-agent composition risk is solved. |
| **Identity layer + `request_re_enablement()`** (`identity.py`, `governance.py`) | Scoped agent/instance identity, plus a single named path back into operation after a suspension — one that requires a `GovernanceAuthority`, a named human approver, and structured `Evidence` before it will construct a `HumanAuthorisedTransition`. |
| **VerbaLedger** (`ledger.py`) | A hash-chained, append-only log with seven entry types and an `audit()` method running five named cross-referencing checks (not just presence checks). A single-byte tamper anywhere in a persisted chain flips `verify_integrity()` from `True` to `False` — confirmed live, not just claimed. |
| **VerbaCertificate** (`ledger.py`) | `issue_certificate()` returns `None` if any audit check fails. It does not fabricate a passing certificate, and the certificate itself carries a disclaimer (surfaced in `__str__`) that it certifies the governance *process*, not the underlying system. |
| **Drift Class catalog** (`catalog/`) | A taxonomy of 45 named failure modes, each detection heuristic honestly graded by confidence — 10 of the 45 are marked as having zero detection heuristics today. This is a disclosure discipline, not an enforcement mechanism. |

---

## Canonical examples

These are the actual code patterns referenced throughout the framework sections below, so they're written out once instead of forty times. All of them run against the real, current API (`src/vsl_core/`) — none of this is invented syntax.

### Example A — gate a high-impact action before it runs

```python
from vsl_core.constructs import PreNode, Fallback
from vsl_core.metrics import AssuranceBasis, F2Modification, GammaEstimate

ALLOWED_TOOLS = {"lookup_order", "issue_refund_under_50"}

async def within_declared_scope(candidate_action) -> GammaEstimate:
    ok = candidate_action.tool_name in ALLOWED_TOOLS
    return GammaEstimate(gamma_hat=2.0 if ok else 0.1)

tool_call_gate = PreNode(
    name="tool_call_gate",
    description="A tool call only proceeds if it's within this agent's declared scope",
    monitor=within_declared_scope,
    assurance_basis=AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL),
    fallback=Fallback(max_retries=1, on_max_retries="AUTOMATION_DENIED"),
)
```
An attempt at "no high-impact action without a check beforehand" — not a claim that scope-checking is exhaustive or that `ALLOWED_TOOLS` is complete.

### Example B — a hard rule that can't be bypassed, with an escalation path

```python
from vsl_core.constructs import Invariant, TerminalState
from vsl_core.metrics import AssuranceBasis, F2Modification

governance_halt = TerminalState(
    name="governance_halt",
    description="Halts pending human review after a hard rule is violated",
    entry_conditions=("invariant_violated",),
)

async def payment_is_verified(candidate) -> bool:
    return candidate.customer.payment_verified is True

payment_required = Invariant(
    name="payment_required",
    description="Never confirm a booking without a verified payment method",
    rule=payment_is_verified,
    assurance_basis=AssuranceBasis(f1_pre_commitment=True, f2_modification=F2Modification.FULL),
    on_violation=governance_halt,
)
```

### Example C — identity scoping and a human-authorised way back into operation

```python
from vsl_core.identity import Evidence
from vsl_core.governance import GovernanceAuthority, request_re_enablement

risk_committee = GovernanceAuthority(name="Risk Committee", escalation_contact="risk@example.com")

evidence = Evidence(
    root_cause_analysis="Booking gate blocked all candidates; provider cache was stale.",
    specification_update_proposal="Refresh the provider cache every 5 minutes instead of hourly.",
)

new_instance, transition = request_re_enablement(
    suspended_instance,
    risk_committee,
    authorised_by="j.smith",
    evidence=evidence,
)
# Both the new Instance and the HumanAuthorisedTransition record exist together --
# a caller can't get one without the other.
```

### Example D — a tamper-evident, auditable record of what happened

```python
from vsl_core.ledger import VerbaLedger, VerificationResult

ledger = VerbaLedger()
ledger.write_monitor(identity_key=str(agent_identity), drift_detected=False)
ledger.write_verification(identity_key=str(agent_identity), result=VerificationResult.SUFFICIENT)

report = ledger.audit()
certificate = ledger.issue_certificate()  # None if any of the 5 audit checks fail -- never fabricated
```

### Example E — multi-agent aggregation that can't silently omit a member

```python
from vsl_core.cluster import Cluster
from vsl_core.identity import IdentityKey, ClusterKey

agents = (IdentityKey.generate("booking"), IdentityKey.generate("payments"))
cluster_key = ClusterKey.from_constituents(agents)

checkout_cluster = Cluster(name="checkout_flow", cluster_key=cluster_key, constituents=agents)
# Constructing a Cluster whose constituents aren't covered by its own cluster_key
# raises ValueError immediately -- an attempt at catching a specific class of
# mistake, not a claim that cluster-level risk is otherwise solved.
```

---

## What the resulting artifacts actually look like

Several frameworks below ask for something concrete: a log, an audit record, a documented assurance level. This is what those actually look like when Examples A–E above are run — real output from the real package, not hand-written illustrations. Referenced from the framework entries below as "(Artifact 1)" etc. rather than repeated inline.

**Artifact 1 — `AssuranceBasis` derivation, across a few different F1/F2 combinations:**
```
AssuranceBasis(f1_pre_commitment=True,  f2_modification=FULL).derived_level     == HIGH
AssuranceBasis(f1_pre_commitment=True,  f2_modification=PARTIAL).derived_level  == MEDIUM
AssuranceBasis(f1_pre_commitment=True,  f2_modification=INDIRECT).derived_level == MEDIUM
AssuranceBasis(f1_pre_commitment=True,  f2_modification=NONE).derived_level     == LOW
AssuranceBasis(f1_pre_commitment=False, f2_modification=FULL).derived_level    == LOW
```
The grade is always recomputed from the two stated facts — there's no path to writing "HIGH" without also stating why.

**Artifact 2 — one raw ledger entry, as it's actually stored:**
```json
{
  "entry_id": "b44f86db-9dce-45f8-9b2c-f36a513d8e20",
  "sequence": 0,
  "entry_type": "MONITOR",
  "identity_key": "agent-booking-7f3a",
  "cluster_key": null,
  "instance_id": null,
  "payload": {"tool": "lookup_order", "drift_detected": false},
  "timestamp": 1784338623.262,
  "prev_hash": "000...000",
  "entry_hash": "e6530932668d4372785b49cf46a44de3edb5c371d3d5d3c04944f9caf7453a3a"
}
```
`prev_hash` chains to the previous entry's `entry_hash`; changing any field of any past entry breaks every `entry_hash` after it.

**Artifact 3 — `ledger.audit()`'s result, after a short scenario of monitor → pre-node → verification entries:**
```
checks_passed: ('no_monitoring_gaps', 'drift_flagged_monitor_has_pre_node',
                 'pre_node_has_verification',
                 'insufficient_verification_has_specification_update',
                 'terminal_has_human_authorised_transition')
checks_failed: ()
all_passed: True
```
And what a *failed* audit looks like — a MONITOR entry flags drift with no PRE_NODE entry following it:
```
checks_failed: ('drift_flagged_monitor_has_pre_node',)
issue_certificate() == None
```
`issue_certificate()` refuses outright rather than issuing something partial.

**Artifact 4 — the certificate text itself, when the audit does pass:**
```
VerbaCertificate(entries_covered=3, all_passed=True) -- This certificate does not
guarantee no Inadmissible State was ever reached. It certifies that every detected
Drift event was addressed, Terminal States were properly escalated, and governance
was continuously monitored -- it certifies the governance process, not the
underlying system, model, or domain.
```
The disclaimer isn't an appendix note — it's baked into the object's own string representation, so it can't be quoted without it.

**Artifact 5 — a `HumanAuthorisedTransition` record:**
```
authority='Risk Committee'
authorised_by='j.smith'
evidence=('Booking gate blocked all candidates; provider cache was stale.',
          'Refresh the provider cache every 5 minutes instead of hourly.')
authorisation_evidence_hash='3ec193a45b34acf2...'
```

---

## Framework by framework: how one might approach each one's stated goals

Each entry below states the framework's own goal, in its own words (with the primary source it came from), followed by an attempt at addressing it — not a claim of having done so.

### OWASP Top 10 for Agentic Applications (ASI01–ASI10, published Dec 2025)

- **ASI01 Agent Goal Hijack** — the real mitigation text calls for "human approval for high-impact or goal-changing actions" and pausing execution on an unexpected goal shift. *An attempt:* gate the action with something like Example A, and make any deviation from the declared scope route into Example B's escalation path.
- **ASI02 Tool Misuse and Exploitation** — the real text names a "Policy Enforcement Middleware ('Intent Gate')... pre-execution PEP/PDP validates intent" as a mitigation. *An attempt:* Example A's `PreNode` is a plain-Python shape of exactly that idea.
- **ASI03 Identity and Privilege Abuse** — the real mitigation list is mostly about short-lived tokens, mTLS, and IAM-platform integration, which vsl-core does not do. *An attempt, narrower than the full requirement:* Example C's identity scoping addresses *who this agent is* structurally; it does not issue, bind, or rotate credentials, and an implementation would need a real IAM layer alongside it.
- **ASI04 Agentic Supply Chain Vulnerabilities** — about tampered third-party tools/models/MCP servers. *We don't attempt to address this* — it's a supply-chain-provenance problem, not a decision-point one.
- **ASI05 Unexpected Code Execution** — real mitigations are sandboxing/runtime controls (no eval in production, non-root execution). *An attempt, if a client wires it in:* Example A's gate could sit in front of any code-execution tool call, but it does not sandbox or secure the execution environment itself.
- **ASI06 Memory & Context Poisoning** — about RAG/vector-store/long-term-memory corruption. *We don't attempt to address this* — it's a memory-architecture concern, not a decision-gating one.
- **ASI07 Insecure Inter-Agent Communication** — real mitigations are mostly transport/crypto (mTLS, PKI, signed messages). *An attempt, narrower than the full requirement:* Example E can check that a cluster's declared membership matches what its `ClusterKey` actually covers, preventing a specific class of silent-omission mistake — it doesn't secure the wire protocol, and it isn't a general answer to inter-agent trust.
- **ASI08 Cascading Agent Failures** — real mitigations include "governance drift detection" and "logging and non-repudiation." *An attempt:* Example D's hash-chaining gives tamper-evidence — a change to any past entry is detectable — which is the detection half of that requirement; it doesn't by itself provide non-repudiation in the stronger cryptographic sense (proving *who* wrote an entry), which would need signing tied to a verified identity. Example E's membership-consistency check is a narrower piece of the "individually-safe agents composing into a cluster-level failure" problem, not a full answer to it.
- **ASI09 Human-Agent Trust Exploitation** — real mitigations call for "explicit confirmations... human in the loop" and "content provenance... digital signature validation." *An attempt:* Example C records the named human authoriser and hashes the associated evidence (Artifact 5); Example D supplies a tamper-evident provenance trail alongside it (Artifact 2). Neither is a digital signature — that would need an added PKI or signing layer binding a record to a verified identity's private key.
- **ASI10 Rogue Agents** — real mitigations include "immutable signed audit logs" and "recovery requiring fresh attestation and human approval." *An attempt:* Example D addresses the tamper-evident-record half, Example C the evidence-backed human re-authorisation half — together, not the same as "immutable" (which implies protected external storage vsl-core doesn't provide) or "signed" (cryptographic attestation, which it also doesn't provide on its own).

### NIST AI RMF 1.0 + Generative AI Profile (NIST AI 600-1)

- **GOVERN** (real text: GOVERN 1.5 calls for "periodic review of content provenance and incident monitoring"; GOVERN 1.7 calls for protocols so systems "are able to be deactivated when necessary") — *an attempt:* Example C's human-authorised path plus Example D's audit trail (Artifact 3 is what that periodic review would actually look at).
- **MAP** (real text: "identification and analysis of... known and reasonably foreseeable risks") — *an attempt:* the Drift Class catalog is exactly this kind of upfront, named risk taxonomy, honestly scored rather than assumed complete.
- **MEASURE** (real text: "assurance criteria are measured... and demonstrated") — *an attempt:* `AssuranceBasis`'s derived HIGH/MEDIUM/LOW grade (Artifact 1), computed from stated F1/F2 facts rather than asserted.
- **MANAGE** (real text: "supersede, disengage, or deactivate," "post-deployment monitoring... appeal and override... incident response, recovery") — *an attempt:* Example C (deactivation/recovery) and Example D (post-deployment monitoring). Worth noting: MANAGE's actual subcategories are about post-deployment response and recovery, not pre-action gating, so Examples A/B don't belong here even though they're the most obviously "governance-shaped" primitives in this document.

### EU AI Act (Regulation (EU) 2024/1689) — high-risk system obligations
*Phasing note: the high-risk-system obligations below activate 2 August 2026 — imminent, not yet in force as of this writing.*

- **Art. 9 — Risk management system** (real text: "testing... carried out against prior defined metrics and probabilistic thresholds") — *an attempt:* Example A's `gamma_threshold` is a plain-Python shape of exactly that testing discipline; the Drift Class catalog addresses the "identification and analysis of... foreseeable risks" half.
- **Art. 12 — Record-keeping** (real text: "technically allow for the automatic recording of events (logs) over the lifetime of the system") — *an attempt:* Example D, directly (Artifact 2 is what one such logged event actually looks like).
- **Art. 14 — Human oversight** (real text: "interrupt... through a 'stop' button... come to a halt in a safe state"; "decide... to disregard, override or reverse the output") — *an attempt:* Example B's `on_violation → TerminalState` is the halt-to-safe-state mechanism; Example C is the human-authorised way back out (Artifact 5).
- **Art. 15 — Accuracy, robustness, cybersecurity** — paragraph 1/3 (accuracy declared, consistent performance) is something `AssuranceBasis` (Artifact 1) and `VerbaCertificate` (Artifact 4) can speak to. *We don't attempt to address paragraph 5* (resilience against data/model poisoning, adversarial examples) — that's model-security hardening, not decision-gating.
- **Annex IV — Technical documentation** (real text requires "test logs signed by responsible persons" and a "post-market monitoring plan") — *an attempt:* Example D can contribute the runtime logs and audit artifacts (Artifacts 2–4 — the raw log, the audit result, the certificate); `AssuranceBasis` and the Drift Class catalog supply the risk/metrics documentation Annex IV also asks for. Where responsible-person *signatures* are specifically required, that's outside what Example D provides on its own — an implementation would need to connect these records to a real digital-signature or organisational sign-off system.

### CSA MAESTRO (7-layer threat model, Feb 2025)

- **L1 Foundation Models, L2 Data Operations, L4 Deployment & Infrastructure** — *we don't attempt to address these* — model-level attacks, data-pipeline poisoning, and infrastructure/container attacks are outside a decision-gating library's reach.
- **L3 Agent Frameworks** — MAESTRO's own named L3 threats (backdoors in the framework, supply-chain compromise of framework dependencies) are about the orchestration framework's own code integrity, which vsl-core doesn't defend against. What is true: vsl-core's constructs are meant to be embedded *inside* an L3 framework as its decision-gating layer (Examples A/B) — that's a statement about where vsl-core sits, not a claim about defending L3's specific threats.
- **L5 Evaluation & Observability** (real text names "poisoning observability data" as a threat) — *an attempt:* Example D's hash-chaining is a direct, tested countermeasure — a single-byte tamper is detectable.
- **L6 Security & Compliance** (real text names "Lack of Explainability: difficulty auditing actions" almost verbatim) — *an attempt:* Example D's `audit()` (Artifact 3) plus `VerbaCertificate` (Artifact 4).
- **L7 Agent Ecosystem** (real text names "Repudiation: AI agents denying actions they performed" as a threat) — *an attempt:* Example D's tamper-evident chain makes after-the-fact denial harder to sustain, though it isn't a cryptographic non-repudiation guarantee without an added signing layer; Example E checks membership consistency within a declared cluster, not broader ecosystem-level registry integrity.

### Singapore IMDA Model AI Governance Framework for Agentic AI (v1.5, May 2026)

- **Dimension 1 — bounding risk upfront** (real text: "limit the agent's scope of impact by designing appropriate boundaries at the planning stage," plus "identity management and access controls for agents") — *an attempt:* Example A for scope-bounding, Example C for identity.
- **Dimension 2 — human accountability** (real text calls for "regularly auditing human oversight effectiveness") — *an attempt:* Example D's `audit()` (Artifact 3) plus Example C (Artifact 5).
- **Dimension 3 — technical controls across the lifecycle** (the framework's own "five negative outcomes" taxonomy — erroneous, unauthorised, biased, data-breach, disruption — closely echoes the Drift Class catalog's whole approach: name the failure modes rather than assume coverage) — *an attempt:* the Drift Class catalog, plus Example D for the "logging and monitoring" component the framework names as one of its eight core agent components. *Sourcing note:* a third-party implementation guide labels this framework's multi-agent-governance control `MRF-317`; that specific ID string is not independently confirmed against IMDA's own primary text and should be treated as illustrative only.
- **Dimension 4 — end-user responsibility** — *we don't attempt to address this* — it's UX/organizational (informing users, training staff), outside what a specification library does.

### ISO/IEC 42001:2023 (AI Management System)

ISO 42001 certifies an organisation's AI management system — its policies, processes, and governance structure — not any single tool used inside it. A code library can't be ISO 42001-certified on its own; at most it can be one input into an organisation's broader management system, which is the only thing an accredited auditor actually certifies.

Its Annex A control text is a commercial document, not accessible here without a paid copy, so nothing below asserts an Annex A control title or number. What's below stays at the level of the standard's main-body clause *structure* (risk assessment, impact assessment, monitoring, management review) — and even that structure is drawn from public secondary summaries of the standard, not from the primary ISO text itself, since the primary text isn't available without a purchase. Treat the clause numbers below as indicative, not as verified quotations: clause 6.1 (risk assessment) and 8.2 (AI system impact assessment) — *an attempt:* the Drift Class catalog plus Example A's testing discipline. Clause 9.1 (monitoring) and 9.3 (management review) — *an attempt:* Example D plus `AssuranceBasis`/`VerbaCertificate` (Artifacts 1, 3, 4).

### OWASP Top 10 for LLM Applications (2025 — a distinct document from the Agentic Top 10)

Mostly not applicable — this is a prompt/runtime-layer taxonomy (prompt injection, insecure output handling, training data poisoning), and vsl-core isn't a runtime engine. The one clear bridge is **LLM06 Excessive Agency**, whose own three named root causes split across two different attempts: *excessive autonomy* ("high-impact actions proceed without a human in the loop") is Examples A/B; *excessive functionality* and *excessive permissions* (tools/privileges broader than the task needs) is Example C's identity scoping, not something a `PreNode`/`Invariant` gate addresses on its own.

### SOC 2 (AICPA Common Criteria)

SOC 2 audits controls as actually operated inside a real, implemented system over a real period of time — an auditor examines evidence from a deployment, not a library in the abstract. vsl-core, used on its own, isn't something SOC 2 evaluates; what could eventually be evaluated is a specific organisation's system that happens to use it.

Only category names are used here, not sub-criteria — AICPA's Trust Services Criteria text is restricted, and no sub-criteria numbers (e.g. "CC7.2" or "CC6.1") should be asserted without a source. At the category level: **CC4 Monitoring Activities** and **CC7 System Operations** — *an attempt:* Example D (Artifacts 2, 3) and Example A. **CC6 Logical/Physical Access** — *an attempt:* Example C.

### Microsoft Agent Governance Toolkit (AGT)

AGT is a real, MIT-licensed, open-source Microsoft project (public preview since April 2026) — a runtime policy-enforcement engine with sandboxing. Microsoft's own project materials describe it as supporting 20+ framework integrations and covering all 10 of the OWASP Agentic Top 10 risks at the runtime layer; those are Microsoft's claims about their own project, not independently verified here. Its policy engine intercepts every tool call and evaluates it against Cedar/OPA Rego/YAML policies, backed by what AGT's own documentation calls a "Merkle-chained, offline-verifiable audit trail" — a broadly similar hash-chaining approach to Example D's, for the same reason: detecting tampering after the fact. Whether AGT's implementation additionally provides cryptographic signing beyond hash-chaining isn't something this document verifies.

vsl-core and AGT are complementary, not competing: AGT is a broader runtime *engine*; vsl-core is a narrower, portable, framework-agnostic *specification* of the decision points themselves — the kind of thing a runtime engine like AGT would need to compile against. A Cedar/Rego compiler for vsl-core `Specification` objects is a plausible future build target, not a shipped capability today, and shouldn't be described as one.

---

## What this document does not claim

- It does not claim vsl-core satisfies, maps to, or complies with any requirement above. Every "attempt" is exactly that — an example of an approach, not a proof.
- It does not claim full coverage of any framework. Several items above are stated plainly as "we don't attempt to address this," and that's the honest answer, not a gap to paper over.
- It does not assert ISO 42001 Annex A or AICPA SOC 2 sub-clause/sub-criteria text without a citable source, since both are paywalled commercial documents.
- It does not claim vsl-core, by itself, could be SOC 2-audited or ISO 42001-certified. Both regimes certify a real implemented system or an organisation's management processes, not a code library in isolation.
- It does not claim the AGT Cedar/Rego compiler exists yet.
- It does not claim this document, or vsl-core, has been audited by anyone with actual authority to make a compliance determination. If this is going in front of a customer, an auditor, or a partner, that determination belongs to a qualified outside reader looking at a real deployment — a compliance lawyer, a security engineer, an accredited auditor — not to this document.
