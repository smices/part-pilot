"""Parametric CAD and manufacturing workflow for AI-assisted industrial design."""

from .core import (
    CADAssembly,
    CADPart,
    JointPair,
    create_assembly,
    create_part,
    export_step,
    export_stl,
    generate_joint,
)
from .validation import validate_geometry, validate_printability
from .workflow import IndustrialDesignWorkflow

__all__ = [
    "CADAssembly",
    "CADPart",
    "IndustrialDesignWorkflow",
    "JointPair",
    "create_assembly",
    "create_part",
    "export_step",
    "export_stl",
    "generate_joint",
    "validate_geometry",
    "validate_printability",
]

