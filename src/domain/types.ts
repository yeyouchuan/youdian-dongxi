export type SeatedPosture =
  | 'upright'
  | 'leanLeft'
  | 'leanRight'
  | 'forward'
  | 'recline'
  | 'edge'
  | 'other';
export type OccupancyState = 'occupied' | 'away';
export type PostureState = SeatedPosture | 'away';
export type MetricTone = 'ok' | 'warn' | 'info' | 'cycle';

export interface PostureSegment {
  startMinute: number;
  endMinute: number;
  posture: PostureState;
  source: 'cushion';
  confidence?: number;
  note?: string;
}

export interface PostureTotal {
  posture: PostureState;
  minutes: number;
  percentage: number;
}

export interface PressureSample {
  timestamp: string;
  frontLeftKg: number;
  frontRightKg: number;
  rearLeftKg: number;
  rearRightKg: number;
  totalKg: number;
  occupancy: OccupancyState;
  posture: SeatedPosture | null;
  confidence: number;
}

export interface DayStats {
  seatedMinutes: number;
  seatedText: string;
  observedMinutes: number;
  uprightPercentage: number;
  standCount: number;
  validBreakCount: number;
  breakTarget: number;
  nonUprightMinutes: number;
  longestSitMinutes: number;
  longestNonUprightMinutes: number;
  dominantNonUprightPosture: SeatedPosture | null;
  postureTotals: PostureTotal[];
}

export interface ScoreBreakdownItem {
  label: string;
  detail: string;
  points: number;
  maxPoints: number;
}

export type ScoreConfidence = 'insufficient' | 'preliminary' | 'stable';

export interface ScoreSummary {
  value: number | null;
  status: string;
  isOK: boolean;
  confidence: ScoreConfidence;
  mainDrag: string;
  breakdown: ScoreBreakdownItem[];
}

export interface HealthMetric {
  type:
    | 'restingHeartRate'
    | 'hrv'
    | 'stateOfMind'
    | 'respiratoryRate'
    | 'bodyMass'
    | 'menstrualCycle';
  label: string;
  value: string;
  unit?: string;
  caption: string;
  tone: MetricTone;
  source: string;
  measuredAt?: string;
  sensitive?: boolean;
}

export interface DayReport {
  date: string;
  axisStart: number;
  axisEnd: number;
  firstSeatedAt: string;
  stats: DayStats;
  score: ScoreSummary;
  segments: PostureSegment[];
  aiSummary: string;
  tags: string[];
}

export type HealthStickerKind =
  | 'balancedDay'
  | 'uprightStable'
  | 'breakTargetMet';

export interface HealthStickerMetric {
  label: string;
  value: string;
}

export interface HealthStickerPresentation {
  id: string;
  date: string;
  kind: HealthStickerKind;
  title: string;
  reason: string;
  advice: string;
  metrics: HealthStickerMetric[];
  scopeNote?: string;
}

export type TrendRangeDays = 7 | 30;

export interface ReportDateRange {
  startDate: string;
  endDate: string;
}

export interface ReportTrendPoint {
  date: string;
  hasData: boolean;
  score: number | null;
  confidence: ScoreConfidence | null;
  uprightPercentage: number | null;
  longestSitMinutes: number | null;
  standCount: number | null;
}

export interface ReportTrendComparison {
  previousAverageScore: number | null;
  scoreDelta: number | null;
}

export interface ReportTrendSummary {
  rangeDays: TrendRangeDays;
  startDate: string;
  endDate: string;
  points: ReportTrendPoint[];
  dataDays: number;
  stableDays: number;
  preliminaryDays: number;
  averageScore: number | null;
  averageUprightPercentage: number | null;
  averageLongestSitMinutes: number | null;
  averageStandCount: number | null;
  comparison: ReportTrendComparison;
}

export interface HealthKitSample {
  uuid: string;
  typeIdentifier: string;
  startDate: string;
  endDate: string;
  value?: number | string;
  unit?: string;
  sourceName: string;
  sourceBundleId: string;
  sourceVersion?: string;
  deviceName?: string;
  metadata?: Record<string, unknown>;
  importedAt: string;
}

export type HealthSyncStatus = 'idle' | 'syncing' | 'success' | 'error';

export interface HealthKitSyncState {
  typeIdentifier: string;
  anchor?: string;
  lastSyncAt?: string;
  earliestAuthorizedDate?: string;
  status: HealthSyncStatus;
  errorCode?: string;
}

export interface HealthSyncBatch {
  typeIdentifier: string;
  samples: HealthKitSample[];
  deletedUuids: string[];
  newAnchor: string;
  earliestAuthorizedDate?: string;
}

export interface EmotionPresentation {
  kind: 'selfReported' | 'unavailable';
  label: string;
  source: 'appleHealthStateOfMind' | 'none';
  measuredAt?: string;
}
