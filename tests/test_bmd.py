import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dengue_link import bmd

F = Path(__file__).parent / "fixtures"
FEED = (F / "bmd_cap_feed.xml").read_text(encoding="utf-8")
RAIN = (F / "bmd_cap_rain.xml").read_text(encoding="utf-8")
MARITIME = (F / "bmd_cap_maritime.xml").read_text(encoding="utf-8")
FORECAST = json.loads((F / "bmd_division_forecast.json").read_text(encoding="utf-8"))
DURING = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)


def DHAKA(*parts):
    return datetime(*parts, tzinfo=timezone(timedelta(hours=6)))


def test_a_rain_warning_names_our_divisions_in_both_languages():
    w = bmd.parse_alert(RAIN, DURING)
    assert w["divisions"] == ["Khulna", "Barisal", "Chittagong", "Sylhet"]
    assert w["expires"] == "2026-08-19T02:00:00+00:00"
    assert w["en"]["headline"].startswith("Heavy Rainfall Warning for Khulna")
    assert "waterlogging" in w["en"]["instruction"]
    assert w["bn"]["headline"].startswith("খুলনা, বরিশাল") and "জলাবদ্ধতা" in w["bn"]["instruction"]
    assert w["web"].startswith("https://cap.bmd.gov.bd/")


def test_a_warning_that_has_run_out_is_dropped():
    assert bmd.parse_alert(RAIN, datetime(2026, 8, 19, 2, 0, 1, tzinfo=timezone.utc)) is None


def test_port_signals_are_not_rain_warnings_for_a_division():
    assert bmd.parse_alert(MARITIME, datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)) is None


def test_only_recent_alerts_are_opened_from_the_feed():
    assert bmd.recent_links(FEED, datetime(2026, 9, 20, tzinfo=timezone.utc)) == []
    assert bmd.recent_links(FEED, datetime(2026, 9, 12, tzinfo=timezone.utc)) == [
        "https://cap.bmd.gov.bd/api/cap/39b75b96-d793-43c7-9119-59fdfba2c5dd.xml"]
    assert len(bmd.recent_links(FEED, datetime(2026, 8, 18, tzinfo=timezone.utc))) == 1


def test_todays_forecast_says_where_rain_is_expected_and_whether_it_will_be_heavy():
    out = bmd.parse_forecast(FORECAST, DHAKA(2026, 9, 20, 13))
    assert out["date"] == "2026-09-20"
    assert set(out["divisions"]) == {"Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"}
    assert out["divisions"]["Sylhet"] == {"coverage": "A FEW PLACES", "heavy": True}
    assert out["divisions"]["Dhaka"] == {"coverage": "MANY PLACES", "heavy": True}


def test_a_dry_division_gets_no_rain_line_and_an_old_forecast_is_not_used():
    dry = json.loads(json.dumps(FORECAST))
    dry[0]["weather"].update(rain="", coverage="", intensity="")
    assert "Dhaka" not in bmd.parse_forecast(dry, DHAKA(2026, 9, 20, 13))["divisions"]
    assert bmd.parse_forecast(FORECAST, DHAKA(2026, 9, 21, 8))["date"] == "2026-09-20"
    assert bmd.parse_forecast(FORECAST, DHAKA(2026, 9, 21, 10)) is None


def test_fetch_reads_the_forecast_and_only_the_recent_warnings(monkeypatch):
    asked = []

    class Reply:
        def __init__(self, url):
            self.text = {bmd.FEED_URL: FEED, bmd.FORECAST_URL: json.dumps(FORECAST)}.get(url, MARITIME)

        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(self.text)

    monkeypatch.setattr(bmd.requests, "get", lambda url, **k: asked.append(url) or Reply(url))
    out = bmd.fetch(None, now=datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc))
    assert out == {"forecast": None, "warnings": []}
    assert sorted(asked) == sorted([bmd.FEED_URL, bmd.FORECAST_URL, "https://cap.bmd.gov.bd/api/cap/39b75b96-d793-43c7-9119-59fdfba2c5dd.xml"])
    asked.clear()
    out = bmd.fetch(None, now=DHAKA(2026, 9, 20, 13))
    assert out["forecast"]["divisions"]["Dhaka"]["heavy"] and out["warnings"] == []
    assert sorted(asked) == sorted([bmd.FEED_URL, bmd.FORECAST_URL])


