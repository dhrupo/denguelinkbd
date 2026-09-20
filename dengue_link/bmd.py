import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from dengue_link.fetch import HEADERS

FEED_URL = "https://cap.bmd.gov.bd/api/cap/rss.xml"
FORECAST_URL = "https://mobile.bmd.gov.bd/warning_automation/divisional_forecast_latest.json"
CAP = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
DHAKA = timezone(timedelta(hours=6))
DIVISIONS = {"Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"}
MAP_NAMES = {"Chattogram": "Chittagong", "Barishal": "Barisal"}


def _division(name):
    name = name.strip().title()
    name = MAP_NAMES.get(name, name)
    return name if name in DIVISIONS else None


def recent_links(feed, now):
    links = []
    for item in ET.fromstring(feed).iter("item"):
        if timedelta(0) <= now - parsedate_to_datetime(item.findtext("pubDate")) <= timedelta(days=7):
            links.append(item.findtext("link"))
    return links


def replaced_ids(xml):
    # An Update or Cancel names the alerts it replaces as "sender,identifier,sent", separated by spaces.
    references = ET.fromstring(xml).findtext("cap:references", default="", namespaces=CAP)
    return {ref.split(",")[1] for ref in references.split() if ref.count(",") >= 2}


def parse_alert(xml, now):
    alert = ET.fromstring(xml)
    get = lambda node, tag: (node.findtext(f"cap:{tag}", namespaces=CAP) or "").strip()
    infos = {get(i, "language")[:2]: i for i in alert.findall("cap:info", CAP)}
    en = infos.get("en")
    if en is None or get(alert, "status") != "Actual" or get(alert, "msgType") == "Cancel" or get(en, "event") != "Rain" or not get(en, "expires"):
        return None
    expires = datetime.fromisoformat(get(en, "expires"))
    divisions = [d for d in (_division(get(a, "areaDesc")) for a in en.findall("cap:area", CAP)) if d]
    if expires <= now or not divisions:
        return None
    words = {lang: {k: get(i, k) for k in ("headline", "instruction")} for lang, i in infos.items()}
    web = get(en, "web")
    return {"id": get(alert, "identifier"), "divisions": divisions, "expires": expires.isoformat(), "en": words["en"],
            "bn": words.get("bn", words["en"]), "web": web if web.startswith(("https://", "http://")) else None}


def parse_forecast(items, now):
    issued = max(date.fromisoformat(i["report_date"]) for i in items)
    # A forecast covers the 24 hours from 9 am Dhaka time on its date. BMD posts it around noon, so each morning has a gap with none in force.
    starts = datetime.combine(issued, time(9), DHAKA)
    if not starts <= now < starts + timedelta(days=1):
        return None
    divisions = {}
    for i in items:
        name, weather = _division(i["division"]), i["weather"]
        if name and weather.get("rain") and not re.search(r"\bDRY\b", weather["rain"]):
            divisions[name] = {"coverage": weather.get("coverage") or "", "heavy": "HEAVY" in (weather.get("intensity") or "")}
    return {"date": issued.isoformat(), "divisions": divisions}


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=(5, 15))
    r.raise_for_status()
    return r


def _warnings(now):
    alerts = []
    for link in recent_links(_get(FEED_URL).text, now):
        try:
            alerts.append(_get(link).text)
        except requests.RequestException as e:
            print(f"FAILED {link}: {e}", file=sys.stderr)
    replaced = {i for xml in alerts for i in replaced_ids(xml)}
    return [w for w in (parse_alert(xml, now) for xml in alerts) if w and w["id"] not in replaced]


def fetch(conn, now=None):
    now = now or datetime.now(timezone.utc)
    # The forecast and the warnings come from two different BMD servers; losing one must not lose the other.
    parts, errors = {}, []
    for name, read in (("forecast", lambda: parse_forecast(_get(FORECAST_URL).json(), now)), ("warnings", lambda: _warnings(now))):
        try:
            parts[name] = read()
        except Exception as e:
            errors.append(e)
            print(f"FAILED BMD {name}: {e}", file=sys.stderr)
    if len(errors) == 2:
        raise errors[0]
    return {"forecast": parts.get("forecast"), "warnings": parts.get("warnings") or []}
