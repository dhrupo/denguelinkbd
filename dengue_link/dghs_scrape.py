import io
import re
import sys

import requests

from dengue_link import db
from dengue_link.dghs_pdf import parse_dengue_pdf
from dengue_link.fetch import HEADERS, get_pdf

BASE = "https://dghs.gov.bd"
def release_urls(html):
    paths = re.findall(r'href="(/pages/press-releases/[^"]+-[0-9a-f]{24})"', html)
    return list(dict.fromkeys(BASE + p for p in paths))


def attachment_urls(html):
    return list(dict.fromkeys(re.findall(r'title="Click here to download"[^>]*href="([^"]+\.pdf)"', html)))


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r


def scrape(conn, list_pages=(1,)):
    done = db.seen(conn, "dghs")
    stored = 0
    for page in list_pages:
        releases = release_urls(_get(f"{BASE}/pages/press-releases?page={page}").text)
        if not releases:
            break
        # Measles-titled releases (হাম) carry only measles PDFs; skipping them saves most of the download time.
        for release in (r for r in releases if "হাম" not in r):
            for pdf_url in attachment_urls(_get(release).text):
                if pdf_url in done:
                    continue
                try:
                    report = parse_dengue_pdf(io.BytesIO(get_pdf(pdf_url)))
                except Exception as e:
                    print(f"FAILED {pdf_url}: {e}", file=sys.stderr)
                    continue
                db.mark_seen(conn, "dghs", pdf_url)
                done.add(pdf_url)
                if report is None:
                    continue
                db.put(conn, "dghs", "dengue_admit_24h", report.date, report.district_24h)
                db.put(conn, "dghs", "dengue_in_hospital", report.date, report.in_hospital)
                db.put(conn, "dghs", "dengue_deaths_year", report.date, report.deaths_year)
                db.put(conn, "dghs", "dengue_deaths_24h", report.date, {"Bangladesh": report.national_deaths_24h})
                stored += 1
    return stored
