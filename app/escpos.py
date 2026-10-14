"""Ticket -> ESC/POS bytes for an 80 mm thermal printer (48 columns, font A).

Layout for stressful situations: big ticket number, priority bar, machine and location in large print,
ONE black safety block, steps with tick boxes, part and shelf, recurring-fault block.

Text is ASCII plus three characters from code page PC437 (the default of practically every ESC/POS
printer, selected explicitly with ESC t 0): "·", "°" and "µ". The on-screen simulator renders exactly these
bytes (app/static/escpos.js knows the same three code points).
"""
import os
import textwrap
import unicodedata

WIDTH = 48

ESC, GS, LF = b"\x1b", b"\x1d", b"\n"
INIT = ESC + b"@" + ESC + b"t\x00"  # initialise, code page PC437
ALIGN_LEFT, ALIGN_CENTER = ESC + b"a\x00", ESC + b"a\x01"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
INVERT_ON, INVERT_OFF = GS + b"B\x01", GS + b"B\x00"
SIZE_NORMAL, SIZE_DOUBLE, SIZE_TALL = GS + b"!\x00", GS + b"!\x11", GS + b"!\x01"
LINE_TIGHT, LINE_DEFAULT = ESC + b"3\x18", ESC + b"2"  # 24-dot spacing = font A height -> solid inverted blocks
CUT = GS + b"VA\x03"  # partial cut after feeding 3 lines

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"  # print "(replay)" on paper only in demo mode

_CP437 = {"·": 0xFA, "°": 0xF8, "µ": 0xE6}
_ASCII = {"–": "-", "—": "-", "Ø": "D", "ø": "d", "×": "x", "’": "'", "“": '"', "”": '"', "⚠": "!", "…": "...",
          "→": "->"}


def ascii_text(s):
    """Text as the printer gets it (before encoding): ASCII plus the PC437 characters above."""
    s = "".join(_ASCII.get(ch, ch) for ch in str(s))
    return "".join(ch if ch in _CP437 else unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
                   for ch in s)


def _enc(s):
    return bytes(_CP437.get(ch, ord(ch)) for ch in ascii_text(s))


def _line(s=""):
    return _enc(s) + LF


def _wrap(s, width=WIDTH, indent=""):
    return textwrap.wrap(ascii_text(s), width=width, subsequent_indent=indent) or [""]


def _block(lines, width=WIDTH):
    """Inverted, bold, tight-spaced block; every line padded to full width so the black area is solid."""
    return [LINE_TIGHT, INVERT_ON, BOLD_ON, *[_line(l.ljust(width)) for l in lines], BOLD_OFF, INVERT_OFF,
            LINE_DEFAULT]


def _big(text):
    """Large centred line(s): double width + height up to 24 columns, else double height only."""
    t = ascii_text(text).upper()
    if len(t) <= WIDTH // 2:
        return [SIZE_DOUBLE, BOLD_ON, _line(t), BOLD_OFF, SIZE_NORMAL]
    return [SIZE_TALL, BOLD_ON, *map(_line, _wrap(t)), BOLD_OFF, SIZE_NORMAL]


