"""Fail-closed bridge from the dual label ledger to recovery v0.2.

Normal writes enter the label ledger first and are projected to recovery. A
projection gap blocks all managed reads/actions. During repair the recovery
owner barrier blocks use until the published manifest has been installed in
both label files and acknowledged by the managed context.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os

from .label_store import (
    Confidentiality, Integrity, PersistentLabelStore,
    SecurityLabel,
)
from .source_auth import AuthenticatedSourceIngest
from .vendor.tma import Channel, Origin, Registry
from .recovery.adapters import ManagedContextProjection
from .recovery.contracts import Edge, RecoveryError, Snapshot, Version, canonical, digest


def _version_from_labels(labels: PersistentLabelStore, node_id: str) -> Version:
    record = labels.read(node_id)
    content = labels.db.execute(
        "SELECT content FROM records WHERE id=?", (node_id,)).fetchone()[0]
    return Version(record.id, record.artifact, content, record.content_hash,
                   tuple(sorted(record.label.origins)), record.parents,
                   status=record.status)


def _snapshot_from_labels(labels: PersistentLabelStore) -> Snapshot:
    records = labels.records()
    versions = tuple(_version_from_labels(labels, record.id) for record in records)
    edges = [Edge(parent, record.id) for record in records for parent in record.parents]
    for row in labels.db.execute(
            "SELECT details_json FROM audit WHERE event='repair_publish' ORDER BY seq"):
        mapping = json.loads(row[0])["mapping"]
        edges.extend(Edge(old, new, "sanitized_from")
                     for old, news in mapping.items() for new in news)
    return Snapshot(labels.scope_id, labels.revision(), versions, tuple(edges))


def _assert_shadow_matches_labels(labels: PersistentLabelStore, recovery) -> int:
    """A working copy can authorize nothing unless it matches committed labels."""
    labels.scan_consistency()
    authoritative = _snapshot_from_labels(labels)
    shadow = recovery.snapshot(labels.scope_id)
    own = {v.version_id: v for v in authoritative.versions}
    copied = {v.version_id: v for v in shadow.versions}
    if (authoritative.revision != shadow.revision or set(own) != set(copied)
        or any(own[vid].artifact_id != copied[vid].artifact_id
               or own[vid].content_sha256 != copied[vid].content_sha256
               or own[vid].status != copied[vid].status
               or own[vid].parents != copied[vid].parents
               or own[vid].origins != copied[vid].origins for vid in own)
        or set(authoritative.edges) != set(shadow.edges)):
        raise RecoveryError("label_recovery_mismatch")
    return authoritative.revision


class LabelOwnedRecoveryStore:
    """Recovery coordinator port with label-owned isolation and revision.

    The recovery SQLite rows are a fenced working copy. Its isolation plan is
    committed to both label files before repair proceeds. A crash after the
    working-copy update can replay the same plan from the durable recovery job.
    Publication is likewise only usable after LabelRepairProjection commits
    the label files and the managed context acknowledges that revision.
    """

    def __init__(self, labels: PersistentLabelStore, working_copy):
        self.labels, self.working_copy = labels, working_copy

    def __getattr__(self, name):
        return getattr(self.working_copy, name)

    def _sync_quarantine(self, job: dict) -> None:
        plan = job.get("plan")
        if plan is None:
            return
        if plan["scope_id"] != self.labels.scope_id:
            raise RecoveryError("scope_mismatch")
        base = plan["revision"]
        current = self.labels.revision()
        if current == base or current == base + 1:
            self.labels.quarantine_repair(job["request_id"],
                                          tuple(plan["targets"]), base)
        elif current != job["revision"]:
            raise RecoveryError("label_recovery_mismatch")

    def quarantine(self, request, plan):
        if request.scope_id != self.labels.scope_id:
            raise RecoveryError("scope_mismatch")
        self.labels.scan_consistency()
        if self.labels.revision() != plan["revision"]:
            raise RecoveryError("label_recovery_mismatch")
        job = self.working_copy.quarantine(request, plan)
        self._sync_quarantine(job)
        return job

    def job(self, scope, request_id):
        job = self.working_copy.job(scope, request_id)
        self._sync_quarantine(job)
        return job


class LabelRecoveryBridge:
    def __init__(self, labels: PersistentLabelStore, recovery):
        self.labels = labels
        self.recovery = LabelOwnedRecoveryStore(labels, recovery)
        self.scope_id = labels.scope_id
        registry = Registry()
        self.channels = {
            "user": Channel("host-user", Origin.USER, "host-user", os.urandom(32)),
            "external": Channel("host-observation", Origin.UNTRUSTED,
                                "host-observation", os.urandom(32)),
        }
        for channel in self.channels.values():
            registry.register(channel)
        self.authenticated_ingest = AuthenticatedSourceIngest(labels, registry)

    def _source_write(self, session_id: str, artifact: str, content: str,
                      channel: str, confidentiality: Confidentiality,
                      principals: frozenset[str]) -> str:
        if channel in self.channels:
            return self.authenticated_ingest.ingest(
                artifact, self.channels[channel].send(content),
                confidentiality, principals, session_id=session_id)
        return self.labels.ingest(artifact, content, channel, confidentiality,
                                  principals, session_id=session_id)

    def _version(self, node_id: str) -> Version:
        return _version_from_labels(self.labels, node_id)

    def label_snapshot(self) -> Snapshot:
        return _snapshot_from_labels(self.labels)

    def snapshot(self, scope_id: str) -> Snapshot:
        if scope_id != self.scope_id:
            raise RecoveryError("scope_mismatch")
        return self.label_snapshot()

    def export_graph_handoff(self, after_revision: int = 0) -> dict:
        """Versioned host event export for a separate graph implementation."""
        revision = self.assert_ready()
        handoff = {"schema_version": "ariadne.label-events/0.1",
                "scope_id": self.scope_id, "ledger_revision": revision,
                "versions": [asdict(self._version(record.id)) for record in self.labels.records()],
                "events": list(self.labels.outbox(after_revision)),
                "repair_commits": [{"request_id": row[0], **json.loads(row[1])}
                                   for row in self.labels.db.execute(
                                       "SELECT record_id,details_json FROM audit "
                                       "WHERE event='repair_publish' ORDER BY seq")],
                "coverage": "complete_within_scope"}
        if (self.labels.revision() != revision
            or not self.recovery.ready(self.scope_id, revision)):
            raise RecoveryError("graph_export_stale")
        return handoff

    def assert_ready(self) -> int:
        self.labels.scan_consistency()
        revision = self.labels.revision()
        if not self.recovery.ready(self.scope_id, revision):
            raise RecoveryError("label_recovery_barrier")
        return _assert_shadow_matches_labels(self.labels, self.recovery)

    def start_session(self, session_id: str, task: str) -> str:
        try:
            self.recovery.snapshot(self.scope_id)
        except RecoveryError as exc:
            if exc.code != "unknown_scope":
                raise
            if self.labels.records():
                self.reconcile()
                return self.capture(session_id, "task:" + session_id, task, channel="user")
            with self.recovery.recovery_lock(self.scope_id):
                node_id = self._source_write(session_id, "task:" + session_id, task,
                                             "user", Confidentiality.PUBLIC, frozenset())
                self.recovery.seed(self.label_snapshot(), {session_id: (node_id,)})
                self.assert_ready()
                return node_id
        self.reconcile()
        return self.capture(session_id, "task:" + session_id, task, channel="user")

    def capture(self, session_id: str, artifact: str, content: str, *,
                channel: str = "external", parents: tuple[str, ...] = (),
                confidentiality: Confidentiality = Confidentiality.PUBLIC,
                principals: frozenset[str] = frozenset()) -> str:
        with self.recovery.recovery_lock(self.scope_id):
            self.assert_ready()
            if parents:
                node_id = self.labels.derive(artifact, content, parents,
                                             session_id=session_id)
            else:
                node_id = self._source_write(session_id, artifact, content, channel,
                                             confidentiality, principals)
            version = self._version(node_id)
            projected_revision = self.recovery.append(self.scope_id, version, session_id)
            if projected_revision != self.labels.revision():
                raise RecoveryError("label_recovery_mismatch")
            self.assert_ready()
            return node_id

    def reconcile(self) -> int:
        """Replay an interrupted normal-write projection from the mirrored outbox."""
        with self.recovery.recovery_lock(self.scope_id):
            return self._reconcile_locked()

    def _reconcile_locked(self) -> int:
        self.labels.scan_consistency()
        try:
            snapshot = self.recovery.snapshot(self.scope_id)
        except RecoveryError as exc:
            if exc.code != "unknown_scope":
                raise
            records = self.labels.records()
            events = self.labels.outbox()
            if (not records or len(events) != len(records)
                or any(e["kind"] != "write" or not e["session_id"] for e in events)
                or any(r.status != "active" for r in records)):
                raise RecoveryError("unreconciled_label_scope")
            sessions: dict[str, tuple[str, ...]] = {}
            for event in events:
                sid = event["session_id"]
                sessions[sid] = (*sessions.get(sid, ()), event["record_id"])
            self.recovery.seed(self.label_snapshot(), sessions)
            return self.assert_ready()
        if snapshot.revision > self.labels.revision():
            raise RecoveryError("label_projection_behind")
        existing = {v.version_id for v in snapshot.versions}
        for event in self.labels.outbox(snapshot.revision):
            if (event["revision"] != snapshot.revision + 1
                or event["kind"] != "write" or not event["session_id"]
                or event["record_id"] in existing):
                raise RecoveryError("unreconciled_label_scope")
            version = self._version(event["record_id"])
            if version.status != "active":
                raise RecoveryError("unreconciled_label_scope")
            self.recovery.append(self.scope_id, version, event["session_id"])
            snapshot = self.recovery.snapshot(self.scope_id)
            existing.add(version.version_id)
        return self.assert_ready()


class LabelRepairProjection:
    """Install one recovery manifest in both label files before context ACK."""

    identity = "dual-label-context/1"

    def __init__(self, labels: PersistentLabelStore, recovery, request_id: str):
        self.labels, self.recovery, self.request_id = labels, recovery, request_id
        self.context = ManagedContextProjection(recovery)

    def install(self, manifest: dict) -> str:
        scope = self.labels.scope_id
        if manifest.get("scope_id") != scope:
            raise RecoveryError("scope_mismatch")
        job = self.recovery.job(scope, self.request_id)
        if job["state"] not in {"published", "ready"} or job["revision"] != manifest["revision"]:
            raise RecoveryError("revision_conflict")
        expected = manifest["digest"]
        if digest(canonical({k: v for k, v in manifest.items() if k != "digest"})) != expected:
            raise RecoveryError("manifest_hash_mismatch")
        active = {v["version_id"]: Version.from_dict(v) for v in manifest["versions"]}
        withdrawn = {v["version_id"]: v for v in manifest["withdrawn"]}
        if set(active) & set(withdrawn):
            raise RecoveryError("manifest_overlap")
        target_ids = set(active) | set(withdrawn)
        existing = {r.id: r for r in self.labels.records()}
        if not set(existing) <= target_ids:
            raise RecoveryError("manifest_drops_version")
        old_for_new = {new: old for old, news in job.get("mapping", {}).items() for new in news}
        if any(new not in active or old not in existing for new, old in old_for_new.items()):
            raise RecoveryError("invalid_replacement_mapping")
        if any(node_id not in existing and node_id not in old_for_new for node_id in active):
            raise RecoveryError("unmapped_replacement")
        db = self.labels.db
        if db.in_transaction:
            raise RecoveryError("label_transaction_busy")
        db.execute("BEGIN IMMEDIATE")
        try:
            current = self.labels.revision()
            if current > manifest["revision"]:
                raise RecoveryError("stale_manifest")
            if current < manifest["revision"]:
                for node_id, record in existing.items():
                    status = "active" if node_id in active else withdrawn[node_id]["status"]
                    if node_id in active and (record.content_hash != active[node_id].content_sha256
                                             or record.status != "active"):
                        raise RecoveryError("existing_version_changed")
                    if node_id in withdrawn and record.content_hash != withdrawn[node_id]["content_sha256"]:
                        raise RecoveryError("existing_version_changed")
                    self._set_status(node_id, status)
                pending = {node_id: version for node_id, version in active.items()
                           if node_id not in existing}
                while pending:
                    ready = [version for version in pending.values() if all(
                        db.execute("SELECT 1 FROM records WHERE id=?", (parent,)).fetchone()
                        for parent in version.parents)]
                    if not ready:
                        raise RecoveryError("replacement_dependency_mismatch")
                    for version in ready:
                        self._insert_replacement(version, old_for_new, manifest["revision"])
                        del pending[version.version_id]
                for table in ("scope_revision", "mirror.scope_revision"):
                    db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)",
                               (scope, manifest["revision"]))
                db.execute("INSERT INTO audit(event,record_id,details_json) VALUES (?,?,?)",
                           ("repair_publish", self.request_id,
                            canonical({"revision": manifest["revision"], "mapping": job["mapping"]})))
                event = (scope, manifest["revision"], "", self.request_id,
                         "repair_publish")
                for table in ("label_outbox", "mirror.label_outbox"):
                    db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", event)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        self.labels.scan_consistency()
        if self.labels.revision() != manifest["revision"]:
            raise RecoveryError("label_replica_mismatch")
        for node_id in target_ids:
            record = self.labels.read(node_id)
            if node_id in active and record.status != "active":
                raise RecoveryError("label_replica_mismatch")
            if node_id in withdrawn and record.status != withdrawn[node_id]["status"]:
                raise RecoveryError("label_replica_mismatch")
        _assert_shadow_matches_labels(self.labels, self.recovery)
        if self.context.install(manifest) != expected:
            raise RecoveryError("projection_not_acknowledged")
        return expected

    def _set_status(self, node_id: str, status: str) -> None:
        db = self.labels.db
        db.execute("UPDATE records SET status=? WHERE id=?", (status, node_id))
        row = db.execute("SELECT * FROM records WHERE id=?", (node_id,)).fetchone()
        fields = ("id", "scope_id", "artifact", "version", "content_hash", "label_json",
                  "status", "parents_json", "producer", "created_revision")
        db.execute("UPDATE mirror.labels SET status=?,seal=? WHERE id=?",
                   (status, self.labels._seal(tuple(row[x] for x in fields)), node_id))

    def _insert_replacement(self, version: Version, old_for_new: dict[str, str],
                            revision: int) -> None:
        db = self.labels.db
        old = self.labels.read(old_for_new[version.version_id])
        related = [old.label] + [self.labels.read(p).label for p in version.parents]
        rank = {Confidentiality.PUBLIC: 0, Confidentiality.PRIVATE: 1,
                Confidentiality.USER_IDENTITY: 2}
        confidentiality = max((v.confidentiality for v in related), key=rank.__getitem__)
        origins = frozenset(version.origins)
        if not old.label.origins <= origins:
            raise RecoveryError("origin_downgrade")
        label = SecurityLabel(Integrity.UNTRUSTED, confidentiality, origins,
                              frozenset().union(*(v.principals for v in related)),
                              frozenset().union(*(v.domains for v in related)))
        number = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM records WHERE scope_id=? AND artifact=?",
                            (self.labels.scope_id, version.artifact_id)).fetchone()[0]
        common = (version.version_id, self.labels.scope_id, version.artifact_id, number,
                  version.content_sha256, canonical(label.as_dict()), "active",
                  canonical(version.parents), "repair", revision)
        db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   common[:4] + (version.content,) + common[4:])
        db.execute("INSERT INTO mirror.labels VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   common + (self.labels._seal(common),))
