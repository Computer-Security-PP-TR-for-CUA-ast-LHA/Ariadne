# Ariadne

Persistent provenance and targeted repair for computer-use agents.

阿里阿德涅之线：沿来源与版本依赖，定位污染并恢复任务。插件及仓库正式名称为 **Ariadne**，Python 分发名为 `ariadne-cua`；内部导入名保留 `cua_guard`。[GitHub 仓库](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne)设为 Private，供团队协作。

根据 Proposal_Revised 的方向，研究跨会话来源记录与污染状态恢复。现有标准库内核、DeepSeek HTTP 客户端、AgentLAB 工具环境适配、RedTeamCUA GUI 执行包装，以及自动语义检测与修复闭环。**真实模型评测尚需本地 API key；没有可报告的真实模型 ASR 结果。** 本轮只实现 Proposal 内容，不加入 novelty 补强机制。具体范围、运行方法与待验收项见 [实施记录](docs/proposal-implementation.md)。

## Quick start

Windows PowerShell：

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m cua_guard.demo
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux（Python 3.11+）：

```bash
bash scripts/bootstrap.sh  # 已有 uv Python 3.13 时离线建 .venv-wsl
bash scripts/check.sh
```

Windows 脚本创建项目内 `.venv`，通过 `.pth` 引用源码，无需下载依赖或 API key。不更改系统 Python。通用开发安装可用 `python -m pip install -e .`，这会获取构建依赖，首次安装需要联网。

## Modules

| 模块 | 当前功能 |
|---|---|
| `store.py` | SQLite 版本节点、内容摘要、来源集合、派生边、审计事件、内联 envelope 校验 |
| `gate.py` | task/operation/resource/recipient 精确权限检查、版本状态检查、调用 ID 去重、宿主执行包装 |
| `repair.py` | 按调用找祖先候选；接受独立确认的污染根，隔离根及后代 |
| `model.py` | DeepSeek Flash JSON、tools、vision HTTP 调用；超时、调用次数与输出长度限制 |
| `semantic.py` | 有原文证据的检测、候选祖先定位、保守隔离、语义净化及双重复检 |
| `runtime.py` | 宿主拥有的上下文、持久化 checkpoint、恢复前复检、参数摘要绑定 |
| `agentlab.py` | 锁定版本的真实 EnvManager/Email 环境及有界工具循环 |
| `redteamcua.py` | 原始 run_single_example 协议适配、视觉感知、有限动作编译与执行包装 |
| `demo.py` | 会话重启、污染派生复制、阻断、局部隔离和重建演示 |

## Trust boundary and limits

- 数据库与 policy 由可信宿主控制。当前库没有防止同账户进程篡改 SQLite 的能力；同目录双份记录不等于安全隔离。
- 来源表示渠道，不判断语义善恶。外部资料在独立授权的动作范围内仍可作为数据使用。
- 图记录已捕获输入依赖，不能称为已证明的 causal graph。所有父节点依赖由宿主采集，不能信任模型报告。
- `semantic.py` 现在自动检测与净化；模型判断是可出错的证据，不是安全证明。相同模型承担检测与复检，可能有相关错误；需要后续真实实验测量。
- 隔离以节点为单位，混合摘要中的正常信息也可能暂时不可用。内容级精确修复尚未实现。
- 当前仅支持单进程研究流程。GUI 视觉感知可能漏读，屏幕也可能在观测后变化；尚不能保证任意桌面副作用安全。进程隔离和副作用补偿仍不具备。
- `dispatch` 在检查后记录调用再执行，崩溃可能导致调用未执行但被标记使用。不要自动重试不确定的外部动作。
- AgentLAB 示例仅允许读模拟邮件与联系人；GUI 仅在专用实验虚拟机中运行，禁止直接执行模型生成的 Python。

## Research and collaboration

项目调研的权威记录在工作区 `项目调研/2026-10-14_启动调研/`。本轮调研副本已于 2026-10-14 同步至仓库 `docs/research/`。

见 `docs/architecture.md`、`docs/roadmap.md` 与 `CONTRIBUTING.md`。首轮 [GitHub Actions](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/actions/runs/38571880362) 已通过：Windows/Ubuntu × Python 3.11/3.13，每组 16 项测试及 demo；对应代码提交 `1c17e8e`。

许可证待四位成员共同确定；当前没有授予开源再分发许可。引用外部代码时需单独遵守其许可证。
