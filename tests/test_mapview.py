import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from dengue_link.mapview import render

RAW = Path(__file__).parent.parent / "data" / "raw"


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    upazilas = json.loads((RAW / "upazilas.geojson").read_text())
    uid_district = {f["properties"]["shapeID"]: "Dhaka" for f in upazilas["features"]}
    districts = pd.DataFrame(
        {
            "division": ["Dhaka", "Chittagong", "Chittagong"],
            "recent_cases": [437, 72, 22],
            "share": [0.5, 0.6, 0.2],
            "next7": [900.0, 300.0, 80.0],
            "change": [0.2, 0.4, 0.4],
            "population": [14_700_000, 9_100_000, 100_000],
            "in_hospital": [663, 119, 32],
            "deaths_year": [74, 13, 1],
        },
        index=["Dhaka", "Chittagong", "Cox's Bazar"],
    )
    divisions = pd.DataFrame({"recent": [1800.0, 500.0], "next7": [2160.0, 700.0], "change": [0.2, 0.4]}, index=["Dhaka", "Chittagong"])
    out = tmp_path_factory.mktemp("map") / "map.html"
    render(
        out,
        upazilas=upazilas,
        upazila_district=uid_district,
        districts=districts,
        divisions=divisions,
        novelty={"week": "2026-09-10", "score": 0.81},
        backtest={"model_mae": 120.0, "baseline_mae": 150.0, "n": 40},
        wards=None,
        country=json.loads((RAW / "country.geojson").read_text()),
        district_shapes=json.loads((RAW / "districts.geojson").read_text()),
        bn=json.loads((RAW / "bangla_names.json").read_text(encoding="utf-8")),
        national={"date": "2026-09-17", "in_hospital": 1484, "deaths_year": 176, "deaths_24h": 5},
        mosquito={"weeks": [
            {"end": "2026-08-04", "adults": {1: 23, 2: 9, 3: 21, 4: 36, 5: 34}, "larvae": {1: 0, 2: 0, 3: 0, 4: 90, 5: 3}},
            {"end": "2026-08-11", "adults": {1: 10, 2: 8, 3: 23, 4: 45, 5: 40}, "larvae": {1: 0, 2: 7, 3: 0, 4: 125, 5: 8}},
        ]},
        ward_spray={9: 6},
        as_of=date(2026, 9, 19),
        sources=[("DGHS dashboard", "ok", "37 weeks")],
        who={
            "patients": {"0-15": {"male": 60, "female": 40}, "16-30": {"male": 250, "female": 150}, "31-45": {"male": 200, "female": 100},
                         "46-60": {"male": 90, "female": 60}, "61+": {"male": 20, "female": 30}},
            "deaths": {"0-15": {"male": 1, "female": 1}, "16-30": {"male": 2, "female": 4}, "31-45": {"male": 3, "female": 5},
                       "46-60": {"male": 1, "female": 2}, "61+": {"male": 0, "female": 1}},
        },
        city={"DNCC": {"day": 61, "year": 6826}, "DSCC": {"day": 40, "year": 7142}},
        hospitals={"checked": "2026-09-18", "items": [
            {"name": "Dhaka Medical College Hospital", "bn": "ঢাকা মেডিকেল কলেজ হাসপাতাল", "kind": "medical_college", "lat": 23.72694,
             "lon": 90.39749, "phone": "01701248097", "emergency": True, "ambulance": True, "beds": 2600, "district": "Dhaka"},
            {"name": "Pinless General Hospital", "bn": "পিনছাড়া জেনারেল হাসপাতাল", "kind": "district", "lat": None, "lon": None,
             "phone": None, "emergency": True, "ambulance": False, "beds": 250, "district": "Dhaka"}]},
        weather={"date": "2026-09-19", "divisions": {"Dhaka": {"coverage": "MANY PLACES", "heavy": True}}},
        warnings=[{"divisions": ["Chittagong"], "expires": "2026-09-21T02:00:00+00:00", "web": "https://cap.bmd.gov.bd/x/",
                   "en": {"headline": "Heavy Rainfall Warning for Chattogram Division", "instruction": "Take precaution against waterlogging."},
                   "bn": {"headline": "চট্টগ্রাম বিভাগের জন্য ভারী বৃষ্টিপাতের সতর্কবার্তা", "instruction": "জলাবদ্ধতা বিষয়ে সতর্ক থাকুন।"}}],
        ward_risk={"date": "2026-09-13", "wards": {"9": {"level": "Moderate", "patients": 40}, "17": {"level": "High", "patients": 167},
                                                    "1": {"level": "Low", "patients": 18}}},
        spray={"checked": "2026-09-18", "items": {"9": [{"days": [1, 5], "areas": [["Mirpur 1", "মিরপুর ১"]]}]}},
        past_weeks=pd.DataFrame({"Dhaka": [100.0, 3000.0], "Chittagong": [50.0, 400.0]}, index=pd.to_datetime(["2026-09-03", "2026-09-10"])),
        test_centres={"checked": "2026-09-18", "items": [
            {"name": "Nagar Shastho Kendra-5, Kuril", "bn": "নগর স্বাস্থ্য কেন্দ্র-৫, কুড়িল", "kind": "free", "ward": 17, "lat": 23.82, "lon": 90.42, "approx": True}]},
    )
    return out.read_text()


