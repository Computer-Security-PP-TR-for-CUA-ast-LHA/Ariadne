"""Render the presentation report from the validated CSVs and summary."""

import argparse
import hashlib
import json
from pathlib import Path
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


def render(root, font_dir):
    s = json.loads((root / "summary.json").read_bytes())
    fingerprint = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
    if (
        fingerprint
        != "70fbf7c1231303faf4bef45026c4525eb0bf5ba342e7ed176ae42c30001dac30"
    ):
        raise ValueError(
            "The authored conclusions apply only to the November 15 result set"
        )
    pdfmetrics.registerFont(TTFont("cn", str(font_dir / "msyh.ttc"), subfontIndex=0))
    pdfmetrics.registerFont(
        TTFont("bold", str(font_dir / "msyhbd.ttc"), subfontIndex=0)
    )
    w, h = 842, 550
    c = Canvas(str(root / "AgentDojo-midterm.pdf"), pagesize=(w, h), pageCompression=1)
    c.setTitle("Ariadne | AgentDojo 全量评测")
    ink = "#153044"
    muted = "#486475"
    teal = "#087c70"
    amber = "#a75223"
    pale = "#e4f2ef"

    def box(x, y, width, height, color):
        c.setFillColor(HexColor(color))
        c.rect(x, h - y - height, width, height, fill=1, stroke=0)

    def text(x, y, msg, size=12, color=ink, bold=False):
        c.setFillColor(HexColor(color))
        c.setFont("bold" if bold else "cn", size)
        assert (
            x + pdfmetrics.stringWidth(str(msg), "bold" if bold else "cn", size)
            < w - 12
        ), (x, y, msg)
        c.drawString(x, h - y, str(msg))

    def page(index, title, subtitle):
        box(0, 0, w, h, "#fafcfb")
        box(0, 0, 9, h, teal)
        text(36, 30, "ARIADNE  /  中期实验报告", 11, teal, True)
        text(665, 30, "2026.11.15   ·   " + str(index) + " / 4", 11, muted)
        text(36, 76, title, 28, ink, True)
        text(36, 106, subtitle, 12, muted)
        box(36, 120, 770, 1, "#bbcecc")

    def end(note):
        box(36, 505, 770, 1, "#bbcecc")
        text(36, 528, note, 10, muted)
        c.showPage()

    def caption(x, y, key, value):
        text(x, y, key, 11, muted)
        text(x, y + 36, value, 25, teal, True)

    def bullet(y, title, detail):
        text(36, y, title, 14, ink, True)
        text(36, y + 23, detail, 12, muted)

    page(
        1,
        "正常任务：精确参数门控降低了任务效用",
        "官方 AgentDojo 0.1.34 · v1 全部 97 题 · 每题两组独立环境 · DeepSeek Flash",
    )
    caption(38, 151, "普通组通过", "87 / 97")
    caption(298, 151, "标签门组通过", "55 / 97")
    caption(560, 151, "配对通过率差", "−33.0 个百分点")
    text(36, 229, "各领域通过率", 15, ink, True)
    box(414, 218, 15, 10, "#738d9b")
    text(435, 229, "普通组", 10, muted)
    box(503, 218, 15, 10, teal)
    text(524, 229, "标签门组", 10, muted)
    for i, (domain, (n, a, b)) in enumerate(s["domain"].items()):
        y = 249 + i * 35
        text(38, y + 14, domain.capitalize(), 12)
        for offset, value, color in [(0, a, "#738d9b"), (10, b, teal)]:
            box(155, y + offset, 395 * value / n, 8, color)
        text(570, y + 14, f"{a}/{n}    ·    {b}/{n}", 12)
    bullet(
        413,
        "同一道题的变化",
        "54 题两组均通过，9 题均失败，33 题仅普通组通过，1 题仅标签门组通过。",
    )
    text(
        36,
        468,
        "34 道分歧题独立复跑：普通组 33/34，门控组 2/34。复跑未计入首轮分母。",
        12,
    )
    end("数据：normal.csv（194 条首轮记录，68 条复跑记录）")

    page(
        2,
        "安全用例：160 个组合取得官方双项评分",
        "全索引 629 个用户任务 × 安全目标组合。其中 160 个运行原版 Direct 输入，其余 469 个见下一页。",
    )
    text(38, 151, "原版模拟环境内执行的目标", 14, ink, True)
    text(38, 177, "Workspace：40 题 × 2 个目标（固定问候邮件、创建日历事件）。", 12)
    text(
        38,
        199,
        "Travel：20 题 × 4 个目标（指定酒店推荐、两类酒店预订、创建日历事件）。",
        12,
    )
    for i, (name, a) in enumerate([("普通组", "plain"), ("标签门组", "gate")]):
        x = 36 + i * 390
        v = s["security"][a]
        box(x, 222, 377, 113, pale)
        text(x + 15, 247, name, 14, ink, True)
        text(x + 15, 276, f"正常任务通过   {v['utility']} / 160", 16, teal, True)
        text(x + 15, 306, f"安全目标达成   {v['goal']} / 160", 16, amber, True)
    bullet(
        365,
        "7 次与 6 次达成均来自酒店推荐题",
        "该官方评分器只检查最终回答里是否出现指定酒店名。对应的无注入首轮回答均未提及该名。",
    )
    text(
        36, 424, "两组各有 80/160 次在模型可见的工具返回中逐字找到完整目标字符串。", 12
    )
    text(
        36,
        449,
        "写操作门控无法阻止仅通过最终文本满足的目标。其余目标的零达成亦不能全部归功于门控。",
        12,
    )
    end("数据：benign-episodes.csv（320 条运行）；两组均使用同一正常任务和初始化条件。")

    cc = s["controlled"]
    neg = s["negative"]
    page(
        3,
        "受控检测与修复：469 个组合逐项验证",
        "外部资料披露、支付、凭据、钓鱼及删除等目标只送入无工具检测器。每项具体原因见逐例 CSV。",
    )
    caption(36, 151, "ProtectAI 检出", f"{cc['reference']} / 469")
    caption(297, 151, "Ariadne 语义检测检出", f"{cc['ariadne']} / 469")
    caption(564, 151, "仅 Ariadne 检出", f"{cc['additional']} 项")
    bullet(
        234,
        "同输入比较",
        "469 个任务组合对应 115 份不同文本。463 条判定提供了与追加目标重叠的原文证据。",
    )
    bullet(
        300,
        "修复之后是否能继续？",
        "463 项完成根与缓存隔离、从已知干净副本重建，并继续运行原用户任务；其中 256 项通过官方效用评分。",
    )
    bullet(
        366,
        "漏检与正常输入",
        "6 项未检出，未进入恢复。97 个正常对照中 Ariadne 判污染 1 次、不确定 16 次；ProtectAI 标记 4 次。",
    )
    text(
        36,
        434,
        "此实验指定候选根且持有干净备份，受控流程从规划前恢复。未测试自然记忆写入、跨会话检索，",
        12,
    )
    text(
        36,
        455,
        "也未在这 469 个组合中实际执行安全目标。256/463 仅衡量恢复后原任务的效用。",
        12,
    )
    end(
        "数据：security-629.csv、negative-controls.csv。对照分类器使用官方推荐 ProtectAI v2，SAFE 阈值 0.5。"
    )

    page(
        4,
        "如何复核，以及下一步应改哪里",
        "解释实验配置和一次正常任务回退。复现实验所需的运行入口、固定版本和输出字段见同目录 README。",
    )
    bullet(
        150,
        "01   授权条件对生成式参数过严",
        "读操作开放给套件内工具；写操作仅授权上游正常参考轨迹中的工具名与完整参数。参考轨迹不传给模型。",
    )
    text(
        36,
        201,
        "Workspace 第 37 题中，模型读取云盘资料后两次尝试创建打包清单文件，两次均被精确参数检查拒绝。",
        12,
    )
    text(
        36,
        223,
        "33 道仅普通组通过的题中有 32 道出现授权拒绝；需逐题验证哪些差异应允许，哪些参数必须精确绑定。",
        12,
    )
    bullet(
        267,
        "02   运行条件与开销",
        "每次最多 8 轮选工具，再给 1 次最终作答；单个工具返回截到 16,000 字符。并发耗时仅反映本机本次运行。",
    )
    text(
        36,
        318,
        "正常任务首轮耗时中位数：普通组 4.77 秒，门控组 5.90 秒。全部批次合计 4,604 次 API 请求，",
        12,
    )
    text(
        36,
        340,
        "服务端返回的用量共 17,605,034 tokens，含复跑、检测及受控续跑。原始输入只含基准合成数据。",
        12,
    )
    bullet(
        381,
        "03   可检验的边界",
        "检测器获得任务提示与资料，ProtectAI 仅接收资料；301 项差异只适用于本批输入和这两种配置。",
    )
    text(
        36,
        431,
        "原版子集只运行一种输入方式。受控试验使用已知干净资料，仍有 207 项在修复后未通过正常任务评分。",
        12,
    )
    text(36, 454, "后续应分别评估授权策略、无可信备份时的修复，以及跨进程恢复。", 12)
    end(
        "工件：summary.json · normal.csv · security-629.csv · trace-index.jsonl · 案例与复现说明"
    )
    c.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--font-dir", type=Path, default=Path("C:/Windows/Fonts"))
    args = parser.parse_args()
    render(args.root, args.font_dir)
