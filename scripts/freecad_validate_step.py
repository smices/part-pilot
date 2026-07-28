"""Validate one STEP file with FreeCAD's native Part kernel."""

from pathlib import Path
import sys

import Assembly
import FreeCAD as App
import Part


if len(sys.argv) < 2:
    raise SystemExit("usage: FreeCADCmd scripts/freecad_validate_step.py STEP_FILE")

step_file = Path(sys.argv[-1]).resolve()
if not step_file.is_file():
    raise FileNotFoundError(step_file)

shape = Part.read(str(step_file))
if shape.isNull() or not shape.isValid() or shape.Volume <= 0:
    raise RuntimeError(f"FreeCAD rejected STEP geometry: {step_file}")
optimal_bounds = shape.optimalBoundingBox()

print(f"FreeCAD version: {'.'.join(App.Version()[:3])}")
print("Part workbench module: ok")
print(f"Assembly workbench module: {Assembly.__name__}")
print(f"STEP valid: {shape.isValid()}")
print(f"Solids: {len(shape.Solids)}")
print(f"Volume mm3: {shape.Volume:.3f}")
print(f"Bounds mm: {optimal_bounds.XLength:.3f} x "
      f"{optimal_bounds.YLength:.3f} x {optimal_bounds.ZLength:.3f}")
