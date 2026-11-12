# Setup

## Requirements

- Python 3.11 or newer
- pip
- Optional: Docker + Docker Compose, if you'd rather not install Python deps
- Optional: a Tavily API key, if you want broad web coverage

## Local install

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-19-jugnu.git
cd day-19-jugnu

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

`pip install -e .` installs the runtime dependencies. The `[dev]` extra adds
pytest, ruff and the test client.

## Configure

```bash
cp .env.example .env
```

The defaults work with no edits. The app will use Wikipedia as its only search
provider and extractive synthesis, which needs no API key and costs nothing.

If you want to change something, open `.env` and edit. Every variable is
documented inline.

### Getting a Tavily key (optional)

Wikipedia covers encyclopedic questions well. For news, product pages and
general web results, add Tavily:

1. Sign up at <https://tavily.com> — there is a free tier.
2. Copy the key into `.env` as `TAVILY_API_KEY=tvly-...`.
3. Set `SEARCH_PROVIDERS=wikipedia,tavily`.

### Running your own SearXNG (optional)

If you'd rather not depend on a third party at all:

```bash
docker run -d --name searxng -p 8888:8080 searxng/searxng
```

Then in `.env`:

```
SEARXNG_URL=http://localhost:8888
SEARCH_PROVIDERS=wikipedia,searxng
```

SearXNG needs `format: json` enabled in its `settings.yml` for the API to
respond.

## Database

The default is SQLite at `./jugnu.db`, created automatically on first start.
Nothing to do.

For Postgres, set `DATABASE_URL`:

```
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/jugnu
```

Tables are created at startup. There are no migrations yet — if you change a
model, drop the database or add Alembic.

## Seed a demo account

```bash
python -m app.seed
```

Creates `demo@jugnu.app` / `demo12345` and runs one search so the history view
is not empty. Safe to run more than once.

## Run

```bash
uvicorn app.main:app --reload
```

- App: <http://127.0.0.1:8000>
- Interactive API docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/api/health>

## Docker

```bash
docker compose up --build
```

This starts the app on port 8000 and Postgres on 5432, with the app pointed at
Postgres automatically. Data persists in a named volume.

To stop and remove everything including the database volume:

```bash
docker compose down -v
```

## Tests and linting

```bash
pytest -q                    # 136 tests, ~2 seconds, no network
ruff check .                 # lint
ruff format --check .        # formatting
ruff check --fix . && ruff format .   # fix both
```

## Troubleshooting

**`ModuleNotFoundError: No module named 'app'`**
Run commands from the repository root, and make sure you installed with
`pip install -e .` rather than just `pip install .`.

**Searches return nothing**
Check `/api/health` — it reports which providers are actually available. If
`wikipedia` is missing, the sandbox or network is blocking outbound HTTPS.

**`429 Too Many Requests`**
The rate limiter is working. Defaults are 20 searches/minute and 10 auth
attempts/minute per identity. Raise them in `.env` or set
`RATE_LIMIT_ENABLED=false` for local development.

**Answers are short and choppy**
That is extractive synthesis doing its job — it can only quote what the sources
say. Add a Tavily key for more sources, or set `ANSWER_PROVIDER=openai` with a
key for fluent prose.

**`sqlite3.OperationalError: database is locked`**
Two processes are writing the same SQLite file. Stop the extra one, or move to
Postgres.
