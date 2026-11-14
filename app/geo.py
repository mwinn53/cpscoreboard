"""Approximate location of device IPs for the admin page (issue #8), looked up offline.

Uses DB-IP's free "IP to City Lite" database (CC BY 4.0, attribution shown on the
admin page): downloaded once a month to ``<DATA_DIR>/geoip/`` and read locally, so
no viewer's IP is ever sent to a third party. Lookups happen when the admin page
renders; nothing extra is stored. Private and unknown addresses show nothing.
"""

from __future__ import annotations

import asyncio
import gzip
import ipaddress
import logging
import os
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DB_NAME = "dbip-city-lite.mmdb"
URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
MAX_AGE = 35 * 86400  # seconds; DB-IP publishes monthly
ATTRIBUTION = ("IP geolocation by DB-IP", "https://db-ip.com")


def _months(now: datetime) -> list[str]:
    """This month and last month (the new file appears early in the month)."""
    prev = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    return [f"{now.year}-{now.month:02d}", f"{prev[0]}-{prev[1]:02d}"]


class Geo:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / DB_NAME
        self._reader = None
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}
        self._open()

    def _open(self) -> None:
        if not self.path.is_file():
            return
        try:
            import maxminddb
            reader = maxminddb.open_database(str(self.path), maxminddb.MODE_MMAP)
        except Exception as e:
            log.warning("Can't open the geolocation database %s: %s", self.path, e)
            return
        with self._lock:
            old, self._reader = self._reader, reader
            self._cache.clear()
        if old is not None:
            old.close()

    @property
    def available(self) -> bool:
        return self._reader is not None

    def stale(self) -> bool:
        return not self.path.is_file() or time.time() - self.path.stat().st_mtime > MAX_AGE

    def locate(self, ip: str) -> str:
        """"City, Region, CC" for a public IP, else ""."""
        if not ip or self._reader is None:
            return ""
        if ip in self._cache:
            return self._cache[ip]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return ""
        place = ""
        if addr.is_global:
            with self._lock:
                rec = self._reader.get(ip) if self._reader else None
            if isinstance(rec, dict):
                city = (rec.get("city") or {}).get("names", {}).get("en", "")
                subs = rec.get("subdivisions") or [{}]
                region = (subs[0] or {}).get("names", {}).get("en", "")
                country = (rec.get("country") or {}).get("iso_code", "")
                place = ", ".join(p for p in (city, region, country) if p)
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[ip] = place
        return place

    async def refresh(self, client: httpx.AsyncClient) -> bool:
        """Download this month's database if ours is missing or over a month old."""
        if not self.stale():
            return False
        self.directory.mkdir(parents=True, exist_ok=True)
        for month in _months(datetime.now(UTC)):
            url = URL.format(month=month)
            tmp = self.directory / (DB_NAME + ".download")
            try:
                async with client.stream("GET", url, timeout=300) as resp:
                    if resp.status_code != 200:
                        continue
                    with open(tmp, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                await asyncio.to_thread(self._install, tmp)
            except Exception as e:
                log.warning("Geolocation database download failed (%s): %s", url, e)
                tmp.unlink(missing_ok=True)
                continue
            log.info("Geolocation database updated from %s", url)
            return True
        return False

    def _install(self, gz: Path) -> None:
        out = self.path.with_name(DB_NAME + ".tmp")
        with gzip.open(gz, "rb") as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        gz.unlink(missing_ok=True)
        os.replace(out, self.path)
        self._open()

    async def run(self, client: httpx.AsyncClient) -> None:
        """Keep the database current: check now, then daily."""
        while True:
            try:
                await self.refresh(client)
            except Exception:
                log.exception("Geolocation refresh failed")
            await asyncio.sleep(86400)
