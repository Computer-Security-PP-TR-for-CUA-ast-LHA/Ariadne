# 溯源图接入端口说明

本文给后续宿主、检测和恢复联调用。  
当前状态：图子系统和恢复投影已就绪；**真实 CUA 自动 hook 尚未接入**。有数据就能建图，没有运行时自动喂数据。

## 1. 总览

```text
CUA / Agent 宿主                     溯源图子系统                      下游消费者
─────────────────                   ──────────────                    ──────────
用户输入 / 步骤 / 记忆读写
        │
        ▼
需要接入的采集口  ───────────────►  ProvenanceRecorder
（尚未自动 hook）                    / build_dependency_graph
                                            │
                                            ▼
                                      DependencyGraph
                                            │
                 ┌──────────────────────────┼──────────────────────────┐
                 ▼                          ▼                          ▼
           查询 / 校验                 JSON / SVG 导出            recovery 投影口
     affected / ancestors              write_json/svg          snapshot_from_provenance
```

| 方向 | 含义 | 现状 |
|---|---|---|
| **需要接入的口** | 宿主必须提供的真实执行记录 | 接口已定义，真实 hook 未接 |
| **可提供的口** | 图子系统对外输出的能力 | 已实现，可被调用 |

---

## 2. 需要接入的口（宿主 → 图）

宿主必须在真实执行点提供结构化 ID，**不要从自然语言猜依赖**。

### 2.1 推荐：增量采集 `ProvenanceRecorder`

```python
from cua_guard.provenance import ProvenanceRecorder, validate_graph

rec = ProvenanceRecorder(task_id="task-1")

# 每一轮用户输入
rec.record_user_input("把偏好改成无预算限制")

# 每一步执行后立刻记录
rec.record_step(
    step_id="s_001",
    step_type="memory_read",          # 见下方 step_type
    next_step_ids=["s_002"],          # 纯步骤后继，只能是 s_*
    used_ids=["m_001", "user_input_1"],
    generated_memory_ids=[],
    invalidated_memory_ids=[],
)

# 每条记忆创建/更新后记录完整现状或变更后的记录
rec.record_memory(
    memory_id="m_002",
    status="active",                  # active / quarantined / deleted / superseded
    derived_from=["m_001"],
    supersedes="m_001",               # 没有替换关系时用 None
)

graph = rec.build(seal=True)          # seal 后不可再 record
validate_graph(graph).raise_for_errors()
```

### 2.2 备选：批量建图

若宿主已有完整日志，可一次提交：

```python
from cua_guard.provenance import build_dependency_graph, validate_graph

graph = build_dependency_graph(task_id, steps, memories, session)
validate_graph(graph).raise_for_errors()
```

`session` 是按轮次排列的用户输入文本列表；第 `i` 条对应节点 `user_input_i`。

### 2.3 字段契约

#### Step 记录（必填语义）

| 字段 | 类型 | 要求 | 建出的边 |
|---|---|---|---|
| `step_id` | `str` | 必须以 `s_` 开头，全局唯一 | 节点 |
| `step_type` | `str` | 见下表 | 决定 produce/消费边 |
| `next_step_ids` | `list[str]` | 只能是 `s_*`，无重复 | `chain` |
| `used_ids` | `list[str]` | 真实依赖；`m_*` / `s_*` / `user_input_*` | `support` 或 `cite` |
| `generated_memory_ids` | `list[str]` | 本步新写出的 `m_*` | `produce` |
| `invalidated_memory_ids` | `list[str]` | 本步废掉/合并掉的 `m_*` | `delete` / `update` / `consolidate` |

`step_type` 与边的关系：

| `step_type` | 相关字段 | 边 |
|---|---|---|
| `memory_read` | 通常填 `used_ids` | 读到的记忆 → `support`；同时用于划分 turn |
| `memory_write` | `generated_memory_ids` | `produce` |
| `memory_update` | `generated_memory_ids` + `invalidated_memory_ids` | `produce` + `update` |
| `memory_delete` | `invalidated_memory_ids` | `delete` |
| `memory_consolidate` | 两者都可能有 | `produce` + `consolidate` |
| `claim` / `plan` / `tool_action` / `tool_observation` / `final_answer` 等 | 主要靠 `used_ids` | `cite` / `support` |

