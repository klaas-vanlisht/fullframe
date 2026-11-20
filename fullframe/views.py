"""Read-side: turn DB rows into the JSON the web UI shows."""
import datetime as dt
import json
from collections import defaultdict

from .feeds import good_image, upgrade_image_url
from . import places as placemod
from .util import country_names, hours_ago, iso, now_utc

__all__ = ["story_cards", "story_detail", "list_sources", "stats"]

SIDES = ("left", "center", "right")
FACT_GROUP = {"very-high": "high", "high": "high", "mostly-factual": "mixed", "mixed": "mixed", "low": "low"}


def countries_with_tabs(sources, cfg):
    """Countries that get their own tab: every country with enough outlets in sources.json."""
    names = country_names()
    count = defaultdict(int)
    for s in sources.values():
        count[s["country"]] += 1
    out = [{"code": c, "name": names.get(c, c), "outlets": n} for c, n in count.items()
           if n >= cfg.get("min_outlets_for_country_tab", 2)]
    out.sort(key=lambda c: (-c["outlets"], c["name"]))
    return out


def _active_per_side(db, sources):
    """Active outlets per side for every country (used to normalize coverage)."""
    ok = {r["id"] for r in db.q("SELECT id FROM source_status WHERE status = 'ok'")}
    out = defaultdict(lambda: {s: 0 for s in SIDES})
    for sid, s in sources.items():
        if (not ok or sid in ok) and s["side"] in SIDES:
            out[s["country"]][s["side"]] += 1
    return dict(out)


def _denominators(source_ids, sources, active):
    """Outlets per side across the countries that covered this story."""
    countries = {sources[s]["country"] for s in source_ids if s in sources}
    tot = {k: 0 for k in SIDES}
    for c in countries:
        for k in SIDES:
            tot[k] += active.get(c, {}).get(k, 0)
    return {k: max(v, 1) for k, v in tot.items()}


def story_places(st, arts, aiobj):
    """Countries a story is about: the AI's tags and headline/summary mentions, plus countries named
    in a good share of the outlets' own headlines (one stray mention doesn't count)."""
    found = set((aiobj or {}).get("countries") or [])
    found |= placemod.detect((aiobj or {}).get("headline") or "") | placemod.detect((aiobj or {}).get("summary") or "")
    titles = list({a["title"] for a in arts})
    counts = defaultdict(int)
    for t in titles:
        for c in placemod.detect(t):
            counts[c] += 1
    need = 1 if len(titles) <= 3 else max(2, round(len(titles) * 0.25))
    found |= {c for c, n in counts.items() if n >= need}
    return found


def story_countries(source_ids, sources):
    """Countries whose press is really covering this story (2+ of its outlets, or its only outlet)."""
    per = defaultdict(int)
    for s in source_ids:
        if s in sources:
            per[sources[s]["country"]] += 1
    size = defaultdict(int)
    for s in sources.values():
        size[s["country"]] += 1
    return sorted(c for c, n in per.items() if n >= min(2, size[c]))


def _bias(source_ids, sources, active):
    counts = {s: 0 for s in SIDES}
    counts["unrated"] = 0
    fact = {"high": 0, "mixed": 0, "low": 0}
    for sid in source_ids:
        s = sources.get(sid)
        side = s["side"] if s else "unrated"
        counts[side] = counts.get(side, 0) + 1
        if s:
            fact[FACT_GROUP.get(s.get("factuality"), "mixed")] += 1
    rated = counts["left"] + counts["center"] + counts["right"]
    pct = {k: (round(100 * counts[k] / rated) if rated else 0) for k in SIDES}
    rate = {k: counts[k] / active[k] for k in SIDES}
    gap = None  # "coverage gap": one side is barely covering the story
    lr = rate["left"] + rate["right"]
    if counts["left"] + counts["right"] >= 4 and lr > 0:
        share_left = rate["left"] / lr
        if share_left <= 0.2 and counts["right"] >= 3:
            gap = "left"    # left-leaning outlets are barely covering this
        elif share_left >= 0.8 and counts["left"] >= 3:
            gap = "right"   # right-leaning outlets are barely covering this
    return {"counts": counts, "pct": pct, "coverage_rate": {k: round(rate[k], 3) for k in SIDES},
            "factuality": fact, "gap": gap}


def _story_card(st, arts, sources, active):
    src_ids = sorted({a["source_id"] for a in arts})
    aiobj = json.loads(st["ai"]) if st.get("ai") else None
    b = _bias(src_ids, sources, _denominators(src_ids, sources, active))
    summary = aiobj.get("summary") if aiobj else None
    places = story_places(st, arts, aiobj)
    outlet_countries = {sources[s]["country"] for s in src_ids if s in sources}
    topic = st["topic"] or "Other"
    return {
        "id": st["id"],
        "headline": (aiobj or {}).get("headline") or st["headline"],
        "original_headline": st["headline"],
        "summary": summary,
        "image": upgrade_image_url(st["image"]) if good_image(st["image"]) else None,
        "topic": st["topic"] or "Other",
        "countries": story_countries(src_ids, sources),
        "home": sorted(outlet_countries),
        "places": sorted(places),
        # international: about countries other than the ones the covering outlets are from (or a World story)
        "intl": topic == "World" or bool(places - outlet_countries),
        "n_sources": len(src_ids),
        "n_articles": len(arts),
        "first_seen": st["first_seen"],
        "updated": st["last_article_at"],
        "has_ai": bool(aiobj),
        "coherent": bool(st.get("coherent", 1)),
        "bias": b,
        "source_names": [sources[s]["name"] for s in src_ids if s in sources][:8],
        "score": round(len(src_ids) / (1.0 + hours_ago(st["last_article_at"]) / 6.0), 4),
        "titles": " ".join(a["title"] for a in arts).lower()[:220],
    }


