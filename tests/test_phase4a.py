"""Phase 4A — design system and app shell: behaviour checks, not HTML
snapshots. Navigation must agree with the backend's real permissions, every
page must load only existing same-origin assets, and the frontend may only
call API routes that exist.
"""

import json
import re
from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    ALL_ROLES_USERS,
    archive_published_scenarios,
    login,
    ok,
    server,
)

import app.main as main

STATIC = Path(__file__).resolve().parent.parent / "static"
NAV = json.loads((STATIC / "js" / "nav.json").read_text(encoding="utf-8"))
NAV_ITEMS = [item for group in NAV["groups"] for item in group["items"]]
SHELL_PAGES = {"/": "training", "/dashboard": "dashboard", "/admin": "admin", "/session": "session", "/overview": "overview", "/progress": "progress", "/history": "history", "/team": "team", "/manager": "manager", "/queue": "queue"}
ALL_PAGES = [*SHELL_PAGES, "/login"]
SHARED_VIEWS = {"/static/js/progress-view.js", "/static/js/content-model.js", "/static/js/content-editor.js", "/static/js/scenario-editor.js", "/static/js/kb-editor.js"}


# ------------------------------------------------------------ navigation


@pytest.mark.parametrize("role", list(ALL_ROLES_USERS))
def test_nav_visibility_matches_backend_permissions(server, role):
    """A visible item must work for that role; a hidden item must be refused
    by the backend (unless explicitly listed as hidden_but_allowed)."""
    client = login(ALL_ROLES_USERS[role])
    me = ok(client.get("/auth/me"))
    manager1 = ok(login("manager1").get("/auth/me"))["id"]  # on lead1's team in the seed
    for item in NAV_ITEMS:
        status = client.get(item["probe"].replace("{self}", me["id"]).replace("{manager1}", manager1)).status_code
        if role in item["roles"] or role in item.get("hidden_but_allowed", []):
            assert status == 200, (role, item["key"], status)
        else:
            assert status == 403, (role, item["key"], status)


def test_every_role_gets_at_least_one_destination_and_managers_see_no_content_tools(server):
    for role in ALL_ROLES_USERS:
        assert any(role in item["roles"] for item in NAV_ITEMS), role
    manager_keys = {item["key"] for item in NAV_ITEMS if "manager" in item["roles"]}
    assert manager_keys == {"overview", "train", "progress", "history"}


def test_nav_targets_are_existing_pages(server):
    for item in NAV_ITEMS:
        path = item["href"].split("#")[0].split("?")[0]
        assert server.get(path).status_code == 200, item["href"]


def test_pages_only_activate_known_nav_keys():
    """Every key a page highlights (setActiveNav/initPage literals, admin sections)
    exists in nav.json, so a highlighted item is never silently missing."""
    keys = {item["key"] for item in NAV_ITEMS}
    roles = set(ALL_ROLES_USERS)
    used = set()
    for js in (STATIC / "js" / "pages").glob("*.js"):
        for argument in map("".join, re.findall(r"setActiveNav\(([^;]+?)\);|initPage\(('[a-z_]+')", js.read_text(encoding="utf-8"))):
            used |= {word for word in re.findall(r"'([a-z_]+)'", argument) if word not in roles}
    admin_tabs = set(re.findall(r"^\s{2}([a-z]+): \{ title:", (STATIC / "js" / "pages" / "admin.js").read_text(encoding="utf-8"), re.M))
    assert admin_tabs == {"scenarios", "kb", "users", "audit"}
    assert {"overview", "train", "progress", "history", "dashboard", "team"} <= used
    assert (used | admin_tabs) <= keys


# ------------------------------------------------------------ pages & assets


