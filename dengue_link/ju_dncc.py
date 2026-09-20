import io
from concurrent.futures import ThreadPoolExecutor
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime

import pypdf
import requests

from dengue_link import db
from dengue_link.fetch import HEADERS, get_pdf

LIST_URL = "https://dncc.gov.bd/pages/reports?filters=%7B%22reports_type%22%3A%2269a6621af681a7e27286ba8c%22%7D"
ZONES = range(1, 6)
_WEEK = re.compile(r"Week (\d+) \(([^)]*?\d{4})\)")


@dataclass
class Surveillance:
    week: int
    start: date
    end: date
    aedes_adults: dict
    aedes_larvae: dict


def _day(month, day, year):
    return datetime.strptime(f"{month[:3]} {day} {year}", "%b %d %Y").date()


def _zone_rows(text, table, width):
    block = text[text.index(table):]
    block = block[: re.search(r"\nTotal \d", block).start()]
    # Older reports put a total "N" column before the species columns; skip it when present.
    head = block[block.index("Zone"):]
    skip = 1 if table == "Table 1" and re.search(r"\bN\b", head.split("Ae. aegypti")[0]) else 0
    rows = {}
    for line in block.split("\n"):
        nums = line.split()
        if len(nums) >= width + skip and all(n.isdigit() for n in nums[:width + skip]) and int(nums[0]) in ZONES:
            rows[int(nums[0])] = [int(n) for n in nums[1 + skip:width + skip]]
    if set(rows) != set(ZONES):
        raise ValueError(f"{table}: expected zones 1-5, got {sorted(rows)}")
    return rows


def parse_surveillance_pdf(source):
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(source).pages[:5])
    week, inside = _WEEK.search(text).groups()
    year = re.findall(r"\d{4}", inside)[-1]
    months = re.findall(r"[A-Za-z]+", inside)
    days = re.findall(r"\b\d{1,2}\b", inside)
    adults = _zone_rows(text, "Table 1", 3)
    larvae = _zone_rows(text, "Table 2", 2)
    return Surveillance(
        week=int(week),
        start=_day(months[0], days[0], year),
        end=_day(months[-1], days[-1], year),
        aedes_adults={z: aeg + alb for z, (aeg, alb) in adults.items()},
        aedes_larvae={z: n[0] for z, n in larvae.items()},
    )


def report_urls(html):
    return [u for u in dict.fromkeys(re.findall(r'href="(https://objectstorage[^"]+\.pdf)"', html)) if "/2024/12/" not in u]


def _download(url):
    try:
        return url, get_pdf(url)
    except (ValueError, requests.RequestException) as e:
        print(f"FAILED {url}: {e}", file=sys.stderr)
        return url, None


def fetch(conn):
    done = db.seen(conn, "ju_dncc")
    todo = [u for u in report_urls(requests.get(LIST_URL, headers=HEADERS, timeout=(5, 20)).text) if u not in done]
    stored = 0
    with ThreadPoolExecutor(5) as pool:
        for url, body in pool.map(_download, todo):
            if body is None:
                continue
            try:
                report = parse_surveillance_pdf(io.BytesIO(body))
            except Exception as e:
                print(f"FAILED {url}: {e}", file=sys.stderr)
                continue
            db.put(conn, "ju_dncc", "aedes_adults", report.end, {f"DNCC-Z{z}": n for z, n in report.aedes_adults.items()})
            db.put(conn, "ju_dncc", "aedes_larvae", report.end, {f"DNCC-Z{z}": n for z, n in report.aedes_larvae.items()})
            db.mark_seen(conn, "ju_dncc", url)
            stored += 1
    return stored
