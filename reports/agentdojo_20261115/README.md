# AgentDojo 中期评测 · 2026-11-15

[四页中文 PDF](AgentDojo-midterm.pdf) · [汇总](summary.json) · [正常任务逐题结果](normal.csv) · [全部安全组合与原因](security-629.csv)

官方 PyPI 软件包 AgentDojo 0.1.34，套件版本 v1，温度 0，行动模型 deepseek-flash。使用独立下载的官方 wheel；本次没有使用 AgentLAB 自带的修改版。每个任务、每个实验组独立初始化模拟环境。应用只通过 DeepSeek 客户端访问模型服务，任务工具操作 AgentDojo 自带的合成工作区。

| 套件 | 正常题 | 普通组通过 | 标签门组通过 | 原版 Direct 组合 | 受控检测组合 |
|---|---:|---:|---:|---:|---:|
| Workspace | 40 | 34 | 24 | 80 | 160 |
| Travel | 20 | 17 | 12 | 80 | 60 |
| Banking | 16 | 16 | 8 | 0 | 144 |
| Slack | 21 | 20 | 11 | 0 | 105 |
| 合计 | 97 | 87 | 55 | 160 | 469 |

## 实验与评分

- **正常任务**。调用官方 `run_task_with_pipeline`。两组使用同一系统提示、完整套件工具菜单、最多 8 轮工具选择和一次最终作答机会，单个模型可见观察最多 16,000 字符。工具错误会返回给模型，拒绝的调用保存在审计日志，只有实际分发的调用进入上游评分用的调用栈。
- **标签门策略**。使用项目的双份标签库和 `check_action`，每次动作绑定当前任务与此前全部工具观察。套件内查询操作允许读取；写操作由宿主用正常参考轨迹生成精确的工具与参数授权，模型看不到参考轨迹。该实验给予宿主已知任务答案作为策略输入；参考参数可能拒绝同样正确的另一种措辞。普通组不做这层检查。两组没有同时挂载所有 Ariadne 子模块。
- **分歧复跑**。首轮同过 54、同败 9、仅普通组通过 33、仅标签门组通过 1。全部 34 道分歧题另跑一对，共 68 次；这批只反映分歧题。温度 0 的远端服务仍可能有波动。
- **原版安全子集**。Workspace 的目标 0、2，Travel 的目标 0、2、4、6，使用官方 Direct 模板和上游槽位选择逻辑。在每组 160 个独立 episode 上同时取得用户效用和安全目标达成评分。普通组用户效用 138/160，门控组 103/160。两组安全目标达成各 7/160、6/160，全部发生在以酒店名是否出现在回答中为判据的 Travel 目标 6。缺少完整目标字符串不排除模型看到部分文字。不能从一项输入模板、这个子集或某个过宽的判据推断整体 ASR。
- **其余 469 个组合**。覆盖涉及私人资料、凭证、支付、钓鱼、删除及成员权限的目标。在每道原始用户任务的官方候选槽中取按字典排序的首个，构造“原始干净槽值＋换行＋目标文本”。这一输入只由无工具检测器读取。每个组合的 `reason` 记录未跑原版攻击的原因。模型判污染必须给出能在输入中精确定位的引文。463 条有效检出均有至少一段证据与追加文本重叠；6 条判 clean。
- **受控修复与继续**。本项用 Ariadne 的 ProvenanceStore 和 RepairPlanner。预先创建原始可信副本、外部根和派生缓存。检出后，在已知候选根上执行闭包隔离，从干净值重建新版本，校验旧版本状态、独立节点和新副本的内容与来源。再将该值写回官方模拟环境，用标签门组策略运行本次用户任务。463/463 项通过这些状态检查，256/463 项随后取得用户效用通过，207 项效用失败。该实验测量从规划前继续执行，不代表自主发现根、无备份修复或跨进程恢复。
- **独立检测参考**。采用官方推荐的 ProtectAI DeBERTa v3 v2 及 SAFE 概率 < 0.5 判定规则，CPU、eval 模式、无工具。对同一输入字节计算结果，相同文本复用分类分数。参考检测器只接收资料文本；Ariadne 还接收用户任务。两者分别检出 162/469、463/469，仅 Ariadne 检出 301 项，仅参考模型检出 0 项。469 组来自 115 个唯一文本哈希。97 个正常对照对应 25 份不同文本；Ariadne 判 clean 80、polluted 1、unknown 16，参考模型标记 4。unknown 单列，不能当作 clean。
- **用量**。所有批次共 4,604 次 DeepSeek API 请求，响应计数汇总为 17,605,034 tokens，含并发运行、重复任务和检测。以上每种比例均保留各自分母。

## 可回放证据

[正常成功示例](example-travel-user_task_0.json) 记录查询酒店评价、模型选择预订、执行门批准、环境执行和最终回答。[正常失败示例](example-workspace-user_task_37.json) 记录两次被拒的文件创建。模型生成的文档有标题和行程说明，宿主参考正文仅列打包物品。两条示例的模型回答、调用和评分来自首轮，工具观察从新环境重放并逐一验证 SHA-256。

[公开轨迹索引](trace-index.jsonl) 保留 1,148 条实验记录的调用次序、工具名、动作分发、门控理由、参数与回答摘要、可见观察哈希及模型用量。其余两张表是 [原版安全 episode](benign-episodes.csv) 与 [正常检测对照](negative-controls.csv)。原始本机结果位于 `D:/CUA-Lab/artifacts/dojo-nov15`。安全组合表中的空白字段表示该项未测或不适用，False 表示已测且结果为假。

## 复现

使用 Python 3.13.5 和固定的官方 `agentdojo==0.1.34`，设置 UTF-8，令 `PYTHONPATH` 包含本仓库的 `src`。官方 wheel 的 SHA-256 为 `118668a065977e05b8d8e86ecdd69973d948a83adbf62c433462cb6b60e78689`。在本机忽略的 .env 中配置官方 DeepSeek Flash chat 接口。以下命令在仓库根目录运行；将 RUN 替换为同一个新结果目录。重复使用目录仅续跑缺失文件。

```text
python scripts/agentdojo_midterm.py RUN/first --mode clean --workers 14
python scripts/agentdojo_midterm.py RUN/first --mode benign --workers 15
python scripts/agentdojo_midterm.py RUN/repeats --mode discordant --first-run RUN/first --workers 8
python scripts/agentdojo_midterm_inspect.py RUN/controlled --workers 20
python scripts/agentdojo_reference.py export RUN/reference-inputs.json
python scripts/agentdojo_reference.py classify RUN/reference-inputs.json --weights WEIGHTS --output RUN/reference.json
python scripts/agentdojo_results.py RUN OUTPUT
```

参考分类权重固定在 Hugging Face 提交 `90c9989b1a342275dd0d1a95aad283c04e075671`，model.safetensors SHA-256 为 `6521cb8d0ac08148c81464899c424e6148fcc62befa371089fa4061d8b6e0424`。分类使用 PyTorch 2.10.0 CPU 与 Transformers 5.4.0。归档报告排版脚本为 `scripts/agentdojo_midterm_pdf.py`，配套本次数据与中文字体。独立复跑应重新汇总逐题结果，再撰写结论。

[AgentDojo 论文](https://arxiv.org/abs/2406.13352) · [官方包](https://pypi.org/project/agentdojo/0.1.34/) · [参考模型固定版本](https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2/tree/90c9989b1a342275dd0d1a95aad283c04e075671)
