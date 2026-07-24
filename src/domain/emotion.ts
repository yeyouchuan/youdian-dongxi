import { EmotionPresentation, HealthKitSample } from '@/domain/types';
import { localDateForTimestamp } from '@/domain/date-utils';

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

function parseStateOfMindValue(value: HealthKitSample['value']) {
  if (typeof value !== 'string') return null;
  try {
    return JSON.parse(value) as { labels?: number[]; valence?: number };
  } catch {
    return null;
  }
}

export function buildStateOfMindPresentation(
  samples: HealthKitSample[],
  reportDate: string,
): EmotionPresentation {
  const daySamples = samples.filter(
    (sample) => localDateForTimestamp(sample.startDate) === reportDate,
  );
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
    };
  }

  return { kind: 'unavailable', label: '暂无记录', source: 'none' };
}
