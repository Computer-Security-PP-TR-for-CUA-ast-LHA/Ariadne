"""Exercise the author's TMA-NM gate and parameter recovery, with no model.

All signing keys and authority assertions here are synthetic test fixtures. This
does not establish a real identity/confirmation channel or semantic cleansing.
"""
import argparse
import json
import secrets

from cua_guard.upstreams import UpstreamRegistry


def run(root=None):
    registry = UpstreamRegistry(root)
    scoped, recovery = registry.tma_authority_modules()
    operation, subject = "publish_report", "synthetic-report"
    fields = frozenset({"resource", "recipient"})
    scopes = frozenset((operation, subject, field) for field in fields)
    authorities = {
        "owner": scoped.Authority("project-owner", secrets.token_bytes(32), scopes),
        "reviewer": scoped.Authority("project-reviewer", secrets.token_bytes(32), scopes),
    }
    policy = {operation: fields}
    now = 1_800_000_000
    approved = {"resource": "approved-report", "recipient": "approved@example.test"}
    records = []
    for channel, authority in authorities.items():
        for field, value in approved.items():
            record = {"operation": operation, "subject": subject, "field": field,
                      "value": value, "valid_from": now - 1, "valid_until": now + 60,
                      "endorsed": True}
            body, signature = scoped.sign(record, authority.key)
            records.append({"channel": channel, "body": body, "signature": signature})
    gate = scoped.ScopedGate(authorities, policy, k=2)
    for packet in records:
        if not gate.ingest(packet["channel"], packet["body"], packet["signature"], now):
            raise AssertionError("Original gate rejected a valid fixture endorsement")
    proposed = {**approved, "recipient": "collector@example.test"}
    denied = not gate.authorize_action(operation, subject, proposed, now)[0]
    repaired = recovery.authorized_parameters(authorities, policy, records, operation, subject, now)
    if repaired["status"] != "available":
        raise AssertionError("Original recovery catalog did not find the unique approved values")
    resumed, snapshot = gate.authorize_action(operation, subject, repaired["fields"], now)
    unknown_operation_denied = not gate.authorize_action("other_operation", subject, approved, now)[0]
    expired_denied = not gate.authorize_action(operation, subject, approved, now + 61)[0]
    gate.revoke("reviewer")
    revoked_denied = not gate.authorize_action(operation, subject, approved, now)[0]
    checks = {"unapproved_recipient_denied": denied,
              "author_recovery_returns_exact_approved_fields": repaired["fields"] == approved,
              "recovered_action_authorized": resumed and snapshot == approved,
              "unknown_operation_denied": unknown_operation_denied,
              "expired_authority_denied": expired_denied,
              "revoked_authority_denied": revoked_denied}
    if not all(checks.values()):
        raise AssertionError(checks)
    return {"kind": "original_upstream_authority_integration", "model_calls": 0,
            "upstream_commit": registry.sources["mem-inv-bench"]["commit"],
            "implementation": [str(scoped.__file__), str(recovery.__file__)],
            "checks": checks, "recovered_fields": repaired["fields"],
            "limits": "Synthetic two-domain authority; no real tool execution, semantic repair, or live-model ASR."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root")
    args = parser.parse_args()
    print(json.dumps(run(args.upstream_root), indent=2))
