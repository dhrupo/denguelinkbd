import html
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dengue_link.bangla import bn_digits
from dengue_link.dghs_dashboard import week_start


def _round(coords, places=3):
    if isinstance(coords, (int, float)):
        return round(coords, places)
    return [_round(c, places) for c in coords]


def _slim(geojson, key_prop, keep):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {k: f["properties"][k] for k in keep},
                "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])},
            }
            for f in geojson["features"]
        ],
    }


LEVELS = ["Very low", "Low", "Medium", "High", "Very high"]
LEVELS_BN = ["খুব কম", "কম", "মাঝারি", "বেশি", "খুব বেশি"]
MONTHS_BN = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]
STATUS = {"fetched now": ("up to date", "হালনাগাদ"), "unavailable right now": ("not available right now", "এই মুহূর্তে পাওয়া যাচ্ছে না")}
SOURCE_NAMES = {
    "DGHS dashboard, weekly cases by division": ("Health directorate (DGHS): weekly patients in each division", "স্বাস্থ্য অধিদপ্তর: প্রতি বিভাগে সাপ্তাহিক রোগী"),
    "DGHS daily press-release PDF, cases by district": ("DGHS daily report: patients in each district", "স্বাস্থ্য অধিদপ্তরের দৈনিক প্রতিবেদন: প্রতি জেলায় রোগী"),
    "DNCC Innovation Lab, daily city-corporation history": ("DNCC Innovation Lab: daily cases in Dhaka since 2022", "ডিএনসিসি ইনোভেশন ল্যাব: ২০২২ থেকে ঢাকার দৈনিক রোগী"),
    "DNCC mosquito-control plans": ("Dhaka North: ward spraying plans", "ঢাকা উত্তর: ওয়ার্ডে ওষুধ ছিটানোর পরিকল্পনা"),
    "JU–DNCC weekly mosquito surveillance": ("Jahangirnagar University: weekly mosquito survey in Dhaka North", "জাহাঙ্গীরনগর বিশ্ববিদ্যালয়: ঢাকা উত্তরে সাপ্তাহিক মশা জরিপ"),
    "Open-Meteo weather": ("Open-Meteo: daily rainfall", "ওপেন-মিটিও: দৈনিক বৃষ্টিপাত"),
    "DGHS hospital list": ("Health directorate (DGHS): list of government hospitals, checked weekly", "স্বাস্থ্য অধিদপ্তর: সরকারি হাসপাতালের তালিকা, সপ্তাহে একবার যাচাই করা হয়"),
    "DNCC dengue dashboard": ("Dhaka North dengue dashboard: ward risk, spray days and test centres", "ঢাকা উত্তরের ডেঙ্গু ড্যাশবোর্ড: ওয়ার্ডের ঝুঁকি, ওষুধ ছিটানোর দিন ও পরীক্ষাকেন্দ্র"),
    "BMD forecast and warnings": ("Meteorological Department (BMD): today's rain forecast and official warnings", "আবহাওয়া অধিদপ্তর: আজকের বৃষ্টির পূর্বাভাস ও সরকারি সতর্কবার্তা"),
    "BMD district rain, coming days": ("Meteorological Department (BMD, via BAMIS): district rain for the coming days", "আবহাওয়া অধিদপ্তর (বামিস): সামনের কয়েক দিনে প্রতি জেলায় বৃষ্টি"),
}


def _t(en, bn):
    return f'<span data-l="en">{en}</span><span data-l="bn" lang="bn">{bn}</span>'


def _levels(values):
    idx = (values.rank(pct=True, method="max") * len(LEVELS)).clip(upper=len(LEVELS) - 0.001).astype(int)
    return idx.map(lambda i: LEVELS[i])


def _about(n):
    n = float(n)
    if n < 10:
        return f"{n:.0f}"
    mag = 10 ** (len(str(int(n))) - 2)
    return f"{round(n / mag) * mag:,.0f}"


def _pct(x):
    return f"{abs(x):.0%}"


def _date_en(d):
    return f"{d.day} {d:%B}"


def _date_bn(d):
    return f"{bn_digits(d.day)} {MONTHS_BN[d.month - 1]}"


def _division_outlook(division_en, division_bn, x):
    if x > 0.05:
        return (f"{division_en} division: cases may rise by about {_pct(x)} next week.",
                f"{division_bn} বিভাগে আগামী সপ্তাহে রোগী প্রায় {bn_digits(_pct(x))} বাড়তে পারে।")
    if x < -0.05:
        return (f"{division_en} division: cases may fall by about {_pct(x)} next week.",
                f"{division_bn} বিভাগে আগামী সপ্তাহে রোগী প্রায় {bn_digits(_pct(x))} কমতে পারে।")
    return (f"{division_en} division: cases should stay about the same next week.",
            f"{division_bn} বিভাগে আগামী সপ্তাহে রোগীর সংখ্যা মোটামুটি একই থাকতে পারে।")


def _trend_chip(x):
    if x > 0.05:
        return "up", _t("Going up", "বাড়ছে")
    if x < -0.05:
        return "down", _t("Going down", "কমছে")
    return "flat", _t("About the same", "প্রায় একই")


