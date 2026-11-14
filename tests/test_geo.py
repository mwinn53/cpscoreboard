"""Approximate device locations from the offline DB-IP database (#8)."""

import asyncio
import gzip
import os
import time
from datetime import UTC, datetime

import httpx

from app.geo import DB_NAME, Geo, _months
from test_auth import make_admin, site  # noqa: F401 (fixture)

RECORD = {"city": {"names": {"en": "Augusta"}}, "subdivisions": [{"names": {"en": "Georgia"}}],
          "country": {"iso_code": "US"}}


class FakeReader:
    def __init__(self):
        self.calls = 0

    def get(self, ip):
        self.calls += 1
        return RECORD if ip == "8.8.8.8" else None

    def close(self):
        pass


def test_locate(tmp_path):
    geo = Geo(tmp_path)
    assert not geo.available and geo.locate("8.8.8.8") == ""
    geo._reader = reader = FakeReader()
    assert geo.locate("8.8.8.8") == "Augusta, Georgia, US"
    assert geo.locate("8.8.8.8") == "Augusta, Georgia, US" and reader.calls == 1  # cached
    assert geo.locate("192.168.1.5") == "" and geo.locate("127.0.0.1") == ""  # private: never looked up
    assert geo.locate("not an ip") == "" and geo.locate("") == ""
    assert geo.locate("1.1.1.1") == ""  # unknown


def test_months_wrap_the_year():
    assert _months(datetime(2027, 1, 3, tzinfo=UTC)) == ["2027-01", "2026-12"]
    assert _months(datetime(2026, 11, 14, tzinfo=UTC)) == ["2026-11", "2026-10"]


def test_refresh_downloads_when_missing_or_old_and_falls_back_a_month(tmp_path):
    asked = []

    def handler(request):
        asked.append(request.url.path)
        if request.url.path.endswith(f"{_months(datetime.now(UTC))[0]}.mmdb.gz"):
            return httpx.Response(404)  # this month's file isn't out yet
        return httpx.Response(200, content=gzip.compress(b"fake mmdb"))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            geo = Geo(tmp_path)
            first = await geo.refresh(client)
            second = await geo.refresh(client)  # fresh now: no download
            return geo, first, second

    geo, first, second = asyncio.run(go())
    assert first and not second and len(asked) == 2
    assert (tmp_path / DB_NAME).read_bytes() == b"fake mmdb"
    old = time.time() - 40 * 86400
    os.utime(tmp_path / DB_NAME, (old, old))
    assert geo.stale()


def test_admin_page_and_attribution(site):  # noqa: F811
    admin = make_admin(site)
    geo = Geo(admin.app.state.settings.data_dir / "nowhere")
    geo._reader = FakeReader()
    admin.app.state.geo = geo
    store = admin.app.state.devices
    with store.engine.begin() as conn:
        from sqlalchemy import update

        from app.devices import devices
        conn.execute(update(devices).values(first_ip="8.8.8.8"))  # last_ip is rewritten by each request
    page = admin.get("/admin").text
    assert "Augusta, Georgia, US" in page and "IP geolocation by DB-IP" in page
