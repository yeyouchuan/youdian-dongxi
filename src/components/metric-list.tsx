import { Ionicons } from '@expo/vector-icons';
import { Platform, StyleSheet, Text, View } from 'react-native';

import { Palette, Spacing } from '@/constants/theme';
import { HealthMetric, MetricTone } from '@/domain/types';

interface MetricListProps {
  metrics: HealthMetric[];
}

const TONE_COLORS: Record<MetricTone, string> = {
  ok: Palette.emerald,
  warn: Palette.amber,
  info: Palette.teal,
  cycle: Palette.purple,
};

const METRIC_ICONS: Record<HealthMetric['type'], keyof typeof Ionicons.glyphMap> = {
  restingHeartRate: 'heart-outline',
  hrv: 'analytics-outline',
  stateOfMind: 'happy-outline',
  respiratoryRate: 'pulse-outline',
  bodyMass: 'scale-outline',
  menstrualCycle: 'calendar-outline',
};

export function MetricList({ metrics }: MetricListProps) {
  return (
    <View>
      {metrics.map((metric, index) => {
        const color = TONE_COLORS[metric.tone];
        return (
          <View
            key={metric.type}
            style={styles.row}>
            <View style={[styles.iconWrap, { backgroundColor: `${color}16` }]}>
              <Ionicons name={METRIC_ICONS[metric.type]} size={19} color={color} />
            </View>
            <View style={styles.labelWrap}>
              <Text style={styles.label}>{metric.label}</Text>
              <Text style={styles.source} numberOfLines={1}>
                {metric.source}
              </Text>
            </View>
            <View style={styles.valueWrap}>
              <View style={styles.valueRow}>
                <View style={[styles.valueDot, { backgroundColor: color }]} />
                <Text style={styles.value}>{metric.value}</Text>
                {metric.unit ? <Text style={styles.unit}>{metric.unit}</Text> : null}
              </View>
              <Text style={styles.caption} numberOfLines={2}>
                {metric.caption}
              </Text>
            </View>
          </View>
        );
      })}
      <Text style={styles.accuracy}>* 数据来自 Apple Health 原始记录，仅供健康参考</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 94,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    backgroundColor: Palette.surface,
    borderRadius: 22,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    marginBottom: Spacing.md,
    ...(Platform.OS === 'web'
      ? { boxShadow: '0 2px 10px rgba(0, 0, 0, 0.045)' }
      : {
          shadowColor: '#000000',
          shadowOpacity: 0.045,
          shadowRadius: 10,
          shadowOffset: { width: 0, height: 2 },
          elevation: 1,
        }),
  },
  iconWrap: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  labelWrap: {
    flex: 1,
    gap: 4,
  },
  label: {
    color: Palette.textSecondary,
    fontSize: 15,
    fontWeight: '600',
  },
  source: {
    color: Palette.textMuted,
    fontSize: 10,
  },
  valueWrap: {
    maxWidth: '50%',
    alignItems: 'flex-end',
    gap: 4,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 5,
  },
  valueDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    alignSelf: 'center',
  },
  value: {
    color: Palette.text,
    fontSize: 25,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  unit: {
    color: Palette.textMuted,
    fontSize: 11,
  },
  caption: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 14,
    textAlign: 'right',
  },
  accuracy: {
    color: Palette.textMuted,
    fontSize: 10,
    marginTop: 0,
    paddingHorizontal: Spacing.xs,
  },
});
