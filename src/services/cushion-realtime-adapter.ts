import {
  CushionRealtimeCapabilities,
  CushionRealtimeConnectionOptions,
  CushionRealtimeConnectionSnapshot,
  CushionRealtimeEvent,
  PressureCalibration,
  RadarDiagnosticsSnapshot,
  RealtimeImportError,
  RealtimeImportResult,
} from '@/domain/realtime-types';
import {
  parseRealtimeEvent,
  REALTIME_REORDER_TOLERANCE_MS,
} from '@/domain/realtime';
import { CushionRealtimeAdapter } from '@/services/health-data-adapters';
import {
  createMqttCushionTransport,
  CushionMqttTransport,
  CushionMqttTransportHandlers,
} from '@/services/mqtt-cushion-transport';

function streamKey(event: CushionRealtimeEvent) {
  return `${event.deviceId}:${event.sessionId}:${event.type}`;
}

function eventKey(event: CushionRealtimeEvent) {
  return `${streamKey(event)}:${event.streamSequence}`;
}

function emptyResult(): RealtimeImportResult {
  return { accepted: 0, duplicates: 0, dropped: 0, errors: [] };
}

function copyRadarDiagnostics(
  snapshot: RadarDiagnosticsSnapshot,
): RadarDiagnosticsSnapshot {
  return { ...snapshot, issues: [...snapshot.issues] };
}

function inferredQuality(
  event: CushionRealtimeEvent,
  previous?: CushionRealtimeEvent,
) {
  if (event.quality !== undefined) return event.quality;
  if (!previous) return 1;
  const missing = Math.max(
    0,
    event.streamSequence - previous.streamSequence - 1,
  );
  const missingPenalty = Math.min(0.5, missing * 0.1);
  let jumpPenalty = 0;
  const elapsed =
    Date.parse(event.capturedAt) - Date.parse(previous.capturedAt);
  if (
    event.type === 'heartRate' &&
    previous.type === 'heartRate' &&
    elapsed <= 5_000 &&
    Math.abs(event.payload.bpm - previous.payload.bpm) > 30
  ) {
    jumpPenalty = 0.5;
  }
  if (
    event.type === 'respiratoryRate' &&
    previous.type === 'respiratoryRate' &&
    elapsed <= 90_000 &&
    Math.abs(
      event.payload.breathsPerMinute -
        previous.payload.breathsPerMinute,
    ) > 12
  ) {
    jumpPenalty = 0.3;
  }
  return Math.max(0, 1 - missingPenalty - jumpPenalty);
}

function withQuality(
  event: CushionRealtimeEvent,
  previous?: CushionRealtimeEvent,
): CushionRealtimeEvent {
  return { ...event, quality: inferredQuality(event, previous) };
}

function appendError(
  result: RealtimeImportResult,
  error: RealtimeImportError,
) {
  result.dropped += 1;
  result.errors.push(error);
}

