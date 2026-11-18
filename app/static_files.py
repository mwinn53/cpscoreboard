"""Static files with long-lived caching.

Pages link to ``/static/<file>?v=<content hash>`` (``static_url`` in the templates),
so a changed file gets a new URL. Those requests are answered with a one-year,
immutable cache lifetime: after the first visit, a page load doesn't re-check the
stylesheet or the scripts at all. A request without ``v`` (an old page, or a typed
URL) still gets the file, with the default re-check.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).parent / "static"
IMMUTABLE = "public, max-age=31536000, immutable"


@lru_cache(maxsize=None)
def _version(path: str) -> str:
    try:
        return hashlib.sha256((STATIC / path).read_bytes()).hexdigest()[:10]
    except OSError:
        return ""


def static_url(path: str) -> str:
    """/static/<path>?v=<hash of its contents> (hashed once per process; files only change with a deploy)."""
    v = _version(path)
    return f"/static/{path}" + (f"?v={v}" if v else "")


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and b"v=" in scope.get("query_string", b""):
            response.headers["Cache-Control"] = IMMUTABLE
        return response
