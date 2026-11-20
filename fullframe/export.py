"""Write the site as static files: the web UI plus JSON data.

The same files power both the local app (served by server.py) and the public
website on GitHub Pages. Public builds leave out publishers' excerpts and images
by default (see "publish" in config.json): only headlines, links and AI summaries.
"""
import hashlib
import json
import os
import shutil

from . import views
from .util import ROOT, iso, now_utc

WEB = os.path.join(ROOT, "web")


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _stamp_assets(index_path, out_dir):
    """Add a content hash to style.css / app.js links so browsers never mix old and new files."""
    with open(index_path, encoding="utf-8") as f:
        page = f.read()
    for name in ("style.css", "app.js"):
        with open(os.path.join(out_dir, name), "rb") as f:
            v = hashlib.sha1(f.read()).hexdigest()[:10]
        page = page.replace('"%s"' % name, '"%s?v=%s"' % (name, v))
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(page)


def export(db, sources, cfg, out_dir, public, ai_status=None, copy_web=False):
    pub = cfg.get("publish", {})
    excerpts = (not public) or pub.get("include_excerpts", False)
    images = (not public) or pub.get("include_images", False)

    if copy_web:
        os.makedirs(out_dir, exist_ok=True)
        build = now_utc().strftime("%Y%m%d%H%M%S")
        for name in os.listdir(WEB):
            src = os.path.join(WEB, name)
            if not os.path.isfile(src):
                continue
            if name == "index.html":  # versioned asset URLs, so browsers never mix old CSS with new HTML
                with open(src, encoding="utf-8") as f:
                    html = f.read().replace("__BUILD__", build)
                with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
                    f.write(html)
            else:
                shutil.copy2(src, os.path.join(out_dir, name))
        open(os.path.join(out_dir, ".nojekyll"), "w").close()
        _stamp_assets(os.path.join(out_dir, "index.html"), out_dir)

    data_dir = os.path.join(out_dir, "data")
    story_dir = os.path.join(data_dir, "story")
    os.makedirs(story_dir, exist_ok=True)

    cards, active = views.story_cards(db, sources, cfg, images=images)
    keep = set()
    for c in cards:
        d = views.story_detail(db, sources, c["id"], excerpts=excerpts, images=images, active=active)
        if d:
            _write_json(os.path.join(story_dir, "%d.json" % c["id"]), d)
            keep.add("%d.json" % c["id"])
    for name in os.listdir(story_dir):  # drop stories that aged out
        if name not in keep:
            try:
                os.remove(os.path.join(story_dir, name))
            except OSError:
                pass

    _write_json(os.path.join(data_dir, "stories.json"), {"generated": iso(now_utc()), "stories": cards})
    _write_json(os.path.join(data_dir, "sources.json"), views.list_sources(db, sources))
    ai = ai_status or {}
    _write_json(os.path.join(data_dir, "status.json"), {
        "generated": iso(now_utc()),
        "mode": "static" if public else "local",
        "site_title": pub.get("site_title", "Fullframe"),
        "countries": views.countries_with_tabs(sources, cfg),
        "refresh_minutes": cfg["refresh_minutes"],
        "min_sources_top": cfg["min_sources_top"],
        "min_sources_ai": cfg["ai"]["min_sources"],
        "excerpts": excerpts,
        "ai": {"available": bool(ai.get("available")), "provider": ai.get("provider"), "model": ai.get("model")},
        "stats": views.stats(db),
    })
    return len(cards)
