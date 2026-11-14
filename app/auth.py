"""Access control and the registration → verification → approval flow.

    /register  email ──► 6-digit code emailed (10 min, 5 tries)
    /verify    code  ──► device created as *pending*, device cookie set, admin notified
    /pending   waits (polls) until the admin approves, then on to the dashboard
    /admin     approve / revoke / rename / delete devices
    /admin/claim  a registered device + ADMIN_BOOTSTRAP_TOKEN → that device becomes admin

Pages get a redirect to the right step; API, partial and event requests get 401/403.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .devices import APPROVED, PENDING, REVOKED, CodeCheck, Device, DeviceStore, RateLimited, normalize_email
from .templating import templates

log = logging.getLogger(__name__)

DEVICE_COOKIE = "cpsb_device"
REG_COOKIE = "cpsb_reg"

CLAIM_MAX_FAILURES = 5          # wrong admin tokens per IP...
CLAIM_WINDOW = 15 * 60          # ...per this many seconds

router = APIRouter()


class NotAllowed(Exception):
    """Raised by the access dependencies; turned into a redirect (pages) or an error (API)."""

    def __init__(self, status: int, message: str, redirect_to: str | None = None):
        self.status, self.message, self.redirect_to = status, message, redirect_to


def _is_page(request: Request) -> bool:
    path = request.url.path
    return not (path.startswith(("/api/", "/events", "/partials/")))


async def not_allowed_handler(request: Request, exc: NotAllowed) -> Response:
    if exc.redirect_to and request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": exc.redirect_to})  # htmx navigates
    if exc.redirect_to and _is_page(request):
        return RedirectResponse(exc.redirect_to, status_code=303)
    if _is_page(request):
        return templates.TemplateResponse(request, "message.html", {"title": "Not allowed", "message": exc.message},
                                          status_code=exc.status)
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


def _devices(request: Request) -> DeviceStore:
    return request.app.state.devices


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


async def current_device(request: Request) -> Device | None:
    return await asyncio.to_thread(_devices(request).lookup, request.cookies.get(DEVICE_COOKIE))


async def require_viewer(request: Request) -> Device | None:
    """Dependency for everything behind approval. Sets request.state.device."""
    if not request.app.state.settings.auth_enabled:
        request.state.device = None
        return None
    device = await current_device(request)
    if device is None or device.expired:
        raise NotAllowed(401, "Register this browser to view the scoreboard.", "/register")
    if device.status == PENDING:
        raise NotAllowed(403, "This browser is waiting for approval.", "/pending")
    if device.status == REVOKED:
        raise NotAllowed(403, "Access for this browser has been revoked.", "/blocked")
    await asyncio.to_thread(_devices(request).touch, device, client_ip(request), user_agent(request))
    request.state.device = device
    return device


async def require_admin(request: Request) -> Device:
    if not request.app.state.settings.auth_enabled:
        raise NotAllowed(403, "The admin page needs AUTH_ENABLED=true.")
    device = await require_viewer(request)
    if not device.is_admin:
        raise NotAllowed(403, "Only the admin can open this page.")
    return device


def same_origin(request: Request) -> None:
    """Reject cross-site form posts (defence in depth on top of SameSite=Lax cookies)."""
    origin = request.headers.get("origin")
    if origin and origin != "null" and urlsplit(origin).netloc != request.headers.get("host"):
        raise NotAllowed(403, "Cross-site request refused.")


def _set_cookie(request: Request, response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax",
                        secure=request.app.state.settings.secure_cookies, path="/")


async def _send(request: Request, to: str, subject: str, text: str) -> bool:
    try:
        await asyncio.to_thread(request.app.state.mailer.send, to, subject, text)
        return True
    except Exception:
        log.exception("Sending email to %s failed", to)
        return False


def _page(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


# --- Registration ---

@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    device = await current_device(request)
    if device is not None and not device.expired:
        if device.status == APPROVED:
            return RedirectResponse("/", status_code=303)
        if device.status == PENDING:
            return RedirectResponse("/pending", status_code=303)
    return _page(request, "register.html", email="", error=None)


@router.post("/register", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def register_submit(request: Request, email: str = Form("")):
    address = normalize_email(email)
    if address is None:
        return _page(request, "register.html", 400, email=email, error="Enter a valid email address.")
    try:
        issued = await asyncio.to_thread(_devices(request).issue_code, address, client_ip(request))
    except RateLimited as e:
        return _page(request, "register.html", 429, email=email, error=str(e))

    sent = await _send(request, address, f"Your {request.app.state.settings.site_title} code: {issued.code}",
                       f"Your verification code is {issued.code}\n\n"
                       "Enter it on the page where you requested it. It expires in 10 minutes.\n\n"
                       "If you didn't ask for this, you can ignore this email.")
    if not sent:
        return _page(request, "register.html", 502, email=email,
                     error="We couldn't send the email. Check the address and try again in a minute.")
    response = RedirectResponse("/verify", status_code=303)
    _set_cookie(request, response, REG_COOKIE, issued.reg_token, max_age=15 * 60)
    return response


@router.get("/verify", response_class=HTMLResponse)
async def verify_form(request: Request):
    email = await asyncio.to_thread(_devices(request).pending_email, request.cookies.get(REG_COOKIE))
    if email is None:
        return RedirectResponse("/register", status_code=303)
    return _page(request, "verify.html", email=email, error=None)


@router.post("/verify", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def verify_submit(request: Request, code: str = Form("")):
    devices = _devices(request)
    result, email = await asyncio.to_thread(devices.check_code, request.cookies.get(REG_COOKIE), code)
    if result == CodeCheck.WRONG:
        return _page(request, "verify.html", 400, email=email, error="That code isn't right. Check the email and try again.")
    if result != CodeCheck.OK:
        reason = {CodeCheck.EXPIRED: "That code has expired.",
                  CodeCheck.LOCKED: "Too many wrong attempts."}.get(result, "That code is no longer valid.")
        return _page(request, "register.html", 400, email=email or "", error=f"{reason} Request a new code.")

    ip, ua = client_ip(request), user_agent(request)
    token, device = await asyncio.to_thread(devices.create_device, email, ip, ua)
    log.info("Device %d registered for %s (%s, %s)", device.id, email, ip, ua[:80])

    notify = request.app.state.settings.admin_notify_email
    if notify:
        admin_url = str(request.url_for("admin_page"))
        await _send(request, notify, f"{request.app.state.settings.site_title}: {email} is waiting for approval",
                    f"A new device is waiting for your approval.\n\n"
                    f"Email:   {email}\nBrowser: {templates.env.filters['browser'](ua)}\nIP:      {ip}\n\n"
                    f"Review it here: {admin_url}\n")

    response = RedirectResponse("/pending", status_code=303)
    _set_cookie(request, response, DEVICE_COOKIE, token,
                max_age=request.app.state.settings.device_lifetime_days * 86400)
    response.delete_cookie(REG_COOKIE, path="/")
    return response


@router.get("/pending", response_class=HTMLResponse)
async def pending(request: Request):
    device = await current_device(request)
    if device is None or device.expired:
        return RedirectResponse("/register", status_code=303)
    if device.status == APPROVED:
        return RedirectResponse("/", status_code=303)
    if device.status == REVOKED:
        return RedirectResponse("/blocked", status_code=303)
    return _page(request, "pending.html", device=device,
                 can_claim=bool(request.app.state.settings.admin_bootstrap_token))


@router.get("/pending/status")
async def pending_status(request: Request) -> Response:
    """Polled by the pending page; tells htmx to move on once the status changes."""
    device = await current_device(request)
    if device is not None and device.status == APPROVED and not device.expired:
        return Response(headers={"HX-Redirect": "/"})
    if device is None or device.status == REVOKED or device.expired:
        return Response(headers={"HX-Redirect": "/pending"})
    return Response(status_code=204)


@router.get("/blocked", response_class=HTMLResponse)
async def blocked(request: Request):
    return _page(request, "message.html", 403, title="Access revoked",
                 message="Access for this browser has been revoked. Contact the site admin if you think this is a mistake.")


@router.post("/forget", dependencies=[Depends(same_origin)])
async def forget(request: Request):
    """Drop this browser's device cookie (the device record stays for the admin)."""
    response = RedirectResponse("/register", status_code=303)
    response.delete_cookie(DEVICE_COOKIE, path="/")
    return response


