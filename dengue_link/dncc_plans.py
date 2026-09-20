import io
from concurrent.futures import ThreadPoolExecutor
import re
import sys
from datetime import date

import pypdf
import requests

from dengue_link import db
from dengue_link.fetch import get_pdf

# Plans are typed in SutonnyMJ (Bijoy ASCII), so Bangla words arrive as Latin byte soup:
# "IqvW© bs-9" is "ওয়ার্ড নং-৯", "kwbevi" is "শনিবার".
WEEKDAYS = {
    "kwbevi": "Sat", "iweevi": "Sun", "‡mvgevi": "Mon", "†mvgevi": "Mon", "g½jevi": "Tue",
    "eyaevi": "Wed", "e„n¯úwZevi": "Thu", "ïµevi": "Fri",
}
_WARD = re.compile(r"IqvW©\s*bs\s*-?\s*(\d+)|(\d+)\s*bs\s*IqvW©")


def plan_pdf_urls(html):
    urls = re.findall(r'href="(https://objectstorage[^"]+/office-dncc/(?!2024/12/)[^"]+\.pdf)"', html)
    return list(dict.fromkeys(urls))


def parse_plan_pdf(path):
    wards = {}
    for page in pypdf.PdfReader(path).pages:
        text = page.extract_text() or ""
        m = _WARD.search(text)
        if not m:
            continue
        ward = int(m.group(1) or m.group(2))
        wards.setdefault(ward, set()).update(day for word, day in WEEKDAYS.items() if word in text)
    return wards


def _download(url):
    try:
        return url, get_pdf(url)
    except Exception as e:
        print(f"FAILED {url}: {e}", file=sys.stderr)
        return url, None


def fetch(conn):
    html = requests.get("https://dncc.gov.bd/pages/mosquito-kill-plans", timeout=(5, 20)).text
    stored = 0
    with ThreadPoolExecutor(5) as pool:
        for url, body in pool.map(_download, plan_pdf_urls(html)):
            if body is None:
                continue
            try:
                wards = parse_plan_pdf(io.BytesIO(body))
            except Exception as e:
                print(f"FAILED {url}: {e}", file=sys.stderr)
                continue
            year, month = re.search(r"office-dncc/(\d{4})/(\d{1,2})/", url).groups()
            db.put(conn, "dncc", "spray_days_per_week", date(int(year), int(month), 1),
                   {f"DNCC-W{w:02d}": len(days) for w, days in wards.items()})
            stored += 1
    return stored
