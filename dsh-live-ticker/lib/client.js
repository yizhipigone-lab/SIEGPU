window.__ModuleLoader__.load({
  id: "dsh-live-ticker",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
    var __create = Object.create;
    var __defProp = Object.defineProperty;
    var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
    var __getOwnPropNames = Object.getOwnPropertyNames;
    var __getProtoOf = Object.getPrototypeOf;
    var __hasOwnProp = Object.prototype.hasOwnProperty;
    var __export = (target, all) => {
      for (var name2 in all)
        __defProp(target, name2, { get: all[name2], enumerable: true });
    };
    var __copyProps = (to, from, except, desc) => {
      if (from && typeof from === "object" || typeof from === "function") {
        for (let key of __getOwnPropNames(from))
          if (!__hasOwnProp.call(to, key) && key !== except)
            __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
      }
      return to;
    };
    var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
      // If the importer is in node compatibility mode or this is not an ESM
      // file that has been converted to a CommonJS file using a Babel-
      // compatible transform (i.e. "__esModule" has not been set), then set
      // "default" to the CommonJS "module.exports" for node compatibility.
      isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
      mod
    ));
    var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);
    
    // src/client/index.tsx
    var index_exports = {};
    __export(index_exports, {
      apply: () => apply,
      inject: () => inject,
      name: () => name
    });
    module.exports = __toCommonJS(index_exports);
    var import_react2 = __toESM(require("react"), 1);
    
    // src/client/TickerBar.tsx
    var import_react = require("react");
    
    // src/quotes.ts
    var INDEX_SECIDS = ["1.000001", "0.399006", "1.000688", "1.000510"];
    var QUOTES_URL = `https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=${INDEX_SECIDS.join(",")}&fields=f2,f3,f12,f14`;
    function toNumber(v) {
      if (typeof v === "number" && Number.isFinite(v)) return v;
      if (typeof v === "string") {
        const n = Number(v.replace(/,/g, ""));
        return Number.isFinite(n) ? n : null;
      }
      return null;
    }
    function parsePush2Quotes(json) {
      const diff = json?.data?.diff;
      if (!Array.isArray(diff)) return [];
      const quotes = [];
      for (const row of diff) {
        const r = row;
        if (typeof r.f14 !== "string" || !r.f14.trim()) continue;
        const price = toNumber(r.f2);
        const changePct = toNumber(r.f3);
        if (price === null || changePct === null) continue;
        quotes.push({ name: r.f14.trim(), price, changePct });
      }
      return quotes;
    }
    
    // src/client/fetch.ts
    async function fetchQuotes(signal) {
      try {
        const res = await fetch(QUOTES_URL, { signal });
        if (!res.ok) return { quotes: [], fetchedAt: Date.now(), ok: false };
        return { quotes: parsePush2Quotes(await res.json()), fetchedAt: Date.now(), ok: true };
      } catch {
        return { quotes: [], fetchedAt: Date.now(), ok: false };
      }
    }
    async function fetchNews(signal) {
      try {
        const res = await fetch("/live-ticker/news", { signal });
        if (!res.ok) return { snapshot: null, ok: false, error: `HTTP ${res.status}` };
        const body = await res.json();
        if (!body.ok) return { snapshot: null, ok: false, error: body.error };
        return {
          snapshot: { items: body.items, fetchedAt: body.fetchedAt, stale: body.stale },
          ok: true
        };
      } catch (e) {
        return { snapshot: null, ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
    
    // src/client/TickerBar.tsx
    var import_jsx_runtime = require("react/jsx-runtime");
    var QUOTE_POLL_MS = 5e3;
    var NEWS_POLL_MS = 6e4;
    function TickerBar() {
      const [quotes, setQuotes] = (0, import_react.useState)([]);
      const [quotesAt, setQuotesAt] = (0, import_react.useState)(null);
      const [quotesOk, setQuotesOk] = (0, import_react.useState)(true);
      const [news, setNews] = (0, import_react.useState)([]);
      const [newsStale, setNewsStale] = (0, import_react.useState)(false);
      const [newsAt, setNewsAt] = (0, import_react.useState)(null);
      const [newsErr, setNewsErr] = (0, import_react.useState)("");
      const pausedRef = (0, import_react.useRef)(false);
      (0, import_react.useEffect)(() => {
        let alive = true;
        let quoteTimer = 0;
        let newsTimer = 0;
        const onVisibility = () => {
          pausedRef.current = document.hidden;
          if (!document.hidden) {
            refreshQuotes();
            refreshNews();
          }
        };
        async function refreshQuotes() {
          if (pausedRef.current || !alive) return;
          const r = await fetchQuotes();
          if (!alive) return;
          setQuotes(r.quotes);
          setQuotesAt(r.fetchedAt);
          setQuotesOk(r.ok);
          scheduleQuotes();
        }
        async function refreshNews() {
          if (pausedRef.current || !alive) return;
          const r = await fetchNews();
          if (!alive) return;
          if (r.snapshot) {
            setNews(r.snapshot.items);
            setNewsStale(r.snapshot.stale);
            setNewsAt(r.snapshot.fetchedAt);
            setNewsErr("");
          }
          if (!r.ok && r.error) setNewsErr(r.error);
          scheduleNews();
        }
        function scheduleQuotes() {
          if (!alive) return;
          quoteTimer = window.setTimeout(refreshQuotes, QUOTE_POLL_MS);
        }
        function scheduleNews() {
          if (!alive) return;
          newsTimer = window.setTimeout(refreshNews, NEWS_POLL_MS);
        }
        refreshQuotes();
        refreshNews();
        document.addEventListener("visibilitychange", onVisibility);
        return () => {
          alive = false;
          clearTimeout(quoteTimer);
          clearTimeout(newsTimer);
          document.removeEventListener("visibilitychange", onVisibility);
        };
      }, []);
      const fmtTime = (t) => t ? new Date(t).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "";
      return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [
        /* @__PURE__ */ (0, import_jsx_runtime.jsx)("style", { children: `
            .lt-ticker-inner { animation: lt-ticker-scroll 40s linear infinite; }
            .lt-ticker-scroll:hover .lt-ticker-inner { animation-play-state: paused; }
            @keyframes lt-ticker-scroll {
              0% { transform: translateX(0); }
              100% { transform: translateX(-50%); }
            }
          ` }),
        /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { className: "lt-ticker", style: styles.root, children: [
          /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("details", { open: true, children: [
            /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("summary", { style: styles.summary, children: [
              /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.summaryTitle, children: "\u884C\u60C5" }),
              /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { style: styles.meta, children: [
                quotesAt ? `\u66F4\u65B0\u4E8E ${fmtTime(quotesAt)}` : "\u52A0\u8F7D\u4E2D\u2026",
                !quotesOk && quotes.length > 0 ? "\uFF08\u8FDE\u63A5\u4E2D\u65AD\uFF0C\u663E\u793A\u4E0A\u6B21\u6570\u636E\uFF09" : ""
              ] })
            ] }),
            /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.quoteGrid, children: [
              quotes.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.empty, children: "\u6682\u65E0\u884C\u60C5\u6570\u636E" }),
              quotes.map((q) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.quoteCell, children: [
                /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.quoteName, children: q.name }),
                /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.quotePrice, children: q.price.toFixed(2) }),
                /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { style: changeStyle(q.changePct), children: [
                  q.changePct > 0 ? "\u25B2" : q.changePct < 0 ? "\u25BC" : "\u2014",
                  " ",
                  q.changePct > 0 ? "+" : "",
                  q.changePct.toFixed(2),
                  "%"
                ] })
              ] }, q.name))
            ] })
          ] }),
          /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("details", { open: true, children: [
            /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("summary", { style: styles.summary, children: [
              /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.summaryTitle, children: "\u8D22\u7ECF\u5FEB\u8BAF" }),
              /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { style: styles.meta, children: [
                newsAt ? `\u66F4\u65B0\u4E8E ${fmtTime(newsAt)}` : "\u52A0\u8F7D\u4E2D\u2026",
                newsStale || newsErr ? `\uFF08${newsErr || "\u66F4\u65B0\u5931\u8D25\uFF0C\u663E\u793A\u4E0A\u6B21\u6570\u636E"}\uFF09` : ""
              ] })
            ] }),
            /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", { style: styles.tickerWrap, className: "lt-ticker-scroll", children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.tickerInner, className: "lt-ticker-inner", children: [
              news.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.empty, children: "\u6682\u65E0\u65B0\u95FB" }),
              [...news, ...news].map((n, i) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("a", { href: n.url, target: "_blank", rel: "noreferrer", title: n.title, style: styles.tickerItem, children: [
                /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.tickerTime, children: n.showTime.slice(11) }),
                /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: n.title })
              ] }, `${n.url}-${i}`))
            ] }) })
          ] })
        ] })
      ] });
    }
    function changeStyle(pct) {
      if (pct > 0) return { ...styles.quotePct, color: "#ef4444" };
      if (pct < 0) return { ...styles.quotePct, color: "#22c55e" };
      return { ...styles.quotePct, color: "#9ca3af" };
    }
    var styles = {
      root: { fontSize: 13, color: "var(--dsw-alias-label-primary, #e5e7eb)" },
      summary: { display: "flex", alignItems: "center", gap: 8, cursor: "pointer", padding: "4px 0", userSelect: "none" },
      summaryTitle: { fontWeight: 600 },
      meta: { fontSize: 11, color: "var(--dsw-alias-label-secondary, #9ca3af)" },
      quoteGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 6, paddingBottom: 6 },
      quoteCell: { display: "flex", alignItems: "baseline", gap: 8, padding: "4px 8px", borderRadius: 6, background: "var(--dsw-alias-bg-elevated, rgba(128,128,128,.08))" },
      quoteName: { color: "var(--dsw-alias-label-secondary, #9ca3af)" },
      quotePrice: { fontWeight: 700, fontVariantNumeric: "tabular-nums" },
      quotePct: { fontSize: 12, fontWeight: 600, fontVariantNumeric: "tabular-nums" },
      tickerWrap: { overflow: "hidden", paddingBottom: 4 },
      tickerInner: { display: "flex", gap: 20, whiteSpace: "nowrap" },
      tickerItem: { display: "inline-flex", gap: 6, alignItems: "baseline", color: "var(--dsw-alias-label-primary, #e5e7eb)", textDecoration: "none", fontSize: 12 },
      tickerTime: { color: "var(--dsw-alias-label-secondary, #9ca3af)", fontVariantNumeric: "tabular-nums" },
      empty: { color: "var(--dsw-alias-label-secondary, #9ca3af)" }
    };
    
    // src/client/index.tsx
    var name = "dsh-live-ticker";
    var inject = ["slots"];
    function apply(ctx) {
      ctx.slots.inject(
        "conversation.composer.dock",
        () => ctx.slots.register({
          name: "conversation.composer.dock",
          id: "live-ticker",
          order: 100,
          label: () => "live-ticker"
        }, () => import_react2.default.createElement(TickerBar))
      );
    }
    
    return module.exports;
  }
});
