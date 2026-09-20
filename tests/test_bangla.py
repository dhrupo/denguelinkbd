from pathlib import Path

import pytest

from dengue_link.areas import build_areas
from dengue_link.bangla import bangla_names, bn_digits

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
BN = Path(__file__).parent / "fixtures" / "bn"


@pytest.fixture(scope="module")
def names():
    areas = build_areas(RAW / "districts.geojson", RAW / "upazilas.geojson", RAW / "divisions.geojson")
    return areas, bangla_names(areas, BN / "bd_divisions.json", BN / "bd_districts.json", BN / "bd_upazilas.json")


def test_every_division_and_district_has_a_bangla_name(names):
    areas, bn = names
    assert set(bn["division"]) == set(areas.division_centroid)
    assert set(bn["district"]) == set(areas.districts)
    assert bn["district"]["Chittagong"] == "চট্টগ্রাম"
    assert bn["district"]["Nawabganj"] == "চাঁপাইনবাবগঞ্জ"
    assert bn["division"]["Dhaka"] == "ঢাকা"


def test_upazilas_get_bangla_names_within_their_own_district(names):
    areas, bn = names
    by_name = {}
    for uid, name in areas.upazila_name.items():
        if uid in bn["upazila"]:
            by_name.setdefault((name, areas.upazila_district[uid]), bn["upazila"][uid])
    assert by_name[("Savar", "Dhaka")] == "সাভার"
    assert by_name[("Teknaf", "Cox's Bazar")] == "টেকনাফ"
    assert by_name[("Mirpur", "Kushtia")] == "মিরপুর"
    assert len(bn["upazila"]) >= 460


def test_numbers_are_written_with_bangla_digits():
    assert bn_digits("2,300") == "২,৩০০"
    assert bn_digits("11%") == "১১%"
