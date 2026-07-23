import {
  DayReport,
  HealthKitSyncState,
  HealthSyncBatch,
  ReportDateRange,
} from '@/domain/types';

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

export interface ManualRecordAdapter {
  isSupported(): boolean;
}

export interface HealthDataService {
  cushion: CushionDataAdapter;
  appleHealth: AppleHealthAdapter;
  manual: ManualRecordAdapter;
}
