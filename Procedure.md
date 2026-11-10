# Ariadne 项目进展 · 2026-11-10

本轮核查基于 `main` 的 `540e831`。相对上次文档提交 `6cc9885`，远程新增了[数据与实验方案](数据推荐.md)，运行代码和测试没有变更。标签、图和恢复代码已经合入同一仓库。当前可以复现标签持久化、依赖图投影和定向恢复。下一个里程碑是让同一次 benchmark 任务产生可追踪的观测、图、修复记录与官方得分。

## 主线交付

| 合入点 | 已交付 | 证据入口 |
|---|---|---|
| `aea1a70` · PR #2 | 修复协调器隔离已确认的根和后代，验证候选版本并发布。LangGraph 记录持久执行位置，SRR 重放记忆或摘要 writer | [恢复审查与故障测试](docs/recovery/reuse-audit.md) |
| `40dc473` | 双份标签库成为版本状态的权威来源。AgentLAB Email 和 RedTeamCUA 的受控入口使用标签会话，标签桥接层把提交结果同步给恢复库 | [写入、隔离与恢复协议](docs/label-layer.md) |
| `316c0be` · PR #3 | 由宿主提供的 trace 构建三类节点、十类边的图，支持影响范围查询、JSON/SVG 导出和版本快照投影 | [图接口及十类边样例](docs/provenance/README.md) |

## 11 月 10 日复核

| 检查对象 | 方法 | 结果与适用范围 |
|---|---|---|
| 主线回归 | 在干净的主线工作树设置 `PYTHONPATH=src`，启用固定版本的 TMA 和 SRR checkout，运行 `python -m unittest discover -s tests -q` | Windows Python 3.13 上 147 项通过，0 跳过，146.925 秒 |
| AgentLAB Email | 运行 `python scripts/smoke_label_agentlab.py --agentlab <AgentLAB检出目录>`，上游提交 `36f58e60` | 正常邮件任务完成，注入用例发出污染告警、修复至 ready 并完成任务，未授权发送在 send_email 执行前被阻断。使用真实 Email 环境、脚本模型及夹具验证器 |
| RTC-Bench 配置 | 在 RedTeamCUA 提交 `a05b8bd0` 遍历 `evaluation_examples/test_all.json`，按平台与 ID 从同目录的 `RedTeamCUA_configs.zip` 逐个读取 `examples/<平台>/<ID>.json` | OwnCloud、Reddit、Rocket.Chat 各 288 个平台内唯一 ID。全部 864 份均可解析，ID 和平台与索引相符，instruction、evaluator 和 adversary_evaluator 非空。GUI 执行与评分器运行仍待验收 |

### 审核发现与优先处理项

| 状态 | 发现及影响 | 下一项验收 |
|---|---|---|
| 文档口径已校正 | 实验方案原先把执行门画进 B0，技术详解又把仅执行门的组称为 B1，与写入过滤组重名。沿用旧标签会混淆实验结果 | B0–B4 用于端到端评测，恢复实验的仅门控组写作 Gate-only。每条结果附配置和初始快照 ID |
| 批量运行前待处理 | Ariadne GUI 入口直接将 `--output` 交给原始 runner。复用同一目录时，成功轨迹的 `result.txt` 和 `adversary_result.txt` 会被后一次写入覆盖，`traj.jsonl` 则会追加；执行中断还可能缺少评分文件 | 为每个 case、对照组和重复轮次指定独立输出目录。先跑两次并核对各自轨迹、两项评分与终止原因；运行清单保留失败项。[入口实现](src/cua_guard/redteamcua.py) |
| 宿主联调仍有缺口 | 两个 benchmark 入口使用标签会话。图模块已有 recorder、版本投影和单测，在这两个入口中尚未找到直接调用 recorder 并将该次完整图送入恢复的路径。Email 冒烟验证到标签与恢复，完整事件采集仍缺同次运行的证据 | 同一次邮件读取、摘要写入和调用提议携带真实 ID，核对标签 revision、图 JSON、恢复旧新版本映射和最终评分 |
| 实验设计待落地 | SQLite 账本和受控 runner 已入库。FTS5 检索、40 个生命周期用例、B0–B4 批量运行与 96/288 个 GUI 子集均属于新方案的计划项。无跨会话记忆仍可能受到当轮输入影响 | 先冻结一个正常/攻击任务对，在同一任务与权限下比较 B0 和 B3；另从同一污染快照比较恢复方式。记录分母、正常任务得分、攻击得分与重启后复发 |

