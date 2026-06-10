"""Debug vault — curated anomalies for review.

Used by Validator failures, memory judge skips, factual inconsistency
flags. Separate from audit_logs (which is high-volume runtime trace).
On write, a parallel audit_logs row is created with severity='audit_fail'
so the same UI can find the entry from either side.
"""

from modules.debug_vault.repository import (
    DebugVaultRepository,
    debug_vault_repository,
)
from modules.debug_vault.service import write_vault_entry


__all__ = [
    "DebugVaultRepository",
    "debug_vault_repository",
    "write_vault_entry",
]
