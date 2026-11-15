# Ariadne

Ariadne 研究计算机使用代理的持久记忆安全。宿主在双份 SQLite 标签库中记录来源与版本，按依赖图隔离或修复受污染记录，再从活动会话继续执行用户任务。

## 中期实验与证据

| 实验 | 运行范围与主要结果 |
|---|---|
| [AgentDojo 全量评测](reports/agentdojo_20261115/README.md) | 97 道正常题两组实跑，普通组 87/97、精确授权门控组 55/97。160 个安全组合取得双组官方评分；另 469 个做受控检测，463 个修复后继续，256 个最终通过效用评分。 |
| [跨会话发布](reports/release_memory_20261115/README.md) | 四组、每组三个进程。仅门控组在重启后仍有污染记录，完整修复组替换了受影响版本。模型首次均选择本地打包。 |
| [授权与摘要压缩](reports/granted_memory_20261115/README.md) | 新版邮件执行门在直接读取及两次七天运行中均通过四格授权／来源对照。直接组完成修复并打包，两次七天运行均在修复候选验证后进入人工复核。 |
| [RedTeamCUA 实际运行进展](reports/codex_owncloud_benchmark_progress_20261115.md) | 三平台配置预检覆盖 864 项。OwnCloud 已取得真实 GUI 轨迹，尚无完整对抗 episode 官方得分。 |

[组件设计](docs/design.md) · [架构](docs/architecture.md) · [研发进度历史](docs/progress-history.md) · [实验设计与数据选择](docs/research/evaluation-plan.md) · [三平台预检数据](reports/midterm_20261113/README.md)

## Quick start

以下是已入库的机制原型测试和演示入口。演示不调用真实模型，不代表完整 benchmark 或桌面接入已完成。

在仓库根目录使用 Python 3.11+ 的虚拟环境运行以下命令。运行全部上游用例还需设置 `ARIADNE_SRR_CHECKOUT` 和 `ARIADNE_TMA_CHECKOUT`，见 [复现条件](docs/recovery/reuse-audit.md)。

```sh
python -m pip install -c requirements/recovery-tested.txt -e ".[srr]"
python -m unittest discover -s tests -q
python -m cua_guard.demo
```

## Modules

| 模块 | 当前功能 |
|---|---|
| `store.py` | SQLite 版本节点、内容摘要、来源集合、派生边、审计事件、内联 envelope 校验 |
| `gate.py` | task/operation/resource/recipient 精确权限检查、版本状态检查、调用 ID 去重、宿主执行包装 |
| `repair.py` | 按调用找祖先候选；接受独立确认的污染根，隔离根及后代 |
| `model.py` | DeepSeek Flash JSON、tools、vision HTTP 调用；超时、调用次数与输出长度限制 |
| `semantic.py` | 有原文证据的检测、候选祖先定位、保守隔离、语义净化及双重复检 |
| `runtime.py` | 宿主拥有的上下文、持久化 checkpoint、恢复前复检、参数摘要绑定 |
| `label_store.py` / `label_bridge.py` / `label_runtime.py` | 双份权威标签与版本、恢复投影及执行前检查；新 benchmark 入口使用此链路 |
| `agentlab.py` | 锁定版本的真实 EnvManager/Email 环境及有界工具循环 |
| `redteamcua.py` | 原始 run_single_example 协议适配、视觉感知、有限动作编译与执行包装 |
| `demo.py` | 会话重启、污染派生复制、阻断、局部隔离和重建演示 |

## 运行边界

- 双份标签由宿主管理。模型摘要可丢弃内联元数据，宿主仍需保存摘要与输入版本的父边。镜像缺行或两份记录不一致时读取失败。本地双库共享宿主的系统权限。
- 标签记录来源与完整性。双库执行门要求邮件外发及标记为高风险的动作同时具备有效确认与可信证据。其他动作可用 `require_trusted_evidence` 加严检查。语义检测另行判断内容是否污染。
- 修复协调器按已记录的依赖替换活动版本，并保留旧版本供审计。检测、修复与复核可使用同一模型，判断错误可能相关。若已提交的副作用涉及污染记录，恢复流程要求人工复核。
- 跨进程实验证据覆盖顺序重启和本地归档。GUI 实验的实际动作、可用评分及运行环境见上表各报告。

## Research and collaboration

仓库 `docs/research/` 保存此前的调研副本，`docs/architecture.md` 和 `docs/proposal-implementation.md` 记录已有原型及边界；早期路线若与本 README 不同，以本页的阶段状态为准。工作区另有 `项目调研/相关文献/` 和 `项目调研/文献综述/`，论文 PDF 与新增笔记尚未全部纳入本仓库。

团队流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。已有 [PR #1 的 CI](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/actions/runs/41052088365) 通过 Windows/Ubuntu × Python 3.11/3.13 四组检查，覆盖当时的 28 项测试与机制演示；这不代表完整安全效果评测通过。

`luowentao` 的通用实现替换已通过 [五项跨平台 CI](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/actions/runs/41451944312)，当时的干净安装包全量测试 98 项通过、无跳过。源码选型、默认 LangGraph/SRR 接入、复用边界和可复现记录见 [复用替换审查](docs/recovery/reuse-audit.md)。

许可证待四位成员共同确定；当前没有授予开源再分发许可。引用外部代码时需单独遵守其许可证。
