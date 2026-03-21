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
_SLACK_BARE_LINK_RE = re.compile(r"<(https?://[^>]+)>")


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


# Regex to strip ANSI escape sequences (color codes, cursor movement, etc.)
# Matches sequences like \x1b[31m, \x1b[0m, \x1b[38;5;196m
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Regex to strip control characters:
# - \x00-\x1f: C0 control codes (null, bell, backspace, tab, newline, etc.)
# - \x7f: DEL character
# - \x80-\x9f: C1 control codes
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_display_text(text: str) -> str:
    """Sanitize text for safe terminal display.

    Removes ANSI escape sequences and control characters that could:
    - Corrupt terminal output via cursor manipulation
    - Inject malicious escape sequences from user-provided persona names
    - Cause rendering issues in non-TTY environments

    Preserves:
    - Normal printable ASCII
    - Unicode characters (emoji, accented chars, box-drawing, etc.)

    Args:
        text: Raw text that may contain ANSI escapes or control characters.

    Returns:
        Sanitized text safe for terminal display, with leading/trailing
        whitespace stripped.
    """
    # Strip ANSI escape sequences first
    text = _ANSI_ESCAPE_RE.sub("", text)
    # Strip control characters
    text = _CONTROL_CHARS_RE.sub("", text)
    return text.strip()
