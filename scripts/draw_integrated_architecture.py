"""Draw the integrated architecture as PNG and editable SVG (Pillow required).

python scripts/draw_integrated_architecture.py --font C:/Windows/Fonts/msyh.ttc
"""
import argparse
from html import escape
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

p = argparse.ArgumentParser()
p.add_argument('--font', required=True)
args = p.parse_args()
W, H, SCALE = 1820, 1335, 2
BG, INK, MUTED = '#f7f9fc', '#1b334c', '#526b83'
BLUE, TEAL, ORANGE, PURPLE = '#326c9f', '#167f89', '#b75b27', '#7357a5'
im = Image.new('RGB', (W*SCALE,H*SCALE), BG)
d = ImageDraw.Draw(im)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<title>Ariadne integrated benchmark, provenance and recovery architecture</title>',
       f'<rect width="{W}" height="{H}" fill="{BG}"/>']

def rect(x,y,w,h,fill='white',stroke='#c8d6e3',r=14):
    d.rounded_rectangle((x*SCALE,y*SCALE,(x+w)*SCALE,(y+h)*SCALE),r*SCALE,fill,stroke,2*SCALE)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')

def text(x,y,s,size=22,color=INK,center=False,max_width=None):
    font=ImageFont.truetype(args.font,size*SCALE)
    if max_width is not None:
        assert d.textlength(s,font=font) <= max_width*SCALE, (s,max_width)
    d.text((x*SCALE,y*SCALE),s,font=font,fill=color,anchor='mm' if center else 'lm')
    anchor='middle' if center else 'start'
    svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" font-size="{size}" text-anchor="{anchor}" dominant-baseline="central">{escape(s)}</text>')

def arrow(points,color=BLUE,width=3):
    d.line([(x*SCALE,y*SCALE) for x,y in points],fill=color,width=width*SCALE,joint='curve')
    svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
    x,y=points[-1]; px,py=points[-2]; dx,dy=x-px,y-py
    length=(dx*dx+dy*dy)**.5; ux,uy=dx/length,dy/length
    head=[(x,y),(x-11*ux+5*uy,y-11*uy-5*ux),(x-11*ux-5*uy,y-11*uy+5*ux)]
    d.polygon([(a*SCALE,b*SCALE) for a,b in head],fill=color)
    svg.append(f'<polygon points="{" ".join(f"{a},{b}" for a,b in head)}" fill="{color}"/>')

def panel(x,w,title,color,fill):
    rect(x,425,w,605,fill,color)
    rect(x+1,426,w-2,56,color,color,12)
    text(x+22,454,title,26,'white',max_width=w-44)

text(30,48,'Ariadne  |  从持久来源记录到定向修复与安全续行',38)
text(30,95,'本轮：四人共同完成代码复用、适配、实现与 Benchmark；后续共同接入 ChatGPT。',23,MUTED)
text(1680,48,'统一目标架构',23,TEAL,True)

# Normal host execution chain; the upper orange line is the recovery loop.
for x,w,head,color,lines in [
    (30,240,'① Benchmark',PURPLE,['AgentLAB / RedTeamCUA','任务、环境与攻击样例','成员 1：搭建 / 测试 / 采集']),
    (310,420,'统一宿主接口 / 适配器',BLUE,['观测 · 记忆写入 / 摘要 · 动作提议','task / session / version / call ID','hash · 来源 · 输入输出 · revision']),
    (770,280,'记忆与动作规划',BLUE,['写入 / 摘要 / 检索','内容携带 ID + hash 引用','模型提议；宿主记录依赖']),
    (1090,320,'② 执行前检查',TEAL,['独立授权 + 标签 / 版本校验','绑定完整参数与当前状态','通过才交给执行器']),
    (1450,340,'受保护工具执行',BLUE,['真实执行与效果核对','结果 / 新观测回到适配器','效果与已消耗授权持续记录'])]:
    rect(x,165,w,160,'white',color)
    text(x+18,194,head,25,color,max_width=w-36)
    for i,line in enumerate(lines): text(x+18,235+i*31,line,16 if w == 240 else 19,MUTED,max_width=w-36)
for a,b in [(270,310),(730,770),(1050,1090),(1410,1450)]:arrow([(a,245),(b,245)])
text(1430,221,'通过',16,TEAL,True)

# Capture and control lanes kept separate from the panels.
arrow([(470,325),(470,365),(290,365),(290,425)],TEAL)
text(50,350,'版本 / 标签登记与加载核对',19,TEAL)
arrow([(620,325),(620,390),(870,390),(870,425)],BLUE)
text(650,370,'宿主采集真实输入与派生事件',19,BLUE)
arrow([(1250,325),(1250,365),(1480,365),(1480,425)],ORANGE)
text(1290,345,'拒绝 / 可疑 → 暂停并诊断',19,ORANGE)

panel(30,535,'② 双份持久标签与版本账本',TEAL,'#edf8f8')
text(52,506,'内容引用是载体；双份记录按同一版本核对',21,TEAL,max_width=491)
for x,w,title,lines in [
    (52,235,'第一份：主库',['内容 + 标签','版本 ID + 内容 hash','来源 / 状态 / 父节点']),
    (310,233,'第二份：校验库',['标签 + 内容 hash','同版本校验记录','可选签名 / 密钥校验'])]:
    rect(x,540,w,166,'white','#8ebfc4')
    text(x+w/2,568,title,23,INK,True,max_width=w-20)
    for i,line in enumerate(lines):text(x+15,610+i*31,line,19,MUTED,max_width=w-30)
