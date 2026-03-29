"""
weather.py — Update weather in a local Notion markdown file.

Writes to the local file only. Run `make push` (or push.py) to sync to Notion.
If a weather section for the same city + date range already exists, it is
updated in place. Otherwise it is appended.

Usage:
    # Current weather, coords from .env
    python scripts/weather.py "Page Title"

    # Date range
    python scripts/weather.py "Page Title" 2026-04-03 2026-04-06

    # Specific city (geocoded automatically)
    python scripts/weather.py "Page Title" 2026-04-03 2026-04-06 --city Stuttgart

    # Save config so push.py auto-refreshes weather before every push
    python scripts/weather.py "Page Title" 2026-04-03 2026-04-06 --city Stuttgart --remember

    # Page can be a title or a path relative to the pages folder
    python scripts/weather.py "Travel/2026_events/Easter_in_BW" 2026-04-03 2026-04-06 --city Stuttgart --remember

Configure in .env:
    WEATHER_PAGE=Daily Notes
    WEATHER_LAT=48.78
    WEATHER_LON=9.18
    WEATHER_TZ=Europe/Berlin
"""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).parent.parent


def _load_dotenv():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

PAGES_DIR = REPO_ROOT / "notebook" / os.environ.get("PAGES_DIR", "pages")
WEATHER_CONFIG_FILE = PAGES_DIR / ".weather_config.json"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    95: "Thunderstorm", 99: "Thunderstorm with hail",
}

WMO_SYMBOLS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "🌨️", 73: "❄️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 99: "⛈️",
}


# ---------------------------------------------------------------------------
# Weather config
# Config format: { "relative/path.md": [ {city, lat, lon, start, end, ...}, ... ] }
# A file can have multiple entries — one per weather table (different city or dates).
# ---------------------------------------------------------------------------

def load_weather_config() -> dict:
    if not WEATHER_CONFIG_FILE.exists():
        return {}
    config = json.loads(WEATHER_CONFIG_FILE.read_text(encoding="utf-8"))
    # Migrate old format (single dict per file) to list format
    for key, val in config.items():
        if isinstance(val, dict):
            config[key] = [val]
    return config


def save_weather_config(config: dict):
    WEATHER_CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _config_key(entry: dict) -> tuple:
    """Unique key for a config entry: (resolved_city, start, end)."""
    return (entry.get("resolved_city"), entry.get("start"), entry.get("end"))


def upsert_weather_config(config: dict, rel: str, entry: dict):
    """Add or update a single weather entry for a file."""
    entries = config.get(rel, [])
    key = _config_key(entry)
    for i, existing in enumerate(entries):
        if _config_key(existing) == key:
            entries[i] = entry
            config[rel] = entries
            return
    entries.append(entry)
    config[rel] = entries


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

