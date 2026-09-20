import re
from concurrent.futures import ThreadPoolExecutor

import requests

from dengue_link.fetch import HEADERS, weekly

URL = "https://hrm.dghs.gov.bd/public/facilities/json"
KINDS = {28: "district", 29: "upazila", 5: "medical_college"}
MAP_NAMES = {"Barishal": "Barisal", "Bogura": "Bogra", "Brahmanbaria": "Brahamanbaria", "Chapainawabganj": "Nawabganj", "Chattogram": "Chittagong",
             "Cumilla": "Comilla", "Jashore": "Jessore", "Jhalokathi": "Jhalokati", "Khagrachari": "Khagrachhari"}


def _phone(item):
    for field in ("official_contact_no", "mobile_1", "land_phone_1"):
        number = re.sub(r"[\s\-]", "", item.get(field) or "")
        if re.fullmatch(r"(\+?880|0)\d{8,10}", number) and set(number) - set("+0"):
            return number
    return None


def parse_page(payload, in_district):
    # The registry also publishes staff names, personal numbers and bank details; only the fields built here are ever read.
    hospitals = []
    for item in payload["data"]["items"]:
        if not item["is_active"]:
            continue
        district = MAP_NAMES.get(item["district_name"], item["district_name"])
        try:
            lat, lon = float(item["latitude"]), float(item["longitude"])
        except (TypeError, ValueError):
            lat = lon = None
        # About 1 in 13 registry pins is wrong (round numbers, another district, the sea). A wrong pin would send someone
        # the wrong way, so those hospitals keep their district but lose the pin.
        if lat is not None and not in_district(district, lat, lon):
            lat = lon = None
        hospitals.append({
            "name": item["name"], "bn": item["name_bn"], "kind": KINDS[item["facility_type_id"]], "district": district,
            "lat": lat and round(lat, 5), "lon": lon and round(lon, 5), "phone": _phone(item),
            "emergency": bool(item["has_emergency"]), "ambulance": bool(item["has_ambulance"]), "beds": item["approved_bed_number"],
        })
    return hospitals, payload["data"]["last_page"]


def download(in_district):
    def page(kind, number):
        r = requests.get(URL, params={"facility_type_id": kind, "page": number}, headers=HEADERS, timeout=(5, 25))
        r.raise_for_status()
        return parse_page(r.json(), in_district)

    with ThreadPoolExecutor(6) as pool:
        first = list(pool.map(lambda kind: page(kind, 1), KINDS))
        rest = [(kind, n) for kind, (_, last) in zip(KINDS, first) for n in range(2, last + 1)]
        pages = first + list(pool.map(lambda args: page(*args), rest))
    return [h for hospitals, _ in pages for h in hospitals]


def fetch(cache, in_district, today):
    return weekly(cache / "hospitals.json", today, lambda: download(in_district))
