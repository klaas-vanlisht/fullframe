"""Group articles from different outlets into stories.

Incremental TF-IDF clustering: each new article joins the most similar recent
story (cosine similarity against the story's centroid) or starts a new one.
Story ids stay stable across refreshes, so AI summaries are kept.
"""
import math
import re
from collections import Counter, defaultdict

from .feeds import good_image
from .util import iso, now_utc, parse_iso
import datetime as dt

STOP = set("""
a about above after again against all also am an and any are aren't as at be because been before being below
between both but by can cannot could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just let me more most my myself no nor
not of off on once only or other ought our ours ourselves out over own same she should so some such than that the
their theirs them themselves then there these they this those through to too under until up very was we were what
when where which while who whom why will with would you your yours yourself yourselves new news says say said
report reports reported according amid after over just could would may might will can get got gets make makes made
one two three first last year years week weeks day days today yesterday tomorrow time times now latest live update
updates breaking video watch photos inside here's what's how's who's it's he's she's they're we're don't doesn't
didn't won't can't isn't aren't wasn't weren't hasn't haven't via per told tells back still even like many much
mr mrs ms dr people man woman men women off amid against despite set sets take takes taking took big top
de het een en van in op te dat die is zijn was voor met als aan er om ook maar niet bij nog wel uit dan door
naar over tot wat hij zij ze we wij je jij ik u hun haar hem dit deze kan moet zal zou worden wordt werd heeft
hebben had nu al meer na toch geen jaar jaren dag week vandaag gisteren nieuw nieuwe eerste live video foto
le la les un une des du et en au aux est sont pour par sur dans avec qui que ne pas plus ses son sa leur
leurs ce cette ces il elle ils elles nous vous on été être avoir fait a ont après avant selon an ans jour
semaine aujourd hier nouveau nouvelle direct vidéo photos
""".split())

_TOKEN = re.compile(r"[a-z0-9à-ÿ][a-z0-9à-ÿ'’\-]*")


def tokens(text):
    out = []
    for w in _TOKEN.findall((text or "").lower().replace("’", "'")):
        w = w.strip("'-")
        if len(w) > 2 and w[1] == "'" and w[0] in "ldjnmcst":  # French elisions: l'état -> état
            w = w[2:]
        if w.endswith("'s"):
            w = w[:-2]
        if w in STOP or (len(w) < 3 and not w.isdigit()):
            continue
        if "-" in w:  # also index the parts of compounds: regering-de -> regering
            out.extend(p for p in w.split("-") if len(p) >= 3 and p not in STOP)
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]
        out.append(w)
    return out


def features(title, desc):
    t = tokens(title)
    d = tokens((desc or "")[:400])
    f = Counter()
    for w in t:
        f[w] += 2.0
    for a, b in zip(t, t[1:]):
        f[a + "_" + b] += 1.5
    for w in d:
        f[w] += 1.0
    return f


class Vectorizer:
    def __init__(self, feature_list):
        self.n = len(feature_list)
        df = Counter()
        for f in feature_list:
            df.update(f.keys())
        self.df = df

    def idf(self, term):
        return math.log((self.n + 1) / (self.df.get(term, 0) + 1)) + 1.0

    def vec(self, feats):
        v = {}
        for k, tf in feats.items():
            df = self.df.get(k, 0)
            if df > max(8, self.n * 0.12):  # ubiquitous terms carry no signal
                continue
            v[k] = (1.0 + math.log(tf)) * self.idf(k)
        n = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {k: x / n for k, x in v.items()}


def _dot(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(k, 0.0) for k, x in a.items())


def _top_terms(v, n=12):
    return [k for k, _ in sorted(v.items(), key=lambda kv: -kv[1])[:n]]


class _Centroid:
    __slots__ = ("sum", "norm", "members")

    def __init__(self):
        self.sum, self.norm, self.members = defaultdict(float), 0.0, []

    def add(self, v, aid):
        for k, x in v.items():
            self.sum[k] += x
        self.norm = math.sqrt(sum(x * x for x in self.sum.values())) or 1.0
        self.members.append(aid)

    def sim(self, v):
        return _dot(v, self.sum) / self.norm


