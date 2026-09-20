import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

import pypdf

def _norm(s):
    return re.sub(r"\s", "", unicodedata.normalize("NFC", s))


# DGHS exports these tables with a legacy font, so pypdf yields mangled Bangla
# (e.g. "টাঙ্গাইল" survives but "ময়মনসিংহ" becomes " য় নরসিংহ"). Keys are that exact output.
GARBLED_DISTRICTS = {
    "ঢাকা": "Dhaka", "ফরিদপুি": "Faridpur", "গাজীপুি": "Gazipur", "বগাপালগঞ্জ": "Gopalganj",
    "রকম ািগঞ্জ": "Kishoreganj", "াদািীপুি": "Madaripur", "ারনকগঞ্জ": "Manikganj",
    "মুরিরগঞ্জ": "Munshiganj", "নািায়ণগঞ্জ": "Narayanganj", "নিরসিংদী": "Narsingdi",
    "িাজোড়ী": "Rajbari", "িীয়তপুি": "Shariatpur", "টাঙ্গাইল": "Tangail",
    "য় নরসিংহ": "Mymensingh", "জা ালপুি": "Jamalpur", "ব িপুি": "Sherpur", "বনত্রমকানা": "Netrakona",
    "চট্টগ্রা": "Chittagong", "কক্সোজাি": "Cox's Bazar", "োন্দিোন": "Bandarban",
    "িাঙ্গা াটি": "Rangamati", "খাগড়াছরড়": "Khagrachhari", "বফনী": "Feni", "বনায়াখালী": "Noakhali",
    "কুর ল্লা": "Comilla", "চাঁদপুি": "Chandpur", "লক্ষীপুি": "Lakshmipur",
    "ব্রাহ্মনোরড়য়া": "Brahamanbaria",
    "খুলনা": "Khulna", "োমগিহাট": "Bagerhat", "সাতক্ষীিা": "Satkhira", "যম াি": "Jessore",
    "রিনাইদহ": "Jhenaidah", "াগুিা": "Magura", "নড়াইল": "Narail", "কুরিয়া": "Kushtia",
    "চুয়ািাঙ্গা": "Chuadanga", "ব মহিপুি": "Meherpur",
    "িাজ াহী": "Rajshahi", "চাপাইনোেগঞ্জ": "Nawabganj", "নওগাঁ": "Naogaon", "নামটাি": "Natore",
    "জয়পুিহাট": "Joypurhat", "েগুড়া": "Bogra", "রসিাজগঞ্জ": "Sirajganj", "পােনা": "Pabna",
    "িিংপুি": "Rangpur", "লাল রনিহাট": "Lalmonirhat", "কুরড়গ্রা": "Kurigram", "নীলফা ািী": "Nilphamari",
    "রদনাজপুি": "Dinajpur", "গাইোন্ধা": "Gaibandha", "ঠাকুিগাঁও": "Thakurgaon", "পঞ্চগড়": "Panchagarh",
    "েরি াল": "Barisal", "পটুয়াখালী": "Patuakhali", "বভালা": "Bhola", "রপমিাজপুি": "Pirojpur",
    "েিগুনা": "Barguna", "িালকাঠি": "Jhalokati",
    "রসমলট": "Sylhet", "সুনা গঞ্জ": "Sunamganj", "হরেগঞ্জ": "Habiganj", "ব ৌলভীোজাি": "Maulvibazar",
}
_KEYS = sorted(((_norm(k), v) for k, v in GARBLED_DISTRICTS.items()), key=lambda kv: -len(kv[0]))

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM = r"[০-৯0-9,]+"
_DISTRICT_ROW = re.compile(rf"^(.*?)\s*((?:{_NUM}\s+){{6}}{_NUM})\s*$")
_CITY_ROW = re.compile(rf"^[০-৯]+\s+\S.*?\s((?:{_NUM}\s+){{4}}{_NUM})\s*$", re.M)


@dataclass
class DengueReport:
    date: date
    national_24h: int
    district_24h: dict[str, int]
    in_hospital: dict[str, int]
    deaths_year: dict[str, int]
    national_deaths_year: int
    national_deaths_24h: int


def _int(s):
    return int(s.translate(_BN_DIGITS).replace(",", ""))


def undo_triple(s):
    s = s.strip()
    if len(s) % 3 == 0 and s == s[: len(s) // 3] * 3:
        s = s[: len(s) // 3]
    return _int(s)


def _district(text):
    t = _norm(re.sub(r"^[০-৯0-9]+", "", text.strip()))
    return next((name for key, name in _KEYS if t.startswith(key)), None)


def _district_rows(text):
    prev = ""
    for line in text.split("\n"):
        m = _DISTRICT_ROW.match(line)
        if not m:
            prev = line
            continue
        label = re.sub(r"^[০-৯0-9\s]+", "", m.group(1))
        if label:
            name = _district(label) or _district(prev)
            if name is None:
                raise ValueError(f"unknown district in DGHS row: {line!r}")
            yield name, [_int(n) for n in m.group(2).split()]
        prev = ""


def parse_dengue_pdf(path):
    pages = [p.extract_text() for p in pypdf.PdfReader(path).pages]
    if "Daily Dengue Press Release" not in pages[0]:
        return None
    lines = pages[0].split("\n")
    report_date = datetime.strptime(lines[0].strip(), "%d-%b-%Y").date()
    national = undo_triple(lines[lines.index("Dengue cases of last 24 hours") + 2])
    deaths_24h = undo_triple(lines[lines.index("Dengue death of last 24 hours") + 2])
    summary = pages[1].split("\n")
    deaths_year = undo_triple(summary[summary.index("Total Dengue deaths from 1 January to till date") + 2])

    district_24h = dict.fromkeys(GARBLED_DISTRICTS.values(), 0)
    in_hospital = dict.fromkeys(GARBLED_DISTRICTS.values(), 0)
    deaths = dict.fromkeys(GARBLED_DISTRICTS.values(), 0)
    for text in pages[1:]:
        rows = list(_district_rows(text))
        if rows:
            # govt, private, total 24h, total this year, deaths this year, discharged, in hospital now
            for name, nums in rows:
                district_24h[name] += nums[2]
                deaths[name] += nums[4]
                in_hospital[name] += nums[6]
        else:
            # Dhaka city hospitals: new 24h, total this year, deaths this year, discharged, in hospital now
            for m in _CITY_ROW.finditer(text):
                nums = [_int(n) for n in m.group(1).split()]
                district_24h["Dhaka"] += nums[0]
                deaths["Dhaka"] += nums[2]
                in_hospital["Dhaka"] += nums[4]

    if sum(district_24h.values()) != national:
        raise ValueError(f"district rows ({sum(district_24h.values())}) do not reconcile with national total ({national})")
    if sum(deaths.values()) != deaths_year:
        raise ValueError(f"district deaths ({sum(deaths.values())}) do not reconcile with national total ({deaths_year})")
    return DengueReport(report_date, national, district_24h, in_hospital, deaths, deaths_year, deaths_24h)
