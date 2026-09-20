import difflib
import json
import re

SOURCE = "https://raw.githubusercontent.com/nuhil/bangladesh-geocode/master/{0}/{0}.json"
_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn_digits(text):
    return str(text).translate(_BN_DIGITS)


def _rows(path):
    return next(x for x in json.load(open(path, encoding="utf-8")) if isinstance(x, dict) and x.get("type") == "table")["data"]


def _key(name):
    return re.sub(r"[^a-z]", "", name.lower().replace("sadar", "").replace("upazila", ""))


def _best(name, rows, cutoff):
    keys = {_key(r["name"]): r for r in rows}
    hit = difflib.get_close_matches(_key(name), list(keys), 1, cutoff)
    return keys[hit[0]] if hit else None


def bangla_names(areas, divisions_path, districts_path, upazilas_path):
    divisions, districts, upazilas = _rows(divisions_path), _rows(districts_path), _rows(upazilas_path)
    district_rows = {d: _best(d, districts, 0.6) for d in areas.districts}
    upazila = {}
    for uid, name in areas.upazila_name.items():
        own = [u for u in upazilas if u["district_id"] == district_rows[areas.upazila_district[uid]]["id"]]
        row = _best(name, own, 0.75)
        if row:
            upazila[uid] = row["bn_name"]
    return {
        "division": {d: _best(d, divisions, 0.6)["bn_name"] for d in areas.division_centroid},
        "district": {d: row["bn_name"] for d, row in district_rows.items()},
        "upazila": upazila,
    }
