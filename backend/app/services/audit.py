"""Audit trail for sign-ins, uploads, analyses and reads of results."""

import logging

from app.storage import AuditEvent, Store

log = logging.getLogger("audit")


def record(
    store: Store,
    owner_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    event = store.audit.append(AuditEvent(
        owner_id=owner_id, action=action, resource_type=resource_type,
        resource_id=resource_id, details=details or {},
    ))
    log.info("audit action=%s resource=%s/%s user=%s", action, resource_type, resource_id, owner_id)
    return event
