(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------- theme toggle */
  (function theme() {
    var root = document.documentElement;
    var btn = document.getElementById("theme-toggle");
    var stored = null;
    try { stored = localStorage.getItem("cins-theme"); } catch (e) {}
    if (stored === "light" || stored === "dark") {
      root.setAttribute("data-theme", stored);
    }
    function label() {
      var mode = root.getAttribute("data-theme");
      if (!mode) { mode = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
      return mode === "dark" ? "☀" : "◑";
    }
    if (btn) {
      btn.textContent = label();
      btn.addEventListener("click", function () {
        var current = root.getAttribute("data-theme");
        if (!current) { current = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
        var next = current === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem("cins-theme", next); } catch (e) {}
        btn.textContent = label();
      });
    }
  })();

  /* ---------------------------------------------------------- progress bar */
  (function progress() {
    var fill = document.getElementById("progress-fill");
    if (!fill) return;
    var ticking = false;
    function update() {
      var doc = document.documentElement;
      var scrollTop = doc.scrollTop || document.body.scrollTop;
      var height = doc.scrollHeight - doc.clientHeight;
      var pct = height > 0 ? Math.min(100, Math.max(0, (scrollTop / height) * 100)) : 0;
      fill.style.width = pct + "%";
      ticking = false;
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    update();
  })();

  /* ---------------------------------------------------------- dot nav scroll-spy */
  (function scrollSpy() {
    var links = new Map();
    document.querySelectorAll("[data-scene-link]").forEach(function (a) {
      links.set(a.dataset.sceneLink, a);
    });
    if (!links.size || !("IntersectionObserver" in window)) return;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          links.forEach(function (a) { a.removeAttribute("aria-current"); });
          var a = links.get(e.target.id);
          if (a) a.setAttribute("aria-current", "true");
        }
      });
    }, { rootMargin: "-45% 0px -45% 0px" });
    document.querySelectorAll("main [id]").forEach(function (s) { obs.observe(s); });
  })();

  /* ---------------------------------------------------------- reveal-on-scroll */
  (function reveal() {
    var els = document.querySelectorAll(".reveal");
    if (!els.length) return;
    if (reduceMotion || !("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("is-visible"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    els.forEach(function (el) { io.observe(el); });
  })();

  /* ---------------------------------------------------------- demo video graceful fallback */
  (function demoVideo() {
    var video = document.getElementById("demo-video-el");
    var fallback = document.getElementById("demo-video-fallback");
    if (!video || !fallback) return;
    var source = video.querySelector("source");
    var declared = fallback.style.display !== "none";
    function showFallback() {
      video.style.display = "none";
      fallback.style.display = "block";
    }
    if (!source || !source.getAttribute("src")) { showFallback(); return; }
    video.addEventListener("error", showFallback, true);
    if (source) {
      source.addEventListener("error", showFallback);
    }
    // If metadata never loads (file missing / 404), fall back after a short grace period.
    var settled = false;
    video.addEventListener("loadedmetadata", function () { settled = true; });
    setTimeout(function () {
      if (!settled && video.readyState < 1) { showFallback(); }
    }, 2500);
  })();

  /* ---------------------------------------------------------- hero particle field (canvas 2D) */
  (function particles() {
    var canvas = document.getElementById("hero-particles");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    var host = canvas.parentElement;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = 0, h = 0, pts = [];
    var mouse = { x: 0, y: 0, active: false };
    var COUNT = 0;

    function accent() {
      var cs = getComputedStyle(document.documentElement);
      return {
        a: cs.getPropertyValue("--accent").trim() || "#4cc9f0",
        b: cs.getPropertyValue("--accent2").trim() || "#f4b842",
        line: cs.getPropertyValue("--ink-faint").trim() || "#7e899a"
      };
    }

    function resize() {
      var rect = host.getBoundingClientRect();
      w = rect.width; h = rect.height;
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + "px"; canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      COUNT = Math.max(40, Math.min(140, Math.floor((w * h) / 14000)));
      pts = [];
      for (var i = 0; i < COUNT; i++) {
        pts.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.18,
          vy: (Math.random() - 0.5) * 0.18,
          r: Math.random() * 1.4 + 0.6
        });
      }
    }

    function step() {
      var col = accent();
      ctx.clearRect(0, 0, w, h);
      for (var i = 0; i < pts.length; i++) {
        var p = pts[i];
        if (!reduceMotion) {
          p.x += p.vx; p.y += p.vy;
          if (mouse.active) {
            var dx = p.x - mouse.x, dy = p.y - mouse.y;
            var d2 = dx * dx + dy * dy;
            if (d2 < 12000) {
              var f = (12000 - d2) / 12000 * 0.02;
              p.vx += dx * f * 0.02; p.vy += dy * f * 0.02;
            }
          }
          p.vx *= 0.995; p.vy *= 0.995;
          if (p.x < -10) p.x = w + 10; if (p.x > w + 10) p.x = -10;
          if (p.y < -10) p.y = h + 10; if (p.y > h + 10) p.y = -10;
        }
      }
      // connections
      ctx.lineWidth = 1;
      for (var i2 = 0; i2 < pts.length; i2++) {
        for (var j = i2 + 1; j < pts.length; j++) {
          var dx2 = pts[i2].x - pts[j].x, dy2 = pts[i2].y - pts[j].y;
          var dist = Math.sqrt(dx2 * dx2 + dy2 * dy2);
          if (dist < 130) {
            var alpha = (1 - dist / 130) * 0.18;
            ctx.strokeStyle = hexA(col.line, alpha);
            ctx.beginPath();
            ctx.moveTo(pts[i2].x, pts[i2].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.stroke();
          }
        }
      }
      // dots
      for (var k = 0; k < pts.length; k++) {
        var pp = pts[k];
        ctx.beginPath();
        ctx.fillStyle = hexA(k % 2 === 0 ? col.a : col.b, 0.55);
        ctx.arc(pp.x, pp.y, pp.r, 0, Math.PI * 2);
        ctx.fill();
      }
      if (!reduceMotion) requestAnimationFrame(step);
    }

    function hexA(hex, alpha) {
      hex = hex.replace("#", "");
      if (hex.length === 3) { hex = hex.split("").map(function (c) { return c + c; }).join(""); }
      var r = parseInt(hex.substring(0, 2), 16) || 0;
      var g = parseInt(hex.substring(2, 4), 16) || 0;
      var b = parseInt(hex.substring(4, 6), 16) || 0;
      return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
    }

    window.addEventListener("pointermove", function (e) {
      var rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left; mouse.y = e.clientY - rect.top; mouse.active = true;
    }, { passive: true });
    window.addEventListener("resize", resize);
    resize();
    step();
  })();

  /* ---------------------------------------------------------- gate ledger */
  (function gates() {
    var el = document.getElementById("gate-ledger");
    if (!el) return;
    fetch("gates.json").then(function (r) { return r.json(); }).then(function (d) {
      el.innerHTML = d.gates.map(function (g) {
        var color = g.status === "closed" ? "var(--ok)" : g.status === "in_progress" ? "var(--warn)" : "var(--ink-faint)";
        return '<div class="gate-chip" title="' + escapeHtml(g.title) + (g.evidence ? ": " + escapeHtml(g.evidence) : "") + '">' +
          '<span class="g-id">' + escapeHtml(g.id) + '</span>' +
          '<span class="g-dot" style="background:' + color + '"></span>' +
          '</div>';
      }).join("");
    }).catch(function () { /* gates.json optional; fail silent */ });
    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }
  })();
})();
