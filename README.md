# Vero

An AI credit underwriting agent that reasons about loan applications, calls validated
backend tools, and escalates to a human reviewer when policy or confidence thresholds trip.

> **This is a technical demonstration, not a real credit decisioning system.**
> All applicant data, documents, and credit scores are synthetic. Vero is not connected to
> any financial institution or credit bureau, and nothing it produces is a lending decision.

## The idea

> The LLM reasons and **proposes**. It never causes side effects directly.

Every agent action takes the same enforced path:

```
LLM proposes structured action
    → backend validates schema + permissions
    → state machine checks the transition is legal
    → tool executes
    → DB records an immutable event
    → next state
```

`DOCUMENT_CHECK → APPROVED` is unreachable regardless of what the model emits.

| Owned by the LLM | Owned by deterministic code |
|---|---|
| Interpretation | DTI / affordability math |
| Document extraction | Policy rules |
| Conversation | Permissions |
| Action selection | State transitions |

North star: *use AI where intelligence is useful, and deterministic software where
correctness is mandatory.*

## Status

**Phase 1 (core workflow) is complete.** An application can be submitted, driven through
the state machine by the agent, and reach approval, rejection, human review, or failure —
with every step recorded in an immutable audit trail.

Next: Phase 2 (reliability) adds the reviewer UI, applicant chat, queue-backed execution
and workflow resume. See [`docs/plan.md`](docs/plan.md) for the milestone breakdown,
[`docs/decisions.md`](docs/decisions.md) for what was decided while building, and
[`docs/00-handoff.md`](docs/00-handoff.md) to pick the project up cold.

No latency figures are published here. Any that appear later will come from real telemetry
recorded by the system, never from estimates.

## Layout

```
apps/api/    FastAPI backend — state machine, policy engine, agent, tools
apps/web/    React + TypeScript frontend
docs/        Spec, architecture diagrams, plan
scripts/     Synthetic fixture generation
```

## Running it

Requires Docker, [uv](https://docs.astral.sh/uv/), and Node 20+.

```bash
cp .env.example .env          # defaults use the fake LLM/extractor — no API key needed
docker compose up -d db      # publishes Postgres on host port 5433

cd apps/api && uv sync && uv run alembic upgrade head
uv run uvicorn vero.main:app --reload      # http://localhost:8000

cd ../web && npm install && npm run dev    # http://localhost:5173
```

Then open http://localhost:5173 and submit an application.

The defaults need no API key and no network. `LLM_PROVIDER=fake` uses a rule-based
stand-in that reads the same structured prompt the real agent gets and returns the
obvious next action, which is enough to drive the whole workflow; `DOCUMENT_EXTRACTOR=fake`
reads structured data the synthetic PDFs carry. Neither is a language model and neither
pretends to be one. Set `LLM_PROVIDER=openai`, `DOCUMENT_EXTRACTOR=openai` and
`OPENAI_API_KEY` to run against real models.

Generate the synthetic documents first if you want files to upload:

```bash
cd apps/api && uv run python ../../scripts/generate_fixtures.py
```

To check the whole stack end to end while both servers are running:

```bash
cd apps/api && uv run python ../../scripts/smoke_demo.py
```

## Tests

```bash
cd apps/api && uv run pytest && uv run ruff check . && uv run mypy src
cd apps/web && npm run typecheck && npm run lint && npm test
```

The frontend's types are generated from the backend's OpenAPI schema. With the API
running, `npm run gen:types` regenerates them and `npm run check:types` fails if the
committed copy has drifted.
