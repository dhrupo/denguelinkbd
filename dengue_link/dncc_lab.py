import csv
import io
from datetime import date

import requests

from dengue_link import db

URL = "https://raw.githubusercontent.com/dnccinnovationlab/dengue-dashboard/main/daily_dengue_dghs.csv"
COLUMNS = {
    "affected": ("dengue_admit_24h", "Bangladesh"),
    "death": ("dengue_death_24h", "Bangladesh"),
    "dncc_case": ("dengue_admit_24h", "DNCC"),
    "dncc_death": ("dengue_death_24h", "DNCC"),
    "dscc_case": ("dengue_admit_24h", "DSCC"),
    "dscc_death": ("dengue_death_24h", "DSCC"),
}


def import_csv(conn, text):
    for row in csv.DictReader(io.StringIO(text)):
        day = date.fromisoformat(row["date"])
        by_metric = {}
        for col, (metric, area) in COLUMNS.items():
            if row[col] not in ("", "NA"):
                by_metric.setdefault(metric, {})[area] = float(row[col])
        for metric, values in by_metric.items():
            db.put(conn, "dncc_lab", metric, day, values)


def fetch(conn, today=None):
    today = today or date.today()
    latest = conn.execute("select max(date) from obs where source='dncc_lab'").fetchone()[0]
    if latest and date.fromisoformat(latest) >= date(today.year - 1, 12, 1):
        return 0
    r = requests.get(URL, timeout=60)
    r.raise_for_status()
    import_csv(conn, r.text)
    return 1
