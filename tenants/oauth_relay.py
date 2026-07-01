"""Single-callback Google OAuth relay for the multi-tenant setup.

Problem
-------
Every tenant is on its own domain, so allauth sends Google a per-domain
``redirect_uri`` (``https://<tenant>/accounts/google/login/callback/``). Google
only accepts redirect URIs pre-registered on the OAuth client, and it does NOT
allow wildcards — so Google login breaks on any tenant domain that isn't
individually registered (and ``*.ofleet0.com`` subdomains can't be covered).

Solution
--------
Send Google ONE fixed ``redirect_uri`` — ``https://<RELAY>/oauth/google/relay/``
— and register just that single URI. After Google returns to the relay we
bounce the ``code`` back to the originating tenant, which exchanges it (still
presenting the relay ``redirect_uri``) and logs the user in **in its own schema,
on its own session**. One registered URI then covers every tenant, present and
future.

Opt-in / reversible
-------------------
Enabled only when ``OAUTH_RELAY_DOMAIN`` is set. When unset, :func:`google_start`
falls back to the normal per-domain allauth flow — zero behaviour change.

Security
--------
* ``state`` is signed with ``SECRET_KEY`` and time-limited → tamper/replay proof.
* the origin domain is validated against the ``Domain`` table → the ``code`` can
  only ever be bounced to a real tenant domain (no open-redirect / code leak).
* a per-session nonce binds the callback to the session that started it (CSRF).
* only relative ``next`` targets are honoured.
"""
from urllib.parse import urlencode
import logging
import secrets

logger = logging.getLogger("oauth_relay")

from django.conf import settings
from django.core import signing
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect

RELAY_PATH = "/oauth/google/relay/"
RESUME_PATH = "/oauth/google/resume/"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
STATE_SALT = "google-oauth-relay-v1"
STATE_MAX_AGE = 600  # 10 minutes
GOOGLE_SCOPE = "openid email profile"


def _relay_domain():
    return (getattr(settings, "OAUTH_RELAY_DOMAIN", "") or "").strip()


def _relay_uri():
    return f"https://{_relay_domain()}{RELAY_PATH}"


def _google_app(request):
    from allauth.socialaccount.adapter import get_adapter
    return get_adapter().get_app(request, "google")


def _is_known_domain(host):
    host = (host or "").split(":")[0].strip().lower()
    if not host:
        return False
    from tenants.models import Domain
    return Domain.objects.filter(domain__iexact=host).exists()


def _safe_next(value):
    """Only allow same-site relative paths (block open redirects)."""
    value = value or ""
    if value.startswith("/") and not value.startswith("//"):
        return value
    return ""


def _fallback_to_allauth(request):
    """Preserve the current per-domain flow when the relay is disabled."""
    nxt = _safe_next(request.GET.get("next", ""))
    url = "/accounts/google/login/?process=login"
    if nxt:
        url += "&" + urlencode({"next": nxt})
    return redirect(url)


def _login_error(request):
    from django.contrib import messages
    try:
        messages.error(request, "تعذّر تسجيل الدخول عبر Google، يُرجى المحاولة مرة أخرى.")
    except Exception:
        pass
    return redirect(getattr(settings, "LOGIN_URL", "/accounts/login/"))


def google_start(request):
    """On the tenant: kick off Google login via the fixed relay redirect_uri."""
    if not _relay_domain():
        return _fallback_to_allauth(request)
    try:
        app = _google_app(request)
    except Exception:
        return _fallback_to_allauth(request)

    nonce = secrets.token_urlsafe(24)
    request.session["g_relay_nonce"] = nonce
    state = signing.dumps(
        {"o": request.get_host(), "n": nonce, "next": _safe_next(request.GET.get("next", ""))},
        salt=STATE_SALT,
    )
    params = {
        "client_id": app.client_id,
        "redirect_uri": _relay_uri(),
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = redirect(f"{AUTHORIZE_URL}?{urlencode(params)}")
    # The session cookie is SameSite=Lax and doesn't reliably survive the
    # cross-domain relay bounce (relay domain -> a *different* tenant domain),
    # so also carry the nonce in a SameSite=None cookie that does.
    resp.set_cookie("goauth_n", nonce, max_age=STATE_MAX_AGE, secure=True,
                    httponly=True, samesite="None")
    return resp


def google_relay(request):
    """On the RELAY domain: verify state and bounce the code to the origin."""
    code = request.GET.get("code")
    err = request.GET.get("error")
    state = request.GET.get("state", "")
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature:
        return HttpResponseBadRequest("Invalid OAuth state.")
    origin = data.get("o", "")
    if not _is_known_domain(origin):
        logger.warning("OAUTHRELAY relay: unknown origin=%s", origin)
        return HttpResponseBadRequest("Unknown OAuth origin.")
    q = {"state": state}
    if code:
        q["code"] = code
    if err:
        q["error"] = err
    logger.warning("OAUTHRELAY relay: bounce -> origin=%s has_code=%s err=%s", origin, bool(code), err)
    return redirect(f"https://{origin}{RESUME_PATH}?{urlencode(q)}")


def google_resume(request):
    """On the ORIGIN tenant: exchange the code and complete the login."""
    state = request.GET.get("state", "")
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature:
        logger.warning("OAUTHRELAY resume: bad/expired state signature")
        return _login_error(request)
    if data.get("o", "") != request.get_host():
        logger.warning("OAUTHRELAY resume: origin mismatch state_o=%s host=%s", data.get("o"), request.get_host())
        return _login_error(request)
    # Nonce (CSRF) may arrive via the session (same-domain) or the SameSite=None
    # cookie (cross-domain relay bounce) — accept either.
    sess_nonce = request.session.pop("g_relay_nonce", None)
    cookie_nonce = request.COOKIES.get("goauth_n")
    expected = data.get("n")
    if not expected or expected not in (sess_nonce, cookie_nonce):
        logger.warning("OAUTHRELAY resume: nonce mismatch host=%s expected=%s sess=%s cookie=%s",
                       request.get_host(), bool(expected), bool(sess_nonce), bool(cookie_nonce))
        return _login_error(request)
    if request.GET.get("error") or not request.GET.get("code"):
        logger.warning("OAUTHRELAY resume: google error=%s has_code=%s", request.GET.get("error"), bool(request.GET.get("code")))
        return _login_error(request)

    from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
    from allauth.socialaccount.helpers import complete_social_login
    try:
        adapter = GoogleOAuth2Adapter(request)
        app = _google_app(request)
        client = adapter.get_client(request, app)
        # The token exchange must present the SAME redirect_uri Google saw at
        # authorize time (the relay), not this tenant's own callback URL.
        client.callback_url = _relay_uri()
        token_resp = adapter.get_access_token_data(request, app, client)
        token = adapter.parse_token(token_resp)
        if app.pk:
            token.app = app
        login = adapter.complete_login(request, app, token, response=token_resp)
        login.token = token
        login.state = {"process": "login", "next": _safe_next(data.get("next", ""))}
        resp = complete_social_login(request, login)
        try:
            resp.delete_cookie("goauth_n")
        except Exception:
            pass
        return resp
    except Exception:
        logger.exception("OAUTHRELAY resume: token exchange / complete_login failed host=%s", request.get_host())
        return _login_error(request)
