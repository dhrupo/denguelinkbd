from datetime import date
from pathlib import Path

import pytest

from dengue_link.dghs_pdf import GARBLED_DISTRICTS, parse_dengue_pdf, undo_triple

FIXTURES = Path(__file__).parent / "fixtures"
RAW = Path(__file__).parent.parent / "data" / "raw"


@pytest.fixture(scope="module")
def report():
    return parse_dengue_pdf(FIXTURES / "dghs_dengue_2026-09-17.pdf")


def test_report_date_and_national_total(report):
    assert report.date == date(2026, 9, 17)
    assert report.national_24h == 1484


def test_every_district_reported_and_totals_reconcile(report):
    assert len(report.district_24h) == 64
    assert sum(report.district_24h.values()) == report.national_24h


def test_district_values_match_the_pdf(report):
    assert report.district_24h["Gopalganj"] == 17
    assert report.district_24h["Kishoreganj"] == 20
    assert report.district_24h["Chittagong"] == 72
    assert report.district_24h["Mymensingh"] == 44
    assert report.district_24h["Rangpur"] == 0
    assert report.district_24h["Dhaka"] == 437


def test_district_names_match_the_boundary_file():
    import json

    names = {f["properties"]["shapeName"] for f in json.load(open(RAW / "districts.geojson"))["features"]}
    assert set(GARBLED_DISTRICTS.values()) == names


def test_chart_labels_rendered_three_times_are_collapsed():
    assert undo_triple("1,4841,4841,484") == 1484
    assert undo_triple("555") == 5


def test_totals_that_do_not_reconcile_are_rejected(tmp_path, monkeypatch):
    import dengue_link.dghs_pdf as mod

    monkeypatch.setattr(mod, "undo_triple", lambda s: 9999)
    with pytest.raises(ValueError, match="reconcile"):
        parse_dengue_pdf(FIXTURES / "dghs_dengue_2026-09-17.pdf")


def test_other_press_release_pdfs_are_not_dengue_reports():
    assert parse_dengue_pdf(FIXTURES / "dghs_measles_2026-09-17.pdf") is None


def test_hospital_load_and_deaths_are_read_per_district(report):
    assert report.in_hospital["Gopalganj"] == 32
    assert report.in_hospital["Kishoreganj"] == 91
    assert report.in_hospital["Dhaka"] == 663
    assert report.deaths_year["Dhaka"] == 74
    assert report.deaths_year["Gopalganj"] == 0


def test_deaths_add_up_to_the_national_total(report):
    assert report.national_deaths_year == 176
    assert report.national_deaths_24h == 5
    assert sum(report.deaths_year.values()) == report.national_deaths_year
