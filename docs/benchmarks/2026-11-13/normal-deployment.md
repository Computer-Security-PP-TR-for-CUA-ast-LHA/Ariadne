# 11 月 13 日正常任务验收

在仓库根目录打开 PowerShell。下列命令复用本机已经部署的 AriadneLab、论坛镜像和专用 RTC 来宾。

## 启动论坛并检查原题页面

```powershell
wsl -d AriadneLab -u root -- bash scripts/deploy-forum.sh
curl.exe --noproxy "*" --fail --silent --output NUL --write-out "%{http_code}" http://127.0.0.1:9999/f/coolgithubprojects/103666/i-made-a-browser-extension-that-displays-ai-generated
```

正常响应是 200。容器仅向本机发布 9999 端口。部署脚本校验镜像身份并执行环境初始化。

## 启动并核对来宾

```powershell
$vmrun = "C:/Program Files (x86)/VMware/VMware Workstation/vmrun.exe"
$vm = "D:/CUA-Lab/vm/rtc-normal-evaluation/Ubuntu.vmx"
& $vmrun -T ws start $vm nogui
& $vmrun list
```

本次来宾地址为 192.168.131.136。若 VMware Tools 无法报告地址，读取 VMX 的 ethernet0.generatedAddress，在 C:/ProgramData/VMware/vmnetdhcp.leases 中用 MAC 对应当前租约。

## 复测正常目标

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$guestIP = "192.168.131.136"
$rtc = "D:/CUA-Lab/upstream/RedTeamCUA"
$rtcPy = "D:/CUA-Lab/envs/redteamcua/Scripts/python.exe"
$run = New-Item -ItemType Directory (Join-Path "D:/CUA-Lab/artifacts" ("rtc-clean-" + [guid]::NewGuid()))
& $rtcPy scripts/check_rtc_guest_gui.py --upstream $rtc --guest $guestIP --output "$run/gui"
& $rtcPy scripts/check_rtc_clean_forum.py --upstream $rtc --guest $guestIP --output "$run/forum.json"
```

GUI 对照检查创建目录前、创建后和清理后的三个评分。论坛正常目标采用宿主机读取页面 DOM、DeepSeek 选择链接、固定 Git 动作在来宾执行的方式。两个入口均要求起始时不存在名为 ChatOverflow 的目录。第二个入口需要来宾能访问 GitHub。

## 复测 AgentDojo 只读任务

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& D:/CUA-Lab/envs/dojo-clean-pilot/Scripts/python.exe scripts/benchmark_calendar_pilot.py --deepseek-flash --expanded --output D:/CUA-Lab/artifacts/nov13-deepseek-readonly
```

12 题各跑普通组和标签门组，各组日历 3/5、邮件 2/3、云盘 1/4。两组逐题判分全部一致。本轮采用单次只读工具查询，每题每组运行一次。有效批次 c15d047f-452e-4395-9e3d-26d2723ef2a4 共 48 次模型响应，13235 tokens。首次批次因结构化请求提示缺少 JSON 字样，24 次运行均返回 HTTP 400，修正后完整重跑。逐题轨迹在对应批次目录。

首次常规浅克隆超过控制器等待时间。最终采用稀疏浅克隆，检出扩展源码，跳过约 54 MB 的 demo.gif。已校验源码文件、origin、HEAD 和三阶段上游评分，详见 rtc-clean-forum.json。
