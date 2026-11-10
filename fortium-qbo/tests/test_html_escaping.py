"""Names and query params must reach the admin pages as text, never as markup or script.

Two paths, both reproduced locally from a source-read audit:

1. `_error_response` interpolated its message into HTML unescaped, and two callers
   put request input in that message (`error` on the OAuth callback, `region` on
   connect). A link carrying markup in either rendered it on our origin.
2. Key names and company names sat inside single-quoted JS strings in onclick /
   onsubmit attributes. Jinja's HTML escaping turns `'` into `&#39;`, but the
   browser decodes the attribute before running it, so the quote came back and
   closed the JS string.

The attribute tests decode the attribute the way a browser does (html.parser),
pull out the argument, and require it to parse as one JSON string equal to the
original name. A broken-out string fails that parse.
"""

import json
import re
from datetime import datetime
from html.parser import HTMLParser
from types import SimpleNamespace

from app.routers.pages import templates
from app.routers.qbo_oauth import _error_response

HOSTILE = "x');alert(1);//\"<b>&"


class _AttrCollector(HTMLParser):
    def __init__(self, attr: str):
        super().__init__()
        self.attr = attr
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == self.attr and value is not None:
                self.values.append(value)


def _attrs(html: str, attr: str) -> list[str]:
    parser = _AttrCollector(attr)
    parser.feed(html)
    return parser.values


def test_error_page_renders_message_as_text():
    body = _error_response("denied: <script>alert(1)</script>").body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "denied: &lt;script&gt;alert(1)&lt;/script&gt;" in body


def _key(key_id: int, name: str, active: bool):
    return SimpleNamespace(
        id=key_id,
        name=name,
        key_prefix="fpq_abc",
        company=SimpleNamespace(name="Co"),
        is_active=active,
        is_read_only=False,
        created_at=datetime(2026, 1, 1),
        last_used_at=None,
    )


def _render(template: str, **ctx) -> str:
    return templates.env.get_template(template).render(
        user=SimpleNamespace(email="a@b.c"), **ctx
    )


def _js_string_arg(call: str, fn: str) -> str:
    match = re.fullmatch(rf"(?:return )?{fn}\((?:\d+, )?(.*)\)", call.strip())
    assert match, f"unexpected handler shape: {call!r}"
    return json.loads(match.group(1))


def test_key_name_stays_inside_its_js_string():
    html = _render(
        "admin/api_keys.html",
        api_keys=[_key(5, HOSTILE, True), _key(6, HOSTILE, False)],
        companies=[],
        message=None,
    )
    handlers = _attrs(html, "onclick")
    revoke = [h for h in handlers if h.startswith("revokeKey(")]
    reactivate = [h for h in handlers if h.startswith("reactivateKey(")]
    assert len(revoke) == 1 and len(reactivate) == 1
    assert _js_string_arg(revoke[0], "revokeKey") == HOSTILE
    assert _js_string_arg(reactivate[0], "reactivateKey") == HOSTILE


def test_company_name_stays_inside_its_confirm_string():
    company = SimpleNamespace(
        id=7,
        name=HOSTILE,
        code="FOR-1",
        region="US",
        is_sandbox=False,
        realm_id="1",
        token_status="valid",
        token_status_info=SimpleNamespace(
            css_class="", label="", expires_display=""
        ),
        refresh_token_status_info=SimpleNamespace(
            refresh_css_class="", refresh_expires_display=""
        ),
        last_refreshed_at=None,
    )
    html = _render("admin/companies.html", companies=[company], message=None)
    (handler,) = _attrs(html, "onsubmit")
    assert _js_string_arg(handler, "confirm") == (
        f"Disconnect {HOSTILE}? This will revoke API access."
    )
