import { Ionicons } from '@expo/vector-icons';
import {
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Animated,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { ReportSkeleton } from '@/components/report-skeleton';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { TrendHeatmap } from '@/components/trend-heatmap';
import { TrendLineChart } from '@/components/trend-line-chart';
import { TrendRangeControl } from '@/components/trend-range-control';
import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  formatChineseMonthDay,
  isISODate,
  todayISODate,
} from '@/domain/date-utils';
import {
  buildReportTrendSummary,
  buildTrendAccessibilityLabel,
  getTrendDateRanges,
} from '@/domain/trends';
import {
  ReportTrendSummary,
  TrendRangeDays,
} from '@/domain/types';
import { useReduceMotion } from '@/hooks/use-reduce-motion';
import { healthDataService } from '@/services/health-data-service';
import { useRealtime } from '@/state/realtime-context';

type LoadState = 'loading' | 'ready' | 'error';

function Metric({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <View
      accessibilityLabel={`${label}，${value}，${caption}`}
      style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
      <Text style={styles.metricCaption}>{caption}</Text>
    </View>
  );
}

export default function TrendsScreen() {
  const params = useLocalSearchParams<{ endDate?: string }>();
  const router = useRouter();
  const reduceMotion = useReduceMotion();
  const realtime = useRealtime();
  const endDate = isISODate(params.endDate) ? params.endDate : todayISODate();
  const [rangeDays, setRangeDays] = useState<TrendRangeDays>(7);
  const [selection, setSelection] = useState({
    endDate,
    selectedDate: endDate,
  });
  const selectedDate =
    selection.endDate === endDate ? selection.selectedDate : endDate;
  const [summary, setSummary] = useState<ReportTrendSummary>();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [reloadKey, setReloadKey] = useState(0);

  useFocusEffect(
    useCallback(() => {
      setReloadKey((current) => current + 1);
    }, []),
  );
  const [reveal] = useState(() => new Animated.Value(0));

  useEffect(() => {
    let active = true;
    const ranges = getTrendDateRanges(endDate, rangeDays);
    void Promise.resolve().then(async () => {
      if (!active) return;
      setLoadState('loading');
      try {
        const [reports, previousReports] = await Promise.all([
          healthDataService.cushion.getReports(ranges.current),
          healthDataService.cushion.getReports(ranges.previous),
        ]);
        if (!active) return;
        setSummary(
          buildReportTrendSummary(reports, previousReports, endDate, rangeDays),
        );
        setLoadState('ready');
      } catch {
        if (active) setLoadState('error');
      }
    });

    return () => {
      active = false;
    };
  }, [endDate, rangeDays, realtime.postureRevision, reloadKey]);

  useEffect(() => {
    if (loadState !== 'ready') return;
    reveal.setValue(reduceMotion ? 1 : 0);
    if (reduceMotion) return;

    const animation = Animated.timing(reveal, {
      toValue: 1,
      duration: 320,
      useNativeDriver: Platform.OS !== 'web',
    });
    animation.start();
    return () => animation.stop();
  }, [loadState, reduceMotion, reveal, summary]);

  const selectedPoint = useMemo(
    () => summary?.points.find((point) => point.date === selectedDate),
    [selectedDate, summary],
  );

  const scoreDelta = summary?.comparison.scoreDelta;
  const comparisonText =
    scoreDelta === null || scoreDelta === undefined
      ? '暂无上一周期'
      : scoreDelta === 0
        ? '与上一周期持平'
        : `较上一周期${scoreDelta > 0 ? '提高' : '下降'} ${Math.abs(scoreDelta)} 分`;

  const close = () => {
    if (router.canGoBack()) router.back();
    else router.replace({ pathname: '/', params: { date: endDate } });
  };

  const openSelectedReport = () => {
    if (!selectedPoint?.hasData) return;
    router.dismissTo({ pathname: '/', params: { date: selectedPoint.date } });
  };

  const selectDate = (date: string) => {
    setSelection({ endDate, selectedDate: date });
  };

  const changeRange = (nextRange: TrendRangeDays) => {
    setRangeDays(nextRange);
    setSelection({ endDate, selectedDate: endDate });
  };

  return (
    <AppScreen bottomPadding={32}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="返回日报"
          hitSlop={8}
          onPress={close}
          style={({ pressed }) => [
            styles.backButton,
            pressed && styles.pressed,
          ]}>
          <Ionicons name="chevron-back" size={25} color={Palette.text} />
        </Pressable>
        <View style={styles.headerText}>
          <Text style={styles.title}>坐姿趋势</Text>
          <Text style={styles.subtitle}>截至 {formatChineseMonthDay(endDate)}</Text>
        </View>
      </View>

      <TrendRangeControl value={rangeDays} onChange={changeRange} />

      {loadState === 'loading' ? (
        <ReportSkeleton label="正在加载坐姿趋势" />
      ) : null}

      {loadState === 'error' ? (
        <SurfaceCard style={styles.stateCard}>
          <View style={styles.stateIcon}>
            <Ionicons name="cloud-offline-outline" size={25} color={Palette.amber} />
          </View>
          <Text style={styles.stateTitle}>趋势暂时没有加载完成</Text>
          <Text style={styles.stateCopy}>日报仍保留在本机，可以重新读取。</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => setReloadKey((current) => current + 1)}
            style={({ pressed }) => [
              styles.primaryButton,
              pressed && styles.pressed,
            ]}>
            <Text style={styles.primaryButtonText}>重新加载</Text>
          </Pressable>
        </SurfaceCard>
      ) : null}

      {loadState === 'ready' && summary ? (
        <Animated.View
          style={[
            styles.content,
            {
              opacity: reveal,
              transform: [
                {
                  translateY: reveal.interpolate({
                    inputRange: [0, 1],
                    outputRange: [8, 0],
                  }),
                },
              ],
            },
          ]}>
          <SurfaceCard
            accessibilityLabel={buildTrendAccessibilityLabel(summary)}
            style={styles.summaryCard}>
            <Text style={styles.summaryEyebrow}>平均健康得分</Text>
            <View style={styles.summaryScoreRow}>
              <Text style={styles.summaryScore}>
                {summary.averageScore ?? '—'}
              </Text>
              {summary.averageScore !== null ? (
                <Text style={styles.summaryUnit}>分</Text>
              ) : null}
            </View>
            <Text
              style={[
                styles.comparison,
                scoreDelta !== null &&
                  scoreDelta !== undefined &&
                  (scoreDelta >= 0 ? styles.comparisonGood : styles.comparisonBad),
              ]}>
              {comparisonText}
            </Text>
            <View style={styles.completeness}>
              <Ionicons
                name="calendar-clear-outline"
                size={17}
                color={Palette.textMuted}
              />
              <Text style={styles.completenessText}>
                {summary.rangeDays} 天中有 {summary.dataDays} 天数据 ·{' '}
                {summary.stableDays} 天稳定评分
                {summary.preliminaryDays > 0
                  ? ` · ${summary.preliminaryDays} 天初步评分`
                  : ''}
              </Text>
            </View>
          </SurfaceCard>

          <SurfaceCard>
            <SectionTitle title="健康得分趋势" icon="trending-up-outline" />
            <TrendLineChart
              points={summary.points}
              selectedDate={selectedDate}
              onSelect={selectDate}
            />
          </SurfaceCard>

          <SurfaceCard>
            <SectionTitle title="周期表现" />
            <View style={styles.metricGrid}>
              <Metric
                label="平均正坐率"
                value={
                  summary.averageUprightPercentage === null
                    ? '—'
                    : `${summary.averageUprightPercentage}%`
                }
                caption="仅稳定评分日期"
              />
              <Metric
                label="平均最长久坐"
                value={
                  summary.averageLongestSitMinutes === null
                    ? '—'
                    : `${summary.averageLongestSitMinutes}分`
                }
                caption="60 分钟后开始降分"
              />
              <Metric
                label="平均有效离座"
                value={
                  summary.averageStandCount === null
                    ? '—'
                    : `${summary.averageStandCount}次`
                }
                caption="连续离座满 2 分钟"
              />
            </View>
          </SurfaceCard>

          <SurfaceCard>
            <SectionTitle title="坐姿日历" icon="grid-outline" />
            <Text style={styles.sectionCopy}>
              色块和数字表示每日健康得分；初步评分不进入周期平均。
            </Text>
            <TrendHeatmap
              points={summary.points}
              selectedDate={selectedDate}
              onSelect={selectDate}
            />
          </SurfaceCard>

          <SurfaceCard style={styles.selectedCard}>
            <View style={styles.selectedIcon}>
              <Ionicons
                name={selectedPoint?.hasData ? 'document-text-outline' : 'radio-outline'}
                size={23}
                color={selectedPoint?.hasData ? Palette.red : Palette.textMuted}
              />
            </View>
            <View style={styles.selectedText}>
              <Text style={styles.selectedTitle}>
                {formatChineseMonthDay(selectedDate)}
              </Text>
              <Text style={styles.selectedCopy}>
                {selectedPoint?.hasData
                  ? selectedPoint.score === null
                    ? `有效在座不足 15 分钟 · 暂不评分`
                    : `${selectedPoint.confidence === 'preliminary' ? '初步' : '稳定'}健康得分 ${selectedPoint.score} 分 · 正坐 ${selectedPoint.uprightPercentage}%`
                  : '这一天没有坐垫数据，不生成评分。'}
              </Text>
            </View>
            {selectedPoint?.hasData ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`查看${formatChineseMonthDay(selectedDate)}日报`}
                hitSlop={8}
                onPress={openSelectedReport}
                style={({ pressed }) => pressed && styles.pressed}>
                <Ionicons
                  name="chevron-forward"
                  size={22}
                  color={Palette.textMuted}
                />
              </Pressable>
            ) : null}
          </SurfaceCard>
        </Animated.View>
      ) : null}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
  },
  backButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Palette.border,
  },
  headerText: {
    flex: 1,
  },
  title: {
    color: Palette.text,
    fontSize: 32,
    fontWeight: '800',
    letterSpacing: -0.8,
  },
  subtitle: {
    color: Palette.textMuted,
    fontSize: 14,
    marginTop: 2,
  },
  content: {
    gap: 14,
  },
  summaryCard: {
    alignItems: 'center',
    paddingVertical: Spacing.xxl,
  },
  summaryEyebrow: {
    color: Palette.red,
    fontSize: 13,
    fontWeight: '800',
  },
  summaryScoreRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginTop: 2,
  },
  summaryScore: {
    color: Palette.text,
    fontSize: 68,
    lineHeight: 76,
    fontWeight: '300',
    letterSpacing: -3,
    fontVariant: ['tabular-nums'],
  },
  summaryUnit: {
    color: Palette.textSecondary,
    fontSize: 17,
    fontWeight: '700',
    marginLeft: 5,
  },
  comparison: {
    color: Palette.textMuted,
    fontSize: 14,
    fontWeight: '700',
  },
  comparisonGood: {
    color: '#197A3B',
  },
  comparisonBad: {
    color: Palette.red,
  },
  completeness: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: Spacing.lg,
    borderRadius: Radius.pill,
    paddingVertical: 8,
    paddingHorizontal: Spacing.md,
    backgroundColor: Palette.surfaceRaised,
  },
  completenessText: {
    color: Palette.textMuted,
    fontSize: 12,
  },
  metricGrid: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginTop: Spacing.lg,
  },
  metric: {
    flex: 1,
    minHeight: 112,
    borderRadius: Radius.md,
    padding: Spacing.md,
    backgroundColor: Palette.surfaceRaised,
  },
  metricLabel: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 16,
  },
  metricValue: {
    color: Palette.text,
    fontSize: 19,
    lineHeight: 27,
    fontWeight: '800',
    marginTop: 5,
    fontVariant: ['tabular-nums'],
  },
  metricCaption: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 15,
    marginTop: 3,
  },
  sectionCopy: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 19,
    marginTop: Spacing.sm,
  },
  selectedCard: {
    minHeight: 82,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
  },
  selectedIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: Palette.surfaceRaised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectedText: {
    flex: 1,
  },
  selectedTitle: {
    color: Palette.text,
    fontSize: 15,
    fontWeight: '800',
  },
  selectedCopy: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 18,
    marginTop: 3,
  },
  stateCard: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  stateIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: '#FFF5D9',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stateTitle: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '800',
    marginTop: Spacing.lg,
  },
  stateCopy: {
    color: Palette.textMuted,
    fontSize: 13,
    marginTop: Spacing.sm,
  },
  primaryButton: {
    minHeight: 46,
    borderRadius: Radius.pill,
    backgroundColor: Palette.red,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.xxl,
    marginTop: Spacing.xl,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  pressed: {
    opacity: 0.65,
    transform: [{ scale: 0.97 }],
  },
});