ZONES = {1: ("Uttara", "উত্তরা"), 2: ("Mirpur", "মিরপুর"), 3: ("Gulshan", "গুলশান"), 4: ("Mirpur-1", "মিরপুর-১"), 5: ("Mohammadpur", "মোহাম্মদপুর")}
DNCC_LINKS = [
    ("What DNCC says it has done so far", "ডিএনসিসি এ পর্যন্ত যা করেছে",
     "https://dncc.gov.bd/pages/static-pages/গৃহীত-পদক্ষেপসমূহ-oh9wky-69ae3ada7706b1acf8d9a20a"),
    ("Spraying timetable for each zone", "প্রতিটি অঞ্চলে ওষুধ ছিটানোর সময়সূচি", "https://dncc.gov.bd/pages/static-pages/6922e094933eb65569e27aff"),
    ("Spraying plan for each ward", "প্রতিটি ওয়ার্ডের পরিকল্পনা", "https://dncc.gov.bd/pages/mosquito-kill-plans"),
    ("Weekly mosquito survey reports (Jahangirnagar University)", "সাপ্তাহিক মশা জরিপ (জাহাঙ্গীরনগর বিশ্ববিদ্যালয়)",
     "https://dncc.gov.bd/pages/reports?filters=%7B%22reports_type%22%3A%2269a6621af681a7e27286ba8c%22%7D"),
]


def _change(now, before):
    if not before:
        return 1.0 if now else 0.0
    return (now - before) / before


def _spark(totals):
    if len(totals) < 2:
        return ""
    top = max(totals) or 1
    pts = " ".join(f"{i * 300 / (len(totals) - 1):.1f},{58 - n * 52 / top:.1f}" for i, n in enumerate(totals))
    return (f'<svg class="spark" viewBox="0 0 300 60" preserveAspectRatio="none" role="img" aria-label="Aedes mosquitoes caught each week, '
            f'oldest first: {", ".join(map(str, totals))}"><polyline points="{pts}" fill="none" stroke="currentColor" '
            'stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>')


def _ward_rating(ward_risk):
    if not ward_risk or not ward_risk["wards"]:
        return ""
    counts = {level: sum(1 for w in ward_risk["wards"].values() if w["level"] == level) for level in ("High", "Moderate")}
    day = date.fromisoformat(ward_risk["date"])
    wards_en = lambda n: "no wards" if not n else f"{n} ward" + ("" if n == 1 else "s")
    wards_bn = lambda n: "কোনো ওয়ার্ড নেই" if not n else f"{bn_digits(n)}টি ওয়ার্ড"
    return "<h3>" + _t("How Dhaka North rates its own wards", "ঢাকা উত্তর নিজের ওয়ার্ডগুলোকে যেভাবে দেখছে") + "</h3><p>" + _t(
        f"As of {_date_en(day)}, the city corporation rates {wards_en(counts['High'])} as high risk and {wards_en(counts['Moderate'])} as moderate risk, "
        f"out of {len(ward_risk['wards'])}. It looks at patients, deaths, mosquito counts and how crowded the ward is. "
        'Tick "Dhaka North wards" on the map to see each one and its spraying days.',
        f"{_date_bn(day)} পর্যন্ত সিটি কর্পোরেশনের হিসাবে {bn_digits(len(ward_risk['wards']))}টি ওয়ার্ডের মধ্যে বেশি ঝুঁকিতে {wards_bn(counts['High'])}, "
        f"আর মাঝারি ঝুঁকিতে {wards_bn(counts['Moderate'])}। রোগী, মৃত্যু, মশার সংখ্যা আর বসতির ঘনত্ব দেখে এই হিসাব করা হয়। "
        "প্রতিটি ওয়ার্ড আর সেখানে ওষুধ ছিটানোর দিন দেখতে মানচিত্রে “ঢাকা উত্তরের ওয়ার্ড” ঘরে টিক দিন।") + "</p>"


