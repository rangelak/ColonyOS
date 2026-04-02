"""Shared content sanitization utilities for ColonyOS.

Provides XML tag stripping used by both the GitHub and Slack integrations
to mitigate prompt injection when untrusted user content flows into agent
prompts executed with ``permission_mode="bypassPermissions"``.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Regex to strip XML-like tags from untrusted content.  Removes anything that
# looks like <tag>, </tag>, or <tag attr="…"> — prevents an attacker from
# closing wrapper delimiters (e.g. ``<github_issue>``, ``<slack_message>``)
# or injecting new XML delimiters.
XML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9_-]*(?:\s[^>]*)?>")


def sanitize_untrusted_content(text: str) -> str:
    """Strip XML-like tags from untrusted content to reduce prompt injection risk."""
    return XML_TAG_RE.sub("", text)


# Common secret patterns found in CI logs.  Each pattern is compiled once and
# applied in order by ``sanitize_ci_logs()``.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ghp_\w+"),          # GitHub personal access tokens
    re.compile(r"ghs_\w+"),          # GitHub server tokens
    re.compile(r"github_pat_\w+"),   # GitHub fine-grained personal access tokens
    re.compile(r"gho_\w+"),          # GitHub OAuth tokens
    re.compile(r"sk-\w+"),           # OpenAI / Stripe secret keys
    re.compile(r"AKIA\w+"),          # AWS access key IDs
    re.compile(r"Bearer\s+\S+"),     # Bearer tokens
    re.compile(r"xoxb-\S+"),         # Slack bot tokens
    re.compile(r"xoxp-\S+"),         # Slack user tokens
    re.compile(r"npm_\w+"),          # npm tokens
    # High-entropy base64 blobs (>40 chars) adjacent to secret-like keywords.
    re.compile(
        r"(?i)(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|API_?KEY)\s*[:=]\s*[A-Za-z0-9+/]{40,}={0,2}"
    ),
]

_REDACTED = "[REDACTED]"


# Regex to strip Slack link markup: ``<URL|display_text>`` → ``display_text``
# and bare ``<URL>`` → ``URL`` (without angle brackets).
_SLACK_LINK_RE = re.compile(r"<([^|>]+)\|([^>]+)>")
_SLACK_BARE_LINK_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*://[^>]+|mailto:[^>]+)>")


def strip_slack_links(text: str) -> str:
    """Strip Slack link markup, keeping only the display text.

    Handles:
    - ``<https://evil.com|click here>`` → ``click here``
    - ``<https://example.com>`` → ``https://example.com``
    - Malformed markup (missing pipe, nested brackets) is left as-is

    Stripped URLs are logged at DEBUG level to avoid excessive log volume.
    """
    # First pass: <URL|display_text> → display_text
    # Log stripped URLs for audit before removing them.
    for m in _SLACK_LINK_RE.finditer(text):
        logger.debug("Stripping Slack link URL: %s (display: %s)", m.group(1), m.group(2))
    text = _SLACK_LINK_RE.sub(r"\2", text)
    # Second pass: bare <URL> → URL (angle brackets removed, URL kept)
    text = _SLACK_BARE_LINK_RE.sub(r"\1", text)
    return text


# Slack mrkdwn metacharacters that must be escaped in untrusted content to
# prevent formatting injection.  We escape ``*``, ``_``, ``~``, and `` ` ``
# which control bold, italic, strikethrough, and inline code respectively.
# ``>`` at the start of a line creates a blockquote — we prefix it with a
# zero-width space to neutralize it.
_SLACK_MRKDWN_CHARS_RE = re.compile(r"([*_~`])")

# Mention patterns that could be used for injection: @here, @channel,
# @everyone, Slack special-mention syntax <!here>, <!channel>, <!everyone>,
# and user/group mentions like <@U12345> or <@U12345|display>.
_SLACK_MENTION_RE = re.compile(
    r"<!(?:here|channel|everyone)(?:\|[^>]*)?>|<@[UWB]\w+(?:\|[^>]*)?>|@(?:here|channel|everyone)",
    re.IGNORECASE,
)

# Slack link markup: <URL|display_text> — used for phishing link injection.
# Covers http, https, mailto, slack, and other URI schemes.
_SLACK_LINK_INJECTION_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*://[^|>]+|mailto:[^|>]+)\|([^>]+)>")


def sanitize_for_slack(text: str) -> str:
    """Escape Slack mrkdwn metacharacters and neutralize injection in untrusted content.

    Applies four sanitization passes:
    1. Neutralize Slack link markup (``<url|text>`` → ``url - text``)
    2. Escape mrkdwn formatting characters (``*``, ``_``, ``~``, `` ` ``)
    3. Neutralize mention injection (``@here``, ``@channel``, ``<!everyone>``, etc.)
    4. Neutralize leading ``>`` (blockquote) with a zero-width space prefix

    This function is intended for untrusted user-derived content (task descriptions,
    review findings) that will be interpolated into Slack mrkdwn messages.  It does
    NOT strip XML tags — call ``sanitize_untrusted_content()`` separately for that.
    """
    original = text
    # 1. Neutralize link injection: <url|display> → url - display
    text = _SLACK_LINK_INJECTION_RE.sub(r"\1 - \2", text)
    # Also strip bare Slack link markup: <url> → url
    text = _SLACK_BARE_LINK_RE.sub(r"\1", text)
    # 2. Escape mrkdwn metacharacters
    text = _SLACK_MRKDWN_CHARS_RE.sub(r"\\\1", text)
    # 3. Neutralize mention injection
    text = _SLACK_MENTION_RE.sub("[mention]", text)
    # 4. Neutralize leading > (blockquote) on each line
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            lines[i] = "\u200b" + line
    result = "\n".join(lines)
    if result != original:
        logger.debug("sanitize_for_slack neutralized content (len=%d→%d)", len(original), len(result))
    return result


def sanitize_ci_logs(text: str) -> str:
    """Sanitize CI log content for safe inclusion in agent prompts.

    Applies two passes:
    1. XML tag stripping (``sanitize_untrusted_content``)
    2. Secret-pattern redaction (``SECRET_PATTERNS``)
    """
    text = sanitize_untrusted_content(text)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


# Regex to strip ALL ANSI/terminal escape sequences:
# 1. CSI sequences: \x1b[ ... <letter>  (colors, cursor movement)
# 2. OSC sequences: \x1b] ... (ST|\x07)  (window title, clipboard writes)
# 3. DCS sequences: \x1bP ... (ST|\x07)  (device control strings)
# 4. Single-char escapes: \x1b followed by one printable char (e.g. \x1b7, \x1b8)
# ST (String Terminator) = \x1b\\ or \x07 (BEL)
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]"           # CSI sequences
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC sequences (terminated by BEL or ST)
    r"|\x1bP[^\x07\x1b]*(?:\x07|\x1b\\)?"   # DCS sequences (terminated by BEL or ST)
    r"|\x1b[\x20-\x7e]"                # Single-char escape sequences
)

# Regex to strip control characters:
# - \x00-\x08: C0 control codes before tab (null, bell, backspace, etc.)
# - \x0b-\x0c: vertical tab, form feed (between \n and \r)
# - \x0e-\x1f: C0 control codes after carriage return
# - \x7f: DEL character
# - \x80-\x9f: C1 control codes
# Preserves \t (\x09) and \n (\x0a) for display formatting.
# \r (\x0d) is NOT preserved — bare \r enables content-overwrite attacks.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]")


def sanitize_display_text(text: str) -> str:
    """Sanitize text for safe terminal display.

    Removes ANSI escape sequences and control characters that could:
    - Corrupt terminal output via cursor manipulation
    - Inject malicious escape sequences from user-provided persona names
    - Cause rendering issues in non-TTY environments

    Preserves:
    - Normal printable ASCII
    - Unicode characters (emoji, accented chars, box-drawing, etc.)
    - Tabs (\\t) and newlines (\\n)

    Carriage returns are normalized: ``\\r\\n`` becomes ``\\n``, and bare
    ``\\r`` is stripped to prevent content-overwrite attacks where
    ``"safe text\\rmalicious"`` renders as ``malicious`` in some terminals.

    Args:
        text: Raw text that may contain ANSI escapes or control characters.

    Returns:
        Sanitized text safe for terminal display, with leading/trailing
        whitespace stripped.
    """
    # Strip ANSI escape sequences first (CSI, OSC, DCS, single-char)
    text = _ANSI_ESCAPE_RE.sub("", text)
    # Normalize CRLF to LF, then strip bare CR to prevent overwrite attacks
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "")
    # Strip remaining control characters
    text = _CONTROL_CHARS_RE.sub("", text)
    return text.strip()


def sanitize_hook_output(text: str, max_bytes: int = 8192) -> str:
    """Sanitize hook subprocess output for safe injection into agent prompts.

    Applies three sanitization passes in order:
    1. ``sanitize_display_text()`` — strips ANSI escapes and control characters
    2. ``sanitize_ci_logs()`` — strips XML tags and redacts secret patterns
    3. Byte-level truncation with a ``[truncated]`` marker

    Args:
        text: Raw stdout captured from a hook subprocess.
        max_bytes: Maximum byte length of the returned string (default 8192).
            Output exceeding this limit is truncated with a marker showing
            the original size.

    Returns:
        Sanitized, size-capped text safe for inclusion in agent prompts.
    """
    # Pass 1: strip ANSI escapes and control characters
    text = sanitize_display_text(text)
    # Pass 2: strip XML tags and redact secrets
    text = sanitize_ci_logs(text)
    # Pass 3: truncate to max_bytes
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        original_len = len(encoded)
        # Truncate and decode safely (errors="ignore" handles mid-codepoint cuts)
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")
        text += f"\n[truncated — {original_len} bytes total]"
    return text
