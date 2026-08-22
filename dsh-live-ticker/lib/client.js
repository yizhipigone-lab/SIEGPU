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
    
    // src/client/fetch.ts
    async function fetchQuotes(signal) {
      try {
        const res = await fetch("/live-ticker/quotes", { signal });
        if (!res.ok) return { quotes: [], fetchedAt: Date.now(), ok: false };
        const body = await res.json();
        if (!body.ok) return { quotes: body.quotes ?? [], fetchedAt: Date.now(), ok: false };
        return { quotes: body.quotes, fetchedAt: body.fetchedAt ?? Date.now(), ok: true };
      } catch {
        return { quotes: [], fetchedAt: Date.now(), ok: false };
      }
    }
    async function fetchNews(signal) {
      try {
        const res = await fetch("/live-ticker/news", { signal });
        if (!res.ok) return { snapshot: null, ok: false, error: `HTTP ${res.status}` };
        const body = await res.json();
        if (!body.ok) {
          return {
            snapshot: Array.isArray(body.items) && body.items.length > 0 ? { items: body.items, fetchedAt: body.fetchedAt ?? 0, stale: true } : null,
            ok: false,
            error: body.error
          };
        }
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
    var NEWS_BAR_H = 26;
    function QuotesBar() {
      const [quotes, setQuotes] = (0, import_react.useState)([]);
      const [quotesOk, setQuotesOk] = (0, import_react.useState)(true);
      (0, import_react.useEffect)(() => {
        let alive = true;
        let timer = 0;
        const pausedRef = { current: false };
        const onVisibility = () => {
          pausedRef.current = document.hidden;
          if (!document.hidden) void refresh();
        };
        async function refresh() {
          if (pausedRef.current || !alive) return;
          const r = await fetchQuotes();
          if (!alive) return;
          if (r.quotes.length > 0) setQuotes(r.quotes);
          setQuotesOk(r.ok);
          timer = window.setTimeout(refresh, QUOTE_POLL_MS);
        }
        void refresh();
        document.addEventListener("visibilitychange", onVisibility);
        return () => {
          alive = false;
          clearTimeout(timer);
          document.removeEventListener("visibilitychange", onVisibility);
        };
      }, []);
      return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.quotesRoot, title: quotesOk ? "" : "\u8FDE\u63A5\u4E2D\u65AD\uFF0C\u663E\u793A\u4E0A\u6B21\u6570\u636E", children: [
        quotes.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.empty, children: "\u6682\u65E0\u884C\u60C5\u6570\u636E" }),
        quotes.map((q) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.quoteChip, children: [
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
      ] });
    }
    function NewsBar() {
      const [news, setNews] = (0, import_react.useState)([]);
      (0, import_react.useEffect)(() => {
        let alive = true;
        let timer = 0;
        const pausedRef = { current: false };
        const onVisibility = () => {
          pausedRef.current = document.hidden;
          if (!document.hidden) void refresh();
        };
        async function refresh() {
          if (pausedRef.current || !alive) return;
          const r = await fetchNews();
          if (!alive) return;
          const items = r.snapshot?.items;
          if (Array.isArray(items) && items.length > 0) {
            setNews(items);
          }
          timer = window.setTimeout(refresh, NEWS_POLL_MS);
        }
        void refresh();
        document.addEventListener("visibilitychange", onVisibility);
        return () => {
          alive = false;
          clearTimeout(timer);
          document.removeEventListener("visibilitychange", onVisibility);
        };
      }, []);
      return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.newsRoot, className: "lt-news-root", children: [
        /* @__PURE__ */ (0, import_jsx_runtime.jsx)("style", { children: `
            .lt-ticker-inner { animation: lt-ticker-scroll 100s linear infinite; }
            .lt-news-root:hover .lt-ticker-inner { animation-play-state: paused; }
            @keyframes lt-ticker-scroll {
              0% { transform: translateX(0); }
              100% { transform: translateX(-50%); }
            }
          ` }),
        /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { style: styles.tickerInner, className: "lt-ticker-inner", children: [
          news.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.empty, children: "\u6682\u65E0\u65B0\u95FB" }),
          [...news, ...news].map((n, i) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("a", { href: n.url, target: "_blank", rel: "noreferrer", title: n.title, style: styles.tickerItem, children: [
            /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { style: styles.tickerTime, children: typeof n.showTime === "string" ? n.showTime.slice(11) : "" }),
            /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: n.title })
          ] }, `${n.url}-${i}`))
        ] })
      ] });
    }
    function changeStyle(pct) {
      if (pct > 0) return { ...styles.quotePct, color: "var(--dsh-up, #ef4444)" };
      if (pct < 0) return { ...styles.quotePct, color: "var(--dsh-down, #22c55e)" };
      return { ...styles.quotePct, color: "var(--dsw-alias-label-secondary, #9ca3af)" };
    }
    var styles = {
      // 指数条：正常文档流（槽位本身在卡片下方），内容水平居中。
      quotesRoot: {
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexWrap: "nowrap",
        columnGap: 22,
        overflow: "hidden",
        whiteSpace: "nowrap",
        fontSize: 13,
        padding: "2px 0",
        color: "var(--dsw-alias-label-primary, #e5e7eb)"
      },
      quoteChip: { display: "inline-flex", alignItems: "baseline", gap: 6, whiteSpace: "nowrap", fontSize: 13 },
      quoteName: { color: "var(--dsw-alias-label-secondary, #9ca3af)", fontSize: 12 },
      quotePrice: { fontWeight: 700, fontVariantNumeric: "tabular-nums" },
      quotePct: { fontSize: 12, fontWeight: 600, fontVariantNumeric: "tabular-nums" },
      // 新闻条：对话窗口内正常文档流（composer.dock 槽位，输入框下方），不浮层、不遮挡其他 UI。
      newsRoot: {
        display: "flex",
        alignItems: "center",
        overflow: "hidden",
        whiteSpace: "nowrap",
        fontSize: 12,
        height: NEWS_BAR_H,
        padding: "2px 0",
        borderTop: "1px solid var(--dsw-alias-border-l1, #374151)",
        color: "var(--dsw-alias-label-primary, #e5e7eb)"
      },
      tickerInner: { display: "flex", gap: 20, whiteSpace: "nowrap", alignItems: "baseline" },
      tickerItem: { display: "inline-flex", gap: 6, alignItems: "baseline", color: "var(--dsw-alias-label-primary, #e5e7eb)", textDecoration: "none", fontSize: 12 },
      tickerTime: { color: "var(--dsw-alias-label-secondary, #9ca3af)", fontVariantNumeric: "tabular-nums" },
      empty: { color: "var(--dsw-alias-label-secondary, #9ca3af)", padding: "0 8px" }
    };
    
    // src/client/index.tsx
    var name = "dsh-live-ticker";
    var inject = ["slots"];
    function apply(ctx) {
      ctx.slots.inject(
        "conversation.composer.dock",
        () => ctx.slots.register({
          name: "conversation.composer.dock",
          id: "live-ticker-quotes",
          order: 10,
          label: () => "live-ticker"
        }, () => import_react2.default.createElement(QuotesBar))
      );
      ctx.slots.inject(
        "conversation.composer.dock",
        () => ctx.slots.register({
          name: "conversation.composer.dock",
          id: "live-ticker-news",
          order: 20,
          label: () => "live-ticker"
        }, () => import_react2.default.createElement(NewsBar))
      );
    }
    
    return module.exports;
  }
});
