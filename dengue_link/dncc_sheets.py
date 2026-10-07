import csv
import io
import re
import sys
from datetime import date, timedelta

import requests

from dengue_link.fetch import HEADERS, weekly

# DNCC's own dengue dashboard (linked from dncc.gov.bd) reads these public Google Sheets.
SHEET = "https://docs.google.com/spreadsheets/d/{book}/gviz/tq"
CENTRES_BOOK = "1EMva389XPbDyJs80M3FZhgj8hGNCOouWzo4bz0cr0Ww"
RISK_BOOK = "1EdVgB-WUZIFtjMznhnriTPZ5_HfMQkYQPZI84bR2M8A"
WEEKDAYS = [("monday", "সোম", "সেম"), ("tuesday", "মঙ্গল"), ("wednesday", "বুধ"), ("thursday", "বৃহস্পতি"), ("friday", "শুক্র"),
            ("saturday", "শনি"), ("sunday", "রবি")]
KINDS = {"Free dengue testing centre": "free", "Diagnostic Center": "diagnostic",
         "Private Hospital/Clinic": "private", "Government hospital": "government"}


def _sheet(book, tab, query=None):
    params = {"tqx": "out:csv", "sheet": tab, **({"tq": query} if query else {})}
    r = requests.get(SHEET.format(book=book), params=params, headers=HEADERS, timeout=(5, 20))
    r.raise_for_status()
    return r.text


def parse_test_centres(text, ward_centres):
    centres = []
    for row in csv.DictReader(io.StringIO(text)):
        kind = KINDS.get(row["type"])
        if not kind or not row["name"]:
            continue
        ward = int(row["ward"]) if row["ward"].isdigit() else None
        try:
            lat, lon, approx = float(row["lat"]), float(row["lng"]), False
            if not (23.6 < lat < 24.0 and 90.25 < lon < 90.55):
                raise ValueError("pin is outside Dhaka")
        except ValueError:
            if ward not in ward_centres:
                continue
            (lat, lon), approx = ward_centres[ward], True
        centres.append({"name": row["name"], "bn": row["নাম"], "kind": kind, "ward": ward,
                        "lat": round(lat, 5), "lon": round(lon, 5), "approx": approx})
    return centres


def _areas(text):
    # Commas inside brackets ("Shahzadpur (A, B and C)") don't split; the bracketed detail is dropped from the name.
    names = (re.sub(r"^and\s+|\s*\(.*$|\.$", "", part.strip()).strip() for part in re.split(r",(?![^(]*\))", text))
    return list(dict.fromkeys(n for n in names if n))


def parse_ward_risk(text, today):
    rows = list(csv.DictReader(io.StringIO(text)))
    newest = max(date.fromisoformat(r["Date"]) for r in rows)
    # DNCC updates the ratings weekly; after three weeks of silence they no longer describe the present.
    if (today - newest).days > 21:
        return None
    daily = {}
    for r in rows:
        if r["ward"].isdigit():
            daily.setdefault(r["ward"], {})[date.fromisoformat(r["Date"])] = int(float(r["Total_patient"] or 0))

    def total(ward, first, last):
        days = [n for d, n in daily.get(ward, {}).items() if newest - timedelta(days=first) <= d <= newest - timedelta(days=last)]
        return sum(days) if len(days) == 7 else None

    wards = {r["ward"]: {"level": r["composite_risk_category"], "patients": int(float(r["roll_total_patients"] or 0)),
                         "week": total(r["ward"], 6, 0), "prev_week": total(r["ward"], 13, 7),
                         "population": int(float(r["population"])) if r["population"] else None,
                         "reason": {"patients": r["category_patients"], "crowding": r["category_pop_den"]},
                         "areas": _areas(r["area"])}
             for r in rows if r["Date"] == newest.isoformat() and r["ward"].isdigit() and r["composite_risk_category"] in ("Low", "Moderate", "High")}
    return {"date": newest.isoformat(), "wards": wards}


def _days(english, bangla):
    text = f"{english} {bangla}".lower()
    return [i for i, spellings in enumerate(WEEKDAYS) if any(s in text for s in spellings)]


def parse_spray(text):
    wards = {}
    for row in csv.DictReader(io.StringIO(text)):
        days = _days(row["Schedule in the week"], row["সপ্তাহের সময়সূচী"])
        if not days or not row["ward"].isdigit():
            continue
        groups = wards.setdefault(row["ward"], [])
        group = next((g for g in groups if g["days"] == days), None)
        if group is None:
            groups.append(group := {"days": days, "areas": []})
        area = [re.sub(r"[\s,]+$", "", row["Area"]), re.sub(r"[\s,]+$", "", row["এলাকা"])]
        if area not in group["areas"]:
            group["areas"].append(area)
    return wards


def test_centres(cache, today, ward_centres):
    # Only the ward, name, type and pin columns are asked for; each centre's contact person, mobile and email never leave Google.
    return weekly(cache / "dncc_test_centres.json", today,
                  lambda: parse_test_centres(_sheet(CENTRES_BOOK, "list_hosp_diag_ward", "select C, F, G, H, R, S"), ward_centres))


def fetch(cache, today, ward_centres):
    sheets = {
        "centres": lambda: test_centres(cache, today, ward_centres),
        # Only the ward, area and day columns are asked for; the sheet's supervisor names and phone numbers never leave Google.
        "spray": lambda: weekly(cache / "dncc_spray.json", today,
                                lambda: parse_spray(_sheet(CENTRES_BOOK, "mosquito_control_detailed", "select C, E, F, G, H, I, J"))),
        # Two weeks of daily patients per ward, by named columns; each ward's death counts never leave Google.
        "wards": lambda: parse_ward_risk(_sheet(RISK_BOOK, "zone_ward_patient_death_larv_mosq_risk",
                                                "select A, H, J, K, M, T, AH, AN, AP order by A desc limit 1000"), today),
    }
    out, errors = {}, []
    for name, read in sheets.items():
        try:
            out[name] = read()
        except Exception as e:
            out[name] = None
            errors.append(e)
            print(f"FAILED DNCC sheet {name}: {e}", file=sys.stderr)
    if len(errors) == len(sheets):
        raise errors[0]
    return out
