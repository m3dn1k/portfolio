(function () {
  var KEYS = ["visits", "invite", "project", "wink"];

  function paint(data) {
    if (!data) return;
    KEYS.forEach(function (k) {
      var el = document.querySelector("[data-live='" + k + "']");
      if (el && data[k] != null) el.textContent = String(data[k]);
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

  get().then(paint);
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
