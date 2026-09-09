# Decisions

Decisions taken while building Phase 1, and why. Decisions settled before any code was
written are in `00-handoff.md` section 7; this file records what building revealed.

---

## Architecture

### The agent chooses actions; the state machine owns sequence

The workflow is nearly linear and the policy rules are deterministic, so "let the LLM
orchestrate" needed a sharper definition. The model picks which tool to call in the
state it is in. It never names a target state — the proposal schema has no field for
one, so it cannot ask for something the shape cannot express. The runner derives the
next state by reading what the tools actually recorded.

Rejected: letting the model propose transitions and validating them. It is more visibly
agentic and a refused `DOCUMENT_CHECK -> APPROVED` is a vivid demo, but it puts real
nondeterminism on the critical path for an artifact you can get from a fault-injection
test instead.

### Every transition records who caused it

`apply_transition` takes a required `actor` and checks it against the transition table.
Making it optional would let any caller skip the check by omitting it.

This caught a real bug. The runner attributed every transition to the system, and the
table refused: `SYSTEM may not drive DOCUMENT_CHECK -> INCOME_VERIFICATION; owned by
AGENT`. The table was right — an audit trail should record who *caused* a move, not
merely that code applied it.

### `update_application_status` is registered but system-only

Leaving it out of the registry would make an agent attempt look like a typo. Keeping it
visible and refusing it means the attempt is recorded as `REJECTED_PERMISSION` — the
boundary doing its job, in a form you can point at in the timeline. The system path
still goes through the transition table, so it is not a back door.

### Both AI components sit behind interfaces with working offline implementations

`LLM_PROVIDER=fake` and `DOCUMENT_EXTRACTOR=fake` are the defaults, so a fresh checkout
runs its whole test suite and a full demo with no API key and no network. Neither is a
language model and the README says so.

The offline agent provider was originally an empty script that raised on first use. That
was right for tests and wrong as a server default: it failed the first agent step of
every run. A proof-of-work project should demo without credentials.

---

## Correctness

### Money is integer paise; ratios are `Decimal`. No float anywhere in the policy path

Band edges decide outcomes. A DTI of exactly 40% has to land in PASS deterministically,
and binary floating point is precisely where that goes wrong. Model columns are typed
`Paise` via SQLAlchemy's `type_annotation_map`, so the domain type survives the round
trip; that removed 14 strict-mypy errors at the DB boundary rather than papering over
them with casts.

### PASS owns its band edge

`<= 40%` passes, `> 50%` fails, REVIEW takes the middle. Stated once, applied to all five
gates, and every edge pinned by a test.

### `debt_to_income` takes an optional EMI rather than splitting in two

Without it you get the spec's stated 23.3%; with it, the post-loan figure policy gates
on. The spec quotes only the first, which is easy to mistake for the underwriting
figure.

### The audit trail is immutable in the database, not in Python

A trigger rejects `UPDATE` and `DELETE` on `workflow_event`. Enforcing it in the
application means trusting every future caller, including a migration or someone at a
psql prompt.

`TRUNCATE` does not fire row-level triggers, so it needed a second statement-level
guard. Without it the entire trail was one statement away from being erased, which would
have made the other two guards nearly worthless.

### Idempotency is unique among successful calls only

A step that fails twice and succeeds once is one step. The first implementation mangled
the key on failures (`…#failed1`) so retries would not collide; that worked but split one
step across three different keys. A partial unique index over `status = 'OK'` lets the
attempts share the real key.

### `clock_timestamp()`, not `now()`

`now()` is transaction start time in Postgres, so every row written in one transaction
shares a `created_at` and cannot be ordered.

---

## Simplifications from the spec

| Spec | Built | Why |
|---|---|---|
| `services/` and `packages/` top-level | Internal packages under `apps/api` | A distribution boundary buys nothing while there is one deployable. Names kept, so a Phase 2 split is a move. |
| `AuditLog` and `WorkflowEvent` | `WorkflowEvent` only | With no auth in Phase 1 they are the same table. `AuditLog` returns in Phase 4 when there are access events to record. |
| `Conversation` | Deferred | No chat in Phase 1. |
| WebSockets/SSE | Polling | Phase 1 runs in-process; there is no second producer to stream from. Revisit with the queue. |
| Node.js backend | Python/FastAPI | Handoff section 7, before any code. |

---

## Things that went wrong, and what changed

### Three bugs survived 429 passing tests

`TestClient` runs background tasks synchronously and hands them the request's own
session, so an entire class of behaviour was untestable there. Against a real server:
the API hung on a lock within seconds; applications stranded with every document present;
and the default provider failed every run.

Changed: `scripts/smoke_demo.py` drives four applications through the running stack, and
`tests/test_workflow_task.py` covers the task directly rather than through the client.

### Two tests could not fail

A path-traversal test accepted `DocumentNotFound` as well as `UnsafeStorageURI`, so it
passed with the root check deleted — the traversal targets simply did not exist on this
machine. An idempotency guard was similarly unguarded until fault injection showed it.

Changed: fault injection is now routine on anything load-bearing. Every safety property
in the state machine, tool executor, agent runner and API has been verified by breaking
it and confirming a named test fails.

### An edge existed but was unreachable

`MORE_INFORMATION_REQUIRED -> FAILED` had a passing transition test and could never
occur: the runner paused as soon as the request count was above zero, so the agent never
got another turn to ask and the count never grew. A cycle is one exchange with the
applicant, so the runner counts when it pauses; the tool that sends the message does not
count at all.

### The fixture generator and the extractor did not fit together

Fifteen generated PDFs, all failing extraction. Reportlab compressed the page stream so
the marker was absent; with compression off it appeared, wrapped in PDF text-operator
syntax that broke JSON parsing. Two components that each worked, that had never been run
against each other.

Changed: `tests/test_fixture_documents.py` runs the real generated files through the real
extractor.

---

## Still open

| Item | Status |
|---|---|
| Voice: Realtime API vs STT → LLM → TTS | Phase 3. Resolve with measured latency, not estimates. |
| Reviewer authentication | Phase 4. Real provider vs demo stub undecided. |
| AWS deployment target | Phase 4. |
| Serving the SPA in production | The `/api` prefix is a Vite dev proxy. Deployment needs a real origin or a reverse proxy. |
| Latency figures | None published. Per-step model latency and tokens are recorded on `agent_action` from M6; any published number must come from those. |
