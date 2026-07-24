import { StyleSheet, Text, View } from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  POSTURE_COLORS,
  POSTURE_LABELS,
  POSTURE_ORDER,
} from '@/domain/report';
import { PostureSegment } from '@/domain/types';

interface PostureTimelineProps {
  segments: PostureSegment[];
  axisStart: number;
  axisEnd: number;
}

function timeLabel(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `${String(hours).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}

export function PostureTimeline({
  segments,
  axisStart,
  axisEnd,
}: PostureTimelineProps) {
  const total = axisEnd - axisStart;
  const axisLabels = Array.from({ length: 4 }, (_, index) =>
    Math.round(axisStart + (total * index) / 3),
  );
  return (
    <View style={styles.wrap}>
      <View style={styles.track}>
        {segments.map((segment) => (
          <View
            key={`${segment.startMinute}-${segment.endMinute}-${segment.posture}`}
            accessibilityLabel={`${POSTURE_LABELS[segment.posture]} ${Math.max(
              1,
              Math.round(segment.endMinute - segment.startMinute),
            )}分钟`}
            style={{
              position: 'absolute',
              left: `${((segment.startMinute - axisStart) / total) * 100}%`,
              width: `${((segment.endMinute - segment.startMinute) / total) * 100}%`,
              top: 0,
              bottom: 0,
              backgroundColor: POSTURE_COLORS[segment.posture],
              borderLeftWidth: 1,
              borderRightWidth: 1,
              borderLeftColor: Palette.surface,
              borderRightColor: Palette.surface,
            }}
          />
        ))}
      </View>
      <View style={styles.axis}>
        {axisLabels.map((minute) => (
          <Text key={minute} style={styles.axisText}>
            {timeLabel(minute)}
          </Text>
        ))}
      </View>
      <View style={styles.legend}>
        {POSTURE_ORDER.map((posture) => (
          <View key={posture} style={styles.legendItem}>
            <View
              style={[styles.legendDot, { backgroundColor: POSTURE_COLORS[posture] }]}
            />
            <Text style={styles.legendText}>{POSTURE_LABELS[posture]}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: Spacing.md,
  },
  track: {
    height: 68,
    borderRadius: Radius.md,
    overflow: 'hidden',
    position: 'relative',
    backgroundColor: Palette.surfaceMuted,
  },
  axis: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  axisText: {
    color: Palette.textMuted,
    fontSize: 11,
    fontVariant: ['tabular-nums'],
  },
  legend: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.lg,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    color: Palette.textSecondary,
    fontSize: 12,
  },
});
