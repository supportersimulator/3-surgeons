"""Content sanitizer — defense against prompt-injection via stored/recalled memory.

Ported from IJFW's `mcp-server/src/sanitizer.js` (commit per harvest plan
2026-04-25). Original is JavaScript; this is the Python port for 3-Surgeons
plus 1 extra rule (rule 8: ANSI escape sequences) added based on local
attack-surface review.

WHY THIS EXISTS
---------------
3-Surgeons recalls evidence and surgeon verdicts from disk. Anything that
goes through ``sanitize_content`` cannot be weaponised by an attacker who
controls the storage layer (rogue dep, malicious commit, compromised plugin,
poisoned CardioReport from an external API).

The sanitizer is a *structural* defense — it strips/defangs structures the
model treats as instructions or scope changes. It does NOT semantically
analyse the text; that is the surgeons' job.

RULES (8)
---------
1. Strip C0/C1 control characters (incl. NUL) except tab + newline.
2. Strip Unicode bidi / zero-width / format chars used to hide payloads.
3. Defang ANY heading prefix (``#`` ... ``######``) → ``> `` quote prefix.
4. Defang setext headings (``===``/``---`` underline) → blank.
5. Neutralize fenced code blocks (``` and ~~~) → blockquote prefix.
6. Escape HTML/XML angle brackets so ``<system>`` etc. aren't parsed.
7. Collapse newlines to ``" | "`` so multi-line content can't fake a new
   journal section in a single-line render.
8. Strip ANSI CSI escape sequences (``ESC[…``) — terminal hijack vectors
   that some renderers / log viewers honour.

NON-GOALS
---------
- Not a content filter (no profanity / topic blocks).
- Not a Markdown sanitiser for HTML rendering — output is for *LLM context
  injection*, not browsers.
- Not idempotent for free-form Markdown intent (e.g. legitimate headings
  become quoted text). Caller decides whether to sanitise.
"""
from __future__ import annotations

import re
from typing import Final

# Compile once — these are hot-path regexes invoked on every recall.

# 1. C0/C1 control chars except tab (\t = 0x09) and newline (\n = 0x0A)
_RE_CONTROL: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0B-\x1F\x7F-\x9F]"
)

# 2. Unicode bidi / zero-width / format / BOM
_RE_BIDI: Final[re.Pattern[str]] = re.compile(
    r"[​-‏‪-‮⁦-⁩﻿]"
)

# 3. Heading prefix at line start (1+ hashes followed by whitespace)
_RE_HEADING_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*#+[ \t]+", re.MULTILINE
)

# 4. Setext heading underline (=== or ---) on its own line
_RE_SETEXT_UNDERLINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*[=-]{3,}[ \t]*$", re.MULTILINE
)

# 5. Fenced code block markers (``` and ~~~) at line start
_RE_FENCE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(```|~~~).*$", re.MULTILINE
)

# 6. HTML/XML angle brackets
_RE_LT: Final[re.Pattern[str]] = re.compile(r"<")
_RE_GT: Final[re.Pattern[str]] = re.compile(r">")

# 7. Line endings (CRLF, CR, LF)
_RE_NEWLINE: Final[re.Pattern[str]] = re.compile(r"\r\n?|\n")

# 8. ANSI CSI escape sequences (ESC[ ... letter)
_RE_ANSI_CSI: Final[re.Pattern[str]] = re.compile(
    r"\x1B\[[0-?]*[ -/]*[@-~]"
)


def sanitize_content(text: object) -> str:
    """Defang stored content before it reaches the LLM context window.

    Non-string inputs return ``""`` (defensive — never crash the recall path).
    See module docstring for the 8-rule taxonomy.
    """
    if not isinstance(text, str):
        return ""

    out = text
    out = _RE_ANSI_CSI.sub("", out)        # rule 8 (before control-char strip)
    out = _RE_CONTROL.sub("", out)         # rule 1
    out = _RE_BIDI.sub("", out)            # rule 2
    out = _RE_HEADING_PREFIX.sub("> ", out)  # rule 3
    out = _RE_SETEXT_UNDERLINE.sub("", out)  # rule 4
    out = _RE_FENCE.sub(r"> \1", out)        # rule 5
    out = _RE_LT.sub("&lt;", out)            # rule 6 (must precede &gt;)
    out = _RE_GT.sub("&gt;", out)            # rule 6
    out = _RE_NEWLINE.sub(" | ", out)        # rule 7

    return out


__all__ = ["sanitize_content"]
