"""Persistent, host-owned labels with an independent SQLite mirror.

The integrity/confidentiality lattice is adapted from Microsoft Agent Framework
FIDES (MIT), security.py blob 0ae5b5e77de905755ae3029e8f8518657fdd9571.
The durable schema, mirror protocol and action-evidence rules are Ariadne work.
This module does not make labels or SQLite tamper-proof against the host account.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from .vendor.tma import ActClass


class LabelConflict(RuntimeError):
    """The two records disagree or an expected record is missing."""


class Integrity(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class Confidentiality(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    USER_IDENTITY = "user_identity"


_CONF_RANK = {Confidentiality.PUBLIC: 0, Confidentiality.PRIVATE: 1,
              Confidentiality.USER_IDENTITY: 2}
_CHANNELS = {"user", "external", "tool", "model", "unknown"}


@dataclass(frozen=True)
class SecurityLabel:
    integrity: Integrity
    confidentiality: Confidentiality
    origins: frozenset[str]
    principals: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()
    authority: ActClass = ActClass.NONE

    def __post_init__(self):
        if not self.origins or not self.origins <= _CHANNELS:
            raise ValueError("Invalid observed origins")
        if self.confidentiality == Confidentiality.USER_IDENTITY and not self.principals:
            raise ValueError("Identity-restricted labels require principals")
        if self.confidentiality != Confidentiality.USER_IDENTITY and self.principals:
            raise ValueError("Principals require identity-restricted confidentiality")
        if any(not value for value in self.domains):
            raise ValueError("Empty administrative domain")
        if not isinstance(self.authority, ActClass):
            raise ValueError("Invalid action authority class")

    def as_dict(self) -> dict:
        return {"integrity": self.integrity.value,
                "confidentiality": self.confidentiality.value,
                "origins": sorted(self.origins), "principals": sorted(self.principals),
                "domains": sorted(self.domains), "authority": int(self.authority)}

    @classmethod
    def from_dict(cls, value: dict) -> SecurityLabel:
        return cls(Integrity(value["integrity"]), Confidentiality(value["confidentiality"]),
                   frozenset(value["origins"]), frozenset(value.get("principals", ())),
                   frozenset(value.get("domains", ())), ActClass(value.get("authority", 0)))


def join_labels(*labels: SecurityLabel) -> SecurityLabel:
    """FIDES restrictive join, extended with observed origin union.

    An absent parent set stays unknown and untrusted. A summary never promotes
    external or model content merely because trusted user content is also present.
    """
    if not labels:
        return SecurityLabel(Integrity.UNTRUSTED, Confidentiality.PUBLIC,
                             frozenset({"unknown"}))
    return SecurityLabel(
        Integrity.UNTRUSTED if any(x.integrity == Integrity.UNTRUSTED for x in labels)
        else Integrity.TRUSTED,
        max((x.confidentiality for x in labels), key=_CONF_RANK.__getitem__),
        frozenset().union(*(x.origins for x in labels)),
        frozenset().union(*(x.principals for x in labels)),
        frozenset().union(*(x.domains for x in labels)),
        min((x.authority for x in labels), default=ActClass.NONE),
    )


def derived_label(parents: tuple[SecurityLabel, ...], producer: str) -> SecurityLabel:
    """A model-written summary is untrusted even if all inputs were user text."""
    if producer not in {"model", "host"}:
        raise ValueError("Producer must be host or model")
    base = join_labels(*parents)
    if producer == "host":
        return base
    return join_labels(base, SecurityLabel(Integrity.UNTRUSTED,
                                          Confidentiality.PUBLIC, frozenset({"model"}),
                                          authority=ActClass.INFORM))


@dataclass(frozen=True)
class LabelRecord:
    id: str
    artifact: str
    version: int
    content_hash: str
    label: SecurityLabel
    status: str
    parents: tuple[str, ...]
    producer: str
    scope_id: str = "default"
    created_revision: int = 0


class PersistentLabelStore:
    """Two SQLite files, one connection, ATTACH-based atomic transactions.

    SQLite rollback-journal mode is used for cross-file atomic commit. The host
    must own both paths and serialize writes through this API. No WAL or :memory:
    path is accepted. File deletion, backup and OS compromise are out of scope.
    """

    def __init__(self, primary_path: str | Path, mirror_path: str | Path,
                 *, seal_key: bytes | None = None, scope_id: str = "default"):
        if seal_key is not None and (not isinstance(seal_key, bytes) or len(seal_key) < 32):
            raise ValueError("Host-held seal key must contain at least 32 bytes")
        self.seal_key = seal_key
        if not isinstance(scope_id, str) or not scope_id.strip() or len(scope_id) > 512:
            raise ValueError("Invalid scope ID")
        self.scope_id = scope_id
        primary = Path(primary_path).resolve()
        mirror = Path(mirror_path).resolve()
        if primary == mirror:
            raise ValueError("Primary and mirror must be distinct files")
        if primary.exists() != mirror.exists():
            raise LabelConflict("Exactly one ledger file is missing")
        primary.parent.mkdir(parents=True, exist_ok=True)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(primary), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("ATTACH DATABASE ? AS mirror", (str(mirror),))
        self.db.execute("PRAGMA mirror.journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=EXTRA")
        self.db.execute("PRAGMA mirror.synchronous=EXTRA")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
              id TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
              artifact TEXT NOT NULL, version INTEGER NOT NULL,
              content TEXT NOT NULL, content_hash TEXT NOT NULL,
              label_json TEXT NOT NULL, status TEXT NOT NULL,
              parents_json TEXT NOT NULL, producer TEXT NOT NULL,
              created_revision INTEGER NOT NULL,
              UNIQUE(scope_id,artifact,version));
            CREATE TABLE IF NOT EXISTS mirror.labels (
              id TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
              artifact TEXT NOT NULL, version INTEGER NOT NULL,
              content_hash TEXT NOT NULL, label_json TEXT NOT NULL,
              status TEXT NOT NULL, parents_json TEXT NOT NULL,
              producer TEXT NOT NULL, created_revision INTEGER NOT NULL,
              seal TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scope_revision (
              scope_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS mirror.scope_revision (
              scope_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS label_outbox (
              scope_id TEXT NOT NULL, revision INTEGER NOT NULL,
              session_id TEXT NOT NULL, record_id TEXT NOT NULL,
              kind TEXT NOT NULL, PRIMARY KEY(scope_id,revision));
            CREATE TABLE IF NOT EXISTS mirror.label_outbox (
              scope_id TEXT NOT NULL, revision INTEGER NOT NULL,
              session_id TEXT NOT NULL, record_id TEXT NOT NULL,
              kind TEXT NOT NULL, PRIMARY KEY(scope_id,revision));
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY, event TEXT NOT NULL, record_id TEXT NOT NULL,
              details_json TEXT NOT NULL);
        """)
        try:
            self.scan_consistency()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical(value) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _seal(self, fields: tuple) -> str:
        if self.seal_key is None:
            return ""
        body = self._canonical(fields).encode("utf-8")
        return hmac.new(self.seal_key, body, hashlib.sha256).hexdigest()

    @contextmanager
    def _stable_read(self):
        own_transaction = not self.db.in_transaction
        if own_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            if own_transaction:
                self.db.execute("COMMIT")
        except BaseException:
            if own_transaction:
                self.db.execute("ROLLBACK")
            raise

    def revision(self) -> int:
        primary = self.db.execute("SELECT revision FROM scope_revision WHERE scope_id=?",
                                  (self.scope_id,)).fetchone()
        mirror = self.db.execute("SELECT revision FROM mirror.scope_revision WHERE scope_id=?",
                                 (self.scope_id,)).fetchone()
        if (primary is None) != (mirror is None) or (primary and primary[0] != mirror[0]):
            raise LabelConflict("Revision copies disagree")
        return primary[0] if primary else 0

    def _advance_revision(self) -> int:
        next_revision = self.revision() + 1
        for table in ("scope_revision", "mirror.scope_revision"):
            self.db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                            (self.scope_id, next_revision))
        return next_revision

    def _write(self, artifact: str, content: str, label: SecurityLabel,
               parents: tuple[str, ...], producer: str,
               session_id: str = "") -> str:
        if not artifact or not isinstance(content, str):
            raise ValueError("Artifact and content required")
        node_id = str(uuid4())
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        try:
            version = self.db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM records WHERE scope_id=? AND artifact=?",
                (self.scope_id, artifact)).fetchone()[0]
            revision = self._advance_revision()
            common = (node_id, self.scope_id, artifact, version, self._hash(content),
                      self._canonical(label.as_dict()), "active",
                      self._canonical(parents), producer, revision)
            self.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            common[:4] + (content,) + common[4:])
            self.db.execute("INSERT INTO mirror.labels VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            common + (self._seal(common),))
            event = (self.scope_id, revision, session_id, node_id, "write")
            for table in ("label_outbox", "mirror.label_outbox"):
                self.db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", event)
            self.db.execute("INSERT INTO audit(event,record_id,details_json) VALUES (?,?,?)",
                            ("write", node_id, self._canonical({"parents": parents})))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return node_id

    def ingest(self, artifact: str, content: str, channel: str,
               confidentiality: Confidentiality = Confidentiality.PUBLIC,
               principals: frozenset[str] = frozenset(), *,
               session_id: str = "") -> str:
        """Trusted host supplies channel; content and model cannot set it."""
        if channel not in _CHANNELS:
            raise ValueError("Unsupported host channel")
        confidentiality = Confidentiality(confidentiality)
        label = SecurityLabel(Integrity.TRUSTED if channel == "user" else Integrity.UNTRUSTED,
                              confidentiality, frozenset({channel}), frozenset(principals),
                              authority=ActClass.ACT if channel == "user" else
                              ActClass.INFORM if channel == "model" else ActClass.NONE)
        return self._write(artifact, content, label, (), "source", session_id)

    def derive(self, artifact: str, content: str, parents: tuple[str, ...],
               *, producer: str = "model", session_id: str = "") -> str:
        """Host must supply all actual inputs; empty input becomes unknown."""
        unique = tuple(dict.fromkeys(parents))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            labels = []
            for parent in unique:
                record = self.read(parent)
                if record.scope_id != self.scope_id:
                    raise ValueError("Parent belongs to another scope")
                if record.status != "active":
                    raise ValueError("Cannot derive from inactive state")
                labels.append(record.label)
            return self._write(artifact, content, derived_label(tuple(labels), producer),
                               unique, producer, session_id)
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def read(self, node_id: str) -> LabelRecord:
        with self._stable_read():
            return self._read_locked(node_id)

    def _read_locked(self, node_id: str) -> LabelRecord:
        primary = self.db.execute("SELECT * FROM records WHERE id=?", (node_id,)).fetchone()
        mirror = self.db.execute("SELECT * FROM mirror.labels WHERE id=?", (node_id,)).fetchone()
        if primary is None and mirror is None:
            raise KeyError(node_id)
        if primary is None or mirror is None:
            raise LabelConflict("Missing label copy")
        fields = ("id", "scope_id", "artifact", "version", "content_hash", "label_json",
                  "status", "parents_json", "producer", "created_revision")
        if any(primary[x] != mirror[x] for x in fields):
            raise LabelConflict("Conflicting label copies")
        signed = tuple(primary[x] for x in fields)
        if not hmac.compare_digest(mirror["seal"], self._seal(signed)):
            raise LabelConflict("Mirror seal missing or invalid")
        if self._hash(primary["content"]) != primary["content_hash"]:
            raise LabelConflict("Content hash mismatch")
        try:
            label = SecurityLabel.from_dict(json.loads(primary["label_json"]))
            parents = tuple(json.loads(primary["parents_json"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise LabelConflict("Malformed persisted label") from exc
        if primary["scope_id"] != self.scope_id:
            raise LabelConflict("Record belongs to another scope")
        if primary["status"] not in {"active", "quarantined", "staged", "superseded"}:
            raise LabelConflict("Invalid persisted status")
        return LabelRecord(primary["id"], primary["artifact"], primary["version"],
                           primary["content_hash"], label, primary["status"], parents,
                           primary["producer"], primary["scope_id"], primary["created_revision"])

    def content(self, node_id: str) -> str:
        with self._stable_read():
            record = self._read_locked(node_id)
            if record.status != "active":
                raise LabelConflict("Inactive content is not visible")
            return self.db.execute("SELECT content FROM records WHERE id=?", (node_id,)).fetchone()[0]

    def records(self) -> tuple[LabelRecord, ...]:
        with self._stable_read():
            ids = [row[0] for row in self.db.execute(
                "SELECT id FROM records WHERE scope_id=? ORDER BY created_revision,id",
                (self.scope_id,))]
            return tuple(self._read_locked(node_id) for node_id in ids)

    def outbox(self, after_revision: int = 0) -> tuple[dict, ...]:
        return tuple(dict(row) for row in self.db.execute(
            "SELECT * FROM label_outbox WHERE scope_id=? AND revision>? ORDER BY revision",
            (self.scope_id, after_revision)))

    def verify(self, node_id: str, content: str) -> bool:
        try:
            record = self.read(node_id)
            return record.status == "active" and record.content_hash == self._hash(content)
        except (KeyError, LabelConflict, ValueError):
            return False

    def quarantine(self, node_id: str) -> None:
        status = "quarantined"
        self.read(node_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            revision = self._advance_revision()
            self.db.execute("UPDATE records SET status=? WHERE id=?", (status, node_id))
            row = self.db.execute("SELECT * FROM records WHERE id=?", (node_id,)).fetchone()
            fields = ("id", "scope_id", "artifact", "version", "content_hash", "label_json",
                      "status", "parents_json", "producer", "created_revision")
            self.db.execute("UPDATE mirror.labels SET status=?, seal=? WHERE id=?",
                            (status, self._seal(tuple(row[x] for x in fields)), node_id))
            event = (self.scope_id, revision, "", node_id, "quarantine")
            for table in ("label_outbox", "mirror.label_outbox"):
                self.db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", event)
            self.db.execute("INSERT INTO audit(event,record_id,details_json) VALUES (?,?,?)",
                            ("status", node_id, self._canonical({"status": status})))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def quarantine_repair(self, request_id: str, targets: tuple[str, ...],
                          expected_revision: int) -> int:
        """Commit one recovery isolation plan in both authoritative label files.

        The recovery worker may prepare its shadow state first, but managed
        reads remain barred until this committed revision is projected there.
        A repeated request is accepted only with the same recorded target set.
        """
        if not request_id or not targets or len(set(targets)) != len(targets):
            raise ValueError("A recovery request and distinct targets are required")
        self.scan_consistency()
        current = self.revision()
        event = self.db.execute(
            "SELECT kind,record_id FROM label_outbox WHERE scope_id=? AND revision=?",
            (self.scope_id, expected_revision + 1)).fetchone()
        if current == expected_revision + 1 and event is not None:
            audit = self.db.execute(
                "SELECT details_json FROM audit WHERE event='repair_quarantine' "
                "AND record_id=? ORDER BY seq DESC LIMIT 1", (request_id,)).fetchone()
            if (event["kind"] == "repair_quarantine" and event["record_id"] == request_id
                and audit is not None
                and json.loads(audit[0]) == {"revision": current, "targets": list(targets)}
                and all(self.read(node_id).status == "quarantined" for node_id in targets)):
                return current
            raise LabelConflict("Recovery quarantine retry differs from committed plan")
        if current != expected_revision:
            raise LabelConflict("Recovery quarantine revision differs from label ledger")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for node_id in targets:
                record = self.read(node_id)
                if record.status != "active":
                    raise LabelConflict("Recovery target is not active")
            revision = self._advance_revision()
            fields = ("id", "scope_id", "artifact", "version", "content_hash",
                      "label_json", "status", "parents_json", "producer",
                      "created_revision")
            for node_id in targets:
                self.db.execute("UPDATE records SET status='quarantined' WHERE id=?",
                                (node_id,))
                row = self.db.execute("SELECT * FROM records WHERE id=?", (node_id,)).fetchone()
                self.db.execute("UPDATE mirror.labels SET status='quarantined',seal=? WHERE id=?",
                                (self._seal(tuple(row[x] for x in fields)), node_id))
            event_value = (self.scope_id, revision, "", request_id,
                           "repair_quarantine")
            for table in ("label_outbox", "mirror.label_outbox"):
                self.db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", event_value)
            self.db.execute("INSERT INTO audit(event,record_id,details_json) VALUES (?,?,?)",
                            ("repair_quarantine", request_id,
                             self._canonical({"revision": revision, "targets": list(targets)})))
            self.db.execute("COMMIT")
            return revision
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM audit ORDER BY seq")]

    def scan_consistency(self) -> int:
        """Audit one stable cross-file snapshot, including parent joins."""
        if self.db.in_transaction:
            return self._scan_consistency_locked()
        # A writer commits the two attached files together. Reserve the same
        # lock while scanning so a concurrent connection cannot be observed
        # halfway between our separate primary/mirror SELECT statements.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            count = self._scan_consistency_locked()
            self.db.execute("COMMIT")
            return count
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _scan_consistency_locked(self) -> int:
        primary_ids = {row[0] for row in self.db.execute("SELECT id FROM records")}
        mirror_ids = {row[0] for row in self.db.execute("SELECT id FROM mirror.labels")}
        if primary_ids != mirror_ids:
            raise LabelConflict("Primary and mirror ID sets differ")
        current_revision = self.revision()
        primary_events = [tuple(row) for row in self.db.execute(
            "SELECT * FROM label_outbox ORDER BY scope_id,revision")]
        mirror_events = [tuple(row) for row in self.db.execute(
            "SELECT * FROM mirror.label_outbox ORDER BY scope_id,revision")]
        if primary_events != mirror_events:
            raise LabelConflict("Outbox copies differ")
        for node_id in primary_ids:
            record = self.read(node_id)
            if record.created_revision > current_revision:
                raise LabelConflict("Record is newer than scope revision")
            if record.producer in {"model", "host"}:
                try:
                    parent_labels = [self.read(parent).label for parent in record.parents]
                except KeyError as exc:
                    raise LabelConflict("Missing captured parent") from exc
                if record.label != derived_label(tuple(parent_labels), record.producer):
                    raise LabelConflict("Derived label no longer matches parents")
            elif record.producer == "repair":
                try:
                    parent_labels = [self.read(parent).label for parent in record.parents]
                except KeyError as exc:
                    raise LabelConflict("Missing repair parent") from exc
                inherited = frozenset().union(*(x.origins for x in parent_labels))
                if (record.label.integrity != Integrity.UNTRUSTED
                    or not inherited <= record.label.origins):
                    raise LabelConflict("Repair label promoted inherited input")
            elif record.producer != "source":
                raise LabelConflict("Unknown producer")
        return len(primary_ids)
