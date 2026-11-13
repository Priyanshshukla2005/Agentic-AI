"""Phase 5: the web app files are served correctly, and /api/samples works."""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_serves_index_html():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<main id="app"' in r.text
    assert '<script type="module" src="/static/js/app.js">' in r.text


def test_compare_page_is_served():
    r = client.get("/compare.html")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "/static/js/compare.js" in r.text
    assert client.get("/static/compare.html").status_code == 200


@pytest.mark.parametrize("path", [
    "/static/js/app.js", "/static/js/api.js", "/static/js/i18n.js",
    "/static/js/plan_view.js", "/static/js/compare.js",
])
def test_js_files_served_as_javascript(path):
    r = client.get(path)
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


def test_css_served_as_css():
    r = client.get("/static/css/styles.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "@media print" in r.text


def test_every_referenced_static_file_exists():
    """Every /static/... path used by the HTML pages and JS imports is really served."""
    html = client.get("/").text + client.get("/compare.html").text
    paths = set(re.findall(r'(/static/[\w/.-]+)', html))
    for js in ["app.js", "compare.js", "plan_view.js"]:
        text = client.get(f"/static/js/{js}").text
        paths |= {f"/static/js/{m}" for m in re.findall(r'from "\./([\w.]+)"', text)}
    assert paths
    for path in paths:
        assert client.get(path).status_code == 200, path


def test_samples_endpoint():
    r = client.get("/api/samples")
    assert r.status_code == 200
    samples = r.json()["samples"]
    assert len(samples) == 5
    assert [s["index"] for s in samples] == list(range(5))
    assert sum(s["language"] == "hi" for s in samples) >= 2
    first = samples[0]
    assert first["label"] == first["profile"]["business_idea"]
    assert first["profile"]["budget_inr"] == 20000


def test_no_inner_html_with_api_text():
    """Safety: our JS never uses innerHTML (all API text goes in as text nodes)."""
    for js in ["app.js", "plan_view.js", "compare.js", "api.js", "i18n.js"]:
        text = client.get(f"/static/js/{js}").text
        assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", text), js


def test_phase1_endpoints_still_work():
    assert client.get("/health").json()["status"] == "ok"
