"""Function-based patch mapping, PowerMove routing and instruction scheduling."""
from dataclasses import asdict, dataclass
import random

import networkx as nx

from .compiler import CompiledCircuit
from .hardware import Processor

CZ = {"cz", "icz"}
DEFORMATION = {"rot", "folding", "unfolding"}
SUPPORTED = CZ | DEFORMATION | {"h", "s", "sdg", "x", "y", "z", "id", "reset", "measure", "barrier"}


class RoutingError(ValueError):
    """An explicit failed plan, not a proof of physical infeasibility."""


@dataclass(frozen=True)
class Move:
    qubit: int
    start: str
    target: str


@dataclass
class Mapping:
    initial_data_patch: dict[int, str]
    ancilla_patch: dict[int, str]


@dataclass
class InstructionBlock:
    kind: str
    nodes: tuple[int, ...] = ()
    moves: tuple[Move, ...] = ()


@dataclass
class RoutingSchedule:
    mapping: Mapping
    blocks: list[InstructionBlock]
    cz_blocks: tuple[tuple[int, ...], ...]
    final_positions: dict[int, str]
    seed: int
    cost: float

    @property
    def stage_count(self):
        return sum(b.kind == "aod" for b in self.blocks)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        mapping = Mapping(**{k: {int(q): p for q, p in v.items()} for k, v in data["mapping"].items()})
        blocks = [InstructionBlock(b["kind"], tuple(b["nodes"]), tuple(Move(**m) for m in b["moves"]))
                  for b in data["blocks"]]
        return cls(mapping, blocks, tuple(tuple(b) for b in data["cz_blocks"]),
                   {int(q): p for q, p in data["final_positions"].items()}, data["seed"], data["cost"])


def _check_input(circuit):
    if not nx.is_directed_acyclic_graph(circuit.dag):
        raise RoutingError("input operation graph is not a DAG")
    for op in circuit.operations():
        if op.kind not in SUPPORTED:
            raise RoutingError(f"unsupported operation {op.kind} at node {op.id}")
        if len(set(op.qubits)) != len(op.qubits) or any(q < 0 or q >= circuit.num_qubits for q in op.qubits):
            raise RoutingError(f"invalid operands at node {op.id}")
        arity = 2 if op.kind == "cz" else 1
        if op.kind != "barrier" and len(op.qubits) != arity:
            raise RoutingError(f"invalid arity at node {op.id}")


def build_cz_blocks(circuit: CompiledCircuit):
    """Construct the priority topological order before any spatial decisions."""
    _check_input(circuit)
    graph = circuit.dag
    degree = dict(graph.in_degree())
    front = {n for n in graph if degree[n] == 0}
    blocks = []
    previous_cz = False
    while front:
        normal = {n for n in front if circuit.operation(n).kind not in CZ | DEFORMATION}
        deform = {n for n in front if circuit.operation(n).kind in DEFORMATION}
        chosen = normal or deform or front.copy()
        is_cz = not normal and not deform
        if is_cz:
            if not previous_cz:
                blocks.append([])
            blocks[-1].extend(sorted(chosen))
        previous_cz = is_cz
        for node in sorted(chosen):
            front.remove(node)
            for nxt in graph.successors(node):
                degree[nxt] -= 1
                if degree[nxt] == 0:
                    front.add(nxt)
    return tuple(tuple(b) for b in blocks)


def initial_mapping(qubits, blocks, circuit, processor):
    qubits = tuple(qubits)
    if len(qubits) > min(len(processor.data_patches), len(processor.ancilla_patches)):
        raise RoutingError("storage capacity insufficient for data and ancilla patches")
    first = dict.fromkeys(qubits, float("inf"))
    for index, block in enumerate(blocks):
        for node in block:
            for q in circuit.operation(node).qubits:
                first[q] = min(first[q], index)
    order = sorted(qubits, key=lambda q: (first[q], q))
    return Mapping(dict(zip(order, processor.data_patches)), dict(zip(order, processor.ancilla_patches)))


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


def assign_positions(group, circuit, pos, processor, rng):
    target, reserved, pending = {}, set(), []
    active = {q for n in group for q in circuit.operation(n).qubits}
    occupied = set(pos.values())
    for q in sorted(set(pos) - active):
        if processor.zone_of(pos[q]) == "storage":
            target[q] = pos[q]
    returning = [q for q in set(pos)-active if processor.zone_of(pos[q]) == "entanglement"]
    for q in sorted(returning, key=lambda q: (-processor.patch_anchor(pos[q])[1], q)):
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


def _sign(x):
    return (x > 0) - (x < 0)


def compatible(a, b, processor):
    sa, ta = processor.patch_anchor(a.start), processor.patch_anchor(a.target)
    sb, tb = processor.patch_anchor(b.start), processor.patch_anchor(b.target)
    return all(_sign(sa[i]-sb[i]) == _sign(ta[i]-tb[i]) for i in (0, 1))


