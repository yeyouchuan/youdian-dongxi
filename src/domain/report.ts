import {
  DayReport,
  DayStats,
  HealthMetric,
  PostureSegment,
  PostureState,
  PressureSample,
  ScoreBreakdownItem,
  ScoreSummary,
  SeatedPosture,
} from '@/domain/types';

export const DEMO_REPORT_DATE = '2026-07-20';
export const AXIS_START = 9 * 60;
export const AXIS_END = 18 * 60 + 40;

export const POSTURE_LABELS: Record<PostureState, string> = {
  upright: '正坐',
  legsCrossed: '二郎腿',
  away: '离座',
};

export const POSTURE_COLORS: Record<PostureState, string> = {
  upright: '#34C759',
  legsCrossed: '#FF9F0A',
  away: '#D1D1D6',
};

export const DEMO_SEGMENTS: PostureSegment[] = [
  { startMinute: 542, endMinute: 638, posture: 'upright', source: 'cushion' },
  { startMinute: 638, endMinute: 648, posture: 'away', source: 'cushion' },
  { startMinute: 648, endMinute: 715, posture: 'upright', source: 'cushion' },
  {
    startMinute: 715,
    endMinute: 825,
    posture: 'away',
    source: 'cushion',
    note: '午休',
  },
  { startMinute: 825, endMinute: 845, posture: 'upright', source: 'cushion' },
  {
    startMinute: 845,
    endMinute: 888,
    posture: 'legsCrossed',
    source: 'cushion',
  },
  { startMinute: 888, endMinute: 905, posture: 'upright', source: 'cushion' },
  { startMinute: 905, endMinute: 915, posture: 'away', source: 'cushion' },
  { startMinute: 915, endMinute: 935, posture: 'upright', source: 'cushion' },
  {
    startMinute: 935,
    endMinute: 939,
    posture: 'legsCrossed',
    source: 'cushion',
  },
  { startMinute: 939, endMinute: 974, posture: 'upright', source: 'cushion' },
  { startMinute: 974, endMinute: 990, posture: 'away', source: 'cushion' },
  {
    startMinute: 990,
    endMinute: 1120,
    posture: 'upright',
    source: 'cushion',
    note: '当日最长连续久坐',
  },
];

function durationText(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours === 0) return `${remainder}分`;
  if (remainder === 0) return `${hours}小时`;
  return `${hours}小时${remainder}分`;
}

export function buildDayStats(
  segments: PostureSegment[],
  axisStart: number,
  axisEnd: number,
  standCount: number,
): DayStats {
  const totals = new Map<PostureState, number>([
    ['upright', 0],
    ['legsCrossed', 0],
    ['away', 0],
  ]);

  let longestSitMinutes = 0;
  for (const segment of segments) {
    const duration = segment.endMinute - segment.startMinute;
    totals.set(segment.posture, (totals.get(segment.posture) ?? 0) + duration);
    if (segment.posture !== 'away') {
      longestSitMinutes = Math.max(longestSitMinutes, duration);
    }
  }

  const uprightMinutes = totals.get('upright') ?? 0;
  const legCrossMinutes = totals.get('legsCrossed') ?? 0;
  const seatedMinutes = uprightMinutes + legCrossMinutes;
  const observationMinutes = axisEnd - axisStart;

  return {
    seatedMinutes,
    seatedText: durationText(seatedMinutes),
    uprightPercentage:
      seatedMinutes === 0 ? 0 : Math.round((uprightMinutes / seatedMinutes) * 100),
    standCount,
    legCrossMinutes,
    longestSitMinutes,
    postureTotals: (['upright', 'legsCrossed', 'away'] as PostureState[]).map(
      (posture) => ({
        posture,
        minutes: totals.get(posture) ?? 0,
        percentage: Math.round(((totals.get(posture) ?? 0) / observationMinutes) * 100),
      }),
    ),
  };
}

export function classifyPressureSample(
  sample: Omit<PressureSample, 'occupancy' | 'posture' | 'confidence'>,
): Pick<PressureSample, 'occupancy' | 'posture' | 'confidence'> {
  if (sample.totalKg < 5) {
    return { occupancy: 'away', posture: null, confidence: 1 };
  }

  const leftKg = sample.frontLeftKg + sample.rearLeftKg;
  const rightKg = sample.frontRightKg + sample.rearRightKg;
  const differenceRatio = Math.abs(leftKg - rightKg) / sample.totalKg;
  const posture: SeatedPosture = differenceRatio >= 0.18 ? 'legsCrossed' : 'upright';
  const confidence = Math.min(0.99, 0.72 + Math.abs(differenceRatio - 0.18));
  return { occupancy: 'occupied', posture, confidence };
}