export function createCushionRealtimeAdapter({
  initialCapabilities = {
    heartRate: true,
    respiratoryRate: true,
    posture: false,
    pressure: false,
    pressureCalibrated: false,
  },
  transportFactory = createMqttCushionTransport,
}: {
  initialCapabilities?: CushionRealtimeCapabilities;
  transportFactory?: (
    handlers: CushionMqttTransportHandlers,
  ) => CushionMqttTransport;
} = {}): CushionRealtimeAdapter {
  const listeners = new Set<(event: CushionRealtimeEvent) => void>();
  const connectionListeners = new Set<
    (snapshot: CushionRealtimeConnectionSnapshot) => void
  >();
  const radarDiagnosticsListeners = new Set<
    (snapshot: RadarDiagnosticsSnapshot) => void
  >();
  const importResultListeners = new Set<
    (result: RealtimeImportResult) => void
  >();
  const seenKeys = new Set<string>();
  const latestByStream = new Map<
    string,
    { sequence: number; capturedAt: number; event: CushionRealtimeEvent }
  >();
  const lastEmittedByStream = new Map<string, CushionRealtimeEvent>();
  const pendingByStream = new Map<string, CushionRealtimeEvent[]>();
  const flushTimers = new Map<string, ReturnType<typeof setTimeout>>();
  let connectionSnapshot: CushionRealtimeConnectionSnapshot = {
    state: 'disconnected',
  };
  let radarDiagnostics: RadarDiagnosticsSnapshot = {
    keepaliveCount: 0,
    issues: [],
  };
  let capabilities = { ...initialCapabilities };
  let pressureCalibration: PressureCalibration | undefined;

  const updateConnection = (snapshot: CushionRealtimeConnectionSnapshot) => {
    connectionSnapshot = snapshot;
    for (const listener of connectionListeners) listener(snapshot);
  };

  const notifyImportResult = (result: RealtimeImportResult) => {
    for (const listener of importResultListeners) listener(result);
  };

  const updateRadarDiagnostics = (snapshot: RadarDiagnosticsSnapshot) => {
    radarDiagnostics = copyRadarDiagnostics(snapshot);
    for (const listener of radarDiagnosticsListeners) {
      listener(copyRadarDiagnostics(radarDiagnostics));
    }
  };

  const flushStream = (stream: string) => {
    const pending = [...(pendingByStream.get(stream) ?? [])].sort((a, b) => {
      const timeDelta = Date.parse(a.capturedAt) - Date.parse(b.capturedAt);
      return timeDelta || a.streamSequence - b.streamSequence;
    });
    pendingByStream.delete(stream);
    flushTimers.delete(stream);
    let previous = lastEmittedByStream.get(stream);
    for (const rawEvent of pending) {
      const event = withQuality(rawEvent, previous);
      for (const listener of listeners) listener(event);
      previous = event;
    }
    if (previous) lastEmittedByStream.set(stream, previous);
  };

  let adapter: CushionRealtimeAdapter;
  const transport = transportFactory({
    onConnection: updateConnection,
    onRadarDiagnostics: updateRadarDiagnostics,
    onInput(input) {
      adapter.ingest(input);
    },
    onImportError(error) {
      const result = emptyResult();
      appendError(result, error);
      notifyImportResult(result);
    },
  });

  adapter = {
    async connect(options: CushionRealtimeConnectionOptions) {
      await transport.connect(options);
    },

    async disconnect() {
      await transport.disconnect();
      for (const timer of flushTimers.values()) clearTimeout(timer);
      flushTimers.clear();
      for (const stream of [...pendingByStream.keys()]) flushStream(stream);
    },

    getConnectionState() {
      return connectionSnapshot.state;
    },

    getConnectionSnapshot() {
      return {
        ...connectionSnapshot,
        error: connectionSnapshot.error
          ? { ...connectionSnapshot.error }
          : undefined,
      };
    },

    getCapabilities() {
      return { ...capabilities };
    },

    getRadarDiagnostics() {
      return copyRadarDiagnostics(radarDiagnostics);
    },

    getPressureCalibration() {
      return pressureCalibration;
    },

    setPressureCalibration(calibration) {
      pressureCalibration = calibration ?? undefined;
      capabilities = {
        ...capabilities,
        pressureCalibrated: Boolean(calibration),
      };
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    subscribeConnection(listener) {
      connectionListeners.add(listener);
      return () => connectionListeners.delete(listener);
    },

    subscribeRadarDiagnostics(listener) {
      radarDiagnosticsListeners.add(listener);
      return () => radarDiagnosticsListeners.delete(listener);
    },

    subscribeImportResults(listener) {
      importResultListeners.add(listener);
      return () => importResultListeners.delete(listener);
    },

    ingest(input) {
      const result = emptyResult();
      const parsed = parseRealtimeEvent(input);
      if (parsed.error) {
        appendError(result, parsed.error);
        notifyImportResult(result);
        return result;
      }
      const key = eventKey(parsed.event);
      if (seenKeys.has(key)) {
        result.duplicates += 1;
        result.errors.push({ code: 'DUPLICATE_EVENT' });
        notifyImportResult(result);
        return result;
      }
      const stream = streamKey(parsed.event);
      const latest = latestByStream.get(stream);
      const capturedAt = Date.parse(parsed.event.capturedAt);
      if (
        latest &&
        (capturedAt <
          latest.capturedAt - REALTIME_REORDER_TOLERANCE_MS ||
          (capturedAt >= latest.capturedAt &&
            parsed.event.streamSequence < latest.sequence))
      ) {
        appendError(result, { code: 'OUT_OF_ORDER_EVENT' });
        notifyImportResult(result);
        return result;
      }

      seenKeys.add(key);
      if (
        !latest ||
        capturedAt > latest.capturedAt ||
        (capturedAt === latest.capturedAt &&
          parsed.event.streamSequence > latest.sequence)
      ) {
        latestByStream.set(stream, {
          sequence: parsed.event.streamSequence,
          capturedAt,
          event: parsed.event,
        });
      }
      if (parsed.event.type === 'pressureFrame' && !capabilities.pressure) {
        capabilities = { ...capabilities, pressure: true };
      }
      if (parsed.event.type === 'posture' && !capabilities.posture) {
        capabilities = { ...capabilities, posture: true };
      }
      pendingByStream.set(stream, [
        ...(pendingByStream.get(stream) ?? []),
        parsed.event,
      ]);
      if (!flushTimers.has(stream)) {
        flushTimers.set(
          stream,
          setTimeout(
            () => flushStream(stream),
            REALTIME_REORDER_TOLERANCE_MS,
          ),
        );
      }
      result.accepted += 1;
      notifyImportResult(result);
      return result;
    },

    ingestBatch(inputs) {
      return inputs.reduce<RealtimeImportResult>((total, input) => {
        const result = adapter.ingest(input);
        total.accepted += result.accepted;
        total.duplicates += result.duplicates;
        total.dropped += result.dropped;
        total.errors.push(...result.errors);
        return total;
      }, emptyResult());
    },
  };
  return adapter;
}

export const cushionRealtimeAdapter = createCushionRealtimeAdapter();