def apply_stage(pos, stage, processor):
    """Validate against pre-stage state, then apply the simultaneous move."""
    if not stage or len({m.qubit for m in stage}) != len(stage):
        raise RoutingError("empty stage or duplicate moving qubit")
    if len({m.target for m in stage}) != len(stage):
        raise RoutingError("duplicate move targets")
    moving = {m.qubit for m in stage}
    fixed = {p for q, p in pos.items() if q not in moving}
    for index, move in enumerate(stage):
        if pos.get(move.qubit) != move.start:
            raise RoutingError(f"incorrect move start for q{move.qubit}")
        if move.target in fixed:
            raise RoutingError(f"occupied target {move.target}")
        if move.target not in processor.data_patches and processor.zone_of(move.target) != "entanglement":
            raise RoutingError("move targets an excluded region")
        if any(not compatible(move, other, processor) for other in stage[:index]):
            raise RoutingError("AOD non-crossing constraint violated")
    pos.update({m.qubit: m.target for m in stage})


def plan_aod_stages(pos, target, processor):
    if set(pos) != set(target) or len(set(target.values())) != len(target):
        raise RoutingError("invalid target mapping")
    current = pos.copy()
    buffer_stages = []
    # A target pair is reserved in full, including the vacant icz member.
    used = set(target.values())
    for patch in target.values():
        pair = processor.pair_of(patch)
        if pair is not None:
            used.update(processor.pair_members(pair))
    allowed = set(processor.data_patches) | {
        p for members in processor.pairs.values() for p in members}
    while True:
        moves = {q: Move(q, current[q], target[q]) for q in current if current[q] != target[q]}
        owner = {p: q for q, p in current.items()}
        dependency = nx.DiGraph()
        dependency.add_nodes_from(moves)
        for q, move in moves.items():
            if move.target in owner:
                before = owner[move.target]
                if before not in moves:
                    raise RoutingError(f"target occupied by stationary q{before}")
                dependency.add_edge(before, q)
        if nx.is_directed_acyclic_graph(dependency):
            break
        cycle = sorted({a for a, _ in nx.find_cycle(dependency)})
        free = allowed - set(current.values()) - used
        if not free:
            raise RoutingError(f"no unused empty buffer patch for cycle {cycle}")
        q, buffer = min(((q, p) for q in cycle for p in free),
                        key=lambda item: (processor.distance2(current[item[0]], item[1]), item[0], item[1]))
        stage = (Move(q, current[q], buffer),)
        apply_stage(current, stage, processor)
        buffer_stages.append(stage)
        used.add(buffer)
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
        apply_stage(replay, stage, processor)
    if replay != target:
        raise RoutingError("move replay does not reach target")
    return stages


def _update_state(op, orientations, epochs):
    if op.kind in {"rot", "h"}:
        orientations[op.qubits[0]] ^= True
    elif op.kind == "reset":
        orientations[op.qubits[0]] = False
        epochs[op.qubits[0]] += 1


def _check_gate_group(group, circuit, pos, processor, orientations):
    active, pairs = set(), set()
    for n in group:
        op = circuit.operation(n)
        if active.intersection(op.qubits):
            raise RoutingError("gate group shares logical qubits")
        active.update(op.qubits)
        pair = processor.pair_of(pos[op.qubits[0]])
        if pair is None or pair in pairs:
            raise RoutingError(f"invalid or shared pair at node {n}")
        pairs.add(pair)
        occupants = {q for q, p in pos.items() if processor.pair_of(p) == pair}
        if occupants != set(op.qubits):
            raise RoutingError(f"incorrect pair occupants at node {n}: {occupants}")
        if op.kind == "cz" and orientations[op.qubits[0]] == orientations[op.qubits[1]]:
            raise RoutingError(f"CZ orientation mismatch at node {n}")
    if any(processor.zone_of(p) != "storage" for q, p in pos.items() if q not in active):
        raise RoutingError("inactive data block outside storage")


