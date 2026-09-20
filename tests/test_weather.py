import json
from pathlib import Path

import pytest

from dengue_link import db
from dengue_link.weather import store_response

FIXTURES = Path(__file__).parent / "fixtures"


def test_daily_weather_is_stored_per_district(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    store_response(conn, ["Dhaka", "Chittagong"], json.loads((FIXTURES / "openmeteo_2districts.json").read_text()))
    rows = dict(
        ((m, a), v)
        for m, a, v in conn.execute(
            "select metric, area, value from obs where source='open_meteo' and date='2026-08-02'"
        )
    )
    assert rows[("rain_mm", "Dhaka")] == 21.4
    assert rows[("temp_c", "Dhaka")] == 28.2
    assert rows[("humidity_pct", "Dhaka")] == 89
    assert ("rain_mm", "Chittagong") in rows


def test_response_must_line_up_with_requested_districts(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    with pytest.raises(ValueError):
        store_response(conn, ["Dhaka"], json.loads((FIXTURES / "openmeteo_2districts.json").read_text()))