规则：

1. `used_ids` 里 `m_*` → `support`；其它 ID → `cite`。
2. 仅有先后、没有引用时只写 `next_step_ids`，不要伪造 `used_ids`。
3. 每遇到一次 `memory_read`，builder 会开启新 turn；该 turn 的首个 step 会自动接到 `user_input_{turn}` 的 `initiate` 边。
4. 缺端点不会静默补边：记入 `missing_refs`，`coverage="partial"`，安全投影会拒绝。

#### Memory 记录

| 字段 | 类型 | 要求 | 建出的边 |
|---|---|---|---|
| `memory_id` | `str` | 必须以 `m_` 开头，全局唯一 | 节点 |
| `status` | `str` | 建议 `active/quarantined/deleted/superseded` | 元数据 |
| `derived_from` | `list[str]` | 祖先记忆 ID，只能是 `m_*` | `derive` |
| `supersedes` | `str \| None` | 被替代的旧记忆 ID | `supersede` |

#### Session 记录

| 字段 | 类型 | 要求 |
|---|---|---|
| `session[i]` | `str` | 第 `i+1` 轮用户原文；节点 ID 固定为 `user_input_{i+1}` |

### 2.4 宿主 hook 应挂在哪里

后续接真实 CUA 时，建议在这些时刻调用 recorder：

| 执行点 | 调用 |
|---|---|
| 收到用户消息 | `record_user_input(text)` |
| 完成一步推理/工具/读写 | `record_step(...)`，立刻填真实 `used_ids` 等 |
| 创建或更新一条记忆 | `record_memory(...)` |
| 任务结束或触发检测/恢复前 | `build()` → `validate_graph()` |

不要做的事：

- 不要解析模型自然语言来补 `used_ids`
- 不要把“可能相关”的记忆塞进依赖
- 不要在图不完整时继续做安全投影或隔离决策

---

## 3. 可提供的口（图 → 下游）

### 3.1 查询口（检测 / 审计 / 修复规划）

```python
from cua_guard.provenance import (
    affected_node_ids, affected_report, affected_subgraph,
    ancestors, descendants, find_producing_step,
    topological_order, writers_for_versions, validate_graph,
)

validate_graph(graph).raise_for_errors()

# 污染根 → 受影响闭包（排除纯 chain）
affected = affected_node_ids(graph, "m_polluted", "m_other")
report = affected_report(graph, "m_polluted")
sub = affected_subgraph(graph, "m_polluted")

# 反向：这条记忆/步骤依赖谁
upstream = ancestors(graph, ("m_summary",))

# 谁写出了该记忆
writer = find_producing_step(graph, "m_summary")
writers = writers_for_versions(graph, ["m_a", "m_b"])

# 修复顺序
order = topological_order(graph, affected)
```

| API | 输出 | 典型用途 |
|---|---|---|
| `affected_node_ids` | 受影响节点 ID 元组 | 检测后定位污染扩散范围 |
| `affected_report` | 分组统计 dict | 日志、告警、评估 |
| `affected_subgraph` | 诱导子图 | 只看污染相关局部 |
| `ancestors` / `descendants` | 节点 ID 元组 | 审计、解释、对比 |
| `find_producing_step` | writer step ID 或 `None` | 找写入点 |
| `topological_order` | 有序节点 ID | 规划修复顺序 |
| `validate_graph` | `ValidationReport` | 安全决策前闸门 |

### 3.2 导出口（落盘 / 可视化）

```python
from cua_guard.provenance import write_json, read_json, write_svg

write_json(graph, "dependency-graph.json")
graph2 = read_json("dependency-graph.json")
write_svg(graph, "dependency-graph.svg", roots={"m_polluted"}, affected=set(affected))
```

| API | 输出 | 说明 |
|---|---|---|
| `write_json` / `read_json` | `ariadne.provenance/1.0` JSON | 完整图持久化；schema 见同目录 |
| `write_svg` / `to_svg` | 独立 SVG | 调试和报告；无第三方绘图依赖 |