def _control_view(mosquito, ward_spray, ward_risk=None):
    coverage = '<p class="note">' + _t(
        "<strong>Only Dhaka North City Corporation shares this kind of data.</strong> We couldn't find anything similar from "
        "Dhaka South, Chattogram, the other city corporations or the health directorate.",
        "<strong>শুধু ঢাকা উত্তর সিটি কর্পোরেশন এ ধরনের তথ্য প্রকাশ করে।</strong> ঢাকা দক্ষিণ, চট্টগ্রাম, অন্য সিটি কর্পোরেশন বা "
        "স্বাস্থ্য অধিদপ্তরের কাছ থেকে এমন কোনো তথ্য আমরা পাইনি।") + "</p>"
    links = "".join(f'<li><a href="{html.escape(u)}" target="_blank" rel="noopener">{_t(en, bn)}</a></li>' for en, bn, u in DNCC_LINKS)
    spraying = (
        _t(f"Its ward plans schedule spraying in {len(ward_spray)} wards.",
           f"ওয়ার্ড পরিকল্পনা অনুযায়ী {bn_digits(len(ward_spray))}টি ওয়ার্ডে মশার ওষুধ ছিটানোর কথা।")
        if ward_spray else
        _t("We couldn't open the ward spraying plans just now.", "ওয়ার্ডের ওষুধ ছিটানোর পরিকল্পনা এই মুহূর্তে খোলা যায়নি।")
    )
    doing = (_ward_rating(ward_risk) + "<h3>" + _t("What Dhaka North is doing", "ঢাকা উত্তর যা করছে") + f"</h3><p>{spraying}</p>"
             + f'<ul class="doc-links">{links}</ul>')
    if not mosquito or not mosquito["weeks"]:
        return coverage + "<p>" + _t("The weekly mosquito survey couldn't be loaded just now.",
                                      "সাপ্তাহিক মশা জরিপ এই মুহূর্তে পাওয়া যাচ্ছে না।") + "</p>" + doing
    weeks = mosquito["weeks"]
    now = weeks[-1]
    before = weeks[-2] if len(weeks) > 1 else None
    total, prev = sum(now["adults"].values()), sum(before["adults"].values()) if before else 0
    end = date.fromisoformat(now["end"])
    ch = _change(total, prev)
    if not before:
        compare_en, compare_bn = "", ""
    elif not prev:
        compare_en, compare_bn = " The week before, none were caught.", " আগের সপ্তাহে একটিও ধরা পড়েনি।"
    elif ch > 0.05:
        compare_en, compare_bn = f" That's {_pct(ch)} more than the week before ({prev}).", f" আগের সপ্তাহের ({bn_digits(prev)}টি) চেয়ে {bn_digits(_pct(ch))} বেশি।"
    elif ch < -0.05:
        compare_en, compare_bn = f" That's {_pct(ch)} fewer than the week before ({prev}).", f" আগের সপ্তাহের ({bn_digits(prev)}টি) চেয়ে {bn_digits(_pct(ch))} কম।"
    else:
        compare_en, compare_bn = f" About the same as the week before ({prev}).", f" আগের সপ্তাহেও প্রায় একই ছিল ({bn_digits(prev)}টি)।"
    headline = '<p class="lead-big">' + _t(
        f"Traps across Dhaka North caught <strong>{total}</strong> Aedes mosquitoes, the kind that spreads dengue, in the week to {_date_en(end)}." + compare_en,
        f"{_date_bn(end)} পর্যন্ত এক সপ্তাহে ঢাকা উত্তরের ফাঁদে <strong>{bn_digits(total)}</strong>টি এডিস মশা ধরা পড়েছে। এই মশাই ডেঙ্গু ছড়ায়।" + compare_bn,
    ) + "</p>"
    cards = ""
    for z, (en, bn_) in ZONES.items():
        a, b = now["adults"].get(z, 0), (before or {"adults": {}})["adults"].get(z, 0)
        cls, chip = _trend_chip(_change(a, b)) if before else ("flat", "")
        lv = now.get("larvae", {}).get(z)
        larvae = ""
        if lv is not None:
            larvae = '<p class="muted">' + (
                _t(f"{lv} larvae found in the traps.", f"ফাঁদে {bn_digits(lv)}টি লার্ভা পাওয়া গেছে।") if lv
                else _t("No larvae found in the traps.", "ফাঁদে কোনো লার্ভা পাওয়া যায়নি।")) + "</p>"
        cards += (
            f'<li class="card zone-card"><div class="row"><h3>{_t(f"{en} <span class=muted>(zone {z})</span>", f"{bn_} <span class=muted>(অঞ্চল {bn_digits(z)})</span>")}</h3>'
            f'<span class="trend {cls}">{chip}</span></div><p>'
            + _t(f"<strong>{a}</strong> Aedes mosquitoes caught, {b} the week before.",
                 f"<strong>{bn_digits(a)}</strong>টি এডিস মশা ধরা পড়েছে, আগের সপ্তাহে {bn_digits(b)}টি।") + "</p>"
            + larvae + "</li>"
        )
    totals = [sum(w["adults"].values()) for w in weeks]
    first = date.fromisoformat(weeks[0]["end"])
    dates = (f'<div class="spark-dates muted"><span>{_t(_date_en(first), _date_bn(first))}</span>'
             f'<span>{_t(_date_en(end), _date_bn(end))}</span></div>') if len(weeks) > 1 else ""
    trend = ('<figure class="trend-fig">' + _spark(totals) + dates + '<figcaption class="muted">'
             + _t(f"Aedes mosquitoes caught each week (last {len(totals)} weeks).", f"প্রতি সপ্তাহে ধরা পড়া এডিস মশা (গত {bn_digits(len(totals))} সপ্তাহ)।")
             + "</figcaption></figure>")
    return coverage + headline + trend + f'<ul class="cards">{cards}</ul>' + doing


def _novelty_view(novelty):
    if not novelty or not novelty.get("history"):
        return "<p>" + _t("We need a few more weeks of data first.", "এর জন্য আরও কয়েক সপ্তাহের তথ্য দরকার।") + "</p>"
    history = novelty["history"]
    bars = ""
    for wk, score in history:
        d = date.fromisoformat(wk)
        odd = score >= 0.5
        bars += (
            f'<li class="nov{" odd" if odd else ""}"><span class="nov-date">{_t(_date_en(d), _date_bn(d))}</span>'
            f'<span class="nov-bar"><i style="width:{max(score, 0.02) * 100:.0f}%"></i></span>'
            f'<span class="nov-val num">{_t(f"{score:.2f}", bn_digits(f"{score:.2f}"))}</span>'
            + (f'<span class="nov-flag">{_t("unusual", "অস্বাভাবিক")}</span>' if odd else "") + "</li>"
        )
    odd_weeks = [date.fromisoformat(w) for w, s in history if s >= 0.5]
    if odd_weeks:
        summary = _t(
            "The pattern looked unusual in the week of " + ", ".join(_date_en(d) for d in odd_weeks) + ". Those are the weeks worth a closer look.",
            "যেসব সপ্তাহে ধরনটা অন্যরকম ছিল: " + ", ".join(_date_bn(d) for d in odd_weeks) + "। এই সপ্তাহগুলো ভালো করে খতিয়ে দেখা দরকার।")
    else:
        summary = _t("Nothing unusual in these weeks. Cases rose and fell in ways we'd already seen this year.",
                     "এই সপ্তাহগুলোতে অস্বাভাবিক কিছু নেই। রোগী যেভাবে বেড়েছে বা কমেছে, এ বছর আগেও তেমন দেখা গেছে।")
    return (
        "<p>" + _t("Each bar is one week. 0 means the fly brain had seen that pattern before this year; 1 means it was completely new.",
                   "প্রতিটি দাগ এক সপ্তাহের। ০ মানে এ বছর আগেও এমন ধরন দেখা গেছে, ১ মানে একেবারে নতুন।") + "</p>"
        + f'<ol class="novelty">{bars}</ol><p>{summary}</p>'
    )


