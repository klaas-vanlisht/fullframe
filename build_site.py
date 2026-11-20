#!/usr/bin/env python3
"""One-shot build for the public website (used by GitHub Actions).

Fetches the news, groups stories, writes AI summaries with Gemini (GEMINI_API_KEY),
then writes the finished static site to ./site. The database lives in ./data/news.db
and is carried between runs by the workflow.

Run it yourself:  GEMINI_API_KEY=... python build_site.py
"""
import os
import shutil
import sys
import time

try:
    sys.stdout.reconfigure(errors="replace")
except AttributeError:
    pass

from fullframe import export  # noqa: E402
from fullframe.db import DB  # noqa: E402
from fullframe.pipeline import Pipeline  # noqa: E402
from fullframe.util import ROOT, iso, load_config, load_sources, now_utc  # noqa: E402
import datetime as dt  # noqa: E402


def main():
    t0 = time.time()
    cfg = load_config()
    if not os.environ.get("FULLFRAME_AI"):
        os.environ["FULLFRAME_AI"] = "gemini"  # never use a personal Claude login for the public site
    cfg["keep_days"] = min(cfg["keep_days"], cfg.get("publish", {}).get("keep_days", 4))
    sources = load_sources()
    db = DB()
    p = Pipeline(cfg, db, sources)
    if not p.llm:
        print("[build] No GEMINI_API_KEY set: building without AI summaries.", flush=True)
    else:
        print("[build] AI: %s (%s)" % (p.llm.name, p.llm.model), flush=True)
    p.run()
    if p.status["last_error"]:
        print("[build] pipeline error: %s" % p.status["last_error"], flush=True)

    out = os.path.join(ROOT, "site")
    shutil.rmtree(out, ignore_errors=True)
    n = export.export(db, sources, cfg, out, public=True, ai_status=p.status["ai"], copy_web=True)

    # keep the database small: drop fetched article text older than a day, then compact
    db.x("UPDATE articles SET body = NULL WHERE body IS NOT NULL AND fetched < ?",
         (iso(now_utc() - dt.timedelta(hours=24)),))
    # excerpts are only needed while stories are still being grouped (72h); drop them after 4 days
    db.x("UPDATE articles SET description = NULL WHERE description IS NOT NULL AND published < ?",
         (iso(now_utc() - dt.timedelta(days=4)),))
    db.x("VACUUM")
    db.close()
    size = os.path.getsize(db.path) / 1e6
    print("[build] %d stories published to ./site, %d AI requests today, db %.1f MB, %.0fs"
          % (n, p.status["ai"].get("requests_today", 0), size, time.time() - t0), flush=True)
    if p.status["last_error"] and n == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
