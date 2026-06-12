/* =====================================================================
   ARIA NEXUS — particles.js
   Canvas starfield using requestAnimationFrame (60fps target).
   ===================================================================== */
(function () {
  'use strict';

  window.initParticles = function (canvasId) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.willChange = 'transform';

    var w = 0, h = 0;
    var COUNT = 80;
    var LINK_DIST = 120;
    var COLORS = [
      'hsl(195,100%,55%)',     // cyan accent-1
      'hsl(265,80%,65%)',      // purple accent-2
      'rgba(255,255,255,0.8)'  // white star
    ];
    var particles = [];

    function rand(min, max) { return Math.random() * (max - min) + min; }

    function sizeCanvas() {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w;
      canvas.height = h;
    }

    function buildParticles() {
      particles = [];
      for (var i = 0; i < COUNT; i++) {
        particles.push({
          x: rand(0, w),
          y: rand(0, h),
          vx: rand(-0.4, 0.4),
          vy: rand(-0.4, 0.4),
          size: rand(1, 2.5),
          opacity: rand(0.4, 1),
          color: COLORS[Math.floor(Math.random() * COLORS.length)]
        });
      }
    }

    function loop() {
      ctx.clearRect(0, 0, w, h);

      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;

        ctx.globalAlpha = p.opacity;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      for (var a = 0; a < particles.length; a++) {
        for (var b = a + 1; b < particles.length; b++) {
          var dx = particles[a].x - particles[b].x;
          var dy = particles[a].y - particles[b].y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < LINK_DIST) {
            ctx.strokeStyle = 'rgba(120,180,255,' + ((1 - dist / LINK_DIST) * 0.12) + ')';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(particles[a].x, particles[a].y);
            ctx.lineTo(particles[b].x, particles[b].y);
            ctx.stroke();
          }
        }
      }

      window.particlesAnimId = requestAnimationFrame(loop);
    }

    var resizeTimer = null;
    window.addEventListener('resize', function () {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        sizeCanvas();
      }, 200);
    });

    function drawStatic() {
      ctx.clearRect(0, 0, w, h);
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        ctx.globalAlpha = p.opacity;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    var reduceMotion = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    sizeCanvas();
    buildParticles();
    /* PERF: honor reduced-motion - paint one static field and skip the rAF loop */
    if (reduceMotion) { drawStatic(); return 0; }
    window.particlesAnimId = requestAnimationFrame(loop);
    return window.particlesAnimId;
  };
})();
