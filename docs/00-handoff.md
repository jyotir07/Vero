# Handoff: Vero

Entry point for anyone (human or agent) picking this project up cold.
Read this first, then `ai-credit-underwriting-agent.md` for the full spec.

Last updated: 2026-09-09 (Phase 1 complete)

---

## 1. Current state

**Phase 1 is built.** The workflow runs end to end on `dev/p1`.

- `apps/api` - FastAPI backend: state machine, policy engine, agent runner, tool layer,
  document extraction, HTTP API.
- `apps/web` - React + TypeScript frontend: application list, intake form, detail view
  with stepper, document checklist, risk panel and workflow timeline.
- 432 backend tests, ruff and strict mypy clean. `scripts/smoke_demo.py` drives four
  applications through the running stack and checks each reaches its expected outcome.
- The default configuration needs no API key and no network. See the README.

Not built: reviewer UI and review actions, applicant chat, voice, Redis, queues and
workers, SSE, S3, authentication, AWS deployment, CI/CD, the observability page. Those
are Phases 2 to 4, listed in section 10.

---

## 2. What the project is

**Vero** (Latin: truth / verification) - a simulated AI credit underwriting system.

An applicant submits a loan application through a web app. An LLM agent drives it
through a stateful workflow (document check -> income verification -> credit
analysis -> risk assessment -> decision), escalating to a human reviewer when
policy rules or confidence thresholds trip.

All data is synthetic. The project must be explicitly labelled a technical
demonstration, not a real credit decisioning system.

Its purpose is proof-of-work for a Full Stack AI Engineer role, which is why the
scope deliberately spans frontend, backend, agents, state machines, voice, AWS,
and observability rather than going deep on one axis.

---

## 3. The core architectural principle

Everything in this project hangs off one idea:

> The LLM reasons and **proposes**. It never causes side effects directly.

The enforced path for every agent action:

```
LLM proposes structured action
    -> backend validates schema + permissions
    -> state machine checks the transition is legal
    -> tool executes
    -> DB records an immutable event
    -> next state
```

So `DOCUMENT_CHECK -> APPROVED` is unreachable regardless of what the model emits.

Division of responsibility:

| Owned by the LLM | Owned by deterministic code |
|---|---|
| Interpretation | DTI / affordability math |
| Document extraction | Policy rules |
| Conversation | Permissions |
| Orchestration / next-action choice | State transitions |

North star (spec section 22): *use AI where intelligence is useful, and
deterministic software where correctness is mandatory.*

---

## 4. The state machine

Eleven states. Full transition map lives in `02-agent-workflow.md`.

```
RECEIVED
DOCUMENT_CHECK
INCOME_VERIFICATION
CREDIT_ANALYSIS
RISK_ASSESSMENT
HUMAN_REVIEW
DECISION
APPROVED
REJECTED
MORE_INFORMATION_REQUIRED
FAILED
```

Terminal states: `APPROVED`, `REJECTED`, `FAILED`.

`MORE_INFORMATION_REQUIRED` loops back to `DOCUMENT_CHECK` on document receipt.
`HUMAN_REVIEW` exits to either `DECISION` or `MORE_INFORMATION_REQUIRED`.

The transition table must be explicit and enforced. This is the single most
important piece of the system to get right and to test.

---

## 5. Agent tool layer

Roughly eleven validated backend functions the agent may call:

```
extract_document          check_required_documents
calculate_dti             calculate_affordability
verify_income             run_credit_check
evaluate_policy           request_information
create_human_review       get_application
update_application_status
```

The agent returns structured actions, never free text that gets executed:

```json
{
  "action": "REQUEST_DOCUMENT",
  "document_type": "BANK_STATEMENT",
  "reason": "Required document is missing"
}
```

---

## 6. Data model

```
Application    Document       WorkflowRun    WorkflowEvent
AgentAction    ToolCall       RiskAssessment HumanReview
Conversation   AuditLog
```

