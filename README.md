# Ariadne

Persistent provenance and targeted repair for computer-use agents.

阿里阿德涅之线：沿来源与版本依赖，定位污染并恢复任务。插件及仓库正式名称为 **Ariadne**，Python 分发名为 `ariadne-cua`；内部导入名保留 `cua_guard`。[GitHub 仓库](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne)设为 Private，供团队协作。

根据 Proposal_Revised 的方向，研究跨会话来源记录与污染状态恢复。当前实现是 **Python 标准库内核 + 确定性机制演示**，不是已经装载到 RedTeamCUA/AgentLAB 的防护产品，没有真实模型 ASR 结果。

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
| `adapters.py` | 待实现的宿主适配接口；不声称已集成真实 benchmark |
| `demo.py` | 会话重启、污染派生复制、阻断、局部隔离和重建演示 |

## Trust boundary and limits

- 数据库与 policy 由可信宿主控制。当前库没有防止同账户进程篡改 SQLite 的能力；同目录双份记录不等于安全隔离。
- 来源表示渠道，不判断语义善恶。外部资料在独立授权的动作范围内仍可作为数据使用。
- 图记录已捕获输入依赖，不能称为已证明的 causal graph。所有父节点依赖由宿主采集，不能信任模型报告。
- 修复根由外部 detector／实验 oracle 给出。当前 `rebuild` 接收已验证内容，未实现自动语义净化。
- 隔离以节点为单位，混合摘要中的正常信息也可能暂时不可用。内容级精确修复尚未实现。
- 当前仅支持单进程研究流程；真实文件 TOCTOU、GUI 语义识别、外部副作用补偿、缓存刷新、进程隔离均需适配器实现。
- `dispatch` 在检查后记录调用再执行，崩溃可能导致调用未执行但被标记使用。不要自动重试不确定的外部动作。
- 不提供通用 shell/HTTP 代理，不操作真实账号、文件上传或第三方目标。

## Research and collaboration

项目调研的权威记录在工作区 `项目调研/2026-10-14_启动调研/`。本轮调研副本已于 2026-10-14 同步至仓库 `docs/research/`。

见 `docs/architecture.md`、`docs/roadmap.md` 与 `CONTRIBUTING.md`。首轮 [GitHub Actions](https://github.com/Computer-Security-PP-TR-for-CUA-ast-LHA/Ariadne/actions/runs/38571880362) 已通过：Windows/Ubuntu × Python 3.11/3.13，每组 16 项测试及 demo；对应代码提交 `1c17e8e`。

许可证待四位成员共同确定；当前没有授予开源再分发许可。引用外部代码时需单独遵守其许可证。
