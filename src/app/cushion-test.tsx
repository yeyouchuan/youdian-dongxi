import { Ionicons } from '@expo/vector-icons';
import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';
import { Redirect, useRouter } from 'expo-router';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { AppScreen } from '@/components/app-screen';
import { SectionTitle } from '@/components/section-title';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { CushionRealtimeStreamType } from '@/domain/realtime-types';
import { useRealtime } from '@/state/realtime-context';

const SPEEDS = [0.5, 1, 2] as const;

function asReplayEvent(value: unknown, sessionId: string) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return value;
  }
  return {
    ...value,
    sessionId,
    capturedAt: new Date().toISOString(),
  };
}

function statusLabel(state: 'waiting' | 'live' | 'stale') {
  if (state === 'live') return '实时';
  if (state === 'stale') return '已中断';
  return '等待数据';
}

export default function CushionTestScreen() {
  const router = useRouter();
  const realtime = useRealtime();
  const componentId = useId().replaceAll(':', '');
  const ingest = realtime.ingest;
  const sequenceRef = useRef({ heartRate: 0, respiratoryRate: 0 });
  const manualSessionRef = useRef(`manual-${componentId}`);
  const replaySessionRef = useRef(`replay-${componentId}`);
  const [bpm, setBpm] = useState('72');
  const [breaths, setBreaths] = useState('14');
  const [replayEvents, setReplayEvents] = useState<unknown[]>([]);
  const [replayName, setReplayName] = useState<string>();
  const [replayIndex, setReplayIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [fileError, setFileError] = useState<string>();
  const postureEvent =
    realtime.latestByStream.posture?.type === 'posture'
      ? realtime.latestByStream.posture
      : undefined;

  useEffect(() => {
    if (!isPlaying || replayEvents.length === 0) return;
    if (replayIndex >= replayEvents.length) return;
    const timer = setTimeout(() => {
      ingest(
        asReplayEvent(
          replayEvents[replayIndex],
          replaySessionRef.current,
        ),
      );
      const nextIndex = replayIndex + 1;
      setReplayIndex(nextIndex);
      if (nextIndex >= replayEvents.length) setIsPlaying(false);
    }, 1_000 / speed);
    return () => clearTimeout(timer);
  }, [ingest, isPlaying, replayEvents, replayIndex, speed]);

  const diagnostics = useMemo(
    () =>
      (
        [
          ['heartRate', '心率'],
          ['respiratoryRate', '呼吸率'],
          ['posture', '坐姿'],
          ['pressureFrame', '压力'],
        ] as [CushionRealtimeStreamType, string][]
      ).map(([type, label]) => ({
        type,
        label,
        status: realtime.streamStatuses[type],
      })),
    [realtime.streamStatuses],
  );

  if (!__DEV__) return <Redirect href="/settings" />;

  const submitManual = async () => {
    const heartRate = Number(bpm);
    const respiratoryRate = Number(breaths);
    const capturedAt = new Date().toISOString();
    realtime.ingestBatch([
      {
        schemaVersion: 1,
        deviceId: 'development-replay',
        sessionId: manualSessionRef.current,
        streamSequence: sequenceRef.current.heartRate++,
        capturedAt,
        type: 'heartRate',
        payload: { bpm: heartRate },
      },
      {
        schemaVersion: 1,
        deviceId: 'development-replay',
        sessionId: manualSessionRef.current,
        streamSequence: sequenceRef.current.respiratoryRate++,
        capturedAt,
        type: 'respiratoryRate',
        payload: { breathsPerMinute: respiratoryRate },
      },
    ]);
  };

  const chooseJsonl = async () => {
    setFileError(undefined);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['application/json', 'application/jsonl', 'text/plain'],
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      const asset = result.assets[0];
      const contents = await new File(asset.uri).text();
      const lines = contents
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const parsed: unknown[] = [];
      for (let index = 0; index < lines.length; index += 1) {
        try {
          parsed.push(JSON.parse(lines[index]));
        } catch {
          throw new Error(`第 ${index + 1} 行不是有效 JSON`);
        }
      }
      if (parsed.length === 0) throw new Error('文件中没有事件');
      replaySessionRef.current = `replay-${Date.now()}`;
      setReplayEvents(parsed);
      setReplayIndex(0);
      setIsPlaying(false);
      setReplayName(asset.name);
    } catch (error) {
      setFileError(error instanceof Error ? error.message : '无法读取文件');
    }
  };

  const reconnect = async () => {
    setIsPlaying(false);
    await realtime.disconnect();
    await realtime.connect();
  };

  const toggleReplay = async () => {
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    if (replayIndex >= replayEvents.length) {
      replaySessionRef.current = `replay-${Date.now()}`;
      setReplayIndex(0);
    }
    setIsPlaying(true);
  };

  return (
    <AppScreen bottomPadding={48}>
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="返回"
          hitSlop={8}
          onPress={() => router.back()}
          style={styles.back}>
          <Ionicons name="chevron-back" size={25} color={Palette.text} />
        </Pressable>
        <View style={styles.headerText}>
          <Text style={styles.title}>坐垫数据测试</Text>
          <Text style={styles.subtitle}>仅 development build 可见</Text>
        </View>
      </View>

      <SurfaceCard>
        <SectionTitle title="手动导入" icon="pulse-outline" />
        <Text style={styles.copy}>
          事件只进入内存缓冲；原始 BPM 和呼吸率不会写入数据库。
        </Text>
        <View style={styles.inputRow}>
          <View style={styles.inputWrap}>
            <Text style={styles.inputLabel}>心率 BPM</Text>
            <TextInput
              accessibilityLabel="心率 BPM"
              keyboardType="decimal-pad"
              value={bpm}
              onChangeText={setBpm}
              style={styles.input}
            />
          </View>
          <View style={styles.inputWrap}>
            <Text style={styles.inputLabel}>呼吸 次/分</Text>
            <TextInput
              accessibilityLabel="呼吸次数每分钟"
              keyboardType="decimal-pad"
              value={breaths}
              onChangeText={setBreaths}
              style={styles.input}
            />
          </View>
        </View>
        <Pressable
          accessibilityRole="button"
          onPress={() => void submitManual()}
          style={({ pressed }) => [
            styles.primaryButton,
            pressed && styles.pressed,
          ]}>
          <Text style={styles.primaryButtonText}>发送一组数据</Text>
        </Pressable>
      </SurfaceCard>

      {postureEvent ? (
        <SurfaceCard>
          <SectionTitle title="MQTT 原始姿态" icon="grid-outline" />
          <Text style={styles.connection}>
            {postureEvent.payload.posture} · {postureEvent.payload.layoutId}
          </Text>
          <View style={styles.rawSensorGrid}>
            {postureEvent.payload.sensors.map((sensor) => (
              <View key={sensor.sensorId} style={styles.rawSensor}>
                <Text style={styles.rawSensorLabel}>{sensor.sensorId}</Text>
                <Text style={styles.rawSensorValue}>{sensor.rawAdc}</Text>
              </View>
            ))}
          </View>
        </SurfaceCard>
      ) : null}

      <SurfaceCard>
        <SectionTitle title="JSONL 回放" icon="document-text-outline" />
        <Text style={styles.copy}>
          每行一个版本化事件。回放会创建新会话并重写时间，不修改文件内容。
        </Text>
        <Pressable
          accessibilityRole="button"
          onPress={() => void chooseJsonl()}
          style={({ pressed }) => [
            styles.fileButton,
            pressed && styles.pressed,
          ]}>
          <Ionicons
            name="folder-open-outline"
            size={19}
            color={Palette.sky}
          />
          <Text style={styles.fileButtonText}>
            {replayName ?? '选择 .jsonl 文件'}
          </Text>
        </Pressable>
        {fileError ? <Text style={styles.errorText}>{fileError}</Text> : null}
        <View style={styles.speedRow}>
          {SPEEDS.map((value) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: speed === value }}
              onPress={() => setSpeed(value)}
              style={[
                styles.speedButton,
                speed === value && styles.speedButtonSelected,
              ]}>
              <Text
                style={[
                  styles.speedText,
                  speed === value && styles.speedTextSelected,
                ]}>
                {value}×
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.controlRow}>
          <Pressable
            accessibilityRole="button"
            disabled={replayEvents.length === 0}
            onPress={() => void toggleReplay()}
            style={[
              styles.controlButton,
              replayEvents.length === 0 && styles.disabled,
            ]}>
            <Ionicons
              name={isPlaying ? 'pause' : 'play'}
              size={19}
              color={Palette.text}
            />
            <Text style={styles.controlText}>
              {isPlaying ? '暂停' : '播放'} · {replayIndex}/{replayEvents.length}
            </Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            onPress={() => void reconnect()}
            style={styles.controlButton}>
            <Ionicons name="refresh" size={19} color={Palette.text} />
            <Text style={styles.controlText}>断线重连</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SectionTitle title="流诊断" icon="analytics-outline" />
        <Text style={styles.connection}>
          连接：{realtime.connectionState} · 接受 {realtime.importResult.accepted}{' '}
          · 重复 {realtime.importResult.duplicates} · 丢弃{' '}
          {realtime.importResult.dropped}
        </Text>
        <View style={styles.diagnosticList}>
          {diagnostics.map(({ type, label, status }) => (
            <View key={type} style={styles.diagnosticRow}>
              <View
                style={[
                  styles.dot,
                  status.state === 'live'
                    ? styles.dotLive
                    : status.state === 'stale'
                      ? styles.dotStale
                      : styles.dotWaiting,
                ]}
              />
              <View style={styles.diagnosticText}>
                <Text style={styles.diagnosticLabel}>{label}</Text>
                <Text style={styles.diagnosticMeta}>
                  {status.lastCapturedAt
                    ? new Date(status.lastCapturedAt).toLocaleTimeString(
                        'zh-CN',
                      )
                    : '尚无数据'}
                </Text>
              </View>
              <Text style={styles.diagnosticState}>
                {statusLabel(status.state)}
                {status.quality === undefined
                  ? ''
                  : ` · 质量 ${Math.round(status.quality * 100)}%`}
              </Text>
            </View>
          ))}
        </View>
        {realtime.importResult.errors.length > 0 ? (
          <Text style={styles.errorSummary}>
            最近错误：{realtime.importResult.errors.at(-1)?.code}
          </Text>
        ) : null}
      </SurfaceCard>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xs,
    flexDirection: 'row',
    alignItems: 'center',
  },
  back: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: Palette.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  headerText: { flex: 1 },
  title: {
    color: Palette.text,
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -0.6,
  },
  subtitle: { color: Palette.textMuted, fontSize: 12, marginTop: 3 },
  copy: {
    color: Palette.textMuted,
    fontSize: 12,
    lineHeight: 19,
    marginTop: Spacing.sm,
  },
  inputRow: {
    flexDirection: 'row',
    gap: Spacing.md,
    marginTop: Spacing.lg,
  },
  inputWrap: { flex: 1 },
  inputLabel: {
    color: Palette.textSecondary,
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 6,
  },
  input: {
    minHeight: 48,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceRaised,
    color: Palette.text,
    fontSize: 18,
    fontWeight: '700',
    paddingHorizontal: Spacing.md,
  },
  primaryButton: {
    minHeight: 48,
    borderRadius: Radius.pill,
    backgroundColor: Palette.red,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: Spacing.lg,
  },
  primaryButtonText: { color: '#FFFFFF', fontSize: 14, fontWeight: '800' },
  fileButton: {
    minHeight: 48,
    borderRadius: Radius.md,
    backgroundColor: '#E7F2FF',
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    paddingHorizontal: Spacing.lg,
    marginTop: Spacing.lg,
  },
  fileButtonText: {
    color: Palette.sky,
    fontSize: 13,
    fontWeight: '700',
    flexShrink: 1,
  },
  errorText: {
    color: Palette.red,
    fontSize: 11,
    lineHeight: 17,
    marginTop: Spacing.sm,
  },
  speedRow: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginTop: Spacing.lg,
  },
  speedButton: {
    minWidth: 58,
    minHeight: 44,
    borderRadius: Radius.pill,
    backgroundColor: Palette.surfaceRaised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  speedButtonSelected: { backgroundColor: Palette.text },
  speedText: { color: Palette.textSecondary, fontWeight: '700' },
  speedTextSelected: { color: '#FFFFFF' },
  controlRow: {
    flexDirection: 'row',
    gap: Spacing.sm,
    marginTop: Spacing.md,
  },
  controlButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceMuted,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    paddingHorizontal: Spacing.sm,
  },
  controlText: { color: Palette.text, fontSize: 12, fontWeight: '700' },
  disabled: { opacity: 0.45 },
  connection: {
    color: Palette.textSecondary,
    fontSize: 12,
    lineHeight: 19,
    marginTop: Spacing.md,
  },
  rawSensorGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.sm,
    marginTop: Spacing.md,
  },
  rawSensor: {
    minWidth: '30%',
    flexGrow: 1,
    borderRadius: Radius.md,
    backgroundColor: Palette.surfaceMuted,
    padding: Spacing.md,
  },
  rawSensorLabel: {
    color: Palette.textMuted,
    fontSize: 10,
  },
  rawSensorValue: {
    color: Palette.text,
    fontSize: 20,
    fontWeight: '800',
    marginTop: 4,
  },
  diagnosticList: { marginTop: Spacing.md },
  diagnosticRow: {
    minHeight: 58,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
    flexDirection: 'row',
    alignItems: 'center',
  },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: Spacing.md },
  dotLive: { backgroundColor: Palette.emerald },
  dotStale: { backgroundColor: Palette.amber },
  dotWaiting: { backgroundColor: Palette.textMuted },
  diagnosticText: { flex: 1 },
  diagnosticLabel: { color: Palette.text, fontSize: 13, fontWeight: '700' },
  diagnosticMeta: { color: Palette.textMuted, fontSize: 10, marginTop: 3 },
  diagnosticState: {
    color: Palette.textSecondary,
    fontSize: 11,
    textAlign: 'right',
  },
  errorSummary: {
    color: Palette.red,
    fontSize: 11,
    lineHeight: 17,
    marginTop: Spacing.md,
  },
  pressed: { opacity: 0.7, transform: [{ scale: 0.99 }] },
});
