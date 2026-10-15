// PaperOps UI: push-to-talk -> /api/ticket (NDJSON progress stream) -> virtual thermal receipt.
(() => {
  const $ = (id) => document.getElementById(id);
  const STEPS = ["listening", "understanding", "manual", "stock", "printing"];
  const MAX_RECORD_MS = 30000;
  const MIN_RECORD_MS = 400;

  let busy = false;
  let fromJudges = false;  // last request came from the judges' panel (sample, demo, text)

  // keeps ?mode=floor (shop-floor view) when the ticket id or the tab changes
  function setUrl({ ticket, hash } = {}) {
    const q = new URLSearchParams(location.search);
    if (ticket === null) q.delete("ticket");
    else if (ticket !== undefined) q.set("ticket", ticket);
    const qs = q.toString();
    history.replaceState(null, "", location.pathname + (qs ? `?${qs}` : "") + (hash !== undefined ? hash : location.hash));
  }
  let primaryModel = null;
  let current = null; // last result shown on the receipt

  // ---------- status header ----------
  async function loadStatus() {
    try {
      const s = await (await fetch("/api/status")).json();
      const p = $("printer-status");
      p.dataset.state = s.printer;
      p.querySelector(".label").textContent =
        s.printer === "connected" ? "Printer: connected" : s.printer === "offline" ? "Printer: offline (simulator)" : "Printer: simulator";
      const setupBtn = $("printer-settings");
      setupBtn.disabled = !s.printer_setup;
      setupBtn.title = s.printer_setup ? "Printer address, port and test print"
        : "Disabled on the hosted demo. On a local install set ALLOW_PRINTER_SETUP=1.";
      if (s.models.length) primaryModel = s.models[0];
      // claim a model only if it answered last; before the first ticket the primary, unless it is failing now
      if (s.last_model) setModelBadge(s.last_model, s.last_replay);
      else if (s.primary_down) setModelBadge(null);
      else if (primaryModel) setModelBadge(primaryModel);
      else $("model-status").textContent = "AI: connecting…";
      if (!s.models.length) setTimeout(loadStatus, 3000);
    } catch {
      setTimeout(loadStatus, 5000);
    }
  }

  // "Gemma 4" for Gemma, otherwise the short model name (e.g. "MiMo" after a fallback)
  // short line in the header, details in the tooltip
  function setModelBadge(model, replay) {
    const badge = $("model-status");
    if (!model) {  // no answer yet and the primary model is unavailable: say nothing about a model
      badge.textContent = "AI on AMD GPUs";
      badge.title = "AMD Token Factory";
      return;
    }
    const plain = String(model).split("/").pop();  // "self-dploy/Gemma-4-31B-IT" -> "Gemma-4-31B-IT"
    const name = /^Gemma-4/i.test(plain) ? "Gemma 4" : plain.replace(/-V?[\d.]+.*$/i, "");  // "MiMo-V2.6-Flash" -> "MiMo"
    badge.textContent = `AI: ${name} on AMD${replay ? " (replay)" : ""}`;
    badge.title = `${model} on AMD GPUs via AMD Token Factory` +
      (primaryModel && model !== primaryModel ? ` (fallback for ${primaryModel})` : "") +
      (replay ? " - replay of a recorded live run" : "");
  }

  // ---------- progress ----------
  function resetProgress() {
    document.querySelectorAll("#progress li").forEach((li) => { li.dataset.state = ""; li.querySelector(".ms").textContent = ""; });
    $("total").hidden = true;
    $("error").hidden = true;
    $("clarify").hidden = true;
  }
  function setStep(step, state, ms, note) {
    const li = document.querySelector(`#progress li[data-step="${step}"]`);
    if (!li) return;
    li.dataset.state = state;
    if (ms !== undefined) li.querySelector(".ms").textContent = ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
    if (note) li.querySelector(".ms").textContent = note;
  }
  function showError(msg) {
    const e = $("error");
    e.textContent = msg;
    e.hidden = false;
    document.querySelectorAll('#progress li[data-state="active"]').forEach((li) => (li.dataset.state = "failed"));
  }
  function showHeard(text) {
    const h = $("heard");
    h.hidden = !text;
    h.textContent = text ? `“${text}”` : "";
  }

  // smooth scrolling, but not for people who asked the OS for reduced motion
  function scrollToView(el, block) {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block });
  }

  // Judges' panel: the progress card is often out of view, so bring it in at once and mark the clicked
  // button as working until the result is there.
  async function submitFromJudges(form, button) {
    if (busy) return;
    fromJudges = true;
    scrollToView($("progress"), "center");
    const label = button ? button.innerHTML : "";
    if (button) {
      button.disabled = true;
      button.classList.add("is-working");
      button.setAttribute("aria-busy", "true");
      button.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span>Working…';
    }
    try {
      await submit(form);
    } finally {
      if (button) {
        button.innerHTML = label;
        button.disabled = false;
        button.classList.remove("is-working");
        button.removeAttribute("aria-busy");
      }
    }
  }

  // ---------- request ----------
  async function submit(form) {
    if (busy) return;
    busy = true;
    document.body.classList.add("busy");
    resetProgress();
    showHeard(form.get("text") || "");
    const startedAt = performance.now();
    try {
      const res = await fetch("/api/ticket", { method: "POST", body: form });
      if (!res.ok) {
        const msg = await res.json().then((j) => j.detail).catch(() => res.statusText);
        throw new Error(msg || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (line) handleEvent(JSON.parse(line), startedAt);
        }
      }
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      busy = false;
      document.body.classList.remove("busy");
    }
  }

  function handleEvent(ev, startedAt) {
    if (ev.step === "error") return showError(ev.message);
    if (ev.step === "result") {
      const total = ev.total_ms;
      const t = $("total");
      t.innerHTML = ev.replay
        ? `<strong>${(total / 1000).toFixed(1)} s</strong> Replay of a recorded live run` +
          `<span class="via">${ev.model} · live AI did not answer in time, so a recorded real run is shown with its original timing</span>`
        : `<strong>${(total / 1000).toFixed(1)} s</strong> from report to ticket` +
          `<span class="via">${ev.model}${primaryModel && ev.model !== primaryModel ? ` (fallback: ${primaryModel} was too slow or failed)` : ""}</span>`;
      t.hidden = false;
      setModelBadge(ev.model, ev.replay);
      showTicket(ev, true);
      loadRecent();
      loadMachines();
      return;
    }
    if (ev.step === "clarify") return showClarify(ev);
    if (ev.transcript !== undefined) showHeard(ev.transcript);
    setStep(ev.step, ev.status, ev.ms, ev.note);
  }

  // ---------- nothing recognised: ask back instead of printing ----------
  let draftId = null;
  function showClarify(ev) {
    draftId = ev.draft;
    $("clarify-q").textContent = ev.question;
    $("print-anyway").disabled = false;
    $("clarify").hidden = false;
    setModelBadge(ev.model, ev.replay);
    clearReceipt("Nothing printed – see the question above.");
    // started from the judges' panel (often below or beside): bring the question into view
    if (fromJudges) scrollToView($("clarify"), "center");
  }
  $("print-anyway").addEventListener("click", async () => {
    if (!draftId) return;
    $("print-anyway").disabled = true;
    try {
      const res = await fetch(`/api/drafts/${draftId}/print`, { method: "POST" });
      if (!res.ok) throw new Error(await res.json().then((j) => j.detail).catch(() => res.statusText));
      const r = await res.json();
      draftId = null;
      $("clarify").hidden = true;
      setStep("printing", "done", r.timings_ms.printing);
      showTicket(r, true);
      loadRecent();
      loadMachines();
    } catch (err) {
      $("print-anyway").disabled = false;
      showError(err.message || String(err));
    }
  });

  // ---------- receipt ----------

  function renderLine(line) {
    if (line.cut) {
      const el = document.createElement("div");
      el.className = "cut";
      return el;
    }
    if (line.qr !== undefined) {
      const el = document.createElement("div");
      el.className = `line qr align-${line.align}`;
      if (window.qrcode) {
        const q = qrcode(0, "M");
        q.addData(line.qr);
        q.make();
        el.innerHTML = q.createImgTag(4, 0, "QR code to close the ticket"); // <img> so html2canvas can export it
      } else {
        el.textContent = `[QR ${line.qr}]`;
      }
      return el;
    }
    const el = document.createElement("div");
    el.className = `line align-${line.align}`;
    if (!line.segments.length) el.innerHTML = "&nbsp;";
    let fullInvert = line.segments.length > 0;
    for (const s of line.segments) {
      const span = document.createElement("span");
      span.textContent = s.text;
      if (s.bold) span.classList.add("b");
      if (s.double) span.classList.add("dbl");
      else if (s.tall) span.classList.add("tall");
      if (!s.invert) fullInvert = false;
      el.appendChild(span);
    }
    if (fullInvert) el.classList.add("inv");  // black on white, exactly like the thermal printer
    if (line.segments.some((s) => s.double)) el.classList.add("dbl-line");
    if (line.segments.some((s) => s.tall && !s.double)) el.classList.add("tall-line");
    return el;
  }

  function showTicket(result, animate) {
    current = result;
    const bytes = EscPos.fromBase64(result.escpos);
    const { lines, commands } = EscPos.parse(bytes);
    const receipt = $("receipt");
    const paper = $("paper");
    receipt.innerHTML = "";
    paper.classList.remove("idle");
    paper.classList.toggle("animate", animate);
    fitPaper();

    const els = lines.map(renderLine);
    // stacked layout on phones: bring the receipt into view when it prints
    if (animate && window.matchMedia("(max-width: 860px)").matches) scrollToView(paper, "start");
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      els.forEach((el) => receipt.appendChild(el));
    } else {
      // slide out of the slot line by line
      els.forEach((el, i) => setTimeout(() => {
        el.classList.add("in");
        receipt.appendChild(el);
      }, i * 45));
    }

    $("cmd-list").textContent = commands.map((c) => `${c.hex.padEnd(26)} ${c.label}`).join("\n") +
      `\n\n${bytes.length} bytes`;
    $("download").disabled = false;
    $("print").disabled = false;
    setUrl({ ticket: result.id });
  }

  // Scale the font so exactly 48 monospace columns fit the paper (character width varies by font).
  function fitPaper() {
    const paper = $("paper");
    paper.style.fontSize = "";
    const probe = document.createElement("span");
    probe.textContent = "0".repeat(48);
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre";
    $("receipt").appendChild(probe);
    const body = paper.querySelector(".paper-body");
    const avail = body.clientWidth - parseFloat(getComputedStyle(body).paddingLeft) * 2;
    const need = probe.getBoundingClientRect().width;
    probe.remove();
    if (need > avail) paper.style.fontSize = `${parseFloat(getComputedStyle(paper).fontSize) * avail / need}px`;
  }
  window.addEventListener("resize", fitPaper);

  // ---------- recent tickets ----------
  async function loadRecent() {
    try {
      const list = await (await fetch("/api/tickets")).json();
      const ul = $("recent");
      ul.innerHTML = "";
      if (!list.length) {
        ul.innerHTML = '<li class="empty">No tickets yet.</li>';
        return;
      }
      for (const t of list.slice(0, 8)) {
        const li = document.createElement("li");
        const b = document.createElement("button");
        b.type = "button";
        b.innerHTML = `<span class="tid">#${t.id}</span><span class="tm">${t.machine_id}${t.error_code ? " · " + t.error_code : ""}</span>` +
          `<span class="tp p-${t.priority.toLowerCase()}">${t.priority}</span>`;
        b.addEventListener("click", () => openTicket(t.id));
        li.appendChild(b);
        ul.appendChild(li);
      }
    } catch { /* not critical */ }
  }
  async function openTicket(id) {
    const res = await fetch(`/api/tickets/${id}`);
    if (!res.ok) return;
    const r = await res.json();
    showHeard(r.transcript);
    showTicket(r, false);
  }

  // ---------- machine health ----------
  async function loadMachines() {
    try {
      const h = await (await fetch("/api/machines")).json();
      const asOf = new Date(h.as_of).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
      $("health-sub").textContent = `Demo history (fictional data): ${h.window_days} days up to ${asOf}, ` +
        `plus tickets printed today · outlook: ${h.label}`;
      const table = $("health-table");
      table.querySelectorAll("tbody").forEach((b) => b.remove());
      for (const m of h.machines) {
        const body = document.createElement("tbody");
        // only a fault that came back is worth naming here
        const top = m.top_fault && m.top_fault.count >= 2 ? `${m.top_fault.code} <span class="muted">${m.top_fault.count}×</span>` : "–";
        const hrs = m.downtime_min >= 60 ? `${(m.downtime_min / 60).toFixed(1)} h` : `${m.downtime_min} min`;
        body.innerHTML =
          `<tr class="m-row"><th scope="row"><span class="m-id">${m.machine_id}</span><span class="m-name">${m.name.replace(m.machine_id, "").trim()}</span></th>` +
          `<td>${m.reports}${m.new_reports ? ` <span class="muted">(+${m.new_reports} new)</span>` : ""}</td><td>${hrs}</td><td>${top}</td></tr>` +
          `<tr class="o-row"><td colspan="4"><ul class="outlook">${m.outlook.map((o) =>
            `<li class="o-${o.level}"><span class="o-dot" aria-hidden="true"></span>${o.text}</li>`).join("")}</ul></td></tr>`;
        table.appendChild(body);
      }
    } catch { /* not critical */ }
  }

  // ---------- tabs: Dispatcher | Machine health ----------
  const TABS = { dispatch: ["tab-dispatch", "view-dispatch"], health: ["tab-health", "view-health"] };
  function showTab(name, focus) {
    for (const [key, [tabId, viewId]] of Object.entries(TABS)) {
      const on = key === name;
      $(tabId).setAttribute("aria-selected", String(on));
      $(tabId).tabIndex = on ? 0 : -1;
      $(viewId).hidden = !on;
    }
    if (focus) $(TABS[name][0]).focus();
    if (name === "health") loadMachines();
    setUrl({ hash: name === "health" ? "#health" : "" });
  }
  $("tab-dispatch").addEventListener("click", () => showTab("dispatch"));
  $("tab-health").addEventListener("click", () => showTab("health"));
  document.querySelector(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    showTab($("tab-health").getAttribute("aria-selected") === "true" ? "dispatch" : "health", true);
  });

  // ---------- printer settings (local installs only: ALLOW_PRINTER_SETUP=1) ----------
  const dlg = $("printer-dialog");
  const dlgStatus = (text, kind) => { $("printer-dlg-status").textContent = text; $("printer-dlg-status").dataset.kind = kind || ""; };
  const STATE_TEXT = { connected: "Printer connected.", offline: "Printer not reachable - check address, port and power.",
                       simulator: "No printer set - tickets appear in the on-screen simulator." };
  async function printerCall(url, body) {
    const res = await fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
                                      : url.endsWith("/test") ? { method: "POST" } : {});
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.detail || res.statusText);
    return json;
  }
  $("printer-settings").addEventListener("click", async () => {
    dlgStatus("Checking…");
    dlg.showModal();
    try {
      const p = await printerCall("/api/printer");
      $("printer-host").value = p.host;
      $("printer-port").value = p.port;
      dlgStatus(STATE_TEXT[p.status] || p.status, p.status === "connected" ? "ok" : p.status === "offline" ? "bad" : "");
    } catch (e) { dlgStatus(e.message, "bad"); }
    $("printer-host").focus();
  });
  $("printer-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    dlgStatus("Saving…");
    try {
      const p = await printerCall("/api/printer", { host: $("printer-host").value.trim(), port: Number($("printer-port").value) });
      dlgStatus(`Saved. ${STATE_TEXT[p.status] || p.status}`, p.status === "connected" ? "ok" : p.status === "offline" ? "bad" : "");
      loadStatus();
    } catch (err) { dlgStatus(err.message, "bad"); }
  });
  $("printer-test").addEventListener("click", async () => {
    dlgStatus("Sending test page…");
    try {
      const r = await printerCall("/api/printer/test");
      dlgStatus(r.message, r.result === "printed" ? "ok" : r.result === "simulator" ? "" : "bad");
      loadStatus();
    } catch (err) { dlgStatus(err.message, "bad"); }
  });
  $("printer-close").addEventListener("click", () => dlg.close());

  function clearReceipt(message) {
    current = null;
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent = message;
    $("receipt").replaceChildren(p);
    $("paper").classList.add("idle");
    $("cmd-list").textContent = "";
    $("download").disabled = $("print").disabled = true;
    setUrl({ ticket: null });  // a reload must not bring the old ticket back
  }

  // ---------- reset demo (clean video takes) ----------
  $("reset-demo").addEventListener("click", async () => {
    if (busy) return;
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) return showError("Reset failed - please try again.");
    clearReceipt("Your repair ticket prints here.");
    resetProgress();
    showHeard("");
    loadRecent();
    loadMachines();
  });

  // ---------- what judges can say (from the machine manuals) ----------
  async function loadCatalog() {
    try {
      const machines = await (await fetch("/api/catalog")).json();
      const tbody = document.querySelector("#catalog tbody");
      for (const m of machines) {
        const tr = document.createElement("tr");
        const said = m.aliases.filter((a) => /[a-z]/.test(a) && a === a.toLowerCase()).slice(0, 2);
        tr.innerHTML = `<th scope="row"></th><td></td><td></td>`;
        tr.children[0].textContent = m.name;
        tr.children[1].textContent = (said.length ? said : m.aliases.slice(0, 2)).map((a) => `“${a}”`).join(", ");
        tr.children[2].textContent = m.faults.map((f) => `${f.code} ${f.title.toLowerCase()}`).join("; ");
        tbody.appendChild(tr);
      }
    } catch { /* not critical */ }
  }

  // ---------- samples + text ----------
  let sampleList = [];
  let player = null;

  // Plays the recording out loud (so judges hear the report) and sends the same file through the pipeline.
  function playSample(s, button) {
    if (busy) return;
    const f = new FormData();
    if (s.audio) {
      f.append("sample", s.id);
      if (player) player.pause();
      player = new Audio(s.audio);
      player.play().catch(() => {}); // autoplay may be blocked - the request still runs
    } else {
      f.append("text", s.transcript);
    }
    submitFromJudges(f, button);
  }
  $("demo").addEventListener("click", (e) => {
    const s = sampleList.find((x) => x.id === "T01");
    if (s) playSample(s, e.currentTarget);
  });

  async function loadSamples() {
    const box = $("samples");
    try {
      const samples = await (await fetch("/api/samples")).json();
      sampleList = samples;
      for (const s of samples) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "sample";
        b.title = `${s.id}: "${s.transcript}"`;  // test-case id only as tooltip
        b.textContent = s.label;
        b.addEventListener("click", () => playSample(s, b));
        (s.featured ? box : $("samples-more")).appendChild(b);
      }
    } catch { box.textContent = "Samples unavailable."; }
  }
  $("text-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("text-input").value.trim();
    if (!text) return;
    const f = new FormData();
    f.append("text", text);
    submitFromJudges(f, e.submitter || $("text-form").querySelector('button[type="submit"]'));
  });

  // ---------- push to talk ----------
  const ptt = $("ptt");
  let stream = null, recorder = null, chunks = [], recStart = 0, timerId = null, wantRecording = false;

  function pickMime() {
    for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
    }
    return "";
  }

  // Why getUserMedia failed, in words that say what to do. The browser often shows no prompt at all:
  // the site was blocked before, the OS denies the browser the microphone, or the page is in a frame.
  async function micErrorText(err) {
    console.warn("microphone:", err && err.name, err && err.message);
    const fallback = " Or use the text input or the samples.";
    if (!window.isSecureContext || !navigator.mediaDevices) return "The microphone needs HTTPS." + fallback;
    // the site permission first: some browsers report a blocked site as "no device"
    let state = "";
    try { state = (await navigator.permissions.query({ name: "microphone" })).state; } catch { /* Firefox/Safari */ }
    if (window.top !== window.self) return "The microphone does not work inside this embedded view. Open PaperOps in its own browser tab." + fallback;
    if (state === "denied") {
      return "Microphone blocked for this site. Click the icon left of the address bar → Microphone → Allow, then reload the page." + fallback;
    }
    const name = err && err.name;
    if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone found. Connect one and try again." + fallback;
    if (name === "NotReadableError" || name === "AbortError") return "The microphone is in use by another app (e.g. a video call). Close it and try again." + fallback;
    // site not blocked, yet denied without a prompt: the operating system blocks the browser
    return "Your system blocks the microphone for this browser. Windows: Settings → Privacy & security → Microphone → " +
      "allow access for apps and desktop apps. macOS: System Settings → Privacy & Security → Microphone → turn on your browser." + fallback;
  }

  async function startRecording() {
    if (busy || recorder) return;
    fromJudges = false;
    wantRecording = true;
    try {
      if (!stream) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      }
    } catch (err) {
      wantRecording = false;
      showError(await micErrorText(err));
      return;
    }
    if (!wantRecording) return; // released while the permission prompt was open
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = onRecorded;
    recorder.start();
    recStart = performance.now();
    ptt.classList.add("recording");
    ptt.setAttribute("aria-pressed", "true");
    ptt.querySelector(".ptt-label").textContent = "LISTENING…";
    resetProgress();
    showHeard("");
    setStep("listening", "active");
    timerId = setInterval(() => {
      const ms = performance.now() - recStart;
      $("ptt-timer").textContent = `${(ms / 1000).toFixed(1)} s`;
      if (ms > MAX_RECORD_MS) stopRecording();
    }, 100);
  }

  function stopRecording() {
    wantRecording = false;
    if (!recorder) return;
    clearInterval(timerId);
    $("ptt-timer").textContent = "";
    ptt.classList.remove("recording");
    ptt.setAttribute("aria-pressed", "false");
    ptt.querySelector(".ptt-label").textContent = "HOLD TO SPEAK";
    recorder.stop();
  }

  function onRecorded() {
    const duration = performance.now() - recStart;
    const type = recorder.mimeType || "audio/webm";
    recorder = null;
    if (duration < MIN_RECORD_MS) {
      setStep("listening", "");
      showError("Hold the button while you speak.");
      return;
    }
    const blob = new Blob(chunks, { type });
    const f = new FormData();
    f.append("audio", blob, type.includes("mp4") ? "report.m4a" : "report.webm");
    submit(f);
  }

  ptt.addEventListener("pointerdown", (e) => { e.preventDefault(); ptt.setPointerCapture(e.pointerId); startRecording(); });
  ptt.addEventListener("pointerup", stopRecording);
  ptt.addEventListener("pointercancel", stopRecording);
  ptt.addEventListener("contextmenu", (e) => e.preventDefault());

  const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
  window.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.repeat || typing(document.activeElement)) return;
    e.preventDefault();
    startRecording();
  });
  window.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || typing(document.activeElement)) return;
    e.preventDefault();
    stopRecording();
  });
  window.addEventListener("blur", stopRecording);

  // ---------- download / print / commands ----------
  $("download").addEventListener("click", async () => {
    if (!current || !window.html2canvas) return;
    const canvas = await html2canvas($("paper"), { backgroundColor: null, scale: 2 });
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `paperops-ticket-${current.id}.png`;
    a.click();
  });
  $("print").addEventListener("click", () => window.print());
  $("show-cmds").addEventListener("change", (e) => { $("commands").hidden = !e.target.checked; });

  // touch devices have no Space bar or foot pedal
  if (window.matchMedia("(pointer: coarse)").matches && !window.matchMedia("(pointer: fine)").matches) {
    $("ptt-hint").textContent = "Hold the button while you speak.";
  }

  // ---------- start ----------
  loadStatus();
  loadSamples();
  loadRecent();
  loadMachines();
  loadCatalog();
  if (location.hash === "#health") showTab("health");
  const qs = new URLSearchParams(location.search).get("ticket");
  if (qs) openTicket(qs);
})();
