import json
from datetime import date
from pathlib import Path

import pytest

from dengue_link import hospitals

PAGE = json.loads((Path(__file__).parent / "fixtures" / "dghs_facilities_page.json").read_text())


def anywhere(name, lat, lon):
    return True


def test_only_the_fields_the_public_needs_are_kept():
    items, last_page = hospitals.parse_page(PAGE, anywhere)
    assert last_page == 1
    dmch = next(h for h in items if h["name"] == "Dhaka Medical College Hospital")
    assert dmch == {"name": "Dhaka Medical College Hospital", "bn": "ঢাকা মেডিকেল কলেজ হাসপাতাল", "kind": "medical_college", "district": "Dhaka",
                    "lat": 23.72694, "lon": 90.39749, "phone": "01701248097", "emergency": True, "ambulance": True, "beds": 2600}


def test_staff_names_personal_numbers_and_bank_details_never_leave_the_registry():
    kept = json.dumps(hospitals.parse_page(PAGE, anywhere)[0], ensure_ascii=False)
    raw = json.dumps(PAGE, ensure_ascii=False)
    for private in ("01700000000", "head@example.com", "0000000000000"):
        assert private in raw and private not in kept
    assert "account" not in kept and "head" not in kept


def test_hospitals_without_a_map_pin_are_kept_under_their_district():
    items = hospitals.parse_page(PAGE, anywhere)[0]
    assert len(items) == 3
    satkhira = next(h for h in items if h["name"].startswith("Satkhira"))
    assert (satkhira["lat"], satkhira["lon"], satkhira["district"], satkhira["phone"]) == (None, None, "Satkhira", "01701248109")


@pytest.mark.parametrize("fields, expected", [
    ({"official_contact_no": None, "mobile_1": "coxmch@hospi.dghs. gov.bd", "land_phone_1": None}, None),
    ({"official_contact_no": None, "mobile_1": "00000000000", "land_phone_1": "02-478847701"}, "02478847701"),
    ({"official_contact_no": None, "mobile_1": None, "land_phone_1": "55165143"}, None),
    ({"official_contact_no": "01701 248097", "mobile_1": "01715016984", "land_phone_1": None}, "01701248097"),
])
def test_only_numbers_that_can_be_dialled_are_kept(fields, expected):
    assert hospitals._phone(fields) == expected


class _Registry:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, url, params, **_):
        self.calls.append((params["facility_type_id"], params["page"]))
        if self.calls[-1] == self.fail_on:
            raise ConnectionError("registry down")
        page = json.loads(json.dumps(PAGE))
        page["data"]["last_page"] = 2 if params["facility_type_id"] == 29 else 1

        class Reply:
            def raise_for_status(self):
                pass

            def json(self):
                return page

        return Reply()


def test_every_page_of_the_three_hospital_types_is_read_once_a_week(tmp_path, monkeypatch):
    registry = _Registry()
    monkeypatch.setattr(hospitals.requests, "get", registry)
    first = hospitals.fetch(tmp_path, anywhere, date(2026, 9, 20))
    assert sorted(registry.calls) == [(5, 1), (28, 1), (29, 1), (29, 2)]
    assert first["checked"] == "2026-09-20" and len(first["items"]) == 12
    again = hospitals.fetch(tmp_path, anywhere, date(2026, 9, 26))
    assert len(registry.calls) == 4 and again == first
    hospitals.fetch(tmp_path, anywhere, date(2026, 9, 27))
    assert len(registry.calls) == 8


def test_a_half_finished_download_does_not_replace_the_saved_list(tmp_path, monkeypatch):
    monkeypatch.setattr(hospitals.requests, "get", _Registry())
    hospitals.fetch(tmp_path, anywhere, date(2026, 9, 1))
    monkeypatch.setattr(hospitals.requests, "get", _Registry(fail_on=(29, 2)))
    with pytest.raises(ConnectionError):
        hospitals.fetch(tmp_path, anywhere, date(2026, 9, 20))
    assert json.loads((tmp_path / "hospitals.json").read_text())["checked"] == "2026-09-01"


def test_a_hospital_pinned_outside_its_own_district_is_left_out():
    asked = []

    def only_dhaka(name, lat, lon):
        asked.append((name, lat, lon))
        return False

    dmch = next(h for h in hospitals.parse_page(PAGE, only_dhaka)[0] if h["name"].startswith("Dhaka"))
    assert (dmch["lat"], dmch["lon"], dmch["district"]) == (None, None, "Dhaka")
    assert asked == [("Dhaka", 23.726939279843375, 90.39748628465777)]


def test_the_registrys_new_district_spellings_are_matched_to_the_map():
    page = json.loads(json.dumps(PAGE))
    page["data"]["items"][0]["district_name"] = "Chattogram"
    asked = []
    hospitals.parse_page(page, lambda name, lat, lon: asked.append(name) or True)
    assert asked == ["Chittagong"]
