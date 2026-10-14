// Minimal ESC/POS interpreter for the printer simulator.
// Handles exactly the subset app/escpos.py emits: init, align, bold, invert, size, QR, cut, text, LF.
// parse(bytes) -> { lines: [{align, segments:[{text,bold,invert,double,tall}]} | {qr:string} | {cut:true}],
//                   commands: [{hex, label}] }
const EscPos = (() => {
  const hex = (arr) => Array.from(arr, (b) => b.toString(16).padStart(2, "0").toUpperCase()).join(" ");

  function parse(bytes) {
    const lines = [];
    const commands = [];
    const st = { align: "left", bold: false, invert: false, double: false, tall: false };
    let segs = [];
    let text = "";
    let qrData = "";

    const flushText = () => {
      if (!text) return;
      segs.push({ text, bold: st.bold, invert: st.invert, double: st.double, tall: st.tall });
      commands.push({ hex: "", label: `TEXT  "${text}"` });
      text = "";
    };
    const newline = () => {
      flushText();
      lines.push({ align: st.align, segments: segs });
      segs = [];
    };
    const cmd = (start, len, label) => commands.push({ hex: hex(bytes.slice(start, start + len)), label });

    let i = 0;
    while (i < bytes.length) {
      const b = bytes[i];
      if (b === 0x1b) {                       // ESC
        const c = bytes[i + 1];
        flushText();
        if (c === 0x40) { Object.assign(st, { align: "left", bold: false, invert: false, double: false, tall: false }); cmd(i, 2, "ESC @      initialise printer"); i += 2; }
        else if (c === 0x61) { const n = bytes[i + 2]; st.align = ["left", "center", "right"][n] || "left"; cmd(i, 3, `ESC a ${n}    align ${st.align}`); i += 3; }
        else if (c === 0x45) { st.bold = !!bytes[i + 2]; cmd(i, 3, `ESC E ${bytes[i + 2]}    bold ${st.bold ? "on" : "off"}`); i += 3; }
        else if (c === 0x33) { cmd(i, 3, `ESC 3 ${bytes[i + 2]}   line spacing ${bytes[i + 2]} dots`); i += 3; }
        else if (c === 0x32) { cmd(i, 2, "ESC 2      default line spacing"); i += 2; }
        else { cmd(i, 2, "ESC ?      (unknown)"); i += 2; }
      } else if (b === 0x1d) {                // GS
        const c = bytes[i + 1];
        flushText();
        if (c === 0x42) { st.invert = !!bytes[i + 2]; cmd(i, 3, `GS B ${bytes[i + 2]}     invert ${st.invert ? "on" : "off"}`); i += 3; }
        else if (c === 0x21) {
          const n = bytes[i + 2];
          st.double = (n & 0xf0) !== 0; st.tall = (n & 0x0f) !== 0;
          cmd(i, 3, `GS ! 0x${n.toString(16).padStart(2, "0")}  size ${st.double ? "double" : st.tall ? "tall" : "normal"}`);
          i += 3;
        } else if (c === 0x28 && bytes[i + 2] === 0x6b) {   // GS ( k  (QR code)
          const len = bytes[i + 3] + bytes[i + 4] * 256;
          const fn = bytes[i + 6];
          if (fn === 0x50) {
            qrData = String.fromCharCode(...bytes.slice(i + 8, i + 5 + len));
            cmd(i, 8, `GS ( k      QR store "${qrData}"`);
          } else if (fn === 0x51) {
            lines.push({ qr: qrData, align: st.align });
            cmd(i, 5 + len, "GS ( k      QR print");
          } else {
            cmd(i, 5 + len, { 0x41: "GS ( k      QR model 2", 0x43: "GS ( k      QR module size", 0x45: "GS ( k      QR error correction" }[fn] || "GS ( k      QR setting");
          }
          i += 5 + len;
        } else if (c === 0x56) { lines.push({ cut: true }); cmd(i, 4, "GS V A 3   feed and cut paper"); i += 4; }
        else { cmd(i, 2, "GS ?       (unknown)"); i += 2; }
      } else if (b === 0x0a) {
        flushText();
        cmd(i, 1, "LF         line feed");
        newline();
        i += 1;
      } else {
        text += String.fromCharCode(b);
        i += 1;
      }
    }
    flushText();
    if (segs.length) newline();
    return { lines, commands };
  }

  function fromBase64(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  return { parse, fromBase64 };
})();
