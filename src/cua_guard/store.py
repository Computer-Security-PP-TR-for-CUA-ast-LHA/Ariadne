"""Versioned host ledger. The caller is a trusted harness, not the model.

Origin records denote observed channels. They do not certify content truth.
Edges record captured input dependencies, not proven causal influence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ProvenanceStore:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
          id TEXT PRIMARY KEY, artifact TEXT NOT NULL, version INTEGER NOT NULL,
          content TEXT NOT NULL, hash TEXT NOT NULL, origins TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('active','quarantined')),
          kind TEXT NOT NULL, UNIQUE(artifact,version));
        CREATE TABLE IF NOT EXISTS edges (
          parent TEXT REFERENCES nodes(id), child TEXT REFERENCES nodes(id),
          PRIMARY KEY(parent,child));
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls (
          id TEXT PRIMARY KEY, payload TEXT NOT NULL, decision TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    def _event(self, kind: str, payload: dict) -> None:
        self.db.execute("INSERT INTO events(kind,payload) VALUES (?,?)",
                        (kind, json.dumps(payload, sort_keys=True)))

    def get(self, node_id: str) -> dict:
        row = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(node_id)
        node = dict(row)
        node["origins"] = json.loads(node["origins"])
        return node

    def _insert(self, artifact: str, content: str, origins: set[str],
                parents: tuple[str, ...], kind: str) -> str:
        if not artifact or not isinstance(content, str):
            raise ValueError("An artifact ID and string content are required")
        for parent in parents:
            if self.get(parent)["status"] != "active":
                raise ValueError("Cannot derive from quarantined state")
        version = self.db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM nodes WHERE artifact=?", (artifact,)
        ).fetchone()[0]
        node_id = str(uuid4())
        self.db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)", (
            node_id, artifact, version, content, digest(content),
            json.dumps(sorted(origins)), "active", kind))
        self.db.executemany("INSERT INTO edges VALUES (?,?)", [(p, node_id) for p in parents])
        self._event("write", {"node": node_id, "parents": parents, "kind": kind})
        return node_id

    def ingest(self, artifact: str, content: str, channel: str = "external") -> str:
        """Trusted host supplies channel; never read it from document text."""
        if channel not in {"user", "external", "unknown"}:
            raise ValueError("Unsupported origin channel")
        with self.db:
            return self._insert(artifact, content, {channel}, (), "ingest")

    def derive(self, artifact: str, content: str, parents: tuple[str, ...]) -> str:
        """Host supplies every captured input; missing parents stay unknown."""
        parents = tuple(dict.fromkeys(parents))
        with self.db:
            origins = {o for p in parents for o in self.get(p)["origins"]}
            return self._insert(artifact, content, origins or {"unknown"}, parents, "derive")

    def envelope(self, node_id: str) -> dict:
        n = self.get(node_id)
        return {k: n[k] for k in ("id", "version", "hash", "origins")}

    def verify(self, envelope: dict, content: str) -> bool:
        try:
            n = self.get(envelope["id"])
            return (n["status"] == "active" and self.envelope(n["id"]) == envelope
                    and digest(content) == n["hash"])
        except (KeyError, TypeError):
            return False

    def descendants(self, roots: tuple[str, ...]) -> set[str]:
        visited: set[str] = set()
        todo = list(roots)
        while todo:
            node_id = todo.pop()
            self.get(node_id)  # Reject nonexistent roots.
            if node_id in visited:
                continue
            visited.add(node_id)
            todo.extend(row[0] for row in self.db.execute(
                "SELECT child FROM edges WHERE parent=?", (node_id,)))
        return visited

    def quarantine(self, roots: tuple[str, ...], reason: str) -> list[str]:
        """Conservative closure, not exact semantic contamination detection."""
        if not roots or not reason.strip():
            raise ValueError("Evidence roots and a reason are required")
        with self.db:
            affected = sorted(self.descendants(roots))
            self.db.executemany("UPDATE nodes SET status='quarantined' WHERE id=?",
                                [(n,) for n in affected])
            self._event("quarantine", {"roots": roots, "affected": affected, "reason": reason})
        return affected

    def rebuild(self, old_id: str, content: str, clean_parents: tuple[str, ...]) -> str:
        """Commit host-validated output as a new version; never untaint old state.

        Does not run an LLM or validate semantic cleanliness. Callers must do so
        separately. 'external' provenance remains external after rebuilding.
        """
        with self.db:
            old = self.get(old_id)
            if old["status"] != "quarantined" or not clean_parents:
                raise ValueError("Rebuild needs quarantined old state and active inputs")
            parents = tuple(dict.fromkeys(clean_parents))
            origins = {o for p in parents for o in self.get(p)["origins"]}
            new_id = self._insert(old["artifact"], content, origins, parents, "rebuild")
            # Supersession is an audit relation, not a polluted content dependency.
            self._event("supersede", {"old": old_id, "new": new_id})
            return new_id

    def record_call(self, call_id: str, payload: dict, decision: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO calls VALUES (?,?,?)",
                            (call_id, json.dumps(payload, sort_keys=True), decision))

    def call(self, call_id: str) -> dict:
        row = self.db.execute("SELECT payload FROM calls WHERE id=?", (call_id,)).fetchone()
        if row is None:
            raise KeyError(call_id)
        return json.loads(row[0])
