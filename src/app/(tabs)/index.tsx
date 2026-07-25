import { Ionicons } from '@expo/vector-icons';
import {
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { DateItem, DateStrip } from '@/components/date-strip';
import { HealthStickerCard } from '@/components/health-sticker-card';
import { MetricList } from '@/components/metric-list';
import { PostureTimeline } from '@/components/posture-timeline';
import { ReportSkeleton } from '@/components/report-skeleton';
import { ScoreGauge } from '@/components/score-gauge';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  addDays,
  buildDateRange,
  daysBetween,
  endOfISOWeek,
  formatChineseMonthDay,
  isISODate,
  parseISODate,
  startOfISOWeek,
  todayISODate,
  weekdayLabel,
} from '@/domain/date-utils';
import { buildHealthStickerPresentation } from '@/domain/health-sticker';
import { buildReportHealthMetrics } from '@/domain/health-presentation';
import { POSTURE_LABELS } from '@/domain/report';
import { DayReport } from '@/domain/types';
import { useReduceMotion } from '@/hooks/use-reduce-motion';
import { healthDataService } from '@/services/health-data-service';
import { useHealth } from '@/state/health-context';
import { useRealtime } from '@/state/realtime-context';

type ReportLoadState = 'loading' | 'ready' | 'error';
const DATE_STRIP_ADJACENT_WEEK_DAYS = 7;

interface ReportDateSelection {
  routeDate: string;
  selectedDate: string;
  previousDate?: string;
  transitionId: number;
}

function AnimatedDateTitle({
  date,
  previousDate,
  transitionId,
}: {
  date: string;
  previousDate?: string;
  transitionId: number;
}) {
  const label = formatChineseMonthDay(date);
  const previousLabel = previousDate
    ? formatChineseMonthDay(previousDate)
    : undefined;
  const reduceMotion = useReduceMotion();
  const direction = previousDate && date < previousDate ? -1 : 1;

  return (
    <View
      accessibilityRole="header"
      accessibilityLabel={`当前日报日期：${label}`}
      accessibilityLiveRegion="polite"
      style={styles.dateTitleFrame}>
      {!previousLabel || !previousDate || reduceMotion ? (
        <DateTitleContent date={date} />
      ) : (
        <AnimatedDateTransition
          key={`${transitionId}-${date}`}
          currentDate={date}
          direction={direction}
          previousDate={previousDate}
        />
      )}
    </View>
  );
}

function DateTitleContent({ date }: { date: string }) {
  const value = parseISODate(date);

  return (
    <View
      accessible={false}
      pointerEvents="none"
      testID="date-title-current"
      style={styles.dateTitleRow}>
      <Text style={styles.headerTitle}>{value.getUTCMonth() + 1}</Text>
      <Text testID="date-title-month-unit" style={styles.headerTitle}>
        月
      </Text>
      <Text style={styles.headerTitle}>{value.getUTCDate()}</Text>
      <Text testID="date-title-day-unit" style={styles.headerTitle}>
        日
      </Text>
    </View>
  );
}

function AnimatedDateTransition({
  currentDate,
  direction,
  previousDate,
}: {
  currentDate: string;
  direction: -1 | 1;
  previousDate: string;
}) {
  const [progress] = useState(() => new Animated.Value(0));
  const current = parseISODate(currentDate);
  const previous = parseISODate(previousDate);

  useEffect(() => {
    progress.setValue(0);
    const animation = Animated.spring(progress, {
      toValue: 1,
      stiffness: 150,
      damping: 18,
      mass: 1,
      restDisplacementThreshold: 0.001,
      restSpeedThreshold: 0.001,
      useNativeDriver: true,
    });
    animation.start();
    return () => animation.stop();
  }, [progress]);

  return (
    <View
      accessible={false}
      pointerEvents="none"
      testID="date-title-current"
      style={styles.dateTitleRow}>
      <AnimatedDateDigits
        currentValue={current.getUTCMonth() + 1}
        direction={direction}
        previousValue={previous.getUTCMonth() + 1}
        progress={progress}
        testIDPrefix="date-title-month"
      />
      <Text testID="date-title-month-unit" style={styles.headerTitle}>
        月
      </Text>
      <AnimatedDateDigits
        currentValue={current.getUTCDate()}
        direction={direction}
        previousValue={previous.getUTCDate()}
        progress={progress}
        testIDPrefix="date-title-day"
      />
      <Text testID="date-title-day-unit" style={styles.headerTitle}>
        日
      </Text>
    </View>
  );
}

