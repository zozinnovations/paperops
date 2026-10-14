// PaperOps UI: push-to-talk -> /api/ticket (NDJSON progress stream) -> virtual thermal receipt.
(() => {
  const $ = (id) => document.getElementById(id);
  const STEPS = ["listening", "understanding", "manual", "stock", "printing"];
  const MAX_RECORD_MS = 30000;
  const MIN_RECORD_MS = 400;

  let busy = false;
  let current = null; // last result shown on the receipt

  // ---------- status header ----------
  async function loadStatus() {
    try {
      const s = await (await fetch("/api/status")).json();
      const p = $("printer-status");
      p.dataset.state = s.printer;
      p.querySelector(".label").textContent =
        s.printer === "connected" ? "Printer: connected" : s.printer === "offline" ? "Printer: offline (simulator)" : "Printer: simulator";
      $("model-status").textContent = s.models.length ? `AI on AMD: ${s.models[0]}` : "AI on AMD: connecting…";
      if (!s.models.length) setTimeout(loadStatus, 3000);
    } catch {
      setTimeout(loadStatus, 5000);
    }
  }

  // ---------- progress ----------
  function resetProgress() {
    document.querySelectorAll("#progress li").forEach((li) => { li.dataset.state = ""; li.querySelector(".ms").textContent = ""; });
    $("total").hidden = true;
    $("error").hidden = true;
  }
  function setStep(step, state, ms) {
    const li = document.querySelector(`#progress li[data-step="${step}"]`);
    if (!li) return;
    li.dataset.state = state;
    if (ms !== undefined) li.querySelector(".ms").textContent = ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
    if (state === "skipped") li.querySelector(".ms").textContent = "text input";
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
      t.innerHTML = `<strong>${(total / 1000).toFixed(1)} s</strong> from report to ticket` +
        (ev.replay
          ? `<span class="via">Live AI was slow or unavailable: showing a recorded real run (${ev.model})</span>`
          : `<span class="via">${ev.model}${ev.attempts && ev.attempts.length ? ` · fallback after ${ev.attempts.length} failed` : ""}</span>`);
      t.hidden = false;
      showTicket(ev, true);
      loadRecent();
      return;
    }
    if (ev.transcript !== undefined) showHeard(ev.transcript);
    setStep(ev.step, ev.status, ev.ms);
  }

  // ---------- receipt ----------
  const PRIO_CLASS = (text) => (/CRITICAL/.test(text) ? "prio-critical" : /HIGH/.test(text) ? "prio-high" : /NORMAL/.test(text) ? "prio-normal" : "");

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
    if (fullInvert) {
      // inverted lines print black; the simulator colours the priority bar like the design concept
      el.classList.add("inv", PRIO_CLASS(el.textContent) || "inv-dark");
    }
    if (line.segments.some((s) => s.double)) el.classList.add("dbl-line");
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
    if (animate && window.matchMedia("(max-width: 860px)").matches) paper.scrollIntoView({ behavior: "smooth", block: "start" });
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
    history.replaceState(null, "", `?ticket=${result.id}`);
  }

  // Scale the font so exactly 48 monospace columns fit the paper (character width varies by font).
  function fitPaper() {
    const paper = $("paper");
    paper.style.fontSize = "";
    const probe = document.createElement("span");
    probe.textContent = "0".repeat(48);
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre";
    $("receipt").appendChild(probe);
    const avail = paper.clientWidth - parseFloat(getComputedStyle(paper).paddingLeft) * 2;
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

  // ---------- samples + text ----------
  let sampleList = [];
  let player = null;

  // Plays the recording out loud (so judges hear the report) and sends the same file through the pipeline.
  function playSample(s) {
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
    submit(f);
  }
  $("demo").addEventListener("click", () => {
    const s = sampleList.find((x) => x.id === "T01");
    if (s) playSample(s);
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
        b.title = s.transcript;
        b.innerHTML = `<span class="sid">${s.id}</span><span class="sdesc">${s.difficulty.replace(/\s*->.*$/, "").replace(/\(.*\)/, "")}</span>`;
        b.addEventListener("click", () => playSample(s));
        box.appendChild(b);
      }
    } catch { box.textContent = "Samples unavailable."; }
  }
  $("text-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("text-input").value.trim();
    if (!text) return;
    const f = new FormData();
    f.append("text", text);
    submit(f);
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

  async function startRecording() {
    if (busy || recorder) return;
    wantRecording = true;
    try {
      if (!stream) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      }
    } catch (err) {
      wantRecording = false;
      showError(window.isSecureContext ? "Microphone access was blocked. Allow it in the browser, or use text input."
        : "The microphone needs HTTPS. Use text input or the samples.");
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

  // ---------- start ----------
  loadStatus();
  loadSamples();
  loadRecent();
  const qs = new URLSearchParams(location.search).get("ticket");
  if (qs) openTicket(qs);
})();
