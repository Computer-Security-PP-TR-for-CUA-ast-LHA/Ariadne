# 完整 Benchmark 打通清单

当前 Ariadne/RedTeamCUA 的代码和 864 个任务配置已准备好，但完整 GUI benchmark 还缺少独立的 OSWorld target VM、快照、Web 服务和模型凭据。当前网络无法连接官方 Hugging Face VM 下载地址，因此需要先完成下面的宿主机步骤。

## 你需要完成的宿主机步骤

### 1. 准备官方 target VM

下载官方镜像：

```text
https://huggingface.co/datasets/xlangai/ubuntu_osworld/resolve/main/Ubuntu-x86.zip
```

文件约 12.1 GB，解压后约 22 GB。建议放在 `E:\CUA-Lab\cache`，解压到全新的 `E:\CUA-Lab\vm\Ubuntu-x86`，不要覆盖 `cs315proj.vmx`。

也可以在能访问 Hugging Face 的机器下载后，通过移动硬盘或局域网复制到该目录。

### 2. 启用 VMware 控制链

关闭 target VM 后，在 `.vmx` 中确认：

```text
vhv.enable = "TRUE"
```

启动 target VM 后确认：

```powershell
D:\VMware\vmrun.exe -T ws list
D:\VMware\vmrun.exe -T ws listSnapshots <target.vmx>
```

必须存在 `init_state` 或等价的干净快照。当前 `cs315proj.vmx` 没有快照，不能作为正式 target。

### 3. 准备 RedTeamCUA 依赖环境

在 Windows 宿主机中执行：

```powershell
uv sync --project E:\CUA-Lab\upstream\RedTeamCUA --frozen --no-dev --no-install-project
E:\CUA-Lab\envs\redteamcua\Scripts\python.exe -c "import desktop_env; import easyocr; print('runner imports ok')"
```

如果没有 `uv`，先安装 Astral uv；不要在 6 GB 可用空间的远程 Ubuntu guest 中安装 CUDA 版 PyTorch。

### 4. 配置模型

Ariadne 的 DeepSeek client 读取：

```text
MODEL_API_KEY=<key>
MODEL_BASE_URL=https://api.deepseek.com
MODEL_ID=deepseek-flash
```

密钥只放在本地 `.env`，不要复制进 Git、报告或结果 JSON。

## 我随后可以继续执行的命令

target VM、快照和模型环境准备好后，在 `E:\Ariadne` 中运行：

```powershell
$env:MODEL_API_KEY = '<local-only-key>'
$env:MODEL_BASE_URL = 'https://api.deepseek.com'
$env:MODEL_ID = 'deepseek-flash'

E:\Ariadne\.venv\Scripts\python.exe -m cua_guard.redteamcua `
  --upstream E:\CUA-Lab\upstream\RedTeamCUA `
  --vm-path '<target.vmx>' `
  --example '<reviewed-example.json>' `
  --output E:\Ariadne\runs\redteamcua\smoke-001 `
  --max-steps 5
```

先跑 1 个正常 case 和 1 个攻击 case，检查：

- `traj.jsonl`；
- `result.txt` 和 `adversary_result.txt`；
- Ariadne SQLite 标签库；
- provenance JSON；
- 执行动作是否经过 gate；
- VM 是否恢复到干净快照。

只有这两个 case 都有真实轨迹和评分后，才扩展到 96、288，再到 864 cases。每个 case、baseline 和重复轮次必须使用独立输出目录。

## 当前不能声称的结果

- 864/864 只是 metadata preflight；
- 本地 deterministic demo 不是真实模型结果；
- 当前没有可报告的 ASR、正常任务成功率或 Ariadne 防御提升；
- 不应把 `run.py --help` 导入失败写成 benchmark 失败率。
