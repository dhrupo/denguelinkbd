from datetime import date
from pathlib import Path

from dengue_link import db
from dengue_link.dghs_scrape import attachment_urls, release_urls

FIXTURES = Path(__file__).parent / "fixtures"


def test_release_links_are_read_from_the_list_page():
    urls = release_urls((FIXTURES / "dghs_press_list.html").read_text())
    assert len(urls) >= 7
    assert all(u.startswith("https://dghs.gov.bd/pages/press-releases/") for u in urls)
    assert any(u.endswith("6aac0ecd98e3eb11ce79e8ac") for u in urls)


def test_pdf_attachments_are_read_from_a_release_page():
    urls = attachment_urls((FIXTURES / "dghs_press_release.html").read_text())
    assert urls == [
        "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-dghs/2026/8/2124d8c1-e69e-47d8-876c-9bfcfd72067f.pdf",
        "https://objectstorage.ap-dcc-gazipur-1.oraclecloud15.com/n/axvjbnqprylg/b/V2Ministry/o/office-dghs/2026/8/1825c05e-d8e0-4527-94f2-cd952a3bfdcf.pdf",
    ]


def test_rescraping_a_day_replaces_instead_of_duplicating(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.put(conn, "dghs", "dengue_admit_24h", date(2026, 9, 17), {"Dhaka": 437, "Feni": 10})
    db.put(conn, "dghs", "dengue_admit_24h", date(2026, 9, 17), {"Dhaka": 440})
    rows = conn.execute("select area, value from obs order by area").fetchall()
    assert rows == [("Dhaka", 440.0), ("Feni", 10.0)]
