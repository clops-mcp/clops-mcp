"""Model tier configuration.

Semantic model tiers so Ops reference capability levels, not model IDs.
Update the mappings here when new models ship — every Op picks it up.

A floor worth knowing about: every dispatched step must call `complete` (or
`need`) before it ends its turn — that is the whole contract. A step whose
agent cannot reliably call an MCP tool cannot hold up its end, and the
cheapest tier has been observed failing exactly there: MCP schemas loaded
lazily never became callable, and the step burned a dispatch to report that
it could not finish. Treat MEDIUM as the floor for any real step; keep LOW
for work you can afford to have to re-dispatch.
"""


# ---------------------------------------------------------------------------
# Tier definitions — what each tier means
# ---------------------------------------------------------------------------

HIGH = "high"       # Deep reasoning, complex analysis, nuanced judgment
MEDIUM = "medium"   # Solid reasoning, most structured tasks — the practical floor
LOW = "low"         # Fast/cheap, but see the tool-calling caveat in the module docstring


# ---------------------------------------------------------------------------
# Default mapping — tier → model ID
# ---------------------------------------------------------------------------

_DEFAULT_TIER_MAP: dict[str, str] = {
    HIGH: "claude-opus-4-6",        # Deep reasoning, complex analysis
    MEDIUM: "claude-sonnet-4-6",    # Good balance of quality and speed
    LOW: "claude-haiku-4-5",        # Fast and cheap
}

# Active mapping (mutable — can be overridden at runtime)
_tier_map: dict[str, str] = dict(_DEFAULT_TIER_MAP)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def resolve(tier: str) -> str:
    """Resolve a tier name to a model ID."""
    if tier in _tier_map:
        return _tier_map[tier]
    # If it's already a model ID (not a tier), pass through
    return tier


def configure(overrides: dict[str, str]) -> None:
    """Override tier mappings. Call at startup or from config.

    Example:
        models.configure({
            models.HIGH: "claude-opus-4-6",
            models.LOW: "claude-haiku-4-5",
        })
    """
    _tier_map.update(overrides)


def reset() -> None:
    """Reset to default mappings."""
    _tier_map.clear()
    _tier_map.update(_DEFAULT_TIER_MAP)


def current() -> dict[str, str]:
    """Return current tier → model ID mapping."""
    return dict(_tier_map)