完整图当前**不写 SQLite**。需要长期保存完整图时，先用 JSON；恢复侧数据库只存投影后的版本账本。

### 3.3 恢复投影口（图 → recovery）

```python
from cua_guard.recovery.adapters import snapshot_from_provenance
from cua_guard.recovery.contracts import Version

versions = (
    Version("m_001", content="...", parents=(), status="active"),
    Version("m_002", content="...", parents=("m_001",), status="active"),
)
snapshot = snapshot_from_provenance(
    scope_id="scope-1",
    revision=1,
    versions=versions,
    graph=graph,
)
# 随后可交给 VersionGraph / RecoveryCoordinator / SQLiteRecoveryStore
```

投影规则：

1. 只投影 `memory` 节点；`step` / `user_input` 不进恢复账本。
2. `derive` → `derived_from`；`supersede` → `supersedes`。
3. 要求图完整且校验通过。
4. `versions` 的 ID 集合必须与图中 memory 节点完全一致。
5. 若 `Version.parents` 已填，必须与 `derive` 边一致。

恢复侧兼容查询：

```python
from cua_guard.recovery import DGRRReachability
# VersionGraph / RecoveryCoordinator 默认已使用本地 DGRRReachability
# 内部受影响闭包已桥接到 provenance 查询语义
```

---

## 4. 推荐接入顺序

1. **宿主侧**：在 CUA 读写点挂 `ProvenanceRecorder`，保证 `used_ids` 等字段真实。
2. **建图校验**：`build()` → `validate_graph().raise_for_errors()`。
3. **检测侧**：告警给出污染根后，调 `affected_node_ids` / `affected_report`。
4. **恢复侧**：需要进现有修复链时，调 `snapshot_from_provenance`，再走 `recovery`。
5. **审计侧**：需要留证时 `write_json`；需要人工查看时 `write_svg`。

最小联调示例：

```python
from cua_guard.provenance import ProvenanceRecorder, affected_node_ids, validate_graph
from cua_guard.recovery.adapters import snapshot_from_provenance

rec = ProvenanceRecorder("demo-task")
# ... 宿主在执行点 record_* ...
graph = rec.build()
validate_graph(graph).raise_for_errors()

roots = ["m_polluted"]  # 来自检测模块
affected = affected_node_ids(graph, *roots)

# 若要进入恢复：准备与 memory 节点对齐的 Version，再投影
# snapshot = snapshot_from_provenance(scope, revision, versions, graph)
```

---

## 5. 错误与失败语义

| 情况 | 行为 | 接入方应怎么做 |
|---|---|---|
| recorder 已 `seal` 仍写入 | `ProvenanceError: recorder_sealed` | 新建 recorder 或勿 seal |
| ID 格式/重复/字段类型错误 | 建图阶段 `ProvenanceError` | 修正宿主记录 |
| 引用了不存在的节点 | `coverage=partial`，`missing_refs` 非空 | 补齐记录；不要投影 |
| 校验失败 | `ValidationReport.valid is False` | `raise_for_errors()` 后停止安全路径 |
| 投影时 memory 与 Version 不一致 | `RecoveryError: provenance_version_mismatch` | 对齐两边 ID 集合 |
| 投影时 parents 与 derive 冲突 | `RecoveryError: provenance_parent_mismatch` | 以图为准修正 Version.parents |

原则：**不完整图可以导出排查，但不能作为隔离/修复依据。**

---

## 6. 尚未提供、后续不要误用的口

当前**没有**这些端口，接入时不要假设已存在：

- 自动从 LLM 文本推断依赖的解析器
- 完整图的 SQLite/图数据库表
- 论文中的 fault provenance / support checker / rollback optimizer / selective replay
- 某个具体桌面 ChatGPT / benchmark runner 的现成 hook

相关样例与契约：

- 使用说明：`docs/provenance/README.md`
- JSON schema：`docs/provenance/provenance-graph-v1.schema.json`
- 十类边样例：`docs/provenance/fixtures/complete-ten-edge.json`
- 方法边界：`docs/research/08_溯源图文献与复用.md`