def _view(page, name):
    section = page[page.index(f'id="view-{name}"'):]
    ends = [i for i in (section.find('<section class="view', 1), section.find("</main>")) if i > 0]
    return section[: min(ends)]


def _data(page):
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))


def test_map_is_drawn_by_district_with_upazilas_only_as_search_names(page):
    data = _data(page)
    assert "upazilas" not in data
    assert len(data["districtShapes"]["features"]) == 64
    assert data["districts"]["Dhaka"]["next7"] == 900.0
    assert len(data["upazilaIndex"]) == 544
    assert {"name": "Savar", "district": "Dhaka"}.items() <= next(u for u in data["upazilaIndex"] if u["name"] == "Savar").items()


def test_page_says_where_the_numbers_come_from(page):
    assert "division forecast" in page and "district share" in page
    assert "scheduled" in page
    assert "DGHS dashboard" in page


def test_rising_list_and_accessible_table_are_present(page):
    assert re.search(r'<ol[^>]*id="rising"', page)
    assert "<table" in page and "<caption" in page
    assert page.count("<tr data-district") == 3


def test_fly_novelty_and_backtest_are_shown(page):
    assert "0.81" in page
    assert "120" in page and "150" in page


def test_names_with_quotes_do_not_break_the_embedded_json(page):
    assert _data(page)["districts"]["Cox's Bazar"]["division"] == "Chittagong"
    assert "</script>" not in re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)


def test_unavailable_page_names_the_failed_source_and_shows_no_forecast(tmp_path):
    from dengue_link.mapview import render_unavailable

    out = tmp_path / "map.html"
    render_unavailable(out, as_of=date(2026, 9, 19), sources=[("DGHS dashboard", "unavailable right now", "timed out")])
    page = out.read_text()
    assert "DGHS dashboard" in page and "not available right now" in page
    assert "timed out" not in page
    assert "No forecast" in page
    assert 'id="data"' not in page


def test_menu_has_five_linkable_views(page):
    for view in ("map", "risk", "control", "help", "about"):
        assert f'href="#{view}"' in page
        assert f'id="view-{view}"' in page
    assert 'href="#divisions"' not in page and 'href="#safety"' not in page
    assert page.count("<li><a href=\"#") == 5
    assert "grid-template-columns:repeat(5,1fr)" in page
    assert 'aria-label="Views"' in page


def test_divisions_are_a_switch_inside_hotspots(page):
    risk = _view(page, "risk")
    assert 'id="rising"' in risk and 'id="division-cards"' in risk
    assert risk.count('aria-pressed="') == 2
    assert "Districts" in risk and "Divisions" in risk and "বিভাগ" in risk