async def geocode(city: str) -> tuple[float, float, str]:
    """Return (lat, lon, resolved_name) for a city via Open-Meteo geocoding."""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&format=json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results")
    if not results:
        raise ValueError(f"City not found: '{city}'. Try a more specific name.")
    r = results[0]
    name = r.get("name", city)
    country = r.get("country", "")
    resolved = f"{name}, {country}" if country else name
    return r["latitude"], r["longitude"], resolved


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def fetch_current(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
        "precipitation,wind_speed_10m,weather_code"
        "&wind_speed_unit=kmh"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()["current"]


async def fetch_daily(lat: float, lon: float, start: str, end: str, tz: str) -> dict:
    today = date.today().isoformat()
    base = (
        "https://archive-api.open-meteo.com/v1/archive"
        if end < today
        else "https://api.open-meteo.com/v1/forecast"
    )
    url = (
        f"{base}?latitude={lat}&longitude={lon}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "apparent_temperature_max,precipitation_sum,wind_speed_10m_max"
        f"&start_date={start}&end_date={end}"
        f"&timezone={tz}&wind_speed_unit=kmh"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()["daily"]


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def _symbol(code: int) -> str:
    return WMO_SYMBOLS.get(code, "🌡️")


def _condition(code: int) -> str:
    return WMO_CODES.get(code, str(code))


def _t(val) -> str:
    return f"{round(float(val))}°C"


def format_current(weather: dict, city_label: str | None) -> tuple[str, str]:
    code = weather["weather_code"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    city_tag = f" · {city_label}" if city_label else ""
    anchor = f"## Weather{city_tag} — "
    header = f"{anchor}{now}"
    table = (
        f"{header}\n\n"
        f"| | Condition | Temp | Feels Like | Humidity | Precipitation | Wind |\n"
        f"|--|-----------|------|------------|----------|---------------|------|\n"
        f"| {_symbol(code)} | {_condition(code)} "
        f"| {_t(weather['temperature_2m'])} "
        f"| {_t(weather['apparent_temperature'])} "
        f"| {weather['relative_humidity_2m']}% "
        f"| {weather['precipitation']} mm "
        f"| {round(float(weather['wind_speed_10m']))} km/h |\n"
    )
    return anchor, table


def format_daily(daily: dict, start: str, end: str, city_label: str | None) -> tuple[str, str]:
    city_tag = f" · {city_label}" if city_label else ""
    header = f"## Weather{city_tag} {start} → {end}"
    rows = ""
    for i, day in enumerate(daily["time"]):
        code = daily["weather_code"][i]
        day_name = datetime.strptime(day, "%Y-%m-%d").strftime("%A")
        rows += (
            f"| {day} | {day_name} "
            f"| {_symbol(code)} | {_condition(code)} "
            f"| {_t(daily['temperature_2m_max'][i])} "
            f"| {_t(daily['temperature_2m_min'][i])} "
            f"| {_t(daily['apparent_temperature_max'][i])} "
            f"| {daily['precipitation_sum'][i]} mm "
            f"| {round(float(daily['wind_speed_10m_max'][i]))} km/h |\n"
        )
    table = (
        f"{header}\n\n"
        f"| Date | Day | | Condition | High | Low | Feels Like | Precipitation | Wind |\n"
        f"|------|-----|--|-----------|------|-----|------------|---------------|------|\n"
        + rows
    )
    return header, table


# ---------------------------------------------------------------------------
# Local file update
# ---------------------------------------------------------------------------

def update_section(content: str, anchor: str, new_section: str) -> tuple[str, bool]:
    idx = content.find(anchor)
    if idx == -1:
        return content, False
    tail = content[idx + len(anchor):]
    next_heading = re.search(r'\n##\s', tail)
    end = idx + len(anchor) + (next_heading.start() if next_heading else len(tail))
    new_content = content[:idx] + new_section.strip() + "\n" + content[end:]
    return new_content, True


def update_local_file(filepath: Path, anchor: str, section: str) -> bool:
    """Update or append weather section in a local markdown file."""
    text = filepath.read_text(encoding="utf-8")

    # Preserve frontmatter
    fm_match = re.match(r'^(---\n.*?\n---\n)', text, re.DOTALL)
    frontmatter = fm_match.group(1) if fm_match else ""
    content = text[fm_match.end():] if fm_match else text

    new_content, replaced = update_section(content, anchor, section)
    if not replaced:
        new_content = content.rstrip() + "\n\n" + section.strip() + "\n"

    filepath.write_text(frontmatter + new_content, encoding="utf-8")
    return replaced


def find_local_file(page_ref: str) -> Path | None:
    """Find a local .md file by path or stem."""
    stem = page_ref[:-3] if page_ref.endswith(".md") else page_ref

    # Try as a direct relative path first
    for candidate in [PAGES_DIR / (stem + ".md"), PAGES_DIR / page_ref]:
        if candidate.exists():
            return candidate

    # Search by filename stem across all subdirs
    target = Path(stem).name.lower()
    for f in PAGES_DIR.rglob("*.md"):
        if f.stem.lower() == target or f.stem.lower() == target.replace(" ", "_"):
            return f
    return None


# ---------------------------------------------------------------------------
# Core apply function (used by both weather.py and push.py)
# ---------------------------------------------------------------------------

async def apply_weather(
    filepath: Path,
    start: str | None,
    end: str | None,
    lat: float,
    lon: float,
    tz: str,
    city_label: str | None,
) -> bool:
    """Fetch weather and update the local file. Returns True if updated in place."""
    if start and end:
        daily = await fetch_daily(lat, lon, start, end, tz)
        anchor, section = format_daily(daily, start, end, city_label)
    else:
        current = await fetch_current(lat, lon)
        anchor, section = format_current(current, city_label)
    return update_local_file(filepath, anchor, section)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Update weather in a local Notion markdown file.")
    parser.add_argument("page", nargs="?", default=None, help="Page title or path")
    parser.add_argument("start", nargs="?", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("end", nargs="?", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--city", default=None, help="City name (e.g. Stuttgart)")
    parser.add_argument("--remember", action="store_true",
                        help="Save this config so push.py auto-refreshes weather before pushing")
    args = parser.parse_args()

    page_ref = args.page or os.environ.get("WEATHER_PAGE")
    if not page_ref:
        parser.print_help()
        return

    if (args.start is None) != (args.end is None):
        parser.error("Provide both start and end dates, or neither.")

    tz = os.environ.get("WEATHER_TZ", "Europe/Berlin")

    # Resolve coordinates and city label
    if args.city:
        print(f"Geocoding '{args.city}'...")
        lat, lon, city_label = await geocode(args.city)
        print(f"  → {city_label} ({lat:.4f}, {lon:.4f})")
    else:
        lat = float(os.environ.get("WEATHER_LAT", "48.78"))
        lon = float(os.environ.get("WEATHER_LON", "9.18"))
        # Use WEATHER_CITY from .env as display name even when no --city flag given
        city_label = os.environ.get("WEATHER_CITY") or None

    # Find local file
    filepath = find_local_file(page_ref)
    if filepath is None:
        print(f"File not found locally for '{page_ref}'. Run pull.py first.")
        return

    rel = str(filepath.relative_to(PAGES_DIR))
    print(f"Updating {rel}...")

    replaced = await apply_weather(filepath, args.start, args.end, lat, lon, tz, city_label)
    print("Updated in place." if replaced else "Appended new weather section.")

    # Save config for push.py auto-refresh
    if args.remember:
        config = load_weather_config()
        entry = {
            "city": args.city,
            "resolved_city": city_label,
            "lat": lat,
            "lon": lon,
            "start": args.start,
            "end": args.end,
        }
        upsert_weather_config(config, rel, entry)
        save_weather_config(config)
        print(f"Remembered: push will auto-refresh weather for {rel}.")


if __name__ == "__main__":
    asyncio.run(main())
