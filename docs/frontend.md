# Frontend

`services/api/frontend` is a Vite + React 18 + TypeScript app, with shadcn/ui components over
Tailwind. The first stage of the api Dockerfile builds it, and FastAPI serves the build from the
same origin as the API. The client uses relative URLs, so production needs no CORS configuration.

## Layout

| Path | What is there |
|---|---|
| `src/pages/Index.tsx` | The chat screen. Owns the streaming lifecycle: sending a question, re-answering a reply with the thinking model, retrying, and naming a new conversation through `/rewriteQuery` |
| `src/pages/NotFound.tsx` | The 404 page |
| `src/lib/api.ts` | The API client. `askStream()` reads the NDJSON stream and dispatches each event; `StreamEvent` is the union of event types |
| `src/lib/chat-store.ts` | Types for conversations, messages and sources |
| `src/lib/chat-persistence.ts` | Saves conversations to `localStorage` |
| `src/components/chat/` | The composer, message rendering (markdown and LaTeX), source cards, message actions, the welcome screen, the error banner and the conversation search palette |
| `src/components/AppSidebar.tsx` | The conversation list: switch, rename and delete |
| `src/components/ui/` | shadcn/ui components |
| `src/hooks/` | `use-health.ts` polls `/health` every 30 seconds so the UI can show when the backend is unreachable. `use-quota.ts` polls `/quota` but is not used by any component. The rest handle theme, sidebar state, layout and toasts |
| `src/test/` | vitest setup and tests |

## Data flow

1. The user sends a question. `Index.tsx` builds `history` from the conversation's previous
   turns and calls `askStream()`.
2. The `sources` event becomes the reply's source cards.
3. `token` events are buffered and applied to the reply once per animation frame.
4. `step` events are shown as the model's reasoning, in thinking mode.
5. An `error` event is shown in the error banner.
6. `done` ends the reply.

"Think longer" on a reply sends the same question again with `thinking: true`, and with the turns
before that question as history. The answer appears as a new reply.

`extractSources()` in `src/lib/api.ts` parses a sources list out of an answer's text. It is a
fallback for replies that did not receive a `sources` event.

## Storage

The server stores nothing. The browser keeps, in `localStorage`:

| Key | Holds |
|---|---|
| `askpesu-conversations` | Every conversation and its messages |
| `askpesu-theme` | Light or dark |
| `askpesu-sidebar-collapsed` | Whether the sidebar is collapsed |

## Running it

```bash
cd services/api/frontend
npm ci
npm run dev         # dev server on http://localhost:8080
npm run build       # production build into dist/
npm run typecheck   # tsc on both tsconfig projects
npm test            # vitest
npm run lint        # eslint
```

The dev server proxies `/ask`, `/quota`, `/health` and `/rewriteQuery` to `localhost:7860`, so run
the api alongside it. `ENV=test` on the api gives the frontend a realistic stream without
credentials; see [development.md](development.md#working-without-credentials).

`vite build` removes TypeScript types without checking them, so run `npm run typecheck` before
opening a pull request. CI runs it and `npm test` when the frontend changes.
