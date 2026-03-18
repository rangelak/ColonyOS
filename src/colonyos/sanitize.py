"""Shared content sanitization utilities for ColonyOS.

Provides XML tag stripping used by both the GitHub and Slack integrations
to mitigate prompt injection when untrusted user content flows into agent
prompts executed with ``permission_mode="bypassPermissions"``.
"""
from __future__ import annotations

import re

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
