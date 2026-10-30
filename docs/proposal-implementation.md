# Proposal 范围实现与运行

日期：2026-10-15。名称 Ariadne，Private 仓库。只落实 Proposal_Revised 的持久标签、依赖图、污染定位、定向修复与实验适配；不实现额外 novelty 方案。

## 已实现的路径

1. 可信宿主登记用户任务与外部内容，SQLite 保存不可覆盖的版本和输入依赖。
2. 调用前生成绑定当前节点 ID/hash 的检查记录。检测器返回 clean/polluted/unknown；polluted 必须附原文子串证据。
3. 在调用祖先中筛选最早被检测为污染的节点，隔离其后代。该结果是检测器支持的候选污染根，不是已证明的语义因果根。
4. 分别净化受影响节点，检查事实保留和去除恶意指令，再运行一次污染检测。通过后创建新版本并记 supersede 审计；原版本保持隔离，外部来源不会升级为用户权限。
5. 重新构建模型上下文，不重放原污染工具历史。保留不受影响的独立节点；保存 checkpoint，跨进程恢复前重新检测。任何不确定或模型错误均暂停执行。
6. 工具调用由宿主 policy 授权，完整 JSON 参数摘要绑定至执行门。GUI 由结构化动作编译器产生有限 pyautogui 指令，并通过一次性动作凭据执行。

## 模型

用户选择 DeepSeek-V4.1-Flash。根据 [DeepSeek 官方 API](https://api-docs.deepseek.com/api/create-chat-completion/)，使用 `https://api.deepseek.com`、`deepseek-flash`，显式关闭 thinking，按请求启用 JSON、tools 或图片输入。

项目根 `.env` 已创建；只在本机设置 `MODEL_API_KEY`。该文件被 Git 忽略。每次进程默认最多 20 次请求、每次最多 2048 输出 token，没有隐式重试。**这只是请求上限，并非精确人民币费用上限**；实际费用依据供应商 usage 与账单。费用预算和密钥未就绪时不运行付费实验。

```powershell
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe -m cua_guard.agentlab --upstream D:\CUA-Lab\upstream\AgentLAB --fixture tests\fixtures\agentlab_email.json
```

AgentLAB 适配确实加载原始 EnvManager/BaseEnv。示例的 Email 是上游模拟工具环境，没有真实邮件发送；当前 host policy 只允许读邮件和联系人。没有复现 AgentLAB 全部攻击优化器、mem0 或所有环境，不能把此集成报告为完整 benchmark 复现。

## RedTeamCUA

上游固定版本见 `upstream-revisions.json`。完整上游 `uv.lock` 的 255 个依赖已安装在 `D:\CUA-Lab\envs\redteamcua`，Python 3.12.6。DesktopEnv 和 run_single_example 已实际导入成功。它们的首次导入会下载 NLTK punkt_tab 资源。

```powershell
$env:UV_CACHE_DIR='D:\CUA-Lab\cache\uv'
$env:UV_PROJECT_ENVIRONMENT='D:\CUA-Lab\envs\redteamcua'
uv sync --project D:\CUA-Lab\upstream\RedTeamCUA --frozen --no-dev --no-install-project
D:\CUA-Lab\envs\redteamcua\Scripts\python.exe -m cua_guard.redteamcua --help
```

正式运行需要准备好的独立 `.vmx`、`init_state` 快照、5000 端口 screenshot/accessibility/execute 服务，以及一个原始任务 JSON。`--example` 必须是实验维护者审核过的配置，因为上游 setup 本身可执行环境命令。运行器保留原始任务与攻击评价函数，不伪造评分。

```powershell
D:\CUA-Lab\envs\redteamcua\Scripts\python.exe -m cua_guard.redteamcua --upstream D:\CUA-Lab\upstream\RedTeamCUA --vm-path <专用VM.vmx> --example <已配置的任务.json> --max-steps 5
```

目前 GUI 动作支持 click/type/press/scroll/wait/done；type 仅支持可打印 ASCII。感知模型先转写截图与坐标，防护层净化文本后规划器再行动。图片本身的语义攻击、感知漏读、坐标失效与跨观测 TOCTOU 仍需实测，不能宣称视觉渠道已被可靠净化。

## 本地基础设施

- `D:\CUA-Lab\upstream`：两个官方源码 checkout，不加入本仓库。
- `D:\CUA-Lab\envs\redteamcua`：完整 Windows Python 环境。
- `D:\CUA-Lab\cache`：官方镜像与已验证的下载分段。
- `AriadneLab`：独立 WSL2 Ubuntu 22.04，磁盘在 `D:\CUA-Lab\wsl`，Docker 29.1.3；不会迁移个人 Ubuntu 或 Docker Desktop 容器。
- 官方 Ubuntu GUI 镜像 URL 来自 RedTeamCUA 的 VMware manager；下载完成后用 `scripts/prepare_vm.py` 检查 ZIP 路径、容量并解压到新目录，不覆盖已有 VM。

原 WebArena forum 镜像压缩体积约 45.45 GB；官方 Archive 镜像站报告不可用、Google Drive 配额超限。当前选择 [ServiceNow WebArena-Verified Reddit](https://servicenow.github.io/webarena-verified/v1.2.3/environments/reddit/) 做本地服务联调，固定 digest `sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46`，约 4.57 GB。**这是环境适配，数据库及攻击注入兼容性需验证，不能与原始 RedTeamCUA ASR 直接混报。**

由于 WSL 无法访问仅监听 Windows localhost 的代理，`pull_forum_oci.py` 在 Windows 下载并校验每层 SHA256，生成 OCI 包供专用 WSL 导入，不开放代理端口。

```powershell
.\.venv\Scripts\python.exe scripts/pull_forum_oci.py
wsl -d AriadneLab -- docker load -i /mnt/d/CUA-Lab/cache/ariadne-forum-oci.tar
```

OwnCloud、RocketChat 与 TheAgentCompany reset/health API 尚需单独部署。其启动、NPC、SSH 注入与数据初始化不是一个通用网页服务器可以替代的。

## 验证与明确限制

28 项自动测试在 Windows Python 3.12、Linux Python 3.13 通过；包含 HTTP 线级请求、证据伪造拒绝、净化失败、根与后代闭包、无关状态保留、checkpoint 恢复、参数绑定及 GUI 动作重放拒绝。测试替身仅用于机制验证，结果不计入模型评测。

AgentLAB 原始工具调用、RedTeamCUA 全执行器导入均已验证。完整 GUI 启动、网页健康检查和真实模型轨迹必须以实际运行记录验收。当前 API key 未配置，不能声称完成真实模型或安全效果验证。

密钥、SQLite、截图、下载镜像、第三方 checkout、原始运行输出留在本地。提交的文档只记录可复现步骤、版本与验证状态。
