# 数据集、数据库与 Baseline 推荐

> **2026-11-20 阶段更新**：中期答辩已完成。以下 11 月初的选型与六周计划保留为历史背景，不代表当前完成状态。当前三条并行线见 [最终答辩路线](../roadmap.md)；AgentDojo 已从备选工具评测进入当前诊断主线，采用 [诊断与复测计划](agentdojo-diagnosis-plan.md) 中的版本隔离、配对对照和恢复指标。RedTeamCUA 与桌面接入继续并行，不能互相替代验收。

> 项目：Ariadne —— Persistent provenance and targeted repair for computer-use agents  
> 目标：选择环境配置简单、容易复现、能支撑“持久记忆污染—后续动作—定向修复”实验的数据库、评测数据集和 Agent harness。  
> 方案日期：2026-11-05。主线核查：2026-11-10，配置预检和运行记录见 [研发进度历史](../progress-history.md)。

## 1. 结论摘要

建议采用“两层实验”路线：

1. **本地机制实验**：SQLite + FTS5，运行 Write–Execute–Forget 生命周期，快速比较不同 memory backend 和执行门。
2. **真实 CUA 实验**：以 RedTeamCUA/RTC-Bench 为主数据集，先跑分层子集，再扩展到完整 864 cases。

推荐的 baseline 矩阵：

| 编号 | 配置 | 目的 |
|---|---|---|
| B0 | Vanilla/Plain Memory | 无 provenance、无执行门，测量原始污染风险 |
| B1 | Content Filter | 测试关键词/Prompt Guard 类写入前过滤是否足够 |
| B2 | Provenance-Only | 保存来源标签但不强制执行，验证“记录来源”与“阻止越权”的差距 |
| B3 | Ariadne/PPMF Gate | provenance + support binding + risk-authority gate，作为主方法 |
| B4 | No-Memory Oracle | 关闭跨会话记忆，衡量记忆对攻击与正常任务的影响 |

## 2. 评测数据集选择

### 2.1 首选：RedTeamCUA / RTC-Bench

这是当前最适合项目主实验的数据集。现有记录已经完成 Reddit、OwnCloud、Rocket.Chat 三个平台的配置和 metadata 预检，共 **864/864 cases 通过**。需要明确：该结果是 workload/字段校验，不是模型驱动的攻击成功率。

推荐执行顺序：

- 第一阶段：每个平台抽取 32 个分层 case，共 96 个 case，用于联调；
- 第二阶段：每个平台抽取 96 个 case，共 288 个 case，用于 baseline 矩阵；
- 最后：资源和服务稳定后运行完整 864 cases。

当前完整运行的风险是 Docker Hub 镜像网络、VMware nested virtualization、`/dev/kvm` 和 API provider 配置。因此不应把完整 RTC-Bench 作为唯一开发路径。

仓库和主页：

