import { localDateForTimestamp } from '@/domain/date-utils';
import { buildStateOfMindPresentation } from '@/domain/emotion';
import { HealthKitSample, HealthMetric } from '@/domain/types';
import { HEALTH_TYPES } from '@/services/apple-health-adapter';

interface SensitiveMetricVisibility {
  menstrual: boolean;
  stateOfMind: boolean;
}

function sortedSamples(
  samples: HealthKitSample[],
  typeIdentifier: string,
) {
  return samples
    .filter((sample) => sample.typeIdentifier === typeIdentifier)
    .sort(
      (a, b) => Date.parse(b.startDate) - Date.parse(a.startDate),
    );
}

function samplesOnDate(
  samples: HealthKitSample[],
  typeIdentifier: string,
  date: string,
) {
  return sortedSamples(samples, typeIdentifier).filter(
    (sample) => localDateForTimestamp(sample.startDate) === date,
  );
}

function latestAtOrBeforeDate(
  samples: HealthKitSample[],
  typeIdentifier: string,
  date: string,
) {
  return sortedSamples(samples, typeIdentifier).find(
    (sample) => localDateForTimestamp(sample.startDate) <= date,
  );
}

function appleSource(sample: HealthKitSample) {
  return `Apple Health · ${sample.sourceName || '未知来源'}`;
}

