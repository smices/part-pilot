"""Validate generated STEP files with FreeCAD's native Part workbench kernel."""

from pathlib import Path

import FreeCAD as App
import Part
import Assembly


ROOT = Path(__file__).resolve().parents[1]
STEP_FILE = (
    ROOT
    / "ai_cad_designer"
    / "exports"
    / "two_piece_enclosure"
    / "sensor_base.step"
)
OUTPUT = (
    ROOT
    / "ai_cad_designer"
    / "exports"
    / "two_piece_enclosure"
    / "freecad_validation.FCStd"
)

if not STEP_FILE.is_file():
    raise FileNotFoundError(STEP_FILE)

shape = Part.read(str(STEP_FILE))
if shape.isNull() or not shape.isValid() or shape.Volume <= 0:
    raise RuntimeError("FreeCAD rejected the generated STEP geometry")

document = App.newDocument("AICADValidation")
feature = document.addObject("Part::Feature", "SensorBase")
feature.Label = "AI CAD sensor base validation"
feature.Shape = shape
document.recompute()
document.saveAs(str(OUTPUT))

print(f"FreeCAD version: {'.'.join(App.Version()[:3])}")
print("Part workbench module: ok")
print(f"Assembly workbench module: {Assembly.__name__}")
print(f"STEP valid: {shape.isValid()}")
print(f"Solids: {len(shape.Solids)}")
print(f"Volume mm3: {shape.Volume:.3f}")
print(f"Saved: {OUTPUT}")

