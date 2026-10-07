import html
import re
from datetime import datetime

import requests

from dengue_link.fetch import HEADERS

# The Meteorological Department's own district forecast (BAMIS), totals for the coming days.
URL = "https://www.bamis.gov.bd/en/bmd/wrf/table/all/7"
MAP_NAMES = {"Barishal": "Barisal", "Bogura": "Bogra", "Brahmanbaria": "Brahamanbaria", "Chapai Nawabganj": "Nawabganj",
             "Chattogram": "Chittagong", "Cumilla": "Comilla", "Jashore": "Jessore", "Khagrachari": "Khagrachhari",
             "Moulvibazar": "Maulvibazar", "Netrokona": "Netrakona"}


def _cells(row, tag):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip() for c in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", row, re.S)]


def parse(page):
    span = re.search(r"(\d{2} \w+ \d{4}) to (\d{2} \w+ \d{4})", re.sub(r"\s+", " ", page))
    if not span:
        raise ValueError("BAMIS page no longer states the forecast dates")
    rows = re.findall(r"<tr.*?</tr>", page, re.S)
    head = next((_cells(r, "th") for r in rows if "<th" in r), [])
    if "Rainfall Total (mm)" not in head or "District" not in head:
        raise ValueError("BAMIS table no longer has a district rainfall column")
    rain, name = head.index("Rainfall Total (mm)"), head.index("District")
    districts = {}
    for r in rows:
        cells = _cells(r, "td")
        if len(cells) == len(head):
            districts[MAP_NAMES.get(cells[name], cells[name])] = float(cells[rain])
    if len(districts) < 60:
        raise ValueError(f"BAMIS table has only {len(districts)} districts")
    day = lambda s: datetime.strptime(s, "%d %B %Y").date().isoformat()
    return {"from": day(span.group(1)), "to": day(span.group(2)), "districts": districts}


def fetch():
    r = requests.get(URL, headers=HEADERS, timeout=(5, 20))
    r.raise_for_status()
    return parse(r.text)
