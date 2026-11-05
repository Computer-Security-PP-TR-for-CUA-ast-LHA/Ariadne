# 通用实现替换审查与落地（2026-11-02）

本轮响应“先复用成熟工程，未覆盖或未通过资格检查的部分再自行适配”。**默认恢复链现在使用 LangGraph 持久编排、SqliteSaver 检查点、filelock 进程锁，以及 SRR 原始 `replay_dirty_writers`。** 原自写 writer 调度器已经从生产包删除，仅保留为测试替身。此前仅独立测试 TMA/SRR planner 的状态已改变。

这不是“某个完整论文方法被原样复现”：图和权限约束属于 Ariadne；SRR 在这里按标准化 writer 单元适配；净化/验证模型效果仍须独立评测。详细版本、源码 hash、测试命令和证据在 [审查锁文件](reuse-audit.lock.json)。

## 1. 审查方法与候选范围

先比对需求：能持久化已完成步骤；重启不重复已完成 writer；未完成纯计算可重试；确认污染后所有可见读取保持屏障；候选版本不能半发布；外部效果与已消耗授权不能被工作流回滚；能够在当前单机 Windows/Linux Python 宿主落地。随后检查源码、许可、版本、依赖、原始测试、真实进程终止探针，再接入现有契约测试。

| 候选 | 一手依据 / 实测深度 | 判断 |
|---|---|---|
| **LangGraph** | [源码](https://github.com/langchain-ai/langgraph/tree/1.2.19)、[持久化文档](https://docs.langchain.com/oss/python/langgraph/persistence)；阅读 Pregel loop、SqliteSaver、serde；原始 SQLite saver/迁移测试 17 项；真实进程终止探针通过 | **选用**。显式图节点、持久 interrupt、同步 checkpoint 适配当前嵌入式接口；无需接管宿主进程级全局运行时。承认其依赖数量增加；SQLite saver 限于本地小规模同步使用 |
| **DBOS** | [源码](https://github.com/dbos-inc/dbos-transact-py/tree/3.4.0)、[工作流恢复](https://docs.dbos.dev/architecture)；阅读 step/workflow、configured instance、恢复与序列化；5 项原始恢复/单执行/SQLite 线程测试通过；同一真实终止探针通过 | **可行备选**，并非质量不佳。其 launch/destroy、全局注册及自动恢复更适合由宿主统一管理的持久服务；本轮优先保持可嵌入的组件生命周期。没有同时引入两个编排引擎 |
| **Temporal** | [Python SDK](https://docs.temporal.io/develop/python)、[确定性 sandbox](https://docs.temporal.io/develop/python/best-practices/python-sdk-sandbox)；文档审查，未启动服务 | 成熟持久工作流方向；需要 Temporal Service/Worker 生命周期，当前本地组件不承担该部署。未来多机调度应重新评估，不能据此宣称其不适用所有场景 |
| **Restate** | [durable steps](https://docs.restate.dev/develop/python/durable-steps)；文档审查，未部署 server | 有 journal/replay 和重试语义；需要服务接入。默认重试也不能直接套到未知外部效果上。暂不作为本轮默认引擎 |
| **Apache Burr** | [工程仓库](https://github.com/apache/burr)；项目/接口审查，未运行资格测试 | 状态机和持久化候选，但没有证据证明相对已通过探针的 LangGraph 在当前接口上更优；保留候选，不虚报完成源码全面审计 |
| **OpenStack TaskFlow** | [官方文档](https://docs.openstack.org/taskflow/latest/)；文档审查，未运行资格测试 | 持久任务/恢复候选；revert/补偿语义不能自动等同于污染修复或业务效果撤销。本轮不引入第二套通用恢复状态机 |
| **SRR** | [作者页](https://aliuyar.dev/research/selective-revocation-and-replay/)、[固定源码](https://github.com/aliuyar1234/selective-revocation-replay/tree/d7bcb32740156cb985fae0ee93caba35ee45e67e)；原始 smoke 6 项、新原生 replay 集成与进程崩溃测试 | **选用原始 writer 重放**，不再只接 planner；保留作者代码外部 checkout，不重新分发缺少项目级许可证的源码 |
| **memory-rollback** | [论文与源码入口](https://arxiv.org/abs/2608.10502v2)；审查固定版本的数据模型和受影响子图行为 | 类型化边、多根下游闭包作为本地独立实现的设计依据；没有复制或运行其无项目级许可证的源码，完整选择性恢复仍作为方法对照 |
| **MnemoIR** | [源码](https://github.com/DheerajPranav/mnemo-ir/tree/3e83d8337545b9254c1165d69ea84e0016e7de4c)；此前 20 项原始测试与 remediation 源码审查 | 部分 COMPENSATE/RECOMPUTE 分支只是计数；不能直接替换真正的重建执行。可复用 API 思路，不将计数当作修复完成 |
| **AgentSentry / TMA / MemoRepair / ACRFence** | [前轮分析](research-extension.md)及其一手来源 | TMA 原代码保留用于参数恢复；AgentSentry 的原宿主/模型条件尚未通过本项目接入验收；MemoRepair/ACRFence 提供发布与效果边界约束，不声称取得完整原始工程 |

没有因为“尚未测试某候选”就断言它不可用。DBOS 与 LangGraph 都通过同一故障探针，最终选择是宿主适配取舍，不是没有证据的优劣排名。

## 2. 真正替换了什么

| 之前 | 现在 | 本项目保留职责 |
|---|---|---|
| `recover()` 手写 phase 分支与恢复调度 | LangGraph `StateGraph` 节点/条件边、`interrupt` / `Command(resume=...)` | 节点内部的图完整性、隔离、验证和发布规则 |
| 仅用 domain job 的状态实现续作 | 原始 `SqliteSaver` 保存工作流执行点，`durability='sync'` | domain job 继续作为版本发布审计和幂等 SQL 事务依据，不承担通用工作流调度 |
| `msvcrt` / `fcntl` 自写跨平台锁 | 原始 **filelock** 包 | scope 锁路径及冲突错误码，限定本机文件系统 |
| 自写 `WriterRegistryBackend` 在默认 demo 里直接调用回调 | 原始 SRR `build_replay_plan` → `replay_dirty_writers` → 原始对象/事件写入函数 | 标准化版本到原生事件的适配、模型/纯 writer 回调、验证、完整输出映射 |

默认 demo 必须提供固定 SRR checkout；依赖缺失或版本不符会失败，**不会静默切回自写重放器**。TMA 仍是独立参数恢复接口，不声称它在普通记忆修复中必然被调用。

## 3. 深入检查得到的边界及补齐

### SRR 一对多输出

原 `replacement_map[old_id] = new_id` 是标量。一个 memory writer 返回多个同 kind 的 item 时，原始 `_match_replay_target` 会将它们匹配到同一个旧对象，map 最后只保留最后一个 ID。直接把该 map 当作我们的一对多映射会漏掉输出。

实际测试产生两个新对象，但原生 scalar map 只有一个键。适配层没有复制/重写原 replay，而是读取它实际生成的 replay event 的全部 `output_object_ids`，逐项核对 `replay_of` 和输入父节点，再返回所有文本给 Ariadne 验证/发布。下游重放测试确认收到两个前驱输出。

### SRR 的原生适用范围

每次适配一个标准化 writer 单元，使用原生 `memory_write` / `summary_write`；已经修复的输入映射成原生 tool-result 数据，可信 task 单独映射 user-turn。旧污染文本不发送给 writer。原生内部使用固定 session，不能冒称还原了真实多 session 原始轨迹。跨会话闭包与先后顺序由完整版本图和工作流控制。

上游 backend 在原 `replay_dirty_writers` 调用处经本地 IPC 请求宿主 provider，provider 根据 **SRR 实际选择的输入**生成内容，再交还原始 replayer 生成对象和事件。因此不是先调用自写重放器、事后贴一个上游标签。禁止 external-effect recipe，不调用原始 coarse suffix replay。

`summary_write` 目前要求一个输出；一对多仅开放给 memory writer。未知 writer、无支持输入、输入不一致、输出空/超限、checkout 漂移都拒绝。模型生成仍由宿主提供的有界 client 执行；本轮仅用明确标注的合成 provider，没有真实语义效果结论。

### domain 提交和工作流 checkpoint 的间隙

两份 SQLite 数据不是分布式事务。节点可能已经成功提交 domain 状态，却在 LangGraph checkpoint 前被杀死。因此隔离、暂存和发布节点执行前都会读取 domain phase/已暂存版本，重复调用不会再次生成已持久化结果或重复发布。

新增测试使用真实 `os._exit(77)`，分别在暂存提交后、发布提交后、宿主安装后、domain ACK 提交后杀死进程，再启动全新进程。结果验证：根修复只运行一次；新状态正常续作；宿主安装后、ACK 前崩溃必须重新安装；ACK 后崩溃能收敛到最终工作流检查点。安装与 ACK 放在同一个持久节点，避免恢复时复用死亡进程的“已安装”检查点。ACK 已提交后的宿主重启仍须从当前 manifest 装载上下文，参考 `ManagedContextProjection.messages()` 的每次读取校验，不能把历史 receipt 当作内存缓存已恢复的证明。

### 序列化、状态大小和执行效果

显式关闭 pickle fallback 和任意模块解码，仅允许 upstream 安全类型。checkpoint 只保存 scope/request/revision/fingerprint/phase/数量/错误码，源文本、任务及候选内容留在受信任 domain ledger，不在每个 checkpoint 重复存整份 staged 内容。checkpoint 库仍属于可信宿主状态，不允许外部资料写数据库。

外部工具 dispatch 不放进自动重试图。已消耗 grant、授权 epoch、effect tombstone 仍在非回滚 domain 记录中；未知效果和受污染影响的已完成效果仍阻止 ready。通用工作流产品提供持久执行，并不替我们判断 prompt injection、独立授权或远端 exactly-once。

## 4. 为什么还有自写代码

保留的是可替换 domain 规则和团队协议：捕获图校验、来源单调性、整域隔离、验证器接口、前驱闭合的原子版本发布、双标签 ACK、活动上下文、独立授权及效果审查。上述引擎不直接提供这些 Ariadne 语义。

这不是声称这些规则永远找不到可复用实现。实际标签/图后端接入后仍应优先替换参考存储；原生内容净化后端尚需模型资格测试。当前没有证据证明自写 prompt 优于 AgentSentry，故不作该结论。

源码行数也不代表工程质量。本轮加入了真正的上游运行依赖，同时需要 IPC、接口适配和故障测试，**自有文件总行数可能增加**。统计脚本 `scripts/research/count_recovery_loc.py` 将 adapter 计入自写，不把整个依赖包的数万行凑成“复用率”。

同口径统计（仅 `src/cua_guard/recovery/*.py`，不含 demo、测试和研究脚本）：基线 `2d2d346` 为 **1,346 物理行 / 1,095 有效代码行**，本轮为 **1,626 / 1,321**。新增的上游 IPC 和持久工作流接线也算自写。复制进仓库的上游源码仍为 **0 行**；复用通过固定依赖及外部固定 checkout 执行。可复现逐文件结果在锁文件 `line_counts`，不再用少数入口函数行数代表全部被调用的上游代码。

## 5. 可复现运行及接口变化

```powershell
python -m pip install -e ".[srr]"
git clone https://github.com/aliuyar1234/selective-revocation-replay.git <外部目录>/srr
git -C <外部目录>/srr checkout --detach d7bcb32740156cb985fae0ee93caba35ee45e67e
$env:ARIADNE_SRR_CHECKOUT = '<外部目录>/srr'
python -m cua_guard.recovery.demo
python -m unittest discover -s tests -v
```

依赖的精确直接版本见 pyproject.toml，测试时的传递依赖版本见 `requirements/recovery-tested.txt`；可用 `pip install -c requirements/recovery-tested.txt -e ".[srr]"` 重现已测环境。SRR 测试需要 SRR checkout；本地溯源图测试不需要外部仓库；TMA 检查仍可通过 `ARIADNE_TMA_CHECKOUT` 启用。核心 Python 版本保持 3.11+。不再承诺恢复模块零第三方依赖。

新增 `RecoveryStorePort.workflow_path(scope)`；其他图/告警/版本 schema 仍为 v0.2。原 `WriterRegistryBackend` 不再是生产 API，改用 `SRRWriterBackend(checkout, sanitizer, provider, recipes)`，provider 实现 `identity` 和 `write(kind, inputs, task) -> tuple[str,...]`。完整模型入口可组合 `ModelRepairBackend`、`ModelWriterProvider`、`ModelRepairValidator`，但不会自动启用收费模型。

旧 v0.2 未完成 job 不原地改用新引擎：算法身份变化会触发 `request_id_conflict`。先完成旧版本事件，或在隔离快照上由宿主显式迁移；禁止清除 owner 或回滚效果账本来“解决”冲突。历史工作流 checkpoint 不能当作继续执行的授权。

可复现比较探针：安装研究依赖 `dbos==3.4.0` 后运行 `python scripts/research/qualify_durable.py --engine dbos`；LangGraph 对应 `--engine langgraph`。两者均检查已完成步骤一次、被中断步骤两次、重复完成请求无额外调用。该探针不代表吞吐量、分布式保证或真实攻击防御效果。

## 6. 最终验证

实现提交 `e88ecf512a8b13d0c66ca7c633d37587d5a6b727` 从干净 worktree 构建 wheel，再安装到新的 Python 3.13.5 环境；不设置 `PYTHONPATH`，确认导入自安装包，启用两个固定上游 checkout。**98 项测试通过，无跳过，耗时 60.558 秒**。四个真实进程终止窗口、一对多 writer 输出、失败重试、配置变更拒绝及旧安全契约均在其中；`pip check` 无冲突。

在仓库目录以外运行安装包 demo：原始 SRR writer replay 被调用，修复后旧版本可见数为 0，正常版本保留，休眠副本重建，恢复执行一次。它使用合成净化/生成器，模型调用和外部工具调用均为 0。

[GitHub Actions](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/actions/runs/41451944312) 的五个任务全部通过：Windows/Ubuntu × Python 3.11/3.13 加单独 TMA 原始代码接入测试。主矩阵启用 SRR、单独 job 启用 TMA；没有把主矩阵跳过的 TMA 项当作通过。另有本轮原始 LangGraph 17 项、DBOS 5 项、SRR 6 项测试与两个引擎的真实崩溃比较探针通过，具体命令见锁文件。

真实团队标签库/图后端、生产宿主缓存和真实模型/GUI benchmark 尚待联调，当前结果不能解释为真实攻击成功率或端到端生产验收。
