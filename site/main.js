(() => {
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

  /* Hero entrance & subtle desktop scroll lift */
  const shot = document.getElementById("heroShot");
  if (!reduce) {
    root.classList.add("is-ready");
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add("is-loaded")));
    if (shot) {
      let ticking = false;
      const tilt = () => {
        ticking = false;
        const p = Math.min(1, Math.max(0, window.scrollY / (window.innerHeight * 0.5)));
        const small = window.innerWidth <= 734;
        const deg = small ? 0 : (1 - p) * 6;
        const sc = small ? 1 : 0.97 + p * 0.03;
        shot.style.transform = `perspective(2400px) rotateX(${deg.toFixed(2)}deg) scale(${sc.toFixed(4)})`;
      };
      const onScroll = () => {
        if (!ticking) {
          ticking = true;
          requestAnimationFrame(tilt);
        }
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", onScroll, { passive: true });
      tilt();
    }
  }

  /* Scroll reveal */
  const reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduce) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.05 },
    );
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("is-in"));
  }

  /* Accessible tabs with roving tabindex & keyboard arrow support */
  function setupTabs(list, onChange) {
    const btns = Array.from(list.querySelectorAll('[role="tab"]'));
    const select = (btn, focus) => {
      btns.forEach((b) => {
        const on = b === btn;
        b.setAttribute("aria-selected", String(on));
        b.tabIndex = on ? 0 : -1;
        const pane = document.getElementById(b.getAttribute("aria-controls"));
        if (pane) pane.hidden = !on;
      });
      if (focus) btn.focus();
      if (onChange) onChange(btn);
    };
    btns.forEach((b, i) => {
      b.addEventListener("click", () => select(b));
      b.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        select(btns[(i + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length], true);
      });
    });
    return select;
  }

  document.querySelectorAll(".showcase__tabs").forEach((list) => {
    setupTabs(list, (btn) => {
      if (reduce) return;
      const pane = document.getElementById(btn.getAttribute("aria-controls"));
      if (pane) {
        pane.classList.remove("is-swap");
        void pane.offsetWidth;
        pane.classList.add("is-swap");
      }
    });
  });

  /* Install OS tabs — auto-detect visitor platform */
  const osList = document.querySelector(".term__tabs");
  if (osList) {
    const select = setupTabs(osList);
    const plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    const mobile = /android|iphone|ipad/i.test(navigator.userAgent);
    if (!mobile && /mac|linux|x11|cros/i.test(plat)) {
      const unixBtn = document.getElementById("os-unix");
      if (unixBtn) select(unixBtn);
    }
  }

  /* Carousel: dots + arrows */
  const rail = document.getElementById("rail");
  if (rail) {
    const cards = Array.from(rail.children);
    const dotsBox = document.querySelector(".rail-ctrl .dots");
    const prev = document.querySelector('.arrow[data-dir="-1"]');
    const next = document.querySelector('.arrow[data-dir="1"]');
    const dots = cards.map((card, i) => {
      const b = document.createElement("button");
      b.type = "button";
      const label = card.querySelector(".card__k");
      b.setAttribute("aria-label", `第 ${i + 1} 張：${label ? label.textContent : ""}`);
      b.addEventListener("click", () => go(i));
      dotsBox.appendChild(b);
      return b;
    });
    const step = () => (cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : 1);
    const current = () => Math.round(rail.scrollLeft / step());
    const go = (i) =>
      rail.scrollTo({
        left: Math.max(0, Math.min(cards.length - 1, i)) * step(),
        behavior: reduce ? "auto" : "smooth",
      });
    const update = () => {
      const max = rail.scrollWidth - rail.clientWidth - 2;
      const atEnd = rail.scrollLeft >= max;
      const idx = atEnd ? cards.length - 1 : current();
      dots.forEach((d, i) => d.setAttribute("aria-current", String(i === idx)));
      prev.disabled = rail.scrollLeft <= 2;
      next.disabled = atEnd;
    };
    prev.addEventListener("click", () => go(current() - 1));
    next.addEventListener("click", () => go(current() + 1));
    rail.addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });
    window.addEventListener("resize", update, { passive: true });
    window.addEventListener("load", update);
    if ("ResizeObserver" in window) {
      new ResizeObserver(update).observe(rail);
    }
    requestAnimationFrame(update);
  }

  /* Copy buttons */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (_) {
        ok = false;
      }
      ta.remove();
      return ok;
    }
  }

  document.querySelectorAll(".copy").forEach((btn) => {
    const label = btn.textContent;
    btn.addEventListener("click", async () => {
      let text = btn.dataset.copy;
      if (!text && btn.dataset.copyFrom) {
        const cmd = document.querySelector(`#${btn.dataset.copyFrom} .cmd`);
        text = cmd ? cmd.textContent : "";
      }
      const ok = await copyText(text || "");
      btn.textContent = ok ? "已複製" : "請手動選取";
      btn.classList.toggle("is-done", ok);
      setTimeout(() => {
        btn.textContent = label;
        btn.classList.remove("is-done");
      }, 1800);
    });
  });
})();
