import { RealtimePostureSegment } from '@/domain/realtime-types';
import {
  DayReport,
  DayStats,
  PostureSegment,
  PostureState,
  PressureSample,
  ScoreBreakdownItem,
  ScoreSummary,
  SeatedPosture,
} from '@/domain/types';

export const POSTURE_LABELS: Record<PostureState, string> = {
  upright: '正坐',
  leanLeft: '左歪',
  leanRight: '右歪',
  edge: '坐前缘',
  other: '其他坐姿',
  away: '离座',
};

export const POSTURE_COLORS: Record<PostureState, string> = {
  upright: '#34C759',
  leanLeft: '#FF9F0A',
  leanRight: '#FFB340',
  edge: '#FF453A',
  other: '#AF52DE',
  away: '#D1D1D6',
};

export const POSTURE_ORDER: PostureState[] = [
  'upright',
  'leanLeft',
  'leanRight',
  'edge',
  'other',
  'away',
];

function durationText(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours === 0) return `${remainder}分`;
  if (remainder === 0) return `${hours}小时`;
  return `${hours}小时${remainder}分`;
}

function segmentDuration(segment: PostureSegment) {
  return Math.max(0, segment.endMinute - segment.startMinute);
}

function wholeMinutes(value: number) {
  return value > 0 ? Math.max(1, Math.round(value)) : 0;
}

function displayMinutes(value: number) {
  return value > 0 ? Math.max(0.1, Math.round(value * 10) / 10) : 0;
}

function longestContinuousSit(segments: PostureSegment[]) {
  const sorted = [...segments].sort(
    (a, b) => a.startMinute - b.startMinute,
  );
  let longest = 0;
  let currentStart: number | null = null;
  let currentEnd: number | null = null;

  for (const segment of sorted) {
    if (segment.posture === 'away') {
      currentStart = null;
      currentEnd = null;
      continue;
    }

    if (
      currentStart === null ||
      currentEnd === null ||
      segment.startMinute - currentEnd > 10 / 60
    ) {
      currentStart = segment.startMinute;
      currentEnd = segment.endMinute;
    } else {
      currentEnd = Math.max(currentEnd, segment.endMinute);
    }
    longest = Math.max(longest, currentEnd - currentStart);
  }

  return longest;
}