arrow([(287,625),(310,625)],TEAL,2)
rect(52,726,491,72,'white','#8ebfc4')
text(70,749,'一致性服务：共同 revision / 提交状态',21,TEAL,max_width=455)
text(70,778,'丢失、篡改或不一致 → 拒绝使用并记录原因',19,MUTED,max_width=455)
text(52,835,'来源身份由真实渠道确定；权限由可信宿主管理',20,INK,max_width=491)
text(52,872,'上游候选：TMA-NM 来源约束 / FIDES 标签策略',19,MUTED,max_width=491)
text(52,915,'修复时隔离旧版本，验证后发布新版本',21,TEAL,max_width=491)
text(52,956,'两份库不自动构成独立信任边界。',19,MUTED,max_width=491)
text(52,989,'摘要在此指内容 hash；授权来源与事务需对齐。',19,MUTED,max_width=491)

panel(600,535,'③ 面向定向修复的溯源图',BLUE,'#eef4fb')
text(622,506,'成员 3：依赖采集、查询与导出',22,BLUE,max_width=491)
for x,label in [(622,'网页 P'),(802,'笔记 N'),(982,'副本 C')]:
    rect(x,546,130,56,'white','#99b4ce'); text(x+65,574,label,22,INK,True)
arrow([(752,574),(802,574)],BLUE,2); arrow([(932,574),(982,574)],BLUE,2)
text(777,531,'摘要',16,BLUE,True);text(957,531,'复制',16,BLUE,True)
rect(622,634,210,54,'white','#99b4ce');text(727,661,'独立正常资料 Q',20,INK,True)
rect(900,634,212,54,'white','#99b4ce');text(1006,661,'正常笔记 B',20,INK,True)
arrow([(832,661),(900,661)],BLUE,2)
rect(622,726,491,72,'white','#99b4ce')
text(640,749,'call 祖先定位 → 根证据 → 全域后代查询',21,BLUE,max_width=455)
text(640,778,'覆盖跨会话与未进入当前动作的持久副本',19,MUTED,max_width=455)
text(622,835,'writer 事件：实际输入 / 输出 / 重放配方',20,INK,max_width=491)
text(622,872,'图快照：scope + revision + 覆盖缺口',20,INK,max_width=491)
text(622,915,'区分：内容依赖 / 时间顺序 / 审计替换',21,BLUE,max_width=491)
text(622,956,'依赖可达只给出候选范围，不直接证明污染。',19,MUTED,max_width=491)
text(622,989,'缺根、缺边或截断 → 不得以空结果宣告安全。',19,MUTED,max_width=491)

panel(1170,620,'④ 定向修复 · 状态重建 · 恢复运行',ORANGE,'#fff5ec')
text(1192,506,'luowentao：恢复协调器 + 可替换修复后端',22,ORANGE,max_width=576)
steps=[
    ('1  诊断与计划','区分权限不足 / 污染 / 未知；结合证据与图'),
    ('2  隔离与修复','隔离根及副本；净化 / 干净输入重建 / 参数恢复'),
    ('3  复检与一致发布','核验安全与事实保留；新版本 + 旧新映射'),
    ('4  状态重建','重建检索视图、上下文与 checkpoint，排除旧历史'),
    ('5  重新规划与授权','返回主链生成新动作，再次经过执行前检查')]
for i,(head,body) in enumerate(steps):
    y=540+i*84
    rect(1192,y,576,70,'white','#d9b395')
    text(1210,y+23,head,22,ORANGE,max_width=540)
    text(1210,y+51,body,19,INK,max_width=540)
    if i<4:arrow([(1480,y+70),(1480,y+84)],ORANGE,2)
text(1192,987,'失败 / 证据不足 / 外部效果未知 → 保持暂停',21,ORANGE,max_width=576)
# Graph query/response is shown by the direct inter-panel connection.
arrow([(1135,575),(1192,575)],BLUE,3)


# Safe continuation returns to planning, never straight to the tool executor.
arrow([(1768,912),(1805,912),(1805,133),(910,133),(910,165)],ORANGE,3)
text(1220,122,'验证通过：重建后的上下文返回规划',18,ORANGE)

# Consistent commit to both state and graph, with a label below connectors.
arrow([(1480,1030),(1480,1060),(290,1060),(290,1030)],ORANGE,3)
arrow([(870,1060),(870,1030)],ORANGE,3)
text(900,1091,'修复提交：隔离状态 + 已验证新版本 + 新依赖 / 审计映射；图、账本与检索视图水位一致后才续行',21,ORANGE,True,max_width=1740)

rect(30,1145,1760,118,'#edf0f8','#a9b6cd')
text(52,1173,'① 统一实验记录与独立评分',26,PURPLE)
text(52,1210,'汇集四模块：标签 / gate 决定 / 图覆盖 / 修复轨迹 / 实际效果；评估攻击成功、正常任务完成、恢复成功、复发与成本',22,INK,max_width=1716)
text(52,1242,'沿用原 benchmark 判定；机制测试与真实模型结果分开。外部效果与已消耗授权不随记忆回滚，禁止盲目重放。',20,MUTED,max_width=1716)
text(30,1303,'目标架构，不表示全部已实现。存储权威、双份事务与图接口待团队对齐；后续更换宿主适配器时仍需验证拦截与上下文控制能力。',20,MUTED,max_width=1760)

root=Path(__file__).resolve().parents[1]/'docs/assets'
root.mkdir(parents=True,exist_ok=True)
im.save(root/'architecture-integrated.png',optimize=True)
svg.append('</svg>')
(root/'architecture-integrated.svg').write_text('\n'.join(svg),encoding='utf-8')
print(root/'architecture-integrated.png')
print(root/'architecture-integrated.svg')
