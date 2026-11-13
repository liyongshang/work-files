"""Site-level three-leg BUS trajectories, with exact micrometre coordinates."""
from fractions import Fraction
import math


class SiteRoads:
    def __init__(self, processor):
        if not processor.has_roads:
            raise ValueError("site roads require vertical_roads geometry")
        self.processor = processor

    def path(self, source, target, source_patch, *, bit=0):
        p = self.processor
        source, target = tuple(map(Fraction, source)), tuple(map(Fraction, target))
        if source == target:
            return (source,)
        if source[0] != target[0] and source[1] != target[1]:
            raise ValueError("BUS road moves must change only one coordinate")
        if source[0] != target[0]:
            ent = p.zone_of(source_patch) == "entanglement"
            count = p.config.entanglement_num_x_road if ent else p.config.storage_num_x_road
            fraction = Fraction(bit % count+1, count+1)
            if ent:
                # Roads lie above shuttle and below the next load row.
                lift = (p.s-p.pair_offset)*fraction
                if p.patches[source_patch].member == 0:
                    lift += p.pair_offset
            else:
                lift = p.s*fraction
            road = source[1]+lift
            return (source, (source[0], road), (target[0], road), target)
        count = p.config.num_y_road
        road = source[0]+p.s*Fraction(bit % count+1, count+1)
        return (source, (road, source[1]), (road, target[1]), target)

    def groups(self):
        p, groups = self.processor, []
        for zone in ("storage", "measurement", "entanglement"):
            ent = zone == "entanglement"
            origin = p.patch_anchor("entanglement:0:0:0" if ent else f"{zone}:0:0")
            rows = (p.config.b2 if ent else p.config.a1)*p.site_grid_size
            cols = (p.config.a2 if ent else p.config.b1)*p.site_grid_size
            for col in range(cols):
                left = origin[0]+col*p.s
                groups.append(dict(zone=zone, axis="y", interval=[str(left), str(left+p.s)],
                    coordinates=[str(left+p.s*Fraction(i+1, p.config.num_y_road+1))
                                 for i in range(p.config.num_y_road)], exterior=col == cols-1))
            count = p.config.entanglement_num_x_road if ent else p.config.storage_num_x_road
            for row in range(rows):
                low = origin[1]+row*p.s+(p.pair_offset if ent else 0)
                high = origin[1]+(row+1)*p.s
                groups.append(dict(zone=zone, axis="x", interval=[str(low), str(high)],
                    coordinates=[str(low+(high-low)*Fraction(i+1, count+1)) for i in range(count)],
                    exterior=row == rows-1))
        return groups

    def to_dict(self):
        return {"schema": "ftqc.site-roads.v1", "units": "um", "pair_axis": "vertical",
                "rule": "x: up/right-or-left/down; y: right/up-or-down/left",
                "selection": "BUS bit modulo road count; non-bit BUS uses road 0",
                "groups": self.groups()}


def path_length(points):
    return sum(math.hypot(float(Fraction(b[0]))-float(Fraction(a[0])), float(Fraction(b[1]))-float(Fraction(a[1])))
               for a, b in zip(points, points[1:]))


def bus_atom_paths(processor, moves, states, bus_id):
    """Expand block selectors to persistent physical carriers and road paths."""
    from ftqc_patch_rotation.codes import rotated_patch_layout
    from ftqc_patch_rotation.passes.transversal_protocols import check_carriers
    roads = SiteRoads(processor)
    layout = rotated_patch_layout(processor.config.d, processor.site_grid_size)
    bit = int(bus_id.rsplit(":", 1)[1]) if ":bit:" in bus_id else 0
    records = []
    for move in moves:
        q = move.qubit//2
        local_sites = layout.data if move.qubit % 2 == 0 else layout.checks
        carriers = states[q].carriers_by_site if move.qubit % 2 == 0 else check_carriers(states[q].representation.layout, q)
        a, b = processor.patch_anchor(move.start), processor.patch_anchor(move.target)
        for site, x, y in local_sites:
            source = (a[0]+x*processor.s, a[1]+y*processor.s)
            target = (b[0]+x*processor.s, b[1]+y*processor.s)
            points = roads.path(source, target, move.start, bit=bit)
            records.append(dict(block=move.qubit, site=site, carrier=carriers[site],
                road_index=bit % (processor.config.num_y_road if source[1] != target[1] else
                    processor.config.entanglement_num_x_road if processor.zone_of(move.start) == "entanglement"
                    else processor.config.storage_num_x_road),
                waypoints=[[str(x), str(y)] for x, y in points], distance_um=path_length(points)))
    return records
