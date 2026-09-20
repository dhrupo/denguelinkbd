import json
from datetime import date

import requests
import truststore

# dncc.gov.bd serves an incomplete certificate chain; the OS trust store fetches the missing intermediate, certifi does not.
truststore.inject_into_ssl()

HEADERS = {"User-Agent": "Mozilla/5.0 (dengue-link research scraper)"}


# The ministry file server sometimes hangs a request; a normal PDF arrives in ~1 s, so fail fast and retry.
def get_pdf(url, tries=3):
    for _ in range(tries):
        try:
            body = requests.get(url, headers=HEADERS, timeout=(5, 10)).content
        except requests.RequestException:
            continue
        if body.startswith(b"%PDF") and b"%%EOF" in body[-2048:]:
            return body
    raise ValueError(f"truncated or unreachable PDF after {tries} tries: {url}")


def weekly(path, today, download):
    """Lists that rarely change (hospitals, test centres) are downloaded again only when the saved copy is a week old."""
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if (today - date.fromisoformat(saved["checked"])).days < 7:
            return saved
    items = download()
    if not items:
        raise ValueError(f"nothing came back for {path.name}; keeping the saved list")
    fresh = {"checked": today.isoformat(), "items": items}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return fresh
