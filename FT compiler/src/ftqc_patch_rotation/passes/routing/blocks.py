"""Build the CZ/icz block sequence before spatial decisions."""
from ftqc_patch_rotation.ir.logical import CompiledCircuit
from .semantics import CZ, DEFORMATION, _check_input

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
