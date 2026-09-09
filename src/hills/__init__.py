"""hills: local verification environments for AI research agents.

This module is imported inside a hill's own environment by its tests, which
may not have the tool's dependencies. Keep it to the standard library; the
bundle commands are resolved on first use.
"""

from hills.core_schema import validate_core
from hills.errors import BundleError
from hills.sdk import load_evaluator, run_evaluator

__version__ = "0.5.0"
__all__ = [
    "__version__",
    "BundleError",
    "bundle",
    "load_evaluator",
    "run_evaluator",
    "unbundle",
    "validate_core",
]


def bundle(hill, **options):
    """Write a committed hill to one `.hill.tar`. See `hills.bundles.bundle`."""
    from hills.bundles import bundle as _bundle

    return _bundle(hill, **options)


def unbundle(archive, **options):
    """Unpack a `.hill.tar` into a verified working hill. See `hills.bundles.unbundle`."""
    from hills.bundles import unbundle as _unbundle

    return _unbundle(archive, **options)