def test_first_screen_answers_before_you_search(page):
    assert 'id="answer"' in _view(page, "map")
    assert "Use my location" in page and "আমার অবস্থান" in page
    assert "Pick your district" in page and "জেলা বেছে নিন" in page
    assert "navigator.geolocation" in page
    assert "dl-place" in page


def test_location_is_matched_to_a_district_inside_the_browser(page):
    script = page[page.index("var T = {"):]
    assert "function districtAt(" in script
    assert "fetch(" not in script and "XMLHttpRequest" not in script


def test_legend_is_always_showing(page):
    assert '<details class="overlay" id="legend"' not in page
    assert 'id="legend"' in _view(page, "map")
    assert '.open = false' not in page


def test_place_panel_is_one_line_three_facts_and_a_call_button(page):
    script = page[page.index("var T = {"):]
    assert 'el("ul", "facts")' in script
    assert '"tel:16263"' in script
    assert script.index("perLakh")  # still available, but under More detail
    assert script.index('t("perLakh")') > script.index('el("summary"')


def test_get_help_page_has_tap_to_call_numbers_with_official_sources(page):
    helpv = _view(page, "help")
    for number in ("16263", "999", "01709900888"):
        assert f'href="tel:{number}"' in helpv
    for site in ("16263.dghs.gov.bd", "bangladesh.gov.bd", "dscc.gov.bd"):
        assert site in helpv
    assert "333" not in helpv


def test_advice_is_taken_from_the_national_guideline_and_says_so(page):
    helpv = _view(page, "help")
    assert "National Guideline for Clinical Management of Dengue" in helpv and "5th edition" in helpv
    assert "dghs.gov.bd/pages/static-pages/6922e05c933eb65569e26afe" in helpv
    assert "ORS" in helpv and "ওআরএস" in helpv
    assert "3 g" in helpv
    assert "ibuprofen" in helpv
    assert "cold and clammy" in helpv.lower()


def test_who_is_getting_sick_is_shown_in_plain_age_bands(page):
    risk = _view(page, "risk")
    assert 'id="who"' in risk
    assert "16 to 30" in risk and "১৬ থেকে ৩০" in risk
    assert "40%" in risk and "৪০%" in risk
    assert "62%" in risk  # men among patients: 620 of 1,000


def test_dhaka_north_and_south_counts_reach_the_place_panel(page):
    assert _data(page)["city"] == {"DNCC": {"day": 61, "year": 6826}, "DSCC": {"day": 40, "year": 7142}}
    assert "cityLine" in page


def test_theme_can_be_switched_between_light_and_dark(page):
    assert 'id="theme-toggle"' in page and "aria-pressed" in page
    assert '[data-theme="dark"]' in page
    assert "localStorage" in page


def test_places_can_be_searched_by_upazila_with_district_shown(page):
    assert 'role="combobox"' in page and 'aria-controls="search-results"' in page
    assert 'role="listbox"' in page
    assert "Nothing found for" in page


def test_districts_get_plain_word_risk_levels(page):
    data = _data(page)
    levels = {d["level"] for d in data["districts"].values()}
    assert levels <= {"Very low", "Low", "Medium", "High", "Very high"}
    assert data["districts"]["Cox's Bazar"]["level"] == "Very high"
    assert "Very high" in page


def test_map_is_kept_to_bangladesh(page):
    data = _data(page)
    assert data["country"]["type"] == "MultiPolygon"
    assert "setMaxBounds" in page and "setMinZoom" in page


def test_map_is_our_own_outline_map_with_no_background_tiles(page):
    assert "tileLayer" not in page
    assert "arcgisonline" not in page and "openstreetmap.org" not in page and "cartocdn" not in page
    assert len(_data(page)["districtShapes"]["features"]) == 64
    assert "geoBoundaries" in page and "CC BY 3.0 IGO" in page


