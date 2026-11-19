"""A copy of the season archive (app/archive.py) in S3, besides the EBS snapshots.

Every ``ARCHIVE_SYNC_MINUTES`` (and once at startup) the daily files are compared with
the bucket under ``archive/``: a file S3 doesn't have is uploaded, and an object a newer
file of the same day has replaced is deleted, so the bucket mirrors the folder and can
be replayed after ``aws s3 sync``. The bucket is versioned (a deleted or replaced
object stays as a noncurrent version for a while) and moves to Glacier after the
season (infra/archive.tf). Off unless ``ARCHIVE_BUCKET`` is set.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .archive import NAME_RE, Archive

log = logging.getLogger(__name__)

PREFIX = "archive/"


@dataclass
class CopyStatus:
    checked_at: datetime | None = None    # the last sync that reached the bucket
    error: str = ""                         # the last sync's error, if it failed
    remote: set[str] = field(default_factory=set)   # file names in the bucket
    uploaded: int = 0                       # files uploaded since startup


class ArchiveCopy:
    def __init__(self, archive: Archive, bucket: str, region: str, interval: float = 3600, client=None):
        self.archive = archive
        self.bucket = bucket
        self.region = region
        self.interval = interval
        self._client = client
        self.status = CopyStatus()

    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _remote(self) -> set[str]:
        names = set()
        for page in self.client().get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=PREFIX):
            for obj in page.get("Contents", []):
                names.add(obj["Key"].removeprefix(PREFIX))
        return names

    def sync(self) -> int:
        """Upload what's missing and delete what a newer file of its day replaced; the number uploaded."""
        s3 = self.client()
        remote = self._remote()
        local = self.archive.files()                 # newest first
        latest: dict = {}
        for f in local:
            latest.setdefault(f.day, f.name)
        uploaded = 0
        for f in local:
            if f.name in remote or latest[f.day] != f.name:
                continue
            path = self.archive.path(f.name)
            if path is None:                          # replaced since the listing
                continue
            s3.upload_file(str(path), self.bucket, PREFIX + f.name, ExtraArgs={"ContentType": "application/gzip"})
            remote.add(f.name)
            uploaded += 1
        for name in sorted(remote):
            day = self.archive.day_of(name) if NAME_RE.match(name) else None
            if day is not None and latest.get(day) not in (None, name) and latest[day] in remote:
                s3.delete_object(Bucket=self.bucket, Key=PREFIX + name)
                remote.discard(name)
        self.status = CopyStatus(datetime.now(UTC), "", remote, self.status.uploaded + uploaded)
        if uploaded:
            log.info("Archive copy: uploaded %d file(s) to s3://%s/%s", uploaded, self.bucket, PREFIX)
        return uploaded

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.sync)
            except Exception as e:  # noqa: BLE001 (network, permissions: shown on /admin/archive, retried)
                log.warning("Archive copy to S3 failed: %s", e)
                self.status.error = str(e) or type(e).__name__
            await asyncio.sleep(self.interval)
