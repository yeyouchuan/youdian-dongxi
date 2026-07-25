import { StyleSheet, Text, View } from 'react-native';
import Svg, { Line } from 'react-native-svg';

import { Palette } from '@/constants/theme';

interface ScoreGaugeProps {
  score: number | null;
  status: string;
}

const TICK_COUNT = 46;
const CENTER_X = 160;
const CENTER_Y = 144;
const OUTER_RADIUS = 116;
const INNER_RADIUS = 94;

function point(angleDegrees: number, radius: number) {
  const radians = (angleDegrees * Math.PI) / 180;
  return {
    x: CENTER_X + Math.cos(radians) * radius,
    y: CENTER_Y + Math.sin(radians) * radius,
  };
}

export function ScoreGauge({ score, status }: ScoreGaugeProps) {
  const tone =
    score === null
      ? Palette.textMuted
      : score >= 90
        ? Palette.emerald
        : score >= 80
          ? Palette.teal
          : score >= 70
            ? Palette.amber
            : Palette.red;
  const activeTicks =
    score === null
      ? 0
      : Math.round(
          (Math.max(0, Math.min(100, score)) / 100) * TICK_COUNT,
        );
  return (
    <View style={styles.wrap}>
      <Svg width={320} height={166} viewBox="0 0 320 166">
        {Array.from({ length: TICK_COUNT }, (_, index) => {
          const angle = 200 + (140 / (TICK_COUNT - 1)) * index;
          const start = point(angle, INNER_RADIUS);
          const end = point(angle, OUTER_RADIUS);
          const active = index < activeTicks;
          return (
            <Line
              key={angle}
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              stroke={active ? tone : Palette.border}
              strokeWidth={4.5}
              strokeLinecap="round"
            />
          );
        })}
      </Svg>
      <View style={styles.valueWrap}>
        <Text style={styles.value}>{score ?? '—'}</Text>
        <View style={styles.statusRow}>
          <Text style={styles.status}>{status}</Text>
          <View style={[styles.statusDot, { backgroundColor: tone }]} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    height: 174,
    marginTop: -6,
  },
  valueWrap: {
    position: 'absolute',
    top: 62,
    alignItems: 'center',
  },
  value: {
    color: Palette.text,
    fontSize: 66,
    lineHeight: 72,
    fontWeight: '300',
    letterSpacing: -3,
    fontVariant: ['tabular-nums'],
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  status: {
    color: Palette.textSecondary,
    fontSize: 14,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
});
