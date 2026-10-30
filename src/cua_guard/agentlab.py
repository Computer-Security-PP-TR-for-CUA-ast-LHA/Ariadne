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
from .runtime import GuardedSession
from .store import ProvenanceStore

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


def run(env, session, max_steps=5):
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
            result = session.dispatch(tool, arguments, email_policy,
                                      lambda name, args: env.call_tool(name, args))
            # Never replay unsanitized assistant/tool histories after a repair.
            session.capture("tool-result:" + str(uuid4()), json.dumps({
                "tool": tool, "arguments": arguments, "result": result}, ensure_ascii=False))
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
    store = ProvenanceStore(args.output / (str(uuid4()) + ".sqlite"))
    session = GuardedSession(store, client, fixture["task"])
    try:
        answer = run(env, session, args.max_steps)
        report = {"kind": "live_model_agentlab_environment", "upstream": REVISION,
                  "model": client.model, "answer": answer, "usage": client.usage,
                  "repairs": session.repairs}
        (args.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "completed", "calls": client.calls, "output": str(args.output)}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
