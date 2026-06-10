"""Public write helper for DebugVault.

Used by Validator integration (and later: memory_judge, factuality check) to
record an anomaly AND emit a parallel audit_logs row with severity='audit_fail'
so a single debug page can surface both views.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from modules.debug_vault.repository import debug_vault_repository
from modules.system.logger import AuditStatus, log_audit_entry


def write_vault_entry(
    *,
    kind: str,
    summary: str,
    character_id: Optional[str] = None,
    severity: str = "warning",
    context: Optional[Dict[str, Any]] = None,
    output: str = "",
    violations: Optional[Sequence[str]] = None,
    runtime_meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Persist the vault entry and mirror an audit_fail row for cross-search.

    Returns the entry id, or None if persistence failed — the caller treats
    failure as "couldn't record, proceed anyway", because a broken vault
    must not block generation.
    """
    try:
        entry_id = debug_vault_repository.insert(
            kind=kind,
            summary=summary,
            character_id=character_id,
            severity=severity,
            context=context,
            output=output,
            violations=violations,
            runtime_meta=runtime_meta,
        )
    except Exception as exc:
        log_audit_entry(
            "debug_vault_insert_failed",
            "[DebugVault] Could not persist anomaly entry.",
            AuditStatus.WARNING,
            details={"error": str(exc), "kind": kind, "summary": summary[:200]},
        )
        return None

    # Mirror into audit_logs so the same UI's severity=audit_fail filter
    # surfaces it. Details include vault_entry_id for reverse lookup.
    log_audit_entry(
        "debug_vault_entry_recorded",
        f"[DebugVault] {summary[:200]}",
        AuditStatus.ERROR,  # Closest existing severity to "audit_fail" until
                            # the enum is extended; audit_logs.severity column
                            # will carry the "error" string either way.
        details={
            "vault_entry_id": entry_id,
            "kind": kind,
            "character_id": character_id,
            "violations": list(violations or []),
        },
        meta=runtime_meta,
    )
    return entry_id
