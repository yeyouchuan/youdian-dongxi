export type CushionRealtimeConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'reconnecting'
  | 'connected'
  | 'error';

export interface CushionRealtimeConnectionOptions {
  brokerUrl: string;
}

export type CushionRealtimeConnectionErrorCode =
  | 'INVALID_BROKER_URL'
  | 'CONNECT_TIMEOUT'
  | 'SUBSCRIBE_FAILED'
  | 'CONNECTION_FAILED';

export interface CushionRealtimeConnectionError {
  code: CushionRealtimeConnectionErrorCode;
}

export interface CushionRealtimeConnectionSnapshot {
  state: CushionRealtimeConnectionState;
  error?: CushionRealtimeConnectionError;
}

export type RadarDiagnosticsIssue =
  | 'INVALID_RADAR_SEQUENCE'
  | 'INVALID_RADAR_DISTANCE'
  | 'INVALID_RADAR_HEART_MEDIAN'
  | 'INVALID_RADAR_BREATH_MEDIAN';

export type RadarMessageKind = 'fresh' | 'keepalive' | 'invalid';

export interface RadarDiagnosticsSnapshot {
  seq?: number;
  distanceCm?: number;
  heartRaw?: number;
  breathRaw?: number;
  heartMedian?: number;
  breathMedian?: number;
  lastMessageAt?: string;
  lastFreshFrameAt?: string;
  keepaliveCount: number;
  lastMessageKind?: RadarMessageKind;
  issues: RadarDiagnosticsIssue[];
}

export type RadarFrameState = 'waiting' | 'live' | 'cached' | 'stale';

export interface RadarFrameStatus {
  state: RadarFrameState;
  lastMessageAt?: string;
  lastFreshFrameAt?: string;
}

export type CushionRealtimeStreamType =
  | 'heartRate'
  | 'respiratoryRate'
  | 'posture'
  | 'pressureFrame';

export interface CushionRealtimeCapabilities {
  heartRate: boolean;
  respiratoryRate: boolean;
  posture: boolean;
  pressure: boolean;
  pressureCalibrated: boolean;
}

export type CushionPosture =
  | 'away'
  | 'upright'
  | 'leanLeft'
  | 'leanRight'
  | 'forward'
  | 'recline'
  | 'edge'
  | 'other';

export type CushionPostureSensorId =
  | 'leftKnee'
  | 'leftMid'
  | 'leftIschial'
  | 'rightIschial'
  | 'rightMid'
  | 'rightKnee';

export interface CushionPostureSensorReading {
  sensorId: CushionPostureSensorId;
  rawAdc: number;
}

export interface CushionPressureBalance {
  leftPercentage: number;
  rightPercentage: number;
  ischialPercentage: number;
  legPercentage: number;
  capturedAt: string;
}

export interface RealtimeEventBase {
  schemaVersion: 1;
  deviceId: string;
  sessionId: string;
  streamSequence: number;
  capturedAt: string;
  quality?: number;
}

export interface PressureCell {
  sensorId: string;
  x: number;
  y: number;
  forceN: number;
  quality?: number;
}

export type CushionRealtimeEvent =
  | (RealtimeEventBase & {
      type: 'heartRate';
      payload: { bpm: number };
    })
  | (RealtimeEventBase & {
      type: 'respiratoryRate';
      payload: { breathsPerMinute: number };
    })
  | (RealtimeEventBase & {
      type: 'posture';
      payload: {
        posture: CushionPosture;
        layoutId: 'fsr6-v1';
        sensors: CushionPostureSensorReading[];
      };
    })
  | (RealtimeEventBase & {
      type: 'pressureFrame';
      payload: {
        layoutId: string;
        cells: PressureCell[];
      };
    });

export type RealtimeImportErrorCode =
  | 'INVALID_SCHEMA_VERSION'
  | 'INVALID_EVENT'
  | 'INVALID_TIMESTAMP'
  | 'INVALID_HEART_RATE'
  | 'INVALID_RESPIRATORY_RATE'
  | 'INVALID_POSTURE'
  | 'SENSOR_SATURATED'
  | 'INVALID_PRESSURE_FRAME'
  | 'INVALID_QUALITY'
  | 'DUPLICATE_EVENT'
  | 'OUT_OF_ORDER_EVENT';

export interface RealtimeImportError {
  code: RealtimeImportErrorCode;
  field?: string;
}

export interface RealtimeImportResult {
  accepted: number;
  duplicates: number;
  dropped: number;
  errors: RealtimeImportError[];
}

export interface RealtimeStreamStatus {
  type: CushionRealtimeStreamType;
  state: 'waiting' | 'live' | 'stale';
  lastCapturedAt?: string;
  quality?: number;
}

export interface PhysiologyWindowSummary {
  id: string;
  deviceId: string;
  sessionId: string;
  startAt: string;
  endAt: string;
  heartRateMedian: number | null;
  respiratoryRateMedian: number | null;
  heartRateCoverage: number;
  respiratoryRateCoverage: number;
  heartRateStable: boolean;
  heartRateQuality: number | null;
  respiratoryRateQuality: number | null;
}

export interface PressureCalibration {
  layoutId: string;
  emptyBaselineBySensor: Record<string, number>;
  occupantThresholdN: number;
  modelVersion: string;
}

export interface PressureQuadrants {
  frontLeftN: number;
  frontRightN: number;
  rearLeftN: number;
  rearRightN: number;
}

export interface PostureInference {
  occupancy: 'occupied' | 'away' | 'unknown';
  posture:
    | 'upright'
    | 'leanLeft'
    | 'leanRight'
    | 'forward'
    | 'recline'
    | 'edge'
    | 'other'
    | 'unknown';
  confidence: number;
  modelVersion: string;
  reasons: string[];
}

export interface PressureFeatureSummary {
  id: string;
  deviceId: string;
  sessionId: string;
  capturedAt: string;
  layoutId: string;
  calibrationState: 'ready' | 'calibrationRequired';
  totalForceN: number;
  centerOfPressure: { x: number; y: number };
  quadrants: PressureQuadrants;
  quality: number;
  inference: PostureInference;
}

export interface RealtimePostureSegment {
  id: string;
  deviceId: string;
  sessionId: string;
  startAt: string;
  endAt: string;
  posture:
    | 'upright'
    | 'leanLeft'
    | 'leanRight'
    | 'forward'
    | 'recline'
    | 'edge'
    | 'other'
    | 'away'
    | 'unknown';
  confidence: number;
  modelVersion: string;
}

export type RecoveryState =
  | 'recoveryGood'
  | 'steady'
  | 'elevatedLoad'
  | 'insufficient';

export type RecoveryConfidence = 'high' | 'medium' | 'low';

export interface HrvBaseline {
  sourceBundleId: string;
  startDate: string;
  endDate: string;
  valueMs: number;
  sampleCount: number;
  dayCount: number;
}

export interface VitalBaseline {
  heartRateMedian: number | null;
  respiratoryRateMedian: number | null;
  sessionCount: number;
}

export interface RecoveryAssessment {
  id: string;
  state: RecoveryState;
  confidence: RecoveryConfidence;
  label: string;
  measuredAt?: string;
  hrvSampleUuid?: string;
  hrvSdnnMs?: number;
  hrvBaselineMs?: number;
  hrvRatio?: number;
  physiologyWindowId?: string;
  reasons: string[];
  createdAt: string;
}
