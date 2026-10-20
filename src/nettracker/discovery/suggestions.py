"""Persist suggestions without merging devices or sending notifications."""

from datetime import datetime

from nettracker.db.repository import Repository
from nettracker.discovery.merge import merge_candidates


def record_merge_suggestions(
    repo: Repository, device_id: int, *, created_at: datetime
) -> int:
    """Record each directed candidate pair once, including after a database reopen."""
    with repo.transaction():
        candidate = repo.get_device(device_id)
        if candidate is None or candidate.merged_into is not None:
            return 0
        matches = merge_candidates(candidate, repo.list_devices())
        if not matches:
            return 0
        previous = {
            event.details.get("candidate_device_id")
            for event in repo.list_events(kind="merge_suggested", limit=-1)
            if event.device_id == device_id and event.details is not None
        }
        count = 0
        for existing_id in matches:
            if existing_id in previous:
                continue
            repo.add_event(
                "merge_suggested",
                created_at=created_at,
                device_id=device_id,
                details={"candidate_device_id": existing_id},
            )
            count += 1
        return count
