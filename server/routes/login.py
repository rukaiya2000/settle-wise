"""Login/logout for the dashboard session cookie - see server/auth.py for
the signing logic and the middleware that gates on it. A styled in-app
page instead of HTTP Basic's native browser prompt.
"""

import html
import secrets

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import SESSION_COOKIE, SESSION_MAX_AGE, make_session_token, resolve_credentials

router = APIRouter()


def _safe_next(next_path: str | None) -> str:
    """`next` comes from a query param / hidden form field, so it's user
    input - restrict it to a same-origin relative path or an open redirect
    (next=https://evil.example) could send a just-authenticated user
    anywhere."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/dashboard/"

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SettleWise</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #f4f6f8; color: #1c2430;
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  .card {{ width: 320px; padding: 32px; background: #ffffff; border: 1px solid #e2e6ea; border-radius: 12px; }}
  .brand {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #5b6470; font-size: 13px; margin-bottom: 24px; }}
  label {{ display: block; font-size: 12px; color: #5b6470; margin-bottom: 6px; }}
  input {{
    width: 100%; padding: 10px 12px; margin-bottom: 16px; background: #f4f6f8; color: #1c2430;
    border: 1px solid #e2e6ea; border-radius: 8px; font-size: 14px; font-family: inherit;
  }}
  input:focus {{ outline: none; border-color: #3564c7; box-shadow: 0 0 0 3px #dbeafe; }}
  button {{
    width: 100%; padding: 11px; background: #3564c7; color: #fff; border: none; border-radius: 8px;
    font-size: 14px; font-weight: 600; cursor: pointer; font-family: inherit;
  }}
  button:hover {{ background: #2a53ad; }}
  .error {{
    background: #fee2e2; color: #991b1b; border-radius: 8px; padding: 8px 12px;
    font-size: 13px; margin-bottom: 16px;
  }}
</style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <div class="brand">SettleWise</div>
    <div class="subtitle">Sign in to the operator dashboard</div>
    {error_html}
    <input type="hidden" name="next" value="{next_path}" />
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" autofocus required />
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required />
    <button type="submit">Sign in</button>
  </form>
</body>
</html>"""


def _render(error: bool = False, next_path: str = "/dashboard/") -> str:
    error_html = '<div class="error">Incorrect username or password.</div>' if error else ""
    return _PAGE.format(error_html=error_html, next_path=html.escape(next_path, quote=True))


@router.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/dashboard/"):
    return _render(next_path=_safe_next(next))


@router.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...), next: str = Form("/dashboard/")):
    next = _safe_next(next)
    expected_user, expected_password = resolve_credentials()
    # Both comparisons run even when the first fails, so a wrong username
    # doesn't return faster than a wrong password would.
    ok = secrets.compare_digest(username, expected_user) & secrets.compare_digest(password, expected_password)
    if not ok:
        return HTMLResponse(_render(error=True, next_path=next), status_code=401)

    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(SESSION_COOKIE, make_session_token(expected_user), max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
