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
