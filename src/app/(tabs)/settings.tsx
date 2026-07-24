import { Ionicons } from '@expo/vector-icons';
import { Href, Link } from 'expo-router';
import { useState } from 'react';
import {
  Alert,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { useHealth } from '@/state/health-context';
import { useRealtime } from '@/state/realtime-context';

function cushionConnectionLabel(state: ReturnType<typeof useRealtime>['connectionState']) {
  if (state === 'connected') return '已连接';
  if (state === 'connecting') return '连接中';
  if (state === 'reconnecting') return '正在重连';
  if (state === 'error') return '连接失败';
  return '未连接';
}

function SettingSwitch({
  title,
  copy,
  value,
  disabled = false,
  disabledReason,
  onValueChange,
}: {
  title: string;
  copy: string;
  value: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onValueChange: (value: boolean) => void;
}) {
  return (
    <View style={styles.settingRow}>
      <View style={styles.settingText}>
        <Text style={styles.settingTitle}>{title}</Text>
        <Text style={styles.settingCopy}>{copy}</Text>
        {disabled && disabledReason ? (
          <View style={styles.disabledReasonRow}>
            <Ionicons
              name="information-circle-outline"
              size={14}
              color={Palette.textMuted}
            />
            <Text style={styles.disabledReason}>{disabledReason}</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.switchSlot}>
        <Switch
          accessibilityLabel={title}
          accessibilityHint={disabled ? disabledReason : undefined}
          disabled={disabled}
          value={value}
          onValueChange={onValueChange}
          trackColor={{ false: Palette.surfaceMuted, true: Palette.emerald }}
          thumbColor="#FFFFFF"
          ios_backgroundColor={Palette.surfaceMuted}
        />
      </View>
    </View>
  );
}

export default function SettingsScreen() {
  const health = useHealth();
  const realtime = useRealtime();
  const [busyKey, setBusyKey] = useState<string>();
  const [brokerDraftOverride, setBrokerDraftOverride] = useState<
    string | null
  >(null);
  const brokerDraft = brokerDraftOverride ?? realtime.brokerUrl;
  const [brokerInputError, setBrokerInputError] = useState<string>();
  const sensitiveEnabled =
    health.sensitive.menstrual || health.sensitive.stateOfMind;

  const saveBroker = async () => {
    setBusyKey('broker');
    setBrokerInputError(undefined);
    try {
      const saved = await realtime.saveBrokerUrl(brokerDraft);
      if (!saved) {
        setBrokerInputError(
          '请输入 wss:// 地址，或同一局域网内的 ws:// 私有地址。',
        );
      } else {
        setBrokerDraftOverride(null);
      }
    } finally {
      setBusyKey(undefined);
    }
  };

  const setSensitive = async (
    key: 'menstrual' | 'stateOfMind',
    enabled: boolean,
  ) => {
    setBusyKey(key);
    try {
      await health.setSensitive(key, enabled);
      const otherSensitiveEnabled =
        key === 'menstrual'
          ? health.sensitive.stateOfMind
          : health.sensitive.menstrual;
      if (!enabled && !otherSensitiveEnabled) {
        await health.setShowSensitiveOnReport(false);
      }
    } finally {
      setBusyKey(undefined);
    }
  };

  const confirmClearCache = () => {
    Alert.alert(
      '删除导入缓存？',
      '将删除本机 HealthKit 镜像和同步锚点，下次同步会重新导入。系统“健康”中的原始数据不会被删除。',
      [
        { text: '取消', style: 'cancel' },
        {
          text: '删除缓存',
          style: 'destructive',
          onPress: () => {
            realtime.clearSessionData();
            void health.clearCache();
          },
        },
      ],
    );
  };

  return (
    <AppScreen>
      <View style={styles.header}>
        <Text style={styles.title}>设置</Text>
        <Text style={styles.subtitle}>隐私、同步与敏感数据</Text>
      </View>

      <SurfaceCard>
        <SectionTitle title="智能坐垫连接" icon="wifi-outline" />
        <Text style={styles.sectionCopy}>
          iPhone 与坐垫需要连接同一个 Wi‑Fi。Broker 地址变化后可在这里直接修改，无需重新打包。
        </Text>
        <Text style={styles.inputLabel}>MQTT WebSocket 地址</Text>
        <TextInput
          accessibilityLabel="MQTT WebSocket 地址"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          onChangeText={setBrokerDraftOverride}
          placeholder="ws://10.76.7.182:9001"
          placeholderTextColor={Palette.textMuted}
          style={styles.brokerInput}
          value={brokerDraft}
        />
        {brokerInputError ? (
          <Text style={styles.brokerError}>{brokerInputError}</Text>
        ) : null}
        <View style={styles.brokerStatusRow}>
          <View
            style={[
              styles.statusDot,
              realtime.connectionState === 'connected' && styles.statusDotLive,
            ]}
          />
          <Text style={styles.brokerStatusText}>
            {cushionConnectionLabel(realtime.connectionState)}
          </Text>
        </View>
        {realtime.connectionError ? (
          <Text style={styles.brokerHelp}>
            无法连接时，请确认已允许“本地网络”、Broker 正在运行，且手机与坐垫位于同一 Wi‑Fi。
          </Text>
        ) : null}
        <Pressable
          accessibilityRole="button"
          disabled={busyKey === 'broker'}
          onPress={() => void saveBroker()}
          style={({ pressed }) => [
            styles.brokerSave,
            busyKey === 'broker' && styles.actionDisabled,
            pressed && styles.pressed,
          ]}>
          <Text style={styles.brokerSaveText}>
            {realtime.connectionState === 'connected'
              ? '保存并重新连接'
              : '保存地址'}
          </Text>
        </Pressable>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="敏感项目" icon="eye-off-outline" />
        <Text style={styles.sectionCopy}>
          默认不申请，也不会在日报中公开展示。启用时系统会追加一次只读授权。
        </Text>
        <View style={styles.settingList}>
          <SettingSwitch
            title="经期流量"
            copy="读取 Apple Health 经期流量记录"
            value={health.sensitive.menstrual}
            disabled={!health.available || busyKey === 'menstrual'}
            disabledReason={
              busyKey === 'menstrual'
                ? '正在请求只读授权'
                : '需要在 iPhone 真机连接 Apple Health'
            }
            onValueChange={(value) => void setSensitive('menstrual', value)}
          />
          <SettingSwitch
            title="心境记录"
            copy="优先显示你在 Apple Health 中选择的原始标签"
            value={health.sensitive.stateOfMind}
            disabled={!health.available || busyKey === 'stateOfMind'}
            disabledReason={
              busyKey === 'stateOfMind'
                ? '正在请求只读授权'
                : '需要在 iPhone 真机连接 Apple Health'
            }
            onValueChange={(value) => void setSensitive('stateOfMind', value)}
          />
          <SettingSwitch
            title="在日报展示敏感数据"
            copy="只有启用的敏感项目才会进入日报"
            value={health.sensitive.showSensitiveOnReport}
            disabled={!sensitiveEnabled}
            disabledReason="请先启用经期流量或心境记录"
            onValueChange={(value) =>
              void health.setShowSensitiveOnReport(value)
            }
          />
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="恢复状态提醒" icon="notifications-outline" />
        <Text style={styles.sectionCopy}>
          默认关闭。仅当 HRV 明显低于个人基线、心率持续升高且信号质量合格时在本机提醒。
        </Text>
        <View style={styles.settingList}>
          <SettingSwitch
            title="允许本地休息提醒"
            copy="4 小时冷却，每天最多 2 次，22:00–08:00 静默"
            value={realtime.notificationsEnabled}
            disabled={busyKey === 'notifications'}
            disabledReason="正在请求系统通知权限"
            onValueChange={(enabled) => {
              setBusyKey('notifications');
              void realtime
                .setNotificationsEnabled(enabled)
                .then((applied) => {
                  if (enabled && !applied) {
                    Alert.alert(
                      '通知没有开启',
                      '请在 iPhone“设置”中允许有垫东西发送通知后再试。',
                    );
                  }
                })
                .finally(() => setBusyKey(undefined));
            }}
          />
        </View>
        <View style={styles.notificationPrivacy}>
          <Ionicons
            name="eye-off-outline"
            size={16}
            color={Palette.textMuted}
          />
          <Text style={styles.notificationPrivacyText}>
            锁屏文案不会显示 HRV、心率、呼吸率或情绪标签；应用不申请推送令牌。
          </Text>
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="Apple Health 同步" icon="heart-outline" />
        <View style={styles.actionList}>
          <Pressable
            accessibilityRole="button"
            accessibilityHint={
              !health.available
                ? '需要在 iPhone 真机连接 Apple Health'
                : health.status === 'disconnected'
                  ? '当前尚未连接 Apple Health'
                  : undefined
            }
            disabled={!health.available || health.status === 'disconnected'}
            onPress={health.disconnect}
            style={({ pressed }) => [
              styles.actionRow,
              (!health.available || health.status === 'disconnected') &&
                styles.actionDisabled,
              pressed && styles.pressed,
            ]}>
            <View style={styles.actionIcon}>
              <Ionicons name="pause-outline" size={20} color={Palette.amber} />
            </View>
            <View style={styles.actionText}>
              <Text style={styles.actionTitle}>停止同步</Text>
              <Text style={styles.actionCopy}>保留已导入的本地缓存</Text>
            </View>
            <Ionicons name="chevron-forward" size={17} color={Palette.textMuted} />
          </Pressable>

          <Pressable
            accessibilityRole="button"
            onPress={confirmClearCache}
            style={({ pressed }) => [
              styles.actionRow,
              pressed && styles.pressed,
            ]}>
            <View style={[styles.actionIcon, styles.destructiveIcon]}>
              <Ionicons name="trash-outline" size={19} color={Palette.red} />
            </View>
            <View style={styles.actionText}>
              <Text style={[styles.actionTitle, styles.destructiveText]}>
                删除导入缓存
              </Text>
              <Text style={styles.actionCopy}>不会删除 Apple Health 原始记录</Text>
            </View>
            <Ionicons name="chevron-forward" size={17} color={Palette.textMuted} />
          </Pressable>
        </View>
      </SurfaceCard>

      <SurfaceCard style={styles.privacyCard}>
        <View style={styles.privacyHeader}>
          <View style={styles.privacyIcon}>
            <Ionicons name="lock-closed" size={22} color={Palette.teal} />
          </View>
          <View style={styles.privacyTitleWrap}>
            <Text style={styles.privacyTitle}>健康数据留在你的设备</Text>
            <Text style={styles.privacySubtitle}>本地加密 · 不接入云端 AI</Text>
          </View>
        </View>
          <Text style={styles.privacyBody}>
            HealthKit 镜像使用 SQLCipher 加密，数据库密钥存放在 iOS
            钥匙串。应用不申请任何写入权限；坐姿洞察只根据本机保存的真实坐垫片段生成。
          </Text>
        <View style={styles.permissionNote}>
          <Ionicons
            name="information-circle-outline"
            size={17}
            color={Palette.textMuted}
          />
          <Text style={styles.permissionText}>
            如需撤销系统授权，请前往 iPhone“健康”App 的数据访问与设备页面。
          </Text>
        </View>
      </SurfaceCard>

      {__DEV__ ? (
        <Link href={'/cushion-test' as Href} asChild>
          <Pressable
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.testEntry,
              pressed && styles.pressed,
            ]}>
            <Ionicons name="flask-outline" size={19} color={Palette.sky} />
            <View style={styles.testEntryText}>
              <Text style={styles.testEntryTitle}>坐垫数据测试</Text>
              <Text style={styles.testEntryCopy}>
                手动输入、JSONL 回放与断线重连
              </Text>
            </View>
            <Ionicons
              name="chevron-forward"
              size={17}
              color={Palette.textMuted}
            />
          </Pressable>
        </Link>
      ) : null}

      <Text style={styles.version}>有垫东西 · development build 1</Text>
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
  sectionCopy: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 19,
    marginTop: Spacing.sm,
  },
  inputLabel: {
    color: Palette.textSecondary,
    fontSize: 12,
    fontWeight: '700',
    marginTop: Spacing.lg,
    marginBottom: Spacing.sm,
  },
  brokerInput: {
    minHeight: 46,
    borderRadius: Radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Palette.border,
    backgroundColor: Palette.surfaceRaised,
    color: Palette.text,
    fontSize: 13,
    paddingHorizontal: Spacing.md,
  },
  brokerError: {
    color: Palette.red,
    fontSize: 11,
    lineHeight: 17,
    marginTop: Spacing.sm,
  },
  brokerStatusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    marginTop: Spacing.md,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: Palette.textMuted,
  },
  statusDotLive: {
    backgroundColor: Palette.emerald,
  },
  brokerStatusText: {
    color: Palette.textSecondary,
    fontSize: 12,
    fontWeight: '700',
  },
  brokerHelp: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 18,
    marginTop: Spacing.sm,
  },
  brokerSave: {
    minHeight: 44,
    borderRadius: Radius.md,
    backgroundColor: Palette.text,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Spacing.md,
  },
  brokerSaveText: {
    color: Palette.surface,
    fontSize: 13,
    fontWeight: '800',
  },
  settingList: {
    marginTop: Spacing.md,
  },
  settingRow: {
    minHeight: 74,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  settingText: {
    flex: 1,
    alignSelf: 'stretch',
    justifyContent: 'center',
    paddingVertical: Spacing.md,
  },
  switchSlot: {
    width: 54,
    alignSelf: 'stretch',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  settingTitle: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '700',
  },
  settingCopy: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 17,
    marginTop: 4,
  },
  disabledReasonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 6,
  },
  disabledReason: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 16,
    flex: 1,
  },
  notificationPrivacy: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
    padding: Spacing.md,
    marginTop: Spacing.sm,
  },
  notificationPrivacyText: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 17,
    flex: 1,
  },
  actionList: {
    marginTop: Spacing.md,
  },
  actionRow: {
    minHeight: 68,
    flexDirection: 'row',
    alignItems: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  actionIcon: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: '#FFF5D9',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  destructiveIcon: {
    backgroundColor: '#FFE8ED',
  },
  actionText: {
    flex: 1,
  },
  actionTitle: {
    color: Palette.text,
    fontSize: 14,
    fontWeight: '700',
  },
  destructiveText: {
    color: Palette.red,
  },
  actionCopy: {
    color: Palette.textMuted,
    fontSize: 11,
    marginTop: 4,
  },
  privacyCard: {
    overflow: 'hidden',
  },
  privacyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  privacyIcon: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: '#E6F9F7',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  privacyTitleWrap: {
    flex: 1,
  },
  privacyTitle: {
    color: Palette.text,
    fontSize: 16,
    fontWeight: '800',
  },
  privacySubtitle: {
    color: Palette.teal,
    fontSize: 11,
    marginTop: 4,
  },
  privacyBody: {
    color: Palette.textSecondary,
    fontSize: 13,
    lineHeight: 22,
    marginTop: Spacing.lg,
  },
  permissionNote: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    backgroundColor: Palette.surfaceRaised,
    borderRadius: Radius.md,
    padding: Spacing.md,
    marginTop: Spacing.lg,
  },
  permissionText: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 18,
    flex: 1,
  },
  actionDisabled: {
    opacity: 0.72,
  },
  testEntry: {
    minHeight: 68,
    borderRadius: Radius.lg,
    backgroundColor: Palette.surface,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    paddingHorizontal: Spacing.xl,
  },
  testEntryText: { flex: 1 },
  testEntryTitle: { color: Palette.text, fontSize: 13, fontWeight: '700' },
  testEntryCopy: {
    color: Palette.textMuted,
    fontSize: 10,
    lineHeight: 16,
    marginTop: 3,
  },
  pressed: {
    opacity: 0.68,
  },
  version: {
    color: Palette.textMuted,
    fontSize: 11,
    textAlign: 'center',
    marginVertical: Spacing.sm,
  },
});
