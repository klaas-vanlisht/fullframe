"""Fetching and parsing RSS / Atom / RDF feeds (stdlib only)."""
import email.utils
import datetime as dt
import gzip
import html
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser

from .util import clean_text, now_utc

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def _ssl_context():
    try:
        import certifi  # optional, helps on macOS python.org installs
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_CTX = _ssl_context()


def http_get(url, timeout=15, max_bytes=6_000_000, accept=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": accept or "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        data = r.read(max_bytes)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            data = gzip.decompress(data)
        elif enc == "deflate":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
        return data, r.headers.get_content_charset(), r.geturl()


# ---------------------------------------------------------------- dates

def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d is not None:
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        t = s.replace("Z", "+00:00")
        if re.match(r".*[+-]\d{4}$", t):
            t = t[:-2] + ":" + t[-2:]
        d = dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------- URLs

_TRACKING = re.compile(r"^(utm_|cmp|mbid|ncid|ito|smid|taid|at_|ref$|src$|traffic_source|dicbo|fbclid|gclid|cid$|mc_)", re.I)


def canonical_url(u):
    try:
        p = urllib.parse.urlsplit(u.strip())
        qs = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
        return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urllib.parse.urlencode(qs), ""))
    except Exception:
        return u.strip()


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


_JUNK_IMG = re.compile(r"(?<![a-z])(?:pixel|tracking|1x1|spacer|blank|logo|icon|avatar|placeholder|gravatar|emoji|"
                       r"feedburner|doubleclick|badge|sprite)s?(?![a-z])|default[-_]image|/ads?/", re.I)


def good_image(url):
    """True for a real photo URL (skips tracking pixels, logos, icons)."""
    if not url or not url.startswith("http") or len(url) > 2000:
        return False
    return not _JUNK_IMG.search(url.split("?")[0] + " " + (url.split("?")[1][:200] if "?" in url else ""))


_IMG_IN_HTML = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def _item_from_elem(el):
    d = {"title": "", "link": "", "description": "", "content": "", "date": None, "image": None, "gn_source": None}
    for c in el:
        name = _local(c.tag)
        text = (c.text or "").strip()
        if name == "title":
            d["title"] = text or "".join(c.itertext()).strip()
        elif name == "link":
            href = c.get("href")
            rel = c.get("rel", "alternate")
            if href and rel == "alternate":
                d["link"] = d["link"] or href
            elif text:
                d["link"] = d["link"] or text
        elif name == "guid" and not d["link"] and text.startswith("http") and c.get("isPermaLink", "true") != "false":
            d["link"] = text
        elif name in ("description", "summary"):
            d["description"] = d["description"] or text or "".join(c.itertext())
        elif name in ("encoded", "content"):
            d["content"] = d["content"] or text or "".join(c.itertext())
        elif name in ("pubdate", "published", "updated", "date", "issued"):
            if d["date"] is None:
                d["date"] = parse_date(text)
        if name in ("content", "thumbnail", "enclosure") and not d["image"]:
            url = c.get("url")
            if not good_image(url):
                url = None
            typ = (c.get("type") or "").lower()
            medium = (c.get("medium") or "").lower()
            if url and (name == "thumbnail" or medium == "image" or typ.startswith("image")
                        or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I)):
                d["image"] = url
        if name == "group" and not d["image"]:  # media:group > media:content
            for g in c:
                if _local(g.tag) in ("content", "thumbnail") and good_image(g.get("url")):
                    d["image"] = g.get("url")
                    break
        if name == "source" and c.get("url"):
            d["gn_source"] = text
    if not d["image"]:
        for m in _IMG_IN_HTML.finditer((d["content"] or "") + " " + (d["description"] or "")):
            u = html.unescape(m.group(1))
            if good_image(u):
                d["image"] = u
                break
    return d


def _parse_xml(data):
    root = ET.fromstring(data)
    items = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    return [_item_from_elem(e) for e in items]


_ITEM_RE = re.compile(r"<(item|entry)\b[^>]*>(.*?)</\1>", re.S | re.I)


def _parse_regex(text):
    """Fallback for feeds with broken XML (bad entities etc.)."""
    out = []
    for m in _ITEM_RE.finditer(text):
        body = m.group(2)

        def grab(tag):
            mm = re.search(r"<(?:\w+:)?%s\b[^>]*>(.*?)</(?:\w+:)?%s>" % (tag, tag), body, re.S | re.I)
            if not mm:
                return ""
            v = mm.group(1).strip()
            v = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", v, flags=re.S)
            return v.strip()

        link = grab("link")
        if not link:
            mm = re.search(r"<link[^>]+href=[\"']([^\"']+)", body, re.I)
            link = mm.group(1) if mm else ""
        img = None
        mm = re.search(r"<(?:media:content|media:thumbnail|enclosure)[^>]+url=[\"']([^\"']+)", body, re.I)
        if mm:
            img = mm.group(1)
        desc = grab("description") or grab("summary")
        content = grab("encoded") or grab("content")
        if img and not good_image(img):
            img = None
        if not img:
            for mm in _IMG_IN_HTML.finditer((content or "") + " " + (desc or "")):
                if good_image(html.unescape(mm.group(1))):
                    img = html.unescape(mm.group(1))
                    break
        out.append({
            "title": grab("title"), "link": html.unescape(link), "description": desc, "content": content,
            "date": parse_date(grab("pubDate") or grab("published") or grab("updated") or grab("date")),
            "image": img, "gn_source": grab("source") or None,
        })
    return out