Every significant workflow mutation emits an **immutable** event. Every state
transition, agent action, tool execution, and human decision must be traceable
back to an application and a workflow run.

---

## 7. Decisions locked in

These are settled. Do not relitigate without a reason.

| Decision | Choice | Why |
|---|---|---|
| Repo structure | Monorepo | User directive. Follows spec section 16. |
| Backend language | Python | User directive; matches their primary stack. |
| Backend framework | FastAPI | Python default; Pydantic models double as the agent's structured-output schemas. |
| Frontend | React + TypeScript | Mandated by the spec. The one place TS is non-negotiable. |
| Database | PostgreSQL | Durable workflow state. |
| Cache / queue | Redis | Phase 2 onward. |
| LLM provider | OpenAI | User directive. |
| Provider coupling | Thin provider interface | User's global rule requires provider-agnostic design. Concrete calls are OpenAI; the swap point exists. |
| Cross-boundary types | Generate TS types from FastAPI's OpenAPI schema | Keeps Pydantic models the single source of truth. This is the mitigation for the usual two-language type-drift problem. |
| Document extraction | OpenAI vision against synthetic PDFs, structured into Pydantic models | No separate OCR stack needed. Keeps `document-ai` small. |
| Agent output | OpenAI structured outputs with Pydantic schemas | Maps directly onto the propose/validate boundary. Makes malformed-output handling a real testable path. |

---

## 8. Decisions made on the user's behalf - pending sign-off

Flagged explicitly because they were judgement calls, not user directives.

### 8.1 Policy thresholds - DRAFTED AND APPROVED

Five gates, three bands each. The authoritative copy is
`apps/api/src/vero/policy/rules.py`; these values are invented for this demonstration
and are not any real lender's criteria.

| Gate | PASS | REVIEW | FAIL |
|---|---|---|---|
| Credit score (300-900) | >= 720 | 650-719 | < 650 |
| DTI after the loan | <= 40% | 40-50% | > 50% |
| Loan-to-income (annual) | <= 3.5x | 3.5-5.0x | > 5.0x |
| Disposable income after EMI | >= Rs 25,000 | Rs 15,000-25,000 | < Rs 15,000 |
| Verified vs stated income | within 10% | 10-25% | > 25% |

Any FAIL rejects outright; else any REVIEW escalates; else approve. Hard fails
auto-reject rather than escalating, so the deterministic reject path stays demonstrable.

Band edges belong to PASS: exactly 40% DTI passes, exactly 50% refers. Every edge is
pinned by a test.

Two figures the spec left implicit:

- The spec's stated DTI of 23.3% is `existing debt / income` and **excludes** the new
  instalment. Both are stored; policy gates on the post-loan figure.
- The product is 14% p.a. reducing balance, tenure in {12, 24, 36, 48, 60} months,
  principal Rs 50,000 to Rs 50,00,000.

**Calibration.** The spec's worked applicant approves at 60 months (EMI Rs 18,614.60,
post-loan DTI 35.7%) and lands in review at 36 months (Rs 27,342.10, 41.6%), tripping
only the DTI gate. Same person, same loan, different tenure — so scenes 2 and 5 of the
demo need no contrived fixture.

### 8.2 Sync vs async agent execution - DECIDED

**Phase 1 runs the agent inline against a durable state row in Postgres.**
The queue/worker swap happens in Phase 2.

Reasoning: workflow state lives in the database from day one, so the executor is
swappable without touching the state machine. Going straight to SQS-style workers
adds infrastructure before there is anything to run on it, and spec section 17
explicitly says not to overbuild Phase 1.

---

## 9. Open / deferred

| Item | Status |
|---|---|
| Voice: OpenAI Realtime API vs Whisper -> LLM -> TTS pipeline | Deferred to Phase 3. Real tension: Realtime is lower latency but collapses the stages, while spec sections 7-8 want per-stage p50/p95 measurements. Resolve with actual numbers in hand. |
| Reviewer authentication | Deferred to Phase 4. Real provider vs demo stub not yet decided. |
| AWS account / deployment target | Deferred to Phase 4. |

