# 前人成果复用审查、资源评估与接入记录

日期：2026-11-01。执行用户的新方向：先复用、集成和补强，再通过 benchmark 与桌面真实场景寻找新增贡献。当前分支 `feat/upstream-reuse-audit`。本记录不表示四阶段工作已经完成。

## 1. 本机资源与结论

本轮实际读取系统信息：Windows 11 Home；Intel i5-13500H，12 核/16 逻辑处理器；物理内存 15.73 GiB；Intel Iris Xe 核显，未检测到独立 NVIDIA GPU。核显报告值不能当成独立可用 VRAM。

采样时可用内存约 2.15 GiB；C: 剩余约 2.8 GiB；D: 剩余约 93.3 GiB。这是瞬时采样，不是稳定可用配额。

| 工作负载 | 判断 | 条件 |
|---|---|---|
| 来源标签、SQLite、图操作和确定性策略引擎 | 可以开展 | 单进程或轻量 sidecar；数据规模需实测 |
| 调用桌面 ChatGPT 的受支持工具接入 | 可以做小范围开发验证 | 模型推理不在本机运行；接口和上下文控制仍需验证 |
| 工具型 benchmark 和原始离线检查 | 可以开展 | 单任务运行，不额外启动本地大模型 |
| 完整 RedTeamCUA 的 VM＋多网页服务 | 当前资源紧张，未启动验收 | 先释放运行内存、核对镜像解压和服务实际占用，再小范围串行运行 |
| 本地中大型模型及大批量并行实验 | 不作为当前路线 | 无需为复用算法而部署模型权重 |

因此硬件不是“必须自写简化算法”的理由，但当前不能在只剩约 2 GiB 可用内存时盲目启动完整 GUI 栈。本轮新增源码、工具和报告均放到 `D:/CUA-Lab`，不自动清理 C: 或关闭用户程序。

另外实际读取了已下载官方 VM 的 ZIP 中央目录和 `Ubuntu.vmx`：压缩包 11.29 GiB，列出的解压文件合计 22.13 GiB；默认 4 个 vCPU、4096 MiB 内存。D: 可容纳这份基础 VM，但还要预留网页镜像、快照和运行数据；当前空闲内存低于 VM 默认配置，尚不能据此保证 VM 与网页服务同时稳定运行。

## 2. 固定上游及实际角色

完整 SHA、来源角色与观察到的许可证见 [锁文件](upstream-reuse-lock.json)。官方代码来自论文链接、作者/组织仓库交叉核对；同名不视为同一方法。

