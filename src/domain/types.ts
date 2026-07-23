export type SeatedPosture = 'upright' | 'legsCrossed';
export type OccupancyState = 'occupied' | 'away';
export type PostureState = SeatedPosture | 'away';
export type MetricTone = 'ok' | 'warn' | 'info' | 'cycle';

export interface UserSummary {
  id: string;
  displayName: string;
  recognitionConfidence?: number;
}

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
  uprightPercentage: number;
  standCount: number;
  legCrossMinutes: number;
  longestSitMinutes: number;
  postureTotals: PostureTotal[];
}

export interface ScoreBreakdownItem {
  label: string;
  detail: string;
  delta: number;
}

export interface ScoreSummary {
  value: number;
  status: string;
  isOK: boolean;
  mainDrag: string;
  breakdown: ScoreBreakdownItem[];
}

export interface HealthMetric {
  type:
    | 'restingHeartRate'
    | 'emotionReference'
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
  isEstimated?: boolean;
  sensitive?: boolean;
}

export interface WeightRecord {
  date: string;
  valueKg: number;
  source: string;
  isEstimated?: boolean;
}

export type EmotionBand = '放松' | '平静' | '紧张' | '压力偏高';

export interface HrvRecord {
  timestamp: string;
  valueMs: number;
  baselineMs: number;
  emotionDisplay: EmotionBand;
  source: string;
}

export interface MenstrualRecord {
  cycleStartDate: string;
  cycleDay: number;
  phase: '经期' | '卵泡期' | '排卵期' | '黄体期';
  flow: string;
  symptoms: string[];
  expectedPeriodEnd: string;
  predictedNextPeriodStart: string;
  source: string;
}

export interface DayReport {
  date: string;
  user: UserSummary;
  axisStart: number;
  axisEnd: number;
  firstSeatedAt: string;
  stats: DayStats;
  score: ScoreSummary;
  healthMetrics: HealthMetric[];
  segments: PostureSegment[];
  pressureSamples: PressureSample[];
  hrvRecords: HrvRecord[];
  weightRecords: WeightRecord[];
  menstrualRecord: MenstrualRecord;
  aiSummary: string;
  tags: string[];
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
  kind: 'selfReported' | 'estimated' | 'buildingBaseline' | 'unavailable';
  label: string;
  source: 'appleHealthStateOfMind' | 'appleHealthHrv' | 'cushionHrv' | 'none';
  measuredAt?: string;
  isEstimated: boolean;
}
