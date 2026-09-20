from pathlib import Path

import pytest
import requests

from dengue_link import db, dghs_scrape, fetch

FIXTURES = Path(__file__).parent / "fixtures"


class Resp:
    def __init__(self, content=b"", text=""):
        self.content, self.text = content, text

    def raise_for_status(self):
        pass


def test_truncated_pdf_is_retried_until_complete(monkeypatch):
    bodies = iter([b"%PDF-1.4 cut off", b"%PDF-1.4 whole\n%%EOF\n"])
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: Resp(next(bodies)))
    assert fetch.get_pdf("u").endswith(b"%%EOF\n")


def test_pdf_that_never_arrives_whole_raises(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: Resp(b"%PDF cut"))
    with pytest.raises(ValueError, match="truncated"):
        fetch.get_pdf("u")


def test_one_failed_download_does_not_stop_the_scrape(tmp_path, monkeypatch, capsys):
    pages = {
        f"{dghs_scrape.BASE}/pages/press-releases?page=1": (FIXTURES / "dghs_press_list.html").read_text(),
    }
    release = (FIXTURES / "dghs_press_release.html").read_text()
    monkeypatch.setattr(dghs_scrape, "_get", lambda url: Resp(text=pages.get(url, release)))
    good = (FIXTURES / "dghs_dengue_2026-09-17.pdf").read_bytes()

    def flaky(url):
        if "2124d8c1" in url:
            raise requests.exceptions.ConnectionError("Read timed out.")
        return good

    monkeypatch.setattr(dghs_scrape, "get_pdf", flaky)
    conn = db.connect(tmp_path / "t.db")
    assert dghs_scrape.scrape(conn, list_pages=[1]) >= 1
    assert [p.name for p in tmp_path.iterdir()] == ["t.db"]
    assert "FAILED" in capsys.readouterr().err


def test_measles_releases_are_skipped(tmp_path, monkeypatch):
    visited = []
    listing = (FIXTURES / "dghs_press_list.html").read_text()

    def fake_get(url):
        visited.append(url)
        return Resp(text=listing if "?page=" in url else "")

    monkeypatch.setattr(dghs_scrape, "_get", fake_get)
    dghs_scrape.scrape(db.connect(tmp_path / "t.db"), list_pages=[1])
    releases = [u for u in visited if "?page=" not in u]
    assert releases and not any("হাম" in u for u in releases)
    assert any("ডেঙ্গু" in u for u in releases)


def test_scrape_reads_each_pdf_once_and_stores_hospital_load_and_deaths(tmp_path, monkeypatch):
    listing = (FIXTURES / "dghs_press_list.html").read_text()
    release = (FIXTURES / "dghs_press_release.html").read_text()
    monkeypatch.setattr(dghs_scrape, "_get", lambda url: Resp(text=listing if "?page=" in url else release))
    downloads = []
    dengue = (FIXTURES / "dghs_dengue_2026-09-17.pdf").read_bytes()
    measles = (FIXTURES / "dghs_measles_2026-09-17.pdf").read_bytes()
    monkeypatch.setattr(dghs_scrape, "get_pdf", lambda url: downloads.append(url) or (dengue if "1825c05e" in url else measles))
    conn = db.connect(tmp_path / "t.db")
    assert dghs_scrape.scrape(conn, list_pages=[1]) == 1
    value = lambda m, a: conn.execute("select value from obs where source='dghs' and metric=? and area=?", (m, a)).fetchone()
    assert value("dengue_in_hospital", "Dhaka") == (663.0,)
    assert value("dengue_deaths_year", "Dhaka") == (74.0,)
    assert value("dengue_deaths_24h", "Bangladesh") == (5.0,)
    downloads.clear()
    assert dghs_scrape.scrape(conn, list_pages=[1]) == 0
    assert downloads == []


def test_an_unreadable_pdf_is_skipped_and_the_scrape_carries_on(tmp_path, monkeypatch):
    listing = (FIXTURES / "dghs_press_list.html").read_text()
    release = (FIXTURES / "dghs_press_release.html").read_text()
    monkeypatch.setattr(dghs_scrape, "_get", lambda url: Resp(text=listing if "?page=" in url else release))
    dengue = (FIXTURES / "dghs_dengue_2026-09-17.pdf").read_bytes()
    monkeypatch.setattr(dghs_scrape, "get_pdf", lambda url: dengue if "1825c05e" in url else b"%PDF-1.4 not really a pdf %%EOF")
    conn = db.connect(tmp_path / "t.db")
    assert dghs_scrape.scrape(conn, list_pages=[1]) == 1


def test_an_empty_download_is_never_saved_as_the_weekly_list(tmp_path):
    from datetime import date

    import pytest

    from dengue_link.fetch import weekly

    with pytest.raises(ValueError):
        weekly(tmp_path / "list.json", date(2026, 9, 20), lambda: [])
    assert not (tmp_path / "list.json").exists()


def test_dnccs_missing_certificate_link_is_supplied_rather_than_checks_being_turned_off(monkeypatch, tmp_path):
    from pathlib import Path

    from dengue_link import db, dncc_plans, ju_dncc
    from dengue_link.fetch import DNCC_CA

    pem = Path(DNCC_CA).read_text()
    assert pem.count("BEGIN CERTIFICATE") == 1
    asked = []

    class Reply:
        text = ""

    for module in (dncc_plans, ju_dncc):
        monkeypatch.setattr(module.requests, "get", lambda url, **k: asked.append((url, k.get("verify"))) or Reply())
        module.fetch(db.connect(tmp_path / f"{module.__name__}.db"))
    assert [verify for _, verify in asked] == [DNCC_CA, DNCC_CA]
    assert all(url.startswith("https://dncc.gov.bd/") for url, _ in asked)
