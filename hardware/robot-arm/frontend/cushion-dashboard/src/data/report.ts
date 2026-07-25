// ---------------------------------------------------------------------------
// 静态演示数据:Amber 的一天(7月20日 星期一)
// 09:02 入座 → 18:40 离开,全部数字彼此自洽:
//   坐姿时长 = 432 分钟 = 7小时12分
//   坐姿端正 = (432 - 二郎腿47 - 瘫坐31) / 432 ≈ 82%
//   得分 78 = 100 - 8(二郎腿)- 9(连续久坐 96 分钟)- 5(午后状态指数走低)
// ---------------------------------------------------------------------------

export type PostureKey = '正坐' | '前倾' | '二郎腿' | '瘫坐' | '离座'

export interface Segment {
  start: number // 从 00:00 起的分钟数
  end: number
  posture: PostureKey
}

export const POSTURE_COLORS: Record<PostureKey, string> = {
  正坐: '#34d399',
  前倾: '#38bdf8',
  二郎腿: '#fbbf24',
  瘫坐: '#fb923c',
  离座: '#3f3f46',
}

export const AXIS_START = 9 * 60 // 09:00
export const AXIS_END = 18 * 60 + 40 // 18:40

export const SEGMENTS: Segment[] = [
  { start: 9 * 60 + 2, end: 10 * 60 + 38, posture: '正坐' }, // 96 min · 最长连续久坐
  { start: 10 * 60 + 38, end: 10 * 60 + 48, posture: '离座' },
  { start: 10 * 60 + 48, end: 11 * 60 + 30, posture: '正坐' },
  { start: 11 * 60 + 30, end: 11 * 60 + 55, posture: '前倾' },
  { start: 11 * 60 + 55, end: 13 * 60 + 45, posture: '离座' }, // 午休
  { start: 13 * 60 + 45, end: 14 * 60 + 5, posture: '正坐' },
  { start: 14 * 60 + 5, end: 14 * 60 + 48, posture: '二郎腿' },
  { start: 14 * 60 + 48, end: 15 * 60 + 5, posture: '正坐' },
  { start: 15 * 60 + 5, end: 15 * 60 + 15, posture: '离座' },
  { start: 15 * 60 + 15, end: 15 * 60 + 35, posture: '前倾' },
  { start: 15 * 60 + 35, end: 15 * 60 + 39, posture: '二郎腿' },
  { start: 15 * 60 + 39, end: 16 * 60 + 10, posture: '瘫坐' },
  { start: 16 * 60 + 10, end: 16 * 60 + 14, posture: '正坐' },
  { start: 16 * 60 + 14, end: 16 * 60 + 30, posture: '离座' },
  { start: 16 * 60 + 30, end: 17 * 60 + 40, posture: '正坐' },
  { start: 17 * 60 + 40, end: 18 * 60 + 10, posture: '前倾' },
  { start: 18 * 60 + 10, end: 18 * 60 + 40, posture: '正坐' },
]

export interface DayStats {
  date: string
  name: string
  seatedMinutes: number // 432
  seatedText: string // 7小时12分
  uprightPct: number // 82
  standCount: number // 13
  legCrossMinutes: number // 47
  longestSitMinutes: number // 96
  totals: { posture: PostureKey; minutes: number; pct: number }[]
}

function buildStats(): DayStats {
  const totalsMap = new Map<PostureKey, number>()
  let seated = 0
  for (const s of SEGMENTS) {
    const dur = s.end - s.start
    totalsMap.set(s.posture, (totalsMap.get(s.posture) ?? 0) + dur)
    if (s.posture !== '离座') seated += dur
  }
  const total = AXIS_END - AXIS_START
  const order: PostureKey[] = ['正坐', '前倾', '二郎腿', '瘫坐', '离座']
  return {
    date: '7月20日 星期一',
    name: 'Amber',
    seatedMinutes: seated,
    seatedText: `${Math.floor(seated / 60)}小时${seated % 60}分`,
    uprightPct: Math.round(((seated - 47 - 31) / seated) * 100),
    standCount: 13,
    legCrossMinutes: 47,
    longestSitMinutes: 96,
    totals: order.map((p) => ({
      posture: p,
      minutes: totalsMap.get(p) ?? 0,
      pct: Math.round(((totalsMap.get(p) ?? 0) / total) * 100),
    })),
  }
}

export const DAY = buildStats()

export interface ScoreBreakdownItem {
  label: string
  detail: string
  delta: number
}

export const SCORE = {
  value: 78,
  status: '处于正常范围',
  ok: true,
  mainDrag: '午后连续久坐 96 分钟',
  breakdown: [
    { label: '基础分', detail: '坐姿端正 82% · 起身活动 13 次达标', delta: 100 },
    { label: '二郎腿 47 分钟', detail: '超出 30 分钟建议上限', delta: -8 },
    { label: '连续久坐 96 分钟', detail: '超出 90 分钟提醒阈值', delta: -9 },
    { label: '状态指数午后走低', detail: '15:00 后换姿频率上升', delta: -5 },
  ] as ScoreBreakdownItem[],
}

export const BIOMETRICS = [
  {
    label: '静息心率',
    value: '72',
    unit: 'bpm',
    caption: '高于你的平均值 68 bpm',
    tone: 'warn' as const,
  },
  {
    label: '心率变异性',
    value: '41',
    unit: 'ms',
    caption: '低于你的平均值 46 ms',
    tone: 'warn' as const,
  },
  {
    label: '呼吸频率',
    value: '15.2',
    unit: 'brpm',
    caption: '处于正常范围',
    tone: 'ok' as const,
  },
]

export const AI_SUMMARY =
  '上午坐姿稳定,下午三点后换姿频率明显上升,状态指数一路走低——有点坐不住了。'

export const TAGS = ['连续加班', '午后困倦', '二郎腿常客']