# --- Admin ---

@router.get("/admin", response_class=HTMLResponse, name="admin_page")
async def admin_page(request: Request, admin: Device = Depends(require_admin)):
    all_devices = await asyncio.to_thread(_devices(request).list)
    groups = {s: [d for d in all_devices if d.status == s] for s in (PENDING, APPROVED, REVOKED)}
    return _page(request, "admin.html", groups=groups, me=admin)


@router.post("/admin/devices/{device_id}/{action}", dependencies=[Depends(same_origin)])
async def admin_action(request: Request, device_id: int, action: str, label: str = Form(""),
                       admin: Device = Depends(require_admin)):
    devices = _devices(request)
    if device_id == admin.id and action in ("revoke", "delete"):
        raise NotAllowed(400, "You can't revoke or delete the device you're using.")
    handlers = {
        "approve": lambda: devices.approve(device_id),
        "revoke": lambda: devices.revoke(device_id),
        "delete": lambda: devices.delete(device_id),
        "label": lambda: devices.set_label(device_id, label),
        "make-admin": lambda: devices.make_admin(device_id),
    }
    if action not in handlers:
        raise NotAllowed(404, "Unknown action.")
    before = await asyncio.to_thread(devices.get, device_id)
    if before is None or not await asyncio.to_thread(handlers[action]):
        raise NotAllowed(404, "No such device.")
    log.info("Admin device %d: %s device %d", admin.id, action, device_id)
    if action == "approve" and before.status != APPROVED:
        await _send(request, before.email, f"{request.app.state.settings.site_title}: you're approved",
                    f"Your browser has been approved. Open the scoreboard here: {request.url_for('dashboard')}\n\n"
                    "Use the same browser you registered with.")
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/claim", response_class=HTMLResponse)
async def claim_form(request: Request):
    return _page(request, "claim.html", error=None, device=await current_device(request))


