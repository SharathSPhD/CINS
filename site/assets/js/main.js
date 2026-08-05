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
        window.dispatchEvent(new CustomEvent("cins:theme-changed"));
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
    function showFallback() {
      video.style.display = "none";
      fallback.style.display = "block";
    }
    function hideFallback() {
      video.style.display = "";
      fallback.style.display = "none";
    }
    if (!source || !source.getAttribute("src")) { showFallback(); return; }

    // A missing file raises a real error on the element or its source. That is
    // the only reliable "not published" signal, so it is the only one that
    // decides on its own.
    video.addEventListener("error", showFallback, true);
    source.addEventListener("error", showFallback);

    // A slow file is not a missing file. The previous version hid the video for
    // good if metadata had not arrived within 2.5 seconds, which is routine for
    // a 1.7 MB asset on a cold CDN edge, and nothing ever re-checked: the page
    // then claimed the recording was unpublished while it was being served with
    // HTTP 200. The wait is longer now and, more importantly, reversible.
    var settled = false;
    ["loadedmetadata", "canplay", "playing"].forEach(function (ev) {
      video.addEventListener(ev, function () { settled = true; hideFallback(); });
    });
    setTimeout(function () {
      if (!settled && video.readyState < 1) { showFallback(); }
    }, 12000);
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

  /* ---------------------------------------------------------- CST decomposition visuals
     Draws the class function, the Bernstein shape-function terms, the assembled surface,
     and the fitted-coefficient bar chart for the "CST is linear" scene. Everything below is
     computed from the CST formulas in docs/CST_MISES_Monolithic_Inverse_Design.md sec 3.1-3.4:
       C(psi)    = psi^0.5 * (1-psi)^1.0                          (class function)
       S_i(psi)  = K_i * psi^i * (1-psi)^(n-i), K_i = n!/(i!(n-i)!) (Bernstein shape terms)
       zeta(psi) = C(psi) * sum_i A_i S_i(psi) + psi * zeta_T       (surface)
     No fetch, no external library: this is a static site and the coefficients below are
     hard-coded, read from the project's own fitted-airfoil corpus. */
  (function cstViz() {
    var classCanvas = document.getElementById("cst-canvas-class");
    var shapeCanvas = document.getElementById("cst-canvas-shape");
    var surfaceCanvas = document.getElementById("cst-canvas-surface");
    var barsCanvas = document.getElementById("cst-canvas-bars");
    if (!classCanvas && !shapeCanvas && !surfaceCanvas && !barsCanvas) return;

    // Order-8 CST fit (n=8, 9 coefficients/surface), two real sections from the project's
    // own corpus. Source: app/frontend/public/corpus.json, ids "naca:2412" and "naca:6409"
    // (A_upper, A_lower fields). zeta_T,u / zeta_T,l are each section's own fitted
    // trailing-edge offset (that corpus file's coords[-1][1] / coords[0][1]).
    var AIRFOILS = {
      naca2412: {
        label: "NACA 2412",
        n: 8,
        A_upper: [0.179538, 0.211387, 0.185650, 0.249930, 0.151141, 0.238065, 0.181854, 0.210407, 0.206570],
        A_lower: [-0.167224, -0.090704, -0.172794, 0.007847, -0.211765, 0.009189, -0.132172, -0.054516, -0.080480],
        zeta_Tu: 0.00126,
        zeta_Tl: -0.00126
      },
      naca6409: {
        label: "NACA 6409",
        n: 8,
        A_upper: [0.148507, 0.294309, 0.153701, 0.477446, 0.045154, 0.456709, 0.192282, 0.333184, 0.296779],
        A_lower: [-0.111565, 0.067740, -0.115132, 0.295883, -0.227025, 0.285052, -0.043237, 0.134491, 0.081491],
        zeta_Tu: 0.00094,
        zeta_Tl: -0.00094
      }
    };

    function factorial(k) { var r = 1; for (var i = 2; i <= k; i++) r *= i; return r; }
    function binom(n, i) { return factorial(n) / (factorial(i) * factorial(n - i)); }
    function bernstein(n, i, psi) { return binom(n, i) * Math.pow(psi, i) * Math.pow(1 - psi, n - i); }
    function classFn(psi) { return Math.pow(psi, 0.5) * Math.pow(1 - psi, 1.0); }
    function shapeSum(A, n, psi) {
      var s = 0;
      for (var i = 0; i <= n; i++) s += A[i] * bernstein(n, i, psi);
      return s;
    }
    function surfaceAt(A, n, zetaT, psi) { return classFn(psi) * shapeSum(A, n, psi) + psi * zetaT; }

    // Dense-near-0 psi sampling so the infinite-slope nose renders smoothly.
    function psiSamples(count) {
      var out = [];
      for (var k = 0; k <= count; k++) {
        var t = k / count;
        out.push(t * t * (3 - 2 * t) * 0.998 + 0.001); // smoothstep easing, avoid exact 0/1
      }
      return out;
    }
    var PSI = psiSamples(220);

    function colors() {
      var cs = getComputedStyle(document.documentElement);
      function v(name, fallback) { var x = cs.getPropertyValue(name).trim(); return x || fallback; }
      return {
        ink: v("--ink", "#eef1f5"),
        inkSoft: v("--ink-soft", "#aab4c2"),
        inkFaint: v("--ink-faint", "#7e899a"),
        hairline: v("--hairline", "#1f2937"),
        accent: v("--accent", "#4cc9f0"),
        accent2: v("--accent2", "#f4b842"),
        bad: v("--bad", "#fb7185"),
        bgPanel: v("--bg-panel", "#0d131b")
      };
    }

    function fitCanvas(canvas) {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var rect = canvas.getBoundingClientRect();
      var w = rect.width || canvas.width;
      var h = w * (canvas.height / canvas.width);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.height = h + "px";
      var ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { ctx: ctx, w: w, h: h };
    }

    function drawAxes(ctx, w, h, pad, col, xLabel, yLabel) {
      ctx.strokeStyle = col.hairline;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
      ctx.stroke();
      ctx.fillStyle = col.inkFaint;
      ctx.font = "11px " + (getComputedStyle(document.body).fontFamily || "sans-serif");
      if (xLabel) ctx.fillText(xLabel, (pad.l + (w - pad.r)) / 2 - 10, h - 6);
      if (yLabel) {
        ctx.save();
        ctx.translate(12, (pad.t + (h - pad.b)) / 2 + 20);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText(yLabel, 0, 0);
        ctx.restore();
      }
    }

    function drawClass(canvas) {
      var f = fitCanvas(canvas), ctx = f.ctx, w = f.w, h = f.h, col = colors();
      ctx.clearRect(0, 0, w, h);
      var pad = { l: 34, r: 14, t: 16, b: 26 };
      drawAxes(ctx, w, h, pad, col, "ψ = x/c", "C(ψ)");
      var yMax = 0.4;
      function px(psi) { return pad.l + psi * (w - pad.l - pad.r); }
      function py(val) { return (h - pad.b) - (val / yMax) * (h - pad.t - pad.b); }
      ctx.strokeStyle = col.accent;
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      for (var k = 0; k < PSI.length; k++) {
        var psi = PSI[k], val = classFn(psi);
        var x = px(psi), y = py(val);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.fillStyle = col.inkFaint;
      ctx.font = "11px " + (getComputedStyle(document.body).fontFamily || "sans-serif");
      ctx.fillText("round nose", px(0.03), py(classFn(0.14)) - 8);
      ctx.fillText("sharp tail → 0", px(0.66), h - pad.b - 8);
    }

    function drawShape(canvas) {
      var f = fitCanvas(canvas), ctx = f.ctx, w = f.w, h = f.h, col = colors();
      ctx.clearRect(0, 0, w, h);
      var pad = { l: 34, r: 14, t: 16, b: 26 };
      var A = AIRFOILS.naca2412.A_upper, n = AIRFOILS.naca2412.n;
      // y-range: individual terms peak below 1; the weighted sum can exceed that.
      var sumMax = 0;
      for (var k0 = 0; k0 < PSI.length; k0++) sumMax = Math.max(sumMax, Math.abs(shapeSum(A, n, PSI[k0])));
      var yMax = Math.max(1.05, sumMax * 1.1);
      drawAxes(ctx, w, h, pad, col, "ψ = x/c", "S(ψ)");
      function px(psi) { return pad.l + psi * (w - pad.l - pad.r); }
      function py(val) { return (h - pad.b) - (val / yMax) * (h - pad.t - pad.b); }
      // faint individual Bernstein terms
      ctx.lineWidth = 1.1;
      for (var i = 0; i <= n; i++) {
        ctx.strokeStyle = col.inkFaint;
        ctx.globalAlpha = 0.38;
        ctx.beginPath();
        for (var k = 0; k < PSI.length; k++) {
          var psi = PSI[k], val = bernstein(n, i, psi);
          var x = px(psi), y = py(val);
          if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // bold weighted sum
      ctx.strokeStyle = col.accent;
      ctx.lineWidth = 2.6;
      ctx.beginPath();
      for (var k1 = 0; k1 < PSI.length; k1++) {
        var psi1 = PSI[k1], val1 = shapeSum(A, n, psi1);
        var x1 = px(psi1), y1 = py(val1);
        if (k1 === 0) ctx.moveTo(x1, y1); else ctx.lineTo(x1, y1);
      }
      ctx.stroke();
    }

    function drawSurface(canvas) {
      var f = fitCanvas(canvas), ctx = f.ctx, w = f.w, h = f.h, col = colors();
      ctx.clearRect(0, 0, w, h);
      var pad = { l: 34, r: 14, t: 16, b: 26 };
      var yMax = 0.16;
      drawAxes(ctx, w, h, pad, col, "ψ = x/c", "ζ = z/c");
      function px(psi) { return pad.l + psi * (w - pad.l - pad.r); }
      function py(val) { return (h - pad.t - pad.b) / 2 + pad.t - (val / yMax) * (h - pad.t - pad.b) / 2; }
      // chord line
      ctx.strokeStyle = col.hairline;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px(0), py(0)); ctx.lineTo(px(1), py(0)); ctx.stroke();

      function plotAirfoil(af, color, dashed) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 2.4;
        ctx.setLineDash(dashed ? [6, 4] : []);
        [af.A_upper, af.A_lower].forEach(function (A, idx) {
          var zetaT = idx === 0 ? af.zeta_Tu : af.zeta_Tl;
          ctx.beginPath();
          for (var k = 0; k < PSI.length; k++) {
            var psi = PSI[k], val = surfaceAt(A, af.n, zetaT, psi);
            var x = px(psi), y = py(val);
            if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.stroke();
        });
        ctx.setLineDash([]);
      }
      plotAirfoil(AIRFOILS.naca2412, col.accent, false);
      plotAirfoil(AIRFOILS.naca6409, col.accent2, true);

      ctx.font = "11px " + (getComputedStyle(document.body).fontFamily || "sans-serif");
      ctx.fillStyle = col.bgPanel;
      ctx.globalAlpha = 0.82;
      ctx.fillRect(pad.l, pad.t, 110, 30);
      ctx.globalAlpha = 1;
      ctx.fillStyle = col.accent;
      ctx.fillText("— NACA 2412", pad.l + 6, pad.t + 12);
      ctx.fillStyle = col.accent2;
      ctx.fillText("- - NACA 6409", pad.l + 6, pad.t + 28);
    }

    function drawBars(canvas) {
      var f = fitCanvas(canvas), ctx = f.ctx, w = f.w, h = f.h, col = colors();
      ctx.clearRect(0, 0, w, h);
      var rows = [
        { title: "Upper surface Aᵢ", key: "A_upper" },
        { title: "Lower surface Aᵢ", key: "A_lower" }
      ];
      var n = 8, groups = n + 1;
      var padL = 34, padR = 14, headerH = 26;
      var rowH = (h - headerH) / 2;
      var vMax = 0.5;
      ctx.font = "11px " + (getComputedStyle(document.body).fontFamily || "sans-serif");
      rows.forEach(function (row, rIdx) {
        var top = headerH + rIdx * rowH;
        var baseline = top + rowH * 0.55;
        var plotTop = top + 22, plotBottom = top + rowH - 18;
        var usable = w - padL - padR;
        var groupW = usable / groups;
        // zero line
        ctx.strokeStyle = col.hairline;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(padL, baseline); ctx.lineTo(w - padR, baseline); ctx.stroke();
        ctx.fillStyle = col.inkSoft;
        ctx.fillText(row.title, padL, top + 14);
        for (var i = 0; i < groups; i++) {
          var gx = padL + i * groupW;
          var barW = groupW * 0.32;
          [
            { af: AIRFOILS.naca2412, color: col.accent, offset: 0.12 },
            { af: AIRFOILS.naca6409, color: col.accent2, offset: 0.52 }
          ].forEach(function (series) {
            var val = series.af[row.key][i];
            var scale = (baseline - plotTop) / vMax;
            var barH = Math.abs(val) * scale;
            var x = gx + series.offset * groupW;
            var y = val >= 0 ? baseline - barH : baseline;
            ctx.fillStyle = series.color;
            ctx.globalAlpha = 0.85;
            ctx.fillRect(x, y, barW, Math.max(1, barH));
            ctx.globalAlpha = 1;
          });
          ctx.fillStyle = col.inkFaint;
          ctx.fillText("A" + i, gx + groupW * 0.32, plotBottom + 12);
        }
      });
      ctx.fillStyle = col.accent;
      ctx.fillText("■ NACA 2412", padL, 14);
      ctx.fillStyle = col.accent2;
      ctx.fillText("■ NACA 6409", padL + 110, 14);
    }

    function drawAll() {
      if (classCanvas) drawClass(classCanvas);
      if (shapeCanvas) drawShape(shapeCanvas);
      if (surfaceCanvas) drawSurface(surfaceCanvas);
      if (barsCanvas) drawBars(barsCanvas);
    }

    drawAll();
    window.addEventListener("resize", function () {
      clearTimeout(window.__cstVizResizeT);
      window.__cstVizResizeT = setTimeout(drawAll, 120);
    });
    window.addEventListener("cins:theme-changed", drawAll);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);
  })();
})();
