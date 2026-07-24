import {
  DayReport,
  HealthKitSyncState,
  HealthSyncBatch,
  ReportDateRange,
} from '@/domain/types';
import {
  CushionRealtimeCapabilities,
  CushionRealtimeConnectionOptions,
  CushionRealtimeConnectionSnapshot,
  CushionRealtimeConnectionState,
  CushionRealtimeEvent,
  PressureCalibration,
  RadarDiagnosticsSnapshot,
  RealtimeImportResult,
} from '@/domain/realtime-types';

export interface CushionDataAdapter {
  getReport(date: string): Promise<DayReport | null>;
  getReports(range: ReportDateRange): Promise<DayReport[]>;
}

export interface AppleHealthAdapter {
  isAvailable(): Promise<boolean>;
  requestCoreReadAccess(): Promise<boolean>;
  requestSensitiveReadAccess(type: 'menstrual' | 'stateOfMind'): Promise<boolean>;
  syncType(typeIdentifier: string, previous?: HealthKitSyncState): Promise<HealthSyncBatch>;
}

export interface CushionRealtimeAdapter {
  connect(options: CushionRealtimeConnectionOptions): Promise<void>;
  disconnect(): Promise<void>;
  getConnectionState(): CushionRealtimeConnectionState;
  getConnectionSnapshot(): CushionRealtimeConnectionSnapshot;
  getCapabilities(): CushionRealtimeCapabilities;
  getRadarDiagnostics(): RadarDiagnosticsSnapshot;
  getPressureCalibration(): PressureCalibration | undefined;
  setPressureCalibration(calibration: PressureCalibration | null): void;
  subscribe(listener: (event: CushionRealtimeEvent) => void): () => void;
  subscribeConnection(
    listener: (snapshot: CushionRealtimeConnectionSnapshot) => void,
  ): () => void;
  subscribeRadarDiagnostics(
    listener: (snapshot: RadarDiagnosticsSnapshot) => void,
  ): () => void;
  subscribeImportResults(
    listener: (result: RealtimeImportResult) => void,
  ): () => void;
  ingest(event: unknown): RealtimeImportResult;
  ingestBatch(events: unknown[]): RealtimeImportResult;
}

export interface ManualRecordAdapter {
  isSupported(): boolean;
}

export interface HealthDataService {
  cushion: CushionDataAdapter;
  cushionRealtime: CushionRealtimeAdapter;
  appleHealth: AppleHealthAdapter;
  manual: ManualRecordAdapter;
}
