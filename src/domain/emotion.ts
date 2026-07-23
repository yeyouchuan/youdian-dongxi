import { EmotionBand, EmotionPresentation, HealthKitSample } from '@/domain/types';

export const STATE_OF_MIND_LABELS: Record<number, string> = {
  1: '惊叹',
  2: '愉悦',
  3: '生气',
  4: '焦虑',
  5: '羞愧',
  6: '勇敢',
  7: '平静',
  8: '满足',
  9: '失望',
  10: '沮丧',
  11: '厌恶',
  12: '尴尬',
  13: '兴奋',
  14: '挫败',
  15: '感恩',
  16: '内疚',
  17: '开心',
  18: '无望',
  19: '烦躁',
  20: '嫉妒',
  21: '喜悦',
  22: '孤独',
  23: '热情',
  24: '安宁',
  25: '自豪',
  26: '释然',
  27: '难过',
  28: '害怕',
  29: '有压力',
  30: '惊讶',
  31: '担忧',
  32: '恼火',
  33: '自信',
  34: '疲惫',
  35: '有希望',
  36: '无感',
  37: '不堪重负',
  38: '满意',
};

export function mapHrvToEmotion(valueMs: number, baselineMs: number): EmotionBand {
  const ratio = baselineMs <= 0 ? 0 : valueMs / baselineMs;
  if (ratio >= 1.05) return '放松';
  if (ratio >= 0.85) return '平静';
  if (ratio >= 0.7) return '紧张';
  return '压力偏高';
}

export function calculateHrvBaseline(
  samples: HealthKitSample[],
  reportDate: string,
): number | null {
  const reportTime = new Date(`${reportDate}T23:59:59`).getTime();
  const earliest = reportTime - 30 * 24 * 60 * 60 * 1000;
  const eligible = samples
    .filter(
      (sample) =>
        sample.typeIdentifier === 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN' &&
        typeof sample.value === 'number',
    )
    .filter((sample) => {
      const time = new Date(sample.startDate).getTime();
      return time >= earliest && time <= reportTime;
    });

  const distinctDates = new Set(eligible.map((sample) => sample.startDate.slice(0, 10)));
  if (distinctDates.size < 5) return null;

  const values = eligible
    .map((sample) => sample.value as number)
    .sort((a, b) => a - b);
  const middle = Math.floor(values.length / 2);
  return values.length % 2 === 0
    ? (values[middle - 1] + values[middle]) / 2
    : values[middle];
}

function parseStateOfMindValue(value: HealthKitSample['value']) {
  if (typeof value !== 'string') return null;
  try {
    return JSON.parse(value) as { labels?: number[]; valence?: number };
  } catch {
    return null;
  }
}

export function buildEmotionPresentation(
  samples: HealthKitSample[],
  reportDate: string,
): EmotionPresentation {
  const daySamples = samples.filter((sample) => sample.startDate.slice(0, 10) === reportDate);
  const stateOfMind = daySamples
    .filter((sample) => sample.typeIdentifier === 'HKStateOfMindTypeIdentifier')
    .sort((a, b) => b.startDate.localeCompare(a.startDate))[0];

  if (stateOfMind) {
    const parsed = parseStateOfMindValue(stateOfMind.value);
    const label =
      parsed?.labels
        ?.map((item) => STATE_OF_MIND_LABELS[item])
        .filter(Boolean)
        .slice(0, 2)
        .join(' · ') || '已记录心境';
    return {
      kind: 'selfReported',
      label,
      source: 'appleHealthStateOfMind',
      measuredAt: stateOfMind.startDate,
      isEstimated: false,
    };
  }

  const latestHrv = daySamples
    .filter(
      (sample) =>
        sample.typeIdentifier === 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN' &&
        typeof sample.value === 'number',
    )
    .sort((a, b) => b.startDate.localeCompare(a.startDate))[0];

  if (!latestHrv) {
    return { kind: 'unavailable', label: '暂无数据', source: 'none', isEstimated: false };
  }

  const baseline = calculateHrvBaseline(samples, reportDate);
  if (baseline === null) {
    return {
      kind: 'buildingBaseline',
      label: '正在建立个人基线',
      source: 'appleHealthHrv',
      measuredAt: latestHrv.startDate,
      isEstimated: true,
    };
  }

  return {
    kind: 'estimated',
    label: mapHrvToEmotion(latestHrv.value as number, baseline),
    source: 'appleHealthHrv',
    measuredAt: latestHrv.startDate,
    isEstimated: true,
  };
}
