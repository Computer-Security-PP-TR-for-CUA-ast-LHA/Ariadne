"""Real AgentLAB EnvManager/BaseEnv adapter, with a bounded DeepSeek tool loop.

This is an environment integration, not a reproduction of its attack optimizer.
"""
import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from .model import DeepSeekClient, ModelError
from .label_bridge import LabelRecoveryBridge
from .label_runtime import LabelSession
from .label_policy import HostGrant
from .label_store import Confidentiality, PersistentLabelStore
from .label_provenance import LabelProvenancePort
from .provenance import write_json
from .recovery import SQLiteRecoveryStore
from .recovery.semantic import ModelRepairBackend, ModelRepairValidator
from .recovery.contracts import canonical, digest
from .runtime import GuardedSession
from .semantic import SemanticDefense

REVISION = "36f58e60c36bbd6d5b8e61d50d7db7d9ea7258d7"


def load_email_environment(root, parameters):
    root = Path(root).resolve()
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise RuntimeError("AgentLAB revision differs from the reviewed integration")
    sys.path.insert(0, str(root / "environments"))
    manager = importlib.import_module("EnvManager")
    if Path(manager.__file__).resolve().parent != root / "environments":
        raise RuntimeError("Unexpected EnvManager module")
    env = manager.EnvManager().init_env("Email", parameters)
    if env is None:
        raise RuntimeError("AgentLAB Email initialization failed")
    return env


def email_policy(tool, args):
    # This fixture authorizes reading and drafting a summary only. Sending,
    # links, attachments and password retrieval have no host capability.
    return tool in {"search_emails", "search_contacts", "list_contacts"}


def validate_tool_arguments(env, tool: str, arguments: dict) -> dict:
    """Reject coercion/field dropping before the approved byte string is bound."""
    description = env.get_tool_descs([tool])[0]["parameters"]
    properties = description.get("properties", {})
    if set(arguments) - set(properties) or not set(description.get("required", ())) <= set(arguments):
        raise ValueError("Tool arguments do not match the benchmark schema")
    kinds = {"string": lambda v: isinstance(v, str),
             "integer": lambda v: type(v) is int,
             "number": lambda v: type(v) in (int, float),
             "boolean": lambda v: type(v) is bool,
             "object": lambda v: isinstance(v, dict),
             "array": lambda v: isinstance(v, list)}
    normalized = {}
    for name, value in arguments.items():
        kind = properties[name].get("type")
        if kind not in kinds or not kinds[kind](value):
            raise ValueError("Tool argument type differs from the benchmark schema")
        normalized[name] = float(value) if kind == "number" else value
    return json.loads(canonical(normalized))


def run(env, session, max_steps=5, *, principal: str | None = None):
    if principal is not None and (not isinstance(principal, str) or not principal.strip()):
        raise ValueError("Benchmark principal must be a nonempty host string")
    allowed = [x for x in env.tool_list if email_policy(x, {})]
    tools = [{"type": "function", "function": x} for x in env.get_tool_descs(allowed)]
    for _ in range(max_steps):
        session.screen()
        reply = session.client.complete(session.messages(), tools=tools)
        calls = reply.get("tool_calls", [])
        if not calls:
            answer = reply.get("content")
            if not isinstance(answer, str) or not answer.strip():
                raise ModelError("Missing final answer")
            # Generated memory/output is also tracked and checked before release.
            node = session.capture("answer:" + str(uuid4()), answer, tuple(session.context))
            session.screen()
            if isinstance(session, LabelSession):
                return session.output_for(node)
            clean = next((r["replacements"][node] for r in reversed(session.repairs)
                          if node in r["replacements"]), node)
            return session.store.get(clean)["content"]
        if len(calls) > 4:
            raise ModelError("Too many tool calls")
        for call in calls:
            tool = call["function"]["name"]
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ModelError("Tool arguments must be an object")
            if tool not in env.tool_list and isinstance(session, LabelSession):
                session.reject_proposal(tool, arguments, "unknown_benchmark_tool")
            try:
                arguments = validate_tool_arguments(env, tool, arguments)
            except ValueError as exc:
                if isinstance(session, LabelSession):
                    session.reject_proposal(tool, arguments, "invalid_benchmark_arguments")
                raise ModelError(str(exc)) from exc

            def execute(name, args):
                approved_bytes = canonical(args)
                result = env.call_tool(name, args)
                if canonical(args) != approved_bytes:
                    raise RuntimeError("Benchmark tool mutated approved arguments")
                return result
            if isinstance(session, LabelSession):
                def policy(name, args):
                    if not email_policy(name, args):
                        return False
                    resource = digest(canonical({"tool": name, "arguments": args}))
                    return HostGrant(session.task_id, name, resource, "host-tool",
                                     Confidentiality.USER_IDENTITY if principal else
                                     Confidentiality.PRIVATE,
                                     frozenset({principal}) if principal else frozenset())
            else:
                policy = email_policy
            result = session.dispatch(tool, arguments, policy,
                                      execute)
            if callback := getattr(getattr(session, "graph", None),
                                   "on_tool_observation", None):
                callback(tool)
            # Never replay unsanitized assistant/tool histories after a repair.
            content = json.dumps({"tool": tool, "arguments": arguments, "result": result},
                                 ensure_ascii=False)
            if isinstance(session, LabelSession):
                session.capture("tool-result:" + str(uuid4()), content,
                                confidentiality=Confidentiality.USER_IDENTITY if principal else
                                Confidentiality.PRIVATE,
                                principals=frozenset({principal}) if principal else frozenset())
            else:
                session.capture("tool-result:" + str(uuid4()), content)
    raise ModelError("Agent step limit reached")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--upstream", required=True)
    p.add_argument("--fixture", required=True, type=Path)
    p.add_argument("--output", type=Path, default=Path("runs/agentlab"))
    p.add_argument("--max-steps", type=int, default=5)
    args = p.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    client = DeepSeekClient.from_env()
    env = load_email_environment(args.upstream, fixture["parameters"])
    args.output.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    store = PersistentLabelStore(args.output / (run_id + "-primary.sqlite"),
                                 args.output / (run_id + "-labels.sqlite"), scope_id=run_id)
    recovery = SQLiteRecoveryStore(args.output / (run_id + "-recovery.sqlite"))
    bridge = LabelRecoveryBridge(store, recovery)
    graph_port = LabelProvenancePort(bridge, fixture["task"])
    session = LabelSession(bridge, client, fixture["task"], graph=graph_port,
                           detector=SemanticDefense(store, client).inspect,
                           repair_backend=ModelRepairBackend(client, configuration_id=client.model),
                           validator=ModelRepairValidator(client, configuration_id=client.model))
    try:
        answer = run(env, session, args.max_steps, principal=fixture.get("principal"))
        graph = graph_port.build()
        graph_port.snapshot(run_id)
        write_json(graph, args.output / (run_id + "-provenance.json"))
        report = {"kind": "live_model_agentlab_environment", "upstream": REVISION,
                  "model": client.model, "answer": answer, "usage": client.usage,
                  "repairs": session.repairs,
                  "alerts": [alert.as_dict() for alert in session.alerts],
                  "scope_id": run_id, "ledger_revision": store.revision(),
                  "provenance_nodes": len(graph.nodes),
                  "provenance_coverage": graph.coverage}
        (args.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "completed", "calls": client.calls, "output": str(args.output)}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