@pytest.mark.parametrize("page", ALL_PAGES)
def test_page_assets_exist_with_correct_types(server, page):
    html = server.get(page).text
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert any(a.endswith(".css") for a in assets) and any(a.endswith(".js") for a in assets)
    for asset in assets:
        response = server.get(asset)
        assert response.status_code == 200, asset
        expected = {".css": "text/css", ".js": "javascript", ".svg": "image/svg+xml"}[Path(asset).suffix]
        assert expected in response.headers["content-type"], (asset, response.headers["content-type"])


@pytest.mark.parametrize("page,script", SHELL_PAGES.items())
def test_shell_pages_have_the_shell_and_load_scripts_in_order(server, page, script):
    html = server.get(page).text
    for element_id in ("app-shell", "sidebar", "menu-toggle", "page-title", "page-subtitle", "page-actions", "main"):
        assert f'id="{element_id}"' in html, (page, element_id)
    assert 'class="skip-link" href="#main"' in html
    order = re.findall(r'<script src="([^"]+)"', html)
    assert order[:4] == ["/static/theme.js", "/static/app.js", "/static/js/ui.js", "/static/js/shell.js"]
    assert order[-1] == f"/static/js/pages/{script}.js"
    assert set(order[4:-1]) <= SHARED_VIEWS  # shared presentation modules only


def test_login_page_is_standalone_and_keeps_its_form(server):
    html = server.get("/login").text
    for element_id in ("login-form", "username", "password", "login-btn", "error", "theme-row"):
        assert f'id="{element_id}"' in html
    assert "shell.js" not in html and 'id="sidebar"' not in html
    assert 'autocomplete="current-password"' in html


def test_old_stylesheet_is_gone(server):
    assert server.get("/static/app.css").status_code == 404
    assert server.get("/static/css/app.css").status_code == 200


# ------------------------------------------------------------ frontend code


def _frontend_js():
    files = [STATIC / "app.js", STATIC / "theme.js", *(STATIC / "js").rglob("*.js")]
    return {f.relative_to(STATIC).as_posix(): f.read_text(encoding="utf-8") for f in files}


def test_frontend_has_no_inline_styles_eval_or_javascript_urls():
    for name, text in _frontend_js().items():
        assert 'style="' not in text, name  # would be blocked by style-src 'self'
        assert "eval(" not in text and "new Function" not in text, name
        assert "javascript:" not in text, name
        assert not re.search(r"setTimeout\(\s*['\"`]", text), name


def test_frontend_calls_only_existing_api_routes():
    # The OpenAPI schema lists every API route, including those of included
    # routers (which app.routes keeps nested in this FastAPI version).
    routes = list(main.app.openapi()["paths"])
    patterns = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$") for p in routes]
    called = set()
    for text in _frontend_js().values():
        for raw in re.findall(r"(?:api|fetch)\(\s*[`'\"](/[^`'\"?]*)", text):
            called.add(re.sub(r"\$\{[^}]+\}", "x", raw))
    assert called, "no API calls found — pattern broken?"
    api_paths = {path for path in called if not path.startswith("/static/")}  # assets are checked above
    unknown = sorted(path for path in api_paths if not any(p.match(path) for p in patterns))
    assert not unknown, unknown


def test_shell_uses_only_fields_auth_me_provides(server):
    me = ok(login("manager1").get("/auth/me"))
    shell = (STATIC / "js" / "shell.js").read_text(encoding="utf-8")
    for field in set(re.findall(r"\bme\.([a-z_]+)", shell)):
        assert field in me, field


# ------------------------------------------------------------ no new exposure


def test_shell_reveals_nothing_beyond_auth_me(server):
    """The sidebar is built from /auth/me (the user's own record) and the
    static nav config; it requests no other data."""
    shell = (STATIC / "js" / "shell.js").read_text(encoding="utf-8")
    requested = set(re.findall(r"(?:api|fetch)\(\s*['\"`]([^'\"`]+)", shell))
    assert requested == {"/auth/me", "/static/js/nav.json", "/auth/logout"}
    nav = server.get("/static/js/nav.json").text
    assert "password" not in nav.lower() and "secret" not in nav.lower()
