# review_fetcher.py — v2 (coordinate-biased, type-validated)

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "config" / "cookies.env")

import re

SERP_API_KEY = os.getenv("SERP_API_KEY")
CACHE_FILE = Path(__file__).parent / "reviews_cache.json"

HOTEL_TYPES = {
    "hotel", "motel", "hostel", "inn", "resort",
    "bed and breakfast", "lodging", "guest house",
    "serviced apartment", "vacation rental"
}


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _search_google_maps(query: str, lat, lng) -> dict:
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "api_key": SERP_API_KEY,
        "hl": "en",
        "gl": "my",
    }
    # Only add coordinate bias if lat/lng are available
    if lat and lng:
        params["ll"] = f"@{lat},{lng},15z"

    resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _is_residential(place: dict) -> bool:
    raw_type = place.get("type") or ""
    place_type = " ".join(raw_type).lower() if isinstance(raw_type, list) else raw_type.lower()
    subtypes = [s.lower() for s in (place.get("subtypes") or [])]
    all_type_text = place_type + " " + " ".join(subtypes)

    for hotel_kw in HOTEL_TYPES:
        if hotel_kw in all_type_text:
            return False

    residential_keywords = ["condominium", "apartment", "residential", "housing", "flat", "residency", "condo"]
    for kw in residential_keywords:
        if kw in all_type_text:
            return True

    return True  # ambiguous — accept, name check will catch false positives


def _name_matches(listing_title: str, place_name: str) -> bool:
    stop_words = {"the", "a", "at", "in", "by", "and", "or", "@", "tower", "block"}
    title_words = set(listing_title.lower().split()) - stop_words
    place_name_lower = place_name.lower()
    return any(w in place_name_lower for w in title_words)


def _fetch_place_reviews(place_id: str) -> list:
    """Returns list of {"text": snippet} dicts — format analyzer.py expects."""
    try:
        params = {
            "engine": "google_maps_reviews",
            "place_id": place_id,
            "api_key": SERP_API_KEY,
            "hl": "en",
            "sort_by": "qualityScore",
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        reviews = data.get("reviews", [])
        return [{"text": r["snippet"]} for r in reviews[:3] if r.get("snippet")]
    except Exception:
        return []


def fetch_building_reviews(
    listing_id: str,
    title: str,
    address: str,
    lat=None,
    lng=None,
) -> dict:
    """
    Main entry point — called from scraper.py.
    Returns dict with keys: status, rating, review_count, reviews (list), matched_name
    """
    cache = load_cache()

    if listing_id in cache:
        return cache[listing_id]

    if not SERP_API_KEY:
        return {"status": "no_api_key", "rating": None, "review_count": 0, "reviews": []}

    result = {
        "listing_id": listing_id,
        "status": "not_found",
        "rating": None,
        "review_count": 0,
        "reviews": [],
    }

# Extract neighbourhood (2nd to last) and city (last) from address
    parts = [p.strip() for p in address.split(",") if p.strip()]
    area_neighbourhood = parts[-2] if len(parts) >= 2 else (parts[-1] if parts else "")
    area_city          = parts[-1] if parts else ""

    # Normalize title: "Palm Spring @ Damansara" -> "Palm Spring@Damansara"
    title_normalized = re.sub(r"\s*@\s*", "@", title)

    queries = [
        f"{title_normalized} Condominium",           # handles @ buildings (e.g. Palm Spring@Damansara)
        f"{title} Condominium",                       # standard
        f"{title} Condominium {area_neighbourhood}",
        f"{title} {area_neighbourhood} Malaysia",
        f"{title} {area_city}",
    ]

    for query in queries:
        try:
            data = _search_google_maps(query, lat, lng)
            places = data.get("local_results", [])
            if not places and data.get("place_results"):
                places = [data["place_results"]]

            for place in places:
                if not _is_residential(place):
                    continue

                place_name = place.get("title") or ""
                if not _name_matches(title, place_name):
                    continue

                place_id = place.get("place_id")
                reviews = _fetch_place_reviews(place_id) if place_id else []

                result = {
                    "listing_id": listing_id,
                    "status": "found",
                    "rating": place.get("rating"),
                    "review_count": place.get("reviews") or 0,
                    "reviews": reviews,
                    "matched_name": place_name,
                    "query_used": query,
                }

                cache[listing_id] = result
                save_cache(cache)
                time.sleep(0.5)
                return result

            time.sleep(0.5)

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            cache[listing_id] = result
            save_cache(cache)
            return result

    cache[listing_id] = result
    save_cache(cache)
    return result


def score_reviews(review_data: dict) -> tuple:
    """
    Called from analyzer.py. Returns (adjustment, note).
    Adjustment range: -5 to +5 (feeds into building age + reviews category).
    Low review count (<10) dampens the adjustment — less confident signal.
    """
    if not review_data or review_data.get("status") != "found":
        return 0, "No reviews found"

    rating = review_data.get("rating")
    count  = review_data.get("review_count", 0)

    if rating is None:
        return 0, "No rating available"

    # Base adjustment from rating
    if rating >= 4.5:
        adj = 5
    elif rating >= 4.0:
        adj = 2
    elif rating >= 3.5:
        adj = 0
    elif rating >= 3.0:
        adj = -2
    else:
        adj = -5

    # Dampen if very few reviews — low confidence signal
    if count < 10:
        adj = round(adj * 0.5)
        note = f"★{rating} ({count} reviews — low confidence)"
    else:
        note = f"★{rating} ({count} reviews)"

    return adj, note