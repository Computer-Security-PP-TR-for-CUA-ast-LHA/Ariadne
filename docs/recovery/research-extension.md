# 恢复方案的追加调研与工程选择

核查日期：2026-11-02。本文补充 [前轮源码调研](literature-and-reuse.md)，以当前固定 checkout 为准。论文思想、直接调用的作者代码、本项目新增的工程代码分开记录；不根据仓库名称或测试通过推断安全性。

## 选择结论

采用 **SRR 的依赖撤销/纯 writer 重放思想 + MemoRepair 的先屏障后发布约束 + ACRFence 的效果/授权不回滚约束**。直接复用 TMA 原始参数恢复和 SRR 原始候选规划；本项目新增可替换事务协调层、图接口、宿主投影和安全 dispatch。没有把未知许可仓库复制进项目，也没有宣称完整复现各篇论文。

| 候选 | 一手来源与定位 | 本轮处理 |
|---|---|---|
| SRR | [作者论文页](https://aliuyar.dev/research/selective-revocation-and-replay/) / [源码](https://github.com/aliuyar1234/selective-revocation-replay)；显式持久状态撤销与 dirty writer 重放 | 直接调用固定版本 `compute_persisted_descendant_closure`、`build_replay_plan`；3 项新 adapter 检查通过。保留其原始 replay 模式，不将它的安全判断作为 Ariadne 发布许可 |
| Dependency-Guided Rollback Repair | [论文 v2](https://arxiv.org/abs/2608.10502v2) / [源码](https://github.com/xiaoqi-7/memory-rollback)；类型边、支持检查、选择性重放 | 保留此前 4 项行为探针。缺根时原实现跳过，以及无 support 默认为受支持，不适合作为安全恢复默认值；本组件明确拒绝未知根，不能凭缺证据保留污染节点 |
| MemoRepair | [论文](https://arxiv.org/abs/2605.07242)；撤回 affected cascade 后才修复、只发布验证且前驱闭合的新版本 | 新增为最直接的恢复事务约束依据。未核实作者代码。采用思想适配，不复制算法；当前全有或全无发布，没有 min-cut 选择优化，也不借用论文数字声称本项目效果 |
| AgentSentry | [论文](https://arxiv.org/abs/2602.22724v2) / [源码](https://github.com/CyberGuardianAI/AgentSentry)；边界诊断与反事实净化/续行 | 可替换诊断后端候选；依赖原 AgentDojo/模型轨迹，未完成完整复现。新 ModelRepairBackend 只是本项目模型 adapter，不能称其为 AgentSentry |
| TMA-NM | [论文](https://arxiv.org/abs/2606.24322) / [MIT 源码](https://github.com/yedidel/mem-inv-bench) | 真正调用原 `recovery_catalog.authorized_parameters()` 与 `ScopedGate`。8 项新检查覆盖独立域、撤销、过期、歧义、伪造、错误范围、代码校验；不承担语义净化 |
| ACRFence | [论文](https://arxiv.org/abs/2603.20625)；语义重试与授权复活问题 | 作者 artifact 尚未核实。实现思想适配：持久业务操作身份、效果账本、一次性授权、撤销 epoch、未知效果暂停；不声称完成论文协议复现 |
| MnemoIR | [MIT 仓库](https://github.com/DheerajPranav/mnemo-ir)，本轮固定 `3e83d8337545b9254c1165d69ea84e0016e7de4c` | 阅读 impact/remediation/replay/models，运行原始 impact/remediation/replay 的 20 项离线测试通过。适合事件响应 API 和对照；暂不作为生产恢复执行底座，原因见下 |
| LangGraph | [官方 persistence 文档](https://docs.langchain.com/oss/python/langgraph/persistence) | 有 checkpoint/store 基础设施，不能单独解决污染传播或外部副作用。当前项目是标准库内核，为这部分引入完整 agent 框架会扩大依赖；保留 ProjectionPort 后续适配 |
| OpenAPPA / Fides | [OpenAPPA](https://github.com/archestra-ai/OpenAPPA) / [Fides](https://github.com/microsoft/fides)；此前 Details.md 已记录的策略/标签候选 | 属于成员 2 的策略与信息流边界，保留既有调研。本轮未将未通过的实际 redactor 路径或教学 notebook 当作完成的持久恢复服务 |

## 为什么不能直接把某个仓库整体接上

SRR 的原生对象区分临时结果与 memory/summary；闭包经过临时节点但只输出持久后代，且不包含根本身。它的原始场景有固定 session 顺序、已知可疑根、文本文件宿主。Ariadne 需要全域冻结、根和后代一起隔离、跨会话重建以及副作用保护。因此原始计划作为候选/对照保留，不能绕过本项目图完整性和发布验证。当前 SRR adapter **没有调用原始 replay_dirty_writers 或 coarse suffix tools**；本项目 WriterRegistryBackend 是显式标注的适配实现。

memory-rollback 将时序链和依赖边区分，值得保留；但面向回答的选择性重放不等于所有长期副本均已恢复。本项目先用全 scope 后代闭包和全有或全无发布保证保守性，未来再以独立支持证据缩小代价。不是宣称更强效果，而是明确不同工程约束。

MemoRepair 给出了“屏障先行、候选暂存、前驱闭合发布”的清晰契约。本组件的 SQL 隔离和全量发布实现这一工程方向；验证器可能误判、采集可能缺边，不能由事务正确性推出语义安全。原论文的性能结果未在这里重现。

MnemoIR 在固定版本的 `sdk/remediation/__init__.py::Remediator.apply` 中，对 COMPENSATE 和 RECOMPUTE 的处理是计数，而不是调用真实外部补偿或实际内容重算；不能把 `repaired` 数字等同于已经完成业务修复。`sdk/replay` 的 outcome 变化依赖调用方提供 rerun，变化本身也不能在随机模型上证明恶意因果。原始 20 项测试是实现自检，不能替代真实 CUA 验收。因此不把这个工程 scaffold 升格为可直接使用的完整恢复系统。

SQLite [原子提交说明](https://www.sqlite.org/atomiccommit.html) 支持本机事务参考实现。这里使用短事务、明确 revision 和持久状态机；跨双份标签回写不能假装属于同一 SQL 事务，需要屏障和回写确认。新工程代码重点补足这些接口与故障行为，不重新发明图算法（拓扑使用标准库 graphlib）。

## 可复用性与证据等级

| 级别 | 当前证据 |
|---|---|
| 文献可追溯 | 上述论文/作者页与源码 URL，访问日期；此前版本/hash 在 sources.lock.json |
| 作者代码可执行 | SRR 原始 smoke 6 项此前通过；本轮 native planner 3 项；TMA 原始授权/恢复经新 adapter 8 项；MnemoIR 20 项 |
| 本组件机制可执行 | SQLite 恢复状态机、图/宿主/标签 adapters、异常/崩溃/权限测试、离线续行 demo |
| 真实防护有效 | **尚无此结论**：没有付费 API、完整真实模型 matrix 或真实 GUI 恢复实验 |
| 团队集成完成 | **尚无此结论**：成员 2/3 的真实实现尚待按 v0.2 连接；图捕获覆盖、双副本故障域及宿主隐藏状态需验收 |

下一步最有价值的是固定污染快照下的原方法/集成方法对照，以及同源模型净化/验证的误判率测试；不是继续叠加更多未验证后端。新发现或新模型应先保留独立实验入口和锁定版本，再决定是否加入默认路径。