function createPressureSample(
  sample: Omit<PressureSample, 'occupancy' | 'posture' | 'confidence'>,
): PressureSample {
  return { ...sample, ...classifyPressureSample(sample) };
}

export const DEMO_PRESSURE_SAMPLES: PressureSample[] = [
  createPressureSample({
    timestamp: '2026-07-20T09:02:00+08:00',
    frontLeftKg: 12.6,
    frontRightKg: 12.4,
    rearLeftKg: 13.8,
    rearRightKg: 13.7,
    totalKg: 52.5,
  }),
  createPressureSample({
    timestamp: '2026-07-20T14:05:00+08:00',
    frontLeftKg: 17,
    frontRightKg: 8.5,
    rearLeftKg: 17.8,
    rearRightKg: 9.2,
    totalKg: 52.5,
  }),
  createPressureSample({
    timestamp: '2026-07-20T15:05:00+08:00',
    frontLeftKg: 0,
    frontRightKg: 0,
    rearLeftKg: 0,
    rearRightKg: 0,
    totalKg: 0,
  }),
  createPressureSample({
    timestamp: '2026-07-20T18:10:00+08:00',
    frontLeftKg: 12.8,
    frontRightKg: 12.9,
    rearLeftKg: 13.4,
    rearRightKg: 13.5,
    totalKg: 52.6,
  }),
];

export function buildScore(stats: DayStats): ScoreSummary {
  const legCrossPenalty =
    stats.legCrossMinutes <= 30
      ? 0
      : -Math.min(14, 6 + Math.ceil((stats.legCrossMinutes - 30) / 10));
  const longSitPenalty =
    stats.longestSitMinutes <= 90
      ? 0
      : -Math.min(18, 5 + Math.ceil((stats.longestSitMinutes - 90) / 10));
  const rhythmPenalty = stats.uprightPercentage < 82 ? -7 : -5;
  const breakdown: ScoreBreakdownItem[] = [
    {
      label: '基础分',
      detail: `坐姿端正 ${stats.uprightPercentage}% · 起身活动 ${stats.standCount} 次达标`,
      delta: 100,
    },
    {
      label: `二郎腿 ${stats.legCrossMinutes} 分钟`,
      detail: '超出 30 分钟建议上限',
      delta: legCrossPenalty,
    },
    {
      label: `连续久坐 ${stats.longestSitMinutes} 分钟`,
      detail: '超出 90 分钟提醒阈值',
      delta: longSitPenalty,
    },
    {
      label: '状态指数午后走低',
      detail: '15:00 后坐垫压力波动增加',
      delta: rhythmPenalty,
    },
  ];
  const value = breakdown.reduce((total, item) => total + item.delta, 0);
  return {
    value,
    status: value >= 70 ? '处于正常范围' : '建议关注',
    isOK: value >= 70,
    mainDrag: `傍晚连续久坐 ${stats.longestSitMinutes} 分钟`,
    breakdown,
  };
}

export function buildDailyInsight(report: Pick<DayReport, 'stats' | 'score'>) {
  if (report.stats.longestSitMinutes >= 120) {
    return `今天最值得改善的是连续久坐 ${report.stats.longestSitMinutes} 分钟。下一次专注前先设一个 90 分钟起身提醒。`;
  }
  if (report.stats.legCrossMinutes > 40) {
    return `二郎腿累计 ${report.stats.legCrossMinutes} 分钟，是今天的主要扣分项。坐下后可以先确认双脚都落地。`;
  }
  if (report.stats.uprightPercentage >= 90) {
    return `今天正坐比例达到 ${report.stats.uprightPercentage}%，整体节奏稳定。继续保持规律起身即可。`;
  }
  return `今天正坐比例为 ${report.stats.uprightPercentage}%，起身 ${report.stats.standCount} 次。午后可以增加一次短暂活动。`;
}

