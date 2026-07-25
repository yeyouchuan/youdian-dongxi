import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  formatChineseMonthDay,
  parseISODate,
} from '@/domain/date-utils';
import { heatmapTone, HeatmapTone } from '@/domain/trends';
import { ReportTrendPoint } from '@/domain/types';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

const TONE_STYLES: Record<HeatmapTone, { backgroundColor: string; color: string }> = {
  missing: { backgroundColor: Palette.surfaceMuted, color: Palette.textMuted },
  preliminary: { backgroundColor: '#FFF2D6', color: '#8A5700' },
  risk: { backgroundColor: '#FFD7DE', color: '#9E1731' },
  watch: { backgroundColor: '#FFE8B8', color: '#7A4A00' },
  good: { backgroundColor: '#DDF3E4', color: '#176B35' },
  great: { backgroundColor: '#BCE8CA', color: '#0D5A29' },
};

function mondayIndex(date: string) {
  const day = parseISODate(date).getUTCDay();
  return day === 0 ? 6 : day - 1;
}

export function TrendHeatmap({
  points,
  selectedDate,
  onSelect,
}: {
  points: ReportTrendPoint[];
  selectedDate: string;
  onSelect: (date: string) => void;
}) {
  const padded: (ReportTrendPoint | null)[] = [
    ...Array.from({ length: points[0] ? mondayIndex(points[0].date) : 0 }, () => null),
    ...points,
  ];
  while (padded.length % 7 !== 0) padded.push(null);
  const rows = Array.from({ length: padded.length / 7 }, (_, index) =>
    padded.slice(index * 7, index * 7 + 7),
  );

  return (
    <View style={styles.wrap}>
      <View style={styles.weekdayRow}>
        {WEEKDAYS.map((weekday) => (
          <Text key={weekday} style={styles.weekday}>
            {weekday}
          </Text>
        ))}
      </View>
      {rows.map((row, rowIndex) => (
        <View key={rowIndex} style={styles.row}>
          {row.map((point, columnIndex) => {
            if (!point) return <View key={`empty-${columnIndex}`} style={styles.cell} />;
            const tone = heatmapTone(point.score, point.confidence);
            const toneStyle = TONE_STYLES[tone];
            const selected = point.date === selectedDate;
            return (
              <Pressable
                key={point.date}
                accessibilityRole="button"
                accessibilityLabel={`${formatChineseMonthDay(point.date)}，${
                  point.score === null
                    ? point.hasData
                      ? '数据不足'
                      : '无坐垫数据'
                    : `${point.confidence === 'preliminary' ? '初步' : '稳定'}健康得分${point.score}分`
                }`}
                accessibilityState={{ selected }}
                onPress={() => onSelect(point.date)}
                style={({ pressed }) => [
                  styles.cell,
                  styles.dataCell,
                  { backgroundColor: toneStyle.backgroundColor },
                  tone === 'missing' && styles.missingCell,
                  selected && styles.selectedCell,
                  pressed && styles.pressed,
                ]}>
                <Text style={[styles.cellText, { color: toneStyle.color }]}>
                  {point.score ?? '—'}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ))}
      <View style={styles.legend}>
        {[
          ['无数据', 'missing'],
          ['初步', 'preliminary'],
          ['需关注', 'risk'],
          ['待改善', 'watch'],
          ['良好', 'good'],
          ['优秀', 'great'],
        ].map(([label, tone]) => (
          <View key={tone} style={styles.legendItem}>
            <View
              style={[
                styles.legendSwatch,
                { backgroundColor: TONE_STYLES[tone as HeatmapTone].backgroundColor },
              ]}
            />
            <Text style={styles.legendText}>{label}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: Spacing.lg,
    gap: 6,
  },
  weekdayRow: {
    flexDirection: 'row',
    gap: 6,
    marginBottom: 2,
  },
  weekday: {
    flex: 1,
    color: Palette.textMuted,
    fontSize: 11,
    textAlign: 'center',
  },
  row: {
    flexDirection: 'row',
    gap: 6,
  },
  cell: {
    flex: 1,
    aspectRatio: 1,
  },
  dataCell: {
    minHeight: 38,
    borderRadius: Radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  missingCell: {
    borderStyle: 'dashed',
    borderColor: Palette.border,
  },
  selectedCell: {
    borderColor: Palette.text,
  },
  cellText: {
    fontSize: 11,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  pressed: {
    opacity: 0.64,
  },
  legend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.md,
    marginTop: Spacing.sm,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  legendSwatch: {
    width: 12,
    height: 12,
    borderRadius: 4,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Palette.border,
  },
  legendText: {
    color: Palette.textMuted,
    fontSize: 11,
  },
});
