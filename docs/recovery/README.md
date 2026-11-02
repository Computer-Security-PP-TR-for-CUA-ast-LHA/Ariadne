# luowentao：定向修复、状态重建与恢复运行

日期：2026-11-02。状态：调研与接口提案；尚未成为团队已确认协议，也不是完成的恢复实现。

- [论文、源码审查与复用选择](literature-and-reuse.md)
- [与标签库、溯源图和运行器的接口 v0.1](interface-v0.1.md)
- [固定版本与本轮验证记录](sources.lock.json)
- [最小交接图及预期计划](fixtures/minimal-recovery.json)
- [上游 memory-rollback 行为探针](../../scripts/research/probe_memory_rollback.py)

## 本轮结论

优先评估 **SRR 的持久后代撤销/写入事件重放**与 **memory-rollback 的类型化图/恢复规划**，两者比纯上下文净化更贴近本模块。AgentSentry 补充边界诊断与上下文净化；TMA-NM 只承担具有独立授权证据的参数恢复。不能把这些异构方法简单串起来就宣称完成原方法复现。

本轮实际运行：Ariadne 原有 28 项测试与 demo；SRR 原始 runtime smoke 的 6 项测试；memory-rollback 图结构自检和 4 项行为探针；已有本地 TMA 接入实验的 6 个检查。没有调用真实模型、部署大模型或启动付费 API，没有生成真实 ASR 或完整 benchmark 结果。

## 可独立提交的实现顺序

| 交付 | 内容 | 验收 |
|---|---|---|
| P0 接口 | 与成员 2/3 确定版本身份、依赖类型、writer 事件、revision、覆盖缺口 | 同一夹具由内存图与实际图 adapter 返回相同闭包；冻结协议后再写生产 adapter |
| P1 计划 | 结构化告警、全域后代、隔离集合、纯写入重放顺序 | 不误伤独立分支、不跳过失踪根、不只清当前上下文 |
| P2 执行 | 资格通过的原始后端适配、候选版本暂存、验证和原子发布 | 原版本隔离；新版本无权限升级；失败不半发布 |
| P3 恢复 | 活动检索视图、上下文和 checkpoint 重建、重规划、交回 gate | 进程重开后旧副本不可检索，合法任务能继续；外部效果未知则暂停 |
| P4 评测 | 固定污染状态分叉、相同定位证据和净化模型 | 比较删除根、清空、全局回滚、上下文净化、原始方法和集成方案 |

先以假数据验证协议，真实模型与原始方法结果另列。本文不承诺新增 novelty；SRR 与 memory-rollback 已直接覆盖“图引导撤销/重放、保留正常状态”的主要思想。

## 本次 Git 整理

README 和 PNG 架构图直接发布到 main（`79edc0b`，图注排版调整 `ee3abb5`）。从该 main 建立 `luowentao`。

核对提交祖先关系后删除：本地及远程 `docs/team-roadmap`（`0439bd9`）、`feat/proposal-integration`（`82f89ac`）；仅本地 `feat/upstream-reuse-audit`（`a0ca0b1`）。三者内容均已包含于 main，未删除任何独有提交。

既有未提交的 `docs/roadmap.md` 修改，以及 `upstreams.py`、`check_reuse.py`、`demo_reused_authority.py`、相关上游测试/文档保持原样，未夹带进本次提交。TMA 的既有本地脚本尚非此分支的可分发交付；其测试记录须结合这一限制阅读。
