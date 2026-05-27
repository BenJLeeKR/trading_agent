"""Internal prompt configuration constants for AI agents.

These constants control how many events and how much context
each agent receives. Tuning these values directly affects
token usage, API latency, and decision quality.
"""

# ── Event count limits per agent ──────────────────────────
# EI: Event Interpretation — receives the most raw events
MAX_EVENTS_EI: int = 10
# AR: AI Risk — receives interpreted events + raw events
MAX_EVENTS_AR: int = 10
# FDC: Final Decision Composer — receives EI/AR output + limited raw events
MAX_EVENTS_FDC: int = 5

# ── Interpreted event limit ───────────────────────────────
# Max interpreted events passed from EI output to AR/FDC
MAX_INTERPRETED_EVENTS: int = 10
