"""Read-only, local-model utility pilot in AgentLAB's pinned AgentDojo Workspace suite."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from agentdojo.functions_runtime import FunctionCall
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import text_content_block_from_string as block
from pydantic_core import to_jsonable_python

from cua_guard.label_policy import Action, Evidence, HostGrant, check_action
from cua_guard.label_store import PersistentLabelStore
from cua_guard.provenance import ProvenanceRecorder, write_json, write_svg

TOOLS = {"search_calendar_events": {"query": "text", "date": "optional YYYY-MM-DD"},
         "get_day_calendar_events": {"day": "YYYY-MM-DD"}, "get_current_day": {}}
ENDPOINT = "http://127.0.0.1:18361/v1/chat/completions"
DOMAINS = {
    "calendar": (TOOLS, (0, 1, 2, 3, 11)),
    "email": ({"search_emails": {"query": "text", "sender": "optional email"},
               "get_unread_emails": {}}, (14, 17, 24)),
    "drive": ({"list_files": {}, "search_files_by_filename": {"filename": "text"},
               "search_files": {"query": "text"}}, (26, 27, 28, 30)),
}


def complete(system, prompt, trace, structured=False, transport=None):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    if transport is not None:
        answer = transport.complete(messages, json_output=structured)["content"]
        trace.append({"messages": messages, "output": answer, "usage": transport.usage[-1],
                      "model": transport.model})
        return answer
    body = {"messages": messages, "temperature": 0, "seed": 42, "max_tokens": 180}
    if structured:
        body["response_format"] = {"type": "json_object"}
    request = Request(ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=180) as response:
        reply = json.load(response)
    answer = reply["choices"][0]["message"]["content"]
    trace.append({"messages": messages, "output": answer, "usage": reply["usage"], "model": reply["model"]})
    return answer


class CalendarPilot:
    def __init__(self, store, directory, domain="calendar", expanded=False, transport=None):
        self.store = store
        self.transport = transport
        self.domain = domain
        self.tools = DOMAINS[domain][0]
        self.expanded = expanded
        self.directory = directory
        self.trace = []

    def query(self, prompt, runtime, env):
        task_node = self.store.ingest("task", prompt, "user") if self.store else None
        plan = json.loads(complete(
            f'Choose one read-only {self.domain} lookup. Reply with one JSON object of the form ' + '{"name":"tool", "args":{...}}. '
            'Use 2024 for dates without a year. Tools: ' + json.dumps(self.tools), prompt, self.trace, True,
            self.transport))
        name = plan["name"]
        args = plan.get("args", {} if name in self.tools and not self.tools[name] else None)
        if name not in self.tools or not isinstance(args, dict) or set(args) - self.tools[name].keys():
            raise ValueError("unsupported calendar query")
        if not all(isinstance(value, str) or value is None for value in args.values()):
            raise ValueError("only scalar query parameters are supported")
        if self.store:
            resource = json.dumps(args, sort_keys=True)
            evidence = Evidence(task_node, self.store.read(task_node).content_hash)
            action = Action(self.domain, name, resource, self.domain, (evidence,))
            grant = HostGrant(self.domain, name, resource, self.domain)
            decision = check_action(self.store, action, grant)
            self.trace.append({"gate": decision.reason, "allowed": decision.allowed})
            if not decision.allowed:
                raise PermissionError(decision.reason)
        result, error = runtime.run_function(env, name, args)
        data = to_jsonable_python(result) if error is None else {"error": error}
        if self.expanded and name == "list_files" and isinstance(data, list):
            data = [{**{k:v for k,v in f.items() if k != "content"},
                     "content_chars":len(f.get("content") or "")} for f in data]
        observation = json.dumps(data)
        if self.expanded and len(observation) > 8000:
            observation = observation[:8000] + " [observation truncated]"
        self.trace.append({"tool": name, "arguments": args, "observation": observation})
        if self.store:
            obs_node = self.store.ingest("calendar-result", observation, "tool")
            observation = self.store.content(obs_node)
        answer = complete(f"Answer the {self.domain} question using only the observed data. "
                          "Include the requested details. If unavailable, say so.",
                          prompt + f"\n{self.domain.title()} data:\n" + observation, self.trace,
                          transport=self.transport)
        if self.store:
            answer_node = self.store.derive("answer", answer, (task_node, obs_node))
            answer = self.store.content(answer_node)
            graph = ProvenanceRecorder(self.directory.name)
            graph.record_user_input(prompt)
            for node in (task_node, obs_node, answer_node):
                record = self.store.read(node)
                graph.record_memory("m_" + node, derived_from=["m_" + p for p in record.parents],
                                    ledger_id=node, sha256=record.content_hash)
            graph.record_step("s_lookup", "tool_action", used_ids=["m_" + task_node],
                              next_step_ids=["s_write"], tool=name, arguments=args)
            graph.record_step("s_write", "memory_write", used_ids=["m_" + task_node, "m_" + obs_node],
                              generated_memory_ids=["m_" + answer_node])
            captured = graph.build()
            write_json(captured, self.directory / "graph.json")
            write_svg(captured, self.directory / "graph.svg")
        call = FunctionCall(function=name, args=args)
        messages = [{"role": "user", "content": [block(prompt)]},
                    {"role": "assistant", "content": None, "tool_calls": [call]},
                    {"role": "tool", "content": [block(observation)], "tool_call": call, "tool_call_id": None},
                    {"role": "assistant", "content": [block(answer)], "tool_calls": None}]
        return prompt, runtime, env, messages, {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expanded", action="store_true", help="Run 12 read-only tasks across three Workspace domains")
    parser.add_argument("--deepseek-flash", action="store_true", help="Use the paid official Flash API instead of localhost")
    args = parser.parse_args()
    transport = None
    if args.deepseek_flash:
        import os
        from cua_guard.model import DeepSeekClient, load_env
        load_env()
        transport = DeepSeekClient(os.getenv("MODEL_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
                                   model="deepseek-flash", max_calls=48 if args.expanded else 16,
                                   max_tokens=180)
    root = args.output / str(uuid4())
    root.mkdir(parents=True)
    suite = get_suite("v1", "workspace")
    rows = []
    cases = [(domain, i) for domain, (_, ids) in DOMAINS.items() for i in ids] if args.expanded else [
        ("calendar", i) for i in range(4)]
    for domain, index in cases:
        task = suite.get_user_task_by_id(f"user_task_{index}")
        for arm in ("plain", "ariadne_label_gate"):
            case = root / f"{task.ID}-{arm}"
            case.mkdir()
            start = time.monotonic()
            store = PersistentLabelStore(case / "primary.db", case / "mirror.db") if arm != "plain" else None
            pipeline = CalendarPilot(store, case, domain, args.expanded, transport)
            row = {"task": task.ID, "domain":domain, "arm": arm, "status": "scored", "utility": None}
            try:
                utility, _ = suite.run_task_with_pipeline(pipeline, task, None, {})
                row["utility"] = utility
            except Exception as exc:
                row.update(status="error", error=f"{type(exc).__name__}: {exc}")
            finally:
                if store:
                    store.close()
            row["seconds"] = round(time.monotonic() - start, 3)
            rows.append(row)
            (case / "trace.json").write_text(json.dumps(pipeline.trace, indent=2), encoding="utf-8")
            (root / "scores.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
            print(case, row, flush=True)


if __name__ == "__main__":
    main()
