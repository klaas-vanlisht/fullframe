"""Write the site as static files: the web UI plus JSON data.

The same files power both the local app (served by server.py) and the public
website on GitHub Pages. Public builds leave out publishers' excerpts and images
by default (see "publish" in config.json): only headlines, links and AI summaries.
"""
import hashlib
import html
import json
import os
import shutil

from . import places, views
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


def _seo(out_dir, cards, cfg):
    """Search-engine extras for the public site: real headlines in the HTML (so crawlers see
    content without running JavaScript), site-verification tags and a sitemap."""
    pub = cfg.get("publish", {})
    url = pub.get("site_url", "").rstrip("/") + "/"
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, encoding="utf-8") as f:
        page = f.read()
    top = sorted((c for c in cards if c["n_sources"] >= cfg["min_sources_top"]), key=lambda c: -c["score"])[:30]
    items = []
    for c in top:
        summ = "<p>%s</p>" % html.escape(c["summary"]) if c.get("summary") else ""
        items.append('<li><a href="#/story/%d"><h3>%s</h3></a>%s<p class="aside-note">%s · covered by %d outlets</p></li>'
                     % (c["id"], html.escape(c["headline"]), summ, html.escape(c["topic"]), c["n_sources"]))
    if items:
        page = page.replace("<!--STATIC_STORIES-->",
                            '<h2 class="section-title">Top stories</h2><ul class="static-list">%s</ul>' % "".join(items))
    tags = []
    if pub.get("google_site_verification"):
        tags.append('<meta name="google-site-verification" content="%s">' % html.escape(pub["google_site_verification"]))
    if pub.get("bing_site_verification"):
        tags.append('<meta name="msvalidate.01" content="%s">' % html.escape(pub["bing_site_verification"]))
    page = page.replace("<!--SITE_VERIFICATION-->", "\n".join(tags))
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(page)
    if url != "/":
        with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    '  <url><loc>%s</loc><lastmod>%s</lastmod><changefreq>hourly</changefreq><priority>1.0</priority></url>\n'
                    '</urlset>\n' % (html.escape(url), now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")))


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

    if copy_web and public:
        _seo(out_dir, cards, cfg)

    _write_json(os.path.join(data_dir, "stories.json"), {"generated": iso(now_utc()), "stories": cards})
    _write_json(os.path.join(data_dir, "sources.json"), views.list_sources(db, sources))
    ai = ai_status or {}
    _write_json(os.path.join(data_dir, "status.json"), {
        "generated": iso(now_utc()),
        "mode": "static" if public else "local",
        "site_title": pub.get("site_title", "Fullframe"),
        "country_names": places.COUNTRY_NAMES,
        "refresh_minutes": cfg["refresh_minutes"],
        "min_sources_top": cfg["min_sources_top"],
        "min_sources_ai": cfg["ai"]["min_sources"],
        "excerpts": excerpts,
        "ai": {"available": bool(ai.get("available")), "provider": ai.get("provider"), "model": ai.get("model")},
        "stats": views.stats(db),
    })
    return len(cards)
