# 定向恢复：论文、源码与适配审查

访问与本地验证日期：2026-11-02。负责人分支：`luowentao`。固定 commit、文件 hash、实测项见 [锁文件](sources.lock.json)。本文中的适配设计是 Ariadne 的建议，不是原作者结论。只报告执行过的验证；源码可读、原测试通过和真实防护有效是不同证据等级。

## 1. 选择结论与修正

此前以 AgentSentry / TMA-NM 为主要修复候选的清单不够完整。本轮找到两个直接处理持久派生状态恢复的作者关联仓库，应将它们提升为优先评估对象：

| 优先级 | 工作 | 适合承接的能力 | 尚缺什么 |
|---|---|---|---|
| P0 | Selective Revocation and Replay（SRR） | 持久后代撤销、dirty writer 事件重放、失败回退 | 通用事件/版本协议、CUA 副作用边界、真实来源覆盖、项目级许可核查 |
| P0 | Dependency-Guided Rollback Repair（memory-rollback） | 类型化依赖图、影响范围、支持检查、修复计划与选择性重放 | 跨会话全域图、严格缺失行为、可信支持判定、外部工具控制、许可核查 |
| P1 | AgentSentry | 工具返回边界诊断、净化、修订动作和续行 | 原始 AgentDojo 接入及模型资格测试；持久副本失效需补齐 |
| P1 | TMA-NM | 从独立且有效授权记录恢复完整参数 | 真实权威渠道；不承担内容净化和状态重建 |
| 对照 | ChronoMem | 全量快照与全局恢复思想 | 作者代码未定位，不得冒称运行原方法 |
| 约束 | ACRFence | 防止 checkpoint 后重复副作用和已消耗权限复活 | 作者代码未定位；先体现为执行协议不变量 |

推荐路线：先保留上游独立运行入口，再将其结果映射为 Ariadne 修复计划；不要先大规模复制代码或把多个后端的“允许”结果做 OR。当前三个 P0/P1 仓库（SRR、memory-rollback、AgentSentry）均未找到项目级 LICENSE，故暂不 vendoring；可分发的代码集成需先核实授权范围。没有替用户联系作者。

## 2. SRR：最贴合“持久副本撤销 + 状态重建”的轻量起点