function measuredAtText(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
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

function hiddenMetric(
  type: HealthMetric['type'],
  label: string,
): HealthMetric {
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

function restingHeartRateMetric(sample?: HealthKitSample): HealthMetric {
  if (!sample || typeof sample.value !== 'number') {
    return metricPlaceholder('restingHeartRate', '静息心率');
  }
  return {
    type: 'restingHeartRate',
    label: '静息心率',
    value: String(Math.round(sample.value)),
    unit: 'bpm',
    caption: `记录于 ${measuredAtText(sample.startDate)}`,
    tone: 'info',
    source: appleSource(sample),
    measuredAt: sample.startDate,
  };
}

function hrvMetric(sample?: HealthKitSample): HealthMetric {
  if (!sample || typeof sample.value !== 'number') {
    return metricPlaceholder('hrv', 'HRV（SDNN）');
  }
  return {
    type: 'hrv',
    label: 'HRV（SDNN）',
    value: sample.value.toFixed(1),
    unit: 'ms',
    caption: `记录于 ${measuredAtText(sample.startDate)}`,
    tone: 'info',
    source: appleSource(sample),
    measuredAt: sample.startDate,
  };
}

function respiratoryRateMetric(sample?: HealthKitSample): HealthMetric {
  if (!sample || typeof sample.value !== 'number') {
    return metricPlaceholder('respiratoryRate', '呼吸频率');
  }
  return {
    type: 'respiratoryRate',
    label: '呼吸频率',
    value: sample.value.toFixed(1),
    unit: '次/分',
    caption: `记录于 ${measuredAtText(sample.startDate)}`,
    tone: 'info',
    source: appleSource(sample),
    measuredAt: sample.startDate,
  };
}

function bodyMassMetric(sample?: HealthKitSample): HealthMetric {
  if (!sample || typeof sample.value !== 'number') {
    return metricPlaceholder('bodyMass', '体重');
  }
  return {
    type: 'bodyMass',
    label: '体重',
    value: sample.value.toFixed(1),
    unit: 'kg',
    caption: `最近记录 · ${measuredAtText(sample.startDate)}`,
    tone: 'info',
    source: appleSource(sample),
    measuredAt: sample.startDate,
  };
}

function stateOfMindMetric(
  samples: HealthKitSample[],
  sample: HealthKitSample | undefined,
  visible: boolean,
): HealthMetric {
  if (!visible) return hiddenMetric('stateOfMind', '心境记录');
  if (!sample) {
    return metricPlaceholder('stateOfMind', '心境记录', true);
  }
  const presentation = buildStateOfMindPresentation(
    samples,
    localDateForTimestamp(sample.startDate),
  );
  if (presentation.kind === 'unavailable') {
    return metricPlaceholder('stateOfMind', '心境记录', true);
  }
  return {
    type: 'stateOfMind',
    label: '心境记录',
    value: presentation.label,
    caption: `用户主动记录 · ${measuredAtText(sample.startDate)}`,
    tone: 'info',
    source: appleSource(sample),
    measuredAt: sample.startDate,
    sensitive: true,
  };
}

function menstrualMetric(
  sample: HealthKitSample | undefined,
  visible: boolean,
): HealthMetric {
  if (!visible) return hiddenMetric('menstrualCycle', '女性经期');
  if (!sample || typeof sample.value !== 'number') {
    return metricPlaceholder('menstrualCycle', '女性经期', true);
  }
  const flowLabels: Record<number, string> = {
    1: '未指定',
    2: '较少',
    3: '中等',
    4: '较多',
    5: '无',
  };
  return {
    type: 'menstrualCycle',
    label: '女性经期',
    value: '已记录',
    caption: `经量${flowLabels[sample.value] ?? '已记录'} · ${measuredAtText(sample.startDate)}`,
    tone: 'cycle',
    source: appleSource(sample),
    measuredAt: sample.startDate,
    sensitive: true,
  };
}

function buildMetrics(
  samples: HealthKitSample[],
  selection: {
    resting?: HealthKitSample;
    hrv?: HealthKitSample;
    respiratory?: HealthKitSample;
    bodyMass?: HealthKitSample;
    stateOfMind?: HealthKitSample;
    menstrual?: HealthKitSample;
  },
  sensitive: SensitiveMetricVisibility,
) {
  return [
    restingHeartRateMetric(selection.resting),
    hrvMetric(selection.hrv),
    respiratoryRateMetric(selection.respiratory),
    bodyMassMetric(selection.bodyMass),
    stateOfMindMetric(
      samples,
      selection.stateOfMind,
      sensitive.stateOfMind,
    ),
    menstrualMetric(selection.menstrual, sensitive.menstrual),
  ];
}

export function buildReportHealthMetrics(
  samples: HealthKitSample[],
  date: string,
  showSensitive: boolean,
): HealthMetric[] {
  return buildMetrics(
    samples,
    {
      resting: samplesOnDate(
        samples,
        HEALTH_TYPES.restingHeartRate,
        date,
      )[0],
      hrv: samplesOnDate(samples, HEALTH_TYPES.hrv, date)[0],
      respiratory: samplesOnDate(
        samples,
        HEALTH_TYPES.respiratoryRate,
        date,
      )[0],
      bodyMass: latestAtOrBeforeDate(
        samples,
        HEALTH_TYPES.bodyMass,
        date,
      ),
      stateOfMind: samplesOnDate(
        samples,
        HEALTH_TYPES.stateOfMind,
        date,
      )[0],
      menstrual: samplesOnDate(
        samples,
        HEALTH_TYPES.menstrualFlow,
        date,
      )[0],
    },
    {
      menstrual: showSensitive,
      stateOfMind: showSensitive,
    },
  );
}

export function buildLatestHealthMetrics(
  samples: HealthKitSample[],
  sensitive: SensitiveMetricVisibility,
): HealthMetric[] {
  return buildMetrics(
    samples,
    {
      resting: sortedSamples(
        samples,
        HEALTH_TYPES.restingHeartRate,
      )[0],
      hrv: sortedSamples(samples, HEALTH_TYPES.hrv)[0],
      respiratory: sortedSamples(
        samples,
        HEALTH_TYPES.respiratoryRate,
      )[0],
      bodyMass: sortedSamples(samples, HEALTH_TYPES.bodyMass)[0],
      stateOfMind: sortedSamples(
        samples,
        HEALTH_TYPES.stateOfMind,
      )[0],
      menstrual: sortedSamples(
        samples,
        HEALTH_TYPES.menstrualFlow,
      )[0],
    },
    sensitive,
  );
}