def story_detail(db, sources, story_id, excerpts=True, images=True, active=None):
    st = db.one("SELECT * FROM stories WHERE id = ?", (story_id,))
    if not st:
        return None
    arts = db.q("SELECT id, source_id, title, description, url, image, og_image, published FROM articles "
                "WHERE story_id = ? ORDER BY published DESC", (story_id,))
    active = active or _active_per_side(db, sources)
    card = _story_card(st, arts, sources, active)
    card.pop("titles", None)
    if not images:
        card["image"] = None
    card["ai"] = json.loads(st["ai"]) if st.get("ai") else None
    card["ai_at"] = st.get("ai_at")
    card["ai_error"] = st.get("ai_error")
    out_arts = []
    for a in arts:
        s = sources.get(a["source_id"], {})
        out_arts.append({
            "title": a["title"], "url": a["url"], "description": a["description"] if excerpts else None,
            "image": (a["og_image"] if good_image(a["og_image"]) else upgrade_image_url(a["image"]) if good_image(a["image"]) else None)
                     if images else None,
            "published": a["published"], "source_id": a["source_id"], "source": s.get("name", a["source_id"]),
            "lean": s.get("lean", "unrated"), "side": s.get("side", "unrated"),
            "factuality": s.get("factuality", "unrated"), "country": s.get("country"), "lang": s.get("lang", "en"),
        })
    card["articles"] = out_arts
    return card


def list_sources(db, sources):
    names = country_names()
    status = {r["id"]: r for r in db.q("SELECT * FROM source_status")}
    since = iso(now_utc() - dt.timedelta(hours=24))
    counts = {r["source_id"]: r["n"] for r in db.q(
        "SELECT source_id, COUNT(*) AS n FROM articles WHERE published >= ? GROUP BY source_id", (since,))}
    out = []
    for sid, s in sources.items():
        st = status.get(sid, {})
        out.append({"id": sid, "name": s["name"], "domain": s.get("domain"), "lean": s.get("lean"),
                    "side": s["side"], "factuality": s.get("factuality"), "country": s.get("country"),
                    "lang": s.get("lang", "en"), "country_name": names.get(s["country"], s["country"]),
                    "status": st.get("status", "pending"), "via": st.get("via"), "error": st.get("error"),
                    "last_fetch": st.get("last_fetch"), "articles_24h": counts.get(sid, 0)})
    order = {"far-left": 0, "left": 1, "lean-left": 2, "center": 3, "lean-right": 4, "right": 5, "far-right": 6}
    out.sort(key=lambda r: (r["country"], order.get(r["lean"], 9), r["name"]))
    return out


def stats(db):
    return {
        "articles": db.one("SELECT COUNT(*) AS n FROM articles")["n"],
        "stories": db.one("SELECT COUNT(*) AS n FROM stories")["n"],
        "summarized": db.one("SELECT COUNT(*) AS n FROM stories WHERE ai IS NOT NULL")["n"],
    }


def story_cards(db, sources, cfg, images=True, min_sources=2):
    """All recent stories (2+ outlets) as cards; filtering/sorting happens in the browser."""
    since = iso(now_utc() - dt.timedelta(hours=max(cfg["max_article_age_hours"], 36)))
    stories = db.q("SELECT id, first_seen, last_article_at, headline, image, topic, ai, coherent "
                   "FROM stories WHERE last_article_at >= ?", (since,))
    arts = db.q("SELECT a.story_id, a.source_id, a.title FROM articles a JOIN stories s ON s.id = a.story_id "
                "WHERE s.last_article_at >= ?", (since,))
    by_story = defaultdict(list)
    for a in arts:
        by_story[a["story_id"]].append(a)
    active = _active_per_side(db, sources)
    cards = []
    size = defaultdict(int)  # outlets per country
    for src in sources.values():
        size[src["country"]] += 1
    singles = []
    for s in stories:
        srcs = {a["source_id"] for a in by_story.get(s["id"], [])}
        if not srcs:
            continue
        if len(srcs) < min_sources:
            # one-outlet stories from smaller countries' local press still matter for the Local view
            home = sources.get(next(iter(srcs)), {}).get("country")
            if len(srcs) == 1 and home and size[home] <= 8:
                singles.append(s)
            continue
        if s.get("ai") and json.loads(s["ai"]).get("not_news"):
            continue  # the AI flagged it as shopping / food review / puzzle content
        c = _story_card(s, by_story[s["id"]], sources, active)
        if not images:
            c["image"] = None
        cards.append(c)
    # keep the download small: the strongest ~900 stories of the week (recent ones get a boost)
    cards.sort(key=lambda c: -(c["n_sources"] / (1.0 + hours_ago(c["updated"]) / 24.0)))
    cards = cards[:cfg.get("publish", {}).get("max_stories", 900)]
    # plus the newest local one-outlet stories (only shown under Local)
    singles.sort(key=lambda s: s["last_article_at"] or "", reverse=True)
    per_country, keep = defaultdict(int), []
    for s in singles:  # the newest ~40 per country, so no single country crowds out the rest
        home = sources.get(by_story[s["id"]][0]["source_id"], {}).get("country")
        if per_country[home] < cfg.get("publish", {}).get("local_singles_per_country", 40):
            per_country[home] += 1
            keep.append(s)
    for s in keep:
        c = _story_card(s, by_story[s["id"]], sources, active)
        if not images:
            c["image"] = None
        c["local_only"] = True
        cards.append(c)
    for c in cards:
        if c.get("summary") and len(c["summary"]) > 280:
            c["summary"] = c["summary"][:280].rsplit(" ", 1)[0] + "…"
    cards.sort(key=lambda c: -c["score"])
    return cards, active
