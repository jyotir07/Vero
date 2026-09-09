# Vero — Phase 1 Implementation Plan

> **Status: complete.** All nine milestones are built on `dev/p1`. This document is the
> plan as approved before implementation and has not been rewritten to match what was
> built. Where the two differ, `decisions.md` records the change and why. Notable
> deviations: the request-cycle count moved from the tool to the runner (the documented
> bound was otherwise unreachable), and the offline agent provider became a working
> rule-based stand-in rather than an empty script.

## Context

`docs/00-handoff.md` §14 says the next step is "Write the Phase 1 plan. Not started yet."
The repo is documentation only — six files, zero code.

Vero is a simulated AI credit underwriting system, built as proof-of-work for a Full
Stack AI Engineer role. Its thesis (spec §22): *use AI where intelligence is useful, and
deterministic software where correctness is mandatory.* Everything below exists to make
that thesis demonstrable rather than merely claimed.

Phase 1 delivers the automated underwriting path end-to-end: an applicant submits, the
agent drives the workflow through document check → income verification → credit analysis
→ risk assessment → decision, and the UI shows the state machine working. Reviewer UI,
applicant chat, and voice are explicitly later phases.

Four gaps in the source docs are closed by this plan: undefined policy thresholds
(handoff §8.1), an incomplete transition table, an unbounded resubmission loop, and
Node-vs-Python drift in the diagrams.

## Decisions settled during design

| Question | Choice |
|---|---|
| Phase 1 boundary | Automated path + missing-doc loop. `HUMAN_REVIEW` reachable but parks the application — no reviewer UI, no chat. |
| Agent latitude | LLM picks actions legal in the current state; the **state machine owns sequence**. The agent never names a target state. |
| Document extraction | `DocumentExtractor` protocol, two impls: OpenAI vision + a deterministic fixture-driven fake. Fake is the default for tests/dev. |
| Repo layout | Flatten spec §16 to `apps/web` + `apps/api`; §16's `services/`/`packages/` become internal Python packages under `apps/api`, keeping the names so a Phase 2 split is a move, not a rewrite. |
| Live updates | Poll. `POST /applications` returns 201 and kicks a `BackgroundTask`; detail page polls while non-terminal. SSE waits for Phase 2's queue. |
| Toolchain | `uv` + ruff + mypy (api); Vite + React + TS + Tailwind + shadcn/ui (web). |
| Currency | INR throughout — settled by the spec's ₹ figures. Money stored as **bigint paise**, never float. |

Carried in from handoff §7: monorepo, FastAPI, PostgreSQL, OpenAI behind a thin provider
interface, OpenAI structured outputs, TS types generated from FastAPI's OpenAPI schema.

## The transition table — the spine

Build this first; everything else depends on it. Encoded as **data** in
`state_machine/transitions.py`, not as branching logic.

| From | To | Trigger | Actor |
|---|---|---|---|
| RECEIVED | DOCUMENT_CHECK | submitted | system |
| DOCUMENT_CHECK | INCOME_VERIFICATION | all required docs extracted | agent |
| DOCUMENT_CHECK | MORE_INFORMATION_REQUIRED | required doc missing | agent |
| DOCUMENT_CHECK | FAILED | extraction failed, retries exhausted | system |
| MORE_INFORMATION_REQUIRED | DOCUMENT_CHECK | document received | applicant |
| MORE_INFORMATION_REQUIRED | FAILED | 4th request cycle exceeded ← **new** | system |
| INCOME_VERIFICATION | CREDIT_ANALYSIS | within 10% tolerance | system |
| INCOME_VERIFICATION | HUMAN_REVIEW | divergence >10% or confidence <0.7 | system |
| INCOME_VERIFICATION | FAILED | unrecoverable | system |
| CREDIT_ANALYSIS | RISK_ASSESSMENT | credit pulled, metrics computed | system |
| CREDIT_ANALYSIS | FAILED | bureau call failed, retries exhausted ← **new** | system |
| RISK_ASSESSMENT | DECISION | all PASS, or any FAIL | system |
| RISK_ASSESSMENT | HUMAN_REVIEW | any REVIEW band | system |
| HUMAN_REVIEW | DECISION | reviewer decided (Phase 2) | reviewer |
| HUMAN_REVIEW | MORE_INFORMATION_REQUIRED | reviewer requests info (Phase 2) | reviewer |
| DECISION | APPROVED | outcome = approve | system |
| DECISION | REJECTED | outcome = reject | system |

Terminal: `APPROVED`, `REJECTED`, `FAILED`.

**Deliberate omissions.** `RISK_ASSESSMENT` and `DECISION` get no `FAILED` edge: both are
pure deterministic math under the chosen agent design, and their only model call is the
human-readable narrative, which degrades to a template rather than failing the workflow.
`RECEIVED → FAILED` is absent because intake validation is a 422 — the application is
never created.

