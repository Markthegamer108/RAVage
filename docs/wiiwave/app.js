// WiiWave status site. Plain fetch() against the public league JSON API (same origin in
// production, where the reverse proxy forwards /league/ to the league WSGI app).
// No build step, no framework. API_BASE can be overridden for local testing:
//   <script>window.WIIWAVE_API_BASE = "http://127.0.0.1:8090"</script>
(function () {
  "use strict";

  var API_BASE = window.WIIWAVE_API_BASE || "";
  var PAGE_SIZE = 25;
  var state = { tab: "week", offset: 0, week: null, online: false };

  // ---------------------------------------------------------------- helpers
  function api(path) {
    return fetch(API_BASE + path, { headers: { "Accept": "application/json" } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        return { ok: r.ok, status: r.status, body: body };
      });
    });
  }

  function el(id) { return document.getElementById(id); }

  function fmtDate(ts) {
    try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return String(ts); }
  }

  function fmtCountdown(endTs) {
    var s = Math.max(0, Math.floor(endTs - Date.now() / 1000));
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d > 0) return d + "d " + h + "h left";
    if (h > 0) return h + "h " + m + "m left";
    return m + "m left";
  }

  function setStatus(online) {
    state.online = online;
    var pill = el("status-pill");
    pill.className = "status-pill " + (online ? "ok" : "bad");
    el("status-text").textContent = online ? "server online" : "server unreachable";
  }

  function setCard(id, value, sub) {
    var card = el(id);
    card.querySelector("[data-value]").textContent = value;
    card.querySelector("[data-sub]").textContent = sub;
  }

  // ---------------------------------------------------------------- week / hero
  function loadWeek() {
    return api("/league/week").then(function (res) {
      if (!res.ok) { setStatus(false); el("hero-meta").textContent = "could not reach the server API"; return; }
      setStatus(true);
      var w = res.body.week || {};
      state.week = w;
      el("hero-meta").textContent =
        "week " + w.week + " of championship " + (w.championship + 1) + " \u00b7 updated " + fmtDate(res.body.now) +
        (w.end ? " \u00b7 " + fmtCountdown(w.end) : "");
      setCard("card-week", "Week " + w.week, "ends " + (w.end ? fmtDate(w.end) : "\u2014"));
      setCard("card-season", cap(w.stage_name || "?"), "season " + (w.season != null ? w.season : "?") +
        (w.week_in_stage != null ? " \u00b7 week " + w.week_in_stage + " in stage" : ""));
      setCard("card-event", w.event_name || "#" + (w.event != null ? w.event : "?"),
        w.start && w.end ? fmtDate(w.start) + " \u2192 " + fmtDate(w.end) : "this week");
      setCard("card-stage", "Stage " + ((w.stage != null ? w.stage : 0) + 1) + " / " + (res.body.championship_weeks ? "championship " + (w.championship + 1) : ""),
        w.stage_name ? cap(w.stage_name) + " stage" : "");
      el("updated").textContent = "last refresh " + new Date().toLocaleTimeString();
    }).catch(function () {
      setStatus(false);
      el("hero-meta").textContent = "could not reach the server API";
    });
  }

  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  // ---------------------------------------------------------------- standings
  function standingsPath() {
    if (state.tab === "week") return "/league/standings/week?limit=" + PAGE_SIZE + "&offset=" + state.offset;
    if (state.tab === "stage") return "/league/standings/stage?limit=" + PAGE_SIZE + "&offset=" + state.offset;
    return "/league/standings/championship?limit=" + PAGE_SIZE + "&offset=" + state.offset;
  }

  function loadStandings() {
    var note = el("standings-note");
    note.textContent = "Loading\u2026";
    return api(standingsPath()).then(function (res) {
      if (!res.ok) {
        note.textContent = "Standings are unavailable right now (HTTP " + res.status + ").";
        renderRows([]);
        return;
      }
      var b = res.body;
      var rows = b.verified || [];
      var prov = (b.provisional || []).length;
      var label;
      if (state.tab === "week") label = "Week " + (b.week ? b.week.week : "?") + " \u00b7 verified races";
      else if (state.tab === "stage") label = cap(b.stage_name || "stage") + " stage \u00b7 championship " + (b.championship + 1) + " \u00b7 season " + b.season;
      else label = "Championship " + (b.championship + 1) + " \u00b7 verified races";
      note.textContent = label + (prov ? " \u00b7 " + prov + " provisional row(s) not shown" : "");
      renderRows(rows);
      el("page-info").textContent = rows.length
        ? "showing " + (state.offset + 1) + "\u2013" + (state.offset + rows.length)
        : "no ranked races yet";
      el("prev-page").disabled = state.offset === 0;
      el("next-page").disabled = rows.length < PAGE_SIZE;
    }).catch(function () {
      note.textContent = "Could not reach the server API.";
      renderRows([]);
    });
  }

  function renderRows(rows) {
    var body = el("standings-body");
    body.innerHTML = "";
    if (!rows.length) {
      var tr = document.createElement("tr");
      tr.className = "empty-row";
      var td = document.createElement("td");
      td.colSpan = 4;
      td.textContent = "No ranked races yet \u2014 be the first on the board.";
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      [r.rank, r.player, r.score, r.races].forEach(function (v, i) {
        var td = document.createElement("td");
        if (i === 0) td.className = "rank";
        if (i === 2) td.className = "score";
        td.textContent = v;
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
  }

  // ---------------------------------------------------------------- player lookup
  function lookupPlayer(code) {
    var box = el("player-result");
    box.classList.remove("hidden");
    box.innerHTML = "<p class='panel-note'>Searching\u2026</p>";
    var digits = code.replace(/[^0-9]/g, "");
    if (digits.length !== 12) {
      box.innerHTML = "<p class='player-error'>Enter the full 12-digit friend code.</p>";
      return;
    }
    api("/league/player/" + encodeURIComponent(code.replace(/\s+/g, ""))).then(function (res) {
      if (!res.ok) {
        box.innerHTML = "<p class='player-error'>No player found for that friend code (or the API is down: HTTP " +
          res.status + ").</p>";
        return;
      }
      var b = res.body;
      var card = document.createElement("div");
      card.className = "player-card";
      var h = document.createElement("h3");
      h.textContent = "Friend code " + digits.replace(/(\d{4})(\d{4})(\d{4})/, "$1-$2-$3");
      card.appendChild(h);
      var dl = document.createElement("dl");
      [["Week (verified)", b.week_verified], ["Week (provisional)", b.week_provisional],
       ["Stage (verified)", b.stage_verified], ["Stage (provisional)", b.stage_provisional],
       ["Championship (verified)", b.championship_verified], ["Championship (provisional)", b.championship_provisional]
      ].forEach(function (pair) {
        var dt = document.createElement("dt");
        dt.textContent = pair[0];
        var dd = document.createElement("dd");
        var v = pair[1];
        dd.textContent = v ? ("#" + v.rank + " \u00b7 " + v.score + " pts \u00b7 " + v.races + " races") : "not ranked";
        dl.appendChild(dt); dl.appendChild(dd);
      });
      card.appendChild(dl);
      box.innerHTML = "";
      box.appendChild(card);
    }).catch(function () {
      box.innerHTML = "<p class='player-error'>Could not reach the server API.</p>";
    });
  }

  // ---------------------------------------------------------------- wiring
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.tab = btn.getAttribute("data-tab");
      state.offset = 0;
      loadStandings();
    });
  });
  el("refresh-standings").addEventListener("click", loadStandings);
  el("prev-page").addEventListener("click", function () {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    loadStandings();
  });
  el("next-page").addEventListener("click", function () {
    state.offset += PAGE_SIZE;
    loadStandings();
  });
  el("player-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    lookupPlayer(el("player-code").value.trim());
  });

  function refreshAll() {
    loadWeek().then(loadStandings);
  }

  refreshAll();
  setInterval(refreshAll, 60000);
})();
