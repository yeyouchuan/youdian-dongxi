import {
  CushionRealtimeEvent,
  CushionRealtimeStreamType,
  PhysiologyWindowSummary,
  PressureCalibration,
  PressureFeatureSummary,
  RadarDiagnosticsSnapshot,
  RadarFrameStatus,
  RealtimePostureSegment,
  RealtimeImportError,
  RealtimeStreamStatus,
} from '@/domain/realtime-types';
import { PressureSample } from '@/domain/types';

export const REALTIME_WINDOW_MS = 5 * 60 * 1000;
export const REALTIME_REORDER_TOLERANCE_MS = 2_000;
export const RADAR_STALE_AFTER_MS = 15_000;

const STALE_AFTER_MS: Record<CushionRealtimeStreamType, number> = {
  heartRate: RADAR_STALE_AFTER_MS,
  respiratoryRate: RADAR_STALE_AFTER_MS,
  posture: 2_000,
  pressureFrame: 2_000,
};

const POSTURES = new Set([
  'away',
  'upright',
  'leanLeft',
  'leanRight',
  'edge',
  'other',
]);

const POSTURE_SENSOR_IDS = new Set([
  'leftIschial',
  'rightIschial',
  'leftThigh',
  'rightThigh',
  'frontEdge',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function validText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function commonError(event: Record<string, unknown>): RealtimeImportError | null {
  if (event.schemaVersion !== 1) {
    return { code: 'INVALID_SCHEMA_VERSION', field: 'schemaVersion' };
  }
  if (
    !validText(event.deviceId) ||
    !validText(event.sessionId) ||
    !Number.isSafeInteger(event.streamSequence) ||
    (event.streamSequence as number) < 0
  ) {
    return { code: 'INVALID_EVENT' };
  }
  if (
    !validText(event.capturedAt) ||
    !Number.isFinite(Date.parse(event.capturedAt))
  ) {
    return { code: 'INVALID_TIMESTAMP', field: 'capturedAt' };
  }
  if (
    event.quality !== undefined &&
    (!finiteNumber(event.quality) || event.quality < 0 || event.quality > 1)
  ) {
    return { code: 'INVALID_QUALITY', field: 'quality' };
  }
  return null;
}

export function parseRealtimeEvent(
  input: unknown,
):
  | { event: CushionRealtimeEvent; error?: never }
  | { event?: never; error: RealtimeImportError } {
  if (!isRecord(input)) {
    return { error: { code: 'INVALID_EVENT' } };
  }
  const sharedError = commonError(input);
  if (sharedError) return { error: sharedError };
  if (!isRecord(input.payload)) {
    return { error: { code: 'INVALID_EVENT', field: 'payload' } };
  }

  if (input.type === 'heartRate') {
    if (
      !finiteNumber(input.payload.bpm) ||
      input.payload.bpm < 30 ||
      input.payload.bpm > 240
    ) {
      return { error: { code: 'INVALID_HEART_RATE', field: 'payload.bpm' } };
    }
  } else if (input.type === 'respiratoryRate') {
    if (
      !finiteNumber(input.payload.breathsPerMinute) ||
      input.payload.breathsPerMinute < 4 ||
      input.payload.breathsPerMinute > 60
    ) {
      return {
        error: {
          code: 'INVALID_RESPIRATORY_RATE',
          field: 'payload.breathsPerMinute',
        },
      };
    }
  } else if (input.type === 'posture') {
    if (
      input.payload.layoutId !== 'fsr5-v1' ||
      !POSTURES.has(input.payload.posture as string) ||
      !Array.isArray(input.payload.sensors) ||
      input.payload.sensors.length !== POSTURE_SENSOR_IDS.size
    ) {
      return {
        error: { code: 'INVALID_POSTURE', field: 'payload' },
      };
    }
    const sensorIds = new Set<string>();
    const rawValues: number[] = [];
    for (const value of input.payload.sensors) {
      if (
        !isRecord(value) ||
        !POSTURE_SENSOR_IDS.has(value.sensorId as string) ||
        sensorIds.has(value.sensorId as string) ||
        !Number.isInteger(value.rawAdc) ||
        (value.rawAdc as number) < 0 ||
        (value.rawAdc as number) > 4095
      ) {
        return {
          error: { code: 'INVALID_POSTURE', field: 'payload.sensors' },
        };
      }
      sensorIds.add(value.sensorId as string);
      rawValues.push(value.rawAdc as number);
    }
    if (rawValues.every((value) => value >= 4090)) {
      return {
        error: { code: 'SENSOR_SATURATED', field: 'payload.sensors' },
      };
    }
  } else if (input.type === 'pressureFrame') {
    if (
      !validText(input.payload.layoutId) ||
      !Array.isArray(input.payload.cells) ||
      input.payload.cells.length === 0
    ) {
      return {
        error: { code: 'INVALID_PRESSURE_FRAME', field: 'payload' },
      };
    }
    for (const value of input.payload.cells) {
      if (
        !isRecord(value) ||
        !validText(value.sensorId) ||
        !finiteNumber(value.x) ||
        value.x < 0 ||
        value.x > 1 ||
        !finiteNumber(value.y) ||
        value.y < 0 ||
        value.y > 1 ||
        !finiteNumber(value.forceN) ||
        value.forceN < 0 ||
        (value.quality !== undefined &&
          (!finiteNumber(value.quality) ||
            value.quality < 0 ||
            value.quality > 1))
      ) {
        return {
          error: {
            code: 'INVALID_PRESSURE_FRAME',
            field: 'payload.cells',
          },
        };
      }
    }
  } else {
    return { error: { code: 'INVALID_EVENT', field: 'type' } };
  }

  return { event: input as unknown as CushionRealtimeEvent };
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function rounded(value: number) {
  return Math.round(value * 1000) / 1000;
}

function coverageFor(
  events: CushionRealtimeEvent[],
  windowStart: number,
  windowMs: number,
  continuityLimitMs: number,
) {
  if (events.length === 0) return 0;
  const windowEnd = windowStart + windowMs;
  const times = events
    .map((event) => Date.parse(event.capturedAt))
    .sort((a, b) => a - b);
  let coveredMs = 0;
  for (let index = 0; index < times.length; index += 1) {
    const start = Math.max(windowStart, times[index]);
    const next = times[index + 1] ?? windowEnd;
    const end = Math.min(windowEnd, next, start + continuityLimitMs);
    coveredMs += Math.max(0, end - start);
  }
  return Math.min(1, coveredMs / windowMs);
}

export function buildPhysiologyWindow(
  events: CushionRealtimeEvent[],
  now = new Date(),
  windowMs = REALTIME_WINDOW_MS,
): PhysiologyWindowSummary | null {
  const endTime = now.getTime();
  const startTime = endTime - windowMs;
  const eligible = events
    .filter((event) => {
      const time = Date.parse(event.capturedAt);
      return time >= startTime && time <= endTime;
    })
    .sort(
      (a, b) => Date.parse(a.capturedAt) - Date.parse(b.capturedAt),
    );
  const latest = eligible.at(-1);
  if (!latest) return null;
  const sessionEvents = eligible.filter(
    (event) =>
      event.deviceId === latest.deviceId &&
      event.sessionId === latest.sessionId,
  );

  const heartEvents = sessionEvents.filter(
    (event): event is Extract<CushionRealtimeEvent, { type: 'heartRate' }> =>
      event.type === 'heartRate',
  );
  const respiratoryEvents = sessionEvents.filter(
    (
      event,
    ): event is Extract<
      CushionRealtimeEvent,
      { type: 'respiratoryRate' }
    > => event.type === 'respiratoryRate',
  );
  let heartRateStable = heartEvents.length > 0;
  for (let index = 1; index < heartEvents.length; index += 1) {
    const previous = heartEvents[index - 1];
    const current = heartEvents[index];
    if (
      Date.parse(current.capturedAt) - Date.parse(previous.capturedAt) <= 5_000 &&
      Math.abs(current.payload.bpm - previous.payload.bpm) > 30
    ) {
      heartRateStable = false;
      break;
    }
  }

  return {
    id: `${latest.deviceId}:${latest.sessionId}:${new Date(startTime).toISOString()}`,
    deviceId: latest.deviceId,
    sessionId: latest.sessionId,
    startAt: new Date(startTime).toISOString(),
    endAt: now.toISOString(),
    heartRateMedian: median(
      heartEvents.map((event) => event.payload.bpm),
    ),
    respiratoryRateMedian: median(
      respiratoryEvents.map((event) => event.payload.breathsPerMinute),
    ),
    heartRateCoverage: rounded(
      coverageFor(heartEvents, startTime, windowMs, 10_000),
    ),
    respiratoryRateCoverage: rounded(
      coverageFor(respiratoryEvents, startTime, windowMs, 90_000),
    ),
    heartRateStable,
    heartRateQuality: median(
      heartEvents.map((event) => event.quality ?? 1),
    ),
    respiratoryRateQuality: median(
      respiratoryEvents.map((event) => event.quality ?? 1),
    ),
  };
}

export function isValidPhysiologyWindow(
  window: PhysiologyWindowSummary | null,
): window is PhysiologyWindowSummary {
  return Boolean(
    window &&
      window.heartRateMedian !== null &&
      window.respiratoryRateMedian !== null &&
      window.heartRateCoverage >= 0.8 &&
      window.respiratoryRateCoverage >= 0.8 &&
      window.heartRateStable &&
      (window.heartRateQuality ?? 0) >= 0.7 &&
      (window.respiratoryRateQuality ?? 0) >= 0.7,
  );
}

export function getRealtimeStreamStatus(
  type: CushionRealtimeStreamType,
  event: CushionRealtimeEvent | undefined,
  now = new Date(),
): RealtimeStreamStatus {
  if (!event) return { type, state: 'waiting' };
  const age = now.getTime() - Date.parse(event.capturedAt);
  return {
    type,
    state: age <= STALE_AFTER_MS[type] ? 'live' : 'stale',
    lastCapturedAt: event.capturedAt,
    quality: event.quality,
  };
}

export function getRadarFrameStatus(
  diagnostics: RadarDiagnosticsSnapshot,
  now = new Date(),
): RadarFrameStatus {
  const shared = {
    lastMessageAt: diagnostics.lastMessageAt,
    lastFreshFrameAt: diagnostics.lastFreshFrameAt,
  };
  if (!diagnostics.lastFreshFrameAt) {
    return { state: 'waiting', ...shared };
  }
  const age = now.getTime() - Date.parse(diagnostics.lastFreshFrameAt);
  if (age > RADAR_STALE_AFTER_MS) {
    return { state: 'stale', ...shared };
  }
  return {
    state:
      diagnostics.lastMessageKind === 'keepalive' ? 'cached' : 'live',
    ...shared,
  };
}

function pressureQuality(
  event: Extract<CushionRealtimeEvent, { type: 'pressureFrame' }>,
) {
  return (
    median(
      event.payload.cells.map((cell) => cell.quality ?? event.quality ?? 1),
    ) ?? 0
  );
}

export function buildPressureFeatures(
  event: Extract<CushionRealtimeEvent, { type: 'pressureFrame' }>,
  calibration?: PressureCalibration,
): PressureFeatureSummary {
  const calibrationReady =
    calibration?.layoutId === event.payload.layoutId;
  const normalized = event.payload.cells.map((cell) => ({
    ...cell,
    forceN: Math.max(
      0,
      cell.forceN -
        (calibrationReady
          ? (calibration.emptyBaselineBySensor[cell.sensorId] ?? 0)
          : 0),
    ),
  }));
  const totalForceN = normalized.reduce(
    (total, cell) => total + cell.forceN,
    0,
  );
  const center =
    totalForceN > 0
      ? {
          x:
            normalized.reduce(
              (total, cell) => total + cell.x * cell.forceN,
              0,
            ) / totalForceN,
          y:
            normalized.reduce(
              (total, cell) => total + cell.y * cell.forceN,
              0,
            ) / totalForceN,
        }
      : { x: 0.5, y: 0.5 };
  const quadrants = {
    frontLeftN: 0,
    frontRightN: 0,
    rearLeftN: 0,
    rearRightN: 0,
  };
  for (const cell of normalized) {
    const front = cell.y < 0.5;
    const left = cell.x < 0.5;
    const key = front
      ? left
        ? 'frontLeftN'
        : 'frontRightN'
      : left
        ? 'rearLeftN'
        : 'rearRightN';
    quadrants[key] += cell.forceN;
  }

  let inference: PressureFeatureSummary['inference'];
  if (!calibrationReady) {
    inference = {
      occupancy: 'unknown',
      posture: 'unknown',
      confidence: 0,
      modelVersion: 'unavailable',
      reasons: ['calibrationRequired'],
    };
  } else if (totalForceN < calibration.occupantThresholdN) {
    inference = {
      occupancy: 'away',
      posture: 'unknown',
      confidence: 1,
      modelVersion: calibration.modelVersion,
      reasons: ['belowOccupantThreshold'],
    };
  } else {
    const leftForce = quadrants.frontLeftN + quadrants.rearLeftN;
    const rightForce = quadrants.frontRightN + quadrants.rearRightN;
    const differenceRatio =
      Math.abs(leftForce - rightForce) / Math.max(1, totalForceN);
    inference = {
      occupancy: 'occupied',
      posture: differenceRatio >= 0.18 ? 'other' : 'upright',
      confidence: Math.min(
        0.99,
        0.72 + Math.abs(differenceRatio - 0.18),
      ),
      modelVersion: calibration.modelVersion,
      reasons: [
        differenceRatio >= 0.18
          ? 'leftRightImbalance'
          : 'leftRightBalanced',
      ],
    };
  }

  return {
    id: `${event.deviceId}:${event.sessionId}:${event.capturedAt}`,
    deviceId: event.deviceId,
    sessionId: event.sessionId,
    capturedAt: event.capturedAt,
    layoutId: event.payload.layoutId,
    calibrationState: calibrationReady
      ? 'ready'
      : 'calibrationRequired',
    totalForceN: rounded(totalForceN),
    centerOfPressure: {
      x: rounded(center.x),
      y: rounded(center.y),
    },
    quadrants: {
      frontLeftN: rounded(quadrants.frontLeftN),
      frontRightN: rounded(quadrants.frontRightN),
      rearLeftN: rounded(quadrants.rearLeftN),
      rearRightN: rounded(quadrants.rearRightN),
    },
    quality: rounded(pressureQuality(event)),
    inference,
  };
}

export function legacyPressureSampleToFeature(
  sample: PressureSample,
  {
    deviceId = 'legacy-cushion',
    sessionId = `legacy:${sample.timestamp.slice(0, 10)}`,
  }: { deviceId?: string; sessionId?: string } = {},
): PressureFeatureSummary {
  const toNewtons = (kilograms: number) => kilograms * 9.80665;
  const quadrants = {
    frontLeftN: toNewtons(sample.frontLeftKg),
    frontRightN: toNewtons(sample.frontRightKg),
    rearLeftN: toNewtons(sample.rearLeftKg),
    rearRightN: toNewtons(sample.rearRightKg),
  };
  const totalForceN =
    quadrants.frontLeftN +
    quadrants.frontRightN +
    quadrants.rearLeftN +
    quadrants.rearRightN;
  const left = quadrants.frontLeftN + quadrants.rearLeftN;
  const front = quadrants.frontLeftN + quadrants.frontRightN;
  return {
    id: `${deviceId}:${sessionId}:${sample.timestamp}`,
    deviceId,
    sessionId,
    capturedAt: sample.timestamp,
    layoutId: 'legacy-four-quadrant',
    calibrationState: 'ready',
    totalForceN: rounded(totalForceN),
    centerOfPressure: {
      x: totalForceN > 0 ? rounded(1 - left / totalForceN) : 0.5,
      y: totalForceN > 0 ? rounded(front / totalForceN) : 0.5,
    },
    quadrants: {
      frontLeftN: rounded(quadrants.frontLeftN),
      frontRightN: rounded(quadrants.frontRightN),
      rearLeftN: rounded(quadrants.rearLeftN),
      rearRightN: rounded(quadrants.rearRightN),
    },
    quality: sample.confidence,
    inference: {
      occupancy: sample.occupancy,
      posture: sample.posture ?? 'unknown',
      confidence: sample.confidence,
      modelVersion: 'legacy-four-quadrant-v1',
      reasons: ['convertedFromLegacyPressureSample'],
    },
  };
}

export function appendPostureFeature(
  segments: RealtimePostureSegment[],
  feature: PressureFeatureSummary,
): RealtimePostureSegment[] {
  if (feature.calibrationState !== 'ready') return segments;
  const posture =
    feature.inference.occupancy === 'away'
      ? 'away'
      : feature.inference.occupancy === 'occupied'
        ? feature.inference.posture
        : 'unknown';
  return appendPostureObservation(segments, {
    deviceId: feature.deviceId,
    sessionId: feature.sessionId,
    capturedAt: feature.capturedAt,
    posture,
    confidence: feature.inference.confidence,
    modelVersion: feature.inference.modelVersion,
  });
}

function appendPostureObservation(
  segments: RealtimePostureSegment[],
  observation: Omit<RealtimePostureSegment, 'id' | 'startAt' | 'endAt'> & {
    capturedAt: string;
  },
) {
  const previous = segments.at(-1);
  const canExtend =
    previous?.sessionId === observation.sessionId &&
    previous.posture === observation.posture &&
    Date.parse(observation.capturedAt) - Date.parse(previous.endAt) <= 10_000;
  if (canExtend) {
    return [
      ...segments.slice(0, -1),
      {
        ...previous,
        endAt: observation.capturedAt,
        confidence: rounded(
          (previous.confidence + observation.confidence) / 2,
        ),
      },
    ];
  }
  return [
    ...segments,
    {
      id: `${observation.deviceId}:${observation.sessionId}:${observation.capturedAt}`,
      deviceId: observation.deviceId,
      sessionId: observation.sessionId,
      startAt: observation.capturedAt,
      endAt: observation.capturedAt,
      posture: observation.posture,
      confidence: observation.confidence,
      modelVersion: observation.modelVersion,
    },
  ];
}

export function appendPostureEvent(
  segments: RealtimePostureSegment[],
  event: Extract<CushionRealtimeEvent, { type: 'posture' }>,
) {
  return appendPostureObservation(segments, {
    deviceId: event.deviceId,
    sessionId: event.sessionId,
    capturedAt: event.capturedAt,
    posture: event.payload.posture,
    confidence: event.quality ?? 1,
    modelVersion: 'device-fsr-posture-v1',
  });
}