def _count(x):
    return "–" if x != x else _t(f"{x:,.0f}", bn_digits(f"{x:,.0f}"))


def _rate(x):
    return f"{x:.1f}" if x < 10 else f"{x:,.0f}"


def _load_line(r):
    if r.in_hospital != r.in_hospital:
        return ""
    return '<p class="muted">' + _t(
        f"In hospital right now: {r.in_hospital:,.0f}. Deaths this year: {r.deaths_year:,.0f}.",
        f"এখন হাসপাতালে: {bn_digits(f'{r.in_hospital:,.0f}')} জন। এ বছর মৃত্যু: {bn_digits(f'{r.deaths_year:,.0f}')} জন।") + "</p>"


def _national_line(national):
    if not national:
        return ""
    d = date.fromisoformat(str(national["date"]))
    n, y, t = (f"{national[k]:,.0f}" for k in ("in_hospital", "deaths_year", "deaths_24h"))
    return '<p class="note">' + _t(
        f"<strong>Across Bangladesh on {_date_en(d)}:</strong> {n} people were in hospital with dengue. "
        f"{y} people have died this year, {t} of them in the last day.",
        f"<strong>{_date_bn(d)} পর্যন্ত সারা দেশে:</strong> ডেঙ্গু নিয়ে হাসপাতালে ভর্তি ছিলেন {bn_digits(n)} জন। "
        f"এ বছর মারা গেছেন {bn_digits(y)} জন, তাঁদের {bn_digits(t)} জন গত এক দিনে।") + "</p>"


AGE_BANDS = {"0-15": ("15 and under", "১৫ বছর বা তার কম"), "16-30": ("16 to 30", "১৬ থেকে ৩০ বছর"), "31-45": ("31 to 45", "৩১ থেকে ৪৫ বছর"),
             "46-60": ("46 to 60", "৪৬ থেকে ৬০ বছর"), "61+": ("Over 60", "৬০ বছরের বেশি")}


def _who_view(who):
    if not who:
        return ""
    patients = {b: sum(who["patients"].get(b, {}).values()) for b in AGE_BANDS}
    deaths = {b: sum(who["deaths"].get(b, {}).values()) for b in AGE_BANDS}
    total, died = sum(patients.values()), sum(deaths.values())
    if not total:
        return ""
    share = {b: n / total for b, n in patients.items()}
    top = max(share, key=share.get)
    men = sum(v.get("male", 0) for v in who["patients"].values()) / total
    bars = "".join(
        f'<li class="bar-row"><span>{_t(*AGE_BANDS[b])}</span><span class="nov-bar"><i style="width:{share[b] / share[top] * 100:.0f}%"></i></span>'
        f'<span class="num">{_t(f"{share[b]:.0%}", bn_digits(f"{share[b]:.0%}"))}</span></li>'
        for b in AGE_BANDS
    )
    summary = _t(
        f"The biggest group is people aged {AGE_BANDS[top][0].lower()}: {share[top]:.0%} of all patients. {men:.0%} of patients are men.",
        f"সবচেয়ে বেশি রোগীর বয়স {AGE_BANDS[top][1]}: মোট রোগীর {bn_digits(f'{share[top]:.0%}')}। রোগীদের {bn_digits(f'{men:.0%}')} পুরুষ।")
    lost = ""
    if died:
        worst = max(deaths, key=deaths.get)
        lost = '<p class="muted">' + _t(
            f"Among the people who died, the biggest group was aged {AGE_BANDS[worst][0].lower()} ({deaths[worst] / died:.0%}).",
            f"যাঁরা মারা গেছেন, তাঁদের মধ্যে সবচেয়ে বেশি জনের বয়স {AGE_BANDS[worst][1]} ({bn_digits(f'{deaths[worst] / died:.0%}')})।") + "</p>"
    return ('<section id="who" aria-labelledby="who-title"><h3 id="who-title">' + _t("Who is getting sick this year", "এ বছর কারা বেশি আক্রান্ত")
            + f'</h3><p>{summary}</p><ul class="bars">{bars}</ul>{lost}<p class="muted">'
            + _t("Hospital patients across Bangladesh since 1 January, from the health directorate (DGHS).",
                 "১ জানুয়ারি থেকে সারা দেশে হাসপাতালে ভর্তি রোগী, স্বাস্থ্য অধিদপ্তরের হিসাব।") + "</p></section>")


def _week_month(year, week):
    return (week_start(int(year), week + 1) + timedelta(days=3)).month


def _nice(top):
    mag = 10 ** (len(str(int(top))) - 1)
    return next(m * mag for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * mag >= top)


