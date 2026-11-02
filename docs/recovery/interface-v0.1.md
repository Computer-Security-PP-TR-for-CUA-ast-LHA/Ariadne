# 恢复模块与溯源图接口 v0.1

日期：2026-11-02。状态：**供队友评审的协议提案，未声称已获成员 2/3 同意或已实现**。实现负责人 `luowentao`；图数据库、导出样式不在本协议内。接口示例是设计伪代码，不可当成当前可导入 API。

## 1. 所有权与边界

| 角色 | 拥有并验证的状态 | 对恢复模块提供 |
|---|---|---|
| 成员 1：宿主 / benchmark | 真实观测、动作执行、环境快照、效果与评分 | 暂停、效果核对、受管理上下文替换、重规划、可重放 writer |
| 成员 2：标签 / gate | 不可变内容版本、来源/授权、状态、批准参数绑定 | 内容读取、隔离、候选版本、活动版本原子发布、重新授权 |
| 成员 3：图 | 宿主采集的依赖、writer 输入输出、revision、缺口 | 固定快照查询、全域后代、拓扑顺序、审计关联与迟到事件 |
| luowentao：恢复 | 计划、修复尝试、验证证据、旧新映射、恢复状态机 | 编排后端并请求写入；不自行授予权限，不直接执行业务工具 |

图是权威事件/版本记录的投影，而不是第二套独立权限数据库。若分库存储，必须提供 revision 水位和提交屏障；不能由恢复模块任意写两边后假定一致。第一版推荐同一宿主串行写入并冻结恢复期间的新写入，后续才扩展并发方案。

## 2. 身份、内容与版本

- `schema_version = "ariadne.recovery/0.1"`；不支持的主版本应返回 `unsupported_schema`，不能静默删字段。
- `scope_id`：可信宿主分配的受管理状态空间。跨会话共享记忆属于同一 scope；不能把单次 task/session 当全域。
- `artifact_id` 标识逻辑资料；`version_id` 标识不可覆盖内容版本。ID 视作 opaque string，不能通过前缀推断信任或对象类型。
- `content_sha256`：小写 SHA-256，计算对象为存储的原始 UTF-8 文本字节，不隐式归一化 Unicode/换行。非文本内容在另一个显式编码协议中声明。
- `source_refs` 与 `authority_refs` 分离。净化不能把 external 升为 user，也不能生成 authority。
- 内容不可变，状态可变且受 revision 约束：`staged / active / quarantined / superseded`。历史内容留审计，只有 active 能进模型可见检索结果。
- `semantic_verdict` 与状态分离：`clean / polluted / unknown`；active 不是“永久语义安全证明”。候选版本必须经过约定验证才可发布。
- 根节点本身也需隔离。后代查询统一返回含根集合（`include_roots=true`）；不同上游返回不含根时由 adapter 补齐。

## 3. 节点、边与 writer 事件

| 节点 | 必要信息 |
|---|---|
| `ArtifactVersion` | scope、artifact/version ID、hash、content_ref、source_refs、authority_refs、status、created_revision、channel |
| `WriterEvent` | event ID、session、实际输入版本、输出版本、writer kind/version、模板 hash、模型配置引用、逻辑顺序、重放类型、输入覆盖 |
| `ActionRecord` | call ID、task/session、完整参数摘要、依据版本及其 hash、proposal/execution 状态、effect_ref |

`WriterEvent.replay_class` 由宿主实现注册，不从恶意资料或模型自由文本取得：

- `pure_state_write`：只产生候选记忆，不产生外部业务副作用。
- `captured_read`：可以使用已捕获且重新验证的返回值；若重新读取环境，会创建新的观测版本，不能假装是同一次读取。
- `external_effect`：不得由恢复模块自动重放。
- `unsupported`：暂停并记录缺口。

边方向统一为**输入/旧记录 → 消费者/新记录**，每对端点可有多个关系。查询必须显式指定边集，不能把所有边混合遍历。