def test_page_can_be_read_in_bangla(page):
    data = _data(page)
    assert 'id="lang-toggle"' in page and "dl-lang" in page
    assert 'data-l="bn"' in page and 'data-l="en"' in page
    assert "খুব বেশি" in page
    assert "২,৩০০" in page or "৯০০" in page
    assert data["bn"]["district"]["Dhaka"] == "ঢাকা"


def test_risk_and_division_cards_sit_in_a_multi_column_grid(page):
    assert "repeat(auto-fill, minmax(" in page
    assert page.count('class="card district-card"') == 3


def test_upazila_search_result_explains_which_district_it_belongs_to(page):
    assert "inDistrict" in page
    assert "উপজেলা" in page


def test_mosquito_control_view_is_in_the_menu(page):
    assert 'href="#control"' in page and 'id="view-control"' in page
    assert "মশা নিধন" in page


def test_zone_cards_show_this_week_against_last_week(page):
    assert page.count('class="card zone-card"') == 5
    assert "<strong>45</strong>" in page and "36" in page
    assert "126" in page


def test_weekly_trend_and_what_dncc_is_doing_are_shown(page):
    assert '<svg class="spark"' in page
    assert "গৃহীত-পদক্ষেপসমূহ" in page or "static-pages" in page
    assert "Only Dhaka North City Corporation" in page


def test_ward_layer_carries_zone_mosquito_counts(page):
    data = _data(page)
    assert data["mosquito"]["weeks"][-1]["adults"]["4"] == 45


def test_fly_brain_scores_are_shown_for_past_weeks(tmp_path):
    from datetime import date

    import pandas as pd

    from dengue_link.mapview import render

    upazilas = json.loads((RAW / "upazilas.geojson").read_text())
    districts = pd.DataFrame({"division": ["Dhaka"], "recent_cases": [10], "share": [1.0], "next7": [20.0], "change": [0.1],
                              "population": [1_000_000], "in_hospital": [5], "deaths_year": [0]}, index=["Dhaka"])
    out = tmp_path / "m.html"
    render(out, upazilas=upazilas, upazila_district={}, districts=districts,
           divisions=pd.DataFrame({"recent": [10.0], "next7": [20.0], "change": [0.1]}, index=["Dhaka"]),
           novelty={"week": "2026-09-10", "score": 0.1,
                    "history": [("2026-07-30", 0.0), ("2026-08-06", 0.83), ("2026-08-13", 0.05)]},
           backtest={"model_mae": 1.0, "baseline_mae": 2.0, "n": 8}, wards=None, ward_spray={}, as_of=date(2026, 9, 19),
           sources=[], country=json.loads((RAW / "country.geojson").read_text()),
           district_shapes=json.loads((RAW / "districts.geojson").read_text()),
           bn=json.loads((RAW / "bangla_names.json").read_text(encoding="utf-8")), mosquito=None, national=None)
    page = out.read_text()
    assert page.count('<li class="nov') == 3
    assert page.count('class="nov odd"') == 1
    assert "6 August" in page and "৬ আগস্ট" in page


def test_risk_is_judged_per_100000_people_so_small_districts_are_not_hidden(page):
    data = _data(page)
    assert data["districts"]["Cox's Bazar"]["rate"] == pytest.approx(80.0)
    assert data["districts"]["Dhaka"]["level"] != "Very high"
    assert "for every 100,000 people" in page and "প্রতি ১ লাখ" in page
    assert page.index('data-district="Cox') < page.index('data-district="Dhaka"')


def test_hospital_load_and_deaths_are_shown(page):
    assert "1,484" in page and "176" in page
    assert "in hospital" in page and "হাসপাতালে" in page
    assert _data(page)["districts"]["Dhaka"]["in_hospital"] == 663


def test_exact_place_names_come_first_in_search(page):
    assert "exact" in page and "kind === \"district\"" in page


def test_protection_advice_has_its_own_menu_page(page):
    safety = _view(page, "help")
    assert "mosquito net" in safety and "মশারি" in safety
    assert "16263" in safety