export function buildDayStats(
  segments: PostureSegment[],
  _axisStart: number,
  _axisEnd: number,
  standCount: number,
): DayStats {
  const totals = new Map<PostureState, number>([
    ['upright', 0],
    ['leanLeft', 0],
    ['leanRight', 0],
    ['edge', 0],
    ['other', 0],
    ['away', 0],
  ]);

  for (const segment of segments) {
    const duration = segmentDuration(segment);
    totals.set(segment.posture, (totals.get(segment.posture) ?? 0) + duration);
  }

  const uprightMinutesRaw = totals.get('upright') ?? 0;
  const seatedMinutesRaw = [...totals.entries()]
    .filter(([posture]) => posture !== 'away')
    .reduce((total, [, minutes]) => total + minutes, 0);
  const nonUprightMinutesRaw = Math.max(
    0,
    seatedMinutesRaw - uprightMinutesRaw,
  );
  const observedMinutesRaw = [...totals.values()].reduce(
    (total, value) => total + value,
    0,
  );
  const seatedMinutes = wholeMinutes(seatedMinutesRaw);
  const observedMinutes = wholeMinutes(observedMinutesRaw);

  return {
    seatedMinutes,
    seatedText: durationText(seatedMinutes),
    observedMinutes,
    uprightPercentage:
      seatedMinutesRaw === 0
        ? 0
        : Math.round((uprightMinutesRaw / seatedMinutesRaw) * 100),
    standCount,
    nonUprightMinutes: wholeMinutes(nonUprightMinutesRaw),
    longestSitMinutes: wholeMinutes(longestContinuousSit(segments)),
    postureTotals: POSTURE_ORDER.map((posture) => ({
        posture,
        minutes: displayMinutes(totals.get(posture) ?? 0),
        percentage:
          observedMinutesRaw === 0
            ? 0
            : Math.round(
                ((totals.get(posture) ?? 0) / observedMinutesRaw) * 100,
              ),
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
  const posture: SeatedPosture =
    differenceRatio >= 0.18 ? 'other' : 'upright';
  const confidence = Math.min(
    0.99,
    0.72 + Math.abs(differenceRatio - 0.18),
  );
  return { occupancy: 'occupied', posture, confidence };
}

export function getStandTarget(seatedMinutes: number) {
  return Math.max(1, Math.floor(seatedMinutes / 90));
}

export function buildScore(stats: DayStats): ScoreSummary {
  const longSitPenalty =
    stats.longestSitMinutes <= 90
      ? 0
      : -Math.min(
          18,
          5 + Math.ceil((stats.longestSitMinutes - 90) / 10),
        );
  const standTarget = getStandTarget(stats.seatedMinutes);
  const activityPenalty =
    stats.standCount >= standTarget
      ? 0
      : -Math.min(10, (standTarget - stats.standCount) * 3);
  const breakdown: ScoreBreakdownItem[] = [
    {
      label: '基础分',
      detail: `真实坐姿记录 ${stats.seatedText} · 正坐 ${stats.uprightPercentage}%`,
      delta: 100,
    },
    {
      label: `非正坐 ${stats.nonUprightMinutes} 分钟`,
      detail: '仅展示实际分类结果，暂不参与评分',
      delta: 0,
    },
    {
      label: `连续久坐 ${stats.longestSitMinutes} 分钟`,
      detail: '连续坐姿片段超过 90 分钟时扣分',
      delta: longSitPenalty,
    },
    {
      label: `起身活动 ${stats.standCount} 次`,
      detail: `按坐姿时长建议至少 ${standTarget} 次`,
      delta: activityPenalty,
    },
  ];
  const value = Math.max(
    0,
    breakdown.reduce((total, item) => total + item.delta, 0),
  );
  const penalties = [
    {
      value: longSitPenalty,
      label: `连续久坐 ${stats.longestSitMinutes} 分钟`,
    },
    { value: activityPenalty, label: `起身活动仅 ${stats.standCount} 次` },
  ].filter((item) => item.value < 0);
  const mainPenalty = penalties.sort((a, b) => a.value - b.value)[0];

  return {
    value,
    status: value >= 70 ? '处于正常范围' : '建议关注',
    isOK: value >= 70,
    mainDrag: mainPenalty?.label ?? '真实记录中未发现明显扣分项',
    breakdown,
  };
}

export function buildDailyInsight(report: Pick<DayReport, 'stats' | 'score'>) {
  if (report.stats.longestSitMinutes >= 120) {
    return `已记录时段最值得改善的是连续久坐 ${report.stats.longestSitMinutes} 分钟。下一次专注前可以先设一个 90 分钟起身提醒。`;
  }
  if (report.stats.nonUprightMinutes > 40) {
    return `已记录时段中非正坐累计 ${report.stats.nonUprightMinutes} 分钟；该数据仅作姿态观察，暂不参与评分。`;
  }
  if (report.stats.uprightPercentage >= 90) {
    return `已记录时段正坐比例达到 ${report.stats.uprightPercentage}%，真实坐姿记录整体稳定。`;
  }
  return `已记录时段正坐比例为 ${report.stats.uprightPercentage}%，记录到起身 ${report.stats.standCount} 次。`;
}

function localDayBounds(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  const start = new Date(year, month - 1, day);
  const end = new Date(year, month - 1, day + 1);
  return { start: start.getTime(), end: end.getTime() };
}

function normalizedPostureSegments(
  date: string,
  storedSegments: RealtimePostureSegment[],
): PostureSegment[] {
  const bounds = localDayBounds(date);
  const candidates = storedSegments
    .filter(
      (
        segment,
      ): segment is RealtimePostureSegment & {
        posture: PostureState;
      } =>
        segment.posture !== 'unknown' &&
        Number.isFinite(Date.parse(segment.startAt)) &&
        Number.isFinite(Date.parse(segment.endAt)),
    )
    .map((segment) => {
      const clippedStart = Math.max(Date.parse(segment.startAt), bounds.start);
      const clippedEnd = Math.min(Date.parse(segment.endAt), bounds.end);
      return {
        startMinute: Math.max(0, (clippedStart - bounds.start) / 60_000),
        endMinute: Math.min(24 * 60, (clippedEnd - bounds.start) / 60_000),
        posture: segment.posture,
        source: 'cushion' as const,
        confidence: segment.confidence,
      };
    })
    .filter(
      (segment) =>
        segment.endMinute > segment.startMinute &&
        segment.endMinute > 0 &&
        segment.startMinute < 24 * 60,
    )
    .sort((a, b) => a.startMinute - b.startMinute);

  const normalized: PostureSegment[] = [];
  for (const candidate of candidates) {
    const previous = normalized.at(-1);
    if (
      previous &&
      previous.posture === candidate.posture &&
      candidate.startMinute <= previous.endMinute
    ) {
      previous.endMinute = Math.max(previous.endMinute, candidate.endMinute);
      previous.confidence =
        previous.confidence === undefined
          ? candidate.confidence
          : (previous.confidence + candidate.confidence) / 2;
      continue;
    }

    const startMinute = previous
      ? Math.max(previous.endMinute, candidate.startMinute)
      : candidate.startMinute;
    if (candidate.endMinute <= startMinute) continue;
    normalized.push({ ...candidate, startMinute });
  }
  return normalized;
}

function countStandEvents(segments: PostureSegment[]) {
  let count = 0;
  for (let index = 1; index < segments.length; index += 1) {
    if (
      segments[index].posture === 'away' &&
      segments[index - 1].posture !== 'away' &&
      segments[index].startMinute - segments[index - 1].endMinute <=
        10 / 60
    ) {
      count += 1;
    }
  }
  return count;
}

function minuteLabel(minute: number) {
  const hours = Math.floor(minute / 60);
  const minutes = minute % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function buildTags(stats: DayStats) {
  const tags: string[] = [];
  if (stats.longestSitMinutes > 90) tags.push('连续久坐');
  if (stats.uprightPercentage >= 90) tags.push('坐姿稳定');
  if (stats.standCount > 0) tags.push(`起身${stats.standCount}次`);
  return tags;
}

export function buildDayReportFromStoredSegments(
  date: string,
  storedSegments: RealtimePostureSegment[],
): DayReport | null {
  const segments = normalizedPostureSegments(date, storedSegments);
  const firstSeated = segments.find((segment) => segment.posture !== 'away');
  if (!firstSeated) return null;

  const axisStart = Math.max(
    0,
    Math.floor(segments[0].startMinute / 60) * 60,
  );
  const latestEnd = segments.at(-1)?.endMinute ?? axisStart + 60;
  const axisEnd = Math.min(
    24 * 60,
    Math.max(axisStart + 60, Math.ceil(latestEnd / 60) * 60),
  );
  const standCount = countStandEvents(segments);
  const stats = buildDayStats(segments, axisStart, axisEnd, standCount);
  if (stats.seatedMinutes === 0) return null;
  const score = buildScore(stats);
  const draft = {
    date,
    axisStart,
    axisEnd,
    firstSeatedAt: minuteLabel(firstSeated.startMinute),
    stats,
    score,
    segments,
  };

  return {
    ...draft,
    aiSummary: buildDailyInsight(draft),
    tags: buildTags(stats),
  };
}

export function validateDayReport(report: DayReport): string[] {
  const issues: string[] = [];
  const sorted = [...report.segments].sort(
    (a, b) => a.startMinute - b.startMinute,
  );
  for (let index = 0; index < sorted.length; index += 1) {
    const segment = sorted[index];
    if (segment.endMinute <= segment.startMinute) {
      issues.push(`片段 ${index + 1} 的结束时间必须晚于开始时间`);
    }
    if (
      segment.startMinute < report.axisStart ||
      segment.endMinute > report.axisEnd
    ) {
      issues.push(`片段 ${index + 1} 超出日报时间轴`);
    }
    if (
      index > 0 &&
      sorted[index - 1].endMinute > segment.startMinute
    ) {
      issues.push(`片段 ${index} 与 ${index + 1} 存在重叠`);
    }
  }
  if (report.axisEnd <= report.axisStart) {
    issues.push('日报时间轴结束时间必须晚于开始时间');
  }
  if (report.stats.seatedMinutes <= 0) {
    issues.push('日报必须包含真实坐姿时长');
  }
  return issues;
}
