"""Mobile ticket page behind the receipt's QR code (/t/<id>): the ticket and one big "Mark as fixed" button.

Server-rendered and without login or JavaScript, so it opens fast on any phone on the shop floor.
"""
from html import escape


def _e(value):
    return escape(str(value or ""))


def render(result, asset_version=""):
    t = result["ticket"]
    tid = result["id"]
    prio = t.get("priority", "NORMAL")
    steps = list(t.get("steps", []))
    safety = t.get("safety_short") or (steps[0] if steps else "")
    rest = steps[1:]
    code_cause = " · ".join(x for x in (t.get("error_code"), t.get("cause")) if x)
    part = t.get("part_needed") or "none"
    fixed = result.get("status") == "fixed"

    rows = []
    if t.get("unconfirmed"):
        rows.append(f'<p class="tk-warn">UNCONFIRMED – verify machine on site. {_e(t["unconfirmed"])}</p>')
    if t.get("report"):
        rows.append(f'<p class="tk-report">Report: “{_e(t["report"])}”</p>')
    if code_cause:
        rows.append(f'<p class="tk-cause">{_e(code_cause)}</p>')
    if safety:
        rows.append(f'<p class="tk-safety">{_e(safety)}</p>')
    if rest:
        rows.append('<ol class="tk-steps">' + "".join(f"<li>{_e(s)}</li>" for s in rest) + "</ol>")
    if part.lower() != "none":
        rows.append(f'<div class="tk-part"><span>Part</span><strong>{_e(part)}</strong>'
                    f'<span class="tk-shelf">{_e(t.get("location"))}</span>'
                    + (f'<span>{_e(t["stock"])}</span>' if t.get("stock") else "") + "</div>")
    if t.get("recurring_fault"):
        rows.append(f'<p class="tk-recurring">Recurring fault: {_e(t["recurring_fault"])}</p>')

    if fixed:
        action = f'<p class="tk-fixed" role="status">FIXED · {_e(result.get("fixed_at"))}</p>'
    else:
        action = (f'<form method="post" action="/t/{tid}/fixed">'
                  '<button class="tk-fix" type="submit">Mark as fixed</button></form>')

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ticket #{tid} – PaperOps</title>
  <link rel="icon" href="/favicon.ico?v={asset_version}" sizes="any">
  <link rel="stylesheet" href="/static/style.css?v={asset_version}">
</head>
<body class="ticket-page">
  <main class="tk">
    <p class="tk-brand">PaperOps · Repair ticket</p>
    <div class="tk-head">
      <h1>#{tid}</h1>
      <span class="tp p-{prio.lower()}">{_e(prio)}</span>
      {'<span class="tp tk-badge-fixed">FIXED</span>' if fixed else ""}
    </div>
    <p class="tk-time">{_e(result.get("created"))}</p>
    <h2 class="tk-machine">{_e(t.get("machine", "UNKNOWN"))}</h2>
    <p class="tk-where">{_e(t.get("machine_location"))}</p>
    {"".join(rows)}
    {action}
    <p class="tk-more"><a href="/?ticket={tid}">Open in PaperOps</a></p>
  </main>
</body>
</html>"""


def not_found(tid, asset_version=""):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ticket not found – PaperOps</title>
  <link rel="stylesheet" href="/static/style.css?v={asset_version}">
</head>
<body class="ticket-page">
  <main class="tk">
    <p class="tk-brand">PaperOps · Repair ticket</p>
    <h1>Ticket #{_e(tid)} not found</h1>
    <p class="tk-time">The demo keeps tickets in memory, so a restart or "Reset demo" clears them.</p>
    <p class="tk-more"><a href="/">Open PaperOps</a></p>
  </main>
</body>
</html>"""
