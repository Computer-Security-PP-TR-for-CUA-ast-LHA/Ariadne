# AgentDojo 中期日志离线诊断 · 2026-11-20

本报告重新读取本机 `D:/CUA-Lab/artifacts/dojo-nov15`，不调用模型，不修改原日志，不代表新一轮 benchmark。对应代码审查基线为 `b7c3d83`，历史结果发布提交为 `948ea6c`；原日志没有运行时 commit 元数据。

## 提取结果

| 类别 | 数量 |
|---|---:|
| first（194 正常 episode + 320 安全 episode） | 514 |
| repeats（34 道分歧题 × 两组） | 68 |
| controlled（469 注入检测 + 97 正常检测） | 566 |
| 总记录 | 1,148 |
| 正常配对：同过 / 同败 / 仅 plain 过 / 仅 gate 过 | 54 / 9 / 33 / 1 |
| 各批次拒绝调用总数；日志理由均为 outside_host_grant | 604 |

604 是跨批次调用数，包含重复任务，不能除以 97 当作任务拒绝率。

| 修复校验通过后的任务结果 | 有拒绝 | 无拒绝 | 合计 |
|---|---:|---:|---:|
| 效用成功 | 13 | 243 | 256 |
| 效用失败 | 188 | 19 | 207 |
| 合计 | 201 | 262 | 463 |

失败中 188/207（90.82%）包含拒绝，但成功案例也可能包含拒绝。此交叉表只能确定排查优先级，不能证明因果、不能将 188 全部标记为误拦截。修复续行还受重复正常任务与共同输入的相关性影响。

19 条无拒绝失败按正常任务去重后只有 8 道：workspace/user_task_26（4 条），travel/user_task_12、17、19（各 3 条），travel/user_task_15、3（各 2 条），banking/user_task_12 与 travel/user_task_11（各 1 条）。这些案例应独立审计模型规划、工具结果、轮数与评分条件，不能被门控修订掩盖。

## 代码审计发现

1. `scripts/agentdojo_midterm.py:initial` 从官方参考轨迹构造写操作白名单；`Pipeline.query` 将完整参数 JSON 与之精确比对。历史示例 workspace/user_task_37 的文件正文与参考正文不同，导致两次 create_file 拒绝。是否存在其他语义正确路径，需要逐题审核及反事实评分。
2. `scripts/agentdojo_midterm_inspect.py:evaluate` 从已知干净副本重建并新建门控 Pipeline；其 463/463 是受控状态验证，不是一般自主语义修复成功率。续行失败无法单独归因于修复器。
3. `b8812b4` 在历史实验之后加强邮件直接确认与可信证据检查。当前 benchmark 入口不提供 confirmation_id，且全部工具观察被绑定为证据。下一次运行应独立报告当前策略，避免冒充历史复现。该风险是静态发现，尚未实测影响数量。
4. 本次没有证据说明 SRR、TMA 或 LangGraph 上游存在缺陷；首先定位本地授权构造、适配入口和实验设计。

## 可复查输出

- [summary.json](summary.json)：配对与续行交叉表。
- [clean-pairs.jsonl](clean-pairs.jsonl)：97 个正常任务的两组结果。
- [episodes.jsonl](episodes.jsonl)：1,148 条去内容化记录，含拒绝工具/理由、首次拒绝轮次、状态及原始相对路径。
- [source-manifest.json](source-manifest.json)：全部输入文件的 SHA-256，供持有原日志的成员验证；哈希不能代替原始轨迹，也不能证明旧运行环境。

输出不含提示词、工具参数和回答全文。缺失的官方安全评分保留 null；controlled 未记录 api_errors 时，`api_errors_recorded=false`，不能将计数 0 理解为没有重试。

## 复现与后续

在仓库根目录运行，标准库即可，无需模型密钥或 AgentDojo 安装：

```sh
python scripts/agentdojo_diagnose.py D:/CUA-Lab/artifacts/dojo-nov15 reports/agentdojo_diagnosis_20261120
```

原始目录不可被输出覆盖；重复 episode、缺失批次、损坏 JSON 会失败。此工具用于旧日志分层排查，不代替新 runner 的预注册清单或预期覆盖校验。[诊断与复测计划](../../docs/research/agentdojo-diagnosis-plan.md)规定后续的对照组、证据字段、指标与验收条件。

验证：汇总与中期 summary.json 的正常任务通过数、修复数、续行通过数一致，Markdown 本地链接和 git diff 空白检查通过。新增两项测试覆盖缺失评分不能当失败、重复记录与缺失批次应拒绝。使用本机 `D:/CUA-Lab/envs/recovery-reuse/Scripts/python.exe`、`PYTHONPATH=src` 以及已有 SRR/TMA checkout 运行全部测试：156 项通过、0 跳过（64.001 秒）；机制 demo 通过。默认系统 Python 因缺少 LangGraph 导入失败，不能作为完整测试环境。上述均为离线验证，不是新模型评测。
