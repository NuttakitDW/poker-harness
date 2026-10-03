// First-party visit counting for tamkwai.com: one "view" per page load and the time the page was
// actually visible ("time", in ms). No cookies, no IP or browser fingerprint: the visitor id is a
// random value this browser keeps, the session id lives for one tab. Do Not Track / Global Privacy
// Control switch it off.
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
  send("view", { referrer: document.referrer });
})();
