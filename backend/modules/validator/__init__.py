"""Output validator.

Concept: see Pai_Updated_Concept.md > 3.5 Validator. Given the assistant output
and the instructions that guided its generation, the validator scores compliance
0.0-1.0 and lists explicit violations. The generation pipeline can then act
on the score — write to DebugVault for low scores, retry, or simply log.

This module is intentionally minimal:
  * No retry/reroll logic — caller decides.
  * No DebugVault write — caller decides.
  * No streaming — only operates on finished outputs.
"""

from modules.validator.service import validate_output
from modules.validator.types import ValidationResult, ValidationError


__all__ = ["validate_output", "ValidationResult", "ValidationError"]
