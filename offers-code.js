/*
 * offers-core.js
 * Shared front-end helpers for index.html and dashboard.html.
 *
 * The important part is computeStatus(). It is a direct port of
 * offer_status.py, and it runs in the browser against the offer's raw
 * start_date / end_date rather than reading a stored countdown.
 *
 * That matters because data/offers.json is regenerated once a day. If the
 * GitHub Action is delayed or skipped, a stored "2 days left" quietly
 * becomes wrong, and an offer that finished overnight keeps advertising
 * itself as live. Deriving from the dates means the page is right whenever
 * someone happens to open it.
 *
 * Keep this in sync with offer_status.py — same thresholds, same labels.
 */
(function (global) {
  "use strict";

  var ENDING_SOON_DAYS = 3;

  var STATUS_LABELS = {
    upcoming: "ჯერ არ დაწყებულა",
    active: "აქტიური",
    ending_soon: "მალე იწურება",
    ended: "დასრულებული",
    evergreen: "მუდმივი"
  };

  var LIVE_STATUSES = ["active", "ending_soon", "evergreen"];

  function parseDate(value) {
    if (!value) return null;
    var text = String(value).slice(0, 10);
    var parts = text.split("-");
    if (parts.length !== 3) return null;
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    return isNaN(d.getTime()) ? null : d;
  }

  function todayUTC() {
    var now = new Date();
    return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  }

  function dayDiff(a, b) {
    return Math.round((a - b) / 86400000);
  }

  function computeStatus(offer, today) {
    today = today || todayUTC();
    var start = parseDate(offer.start_date);
    var end = parseDate(offer.end_date);

    var daysLeft = end ? dayDiff(end, today) : null;
    var daysUntilStart = start ? dayDiff(start, today) : null;
    var duration = (start && end && end >= start) ? dayDiff(end, start) + 1 : null;

    var status;
    if (end && daysLeft < 0) status = "ended";
    else if (start && daysUntilStart > 0) status = "upcoming";
    else if (end === null) status = "evergreen";
    else if (daysLeft <= ENDING_SOON_DAYS) status = "ending_soon";
    else status = "active";

    return {
      status: status,
      status_label: STATUS_LABELS[status],
      is_live: LIVE_STATUSES.indexOf(status) !== -1,
      days_left: daysLeft,
      days_until_start: daysUntilStart,
      duration_days: duration
    };
  }

  /* Georgian countdown text. TBC's own site counts the final day as 1. */
  function daysLeftLabel(state) {
    if (state.status === "ended") return "დასრულებული";
    if (state.status === "upcoming") {
      return state.days_until_start === 1
        ? "იწყება ხვალ"
        : "იწყება " + state.days_until_start + " დღეში";
    }
    if (state.days_left === null) return "ვადის გარეშე";
    if (state.days_left === 0) return "ბოლო დღე";
    return "დარჩა " + state.days_left + " დღე";
  }

  /*
   * Detects data written by the pre-status scraper.
   *
   * Old records have no `end_date` key at all. computeStatus() sees an
   * absent end date and calls the offer "evergreen", which is the right
   * answer for a genuine standing offer but the wrong one for a whole
   * file that simply predates the field. The visible symptom is every
   * offer landing in აქტიური with 0 in ending_soon / upcoming / ended.
   *
   * Rather than mislabel silently, say so.
   */
  function detectSchema(offers) {
    if (!offers.length) return "empty";
    var withDateField = offers.filter(function (o) {
      return Object.prototype.hasOwnProperty.call(o, "end_date");
    }).length;
    if (withDateField === 0) return "legacy";
    if (withDateField < offers.length * 0.5) return "partial";
    return "current";
  }

  var SCHEMA_WARNINGS = {
    legacy:
      "მონაცემები ძველი სქემითაა (არ აქვს end_date). ყველა შეთავაზება " +
      "„მუდმივად“ ითვლება, ამიტომ „მალე იწურება“, „ჯერ არ დაწყებულა“ და " +
      "„დასრულებული“ ცარიელია. გაუშვი <code>python migrate_state.py</code> " +
      "და დაპუშე <code>data/offers.json</code>.",
    partial:
      "შეთავაზებების ნაწილს end_date აკლია — სტატუსები არასრულია. " +
      "შემდეგი სკრეიპი გაასწორებს."
  };

  /*
   * Every offer, with a freshly computed status merged in. The stored
   * status fields from the Python side are deliberately overwritten:
   * whichever is newer, the browser's clock wins.
   */
  function withStatus(offers, today) {
    today = today || todayUTC();
    return offers.map(function (offer) {
      var merged = {};
      for (var key in offer) merged[key] = offer[key];
      var state = computeStatus(offer, today);
      for (var k in state) merged[k] = state[k];
      merged.days_left_label = daysLeftLabel(state);
      return merged;
    });
  }

  function live(offers) {
    return offers.filter(function (o) { return o.is_live; });
  }

  /* Merchant partnerships only — TBC's own product promos excluded. */
  function merchantsOnly(offers) {
    return offers.filter(function (o) { return !o.bank_product; });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }

  function truncate(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function mean(values) {
    if (!values.length) return 0;
    return values.reduce(function (a, b) { return a + b; }, 0) / values.length;
  }

  function median(values) {
    if (!values.length) return 0;
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  /* --- data loading ----------------------------------------------------
   * Try the local copy first so the page works when opened straight from
   * a clone, then fall back to raw.githubusercontent so it also works from
   * a file:// URL or any other host.
   */
  var REPO_RAW = "https://raw.githubusercontent.com/jinchara/Offers_Bot/main/";

  function fetchFirst(paths, fallback) {
    var attempt = function (index) {
      if (index >= paths.length) {
        if (!fallback) return Promise.reject(new Error("ვერ ჩაიტვირთა მონაცემები"));
        return fetch(fallback, { cache: "no-store" }).then(function (res) {
          if (!res.ok) throw new Error("ვერ ჩაიტვირთა მონაცემები");
          return res.text();
        });
      }
      return fetch(paths[index], { cache: "no-store" })
        .then(function (res) { return res.ok ? res.text() : attempt(index + 1); })
        .catch(function () { return attempt(index + 1); });
    };
    return attempt(0);
  }

  function parseJsonl(text) {
    return text.split("\n").filter(Boolean).map(function (line) {
      try { return JSON.parse(line); } catch (e) { return null; }
    }).filter(Boolean);
  }

  /*
   * Resolves to { offers, history, insights }.
   * insights is optional — the pages recompute anything they need from
   * `offers`, so a missing insights.json degrades rather than breaks.
   */
  /* Renders the stale-schema banner above `container`, if needed. */
  function renderSchemaWarning(container, data) {
    if (!data.schemaWarning || !container) return;
    var banner = document.createElement("div");
    banner.className = "schema-banner";
    banner.innerHTML = "⚠️ " + data.schemaWarning;
    container.insertBefore(banner, container.firstChild);
  }

  function loadAll() {
    return Promise.all([
      fetchFirst(["./data/offers.json", "data/offers.json"], REPO_RAW + "data/offers.json"),
      fetchFirst(["./data/history.jsonl", "data/history.jsonl"], REPO_RAW + "data/history.jsonl")
        .catch(function () { return ""; }),
      fetchFirst(["./data/insights.json", "data/insights.json"], REPO_RAW + "data/insights.json")
        .catch(function () { return ""; })
    ]).then(function (results) {
      var offersObj = JSON.parse(results[0]);
      var offers = withStatus(Object.keys(offersObj).map(function (k) { return offersObj[k]; }));
      var insights = null;
      try { insights = results[2] ? JSON.parse(results[2]) : null; } catch (e) { insights = null; }
      var rawList = Object.keys(offersObj).map(function (k) { return offersObj[k]; });
      return {
        offers: offers,
        history: results[1] ? parseJsonl(results[1]) : [],
        insights: insights,
        schema: detectSchema(rawList),
        schemaWarning: SCHEMA_WARNINGS[detectSchema(rawList)] || null
      };
    });
  }

  global.OffersCore = {
    ENDING_SOON_DAYS: ENDING_SOON_DAYS,
    STATUS_LABELS: STATUS_LABELS,
    computeStatus: computeStatus,
    daysLeftLabel: daysLeftLabel,
    withStatus: withStatus,
    live: live,
    merchantsOnly: merchantsOnly,
    escapeHtml: escapeHtml,
    truncate: truncate,
    mean: mean,
    median: median,
    loadAll: loadAll,
    detectSchema: detectSchema,
    renderSchemaWarning: renderSchemaWarning,
    parseDate: parseDate,
    todayUTC: todayUTC
  };
})(window);