def _season_view(season):
    if not season or len(season) < 2:
        return ""
    *past, now = sorted(season)
    seen = [i for i, v in enumerate(season[now]) if v is not None]
    if not seen:
        return ""
    last = seen[-1]
    peak = {y: max((i for i, v in enumerate(season[y]) if v is not None), key=season[y].__getitem__) for y in past if any(v is not None for v in season[y])}
    months = {_week_month(y, k) for y, k in peak.items()}
    first, end = min(months), max(months)
    peak_en = f"in {date(2000, first, 1):%B}" if first == end else f"between {date(2000, first, 1):%B} and {date(2000, end, 1):%B}"
    peak_bn = f"{MONTHS_BN[first - 1]} মাসে" if first == end else f"{MONTHS_BN[first - 1]} থেকে {MONTHS_BN[end - 1]} মাসের মধ্যে"
    compared = [y for y in past if season[y][last] is not None]
    n, higher = len(compared), sum(season[now][last] > season[y][last] for y in compared)
    more_en, more_bn = ("more", "বেশি") if higher else ("fewer", "কম")
    if n == 1:
        cmp_en, cmp_bn = f"{more_en} people were admitted than in the same week of {compared[0]}", f"{compared[0]} সালের একই সপ্তাহের চেয়ে {more_bn}"
    elif higher in (0, n):
        cmp_en, cmp_bn = f"{more_en} people were admitted than in the same week of any of the last {n} years", f"গত {n} বছরের যেকোনো বছরের একই সপ্তাহের চেয়ে {more_bn}"
    else:
        cmp_en, cmp_bn = f"more people were admitted than in the same week of {higher} of the last {n} years", f"গত {n} বছরের মধ্যে {higher} বছরের একই সপ্তাহের চেয়ে বেশি"
    caption = _t(f"In the last {len(peak)} years, dengue peaked {peak_en}." + (f" This week, {cmp_en}." if n else ""),
                 bn_digits(f"গত {len(peak)} বছরে ডেঙ্গু সবচেয়ে বেশি ছড়িয়েছে {peak_bn}।" + (f" এ সপ্তাহে ভর্তি রোগী {cmp_bn}।" if n else "")))

    w, h, left, right, top_pad, bottom = 400, 220, 58, 36, 14, 26
    top = _nice(max(v for y in season for v in season[y] if v is not None) or 1)
    x = lambda k: left + k * (w - left - right) / 51
    y = lambda v: top_pad + (h - top_pad - bottom) * (1 - v / top)
    grid = "".join(
        f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
        f'<text x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{_svg_t(f"{v:,.0f}", bn_digits(f"{v:,.0f}"))}</text>'
        for v in (0, top / 2, top))
    ticks = "".join(
        f'<text x="{x((date(2001, m, 1) - week_start(2001, 1)).days / 7):.1f}" y="{h - 6}" text-anchor="middle">'
        f'{_svg_t(date(2000, m, 1).strftime("%b"), MONTHS_BN[m - 1])}</text>' for m in (1, 4, 7, 10))
    placed = []

    def label(cls, cx, cy, yr):
        # Labels are about 36 by 16 units; a label that would sit on another one moves up until it is clear.
        while any(abs(cx - px) < 36 and abs(cy - py) < 16 for px, py in placed):
            cy -= 16
        placed.append((cx, cy))
        return f'<text{cls} x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle">{_svg_t(yr, bn_digits(yr))}</text>'

    lines = (f'<polyline class="now" points="{" ".join(f"{x(i):.1f},{y(season[now][i]):.1f}" for i in seen)}"/>'
             f'<circle class="now-dot" cx="{x(last):.1f}" cy="{y(season[now][last]):.1f}" r="4"/>')
    labels = label(' class="yr-now"', x(last), y(season[now][last]) - 10, now)
    for yr in sorted(peak, key=lambda yr: -season[yr][peak[yr]]):
        k = peak[yr]
        lines = f'<polyline class="past" points="{" ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(season[yr]) if v is not None)}"/>' + lines
        labels += label("", x(k), y(season[yr][k]) - 8, yr)
    lines += labels

    by_month = {yr: {m: 0.0 for m in range(1, 13)} for yr in season}
    for yr, weeks in season.items():
        for k, v in enumerate(weeks):
            if v is not None:
                by_month[yr][_week_month(yr, k)] += v
    cell = lambda yr, m: ("–" if yr == now and _week_month(now, last) < m else _t(f"{by_month[yr][m]:,.0f}", bn_digits(f"{by_month[yr][m]:,.0f}")))
    rows = "".join(f'<tr><th scope="row">{_t(date(2000, m, 1).strftime("%B"), MONTHS_BN[m - 1])}</th>'
                   + "".join(f'<td class="num">{cell(yr, m)}</td>' for yr in sorted(season)) + "</tr>" for m in range(1, 13))
    head = "".join(f'<th scope="col">{_t(yr, bn_digits(yr))}</th>' for yr in sorted(season))
    return (
        '<section id="season" class="season" aria-labelledby="season-title"><h3 id="season-title">'
        + _t("This year compared with past years", "আগের বছরগুলোর তুলনায় এ বছর") + f"</h3><p>{caption}</p>"
        + f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="season-title"><g aria-hidden="true">{grid}{ticks}{lines}</g></svg>'
        + '<p class="legend-line muted small"><i class="sw now"></i>' + _t(f"This year ({now})", f"এ বছর ({bn_digits(now)})")
        + '<i class="sw past"></i>' + _t("Past years", "আগের বছরগুলো") + "</p>"
        + '<p class="muted small">' + _t("People admitted to hospital with dengue each week across Bangladesh, from the health directorate (DGHS).",
                                          "প্রতি সপ্তাহে সারা দেশে ডেঙ্গু নিয়ে হাসপাতালে ভর্তি রোগী, স্বাস্থ্য অধিদপ্তরের হিসাব।") + "</p>"
        + "<details><summary>" + _t("Show as a table", "টেবিলে দেখুন") + '</summary><div class="table-wrap" tabindex="0" role="region" aria-labelledby="season-caption">'
        + '<table><caption id="season-caption">' + _t("Patients admitted each month", "প্রতি মাসে ভর্তি রোগী")
        + f'</caption><thead><tr><th scope="col">{_t("Month", "মাস")}</th>{head}</tr></thead><tbody>{rows}</tbody></table></div></details></section>'
    )


def _svg_t(en, bn):
    return f'<tspan data-l="en">{en}</tspan><tspan data-l="bn">{bn}</tspan>'


def _full_date(d):
    return _t(f"{d.day} {d:%B %Y}", bn_digits(f"{d.day} {MONTHS_BN[d.month - 1]} {d.year}"))


