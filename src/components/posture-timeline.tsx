import { StyleSheet, Text, View } from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  POSTURE_COLORS,
  POSTURE_LABELS,
} from '@/domain/report';
import { PostureSegment, PostureState } from '@/domain/types';

interface PostureTimelineProps {
  segments: PostureSegment[];
  axisStart: number;
  axisEnd: number;
}

const LEGEND_ORDER: PostureState[] = ['upright', 'legsCrossed', 'away'];

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
  return (
    <View style={styles.wrap}>
      <View style={styles.track}>
        {segments.map((segment, index) => (
          <View
            key={`${segment.startMinute}-${segment.endMinute}`}
            accessibilityLabel={`${POSTURE_LABELS[segment.posture]} ${segment.endMinute - segment.startMinute}分钟`}
            style={{
              flexBasis: `${((segment.endMinute - segment.startMinute) / total) * 100}%`,
              flexGrow: 0,
              flexShrink: 0,
              backgroundColor: POSTURE_COLORS[segment.posture],
              borderLeftWidth: index === 0 ? 0 : 2,
              borderLeftColor: Palette.surface,
            }}
          />
        ))}
      </View>
      <View style={styles.axis}>
        <Text style={styles.axisText}>{timeLabel(axisStart)}</Text>
        <Text style={styles.axisText}>12:00</Text>
        <Text style={styles.axisText}>15:00</Text>
        <Text style={styles.axisText}>{timeLabel(axisEnd)}</Text>
      </View>
      <View style={styles.legend}>
        {LEGEND_ORDER.map((posture) => (
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
    flexDirection: 'row',
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