## Policy engine

Synthetic loan product: 14% p.a. reducing balance, tenure ∈ {12,24,36,48,60} months,
principal ₹50k–₹50L. Standard EMI: `P·r·(1+r)^n / ((1+r)^n − 1)`.

Two DTI figures, both stored:
- `dti_current` = existing debt ÷ gross monthly income — reproduces the spec's 23.3%
- `dti_proposed` = (existing debt + EMI) ÷ gross monthly income — **policy gates on this**

| Gate | PASS | REVIEW | FAIL |
|---|---|---|---|
| Credit score (300–900) | ≥ 720 | 650–719 | < 650 |
| `dti_proposed` | ≤ 40% | 40–50% | > 50% |
| Loan-to-income (annual) | ≤ 3.5× | 3.5–5.0× | > 5.0× |
| Disposable income after EMI | ≥ ₹25,000 | ₹15,000–25,000 | < ₹15,000 |
| Verified vs stated income | within 10% | 10–25% | > 25% |

Decision rule: any FAIL → `REJECTED`; else any REVIEW → `HUMAN_REVIEW`; else → `APPROVED`.
Hard fails auto-reject rather than escalating, so the deterministic reject path is
demonstrable.

**Calibration (verified):** the spec's worked example (₹150k income, ₹35k debt, ₹800k
loan, score 742) is all-PASS → APPROVED at 60mo (EMI ₹18,615, `dti_proposed` 35.7%), and
the *same applicant* lands in REVIEW at 36mo (EMI ₹27,342, `dti_proposed` 41.6%). Free
escalation demo, no contrived fixture.

## Repo layout

```
apps/api/          pyproject.toml, alembic/, src/vero/
  domain/          money.py, enums.py, schemas.py   ← Pydantic DTOs = OpenAPI source of truth
  state_machine/   transitions.py (the table), machine.py
  policy/          product.py, metrics.py, rules.py, decision.py
  agent/           runner.py, validator.py, prompts.py, schemas.py, provider/{base,openai,fake}.py
  tools/           registry.py, documents.py, finance.py, credit.py, workflow.py
  document_ai/     base.py, openai_vision.py, fake.py
  db/              models.py, session.py
  api/routes/      applications.py, documents.py, events.py, health.py
  events/          recorder.py
apps/web/          Vite + React + TS + Tailwind + shadcn
scripts/           generate_fixtures.py (reportlab synthetic PDFs), gen_types.sh
docker-compose.yml postgres
```

## Data model

`application` · `workflow_run` · `document` · `workflow_event` · `agent_action` ·
`tool_call` · `risk_assessment` · `human_review`

Two simplifications from spec §11, both worth stating in `decisions.md`:
- **`Conversation` deferred** to Phase 2 — no chat in Phase 1.
- **`AuditLog` collapsed into `workflow_event`.** With no auth in Phase 1 the two are
  redundant; `AuditLog` returns in Phase 4 when there are auth/access events to record.

Key details:
- Current state lives **only** on `workflow_run.current_state` — single source of truth.
  `application` exposes it via join, so there is no mirror to drift.
- One `workflow_run` per application, spanning its life (`status`: RUNNING/PAUSED/
  COMPLETED/FAILED). Resume continues the same run — matches spec §17's "workflow resume".
- `workflow_event` is append-only, enforced by a **DB trigger** rejecting UPDATE/DELETE.
  Proving immutability beats asserting it.
- `document.extracted_data` JSONB + `extraction_confidence` — no separate facts table.
- `tool_call.idempotency_key` unique on `(workflow_run_id, step_seq, tool_name,
  hash(args))`. A replay returns the recorded result instead of re-executing. Nominally a
  Phase 2 requirement, but retrofitting it costs far more than designing it in now.

## Agent loop and the permission boundary

Per state, who acts:

| State | Driver |
|---|---|
| DOCUMENT_CHECK | **LLM** — chooses extract / check / request_information |
| INCOME_VERIFICATION | **LLM** — interprets extracted payslip data; comparison is deterministic |
| CREDIT_ANALYSIS | deterministic |
| RISK_ASSESSMENT | deterministic gates + LLM narrative (template fallback) |
| DECISION | deterministic + LLM explanation (template fallback) |

Loop: build context → LLM proposes structured action → record `AgentAction` → validate
(schema, tool-allowed-in-state, args) → on rejection record and retry repair, bounded at
2, then `FAILED` → execute tool with idempotency key → record `ToolCall` + `WorkflowEvent`
→ machine derives next state. Bounded total steps; timeout on every LLM and tool call.

`registry.py` maps each tool to the states it is legal in. **`update_application_status`
is registered system-only** — the agent can never call it, and an attempt is recorded as
a `REJECTED_PERMISSION` event. That rejection artifact is the project's thesis made
visible, and is what makes the fault-injection demo possible without putting
nondeterminism on the critical path.