def _finder_view(hospitals, test_centres):
    if not hospitals or not hospitals["items"]:
        return ""
    centres = ""
    if test_centres and test_centres["items"]:
        centres = ('<div id="centres-block" hidden><h3>' + _t("Dengue test centres near you (Dhaka North)", "আপনার কাছের ডেঙ্গু পরীক্ষাকেন্দ্র (ঢাকা উত্তর)")
                   + '</h3><ul class="cards" id="centre-list"></ul><p class="muted small">'
                   + _t("From Dhaka North City Corporation's list, checked on ", "ঢাকা উত্তর সিটি কর্পোরেশনের তালিকা থেকে নেওয়া, সর্বশেষ যাচাই ")
                   + _full_date(date.fromisoformat(test_centres["checked"]))
                   + _t(". It gives the free centres only by ward, so their exact spot is not shown. Ask locally for the address.",
                        "। বিনা মূল্যের কেন্দ্রগুলোর শুধু ওয়ার্ড নম্বর দেওয়া আছে, তাই ঠিক কোথায় তা দেখানো যাচ্ছে না। ঠিকানা এলাকায় জিজ্ঞেস করে জেনে নিন।")
                   + "</p></div>")
    return ('<section id="hospital-finder" aria-labelledby="finder-title"><h3 id="finder-title" tabindex="-1">'
            + _t("Nearest government hospital", "কাছের সরকারি হাসপাতাল")
            + '</h3><p id="finder-from" class="muted" role="status"></p><div class="actions"><button type="button" class="btn" id="finder-locate"></button></div>'
            '<ul class="cards" id="finder-list"></ul><div id="also-block" hidden><p id="also-note" class="muted"></p><ul class="cards" id="also-list"></ul></div>' + centres + '<p class="muted small">'
            + _t("Hospital list checked on ", "হাসপাতালের তালিকা সর্বশেষ যাচাই করা হয়েছে ") + _full_date(date.fromisoformat(hospitals["checked"]))
            + _t('. From the <a href="https://hrm.dghs.gov.bd/public/facility-registry" target="_blank" rel="noopener">DGHS health facility registry</a>. '
                 "Bed numbers are each hospital's approved size, not free beds. Nobody publishes free beds. "
                 "Where the registry's map pin is missing or plainly wrong, the hospital is listed under its district without a distance.",
                 ' তারিখে। তালিকাটি <a href="https://hrm.dghs.gov.bd/public/facility-registry" target="_blank" rel="noopener">স্বাস্থ্য অধিদপ্তরের স্বাস্থ্যকেন্দ্রের তালিকা</a> থেকে নেওয়া। '
                 "শয্যাসংখ্যা হলো হাসপাতালের অনুমোদিত শয্যা, খালি শয্যা নয়। খালি শয্যার হিসাব কেউ প্রকাশ করে না। "
                 "তালিকায় যেসব হাসপাতালের অবস্থান নেই বা স্পষ্টতই ভুল, সেগুলো দূরত্ব ছাড়া শুধু জেলার নামে দেখানো হয়েছে।")
            + "</p></section>")


def _history(districts, past_weeks):
    if past_weeks is None or past_weeks.empty:
        return None
    # Past weeks are coloured on next week's scale, so the map can be compared from one week to the next.
    top = districts.groupby(districts["level"].map(LEVELS.index))["rate"].max()
    cuts = [top[top.index <= i].max() if (top.index <= i).any() else float("-inf") for i in range(len(LEVELS) - 1)]
    levels, counts = {}, {}
    for d, row in districts.iterrows():
        if row.division in past_weeks.columns and row.population == row.population:
            rates = past_weeks[row.division] * row.share / row.population * 100_000
            levels[d] = [int(sum(r > c for c in cuts)) for r in rates]
            counts[d] = [round(float(n), 1) if n == n else None for n in past_weeks[row.division] * row.share]
    return {"weeks": [w.date().isoformat() for w in past_weeks.index], "levels": levels, "counts": counts}


def _badge(level):
    i = LEVELS.index(level)
    return f'<span class="badge lv{i}">{_t(level + " risk", "ঝুঁকি " + LEVELS_BN[i])}</span>'


