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

Phase 1 (core workflow) in progress. See [`docs/plan.md`](docs/plan.md) for the milestone
breakdown and [`docs/00-handoff.md`](docs/00-handoff.md) to pick the project up cold.

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

Set `LLM_PROVIDER=openai`, `DOCUMENT_EXTRACTOR=openai`, and `OPENAI_API_KEY` in `.env` to
run against real models. The defaults are deterministic fakes so the test suite and local
development need no network access or credentials.

## Tests

```bash
cd apps/api && uv run pytest && uv run ruff check . && uv run mypy src
cd apps/web && npm run typecheck && npm run lint && npm test
```
