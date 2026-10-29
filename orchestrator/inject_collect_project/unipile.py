import requests
import json
import re
from datetime import datetime, timezone, timedelta

import config
from unipile_account import ensure_unipile_account_id

API_KEY = config.UNIPILE_API_KEY
DSN = (config.UNIPILE_DSN or "").strip().rstrip("/")
ACCOUNT_ID = None  # resolved lazily

# Nombre max de posts à garder
MAX_POSTS = 10
# Fenêtre temporelle en jours
DAYS_BACK = 7

HEADERS = {
    "X-API-KEY": API_KEY,
    "accept": "application/json",
    "content-type": "application/json"
}

# =========================
# INPUT
# =========================
LINKEDIN_URL = "https://www.linkedin.com/in/chorouk-malmoum/"

# =========================
# RAW DATA REQUEST
# =========================
def get_raw_profile(url_linkedin):
    global ACCOUNT_ID
    if not ACCOUNT_ID:
        ACCOUNT_ID = ensure_unipile_account_id()
    print("[1] Calling Unipile Raw Data")
    url = f"{DSN}/api/v1/linkedin"
    payload = {
        "account_id": ACCOUNT_ID,
        "request_url": url_linkedin
    }

    response = requests.post(url, headers=HEADERS, json=payload)
    print("RAW STATUS:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return None

    data = response.json()

    # save complete raw
    with open("raw_response.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("[OK] Raw response saved")
    return data

# =========================
# EXTRACT PROFILE
# =========================
def extract_profile(raw):
    print("[2] Extracting profile")
    text = json.dumps(raw)

    profile = {
        "id": None,
        "name": None,
        "headline": None,
        "profile_url": None
    }

    # LinkedIn member id
    ids = re.findall(r"ACo[A-Za-z0-9_-]+", text)
    if ids:
        profile["id"] = ids[0]

    # url
    urls = re.findall(r"https://www\.linkedin\.com/in/[A-Za-z0-9\-]+", text)
    if urls:
        profile["profile_url"] = urls[0]

    # names
    names = re.findall(r'"name":"([^"]+)"', text)
    if names:
        profile["name"] = names[0]

    print(json.dumps(profile, indent=4, ensure_ascii=False))
    return profile

# =========================
# HELPERS
# =========================
def parse_datetime_safe(value):
    """
    Parse ISO-like datetime strings such as:
    - 2026-06-23T15:24:19.928Z
    - 2026-06-23T15:24:19.928+00:00
    Returns aware UTC datetime, or None if parsing fails.
    """
    if not value:
        return None

    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

# =========================
# POSTS SEARCH
# =========================
def get_posts(member_id, days_back=DAYS_BACK, max_posts=MAX_POSTS):
    global ACCOUNT_ID
    if not ACCOUNT_ID:
        ACCOUNT_ID = ensure_unipile_account_id()
    print("[3] Searching posts")
    url = f"{DSN}/api/v1/linkedin/search?account_id={ACCOUNT_ID}"
    
    payload = {
        "api": "classic",
        "category": "posts",
        "posted_by": {
            "member": [member_id]
        },
        "sort_by": "date"
    }

    response = requests.post(url, headers=HEADERS, json=payload)
    print("POST STATUS:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return []

    data = response.json()
    posts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    for p in data.get("items", []):
        dt = parse_datetime_safe(p.get("parsed_datetime"))

        # si la date n'est pas lisible, on ignore
        if dt is None:
            continue

        # garder uniquement les posts récents
        if dt < cutoff:
            continue

        posts.append({
            "id": p.get("id"),
            "date": p.get("parsed_datetime"),
            "text": p.get("text"),
            "url": p.get("share_url")
        })

    # tri du plus récent au plus ancien
    posts.sort(key=lambda x: x.get("date", ""), reverse=True)

    # garder seulement les X premiers
    posts = posts[:max_posts]

    print("[OK]", len(posts), "posts found in the last", days_back, "days")
    return posts

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("=" * 60)
    print("LINKEDIN URL -> POSTS")
    print("=" * 60)

    raw = get_raw_profile(LINKEDIN_URL)
    if raw is None:
        exit()

    profile = extract_profile(raw)
    
    if not profile["id"]:
        print("Member ID not found")
        exit()

    # Extraction de la liste des posts
    posts = get_posts(profile["id"], days_back=DAYS_BACK, max_posts=MAX_POSTS)

    # Sauvegarde UNIQUEMENT de la liste des posts dans le JSON
    with open("linkedin_result.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=4, ensure_ascii=False)

    print("[DONE] linkedin_result.json created (only posts saved).")