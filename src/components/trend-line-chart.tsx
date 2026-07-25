import { useMemo, useState } from 'react';
import {
  GestureResponderEvent,
  LayoutChangeEvent,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Svg, {
  Circle,
  Line,
  Polyline,
  Text as SvgText,
} from 'react-native-svg';

import { Palette, Radius, Spacing } from '@/constants/theme';
import { formatChineseMonthDay } from '@/domain/date-utils';
import { ReportTrendPoint } from '@/domain/types';

const VIEW_WIDTH = 320;
const VIEW_HEIGHT = 190;
const PLOT_LEFT = 24;
const PLOT_RIGHT = 304;
const PLOT_TOP = 18;
const PLOT_BOTTOM = 142;
const SCORE_MIN = 0;
const SCORE_MAX = 100;

function yForScore(score: number) {
  const clamped = Math.max(SCORE_MIN, Math.min(SCORE_MAX, score));
  return (
    PLOT_BOTTOM -
    ((clamped - SCORE_MIN) / (SCORE_MAX - SCORE_MIN)) *
      (PLOT_BOTTOM - PLOT_TOP)
  );
}

function xForIndex(index: number, length: number) {
  if (length <= 1) return (PLOT_LEFT + PLOT_RIGHT) / 2;
  return PLOT_LEFT + (index / (length - 1)) * (PLOT_RIGHT - PLOT_LEFT);
}

function contiguousSegments(points: ReportTrendPoint[]) {
  const segments: { index: number; point: ReportTrendPoint }[][] = [];
  let active: { index: number; point: ReportTrendPoint }[] = [];

  points.forEach((point, index) => {
    if (point.score === null || point.confidence !== 'stable') {
      if (active.length > 0) segments.push(active);
      active = [];
      return;
    }
    active.push({ index, point });
  });
  if (active.length > 0) segments.push(active);
  return segments;
}

export function TrendLineChart({
  points,
  selectedDate,
  onSelect,
}: {
  points: ReportTrendPoint[];
  selectedDate: string;
  onSelect: (date: string) => void;
}) {
  const [layoutWidth, setLayoutWidth] = useState(VIEW_WIDTH);
  const selectedIndex = Math.max(
    0,
    points.findIndex((point) => point.date === selectedDate),
  );
  const selectedPoint = points[selectedIndex] ?? points.at(-1);
  const segments = useMemo(() => contiguousSegments(points), [points]);

  const selectIndex = (index: number) => {
    const point = points[Math.max(0, Math.min(points.length - 1, index))];
    if (point) onSelect(point.date);
  };

  const handlePress = (event: GestureResponderEvent) => {
    const ratio = event.nativeEvent.locationX / Math.max(layoutWidth, 1);
    selectIndex(Math.round(ratio * (points.length - 1)));
  };

  const handleLayout = (event: LayoutChangeEvent) => {
    setLayoutWidth(event.nativeEvent.layout.width);
  };

  const selectedLabel = selectedPoint
    ? `${formatChineseMonthDay(selectedPoint.date)}，${
        selectedPoint.score === null
          ? selectedPoint.hasData
            ? '数据不足，暂不评分'
            : '无坐垫数据'
          : `${selectedPoint.confidence === 'preliminary' ? '初步' : '稳定'}健康得分${selectedPoint.score}分`
      }`
    : '暂无趋势数据';

  return (
    <View style={styles.wrap}>
      <View style={styles.selectedRow}>
        <Text style={styles.selectedDate}>
          {selectedPoint ? formatChineseMonthDay(selectedPoint.date) : '暂无日期'}
        </Text>
        <Text style={styles.selectedScore}>
          {selectedPoint?.score === null || !selectedPoint
            ? selectedPoint?.hasData
              ? '数据不足'
              : '无数据'
            : `${selectedPoint.score} 分${selectedPoint.confidence === 'preliminary' ? ' · 初步' : ''}`}
        </Text>
      </View>
      <Pressable
        accessibilityRole="adjustable"
        accessibilityLabel="坐姿健康得分趋势图"
        accessibilityValue={{ text: selectedLabel }}
        accessibilityActions={[
          { name: 'decrement', label: '前一天' },
          { name: 'increment', label: '后一天' },
        ]}
        onAccessibilityAction={(event) => {
          selectIndex(
            selectedIndex + (event.nativeEvent.actionName === 'increment' ? 1 : -1),
          );
        }}
        onLayout={handleLayout}
        onPress={handlePress}
        style={styles.chart}>
        <Svg width="100%" height={VIEW_HEIGHT} viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}>
          {[0, 50, 100].map((score) => (
            <Line
              key={score}
              x1={PLOT_LEFT}
              x2={PLOT_RIGHT}
              y1={yForScore(score)}
              y2={yForScore(score)}
              stroke={Palette.border}
              strokeWidth={1}
            />
          ))}
          {segments.map((segment) => (
            <Polyline
              key={segment[0].point.date}
              points={segment
                .map(({ index, point }) => `${xForIndex(index, points.length)},${yForScore(point.score!)}`)
                .join(' ')}
              fill="none"
              stroke={Palette.red}
              strokeWidth={3}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {points.map((point, index) =>
            point.score === null ? null : (
              <Circle
                key={point.date}
                cx={xForIndex(index, points.length)}
                cy={yForScore(point.score)}
                r={point.date === selectedDate ? 5.5 : 3}
                fill={
                  point.confidence === 'preliminary'
                    ? Palette.surface
                    : point.date === selectedDate
                      ? Palette.red
                      : Palette.surface
                }
                stroke={
                  point.confidence === 'preliminary'
                    ? Palette.amber
                    : Palette.red
                }
                strokeWidth={2}
              />
            ),
          )}
          <SvgText
            x={PLOT_LEFT}
            y={176}
            fill={Palette.textMuted}
            fontSize={10}>
            {points[0]?.date.slice(5).replace('-', '/')}
          </SvgText>
          <SvgText
            x={PLOT_RIGHT}
            y={176}
            fill={Palette.textMuted}
            fontSize={10}
            textAnchor="end">
            {points.at(-1)?.date.slice(5).replace('-', '/')}
          </SvgText>
        </Svg>
      </Pressable>
      <Text style={styles.hint}>
        实线连接稳定评分；橙色空心点表示采集不足 60 分钟的初步评分
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: Spacing.lg,
  },
  selectedRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  selectedDate: {
    color: Palette.textSecondary,
    fontSize: 13,
  },
  selectedScore: {
    color: Palette.red,
    fontSize: 18,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  chart: {
    minHeight: VIEW_HEIGHT,
    marginTop: Spacing.sm,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
  },
  hint: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 18,
    marginTop: Spacing.sm,
  },
});