def _claim_failures(request: Request) -> list[float]:
    """Recent failed claim times for this client IP (kept in memory; a restart clears them)."""
    failures: dict[str, list[float]] | None = getattr(request.app.state, "claim_failures", None)
    if failures is None:
        failures = request.app.state.claim_failures = {}
    now = time.monotonic()
    recent = [t for t in failures.get(client_ip(request), []) if now - t < CLAIM_WINDOW]
    failures[client_ip(request)] = recent
    return recent


@router.post("/admin/claim", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
async def claim_submit(request: Request, token: str = Form("")):
    expected = request.app.state.settings.admin_bootstrap_token
    device = await current_device(request)
    if device is None or device.expired:
        return _page(request, "claim.html", 400, device=None,
                      error="Register this browser first (email + code), then come back here.")
    failures = _claim_failures(request)
    if len(failures) >= CLAIM_MAX_FAILURES:
        return _page(request, "claim.html", 429, device=device,
                      error="Too many wrong tokens. Try again in 15 minutes.")
    if not expected or not hmac.compare_digest(token.strip().encode(), expected.encode()):
        failures.append(time.monotonic())
        log.warning("Failed admin claim from %s (%d recent)", client_ip(request), len(failures))
        await asyncio.sleep(1)  # slow down guessing
        return _page(request, "claim.html", 403, device=device, error="That token isn't right.")
    await asyncio.to_thread(_devices(request).make_admin, device.id)
    log.info("Device %d (%s) claimed admin", device.id, device.email)
    return RedirectResponse("/admin", status_code=303)
