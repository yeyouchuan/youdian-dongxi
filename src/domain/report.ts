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
  forward: '重心前移',
  recline: '后仰',
  edge: '坐前缘',
  other: '其他坐姿',
  away: '离座',
};

export const POSTURE_COLORS: Record<PostureState, string> = {
  upright: '#34C759',
  leanLeft: '#FF9F0A',
  leanRight: '#FFB340',
  forward: '#FF7A45',
  recline: '#5E8CE6',
  edge: '#FF453A',
  other: '#AF52DE',
  away: '#D1D1D6',
};

export const POSTURE_ORDER: PostureState[] = [
  'upright',
  'leanLeft',
  'leanRight',
  'forward',
  'recline',
  'edge',
  'other',
  'away',
];

const VALID_BREAK_MINUTES = 2;
const SEGMENT_JOIN_GAP_MINUTES = 10 / 60;
const SCORE_MINIMUM_MINUTES = 15;
const SCORE_STABLE_MINUTES = 60;

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
  return value > 0 ? Math.max(1, Math.floor(value)) : 0;
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
      if (segmentDuration(segment) >= VALID_BREAK_MINUTES) {
        currentStart = null;
        currentEnd = null;
      } else if (currentEnd !== null) {
        currentEnd = Math.max(currentEnd, segment.endMinute);
        longest = Math.max(
          longest,
          currentEnd - (currentStart ?? currentEnd),
        );
      }
      continue;
    }

    if (
      currentStart === null ||
      currentEnd === null ||
      segment.startMinute - currentEnd > SEGMENT_JOIN_GAP_MINUTES
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

function longestNonUprightSit(segments: PostureSegment[]) {
  const sorted = [...segments].sort(
    (a, b) => a.startMinute - b.startMinute,
  );
  let longest = 0;
  let currentStart: number | null = null;
  let currentEnd: number | null = null;

  for (const segment of sorted) {
    if (segment.posture === 'away' || segment.posture === 'upright') {
      currentStart = null;
      currentEnd = null;
      continue;
    }

    if (
      currentStart === null ||
      currentEnd === null ||
      segment.startMinute - currentEnd > SEGMENT_JOIN_GAP_MINUTES
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

function countValidBreaks(segments: PostureSegment[]) {
  const sorted = [...segments].sort(
    (a, b) => a.startMinute - b.startMinute,
  );
  let count = 0;
  for (let index = 1; index < sorted.length; index += 1) {
    const current = sorted[index];
    const previous = sorted[index - 1];
    if (
      current.posture === 'away' &&
      previous.posture !== 'away' &&
      segmentDuration(current) >= VALID_BREAK_MINUTES &&
      current.startMinute - previous.endMinute <= SEGMENT_JOIN_GAP_MINUTES
    ) {
      count += 1;
    }
  }
  return count;
}

export function buildDayStats(
  segments: PostureSegment[],
  _axisStart: number,
  _axisEnd: number,
): DayStats {
  const totals = new Map<PostureState, number>([
    ['upright', 0],
    ['leanLeft', 0],
    ['leanRight', 0],
    ['forward', 0],
    ['recline', 0],
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
  const validBreakCount = countValidBreaks(segments);
  const dominantNonUprightPosture =
    POSTURE_ORDER.filter(
      (posture): posture is SeatedPosture =>
        posture !== 'upright' && posture !== 'away',
    )
      .map((posture) => ({
        posture,
        minutes: totals.get(posture) ?? 0,
      }))
      .sort((a, b) => b.minutes - a.minutes)[0] ?? null;

  return {
    seatedMinutes,
    seatedText: durationText(seatedMinutes),
    observedMinutes,
    uprightPercentage:
      seatedMinutesRaw === 0
        ? 0
        : Math.round((uprightMinutesRaw / seatedMinutesRaw) * 100),
    standCount: validBreakCount,
    validBreakCount,
    breakTarget: getBreakTarget(seatedMinutes),
    nonUprightMinutes: wholeMinutes(nonUprightMinutesRaw),
    longestSitMinutes: wholeMinutes(longestContinuousSit(segments)),
    longestNonUprightMinutes: wholeMinutes(
      longestNonUprightSit(segments),
    ),
    dominantNonUprightPosture:
      dominantNonUprightPosture &&
      dominantNonUprightPosture.minutes > 0
        ? dominantNonUprightPosture.posture
        : null,
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

export function getBreakTarget(seatedMinutes: number) {
  return Math.floor(Math.max(0, seatedMinutes) / 60);
}

export const getStandTarget = getBreakTarget;

function interpolatePoints(
  minutes: number,
  stops: readonly (readonly [number, number])[],
) {
  if (minutes <= stops[0][0]) return stops[0][1];
  for (let index = 1; index < stops.length; index += 1) {
    const [endMinute, endPoints] = stops[index];
    if (minutes > endMinute) continue;
    const [startMinute, startPoints] = stops[index - 1];
    const progress =
      (minutes - startMinute) / (endMinute - startMinute);
    return Math.round(
      startPoints + (endPoints - startPoints) * progress,
    );
  }
  return stops.at(-1)?.[1] ?? 0;
}

function scoreStatus(value: number | null, confidence: ScoreSummary['confidence']) {
  if (value === null) return '数据不足';
  if (confidence === 'preliminary') return '初步评分';
  if (value >= 90) return '优秀';
  if (value >= 80) return '良好';
  if (value >= 70) return '待改善';
  return '需关注';
}

export function buildScore(stats: DayStats): ScoreSummary {
  const confidence: ScoreSummary['confidence'] =
    stats.seatedMinutes < SCORE_MINIMUM_MINUTES
      ? 'insufficient'
      : stats.seatedMinutes < SCORE_STABLE_MINUTES
        ? 'preliminary'
        : 'stable';
  const posturePoints = Math.round(
    65 * (stats.uprightPercentage / 100),
  );
  const continuousSitPoints = interpolatePoints(
    stats.longestSitMinutes,
    [
      [0, 25],
      [60, 25],
      [75, 20],
      [90, 12],
      [120, 4],
      [150, 0],
    ],
  );
  const breakPoints =
    stats.breakTarget === 0
      ? 10
      : Math.round(
          10 *
            Math.min(
              1,
              stats.validBreakCount / stats.breakTarget,
            ),
        );
  const breakdown: ScoreBreakdownItem[] = [
    {
      label: '坐姿质量',
      detail: `正坐 ${stats.uprightPercentage}% · 权重 65%`,
      points: posturePoints,
      maxPoints: 65,
    },
    {
      label: '连续久坐',
      detail:
        stats.longestSitMinutes <= 60
          ? `最长 ${stats.longestSitMinutes} 分钟 · 60 分钟内不扣分`
          : `最长 ${stats.longestSitMinutes} 分钟 · 超过 60 分钟开始降分`,
      points: continuousSitPoints,
      maxPoints: 25,
    },
    {
      label: '有效离座',
      detail:
        stats.breakTarget === 0
          ? '在座不足 60 分钟，暂不要求离座次数'
          : `连续离座满 2 分钟计一次 · ${stats.validBreakCount}/${stats.breakTarget} 次`,
      points: breakPoints,
      maxPoints: 10,
    },
  ];
  const computedValue = breakdown.reduce(
    (total, item) => total + item.points,
    0,
  );
  const value = confidence === 'insufficient' ? null : computedValue;
  const mainGap = [...breakdown]
    .map((item) => ({
      gap: item.maxPoints - item.points,
      label:
        item.label === '坐姿质量'
          ? `正坐比例 ${stats.uprightPercentage}%`
          : item.label === '连续久坐'
            ? `连续久坐 ${stats.longestSitMinutes} 分钟`
            : `有效离座 ${stats.validBreakCount}/${stats.breakTarget} 次`,
    }))
    .sort((a, b) => b.gap - a.gap)[0];

  return {
    value,
    status: scoreStatus(value, confidence),
    isOK: value !== null && value >= 80,
    confidence,
    mainDrag:
      confidence === 'insufficient'
        ? `至少记录 ${SCORE_MINIMUM_MINUTES} 分钟后生成初步评分`
        : mainGap && mainGap.gap > 0
          ? mainGap.label
          : '记录时段各项表现均达到满分',
    breakdown,
  };
}

export function buildDailyInsight(report: Pick<DayReport, 'stats' | 'score'>) {
  if (report.score.confidence === 'insufficient') {
    return `当前只有 ${report.stats.seatedMinutes} 分钟有效在座数据；记录满 15 分钟后会生成初步评分。`;
  }
  if (report.stats.longestSitMinutes >= 90) {
    return `已记录时段最值得改善的是连续久坐 ${report.stats.longestSitMinutes} 分钟。45 分钟时可开始准备活动，尽量不要连续超过 60 分钟。`;
  }
  if (
    report.stats.dominantNonUprightPosture &&
    report.stats.longestNonUprightMinutes >= 10
  ) {
    return `主要非正坐类型是${POSTURE_LABELS[report.stats.dominantNonUprightPosture]}，最长连续 ${report.stats.longestNonUprightMinutes} 分钟。可以先调整坐垫位置和双脚支撑。`;
  }
  if (report.stats.uprightPercentage >= 90) {
    return `已记录时段正坐比例达到 ${report.stats.uprightPercentage}%，真实坐姿记录整体稳定。`;
  }
  return `已记录时段正坐比例为 ${report.stats.uprightPercentage}%，记录到 ${report.stats.validBreakCount} 次有效离座。`;
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

function minuteLabel(minute: number) {
  const hours = Math.floor(minute / 60);
  const minutes = minute % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function buildTags(stats: DayStats) {
  const tags: string[] = [];
  if (stats.longestSitMinutes > 60) tags.push('连续久坐');
  if (stats.uprightPercentage >= 90) tags.push('坐姿稳定');
  if (stats.validBreakCount > 0) {
    tags.push(`有效离座${stats.validBreakCount}次`);
  }
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
  const stats = buildDayStats(segments, axisStart, axisEnd);
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
