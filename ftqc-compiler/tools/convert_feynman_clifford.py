"""CLI for the package's static magic-state conversion."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from ftqc_patch_rotation.magic_states import convert_text


def convert_tree(source: Path, output: Path, seed: int) -> dict[str, object]:
    files = sorted(source.rglob("*.qasm"))
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"seed": seed, "files": {}}
    totals = {"ccx": 0, "t": 0, "tdg": 0}
    for index, path in enumerate(files):
        relative = path.relative_to(source)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        converted, stats = convert_text(
            path.read_text(encoding="utf-8"), random.Random(seed + index)
        )
        destination.write_text(converted, encoding="utf-8")
        manifest["files"][relative.as_posix()] = stats
        for gate, count in stats.items():
            totals[gate] += count
    manifest["totals"] = totals
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path("external/feynman/benchmarks/qasm")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/feynman_clifford")
    )
    parser.add_argument("--seed", type=int, default=20260826)
    args = parser.parse_args()
    manifest = convert_tree(args.source, args.output, args.seed)
    print(json.dumps({"files": len(manifest["files"]), **manifest["totals"]}))


if __name__ == "__main__":
    main()