function AnimatedDateDigits({
  currentValue,
  direction,
  previousValue,
  progress,
  testIDPrefix,
}: {
  currentValue: number;
  direction: -1 | 1;
  previousValue: number;
  progress: Animated.Value;
  testIDPrefix: string;
}) {
  const currentDigits = String(currentValue).split('');
  const previousDigits = String(previousValue)
    .padStart(currentDigits.length, ' ')
    .slice(-currentDigits.length)
    .split('');

  return (
    <View style={styles.dateDigitGroup}>
      {currentDigits.map((digit, index) => {
        const previousDigit = previousDigits[index];
        if (digit === previousDigit) {
          return (
            <Text
              key={`${index}-${digit}`}
              testID={`${testIDPrefix}-static-${index}`}
              style={styles.headerTitle}>
              {digit}
            </Text>
          );
        }

        return (
          <View key={`${index}-${digit}`} style={styles.dateDigitColumn}>
            <Text
              accessible={false}
              style={[styles.headerTitle, styles.dateDigitPlaceholder]}>
              0
            </Text>
            {previousDigit.trim() ? (
              <Animated.Text
                accessible={false}
                testID={`${testIDPrefix}-previous-${index}`}
                style={[
                  styles.headerTitle,
                  styles.animatedDigitLayer,
                  {
                    opacity: progress.interpolate({
                      inputRange: [0, 0.7, 1],
                      outputRange: [1, 0.2, 0],
                      extrapolate: 'clamp',
                    }),
                    transform: [
                      {
                        translateY: progress.interpolate({
                          inputRange: [0, 1],
                          outputRange: [0, -8 * direction],
                          extrapolate: 'clamp',
                        }),
                      },
                      {
                        scale: progress.interpolate({
                          inputRange: [0, 1],
                          outputRange: [1, 0.5],
                          extrapolate: 'clamp',
                        }),
                      },
                    ],
                  },
                ]}>
                {previousDigit}
              </Animated.Text>
            ) : null}
            <Animated.Text
              accessible={false}
              testID={`${testIDPrefix}-current-${index}`}
              style={[
                styles.headerTitle,
                styles.animatedDigitLayer,
                {
                  opacity: progress.interpolate({
                    inputRange: [0, 0.3, 1],
                    outputRange: [0, 0.8, 1],
                    extrapolate: 'clamp',
                  }),
                  transform: [
                    {
                      translateY: progress.interpolate({
                        inputRange: [0, 1],
                        outputRange: [8 * direction, 0],
                        extrapolate: 'clamp',
                      }),
                    },
                    {
                      scale: progress.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0.5, 1],
                        extrapolate: 'clamp',
                      }),
                    },
                  ],
                },
              ]}>
              {digit}
            </Animated.Text>
          </View>
        );
      })}
    </View>
  );
}

function StatItem({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <View style={styles.statValueRow}>
        <View style={[styles.statDot, { backgroundColor: tone }]} />
        <Text style={styles.statValue}>{value}</Text>
      </View>
    </View>
  );
}