| 边类型 | 方向 / 用途 | 默认影响传播 |
|---|---|---|
| `input` | 版本 → writer event | 是 |
| `output` | writer event → 输出版本 | 是 |
| `derived_from` | 版本 → 派生版本；可由 input/output 投影得到 | 是 |
| `uses` | 版本 → action | 是；只确定检查范围，不自动重放动作 |
| `sequence` | 事件 → 后续事件 | 否，仅时间顺序 |
| `supports` | 独立证据 → claim/版本 | 单独查询；不能凭此自动洗白受影响内容 |
| `supersedes` | 旧版本 → 新版本 | 审计/迟到告警查询；不作为普通活动污染传播边 |
| `sanitized_from` | 被净化旧版本 → 验证后的候选新版本 | 同上；携带修复与验证证据 ID |

摘要、复制、工具返回、缓存物化、跨会话检索必须保留实际输入关系。遍历可经过临时 event/tool-result，不能仅在持久节点间搜索。图形导出须保留边类型，不得将纯 sequence 绘成“恶意因果”。

## 4. 只读图接口

```python
open_snapshot(scope_id) -> GraphSnapshot
get_versions(snapshot, version_ids) -> list[ArtifactVersion]
get_call(snapshot, call_id) -> ActionRecord
ancestors_of_call(snapshot, call_id, edge_types) -> QueryResult
descendants(snapshot, roots, edge_types, include_roots=True) -> QueryResult
writers_for_versions(snapshot, version_ids) -> list[WriterEvent]
topological_writers(snapshot, event_ids) -> list[WriterEvent]
audit_successors(snapshot, old_version_ids) -> QueryResult
```

`GraphSnapshot` 至少包含：`scope_id`、`graph_revision`、`ledger_revision`、`captured_through_event_seq`、`snapshot_id`、覆盖声明。revision 必须能指向一致的账本和图投影；纯导出时间字符串不是快照一致性保证。

`QueryResult` 至少包含：`version_ids`、`event_ids`、`action_ids`、所用 `edge_types`、路径/边证据、`coverage`、`missing_refs`、`truncated`、结果水位。

- `coverage = complete_within_scope / partial / unknown`。complete 只覆盖宿主声明的范围；不是全电脑保证。
- `missing_refs` 非空、查询截断或跨 scope 引用不得返回“空闭包 = 安全”。第一版不自动恢复。
- `not_found`、`scope_mismatch`、`snapshot_expired`、`cycle_detected`、`unsupported_capability` 使用不同错误码。
- 如做分页，所有页固定同一 snapshot，最终聚合后方可制定计划。预算耗尽返回 incomplete，禁止将前 N 个后代当完整闭包。
- 图内允许审计关联形成复杂历史，但 writer 的活动数据依赖必须可拓扑排序；发现循环不能随意按 ID 排序重放。

## 5. 告警与计划

`RecoveryRequest`：`request_id`、`scope_id`、`task_id`、`session_id`、`call_id`（可空）、`reason_code`、证据引用、检测器/locator 版本、候选根、checkpoint 引用、effect 水位、允许修复预算。

`reason_code` 分为 `pollution_confirmed / suspected_pollution / missing_authority / integrity_mismatch / unknown`。权限不足可以走获取有效授权或暂停路径，不自动净化资料。检测 unknown 不等于 confirmed。

调用关联定位：从 call 的真实 bindings 反查祖先，验证确认根在所查范围内；对独立的迟到告警允许 `call_id=null`，但必须有同一 scope 的宿主证据。两种入口不能通过传入任意 version ID 相互绕过。

`RepairPlan`：`plan_id`、request ID、scope、expected revision、证据支持的根、候选影响集合、隔离集合、保留集合及理由、writer 顺序、后端与版本、替代策略、所需宿主能力、未解决项、状态。

三种集合必须区分：

