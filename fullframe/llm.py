"""AI providers.

- gemini:      Google's Gemini API (free tier works). Used for the public website,
               because it runs on a normal developer API key.
- claude-code: the Claude Code CLI logged in with your own Claude subscription.
               Only for running Fullframe on your own computer, for yourself:
               Anthropic's terms don't allow a subscription to power a public service.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import ai
from .feeds import _CTX


class QuotaExhausted(RuntimeError):
    """Daily quota / usage limit hit: stop making requests this run."""


class Provider:
    name = "none"
    model = None

    def complete(self, prompt):  # -> text
        raise NotImplementedError

    def describe(self):
        return {"provider": self.name, "model": self.model}


# ------------------------------------------------------------------ Gemini

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class Gemini(Provider):
    name = "gemini"

    def __init__(self, api_key, model="gemini-flash-lite-latest", min_interval=7.0, timeout=120):
        self.key = api_key
        self.model = model
        self.min_interval = float(min_interval)
        self.timeout = timeout
        self._last = 0.0
        self._model_checked = False

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(GEMINI_BASE + path, data=data, method=method, headers={
            "Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=self.timeout, context=_CTX) as r:
            return json.loads(r.read().decode("utf-8"))

    def _pick_model(self):
        """If the configured model doesn't exist, pick the newest stable Flash-Lite / Flash model."""
        try:
            res = self._req("GET", "/models?pageSize=200")
        except Exception:  # noqa: BLE001
            return None
        names = []
        for m in res.get("models", []):
            n = m.get("name", "").split("/")[-1]
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if re.search(r"preview|exp|tts|image|live|audio|embedding|thinking|computer", n):
                continue
            if "flash" in n:
                names.append(n)

        def rank(n):
            ver = [int(x) for x in re.findall(r"\d+", n)[:2]] or [0]
            return (1 if "lite" in n else 0, ver)

        names.sort(key=rank, reverse=True)
        return names[0] if names else None

    def complete(self, prompt, _retries=2):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            res = self._req("POST", "/models/%s:generateContent" % self.model, body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:800]
            if e.code == 404 and not self._model_checked:
                self._model_checked = True
                alt = self._pick_model()
                if alt and alt != self.model:
                    print("[ai] Gemini model '%s' not found, using '%s'" % (self.model, alt), flush=True)
                    self.model = alt
                    return self.complete(prompt, _retries)
            if e.code == 429:
                if re.search(r"per ?day|PerDay|daily", detail, re.I):
                    raise QuotaExhausted("Gemini free-tier daily limit reached; summaries resume tomorrow.")
                if _retries > 0:
                    time.sleep(40)
                    return self.complete(prompt, _retries - 1)
                raise QuotaExhausted("Gemini rate limit hit repeatedly; trying again next run.")
            if e.code in (500, 502, 503, 504) and _retries > 0:
                time.sleep(15)
                return self.complete(prompt, _retries - 1)
            if e.code in (400, 401, 403) and re.search(r"API key|API_KEY|permission", detail, re.I):
                raise QuotaExhausted("Gemini rejected the API key (%s). Check the GEMINI_API_KEY secret." % e.code)
            raise RuntimeError("Gemini HTTP %s: %s" % (e.code, detail[:300]))
        cands = res.get("candidates") or []
        if not cands:
            raise RuntimeError("Gemini returned no answer (%s)" % str(res.get("promptFeedback", ""))[:200])
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise RuntimeError("Gemini returned an empty answer (finish: %s)" % cands[0].get("finishReason"))
        return text


# ------------------------------------------------------------------ Claude Code

class ClaudeCode(Provider):
    name = "claude-code"

    def __init__(self, path, model="haiku", timeout=240):
        self.path, self.model, self.timeout = path, model, timeout
        self.version = None

    def complete(self, prompt):
        try:
            return ai.run_claude(self.path, prompt, self.model, self.timeout)
        except RuntimeError as e:
            msg = str(e)
            if "usage limit" in msg.lower() or "authenticate" in msg.lower():
                raise QuotaExhausted(msg)
            raise

    def describe(self):
        d = super().describe()
        d["path"] = self.path
        return d


# ------------------------------------------------------------------ choose

def make_provider(cfg):
    acfg = cfg["ai"]
    if not acfg.get("enabled", True):
        return None
    choice = (os.environ.get("FULLFRAME_AI") or acfg.get("provider") or "auto").lower()
    gkey = os.environ.get("GEMINI_API_KEY") or acfg.get("gemini_api_key") or ""
    if choice in ("auto", "gemini") and gkey:
        return Gemini(gkey, acfg.get("gemini_model") or "gemini-flash-lite-latest",
                      acfg.get("min_seconds_between_requests", 7))
    if choice in ("auto", "claude-code"):
        path = ai.find_claude(acfg.get("claude_path", ""))
        if path:
            return ClaudeCode(path, acfg.get("claude_model") or acfg.get("model") or "haiku",
                              acfg.get("timeout_seconds", 240))
    return None