def test_place_panel_no_longer_carries_the_advice(page):
    script = page[page.index("var T = {"):]
    assert "advice" not in script and "whatToDo" not in script


def test_wide_table_can_be_scrolled_by_keyboard(page):
    assert re.search(r'<div class="table-wrap" tabindex="0" role="region" aria-labelledby="[^"]+"', page)


def test_place_panel_closes_with_escape(page):
    assert 'e.key === "Escape" && !place.hidden' in page


def test_missing_hospital_figures_do_not_break_the_page(tmp_path):
    from datetime import date

    import numpy as np

    from dengue_link.mapview import render

    districts = pd.DataFrame({"division": ["Dhaka"], "recent_cases": [10], "share": [1.0], "next7": [20.0], "change": [0.1],
                              "population": [1_000_000], "in_hospital": [np.nan], "deaths_year": [np.nan]}, index=["Dhaka"])
    out = tmp_path / "m.html"
    render(out, upazilas=json.loads((RAW / "upazilas.geojson").read_text()), upazila_district={}, districts=districts,
           divisions=pd.DataFrame({"recent": [10.0], "next7": [20.0], "change": [0.1]}, index=["Dhaka"]), novelty=None,
           backtest={"model_mae": 1.0, "baseline_mae": 2.0, "n": 8}, wards=None, ward_spray={}, as_of=date(2026, 9, 19),
           sources=[], country=json.loads((RAW / "country.geojson").read_text()),
           district_shapes=json.loads((RAW / "districts.geojson").read_text()),
           bn=json.loads((RAW / "bangla_names.json").read_text(encoding="utf-8")), mosquito=None, national=None)
    page = out.read_text()
    payload = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    data = json.loads(payload, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert data["districts"]["Dhaka"]["in_hospital"] is None
    assert ">nan<" not in page


def test_mosquitoes_appearing_from_zero_count_as_going_up():
    from dengue_link.mapview import _control_view

    weeks = {"weeks": [{"end": "2026-08-04", "adults": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}, "larvae": {}},
                       {"end": "2026-08-11", "adults": {1: 40, 2: 0, 3: 0, 4: 0, 5: 0}, "larvae": {}}]}
    html = _control_view(weeks, {})
    zone1 = html[html.index("Uttara"):html.index("Mirpur")]
    assert "Going up" in zone1
    assert "About the same as the week before (0)" not in html


def test_nearest_hospital_finder_sits_on_the_get_help_page(page):
    helpv = _view(page, "help")
    assert 'id="hospital-finder"' in helpv
    assert "18 September 2026" in helpv and "১৮ সেপ্টেম্বর ২০২৬" in helpv
    assert "hrm.dghs.gov.bd" in helpv
    assert "not free beds" in helpv
    data = _data(page)
    assert data["hospitals"][0]["phone"] == "01701248097"
    assert data["testCentres"][0]["kind"] == "free"


def test_nearest_is_worked_out_in_the_browser_from_the_list_on_the_page(page):
    script = page[page.index("var T = {"):]
    assert "function nearest(" in script and "function km(" in script
    assert "fetch(" not in script
    assert "Nearest hospital" in script and "কাছের হাসপাতাল" in script
    assert "google.com/maps/search/" in script


def test_free_test_centres_say_their_exact_spot_is_not_published(page):
    assert "Free dengue test" in page and "বিনা মূল্যে ডেঙ্গু পরীক্ষা" in page
    assert "exact spot" in _view(page, "help")