def _qr(data):
    d = ascii_text(data).encode("ascii")
    n = len(d) + 3
    return (GS + b"(k\x04\x001A2\x00"           # model 2
            + GS + b"(k\x03\x001C\x06"          # module size 6
            + GS + b"(k\x03\x001E1"             # error correction M
            + GS + b"(k" + bytes([n % 256, n // 256]) + b"1P0" + d  # store data
            + GS + b"(k\x03\x001Q0")            # print


def test_page(target, created):
    """Short page for "Test print" in the printer settings."""
    return b"".join([INIT, ALIGN_CENTER, SIZE_DOUBLE, BOLD_ON, _line("PAPEROPS"), BOLD_OFF, SIZE_NORMAL,
                     _line("Printer test"), _line("-" * WIDTH), _line(f"Target: {target}"), _line(created),
                     LF, *_block(["If you can read this, the printer is ready.".center(WIDTH)]), LF * 3, CUT])


def render(ticket, ticket_id=None, created=None, footer=None, replay=False):
    out = [INIT, ALIGN_CENTER, BOLD_ON, _line("PAPEROPS  REPAIR TICKET"), BOLD_OFF]
    if ticket_id is not None:
        out += [SIZE_DOUBLE, BOLD_ON, _line(f"#{ticket_id}"), BOLD_OFF, SIZE_NORMAL]
    if created:
        out.append(_line(created))
    out.append(_line("-" * WIDTH))

    # priority, readable on black-and-white thermal paper (shape, not colour):
    # CRITICAL = black double bar + black stripe, HIGH = black bar, NORMAL = no bar, bold text only
    prio = ticket.get("priority", "NORMAL")
    if prio == "CRITICAL":
        out += [LINE_TIGHT, SIZE_DOUBLE, INVERT_ON, BOLD_ON, _line("!! CRITICAL !!".center(WIDTH // 2)), SIZE_NORMAL,
                _line("STOP - SAFETY FIRST - ACT NOW".center(WIDTH)), BOLD_OFF, INVERT_OFF, LINE_DEFAULT]
    elif prio == "HIGH":
        out += [SIZE_DOUBLE, INVERT_ON, BOLD_ON, _line("HIGH PRIORITY".center(WIDTH // 2)), BOLD_OFF, INVERT_OFF,
                SIZE_NORMAL]
    else:
        out += [SIZE_DOUBLE, BOLD_ON, _line(f"{prio} PRIORITY".center(WIDTH // 2)), BOLD_OFF, SIZE_NORMAL]

    if ticket.get("unconfirmed"):
        # the match is not backed by what was said: bold banner before anything else
        out += [LF, *_block([" UNCONFIRMED ".center(WIDTH, "!"), "VERIFY MACHINE ON SITE".center(WIDTH)]),
                BOLD_ON, *map(_line, _wrap(ticket["unconfirmed"])), BOLD_OFF]

    # machine and where it stands, large: the first thing a technician looks for
    out.append(LF)
    out += _big(ticket.get("machine", "UNKNOWN"))
    if ticket.get("machine_location"):
        out += _big(ticket["machine_location"].replace(", ", " · "))
    out.append(ALIGN_LEFT)
    out += map(_line, _wrap(" · ".join(x for x in [ticket.get("error_code"), ticket.get("cause")] if x)))
    if ticket.get("likely_cause"):
        out.append(_line(f"Likely: {ticket['likely_cause']}"))

    # ONE black safety block instead of "step 1" plus a separate warning
    steps = list(ticket.get("steps", []))
    safety = ticket.get("safety_short") or (steps[0].rstrip(".").upper() if steps else "EMERGENCY STOP")
    steps = steps[1:]  # step 1 is the safety step - it is in the block now
    out += [LF, *_block(_wrap("! " + safety, WIDTH, indent="  ")), LF]

    for i, step in enumerate(steps, 1):  # tick boxes so the steps can be checked off on paper
        out += map(_line, _wrap(f"[ ] {i}. {step}", indent="       "))
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
        out += [*_block(_wrap("! RECURRING FAULT: " + ticket["recurring_fault"], indent="  ")), LF]
    if ticket.get("qr_action_url"):
        out += [ALIGN_CENTER, _qr(ticket["qr_action_url"]), LF, _line("Scan to close the ticket"), ALIGN_LEFT]
    if ticket.get("est_minutes"):
        out.append(_line(f"Repair time: about {ticket['est_minutes']} min"))
    if footer:
        out += [ALIGN_CENTER, *map(_line, _wrap(footer + (" (replay)" if replay and DEMO_MODE else ""))), ALIGN_LEFT]
    out += [LF * 3, CUT]
    return b"".join(out)