---

## 10. Phasing

From spec section 17. Do not skip ahead.

**Phase 1 - Core workflow**
React dashboard, backend API, PostgreSQL, state machine, synthetic applications,
document upload, basic agent, deterministic credit/risk calculations.

**Phase 2 - Reliability**
Durable workflow state, tool calling, audit events, retries, human review,
workflow resume.

**Phase 3 - Voice**
STT, voice agent, TTS, latency instrumentation, streaming where practical.

**Phase 4 - Productionization**
AWS deployment, CI/CD, observability, error handling, authentication, polished UI.

Phase 2's reliability requirements (spec section 12) are what separate this from a
generic agent demo: idempotency, bounded retries, timeouts, durable state, and no
workflow corruption when the AI fails.

---

## 11. Hard constraints

Violating any of these undermines the point of the project.

1. **No fabricated latency numbers.** The `300ms / 700ms / 150ms / 300ms` figures
   in spec section 8 are an *illustration*, not a target. All published latency
   must come from real telemetry. Never let example numbers leak into a README as
   a claim. (`03-voice-latency.md` states this explicitly.)
2. **Synthetic data only.** No real financial institutions, no real identities.
3. **Label it a simulation.** README must state plainly that this is not a real
   credit decisioning system.
4. **No secrets committed.** Credentials stay server-side, in env / secret
   management. Never expose a key to the browser.
5. **The agent never writes to the database directly.** Only validated tools do.
6. **AWS services must be justified.** Spec section 13: do not use a service
   purely for resume value; explain why each one is there.

---

## 12. What "done" looks like

Spec section 19 defines the deliverable as an engineering artifact, not a demo:

repo, live deployment, 2-3 minute demo video, architecture diagram, technical
writeup, latency measurements, example workflow traces, and tests covering state
transitions and critical business rules.

The README must answer: what did you build, why this architecture, what happens
when the AI fails, how is state persisted, how does human review work, how did you
reduce latency, how is it deployed, and what would change at 10x scale.

---

## 13. Source documents

| File | Contents |
|---|---|
| `ai-credit-underwriting-agent.md` | The full spec. 22 sections. Authoritative. |
| `01-system-architecture.md` | System component diagram (mermaid). |
| `02-agent-workflow.md` | State diagram + agent execution boundary sequence diagram. |
| `03-voice-latency.md` | Voice pipeline + latency budget diagrams. |
| `04-data-and-audit-flow.md` | Data and audit event flow. |
| `plan.md` | Phase 1 milestone breakdown. |
| `decisions.md` | Decisions taken while building, with reasoning. |

`01-system-architecture.md` has been redrawn against what was built: it showed a
Node.js API, which predated the Python decision in section 7. `03-voice-latency.md`
never referenced Node and is unchanged; the "Voice Gateway" box was only ever in `01-`.

---

## 14. Next step

Phase 1 is done. Phase 2 is reliability: reviewer UI and review actions, applicant chat
and the `Conversation` entity, durable queue-backed execution, and workflow resume after
a human decision.

Three things Phase 1 learned that Phase 2 should carry:

1. **The in-process executor is already swappable.** Workflow state has lived in
   Postgres from the first commit, and `api/workflow_task.py` is the only file that
   knows execution is in-process. It already takes a row lock on the run, so concurrent
   workers will not interleave state changes on one application.
2. **Test the thing that runs, not a convenient stand-in.** Three bugs survived 429
   passing tests because `TestClient` runs background tasks synchronously and hands them
   the request's own session. They surfaced within minutes of starting a real server.
   `scripts/smoke_demo.py` exists so that check is one command.
3. **A test that cannot fail is worse than no test.** Two written in Phase 1 passed
   with the code they guarded deleted. Fault injection found them; it is cheap and
   worth repeating on anything load-bearing.
