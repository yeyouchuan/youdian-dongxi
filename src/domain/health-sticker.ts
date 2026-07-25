import { getBreakTarget } from '@/domain/report';
import {
  DayReport,
  HealthStickerKind,
  HealthStickerPresentation,
} from '@/domain/types';

function buildMetrics(report: DayReport) {
  return [
    {
      label: '正坐比例',
      value: `${report.stats.uprightPercentage}%`,
    },
    {
      label: '有效离座',
      value: `${report.stats.validBreakCount}次`,
    },
    {
      label: '最长久坐',
      value: `${report.stats.longestSitMinutes}分钟`,
    },
  ];
}

function buildScopeNote(
  report: DayReport,
  kind: Exclude<HealthStickerKind, 'balancedDay'>,
) {
  const warnings: string[] = [];
  if (report.stats.longestSitMinutes > 60) warnings.push('久坐');
  if (
    kind === 'uprightStable' &&
    report.stats.validBreakCount < getBreakTarget(report.stats.seatedMinutes)
  ) {
    warnings.push('有效离座次数');
  }

  if (warnings.length === 0) return undefined;
  const aspect = kind === 'uprightStable' ? '正坐比例' : '有效离座次数';
  return `这枚贴纸仅表示${aspect}达标；${warnings.join('、')}提醒仍需留意。`;
}

export function buildHealthStickerPresentation(
  report: DayReport,
): HealthStickerPresentation | null {
  if (report.score.confidence !== 'stable') return null;

  const { stats } = report;
  const standTarget = getBreakTarget(stats.seatedMinutes);
  const uprightStable = stats.uprightPercentage >= 90;
  const breakTargetMet =
    standTarget === 0 || stats.validBreakCount >= standTarget;
  const balancedDay =
    uprightStable &&
    stats.longestSitMinutes <= 60 &&
    breakTargetMet;

  const metrics = buildMetrics(report);

  if (balancedDay) {
    return {
      id: `${report.date}:balancedDay`,
      date: report.date,
      kind: 'balancedDay',
      title: '记录时段状态稳定',
      reason: `正坐 ${stats.uprightPercentage}%，最长久坐 ${stats.longestSitMinutes} 分钟，有效离座达到 ${standTarget} 次目标。`,
      advice: '保持现在的节奏，专注一段时间后继续起身活动。',
      metrics,
    };
  }

  if (uprightStable) {
    return {
      id: `${report.date}:uprightStable`,
      date: report.date,
      kind: 'uprightStable',
      title: '坐姿稳定',
      reason: `智能坐垫记录到正坐比例 ${stats.uprightPercentage}%，达到本项贴纸标准。`,
      advice: '继续保持正坐，也别忘了在连续坐一段时间后起身活动。',
      metrics,
      scopeNote: buildScopeNote(report, 'uprightStable'),
    };
  }

  if (breakTargetMet) {
    return {
      id: `${report.date}:breakTargetMet`,
      date: report.date,
      kind: 'breakTargetMet',
      title: '离座节奏达标',
      reason: `记录到 ${stats.validBreakCount} 次有效离座，达到按在座时长计算的 ${standTarget} 次目标。`,
      advice: '保持起身节奏，坐下时也可以留意双脚自然落地。',
      metrics,
      scopeNote: buildScopeNote(report, 'breakTargetMet'),
    };
  }

  return null;
}