## 11 月 9 日机制检查记录

在干净的主线工作树上使用 Windows Python 3.13，从该次检出的 `src` 加载代码。测试设置了 `ARIADNE_TMA_CHECKOUT` 和 `ARIADNE_SRR_CHECKOUT`，分别指向固定版本的 mem-inv-bench 和 selective-revocation-replay。安装条件见 [README](README.md#quick-start)。

| 命令 | 观测结果 |
|---|---|
| `python -m unittest discover -s tests -q` | 147 项全部通过，0 跳过，耗时 65.312 秒 |
| `python scripts/evaluate_labels.py --cases 8` | 8 次邮件夹具输入均保留外部来源、无独立授权。合成屏幕摘要保留不可信来源，重启后 28 条记录一致 |
| `python -m cua_guard.recovery.demo` | 给定污染根后，3 个受影响版本完成修复，旧版本可见数为 0。正常版本保留，休眠副本重建，原任务续行一次。模型与外部工具调用均为 0 |

恢复演示通过 JSON 适配器读取恢复库快照，并使用合成 writer 提供内容。真实 runner 对每次读写的采集覆盖率、污染根识别准确率和官方任务得分仍待测量。

## 已遇到的问题

| 问题与表现 | 当前处理 | 已有证据 |
|---|---|---|
| 一个 writer 可以从同一旧记忆产生多个新版本。上游标量映射只留下最后一个 ID，下游会缺输入 | 从原始重放事件读取全部输出，核对父节点，再交给后续 writer | [一对多回归](tests/test_reused_recovery.py) |
| 标签提交、恢复库发布、宿主安装和工作流检查点可能在不同时间完成。进程中断会留下部分完成的状态 | 标签桥接层重放未完成投影。恢复协调器按已持久化的阶段继续，待两份标签和上下文确认后解除屏障 | [桥接回归](tests/test_label_bridge.py)与[进程终止用例](tests/recovery_process_fixture.py) |
| 图记录引用缺失的记忆时，无法可靠计算修复范围。只按执行顺序传播又会误伤独立步骤 | 记录缺失引用并拒绝不完整图，查询时排除只有 chain 的边 | [图校验与查询用例](tests/test_provenance_graph.py) |

## 潜在问题与下一轮验收

| 负责人 | 风险 | 可检查的交付 |
|---|---|---|
| 环境与 benchmark | GUI 环境启动失败、模型超时或任务异常会改变有效样本分母 | 固定任务、模型配置和评分器。正常与攻击样本分别保存原始得分、失败原因、尝试次数和运行成本 |
| 标签与执行门 | 同一账户控制两份标签文件时，两者一致仍可能同时被修改；绕过执行包装的动作也缺少记录 | 明确文件与宿主的信任边界。抽取一次真实拟执行动作，核对授权、调用 ID、判定及实际效果 |
| 溯源图 | 宿主可能完全漏报一次读取，此时仅靠图内的端点检查无法发现遗漏 | 对照原始 runner 轨迹核对读写 ID、writer 输入、产物及 revision，比较完整图的受影响记忆与恢复投影的目标集合 |
| 定向恢复与续作 | 测试夹具能提供已知污染根和干净内容，真实模型则可能漏检或误删正常事实。已发出的外部动作也可能处于未知状态 | 在相同污染快照上比较局部修复与清空状态，记录漏修、误隔离、正常任务得分及重启后复发。保留未知效果的暂停和核查记录 |

首个联调样例可选同一封含注入指令的邮件和对应正常邮件。四人共用任务 ID，依次保存标签 revision、宿主 trace、图快照、旧新版本映射、执行前复检及 scorer 输出。完成这条链后再扩展样本，并按组内安排进入 ChatGPT 接入阶段。
