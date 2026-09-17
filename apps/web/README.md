# Vero web

The React + TypeScript frontend: submit an application, upload its documents, and watch
the agent drive it through the state machine.

Full setup for both halves of the stack is in the [root README](../../README.md); the API
must be running on port 8000 for anything here to work.

```bash
npm install
npm run dev        # http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000`, so the browser talks to one origin and no
API URL is baked into the build.

## Checks

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

## Types

Nothing in `src/api` hand-writes a request or response type. `src/api/schema.d.ts` is
generated from the backend's OpenAPI document, so a changed Pydantic model surfaces as a
TypeScript error rather than a runtime surprise.

With the API running:

```bash
npm run gen:types      # regenerate the committed schema
npm run check:types    # fail if the committed copy has drifted
```

## Layout

```
src/api/           generated schema and the typed fetch client
src/components/    workflow.tsx, plus shadcn primitives under ui/
src/hooks/         fetching and polling for an in-flight application
src/pages/         application list, detail, and intake
```
