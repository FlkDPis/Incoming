(() => {
  "use strict";
  const $ = (sel) => document.querySelector(sel);
  const LABELS = { armed: "Armée", partial: "Mode partiel", disarmed: "Désarmée", unknown: "État inconnu" };
  let busy = false;

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    children.forEach((c) => c && node.append(c));
    return node;
  }

  function toast(message) {
    const t = $("#toast");
    t.textContent = message;
    t.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.add("hidden"), 3500);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
    });
    if (res.status === 401) { location.href = "/login"; throw new Error("Session expirée"); }
    if (!res.ok) {
      let msg = "Erreur " + res.status;
      try { msg = (await res.json()).error || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res;
  }

  function fmtDate(ts) {
    if (!ts) return "jamais";
    return new Date(ts * 1000).toLocaleTimeString("fr-FR");
  }

  function renderAlarm(s) {
    const level = s.alarm || "unknown";
    $("#alarm-dot").className = "dot " + level;
    $("#alarm-text").textContent = LABELS[level] || level;
    document.querySelectorAll("[data-level]").forEach((b) => b.classList.toggle("active", b.dataset.level === level));
  }

  function renderCameras(s) {
    const box = $("#cameras");
    box.replaceChildren();
    if (!s.cameras || !s.cameras.length) { box.append(el("p", { class: "muted", text: "Aucune caméra trouvée." })); return; }
    s.cameras.forEach((cam) => {
      const stateText = cam.shutter_open === true ? "Volet ouvert" : cam.shutter_open === false ? "Volet fermé" : "Volet : état inconnu";
      const img = el("img", { alt: "Aperçu " + cam.label, class: "hidden" });
      const previewBtn = el("button", { class: "btn ghost", type: "button", text: "Aperçu" });
      previewBtn.addEventListener("click", () => {
        previewBtn.disabled = true;
        img.onload = () => { img.classList.remove("hidden"); previewBtn.disabled = false; };
        img.onerror = () => { toast("Aperçu indisponible (volet fermé ?)"); previewBtn.disabled = false; };
        img.src = "/api/camera/" + encodeURIComponent(cam.id) + "/snapshot?t=" + Date.now();
      });
      const shutter = (action) => () => act(() => api("/api/camera/" + encodeURIComponent(cam.id) + "/shutter", { method: "POST", body: { action } }),
        action === "open" ? "Volet ouvert" : "Volet fermé");
      box.append(el("div", { class: "cam" },
        el("div", { class: "cam-head" }, el("strong", { text: cam.label }), el("span", { class: "muted", text: stateText })),
        el("div", { class: "btn-row" },
          el("button", { class: "btn", type: "button", text: "Ouvrir le volet", onclick: shutter("open") }),
          el("button", { class: "btn", type: "button", text: "Fermer le volet", onclick: shutter("close") }),
          previewBtn),
        img));
    });
  }

  function renderDevices(s) {
    const box = $("#devices");
    box.replaceChildren();
    if (!s.devices || !s.devices.length) { box.append(el("p", { class: "muted", text: "Aucun capteur trouvé." })); return; }
    const head = el("tr", {}, ...["Capteur", "Type", "Batterie", "État"].map((h) => el("th", { text: h })));
    const rows = s.devices.map((d) => {
      let battery;
      if (d.battery == null) battery = el("span", { class: "muted", text: "n/d" });
      else {
        const cls = d.battery <= window.HC2.batteryWarn ? "low" : d.battery <= 40 ? "mid" : "";
        const fill = el("i"); fill.style.width = d.battery + "%";
        battery = el("span", {}, el("span", { class: "bar " + cls }, fill), document.createTextNode(d.battery + " %"));
      }
      return el("tr", {}, el("td", { text: d.label }), el("td", { class: "muted", text: d.model || d.kind }), el("td", {}, battery), el("td", { text: d.state || "—" }));
    });
    box.append(el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows)));
  }

  function renderEvents(s) {
    const ul = $("#events");
    ul.replaceChildren();
    if (!s.events || !s.events.length) { ul.append(el("li", { class: "muted", text: "Aucun événement." })); return; }
    s.events.forEach((e) => {
      const alarm = /intrusion|d[ée]clench|triggered|sir[èe]ne|panic/i.test(e.label + " " + e.kind);
      ul.append(el("li", { class: alarm ? "alarm" : "" }, el("time", { text: e.when || "" }), el("span", { text: e.label + (e.device ? " — " + e.device : "") })));
    });
  }

  async function refresh() {
    try {
      const s = await (await api("/api/status")).json();
      renderAlarm(s); renderCameras(s); renderDevices(s); renderEvents(s);
      $("#updated").textContent = "Dernière mise à jour : " + fmtDate(s.updated) + " · capteurs : " + fmtDate(s.devices_updated);
      const banner = $("#error-banner");
      if (s.error) { banner.textContent = "Problème de communication : " + s.error; banner.classList.remove("hidden"); }
      else banner.classList.add("hidden");
    } catch (e) { if (e.message !== "Session expirée") { $("#error-banner").textContent = e.message; $("#error-banner").classList.remove("hidden"); } }
  }

  async function act(fn, okMessage) {
    if (busy) return;
    busy = true;
    document.querySelectorAll(".btn").forEach((b) => (b.disabled = true));
    try { await fn(); toast(okMessage); }
    catch (e) { toast(e.message); }
    finally {
      busy = false;
      document.querySelectorAll(".btn").forEach((b) => (b.disabled = false));
      setTimeout(refresh, 1500);
    }
  }

  function askPin() {
    return new Promise((resolve) => {
      const dlg = $("#pin-dialog"), input = $("#pin-input");
      input.value = "";
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok" ? input.value : null), { once: true });
      dlg.showModal();
      input.focus();
    });
  }

  document.querySelectorAll("[data-level]").forEach((btn) => btn.addEventListener("click", async () => {
    const level = btn.dataset.level;
    let pin;
    if (level === "disarmed" && window.HC2.pinRequired) { pin = await askPin(); if (pin === null) return; }
    act(() => api("/api/alarm", { method: "POST", body: { level, pin } }), "Alarme : " + (LABELS[level] || level).toLowerCase());
  }));

  const testMail = $("#test-mail");
  if (testMail) testMail.addEventListener("click", () => act(() => api("/api/test-email", { method: "POST" }), "E-mail de test envoyé"));
  const demoTrigger = $("#demo-trigger");
  if (demoTrigger) demoTrigger.addEventListener("click", () => act(() => api("/api/demo/trigger", { method: "POST" }), "Intrusion simulée"));

  refresh();
  setInterval(refresh, 10000);
})();
