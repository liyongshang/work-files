"""Shared compilation errors, independent of individual passes."""

class RoutingError(ValueError):
    """An explicit failed plan, not a proof of physical infeasibility."""
