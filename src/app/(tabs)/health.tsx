import { Ionicons } from '@expo/vector-icons';
import { Href, Link, useRouter } from 'expo-router';
import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { MetricList } from '@/components/metric-list';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { buildLatestHealthMetrics } from '@/domain/health-presentation';
import { POSTURE_LABELS } from '@/domain/report';
import { HealthKitSyncState } from '@/domain/types';
import { HEALTH_TYPES } from '@/services/apple-health-adapter';
import { useHealth } from '@/state/health-context';
import { useRealtime } from '@/state/realtime-context';

const TYPE_LABELS: Record<string, string> = {
  [HEALTH_TYPES.restingHeartRate]: '静息心率',
  [HEALTH_TYPES.hrv]: '心率变异性（HRV）',
  [HEALTH_TYPES.respiratoryRate]: '呼吸频率',
  [HEALTH_TYPES.bodyMass]: '体重',
  [HEALTH_TYPES.menstrualFlow]: '经期流量',
  [HEALTH_TYPES.stateOfMind]: '心境记录',
};

const ERROR_LABELS: Record<string, string> = {
  AUTHORIZATION_REQUIRED: '需要授权',
  ANCHOR_INVALID: '锚点失效',
  HEALTH_DATA_UNAVAILABLE: '当前不可用',
  UNIT_INCOMPATIBLE: '单位不兼容',
  LOCAL_STORE_FAILED: '本地存储失败',
  NATIVE_QUERY_FAILED: '读取失败',
};

