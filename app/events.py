from datetime import datetime, timedelta, timezone
from contextlib import closing
import sqlite3
import threading

from app.schemas import AlertAction, AnalyticsEvent


class EventStore:
    def __init__(self, database_path: str, retention_days: int = 30) -> None:
        self.database_path = database_path
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._writes_since_cleanup = 0
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        import os

        directory = os.path.dirname(self.database_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        occurred_at TEXT NOT NULL,
                        camera_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_camera_time ON events(camera_id, occurred_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_time ON events(occurred_at)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alert_actions (
                        event_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL CHECK(status IN ('Acknowledged', 'Dismissed')),
                        acted_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "DELETE FROM events WHERE occurred_at < ?",
                    (self._retention_cutoff().isoformat(),),
                )

    def _retention_cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self.retention_days)

    def publish(self, event: AnalyticsEvent) -> None:
        payload = event.model_dump_json()
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO events(event_id, occurred_at, camera_id, event_type, payload) VALUES (?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.occurred_at.isoformat(),
                        event.camera_id,
                        event.event_type,
                        payload,
                    ),
                )
                self._writes_since_cleanup += 1
                if self._writes_since_cleanup >= 500:
                    connection.execute(
                        "DELETE FROM events WHERE occurred_at < ?",
                        (self._retention_cutoff().isoformat(),),
                    )
                    self._writes_since_cleanup = 0

    def query(
        self,
        camera_id: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AnalyticsEvent]:
        clauses: list[str] = []
        params: list[str | int] = []
        clauses.append("occurred_at >= ?")
        params.append(self._retention_cutoff().isoformat())
        if camera_id is not None:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            clauses.append("occurred_at >= ?")
            params.append(since.astimezone(timezone.utc).isoformat())
        if until is not None:
            clauses.append("occurred_at <= ?")
            params.append(until.astimezone(timezone.utc).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM events WHERE occurred_at < ?",
                    (self._retention_cutoff().isoformat(),),
                )
            rows = connection.execute(
                f"SELECT payload FROM events {where} ORDER BY occurred_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [AnalyticsEvent.model_validate_json(row["payload"]) for row in rows]

    def get(self, event_id: str) -> AnalyticsEvent | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return AnalyticsEvent.model_validate_json(row["payload"]) if row else None

    def list_alert_actions(self, limit: int = 1000) -> list[AlertAction]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT event_id, status, acted_at FROM alert_actions ORDER BY acted_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AlertAction.model_validate(dict(row)) for row in rows]

    def record_alert_action(self, event_id: str, status: str) -> AlertAction:
        if status not in {"Acknowledged", "Dismissed"}:
            raise ValueError("status must be Acknowledged or Dismissed")
        acted_at = datetime.now(timezone.utc)
        action = AlertAction(event_id=event_id, status=status, acted_at=acted_at)
        with self._lock, closing(self._connect()) as connection:
            with connection:
                event_exists = connection.execute(
                    "SELECT 1 FROM events WHERE event_id = ?", (event_id,)
                ).fetchone()
                if event_exists is None:
                    raise KeyError(event_id)
                connection.execute(
                    """
                    INSERT INTO alert_actions(event_id, status, acted_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET status = excluded.status, acted_at = excluded.acted_at
                    """,
                    (event_id, action.status, action.acted_at.isoformat()),
                )
        return action
