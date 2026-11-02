# 定向修复实现与团队交接 v0.2

> 历史实现说明：通用编排、默认 writer 后端及安装方式已由 [复用替换审查与当前运行说明](reuse-audit.md) 更新。本文的图/标签/授权语义仍适用；“仅标准库”和 WriterRegistryBackend 不再代表当前生产代码。

日期：2026-11-02。代码：`src/cua_guard/recovery/`；工作分支：`luowentao`。
这是已实现、可独立执行的恢复组件与参考宿主，供三方对接评审；不是团队已批准的最终协议，也不是已完成真实 CUA 防护验收的产品。

## 1. 如何运行

Python 3.11+，核心仅用标准库。仓库根目录运行：

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m cua_guard.demo
python -m cua_guard.recovery.demo --output runs/recovery-offline.json
```

Linux/macOS 对应设置 `export PYTHONPATH=src`。最后一个入口完成：导入污染图 → 结构化告警 → 隔离 → 拓扑重建 → 复检 → 发布 → 重开数据库 → 重建上下文 → 独立授权 → 模拟工具续行。demo 的根定位、净化和评分都是明确的合成夹具；没有模型或真实工具调用。`fixture_task_success` 不能混入 benchmark ASR。

可选的**真实上游代码**检查（checkout 不放入本仓库）：

```powershell
$env:ARIADNE_TMA_CHECKOUT = '<mem-inv-bench 固定版本目录>'
$env:ARIADNE_SRR_CHECKOUT = '<selective-revocation-replay 固定版本目录>'
python -m unittest discover -s tests -p test_recovery_upstream.py -v
```

TMA 固定 commit `cf3c9a4ca9f0478000d6aa26eb268b875232d34b`，无额外运行依赖；逐文件校验源码和许可证 SHA-256，允许 Git 的 CRLF/LF 工作树差异。
SRR 固定 commit `d7bcb32740156cb985fae0ee93caba35ee45e67e`，需要其原始环境依赖（本轮使用已有 PyYAML 环境）；adapter 可指定该环境 Python。严格拒绝版本变化及 `src` 已修改/未跟踪文件。两个 worker 均使用 `-I`、参数列表和超时，不使用 shell，不下载代码，不自动安装依赖。它们是进程隔离，**不是恶意 Python 代码的安全沙箱**，checkout 是可信部署配置。

## 2. 实际模块和责任

| 文件 | 已实现内容 | 交接方 |
|---|---|---|
| `contracts.py` | 不可变版本、图快照、恢复请求、验证结果、各类 Protocol | 全组 |
| `graph.py` | 类型化闭包、调用祖先约束、拓扑顺序、覆盖/缺边/环/hash/来源检查 | 成员 3 |
| `adapters.py` | JSON 图桥接、writer-event 投影、纯 writer 注册、检索/上下文重建、双标签回写协调 | 成员 2/3 与宿主 |
| `coordinator.py` | 屏障、隔离、暂存、验证、发布、回写确认、崩溃续作 | luowentao |
| `sqlite.py` | 事务参考账本、scope 单写者、版本/会话/恢复日志、调用与副作用记录 | 可替换存储适配层 |
| `semantic.py` | 接现有 `client.json()` 的内容修复与“安全+保真+再检测”验证 | 模型后端配置方 |
| `tma.py` / `_tma_worker.py` | 直接运行原始 `authorized_parameters()` 和 `ScopedGate` | 独立授权参数来源 |
| `srr.py` / `_srr_worker.py` | 直接运行原始 SRR 闭包和 replay planner，返回原生候选计划 | 原方法对照 |
| `execution.py` | 新动作、精确授权、一次性 grant、授权 epoch、持久 effect claim | 成员 1/2 的工具宿主 |
| `demo.py` | 可运行的离线恢复及续行验收场景 | 全组 |

原 `store.py` / `runtime.py` 仍是原型/对照。新模块没有暗中替换已有运行器，也没有把其无事务屏障的读写路径伪装成已接入。集成时必须把宿主读写、检索和 dispatch 都接入新端口，禁止一边使用新恢复器、一边继续通过旧接口读取污染版本。

## 3. 与成员 3 对齐的图协议

当前可运行 schema 是 **`ariadne.recovery/0.2`**，见 [JSON Schema](snapshot-v0.2.schema.json) 与 [可执行夹具](fixtures/recovery-v0.2.json)。v0.1 是较宽的设计提案，不可静默当成 v0.2 输入。

`scope_id` 表示共享状态空间，不是当前轮对话。当前会话和未来可能检索到的派生副本必须在同一完整快照内；如果系统跨 scope 共享记忆，生产 adapter 必须扩大 scope 或建立跨域协调，不能声称单 scope 查询覆盖全部。

```python
snapshot(scope_id) -> Snapshot
# Snapshot: schema_version, scope_id, revision, versions, edges,
#           coverage='complete_within_scope', missing_refs=()
# Version: version_id, artifact_id, content, content_sha256,
#          origins, parents, status, writer_key?, session_id
# Edge: source, target, kind
```

约定：

1. 边方向为输入/旧版本 → 派生/新版本。版本内容不可覆盖；`content_sha256` 对实际 UTF-8 字节计算，不归一化 Unicode 或换行。
2. `parents` 与 `derived_from` 边必须逐项一致。未知根、缺端点、环、重复节点、缺失来源、来源降级都拒绝。修复不能将 external 变为 user。
3. `derived_from` 参与普通闭包；`sequence` 只是时序；`supports` 只存证据关系，不自动授予信任或裁掉后代。`sanitized_from` / `supersedes` 用于迟到告警保守扩展。
4. 若原图是 Version → WriterEvent → Version，使用 `snapshot_from_events()`；临时工具观察也要成为 Version，不能跳过中转节点。事件的输入/输出及 writer 注册由宿主给出，不能从文档自述来源推断。
5. `coverage` 和 `missing_refs` 是采集方的完整性声明。能检查结构一致性，不能检测“某次真实读取从未被记录”的隐形缺边；这必须由采集覆盖测试验证。
6. 图导出需要一致性读事务。其 scope/revision、节点及类型化边必须与写入账本完全一致；不同则 `graph_ledger_mismatch`，保持屏障。版本号不能来自本地时钟估计。
7. `call_id` 绑定宿主捕获的实际输入版本。传入告警根若不在该调用祖先中则拒绝；事后全域告警可省略 call_id，但仍需可信诊断证据。

```python
graph = JSONGraphAdapter(lambda scope: member3.export_snapshot(scope))
coordinator = RecoveryCoordinator(store, backend, validator, projection, graph=graph)
```

v0.2 将内容内联，方便先联调；二进制/图像、内容引用服务及大规模分片图需明确升级协议。本实现限制单节点 100,000 字符、默认 10,000 节点、边数不超过节点预算的 32 倍、全图内容 16,000,000 字符，不截断图后继续执行。

## 4. 与成员 2 对齐的告警、标签和授权

恢复请求：`RecoveryRequest(request_id, scope_id, task, roots, evidence_refs, reason, call_id)`。`task` 是宿主确定的用户意图，`evidence_refs` 指向宿主审计记录。当前只接受 `pollution_confirmed` 进入内容修复；缺权限、未知诊断、完整性冲突不能被当作已确认污染。根定位可由成员 2 或独立诊断后端给出，本组件不声称从拒绝动作自动证明恶意因果。

标签输出使用 `DualLabelProjection(primary, independent, context, configuration_id=...)`。两个 replica 都实现：

```python
replace_scope(manifest) -> None  # 幂等，拒绝旧 revision，保留 withdrawn 墓碑
digest(scope_id) -> str         # 实际落库后读回当前安装的完整 manifest 摘要
```

manifest 包含 `scope_id / revision / versions(active) / withdrawn / sessions / digest`；摘要为移除 digest 字段后 canonical JSON 的 SHA-256。`withdrawn` 明确告知旧版本失效。两份都写入并读回匹配后才安装上下文、释放屏障；部分写入可用同一 request 重试。这是**带屏障的幂等回写流程**，不是跨数据库原子事务。如果旧宿主绕过屏障读取副本，则这一保证不成立。两份的独立故障/信任边界由成员 2 实现；不同对象实例本身不证明独立性。

本文中的 `origins` 只表示来源，不把 Fides 权限集合、TMA domain 佐证等语义压缩成 `trusted=True`。完整权限仍由成员 2 的 authorizer 决定。

授权通过可信宿主回调返回 `AuthorizationGrant(grant_id, proposal_hash, epoch, expires_at)`，禁止将模型 JSON 直接转换为 grant。`proposal_hash` 覆盖 scope/session/业务 operation ID/revision/版本 hash/tool/完整参数；grant 在 effect claim 同一事务中一次性消耗。撤销策略时宿主调用 `revoke_authorizations(scope)` 增长 epoch，恢复不会回滚 epoch 或已消耗 grant。远端权限变化必须同步到这一撤销钩子。

TMA `recover_parameters()` 只生成参数提案。过期、撤销、非独立 domain、歧义候选均不能输出 available。即使 available，也要重新构造 Proposal，经过成员 2 在提交时的完整授权检查。

## 5. 恢复状态机与存储端口

`reserved → quarantined → published → ready`。任何失败返回 `outcome=needs_review`，保留 durable phase 和屏障；用完全相同 request/config 显式重试。无后台无限重试。request ID 相同但 task/root/backend/prompt/registry 配置变化会拒绝，避免复用旧验证。若需要改诊断或修复策略，应由宿主评审新的事件迁移方案，不能直接清除 owner 或绕过隔离。

- `reserve`：原子创建 job 并冻结 scope；不同请求返回 busy；同请求受 OS 单写者锁约束。锁跨进程，进程死亡由 OS 释放。数据库长期 owner 保留，重启不会意外解冻。
- `quarantine`：所有目标一次事务隔离并提高 revision。此后才调用修复后端。
- `stage`：纯 writer 按拓扑使用已验证前驱和未受影响输入；根或无配方节点调用修复后端。未知 writer 不静默执行。支持一旧版本 → 1–16 个新版本；默认不接受零输出，避免把数据丢失伪装成修复。
- `publish`：仅当全部目标验证完成，一次 SQLite 事务发布所有新版本、旧新审计边、所有会话引用及新 revision；故障会整体回滚。这里采用全有或全无的保守策略，没有实现 MemoRepair 的 min-cut 成本优化。
- `acknowledge`：manifest 一致且双标签/上下文确认、没有未知 effect 后释放屏障。发布成功但宿主回写失败时，数据库中的新版本也不能通过正常上下文读接口访问。

`RecoveryStorePort` 的方法签名在 contracts.py。持久 job 的 JSON 字段：`scope_id, request_id, request, configuration, fingerprint, revision, state, plan, staged, error`；后续增加 `mapping, manifest_digest`。plan 含 `roots/affected/targets(拓扑顺序)/preserved`；staged 按 old_id 存 `versions + validation`；mapping 为 `old_id -> [new_id,...]`。这些结构包含任务和内容，只能给可信宿主，不应原样作为公共日志。对外观测只记录 ID、错误码、数量与耗时。

所有 mutator 必须在原子事务内核对 owner/revision；不得在数据库事务中等待模型请求。SQLite 实现适用于本地文件系统的单机多进程，不适用于共享网络文件系统或分布式无 fencing 的写者。其他存储替换必须保持此语义并通过同一故障契约测试。

## 6. 状态重建和恢复执行

`ManagedContextProjection` 是实际可运行的参考宿主：active 检索集合、每个 session 的版本引用及重建消息来自同一 manifest。旧 assistant/tool transcript 不复制进新上下文；可信 task 单独传入。重启后根据持久状态重建。原版 checkpoints 和旧版本仍可审计，但不能成为活跃上下文。

真实运行器若还保留向量索引、浏览器页面/缓存、服务端线程、私有模型状态或文件副本，必须实现自己的 ProjectionPort：清理/替换全部受管理视图，并只在完成后返回 digest。当前参考宿主不声称清除这些外部或隐藏状态。

续行必须重新规划，然后 `SafeExecutor.dispatch(new_proposal)`。`operation_id` 是可信宿主分配的稳定业务操作身份，不能让模型通过换 call_id/改写参数绕过重复检查。effects/grants/epoch 都在恢复 checkpoint 之外。发送前先持久化 in_flight；返回成功后记录 committed；超时/异常为 unknown；进程突然死亡则留 in_flight。两者都阻止恢复 ready。

这里的 checkpoint 是版本/会话 manifest，不是整个数据库文件的历史备份。宿主不能用旧数据库覆盖 effects/grants/epoch；灾难恢复数据库备份时，必须另行与外部效果和当前授权状态对账，否则会破坏“不回滚副作用与权限”的前提。

宿主通过 `reconcile_effect(..., committed=..., evidence=...)` 对照远端回执/查询/人工审查解决未知结果。确认未发生仍保留 terminal 墓碑，新的尝试要由宿主显式分配新业务 ID 和新授权。模块不承诺远端 exactly-once，不会自动“撤回已发送邮件”或执行补偿。若远端支持幂等键，execute 回调应把 operation_id 传给它。

未知或 in_flight effect 也会阻止同 scope 的下一次 dispatch，不能通过换业务 ID 继续执行。对于已经 committed 且依据落在本次影响范围内的动作，仅仅修好记忆仍不足以恢复：返回 `affected_committed_effect_requires_review`。可信事件处理方必须依据实际补偿结果或对不可逆结果的明确处置，通过 `review_committed_effect(..., request_id, evidence=...)` 留下本次事件的处理记录。该接口不执行补偿，也不删除旧效果；独立未受影响的已完成动作不会阻止恢复。

## 7. 验收边界与下一步联调

已覆盖：完整图/坏图、临时节点传播、跨会话后代、正常分支保留、一对多、来源不升级、失败不发布、SQL 中途故障、暂存/发布后崩溃、幂等续作、双副本部分失败、旧动作拒绝、未知副作用、授权撤销及一次性消耗。测试和演示为离线机制测试。原始 TMA/SRR 适配测试另外标记，不假装是攻击 benchmark。

成员 3 先用真实采集图跑 JSONGraphAdapter 契约；成员 2 用故障注入验证两份标签更新、告警和 grant；成员 1 把所有 ingest/derive/context/dispatch 接入宿主钩子。然后在相同污染状态、相同根诊断、相同模型与授权下比较：不修复、仅删根、全清空、全局回滚、原始 SRR、集成修复。

评分应由 benchmark 原始任务判定器/独立攻击判定器给出：攻击成功、正常任务成功、延后复发、受影响状态残留、正常信息保留、误隔离、模型调用/token、延迟、失败原因。分别报告 oracle 根与真实检测根。真实模型预算、GUI 快照能力及真实采集覆盖仍待团队提供，不把未接入项填写为已完成。
