import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { DiagnosticRow } from '@/components/diagnostic-row';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { POSTURE_LABELS } from '@/domain/report';
import {
  CushionRealtimeConnectionState,
  RadarDiagnosticsIssue,
  RadarFrameState,
} from '@/domain/realtime-types';
import { useRealtime } from '@/state/realtime-context';

const CONNECTION_LABELS: Record<CushionRealtimeConnectionState, string> = {
  disconnected: '未连接',
  connecting: '连接中',
  reconnecting: '重连中',
  connected: '已连接',
  error: '连接失败',
};

const RADAR_STATE_LABELS: Record<RadarFrameState, string> = {
  waiting: '等待新帧',
  live: '实时',
  cached: '缓存保活',
  stale: '已中断',
};

const ISSUE_LABELS: Record<RadarDiagnosticsIssue, string> = {
  INVALID_RADAR_SEQUENCE: 'seq 缺失或非法',
  INVALID_RADAR_DISTANCE: '目标距离缺失或非法',
  INVALID_RADAR_HEART_MEDIAN: 'heart_med 缺失或越界',
  INVALID_RADAR_BREATH_MEDIAN: 'breath_med 缺失或越界',
};

function formatTime(value?: string) {
  if (!value) return '尚无记录';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

function formatMetric(value: number | undefined, digits = 1) {
  return value === undefined ? '—' : value.toFixed(digits);
}

function formatContinuousSeated(seconds: number | null) {
  if (seconds === null) return '—';
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const remainingSeconds = seconds % 60;
  const minuteText = String(minutes).padStart(2, '0');
  const secondText = String(remainingSeconds).padStart(2, '0');
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${minuteText}:${secondText}`
    : `${minuteText}:${secondText}`;
}

function radarTone(state: RadarFrameState) {
  if (state === 'live') return Palette.emerald;
  if (state === 'cached') return Palette.amber;
  if (state === 'stale') return Palette.red;
  return Palette.textMuted;
}

export default function CushionDiagnosticsScreen() {
  const router = useRouter();
  const realtime = useRealtime();
  const [reconnecting, setReconnecting] = useState(false);
  const diagnostics = realtime.radarDiagnostics;
  const frameState = realtime.radarFrameStatus.state;
  const postureEvent =
    realtime.latestByStream?.posture?.type === 'posture'
      ? realtime.latestByStream.posture
      : undefined;
  const postureState = realtime.streamStatuses?.posture?.state ?? 'waiting';
  const postureValues = Object.fromEntries(
    postureEvent?.payload.sensors.map((sensor) => [
      sensor.sensorId,
      sensor.rawAdc,
    ]) ?? [],
  ) as Record<string, number>;
  const issues =
    diagnostics.issues.length === 0
      ? '协议字段正常'
      : diagnostics.issues.map((issue) => ISSUE_LABELS[issue]).join('；');

  const reconnect = async () => {
    if (reconnecting) return;
    setReconnecting(true);
    try {
      await realtime.disconnect();
      await realtime.connect();
    } finally {
      setReconnecting(false);
    }
  };

  return (
    <AppScreen bottomPadding={48}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="返回"
          hitSlop={8}
          onPress={() => router.back()}
          style={({ pressed }) => [
            styles.backButton,
            pressed && styles.pressed,
          ]}>
          <Ionicons name="chevron-back" size={22} color={Palette.text} />
        </Pressable>
        <View style={styles.headerText}>
          <Text style={styles.title}>坐垫连接详情</Text>
          <Text style={styles.subtitle}>展会现场只读诊断</Text>
        </View>
      </View>

      <SurfaceCard>
        <SectionTitle title="链路状态" icon="wifi-outline" />
        <View style={styles.rows}>
          <DiagnosticRow label="Broker" value={realtime.brokerUrl} />
          <DiagnosticRow
            label="MQTT"
            value={CONNECTION_LABELS[realtime.connectionState]}
            tone={
              realtime.connectionState === 'connected'
                ? Palette.emerald
                : realtime.connectionState === 'error'
                  ? Palette.red
                  : Palette.textMuted
            }
          />
          <DiagnosticRow
            label="雷达数据"
            value={RADAR_STATE_LABELS[frameState]}
            tone={radarTone(frameState)}
          />
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="坐姿数据" icon="body-outline" />
        <Text style={styles.sectionCopy}>
          当前姿态由设备端判定；六路 ADC 为最新原始值，仅用于现场排查。
        </Text>
        <View style={styles.rows}>
          <DiagnosticRow
            label="当前坐姿"
            value={
              postureEvent
                ? POSTURE_LABELS[postureEvent.payload.posture]
                : '等待数据'
            }
            tone={
              postureState === 'live'
                ? Palette.emerald
                : postureState === 'stale'
                  ? Palette.red
                  : Palette.textMuted
            }
          />
          <DiagnosticRow
            label="数据状态"
            value={
              postureState === 'live'
                ? '实时'
                : postureState === 'stale'
                  ? '已中断'
                  : '等待新帧'
            }
          />
          <DiagnosticRow
            label="最近更新"
            value={formatTime(postureEvent?.capturedAt)}
          />
          <DiagnosticRow
            label="左膝 s4"
            value={postureValues.leftKnee?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="左中 s6"
            value={postureValues.leftMid?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="左坐骨 s2"
            value={postureValues.leftIschial?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="右坐骨 s3"
            value={postureValues.rightIschial?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="右中 s5"
            value={postureValues.rightMid?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="右膝 s1"
            value={postureValues.rightKnee?.toString() ?? '—'}
          />
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="雷达帧" icon="radio-outline" />
        <View style={styles.rows}>
          <DiagnosticRow
            label="硬件 seq"
            value={diagnostics.seq?.toString() ?? '—'}
          />
          <DiagnosticRow
            label="连续久坐"
            value={formatContinuousSeated(realtime.continuousSeatedSeconds)}
            tone={
              realtime.continuousSeatedSeconds === null
                ? Palette.textMuted
                : Palette.amber
            }
          />
          <DiagnosticRow
            label="最后收到消息"
            value={formatTime(diagnostics.lastMessageAt)}
          />
          <DiagnosticRow
            label="最后新帧"
            value={formatTime(diagnostics.lastFreshFrameAt)}
          />
          <DiagnosticRow
            label="缓存保活次数"
            value={diagnostics.keepaliveCount.toString()}
          />
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="测量诊断" icon="analytics-outline" />
        <Text style={styles.sectionCopy}>
          观众界面只使用 60 秒滑动中值；原始值仅供现场排障。
        </Text>
        <View style={styles.rows}>
          <DiagnosticRow
            label="心率中值"
            value={`${formatMetric(diagnostics.heartMedian)} BPM`}
            tone={Palette.emerald}
          />
          <DiagnosticRow
            label="心率原始值"
            value={`${formatMetric(diagnostics.heartRaw)} BPM`}
          />
          <DiagnosticRow
            label="呼吸中值"
            value={`${formatMetric(diagnostics.breathMedian)} 次/分`}
            tone={Palette.emerald}
          />
          <DiagnosticRow
            label="呼吸原始值"
            value={`${formatMetric(diagnostics.breathRaw)} 次/分`}
          />
          <DiagnosticRow
            label="协议检查"
            value={issues}
            tone={
              diagnostics.issues.length === 0
                ? Palette.emerald
                : Palette.red
            }
          />
        </View>
      </SurfaceCard>

      <Pressable
        accessibilityRole="button"
        disabled={reconnecting}
        onPress={() => void reconnect()}
        style={({ pressed }) => [
          styles.primaryButton,
          reconnecting && styles.disabled,
          pressed && styles.pressed,
        ]}>
        <Ionicons name="refresh" size={18} color="#FFFFFF" />
        <Text style={styles.primaryButtonText}>
          {reconnecting ? '正在重新连接' : '重新连接'}
        </Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        onPress={() => router.push('/settings')}
        style={({ pressed }) => [
          styles.secondaryButton,
          pressed && styles.pressed,
        ]}>
        <Ionicons name="settings-outline" size={18} color={Palette.sky} />
        <Text style={styles.secondaryButtonText} numberOfLines={1}>
          修改 Broker 地址
        </Text>
      </Pressable>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    paddingTop: Spacing.sm,
    marginBottom: Spacing.sm,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Palette.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerText: { flex: 1 },
  title: { color: Palette.text, fontSize: 24, fontWeight: '800' },
  subtitle: {
    color: Palette.textMuted,
    fontSize: 11,
    marginTop: 3,
  },
  rows: { marginTop: Spacing.md },
  sectionCopy: {
    color: Palette.textMuted,
    fontSize: 11,
    lineHeight: 18,
    marginTop: Spacing.sm,
  },
  primaryButton: {
    minHeight: 50,
    borderRadius: Radius.pill,
    backgroundColor: Palette.text,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '800',
  },
  secondaryButton: {
    minHeight: 48,
    borderRadius: Radius.pill,
    backgroundColor: Palette.surface,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
  },
  secondaryButtonText: {
    color: Palette.sky,
    fontSize: 13,
    fontWeight: '700',
  },
  disabled: { opacity: 0.55 },
  pressed: { opacity: 0.68 },
});
