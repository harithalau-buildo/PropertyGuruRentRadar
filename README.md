# PropertyGuruRentRadar

A Python tool that scrapes your PropertyGuru shortlist, enriches each listing with real data, and scores them against your personal criteria — so you spend viewings on the right units, not all of them.

Built for the KL rental market. Outputs a ranked JSON with drive times, Google Maps reviews, value-per-sqft analysis, and a breakdown of every score.

---

## What It Does

1. **Scrapes** your PropertyGuru shortlist (all pages, handles pagination)
2. **Enriches** each listing with:
	 - Actual furnished status from the listing page (not the card — cards lie)
	 - Coordinates (lat/lng) extracted from the listing page
	 - MRT/LRT/KTM proximity
	 - Amenities detected from listing description
3. **Fetches drive times** to up to 6 personal locations (workplace, partner's workplace, family homes) via OpenRouteService
4. **Fetches Google Maps reviews** via SerpAPI — handles Malaysian condo naming quirks (`Building@Area` format, `place_results` vs `local_results` response types)
5. **Scores** each listing 0–100 across 5 categories
6. **Outputs** a ranked JSON with full breakdown per listing

---

## Scoring System

| Category | Points | Logic |
|---|---|---|
| Budget | 10 | Within range = 10, scales down proportionally over budget |
| Value / sqft | 30 | Adjusted price per sqft (unfurnished +RM600, partial +RM300 equiv) |
| Bedrooms | 20 | 2+ beds = 20, studio = 15, 1 bed = 0 |
| Location | 30 | Weighted ORS drive times vs max-minute thresholds per destination |
| Building age + reviews | 10 | Age-based base ± review adjustment (max ±5 based on Google Maps rating) |

---

## Stack

| Tool | Purpose | Cost |
|---|---|---|
| Python + BeautifulSoup | Scraping PropertyGuru shortlist | Free |
| OpenRouteService API | Drive time calculations | Free (no credit card) |
| SerpAPI | Google Maps reviews | Free (100 searches/month) |
| PropertyGuru cookies | Auth for shortlist access | Your own session |

No paid APIs. No cloud. Runs locally.

---

## File Architecture

```
PropertyGuruRentRadar/
├── server.py              # MCP server (tools: get_shortlist, get_criteria, analyze_shortlist)
├── scraper.py             # Scrapes PG shortlist + enriches each listing
├── analyzer.py            # Scoring engine
├── distance.py            # ORS drive time calculator + cache
├── review_fetcher.py      # SerpAPI Google Maps review fetcher + cache
├── config/
│   ├── criteria.json      # ⚠️ gitignored — create locally (see Setup)
│   └── cookies.env        # ⚠️ gitignored — create locally (see Setup)
├── drive_times_cache.json # ⚠️ gitignored — auto-generated, persist between runs
├── reviews_cache.json     # ⚠️ gitignored — auto-generated, persist between runs
├── results.json           # ⚠️ gitignored — analyzer output
└── enriched.json          # ⚠️ gitignored — intermediate scraper output
```

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/yourusername/PropertyGuruRentRadar.git
cd PropertyGuruRentRadar
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Get free API keys

**OpenRouteService** (drive times — no credit card required):
- Sign up at [openrouteservice.org](https://openrouteservice.org)
- Copy your API key

**SerpAPI** (Google Maps reviews — 100 free searches/month, no credit card required):
- Sign up at [serpapi.com](https://serpapi.com)
- Copy your API key

### 3. Create config/cookies.env

```bash
mkdir -p config
touch config/cookies.env
```

Paste this template and fill in your values:

```env
PG_ACCESS_TOKEN=       # __pg_ak — expires ~10 min, refresh before each run
PG_REFRESH_TOKEN=      # __pg_rk — 30 days
PHP_SESSION=           # PHPSESSID2
CF_CLEARANCE=          # cf_clearance
CF_BM=                 # __cf_bm
USER_AGENT=            # Your browser's user agent string
ORS_API_KEY=           # Your OpenRouteService key
SERP_API_KEY=          # Your SerpAPI key
```

Get your PropertyGuru session cookies:
1. Open Safari or Chrome → go to your PG shortlist page
2. Open DevTools → Application/Storage tab → Cookies → `www.propertyguru.com.my`
3. Copy the 5 cookie values above

### 4. Create config/criteria.json

```bash
touch config/criteria.json
```

Paste this template and fill in your locations and budget:

```json
{
	"budget_min_rm": 1200,
	"budget_max_rm": 1600,
	"bedroom_rule": "studio_or_2plus",
	"furnished": "any",
	"locations": {
		"partner_work": {
			"name": "The Curve, Mutiara Damansara",
			"lat": <REDACTED_LAT>,
			"lng": <REDACTED_LNG>,
			"weight": 5,
			"max_minutes": 15
		},
		"my_work": {
			"name": "My Office",
			"lat": <REDACTED_LAT>,
			"lng": <REDACTED_LNG>,
			"weight": 2,
			"max_minutes": 30
		}
	},
	"deal_breakers": ["ground floor"]
}
```

Location `weight` = how much that destination matters in the location score (higher = more impact). `max_minutes` = your acceptable drive time threshold.

---

## Running

```bash
cd PropertyGuruRentRadar
source venv/bin/activate
python analyzer.py > results.json 2>&1
```

First run: ~4–5 minutes (scraping + drive times + reviews).  
Subsequent runs: ~1 minute (everything cached except new listings).

---

## Cache Management

Drive times and reviews are cached locally so you don't burn API calls on repeat runs.

**Clear a specific listing's reviews** (to re-fetch one building):
```bash
python3 -c "
import json
cache = json.load(open('reviews_cache.json'))
cache.pop('LISTING_ID_HERE', None)
json.dump(cache, open('reviews_cache.json', 'w'), indent=2)
"
```

**Clear all reviews** (fresh run — costs ~2 SerpAPI calls per unique building):
```bash
rm reviews_cache.json
```

**Clear drive times** (only needed if coordinates change):
```bash
rm drive_times_cache.json
```

---

## Output

`results.json` — ranked array of listings with full breakdown per listing. Example entry:

```json
{
	"id": "500630163",
	"title": "Kiara Kasih",
	"score": 89,
	"google_reviews": {
		"status": "found",
		"rating": 3.9,
		"review_count": 117,
		"matched_name": "Kiara Kasih Condominium"
	},
	"breakdown": {
		"budget": { "points": 10, "max": 10, "note": "RM1,600 within range" },
		"value_per_sqft": { "points": 30, "max": 30 },
		"location": {
			"points": 19,
			"drive_times": {
				"partner_work": 16.1,
				"my_work": 22.5
			}
		},
		"building_age": { "points": 10, "max": 10, "note": "New build (2023) | ★3.9 (117 reviews)" }
	}
}
```

---

## Known Limitations

- PG access token expires ~10 min — refresh cookies before each run
- SerpAPI free tier: 100 searches/month. With caching, covers ~50 unique buildings per month
- Some buildings not indexed on Google Maps — returns `not_found`, no score impact
- Amenities detection is heuristic (description text scan) — verify manually

---

## Roadmap

- [ ] Claude Desktop MCP integration (`server.py` is wired up, connection pending)
- [ ] HTML report output with map view
- [ ] iProperty / iproperty.com.my support

---

## Built With

Python · BeautifulSoup · OpenRouteService · SerpAPI · PropertyGuru

*Built for personal use. Scraping is for your own shortlist data only.*