def test_a_cancelled_warning_is_not_shown():
    assert bmd.parse_alert(RAIN.replace("<cap:msgType>Alert</cap:msgType>", "<cap:msgType>Cancel</cap:msgType>"), DURING) is None


def test_an_alert_with_no_end_time_is_skipped_instead_of_crashing():
    import re

    assert bmd.parse_alert(re.sub(r"<cap:expires>[^<]*</cap:expires>", "", RAIN), DURING) is None


def test_the_notice_link_is_only_kept_when_it_is_a_web_address():
    import re

    assert bmd.parse_alert(re.sub(r"<cap:web>[^<]*</cap:web>", "<cap:web>javascript:alert(1)</cap:web>", RAIN), DURING)["web"] is None
    assert bmd.parse_alert(re.sub(r"<cap:web>[^<]*</cap:web>", "", RAIN), DURING)["web"] is None


def _feed(*ids):
    items = "".join(f"<item><title>x</title><link>https://cap.bmd.gov.bd/api/cap/{i}.xml</link><pubDate>Mon, 17 Aug 2026 07:46:00 +0000</pubDate></item>" for i in ids)
    return f"<rss><channel>{items}</channel></rss>"


def _serve(monkeypatch, pages):
    class Reply:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(self.text)

    def get(url, **k):
        if isinstance(pages[url], Exception):
            raise pages[url]
        return Reply(pages[url])

    monkeypatch.setattr(bmd.requests, "get", get)


def test_a_warning_that_bmd_has_replaced_or_cancelled_is_dropped(monkeypatch):
    first = "8b70982d-a6b3-468e-a69a-bf7b12f9931c"
    update = RAIN.replace(first, "new-id").replace("<cap:msgType>Alert</cap:msgType>",
                                                   f"<cap:msgType>Update</cap:msgType><cap:references>swc@bmd.gov.bd,{first},2026-08-17T07:46:00+00:00</cap:references>")
    _serve(monkeypatch, {bmd.FEED_URL: _feed("new-id", first), bmd.FORECAST_URL: json.dumps(FORECAST),
                         "https://cap.bmd.gov.bd/api/cap/new-id.xml": update, f"https://cap.bmd.gov.bd/api/cap/{first}.xml": RAIN})
    assert len(bmd.fetch(None, now=DURING)["warnings"]) == 1
    cancel = update.replace("<cap:msgType>Update</cap:msgType>", "<cap:msgType>Cancel</cap:msgType>")
    _serve(monkeypatch, {bmd.FEED_URL: _feed("new-id", first), bmd.FORECAST_URL: json.dumps(FORECAST),
                         "https://cap.bmd.gov.bd/api/cap/new-id.xml": cancel, f"https://cap.bmd.gov.bd/api/cap/{first}.xml": RAIN})
    assert bmd.fetch(None, now=DURING)["warnings"] == []


def test_the_forecast_survives_when_the_warning_server_is_down(monkeypatch):
    import pytest

    _serve(monkeypatch, {bmd.FEED_URL: ConnectionError("cap down"), bmd.FORECAST_URL: json.dumps(FORECAST)})
    out = bmd.fetch(None, now=DHAKA(2026, 9, 20, 13))
    assert out["forecast"]["divisions"]["Dhaka"]["heavy"] and out["warnings"] == []
    _serve(monkeypatch, {bmd.FEED_URL: ConnectionError("cap down"), bmd.FORECAST_URL: ConnectionError("mobile down")})
    with pytest.raises(ConnectionError):
        bmd.fetch(None, now=DHAKA(2026, 9, 20, 13))
