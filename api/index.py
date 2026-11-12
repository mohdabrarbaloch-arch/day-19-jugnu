"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level `app` (or `handler`) in this
file. We just re-export the FastAPI application.

Note: Vercel's filesystem is read-only except /tmp, and /tmp does not persist
between invocations. With the default SQLite database, data will not survive.
Set DATABASE_URL to a hosted Postgres for a real deployment.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repository root importable so `app.*` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app

# Vercel's Python runtime accepts either name.
handler = app

__all__ = ["app", "handler"]