TOPICS = [
    ("Sports", "voetbal wielrennen koers rode duivels cyclisme nfl nba mlb nhl soccer football basketball baseball tennis golf olympic coach quarterback league championship playoff season match tournament fifa premier goal touchdown"),
    ("Business", "economie économie bedrijf bedrijven entreprise beurs bourse banque begroting budget belasting impôt staking grève stock market economy inflation fed interest rate earnings shares investor bank tariff trade company ceo profit revenue gdp jobs unemployment price oil dollar"),
    ("Technology", "technologie tech ai artificial intelligence openai google apple microsoft meta amazon chip software app cyber hacker data privacy startup robot nvidia tesla musk"),
    ("Science", "nasa space scientist study research species climate planet asteroid moon mars telescope fossil physics"),
    ("Health", "gezondheid santé ziekenhuis hôpital zorg soins ziek malade health covid vaccine virus disease hospital drug fda cdc cancer patient medical outbreak measles doctor"),
    ("Climate & Environment", "klimaat climat storm tempête overstroming inondation climate weather hurricane storm flood wildfire heat earthquake emissions carbon environment tornado drought"),
    ("Crime & Justice", "politie police rechtbank tribunal procès moord meurtre gearresteerd arrêté parket parquet justitie justice police shooting arrest charged court judge trial murder lawsuit sentenced prison suspect killed fbi indictment"),
    ("Entertainment", "movie film actor actress singer music album celebrity hollywood netflix oscar grammy tv show star"),
    ("World", "oekraïne rusland russie israël gaza chine china verenigde ukraine russia israel gaza china iran europe eu nato un war minister president syria india korea africa putin zelensky"),
    ("Politics", "regering gouvernement minister ministre premier kamer chambre verkiezingen élections partij parti n-va vlaams vooruit ps mr cd&v open groen ecolo federale fédéral arizona trump biden harris congress senate house republican democrat election vote campaign white governor supreme bill law legislation gop policy administration"),
]
_TOPIC_SETS = [(name, set(words.split())) for name, words in TOPICS]


def guess_topic(texts):
    toks = Counter()
    for t in texts:
        toks.update(set(tokens(t)))
    best, score = "Other", 0
    for name, words in _TOPIC_SETS:
        s = sum(toks[w] for w in words)
        if s > score:
            best, score = name, s
    return best


