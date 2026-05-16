from __future__ import annotations

from typing import Any


# HIGH RISK triggers — these words in the goal string force deep normalization
HIGH_RISK_KEYWORDS = [
    "deploy", "production", "delete", "rm", "drop", "migrate",
    "database", "secret", "auth", "password", "token", "key",
    "payment", "billing", "ssl", "caddy", "nginx", "firewall",
    "docker", "compose", "systemctl", "cron", "sudo",
]

# ARCHITECTURE triggers — route to Claude instead of Codex
ARCHITECTURE_KEYWORDS = [
    "architecture", "design", "structure", "refactor", "rewrite",
    "strategy", "approach", "how should", "what's the best",
    "multi-project", "cross-project", "review", "critique", "audit",
]

# GEMINI REVIEW triggers — add Gemini pass before execution
GEMINI_REVIEW_TRIGGERS = [
    "security", "auth", "secrets", "deploy", "production",
    "policy", "permissions", "delete", "drop", "irreversible",
]

# FUZZY goal signals — escalate to Claude when combined with missing project
FUZZY_PHRASES = [
    "fix the", "make it", "improve it", "update it", "change it",
    "the broken", "doesn't work", "not working", "broken thing",
    "something wrong", "help with", "figure out",
]


def score_risk(goal: str, project: str, registry: dict[str, Any]) -> dict[str, Any]:
    """
    Score the risk level of a raw goal string and determine the normalization path.

    Returns:
    {
        "risk_level": "low | medium | high",
        "normalization_path": "fast | normal | deep",
        "requires_gemini_review": bool,
        "escalate_to_claude": bool,
        "triggered_keywords": [str],
        "is_fuzzy": bool,
    }
    """
    goal_lower = goal.lower()

    def _match(keywords: list[str]) -> list[str]:
        """Return keywords that appear in the goal, preserving list order."""
        return [kw for kw in keywords if kw in goal_lower]

    high_risk_hits = _match(HIGH_RISK_KEYWORDS)
    arch_hits = _match(ARCHITECTURE_KEYWORDS)
    gemini_hits = _match(GEMINI_REVIEW_TRIGGERS)

    # De-duplicate for the triggered list shown in output
    seen: set[str] = set()
    triggered: list[str] = []
    for kw in high_risk_hits + arch_hits:
        if kw not in seen:
            triggered.append(kw)
            seen.add(kw)

    is_fuzzy = any(phrase in goal_lower for phrase in FUZZY_PHRASES)
    escalate_to_claude = bool(arch_hits) or is_fuzzy
    requires_gemini = bool(gemini_hits)

    if high_risk_hits:
        risk_level = "high"
        normalization_path = "deep"
    elif arch_hits:
        risk_level = "medium"
        normalization_path = "deep"
    else:
        risk_level = "low"
        normalization_path = "fast"

    return {
        "risk_level": risk_level,
        "normalization_path": normalization_path,
        "requires_gemini_review": requires_gemini,
        "escalate_to_claude": escalate_to_claude,
        "triggered_keywords": triggered,
        "is_fuzzy": is_fuzzy,
    }
