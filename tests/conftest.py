import gzip
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
S17 = FIXTURES / "scores_s17_2024-11-21.json.gz"  # season 17: has adjustment/score_3/total
S19 = FIXTURES / "scores_s19_2026-11-13.json.gz"  # season 19: has tier, no totals


def load(path: Path) -> bytes:
    with gzip.open(path, "rb") as f:
        return f.read()


@pytest.fixture
def anyio_backend():
    return "asyncio"
