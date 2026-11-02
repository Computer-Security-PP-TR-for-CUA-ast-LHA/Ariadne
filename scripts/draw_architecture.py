"""Render the README design diagram (optional authoring dependency: Pillow).

Usage: python scripts/draw_architecture.py --font C:/Windows/Fonts/msyh.ttc
The font must support Chinese; it is not bundled. No runtime dependencies change.
"""
from pathlib import Path
import argparse
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument('--font', required=True)
args = parser.parse_args()
S = 2
im = Image.new('RGB', (1500*S, 820*S), '#f8fafc')
d = ImageDraw.Draw(im)
NAVY, BLUE, TEAL, ORANGE, GRAY = '#17324d', '#28669b', '#117c83', '#b95926', '#51657a'

def text(x, y, value, size=22, color=NAVY, center=False):
    font = ImageFont.truetype(args.font, size*S)
    d.text((x*S, y*S), value, fill=color, font=font, anchor='mm' if center else 'lt')

def box(x, y, w, h, fill='white', outline='#cad6e2', radius=12):
    d.rounded_rectangle((x*S,y*S,(x+w)*S,(y+h)*S), radius*S, fill=fill, outline=outline, width=2*S)

def arrow(points, color=BLUE, width=3):
    d.line([(x*S,y*S) for x,y in points], fill=color, width=width*S, joint='curve')
    x,y=points[-1]; px,py=points[-2]
    dx,dy=x-px,y-py
    length=(dx*dx+dy*dy)**0.5; ux,uy=dx/length,dy/length
    d.polygon([(x*S,y*S),((x-11*ux+5*uy)*S,(y-11*uy-5*ux)*S),((x-11*ux-5*uy)*S,(y-11*uy+5*ux)*S)],fill=color)

text(30, 24, 'Ariadne  |  持久溯源与定向恢复', 32)
text(1130, 34, '目标设计 · 非完成状态', 21, GRAY)
box(30,85,1440,57,'#e8eff7')
text(750,113,'成员 1   环境搭建 / Benchmark 运行 / 数据收集与独立评分',24,BLUE,True)

for x,w,title,sub in [(30,260,'外部输入与观测','网页 / 文件 / 工具返回'),(350,300,'记忆与规划','写入 · 摘要 · 检索 · 动作'),(710,320,'执行前检查','成员 2 · 权限与版本绑定'),(1170,300,'受保护工具执行','记录实际效果 / 新观测')]:
    box(x,180,w,86)
    text(x+w/2,209,title,25,NAVY,True); text(x+w/2,244,sub,18,GRAY,True)
arrow([(290,223),(350,223)])
arrow([(650,223),(710,223)])
arrow([(1030,223),(1170,223)])
text(1100,202,'通过',18,TEAL,True)

box(30,340,345,385,'#edf5fc','#8eb1cd')
text(52,362,'成员 2  双份持久标签库',25,BLUE)
box(50,418,305,80)
text(202,441,'内容侧引用',23,NAVY,True)
text(202,476,'version ID + 内容 hash',18,GRAY,True)
text(202,521,'双向核对',21,BLUE,True)
box(50,547,305,96)
text(202,574,'宿主权威账本',23,NAVY,True)
text(202,610,'来源 / 权限 / 版本 / 状态',18,GRAY,True)
text(52,677,'隔离旧版本 · 发布已验证新版本',18,GRAY)
arrow([(200,340),(200,300),(500,300),(500,266)])
arrow([(200,300),(200,340)])
text(255,279,'按 ID 写入 / 核对',18,BLUE)

box(410,340,345,385,'#edf8f7','#83b7b4')
text(432,362,'成员 3  面向修复的溯源图',24,TEAL)
for y,label in [(422,'外部版本 P'),(498,'混合笔记 N'),(574,'持久副本 C')]:
    box(455,y,255,50)
    text(582,y+25,label,22,NAVY,True)
arrow([(582,472),(582,498)],TEAL)
arrow([(582,548),(582,574)],TEAL)
text(432,650,'祖先定位 / 全域后代查询 / 导出',18,GRAY)
text(432,682,'版本依赖 ≠ 已证明的语义污染',18,GRAY)
arrow([(620,266),(620,320),(582,320),(582,340)],TEAL)
text(642,286,'采集依赖',18,TEAL)

box(790,340,680,385,'#fff4eb','#d5a483')
text(812,362,'成员 4  luowentao · 定向修复 / 状态重建 / 续行',24,ORANGE)
for y,a,b in [(420,'① 诊断与计划','告警证据 + 图快照 → 影响范围'),(482,'② 隔离与修复','净化 / 干净输入重建 / 参数恢复'),(544,'③ 复检与发布','替代版本 + 旧新映射 + 未解决项'),(606,'④ 状态重建','检索过滤 + 上下文重建 + checkpoint')]:
    box(812,y,636,50)
    text(830,y+15,a,21,ORANGE); text(1015,y+16,b,19,NAVY)
    if y<606: arrow([(1130,y+50),(1130,y+62)],ORANGE,2)
text(812,685,'验证通过 → 重新规划 → 再过执行门；失败 → 保持暂停',19,ORANGE)
arrow([(755,445),(812,445)],TEAL)
arrow([(870,266),(870,306),(1130,306),(1130,340)],ORANGE)
text(970,278,'拒绝 / 可疑 → 暂停诊断',18,ORANGE)
arrow([(1470,680),(1486,680),(1486,158),(870,158),(870,180)],ORANGE,2)
arrow([(1130,725),(1130,765),(202,765),(202,725)],ORANGE,2)
arrow([(582,765),(582,725)],ORANGE,2)
text(620,746,'提交修复：账本状态 + 新版本 + 图中依赖与审计映射',18,ORANGE,True)
text(30,786,'本轮：四人共同完成复用、实现与 Benchmark；下一阶段：共同接入 ChatGPT。',20,GRAY)
out=Path(__file__).resolve().parents[1]/'docs/assets/architecture.png'
out.parent.mkdir(parents=True,exist_ok=True)
im.save(out,optimize=True)
print(out)
