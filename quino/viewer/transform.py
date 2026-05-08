from __future__ import annotations

import numpy as np


class ChannelTransform:
    """Handles shift and multiplier transformations for channel data."""

    def __init__(self):
        self.shift = 0.0
        self.multiplier = 1.0

    def apply(self, data: np.ndarray) -> np.ndarray:
        """Apply shift and multiplier: data * multiplier + shift."""
        return data * self.multiplier + self.shift

    def reset(self) -> None:
        """Reset to identity transform."""
        self.shift = 0.0
        self.multiplier = 1.0

    def set_shift(self, shift: float) -> None:
        """Set shift value."""
        self.shift = shift

    def set_multiplier(self, multiplier: float) -> None:
        """Set multiplier value."""
        self.multiplier = multiplier

    def get_bounds(self, original_data: np.ndarray) -> tuple[float, float]:
        """Calculate min/max after transformation."""
        transformed = self.apply(original_data)
        return float(np.min(transformed)), float(np.max(transformed))
