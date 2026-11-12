"""Seed a demo account and one real search.

Run with:  python -m app.seed

Idempotent — running it twice does not create a second account. The search is
real: it goes out to the configured provider, so the demo history contains an
answer that actually came from a page.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")

DEMO_EMAIL = "demo@jugnu.app"
DEMO_PASSWORD = "demo12345"
DEMO_NAME = "Demo User"
DEMO_QUESTION = "what is a vector database"


def ensure_user() -> User:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing:
            log.info("Demo account already exists: %s", DEMO_EMAIL)
            return existing

        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name=DEMO_NAME,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        log.info("Created demo account: %s / %s", DEMO_EMAIL, DEMO_PASSWORD)
        return user


async def run_demo_search(user_id: str) -> None:
    # Imported here so the module can be imported without a running event loop.
    from app.search.engine import engine as search_engine

    log.info("Running a real search: %r", DEMO_QUESTION)
    try:
        result = await search_engine.search(DEMO_QUESTION)
    except Exception as exc:
        log.warning("Search failed (%s). The account is still usable.", exc)
        return

    from app.models import Query, Source, Thread

    with SessionLocal() as db:
        thread = Thread(user_id=user_id, title=DEMO_QUESTION[:200])
        db.add(thread)
        db.flush()

        query = Query(
            thread_id=thread.id,
            question=DEMO_QUESTION,
            answer=result.answer.text,
            provider_used=result.provider,
            answer_provider=result.answer.provider,
            latency_ms=result.latency_ms,
            source_count=len(result.documents),
        )
        db.add(query)
        db.flush()

        for rank, doc in enumerate(result.documents, start=1):
            db.add(
                Source(
                    query_id=query.id,
                    rank=rank,
                    title=doc.title[:300],
                    url=doc.url,
                    domain=doc.domain,
                    snippet=doc.snippet[:1000],
                    relevance=doc.relevance,
                    fetched_ok=doc.fetched_ok,
                )
            )

        db.commit()
        log.info("Seeded one thread with %d sources.", len(result.documents))


def main() -> None:
    Base.metadata.create_all(bind=engine)
    user = ensure_user()
    asyncio.run(run_demo_search(user.id))
    log.info("")
    log.info("Done. Start the app and sign in with:")
    log.info("  email:    %s", DEMO_EMAIL)
    log.info("  password: %s", DEMO_PASSWORD)


if __name__ == "__main__":
    main()