1. `candidate_affected`：结构上可达，待检查范围。
2. `quarantine_set`：为恢复期间保守隔离的旧版本；不声称每个都是语义恶意。
3. `confirmed_polluted`：有相应定位证据支持的版本。

先隔离全域候选持久副本，再选择只重建当前任务需要的部分是允许的；**未重建的旧副本继续隔离**。不能因“不影响本次最终答案”就让其保持可检索。混合内容须恢复正常事实；只删除整条记忆不能计作事实保留。

## 6. 写入与发布协议

由成员 2 暴露事务服务，图方订阅同一个提交记录。建议接口：

```python
begin_repair(request_id, plan_id, expected_revision) -> RepairTransaction
quarantine_versions(tx, version_ids, evidence_refs) -> QuarantineReceipt
stage_replacement(tx, old_version_ids, candidate, input_versions) -> StagedVersion
record_validation(tx, candidate_id, report) -> None
commit_repair(tx, expected_revision, view_manifest) -> CommitReceipt
abort_repair(tx, reason) -> None
```

第一版单写者过程：暂停 scope 的受影响执行/写入 → 读取一致快照 → 制定计划 → 原子记录隔离与 pending repair（revision 前进）→ 基于隔离后水位暂存修复输出 → 验证 → 原子切换新版本、图关系、活动视图与恢复记录。外部检索索引以 outbox/ack 或同步重建方式追平提交水位，未 ack 前不得恢复规划。长时间模型调用期间不持有数据库写锁。

若模型调用期间允许其他写入，提交使用隔离后的 expected revision 做 CAS；发现变化即重新查闭包/验证，不能使用原始旧 revision 假装未变。不同事务对同一旧版本的竞争必须返回冲突。

`replacement_map` 是 `old_version_id -> list[new_version_id]`，支持一对多/无输出；无输出必须给出 `discarded` 理由、正常事实损失与任务影响，不能当完整重建。新版本反向记录所有旧版本和实际新输入，避免 merge 后丢失来源。纯净化读取旧文本也应保留 `sanitized_from` 证据，不能只切断旧边后隐藏输入历史。

原版本始终隔离或 superseded，不能通过“清除污点标记”重新激活。新版本保持来源约束；净化验证不是新的动作授权。

崩溃处理：同 `request_id` 重试返回既有事务；隔离后崩溃仍暂停；staged 输出不进入检索；提交成功但 checkpoint 未切换时，通过 commit receipt 重建视图，不重复发布。中止保持隔离，不能一概回滚为 active。故障恢复不得重复执行业务工具。

## 7. 验证与恢复结果

`ValidationReport`：validator ID/version、输入输出 hash、恶意指导残留、任务相关事实保留、无编造、依赖与来源一致性、未解决证据、原始后端返回引用。模型复检可能共错，不能标为安全证明。

`RecoveryResult` 至少包含：

```text
request_id / plan_id / scope_id / committed_revision
status: ready_to_replan | needs_review | unsupported | failed
roots / quarantined / preserved / replacements
unresolved[]: {code, version_ids, evidence_refs, required_capability}
retrieval_manifest / context_manifest / checkpoint_id
effect_ledger_watermark / backend_versions / validation_refs
```

`ready_to_replan` 仅表示可以重新规划，不表示工具已经获准，也不表示合法任务已经完成。

恢复检查三层：

1. 内容/版本：旧污染副本已隔离，替代版本复检通过，来源没有升级。
2. 检索/上下文：读实际索引与模型输入，排除旧工具历史、旧缓存与旧摘要；重开进程后仍成立。
3. 任务/效果：新动作走 gate，最终状态由程序/环境评分；后续再次触发攻击条件测复发。

## 8. checkpoint 与外部效果

checkpoint 保存可信 task 引用、活动版本列表及 hash、context/view revision、blocked 状态、repair receipt、效果账本水位。恢复时对照当前账本，禁止只读取旧的 `blocked=false`。若旧 checkpoint 引用已隔离版本，应解析有效替换记录或保持暂停。

