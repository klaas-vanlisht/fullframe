"""Small shared helpers: time, text cleanup, config loading."""
import datetime as dt
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

LEAN_SCORE = {"far-left": -3, "left": -2, "lean-left": -1, "center": 0,
              "lean-right": 1, "right": 2, "far-right": 3}


def side_of(lean):
    s = LEAN_SCORE.get(lean)
    if s is None:
        return "unrated"
    return "left" if s < 0 else "right" if s > 0 else "center"


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(d):
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def hours_ago(s, ref=None):
    d = parse_iso(s)
    if not d:
        return 9999.0
    return ((ref or now_utc()) - d).total_seconds() / 3600.0


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(s, limit=None):
    """Strip HTML tags/entities and collapse whitespace."""
    if not s:
        return ""
    s = html.unescape(_TAG.sub(" ", html.unescape(s)))
    s = _WS.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "…"
    return s


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def load_config():
    cfg = load_json(os.path.join(ROOT, "config.json"), {}) or {}
    cfg.setdefault("host", "127.0.0.1")
    cfg.setdefault("port", 8642)
    cfg.setdefault("open_browser", True)
    cfg.setdefault("refresh_minutes", 30)
    cfg.setdefault("max_article_age_hours", 48)
    cfg.setdefault("keep_days", 10)
    cfg.setdefault("cluster_threshold", 0.25)
    cfg.setdefault("min_sources_top", 3)
    cfg.setdefault("min_outlets_for_country_tab", 2)
    pub = cfg.setdefault("publish", {})
    pub.setdefault("site_title", "Fullframe")
    pub.setdefault("include_excerpts", False)
    pub.setdefault("include_images", False)
    pub.setdefault("keep_days", 4)
    ai = cfg.setdefault("ai", {})
    ai.setdefault("enabled", True)
    ai.setdefault("claude_path", "")
    ai.setdefault("provider", "auto")
    ai.setdefault("gemini_model", "gemini-flash-lite-latest")
    ai.setdefault("min_seconds_between_requests", 7)
    ai.setdefault("max_requests_per_day", 400)
    ai.setdefault("claude_model", ai.get("model", "haiku"))
    ai.setdefault("min_sources", 3)
    ai.setdefault("max_summaries_per_run", 12)
    ai.setdefault("resummarize_after_new_sources", 3)
    ai.setdefault("timeout_seconds", 240)
    ai.setdefault("fetch_article_text", True)
    ai.setdefault("match_languages", True)
    return cfg


COUNTRY_NAMES = {
    "US": "United States", "UK": "United Kingdom", "GB": "United Kingdom", "IE": "Ireland", "CA": "Canada",
    "AU": "Australia", "NZ": "New Zealand", "IN": "India", "ZA": "South Africa", "BE": "Belgium",
    "NL": "Netherlands", "FR": "France", "DE": "Germany", "IT": "Italy", "ES": "Spain", "PT": "Portugal",
    "AT": "Austria", "CH": "Switzerland", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "CZ": "Czechia", "GR": "Greece", "UA": "Ukraine", "RU": "Russia", "TR": "Turkey",
    "IL": "Israel", "QA": "Qatar", "AE": "UAE", "JP": "Japan", "KR": "South Korea", "CN": "China",
    "HK": "Hong Kong", "SG": "Singapore", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "EU": "Europe",
    "LU": "Luxembourg", "HU": "Hungary", "RO": "Romania",
}


def country_names():
    raw = load_json(os.path.join(ROOT, "sources.json"), {}) or {}
    names = dict(COUNTRY_NAMES)
    names.update(raw.get("country_names") or {})
    return names


def load_sources():
    raw = load_json(os.path.join(ROOT, "sources.json"), {"sources": []})
    out = {}
    for s in raw.get("sources", []):
        if not s.get("enabled", True):
            continue
        s.setdefault("feeds", [])
        s["side"] = side_of(s.get("lean"))
        s["country"] = (s.get("country") or "XX").upper()
        s.setdefault("lang", "en")
        out[s["id"]] = s
    return out
