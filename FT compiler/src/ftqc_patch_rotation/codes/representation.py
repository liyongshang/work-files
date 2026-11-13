"""Logical Pauli conventions for the two ZX representations.

This is an encoding frame, not atom placement. Physical H toggles this frame
while implementing logical H. A ZX-duality data permutation toggles the frame
while preserving the logical state (up to stabilizers).
"""
from dataclasses import dataclass, replace

from .rotated_surface import CodeCheck, RotatedSurfaceLayout


@dataclass(frozen=True)
class CodeRepresentation:
    layout: RotatedSurfaceLayout
    orientation: bool = False

    def __post_init__(self):
        if not isinstance(self.orientation, bool):
            raise ValueError("orientation must be bool")

    @property
    def checks(self) -> tuple[CodeCheck, ...]:
        if not self.orientation:
            return self.layout.checks
        return tuple(replace(c, basis="Z" if c.basis == "X" else "X") for c in self.layout.checks)

    @property
    def logical_x(self):
        return self.layout.logical_z if self.orientation else self.layout.logical_x

    @property
    def logical_z(self):
        return self.layout.logical_x if self.orientation else self.layout.logical_z

    def toggled(self):
        """Return the other encoding frame; the caller selects H or ROT semantics."""
        return replace(self, orientation=not self.orientation)


def transversal_cz_pairs(a: CodeRepresentation, b: CodeRepresentation) -> tuple[tuple[int, int], ...]:
    """Data-index pairs for CZ, with IDs local to the respective blocks.

The caller must map these IDs to distinct physical carriers. Equal-distance
blocks must use the same convention, and their encoding frames must differ.
No motion, syndrome round or physical gate is emitted here.
"""
    if a.layout != b.layout:
        raise ValueError("transversal CZ requires identical code layouts")
    if a.orientation == b.orientation:
        raise ValueError("transversal CZ requires opposite ZX representations")
    return tuple((q.id, q.id) for q in a.layout.data)
