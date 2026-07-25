#!/usr/bin/env python3
"""坐姿报告 · 一页 A4 产品介绍 PDF(ReportLab)。

CJK 字体来自环境变量 DAIMON_CJK_FONT_REGULAR / DAIMON_CJK_FONT_BOLD。
用法: python build_onepager.py
"""
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '坐姿报告-产品介绍.pdf')

# ---------------------------------------------------------------- 字体(仅 env)
REG = os.environ.get('DAIMON_CJK_FONT_REGULAR')
BOLD = os.environ.get('DAIMON_CJK_FONT_BOLD')
if not REG or not BOLD:
    raise SystemExit('错误: 需要环境变量 DAIMON_CJK_FONT_REGULAR / DAIMON_CJK_FONT_BOLD')
pdfmetrics.registerFont(TTFont('NotoSC', REG))
pdfmetrics.registerFont(TTFont('NotoSC-Bold', BOLD))
registerFontFamily('NotoSC', normal='NotoSC', bold='NotoSC-Bold',
                   italic='NotoSC', boldItalic='NotoSC-Bold')

# ---------------------------------------------------------------- 色板(冷灰科技)
INK = HexColor('#1a1d24')      # 标题深色
BODY = HexColor('#333333')     # 正文深灰
MUTE = HexColor('#8a8f98')     # 灰标注
RULE = HexColor('#c9ccd2')     # 细分隔线
TABLE_DARK = HexColor('#3a3f47')

# ---------------------------------------------------------------- 样式
S = {
    'title': ParagraphStyle('title', fontName='NotoSC-Bold', fontSize=25, leading=32,
                            textColor=INK, alignment=TA_LEFT),
    'subtitle': ParagraphStyle('subtitle', fontName='NotoSC', fontSize=10.5, leading=15,
                               textColor=MUTE),
    'intro': ParagraphStyle('intro', fontName='NotoSC', fontSize=11, leading=18.5,
                            textColor=BODY),
    'h2': ParagraphStyle('h2', fontName='NotoSC-Bold', fontSize=13, leading=18,
                         textColor=INK),
    'th': ParagraphStyle('th', fontName='NotoSC-Bold', fontSize=10, leading=15,
                         textColor=INK),
    'td': ParagraphStyle('td', fontName='NotoSC', fontSize=10, leading=15,
                         textColor=BODY),
    'caption': ParagraphStyle('caption', fontName='NotoSC', fontSize=8.5, leading=12,
                              textColor=MUTE, alignment=TA_CENTER),
}

HARDWARE = [
    ('坐姿 / 二郎腿 / 在离座 / 身份签名', '压阻薄膜压力阵列(8×8)'),
    ('体重监测', '4×50kg 半桥称重传感器 + HX711'),
    ('呼吸率 / 静息心率趋势', '60GHz 毫米波雷达(非接触)'),
    ('端侧姿态识别', 'ESP32-S3 + TFLite Micro'),
    ('语音提醒', 'MAX98357A 功放 + 腔体喇叭'),
    ('整机 BOM', '约 ¥350–500'),
]

SHOTS = [
    ('01-封面.png', '封面'),
    ('02-健康打分.png', '健康打分'),
    ('03-AI总结.png', 'AI 总结'),
    ('04-姿态分布.png', '姿态分布'),
    ('05-生物特征.png', '生物特征'),
]
IMG_W = 3.2 * cm
IMG_H = IMG_W * 2796 / 1290  # 保持原始宽高比


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('NotoSC', 8.5)
    canvas.setFillColor(MUTE)
    canvas.drawCentredString(A4[0] / 2, 1.35 * cm, '演示数据 · 非医疗诊断设备')
    canvas.restoreState()


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.2 * cm, bottomMargin=2.2 * cm,
        title='坐姿报告 · 产品介绍', author='SmartCushion',
    )
    story = []

    # 1. 标题区
    story.append(Paragraph('坐姿报告', S['title']))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph('SmartCushion · 智能坐垫演示', S['subtitle']))
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width='100%', thickness=0.75, color=RULE))
    story.append(Spacer(1, 7 * mm))

    # 2. 一句话简介
    story.append(Paragraph(
        '一张会看坐姿、会打分、会说人话的坐垫:压力阵列感知每一次重心变化,'
        '毫米波雷达以非接触方式捕捉呼吸与静息心率,端侧 AI 实时识别姿态与身份,'
        '并结合状态指数,每晚生成一份诚实的坐姿健康报告。',
        S['intro']))
    story.append(Spacer(1, 9 * mm))

    # 3. 硬件亮点(三线表)
    story.append(Paragraph('硬件亮点', S['h2']))
    story.append(Spacer(1, 3.5 * mm))
    rows = [[Paragraph('功能', S['th']), Paragraph('硬件方案', S['th'])]]
    rows += [[Paragraph(a, S['td']), Paragraph(b, S['td'])] for a, b in HARDWARE]
    hw = Table(rows, colWidths=[6.4 * cm, 10.2 * cm])
    hw.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1.5, TABLE_DARK),    # 顶线
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, TABLE_DARK),   # 表头下
        ('LINEBELOW', (0, -1), (-1, -1), 1.5, TABLE_DARK),  # 底线
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(hw)
    story.append(Spacer(1, 9 * mm))

    # 4. 产品界面图集
    story.append(Paragraph('产品界面图集', S['h2']))
    story.append(Spacer(1, 3.5 * mm))
    images, captions = [], []
    for fname, cap in SHOTS:
        images.append(Image(os.path.join(HERE, fname), width=IMG_W, height=IMG_H))
        captions.append(Paragraph(cap, S['caption']))
    gallery = Table(
        [images, captions],
        colWidths=[3.32 * cm] * 5,
        rowHeights=[IMG_H, None],
    )
    gallery.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, 0), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, 1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(gallery)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print('written', OUT)


if __name__ == '__main__':
    build()
