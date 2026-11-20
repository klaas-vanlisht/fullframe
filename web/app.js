/* Fullframe front-end. Works as a static site (GitHub Pages) and with the local server.
   All data comes from data/*.json; filtering and sorting happen here in the browser. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app");
  const TOPICS = ["All", "Politics", "World", "Business", "Technology", "Science", "Health",
    "Climate & Environment", "Crime & Justice", "Sports", "Entertainment"];
  const sideLabel = { left: "Left", center: "Center", right: "Right", unrated: "Unrated" };

  let LOCAL = false;          // true when served by the local Python server (live status, refresh button)
  let status = null;          // data/status.json (+ live status in local mode)
  let live = null;            // /api/status in local mode
  let stories = null;         // data/stories.json -> stories
  let storiesStamp = null;

  // ---------------------------------------------------------------- helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
  const bust = () => "?v=" + Math.floor(Date.now() / 60000);
  async function getJSON(path) {
    const r = await fetch(path + bust(), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status === 404 ? "not found" : r.statusText);
    return r.json();
  }
  const hoursAgo = (iso) => (iso ? (Date.now() - new Date(iso).getTime()) / 3.6e6 : 1e9);
  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }
  function parseHash() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, qs] = h.split("?");
    return { parts: path.split("/").filter(Boolean), params: new URLSearchParams(qs || "") };
  }
  const countryName = (code) => ((status && status.countries) || []).find((c) => c.code === code)?.name || code;

  // ---------------------------------------------------------------- data
  async function loadStatus() {
    status = await getJSON("data/status.json").catch(() => null);
    if (status && status.site_title) document.title = status.site_title;
  }
  async function loadStories(force) {
    if (stories && !force) return stories;
    const d = await getJSON("data/stories.json");
    stories = d.stories || [];
    storiesStamp = d.generated;
    return stories;
  }
  const score = (s) => s.n_sources / (1 + hoursAgo(s.updated) / 6);

  function filterStories(list, params) {
    const country = params.get("country"), topic = params.get("topic");
    let out = list;
    if (country) out = out.filter((s) => (s.countries || []).includes(country));
    if (topic && topic !== "All") out = out.filter((s) => s.topic === topic);
    return out;
  }
  function topStories(list, params) {
    const country = params.get("country");
    const c = country && (status.countries || []).find((x) => x.code === country);
    const min = c && c.outlets < 8 ? 2 : (status.min_sources_top || 3);
    const recent = filterStories(list, params).filter((s) => hoursAgo(s.updated) <= 36 && s.coherent);
    let top = recent.filter((s) => s.n_sources >= min);
    if (top.length < 8) top = recent;
    return top.sort((a, b) => score(b) - score(a));
  }
  function latestStories(list, params) {
    return filterStories(list, params).slice().sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  }
  function gapStories(list, params) {
    const g = filterStories(list, params).filter((s) => s.bias.gap && s.coherent).sort((a, b) => score(b) - score(a));
    return { left: g.filter((s) => s.bias.gap === "left"), right: g.filter((s) => s.bias.gap === "right") };
  }
  function searchStories(list, q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return list.filter((s) => { const t = (s.headline + " " + (s.summary || "") + " " + s.titles).toLowerCase(); return words.every((w) => t.includes(w)); })
      .sort((a, b) => score(b) - score(a));
  }

  // ---------------------------------------------------------------- components
  function biasBar(b, size = "") {
    const { pct, counts } = b;
    const total = counts.left + counts.center + counts.right;
    if (!total) return `<div class="biasbar ${size}"><div style="flex:1;color:var(--ink-3)">No rated sources</div></div>`;
    const full = size === "big" ? 24 : 99;
    const seg = (cls, label, p) => (p > 0 ? `<div class="${cls}" style="flex:${p}" title="${label} ${p}%">${p >= full ? label + " " + p + "%" : p >= 12 ? label[0] + " " + p + "%" : ""}</div>` : "");
    return `<div class="biasbar ${size}">${seg("l", "Left", pct.left)}${seg("c", "Center", pct.center)}${seg("r", "Right", pct.right)}</div>`;
  }
  function gapBadge(b) {
    if (b.gap === "left") return `<span class="badge gap-left" title="Barely covered by left-leaning outlets">Left gap</span>`;
    if (b.gap === "right") return `<span class="badge gap-right" title="Barely covered by right-leaning outlets">Right gap</span>`;
    return "";
  }
  function card(s, lead = false) {
    const img = s.image ? `<div class="img"><img src="${safeUrl(s.image)}" alt="" loading="${lead ? "eager" : "lazy"}" referrerpolicy="no-referrer" onerror="imgFail(this)"></div>` : "";
    return `<a class="card${lead ? " lead" : ""}${img ? "" : " noimg"}" href="#/story/${s.id}">
      ${img}
      <div class="body">
        <div class="kicker">${esc(s.topic)} ${gapBadge(s.bias)}</div>
        <h3>${esc(s.headline)}</h3>
        ${s.summary ? `<p class="snip">${esc(s.summary)}</p>` : ""}
        <div class="meta">
          ${biasBar(s.bias, "small")}
          <div class="metaline"><span>${s.n_sources} sources</span><span>${ago(s.updated)}</span></div>
        </div>
      </div></a>`;
  }
  function mini(s) {
    return `<a class="mini${s.image ? "" : " noimg"}" href="#/story/${s.id}">${s.image ? `<img class="mini-img" src="${safeUrl(s.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="imgFail(this)">` : ""}<div class="kicker">${esc(s.topic)} · ${s.n_sources} sources</div>
      <h4>${esc(s.headline)}</h4>${biasBar(s.bias, "small")}</a>`;
  }
  function emptyState() {
    if (LOCAL && live && (live.running || !live.last_run)) {
      return `<div class="empty"><div class="spinner"></div><h2>Gathering the news…</h2>
        <p>Pulling feeds from every outlet${live.progress ? " (" + esc(live.progress) + ")" : ""}. The first run takes a minute or two.</p></div>`;
    }
    return `<div class="empty"><h2>Nothing here yet</h2><p>No stories match. Try another topic${LOCAL ? ", or hit Refresh" : " or check back after the next update"}.</p></div>`;
  }
  function link(base, params, key, value) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value); else p.delete(key);
    const qs = p.toString();
    return "#" + base + (qs ? "?" + qs : "");
  }
  function filterBar(params, base) {
    const topic = params.get("topic") || "All", country = params.get("country") || "";
    const countries = (status && status.countries) || [];
    const crow = $("#countries-row"), trow = $("#topics-row");
    crow.hidden = countries.length < 2;
    $("#countries").innerHTML = crow.hidden ? "" : [["", "All countries"], ...countries.map((c) => [c.code, c.name])].map(([v, label]) =>
      `<a href="${link(base, params, "country", v)}" class="${country === v ? "active" : ""}">${esc(label)}</a>`).join("");
    trow.hidden = false;
    $("#topics").innerHTML = TOPICS.map((t) =>
      `<a href="${link(base, params, "topic", t === "All" ? "" : t)}" class="${topic === t ? "active" : ""}">${esc(t)}</a>`).join("");
    document.querySelectorAll(".chips").forEach((row) => {  // keep the active chip in view
      const a = row.querySelector("a.active");
      if (a && (a.offsetLeft < row.scrollLeft || a.offsetLeft + a.offsetWidth > row.scrollLeft + row.clientWidth))
        row.scrollLeft = a.offsetLeft - 40;
      updateArrows(row);
    });
  }
  function clearFilters() {
    $("#countries-row").hidden = true; $("#topics-row").hidden = true;
  }
  function updateArrows(row) {
    const wrap = row.parentElement;
    wrap.classList.toggle("can-left", row.scrollLeft > 4);
    wrap.classList.toggle("can-right", row.scrollLeft + row.clientWidth < row.scrollWidth - 4);
  }
  function setupChipRows() {
    document.querySelectorAll(".chips").forEach((row) => {
      row.addEventListener("scroll", () => updateArrows(row), { passive: true });
      // a normal (vertical) mouse wheel scrolls the row sideways
      row.addEventListener("wheel", (e) => {
        if (row.scrollWidth <= row.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
        e.preventDefault();
        row.scrollBy({ left: e.deltaY, behavior: "auto" });
      }, { passive: false });
      // click-and-drag with the mouse
      let down = false, startX = 0, startLeft = 0, moved = false;
      row.addEventListener("pointerdown", (e) => {
        if (e.pointerType !== "mouse" || e.button !== 0) return;
        down = true; moved = false; startX = e.clientX; startLeft = row.scrollLeft;
      });
      window.addEventListener("pointermove", (e) => {
        if (!down) return;
        const dx = e.clientX - startX;
        if (Math.abs(dx) > 5) { moved = true; row.classList.add("dragging"); }
        if (moved) row.scrollLeft = startLeft - dx;
      });
      window.addEventListener("pointerup", () => { down = false; setTimeout(() => row.classList.remove("dragging"), 0); });
      row.addEventListener("click", (e) => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);
      const wrap = row.parentElement;
      wrap.querySelector(".chip-arrow.left").addEventListener("click", () => row.scrollBy({ left: -row.clientWidth * 0.7 }));
      wrap.querySelector(".chip-arrow.right").addEventListener("click", () => row.scrollBy({ left: row.clientWidth * 0.7 }));
    });
    window.addEventListener("resize", () => document.querySelectorAll(".chips").forEach(updateArrows));
  }
  window.imgFail = (img) => {  // publisher blocked the picture: fall back to the text-only layout
    const box = img.closest(".img");
    const cardEl = img.closest(".card, .mini");
    if (box) box.remove(); else img.remove();
    if (cardEl) cardEl.classList.add("noimg");
  };
  function setTab(view) {
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  }
  const scopeName = (params) => (params.get("country") ? " · " + esc(countryName(params.get("country"))) : "") +
    (params.get("topic") ? " · " + esc(params.get("topic")) : "");

  // ---------------------------------------------------------------- views
  async function viewTop(params, view) {
    const base = view === "latest" ? "/latest" : "/";
    setTab(view); filterBar(params, base);
    const all = await loadStories();
    const list = view === "latest" ? latestStories(all, params) : topStories(all, params);
    if (!list.length) { app.innerHTML = emptyState(); return; }
    const title = view === "latest" ? "Latest" : "Top Stories";
    const sub = view === "latest" ? "Newest stories covered by at least two outlets" : "Ranked by how many outlets are covering them right now";
    let main;
    if (view === "top") main = card(list[0], true) + `<div class="grid">${list.slice(1, 60).map((s) => card(s)).join("")}</div>`;
    else main = `<div class="grid">${list.slice(0, 80).map((s) => card(s)).join("")}</div>`;
    let aside = "";
    if (view === "top") {
      const g = gapStories(all, params);
      aside = `<aside>
        <section><h2 class="section-title">Underreported on the left</h2><p class="aside-note">Covered mostly by right-leaning outlets</p>
          ${g.left.length ? g.left.slice(0, 4).map(mini).join("") : `<p class="aside-note">None right now.</p>`}</section>
        <section><h2 class="section-title">Underreported on the right</h2><p class="aside-note">Covered mostly by left-leaning outlets</p>
          ${g.right.length ? g.right.slice(0, 4).map(mini).join("") : `<p class="aside-note">None right now.</p>`}</section>
        <p class="aside-note"><a href="${link("/gaps", params, "x", "")}">See all coverage gaps →</a></p>
      </aside>`;
    }
    app.innerHTML = `<div class="page-head"><h1>${title}${scopeName(params)}</h1><span class="sub">${sub}</span></div>
      ${aside ? `<div class="home"><div>${main}</div>${aside}</div>` : main}`;
  }

  async function viewGaps(params) {
    setTab("gaps"); filterBar(params, "/gaps");
    const g = gapStories(await loadStories(), params);
    const col = (list) => (list.length ? `<div class="grid">${list.map((s) => card(s)).join("")}</div>` : `<p class="aside-note">None right now.</p>`);
    app.innerHTML = `<div class="page-head"><h1>Coverage Gaps${scopeName(params)}</h1><span class="sub">Stories one side of the spectrum is barely covering</span></div>
      <div class="gap-cols">
        <div class="col-left"><h2>Underreported on the left</h2><p class="explain">Covered heavily by right-leaning outlets, barely by left-leaning ones. Coverage is compared as a share of each side's outlets, so a side having more outlets in the list doesn't skew it.</p>${col(g.left)}</div>
        <div class="col-right"><h2>Underreported on the right</h2><p class="explain">Covered heavily by left-leaning outlets, barely by right-leaning ones.</p>${col(g.right)}</div>
      </div>`;
  }

  async function viewSearch(params) {
    const q = params.get("q") || "";
    setTab(""); clearFilters();
    $("#search").value = q;
    const list = searchStories(await loadStories(), q);
    app.innerHTML = `<div class="page-head"><h1>Search: “${esc(q)}”</h1><span class="sub">${list.length} stories</span></div>
      ${list.length ? `<div class="grid">${list.slice(0, 80).map((s) => card(s)).join("")}</div>` : `<div class="empty"><h2>No matches</h2><p>Try fewer or different words.</p></div>`}`;
  }

  async function viewStory(id) {
    setTab(""); clearFilters();
    let s;
    try { s = await getJSON("data/story/" + encodeURIComponent(id) + ".json"); }
    catch { app.innerHTML = `<div class="empty"><h2>Story not found</h2><p>It may have been merged into another story or aged out. <a href="#/">Back to top stories</a></p></div>`; return; }
    const b = s.bias, c = b.counts, ai = s.ai;
    const canRegen = LOCAL && live && live.ai && live.ai.available;
    let aiHtml;
    if (ai) {
      const frame = (side) => `<div class="frame ${side}"><h3>${sideLabel[side]}</h3>${ai.framing[side] ? esc(ai.framing[side]) : `<span class="none">No ${side}-leaning coverage in the sample.</span>`}</div>`;
      const aiName = status && status.ai && status.ai.provider === "gemini" ? "Gemini" : "Claude";
      aiHtml = `
        ${!ai.same_story ? `<div class="notice" style="margin-bottom:16px">Heads up: the AI thinks these reports may describe more than one event, so this grouping may be imperfect.</div>` : ""}
        <div class="panel"><h2>Summary</h2><p class="summary-text">${esc(ai.summary)}</p>
          ${ai.key_points.length ? `<ul class="keypoints">${ai.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>` : ""}</div>
        <div class="panel"><h2>How each side covered it</h2><div class="framing">${frame("left")}${frame("center")}${frame("right")}</div>
          ${ai.differences ? `<p style="margin-top:14px"><strong>Where they differ:</strong> ${esc(ai.differences)}</p>` : ""}</div>
        ${ai.disputed.length ? `<div class="panel"><h2>Contested or one-sided claims</h2><ul class="keypoints">${ai.disputed.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>` : ""}
        ${ai.loaded_language.length ? `<div class="panel"><h2>Loaded language</h2><div class="loaded">${ai.loaded_language.map((l) =>
          `<span><b>“${esc(l.phrase)}”</b> <em>— ${esc(l.source || "")}${l.why ? ": " + esc(l.why) : ""}</em></span>`).join("")}</div></div>` : ""}
        <div class="ai-foot"><span>AI-written by ${aiName} ${ago(s.ai_at)} from ${s.n_sources} outlets' reports. It can make mistakes, so check the reports below.</span>
          ${canRegen ? `<button class="btn-ghost" id="resum">Regenerate</button>` : ""}</div>`;
    } else {
      const minAi = (status && status.min_sources_ai) || 3;
      const why = s.ai_error ? `<div class="notice err">The AI summary failed: ${esc(s.ai_error)}</div>`
        : `<div class="notice">No AI summary yet. Stories get one once ${minAi} or more outlets cover them; it'll appear after a later update.</div>`;
      const desc = s.articles.find((a) => a.description);
      aiHtml = `<div class="panel"><h2>Summary</h2>${why}
        ${desc ? `<p class="summary-text" style="margin-top:12px">${esc(desc.description)}</p>` : ""}
        ${canRegen ? `<div class="ai-foot"><span></span><button class="btn-ghost" id="resum">Summarize now</button></div>` : ""}</div>`;
    }

    const counts = { all: s.articles.length, left: 0, center: 0, right: 0 };
    s.articles.forEach((a) => { if (counts[a.side] !== undefined) counts[a.side]++; });
    const srcChips = (side) => [...new Set(s.articles.filter((a) => a.side === side).map((a) => a.source))]
      .map((n) => `<span class="srcchip"><span class="dot ${side}"></span>${esc(n)}</span>`).join("");

    app.innerHTML = `
      <a class="back" href="javascript:history.back()">← Back</a>
      <div class="story">
        <div>
          <div class="kicker">${esc(s.topic)} · first seen ${ago(s.first_seen)} · updated ${ago(s.updated)} ${gapBadge(b)}</div>
          <h1>${esc(s.headline)}</h1>
          ${s.has_ai && s.original_headline !== s.headline ? `<div class="orig">Neutral headline written by AI. Most representative original: “${esc(s.original_headline)}”</div>` : ""}
          ${s.image ? `<img class="hero" src="${safeUrl(s.image)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
          ${aiHtml}
          <div class="panel" id="articles"><h2>${s.n_articles} reports from ${s.n_sources} outlets</h2>
            <div class="filter">${["all", "left", "center", "right"].map((k) =>
              `<button data-f="${k}" class="${k === "all" ? "active" : ""}">${k === "all" ? "All" : sideLabel[k]} · ${counts[k]}</button>`).join("")}</div>
            <div id="artlist"></div>
          </div>
        </div>
        <aside>
          <div class="panel">
            <h2>Coverage</h2>
            ${biasBar(b, "big")}
            <div class="stat-list">
              <span class="k">Total outlets</span><strong>${s.n_sources}</strong>
              <span class="k"><span class="dot left"></span>Leaning left</span><strong>${c.left}</strong>
              <span class="k"><span class="dot center"></span>Center</span><strong>${c.center}</strong>
              <span class="k"><span class="dot right"></span>Leaning right</span><strong>${c.right}</strong>
              ${c.unrated ? `<span class="k"><span class="dot unrated"></span>Unrated</span><strong>${c.unrated}</strong>` : ""}
            </div>
            ${b.gap ? `<div class="gap-box ${b.gap}"><strong>Coverage gap:</strong> barely covered by ${b.gap}-leaning outlets
              (${Math.round(b.coverage_rate[b.gap] * 100)}% of them vs ${Math.round(b.coverage_rate[b.gap === "left" ? "right" : "left"] * 100)}% on the other side).</div>` : ""}
          </div>
          <div class="panel">
            <h2>Source reliability</h2>
            <div class="stat-list">
              <span class="k"><span class="dot" style="background:var(--good)"></span>High factuality</span><strong>${b.factuality.high}</strong>
              <span class="k"><span class="dot" style="background:var(--warn)"></span>Mixed / mostly factual</span><strong>${b.factuality.mixed}</strong>
              <span class="k"><span class="dot" style="background:var(--bad)"></span>Low factuality</span><strong>${b.factuality.low}</strong>
            </div>
          </div>
          <div class="panel"><h2>Who's covering it</h2>
            ${c.left ? `<div class="kicker" style="margin-top:6px">Left</div><div class="srcchips">${srcChips("left")}</div>` : ""}
            ${c.center ? `<div class="kicker" style="margin-top:12px">Center</div><div class="srcchips">${srcChips("center")}</div>` : ""}
            ${c.right ? `<div class="kicker" style="margin-top:12px">Right</div><div class="srcchips">${srcChips("right")}</div>` : ""}
          </div>
        </aside>
      </div>`;

    const renderList = (f) => {
      const list = s.articles.filter((a) => f === "all" || a.side === f);
      $("#artlist").innerHTML = list.map((a) => `
        <div class="art${a.image ? "" : " noimg"}"><a href="${safeUrl(a.url)}" target="_blank" rel="noopener noreferrer">
          <div class="src"><strong>${esc(a.source)}</strong>${a.lang && a.lang !== "en" ? `<span class="lang">${esc(a.lang.toUpperCase())}</span>` : ""}<span class="lean-tag ${a.side}">${esc(a.lean.replace("-", " "))}</span>
            <span class="fact ${esc(a.factuality)}">${esc(a.factuality.replace("-", " "))}</span><span>${ago(a.published)}</span></div>
          <h4>${esc(a.title)}</h4>${a.description ? `<p>${esc(a.description)}</p>` : ""}</a>
          ${a.image ? `<img class="thumb" src="${safeUrl(a.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : ""}
        </div>`).join("") || `<p class="aside-note">No reports from this side.</p>`;
    };
    renderList("all");
    document.querySelectorAll(".filter button").forEach((btn) => btn.addEventListener("click", () => {
      document.querySelectorAll(".filter button").forEach((x) => x.classList.toggle("active", x === btn));
      renderList(btn.dataset.f);
    }));
    const rb = $("#resum");
    if (rb) rb.addEventListener("click", async () => {
      rb.disabled = true; rb.textContent = "Working… (takes ~30s)";
      await fetch(`api/story/${s.id}/resummarize`, { method: "POST" });
      const before = s.ai_at;
      const poll = setInterval(async () => {
        const d = await getJSON("data/story/" + s.id + ".json").catch(() => null);
        if (d && d.ai_at !== before) { clearInterval(poll); if (parseHash().parts[1] == s.id) viewStory(s.id); }
      }, 4000);
      setTimeout(() => clearInterval(poll), 300000);
    });
  }

  async function viewSources() {
    setTab("sources"); clearFilters();
    const list = await getJSON("data/sources.json");
    const n = { left: 0, center: 0, right: 0 };
    list.forEach((s) => { if (n[s.side] !== undefined) n[s.side]++; });
    let lastCountry = null;
    const rows = list.map((s) => (s.country !== lastCountry ? (lastCountry = s.country,
      `<tr class="region-row"><td colspan="5">${esc(s.country_name || s.country)}</td></tr>`) : "") + `<tr>
      <td><strong>${esc(s.name)}</strong><br><span class="aside-note">${esc(s.domain || "")} · ${esc((s.lang || "en").toUpperCase())}</span></td>
      <td><span class="lean-tag ${s.side}">${esc((s.lean || "unrated").replace("-", " "))}</span></td>
      <td><span class="fact ${esc(s.factuality)}">${esc((s.factuality || "unrated").replace("-", " "))}</span></td>
      <td><span class="st ${esc(s.status)}" title="${esc(s.error || "")}">${s.status === "ok" ? (s.via === "google-news" ? "OK via Google News" : "OK") : esc(s.status)}</span>
        ${s.error && s.status !== "ok" ? `<br><span class="aside-note">${esc(s.error.slice(0, 90))}</span>` : ""}</td>
      <td style="text-align:right">${s.articles_24h}</td></tr>`).join("");
    const every = status ? status.refresh_minutes : 30;
    const aiName = status && status.ai && status.ai.available ? (status.ai.provider === "gemini" ? "Google's Gemini" : "Claude") : "an AI model";
    app.innerHTML = `<div class="page-head"><h1>Sources &amp; ratings</h1><span class="sub">${list.length} outlets · ${n.left} left · ${n.center} center · ${n.right} right</span></div>
      <div class="prose">
        <p><strong>How it works.</strong> About every ${every} minutes, Fullframe reads the RSS feeds of the outlets below and groups reports about the same event into one story.
        It then shows which parts of the political spectrum are covering it. Stories covered by several outlets get a neutral summary and a side-by-side comparison of the framing, written by ${aiName}.
        Fullframe shows headlines and links; click through to read the reporting on each outlet's own site.</p>
        <p><strong>About the ratings.</strong> Lean and factuality labels are an approximate consensus of public media-rating projects. They're judgment calls, not facts.
        Coverage gaps compare the share of each side's outlets that covered a story, so a side having more outlets in this list doesn't skew them.</p>
        <div class="spectrum"><div style="flex:${n.left}"></div><div style="flex:${n.center}"></div><div style="flex:${n.right}"></div></div>
      </div>
      <table class="src"><thead><tr><th>Outlet</th><th>Lean</th><th>Factuality</th><th>Feed status</th><th style="text-align:right">Articles (24h)</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---------------------------------------------------------------- router
  async function route() {
    const { parts, params } = parseHash();
    if (parts[0] !== "search") $("#search").value = "";
    try {
      if (parts[0] === "story" && parts[1]) await viewStory(parts[1]);
      else if (parts[0] === "latest") await viewTop(params, "latest");
      else if (parts[0] === "gaps") await viewGaps(params);
      else if (parts[0] === "sources") await viewSources();
      else if (parts[0] === "search") await viewSearch(params);
      else await viewTop(params, "top");
    } catch (e) {
      app.innerHTML = LOCAL && live && !live.last_run ? emptyState()
        : `<div class="empty"><h2>Couldn't load the news</h2><p>${esc(e.message)}</p><p class="aside-note">${LOCAL ? "Is the Fullframe server still running?" : "Try reloading in a minute."}</p></div>`;
    }
  }
  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#search").value.trim();
    location.hash = q ? "#/search?q=" + encodeURIComponent(q) : "#/";
  });

  // ---------------------------------------------------------------- status
  function showStatic() {
    const dot = $("#status-dot"), txt = $("#status-text");
    dot.className = "status-dot ok";
    txt.textContent = status ? "Updated " + ago(status.generated) : "";
  }
  async function pollLive() {
    try {
      const r = await fetch("api/status", { cache: "no-store" });
      live = await r.json();
    } catch {
      $("#status-dot").className = "status-dot err";
      $("#status-text").textContent = "Server offline";
      return setTimeout(pollLive, 8000);
    }
    const dot = $("#status-dot"), txt = $("#status-text"), btn = $("#refresh-btn");
    btn.disabled = live.running;
    if (live.running) {
      dot.className = "status-dot busy";
      txt.textContent = live.stage[0].toUpperCase() + live.stage.slice(1) + (live.progress ? " · " + live.progress : "") + "…";
      const sp = app.querySelector(".empty p");
      if (sp && !app.querySelector(".card")) sp.textContent = "Pulling feeds from every outlet (" + (live.progress || live.stage) + "). The first run takes a minute or two.";
    } else {
      dot.className = "status-dot " + (live.last_error ? "err" : "ok");
      const aiNote = live.ai.available ? (live.ai.last_error ? " · AI paused" : "") : " · AI off";
      txt.textContent = (live.last_run ? "Updated " + ago(live.last_run) : "Not updated yet") + aiNote;
      txt.title = live.last_error || live.ai.last_error || "";
    }
    // new data exported? reload it (never interrupt a story page)
    const st = await getJSON("data/status.json").catch(() => null);
    if (st && st.generated !== (status && status.generated)) {
      status = st;
      await loadStories(true).catch(() => null);
      if (parseHash().parts[0] !== "story") route();
    }
    setTimeout(pollLive, live.running ? 2500 : 20000);
  }

  async function init() {
    setupChipRows();
    await loadStatus();
    if (status && status.mode === "local") {
      try { live = await (await fetch("api/status", { cache: "no-store" })).json(); LOCAL = true; } catch { /* server gone */ }
    }
    if (LOCAL) {
      $("#refresh-btn").hidden = false;
      $("#refresh-btn").addEventListener("click", async () => { await fetch("api/refresh", { method: "POST" }); setTimeout(pollLive, 500); });
      await route();
      pollLive();
    } else {
      showStatic();
      await route();
      setInterval(async () => {  // pick up new builds without a manual reload
        const st = await getJSON("data/status.json").catch(() => null);
        if (st && status && st.generated !== status.generated) {
          status = st; await loadStories(true).catch(() => null); showStatic();
          if (parseHash().parts[0] !== "story") route();
        } else showStatic();
      }, 5 * 60 * 1000);
    }
  }
  init();
})();
