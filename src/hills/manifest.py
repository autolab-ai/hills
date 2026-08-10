"""hill.yaml: the only configuration the tool reads."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hills.errors import ManifestError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")

# Keyword arguments the tool always supplies; a manifest param may not shadow them.
RESERVED_PARAMS = frozenset({"submission", "final"})

PARAM_TYPES = {"int": int, "float": float, "str": str, "bool": bool}
DEFAULT_BLOB_THRESHOLD = 1024 * 1024
SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?\s*$", re.IGNORECASE)
SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def parse_size(value) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ManifestError(f"blobs.threshold must be a size like '10MB', got {value!r}")
    match = SIZE_RE.match(value)
    if not match:
        raise ManifestError(f"blobs.threshold must be a size like '10MB', got {value!r}")
    return int(float(match.group(1)) * SIZE_UNITS[(match.group(2) or "B").upper()])


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    default: object
    min: float | None = None
    max: float | None = None
    choices: tuple | None = None
    help: str | None = None

    @property
    def python_type(self) -> type:
        return PARAM_TYPES[self.type]

    def coerce(self, raw):
        """Turn a CLI string (or a YAML scalar) into a validated value."""
        if isinstance(raw, str):
            if self.type == "bool":
                lowered = raw.strip().lower()
                if lowered not in {"true", "false", "1", "0", "yes", "no"}:
                    raise ManifestError(f"param {self.name}: expected a boolean, got {raw!r}")
                value = lowered in {"true", "1", "yes"}
            elif self.type in {"int", "float"}:
                try:
                    value = self.python_type(raw)
                except ValueError:
                    raise ManifestError(
                        f"param {self.name}: expected {self.type}, got {raw!r}"
                    ) from None
            else:
                value = raw
        else:
            value = raw

        if self.type == "float" and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, self.python_type) or (
            self.type != "bool" and isinstance(value, bool)
        ):
            raise ManifestError(f"param {self.name}: expected {self.type}, got {value!r}")
        if self.min is not None and value < self.min:
            raise ManifestError(f"param {self.name}: {value} is below min {self.min}")
        if self.max is not None and value > self.max:
            raise ManifestError(f"param {self.name}: {value} is above max {self.max}")
        if self.choices is not None and value not in self.choices:
            raise ManifestError(
                f"param {self.name}: {value!r} is not one of {list(self.choices)}"
            )
        return value

    def as_json(self) -> dict:
        out = {"type": self.type, "default": self.default}
        for key in ("min", "max", "help"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.choices is not None:
            out["choices"] = list(self.choices)
        return out


@dataclass(frozen=True)
class BlobSpec:
    threshold: int = DEFAULT_BLOB_THRESHOLD
    track: tuple[str, ...] = ()

    def as_json(self) -> dict:
        return {"threshold": self.threshold, "track": list(self.track)}


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    watchdog_timeout_s: int
    params: dict[str, ParamSpec] = field(default_factory=dict)
    blobs: BlobSpec = field(default_factory=BlobSpec)
    exclusive: str | None = None

    def resolve_params(self, overrides: dict) -> dict:
        unknown = set(overrides) - set(self.params)
        if unknown:
            known = ", ".join(sorted(self.params)) or "(none)"
            raise ManifestError(
                f"unknown param(s): {', '.join(sorted(unknown))}. This hill declares: {known}"
            )
        return {
            name: spec.coerce(overrides[name]) if name in overrides else spec.default
            for name, spec in self.params.items()
        }

    def as_json(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "watchdog_timeout_s": self.watchdog_timeout_s,
            "params": {name: spec.as_json() for name, spec in self.params.items()},
            "blobs": self.blobs.as_json(),
            "exclusive": self.exclusive,
        }


def _parse_param(name: str, raw) -> ParamSpec:
    if name in RESERVED_PARAMS:
        raise ManifestError(f"params.{name} is reserved by the tool; choose another name")
    if not name.isidentifier() or name != name.lower():
        raise ManifestError(f"params.{name}: names must be lowercase Python identifiers")
    if not isinstance(raw, dict):
        raise ManifestError(f"params.{name} must be a mapping with at least 'type'")

    unknown = set(raw) - {"type", "default", "min", "max", "choices", "help"}
    if unknown:
        raise ManifestError(f"params.{name}: unknown keys {', '.join(sorted(unknown))}")

    type_name = raw.get("type")
    if type_name not in PARAM_TYPES:
        raise ManifestError(
            f"params.{name}.type must be one of {', '.join(PARAM_TYPES)}, got {type_name!r}"
        )
    if "default" not in raw:
        raise ManifestError(f"params.{name}: a default is required")

    choices = raw.get("choices")
    if choices is not None and not isinstance(choices, list):
        raise ManifestError(f"params.{name}.choices must be a list")

    spec = ParamSpec(
        name=name,
        type=type_name,
        default=None,
        min=raw.get("min"),
        max=raw.get("max"),
        choices=tuple(choices) if choices is not None else None,
        help=raw.get("help"),
    )
    # Validate the declared default through the same path a CLI value takes.
    default = spec.coerce(raw["default"])
    return ParamSpec(
        name=name,
        type=type_name,
        default=default,
        min=spec.min,
        max=spec.max,
        choices=spec.choices,
        help=spec.help,
    )


def parse(data, source: str = "hill.yaml") -> Manifest:
    if not isinstance(data, dict):
        raise ManifestError(f"{source} must be a mapping")

    unknown = set(data) - {
        "name",
        "version",
        "watchdog_timeout_s",
        "params",
        "blobs",
        "exclusive",
    }
    if unknown:
        raise ManifestError(f"{source}: unknown keys {', '.join(sorted(unknown))}")

    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ManifestError(
            f"{source}: name must be lowercase alphanumeric with . _ -, got {name!r}"
        )

    version = str(data.get("version", ""))
    if not VERSION_RE.match(version):
        raise ManifestError(f"{source}: version must look like 0.1.0, got {version!r}")

    watchdog = data.get("watchdog_timeout_s")
    if not isinstance(watchdog, int) or isinstance(watchdog, bool) or watchdog <= 0:
        raise ManifestError(f"{source}: watchdog_timeout_s must be a positive integer of seconds")

    raw_params = data.get("params") or {}
    if not isinstance(raw_params, dict):
        raise ManifestError(f"{source}: params must be a mapping")
    params = {key: _parse_param(key, value) for key, value in raw_params.items()}

    raw_blobs = data.get("blobs") or {}
    if not isinstance(raw_blobs, dict):
        raise ManifestError(f"{source}: blobs must be a mapping")
    unknown_blob_keys = set(raw_blobs) - {"threshold", "track"}
    if unknown_blob_keys:
        raise ManifestError(f"{source}: blobs has unknown keys {', '.join(sorted(unknown_blob_keys))}")
    track = raw_blobs.get("track") or []
    if not isinstance(track, list) or not all(isinstance(p, str) for p in track):
        raise ManifestError(f"{source}: blobs.track must be a list of glob patterns")
    blobs = BlobSpec(
        threshold=parse_size(raw_blobs.get("threshold", DEFAULT_BLOB_THRESHOLD)),
        track=tuple(track),
    )

    exclusive = data.get("exclusive")
    if exclusive is not None and (not isinstance(exclusive, str) or not exclusive.strip()):
        raise ManifestError(f"{source}: exclusive must be a device name such as 'gpu'")

    return Manifest(
        name=name,
        version=version,
        watchdog_timeout_s=watchdog,
        params=params,
        blobs=blobs,
        exclusive=exclusive,
    )


def load(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"no hill.yaml at {path.parent}")
    return parse(yaml.safe_load(path.read_text()), source=str(path))


def loads(text: str, source: str = "hill.yaml") -> Manifest:
    return parse(yaml.safe_load(text), source=source)