- [RedTeamCUA](https://github.com/OSU-NLP-Group/RedTeamCUA)
- [RedTeamCUA project page](https://osu-nlp-group.github.io/RedTeamCUA/)
- [本项目 Ariadne](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne)

### 2.2 本地备用：自建 MemSecBench-style 数据集

目录中的 MemSecBench 论文适合作为协议参考，但当前项目没有确认其公开代码和原始数据已经可直接使用。因此建议实现一个小型、可审计的扩展集，而不是声称复现原论文：

- 40 个 case；
- 每个 case 包含 `Write`、`Execute`、`Forget` 三阶段；
- 每个 case 同时定义 malicious semantics 和必须保留的 benign memory；
- 用 SQLite 保存状态快照、版本、来源和修复结果；
- 通过规则和 artifact state 判断攻击是否成功。

这套数据可以在没有 Docker、VMware 和浏览器服务时完成主要机制实验，之后再迁移到 RTC-Bench。

### 2.3 不建议作为第一主数据集

| 数据集 | 主要问题 |
|---|---|
| WebArena | 真实度高，但多个 Docker 服务初始化成本较高 |
| OSWorld | 依赖完整桌面和虚拟机，适合后期 GUI 验证 |
| SecureWebArena | 安全相关性高，但部署和视觉评测成本更大 |
| 直接使用 MemSecBench 原始数据 | 当前未确认代码/数据的公开可复现入口 |

相关仓库：

- [WebArena](https://github.com/web-arena-x/webarena)
- [OSWorld](https://github.com/xlang-ai/OSWorld)
- [BrowserGym](https://github.com/ServiceNow/BrowserGym)
- [AgentDojo](https://github.com/ethz-spylab/agentdojo)
- [AgentLab](https://github.com/ServiceNow/AgentLab)

## 3. 数据库和 Memory Backend

### 3.1 首选：SQLite + FTS5

SQLite 最适合当前项目，原因是：

- Python 自带 `sqlite3`，不需要独立服务；
- 一个 `.db` 文件即可复制、归档和复现实验；
- 支持事务和 checkpoint，适合 Write–Execute–Forget；
- FTS5 足以支持第一版关键词检索；
- 可以完整保存 provenance、版本和审计事件；
- 与 Ariadne 当前已有的 SQLite 账本、版本和执行门直接兼容。

建议的核心字段：

```text
memory_id
case_id
content
source                 # user / web / email / tool / model / unknown
trust_level            # unknown / external / trusted_tool / user_history / confirmed
transformation         # 摘要、改写、合并等变换记录
parent_ids             # 来源节点或输入版本
risk_labels
external_derived
active
created_at
```

第一版不要引入 Qdrant、Milvus、Pinecone 或 Redis。只有当关键词检索成为明显瓶颈时，再增加 FAISS 或一个可选向量后端；向量检索不应改变 provenance 和执行门的权威来源。

### 3.2 可选对照后端

如果需要比较 memory backend，可以增加：

1. **Plain JSON/File Memory**：只有文本，没有可信 metadata；作为易受攻击的对照。
2. **SQLite Structured Memory**：有 provenance，但暂时不强制风险策略；对应 B2。
3. **SQLite + Ariadne Gate**：有 provenance、参数级 support binding 和执行前 gate；对应 B3。
4. **Mem0**：可作为外部 memory service 对照，但建议放到扩展实验，不作为第一版依赖。

仓库：

- [Mem0](https://github.com/mem0ai/mem0)
- [LangGraph](https://github.com/langchain-ai/langgraph)

## 4. Vanilla Agent 的替换方案

### 4.1 推荐：DeepSeek harness（近期最容易落地）

Ariadne 当前已经有 DeepSeek HTTP 客户端、tools/JSON/vision 支持，以及 AgentLab 和 RedTeamCUA 的执行包装。因此短期建议把 B0 中的“Vanilla Agent”具体化为：

```text
DeepSeek model
  -> existing bounded tool loop
  -> trusted harness observation capture
  -> plain cross-session memory
  -> host tool within the shared benchmark permissions
```

B0 和 B3 使用相同的宿主权限、输入与工具。观测日志由宿主旁路采集；B3 另外启用 Ariadne 标签检查和执行门。B1 表示写入过滤，恢复实验中的 Gate-only 表示仅启用执行门。

建议固定：

- `temperature=0`；
- 固定 model name、system prompt、tool schema；
- 每次运行限制最大模型调用数和输出 token；
- 保存 model-visible inputs、tool calls、memory IDs、gate decision 和最终 artifact；
- API key 只放环境变量，不写入数据库、日志和 Git。

官方入口：

- [DeepSeek API 文档](https://api-docs.deepseek.com/)
- [Ariadne DeepSeek 适配代码](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/tree/main/src/cua_guard)

### 4.2 可选：Codex-compatible harness

“Codex harness”应理解为一个 **OpenAI-compatible、支持工具调用的受控 harness**，而不是假设存在可直接嵌入的 Codex 内部运行时。实现上可以复用同一个 `AgentHarness` 接口，仅替换模型 transport：

```text
AgentHarness
  - observe() -> trusted observation envelope
  - plan() -> bounded tool call
  - dispatch() -> Ariadne gate then host tool
  - record() -> trace + provenance + effect ledger
```

Codex-compatible 版本至少必须保留以下宿主控制点：

- 模型不能自行写入 trust/provenance 字段；
- 所有受保护动作必须经过 `dispatch()`；
- tool result 和截图必须由宿主记录真实来源；
- tool call 参数必须和 memory support 做绑定；
- gate 拒绝时不能只返回文本提示后继续执行。

可参考的官方/开源接口：

- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [OpenAI Agents SDK for Python](https://github.com/openai/openai-agents-python)

实现优先级上，DeepSeek harness 应先完成；Codex-compatible harness 作为第二个模型 backend，用来测试 Ariadne 是否依赖某一个模型厂商。

### 4.3 两种 harness 的公平比较

比较 DeepSeek 和 Codex-compatible harness 时，必须固定：

- 相同 case、初始 memory snapshot 和攻击 payload；
- 相同 tool schema 和 allowed operations；
- 相同 provenance/gate policy；
- 相同最大轮数和 token/call budget；
- 相同成功判定和 artifact 检查。

不要把模型能力差异、工具权限差异和防御策略差异混在一个实验中。

## 5. 主要指标

至少报告以下指标：

| 指标 | 含义 |
|---|---|
| Write Persistence Rate | 恶意语义是否进入持久 memory |
| Execute ASR | 后续任务是否检索并触发恶意行为 |
| Unauthorized High-Risk Action Rate | 未授权高风险动作比例，作为主要安全指标 |
| Benign Task Success Rate | 正常任务完成率 |
| Selective Repair Success Rate | 删除恶意语义且保留 benign memory 的比例 |
| False Block Rate | 合法任务被错误阻断的比例 |
| Cost/Latency | token、模型调用次数和运行时间 |

“写入成功”不能直接等同于“攻击成功”。必须同时检查后续 memory support、tool call 和外部 artifact state。

## 6. 六周实验进展计划

### 第 1 周：冻结接口和最小数据集

- 固定 Python、依赖版本和实验配置文件；
- 确认 SQLite schema、memory version、provenance envelope 和 effect ledger；
- 定义 40 个本地 Write–Execute–Forget cases；
- 固定统一的 `AgentHarness` 接口；
- 验收：B0/B4 可在无真实模型模式下跑通，结果 JSON schema 稳定。

### 第 2 周：DeepSeek harness 与四组 baseline

- 接入现有 DeepSeek client；
- 完成 B0 Plain Memory、B1 Content Filter、B2 Provenance-Only、B3 Ariadne Gate；
- 固定 temperature、调用上限、超时和日志脱敏；
- 验收：至少 10 个 case 在四组 baseline 下端到端完成，能区分 Write、Execute、Gate、Repair 结果。

### 第 3 周：离线全量机制实验

- 运行 40 cases × 4 baselines；
- 增加 3 个随机种子或重复运行，检查结果稳定性；
- 统计 ASR、未授权高风险动作、正常任务成功率和修复成功率；
- 检查混合摘要、来源丢失、过期规则和派生副本；
- 验收：生成第一版 CSV/JSON 结果和失败案例清单。

### 第 4 周：RTC-Bench 小规模接入

- 先运行 Reddit、OwnCloud、Rocket.Chat 各 32 个分层 case；
- 处理 Docker 服务、浏览器/Xvfb、截图和 tool action 记录；
- 先使用 DeepSeek harness；
- 验收：96 个真实 CUA case 中，至少能稳定记录 observations、actions、memory IDs、gate decision 和最终状态。

### 第 5 周：Codex-compatible harness 与交叉比较

- 实现第二个 OpenAI-compatible model transport；
- 保持相同 harness、工具权限、case 和 gate policy；
- 比较 DeepSeek 与 Codex-compatible harness 的安全和效用指标；
- 对 10～20 个代表性 case 做逐轨迹人工审计；
- 验收：完成模型 backend 交叉实验，明确哪些差异来自模型、哪些来自 Ariadne。

### 第 6 周：扩展、复核与报告

- 视资源情况扩展到 288 或完整 864 RTC-Bench cases；
- 重跑关键结果，固定 commit、配置、模型名和时间戳；
- 完成消融实验：无 provenance、无 support binding、无 gate、无 repair；
- 整理表格、失败样例、限制和复现说明；
- 验收：形成可复现运行命令、结果目录、实验配置和报告草稿。

## 7. 推荐的最终实验组合

```text
数据集：RTC-Bench（先 96，再 288，最后视资源扩展到 864）
备用数据：40-case 本地 Write–Execute–Forget 集
数据库：SQLite + FTS5
主模型：DeepSeek harness
第二模型：Codex-compatible/OpenAI-compatible harness
Baseline：B0 Plain、B1 Filter、B2 Provenance-Only、B3 Ariadne Gate、B4 No-Memory
主要指标：Unauthorized High-Risk Action Rate + Benign Success + Selective Repair
```

这条路线与 Ariadne 当前代码最一致：SQLite、DeepSeek、AgentLab/RedTeamCUA 包装和执行门已经存在；需要新增的主要工作是统一 harness 接口、构造小型 lifecycle 数据集、完成真实 CUA 观测记录，以及把 Codex-compatible transport 接到同一套宿主控制边界。

## 8. 当前限制与复现声明

- 当前仓库已有的自动测试和 deterministic demo 不等于真实模型 ASR；
- RTC-Bench metadata 预检通过不等于完整 GUI benchmark 已通过；
- Codex-compatible harness 需要单独实现和验证，不能写成现成能力；
- 任何模型生成的 provenance、trust 或 confirmation 文本都不能直接获得宿主权限；
- 真实 API key、模型响应和个人数据不得提交 Git；
- 结果必须记录 commit、依赖锁定、模型配置、case 版本和运行环境。

