import mqtt, {
  type IClientOptions,
  type MqttClient,
} from 'mqtt';

import {
  CushionPosture,
  CushionRealtimeConnectionOptions,
  CushionRealtimeConnectionSnapshot,
  CushionRealtimeEvent,
  CushionRealtimeStreamType,
  RadarDiagnosticsSnapshot,
  RadarDiagnosticsIssue,
  RealtimeImportError,
} from '@/domain/realtime-types';

export const DEFAULT_CUSHION_MQTT_URL = 'ws://10.76.12.7:9001';
export const CUSHION_MQTT_SETTING_KEY = 'cushion.mqtt.url';

const POSTURE_TOPIC = 'zuodian/posture';
const RADAR_TOPIC = 'zuodian/radar';
const TOPICS = [POSTURE_TOPIC, RADAR_TOPIC];
const RADAR_HEART_MIN = 40;
const RADAR_HEART_MAX = 150;
const RADAR_BREATH_MIN = 6;
const RADAR_BREATH_MAX = 30;

type EventInput = CushionRealtimeEvent | Record<string, unknown>;

export interface CushionMqttTransportHandlers {
  onConnection(snapshot: CushionRealtimeConnectionSnapshot): void;
  onRadarDiagnostics(snapshot: RadarDiagnosticsSnapshot): void;
  onInput(input: EventInput): void;
  onImportError(error: RealtimeImportError): void;
}

type MqttConnect = (brokerUrl: string, options: IClientOptions) => MqttClient;

interface TransportDependencies {
  connectClient?: MqttConnect;
  now?: () => Date;
  createSessionId?: () => string;
}

const defaultConnectClient: MqttConnect = (brokerUrl, options) => {
  return mqtt.connect(brokerUrl, options);
};

export interface CushionMqttTransport {
  connect(options: CushionRealtimeConnectionOptions): Promise<void>;
  disconnect(): Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function safeSequence(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function emptyRadarDiagnostics(): RadarDiagnosticsSnapshot {
  return { keepaliveCount: 0, issues: [] };
}

function privateIpv4(hostname: string) {
  const parts = hostname.split('.').map(Number);
  if (
    parts.length !== 4 ||
    parts.some(
      (part) => !Number.isInteger(part) || part < 0 || part > 255,
    )
  ) {
    return false;
  }
  return (
    parts[0] === 10 ||
    parts[0] === 127 ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168)
  );
}

function localWebSocketHost(hostname: string) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  const privateIpv6 =
    normalized.includes(':') &&
    (normalized.startsWith('fc') ||
      normalized.startsWith('fd') ||
      normalized.startsWith('fe80:'));
  return (
    normalized === 'localhost' ||
    normalized === '::1' ||
    normalized.endsWith('.local') ||
    privateIpv6 ||
    privateIpv4(normalized)
  );
}

