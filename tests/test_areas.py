from pathlib import Path

import pytest

from dengue_link.areas import build_areas

RAW = Path(__file__).parent.parent / "data" / "raw"


@pytest.fixture(scope="module")
def areas():
    return build_areas(RAW / "districts.geojson", RAW / "upazilas.geojson", RAW / "divisions.geojson")


def test_every_upazila_belongs_to_exactly_one_known_district(areas):
    assert len(areas.districts) == 64
    assert len(areas.upazila_district) == 544
    assert set(areas.upazila_district.values()) <= set(areas.districts)


def test_known_upazilas_land_in_the_right_district(areas):
    by_name = {}
    for uid, name in areas.upazila_name.items():
        by_name.setdefault(name, set()).add(areas.upazila_district[uid])
    assert by_name["Savar"] == {"Dhaka"}
    assert by_name["Teknaf"] == {"Cox's Bazar"}
    assert by_name["Mirpur"] == {"Dhaka", "Kushtia"}


def test_district_neighbours_follow_shared_borders(areas):
    assert {"Gazipur", "Narayanganj", "Manikganj", "Munshiganj"} <= areas.neighbours["Dhaka"]
    assert "Sylhet" not in areas.neighbours["Dhaka"]
    assert "Dhaka" not in areas.neighbours["Dhaka"]
    for d, ns in areas.neighbours.items():
        assert ns, d
        for n in ns:
            assert d in areas.neighbours[n]


def test_district_centroids_fall_inside_bangladesh(areas):
    lon, lat = areas.centroid["Dhaka"]
    assert 89.9 < lon < 90.6 and 23.5 < lat < 24.1
    assert len(areas.centroid) == 64


def test_districts_roll_up_into_the_eight_divisions(areas):
    assert sorted(set(areas.district_division.values())) == [
        "Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"
    ]
    assert len(areas.district_division) == 64
    assert areas.district_division["Gazipur"] == "Dhaka"
    assert areas.district_division["Cox's Bazar"] == "Chittagong"
    assert areas.district_division["Bogra"] == "Rajshahi"
    assert areas.district_division["Sherpur"] == "Mymensingh"


def test_division_neighbours_follow_shared_borders(areas):
    assert {"Mymensingh", "Sylhet", "Chittagong", "Khulna", "Barisal", "Rajshahi"} <= areas.division_neighbours["Dhaka"]
    assert "Rangpur" not in areas.division_neighbours["Dhaka"]


def test_division_centroids_exist_for_all_eight(areas):
    assert len(areas.division_centroid) == 8
    lon, lat = areas.division_centroid["Sylhet"]
    assert 91 < lon < 92.6 and 24 < lat < 25.3


def test_a_map_pin_is_checked_against_its_own_district():
    from dengue_link.areas import pin_checker

    in_district = pin_checker(RAW / "districts.geojson")
    assert in_district("Dhaka", 23.7269, 90.3975)
    assert not in_district("Sylhet", 23.7269, 90.3975)
    assert not in_district("Sylhet", 24.0, 92.0)
    assert not in_district("Atlantis", 23.7269, 90.3975)


def test_a_pin_just_over_a_simplified_border_still_counts():
    from dengue_link.areas import pin_checker

    in_district = pin_checker(RAW / "districts.geojson")
    assert in_district("Narayanganj", 23.7269, 90.4275) or in_district("Dhaka", 23.7269, 90.4275)
    assert not in_district("Dhaka", 23.7269, 91.2)
