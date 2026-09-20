from pathlib import Path

from dengue_link import db
from dengue_link.dncc_lab import import_csv

FIXTURES = Path(__file__).parent / "fixtures"


def _value(conn, metric, day, area):
    row = conn.execute(
        "select value from obs where source='dncc_lab' and metric=? and date=? and area=?", (metric, day, area)
    ).fetchone()
    return row and row[0]


def test_city_corporation_history_is_imported(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    import_csv(conn, (FIXTURES / "dncc_lab_daily.csv").read_text())
    assert _value(conn, "dengue_admit_24h", "2025-12-27", "DNCC") == 28
    assert _value(conn, "dengue_admit_24h", "2025-12-27", "DSCC") == 11
    assert _value(conn, "dengue_admit_24h", "2025-12-27", "Bangladesh") == 96
    assert _value(conn, "dengue_death_24h", "2025-12-27", "Bangladesh") == 0


def test_missing_values_are_left_out_not_stored_as_zero(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    import_csv(conn, (FIXTURES / "dncc_lab_daily.csv").read_text())
    assert _value(conn, "dengue_admit_24h", "2022-01-01", "DNCC") == 0
    assert _value(conn, "dengue_admit_24h", "2022-01-01", "DSCC") is None


def test_finished_seasons_are_not_downloaded_again(tmp_path, monkeypatch):
    from datetime import date

    from dengue_link import dncc_lab

    calls = []
    monkeypatch.setattr(dncc_lab.requests, "get", lambda *a, **k: calls.append(1))
    conn = db.connect(tmp_path / "t.db")
    db.put(conn, "dncc_lab", "dengue_admit_24h", date(2025, 12, 27), {"Bangladesh": 96})
    assert dncc_lab.fetch(conn, today=date(2026, 9, 19)) == 0
    assert calls == []
