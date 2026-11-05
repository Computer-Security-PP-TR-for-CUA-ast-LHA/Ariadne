# 完整溯源图子系统

代码位于 `src/cua_guard/provenance/`。它参考论文 *From Faulty Memories to Corrected Actions* 的依赖图方法独立实现，不复制作者源码，也不包含净化、回滚优化或重放策略。

## 数据模型

节点分为：

- `user_input`：每轮可信用户输入；
- `step`：claim、plan、tool action、memory write 等执行步骤；
- `memory`：持久记忆或其他需要追踪的版本对象。

边有十类：

| 边 | 方向 | 含义 |
|---|---|---|
| `chain` | step → step | 执行顺序，不单独传播污染 |
| `cite` | step/user_input → step | 后一步明确引用前一步或用户输入 |
| `support` | memory → step | 步骤使用该记忆 |
| `produce` | step → memory | writer 产生记忆 |
| `delete/update/consolidate` | memory → step | 记忆被对应操作消费 |
| `initiate` | user_input → step | 用户输入启动该轮首个步骤 |
| `derive` | memory → memory | 派生来源 |
| `supersede` | old memory → new memory | 新版本替代旧版本 |

同一节点对可以同时携带多个标签，例如 `chain + cite`。

## 建图和查询

```python
from cua_guard.provenance import (
    affected_node_ids, build_dependency_graph, validate_graph,
)

graph = build_dependency_graph(task_id, steps, memories, session)
validate_graph(graph).raise_for_errors()
affected = affected_node_ids(graph, "m_polluted")
```

`steps` 必须由宿主提供真实的 `used_ids`、`generated_memory_ids`、`invalidated_memory_ids` 和 `next_step_ids`。系统不会从自然语言猜测依赖。缺失端点会记录到 `missing_refs`，图变为 `partial`，安全相关投影会拒绝继续。

`affected_node_ids` 会沿证据、引用、产生和来源边传播，但排除纯 `chain` 边，避免仅因执行先后关系扩大污染范围；如果同一边同时有 `chain` 和 `cite`，仍会沿 `cite` 传播。

## 导出

```python
from cua_guard.provenance import write_json, write_svg

write_json(graph, "dependency-graph.json")
write_svg(graph, "dependency-graph.svg", roots={"m_polluted"})
```

JSON 契约见 `provenance-graph-v1.schema.json`，十类边样例见 `fixtures/complete-ten-edge.json`。SVG 使用确定性三列布局，不需要 NetworkX 或 Matplotlib。

## 接入恢复模块

`recovery.adapters.snapshot_from_provenance()` 将完整图中的 memory 节点及 `derive/supersede` 关系投影为现有 `ariadne.recovery/0.2` Snapshot。step 和 user_input 不会写入版本账本，现有恢复接口和数据库 schema 无需迁移。

投影要求：

1. 图覆盖状态完整且通过结构校验；
2. memory 节点与提供的 `Version` 集合完全一致；
3. 已有 `Version.parents` 与 `derive` 边一致；
4. 投影结果继续通过 `VersionGraph` 校验。

## 后续接入端口

宿主需要提供什么字段、图子系统能对外提供哪些查询/导出/恢复投影口，见 [integration-ports.md](integration-ports.md)。联调时优先按该文档的“需要接入的口 / 可提供的口”对接。

## 尚未包含

- 真实 CUA 宿主对每一步的自动 hook；当前提供 `ProvenanceRecorder` 接口，由宿主在实际执行点调用；
- 论文的 fault provenance、stale-window、support checker、rollback optimizer；
- 真实 benchmark 的准确率、召回率和性能结果。
