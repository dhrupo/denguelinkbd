import json
import threading
import urllib.request

import pytest

from dengue_link import server


@pytest.fixture
def live(monkeypatch, tmp_path):
    calls = []
    clock = {"now": 1_000_000.0}

    def fake_run(root, progress):
        calls.append(1)
        progress(50, "Fetching DGHS")
        out = tmp_path / "map.html"
        out.write_text(f"<html>map build {len(calls)}</html>")
        return out, {"season": 0.1}, None

    monkeypatch.setattr(server, "run", fake_run)
    monkeypatch.setattr(server.time, "time", lambda: clock["now"])
    server._state.clear()
    httpd = server.make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", calls, clock
    httpd.shutdown()


def test_front_page_shows_percentage_loader_and_uses_browser_storage(live):
    base, calls, _ = live
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "<progress" in page and 'aria-live="polite"' in page
    assert 'fetch("/progress")' in page and 'fetch("/map")' in page
    assert "indexedDB" in page and "DAY = 24 * 60 * 60 * 1000" in page
    assert calls == []


def test_data_is_fetched_once_and_reused_for_24_hours(live):
    base, calls, clock = live
    first = urllib.request.urlopen(base + "/map")
    assert "build 1" in first.read().decode()
    assert first.headers["X-Built-At"] == str(int(1_000_000 * 1000))
    clock["now"] += 23 * 3600
    assert "build 1" in urllib.request.urlopen(base + "/map").read().decode()
    clock["now"] += 2 * 3600
    assert "build 2" in urllib.request.urlopen(base + "/map").read().decode()
    assert len(calls) == 2


def test_progress_endpoint_reports_percent_and_stage(live):
    base, _, _ = live
    urllib.request.urlopen(base + "/map").read()
    state = json.loads(urllib.request.urlopen(base + "/progress").read())
    assert state["pct"] == 100
    assert isinstance(state["msg"], str)


def test_browser_copy_from_an_older_page_design_is_not_reused(live):
    base, _, _ = live
    page = urllib.request.urlopen(base + "/").read().decode()
    assert f'var VERSION = "{server.VERSION}"' in page
    assert "rec.version === VERSION" in page
    assert len(server.VERSION) >= 8


def test_loader_speaks_both_languages_in_plain_words(live):
    base, _, _ = live
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "আজকের" in page and "Getting today" in page
    assert "dl-lang" in page
    assert "waiting for" not in page


def test_an_unavailable_page_is_not_cached(monkeypatch, tmp_path):
    calls = []

    def unavailable(root, progress):
        calls.append(1)
        out = tmp_path / "map.html"
        out.write_text("<html>No forecast right now</html>")
        return out, None, None

    monkeypatch.setattr(server, "run", unavailable)
    server._state.clear()
    httpd = server.make_server(port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        first = urllib.request.urlopen(base + "/map")
        assert first.headers["X-Built-At"] is None
        urllib.request.urlopen(base + "/map").read()
        assert len(calls) == 2
    finally:
        httpd.shutdown()


def test_loader_only_keeps_pages_that_carry_a_build_time(live):
    base, _, _ = live
    page = urllib.request.urlopen(base + "/").read().decode()
    assert 'if (db && record.fetchedAt) save(db, record)' in page
