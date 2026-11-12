(function () {
  var KEYS = ["visits", "invite", "project", "wink"];

  function shown(v) {
    if (v == null || v === "") return "—";
    return String(v);
  }

  function paint(data) {
    KEYS.forEach(function (k) {
      var el = document.querySelector("[data-live='" + k + "']");
      if (!el) return;
      if (data && data[k] != null && data[k] !== "") el.textContent = String(data[k]);
      else if (!el.textContent || !String(el.textContent).trim()) el.textContent = "—";
    });
  }

  function get() {
    return fetch("/api/stats").then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () {
      return null;
    });
  }

  function hit(k) {
    return fetch("/api/hit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ k: k }),
      keepalive: true
    }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(paint).catch(function () {});
  }

  function once(storeKey, k) {
    try {
      if (localStorage.getItem(storeKey)) return;
      localStorage.setItem(storeKey, "1");
    } catch (e) {}
    hit(k);
  }

  get().then(function (data) { paint(data || {}); });
  once("live_visits", "visits");

  var invite = document.querySelector("[data-hit='invite']");
  if (invite) invite.addEventListener("click", function () {
    once("live_invite", "invite");
  });
  var project = document.querySelector("[data-hit='project']");
  if (project) project.addEventListener("click", function () {
    once("live_project", "project");
  });

  window.liveHit = hit;

  // ponytail: 4s poll, not a websocket
  setInterval(function () {
    if (document.hidden) return;
    get().then(paint);
  }, 4000);
})();
