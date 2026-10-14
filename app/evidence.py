"""Checks that the model's match is backed by what the technician actually said.

The model returns "evidence": a short quote from the transcript. A match counts as confirmed when
  1. the quote really is in the transcript (fuzzy: speech recognition and the model may differ slightly), and
  2. the quote names the machine (id, name or alias - or an error code that only this machine has) and the
     fault (error code or symptom) - fuzzy too, with spoken numbers normalised ("E four oh two" = E-402,
     "HP four hundred" = HP400, "nine ten" = 910).
A quote made of fragments ("press three ... E four oh two") is checked fragment by fragment.
Deliberately not a strict literal check: T02 must pass although Whisper heard "light code RE" for "light curtain".
"""
import re
from difflib import SequenceMatcher

_UNITS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4",
          "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
          "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16",
          "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
          "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90"}
_STOP = {"the", "a", "an", "is", "are", "in", "on", "at", "of", "to", "and", "it", "its", "no", "not", "does", "do",
         "from", "with", "there", "s", "t", "won", "can", "cannot", "just", "really", "so", "uh", "yeah", "kind"}

MACHINE_MIN, PHRASE_MIN, QUOTE_MIN = 0.8, 0.75, 0.8


def normalise(text):
    """lowercase words with spoken numbers as digits: "E four oh two" -> "e 4 0 2", "four hundred" -> "400"."""
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w == "hundred" and out and out[-1].isdigit():
            out[-1] += "00"
        else:
            out.append(_UNITS.get(w, w))
    return out


def codes_in(text):
    """Error codes mentioned in a text: "E-402", "E four oh two", "e 4 o 2", "E nine ten" -> {"E-402", "E-910"}."""
    words, found = normalise(text), set()
    for i, w in enumerate(words):
        head = w[1:] if w.startswith("e") and w[1:].isdigit() else ("" if w == "e" else None)
        if head is None:
            continue
        digits = head
        for nxt in words[i + 1:i + 4]:
            if not nxt.isdigit() or len(digits) >= 3:
                break
            digits += nxt
        if len(digits) == 3:
            found.add(f"E-{digits}")
    return found


def _compact(words):
    return "".join(words)


def best_window(phrase_words, text_words):
    """Best fuzzy similarity of a phrase against any same-length window of the text (spaces ignored)."""
    if not phrase_words or not text_words:
        return 0.0
    target, n, best = _compact(phrase_words), len(phrase_words), 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(text_words) - size + 1)):
            best = max(best, SequenceMatcher(None, target, _compact(text_words[i:i + size])).ratio())
    return best


def _content(words):
    return [w for w in words if w not in _STOP]


def symptom_match(symptom, text_words):
    """A symptom counts if the phrase matches fuzzily, or most of its content words appear (fuzzily) in the text."""
    s_words = normalise(symptom)
    if best_window(s_words, text_words) >= PHRASE_MIN:
        return True
    content = _content(s_words)
    hits = sum(1 for w in content if any(SequenceMatcher(None, w, t).ratio() >= 0.8 for t in text_words))
    return bool(content) and hits / len(content) >= 0.5 and hits >= 1


def check(evidence, transcript, machine, error):
    """Returns {"confirmed": bool, "quote_in_transcript", "machine_named", "fault_named"}."""
    tr = normalise(transcript)
    parts = [normalise(f) for f in re.split(r"\.{2,}|…", evidence or "")]
    parts = [f for f in parts if f]
    quote_ok = bool(parts) and all(best_window(f, tr) >= QUOTE_MIN for f in parts)
    ev = [w for f in parts for w in f]
    # Whatever backs the match must be in the quote AND in the transcript itself: the model sometimes
    # "corrects" its quote (heard "See and see two", quoted "CNC 2"), and a mostly-correct quote still
    # passes the fuzzy quote check.
    said_codes = codes_in(evidence or "") & codes_in(transcript)
    names = [machine["machine_id"], machine["name"], *machine["aliases"]]
    own_codes = {e["code"] for e in machine["error_codes"]}  # codes are unique per machine in the manual
    machine_ok = quote_ok and (any(best_window(normalise(n), f) >= MACHINE_MIN and
                                   best_window(normalise(n), tr) >= MACHINE_MIN for n in names for f in parts)
                               or bool(said_codes & own_codes))
    fault_ok = quote_ok and (error["code"] in said_codes or
                             any(symptom_match(s, ev) and symptom_match(s, tr) for s in error["symptoms"]))
    return {"confirmed": quote_ok and machine_ok and fault_ok, "quote_in_transcript": quote_ok,
            "machine_named": machine_ok, "fault_named": fault_ok}
