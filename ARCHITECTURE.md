# Architecture

## What this is

Jugnu is a conversational search engine. You ask a question in plain language;
it finds real pages on the web, reads them, and writes an answer where **every
sentence carries a numbered citation** pointing at the page it came from.

The design goal is not "an AI that sounds confident." It is "an answer you can
audit in ten seconds." That single constraint drives most of the decisions
below.

## System diagram

```
                        ┌──────────────────────────┐
                        │        Browser           │
                        │  index.html + app.js     │
                        │  (no build step)         │
                        └────────────┬─────────────┘
                                     │  JSON over HTTPS
                                     ▼
┌────────────────────────────────────────────────────────────────────┐
│                          FastAPI app                               │
│                                                                    │
│  middleware:  security headers → CORS → request id → rate limit    │
│                                                                    │
│  routers:     /api/auth      register, login, me                   │
│               /api/search    POST /  (the product)                 │
│               /api/threads   list, read, rename, share, delete     │
│               /api/public    health, shared threads                │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                     SearchEngine                             │  │
│  │                                                              │  │
│  │  1. retrieve   ──►  providers (wikipedia | ddg | tavily |    │  │
│  │                     searxng), run concurrently, merged       │  │
│  │  2. fetch      ──►  httpx + BeautifulSoup, cleaned to prose  │  │
│  │  3. rank       ──►  BM25 + title affinity + coverage         │  │
│  │  4. synthesise ──►  extractive (default) or LLM              │  │
│  │  5. persist    ──►  thread + query + sources                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  cache: TTL + LRU, keyed on (question, provider set)               │
└───────────────┬──────────────────────────────┬─────────────────────┘
                │                              │
                ▼                              ▼
        ┌───────────────┐              ┌──────────────────┐
        │  PostgreSQL   │              │  the open web    │
        │  (or SQLite)  │              │  Wikipedia API,  │
        │  SQLAlchemy   │              │  DDG, Tavily,    │
        │               │              │  SearXNG         │
        └───────────────┘              └──────────────────┘
```

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | FastAPI | Async, typed, OpenAPI for free |
| ORM | SQLAlchemy 2.0 | Works on Postgres and SQLite unchanged |
| Validation | Pydantic v2 | Bounded inputs at the edge |
| HTTP client | httpx | One async client, connection pooling |
| HTML parsing | BeautifulSoup + lxml | Tolerant of real-world markup |
| Auth | PyJWT + bcrypt | Boring, correct, no surprises |
| Frontend | Vanilla JS + CSS | No build step, no framework churn |
| Tests | pytest + TestClient | 136 tests, offline and deterministic |

## Data flow: one search

1. **Validate.** The question is trimmed, control characters stripped, length
   bounded to 3–500 chars. A `thread_id`, if present, must belong to the caller.

2. **Cache check.** Key is `sha256(question + provider set)`. A hit returns in
   under a millisecond. TTL is 15 minutes by default.

3. **Retrieve.** Every configured provider runs concurrently under a shared
   timeout. Results are merged and de-duplicated by normalised URL. A provider
   that fails is logged and skipped — one dead backend never fails the search.

4. **Fetch.** The top N URLs are fetched concurrently (semaphore-bounded, 8 at
   a time). Each page is cleaned: scripts, nav, footers, sidebars and reference
   lists removed; the article body kept as plain prose. A page that fails to
   fetch keeps its search snippet and is marked `fetched_ok: false`.

5. **Rank.** Each document gets a relevance score blending:
   - BM25 over the question tokens (the bulk of it),
   - a title-affinity term, so "Quantum computing" beats "Quantum computing in
     India" for the question *what is quantum computing*,
   - a small bonus for pages we actually read.

6. **Synthesise.** In extractive mode, sentences are scored against the
   question, de-duplicated, and the best few are assembled in source order with
   `[n]` markers. Captions and verbless labels are filtered out first — they
   match keywords but assert nothing.

7. **Persist.** For a signed-in user, the thread, query, answer and sources are
   written in one transaction. Anonymous searches are answered but not stored.

## Why extractive by default

An LLM can write a smoother paragraph. It can also invent a citation, and a
fabricated citation is worse than no answer at all — it looks checkable and
isn't.

Extractive synthesis cannot do that. Every sentence in the output is a sentence
that exists on a page we fetched, and the marker next to it points at that
page. The trade-off is real: the prose is less fluid, and it can only say what
the sources already say.

If you want the fluent version, set `ANSWER_PROVIDER=openai` (or `anthropic`)
and supply a key. The LLM path validates its own output: any citation outside
the range of supplied sources causes the answer to be rejected and the
extractive answer to be used instead. The guardrail is in
`app/search/answer.py::_valid_citations`.

## Scaling notes

**Stateless app tier.** No session state in the process; JWT carries identity.
Scale horizontally behind a load balancer with no sticky sessions.

**The cache is per-worker.** `TTLCache` lives in process memory. Behind N
workers you get N caches and a lower effective hit rate. Swap the store for
Redis — `TTLCache.get`/`set` are the only methods to reimplement.

**The rate limiter is per-worker too.** Same story: `SlidingWindowLimiter.check`
is the single method to port to Redis.

**Fetching is the bottleneck.** A search costs one provider round trip plus N
page fetches. Concurrency is capped by a semaphore (default 8) to stay polite
to origin sites. Raise it only if you also raise your own timeouts.

**Database.** SQLite is fine for a single instance and for development.
Postgres is the production target; the schema uses no SQLite-specific types.
Add Alembic before the second environment exists.

**Provider cost.** Wikipedia is free and unmetered. Tavily and SearXNG are the
paid/self-hosted options. Because providers are pluggable, you can start free
and add a paid backend later without touching the engine.

## Security posture

- Passwords: bcrypt, cost 12 by default. Inputs over 72 bytes are rejected
  rather than silently truncated.
- Tokens: HS256 JWT, 7-day expiry, `sub` = user id. A tampered or expired token
  is a 401, never a 500.
- Ownership: reading another user's thread returns **404, not 403**. A 403
  confirms the resource exists; a 404 does not.
- Login: unknown email and wrong password return the identical status and
  message, so the endpoint cannot be used to enumerate accounts.
- Headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and a CSP that allows only same-origin scripts.
- Rate limits: separate buckets for search, auth and writes.
- Secrets: read from the environment only. `.env.example` documents every one;
  no key is ever committed.

## Known limitations

- **Extractive answers read like a summary, not a conversation.** That is the
  price of the citation guarantee.
- **Wikipedia is the only keyless provider.** DuckDuckGo's HTML endpoint
  frequently blocks datacenter IPs, so it is off by default. For broad web
  coverage, supply a Tavily key or point at a SearXNG instance.
- **No JavaScript rendering.** Pages that build their content client-side come
  back nearly empty and fall back to their snippet.
- **No streaming.** The answer arrives in one response. Streaming would need
  SSE and a token-by-token synthesiser.
- **No Alembic migrations.** `create_all()` is used at startup.