def assign_stories(db, sources, threshold=0.3, window_hours=72):
    """Assign every unclustered article to a story. Returns the set of touched story ids."""
    since = iso(now_utc() - dt.timedelta(hours=window_hours))
    rows = db.q("SELECT id, source_id, title, description, image, published, story_id FROM articles "
                "WHERE published >= ? ORDER BY published", (since,))
    if not rows:
        return set()
    feats = {r["id"]: features(r["title"], r["description"]) for r in rows}
    vz = Vectorizer(list(feats.values()))
    vecs = {aid: vz.vec(f) for aid, f in feats.items()}
    by_id = {r["id"]: r for r in rows}

    cents, index = {}, defaultdict(set)
    for r in rows:
        if r["story_id"] is not None:
            c = cents.setdefault(r["story_id"], _Centroid())
            c.add(vecs[r["id"]], r["id"])
    for sid, c in cents.items():
        for t in _top_terms(c.sum, 25):
            index[t].add(sid)

    touched = set()
    new_rows = [r for r in rows if r["story_id"] is None]
    updates = []
    for r in new_rows:
        v = vecs[r["id"]]
        if not v:
            continue
        cand = set()
        for t in _top_terms(v, 10):
            cand |= index.get(t, set())
        best, best_sim = None, 0.0
        for sid in cand:
            s = cents[sid].sim(v)
            if s > best_sim:
                best, best_sim = sid, s
        if best is not None and best_sim >= threshold:
            sid = best
        else:
            cur = db.x("INSERT INTO stories (first_seen, last_article_at) VALUES (?, ?)",
                       (r["published"], r["published"]))
            sid = cur.lastrowid
            cents[sid] = _Centroid()
        cents[sid].add(v, r["id"])
        for t in _top_terms(v, 10):
            index[t].add(sid)
        updates.append((sid, r["id"]))
        touched.add(sid)
    db.many("UPDATE articles SET story_id = ? WHERE id = ?", updates)

    # merge pass: early seeds of the same event can grow into separate stories
    merge_th = max(threshold - 0.05, 0.2)
    merged_any = True
    while merged_any:
        merged_any = False
        norm = {sid: {k: x / c.norm for k, x in c.sum.items()} for sid, c in cents.items()}
        idx = defaultdict(set)
        for sid, v in norm.items():
            for t in _top_terms(v, 15):
                idx[t].add(sid)
        order = sorted(cents, key=lambda s: -len(cents[s].members))
        gone = set()
        for sid in order:
            if sid in gone:
                continue
            cand = set()
            for t in _top_terms(norm[sid], 15):
                cand |= idx[t]
            for other in cand:
                if other == sid or other in gone or (sid not in touched and other not in touched):
                    continue
                if len(cents[other].members) > len(cents[sid].members):
                    continue
                if _dot(norm[sid], norm[other]) >= merge_th:
                    keep, drop = (sid, other)
                    if db.one("SELECT ai FROM stories WHERE id = ? AND ai IS NOT NULL", (drop,)) and \
                            not db.one("SELECT ai FROM stories WHERE id = ? AND ai IS NOT NULL", (keep,)):
                        keep, drop = drop, keep
                    for aid in cents[drop].members:
                        cents[keep].add(vecs[aid], aid)
                    db.x("UPDATE articles SET story_id = ? WHERE story_id = ?", (keep, drop))
                    db.x("DELETE FROM stories WHERE id = ?", (drop,))
                    del cents[drop]
                    gone.add(drop)
                    touched.discard(drop)
                    touched.add(keep)
                    merged_any = True
                    if keep != sid:
                        break
        # loop again until stable (cheap: only a few hundred stories)

    # refresh story metadata (representative headline, image, topic, times)
    for sid in touched:
        c = cents[sid]
        members = [by_id[a] for a in c.members]

        def rank(a):
            src = sources.get(a["source_id"], {})
            bonus = 0.05 if src.get("side") == "center" else 0.0
            return c.sim(vecs[a["id"]]) + bonus

        rep = max(members, key=rank)
        image = next((m["image"] for m in [rep] + sorted(members, key=rank, reverse=True) if good_image(m["image"])), None)
        last = max(m["published"] for m in members)
        first = min(m["published"] for m in members)
        topic = guess_topic([m["title"] + " " + (m["description"] or "") for m in members])
        db.x("UPDATE stories SET headline = ?, image = ?, last_article_at = ?, first_seen = MIN(COALESCE(first_seen, ?), ?), "
             "topic = CASE WHEN ai IS NULL THEN ? ELSE topic END WHERE id = ?",
             (rep["title"], image, last, first, first, topic, sid))
    return touched


def representative_order(db, story_id):
    """Articles in a story, most central first (used to pick prompt material)."""
    rows = db.q("SELECT * FROM articles WHERE story_id = ? ORDER BY published", (story_id,))
    if len(rows) < 2:
        return rows
    feats = [features(r["title"], r["description"]) for r in rows]
    vz = Vectorizer(feats)
    vecs = [vz.vec(f) for f in feats]
    c = _Centroid()
    for i, v in enumerate(vecs):
        c.add(v, i)
    order = sorted(range(len(rows)), key=lambda i: -c.sim(vecs[i]))
    return [rows[i] for i in order]


def merge_stories(db, ids):
    """Merge several stories into one (keeps the one with a summary, else the biggest)."""
    ids = list(dict.fromkeys(int(i) for i in ids))
    if len(ids) < 2:
        return None
    marks = ",".join("?" * len(ids))
    rows = db.q("SELECT s.id, s.ai IS NOT NULL AS has_ai, COUNT(a.id) AS n FROM stories s "
                "LEFT JOIN articles a ON a.story_id = s.id WHERE s.id IN (%s) GROUP BY s.id" % marks, ids)
    if len(rows) < 2:
        return None
    keep = max(rows, key=lambda r: (r["has_ai"], r["n"]))["id"]
    drops = [r["id"] for r in rows if r["id"] != keep]
    dm = ",".join("?" * len(drops))
    db.x("UPDATE articles SET story_id = ? WHERE story_id IN (%s)" % dm, [keep] + drops)
    db.x("DELETE FROM stories WHERE id IN (%s)" % dm, drops)
    db.x("UPDATE stories SET last_article_at = (SELECT MAX(published) FROM articles WHERE story_id = ?), "
         "first_seen = (SELECT MIN(published) FROM articles WHERE story_id = ?) WHERE id = ?", (keep, keep, keep))
    return keep