一手来源：[作者研究页](https://aliuyar.dev/research/selective-revocation-and-replay/)、[作者仓库](https://github.com/aliuyar1234/selective-revocation-replay)、[论文源文件](https://github.com/aliuyar1234/selective-revocation-replay/tree/d7bcb32740156cb985fae0ee93caba35ee45e67e/paper)。作者是 Ali Uyar，作者页标为 2026-03-11；本文不把 `usenix_security26` 文件夹名当成会议录用证据。

论文研究的是污染已经持久化、可疑根已给定之后的恢复，限定文本文件宿主与显式状态。其主要思路是撤销派生持久状态，只重放可安全重放的写入事件，否则回退。原论文狭窄场景中的结果不能外推成 CUA 通用恢复保证。

**实际源码入口**（固定 commit `d7bcb32740156cb985fae0ee93caba35ee45e67e`）：

| 文件 / 符号 | 观察到的实现 | Ariadne 映射 |
|---|---|---|
| `src/schemas.py::ObjectRecord` | 对象 ID、session、kind、parents、status、meta | 不可混淆的版本节点；额外增加内容 hash、来源身份与覆盖状态 |
| `EventRecord` | input/output object IDs 及事件类型 | writer 事件：记录真实输入输出与重放配方 |
| `ReplayPlan` | 撤销对象、dirty events、安全/不安全事件、顺序、替换映射 | 修复计划、未解决项和后端原始返回 |
| `recover.py::compute_persisted_descendant_closure()` | 遍历所有中间对象，输出 memory/summary 后代 | 不能只遍历 memory 节点，否则会漏掉工具结果中转的传播 |
| `build_replay_plan()` / `_is_replay_safe()` | 区分 writer-only 与 coarse rollback | 映射到宿主能力检查；不能当通用副作用安全证明 |
| `replay_dirty_writers()` | 用清理过的输入调用 writer，新增对象并维护映射 | 候选版本暂存，经过额外复检后才发布 |
| `_rebuild_active_state()` | 重建活动记忆和当前摘要视图 | 检索索引与 checkpoint 的一致切换 |

**已识别的适配边界：**

- `select_suspicious_root_ids()` 根据已知攻击文件路径选择根，是实验 oracle，不是通用检测器。接入时由结构化告警提供版本和证据。
- `_is_replay_safe()` 主要检查剩余 user turn 与摘要输入，适用于其限定 writer。CUA 必须额外检查工具副作用、输入覆盖、版本、环境可重放性。
- 会话顺序依赖固定 `SESSION_ORDER`。跨任意会话与分支时应改为宿主事件顺序/拓扑顺序。
- `_match_replay_target()` 先按记忆 kind、再按文本匹配旧对象，不足以作为一般唯一身份映射。Ariadne 需显式输出来源槽位；重建可出现一对多或零输出，不能悄悄把同 kind 的多个节点合为一个。
- 路径隔离只适用于其文件环境；路径被改名、复制、工具回显或新版本进入时，需要宿主内容/版本关联。
- coarse rollback 可能重跑 session；没有证明外部副作用可安全重放时，Ariadne 返回 `needs_review`，不照搬 fallback。

**本轮验证：** 使用原始 `tests/test_runtime_smoke.py`，6 项通过；包含 retrieval writer-only、summary fallback、checkpoint 重开、经 tool_result 的后代闭包、清理隔离路径输入。使用 heuristic backend，无真实模型推理。README 徽章写 Python 3.11+，`pyproject.toml` 实际要求 >=3.12，应以后者作为安装约束。

复现（checkout 放在项目外；下列只运行离线测试）：

```powershell
git clone https://github.com/aliuyar1234/selective-revocation-replay.git <SRR_DIR>
git -C <SRR_DIR> checkout d7bcb32740156cb985fae0ee93caba35ee45e67e
# 在独立 Python >=3.12 环境安装该 checkout 的依赖与 pytest 后：
Set-Location <SRR_DIR>
python -m pytest tests/test_runtime_smoke.py -q
```

## 3. memory-rollback：最值得共同审查的“图—计划—执行”代码

一手来源：[论文 v2](https://arxiv.org/abs/2608.10502v2)、[作者链接的仓库](https://github.com/xiaoqi-7/memory-rollback)。论文于 2026-08-11 首发，2026-10-22 更新。研究给定已诊断错误记忆后的恢复；不解决所有自动定位问题。它明确讨论选择性重放的恢复效果与复发之间的取舍。

固定 commit `713724491b9bbc6e55f0f9d8723da0eb0766ced7`。以下为直接阅读源码的结果：

| 文件 / 符号 | 具体可用点 | 必须适配的语义 |
|---|---|---|
| `graph_schema.py::GraphNode/DependencyGraph` | memory/step/user_input、语义类型、双向邻接表、每对端点的多类型边集合 | 不把单个布尔 trusted 替代来源/权限；任意 ID 通过映射表转换 |
| `build_dependency_graph.py` | 从 memory 和 trace 构造关系 | 上游 trace 字段不等于可信宿主完整观测；不能无条件信任模型 `used_ids` |
| `affected_subgraph.py::affected_node_ids()` | 多根可达闭包，排除纯 `chain` 时间顺序边 | 返回不含根；必须补根并检查不存在 ID，统一作用域和覆盖标记 |
| `support_checker.py::has_trusted_support()` | 评估是否存在独立支持 | 默认无支持边时返回 True；不能直接用作安全释放条件 |
| `rollback_optimizer.py::build_rollback_plan()` | 保留、失效、重放等 disposition | 规划偏向最后一轮答案，不能替代全域持久状态失效 |
| `rollback_executor.py::execute_rollback_plan()` | 轨迹与记忆的重建编排 | 与原 agent/memory store 紧耦合；先外部进程适配，避免大规模内部函数调用 |
| `selective_replay.py::ReplayBackend` | 选择性重计算 | 依赖真实模型/工具；`FakeReplayBackend` 只能用于机制测试 |

本轮图自检通过，另用 [Ariadne 探针](../../scripts/research/probe_memory_rollback.py) 实际验证四个行为：

1. `derive` 连接的副本及其 `support` 消费者可达。
2. 只有 `chain` 边连接的后续步骤不进入闭包。
3. 不存在的根仅输出告警并返回空集合。
4. 没有支持边的 claim 在上游默认支持检查中返回 True。

后两项是**上游行为特征，不是安全测试通过**。Ariadne adapter 必须将未知根视为输入/覆盖错误，将无支持的保留判定视为 `unknown`；独立支持需能说明当前任务相关事实由何种可信渠道独立支撑。存在一条正常支持边并不自动证明混合文本无恶意内容。

```powershell
# checkout 与源码许可按独立依赖管理，不复制进 Ariadne
python scripts/research/probe_memory_rollback.py --upstream <MEMORY_ROLLBACK_DIR>
# 在上游目录中运行其原始结构自检：
python -m methods.ours.graph_schema
```

运行完整原实验需要模型及 embedding 服务；README 要求 agent-based 实验提供 Qwen embedding 凭据。本轮未安装整套模型依赖、未配置密钥、未执行原 150/50 用例。其 baseline 名称带 `-style` 的是适配对照，不能改写成其他论文作者原实现。

## 4. AgentSentry 与 TMA-NM：补充后端

**AgentSentry**：[论文 v2](https://arxiv.org/abs/2602.22724v2)、[仓库](https://github.com/CyberGuardianAI/AgentSentry)。`agentsentry_integration.py::build_agentsentry()` 构造原始 `released-ols` profile；核心在 `pi_detector.py`。输入不只是任意一段文本，而是工具返回边界、上下文、原动作及受控 replay 运行时。反事实 shadow run 不能产生真实外部副作用。当前只做源码审查，未安装/运行其完整模型链。将它改为单节点 sanitizer 属于 adaptation，应保留原始方法对照，不能沿用原论文性能数字。持久副本撤销由 Ariadne 单独负责。

**TMA-NM**：[论文](https://arxiv.org/abs/2606.24322)、[仓库](https://github.com/yedidel/mem-inv-bench)。固定版本的 `code/recovery_catalog.py::authorized_parameters()` 返回 `available/unavailable/ambiguous`，依赖调用方提供 authorities、policy、签名 records、operation、subject、当前时间和撤销信息。`scoped_authorization.py::ScopedGate` 执行最终授权。可直接复用范围清晰，仓库标为 MIT。

本轮重新运行已有本地 `scripts/demo_reused_authority.py`，6 个检查通过：错收件方拒绝、参数精确恢复、再次授权、未知操作拒绝、过期拒绝、撤销拒绝。该脚本及加载器仍是既有未提交实验，本次不夹带发布；结果只有合成权威、无模型、无工具执行，不代表真实身份渠道或语义修复。第三方合成 domain 不等于真实独立组织。

## 5. 其他文献与不选作主依赖的原因

| 文献 / 代码 | 与本模块的联系 | 本轮决定 |
|---|---|---|
| [MemLineage](https://arxiv.org/abs/2605.14421)；[第三方实现](https://github.com/amurlaniakea/memlineage) | 来源图与授权修复的重要近邻 | 作者 artifact 未定位；第三方仓库自称独立实现，AGPL-3.0-or-later，不能冒充原作；由成员 3 评估图底座 |
| [ChronoMem](https://arxiv.org/abs/2607.27773) | 全局版本恢复、暴露之后的恢复一致性 | 查阅论文 HTML 未定位作者仓库；同名项目不算对应代码；只作为全局回滚设计参考 |
| [ACRFence](https://arxiv.org/abs/2603.20625) | 语义等价动作可能换 ID 重复执行；已消耗权限不应因恢复而复活 | 纳入效果账本和 checkpoint 边界；本次未找到原实现，不把第三方实现等同作者代码 |
| [RecoverAgent](https://aclanthology.org/2026.findings-emnlp.830/) | 检测后保持用户意图的响应修订与续行 | 有论文，尚未定位作者代码；不作为当前必需依赖 |
| [MemSecBench](https://arxiv.org/abs/2607.27080) | 从记忆写入到后果、修复的生命周期评测 | 供成员 1 设计指标，本轮未完成 benchmark 复现 |
| [OpenAPPA](https://github.com/archestra-ai/OpenAPPA) | 策略、标签与 remedy 运行机制 | 现有本地真实 redactor 失败记录尚未解决，不设为唯一修复器；不把 stand-in replay 算净化成功 |

附加工程线索 [MnemoIR](https://github.com/DheerajPranav/mnemo-ir) 也描述图范围、隔离与恢复验证，但本轮未做源码/测试资格审查，不因 README 用了 causal/proof 字样就认定具备可验证因果保证。

## 6. 对接口和实验的直接影响

### 图接口不能只有 parent/child

SRR 需要 writer 的真实输入、输出和重放参数；memory-rollback 需要区分内容依赖、时间顺序、支持和替换。故 v0.1 将版本身份、writer 事件和审计边分开，提供固定快照上的类型化查询。边是已采集依赖，不自动等于恶意因果；图缺失与语义不确定分别报告。

### 先比较修复，再比较定位

固定同一已投毒状态与相同根证据，比较原始 SRR、原始 memory-rollback（达到复现条件后）、只删根、全局回滚、清空、仅上下文净化和 Ariadne 适配。新图覆盖、更强净化模型或更准确 locator 带来的收益不能全归因于恢复算法。原方法不可运行时应留空并列出阻塞，不用自写替身填充原方法结果。

### 验收指标与失败归因

- 修复后实际合法任务成功率、再次触发复发率，分母分别固定并记录样本选择。
- 被隔离污染版本与派生副本的召回、误隔离、正常信息保留；oracle 标签仅作评测真值。
- 可检索污染副本数、checkpoint 重开后的旧版本再入、覆盖缺口。
- 修复后模型调用/工具调用、时延、重放事件数；heuristic 调用计数不能当真实 token 成本。
- 失败分为定位不足、缺边、净化失败、状态发布冲突、上下文未重建、外部效果未知和环境失败。

原论文已有“局部恢复比清空保留更多正常状态”的主要思路。当前可主张的是可复现适配与 CUA 集成；迟到告警、来源断链、双份引用丢失或副作用重放是否有新增研究价值，需与这些近邻在相同条件下比较后再决定。