def route_and_schedule(circuit, processor, mapping=None, cost_fn=len, seed=0):
    blocks = build_cz_blocks(circuit)
    mapping = mapping or initial_mapping(range(circuit.num_qubits), blocks, circuit, processor)
    _check_mapping(mapping, circuit, processor)
    pos = mapping.initial_data_patch.copy()
    remaining = set(circuit.dag)
    ancestors = {n: nx.ancestors(circuit.dag, n) for n in remaining}
    bs = [list(b) for b in blocks]
    groups, output = [], []
    orientations, epochs = [False]*circuit.num_qubits, [0]*circuit.num_qubits
    rng = random.Random(seed)
    def ready(kinds, exclude=False):
        return sorted(n for n in remaining if (circuit.operation(n).kind in kinds) != exclude
                      and not ancestors[n].intersection(remaining))
    def record(nodes, kind):
        output.append(InstructionBlock(kind, tuple(nodes)))
        for n in nodes:
            _update_state(circuit.operation(n), orientations, epochs)
            remaining.remove(n)
    while remaining:
        ordinary = []
        while True:
            front = ready(CZ | DEFORMATION, exclude=True)
            if not front:
                break
            for n in front:
                _update_state(circuit.operation(n), orientations, epochs)
                remaining.remove(n)
                ordinary.append(n)
        if ordinary:
            output.append(InstructionBlock("ordinary", tuple(ordinary)))
        front = ready(DEFORMATION)
        if front:
            record(front, "deformation")
            continue
        if not remaining:
            break
        while bs and not bs[0]:
            bs.pop(0)
        if not bs:
            raise RoutingError("remaining operations but no CZ block")
        if not groups:
            groups = partition_block(bs[0], circuit, processor.pair_count)
        group = groups.pop(0)
        for n in group:
            if (ancestors[n] & remaining) - set(bs[0]):
                raise RoutingError(f"unfinished external predecessor for CZ block node {n}")
        target = assign_positions(group, circuit, pos, processor, rng)
        _check_gate_group(group, circuit, target, processor, orientations)
        stages = plan_aod_stages(pos, target, processor)
        for stage in stages:
            output.append(InstructionBlock("aod", moves=stage))
            apply_stage(pos, stage, processor)
        record(group, "cz")
        bs[0] = [n for n in bs[0] if n not in group]
    result = RoutingSchedule(mapping, output, blocks, pos, seed,
                            cost_fn([b.moves for b in output if b.kind == "aod"]))
    validate_schedule(circuit, processor, result)
    return result


def _check_mapping(mapping, circuit, processor):
    for positions, allowed in ((mapping.initial_data_patch, processor.data_patches),
                               (mapping.ancilla_patch, processor.ancilla_patches)):
        if set(positions) != set(range(circuit.num_qubits)) or len(set(positions.values())) != circuit.num_qubits:
            raise RoutingError("mapping must cover every qubit injectively")
        if not set(positions.values()) <= set(allowed):
            raise RoutingError("mapping outside designated storage region")


def validate_schedule(circuit, processor, schedule):
    """Independent replay of emitted instructions, not the planner's internal state."""
    _check_input(circuit)
    _check_mapping(schedule.mapping, circuit, processor)
    expected_blocks = build_cz_blocks(circuit)
    if schedule.cz_blocks != expected_blocks:
        raise RoutingError("serialized CZ blocks disagree with input")
    block_of = {n: index for index, b in enumerate(expected_blocks) for n in b}
    ancestors = {n: nx.ancestors(circuit.dag, n) for n in circuit.dag}
    remaining, done = set(circuit.dag), set()
    pos = schedule.mapping.initial_data_patch.copy()
    orientation, epochs = [False]*circuit.num_qubits, [0]*circuit.num_qubits
    for block in schedule.blocks:
        ordinary_ready = {n for n in remaining if circuit.operation(n).kind not in CZ | DEFORMATION
                          and not ancestors[n].intersection(remaining)}
        deformation_ready = {n for n in remaining if circuit.operation(n).kind in DEFORMATION
                             and not ancestors[n].intersection(remaining)}
        if block.kind != "ordinary" and ordinary_ready:
            raise RoutingError("ordinary instruction priority violated")
        if block.kind in {"aod", "cz"} and deformation_ready:
            raise RoutingError("deformation instruction priority violated")
        if block.kind == "aod":
            if block.nodes:
                raise RoutingError("AOD block includes logical operations")
            apply_stage(pos, block.moves, processor)
            continue
        if block.kind not in {"ordinary", "deformation", "cz"} or not block.nodes or block.moves:
            raise RoutingError("invalid instruction block")
        if block.kind == "cz":
            _check_gate_group(block.nodes, circuit, pos, processor, orientation)
        for n in block.nodes:
            if n not in remaining:
                raise RoutingError(f"duplicate/unknown instruction {n}")
            op = circuit.operation(n)
            expected_kind = "cz" if op.kind in CZ else "deformation" if op.kind in DEFORMATION else "ordinary"
            if block.kind != expected_kind:
                raise RoutingError("incorrect operation category")
            predecessors = ancestors[n] & remaining
            if block.kind == "cz":
                predecessors = {p for p in predecessors if block_of.get(p) != block_of[n]}
                if any(block_of.get(p, block_of[n]) < block_of[n] for p in remaining):
                    raise RoutingError("CZ blocks scheduled out of order")
            if predecessors:
                raise RoutingError(f"unfinished predecessors at {n}: {predecessors}")
            _update_state(op, orientation, epochs)
            remaining.remove(n)
            done.add(n)
    if remaining or pos != schedule.final_positions:
        raise RoutingError("incomplete schedule or incorrect final positions")
    return {"valid": True, "operations": len(done), "aod_stages": schedule.stage_count,
            "final_orientation": orientation, "reset_epochs": epochs}