export default function ReportScreen() {
  const params = useLocalSearchParams<{ date?: string }>();
  const router = useRouter();
  const routeDate = isISODate(params.date) ? params.date : todayISODate();
  const [selection, setSelection] = useState<ReportDateSelection>({
    routeDate,
    selectedDate: routeDate,
    transitionId: 0,
  });
  const selectionMatchesRoute = selection.routeDate === routeDate;
  const selectedDate = selectionMatchesRoute
    ? selection.selectedDate
    : routeDate;
  const previousDate = selectionMatchesRoute
    ? selection.previousDate
    : undefined;
  const transitionId = selectionMatchesRoute ? selection.transitionId : 0;
  const [report, setReport] = useState<DayReport | null>(null);
  const [nearbyReports, setNearbyReports] = useState<DayReport[]>([]);
  const [loadState, setLoadState] = useState<ReportLoadState>('loading');
  const [reloadKey, setReloadKey] = useState(0);

  useFocusEffect(
    useCallback(() => {
      setReloadKey((current) => current + 1);
    }, []),
  );
  const health = useHealth();
  const realtime = useRealtime();
  const reduceMotion = useReduceMotion();

  const selectDate = (date: string) => {
    setSelection((current) => {
      const currentDate =
        current.routeDate === routeDate ? current.selectedDate : routeDate;
      if (date === currentDate) return current;
      return {
        routeDate,
        selectedDate: date,
        previousDate: currentDate,
        transitionId: current.transitionId + 1,
      };
    });
  };

  useEffect(() => {
    let active = true;
    const range = {
      startDate: addDays(
        startOfISOWeek(selectedDate),
        -DATE_STRIP_ADJACENT_WEEK_DAYS,
      ),
      endDate: addDays(
        endOfISOWeek(selectedDate),
        DATE_STRIP_ADJACENT_WEEK_DAYS,
      ),
    };
    void Promise.resolve().then(async () => {
      if (!active) return;
      setLoadState('loading');
      setReport(null);
      try {
        const [nextReport, nextNearbyReports] = await Promise.all([
          healthDataService.cushion.getReport(selectedDate),
          healthDataService.cushion.getReports(range),
        ]);
        if (!active) return;
        setReport(nextReport);
        setNearbyReports(nextNearbyReports);
        setLoadState('ready');
      } catch {
        if (!active) return;
        setReport(null);
        setNearbyReports([]);
        setLoadState('error');
      }
    });
    return () => {
      active = false;
    };
  }, [realtime.postureRevision, reloadKey, selectedDate]);

  const dateStripDates = useMemo<DateItem[]>(() => {
    const availableDates = new Set(nearbyReports.map((item) => item.date));
    return buildDateRange(
      addDays(
        startOfISOWeek(selectedDate),
        -DATE_STRIP_ADJACENT_WEEK_DAYS,
      ),
      addDays(
        endOfISOWeek(selectedDate),
        DATE_STRIP_ADJACENT_WEEK_DAYS,
      ),
    ).map((date) => ({
      date,
      day: String(parseISODate(date).getUTCDate()),
      weekday: weekdayLabel(date),
      hasCushionData: availableDates.has(date),
    }));
  }, [nearbyReports, selectedDate]);

  const nearestReport = useMemo(() => {
    return [...nearbyReports].sort(
      (a, b) =>
        Math.abs(daysBetween(selectedDate, a.date)) -
        Math.abs(daysBetween(selectedDate, b.date)),
    )[0];
  }, [nearbyReports, selectedDate]);

  const metrics = useMemo(
    () =>
      buildReportHealthMetrics(
        health.samples,
        selectedDate,
        health.sensitive.showSensitiveOnReport,
      ),
    [
      health.samples,
      health.sensitive.showSensitiveOnReport,
      selectedDate,
    ],
  );
  const healthSticker = useMemo(
    () => (report ? buildHealthStickerPresentation(report) : null),
    [report],
  );

  const openTrends = () => {
    router.push({
      pathname: '/trends',
      params: { endDate: report?.date ?? nearestReport?.date ?? selectedDate },
    });
  };

  return (
    <AppScreen
      refreshing={health.status === 'syncing'}
      onRefresh={health.status === 'connected' ? health.sync : undefined}>
      <View style={styles.header}>
        <AnimatedDateTitle
          date={selectedDate}
          previousDate={previousDate}
          transitionId={transitionId}
        />
      </View>

      <DateStrip
        dates={dateStripDates}
        selectedDate={selectedDate}
        onSelect={selectDate}
      />

      {loadState === 'loading' ? <ReportSkeleton /> : null}

      {loadState === 'error' ? (
        <SurfaceCard style={styles.emptyCard}>
          <View style={[styles.emptyIcon, styles.errorIcon]}>
            <Ionicons name="cloud-offline-outline" size={25} color={Palette.amber} />
          </View>
          <Text style={styles.emptyTitle}>日报暂时没有加载完成</Text>
          <Text style={styles.emptyCopy}>
            本机数据没有被删除，可以重新读取这一天的日报。
          </Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => setReloadKey((value) => value + 1)}
            style={({ pressed }) => [
              styles.primaryButton,
              pressed && styles.pressed,
            ]}>
            <Text style={styles.primaryButtonText}>重新加载</Text>
          </Pressable>
        </SurfaceCard>
      ) : null}

      {loadState === 'ready' && report ? (
        <>
          <SurfaceCard style={styles.scoreCard}>
            <View style={styles.scoreCategoryRow}>
              <View style={styles.scoreCategory}>
                <Ionicons name="body-outline" size={18} color={Palette.red} />
                <Text style={styles.scoreCategoryText}>坐姿健康</Text>
              </View>
              <Text style={styles.scoreCategoryDate}>
                {selectedDate === todayISODate()
                  ? '今天'
                  : formatChineseMonthDay(selectedDate)}
              </Text>
            </View>
            <ScoreGauge score={report.score.value} status={report.score.status} />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="查看坐姿健康得分趋势"
              onPress={openTrends}
              style={({ pressed }) => [
                styles.scoreLink,
                pressed && styles.pressed,
              ]}>
              <Text style={styles.scoreLinkText}>坐姿健康得分</Text>
              <Ionicons name="chevron-forward" size={16} color={Palette.textSecondary} />
            </Pressable>
            <Text style={styles.scoreDate}>
              {formatChineseMonthDay(selectedDate)} 星期{weekdayLabel(selectedDate)}
            </Text>
            <Text style={styles.coverageNote}>
              有效在座 {report.stats.seatedMinutes} 分钟 · 采集覆盖{' '}
              {report.stats.observedMinutes} 分钟 ·{' '}
              {report.score.confidence === 'stable'
                ? '稳定评分'
                : report.score.confidence === 'preliminary'
                  ? '初步评分'
                  : '数据不足'}
            </Text>
            <Text style={styles.scoreDisclaimer}>
              基于坐垫识别的姿态与离座习惯，仅供日常参考，不作为医疗诊断。
            </Text>
            <Text style={styles.mainDrag}>主要关注：{report.score.mainDrag}</Text>
            <View style={styles.statDivider} />
            <View style={styles.statsRow}>
              <StatItem
                label="坐姿端正"
                value={`${report.stats.uprightPercentage}%`}
                tone={Palette.emerald}
              />
              <View style={styles.verticalDivider} />
              <StatItem
                label="有效离座"
                value={`${report.stats.validBreakCount}次`}
                tone={Palette.emerald}
              />
              <View style={styles.verticalDivider} />
              <StatItem
                label="在座时长"
                value={report.stats.seatedText}
                tone={Palette.amber}
              />
            </View>
          </SurfaceCard>

          <SurfaceCard>
            <SectionTitle eyebrow="坐姿分析" title="当日状态" accent={Palette.sky} />
            <Text style={styles.summary}>{report.aiSummary}</Text>
            <View style={styles.highlight}>
              <Text style={styles.highlightLabel}>非正坐</Text>
              <Text style={styles.highlightValue}>
                {report.stats.nonUprightMinutes}分钟
              </Text>
              <View style={styles.highlightDot} />
            </View>
            <View style={styles.breakdown}>
              {report.score.breakdown.map((item) => (
                <View key={item.label} style={styles.breakdownRow}>
                  <View style={styles.breakdownText}>
                    <Text style={styles.breakdownLabel}>{item.label}</Text>
                    <Text style={styles.breakdownDetail}>{item.detail}</Text>
                  </View>
                  <Text
                    style={styles.breakdownDelta}>
                    {report.score.confidence === 'insufficient'
                      ? '—'
                      : `${item.points}/${item.maxPoints}`}
                  </Text>
                </View>
              ))}
              <View style={styles.breakdownTotal}>
                <Text style={styles.totalLabel}>记录时段得分</Text>
                <Text style={styles.totalValue}>
                  {report.score.value ?? '—'}
                </Text>
              </View>
            </View>
          </SurfaceCard>

          {healthSticker ? (
            <HealthStickerCard
              key={healthSticker.id}
              presentation={healthSticker}
              reduceMotion={reduceMotion}
            />
          ) : null}

          <SurfaceCard>
            <SectionTitle title="姿态分布" />
            <View style={styles.postureSummary}>
              {report.stats.postureTotals
                .filter((total) => total.minutes > 0)
                .map((total) => (
                <Text key={total.posture} style={styles.postureSummaryText}>
                  {POSTURE_LABELS[total.posture]}{' '}
                  <Text
                    style={
                      total.posture === 'upright'
                        ? styles.postureStrong
                        : total.posture === 'away'
                          ? styles.postureMuted
                          : styles.postureWarning
                    }>
                    {total.minutes}分钟
                  </Text>{' '}
                  {total.percentage}%
                </Text>
                ))}
            </View>
            <PostureTimeline
              segments={report.segments}
              axisStart={report.axisStart}
              axisEnd={report.axisEnd}
            />
          </SurfaceCard>
        </>
      ) : null}

      {loadState === 'ready' && !report ? (
        <SurfaceCard style={styles.emptyCard}>
          <View style={styles.emptyIcon}>
            <Ionicons name="radio-outline" size={25} color={Palette.teal} />
          </View>
          <Text style={styles.emptyTitle}>这一天还没有坐垫数据</Text>
          <Text style={styles.emptyCopy}>
            Apple Health 记录仍会在下方显示，但不会生成虚假的坐姿评分或坐姿洞察。
          </Text>
          <View style={styles.emptyActions}>
            {nearestReport ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => selectDate(nearestReport.date)}
                style={({ pressed }) => [
                  styles.primaryButton,
                  pressed && styles.pressed,
                ]}>
                <Text style={styles.primaryButtonText}>查看最近记录</Text>
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              onPress={openTrends}
              style={({ pressed }) => [
                styles.secondaryButton,
                pressed && styles.pressed,
              ]}>
              <Text style={styles.secondaryButtonText}>查看趋势</Text>
            </Pressable>
          </View>
        </SurfaceCard>
      ) : null}

      <View style={styles.healthSection}>
        <SectionTitle
          title="健康数据"
          icon="heart-outline"
          accent={Palette.red}
        />
        <MetricList metrics={metrics} />
      </View>

      {loadState === 'ready' && report && report.tags.length > 0 ? (
        <View style={styles.tags}>
          {report.tags.map((tag, index) => (
            <View key={tag} style={[styles.tag, index === 0 && styles.tagActive]}>
              <Text style={[styles.tagText, index === 0 && styles.tagTextActive]}>
                {tag}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      <Text style={styles.disclaimer}>真实记录仅供健康参考 · 非医疗诊断设备</Text>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.md,
    minHeight: 58,
    justifyContent: 'center',
  },
  dateTitleFrame: {
    minHeight: 44,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  dateTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  dateDigitGroup: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  dateDigitColumn: {
    position: 'relative',
  },
  dateDigitPlaceholder: {
    opacity: 0,
  },
  animatedDigitLayer: {
    position: 'absolute',
    left: 0,
    top: 0,
  },
  headerTitle: {
    color: Palette.text,
    fontSize: 34,
    fontWeight: '800',
    letterSpacing: -1,
    fontVariant: ['tabular-nums'],
  },
  pressed: {
    opacity: 0.65,
    transform: [{ scale: 0.97 }],
  },
  scoreCard: {
    paddingTop: Spacing.xl,
  },
  scoreCategoryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 2,
  },
  scoreCategory: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  scoreCategoryText: {
    color: Palette.red,
    fontSize: 15,
    fontWeight: '800',
  },
  scoreCategoryDate: {
    color: Palette.textMuted,
    fontSize: 13,
  },
  scoreLink: {
    marginTop: -7,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  scoreLinkText: {
    color: Palette.text,
    fontSize: 16,
    fontWeight: '700',
  },
  scoreDate: {
    color: Palette.textMuted,
    textAlign: 'center',
    fontSize: 12,
    marginTop: 5,
  },
  coverageNote: {
    color: Palette.textMuted,
    textAlign: 'center',
    fontSize: 11,
    lineHeight: 17,
    marginTop: 6,
  },
  scoreDisclaimer: {
    color: Palette.textMuted,
    textAlign: 'center',
    fontSize: 10,
    lineHeight: 16,
    marginTop: 4,
  },
  mainDrag: {
    color: Palette.textMuted,
    textAlign: 'center',
    fontSize: 12,
    marginTop: 10,
  },
  statDivider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: Palette.border,
    marginVertical: Spacing.xl,
  },
  statsRow: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  stat: {
    flex: 1,
    alignItems: 'center',
    gap: 8,
  },
  statLabel: {
    color: Palette.textSecondary,
    fontSize: 12,
  },
  statValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  statDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statValue: {
    color: Palette.text,
    fontSize: 16,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  verticalDivider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: Palette.border,
  },
  summary: {
    color: Palette.textSecondary,
    fontSize: 17,
    lineHeight: 29,
    marginTop: Spacing.lg,
  },
  highlight: {
    minHeight: 58,
    borderRadius: Radius.md,
    backgroundColor: '#FFF5E6',
    marginTop: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  highlightLabel: {
    color: Palette.textSecondary,
    fontSize: 15,
  },
  highlightValue: {
    color: Palette.amber,
    fontWeight: '800',
    fontSize: 16,
  },
  highlightDot: {
    marginLeft: 'auto',
    width: 9,
    height: 9,
    borderRadius: 5,
    backgroundColor: Palette.amber,
  },
  breakdown: {
    marginTop: Spacing.lg,
    paddingTop: Spacing.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  breakdownRow: {
    minHeight: 38,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  breakdownText: {
    flex: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 7,
  },
  breakdownLabel: {
    color: Palette.textSecondary,
    fontSize: 13,
  },
  breakdownDetail: {
    color: Palette.textMuted,
    fontSize: 11,
  },
  breakdownDelta: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  breakdownTotal: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
    marginTop: Spacing.sm,
    paddingTop: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  totalLabel: {
    color: Palette.textSecondary,
    fontSize: 14,
  },
  totalValue: {
    color: Palette.text,
    fontSize: 17,
    fontWeight: '800',
  },
  postureSummary: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.lg,
    marginTop: Spacing.md,
    marginBottom: Spacing.lg,
  },
  postureSummaryText: {
    color: Palette.textSecondary,
    fontSize: 13,
  },
  postureStrong: {
    color: Palette.text,
    fontWeight: '700',
  },
  postureWarning: {
    color: Palette.amber,
    fontWeight: '800',
  },
  postureMuted: {
    color: Palette.textMuted,
    fontWeight: '700',
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: 38,
  },
  emptyIcon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#E6F9F7',
    marginBottom: Spacing.lg,
  },
  emptyTitle: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '700',
  },
  emptyCopy: {
    color: Palette.textMuted,
    fontSize: 13,
    lineHeight: 20,
    textAlign: 'center',
    marginTop: Spacing.sm,
    maxWidth: 310,
  },
  errorIcon: {
    backgroundColor: '#FFF5D9',
  },
  emptyActions: {
    width: '100%',
    alignItems: 'center',
    gap: Spacing.sm,
    marginTop: Spacing.xl,
  },
  primaryButton: {
    minHeight: 46,
    borderRadius: Radius.pill,
    backgroundColor: Palette.red,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.xxl,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  secondaryButton: {
    minHeight: 44,
    borderRadius: Radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Palette.border,
    backgroundColor: Palette.surfaceRaised,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.xxl,
  },
  secondaryButtonText: {
    color: Palette.textSecondary,
    fontSize: 14,
    fontWeight: '700',
  },
  tags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.sm,
  },
  tag: {
    backgroundColor: Palette.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Palette.border,
    borderRadius: Radius.pill,
    paddingVertical: 10,
    paddingHorizontal: 18,
  },
  tagActive: {
    backgroundColor: Palette.red,
    borderColor: Palette.red,
  },
  tagText: {
    color: Palette.textSecondary,
    fontSize: 12,
  },
  tagTextActive: {
    color: '#FFFFFF',
    fontWeight: '700',
  },
  disclaimer: {
    color: Palette.textMuted,
    fontSize: 11,
    textAlign: 'center',
    marginVertical: Spacing.sm,
  },
  healthSection: {
    gap: Spacing.md,
    marginTop: Spacing.xs,
  },
});
