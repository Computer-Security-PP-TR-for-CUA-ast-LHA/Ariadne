"""Actual reuse of the TMA-NM channel registry in a durable label adapter.

Vendored upstream: yedidel/mem-inv-bench, commit
cf3c9a4ca9f0478000d6aa26eb268b875232d34b, MIT. The upstream monitor is
experimental and in memory; this adapter only reuses authenticated channel
classification, then persists the resulting label in Ariadne's two files.
"""
from __future__ import annotations

from .label_store import (Confidentiality, Integrity, PersistentLabelStore,
                          SecurityLabel)
from .vendor.tma import BIND, Envelope, Origin, Registry


class AuthenticatedSourceIngest:
    def __init__(self, store: PersistentLabelStore, registry: Registry):
        if registry.fail_open:
            raise ValueError("TMA registry must fail closed")
        self.store = store
        self.registry = registry

    def ingest(self, artifact: str, envelope: Envelope,
               confidentiality: Confidentiality = Confidentiality.PUBLIC,
               principals: frozenset[str] = frozenset(), *,
               session_id: str = "") -> str:
        origin, domain = self.registry.verify(envelope)
        if origin is None or domain is None:
            raise ValueError("Source classification unavailable")
        channel = {Origin.USER: "user", Origin.TRUSTED: "tool",
                   Origin.AGENT: "model", Origin.UNTRUSTED: "external"}[origin]
        label = SecurityLabel(
            Integrity.TRUSTED if origin in {Origin.USER, Origin.TRUSTED} else Integrity.UNTRUSTED,
            Confidentiality(confidentiality), frozenset({channel}),
            frozenset(principals), frozenset({domain}), BIND[origin],
        )
        return self.store._write(artifact, envelope.payload, label, (), "source",
                                 session_id)
