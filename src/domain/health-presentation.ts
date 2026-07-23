import { buildEmotionPresentation } from '@/domain/emotion';
import { DayReport, HealthKitSample, HealthMetric } from '@/domain/types';
import { HEALTH_TYPES } from '@/services/apple-health-adapter';

function samplesOnDate(samples: HealthKitSample[], typeIdentifier: string, date: string) {
  return samples
    .filter(
      (sample) =>
        sample.typeIdentifier === typeIdentifier && sample.startDate.slice(0, 10) === date,
    )
    .sort((a, b) => b.startDate.localeCompare(a.startDate));
}

function appleSource(sample: HealthKitSample) {
  return `Apple Health · ${sample.sourceName}`;
}

function metricPlaceholder(
  type: HealthMetric['type'],
  label: string,
  sensitive = false,
): HealthMetric {
  return {
    type,
    label,
    value: '暂无数据',
    caption: 'Apple Health 中暂无相关记录',
    tone: 'info',
    source: 'Apple Health',
    sensitive,
  };
}

function hiddenMetric(type: HealthMetric['type'], label: string): HealthMetric {
  return {
    type,
    label,
    value: '已隐藏',
    caption: '可在设置中选择显示',
    tone: type === 'menstrualCycle' ? 'cycle' : 'info',
    source: '隐私保护',
    sensitive: true,
  };
}

export function buildReportHealthMetrics(
  report: DayReport | null,
  samples: HealthKitSample[],
  date: string,
  showSensitive: boolean,
): HealthMetric[] {
  const baseByType = new Map(report?.healthMetrics.map((item) => [item.type, item]) ?? []);

  const resting = samplesOnDate(samples, HEALTH_TYPES.restingHeartRate, date)[0];
  const respiratory = samplesOnDate(samples, HEALTH_TYPES.respiratoryRate, date)[0];
  const bodyMass = samplesOnDate(samples, HEALTH_TYPES.bodyMass, date)[0];
  const menstrual = samplesOnDate(samples, HEALTH_TYPES.menstrualFlow, date)[0];

  const restingMetric: HealthMetric =
    resting && typeof resting.value === 'number'
      ? {
          type: 'restingHeartRate',
          label: '静息心率',
          value: String(Math.round(resting.value)),
          unit: 'bpm',
          caption: '静坐状态下更准确',
          tone: 'info',
          source: appleSource(resting),
          measuredAt: resting.startDate,
        }
      : baseByType.get('restingHeartRate') ??
        metricPlaceholder('restingHeartRate', '静息心率');

  const respiratoryMetric: HealthMetric =
    respiratory && typeof respiratory.value === 'number'
      ? {
          type: 'respiratoryRate',
          label: '呼吸频率',
          value: respiratory.value.toFixed(1),
          unit: 'brpm',
          caption: '静坐状态下更准确',
          tone: 'ok',
          source: appleSource(respiratory),
          measuredAt: respiratory.startDate,
        }
      : baseByType.get('respiratoryRate') ??
        metricPlaceholder('respiratoryRate', '呼吸频率');

  const bodyMassMetric: HealthMetric =
    bodyMass && typeof bodyMass.value === 'number'
      ? {
          type: 'bodyMass',
          label: '体重',
          value: bodyMass.value.toFixed(1),
          unit: 'kg',
          caption: '显示最近一次有效记录',
          tone: 'info',
          source: appleSource(bodyMass),
          measuredAt: bodyMass.startDate,
        }
      : baseByType.get('bodyMass') ?? metricPlaceholder('bodyMass', '体重');

  let emotionMetric: HealthMetric;
  if (!showSensitive) {
    emotionMetric = hiddenMetric('emotionReference', '情绪参考');
  } else {
    const emotion = buildEmotionPresentation(samples, date);
    emotionMetric =
      emotion.kind !== 'unavailable'
        ? {
            type: 'emotionReference',
            label: emotion.kind === 'selfReported' ? '心境记录' : '情绪参考',
            value: emotion.label,
            caption:
              emotion.kind === 'selfReported'
                ? '用户在 Apple Health 中主动记录'
                : '根据生理趋势估算 · 非心理诊断',
            tone: 'info',
            source:
              emotion.source === 'appleHealthStateOfMind'
                ? 'Apple Health 心境'
                : 'Apple Health HRV',
            measuredAt: emotion.measuredAt,
            isEstimated: emotion.isEstimated,
            sensitive: true,
          }
        : baseByType.get('emotionReference') ??
          metricPlaceholder('emotionReference', '情绪参考', true);
  }

  let menstrualMetric: HealthMetric;
  if (!showSensitive) {
    menstrualMetric = hiddenMetric('menstrualCycle', '女性经期');
  } else if (menstrual && typeof menstrual.value === 'number') {
    const flowLabels: Record<number, string> = {
      1: '未指定',
      2: '较少',
      3: '中等',
      4: '较多',
      5: '无',
    };
    menstrualMetric = {
      type: 'menstrualCycle',
      label: '女性经期',
      value: '已记录',
      caption: `经量${flowLabels[menstrual.value] ?? '已记录'} · 预计仅供参考`,
      tone: 'cycle',
      source: appleSource(menstrual),
      measuredAt: menstrual.startDate,
      sensitive: true,
    };
  } else {
    menstrualMetric =
      baseByType.get('menstrualCycle') ??
      metricPlaceholder('menstrualCycle', '女性经期', true);
  }

  return [
    restingMetric,
    emotionMetric,
    respiratoryMetric,
    bodyMassMetric,
    menstrualMetric,
  ];
}
