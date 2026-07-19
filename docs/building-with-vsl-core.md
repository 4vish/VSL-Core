# Building with vsl-core

## What this document is for

This is the guide for going from "I have an agent, or an idea for one" to working code that uses vsl-core's real primitives correctly. It's written for two readers at once: a developer reading it directly, and an AI coding assistant (Claude Code, Codex, or similar) using it as reference material while generating code — either works, and neither requires special setup beyond having this file (and its companion, [`vsl-core-primitives.json`](vsl-core-primitives.json)) available to read.

This is not the compliance-framework document — see [`governance-frameworks.md`](governance-frameworks.md) for how vsl-core relates to OWASP/NIST/EU AI Act/etc. This document is about building, not compliance.

**The companion JSON.** Everything in this guide that names a class, a field, or a piece of runnable code is also in `vsl-core-primitives.json`, as structured, exact data — every code sample in it has been executed against the real package, not hand-written and hoped to be correct. If you're an AI generating code from this guide, prefer quoting fields and code directly from the JSON over paraphrasing from this prose; the JSON is the harder-to-hallucinate source.

**One instruction that matters more than any of the reference material below:** if a stated use case doesn't make its risky or irreversible actions obvious, ask 1-2 clarifying questions about what's genuinely external-facing or hard-to-undo in that domain before constructing anything. Don't silently guess and build the wrong governance shape. If the risky actions genuinely are obvious from the prompt (a refund is irreversible, an email is external — no need to ask), proceed without asking; the point is judgment, not a mandatory checklist.

---

## Step 1: find the decision points

Not the whole agent — specific moments where an action is about to happen. Four recognisable shapes cover almost everything:

