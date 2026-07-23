import { Ionicons } from '@expo/vector-icons';
import { useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { HealthKitSyncState } from '@/domain/types';
import { HEALTH_TYPES } from '@/services/apple-health-adapter';
import { useHealth } from '@/state/health-context';

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
  const health = useHealth();
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
  const hasSyncHistory = health.syncStates.length > 0;

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
      title: '连接你的 Apple Health',
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
      title: 'Apple Health 已连接',
      copy: `最近同步 ${formatTime(latestSync)} · ${health.samples.length} 条本地记录`,
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
            onPress={hasSyncHistory ? health.sync : health.connect}
            style={({ pressed }) => [
              styles.primaryButton,
              pressed && styles.pressed,
            ]}>
            <Text style={styles.primaryButtonText}>
              {health.status === 'error'
                ? hasSyncHistory
                  ? '重试同步'
                  : '重新连接'
                : '连接 Apple Health'}
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
          健康数据不上传；日志不会记录 HRV、体重、经期或心境原始值。
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
