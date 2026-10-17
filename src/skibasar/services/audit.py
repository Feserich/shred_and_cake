"""Audit log helper: every manual change is recorded with before/after JSON."""

import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog


def log(
    s: Session,
    entity: str,
    entity_id: int | None,
    action: str,
    before: Any = None,
    after: Any = None,
    client: str = "",
) -> None:
    def dump(value: Any) -> str:
        return "" if value is None else json.dumps(value, ensure_ascii=False, default=str)

    s.add(
        AuditLog(
            client=client,
            entity=entity,
            entity_id=entity_id,
            action=action,
            before=dump(before),
            after=dump(after),
        )
    )
