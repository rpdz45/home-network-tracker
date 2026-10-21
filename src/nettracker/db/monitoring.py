"""Monitoring SQL, kept separate from discovery state and device trust."""

import math
from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address

from nettracker.db.repository import Repository, to_iso
from nettracker.errors import DatabaseError


@dataclass(frozen=True)
class MonitorTarget:
    device_id: int
    ip: str
    observed_at: str


class MonitoringRepository(Repository):
    """Reuse transaction/error handling; never update device trust or discovery last_seen."""

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    def target(self, device_id: int) -> MonitorTarget:
        device = self.get_device(device_id)
        if device is None or device.status == "ignored" or device.merged_into is not None:
            raise DatabaseError("monitor target must be an existing, unmerged, non-ignored device")
        row = self._fetch_one(
            "SELECT ip, seen_at FROM sightings WHERE device_id = ? AND source = 'discovery' "
            "ORDER BY seen_at DESC, id DESC LIMIT 1",
            (device_id,),
        )
        if row is None:
            raise DatabaseError("monitor target has no discovery observation")
        ip = row["ip"]
        # An IP is only a candidate if no other device currently claims it with
        # an equally recent or newer discovery record. Ping cannot authenticate MACs.
        conflict = self._fetch_one(
            "SELECT s.id FROM sightings s WHERE s.source = 'discovery' AND s.ip = ? "
            "AND s.device_id != ? AND s.seen_at >= ? AND s.id = "
            "(SELECT t.id FROM sightings t WHERE t.device_id = s.device_id "
            "AND t.source = 'discovery' ORDER BY t.seen_at DESC, t.id DESC LIMIT 1) LIMIT 1",
            (ip, device_id, row["seen_at"]),
        )
        if conflict is not None:
            raise DatabaseError("monitor target IP has a newer or ambiguous device owner")
        return MonitorTarget(device_id, ip, row["seen_at"])

    def record(
        self,
        target: MonitorTarget,
        *,
        online: bool,
        latency_ms: float | None,
        packet_loss_pct: float,
        checked_at: datetime,
    ) -> bool:
        """Atomically save a measurement and at most one transition; retries are idempotent."""
        IPv4Address(target.ip)
        stamp = to_iso(checked_at)
        if not math.isfinite(packet_loss_pct) or not 0 <= packet_loss_pct <= 100:
            raise ValueError("invalid packet loss")
        if online != (packet_loss_pct < 100):
            raise ValueError("online must agree with packet loss")
        if latency_ms is not None and (not math.isfinite(latency_ms) or latency_ms < 0):
            raise ValueError("invalid latency")
        if online != (latency_ms is not None):
            raise ValueError("online must agree with latency")
        with self.transaction():
            if self.target(target.device_id) != target:
                raise DatabaseError("discovery changed during monitoring; retry with fresh targets")
            state = self._fetch_one(
                "SELECT ip, online, checked_at FROM monitor_state WHERE device_id = ?",
                (target.device_id,),
            )
            if state is not None and stamp <= state["checked_at"]:
                if stamp == state["checked_at"]:
                    return False
                raise DatabaseError("monitor timestamps must not move backwards")
            self._conn.execute(
                "INSERT INTO sightings (device_id, ip, online, latency_ms, packet_loss_pct, "
                "seen_at, source) VALUES (?, ?, ?, ?, ?, ?, 'ping')",
                (target.device_id, target.ip, int(online), latency_ms, packet_loss_pct, stamp),
            )
            if state is not None and state["ip"] == target.ip and bool(state["online"]) != online:
                self.add_event(
                    "online" if online else "offline",
                    device_id=target.device_id,
                    created_at=checked_at,
                    details={"source": "ping", "ip": target.ip},
                )
            self._conn.execute(
                "INSERT INTO monitor_state (device_id, ip, online, checked_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET ip=excluded.ip, "
                "online=excluded.online, checked_at=excluded.checked_at",
                (target.device_id, target.ip, int(online), stamp),
            )
        return True
