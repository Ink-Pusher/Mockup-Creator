#!/usr/bin/env python3
"""
ascii_safe.py -- keep every page, script and email we write pure ASCII, so copy/paste, clipboards,
terminals, the Supabase SQL editor and email can never turn a character into garbage (an em dash
showing up as ",A" plus junk). Standing rule for all Ink Pusher / Cloctopus work (2026-11-11).

    python3 scripts/ascii_safe.py check FILE...    # list non-ASCII characters (exit 1 if any)
    python3 scripts/ascii_safe.py fix FILE...      # rewrite them so the page LOOKS exactly the same

How "fix" keeps things looking identical:
  * HTML text and attributes:   em dash  ->  &#x2014;   (the browser shows the same dash)
  * JavaScript / TypeScript:    em dash  ->  \\u2014    (inside strings, template literals and regexes)
  * CSS strings:                em dash  ->  \\2014     (e.g. content: "...")
  * code comments (// and /* */ lines): typographic punctuation becomes plain ASCII ("--", "...", "->")
Files: .html .htm .js .ts .css .sql .md .txt .py. SQL / Markdown / text / Python get the plain-ASCII
stand-ins everywhere (no escape syntax there), except inside Python string literals, which get \\u escapes.
"""
import re, sys
from pathlib import Path

PLAIN = {"\u2014": "--", "\u2013": "-", "\u2012": "-", "\u2212": "-", "\u2026": "...", "\u2018": "'", "\u2019": "'",
         "\u201c": '"', "\u201d": '"', "\u2032": "'", "\u2033": '"', "\u00b7": "*", "\u2022": "*", "\u00d7": "x",
         "\u2192": "->", "\u2190": "<-", "\u2191": "^", "\u2193": "v", "\u21a9": "<-", "\u2500": "-", "\u2550": "=",
         "\u2502": "|", "\u2551": "|", "\u2713": "ok", "\u2714": "ok", "\u26a0": "(!)", "\u00b2": "^2", "\u215b": "1/8",
         "\u00bd": "1/2", "\u00bc": "1/4", "\u00a0": " ", "\u00e9": "e", "\u00b0": " deg", "\u2122": "(TM)", "\u00ae": "(R)",
         "\u00a9": "(c)", "\u25cf": "*", "\u25a0": "#", "\u25b2": "^", "\u2605": "*", "\u2665": "<3"}

def plain(ch): return PLAIN.get(ch, "?")
def js_esc(ch):
    b = ch.encode("utf-16-be")
    return "".join("\\u%02x%02x" % (b[i], b[i + 1]) for i in range(0, len(b), 2))
def css_esc(ch): return "\\%x " % ord(ch)
def html_ent(ch): return "&#x%x;" % ord(ch)

def fix_code(text, esc):
    """JS/TS/CSS: comment lines get plain ASCII, everything else gets escapes (valid in strings/regex)."""
    out, in_block = [], False
    for line in text.split("\n"):
        if not re.search(r"[^\x00-\x7f]", line): out.append(line); in_block = in_block and "*/" not in line; continue
        s = line.lstrip()
        comment = in_block or s.startswith("//") or s.startswith("/*") or s.startswith("*")
        if comment:
            out.append("".join(c if ord(c) < 128 else plain(c) for c in line))
        else:
            # a trailing // comment after code: plain ASCII after the last " //" that isn't inside quotes
            m = re.search(r"\s//\s[^'\"`]*$", line)
            head, tail = (line[:m.start()], line[m.start():]) if m else (line, "")
            out.append("".join(c if ord(c) < 128 else esc(c) for c in head) + "".join(c if ord(c) < 128 else plain(c) for c in tail))
        if "/*" in line and "*/" not in line[line.rfind("/*"):]: in_block = True
        elif "*/" in line: in_block = False
    return "\n".join(out)

def fix_html(text):
    parts, pos = [], 0
    for m in re.finditer(r"(<script\b[^>]*>)(.*?)(</script>)|(<style\b[^>]*>)(.*?)(</style>)|(<!--)(.*?)(-->)", text, re.S | re.I):
        parts.append("".join(c if ord(c) < 128 else html_ent(c) for c in text[pos:m.start()]))
        if m.group(1): parts.append(m.group(1) + fix_code(m.group(2), js_esc) + m.group(3))
        elif m.group(4): parts.append(m.group(4) + fix_code(m.group(5), css_esc) + m.group(6))
        else: parts.append(m.group(7) + "".join(c if ord(c) < 128 else plain(c) for c in m.group(8)) + m.group(9))
        pos = m.end()
    parts.append("".join(c if ord(c) < 128 else html_ent(c) for c in text[pos:]))
    return "".join(parts)

def fix_python(text):
    # inside quotes -> \\u escapes (same string at run time); comments and the rest -> plain ASCII
    out = []
    for line in text.split("\n"):
        if not re.search(r"[^\x00-\x7f]", line): out.append(line); continue
        res, q = [], None
        for c in line:
            if q is None and c in "'\"": q = c
            elif q == c: q = None
            if ord(c) < 128: res.append(c)
            else: res.append(js_esc(c) if q else plain(c))
        out.append("".join(res))
    return "\n".join(out)

def fix_text(text):
    ext_map = {}
    return "".join(c if ord(c) < 128 else plain(c) for c in text)

def fix_file(path):
    p = Path(path); t = p.read_text(encoding="utf-8")
    ext = p.suffix.lower()
    if ext in (".html", ".htm"): n = fix_html(t)
    elif ext in (".js", ".ts", ".mjs"): n = fix_code(t, js_esc)
    elif ext == ".css": n = fix_code(t, css_esc)
    elif ext == ".py": n = fix_python(t)
    else: n = fix_text(t)
    if n != t: p.write_text(n, encoding="utf-8")
    return t != n

def check(path):
    bad = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").split("\n"), 1):
        for c in line:
            if ord(c) > 127: bad.append((i, c)); break
    return bad

def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("check", "fix"):
        print(__doc__); sys.exit(2)
    status = 0
    for f in sys.argv[2:]:
        if sys.argv[1] == "fix":
            changed = fix_file(f)
            left = check(f)
            print(f"{'fixed' if changed else 'ok   '}  {f}" + (f"  ({len(left)} line(s) still non-ASCII)" if left else ""))
            status |= bool(left)
        else:
            bad = check(f)
            if bad:
                status = 1
                print(f"{f}: {len(bad)} line(s) with non-ASCII, e.g. line {bad[0][0]} {bad[0][1]!r}")
    sys.exit(status)

if __name__ == "__main__":
    main()