def parse_feed(data, charset=None):
    try:
        items = _parse_xml(data)
    except ET.ParseError:
        text = data.decode(charset or "utf-8", errors="replace")
        items = _parse_regex(text)
    res = []
    for it in items:
        title = clean_text(it["title"])
        link = (it["link"] or "").strip()
        if not title or not link.startswith("http"):
            continue
        desc = clean_text(it["description"] or it["content"], 600)
        if desc and desc.lower().startswith(title.lower()[:40]) and len(desc) < len(title) + 40:
            desc = ""  # description just repeats the headline
        res.append({
            "title": title, "url": link, "description": desc,
            "published": it["date"], "image": it["image"], "gn_source": it["gn_source"],
        })
    return res


# ---------------------------------------------------------------- sources

def google_news_url(domain, hours=24, lang="en", country="US"):
    q = urllib.parse.quote("site:%s when:%dh" % (domain, max(1, int(hours))))
    cc = {"UK": "GB", "EU": "BE"}.get((country or "US").upper(), (country or "US").upper())
    if lang == "en" and cc not in ("GB", "IE", "AU", "NZ", "CA", "IN", "ZA"):
        cc = "US"
    hl = "en-%s" % cc if lang == "en" else lang
    return "https://news.google.com/rss/search?q=%s&hl=%s&gl=%s&ceid=%s:%s" % (q, hl, cc, cc, lang)


def _strip_gn_suffix(title, name):
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if len(tail) <= 60:
            return head.strip()
    return title


def fetch_source(src, max_age_hours=48):
    """Return (items, status dict). Tries the outlet's own feeds, then Google News."""
    cutoff = now_utc() - dt.timedelta(hours=max_age_hours)
    items, errors, seen = [], [], set()
    for url in src.get("feeds", []):
        try:
            data, cs, _ = http_get(url)
            for it in parse_feed(data, cs):
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                items.append(it)
        except Exception as e:  # noqa: BLE001 - we report any failure
            errors.append("%s: %s" % (url.split("/")[2] if "//" in url else url, str(e)[:120]))
    fresh = [i for i in items if (i["published"] or now_utc()) >= cutoff]
    via = "feed"
    if not fresh and src.get("domain"):
        try:
            data, cs, _ = http_get(google_news_url(src["domain"], min(max_age_hours, 36), src.get("lang", "en"), src.get("country")))
            gn = parse_feed(data, cs)
            for it in gn:
                it["title"] = _strip_gn_suffix(it["title"], src["name"])
                it["description"] = ""  # GN descriptions are just the headline + outlet name
            fresh = [i for i in gn if (i["published"] or now_utc()) >= cutoff]
            via = "google-news"
        except Exception as e:  # noqa: BLE001
            errors.append("google news: %s" % str(e)[:120])
    status = "ok" if fresh else ("error" if errors else "empty")
    return fresh, {"status": status, "via": via if fresh else None, "count": len(fresh),
                   "error": "; ".join(errors)[:500] if errors else None}


# ---------------------------------------------------------------- article text

class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "figure", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras, self._buf, self._in_p, self._skip = [], [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "p":
            self._in_p += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "p" and self._in_p:
            self._in_p -= 1
            t = " ".join("".join(self._buf).split())
            if len(t) > 60:
                self.paras.append(t)
            self._buf = []

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


_OG_IMAGE = re.compile(r"<meta[^>]+(?:property|name)=[\"'](?:og:image|og:image:url|twitter:image)[\"'][^>]*>", re.I)
_CONTENT = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)


def find_og_image(html_text):
    for m in _OG_IMAGE.finditer(html_text[:300000]):
        c = _CONTENT.search(m.group(0))
        if c:
            u = html.unescape(c.group(1)).strip()
            if u.startswith("//"):
                u = "https:" + u
            if good_image(u):
                return u
    return None


def fetch_og_image(url):
    """The article's share image (og:image), or None. Reads only the top of the page."""
    if "news.google.com" in url:
        return None
    try:
        data, cs, _ = http_get(url, timeout=8, max_bytes=400_000, accept="text/html,*/*;q=0.8")
        return find_og_image(data.decode(cs or "utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def extract_article_text(url, limit=2500):
    if "news.google.com" in url:
        return ""
    try:
        data, cs, _ = http_get(url, timeout=10, max_bytes=3_000_000, accept="text/html,*/*;q=0.8")
        p = _TextExtractor()
        p.feed(data.decode(cs or "utf-8", errors="replace"))
        text = " ".join(p.paras)
        return text[:limit]
    except Exception:  # noqa: BLE001
        return ""
