import json
import re
import sys
from datetime import date, timedelta

import pandas as pd
import requests

from dengue_link import db
from dengue_link.fetch import HEADERS

URL = "https://dashboard.dghs.gov.bd/pages/heoc_dengue_v1.php"
DIVISION_NAMES = {"Chattogram": "Chittagong", "Barishal": "Barisal"}


def week_start(year, week):
    # DGHS counts Sunday-to-Saturday epidemiological weeks, week 1 being the one that holds 4 January.
    # Checked against its own daily series for 2026: 31 of 37 weekly totals match exactly this way, 1 of 37 counting from 1 January.
    jan4 = date(year, 1, 4)
    return jan4 - timedelta(days=(jan4.weekday() + 1) % 7) + timedelta(weeks=week - 1)


def parse_division_weeks(html):
    year = int(re.search(r"in division by EPI\s+\(Epidemiological\)\s+Week in\s+(\d{4})", html).group(1))
    start = html.index("Highcharts.chart('affected_in_division_by_week'")
    block = html[start : html.index("Highcharts.chart(", start + 1)]
    weeks = json.loads(re.search(r"categories:\s*(\[[^\]]*\])", block).group(1))
    series = {
        DIVISION_NAMES.get(name, name): json.loads(data)
        for name, data in re.findall(r"name:\s*['\"]([^'\"]+)['\"][^{}]*?data:\s*(\[[^\]]*\])", block)
    }
    index = [week_start(year, int(w[1:])) for w in weeks]
    return pd.DataFrame(series, index=index).astype(float)


AGE_BANDS = [(15, "0-15"), (30, "16-30"), (45, "31-45"), (60, "46-60"), (999, "61+")]


def _chart(html, chart):
    start = html.index(f"Highcharts.chart('{chart}'")
    return start, html[start : html.index("</script>", start)]


def parse_age_sex(html, chart):
    start, block = _chart(html, chart)
    labels = json.loads(re.findall(r"var categories\s*=\s*(\[[^\]]*\])", html[:start])[-1])
    counts = {name.lower(): json.loads(data) for name, data in re.findall(r"name:\s*'(Male|Female)',\s*data:\s*(\[[^\]]*\])", block)}
    out = {band: {"male": 0, "female": 0} for _, band in AGE_BANDS}
    for i, label in enumerate(labels):
        # The dashboard's spreadsheet turned a few labels into date numbers ("42309"); they hold 1-2 people, so they are left out.
        age = re.fullmatch(r"(\d{1,2})(-\d{1,2}|\+)", label)
        if not age:
            continue
        band = next(name for top, name in AGE_BANDS if int(age.group(1)) <= top)
        for sex in out[band]:
            out[band][sex] += abs(counts[sex][i])
    return out


def parse_city_corporations(html, chart):
    _, block = _chart(html, chart)
    names = json.loads(re.search(r"categories:\s*(\[[^\]]*\])", block).group(1))
    values = json.loads(re.search(r"data:\s*(\[[^\]]*\])", block).group(1))
    return {n: v for n, v in zip(names, values) if n in ("DNCC", "DSCC")}


def fetch(conn):
    r = requests.get(URL, headers={**HEADERS, "Referer": "https://dashboard.dghs.gov.bd/"}, timeout=60)
    r.raise_for_status()
    weeks = parse_division_weeks(r.text)
    for day, row in weeks.iterrows():
        db.put(conn, "dghs_dashboard", "dengue_admit_week", day, row.to_dict())
    side_charts = [(f"{metric}_{sex}", lambda chart=chart, sex=sex: {band: n[sex] for band, n in parse_age_sex(r.text, chart).items()})
                   for metric, chart in (("dengue_cases_year", "dengue_affected_by_age_group"), ("dengue_deaths_year", "dengue_death_by_age_group"))
                   for sex in ("male", "female")]
    side_charts += [("dengue_admit_24h_city", lambda: parse_city_corporations(r.text, "div_city_cor_case_last_24_hour")),
                    ("dengue_admit_year_city", lambda: parse_city_corporations(r.text, "div_city_cor_case_in_year"))]
    for metric, read in side_charts:
        # The forecast needs only the weekly cases above; DGHS renaming one of these extra charts must not cost us those.
        try:
            db.put(conn, "dghs_dashboard", metric, date.today(), read())
        except Exception as e:
            print(f"FAILED dashboard chart {metric}: {e}", file=sys.stderr)
    return weeks