const DEMO_HEALTH_METRICS: HealthMetric[] = [
  {
    type: 'restingHeartRate',
    label: '静息心率',
    value: '72',
    unit: 'bpm',
    caption: '高于个人平均值 68 bpm',
    tone: 'warn',
    source: '智能坐垫 · 演示',
  },
  {
    type: 'emotionReference',
    label: '情绪参考',
    value: '平静',
    caption: '根据生理趋势估算 · 18:35',
    tone: 'info',
    source: 'HRV 映射 · 演示',
    measuredAt: '2026-07-20T18:35:00+08:00',
    isEstimated: true,
    sensitive: true,
  },
  {
    type: 'respiratoryRate',
    label: '呼吸频率',
    value: '15.2',
    unit: 'brpm',
    caption: '处于正常范围',
    tone: 'ok',
    source: '智能坐垫 · 演示',
  },
  {
    type: 'bodyMass',
    label: '体重',
    value: '52.6',
    unit: 'kg',
    caption: '较上次下降 0.3 kg',
    tone: 'info',
    source: '智能坐垫估算 · 演示',
    isEstimated: true,
  },
  {
    type: 'menstrualCycle',
    label: '女性经期',
    value: '第2天',
    caption: '经量中等 · 预计 7月23日结束',
    tone: 'cycle',
    source: '用户手动记录 · 演示',
    sensitive: true,
  },
];

const demoStats = buildDayStats(DEMO_SEGMENTS, AXIS_START, AXIS_END, 13);

export const DEMO_REPORT: DayReport = {
  date: DEMO_REPORT_DATE,
  user: { id: 'demo-amber', displayName: 'Amber', recognitionConfidence: 0.96 },
  axisStart: AXIS_START,
  axisEnd: AXIS_END,
  firstSeatedAt: '09:02',
  stats: demoStats,
  score: buildScore(demoStats),
  healthMetrics: DEMO_HEALTH_METRICS,
  segments: DEMO_SEGMENTS,
  pressureSamples: DEMO_PRESSURE_SAMPLES,
  hrvRecords: [
    {
      timestamp: '2026-07-20T09:10:00+08:00',
      valueMs: 48,
      baselineMs: 46,
      emotionDisplay: '平静',
      source: '毫米波雷达',
    },
    {
      timestamp: '2026-07-20T14:30:00+08:00',
      valueMs: 36,
      baselineMs: 46,
      emotionDisplay: '紧张',
      source: '毫米波雷达',
    },
    {
      timestamp: '2026-07-20T18:35:00+08:00',
      valueMs: 41,
      baselineMs: 46,
      emotionDisplay: '平静',
      source: '毫米波雷达',
    },
  ],
  weightRecords: [
    { date: '2026-07-14', valueKg: 53.1, source: '用户手动记录' },
    {
      date: '2026-07-17',
      valueKg: 52.9,
      source: '智能坐垫',
      isEstimated: true,
    },
    {
      date: '2026-07-20',
      valueKg: 52.6,
      source: '智能坐垫',
      isEstimated: true,
    },
  ],
  menstrualRecord: {
    cycleStartDate: '2026-07-19',
    cycleDay: 2,
    phase: '经期',
    flow: '中等',
    symptoms: ['轻微腹胀'],
    expectedPeriodEnd: '2026-07-23',
    predictedNextPeriodStart: '2026-08-16',
    source: '用户手动记录',
  },
  aiSummary:
    '今天最值得改善的是连续久坐 130 分钟。下一次专注前先设一个 90 分钟起身提醒。',
  tags: ['连续加班', '午后困倦', '二郎腿常客'],
};

export function validateDayReport(report: DayReport): string[] {
  const issues: string[] = [];
  const sorted = [...report.segments].sort((a, b) => a.startMinute - b.startMinute);
  for (let index = 0; index < sorted.length; index += 1) {
    const segment = sorted[index];
    if (segment.endMinute <= segment.startMinute) {
      issues.push(`片段 ${index + 1} 的结束时间必须晚于开始时间`);
    }
    if (index > 0 && sorted[index - 1].endMinute !== segment.startMinute) {
      issues.push(`片段 ${index} 与 ${index + 1} 之间存在重叠或缺口`);
    }
  }
  if (report.stats.seatedMinutes !== 432) issues.push('演示坐姿总时长必须为 432 分钟');
  if (report.stats.uprightPercentage !== 89) issues.push('演示坐姿端正度必须为 89%');
  if (report.stats.longestSitMinutes !== 130) issues.push('最长连续久坐必须为 130 分钟');
  if (report.score.value !== 78) issues.push('演示评分必须为 78 分');
  for (const sample of report.pressureSamples) {
    if (sample.occupancy === 'away' && sample.posture !== null) {
      issues.push('离座压力样本的 posture 必须为空');
    }
  }
  return issues;
}
