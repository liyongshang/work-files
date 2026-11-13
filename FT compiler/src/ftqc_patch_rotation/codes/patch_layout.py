"""Centered block geometry in patch-site units, separate from atom paths."""
from dataclasses import dataclass
from fractions import Fraction

from .rotated_surface import rotated_surface_layout


@dataclass(frozen=True)
class RotatedPatchLayout:
    distance: int
    side: int
    # (topology site ID, local x, local y); centered native topology.
    data: tuple[tuple[int, Fraction, Fraction], ...]
    checks: tuple[tuple[int, Fraction, Fraction], ...]

    @property
    def center(self):
        return Fraction(self.side-1, 2), Fraction(self.side-1, 2)

    def to_dict(self):
        return {"distance": self.distance, "side": self.side, "units": "patch-site-pitch",
                "topology_to_local": f"(x+{Fraction(self.side-1, 2)-self.distance}, y+{Fraction(self.side-1, 2)-self.distance})",
                "storage": "data and checks share one patch on disjoint sites",
                "se_offset_units": "code-lattice; one unit = one site pitch",
                "data": [[i, str(x), str(y)] for i, x, y in self.data],
                "checks": [[i, str(x), str(y)] for i, x, y in self.checks]}


def rotated_patch_layout(distance, side=None):
    layout = rotated_surface_layout(distance)
    side = 2*distance+3 if side is None else side
    if type(side) is not int or side < 2*distance+3:
        raise ValueError("rotated patch side must be an integer >= 2d+3")
    padding = Fraction(side-1, 2)-distance
    def positions(items):
        return tuple((q.id, Fraction(q.x)+padding, Fraction(q.y)+padding) for q in items)
    return RotatedPatchLayout(distance, side, positions(layout.data), positions(layout.checks))