## API surface (Phase 1 subset of spec §10)

`POST /applications` (201 + BackgroundTask kickoff) · `GET /applications` ·
`GET /applications/{id}` · `POST /applications/{id}/documents` ·
`GET /applications/{id}/events` · `GET /health`

Deferred: `/messages`, `/voice`, `/review`, `/resume`.

## Frontend

Three screens: application list, new-application form (manual entry or pick a seeded
fixture applicant), and application detail — state badge, 11-state progress stepper,
document checklist with upload, risk metrics panel, workflow timeline in the spec §9
format, and an agent activity panel showing actions and tool calls.

`openapi-typescript` generates `src/api/schema.d.ts` from `/openapi.json`, checked in,
with a CI check that regeneration produces no diff. This is the mitigation for
two-language type drift named in handoff §7.

## Implementation order

TDD throughout — tests before implementation, per the project's testing skill. Each
milestone ends green before the next starts.

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold: uv project, FastAPI skeleton, docker-compose postgres, Vite/React/Tailwind/shadcn, alembic init, lint+typecheck wired | both apps boot; lint and typecheck clean |
| M1 | Domain + state machine (pure, no DB) | every legal edge passes; illegal `(from,to)` matrix all rejected |
| M2 | Policy engine (pure) | band boundaries exact (720/719, 40.0%…); spec example → APPROVED @60mo, HUMAN_REVIEW @36mo |
| M3 | Persistence: models, migration, append-only trigger, event recorder | UPDATE/DELETE on `workflow_event` raises; event seq monotonic |
| M4 | Tool layer + registry + idempotency | out-of-state tool rejected; replayed key returns recorded result without re-executing |
| M5 | Document extraction + `scripts/generate_fixtures.py` synthetic PDFs | fake extractor passes; extraction-failure → `FAILED` covered |
| M6 | Agent runner, provider protocol, `FakeLLMProvider`, validator | malformed output repaired then bounded; illegal tool → `REJECTED_PERMISSION`; step cap enforced |
| M7 | API routes + background kickoff | end-to-end happy path with fakes; missing-doc loop; 4th cycle → `FAILED` |
| M8 | Frontend: type codegen, three screens, poll hook | full run visible in UI against the real API |
| M9 | Seed fixtures + docs | fixtures cover all four outcomes; docs corrected (below) |

M1 and M2 are pure functions with no I/O — they are the highest-value, most-testable part
of the system and deliberately come before any database or model work.

**M9 doc corrections** (closes handoff §13 drift): `01-system-architecture.md` and
`03-voice-latency.md` say "Node.js / TypeScript API" — correct to Python/FastAPI. Add the
two new edges to `02-agent-workflow.md`. Update handoff §8.1 (thresholds now defined) and
§14. Write `docs/decisions.md` (spec §16) and the design doc to
`docs/superpowers/specs/2026-09-09-vero-phase-1-design.md`. README must state plainly
that this is a simulation, not a real credit decisioning system (hard constraint §11.3).

## Verification

```bash
docker compose up -d db
cd apps/api && uv run alembic upgrade head
uv run pytest -q                      # unit + integration, fakes only, no network
uv run ruff check . && uv run mypy src
cd ../web && npm run typecheck && npm run lint && npm test
```

Then the end-to-end check, run twice — once with `LLM_PROVIDER=fake` (deterministic, CI)
and once with `LLM_PROVIDER=openai` (real model, real vision):

1. `docker compose up` → seed fixtures → open the web app.
2. Submit the spec's worked applicant at 60mo → watch the stepper advance → **APPROVED**.
3. Submit the same applicant at 36mo → parks in **HUMAN_REVIEW**, timeline names the
   tripped gate.
4. Submit with a missing bank statement → **MORE_INFORMATION_REQUIRED**; upload it →
   loop returns to `DOCUMENT_CHECK` and completes.
5. Submit and ignore the request 4× → **FAILED** with the loop bound as the reason.
6. Submit a sub-650 credit score fixture → **REJECTED** without human escalation.
7. Confirm every run's `/events` shows an unbroken transition chain, and that
   `agent_action` rows record proposals, including any rejections.

Latency and token counts are recorded per `agent_action` from M6 onward, so Phase 3 has
real telemetry to compare against. **No latency numbers get published anywhere until they
come from these measurements** — spec §8's `300ms/700ms/150ms/300ms` are an illustration,
and hard constraint §11.1 forbids letting them leak into a README as a claim.

## Out of scope for Phase 1

Reviewer UI and review actions, applicant chat, `Conversation` entity, voice/STT/TTS,
Redis, queues and workers, SSE/WebSocket, S3 (documents go to local disk behind a storage
interface), authentication, AWS deployment, CI/CD, observability page.