function formatTime(value?: string) {
  if (!value) return '尚未同步';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function qualityLabel(value?: number) {
  if (value === undefined) return '质量待评估';
  if (value >= 0.85) return `质量良好 ${Math.round(value * 100)}%`;
  if (value >= 0.7) return `质量一般 ${Math.round(value * 100)}%`;
  return `质量偏低 ${Math.round(value * 100)}%`;
}

function formatContinuousSeated(seconds: number) {
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const remainingSeconds = seconds % 60;
  const minuteText = String(minutes).padStart(2, '0');
  const secondText = String(remainingSeconds).padStart(2, '0');
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${minuteText}:${secondText}`
    : `${minuteText}:${secondText}`;
}

function SyncRow({ state }: { state: HealthKitSyncState }) {
  const tone =
    state.status === 'success'
      ? Palette.emerald
      : state.status === 'error'
        ? Palette.red
        : Palette.textMuted;
  return (
    <View style={styles.syncRow}>
      <View style={[styles.statusDot, { backgroundColor: tone }]} />
      <View style={styles.syncText}>
        <Text style={styles.syncLabel}>
          {TYPE_LABELS[state.typeIdentifier] ?? state.typeIdentifier}
        </Text>
        <Text style={styles.syncMeta}>{formatTime(state.lastSyncAt)}</Text>
      </View>
      <Text style={[styles.syncStatus, { color: tone }]}>
        {state.status === 'success'
          ? '已更新'
          : state.status === 'error'
            ? ERROR_LABELS[state.errorCode ?? ''] ?? '读取失败'
            : '待同步'}
      </Text>
    </View>
  );
}

export default function HealthScreen() {
  const router = useRouter();
  const health = useHealth();
  const realtime = useRealtime();
  const isBusy = health.status === 'connecting' || health.status === 'syncing';
  const latestSync = useMemo(
    () =>
      health.syncStates
        .map((state) => state.lastSyncAt)
        .filter((value): value is string => Boolean(value))
        .sort()
        .at(-1),
    [health.syncStates],
  );
  const sources = useMemo(
    () =>
      [...new Set(health.samples.map((sample) => sample.sourceName).filter(Boolean))],
    [health.samples],
  );
  const latestMetrics = useMemo(
    () =>
      buildLatestHealthMetrics(health.samples, {
        menstrual: health.sensitive.menstrual,
        stateOfMind: health.sensitive.stateOfMind,
      }),
    [
      health.samples,
      health.sensitive.menstrual,
      health.sensitive.stateOfMind,
    ],
  );
  const hasSyncHistory = health.syncStates.length > 0;
  const heartEvent =
    realtime.latestByStream.heartRate?.type === 'heartRate'
      ? realtime.latestByStream.heartRate
      : undefined;
  const respiratoryEvent =
    realtime.latestByStream.respiratoryRate?.type === 'respiratoryRate'
      ? realtime.latestByStream.respiratoryRate
      : undefined;
  const postureEvent =
    realtime.latestByStream.posture?.type === 'posture'
      ? realtime.latestByStream.posture
      : undefined;
  const continuousSeatedSeconds = realtime.continuousSeatedSeconds;
  const seatedPresentation =
    continuousSeatedSeconds === null
      ? {
          title: '连续在座',
          copy:
            postureEvent?.payload.posture === 'away'
              ? '当前已离座 · 再次入座后开始计时'
              : '等待坐姿数据',
          tone: Palette.textMuted,
        }
      : continuousSeatedSeconds >= 90 * 60
        ? {
            title: '久坐时间较长',
            copy: `${formatContinuousSeated(continuousSeatedSeconds)} · 建议尽快起身活动`,
            tone: Palette.red,
          }
        : continuousSeatedSeconds >= 60 * 60
          ? {
              title: '已连续久坐',
              copy: `${formatContinuousSeated(continuousSeatedSeconds)} · 建议现在起身活动`,
              tone: Palette.amber,
            }
          : continuousSeatedSeconds >= 45 * 60
            ? {
                title: '可以准备活动',
                copy: `${formatContinuousSeated(continuousSeatedSeconds)} · 60 分钟后影响得分`,
                tone: Palette.teal,
              }
            : {
                title: '连续在座',
                copy: `${formatContinuousSeated(continuousSeatedSeconds)} · 45 分钟时提醒`,
                tone: Palette.emerald,
              };
  const seatedTone = seatedPresentation.tone;

  const statusPresentation = {
    loading: {
      title: '正在准备本地健康仓库',
      copy: '数据库密钥保存在系统钥匙串中。',
      icon: 'hourglass-outline' as const,
      tone: Palette.sky,
    },
    unavailable: {
      title: '此设备不支持 Apple Health',
      copy: '请在 iPhone 真机的 development build 中连接。网页和模拟器不会读取健康数据。',
      icon: 'phone-portrait-outline' as const,
      tone: Palette.textMuted,
    },
    disconnected: {
      title: '开启 Apple Health 同步',
      copy: '首次仅申请静息心率、HRV、呼吸频率和体重的读取权限。',
      icon: 'heart-outline' as const,
      tone: Palette.teal,
    },
    connecting: {
      title: '等待 Apple Health 授权',
      copy: '请在系统授权面板选择允许读取的项目。',
      icon: 'ellipsis-horizontal' as const,
      tone: Palette.teal,
    },
    connected: {
      title: 'Apple Health 同步已开启',
      copy:
        health.samples.length > 0
          ? `最近同步 ${formatTime(latestSync)} · 已读取 ${health.samples.length} 条真实记录`
          : '授权请求已完成，但暂未读取到记录；Apple 不会向应用透露单项读取权限是否被拒绝。',
      icon: 'checkmark-circle-outline' as const,
      tone: Palette.emerald,
    },
    syncing: {
      title: '正在同步健康数据',
      copy: '每类数据独立增量同步，失败时保留上次成功结果。',
      icon: 'sync-outline' as const,
      tone: Palette.sky,
    },
    error: {
      title: '这次同步没有完成',
      copy: health.lastError ?? '本地缓存仍然可用，你可以稍后重试。',
      icon: 'alert-circle-outline' as const,
      tone: Palette.red,
    },
  }[health.status];

  return (
    <AppScreen
      refreshing={health.status === 'syncing'}
      onRefresh={health.status === 'connected' ? health.sync : undefined}>
      <View style={styles.header}>
        <Text style={styles.title}>健康</Text>
        <Text style={styles.subtitle}>只读同步 · 本机加密</Text>
      </View>

      <SurfaceCard>
        <View style={styles.liveHeader}>
          <SectionTitle title="坐垫实时数据" icon="radio-outline" />
          <View
            style={[
              styles.connectionBadge,
              realtime.connectionState === 'connected' &&
                styles.connectionBadgeLive,
            ]}>
            <Text
              style={[
                styles.connectionBadgeText,
                realtime.connectionState === 'connected' &&
                  styles.connectionBadgeTextLive,
              ]}>
              {realtime.connectionState === 'connected'
                 ? 'MQTT 已连接'
                : realtime.connectionState === 'connecting'
                  ? 'MQTT 连接中'
                  : realtime.connectionState === 'reconnecting'
                    ? 'MQTT 重连中'
                    : realtime.connectionState === 'error'
                      ? 'MQTT 连接失败'
                  : 'MQTT 未连接'}
            </Text>
          </View>
        </View>
        <Text style={styles.sectionCopy}>
          BPM 与呼吸率来自当前坐垫会话；不会据此计算 HRV。
        </Text>
        <View style={styles.seatedStatusRow}>
          <View
            style={[
              styles.seatedStatusIcon,
              { backgroundColor: `${seatedTone}1A` },
            ]}>
            <Ionicons
              name="timer-outline"
              size={20}
              color={seatedTone}
            />
          </View>
          <View style={styles.seatedStatusText}>
            <Text
              style={[
                styles.seatedStatusTitle,
                { color: seatedTone },
              ]}>
              {seatedPresentation.title}
            </Text>
            <Text style={styles.seatedStatusCopy}>
              {seatedPresentation.copy}
            </Text>
          </View>
        </View>
        <View style={styles.liveGrid}>
          <View style={styles.liveMetric}>
            <Text style={styles.liveLabel}>心率</Text>
            <View style={styles.liveValueRow}>
              <Text style={styles.liveValue}>
                {heartEvent ? Math.round(heartEvent.payload.bpm) : '—'}
              </Text>
              <Text style={styles.liveUnit}>BPM</Text>
            </View>
            <Text
              style={[
                styles.liveMeta,
                !heartEvent && styles.waitingMeta,
                realtime.streamStatuses.heartRate.state === 'stale' &&
                  styles.interrupted,
              ]}>
              {realtime.streamStatuses.heartRate.state === 'stale'
                ? '已中断'
                : qualityLabel(heartEvent?.quality)}
            </Text>
            <Text style={styles.liveSource} numberOfLines={1}>
              {heartEvent?.deviceId ?? '等待设备数据'}
            </Text>
          </View>
          <View style={styles.liveMetric}>
            <Text style={styles.liveLabel}>呼吸率</Text>
            <View style={styles.liveValueRow}>
              <Text style={styles.liveValue}>
                {respiratoryEvent
                  ? respiratoryEvent.payload.breathsPerMinute.toFixed(1)
                  : '—'}
              </Text>
              <Text style={styles.liveUnit}>次/分</Text>
            </View>
            <Text
              style={[
                styles.liveMeta,
                !respiratoryEvent && styles.waitingMeta,
                realtime.streamStatuses.respiratoryRate.state === 'stale' &&
                  styles.interrupted,
              ]}>
              {realtime.streamStatuses.respiratoryRate.state === 'stale'
                ? '已中断'
                : qualityLabel(respiratoryEvent?.quality)}
            </Text>
            <Text style={styles.liveSource} numberOfLines={1}>
              {respiratoryEvent?.deviceId ?? '等待设备数据'}
            </Text>
          </View>
        </View>
        {realtime.capabilities.posture ? (
          <View style={styles.pressureRow}>
            <Ionicons
              name="body-outline"
              size={20}
              color={Palette.purple}
            />
            <View style={styles.pressureText}>
              <Text style={styles.pressureTitle}>当前坐姿</Text>
              <Text
                style={[
                  styles.pressureCopy,
                  realtime.streamStatuses.posture.state === 'stale' &&
                    styles.interrupted,
                ]}>
                {postureEvent
                  ? `${POSTURE_LABELS[postureEvent.payload.posture]}${
                      typeof realtime.currentPostureSeconds !== 'number' ||
                      !Number.isFinite(realtime.currentPostureSeconds)
                        ? ''
                        : ` · 已持续 ${formatContinuousSeated(realtime.currentPostureSeconds)}`
                    } · ${
                      realtime.streamStatuses.posture.state === 'stale'
                        ? '已中断'
                        : '实时'
                    }`
                  : '等待坐垫姿态数据'}
              </Text>
            </View>
          </View>
        ) : null}
        {realtime.postureBalance ? (
          <View style={styles.balanceCard}>
            <View style={styles.balanceHeader}>
              <Text style={styles.balanceTitle}>实时承重分布</Text>
              <Text style={styles.balanceMeta}>相对值 · 已平滑</Text>
            </View>
            <View style={styles.balanceMetric}>
              <View style={styles.balanceLabels}>
                <Text style={styles.balanceLabel}>
                  左 {realtime.postureBalance.leftPercentage}%
                </Text>
                <Text style={styles.balanceLabel}>
                  右 {realtime.postureBalance.rightPercentage}%
                </Text>
              </View>
              <View style={styles.balanceTrack}>
                <View
                  style={[
                    styles.balanceLeft,
                    { flex: realtime.postureBalance.leftPercentage },
                  ]}
                />
                <View
                  style={[
                    styles.balanceRight,
                    { flex: realtime.postureBalance.rightPercentage },
                  ]}
                />
              </View>
            </View>
            <View style={styles.balanceMetric}>
              <View style={styles.balanceLabels}>
                <Text style={styles.balanceLabel}>
                  坐骨 {realtime.postureBalance.ischialPercentage}%
                </Text>
                <Text style={styles.balanceLabel}>
                  腿部 {realtime.postureBalance.legPercentage}%
                </Text>
              </View>
              <View style={styles.balanceTrack}>
                <View
                  style={[
                    styles.balanceIschial,
                    { flex: realtime.postureBalance.ischialPercentage },
                  ]}
                />
                <View
                  style={[
                    styles.balanceLeg,
                    { flex: realtime.postureBalance.legPercentage },
                  ]}
                />
              </View>
            </View>
            <Text style={styles.balanceFootnote}>
              六路 ADC 仅用于观察相对分布，不代表重量或医学判断。
            </Text>
          </View>
        ) : null}
        {realtime.capabilities.pressure ? (
          <View style={styles.pressureRow}>
            <Ionicons
              name="grid-outline"
              size={20}
              color={Palette.purple}
            />
            <View style={styles.pressureText}>
              <Text style={styles.pressureTitle}>压力阵列</Text>
              <Text style={styles.pressureCopy}>
                {!realtime.capabilities.pressureCalibrated
                  ? '需要完成空载校准，校准前不进行坐姿分类'
                  : realtime.pressureFeature?.inference.occupancy === 'occupied'
                    ? `持续在座 · ${
                        realtime.pressureFeature.inference.posture === 'upright'
                          ? '正坐'
                          : '其他坐姿'
                      }`
                    : '尚未确认持续在座'}
              </Text>
            </View>
          </View>
        ) : realtime.connectionState === 'connected' &&
          !realtime.capabilities.posture ? (
          <Text style={styles.sessionOnly}>
            生理测量会话进行中；当前设备未报告压力能力，因此不判断在座状态或坐姿。
          </Text>
        ) : null}
        {realtime.connectionError ? (
          <Text style={styles.connectionError}>
            请确认已允许本地网络、Broker 地址正确，并且手机与坐垫连接同一 Wi‑Fi。
          </Text>
        ) : null}
        <Pressable
          accessibilityRole="button"
          disabled={realtime.connectionState === 'connecting'}
          onPress={
            realtime.connectionState === 'connected' ||
            realtime.connectionState === 'reconnecting'
              ? () => void realtime.disconnect()
              : () => void realtime.connect()
          }
          style={({ pressed }) => [
            styles.realtimeButton,
            pressed && styles.pressed,
          ]}>
          <Text style={styles.realtimeButtonText}>
            {realtime.connectionState === 'connected'
              ? '结束实时会话'
              : realtime.connectionState === 'reconnecting'
                ? '停止重连'
              : '连接坐垫数据源'}
          </Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          onPress={() => router.push('/cushion-diagnostics')}
          style={({ pressed }) => [
            styles.detailsLink,
            pressed && styles.pressed,
          ]}>
          <Ionicons
            name="information-circle-outline"
            size={18}
            color={Palette.sky}
          />
          <Text style={styles.detailsLinkText} numberOfLines={1}>
            查看连接详情
          </Text>
          <Ionicons
            name="chevron-forward"
            size={15}
            color={Palette.textMuted}
          />
        </Pressable>
        {__DEV__ ? (
          <Link href={'/cushion-test' as Href} asChild>
            <Pressable
              accessibilityRole="button"
              style={({ pressed }) => [
                styles.devLink,
                pressed && styles.pressed,
              ]}>
              <Text style={styles.devLinkText}>打开坐垫数据测试</Text>
            </Pressable>
          </Link>
        ) : null}
      </SurfaceCard>

      <SurfaceCard
        accessibilityLabel={`${realtime.recovery.label}。生理趋势参考，非心理或医学诊断。`}
        accessibilityLiveRegion="polite">
        <SectionTitle title="近期恢复状态" icon="leaf-outline" />
        <View style={styles.recoveryRow}>
          <View
            style={[
              styles.recoveryIcon,
              realtime.recovery.state === 'elevatedLoad' &&
                styles.recoveryIconWarn,
            ]}>
            <Ionicons
              name={
                realtime.recovery.state === 'insufficient'
                  ? 'remove'
                  : realtime.recovery.state === 'elevatedLoad'
                    ? 'trending-up'
                    : 'checkmark'
              }
              size={22}
              color={
                realtime.recovery.state === 'elevatedLoad'
                  ? Palette.amber
                  : realtime.recovery.state === 'insufficient'
                    ? Palette.textMuted
                    : Palette.emerald
              }
            />
          </View>
          <View style={styles.recoveryText}>
            <Text style={styles.recoveryTitle}>
              {realtime.recovery.label}
            </Text>
            <Text style={styles.recoveryCopy}>
              {realtime.recovery.state === 'insufficient'
                ? '需要 15 分钟内的 Apple Health SDNN、完整 5 分钟心率与呼吸率，以及足够的个人基线。'
                : `基于同来源 30 天 HRV 基线 · 置信度${
                    realtime.recovery.confidence === 'high'
                      ? '高'
                      : '中'
                  }`}
            </Text>
          </View>
        </View>
        <Text style={styles.disclaimer}>
          生理趋势参考，非心理或医学诊断。Apple“心境”是独立的用户自述记录。
        </Text>
      </SurfaceCard>
      <SurfaceCard
        accessibilityLabel={`${statusPresentation.title}。${statusPresentation.copy}`}
        accessibilityLiveRegion="polite"
        style={styles.hero}>
        <View
          style={[
            styles.heroIcon,
            { backgroundColor: `${statusPresentation.tone}1F` },
          ]}>
          <Ionicons
            name={statusPresentation.icon}
            size={30}
            color={statusPresentation.tone}
          />
        </View>
        <Text style={styles.heroTitle}>{statusPresentation.title}</Text>
        <Text style={styles.heroCopy}>{statusPresentation.copy}</Text>

        {health.status === 'disconnected' || health.status === 'error' ? (
          <Pressable
            accessibilityRole="button"
            disabled={!health.available || isBusy}
            onPress={
              health.status === 'disconnected'
                ? health.connect
                : hasSyncHistory
                  ? health.sync
                  : health.connect
            }
            style={({ pressed }) => [
              styles.primaryButton,
              pressed && styles.pressed,
            ]}>
            <Text style={styles.primaryButtonText}>
              {health.status === 'error'
                ? hasSyncHistory
                  ? '重试同步'
                  : '重新连接'
                : '开启 Apple Health 同步'}
            </Text>
          </Pressable>
        ) : null}
        {health.status === 'connected' ? (
          <Pressable
            accessibilityRole="button"
            onPress={health.sync}
            style={({ pressed }) => [
              styles.secondaryButton,
              pressed && styles.pressed,
            ]}>
            <Ionicons name="sync-outline" size={17} color={Palette.text} />
            <Text style={styles.secondaryButtonText}>立即同步</Text>
          </Pressable>
        ) : null}
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="Apple Health 最近记录" icon="heart-outline" />
        <Text style={styles.sectionCopy}>
          这里只显示从 Apple Health 实际读取到的记录、原始来源和测量时间。
        </Text>
        <View style={styles.latestMetrics}>
          <MetricList metrics={latestMetrics} />
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="同步项目" />
        <Text style={styles.sectionCopy}>
          核心项目只读；经期与心境需在设置中单独启用。
        </Text>
        <View style={styles.syncList}>
          {health.syncStates.length > 0 ? (
            health.syncStates.map((state) => (
              <SyncRow key={state.typeIdentifier} state={state} />
            ))
          ) : (
            <View style={styles.empty}>
              <Ionicons name="layers-outline" size={25} color={Palette.textMuted} />
              <Text style={styles.emptyTitle}>还没有导入记录</Text>
              <Text style={styles.emptyCopy}>
                完成连接后会从最近 90 天开始建立本地镜像。
              </Text>
            </View>
          )}
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="数据来源" icon="shield-checkmark-outline" />
        <View style={styles.sourceList}>
          {sources.length > 0 ? (
            sources.map((source) => (
              <View key={source} style={styles.sourceRow}>
                <View style={styles.sourceIcon}>
                  <Ionicons name="watch-outline" size={18} color={Palette.teal} />
                </View>
                <View style={styles.sourceText}>
                  <Text style={styles.sourceName}>{source}</Text>
                  <Text style={styles.sourceMeta}>来源随原始样本完整保留</Text>
                </View>
              </View>
            ))
          ) : (
            <Text style={styles.noSource}>同步后在这里显示 Apple Watch、iPhone 等来源。</Text>
          )}
        </View>
      </SurfaceCard>

      <View style={styles.privacyNote}>
        <Ionicons name="lock-closed-outline" size={15} color={Palette.textMuted} />
        <Text style={styles.privacyText}>
          健康数据不上传；日志不会记录 HRV、BPM、呼吸率、压力、体重、经期或心境原始值。
        </Text>
      </View>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xs,
  },
  title: {
    color: Palette.text,
    fontSize: 34,
    fontWeight: '800',
    letterSpacing: -1,
  },
  subtitle: {
    color: Palette.textMuted,
    fontSize: 14,
    marginTop: 4,
  },
  hero: {
    alignItems: 'center',
    paddingVertical: 30,
  },
  heroIcon: {
    width: 62,
    height: 62,
    borderRadius: 31,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: Spacing.lg,
  },
  heroTitle: {
    color: Palette.text,
    fontSize: 20,
    fontWeight: '800',
    textAlign: 'center',
  },
  heroCopy: {
    color: Palette.textSecondary,
    fontSize: 13,
    lineHeight: 21,
    textAlign: 'center',
    marginTop: Spacing.sm,
    maxWidth: 330,
  },
  primaryButton: {
    minHeight: 50,
    borderRadius: Radius.pill,
    backgroundColor: Palette.red,
    paddingHorizontal: 28,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Spacing.xl,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
  secondaryButton: {
    minHeight: 48,
    borderRadius: Radius.pill,
    backgroundColor: Palette.surfaceMuted,
    paddingHorizontal: 24,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: Spacing.xl,
  },
  secondaryButtonText: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '700',
  },
  sectionCopy: {
    color: Palette.textMuted,
    fontSize: 12,
    marginTop: 6,
  },
  liveHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.sm,
  },
  connectionBadge: {
    minHeight: 28,
    borderRadius: Radius.pill,
    backgroundColor: Palette.surfaceMuted,
    paddingHorizontal: Spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  connectionBadgeLive: { backgroundColor: '#E8F8EC' },
  connectionBadgeText: {
    color: Palette.textMuted,
    fontSize: 10,
    fontWeight: '800',
  },
  connectionBadgeTextLive: { color: Palette.emerald },
  liveGrid: {
    flexDirection: 'row',
    gap: Spacing.md,
    marginTop: Spacing.lg,
  },
  seatedStatusRow: {
    minHeight: 72,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
    padding: Spacing.md,
    marginTop: Spacing.lg,
  },
  seatedStatusIcon: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
  },
  seatedStatusText: { flex: 1 },
  seatedStatusTitle: { fontSize: 13, fontWeight: '800' },
  seatedStatusCopy: {
    color: Palette.textSecondary,
    fontSize: 11,
    lineHeight: 17,
    marginTop: 3,
    fontVariant: ['tabular-nums'],
  },
  liveMetric: {
    flex: 1,
    minHeight: 142,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
    padding: Spacing.lg,
  },
  liveLabel: {
    color: Palette.textSecondary,
    fontSize: 12,
    fontWeight: '700',
  },
  liveValueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 5,
    marginTop: Spacing.sm,
  },
  liveValue: {
    color: Palette.text,
    fontSize: 30,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  liveUnit: { color: Palette.textMuted, fontSize: 10 },
  liveMeta: {
    color: Palette.emerald,
    fontSize: 10,
    lineHeight: 15,
    marginTop: 5,
  },
  interrupted: { color: Palette.amber, fontWeight: '800' },
  waitingMeta: { color: Palette.textMuted },
  liveSource: { color: Palette.textMuted, fontSize: 9, marginTop: 4 },
  pressureRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    borderRadius: Radius.md,
    backgroundColor: '#F4ECFA',
    padding: Spacing.md,
    marginTop: Spacing.md,
  },
  pressureText: { flex: 1 },
  pressureTitle: { color: Palette.text, fontSize: 12, fontWeight: '700' },
  pressureCopy: {
    color: Palette.textSecondary,
    fontSize: 10,
    lineHeight: 16,
    marginTop: 3,
  },
  balanceCard: {
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
    padding: Spacing.md,
    marginTop: Spacing.md,
    gap: Spacing.md,
  },
  balanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.sm,
  },
  balanceTitle: {
    color: Palette.text,
    fontSize: 12,
    fontWeight: '800',
  },
  balanceMeta: {
    color: Palette.textMuted,
    fontSize: 9,
  },
  balanceMetric: { gap: 6 },
  balanceLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  balanceLabel: {
    color: Palette.textSecondary,
    fontSize: 10,
    fontVariant: ['tabular-nums'],
  },
  balanceTrack: {
    height: 8,
    borderRadius: 4,
    overflow: 'hidden',
    flexDirection: 'row',
    backgroundColor: Palette.surfaceMuted,
  },
  balanceLeft: { backgroundColor: Palette.sky },
  balanceRight: { backgroundColor: Palette.purple },
  balanceIschial: { backgroundColor: Palette.emerald },
  balanceLeg: { backgroundColor: Palette.amber },
  balanceFootnote: {
    color: Palette.textMuted,
    fontSize: 9,
    lineHeight: 15,
  },
  sessionOnly: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 17,
    marginTop: Spacing.md,
  },
  connectionError: {
    color: Palette.red,
    fontSize: 10,
    lineHeight: 17,
    marginTop: Spacing.md,
  },
  realtimeButton: {
    minHeight: 48,
    borderRadius: Radius.pill,
    backgroundColor: Palette.text,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Spacing.lg,
  },
  realtimeButtonText: { color: '#FFFFFF', fontSize: 13, fontWeight: '800' },
  detailsLink: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    paddingHorizontal: Spacing.sm,
    marginTop: Spacing.sm,
  },
  detailsLinkText: {
    color: Palette.sky,
    fontSize: 12,
    fontWeight: '700',
    flex: 1,
  },
  devLink: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    marginTop: Spacing.sm,
  },
  devLinkText: { color: Palette.sky, fontSize: 12, fontWeight: '700' },
  recoveryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    marginTop: Spacing.lg,
  },
  recoveryIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#E8F8EC',
    alignItems: 'center',
    justifyContent: 'center',
  },
  recoveryIconWarn: { backgroundColor: '#FFF5D9' },
  recoveryText: { flex: 1 },
  recoveryTitle: { color: Palette.text, fontSize: 18, fontWeight: '800' },
  recoveryCopy: {
    color: Palette.textSecondary,
    fontSize: 11,
    lineHeight: 17,
    marginTop: 4,
  },
  disclaimer: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 16,
    marginTop: Spacing.lg,
  },
  latestMetrics: {
    marginTop: Spacing.lg,
  },
  syncList: {
    marginTop: Spacing.lg,
  },
  syncRow: {
    minHeight: 60,
    flexDirection: 'row',
    alignItems: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: Spacing.md,
  },
  syncText: {
    flex: 1,
  },
  syncLabel: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '600',
  },
  syncMeta: {
    color: Palette.textMuted,
    fontSize: 11,
    marginTop: 3,
  },
  syncStatus: {
    fontSize: 11,
    fontWeight: '700',
  },
  empty: {
    alignItems: 'center',
    paddingVertical: 28,
  },
  emptyTitle: {
    color: Palette.text,
    fontSize: 15,
    fontWeight: '700',
    marginTop: Spacing.sm,
  },
  emptyCopy: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 19,
    textAlign: 'center',
    marginTop: 5,
  },
  sourceList: {
    marginTop: Spacing.md,
  },
  sourceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  sourceIcon: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: '#E6F9F7',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  sourceText: {
    flex: 1,
  },
  sourceName: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '700',
  },
  sourceMeta: {
    color: Palette.textMuted,
    fontSize: 11,
    marginTop: 3,
  },
  noSource: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 20,
    marginTop: Spacing.md,
  },
  privacyNote: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    paddingHorizontal: Spacing.lg,
  },
  privacyText: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 18,
    flexShrink: 1,
    maxWidth: 360,
  },
  pressed: {
    opacity: 0.72,
    transform: [{ scale: 0.98 }],
  },
});
