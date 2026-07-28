"""Manufacturing validation agent."""

from __future__ import annotations

from typing import Any, Iterable

from ai_cad_designer.core import CADPart
from ai_cad_designer.validation import validate_printability


class PrintAgent:
    def validate(self, parts: Iterable[CADPart]) -> dict[str, dict[str, Any]]:
        return {part.name: validate_printability(part) for part in parts}

