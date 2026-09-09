# Handoff: Vero

Entry point for anyone (human or agent) picking this project up cold.
Read this first, then `ai-credit-underwriting-agent.md` for the full spec.

Last updated: 2026-09-09

---

## 1. Current state

**No code exists yet.** The repo contains documentation only.

- `new-proj/` is its own git repo (root: `C:\Users\jyoti\Desktop\Coding\new-proj`),
  separate from the home-directory repo it used to sit inside.
- All five spec docs are tracked. Nothing else is.

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

### 8.1 Policy thresholds - TO BE DRAFTED

The spec shows an example applicant (DTI 23.3%, synthetic credit score 742) but
**never defines what actually fails**. A synthetic policy table is needed:

- maximum DTI
- minimum credit score
- loan-to-income cap
- what triggers `HUMAN_REVIEW`

The demo narrative in spec section 18 depends on these values, since scenes 3-5
require deliberately tripping them. Draft during planning, get approval.

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

Note: the diagrams in `01-` and `03-` reference a Node.js API and a generic
"Voice Gateway". Those predate the Python decision in section 7 above and should
be updated when the code lands.

---

## 14. Next step

Write the Phase 1 plan. Not started yet.
