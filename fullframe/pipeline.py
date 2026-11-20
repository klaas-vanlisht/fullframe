"""Refresh cycle: fetch feeds -> store -> cluster -> summarize. Runs in a background thread."""
import datetime as dt
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import ai, cluster, feeds, llm
from .filters import ContentFilter
from .util import hours_ago, iso, now_utc


class Pipeline:
    def __init__(self, cfg, db, sources):
        self.cfg, self.db, self.sources = cfg, db, sources
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.llm = llm.make_provider(cfg)
        self.filter = ContentFilter(cfg)
        self.after_run = None  # callback, e.g. to export the site
        self.status = {
            "running": False, "stage": "idle", "progress": "", "last_run": None, "last_duration_s": None,
            "next_run": None, "last_error": None, "new_articles": 0,
            "ai": {"enabled": bool(cfg["ai"]["enabled"]), "available": bool(self.llm),
                   "provider": self.llm.name if self.llm else None,
                   "model": self.llm.model if self.llm else None,
                   "last_error": None, "summarized_last_run": 0, "requests_today": 0},
        }
        self._resummarize = set()
        self._stop_ai = False

    # ------------------------------------------------------------ AI budget
    def _today_key(self):
        return "requests:" + now_utc().strftime("%Y-%m-%d")

    def _requests_today(self):
        r = self.db.one("SELECT value FROM meta WHERE key = ?", (self._today_key(),))
        return int(r["value"]) if r else 0

    def _ask(self, prompt):
        """One AI request, respecting the daily budget. Raises llm.QuotaExhausted to stop the run."""
        if self._stop_ai:
            raise llm.QuotaExhausted(self.status["ai"]["last_error"] or "AI paused for this run")
        used = self._requests_today()
        if used >= int(self.cfg["ai"].get("max_requests_per_day", 400)):
            raise llm.QuotaExhausted("Daily AI budget (%d requests) used up; continuing tomorrow." % used)
        self.db.x("INSERT INTO meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = value + 1",
                  (self._today_key(),))
        self.db.x("DELETE FROM meta WHERE key LIKE 'requests:%' AND key < ?",
                  ("requests:" + (now_utc() - dt.timedelta(days=7)).strftime("%Y-%m-%d"),))
        self.status["ai"]["requests_today"] = used + 1
        try:
            out = self.llm.complete(prompt)
            self.status["ai"]["model"] = self.llm.model  # may have been auto-picked
            return out
        except llm.QuotaExhausted as e:
            self._stop_ai = True
            self.status["ai"]["last_error"] = str(e)
            raise

    # ------------------------------------------------------------ scheduling
    def start(self):
        threading.Thread(target=self._loop, name="refresh-loop", daemon=True).start()

    def trigger(self, resummarize_story=None):
        if resummarize_story is not None:
            self._resummarize.add(int(resummarize_story))
        self.wake.set()

    def _loop(self):
        while True:
            self.wake.clear()
            only_ai = bool(self._resummarize) and self.status["last_run"] is not None and \
                hours_ago(self.status["last_run"]) * 60 < self.cfg["refresh_minutes"]
            self.run(skip_fetch=only_ai)
            nxt = now_utc() + dt.timedelta(minutes=self.cfg["refresh_minutes"])
            self.status["next_run"] = iso(nxt)
            self.wake.wait(timeout=self.cfg["refresh_minutes"] * 60)

    # ------------------------------------------------------------ main run
    def run(self, skip_fetch=False):
        if not self.lock.acquire(blocking=False):
            return
        t0 = time.time()
        st = self.status
        st.update(running=True, last_error=None)
        self._stop_ai = False
        try:
            if not skip_fetch:
                st["stage"] = "fetching"
                st["new_articles"] = self.fetch_all()
                self.purge_filtered()
                st["stage"] = "grouping stories"
                st["progress"] = ""
                cluster.assign_stories(self.db, self.sources, self.cfg["cluster_threshold"])
                self.prune()
                st["stage"] = "finding images"
                self.improve_images()
            if self.llm and not skip_fetch and self.cfg["ai"].get("match_languages", True):
                st["stage"] = "matching languages"
                self.match_across_languages()
            if self.llm:
                st["stage"] = "summarizing"
                self.summarize_pending()
            st["last_run"] = iso(now_utc())
            if self.after_run:
                st["stage"] = "publishing"
                self.after_run()
        except Exception as e:  # noqa: BLE001
            st["last_error"] = "%s: %s" % (type(e).__name__, e)
            traceback.print_exc()
        finally:
            st.update(running=False, stage="idle", progress="", last_duration_s=round(time.time() - t0, 1))
            self.lock.release()

    def fetch_all(self):
        srcs = list(self.sources.values())
        done, new_total = 0, 0
        max_age = self.cfg["max_article_age_hours"]
        with ThreadPoolExecutor(max_workers=16) as pool:
            futs = {pool.submit(feeds.fetch_source, s, max_age): s for s in srcs}
            for fut in as_completed(futs):
                s = futs[fut]
                done += 1
                self.status["progress"] = "%d/%d outlets" % (done, len(srcs))
                try:
                    items, info = fut.result()
                except Exception as e:  # noqa: BLE001
                    items, info = [], {"status": "error", "via": None, "count": 0, "error": str(e)[:300]}
                new_total += self.store(s["id"], items)
                self.db.x("INSERT OR REPLACE INTO source_status (id, status, via, last_fetch, last_count, error) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (s["id"], info["status"], info["via"], iso(now_utc()), info["count"], info["error"]))
        print("[fetch] %d new articles from %d outlets" % (new_total, len(srcs)), flush=True)
        return new_total

    def store(self, source_id, items):
        now = now_utc()
        new = 0
        for it in items:
            url = feeds.canonical_url(it["url"])
            if self.filter.blocked(it["title"], url):
                continue  # shopping deals, food reviews, horoscopes, ... (see filters.py)
            pub = it["published"] or now
            if pub > now + dt.timedelta(hours=1):
                pub = now
            exists = self.db.one("SELECT id FROM articles WHERE url = ? OR (source_id = ? AND title = ?)",
                                 (url, source_id, it["title"]))
            if exists:
                continue
            self.db.x("INSERT INTO articles (url, source_id, title, description, image, published, fetched) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (url, source_id, it["title"], it["description"], it["image"], iso(pub), iso(now)))
            new += 1
        return new

    def improve_images(self, limit=80):
        """Give multi-outlet stories a sharp picture: the article's own share image (og:image, usually
        1200px wide) beats the small thumbnails most feeds carry. A few pages per story, cached."""
        since = iso(now_utc() - dt.timedelta(days=7))
        rows = self.db.q(
            "SELECT s.id, COUNT(DISTINCT a.source_id) AS n FROM stories s JOIN articles a ON a.story_id = s.id "
            "WHERE s.last_article_at >= ? AND COALESCE(s.image_hi, 0) = 0 GROUP BY s.id HAVING n >= 2 "
            "ORDER BY n DESC, s.last_article_at DESC", (since,))
        jobs, stories = [], 0
        for r in rows:
            arts = self.db.q("SELECT id, url FROM articles WHERE story_id = ? AND og_image IS NULL "
                             "AND url NOT LIKE '%news.google.com%' ORDER BY published DESC LIMIT 2", (r["id"],))
            if not arts:  # every page already checked: keep whatever picture it has
                self.db.x("UPDATE stories SET image_hi = 1 WHERE id = ?", (r["id"],))
                continue
            jobs += [(r["id"], a["id"], a["url"]) for a in arts]
            stories += 1
            if stories >= limit:
                break
        if not jobs:
            return
        found = set()
        with ThreadPoolExecutor(max_workers=10) as pool:
            for (sid, aid, url), img in zip(jobs, pool.map(lambda j: feeds.fetch_og_image(j[2]), jobs)):
                self.db.x("UPDATE articles SET og_image = ? WHERE id = ?", (img or "none", aid))
                if img and sid not in found:
                    found.add(sid)
                    self.db.x("UPDATE stories SET image = ?, image_hi = 1 WHERE id = ?", (img, sid))
        print("[images] full-size pictures for %d of %d stories" % (len(found), stories), flush=True)

    def purge_filtered(self):
        """Apply the content filter to articles already stored (e.g. after editing the filter)."""
        rows = self.db.q("SELECT id, title, url FROM articles")
        gone = [r["id"] for r in rows if self.filter.blocked(r["title"], r["url"])]
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            self.db.x("DELETE FROM articles WHERE id IN (%s)" % ",".join("?" * len(chunk)), chunk)
        if gone:
            self.db.x("DELETE FROM stories WHERE id NOT IN (SELECT DISTINCT story_id FROM articles WHERE story_id IS NOT NULL)")
            print("[filter] removed %d non-news articles (deals, food reviews, puzzles, ...)" % len(gone), flush=True)

    def prune(self):
        cutoff = iso(now_utc() - dt.timedelta(days=self.cfg["keep_days"]))
        self.db.x("DELETE FROM articles WHERE published < ?", (cutoff,))
        self.db.x("DELETE FROM stories WHERE id NOT IN (SELECT DISTINCT story_id FROM articles WHERE story_id IS NOT NULL)")

    # ------------------------------------------------------------ AI
    def match_across_languages(self):
        """One AI request that links different-language versions of the same story.

        Only runs when sources.json contains non-English outlets. It looks at stories from the
        countries those outlets are in (including that country's English-language outlets).
        """
        multi = {s.get("country") for s in self.sources.values() if s.get("lang", "en") != "en"}
        if not multi:
            return
        local = {sid for sid, s in self.sources.items() if s.get("country") in multi}
        since = iso(now_utc() - dt.timedelta(hours=36))
        marks = ",".join("?" * len(local))
        rows = self.db.q("SELECT a.story_id, a.title, s.lang_checked FROM articles a JOIN stories s ON s.id = a.story_id "
                         "WHERE s.last_article_at >= ? AND a.source_id IN (%s) ORDER BY a.published DESC" % marks,
                         [since] + sorted(local))
        heads, unchecked = {}, set()
        for r in rows:
            if not r["lang_checked"]:
                unchecked.add(r["story_id"])
            h = heads.setdefault(r["story_id"], [])
            if len(h) < 2 and r["title"] not in h:
                h.append(r["title"])
        ids = list(heads)[:150]
        if len(ids) < 2 or not (set(ids) & unchecked):
            return  # nothing new since the last check
        try:
            text = self._ask(ai.build_match_prompt([(i, heads[i]) for i in ids]))
            groups = ai.parse_groups(text, set(ids))
        except Exception as e:  # noqa: BLE001
            self.status["ai"]["last_error"] = "Language matching: " + str(e)[:300]
            print("[ai] language matching failed: %s" % e, flush=True)
            return
        marks = ",".join("?" * len(ids))
        self.db.x("UPDATE stories SET lang_checked = 1 WHERE id IN (%s)" % marks, ids)
        for g in groups:
            cluster.merge_stories(self.db, g)
        if groups:
            print("[ai] merged %d cross-language story groups" % len(groups), flush=True)

    def _candidates(self):
        acfg = self.cfg["ai"]
        since = iso(now_utc() - dt.timedelta(hours=36))
        rows = self.db.q(
            "SELECT s.id, s.ai, s.ai_n_sources, s.ai_error, s.ai_at, s.last_article_at, "
            "COUNT(DISTINCT a.source_id) AS n_src FROM stories s JOIN articles a ON a.story_id = s.id "
            "WHERE s.last_article_at >= ? GROUP BY s.id", (since,))
        out = []
        for r in rows:
            forced = r["id"] in self._resummarize
            if not forced and r["n_src"] < acfg["min_sources"]:
                continue
            if not forced and r["ai"] and r["n_src"] - (r["ai_n_sources"] or 0) < acfg["resummarize_after_new_sources"]:
                continue
            if not forced and r["ai_error"] and r["ai_at"] and hours_ago(r["ai_at"]) < 3 and \
                    r["n_src"] == (r["ai_n_sources"] or 0):
                continue  # failed recently with the same material; don't hammer
            score = r["n_src"] / (1.0 + hours_ago(r["last_article_at"]) / 6.0)
            out.append((forced, score, r))
        out.sort(key=lambda t: (not t[0], -t[1]))
        limit = acfg["max_summaries_per_run"]
        return [r for f, _, r in out if f][:50] + [r for f, _, r in out if not f][:limit]

    def summarize_pending(self):
        cands = self._candidates()
        have = {r["id"] for r in cands}
        for sid in list(self._resummarize - have):
            row = self.db.one("SELECT COUNT(DISTINCT source_id) AS n_src FROM articles WHERE story_id = ?", (sid,))
            if row and row["n_src"]:
                cands.insert(0, {"id": sid, "n_src": row["n_src"]})
            else:
                self._resummarize.discard(sid)
        self.status["ai"]["summarized_last_run"] = 0
        for i, r in enumerate(cands):
            self.status["progress"] = "story %d/%d" % (i + 1, len(cands))
            self._resummarize.discard(r["id"])
            ok = self.summarize_story(r["id"], r["n_src"])
            if ok:
                self.status["ai"]["summarized_last_run"] += 1
            elif self._stop_ai:
                print("[ai] stopping for this run: %s" % self.status["ai"]["last_error"], flush=True)
                break

    def summarize_story(self, story_id, n_src):
        acfg = self.cfg["ai"]
        arts = cluster.representative_order(self.db, story_id)
        if acfg["fetch_article_text"]:
            picked, seen = [], set()
            for a in arts:
                if a["source_id"] not in seen and not a["body"] and "news.google.com" not in a["url"]:
                    seen.add(a["source_id"])
                    picked.append(a)
                if len(picked) >= 6:
                    break
            with ThreadPoolExecutor(max_workers=6) as pool:
                for a, text in zip(picked, pool.map(lambda a: feeds.extract_article_text(a["url"]), picked)):
                    a["body"] = text or ""
                    self.db.x("UPDATE articles SET body = ? WHERE id = ?", (a["body"], a["id"]))
        prompt = ai.build_prompt(arts, self.sources)
        try:
            try:
                res = ai.normalize_result(ai.extract_json(self._ask(prompt)))
            except ValueError:  # malformed JSON now and then: one retry
                res = ai.normalize_result(ai.extract_json(self._ask(prompt)))
        except llm.QuotaExhausted:
            return False  # not the story's fault; try it again next run
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:500]
            self.status["ai"]["last_error"] = msg
            self.db.x("UPDATE stories SET ai_error = ?, ai_at = ?, ai_n_sources = ? WHERE id = ?",
                      (msg, iso(now_utc()), n_src, story_id))
            print("[ai] story %s failed: %s" % (story_id, msg), flush=True)
            return False
        self.db.x("UPDATE stories SET ai = ?, ai_at = ?, ai_n_sources = ?, ai_error = NULL, coherent = ?, "
                  "topic = COALESCE(?, topic) WHERE id = ?",
                  (json.dumps(res), iso(now_utc()), n_src, 1 if res["same_story"] else 0, res["topic"], story_id))
        return True
