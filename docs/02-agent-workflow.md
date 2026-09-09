# Agent + State Machine

The authoritative table lives in `apps/api/src/vero/state_machine/transitions.py` as
data, and `apps/api/tests/test_transitions.py` transcribes it independently from this
document so that drift in either direction fails a test.

Each edge names the one actor permitted to drive it. That is what keeps the agent away
from decisions: `DECISION -> APPROVED` is owned by the system, so no model output can
reach it.

```mermaid
stateDiagram-v2
    [*] --> RECEIVED
    RECEIVED --> DOCUMENT_CHECK: submitted (system)

    DOCUMENT_CHECK --> INCOME_VERIFICATION: documents complete (agent)
    DOCUMENT_CHECK --> MORE_INFORMATION_REQUIRED: missing document (agent)
    DOCUMENT_CHECK --> FAILED: extraction failure (system)

    MORE_INFORMATION_REQUIRED --> DOCUMENT_CHECK: document received (applicant)
    MORE_INFORMATION_REQUIRED --> FAILED: request cycles exhausted (system)

    INCOME_VERIFICATION --> CREDIT_ANALYSIS: verified (system)
    INCOME_VERIFICATION --> HUMAN_REVIEW: conflict / low confidence (system)
    INCOME_VERIFICATION --> FAILED: unrecoverable error (system)

    CREDIT_ANALYSIS --> RISK_ASSESSMENT: metrics computed (system)
    CREDIT_ANALYSIS --> FAILED: bureau call exhausted (system)

    RISK_ASSESSMENT --> HUMAN_REVIEW: policy exception (system)
    RISK_ASSESSMENT --> DECISION: within policy (system)

    HUMAN_REVIEW --> DECISION: reviewer decision (reviewer)
    HUMAN_REVIEW --> MORE_INFORMATION_REQUIRED: more information needed (reviewer)

    DECISION --> APPROVED: outcome approve (system)
    DECISION --> REJECTED: outcome reject (system)

    APPROVED --> [*]
    REJECTED --> [*]
    FAILED --> [*]
```

## Two edges added since the first draft

Both close gaps in the original sketch that spec section 12 requires:

- **`MORE_INFORMATION_REQUIRED -> FAILED`** bounds the resubmission loop. Without it an
  applicant who never supplies a document keeps a workflow alive forever. The count is a
  round trip to the applicant, incremented by the runner when it pauses, not by the tool
  that sends the message — counting tool calls made this edge unreachable, because the
  runner paused before the agent could ask again.
- **`CREDIT_ANALYSIS -> FAILED`** covers the one genuinely external call in Phase 1.

## Edges deliberately not added

`RISK_ASSESSMENT` and `DECISION` have no `FAILED` edge. Both are pure deterministic
arithmetic; the only model involvement is the human-readable narrative, and a narrative
that fails to generate degrades to a template rather than losing a decision. Adding
`FAILED` there would imply the risk maths can fail when it cannot.

`RECEIVED -> FAILED` is absent because intake validation is a 422 — a rejected
application is never created.

## Agent execution boundary

```mermaid
sequenceDiagram
    participant WF as Workflow Runner
    participant A as AI Agent
    participant V as Proposal Validator
    participant T as Tool
    participant DB as PostgreSQL

    WF->>A: Current state + available tools
    A->>A: Choose next action
    A->>V: Structured proposal
    V->>V: Schema, then tool permission for this state
    V-->>DB: Record the proposal, accepted or refused
    V->>T: Execute approved tool
    T->>DB: Persist result + immutable event
    T-->>WF: Result
    WF->>WF: Derive next state from what was persisted
    WF->>DB: Record the transition and its actor
```

The agent never names a target state: the proposal schema has no field for one. The
runner derives the next state by reading what the tools actually recorded, so a
transition follows from persisted facts rather than from what the model asserted.
