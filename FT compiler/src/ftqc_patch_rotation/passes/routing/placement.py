"""PowerMove grouping and target patch assignment."""
from ftqc_patch_rotation.errors import RoutingError

def partition_block(block, circuit, pair_count):
    if block and pair_count < 1:
        raise RoutingError("no entanglement patch pairs")
    operands = {n: set(circuit.operation(n).qubits) for n in block}
    conflicts = {n: {m for m in block if m != n and operands[n] & operands[m]} for n in block}
    groups = []
    for node in sorted(block, key=lambda n: (-len(conflicts[n]), n)):
        for group in groups:
            if len(group) < pair_count and not conflicts[node].intersection(group):
                group.append(node)
                break
        else:
            groups.append([node])
    return [tuple(g) for g in groups]


def assign_positions(group, circuit, pos, processor, rng, *, storage_homes=None):
    target, reserved, pending = {}, set(), []
    active = {q for n in group for q in circuit.operation(n).qubits}
    occupied = set(pos.values())
    for q in sorted(set(pos) - active):
        if processor.zone_of(pos[q]) == "storage":
            target[q] = pos[q]
    returning = [q for q in set(pos)-active if processor.zone_of(pos[q]) == "entanglement"]
    for q in sorted(returning, key=lambda q: (-processor.patch_anchor(pos[q])[1], q)):
        if storage_homes is not None:
            home = storage_homes[q]
            if home in occupied or home in target.values():
                raise RoutingError(f"storage home occupied for q{q}")
            target[q] = home
            continue
        free = set(processor.data_patches) - occupied - set(target.values())
        if not free:
            raise RoutingError(f"no currently empty storage data patch for q{q}")
        target[q] = min(free, key=lambda p: (processor.distance2(pos[q], p), p))

    for node in sorted(group):
        op = circuit.operation(node)
        if op.kind == "icz":
            anchor, partner = op.qubits[0], None
        else:
            a, b = op.qubits
            pa, pb = processor.pair_of(pos[a]), processor.pair_of(pos[b])
            if pa is not None and pa == pb and pa not in reserved:
                target[a], target[b] = pos[a], pos[b]
                reserved.add(pa)
                continue
            if (pa is None) != (pb is None):
                anchor, partner = (a, b) if pa is not None else (b, a)
            elif pa is not None:
                anchor, partner = (a, b) if rng.randrange(2) == 0 else (b, a)
            else:
                anchor, partner = sorted((a, b))
        pair = processor.pair_of(pos[anchor])
        if pair is not None and pair not in reserved:
            target[anchor] = pos[anchor]
            if partner is not None:
                target[partner] = next(p for p in processor.pair_members(pair) if p != pos[anchor])
            reserved.add(pair)
        else:
            pending.append((anchor, partner))
    for anchor, partner in pending:
        options = [p for pair, members in processor.pairs.items() if pair not in reserved for p in members]
        if not options:
            raise RoutingError("no available target patch pair")
        p = min(options, key=lambda p: (processor.distance2(pos[anchor], p), p))
        pair = processor.pair_of(p)
        target[anchor] = p
        if partner is not None:
            target[partner] = next(m for m in processor.pair_members(pair) if m != p)
        reserved.add(pair)
    if set(target) != set(pos) or len(set(target.values())) != len(pos):
        raise RoutingError("target positions are incomplete or not injective")
    return target
