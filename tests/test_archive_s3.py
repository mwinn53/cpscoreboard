"""The archive's copy in S3 (app/archive_s3.py), against a fake S3 client."""

import asyncio

import pytest
from test_archive import eastern
from test_auth import make_admin, site  # noqa: F401 (fixture)

from app.archive import Archive
from app.archive_s3 import PREFIX, ArchiveCopy


class FakeS3:
    def __init__(self, fail=None):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail = fail

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        s3 = self

        class Pages:
            def paginate(self, Bucket, Prefix):
                if s3.fail:
                    raise s3.fail
                keys = sorted(k for k in s3.objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys[:2]]}   # two pages, like a real listing
                yield {"Contents": [{"Key": k} for k in keys[2:]]} if keys[2:] else {}
        return Pages()

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        assert ExtraArgs == {"ContentType": "application/gzip"}
        with open(path, "rb") as f:
            self.objects[key] = f.read()

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        del self.objects[Key]


def test_sync_uploads_new_days_and_retires_replaced_ones(tmp_path):
    a = Archive(tmp_path / "archive")
    s3 = FakeS3()
    copy = ArchiveCopy(a, "bucket", "us-east-1", client=s3)
    first = a.save(b"1", eastern(2026, 11, 13, 21)).name
    morning = a.save(b"2", eastern(2026, 11, 14, 9)).name
    assert copy.sync() == 2 and set(s3.objects) == {PREFIX + first, PREFIX + morning}
    assert copy.sync() == 0                               # nothing new
    evening = a.save(b"3", eastern(2026, 11, 14, 21)).name  # replaces the 14th's file
    assert copy.sync() == 1 and s3.deleted == [PREFIX + morning]
    assert set(s3.objects) == {PREFIX + first, PREFIX + evening}
    assert copy.status.remote == {first, evening} and copy.status.uploaded == 3 and copy.status.checked_at
    # an object for a day no longer on disk stays
    (tmp_path / "archive" / first).unlink()
    assert copy.sync() == 0 and PREFIX + first in s3.objects


@pytest.mark.anyio
async def test_a_failed_sync_is_reported_and_retried(tmp_path):
    a = Archive(tmp_path / "archive")
    a.save(b"1", eastern(2026, 11, 13, 21))
    s3 = FakeS3(fail=RuntimeError("AccessDenied"))
    copy = ArchiveCopy(a, "bucket", "us-east-1", interval=0.01, client=s3)
    task = asyncio.create_task(copy.run())
    await asyncio.sleep(0.05)
    assert copy.status.error == "AccessDenied" and not copy.status.checked_at
    s3.fail = None
    await asyncio.sleep(0.05)
    task.cancel()
    assert copy.status.error == "" and len(s3.objects) == 1


def test_admin_page_shows_what_is_in_s3(site, tmp_path):  # noqa: F811
    admin = make_admin(site)
    a = Archive(tmp_path / "archive")
    admin.app.state.archive = a
    assert "ARCHIVE_BUCKET" in admin.get("/admin/archive").text
    old = a.save(b"1", eastern(2026, 11, 13, 21)).name
    copy = ArchiveCopy(a, "cpsb-archive", "us-east-1", client=FakeS3())
    admin.app.state.archive_copy = copy
    assert "not checked yet" in admin.get("/admin/archive").text
    copy.sync()
    a.save(b"2", eastern(2026, 11, 14, 9))
    page = admin.get("/admin/archive").text
    assert "s3://cpsb-archive/archive/" in page and "1 file there" in page
    assert page.count("✓ yes") == 1 and "not yet" in page and old in page