def render(out_path, *, upazilas, upazila_district, districts, divisions, novelty, backtest, wards, ward_spray, as_of,
           sources, country, district_shapes, bn, mosquito, national=None, who=None, city=None, hospitals=None, test_centres=None,
           weather=None, warnings=(), ward_risk=None, spray=None, past_weeks=None, season=None, rain_week=None, ahead=None):
    districts = districts.assign(rate=districts["next7"] / districts["population"] * 100_000)
    districts = districts.assign(level=_levels(districts["rate"]))
    upazila_index = [
        {"id": f["properties"]["shapeID"], "name": f["properties"]["shapeName"],
         "district": upazila_district.get(f["properties"]["shapeID"]), "bn": bn["upazila"].get(f["properties"]["shapeID"], "")}
        for f in upazilas["features"]
    ]
    data = {
        "upazilaIndex": upazila_index,
        "districtShapes": _slim(district_shapes, None, ["shapeName"]),
        "districts": {
            d: {k: (v if k in ("division", "level") else (float(v) if v == v else None)) for k, v in row.items()}
            for d, row in districts.iterrows()
        },
        "divisions": {d: row.astype(float).to_dict() for d, row in divisions.iterrows()},
        "levels": LEVELS,
        "levelsBn": LEVELS_BN,
        "bn": bn,
        "country": {"type": country["features"][0]["geometry"]["type"], "coordinates": _round(country["features"][0]["geometry"]["coordinates"])},
        "wards": wards and _slim(wards, None, list(wards["features"][0]["properties"])),
        "wardSpray": {str(k): v for k, v in ward_spray.items()},
        "mosquito": mosquito,
        "zones": {str(z): list(names) for z, names in ZONES.items()},
        "city": city,
        "hospitals": hospitals["items"] if hospitals and hospitals["items"] else None,
        "testCentres": test_centres["items"] if test_centres and test_centres["items"] else None,
        "weather": weather,
        "warnings": list(warnings),
        "rainWeek": rain_week,
        "ahead": ahead,
        "wardRisk": ward_risk,
        "spray": spray["items"] if spray else None,
        "sprayChecked": spray["checked"] if spray else None,
        "history": _history(districts, past_weeks),
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    dname = lambda d: _t(html.escape(d), bn["district"].get(d, html.escape(d)))
    vname = lambda d: _t(html.escape(d), bn["division"].get(d, html.escape(d)))
    vbn = lambda d: bn["division"].get(d, d)

    ranked = districts.sort_values("rate", ascending=False)
    rising = "".join(
        f'<li class="card district-card"><div class="row"><h3>{dname(d)}</h3>{_badge(r.level)}</div>'
        "<p>" + _t(f"Around <strong>{_about(r.next7)}</strong> people may be admitted to hospital with dengue next week.",
                   f"আগামী সপ্তাহে প্রায় <strong>{bn_digits(_about(r.next7))}</strong> জন ডেঙ্গু নিয়ে হাসপাতালে ভর্তি হতে পারেন।") + "</p>"
        "<p>" + _t(f"That's about {_rate(r.rate)} for every 100,000 people.", f"অর্থাৎ প্রতি ১ লাখ মানুষে প্রায় {bn_digits(_rate(r.rate))} জন।") + "</p>"
        '<p class="muted">' + _t(*_division_outlook(html.escape(r.division), vbn(r.division), r.change)) + "</p>"
        + _load_line(r) +
        f'<a class="link" href="#map" data-place="district:{html.escape(d)}">{_t("See on map", "মানচিত্রে দেখুন")}</a></li>'
        for d, r in ranked.iterrows()
    )
    rows = "".join(
        f'<tr data-district="{html.escape(d)}"><th scope="row">{dname(d)}</th><td>{vname(r.division)}</td>'
        f"<td>{_t(r.level, LEVELS_BN[LEVELS.index(r.level)])}</td>"
        f'<td class="num">{_t(f"{r.next7:,.0f}", bn_digits(f"{r.next7:,.0f}"))}</td>'
        f'<td class="num">{_t(f"{r.recent_cases:,.0f}", bn_digits(f"{r.recent_cases:,.0f}"))}</td>'
        f'<td class="num">{_t(f"{r.share:.0%}", bn_digits(f"{r.share:.0%}"))}</td>'
        f'<td class="num">{_t(_rate(r.rate), bn_digits(_rate(r.rate)))}</td>'
        f'<td class="num">{_count(r.in_hospital)}</td>'
        f'<td class="num">{_count(r.deaths_year)}</td></tr>'
        for d, r in ranked.iterrows()
    )
    div_cards = ""
    for d, r in divisions.sort_values("next7", ascending=False).iterrows():
        cls, chip = _trend_chip(r.change)
        div_cards += (
            f'<li class="card"><div class="row"><h3>{vname(d)}</h3><span class="trend {cls}">{chip}</span></div><p>'
            + _t(f"Around <strong>{_about(r.next7)}</strong> patients expected next week, against {_about(r.recent)} last week.",
                 f"আগামী সপ্তাহে প্রায় <strong>{bn_digits(_about(r.next7))}</strong> জন রোগী হতে পারে, গত সপ্তাহে ছিল {bn_digits(_about(r.recent))} জন।")
            + "</p></li>"
        )
    unusual = bool(novelty and novelty["score"] >= 0.5)
    better = backtest["model_mae"] < backtest["baseline_mae"]
    m, b = f"{backtest['model_mae']:,.0f}", f"{backtest['baseline_mae']:,.0f}"
    weeks_checked = str(max(backtest["n"] // max(len(divisions), 1), 1))
    accuracy_html = "<p>" + _t(
        f"We checked the forecast against {weeks_checked} past weeks in every division. It was off by about "
        f'<strong class="num">{m}</strong> patients per division each week. Simply guessing “next week will be like this week” was off by '
        f'<strong class="num">{b}</strong>. '
        + ("So the forecast does better than that simple guess." if better else
           "<strong>So for now the forecast is no better than that simple guess. Treat it as a rough pointer, not a firm prediction.</strong>"),
        f"আগের {bn_digits(weeks_checked)} সপ্তাহে প্রতিটি বিভাগের হিসাবের সঙ্গে পূর্বাভাসটি মিলিয়ে দেখা হয়েছে। প্রতি সপ্তাহে প্রতিটি বিভাগে গড়ে প্রায় "
        f'<strong class="num">{bn_digits(m)}</strong> জনের হিসাব মেলেনি। অথচ শুধু “আগামী সপ্তাহও এ সপ্তাহের মতোই হবে” ধরে নিলে গরমিল হতো '
        f'<strong class="num">{bn_digits(b)}</strong> জনের। '
        + ("অর্থাৎ পূর্বাভাসটি সেই সহজ অনুমানের চেয়ে ভালো।" if better else
           "<strong>তাই এখনো এই পূর্বাভাস সেই সহজ অনুমানের চেয়ে ভালো নয়। একে মোটামুটি ইঙ্গিত হিসেবে দেখুন, নিশ্চিত পূর্বাভাস হিসেবে নয়।</strong>"),
    ) + "</p>"
    if backtest.get("band_checked"):
        held, checked = f"{backtest['band_held'] * 100:.0f}", str(backtest["band_checked"])
        accuracy_html += "<p>" + _t(
            f"Each district also gets a likely range, worked out from how far off past forecasts were. In the {checked} past division "
            f"forecasts we checked, the real number of patients fell inside that range about {held} out of every 100 times. "
            "District numbers are less certain than that, because each division's total is shared between its districts.",
            f"প্রতিটি জেলার জন্য একটি সম্ভাব্য সীমাও দেখানো হয়, আগের পূর্বাভাসগুলো কতটা মেলেনি তা দেখে। আগের {bn_digits(checked)}টি "
            f"বিভাগীয় পূর্বাভাস মিলিয়ে দেখা গেছে, প্রতি ১০০টির মধ্যে {bn_digits(held)}টিতে আসল রোগীর সংখ্যা সেই সীমার মধ্যেই ছিল। "
            "জেলার হিসাব এর চেয়ে কম নিশ্চিত, কারণ প্রতিটি বিভাগের মোট সংখ্যা তার জেলাগুলোর মধ্যে ভাগ করা হয়।",
        ) + "</p>"
    source_items = ""
    for nm, st, _detail in sources:
        name_en, name_bn = SOURCE_NAMES.get(nm, (nm, nm))
        st_en, st_bn = STATUS.get(st, (st, st))
        source_items += f"<li><strong>{_t(html.escape(name_en), name_bn)}</strong>: {_t(st_en, st_bn)}</li>"
    banner = (
        '<p class="banner" role="status"><a href="#about">'
        + _t("Cases are spreading in an unusual way this week. See why", "এ সপ্তাহে রোগী ছড়ানোর ধরন অন্যরকম। কারণ দেখুন")
        + "</a></p>"
        if unusual else ""
    )

    Path(out_path).write_text(
        TEMPLATE.replace("{{as_of}}", _t(as_of.strftime("%-d %B %Y"), bn_digits(f"{as_of.day} {MONTHS_BN[as_of.month - 1]} {as_of.year}")))
        .replace("{{rising}}", rising)
        .replace("{{national}}", _national_line(national))
        .replace("{{season}}", _season_view(season))
        .replace("{{rows}}", rows)
        .replace("{{div_cards}}", div_cards)
        .replace("{{who}}", _who_view(who))
        .replace("{{hospitals}}", _finder_view(hospitals, test_centres))
        .replace("{{novelty}}", _novelty_view(novelty))
        .replace("{{novelty_banner}}", banner)
        .replace("{{accuracy}}", accuracy_html)
        .replace("{{sources}}", source_items)
        .replace("{{control}}", _control_view(mosquito, ward_spray, ward_risk))
        .replace("{{payload}}", payload),
        encoding="utf-8",
    )


TEMPLATE = (Path(__file__).parent / "map_template.html").read_text(encoding="utf-8")


REASONS = {
    "dghs_down": ("We couldn't get this week's figures from the health directorate (DGHS). Rather than show old numbers, we're showing nothing. Please try again in a little while.",
                  "স্বাস্থ্য অধিদপ্তর থেকে এ সপ্তাহের হিসাব আনা যায়নি। পুরোনো হিসাব দেখানোর বদলে আমরা কিছুই দেখাচ্ছি না। একটু পরে আবার চেষ্টা করুন।"),
    "too_early": ("It's too early in the year to forecast. We need about seven weeks of this year's figures first.",
                  "বছরের শুরুতে পূর্বাভাস দেওয়ার মতো যথেষ্ট তথ্য থাকে না। এ বছরের অন্তত সাত সপ্তাহের হিসাব দরকার।"),
}


def render_unavailable(out_path, *, as_of, sources, reason="dghs_down"):
    items = ""
    for nm, st, _detail in sources:
        name_en, name_bn = SOURCE_NAMES.get(nm, (nm, nm))
        st_en, st_bn = STATUS.get(st, (st, st))
        items += f"<li><strong>{html.escape(name_en)}</strong>: {st_en}<br><span lang=\"bn\">{name_bn}: {st_bn}</span></li>"
    en, bn = REASONS[reason]
    Path(out_path).write_text(UNAVAILABLE.format(sources=items, why_en=en, why_bn=bn), encoding="utf-8")


UNAVAILABLE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dengue Link | No forecast right now</title>
<style>
:root {{ --bg:#F8FAFC; --fg:#0F172A; --muted:#475569; --accent:#B45309; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0B1220; --fg:#E2E8F0; --muted:#A3B1C6; --accent:#FBBF24; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui,"Noto Sans Bengali",sans-serif; max-width:720px; }}
.notice {{ border-left:4px solid var(--accent); padding:12px 14px; }}
</style></head>
<body><main>
<h1>No forecast right now <span lang="bn">· এই মুহূর্তে পূর্বাভাস নেই</span></h1>
<p class="notice" role="alert">{why_en}<br>
<span lang="bn">{why_bn}</span></p>
<h2>Need help now? <span lang="bn">· এখনই সাহায্য দরকার?</span></h2>
<p><a href="tel:16263">16263</a>: talk to a doctor, 24 hours. <a href="tel:999">999</a>: emergency ambulance.<br>
<span lang="bn"><a href="tel:16263">১৬২৬৩</a>: ডাক্তারের সঙ্গে কথা বলুন, ২৪ ঘণ্টা। <a href="tel:999">৯৯৯</a>: জরুরি অ্যাম্বুলেন্স।</span></p>
<h2>Sources <span lang="bn">· উৎস</span></h2><ul>{sources}</ul>
</main></body></html>
"""
