import { addDays, buildDateRange } from '@/domain/date-utils';
import {
  DayReport,
  ReportTrendPoint,
  ReportTrendSummary,
  ScoreConfidence,
  TrendRangeDays,
} from '@/domain/types';

export type HeatmapTone =
  | 'missing'
  | 'preliminary'
  | 'risk'
  | 'watch'
  | 'good'
  | 'great';

function average(values: number[]) {
  if (values.length === 0) return null;
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length);
}

function pointForDate(date: string, report?: DayReport): ReportTrendPoint {
  if (!report) {
    return {
      date,
      hasData: false,
      score: null,
      confidence: null,
      uprightPercentage: null,
      longestSitMinutes: null,
      standCount: null,
    };
  }

  return {
    date,
    hasData: true,
    score: report.score.value,
    confidence: report.score.confidence,
    uprightPercentage: report.stats.uprightPercentage,
    longestSitMinutes: report.stats.longestSitMinutes,
    standCount: report.stats.validBreakCount,
  };
}

function averageScore(reports: DayReport[]) {
  return average(
    reports
      .map((report) => report.score.value)
      .filter((value): value is number => value !== null),
  );
}

export function buildReportTrendSummary(
  reports: DayReport[],
  previousReports: DayReport[],
  endDate: string,
  rangeDays: TrendRangeDays,
): ReportTrendSummary {
  const startDate = addDays(endDate, -(rangeDays - 1));
  const reportByDate = new Map(reports.map((report) => [report.date, report]));
  const points = buildDateRange(startDate, endDate).map((date) =>
    pointForDate(date, reportByDate.get(date)),
  );
  const currentReports = points
    .map((point) => reportByDate.get(point.date))
    .filter((report): report is DayReport => Boolean(report));
  const stableReports = currentReports.filter(
    (report) =>
      report.score.confidence === 'stable' &&
      report.score.value !== null,
  );
  const stablePreviousReports = previousReports.filter(
    (report) =>
      report.score.confidence === 'stable' &&
      report.score.value !== null,
  );
  const currentAverageScore = averageScore(stableReports);
  const previousAverageScore = averageScore(stablePreviousReports);

  return {
    rangeDays,
    startDate,
    endDate,
    points,
    dataDays: currentReports.length,
    stableDays: stableReports.length,
    preliminaryDays: currentReports.filter(
      (report) => report.score.confidence === 'preliminary',
    ).length,
    averageScore: currentAverageScore,
    averageUprightPercentage: average(
      stableReports.map((report) => report.stats.uprightPercentage),
    ),
    averageLongestSitMinutes: average(
      stableReports.map((report) => report.stats.longestSitMinutes),
    ),
    averageStandCount: average(
      stableReports.map((report) => report.stats.validBreakCount),
    ),
    comparison: {
      previousAverageScore,
      scoreDelta:
        currentAverageScore === null || previousAverageScore === null
          ? null
          : currentAverageScore - previousAverageScore,
    },
  };
}

export function getTrendDateRanges(endDate: string, rangeDays: TrendRangeDays) {
  const currentStartDate = addDays(endDate, -(rangeDays - 1));
  const previousEndDate = addDays(currentStartDate, -1);
  return {
    current: { startDate: currentStartDate, endDate },
    previous: {
      startDate: addDays(previousEndDate, -(rangeDays - 1)),
      endDate: previousEndDate,
    },
  };
}

export function heatmapTone(
  score: number | null,
  confidence: ScoreConfidence | null = null,
): HeatmapTone {
  if (score === null) return 'missing';
  if (confidence === 'preliminary') return 'preliminary';
  if (score < 70) return 'risk';
  if (score < 80) return 'watch';
  if (score < 90) return 'good';
  return 'great';
}

export function buildTrendAccessibilityLabel(summary: ReportTrendSummary) {
  if (summary.averageScore === null) {
    return summary.dataDays === 0
      ? `最近${summary.rangeDays}天没有坐垫数据`
      : `最近${summary.rangeDays}天有坐垫数据，但没有达到稳定评分所需的60分钟`;
  }

  const comparison =
    summary.comparison.scoreDelta === null
      ? '暂无上一周期对比'
      : summary.comparison.scoreDelta === 0
        ? '与上一周期持平'
        : `较上一周期${summary.comparison.scoreDelta > 0 ? '提高' : '下降'}${Math.abs(summary.comparison.scoreDelta)}分`;

  return `最近${summary.rangeDays}天平均健康得分${summary.averageScore}分，${summary.stableDays}天为稳定评分，${comparison}`;
}
