# Ariadne 项目进展 · 2026-11-14

## 中期答辩验收清单

| 工作 | 现有成果 | 答辩前待补 |
|---|---|---|
| 代码与合并 | 双份 SQLite 标签库、动作执行门、来源与派生图、LangGraph 恢复检查点及定向修复已有实现。AgentLAB 与 RTC 适配入口已纳入同一代码库 | 用同一次正常任务的观测、标签、图、修复及最终评分验证跨组件接口 |
| Benchmark | 团队 Ubuntu VM 完成三平台各 288 份配置预检，所有 ID 通过。Windows 宿主端另有 RTC Ubuntu 来宾和本机 Reddit 服务 | 两台环境分别核对依赖、用户权限、GUI、快照、网页初始状态和 runner 的模型接口 |
| 检测与数据 | DeepSeek 检测 864 个条目，429 份不同文本。有效检出 Reddit 288/288、OwnCloud 284/288、Rocket.Chat 288/288。另有 18 个正常输入均判 clean，其中 12 个为人工对照 | 复核 OwnCloud 四项引文定位失败，补充真实正常文档和聊天输入；Rocket.Chat 检测输入为模拟联系人提示 |
| 任务效用 | DeepSeek 在 AgentDojo 12 个只读任务上运行两组，普通与标签门均为 6/12。RTC Reddit 三个正常目标各两种表述已由模型读宿主 DOM、来宾执行限定动作并评分 | RTC 另两个平台共 6 个正常目标、12 种表述尚无真实任务轨迹；记录逐题异常、耗时与用量 |
| 桌面与产品接入 | DeepSeek API、来宾桌面服务和论坛链路分别有实测证据；已有可逆 GUI 评分对照 | 官方 runner 完整对抗 episode 为 0/864。尚无端到端 ASR、端到端防御率或桌面 ChatGPT 接入验收 |
| 展示材料 | 已有提案 PPT、架构资料、预检分布图、检测图与效用图 | 制作中期 PPT，标明各图的实验单位、分母及覆盖范围，补示例轨迹和演示彩排 |

[三平台预检报告](中期汇报报告.md) · [全量检测原始记录](docs/benchmarks/2026-11-13/rtc-fixture-detection.jsonl) · [效用数据](docs/benchmarks/2026-11-13/deepseek-workspace-scores.json) · [本机正常任务验收](docs/benchmarks/2026-11-13/normal-deployment.md)

同伴 VM 的记录显示，官方入口在导入 easyocr 时退出。20 GB 根盘当时剩余约 6.3 GB，CUDA 依赖安装已取消。SSH 会话缺少 DISPLAY；docker 服务已启动且已添加用户组，当前会话访问 socket 仍待复验。该 VM 未找到独立目标 .vmx、vmrun 或 /dev/kvm，亦无已初始化网页容器。本机已有独立 RTC 来宾、论坛和可用 DeepSeek 客户端；两套环境的快照、图形会话和 provider 兼容性须各自验收。[同伴执行记录](reports/full_benchmark_attempt_20261113.md)

## 11 月 10 日主线核查

11 月 10 日核查基于 `main` 的 `540e831`。相对上次文档提交 `6cc9885`，远程新增了[数据与实验方案](数据推荐.md)，运行代码和测试没有变更。标签、图和恢复代码已经合入同一仓库。当前可以复现标签持久化、依赖图投影和定向恢复。下一个里程碑是让同一次 benchmark 任务产生可追踪的观测、图、修复记录与官方得分。

## 11 月 13 日本地扩测

在同一组 12 道 AgentDojo 题上完成 48 次评分。普通 / 标签门组：Qwen3-1.7B 为 6/12、7/12；Qwen2.5-7B 为 5/12、5/12。一个恢复快照使用两个模型复评，均仅定向修复通过。RTC 官方 Ubuntu 已在本机跑通桌面操作与正常评分器的 0 → 1 → 0 对照，完整视觉模型 episode 仍为 0。[逐题结果、RTC 证据和待验收项](docs/benchmarks/2026-11-13/README.md)

## 11 月 12 日真实模型试验

11 月 12 日使用本地 Qwen 模型完成首轮小样本验收。AgentDojo 日历任务两组各 3/4 通过上游评分。一个固定过期快照的对照中，定向修复保留独立记录并通过地点判分。AgentLAB Email 自主读取 0/2，宿主经执行门先读取时 2/2。[逐任务结果、原始轨迹与复现命令](docs/benchmarks/2026-11-12/README.md)

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
