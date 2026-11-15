"""Transactional reference ledger. All host reads/writes must go through this API.

The database is trusted host state, not an attacker-writable memory document.
Content versions are immutable; status, context and recovery jobs are transactional.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import time
import uuid
from filelock import FileLock, Timeout

from .contracts import Edge, RecoveryError, Snapshot, Version, canonical, digest, identity
from .graph import VersionGraph


class SQLiteRecoveryStore:
    def __init__(self, path):
        self.path = str(Path(path))
        if self.path == ':memory:':
            raise ValueError('Use a file: each unit of work opens its own connection')
        self.path = str(Path(path).resolve())
        with self._tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS recovery_scopes(
                scope TEXT PRIMARY KEY, revision INTEGER NOT NULL, owner TEXT);
            CREATE TABLE IF NOT EXISTS recovery_versions(
                scope TEXT, id TEXT, record TEXT NOT NULL, PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS recovery_edges(
                scope TEXT, source TEXT, target TEXT, kind TEXT,
                PRIMARY KEY(scope,source,target,kind));
            CREATE TABLE IF NOT EXISTS recovery_sessions(
                scope TEXT, id TEXT, refs TEXT NOT NULL, PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS recovery_calls(
                scope TEXT, id TEXT, refs TEXT NOT NULL, PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS recovery_jobs(
                scope TEXT, id TEXT, record TEXT NOT NULL, PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS recovery_effects(
                scope TEXT, operation_id TEXT, record TEXT NOT NULL,
                PRIMARY KEY(scope,operation_id));
            CREATE TABLE IF NOT EXISTS recovery_authority_epochs(
                scope TEXT PRIMARY KEY, epoch INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_consumed_grants(
                scope TEXT, grant_id TEXT, PRIMARY KEY(scope,grant_id));
            CREATE TABLE IF NOT EXISTS recovery_audit(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT,
                kind TEXT NOT NULL, record TEXT NOT NULL);
            ''')

    @contextmanager
    def recovery_lock(self, scope):
        """Upstream cross-platform filelock; local single-writer fencing only."""
        name = self.path + '.' + digest(scope)[:32] + '.lock'
        try:
            with FileLock(name, timeout=0):
                yield
        except Timeout as exc:
            raise RecoveryError('scope_worker_busy') from exc

    def workflow_path(self, scope):
        return self.path + '.' + digest(scope)[:32] + '.workflow.sqlite'

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _scope(db, scope):
        row = db.execute('SELECT revision,owner FROM recovery_scopes WHERE scope=?', (scope,)).fetchone()
        if row is None:
            raise RecoveryError('unknown_scope')
        return row

    @staticmethod
    def _versions(db, scope):
        return {row[0]: Version.from_dict(json.loads(row[1])) for row in db.execute(
            'SELECT id,record FROM recovery_versions WHERE scope=? ORDER BY id', (scope,))}

    @staticmethod
    def _audit(db, scope, kind, record):
        db.execute('INSERT INTO recovery_audit(scope,kind,record) VALUES(?,?,?)', (scope, kind, canonical(record)))

    @staticmethod
    def _put_version(db, scope, v):
        db.execute('INSERT INTO recovery_versions VALUES(?,?,?)', (scope, v.version_id, canonical(asdict(v))))

    @staticmethod
    def _job(db, scope, request_id):
        row = db.execute('SELECT record FROM recovery_jobs WHERE scope=? AND id=?', (scope, request_id)).fetchone()
        if row is None:
            raise RecoveryError('unknown_request')
        return json.loads(row[0])

    @staticmethod
    def _save(db, job):
        db.execute('INSERT OR REPLACE INTO recovery_jobs VALUES(?,?,?)',
                   (job['scope_id'], job['request_id'], canonical(job)))

    def _owned(self, db, request):
        rev, owner = self._scope(db, request.scope_id)
        if owner != request.request_id:
            raise RecoveryError('recovery_ownership_lost')
        job = self._job(db, request.scope_id, request.request_id)
        if job['request'] != json.loads(canonical(asdict(request))):
            raise RecoveryError('request_id_conflict')
        if job['revision'] != rev:
            raise RecoveryError('revision_conflict')
        return job

    def seed(self, snapshot: Snapshot, sessions: dict[str, tuple[str, ...]]):
        """One-time trusted import. Existing scopes cannot be overwritten."""
        graph = VersionGraph(snapshot)
        if any(v.status != 'active' for v in graph.nodes.values()):
            raise RecoveryError('initial_versions_must_be_active')
        for session, refs in sessions.items():
            identity(session)
            if not isinstance(refs, tuple) or len(set(refs)) != len(refs) or not set(refs) <= graph.nodes.keys():
                raise RecoveryError('invalid_context')
        with self._tx() as db:
            if db.execute('SELECT 1 FROM recovery_scopes WHERE scope=?', (snapshot.scope_id,)).fetchone():
                raise RecoveryError('scope_exists')
            db.execute('INSERT INTO recovery_scopes VALUES(?,?,NULL)', (snapshot.scope_id, snapshot.revision))
            for v in snapshot.versions:
                self._put_version(db, snapshot.scope_id, v)
            for e in snapshot.edges:
                db.execute('INSERT OR IGNORE INTO recovery_edges VALUES(?,?,?,?)', (snapshot.scope_id, e.source, e.target, e.kind))
            for session, refs in sessions.items():
                db.execute('INSERT INTO recovery_sessions VALUES(?,?,?)', (snapshot.scope_id, session, canonical(refs)))

    def snapshot(self, scope_id):
        """Privileged graph view includes quarantined/audit versions; never feed to agent."""
        with self._tx() as db:
            rev, _ = self._scope(db, scope_id)
            return Snapshot(scope_id, rev, tuple(self._versions(db, scope_id).values()),
                            tuple(Edge(*r) for r in db.execute(
                                'SELECT source,target,kind FROM recovery_edges WHERE scope=? ORDER BY source,target,kind', (scope_id,))))

    def append(self, scope, version: Version, session: str):
        """Host ingest/write hook. Persist dependencies before exposing the version."""
        identity(session)
        with self._tx() as db:
            rev, owner = self._scope(db, scope)
            if owner:
                raise RecoveryError('scope_blocked')
            nodes = self._versions(db, scope)
            if version.version_id in nodes or version.status != 'active':
                raise RecoveryError('invalid_new_version')
            if any(p not in nodes or nodes[p].status != 'active' for p in version.parents):
                raise RecoveryError('inactive_dependency')
            inherited = {o for p in version.parents for o in nodes[p].origins}
            if not inherited <= set(version.origins):
                raise RecoveryError('origin_downgrade')
            self._put_version(db, scope, version)
            for p in version.parents:
                db.execute('INSERT INTO recovery_edges VALUES(?,?,?,?)', (scope, p, version.version_id, 'derived_from'))
            row = db.execute('SELECT refs FROM recovery_sessions WHERE scope=? AND id=?', (scope, session)).fetchone()
            refs = json.loads(row[0]) if row else []
            refs.append(version.version_id)
            db.execute('INSERT OR REPLACE INTO recovery_sessions VALUES(?,?,?)', (scope, session, canonical(refs)))
            db.execute('UPDATE recovery_scopes SET revision=? WHERE scope=?', (rev + 1, scope))
            return rev + 1

    def record_call(self, scope, call_id, refs):
        identity(call_id)
        with self._tx() as db:
            _, owner = self._scope(db, scope)
            nodes = self._versions(db, scope)
            if owner:
                raise RecoveryError('scope_blocked')
            if not refs or any(r not in nodes or nodes[r].status != 'active' for r in refs):
                raise RecoveryError('invalid_call_binding')
            existing = db.execute('SELECT refs FROM recovery_calls WHERE scope=? AND id=?', (scope, call_id)).fetchone()
            if existing and existing[0] != canonical(refs):
                raise RecoveryError('call_id_conflict')
            db.execute('INSERT OR IGNORE INTO recovery_calls VALUES(?,?,?)', (scope, call_id, canonical(refs)))

    def call_bindings(self, scope, call_id):
        with self._tx() as db:
            row = db.execute('SELECT refs FROM recovery_calls WHERE scope=? AND id=?', (scope, call_id)).fetchone()
            if not row:
                raise RecoveryError('unknown_call')
            return tuple(json.loads(row[0]))

    def reserve(self, request, configuration):
        fingerprint = digest(canonical({'request': asdict(request), 'configuration': configuration}))
        with self._tx() as db:
            rev, owner = self._scope(db, request.scope_id)
            row = db.execute('SELECT record FROM recovery_jobs WHERE scope=? AND id=?', (request.scope_id, request.request_id)).fetchone()
            if row:
                job = json.loads(row[0])
                if job['fingerprint'] != fingerprint:
                    raise RecoveryError('request_id_conflict')
                return job
            if owner:
                raise RecoveryError('scope_busy')
            # In-flight effects cannot be rolled back; finish/reconcile before repair.
            uncertain = [json.loads(r[0]) for r in db.execute('SELECT record FROM recovery_effects WHERE scope=?', (request.scope_id,))]
            job = {'scope_id': request.scope_id, 'request_id': request.request_id,
                   'request': asdict(request), 'configuration': configuration, 'fingerprint': fingerprint,
                   'revision': rev, 'state': 'reserved', 'plan': None, 'staged': {}, 'error': None,
                   'unresolved_effects': [r['operation_id'] for r in uncertain if r['status'] in {'in_flight', 'unknown'}]}
            db.execute('UPDATE recovery_scopes SET owner=? WHERE scope=?', (request.request_id, request.scope_id))
            self._save(db, job)
            self._audit(db, request.scope_id, 'barrier', {'request_id': request.request_id})
            return json.loads(canonical(job))

    def job(self, scope, request_id):
        with self._tx() as db:
            return self._job(db, scope, request_id)

    def quarantine(self, request, plan):
        with self._tx() as db:
            job = self._owned(db, request)
            if job['state'] != 'reserved' or plan['revision'] != job['revision']:
                raise RecoveryError('invalid_transition')
            nodes = self._versions(db, request.scope_id)
            for vid in plan['targets']:
                v = replace(nodes[vid], status='quarantined')
                db.execute('UPDATE recovery_versions SET record=? WHERE scope=? AND id=?', (canonical(asdict(v)), request.scope_id, vid))
            job.update(state='quarantined', plan=plan, revision=job['revision'] + 1, error=None)
            db.execute('UPDATE recovery_scopes SET revision=? WHERE scope=?', (job['revision'], request.scope_id))
            self._save(db, job)
            self._audit(db, request.scope_id, 'quarantined', {'targets': plan['targets']})
            return job

    def stage(self, request, old, outputs, inputs, validation):
        if not validation.accepted():
            raise RecoveryError('validation_rejected')
        if not isinstance(outputs, tuple) or not 1 <= len(outputs) <= 16 or any(not isinstance(s, str) or not s.strip() or len(s) > 100_000 for s in outputs):
            raise RecoveryError('invalid_replacement')
        with self._tx() as db:
            job = self._owned(db, request)
            if job['state'] != 'quarantined' or old.version_id not in job['plan']['targets']:
                raise RecoveryError('invalid_transition')
            if old.version_id in job['staged']:
                raise RecoveryError('already_staged')
            nodes = self._versions(db, request.scope_id)
            if nodes[old.version_id] != old or old.status != 'quarantined':
                raise RecoveryError('version_conflict')
            expected = []
            for parent in old.parents:
                if parent in job['plan']['targets']:
                    if parent not in job['staged']:
                        raise RecoveryError('predecessor_not_ready')
                    expected.extend(Version.from_dict(v) for v in job['staged'][parent]['versions'])
                else:
                    if nodes[parent].status != 'active':
                        raise RecoveryError('inactive_dependency')
                    expected.append(nodes[parent])
            if tuple(expected) != inputs:
                raise RecoveryError('replacement_dependency_mismatch')
            origins = tuple(sorted(set(old.origins) | {o for v in inputs for o in v.origins}))
            replacements = [Version(str(uuid.uuid4()), old.artifact_id, s, digest(s), origins,
                                    tuple(v.version_id for v in inputs), 'staged', old.writer_key, old.session_id) for s in outputs]
            job['staged'][old.version_id] = {'versions': [asdict(v) for v in replacements], 'validation': asdict(validation)}
            self._save(db, job)
            return job

    def publish(self, request):
        with self._tx() as db:
            job = self._owned(db, request)
            if job['state'] != 'quarantined' or set(job['staged']) != set(job['plan']['targets']):
                raise RecoveryError('incomplete_repair')
            nodes = self._versions(db, request.scope_id)
            mapping = {}
            for old_id in job['plan']['targets']:
                record = job['staged'][old_id]
                if record['validation']['safe'] is not True or record['validation']['faithful'] is not True or not record['validation']['evidence']:
                    raise RecoveryError('validation_rejected')
                replacements = [replace(Version.from_dict(v), status='active') for v in record['versions']]
                if not replacements:
                    raise RecoveryError('invalid_replacement')
                mapping[old_id] = [v.version_id for v in replacements]
                for v in replacements:
                    if any(p not in nodes or nodes[p].status != 'active' for p in v.parents):
                        raise RecoveryError('predecessor_not_ready')
                    self._put_version(db, request.scope_id, v)
                    nodes[v.version_id] = v
                    for p in v.parents:
                        db.execute('INSERT INTO recovery_edges VALUES(?,?,?,?)', (request.scope_id, p, v.version_id, 'derived_from'))
                    db.execute('INSERT INTO recovery_edges VALUES(?,?,?,?)', (request.scope_id, old_id, v.version_id, 'sanitized_from'))
                nodes[old_id] = replace(nodes[old_id], status='superseded')
                db.execute('UPDATE recovery_versions SET record=? WHERE scope=? AND id=?',
                           (canonical(asdict(nodes[old_id])), request.scope_id, old_id))
            sessions = list(db.execute('SELECT id,refs FROM recovery_sessions WHERE scope=?', (request.scope_id,)))
            for sid, raw in sessions:
                refs = list(dict.fromkeys(n for old in json.loads(raw) for n in mapping.get(old, [old])))
                if any(nodes[n].status != 'active' for n in refs):
                    raise RecoveryError('inactive_context')
                db.execute('UPDATE recovery_sessions SET refs=? WHERE scope=? AND id=?', (canonical(refs), request.scope_id, sid))
            job.update(state='published', mapping=mapping, revision=job['revision'] + 1, error=None)
            db.execute('UPDATE recovery_scopes SET revision=? WHERE scope=?', (job['revision'], request.scope_id))
            self._save(db, job)
            self._audit(db, request.scope_id, 'published', {'request_id': request.request_id, 'mapping': mapping})
            return job

    def _manifest(self, db, scope):
        rev, _ = self._scope(db, scope)
        nodes = self._versions(db, scope)
        result = {'scope_id': scope, 'revision': rev,
                  'versions': [asdict(v) for v in nodes.values() if v.status == 'active'],
                  'withdrawn': [{'version_id': v.version_id, 'status': v.status, 'content_sha256': v.content_sha256}
                                for v in nodes.values() if v.status != 'active'],
                  'sessions': {sid: json.loads(raw) for sid, raw in db.execute(
                      'SELECT id,refs FROM recovery_sessions WHERE scope=? ORDER BY id', (scope,))}}
        result['digest'] = digest(canonical(result))
        return result

    def manifest(self, scope):
        """Privileged projection export; usable by host only after acknowledgment."""
        with self._tx() as db:
            return self._manifest(db, scope)

    def acknowledge(self, request, manifest_digest):
        with self._tx() as db:
            job = self._owned(db, request)
            if job['state'] != 'published' or manifest_digest != self._manifest(db, request.scope_id)['digest']:
                raise RecoveryError('projection_not_acknowledged')
            effects = [json.loads(r[0]) for r in db.execute('SELECT record FROM recovery_effects WHERE scope=?', (request.scope_id,))]
            if any(r['status'] in {'in_flight', 'unknown'} for r in effects):
                raise RecoveryError('unresolved_effect')
            affected = set(job['plan']['affected'])
            if any(r['status'] == 'committed' and any(vid in affected for vid, _ in r['bindings'])
                   and request.request_id not in r.get('incident_reviews', {}) for r in effects):
                raise RecoveryError('affected_committed_effect_requires_review')
            job.update(state='ready', error=None, manifest_digest=manifest_digest)
            db.execute('UPDATE recovery_scopes SET owner=NULL WHERE scope=?', (request.scope_id,))
            self._save(db, job)
            self._audit(db, request.scope_id, 'ready', {'request_id': request.request_id, 'revision': job['revision']})
            return job

    def fail(self, request, code, *, review=None):
        with self._tx() as db:
            job = self._owned(db, request)
            job['error'] = code  # retain durable phase for explicit retry
            if review is not None:
                job['last_validation_rejection'] = review
            self._save(db, job)
            self._audit(db, request.scope_id, 'needs_review', {'request_id': request.request_id, 'code': code})
            return job

    def ready(self, scope, revision):
        with self._tx() as db:
            rev, owner = self._scope(db, scope)
            uncertain = any(json.loads(r[0])['status'] in {'in_flight', 'unknown'} for r in db.execute(
                'SELECT record FROM recovery_effects WHERE scope=?', (scope,)))
            return rev == revision and owner is None and not uncertain

    def context(self, scope, session):
        with self._tx() as db:
            rev, owner = self._scope(db, scope)
            if owner:
                raise RecoveryError('scope_blocked')
            row = db.execute('SELECT refs FROM recovery_sessions WHERE scope=? AND id=?', (scope, session)).fetchone()
            if row is None:
                raise RecoveryError('unknown_session')
            nodes = self._versions(db, scope)
            versions = tuple(nodes[n] for n in json.loads(row[0]))
            if any(v.status != 'active' for v in versions):
                raise RecoveryError('inactive_context')
            return rev, versions

    def authority_epoch(self, scope):
        with self._tx() as db:
            self._scope(db, scope)
            row = db.execute('SELECT epoch FROM recovery_authority_epochs WHERE scope=?', (scope,)).fetchone()
            return row[0] if row else 0

    def revoke_authorizations(self, scope):
        """Host policy hook. Invalidates all outstanding grants; never rewound."""
        with self._tx() as db:
            self._scope(db, scope)
            row = db.execute('SELECT epoch FROM recovery_authority_epochs WHERE scope=?', (scope,)).fetchone()
            epoch = (row[0] if row else 0) + 1
            db.execute('INSERT OR REPLACE INTO recovery_authority_epochs VALUES(?,?)', (scope, epoch))
            self._audit(db, scope, 'authority_revoked', {'epoch': epoch})
            return epoch

    def claim_effect(self, scope, session, operation_id, revision, bindings, payload, grant):
        identity(operation_id)
        encoded = canonical(payload)
        with self._tx() as db:
            rev, owner = self._scope(db, scope)
            if owner or rev != revision:
                raise RecoveryError('stale_or_blocked_action')
            if any(json.loads(r[0])['status'] in {'in_flight', 'unknown'} for r in db.execute(
                    'SELECT record FROM recovery_effects WHERE scope=?', (scope,))):
                raise RecoveryError('unresolved_effect')
            epoch_row = db.execute('SELECT epoch FROM recovery_authority_epochs WHERE scope=?', (scope,)).fetchone()
            epoch = epoch_row[0] if epoch_row else 0
            if grant.proposal_hash != digest(encoded) or grant.epoch != epoch or grant.expires_at <= time.time():
                raise RecoveryError('stale_authorization')
            if db.execute('SELECT 1 FROM recovery_consumed_grants WHERE scope=? AND grant_id=?', (scope, grant.grant_id)).fetchone():
                raise RecoveryError('authorization_consumed')
            nodes = self._versions(db, scope)
            session_row = db.execute('SELECT refs FROM recovery_sessions WHERE scope=? AND id=?', (scope, session)).fetchone()
            if session_row is None:
                raise RecoveryError('unknown_session')
            refs = set(json.loads(session_row[0]))
            if not bindings or len({v for v, _ in bindings}) != len(bindings) or any(
                vid not in refs or nodes[vid].status != 'active' or nodes[vid].content_sha256 != sha for vid, sha in bindings):
                raise RecoveryError('invalid_action_binding')
            if db.execute('SELECT 1 FROM recovery_effects WHERE scope=? AND operation_id=?', (scope, operation_id)).fetchone():
                raise RecoveryError('effect_already_claimed')
            record = {'operation_id': operation_id, 'status': 'in_flight', 'payload_hash': digest(encoded),
                      'revision': rev, 'bindings': bindings, 'result': None}
            db.execute('INSERT INTO recovery_effects VALUES(?,?,?)', (scope, operation_id, canonical(record)))
            db.execute('INSERT INTO recovery_consumed_grants VALUES(?,?)', (scope, grant.grant_id))

    def finish_effect(self, scope, operation_id, result=None, unknown=False):
        with self._tx() as db:
            row = db.execute('SELECT record FROM recovery_effects WHERE scope=? AND operation_id=?', (scope, operation_id)).fetchone()
            if row is None:
                raise RecoveryError('unknown_effect')
            record = json.loads(row[0])
            if record['status'] != 'in_flight':
                raise RecoveryError('invalid_effect_transition')
            record.update(status='unknown' if unknown else 'committed', result=result)
            db.execute('UPDATE recovery_effects SET record=? WHERE scope=? AND operation_id=?', (canonical(record), scope, operation_id))

    def reconcile_effect(self, scope, operation_id, *, committed: bool, evidence: str):
        """Trusted host reconciliation only, based on remote receipt/query/manual review.

        An absent effect remains a terminal tombstone: retry needs a new host ID.
        """
        if type(committed) is not bool or not isinstance(evidence, str) or not evidence.strip():
            raise RecoveryError('reconciliation_evidence_required')
        with self._tx() as db:
            row = db.execute('SELECT record FROM recovery_effects WHERE scope=? AND operation_id=?', (scope, operation_id)).fetchone()
            if row is None:
                raise RecoveryError('unknown_effect')
            record = json.loads(row[0])
            if record['status'] not in {'in_flight', 'unknown'}:
                raise RecoveryError('invalid_effect_transition')
            record.update(status='committed' if committed else 'confirmed_absent', reconciliation=evidence)
            db.execute('UPDATE recovery_effects SET record=? WHERE scope=? AND operation_id=?', (canonical(record), scope, operation_id))
            self._audit(db, scope, 'effect_reconciled', {'operation_id': operation_id, 'evidence': evidence, 'committed': committed})

    def review_committed_effect(self, scope, operation_id, request_id, *, evidence: str):
        """Trusted incident handler attests an already committed effect was handled.

        This does NOT execute compensation. Evidence must reference actual remote
        remediation or an explicit decision accepting an irreversible outcome.
        Review is per incident and never erases the original effect tombstone.
        """
        if not isinstance(evidence, str) or not evidence.strip():
            raise RecoveryError('effect_review_evidence_required')
        with self._tx() as db:
            job = self._job(db, scope, request_id)
            row = db.execute('SELECT record FROM recovery_effects WHERE scope=? AND operation_id=?', (scope, operation_id)).fetchone()
            if row is None or job['plan'] is None:
                raise RecoveryError('unknown_effect_or_incident')
            record = json.loads(row[0])
            if record['status'] != 'committed' or not any(vid in job['plan']['affected'] for vid, _ in record['bindings']):
                raise RecoveryError('effect_not_affected_committed')
            record.setdefault('incident_reviews', {})[request_id] = evidence
            db.execute('UPDATE recovery_effects SET record=? WHERE scope=? AND operation_id=?', (canonical(record), scope, operation_id))
            self._audit(db, scope, 'committed_effect_reviewed', {'operation_id':operation_id,'request_id':request_id,'evidence':evidence})
