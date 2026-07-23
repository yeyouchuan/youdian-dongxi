import { addDays } from '@/domain/date-utils';
import {
  AXIS_END,
  AXIS_START,
  buildDailyInsight,
  buildDayStats,
  buildScore,
  DEMO_REPORT,
  DEMO_REPORT_DATE,
  DEMO_SEGMENTS,
} from '@/domain/report';
import { DayReport, PostureSegment } from '@/domain/types';

const HISTORY_DAYS = 60;

function shiftTimestampDate(timestamp: string, date: string) {
  return `${date}${timestamp.slice(10)}`;
}

function segmentsForOffset(offset: number): PostureSegment[] {
  if (offset === 0) return DEMO_SEGMENTS;

  const durations = DEMO_SEGMENTS.map(
    (segment) => segment.endMinute - segment.startMinute,
  );
  const longSitDelta = ((offset * 7) % 37) - 18;
  const legCrossDelta = ((offset * 5) % 19) - 9;

  durations[3] -= longSitDelta;
  durations[12] += longSitDelta;
  durations[4] -= legCrossDelta;
  durations[5] += legCrossDelta;

  let cursor = DEMO_SEGMENTS[0].startMinute;
  return DEMO_SEGMENTS.map((segment, index) => {
    const next = {
      ...segment,
      startMinute: cursor,
      endMinute: cursor + durations[index],
    };
    cursor = next.endMinute;
    return next;
  });
}

function reportForOffset(offset: number): DayReport {
  if (offset === 0) return DEMO_REPORT;

  const date = addDays(DEMO_REPORT_DATE, -offset);
  const segments = segmentsForOffset(offset);
  const standCount = 9 + ((offset * 3) % 7);
  const stats = buildDayStats(segments, AXIS_START, AXIS_END, standCount);
  const score = buildScore(stats);
  const report: DayReport = {
    ...DEMO_REPORT,
    date,
    segments,
    stats,
    score,
    pressureSamples: DEMO_REPORT.pressureSamples.map((sample) => ({
      ...sample,
      timestamp: shiftTimestampDate(sample.timestamp, date),
    })),
    hrvRecords: DEMO_REPORT.hrvRecords.map((record) => ({
      ...record,
      timestamp: shiftTimestampDate(record.timestamp, date),
    })),
    weightRecords: DEMO_REPORT.weightRecords.map((record, index) => ({
      ...record,
      date: addDays(date, index - 2),
    })),
    tags:
      stats.longestSitMinutes >= 125
        ? ['连续久坐', '午后专注', '需要起身']
        : stats.legCrossMinutes >= 45
          ? ['二郎腿偏多', '午后困倦']
          : ['坐姿稳定', '起身规律'],
    aiSummary: '',
  };
  return { ...report, aiSummary: buildDailyInsight(report) };
}

function shouldInclude(offset: number) {
  return offset === 0 || (offset % 6 !== 0 && offset % 11 !== 0);
}

export const DEMO_REPORTS = Array.from({ length: HISTORY_DAYS }, (_, offset) => offset)
  .filter(shouldInclude)
  .map(reportForOffset)
  .sort((a, b) => a.date.localeCompare(b.date));

export function getDemoReport(date: string) {
  return DEMO_REPORTS.find((report) => report.date === date) ?? null;
}

export function getDemoReports(startDate: string, endDate: string) {
  return DEMO_REPORTS.filter(
    (report) => report.date >= startDate && report.date <= endDate,
  );
}