| Signal in the code or use case | Reach for | Why |
|---|---|---|
| A side effect on an external system (payment, email, database write, infra change — anything not purely in-memory) | `PreNode` (sometimes `Invariant` if it must never be bypassed regardless of context) | Gate the action before it fires, checked against a monitor's `GammaEstimate`. |
| An irreversibility boundary (delete, refund, transfer — anything that can't be cleanly undone) | `Invariant` | These tend to be "cannot be bypassed" cases — always-on, not context-dependent. |
| A point where untrusted input could redirect what the agent does next (a tool's return value, retrieved content, another agent's message) | `PreNode` gating the *next* action | vsl-core doesn't sanitize input — it gates what happens after. |
| A scope/permission escalation (the agent about to act outside what was declared for this task) | `Invariant`, often paired with `IdentityKey`/`Instance`/`Cluster` | Usually a hard "never" rule, and identity scoping is what makes "declared for this task" checkable at all. |

Not every action needs a gate. A read-only lookup with no side effect and no scope implication doesn't need governance wired around it — over-gating adds noise without adding safety.

## Step 2: know what's automatic and what you write yourself

vsl-core does not intercept anything. Everything below that's "automatic" only happens because a compiled gate or the ledger's own methods do it internally — nothing happens because vsl-core is watching your code from the outside.

**Automatic:**
- A compiled gate raising `AutomationDeniedException`/`InvariantViolation` when its check fails.
- The ledger's hash chain updating, and `verify_integrity()` detecting any tampering.
- `audit()`'s five checks running against whatever entries currently exist.
- `issue_certificate()` refusing to fabricate a certificate when the audit fails.

**You write this yourself:**
- Catching the raised exception. vsl-core does not catch it for you.
- Writing the `TERMINAL` ledger entry when a `TerminalState` is entered.
- Actually halting further execution — there's no running "current state" object that flips; your own code decides what happens next after catching the exception.
- Calling `request_re_enablement()` and writing the resulting entries.
- Populating `decision_id`/`caused_by` on ledger writes once more than one decision can be in flight per identity/instance — otherwise `audit()` can match the wrong entries to each other (see `vsl-core-primitives.json`'s `important_gotchas` under `VerbaLedger`).

## Step 3: the five things you'll actually write

Construct → compile → call → log → escalate. This is the same five-step shape regardless of use case:

```python
# 1. Construct — pure data + callables, nothing live yet
gate_spec = PreNode(name=..., monitor=..., assurance_basis=AssuranceBasis(...))

# 2. Compile — turns the spec into an actual callable gate
adapter = PlainPythonReferenceAdapter()  # or a named framework adapter
gate = adapter.compile_pre_node(gate_spec)

# 3. Call — immediately before the real action
await gate(candidate_input)  # raises if blocked; the real action only runs after this returns

# 4. Log — your own code, not automatic
ledger.write_monitor(identity_key=..., drift_detected=...)

# 5. Escalate — only on the exception path, only if you catch it
except InvariantViolation:
    ledger.write(LedgerEntryType.TERMINAL, identity_key=..., payload={})
    # later, once a human has reviewed it:
    # request_re_enablement(instance, authority, authorised_by=..., evidence=...)
```

The five canonical patterns in `vsl-core-primitives.json` (`canonical_patterns` A–E) are real, executed code for each of the building blocks above — a `PreNode` gate, an `Invariant` with escalation, identity/recovery, the ledger, and cluster membership.

## Step 4: the generic project scaffold

The same file layout regardless of domain — substitute real nouns and actions for whatever the use case actually is:

```
domain.py       Plain dataclasses modeling the domain's entities and states
                (e.g. Customer, Order, ProviderStatus)
tools.py        The actual functions that perform side-effecting actions —
                the "controlled tools" this domain needs
                (e.g. issue_refund, send_email, book_appointment)
governance.py   Constructs the PreNode/Invariant/TerminalState/Cluster objects,
                one per decision point found in Step 1. Every AssuranceBasis
                here is justified with real F1/F2 facts, never defaulted to HIGH.
agent.py        Orchestrates: decide what to do -> compile gates -> call gates
                before each tools.py action -> write ledger entries -> catch
                exceptions and handle TerminalState/re-enablement.
tests/          Prove the governance shape: each PreNode/Invariant actually
                blocks the case it should and passes the case it shouldn't,
                using PlainPythonReferenceAdapter directly.
```

## Worked example: applying the procedure to a vague prompt

Prompt: *"Build me a deterministic agent for a customer support bot that can look up orders, issue refunds, and send emails to customers."*

**Are the risky actions obvious?** Yes — no need to ask a clarifying question here. `issue_refund` is financial and irreversible; `send_email` is an external side effect; `lookup_order` is read-only.

**Classify each action:**
- `lookup_order` — read-only, no side effect, no scope implication. No gate needed.
- `issue_refund` — irreversibility boundary → `Invariant` (e.g. "never refund without eligibility and amount-limit checks passing"), with `on_violation` pointing at a `TerminalState` for human review.
- `send_email` — external side effect → `PreNode` (gate checking the email's recipient and content match what this task was actually asked to do, before the send call fires).

**Build it:**
- `domain.py`: `Customer`, `Order`, `RefundRequest`.
- `tools.py`: `lookup_order(order_id)`, `issue_refund(order, amount)`, `send_email(customer, subject, body)`.
- `governance.py`: an `Invariant` named `refund_within_policy` (pattern B's shape) and a `PreNode` named `email_content_gate` (pattern A's shape), each with a real `AssuranceBasis` — both checks run before the actual `tools.py` call fires (F1=True), and both directly determine whether the call happens at all (F2=FULL), so both are justified as HIGH.
- `agent.py`: compiles both via `PlainPythonReferenceAdapter`, calls `email_content_gate` before every `send_email`, calls `refund_within_policy` before every `issue_refund`, catches `InvariantViolation` from the refund check and routes to a `governance_halt` `TerminalState`, writes `MONITOR`/`PRE_NODE`/`VERIFICATION` entries to a `VerbaLedger` around each gated call.
- `tests/`: one test proving `refund_within_policy` blocks an out-of-policy refund, one proving it passes a valid one, same pair for the email gate.

That's the whole procedure, run once, end to end, on a use case this document didn't already know about.
