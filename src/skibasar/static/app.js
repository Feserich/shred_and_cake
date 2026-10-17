/* Small helpers for all screens: price mask, Enter-to-advance, toasts, confirm dialog. */
(function () {
  "use strict";

  /* Lenient client-side price formatting; the server (money.py) stays the authority. */
  function formatPrice(raw) {
    let t = raw.replace(/€/g, "").replace(/\s/g, "");
    if (!t || !/^[\d.,]+$/.test(t)) return raw;
    let int, frac = "";
    const comma = t.lastIndexOf(",");
    if (comma >= 0) {
      int = t.slice(0, comma).replace(/\./g, "");
      frac = t.slice(comma + 1);
    } else if (/\.\d{1,2}$/.test(t) && t.indexOf(".") === t.lastIndexOf(".")) {
      [int, frac] = t.split(".");
    } else {
      int = t.replace(/\./g, "");
    }
    if (!/^\d*$/.test(int) || !/^\d{0,2}$/.test(frac)) return raw;
    int = (int || "0").replace(/^0+(?=\d)/, "");
    frac = (frac + "00").slice(0, 2);
    return int.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + "," + frac;
  }
  document.addEventListener("focusout", (e) => {
    if (e.target.matches && e.target.matches("input[data-price]")) {
      e.target.value = formatPrice(e.target.value);
    }
  });

  /* Enter jumps to the next field; in the last field it submits. */
  document.addEventListener("keydown", (e) => {
    const el = e.target;
    if (e.key !== "Enter" || !el.matches || !el.matches("input")) return;
    const form = el.closest("form[data-enter-advance]");
    if (!form || el.type === "checkbox" || el.type === "submit") return;
    const fields = [...form.querySelectorAll("input:not([type=hidden]):not([disabled]), textarea")];
    const next = fields[fields.indexOf(el) + 1];
    if (next && !next.matches("[type=checkbox]")) {
      e.preventDefault();
      next.focus();
      if (next.select) next.select();
    }
  });

  /* Toasts: window.skibasar.toast(text, "ok"|"err") or <div data-toast="ok">Text</div> in the page. */
  function toast(text, kind) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast " + (kind || "ok");
    el.textContent = text;
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === "err" ? 6000 : 2500);
  }
  /* Errors at the checkout also beep, so a mistake is noticed without reading. */
  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      osc.frequency.value = 220;
      osc.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    } catch (e) { /* no audio available */ }
  }
  window.skibasar = { toast, formatPrice, beep };
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-toast]").forEach((el) => {
      toast(el.textContent.trim(), el.dataset.toast);
      el.remove();
    });
    if (document.querySelector("[data-beep]")) beep();
  });

  /* Confirm dialog: <form data-confirm="Text"> asks before it is submitted. */
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const text = form.dataset && form.dataset.confirm;
    const dialog = document.getElementById("confirm-dialog");
    if (!text || form.dataset.confirmed || !dialog || !dialog.showModal) return;
    e.preventDefault();
    document.getElementById("confirm-text").textContent = text;
    const done = (ok) => {
      dialog.close();
      if (ok) { form.dataset.confirmed = "1"; form.requestSubmit(); }
    };
    document.getElementById("confirm-yes").onclick = () => done(true);
    document.getElementById("confirm-no").onclick = () => done(false);
    dialog.showModal();
  });
})();
