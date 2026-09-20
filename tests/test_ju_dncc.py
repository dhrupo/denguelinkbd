from datetime import date
from pathlib import Path

from dengue_link.ju_dncc import parse_surveillance_pdf, report_urls

FIXTURES = Path(__file__).parent / "fixtures"


def test_weekly_report_gives_dengue_mosquito_counts_per_dncc_zone():
    r = parse_surveillance_pdf(FIXTURES / "ju_dncc_week114.pdf")
    assert r.week == 114
    assert r.start == date(2026, 8, 7) and r.end == date(2026, 8, 11)
    assert r.aedes_adults == {1: 10, 2: 8, 3: 23, 4: 45, 5: 40}
    assert r.aedes_larvae == {1: 0, 2: 7, 3: 0, 4: 125, 5: 8}


def test_previous_week_parses_the_same_way():
    r = parse_surveillance_pdf(FIXTURES / "ju_dncc_week113.pdf")
    assert r.week == 113
    assert r.aedes_adults[4] == 36
    assert sum(r.aedes_adults.values()) == 105 + 18


def test_report_links_are_read_from_the_dncc_listing():
    urls = report_urls((FIXTURES / "dncc_surveillance_list.html").read_text())
    assert len(urls) == 10
    assert all(u.endswith(".pdf") and "/2024/12/" not in u for u in urls)


def test_fetch_reads_each_report_once_and_fills_gaps_left_by_an_interrupted_run(tmp_path, monkeypatch):
    from dengue_link import db, ju_dncc

    listing = (FIXTURES / "dncc_surveillance_list.html").read_text()
    urls = report_urls(listing)
    pdfs = {urls[0]: "ju_dncc_week114.pdf", urls[1]: "ju_dncc_week113.pdf", urls[2]: "ju_dncc_week104.pdf"}

    class Resp:
        text = listing

    monkeypatch.setattr(ju_dncc, "report_urls", lambda html: urls[:3])
    monkeypatch.setattr(ju_dncc.requests, "get", lambda *a, **k: Resp())
    downloads, broken = [], {urls[1]}

    def get_pdf(u):
        downloads.append(u)
        if u in broken:
            raise ValueError("truncated")
        return (FIXTURES / pdfs[u]).read_bytes()

    monkeypatch.setattr(ju_dncc, "get_pdf", get_pdf)
    conn = db.connect(tmp_path / "t.db")
    assert ju_dncc.fetch(conn) == 2
    assert conn.execute("select value from obs where source='ju_dncc' and metric='aedes_adults' and date='2026-08-11' and area='DNCC-Z4'").fetchone() == (45.0,)

    broken.clear(); downloads.clear()
    assert ju_dncc.fetch(conn) == 1
    assert downloads == [urls[1]]

    downloads.clear()
    assert ju_dncc.fetch(conn) == 0
    assert downloads == []


def test_older_layout_with_a_total_column_reads_the_aedes_columns_by_name():
    r = parse_surveillance_pdf(FIXTURES / "ju_dncc_week104.pdf")
    assert r.week == 104
    assert r.end == date(2026, 5, 25)
    assert r.aedes_adults == {1: 10, 2: 5, 3: 27, 4: 8, 5: 19}
