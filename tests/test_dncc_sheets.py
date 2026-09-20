import json
from datetime import date
from pathlib import Path

from dengue_link import dncc_sheets

CSV = (Path(__file__).parent / "fixtures" / "dncc_test_centres.csv").read_text(encoding="utf-8")
WARD_CENTRES = {1: (23.8759, 90.3795), 20: (23.78, 90.40)}


def test_test_centres_come_with_a_kind_and_a_map_pin():
    centres = dncc_sheets.parse_test_centres(CSV, WARD_CENTRES)
    hospital = next(c for c in centres if c["name"] == "Dhaka Infectious Disease Hospital")
    assert hospital == {"name": "Dhaka Infectious Disease Hospital", "bn": hospital["bn"], "kind": "government", "ward": 20,
                        "lat": 23.77611, "lon": 90.40585, "approx": False}
    assert hospital["bn"]
    assert {c["kind"] for c in centres} == {"free", "diagnostic", "government"}


def test_free_centres_have_no_published_pin_so_they_are_placed_at_their_ward():
    free = [c for c in dncc_sheets.parse_test_centres(CSV, WARD_CENTRES) if c["kind"] == "free"]
    assert len(free) == 2
    assert all(c["approx"] and (c["lat"], c["lon"]) == WARD_CENTRES[1] for c in free)


def test_rows_with_no_kind_or_no_way_to_place_them_are_left_out():
    centres = dncc_sheets.parse_test_centres(CSV, {})
    assert [c["kind"] for c in centres] == ["diagnostic", "government"]
    assert "No Pin Diagnostic" not in [c["name"] for c in centres]


def test_contact_people_and_their_numbers_are_never_downloaded(tmp_path, monkeypatch):
    asked = []

    class Reply:
        text = CSV

        def raise_for_status(self):
            pass

    monkeypatch.setattr(dncc_sheets.requests, "get", lambda url, params, **k: asked.append(params) or Reply())
    dncc_sheets.test_centres(tmp_path, date(2026, 9, 20), WARD_CENTRES)
    assert asked[0]["tq"] == "select C, F, G, H, R, S"
    assert "mobile" not in CSV and "focal_person" not in CSV and "email" not in CSV


def test_the_list_is_downloaded_once_a_week(tmp_path, monkeypatch):
    calls = []

    class Reply:
        text = CSV

        def raise_for_status(self):
            pass

    monkeypatch.setattr(dncc_sheets.requests, "get", lambda url, params, **k: calls.append((url, params["sheet"])) or Reply())
    first = dncc_sheets.test_centres(tmp_path, date(2026, 9, 20), WARD_CENTRES)
    assert calls[0][1] == "list_hosp_diag_ward" and "docs.google.com/spreadsheets" in calls[0][0]
    assert len(first["items"]) == 4 and first["checked"] == "2026-09-20"
    dncc_sheets.test_centres(tmp_path, date(2026, 9, 22), WARD_CENTRES)
    assert len(calls) == 1


RISK = (Path(__file__).parent / "fixtures" / "dncc_ward_risk.csv").read_text(encoding="utf-8")
SPRAY = (Path(__file__).parent / "fixtures" / "dncc_spray_schedule.csv").read_text(encoding="utf-8")


def test_ward_risk_is_read_for_the_newest_day_only():
    out = dncc_sheets.parse_ward_risk(RISK, date(2026, 9, 20))
    assert out["date"] == "2026-09-13"
    assert out["wards"] == {"1": {"level": "Low", "patients": 18}, "17": {"level": "Moderate", "patients": 167},
                            "29": {"level": "Moderate", "patients": 180}}


def test_spray_days_are_grouped_by_area_and_read_in_either_language():
    out = dncc_sheets.parse_spray(SPRAY)
    assert out["1"] == [{"days": [1, 5], "areas": [["Uttara Sector 4", "উত্তরা সেক্টর ৪"]]}]
    assert out["29"][0]["days"] == [1, 5]
    assert "2" not in out and "3" not in out


def test_messy_day_spellings_still_give_the_right_days():
    assert dncc_sheets._days("Saturday এবং Tuesday", "") == [1, 5]
    assert dncc_sheets._days("সেমবার and Thursday", "সোমবার ও বৃহস্পতিবার") == [0, 3]
    assert dncc_sheets._days("Monday/Thursday", "") == [0, 3]
    assert dncc_sheets._days("NA", "NA") == []


def test_supervisor_names_and_numbers_are_never_asked_for(tmp_path, monkeypatch):
    asked = []

    class Reply:
        def __init__(self, tab):
            self.text = {"list_hosp_diag_ward": CSV, "mosquito_control_detailed": SPRAY}.get(tab, RISK)

        def raise_for_status(self):
            pass

    monkeypatch.setattr(dncc_sheets.requests, "get", lambda url, params, **k: asked.append(params) or Reply(params["sheet"]))
    out = dncc_sheets.fetch(tmp_path, date(2026, 9, 20), WARD_CENTRES)
    assert out["wards"]["date"] == "2026-09-13" and out["spray"]["items"]["1"] and len(out["centres"]["items"]) == 4
    spray_query = next(p["tq"] for p in asked if p["sheet"] == "mosquito_control_detailed")
    assert spray_query == "select C, E, F, G, H, I, J"


def test_a_pin_outside_dhaka_falls_back_to_the_ward():
    singapore = CSV.replace('"90.40585","23.77611"', '"103.8348","1.30405"')
    assert singapore != CSV
    hospital = next(c for c in dncc_sheets.parse_test_centres(singapore, WARD_CENTRES) if c["name"] == "Dhaka Infectious Disease Hospital")
    assert hospital["approx"] and (hospital["lat"], hospital["lon"]) == WARD_CENTRES[20]
    assert "Dhaka Infectious Disease Hospital" not in [c["name"] for c in dncc_sheets.parse_test_centres(singapore, {})]


def test_ward_ratings_that_dncc_has_stopped_updating_are_not_shown_as_current():
    assert dncc_sheets.parse_ward_risk(RISK, date(2026, 10, 4))["date"] == "2026-09-13"
    assert dncc_sheets.parse_ward_risk(RISK, date(2026, 10, 5)) is None


def test_a_changed_date_format_is_an_error_not_a_wrong_answer():
    import pytest

    with pytest.raises(ValueError):
        dncc_sheets.parse_ward_risk(RISK.replace("2026-09-13", "13/09/2026"), date(2026, 9, 20))


def test_one_broken_sheet_does_not_take_the_others_with_it(tmp_path, monkeypatch):
    import pytest

    class Reply:
        def __init__(self, tab):
            self.text = {"list_hosp_diag_ward": CSV, "mosquito_control_detailed": SPRAY}[tab]

        def raise_for_status(self):
            pass

    def get(url, params, **k):
        if params["sheet"] not in ("list_hosp_diag_ward", "mosquito_control_detailed"):
            raise ConnectionError("risk sheet down")
        return Reply(params["sheet"])

    monkeypatch.setattr(dncc_sheets.requests, "get", get)
    out = dncc_sheets.fetch(tmp_path, date(2026, 9, 20), WARD_CENTRES)
    assert out["wards"] is None and len(out["centres"]["items"]) == 4 and out["spray"]["items"]["1"]

    def all_down(url, params, **k):
        raise ConnectionError("google down")

    monkeypatch.setattr(dncc_sheets.requests, "get", all_down)
    with pytest.raises(ConnectionError):
        dncc_sheets.fetch(tmp_path / "empty", date(2026, 9, 20), WARD_CENTRES)
