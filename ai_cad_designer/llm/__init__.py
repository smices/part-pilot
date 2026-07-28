"""LLM providers for structured industrial-design planning."""

from .providers import (
    CodexCLIProvider,
    DesignLLMProvider,
    LLMPlanningError,
    OpenAICompatibleProvider,
    build_provider,
)
from .schema import (
    DESIGN_PROPOSAL_JSON_SCHEMA,
    HARDWARE_ANALYSIS_JSON_SCHEMA,
    hardware_from_payload,
    proposal_from_payload,
)

__all__ = [
    "CodexCLIProvider",
    "DESIGN_PROPOSAL_JSON_SCHEMA",
    "HARDWARE_ANALYSIS_JSON_SCHEMA",
    "DesignLLMProvider",
    "LLMPlanningError",
    "OpenAICompatibleProvider",
    "build_provider",
    "hardware_from_payload",
    "proposal_from_payload",
]
