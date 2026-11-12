# API reference

Base URL: `http://127.0.0.1:8000` in development.

All request and response bodies are JSON. Authenticated endpoints expect:

```
Authorization: Bearer <access_token>
```

Interactive docs are served at `/docs` (Swagger) and `/redoc`.

## Conventions

**Status codes**

| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created |
| 204 | No content (successful delete) |
| 401 | Missing, malformed or expired token |
| 404 | Not found — **or** not yours |
| 409 | Conflict (email already registered) |
| 422 | Validation failed |
| 429 | Rate limited |
| 500 | Server error |

**Ownership.** Reading another user's thread returns `404`, not `403`. A `403`
would confirm the resource exists; a `404` does not.

**Errors** are always `{"detail": "..."}`. Validation errors add a structured
`errors` array.

---

## Health

### `GET /api/health`

No auth. Use this to check the app and its providers.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "database": "ok",
  "providers": ["wikipedia"],
  "answer_provider": "extractive"
}
```

`providers` lists only the backends that are actually usable — a provider
without its key configured is omitted.

---

## Auth

### `POST /api/auth/register`

Creates an account and returns a token. Rate limited to 10/minute per IP.

```json
{
  "email": "you@example.com",
  "password": "at-least-8-chars",
  "display_name": "Your Name"
}
```

`display_name` is optional; it defaults to the part of the email before `@`.

**201**

```json
{
  "access_token": "eyJhbGciOi…",
  "token_type": "bearer",
  "user": {
    "id": "…",
    "email": "you@example.com",
    "display_name": "Your Name",
    "created_at": "2026-11-12T19:12:11Z"
  }
}
```

**409** — email already registered.
**422** — invalid email, password under 8 characters, or password with no
letter and no digit.

### `POST /api/auth/login`

```json
{ "email": "you@example.com", "password": "at-least-8-chars" }
```

**200** — same shape as register.

**401** — `{"detail": "Incorrect email or password"}`. Deliberately identical
for an unknown email and a wrong password, so the endpoint cannot be used to
discover which accounts exist.

### `GET /api/auth/me`

Requires auth. Returns the current user object.

---

## Search

### `POST /api/search`

The main endpoint. Works with or without auth.

```json
{
  "question": "what is a vector database",
  "thread_id": "optional-existing-thread-id"
}
```

- `question`: 3–500 characters. Control characters are stripped.
- `thread_id`: optional. If given, the query is appended to that thread. If the
  thread belongs to someone else, or you are anonymous, this is a **401**.

**200**

```json
{
  "thread_id": "6a500d7a8fe4488da1db2cc530da8383",
  "thread_title": "what is a vector database",
  "query": {
    "id": "0883e7c0c0fd46c6a96b02aa857a57e6",
    "question": "what is a vector database",
    "answer": "A vector database … in vector space. [1] Vector databases typically … [1]",
    "provider_used": "wikipedia",
    "answer_provider": "extractive",
    "latency_ms": 1652,
    "source_count": 6,
    "created_at": "2026-11-12T19:12:11.094714",
    "sources": [
      {
        "rank": 1,
        "title": "Vector database - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Vector_database",
        "domain": "en.wikipedia.org",
        "snippet": "A vector database, vector store or vector search engine …",
        "published_at": "2026-11-07T21:34:02Z",
        "relevance": 0.86,
        "fetched_ok": true
      }
    ]
  },
  "follow_ups": [
    "How does Similarity search work?",
    "What are the latest developments in Milvus?"
  ]
}
```

Notes on the fields:

- `answer` contains `[n]` markers. `n` is 1-based and indexes `sources`.
- `fetched_ok: false` means the page could not be fetched and the source is
  represented by its search snippet only.
- `relevance` is 0–1, for sorting. It is not a confidence score.
- `thread_id` is `""` for anonymous searches — nothing was persisted.

**401** — `thread_id` given but not authenticated, or not yours.
**422** — question too short or too long.
**429** — over 20 searches/minute.

### `GET /api/search/suggest?q=<prefix>`

Returns up to 5 example questions matching a prefix. Used for the suggestion
chips. No auth.

```json
{ "suggestions": ["What is a vector database?", "…"] }
```

---

## Threads

All thread endpoints require auth.

### `GET /api/threads`

Lists your threads, newest first.

```json
[
  {
    "id": "6a500d7a…",
    "title": "what is a vector database",
    "is_public": false,
    "share_slug": null,
    "query_count": 1,
    "created_at": "2026-11-12T19:12:11Z",
    "updated_at": "2026-11-12T19:12:11Z"
  }
]
```

### `GET /api/threads/{thread_id}`

Full thread with every query and its sources.

```json
{
  "id": "6a500d7a…",
  "title": "what is a vector database",
  "is_public": false,
  "share_slug": null,
  "created_at": "…",
  "updated_at": "…",
  "queries": [ { "…same shape as the search response's query…" } ]
}
```

**404** — does not exist, or is not yours.

### `PATCH /api/threads/{thread_id}?title=<new title>`

Renames a thread. Title is 1–200 characters.

**200** — the updated thread summary.
**404** — not yours.

### `POST /api/threads/{thread_id}/share`

Makes the thread public and returns its slug. Idempotent — calling it twice
returns the same slug.

```json
{ "share_slug": "AbC123xYz", "is_public": true }
```

The public URL is `/s/<share_slug>`.

### `DELETE /api/threads/{thread_id}`

Deletes the thread and all its queries and sources.

**204** — deleted.
**404** — not yours.

---

## Public

### `GET /api/public/threads/{share_slug}`

Reads a shared thread with no authentication. Returns the same shape as
`GET /api/threads/{id}`.

**404** — no such slug, or the thread is no longer public.

---

## Rate limits

| Bucket | Limit | Scope |
|---|---|---|
| Search | 20 / minute | per user, else per IP |
| Auth | 10 / minute | per IP |
| Writes | 60 / minute | per user, else per IP |

A `429` includes a `Retry-After` header in seconds.

Limits are per worker process. Behind multiple workers the effective limit is
`limit × workers`; move the store to Redis if that matters.

---

## Examples

### Ask anonymously

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"question": "who was Ada Lovelace"}'
```

### Register, then ask with history

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"hunter2secure","display_name":"Me"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "what is quantum computing"}'
```

### Follow up in the same thread

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question": "what is a qubit", "thread_id": "6a500d7a…"}'
```

### Share a thread

```bash
curl -X POST http://127.0.0.1:8000/api/threads/6a500d7a…/share \
  -H "Authorization: Bearer $TOKEN"
# → {"share_slug": "AbC123xYz", "is_public": true}
# Public URL: http://127.0.0.1:8000/s/AbC123xYz
```