export function normalizeCushionBrokerUrl(value: string):
  | { url: string; error?: never }
  | { url?: never; error: RealtimeImportError } {
  try {
    const parsed = new URL(value.trim());
    if (
      (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      (parsed.protocol === 'ws:' && !localWebSocketHost(parsed.hostname))
    ) {
      return {
        error: { code: 'INVALID_EVENT', field: 'brokerUrl' },
      };
    }
    const normalized = parsed.toString();
    return {
      url:
        parsed.pathname === '/' && normalized.endsWith('/')
          ? normalized.slice(0, -1)
          : normalized,
    };
  } catch {
    return {
      error: { code: 'INVALID_EVENT', field: 'brokerUrl' },
    };
  }
}

function mappedPosture(value: unknown): CushionPosture | undefined {
  if (value === 'AWAY') return 'away';
  if (value === 'UPRIGHT') return 'upright';
  if (value === 'LEAN_L') return 'leanLeft';
  if (value === 'LEAN_R') return 'leanRight';
  if (value === 'FORWARD') return 'forward';
  if (value === 'RECLINE') return 'recline';
  if (value === 'EDGE') return 'edge';
  if (value === 'OTHER') return 'other';
  return undefined;
}

export function createMqttCushionTransport(
  handlers: CushionMqttTransportHandlers,
  {
    connectClient = defaultConnectClient,
    now = () => new Date(),
    createSessionId = () =>
      `mqtt-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  }: TransportDependencies = {},
): CushionMqttTransport {
  let client: MqttClient | undefined;
  let manualDisconnect = true;
  let sessionId = '';
  let lastRadarSequence: number | undefined;
  let radarDiagnostics = emptyRadarDiagnostics();
  let settledConnect:
    | {
        resolve: () => void;
        reject: (error: Error) => void;
      }
    | undefined;
  let sequences: Record<CushionRealtimeStreamType, number> = {
    heartRate: 0,
    respiratoryRate: 0,
    posture: 0,
    pressureFrame: 0,
  };

  const baseEvent = (
    type: CushionRealtimeStreamType,
    deviceId: string,
  ) => ({
    schemaVersion: 1 as const,
    deviceId,
    sessionId,
    streamSequence: sequences[type]++,
    capturedAt: now().toISOString(),
  });

  const publishRadarDiagnostics = (next: RadarDiagnosticsSnapshot) => {
    radarDiagnostics = { ...next, issues: [...next.issues] };
    handlers.onRadarDiagnostics({
      ...radarDiagnostics,
      issues: [...radarDiagnostics.issues],
    });
  };

  const handleMessage = (topic: string, message: Uint8Array) => {
    let input: unknown;
    try {
      input = JSON.parse(new TextDecoder().decode(message));
    } catch {
      handlers.onImportError({ code: 'INVALID_EVENT' });
      return;
    }
    if (!isRecord(input)) {
      handlers.onImportError({ code: 'INVALID_EVENT' });
      return;
    }

    if (topic === RADAR_TOPIC) {
      const messageAt = now().toISOString();
      if (!safeSequence(input.seq)) {
        publishRadarDiagnostics({
          ...radarDiagnostics,
          lastMessageAt: messageAt,
          lastMessageKind: 'invalid',
          issues: ['INVALID_RADAR_SEQUENCE'],
        });
        handlers.onImportError({ code: 'INVALID_EVENT', field: 'seq' });
        return;
      }

      if (lastRadarSequence === input.seq) {
        publishRadarDiagnostics({
          ...radarDiagnostics,
          lastMessageAt: messageAt,
          lastMessageKind: 'keepalive',
          keepaliveCount: radarDiagnostics.keepaliveCount + 1,
          issues: [],
        });
        return;
      }

      lastRadarSequence = input.seq;
      const issues: RadarDiagnosticsIssue[] = [];
      const distanceCm =
        finiteNumber(input.dist) && input.dist >= 0
          ? input.dist
          : undefined;
      const distanceValid = distanceCm !== undefined;
      const heartMedianValid =
        finiteNumber(input.heart_med) &&
        input.heart_med >= RADAR_HEART_MIN &&
        input.heart_med <= RADAR_HEART_MAX;
      const breathMedianValid =
        finiteNumber(input.breath_med) &&
        input.breath_med >= RADAR_BREATH_MIN &&
        input.breath_med <= RADAR_BREATH_MAX;

      if (!distanceValid) {
        issues.push('INVALID_RADAR_DISTANCE');
        handlers.onImportError({ code: 'INVALID_EVENT', field: 'dist' });
      }
      if (!heartMedianValid) {
        issues.push('INVALID_RADAR_HEART_MEDIAN');
        handlers.onImportError({
          code: 'INVALID_HEART_RATE',
          field: 'heart_med',
        });
      }
      if (!breathMedianValid) {
        issues.push('INVALID_RADAR_BREATH_MEDIAN');
        handlers.onImportError({
          code: 'INVALID_RESPIRATORY_RATE',
          field: 'breath_med',
        });
      }

      publishRadarDiagnostics({
        seq: input.seq,
        distanceCm,
        heartRaw: finiteNumber(input.heart) ? input.heart : undefined,
        breathRaw: finiteNumber(input.breath) ? input.breath : undefined,
        heartMedian: finiteNumber(input.heart_med)
          ? input.heart_med
          : undefined,
        breathMedian: finiteNumber(input.breath_med)
          ? input.breath_med
          : undefined,
        lastMessageAt: messageAt,
        lastFreshFrameAt: messageAt,
        keepaliveCount: radarDiagnostics.keepaliveCount,
        lastMessageKind: 'fresh',
        issues,
      });

      if (heartMedianValid) {
        handlers.onInput({
          ...baseEvent('heartRate', 'zuodian-radar'),
          type: 'heartRate',
          payload: { bpm: input.heart_med },
        });
      }
      if (breathMedianValid) {
        handlers.onInput({
          ...baseEvent('respiratoryRate', 'zuodian-radar'),
          type: 'respiratoryRate',
          payload: { breathsPerMinute: input.breath_med },
        });
      }
      return;
    }

    if (topic === POSTURE_TOPIC) {
      handlers.onInput({
        ...baseEvent('posture', 'zuodian-posture'),
        type: 'posture',
        payload: {
          posture: mappedPosture(input.pose),
          layoutId: 'fsr6-v1',
          sensors: [
            { sensorId: 'leftKnee', rawAdc: input.s4 },
            { sensorId: 'leftMid', rawAdc: input.s6 },
            { sensorId: 'leftIschial', rawAdc: input.s2 },
            { sensorId: 'rightIschial', rawAdc: input.s3 },
            { sensorId: 'rightMid', rawAdc: input.s5 },
            { sensorId: 'rightKnee', rawAdc: input.s1 },
          ],
        },
      });
    }
  };

  const disconnect = async () => {
    manualDisconnect = true;
    const activeClient = client;
    client = undefined;
    if (settledConnect) {
      settledConnect.reject(new Error('MQTT connection cancelled'));
      settledConnect = undefined;
    }
    if (activeClient) {
      await new Promise<void>((resolve) => {
        activeClient.end(true, {}, () => resolve());
      });
      activeClient.removeAllListeners();
    }
    handlers.onConnection({ state: 'disconnected' });
  };

  return {
    async connect(options) {
      const normalized = normalizeCushionBrokerUrl(options.brokerUrl);
      if (normalized.error) {
        handlers.onConnection({
          state: 'error',
          error: { code: 'INVALID_BROKER_URL' },
        });
        throw new Error('Invalid MQTT broker URL');
      }

      if (client) await disconnect();
      manualDisconnect = false;
      sessionId = createSessionId();
      lastRadarSequence = undefined;
      publishRadarDiagnostics(emptyRadarDiagnostics());
      sequences = {
        heartRate: 0,
        respiratoryRate: 0,
        posture: 0,
        pressureFrame: 0,
      };
      handlers.onConnection({ state: 'connecting' });

      await new Promise<void>((resolve, reject) => {
        settledConnect = { resolve, reject };
        let nextClient: MqttClient;
        try {
          nextClient = connectClient(normalized.url, {
            protocolVersion: 4,
            clean: true,
            connectTimeout: 5_000,
            reconnectPeriod: 2_000,
            keepalive: 30,
            forceNativeWebSocket: true,
            timerVariant: 'native',
            createWebsocket: (url, protocols) =>
              new WebSocket(url, protocols),
            clientId: `youdiandongxi-${Math.random().toString(16).slice(2, 12)}`,
          });
        } catch (error) {
          const connectionError =
            error instanceof Error ? error : new Error(String(error));
          handlers.onConnection({
            state: 'error',
            error: { code: 'CONNECTION_FAILED' },
          });
          settledConnect = undefined;
          reject(connectionError);
          return;
        }
        client = nextClient;

        nextClient.on('connect', () => {
          nextClient.subscribe(TOPICS, { qos: 0 }, (error) => {
            if (manualDisconnect) return;
            if (error) {
              handlers.onConnection({
                state: 'error',
                error: { code: 'SUBSCRIBE_FAILED' },
              });
              settledConnect?.reject(error);
              settledConnect = undefined;
              return;
            }
            handlers.onConnection({ state: 'connected' });
            settledConnect?.resolve();
            settledConnect = undefined;
          });
        });
        nextClient.on('message', handleMessage);
        nextClient.on('reconnect', () => {
          if (!manualDisconnect) {
            handlers.onConnection({ state: 'reconnecting' });
          }
        });
        nextClient.on('offline', () => {
          if (!manualDisconnect) {
            handlers.onConnection({ state: 'reconnecting' });
          }
        });
        nextClient.on('close', () => {
          if (!manualDisconnect) {
            handlers.onConnection({ state: 'reconnecting' });
          }
        });
        nextClient.on('error', (error) => {
          if (manualDisconnect) return;
          if (settledConnect) {
            handlers.onConnection({
              state: 'error',
              error: {
                code:
                  error.message.toLowerCase().includes('timeout')
                    ? 'CONNECT_TIMEOUT'
                    : 'CONNECTION_FAILED',
              },
            });
            settledConnect.reject(error);
            settledConnect = undefined;
          } else {
            handlers.onConnection({
              state: 'reconnecting',
              error: { code: 'CONNECTION_FAILED' },
            });
          }
        });
      });
    },

    disconnect,
  };
}
