from datetime import date
from pathlib import Path

from dengue_link.dghs_dashboard import parse_division_weeks

FIXTURES = Path(__file__).parent / "fixtures"


def test_weekly_division_cases_are_read_from_the_dashboard():
    weeks = parse_division_weeks((FIXTURES / "dghs_dashboard.html").read_text())
    assert set(weeks.columns) == {"Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"}
    assert len(weeks) == 37
    assert weeks.index[0] == date(2026, 1, 4)
    assert weeks.loc[date(2026, 1, 4), "Barisal"] == 67
    assert weeks.loc[date(2026, 1, 11), "Dhaka"] == 130
    assert weeks.loc[date(2026, 1, 4), "Chittagong"] == 129


def test_patients_and_deaths_are_grouped_into_five_plain_age_bands():
    from dengue_link.dghs_dashboard import parse_age_sex

    html = (FIXTURES / "dghs_dashboard.html").read_text()
    patients = parse_age_sex(html, "dengue_affected_by_age_group")
    assert list(patients) == ["0-15", "16-30", "31-45", "46-60", "61+"]
    assert patients["0-15"] == {"male": 1664 + 1651 + 2347 + 1, "female": 1292 + 1290 + 1341}
    assert patients["61+"] == {"male": 683 + 458 + 213 + 129 + 93, "female": 432 + 278 + 99 + 65 + 44}
    deaths = parse_age_sex(html, "dengue_death_by_age_group")
    assert deaths["16-30"] == {"male": 3 + 6 + 9, "female": 4 + 8 + 14}


def test_age_labels_the_dashboard_has_mangled_into_numbers_are_left_out():
    from dengue_link.dghs_dashboard import parse_age_sex

    patients = parse_age_sex((FIXTURES / "dghs_dashboard.html").read_text(), "dengue_affected_by_age_group")
    assert sum(b["male"] + b["female"] for b in patients.values()) == 58905 - 3


def test_dhaka_north_and_south_are_read_separately():
    from dengue_link.dghs_dashboard import parse_city_corporations

    html = (FIXTURES / "dghs_dashboard.html").read_text()
    assert parse_city_corporations(html, "div_city_cor_case_last_24_hour") == {"DNCC": 61, "DSCC": 40}
    assert parse_city_corporations(html, "div_city_cor_case_in_year") == {"DNCC": 6826, "DSCC": 7142}


def test_fetch_stores_who_is_getting_sick_alongside_the_weekly_cases(monkeypatch, tmp_path):
    from dengue_link import db, dghs_dashboard

    class Reply:
        text = (FIXTURES / "dghs_dashboard.html").read_text()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(dghs_dashboard.requests, "get", lambda *a, **k: Reply())
    conn = db.connect(tmp_path / "t.db")
    dghs_dashboard.fetch(conn)
    got = dict(conn.execute("select metric || ':' || area, value from obs where source='dghs_dashboard' and metric != 'dengue_admit_week'"))
    assert got["dengue_cases_year_female:16-30"] == 2660 + 2784 + 2906
    assert got["dengue_deaths_year_male:16-30"] == 18
    assert got["dengue_admit_24h_city:DNCC"] == 61 and got["dengue_admit_year_city:DSCC"] == 7142


def test_weeks_are_the_sunday_to_saturday_weeks_dghs_counts_in():
    from dengue_link.dghs_dashboard import week_start

    assert week_start(2026, 1) == date(2026, 1, 4) and week_start(2026, 1).weekday() == 6
    assert week_start(2026, 37) == date(2026, 9, 13)
    assert week_start(2025, 1) == date(2024, 12, 29)


def test_a_changed_side_chart_does_not_cost_us_the_weekly_cases(monkeypatch, tmp_path):
    from dengue_link import db, dghs_dashboard

    class Reply:
        text = (FIXTURES / "dghs_dashboard.html").read_text().replace("'dengue_death_by_age_group'", "'renamed_by_dghs'")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(dghs_dashboard.requests, "get", lambda *a, **k: Reply())
    conn = db.connect(tmp_path / "t.db")
    assert len(dghs_dashboard.fetch(conn)) == 37
    metrics = {m for (m,) in conn.execute("select distinct metric from obs")}
    assert "dengue_admit_week" in metrics and "dengue_cases_year_male" in metrics and "dengue_admit_year_city" in metrics
    assert "dengue_deaths_year_male" not in metrics
