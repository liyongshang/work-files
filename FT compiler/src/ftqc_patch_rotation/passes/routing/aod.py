"""Plan non-crossing AOD stages with move dependencies and cycle buffers."""
import networkx as nx
from ftqc_patch_rotation.errors import RoutingError
from ftqc_patch_rotation.ir.routing import Move

def _sign(x):
    return (x > 0) - (x < 0)


def compatible(a, b, processor):
    sa, ta = processor.patch_anchor(a.start), processor.patch_anchor(a.target)
    sb, tb = processor.patch_anchor(b.start), processor.patch_anchor(b.target)
    return compatible_segments(sa, ta, sb, tb)


def compatible_segments(sa, ta, sb, tb):
    """Preserve AOD row/column ordering, including shared-row equality."""
    return all(_sign(sa[i]-sb[i]) == _sign(ta[i]-tb[i]) for i in (0, 1))


def _can_share(a, b, patch, processor, sharing_groups):
    return (sharing_groups is not None and a in sharing_groups and b in sharing_groups
            and sharing_groups[a] == sharing_groups[b] and processor.zone_of(patch) == "storage")


def _check_occupancy(pos, processor, sharing_groups):
    occupants = {}
    for q, patch in pos.items():
        if patch not in processor.patches:
            raise RoutingError("unknown occupied patch")
        for other in occupants.get(patch, ()):
            if not _can_share(q, other, patch, processor, sharing_groups):
                raise RoutingError(f"incompatible blocks share patch {patch}")
        occupants.setdefault(patch, []).append(q)


def apply_stage(pos, stage, processor, *, storage_patches=None, sharing_groups=None, storage_owners=None):
    """Validate against pre-stage state, then apply the simultaneous move."""
    allowed_storage = set(processor.data_patches if storage_patches is None else storage_patches)
    if any(p not in processor.patches or processor.zone_of(p) != "storage" for p in allowed_storage):
        raise RoutingError("invalid allowed storage region")
    if not stage or len({m.qubit for m in stage}) != len(stage):
        raise RoutingError("empty stage or duplicate moving qubit")
    _check_occupancy(pos, processor, sharing_groups)
    moving = {m.qubit for m in stage}
    for index, move in enumerate(stage):
        if pos.get(move.qubit) != move.start:
            raise RoutingError(f"incorrect move start for q{move.qubit}")
        if any(p == move.target and not _can_share(move.qubit, q, p, processor, sharing_groups)
               for q, p in pos.items() if q not in moving):
            raise RoutingError(f"occupied target {move.target}")
        if move.target not in allowed_storage and processor.zone_of(move.target) != "entanglement":
            raise RoutingError("move targets an excluded region")
        owner = sharing_groups[move.qubit] if sharing_groups is not None else move.qubit
        if storage_owners is not None and move.target in storage_owners and storage_owners[move.target] != owner:
            raise RoutingError("move targets another code block's storage home")
        if any(not compatible(move, other, processor) for other in stage[:index]):
            raise RoutingError("AOD non-crossing constraint violated")
    after = {**pos, **{m.qubit: m.target for m in stage}}
    _check_occupancy(after, processor, sharing_groups)
    pos.update(after)


def plan_aod_stages(pos, target, processor, *, storage_patches=None, sharing_groups=None, storage_owners=None):
    if set(pos) != set(target):
        raise RoutingError("invalid target mapping")
    _check_occupancy(pos, processor, sharing_groups)
    _check_occupancy(target, processor, sharing_groups)
    current = pos.copy()
    buffer_stages = []
    # A target pair is reserved in full, including the vacant icz member.
    used = set(target.values())
    for patch in target.values():
        pair = processor.pair_of(patch)
        if pair is not None:
            used.update(processor.pair_members(pair))
    allowed_storage = tuple(processor.data_patches if storage_patches is None else storage_patches)
    allowed = set(allowed_storage) | {
        p for members in processor.pairs.values() for p in members}
    buffer_reserved = set()
    while True:
        moves = {q: Move(q, current[q], target[q]) for q in current if current[q] != target[q]}
        dependency = nx.DiGraph()
        dependency.add_nodes_from(moves)
        for q, move in moves.items():
            for before, patch in current.items():
                if before == q or patch != move.target or _can_share(q, before, patch, processor, sharing_groups):
                    continue
                if before not in moves:
                    raise RoutingError(f"target occupied by stationary q{before}")
                dependency.add_edge(before, q)
        if nx.is_directed_acyclic_graph(dependency):
            break
        cycle = sorted({a for a, _ in nx.find_cycle(dependency)})
        candidates = []
        for q in cycle:
            group = sharing_groups[q] if sharing_groups is not None else q
            for p in allowed-buffer_reserved:
                if storage_owners is not None and p in storage_owners and storage_owners[p] != group:
                    continue
                actual = [b for b, patch in current.items() if patch == p]
                desired = [b for b, patch in target.items() if patch == p]
                if any(not _can_share(q, b, p, processor, sharing_groups) for b in actual):
                    continue
                if p in used and (not desired or any(not _can_share(q, b, p, processor, sharing_groups) for b in desired)):
                    continue
                candidates.append((q, p))
        if not candidates:
            raise RoutingError(f"no unused empty buffer patch for cycle {cycle}")
        q, buffer = min(candidates,
                        key=lambda item: (processor.distance2(current[item[0]], item[1]), item[0], item[1]))
        stage = (Move(q, current[q], buffer),)
        apply_stage(current, stage, processor, storage_patches=allowed_storage,
                    sharing_groups=sharing_groups, storage_owners=storage_owners)
        buffer_stages.append(stage)
        used.add(buffer)
        buffer_reserved.add(buffer)
    groups, assigned = [], {}
    while len(assigned) < len(moves):
        ready = [q for q in moves if q not in assigned and all(p in assigned for p in dependency.predecessors(q))]
        q = min(ready, key=lambda q: (processor.distance2(moves[q].start, moves[q].target), q))
        first = max((assigned[p] for p in dependency.predecessors(q)), default=0)
        for index in range(first, len(groups)):
            if all(compatible(moves[q], m, processor) for m in groups[index]):
                groups[index].append(moves[q])
                assigned[q] = index
                break
        else:
            assigned[q] = len(groups)
            groups.append([moves[q]])
    stage_graph = nx.DiGraph()
    stage_graph.add_nodes_from(range(len(groups)))
    stage_graph.add_edges_from((assigned[b], assigned[a]) for b, a in dependency.edges if assigned[b] != assigned[a])
    def priority(index):
        value = 0
        for move in groups[index]:
            start, end = processor.zone_of(move.start), processor.zone_of(move.target)
            value += int(start == "entanglement" and end == "storage")
            value -= int(start == "storage" and end == "entanglement")
        return -value, index
    order = nx.lexicographical_topological_sort(stage_graph, key=priority)
    stages = buffer_stages + [tuple(groups[i]) for i in order]
    replay = pos.copy()
    for stage in stages:
        apply_stage(replay, stage, processor, storage_patches=allowed_storage,
                    sharing_groups=sharing_groups, storage_owners=storage_owners)
    if replay != target:
        raise RoutingError("move replay does not reach target")
    return stages
