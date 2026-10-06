// First-party visit counting for tamkwai.com: one "view" per page load, the time the page was
// actually visible ("time", in ms) and one "act" per kind of thing done on the page (scrolled, a
// button, a link). A visitor who never acts is counted apart, as most of them are bots. No
// cookies, no IP or browser fingerprint, nothing typed: the visitor id is a random value this
// browser keeps, the session id lives for one tab. Do Not Track / Global Privacy Control switch it off.
(() => {
  "use strict";
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl) return;
  const random = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, "0")).join("");
  const kept = (storage, key) => {
    try {
      let value = storage.getItem(key);
      if (!/^[a-z0-9]{16}$/.test(value || "")) { value = random(); storage.setItem(key, value); }
      return value;
    } catch (error) {
      return random();
    }
  };
  const visitor = kept(window.localStorage, "tk_visitor");
  const session = kept(window.sessionStorage, "tk_session");
  const path = location.pathname;
  const send = (kind, extra) => {
    const body = JSON.stringify({ kind, path, visitor, session, ...extra });
    try {
      if (navigator.sendBeacon && navigator.sendBeacon("/api/collect", new Blob([body], { type: "text/plain" }))) return;
      fetch("/api/collect", { method: "POST", headers: { "Content-Type": "text/plain" }, body, keepalive: true }).catch(() => {});
    } catch (error) { /* counting never breaks the page */ }
  };

  // ---- time on page: sent when the tab hides, and every minute while it stays open
  const HEARTBEAT_MS = 60000;
  let shown = document.visibilityState === "visible" ? performance.now() : null;
  let visible = 0;
  const flush = () => {
    if (shown !== null) { visible += performance.now() - shown; shown = null; }
    if (visible >= 1000) { send("time", { ms: Math.round(visible) }); visible = 0; }
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
    else if (shown === null) shown = performance.now();
  });
  window.addEventListener("pagehide", flush);
  setInterval(() => {
    if (document.visibilityState !== "visible") return;
    flush();
    shown = performance.now();
  }, HEARTBEAT_MS);

  // ---- actions: each name once per page load. Names come from the page's own markup
  // (data-track, an id, a link's path, a data-* key), never from what the visitor typed.
  const NAME = /^[A-Za-z0-9#:/_.\-]{1,80}$/;
  const done = new Set();
  const act = name => {
    name = String(name || "").slice(0, 80);
    if (!NAME.test(name) || done.has(name)) return;
    done.add(name);
    send("act", { name });
  };
  const nameOf = el => {
    if (el.dataset.track) return el.dataset.track;
    if (el.id) return `#${el.id}`;
    if (el.tagName === "A") {
      const href = el.getAttribute("href") || "";
      if (href.startsWith("#")) return `link:${href.split("-")[0]}`;
      try {
        const url = new URL(href, location.href);
        return url.origin === location.origin ? `link:${url.pathname}` : `out:${url.hostname}`;
      } catch (error) { return ""; }
    }
    const key = Object.keys(el.dataset)[0];
    const home = el.parentElement && el.parentElement.closest("[id]");
    return key ? `${home ? home.id : "page"}:${key}` : "";
  };
  const CONTROL = "[data-track], a[href], button, summary, select, input, [role=tab], [role=button]";
  document.addEventListener("click", event => {
    const el = event.target instanceof Element && event.target.closest(CONTROL);
    if (el && !(el.tagName === "INPUT" && el.type !== "file" && el.type !== "checkbox" && el.type !== "radio")) act(nameOf(el));
  }, true);
  document.addEventListener("change", event => {
    const el = event.target instanceof Element && event.target.closest("select, input");
    if (el) act(nameOf(el));
  }, true);
  document.addEventListener("submit", event => {
    if (event.target instanceof Element) act(`submit:${event.target.id || "form"}`);
  }, true);
  const scrolled = () => {
    if (window.scrollY < Math.min(400, window.innerHeight / 3)) return;
    act("scroll");
    window.removeEventListener("scroll", scrolled);
  };
  window.addEventListener("scroll", scrolled, { passive: true });

  send("view", { referrer: document.referrer });
})();
