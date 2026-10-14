"""Ticket -> ESC/POS bytes for an 80 mm thermal printer (48 columns, font A).

The on-screen simulator renders exactly these bytes, so the output is ASCII only:
every ESC/POS printer prints ASCII, whatever code page it is set to.
"""
import textwrap
import unicodedata

WIDTH = 48

ESC, GS, LF = b"\x1b", b"\x1d", b"\n"
INIT = ESC + b"@"
ALIGN_LEFT, ALIGN_CENTER = ESC + b"a\x00", ESC + b"a\x01"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
INVERT_ON, INVERT_OFF = GS + b"B\x01", GS + b"B\x00"
SIZE_NORMAL, SIZE_DOUBLE, SIZE_TALL = GS + b"!\x00", GS + b"!\x11", GS + b"!\x01"
LINE_TIGHT, LINE_DEFAULT = ESC + b"3\x18", ESC + b"2"  # 24-dot spacing = font A height -> solid inverted blocks
CUT = GS + b"VA\x03"  # partial cut after feeding 3 lines

_ASCII = {"–": "-", "—": "-", "·": "-", "°": " deg", "µ": "u", "Ø": "D", "ø": "d", "×": "x", "’": "'", "“": '"', "”": '"',
          "⚠": "!", "…": "..."}


def ascii_text(s):
    s = "".join(_ASCII.get(ch, ch) for ch in str(s))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _line(s=""):
    return ascii_text(s).encode("ascii") + LF


def _wrap(s, width=WIDTH, indent=""):
    return textwrap.wrap(ascii_text(s), width=width, subsequent_indent=indent) or [""]


def _qr(data):
    d = ascii_text(data).encode("ascii")
    n = len(d) + 3
    return (GS + b"(k\x04\x001A2\x00"           # model 2
            + GS + b"(k\x03\x001C\x06"          # module size 6
            + GS + b"(k\x03\x001E1"             # error correction M
            + GS + b"(k" + bytes([n % 256, n // 256]) + b"1P0" + d  # store data
            + GS + b"(k\x03\x001Q0")            # print


def render(ticket, ticket_id=None, created=None, footer=None):
    out = [INIT, ALIGN_CENTER, SIZE_DOUBLE, BOLD_ON, _line("PAPEROPS"), BOLD_OFF, SIZE_NORMAL]
    out.append(_line(f"Repair ticket #{ticket_id}" + (f"  {created}" if created else "")))
    out.append(_line("-" * WIDTH))

    # priority bar: inverted, double size -> 24 columns
    prio = ticket.get("priority", "NORMAL")
    out += [SIZE_DOUBLE, INVERT_ON, BOLD_ON, _line(f"{prio} PRIORITY".center(WIDTH // 2)), BOLD_OFF, INVERT_OFF,
            SIZE_NORMAL, ALIGN_LEFT, LF]

    out += [BOLD_ON, *map(_line, _wrap(ticket.get("machine", "UNKNOWN"))), BOLD_OFF]
    meta = " | ".join(x for x in [ticket.get("error_code"), ticket.get("machine_location")] if x)
    if meta:
        out.append(_line(meta))
    out += map(_line, _wrap(ticket.get("cause", "")))
    if ticket.get("likely_cause"):
        out += map(_line, _wrap("Likely: " + ticket["likely_cause"]))
    out.append(_line("-" * WIDTH))

    for i, step in enumerate(ticket.get("steps", []), 1):
        lines = _wrap(f"{i}. {step.upper() if i == 1 else step}", indent="   ")
        out += [BOLD_ON, *map(_line, lines), BOLD_OFF] if i == 1 else list(map(_line, lines))
    if ticket.get("safety"):
        out += [LF, *map(_line, _wrap("! " + ticket["safety"], indent="  "))]
    out.append(_line("-" * WIDTH))

    part = ticket.get("part_needed", "none")
    if part and part.lower() != "none":
        out += [BOLD_ON, _line("PART"), BOLD_OFF, *map(_line, _wrap(part))]
        loc = ascii_text(ticket.get("location", "-").upper())
        # double width + height fits 24 columns; longer locations stay one line at double height only
        size = SIZE_DOUBLE if len(loc) <= WIDTH // 2 else SIZE_TALL
        width = WIDTH // 2 if size == SIZE_DOUBLE else WIDTH
        out += [size, BOLD_ON, *map(_line, _wrap(loc, width)), BOLD_OFF, SIZE_NORMAL]
        if ticket.get("stock"):
            out.append(_line(ticket["stock"]))
    else:
        out.append(_line("PART: none needed"))
    if ticket.get("note"):
        out += [BOLD_ON, *map(_line, _wrap("! " + ticket["note"], indent="  ")), BOLD_OFF]
    out.append(_line("-" * WIDTH))

    if ticket.get("recurring_fault"):
        out += [LINE_TIGHT, INVERT_ON, BOLD_ON, *map(_line, _wrap("! RECURRING FAULT: " + ticket["recurring_fault"])),
                BOLD_OFF, INVERT_OFF, LINE_DEFAULT, LF]
    if ticket.get("qr_action_url"):
        out += [ALIGN_CENTER, _qr(ticket["qr_action_url"]), LF, _line("Scan to close the ticket"), ALIGN_LEFT]
    if ticket.get("est_minutes"):
        out.append(_line(f"Est. repair time: {ticket['est_minutes']} min"))
    if footer:
        out += [ALIGN_CENTER, *map(_line, _wrap(footer)), ALIGN_LEFT]
    out += [LF * 3, CUT]
    return b"".join(out)
