"""Device registration: email codes, devices, and approval state.

There are no accounts or passwords. A browser becomes a *device* by proving it
controls an email address (a 6-digit code), and the admin then approves it.
The browser holds a random token in a cookie; only its SHA-256 hash is stored,
so a database leak doesn't hand out working cookies.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (Boolean, Column, DateTime, Integer, String, Table, and_, delete, func,
                        insert, select, update)

from .store import SnapshotStore, add_missing_columns, metadata

CODE_TTL = timedelta(minutes=10)
CODE_MAX_ATTEMPTS = 5
CODES_PER_EMAIL = 3          # per CODE_WINDOW
CODES_PER_IP = 10            # per hour
CODE_WINDOW = timedelta(minutes=15)
RESEND_COOLDOWN = timedelta(seconds=30)
SEEN_UPDATE_EVERY = timedelta(minutes=5)

PENDING, APPROVED, REVOKED = "pending", "approved", "revoked"
RELATIONSHIP_MAX = 200  # "Your relationship to the team", asked at registration

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

devices = Table(
    "devices", metadata,
    Column("id", Integer, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("email", String(254), nullable=False, index=True),
    Column("label", String(100), nullable=False, default=""),
    Column("relationship", String(RELATIONSHIP_MAX), nullable=False, server_default=""),
    Column("status", String(16), nullable=False, default=PENDING),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False),
    Column("approved_at", DateTime),
    Column("expires_at", DateTime, nullable=False),
    Column("first_ip", String(64), nullable=False, default=""),
    Column("first_ua", String(512), nullable=False, default=""),
    Column("last_ip", String(64), nullable=False, default=""),
    Column("last_ua", String(512), nullable=False, default=""),
    Column("last_seen", DateTime, nullable=False),
)

email_codes = Table(
    "email_codes", metadata,
    Column("id", Integer, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),  # the short-lived registration cookie
    Column("email", String(254), nullable=False, index=True),
    Column("ip", String(64), nullable=False, default=""),
    Column("code_hash", String(64), nullable=False),
    Column("relationship", String(RELATIONSHIP_MAX), nullable=False, server_default=""),
    Column("salt", String(32), nullable=False),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("expires_at", DateTime, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("used", Boolean, nullable=False, default=False),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # stored naive UTC, like the rest of the database


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else dt.replace(tzinfo=UTC)


def clean_relationship(text: str) -> str:
    return " ".join(text.split())[:RELATIONSHIP_MAX]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _code_hash(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def normalize_email(email: str) -> str | None:
    email = email.strip().lower()
    return email if len(email) <= 254 and EMAIL_RE.match(email) else None


@dataclass(frozen=True)
class Device:
    id: int
    email: str
    label: str
    relationship: str
    status: str
    is_admin: bool
    created_at: datetime
    approved_at: datetime | None
    expires_at: datetime
    first_ip: str
    first_ua: str
    last_ip: str
    last_ua: str
    last_seen: datetime

    @property
    def expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)

    @property
    def approved(self) -> bool:
        return self.status == APPROVED and not self.expired

    @property
    def name(self) -> str:
        return self.label or self.email

    @classmethod
    def from_row(cls, row: Any) -> Device:
        m = row._mapping
        return cls(id=m["id"], email=m["email"], label=m["label"], relationship=m["relationship"],
                   status=m["status"],
                   is_admin=m["is_admin"], created_at=_aware(m["created_at"]),
                   approved_at=_aware(m["approved_at"]), expires_at=_aware(m["expires_at"]),
                   first_ip=m["first_ip"], first_ua=m["first_ua"], last_ip=m["last_ip"],
                   last_ua=m["last_ua"], last_seen=_aware(m["last_seen"]))


class RateLimited(Exception):
    pass


@dataclass(frozen=True)
class IssuedCode:
    reg_token: str  # goes in the registration cookie
    code: str       # goes in the email


class CodeCheck:
    OK, WRONG, EXPIRED, LOCKED, MISSING = "ok", "wrong", "expired", "locked", "missing"


class DeviceStore:
    def __init__(self, store: SnapshotStore, lifetime: timedelta = timedelta(days=365)):
        self.engine = store.engine
        self.lock = store.lock
        self.lifetime = lifetime
        metadata.create_all(self.engine)  # adds these tables to an existing database
        add_missing_columns(self.engine)

    # --- email codes ---

    def issue_code(self, email: str, ip: str, relationship: str = "") -> IssuedCode:
        now = _now()
        with self.lock, self.engine.begin() as conn:
            recent = conn.execute(select(func.count(), func.max(email_codes.c.created_at))
                                  .where(email_codes.c.email == email,
                                         email_codes.c.created_at > now - CODE_WINDOW)).one()
            if recent[0] >= CODES_PER_EMAIL:
                raise RateLimited("Too many codes requested for this address. Try again in 15 minutes.")
            if recent[1] is not None and recent[1] > now - RESEND_COOLDOWN:
                raise RateLimited("A code was just sent. Wait 30 seconds before asking for another.")
            by_ip = conn.scalar(select(func.count()).where(email_codes.c.ip == ip,
                                                           email_codes.c.created_at > now - timedelta(hours=1)))
            if ip and by_ip >= CODES_PER_IP:
                raise RateLimited("Too many codes requested from this network. Try again later.")

            code = f"{secrets.randbelow(10**6):06d}"
            salt = secrets.token_hex(8)
            reg_token = secrets.token_urlsafe(32)
            conn.execute(insert(email_codes).values(
                token_hash=hash_token(reg_token), email=email, ip=ip, code_hash=_code_hash(code, salt),
                relationship=clean_relationship(relationship),
                salt=salt, created_at=now, expires_at=now + CODE_TTL, attempts=0, used=False))
            # Housekeeping: codes are only useful for minutes.
            conn.execute(delete(email_codes).where(email_codes.c.created_at < now - timedelta(days=2)))
        return IssuedCode(reg_token, code)

    def pending_email(self, reg_token: str | None) -> str | None:
        """The address a registration cookie is verifying, if it's still usable."""
        if not reg_token:
            return None
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(select(email_codes).where(email_codes.c.token_hash == hash_token(reg_token))).first()
        if row is None or row.used or row.expires_at <= _now() or row.attempts >= CODE_MAX_ATTEMPTS:
            return None
        return row.email

    def relationship_for(self, reg_token: str | None) -> str:
        """What the visitor said about themselves when requesting this code."""
        if not reg_token:
            return ""
        with self.lock, self.engine.connect() as conn:
            value = conn.scalar(select(email_codes.c.relationship)
                                .where(email_codes.c.token_hash == hash_token(reg_token)))
        return value or ""

    def check_code(self, reg_token: str | None, code: str) -> tuple[str, str | None]:
        """Returns (result, email). On OK the code is consumed."""
        if not reg_token:
            return CodeCheck.MISSING, None
        code = re.sub(r"\D", "", code)
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(select(email_codes).where(email_codes.c.token_hash == hash_token(reg_token))).first()
            if row is None or row.used:
                return CodeCheck.MISSING, None
            if row.expires_at <= _now():
                return CodeCheck.EXPIRED, row.email
            if row.attempts >= CODE_MAX_ATTEMPTS:
                return CodeCheck.LOCKED, row.email
            if not hmac.compare_digest(_code_hash(code, row.salt), row.code_hash):
                conn.execute(update(email_codes).where(email_codes.c.id == row.id)
                             .values(attempts=email_codes.c.attempts + 1))
                locked = row.attempts + 1 >= CODE_MAX_ATTEMPTS
                return (CodeCheck.LOCKED if locked else CodeCheck.WRONG), row.email
            conn.execute(update(email_codes).where(email_codes.c.id == row.id).values(used=True))
            return CodeCheck.OK, row.email

    # --- devices ---

    def create_device(self, email: str, ip: str, ua: str, relationship: str = "") -> tuple[str, Device]:
        """Register a browser as a new pending device. Returns (cookie token, device)."""
        token = secrets.token_urlsafe(32)
        now = _now()
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(insert(devices).values(
                token_hash=hash_token(token), email=email, label="", status=PENDING, is_admin=False,
                relationship=clean_relationship(relationship),
                created_at=now, expires_at=now + self.lifetime, first_ip=ip, first_ua=ua[:512],
                last_ip=ip, last_ua=ua[:512], last_seen=now))
            row = conn.execute(select(devices).where(devices.c.id == result.inserted_primary_key[0])).one()
        return token, Device.from_row(row)

    def lookup(self, token: str | None) -> Device | None:
        if not token:
            return None
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(select(devices).where(devices.c.token_hash == hash_token(token))).first()
        return Device.from_row(row) if row else None

    def get(self, device_id: int) -> Device | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(select(devices).where(devices.c.id == device_id)).first()
        return Device.from_row(row) if row else None

    def touch(self, device: Device, ip: str, ua: str) -> None:
        """Record activity, at most every few minutes unless the IP or browser changed."""
        if (device.last_ip == ip and device.last_ua == ua[:512]
                and datetime.now(UTC) - device.last_seen < SEEN_UPDATE_EVERY):
            return
        with self.lock, self.engine.begin() as conn:
            conn.execute(update(devices).where(devices.c.id == device.id)
                         .values(last_ip=ip, last_ua=ua[:512], last_seen=_now()))

    def list(self) -> list[Device]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(select(devices).order_by(devices.c.created_at.desc())).all()
        return [Device.from_row(r) for r in rows]

    def count_admins(self) -> int:
        with self.lock, self.engine.connect() as conn:
            return conn.scalar(select(func.count()).where(and_(devices.c.is_admin, devices.c.status == APPROVED)))

    def _set(self, device_id: int, **values: Any) -> bool:
        with self.lock, self.engine.begin() as conn:
            return conn.execute(update(devices).where(devices.c.id == device_id).values(**values)).rowcount > 0

    def approve(self, device_id: int) -> bool:
        now = _now()
        # The lifetime runs from approval, so a long wait in the queue doesn't eat into it.
        return self._set(device_id, status=APPROVED, approved_at=now, expires_at=now + self.lifetime)

    def revoke(self, device_id: int) -> bool:
        return self._set(device_id, status=REVOKED)

    def set_label(self, device_id: int, label: str) -> bool:
        return self._set(device_id, label=label.strip()[:100])

    def make_admin(self, device_id: int) -> bool:
        now = _now()
        return self._set(device_id, is_admin=True, status=APPROVED, approved_at=now, expires_at=now + self.lifetime)

    def delete(self, device_id: int) -> bool:
        with self.lock, self.engine.begin() as conn:
            return conn.execute(delete(devices).where(devices.c.id == device_id)).rowcount > 0


def describe_ua(ua: str) -> str:
    """A short 'Browser on OS' summary of a user-agent string, for the admin page."""
    if not ua:
        return "unknown browser"
    browser = next((name for pat, name in [
        (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"), (r"CriOS|Chrome/", "Chrome"),
        (r"Safari/", "Safari"), (r"curl/", "curl"), (r"python|httpx|requests", "script")] if re.search(pat, ua)),
        "Browser")
    system = next((name for pat, name in [
        (r"iPhone|iPad|iPod", "iOS"), (r"Android", "Android"), (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux")] if re.search(pat, ua)),
        "")
    return f"{browser} on {system}" if system else browser