def test_without_a_hospital_list_the_finder_is_left_out(tmp_path):
    out = tmp_path / "m.html"
    districts = pd.DataFrame({"division": ["Dhaka"], "recent_cases": [10], "share": [1.0], "next7": [20.0], "change": [0.1],
                              "population": [1_000_000], "in_hospital": [5], "deaths_year": [0]}, index=["Dhaka"])
    render(out, upazilas=json.loads((RAW / "upazilas.geojson").read_text()), upazila_district={}, districts=districts,
           divisions=pd.DataFrame({"recent": [10.0], "next7": [20.0], "change": [0.1]}, index=["Dhaka"]), novelty=None,
           backtest={"model_mae": 1.0, "baseline_mae": 2.0, "n": 8}, wards=None, ward_spray={}, as_of=date(2026, 9, 19),
           sources=[], country=json.loads((RAW / "country.geojson").read_text()),
           district_shapes=json.loads((RAW / "districts.geojson").read_text()),
           bn=json.loads((RAW / "bangla_names.json").read_text(encoding="utf-8")), mosquito=None)
    page = out.read_text()
    assert 'id="hospital-finder"' not in page
    assert _data(page)["hospitals"] is None


def test_hospitals_with_no_usable_pin_are_still_listed_for_their_district(page):
    script = page[page.index("var T = {"):]
    assert "alsoIn" in script
    assert "no usable map pin" in script and "অবস্থান তালিকায় ঠিকমতো দেওয়া নেই" in script
    assert _data(page)["hospitals"][1]["lat"] is None


def test_the_map_is_only_fitted_once_it_is_on_screen(page):
    assert 'if (v === "map" && !fitted)' in page
    assert "fitCountry();\n})();" not in page


def test_past_weeks_can_be_replayed_on_the_map_with_the_same_colour_scale(page):
    history = _data(page)["history"]
    assert history["weeks"] == ["2026-09-03", "2026-09-10"]
    dhaka, cox = history["levels"]["Dhaka"], history["levels"]["Cox's Bazar"]
    assert len(dhaka) == 2 and dhaka[0] < dhaka[1]
    assert cox == [4, 4] and history["levels"]["Chittagong"] == [1, 1]
    assert 'id="week"' in _view(page, "map") and 'type="range"' in _view(page, "map")
    assert "aria-valuetext" in page
    assert "shared between districts the same way as the forecast" in page


def test_todays_rain_forecast_and_official_warnings_reach_the_page(page):
    data = _data(page)
    assert data["weather"]["divisions"]["Dhaka"]["heavy"] is True
    assert data["warnings"][0]["divisions"] == ["Chittagong"]
    script = page[page.index("var T = {"):]
    assert "rainLine" in script and "Meteorological Department" in script and "আবহাওয়া অধিদপ্তর" in script
    assert "empty" in script.lower() and "w.expires" in script


def test_home_checklist_is_kept_on_the_device_and_reset_by_rain(page):
    helpv = _view(page, "help")
    assert 'id="home-check"' in helpv and helpv.count('type="checkbox"') == 6
    assert "AC tray" in helpv and "এসির ট্রে" in helpv
    assert "dl-home" in page and "rainToday" in page


def test_dhaka_north_wards_show_dnccs_own_rating_and_spray_days(page):
    data = _data(page)
    assert data["wardRisk"]["wards"]["17"] == {"level": "High", "patients": 167}
    assert data["spray"]["9"][0]["days"] == [1, 5]
    assert "bindPopup" in page
    control = _view(page, "control")
    assert "1 ward" in control and "high risk" in control and "13 September" in control
    assert "১টি ওয়ার্ড" in control


def test_wards_stay_above_a_selected_district(page):
    assert 'map.createPane("wards")' in page
    assert page.count('pane: "wards"') == 2


def test_bangla_age_sentence_reads_correctly_for_every_band():
    from dengue_link.mapview import _who_view

    for band, phrase in (("0-15", "বয়স ১৫ বছর বা তার কম"), ("16-30", "বয়স ১৬ থেকে ৩০ বছর"), ("61+", "বয়স ৬০ বছরের বেশি")):
        counts = {b: {"male": 1, "female": 1} for b in ("0-15", "16-30", "31-45", "46-60", "61+")}
        counts[band] = {"male": 50, "female": 50}
        html = _who_view({"patients": counts, "deaths": counts})
        assert phrase in html
        assert "কম বছর বয়সী" not in html and "বেশি বছর বয়সী" not in html


