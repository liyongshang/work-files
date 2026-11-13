"""Shared experiment configuration and provenance, outside compiler passes."""
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess


def default_output(name):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path("outputs/runs") / f"{stamp}_{name}"


def parse_config(parser):
    """Load JSON defaults, allowing explicit CLI options to override them."""
    parser.add_argument("--config", type=Path, help="JSON defaults; CLI options take precedence")
    preliminary, _ = parser.parse_known_args()
    if preliminary.config:
        config = json.loads(preliminary.config.read_text(encoding="utf-8"))
        actions = {action.dest: action for action in parser._actions}
        if not isinstance(config, dict) or set(config) - (set(actions) - {"help", "config"}):
            parser.error("config must be an object containing only supported argument names")
        for key, value in config.items():
            action = actions[key]
            try:
                config[key] = action.type(value) if action.type else value
            except (TypeError, ValueError) as error:
                parser.error(f"invalid config value for {key}: {error}")
        parser.set_defaults(**config)
    return parser.parse_args()


def start_run(output, config, inputs=(), resume=False):
    """Record exact inputs/environment and reject incompatible checkpoint reuse."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    input_hashes = {str(Path(p)): sha256(Path(p).read_bytes()).hexdigest() for p in sorted(inputs)}
    package = Path(__file__).resolve().parents[1]
    source_hash = sha256()
    for path in sorted(package.rglob("*.py")):
        source_hash.update(path.relative_to(package).as_posix().encode())
        source_hash.update(path.read_bytes())
    identity = {"config": config, "inputs_sha256": input_hashes, "source_sha256": source_hash.hexdigest()}
    marker = output / "metadata.json"
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if not resume or any(existing.get(key) != value for key, value in identity.items()):
            raise ValueError("output already belongs to another run; use a new --output directory")
        return output
    if any(output.iterdir()):
        raise ValueError("output is not empty and has no provenance; use a new --output directory")
    dependencies = {}
    for name in ("qiskit", "networkx", "numpy", "matplotlib", "z3-solver"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=package, capture_output=True,
                                  text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    metadata = {**identity, "started_at": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "dependencies": dependencies,
                "git_revision": revision}
    marker.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def record_attempt(output, **record):
    with (Path(output) / "attempts.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