effect 账本不随记忆回滚：至少有 `not_started / in_flight / committed / failed_no_effect / unknown`。`in_flight/unknown` 要先与执行端核对；新 call ID 不能绕过语义操作的去重约束。幂等键须来自宿主业务操作身份，不由模型随机生成。此接口不承诺对任意远端服务实现 exactly-once。

恢复模块仅发出 `replan(context_manifest)`，由宿主提出新动作并交回成员 2 gate，绑定新参数和当前版本。原执行结果或一次性授权不能因为 rollback 重新变成可用。

## 9. 迟到告警与图缺边

新的告警可能指向已经被净化替换的旧版本。通过 `audit_successors` 找到候选替代版本及其后代，检查原修复是否覆盖了新证据；必要时再次隔离与复检。审计关联只触发重新审查，不能自动把所有新版本永久标成污染，也不能一律忽略它们。

迟到输入边或新的捕获缺口使旧计划 coverage 不再有效：失效旧 `ready_to_replan` receipt，暂停依赖该视图的运行，增量重查范围。状态由可信宿主更新，不由模型维护“已修复”字符串。

## 10. 与两个优先上游的适配约定

| Ariadne | SRR | memory-rollback |
|---|---|---|
| version ID | ObjectRecord.object_id | 映射为 m_*；双向映射必须无碰撞 |
| writer 输入输出 | EventRecord.input/output_object_ids | step used_ids / produced memory 与真实宿主采集交叉核对 |
| 根与后代闭包 | 原函数输出仅持久后代，额外加根 | 原函数不含根且会跳过坏 ID；调用前校验并补根 |
| 时间顺序 | SESSION_ORDER 特定顺序 | chain，不当影响传播 |
| 审计替换 | replay_of / replacement_map | supersede 在上游默认可达图中；Ariadne 必须分离查询语义 |
| 支持判定 | 不提供通用独立支持检验 | 无支持默认 True；映射为 unknown，不能自动释放 |
| 重放安全 | 本地 writer / coarse rollback | ReplayBackend 与环境耦合 |

先提供 `can_adapt(snapshot) -> supported/missing_capabilities`。无法表达事件、版本、作用域、coverage 时返回 unsupported，不强行补造关系。sidecar 输出包含原始结果与 commit；适配规则版本独立于上游版本。

## 11. 交接验收清单

使用 [最小夹具](fixtures/minimal-recovery.json)，验证下面的语义，不以函数名称相同为合格：

| 用例 | 预期 |
|---|---|
| 根 P → writer → N → C，C 被动作 A 使用 | 闭包含 P/N/C/A 和中间事件；持久隔离集合含 P/N/C |
| P 另有未进入 A 的跨会话副本 C2 | C2 也隔离，不能只查 A 的祖先子图 |
| 独立正常资料 Q → B，时间在污染之后 | Q/B 保留；sequence 不扩大污染集合 |
| 根缺失、缺边、截断或 scope 不匹配 | 明确未解决；不能空集合成功 |
| 新旧版本及多个根汇合 | 集合去重，映射保留全部来源；只按版本身份处理 |
| 重放需要旧污染摘要且无替代输入 | 返回 unsupported/needs_review 或受控回退，不静默丢输入 |
| 净化失败、模型超时、事实丢失 | 保持隔离与暂停，staged 版本不可检索 |
| 同 request 重试、提交时 revision 变化、崩溃重启 | 幂等返回、冲突重计划、无部分可见发布 |
| 迟到告警命中旧 superseded 版本 | 能沿审计边发现候选新版本并重新验证 |
| 已执行/效果未知动作 | 不自动重放，不恢复已消耗权限 |

成员 2/3 需要评审的关键项：版本 ID 与 hash 规范、writer 采集粒度、类型化边、scope 覆盖声明、图/账本 revision 的原子性、隔离后新写入规则、旧新多值映射、迟到告警通知。确认前可以据此开发内存适配器，但不得在文档中标注“团队接口已定版”。
