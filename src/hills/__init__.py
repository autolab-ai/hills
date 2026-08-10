"""hills: local verification environments for AI research agents."""

from hills.core_schema import validate_core
from hills.sdk import load_evaluator, run_evaluator

__version__ = "0.1.0"
__all__ = ["__version__", "load_evaluator", "run_evaluator", "validate_core"]
