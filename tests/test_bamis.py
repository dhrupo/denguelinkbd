import json
import re
from pathlib import Path

import pytest

from dengue_link import bamis

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "bamis_wrf_7day.html").read_text(encoding="utf-8")


def test_rain_for_the_next_days_is_read_for_every_district_under_our_names():
    out = bamis.parse(PAGE)
    ours = {f["properties"]["shapeName"] for f in json.loads((FIXTURES.parent.parent / "data" / "raw" / "districts.geojson").read_text())["features"]}
    assert (out["from"], out["to"]) == ("2026-10-07", "2026-10-15")
    assert set(out["districts"]) == ours
    assert out["districts"]["Dhaka"] == 10 and out["districts"]["Bagerhat"] == 7 and out["districts"]["Sylhet"] == 0
    assert out["districts"]["Chittagong"] >= 0 and out["districts"]["Comilla"] >= 0


def test_a_changed_table_is_an_error_not_a_wrong_answer():
    with pytest.raises(ValueError):
        bamis.parse(re.sub(r"Rainfall\s+Total", "Rain", PAGE))
    with pytest.raises(ValueError):
        bamis.parse(re.sub(r"\d{2} October 2026\s+to", "", PAGE))


def test_fetch_asks_for_the_seven_day_table(monkeypatch):
    asked = []

    class Reply:
        text = PAGE

        def raise_for_status(self):
            pass

    monkeypatch.setattr(bamis.requests, "get", lambda url, **k: asked.append(url) or Reply())
    assert bamis.fetch()["districts"]["Dhaka"] == 10
    assert asked == ["https://www.bamis.gov.bd/en/bmd/wrf/table/all/7"]
