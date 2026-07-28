---
name: tolerance
purpose: Apply explicit manufacturing clearances to parametric CAD.
---

# Tolerance

- Default FDM/PETG mating clearance: 0.25 mm per interface.
- Treat clearance as a named parameter, never an implicit dimension adjustment.
- Increase to 0.30–0.35 mm for long sliding rails or uncalibrated printers.
- Compensate first-layer elephant foot with a 0.3–0.5 mm bottom chamfer.
- Print a calibration coupon before committing expensive parts.
- Report designed tolerance separately from slicer dimensional compensation.