def test_no_wards_at_high_risk_is_said_in_words_not_as_zero():
    from dengue_link.mapview import _ward_rating

    html = _ward_rating({"date": "2026-09-13", "wards": {"1": {"level": "Low", "patients": 3}, "2": {"level": "Moderate", "patients": 9}}})
    assert "no wards as high risk" in html and "1 ward as moderate risk" in html
    assert "বেশি ঝুঁকিতে কোনো ওয়ার্ড নেই" in html and "০টি" not in html


def test_the_999_card_says_the_call_is_free_not_the_ambulance(page):
    helpv = _view(page, "help")
    assert "কল করতে টাকা লাগে না" in helpv
    assert "বিনা মূল্যে, ২৪ ঘণ্টা" not in helpv


def test_nobody_is_told_to_call_a_centre_whose_number_we_do_not_show(page):
    helpv = _view(page, "help")
    assert "call first" not in helpv and "ফোন করে নিন" not in helpv


def test_phone_numbers_are_shown_in_bangla_digits_but_dialled_in_ascii(page):
    script = page[page.index("var T = {"):]
    assert "function digits(" in script
    assert 'a.href = "tel:" + x.phone' in script and "digits(x.phone)" in script


def test_past_week_titles_say_the_week_starts_on_that_date(page):
    script = page[page.index("var T = {"):]
    assert "শুরু হওয়া সপ্তাহ" in script and "তারিখের সপ্তাহ" not in script
    assert "week starting" in script


def test_names_from_outside_spreadsheets_are_never_put_into_the_page_as_html(page):
    script = page[page.index("var T = {"):]
    assert 'dot.setTooltipContent(el("span", null,' in script
    assert "dot.setTooltipContent(t(" not in script


def test_even_with_no_forecast_people_can_still_reach_a_doctor_or_an_ambulance(tmp_path):
    from dengue_link.mapview import render_unavailable

    out = tmp_path / "map.html"
    render_unavailable(out, as_of=date(2026, 9, 19), sources=[])
    page = out.read_text()
    assert 'href="tel:16263"' in page and 'href="tel:999"' in page
    assert "ডাক্তার" in page and "অ্যাম্বুলেন্স" in page


def test_skip_link_goes_to_the_district_list(page):
    assert '<a class="skip" href="#view-risk">' in page and 'id="view-risk"' in page
    assert '.replace(/^view-/, "")' in page


def test_location_errors_do_not_linger_once_a_place_is_chosen(page):
    script = page[page.index("var T = {"):]
    show_place = script[script.index("function showPlace("):script.index("document.addEventListener(\"keydown\"")]
    assert 'answerMsg.dataset.busy = ""' in show_place


def test_the_chosen_district_is_kept_even_when_the_browser_blocks_storage(page):
    script = page[page.index("var T = {"):]
    assert "var chosen = null" in script
    assert "if (chosen) return chosen" in script


def test_checklist_ticks_are_dated_in_dhaka_time_like_the_forecast(page):
    script = page[page.index("var T = {"):]
    assert "function dhakaDate(" in script
    assert "on: dhakaDate()" in script


def test_a_forecast_is_dated_not_called_today_and_expires_after_24_hours(page):
    script = page[page.index("var T = {"):]
    assert "latest forecast" in script and "সর্বশেষ পূর্বাভাস" in script
    assert "division today" not in script and "আজ " not in script[script.index("rainLine"):script.index("warnTitle")]
    assert "24 * 3600 * 1000" in script and "36 * 3600" not in script


def test_a_warning_without_a_web_address_gets_no_link(page):
    assert "if (w.web)" in page


def test_ward_ratings_test_centres_and_spray_days_each_carry_a_date(page):
    data = _data(page)
    assert data["sprayChecked"] == "2026-09-18"
    script = page[page.index("var T = {"):]
    assert "D.wardRisk.date" in script and "D.sprayChecked" in script
    helpv = _view(page, "help")
    assert helpv.count("18 September 2026") == 2
