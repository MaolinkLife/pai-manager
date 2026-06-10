"""Language compliance guard (0.9.0 Wave 2, §3.5-bis).

Detects the dominant script of a generated output and compares it with the
expected language tag (resolved from User.language). Used as a post-generation
check next to the Validator, with the same never-raise contract.

The detector counts unicode script ratios (no external library dependency
like langdetect / pycld3) which keeps it fast and avoids new wheel builds.
"""

from .service import check_language, get_language_guard_settings
from .types import LanguageCheckResult

__all__ = [
    "check_language",
    "get_language_guard_settings",
    "LanguageCheckResult",
]
