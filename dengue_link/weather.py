from datetime import date

import requests

from dengue_link import db

URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY = {"precipitation_sum": "rain_mm", "temperature_2m_mean": "temp_c", "relative_humidity_2m_mean": "humidity_pct"}


def store_response(conn, districts, locations):
    if len(locations) != len(districts):
        raise ValueError(f"asked for {len(districts)} districts, got {len(locations)} locations")
    batches = {}
    for district, loc in zip(districts, locations):
        daily = loc["daily"]
        for i, day in enumerate(daily["time"]):
            for field, metric in DAILY.items():
                if daily[field][i] is not None:
                    batches.setdefault((metric, day), {})[district] = daily[field][i]
    for (metric, day), values in batches.items():
        db.put(conn, "open_meteo", metric, date.fromisoformat(day), values)


def fetch(conn, centroids, start, end):
    districts = sorted(centroids)
    r = requests.get(
        URL,
        params={
            "latitude": ",".join(str(centroids[d][1]) for d in districts),
            "longitude": ",".join(str(centroids[d][0]) for d in districts),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(DAILY),
            "timezone": "Asia/Dhaka",
        },
        timeout=120,
    )
    r.raise_for_status()
    store_response(conn, districts, r.json())