| 项目 | 实际发布物 | 本轮决定 |
|---|---|---|
| [OpenAPPA](https://github.com/archestra-ai/OpenAPPA) | MIT；Rust 引擎、运行时和集成协议；有 Windows 官方二进制 | 优先评估为标签/授权/受控恢复底座；已校验 v0.38.1 压缩包及可执行文件 |
| [TMA-NM / MEM-INV-Bench](https://github.com/yedidel/mem-inv-bench) | MIT；来源、授权、恢复与可重复证据代码 | 已直接接入原始 scope gate 与参数恢复；不把其 proxy baseline 冒充 CaMeL/MemLineage 原实现 |
| [AgentSentry](https://github.com/CyberGuardianAI/AgentSentry) | 论文 PDF 链接指向的运行代码；依赖 AgentDojo 与模型重执行 | 已取得源码；尚未找到许可证，未复制其算法到 Ariadne，也未宣称可分发集成完成 |
| [Fides](https://github.com/microsoft/fides) | MIT；配套教学 notebook | 作为 IFC 与策略参考；不能把它当成现成完整服务 |
| [CaMeL](https://github.com/google-research/camel-prompt-injection) | Apache-2.0；完整研究 artifact，含解释器和 AgentDojo 接入 | 保留原实现作为结构性对照；不要只取一个策略函数便称完整复现 |
| [MemLineage 第三方实现](https://github.com/amurlaniakea/memlineage) | AGPL-3.0-or-later；README 明确为独立实现 | 仅候选审查，不作为论文官方实现或默认引擎 |
| [AgentLAB](https://github.com/TanqiuJiang/AgentLAB) | MIT；长时程工具环境与攻击框架 | 已有源码与 Email adapter；完整攻击/评分待验证 |
| [RedTeamCUA](https://github.com/OSU-NLP-Group/RedTeamCUA) | Apache-2.0；混合 Web—OS benchmark | 已有源码；VM 和网页服务仍需完整部署验收 |

未从已检查 PDF/源码定位到 MemLineage 论文原始 artifact 和 ChronoMem 可复用仓库；这只是当前核查结果，不是断言它们不存在。后续继续查证，不偷偷回退为自写同名最小实现。

## 3. 当前真实复用的代码

`src/cua_guard/upstreams.py` 只负责固定版本验证和模块加载。`scripts/demo_reused_authority.py` 直接运行：

- 上游 `mem-inv-bench/code/scoped_authorization.py` 的 `Authority`、`sign` 和 `ScopedGate`；
- 上游 `mem-inv-bench/code/recovery_catalog.py` 的 `authorized_parameters()`。

示例中两个合成权威独立确认报告资源和接收者。恶意替换接收者被原始 gate 拒绝；原始恢复函数找回唯一获准的参数；再次授权通过。过期、撤销和未知操作也由原始代码拒绝。

这是对**原始授权及参数恢复代码的真实调用**，不是我们重新实现这些算法。其身份、密钥和确认记录是测试构造，不能当成真实组织授权，也不涉及语义污染净化、持久图修复或实际邮件发送。

旧 `store.py/gate.py/semantic.py` 暂留作机制原型与回归对照；当前没有把它们声称为最终统一防护内核。后续根据上游资格测试逐项替换或适配，避免一次性删掉可比基线。

## 4. 已执行的离线验证与未通过项

```powershell
.\.venv\Scripts\python.exe scripts\demo_reused_authority.py
.\.venv\Scripts\python.exe scripts\check_reuse.py
```

运行数据保存在 `D:/CUA-Lab/runs/reuse/offline-checks.json`，包含原始标准输出、退出码和时间。脚本不调用模型，不启动真实工具，也不使用付费 API。

已通过：TMA-NM 原始来源/授权检查、原始佐证检查；原始 gate 与参数恢复的 6 项集成条件；OpenAPPA 原始网页信任传播、三级信任、受限收件者、前置效果及禁止重复迁移场景。

**必须区分 OpenAPPA 的两种 replay：** 默认模式可以由 stand-in 回答 authority/sanitizer，只验证策略提供了哪些恢复路径；它不能证明真实净化成功。指定 `--live-remedies` 时可能调用真实外部模型/服务，本项目检查只允许已审查的内置 `redact-email`，禁止任意远程或命令绑定。

实测官方 `redact-before-sending` 示例在真实内置 redactor 模式返回 `cannot_run`，原因文本为 `the sanitizer's derivation was not usable`。另一个包含明确 email 的集成输入也尚未通过。错误输出完整保留，整体脚本返回非零；不改成 stand-in 后宣称修复通过，也不据此直接断言是论文算法缺陷。

当前源码和二进制对应同一发布 commit，初步排除了版本不一致；下一步用官方 body-only 控制用例区分工具参数结构、内置重写与运行平台影响，再决定适配补丁。内置 email redaction 即使通过，也不等于通用提示注入语义检测。

## 5. 桌面 ChatGPT 的适配边界

用户已选择先用桌面 ChatGPT，API 付费实验暂不启动。

官方 [hooks 文档](https://learn.chatgpt.com/docs/hooks) 支持本地运行时对部分 MCP/本地工具做 PreToolUse/PostToolUse；文档也明确某些路径不覆盖，回调异常或超时可能不阻断工具，cloud-orchestrated Work 与本地运行时条件不同。

因此，桌面接入先做**接口资格测试**：目标 CUA 工具的实际名称和粒度；调用前拒绝；返回结果进入模型前的拦截；异常/超时；绕过路径；重启后持久状态。完整动作边界应由被包装的执行器强制约束，不能单凭 skill 提示或 hook 安装成功宣称安全。

AgentSentry 需要受控上下文快照和反事实重执行。桌面账户可用不等于插件自动拥有这些接口；在找到受支持接口前，不用模拟点击 ChatGPT 界面去伪造推理 API，不宣称已接入完整 AgentSentry。

## 6. 两个原始设想怎样验证

“一式两份标签库”先比较内联标签、宿主账本、双份三组，控制丢失、篡改、版本漂移及存储开销。只有第二份处于可验证的独立信任/恢复边界，并带来实际收益，才有必要继续主张。

“基于溯源图的精确修复”先与原始 upstream 修复、只删根、全局回滚和清空状态比较；同时测正常信息可用、任务续行、复发、误隔离和缺边。内容级精确性和因果定位不能由节点可达性自动推出。

以上均为待验证假设。集成、桌面适配和补丁先建立可重复证据，再讨论是否具有前人尚未覆盖的贡献。
