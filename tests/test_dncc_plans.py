from pathlib import Path

import pytest

from dengue_link.dncc_plans import parse_plan_pdf, plan_pdf_urls

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_PDF = FIXTURES / "dncc_plan_zone4.pdf"
# The real plan lists every spray worker's name and mobile number, so it is kept out of the repository.
# To run these, save the Zone 4 plan from https://dncc.gov.bd/pages/mosquito-kill-plans as tests/fixtures/dncc_plan_zone4.pdf.
needs_plan = pytest.mark.skipif(not PLAN_PDF.exists(), reason="DNCC plan PDF is not in the repository (it holds staff phone numbers)")


@needs_plan
def test_ward_rota_is_read_from_bijoy_encoded_plan():
    wards = parse_plan_pdf(PLAN_PDF)
    assert {"Sat", "Tue", "Sun", "Wed"} <= wards[9]
    assert 16 in wards


@needs_plan
def test_only_ward_numbers_and_weekdays_come_out():
    wards = parse_plan_pdf(PLAN_PDF)
    assert all(isinstance(w, int) and 1 <= w <= 60 for w in wards)
    assert set().union(*wards.values()) <= {"Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"}


def test_plan_pdfs_are_listed_from_the_plans_page():
    urls = plan_pdf_urls((FIXTURES / "dncc_mosquito_plans.html").read_text())
    assert len(urls) == 10
    assert all("office-dncc/2026/" in u and u.endswith(".pdf") for u in urls)


@needs_plan
def test_plan_pdf_can_be_read_from_memory():
    import io

    wards = parse_plan_pdf(io.BytesIO(PLAN_PDF.read_bytes()))
    assert 9 in wards


def test_plan_pdfs_download_in_parallel(tmp_path, monkeypatch):
    import time

    from dengue_link import db, dncc_plans

    html = (FIXTURES / "dncc_mosquito_plans.html").read_text()
    pdf = b"%PDF stand-in; the parser is replaced below"

    class Resp:
        text = html

    monkeypatch.setattr(dncc_plans.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(dncc_plans, "get_pdf", lambda url: time.sleep(0.3) or pdf)
    monkeypatch.setattr(dncc_plans, "parse_plan_pdf", lambda f: {9: {"Sat"}})
    start = time.monotonic()
    assert dncc_plans.fetch(db.connect(tmp_path / "t.db")) == 10
    assert time.monotonic() - start < 1.5
