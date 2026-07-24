import { Platform } from 'react-native';
import type { SQLiteDatabase } from 'expo-sqlite';

import {
  openDatabaseWithRecovery,
  withKeyedTransaction,
} from '@/data/database-recovery';
import {
  PhysiologyWindowSummary,
  PressureFeatureSummary,
  RealtimePostureSegment,
  RecoveryAssessment,
} from '@/domain/realtime-types';
import { HealthKitSample, HealthKitSyncState, HealthSyncBatch } from '@/domain/types';
import { buildCommittedSyncSnapshot } from '@/data/sync-merge';

const DATABASE_NAME = 'youdian-health.db';
const DATABASE_KEY_NAME = 'youdian.database-key.v1';
const DATABASE_SCHEMA = `
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS health_samples (
    uuid TEXT PRIMARY KEY NOT NULL,
    type_identifier TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    value_number REAL,
    value_text TEXT,
    unit TEXT,
    source_name TEXT NOT NULL,
    source_bundle_id TEXT NOT NULL,
    source_version TEXT,
    device_name TEXT,
    metadata_json TEXT,
    imported_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS health_samples_type_date
    ON health_samples(type_identifier, start_date);
  CREATE TABLE IF NOT EXISTS health_sync_state (
    type_identifier TEXT PRIMARY KEY NOT NULL,
    anchor TEXT,
    last_sync_at TEXT,
    earliest_authorized_date TEXT,
    status TEXT NOT NULL,
    error_code TEXT
  );
  CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS physiology_windows (
    id TEXT PRIMARY KEY NOT NULL,
    device_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    heart_rate_median REAL,
    respiratory_rate_median REAL,
    heart_rate_coverage REAL NOT NULL,
    respiratory_rate_coverage REAL NOT NULL,
    heart_rate_stable INTEGER NOT NULL,
    heart_rate_quality REAL,
    respiratory_rate_quality REAL
  );
  CREATE INDEX IF NOT EXISTS physiology_windows_end_at
    ON physiology_windows(end_at);
  CREATE TABLE IF NOT EXISTS recovery_assessments (
    id TEXT PRIMARY KEY NOT NULL,
    state TEXT NOT NULL,
    measured_at TEXT,
    created_at TEXT NOT NULL,
    assessment_json TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS recovery_assessments_created_at
    ON recovery_assessments(created_at);
  CREATE TABLE IF NOT EXISTS pressure_features (
    id TEXT PRIMARY KEY NOT NULL,
    captured_at TEXT NOT NULL,
    feature_json TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS pressure_features_captured_at
    ON pressure_features(captured_at);
  CREATE TABLE IF NOT EXISTS realtime_posture_segments (
    id TEXT PRIMARY KEY NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    segment_json TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS realtime_posture_segments_end_at
    ON realtime_posture_segments(end_at);
`;

interface HealthSampleRow {
  uuid: string;
  type_identifier: string;
  start_date: string;
  end_date: string;
  value_number: number | null;
  value_text: string | null;
  unit: string | null;
  source_name: string;
  source_bundle_id: string;
  source_version: string | null;
  device_name: string | null;
  metadata_json: string | null;
  imported_at: string;
}

export function normalizeRealtimePostureSegment(
  segment: RealtimePostureSegment | (Omit<RealtimePostureSegment, 'posture'> & {
    posture: string;
  }),
): RealtimePostureSegment {
  return {
    ...segment,
    posture: segment.posture === 'legsCrossed' ? 'other' : segment.posture,
  } as RealtimePostureSegment;
}

interface SyncStateRow {
  type_identifier: string;
  anchor: string | null;
  last_sync_at: string | null;
  earliest_authorized_date: string | null;
  status: HealthKitSyncState['status'];
  error_code: string | null;
}

let databasePromise: Promise<SQLiteDatabase> | null = null;
let webSamples: HealthKitSample[] = [];
let webPhysiologyWindows: PhysiologyWindowSummary[] = [];
let webRecoveryAssessments: RecoveryAssessment[] = [];
let webPressureFeatures: PressureFeatureSummary[] = [];
let webRealtimePostureSegments: RealtimePostureSegment[] = [];
const webSyncStates = new Map<string, HealthKitSyncState>();
const webSettings = new Map<string, string>();

async function getOrCreateDatabaseKey() {
  const SecureStore = await import('expo-secure-store');
  let key = await SecureStore.getItemAsync(DATABASE_KEY_NAME);
  if (!key) {
    const Crypto = await import('expo-crypto');
    key = `${Crypto.randomUUID()}${Crypto.randomUUID()}`.replaceAll('-', '');
    await SecureStore.setItemAsync(DATABASE_KEY_NAME, key, {
      keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
    });
  }
  return key;
}

async function configureEncryptedDatabase(
  database: SQLiteDatabase,
  key: string,
) {
  await database.execAsync(`PRAGMA key = '${key}';`);
  const cipher = await database.getFirstAsync<{ cipher_version: string }>(
    'PRAGMA cipher_version;',
  );
  if (!cipher?.cipher_version) {
    throw new Error(
      'SQLCipher is unavailable in this development build. Rebuild the native client.',
    );
  }

  // This is the first statement that reads the encrypted file and therefore
  // validates both its format and the current SecureStore key.
  await database.getFirstAsync(
    'SELECT count(*) AS tableCount FROM sqlite_master;',
  );
  await database.execAsync(DATABASE_SCHEMA);
}

function isDatabaseNotFoundError(error: unknown) {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : '';
  return message.toLowerCase().includes('not found');
}

async function deleteOptionalDatabaseFile(
  SQLite: typeof import('expo-sqlite'),
  databaseName: string,
) {
  try {
    await SQLite.deleteDatabaseAsync(databaseName);
  } catch (error) {
    if (!isDatabaseNotFoundError(error)) throw error;
  }
}

async function openNativeDatabase() {
  if (!databasePromise) {
    const opening = (async () => {
      const SQLite = await import('expo-sqlite');
      const key = await getOrCreateDatabaseKey();
      const result = await openDatabaseWithRecovery({
        open: () => SQLite.openDatabaseAsync(DATABASE_NAME),
        configure: (database) =>
          configureEncryptedDatabase(database, key),
        deleteDatabaseFiles: async () => {
          await deleteOptionalDatabaseFile(SQLite, `${DATABASE_NAME}-wal`);
          await deleteOptionalDatabaseFile(SQLite, `${DATABASE_NAME}-shm`);
          await SQLite.deleteDatabaseAsync(DATABASE_NAME);
        },
      });
      if (result.recovered) {
        console.warn(
          '[health-store] Rebuilt an unreadable local HealthKit mirror. Apple Health source data was not changed.',
        );
      }
      return result.database;
    })();
    databasePromise = opening.catch((error) => {
      databasePromise = null;
      throw error;
    });
  }
  return databasePromise;
}

function rowToSample(row: HealthSampleRow): HealthKitSample {
  return {
    uuid: row.uuid,
    typeIdentifier: row.type_identifier,
    startDate: row.start_date,
    endDate: row.end_date,
    value: row.value_number ?? row.value_text ?? undefined,
    unit: row.unit ?? undefined,
    sourceName: row.source_name,
    sourceBundleId: row.source_bundle_id,
    sourceVersion: row.source_version ?? undefined,
    deviceName: row.device_name ?? undefined,
    metadata: row.metadata_json ? JSON.parse(row.metadata_json) : undefined,
    importedAt: row.imported_at,
  };
}

function rowToSyncState(row: SyncStateRow): HealthKitSyncState {
  return {
    typeIdentifier: row.type_identifier,
    anchor: row.anchor ?? undefined,
    lastSyncAt: row.last_sync_at ?? undefined,
    earliestAuthorizedDate: row.earliest_authorized_date ?? undefined,
    status: row.status,
    errorCode: row.error_code ?? undefined,
  };
}

function sampleBindings(sample: HealthKitSample) {
  return [
    sample.uuid,
    sample.typeIdentifier,
    sample.startDate,
    sample.endDate,
    typeof sample.value === 'number' ? sample.value : null,
    typeof sample.value === 'string' ? sample.value : null,
    sample.unit ?? null,
    sample.sourceName,
    sample.sourceBundleId,
    sample.sourceVersion ?? null,
    sample.deviceName ?? null,
    sample.metadata ? JSON.stringify(sample.metadata) : null,
    sample.importedAt,
  ] as const;
}

function physiologyWindowBindings(window: PhysiologyWindowSummary) {
  return [
    window.id,
    window.deviceId,
    window.sessionId,
    window.startAt,
    window.endAt,
    window.heartRateMedian,
    window.respiratoryRateMedian,
    window.heartRateCoverage,
    window.respiratoryRateCoverage,
    window.heartRateStable ? 1 : 0,
    window.heartRateQuality,
    window.respiratoryRateQuality,
  ] as const;
}

function rowToPhysiologyWindow(
  row: Record<string, string | number | null>,
): PhysiologyWindowSummary {
  return {
    id: row.id as string,
    deviceId: row.device_id as string,
    sessionId: row.session_id as string,
    startAt: row.start_at as string,
    endAt: row.end_at as string,
    heartRateMedian: row.heart_rate_median as number | null,
    respiratoryRateMedian: row.respiratory_rate_median as number | null,
    heartRateCoverage: row.heart_rate_coverage as number,
    respiratoryRateCoverage: row.respiratory_rate_coverage as number,
    heartRateStable: row.heart_rate_stable === 1,
    heartRateQuality: row.heart_rate_quality as number | null,
    respiratoryRateQuality: row.respiratory_rate_quality as number | null,
  };
}

async function pruneRealtimeData(database: SQLiteDatabase, now = new Date()) {
  const windowsCutoff = new Date(
    now.getTime() - 30 * 24 * 60 * 60 * 1000,
  ).toISOString();
  const postureCutoff = new Date(
    now.getTime() - 90 * 24 * 60 * 60 * 1000,
  ).toISOString();
  const assessmentsCutoff = new Date(
    now.getTime() - 90 * 24 * 60 * 60 * 1000,
  ).toISOString();
  await database.runAsync(
    'DELETE FROM physiology_windows WHERE end_at < ?',
    windowsCutoff,
  );
  await database.runAsync(
    'DELETE FROM pressure_features WHERE captured_at < ?',
    windowsCutoff,
  );
  await database.runAsync(
    'DELETE FROM realtime_posture_segments WHERE end_at < ?',
    postureCutoff,
  );
  await database.runAsync(
    'DELETE FROM recovery_assessments WHERE created_at < ?',
    assessmentsCutoff,
  );
}

export const healthSampleRepository = {
  async initialize() {
    if (Platform.OS !== 'web') await openNativeDatabase();
  },

  async getSamples(): Promise<HealthKitSample[]> {
    if (Platform.OS === 'web') return [...webSamples];
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<HealthSampleRow>(
      'SELECT * FROM health_samples ORDER BY start_date DESC',
    );
    return rows.map(rowToSample);
  },

  async getSyncStates(): Promise<HealthKitSyncState[]> {
    if (Platform.OS === 'web') return [...webSyncStates.values()];
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<SyncStateRow>(
      'SELECT * FROM health_sync_state ORDER BY type_identifier',
    );
    return rows.map(rowToSyncState);
  },

  async applySyncBatch(batch: HealthSyncBatch): Promise<HealthKitSyncState> {
    const completedAt = new Date().toISOString();
    const nextState = buildCommittedSyncSnapshot([], batch, completedAt).state;

    if (Platform.OS === 'web') {
      const committed = buildCommittedSyncSnapshot(webSamples, batch, completedAt);
      webSamples = committed.samples;
      webSyncStates.set(batch.typeIdentifier, committed.state);
      return committed.state;
    }

    const database = await openNativeDatabase();
    await withKeyedTransaction(database, async (transaction) => {
      for (const uuid of batch.deletedUuids) {
        await transaction.runAsync('DELETE FROM health_samples WHERE uuid = ?', uuid);
      }
      for (const sample of batch.samples) {
        await transaction.runAsync(
          `INSERT INTO health_samples (
            uuid, type_identifier, start_date, end_date, value_number, value_text,
            unit, source_name, source_bundle_id, source_version, device_name,
            metadata_json, imported_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(uuid) DO UPDATE SET
            type_identifier = excluded.type_identifier,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            value_number = excluded.value_number,
            value_text = excluded.value_text,
            unit = excluded.unit,
            source_name = excluded.source_name,
            source_bundle_id = excluded.source_bundle_id,
            source_version = excluded.source_version,
            device_name = excluded.device_name,
            metadata_json = excluded.metadata_json,
            imported_at = excluded.imported_at`,
          ...sampleBindings(sample),
        );
      }
      await transaction.runAsync(
        `INSERT INTO health_sync_state (
          type_identifier, anchor, last_sync_at, earliest_authorized_date, status, error_code
        ) VALUES (?, ?, ?, ?, ?, NULL)
        ON CONFLICT(type_identifier) DO UPDATE SET
          anchor = excluded.anchor,
          last_sync_at = excluded.last_sync_at,
          earliest_authorized_date = excluded.earliest_authorized_date,
          status = excluded.status,
          error_code = NULL`,
        nextState.typeIdentifier,
        nextState.anchor ?? null,
        nextState.lastSyncAt ?? null,
        nextState.earliestAuthorizedDate ?? null,
        nextState.status,
      );
    });
    return nextState;
  },

  async recordSyncError(typeIdentifier: string, errorCode: string) {
    const nextState: HealthKitSyncState = { typeIdentifier, status: 'error', errorCode };
    if (Platform.OS === 'web') {
      webSyncStates.set(typeIdentifier, {
        ...webSyncStates.get(typeIdentifier),
        ...nextState,
      });
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO health_sync_state (type_identifier, status, error_code)
       VALUES (?, 'error', ?)
       ON CONFLICT(type_identifier) DO UPDATE SET status = 'error', error_code = excluded.error_code`,
      typeIdentifier,
      errorCode,
    );
  },

  async clearHealthCache() {
    if (Platform.OS === 'web') {
      webSamples = [];
      webPhysiologyWindows = [];
      webRecoveryAssessments = [];
      webPressureFeatures = [];
      webRealtimePostureSegments = [];
      webSyncStates.clear();
      return;
    }
    const database = await openNativeDatabase();
    await withKeyedTransaction(database, async (transaction) => {
      await transaction.execAsync(`
        DELETE FROM health_samples;
        DELETE FROM health_sync_state;
        DELETE FROM physiology_windows;
        DELETE FROM recovery_assessments;
        DELETE FROM pressure_features;
        DELETE FROM realtime_posture_segments;
      `);
    });
  },

  async savePhysiologyWindow(window: PhysiologyWindowSummary) {
    if (Platform.OS === 'web') {
      webPhysiologyWindows = [
        window,
        ...webPhysiologyWindows.filter((item) => item.id !== window.id),
      ].filter(
        (item) =>
          Date.parse(item.endAt) >= Date.now() - 30 * 24 * 60 * 60 * 1000,
      );
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO physiology_windows (
        id, device_id, session_id, start_at, end_at, heart_rate_median,
        respiratory_rate_median, heart_rate_coverage,
        respiratory_rate_coverage, heart_rate_stable, heart_rate_quality,
        respiratory_rate_quality
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        end_at = excluded.end_at,
        heart_rate_median = excluded.heart_rate_median,
        respiratory_rate_median = excluded.respiratory_rate_median,
        heart_rate_coverage = excluded.heart_rate_coverage,
        respiratory_rate_coverage = excluded.respiratory_rate_coverage,
        heart_rate_stable = excluded.heart_rate_stable,
        heart_rate_quality = excluded.heart_rate_quality,
        respiratory_rate_quality = excluded.respiratory_rate_quality`,
      ...physiologyWindowBindings(window),
    );
    await pruneRealtimeData(database);
  },

  async getPhysiologyWindows(): Promise<PhysiologyWindowSummary[]> {
    if (Platform.OS === 'web') {
      return [...webPhysiologyWindows].sort((a, b) =>
        b.endAt.localeCompare(a.endAt),
      );
    }
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<
      Record<string, string | number | null>
    >('SELECT * FROM physiology_windows ORDER BY end_at DESC');
    return rows.map(rowToPhysiologyWindow);
  },

  async saveRecoveryAssessment(assessment: RecoveryAssessment) {
    if (Platform.OS === 'web') {
      webRecoveryAssessments = [
        assessment,
        ...webRecoveryAssessments.filter(
          (item) => item.id !== assessment.id,
        ),
      ].filter(
        (item) =>
          Date.parse(item.createdAt) >=
          Date.now() - 90 * 24 * 60 * 60 * 1000,
      );
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO recovery_assessments (
        id, state, measured_at, created_at, assessment_json
      ) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        state = excluded.state,
        measured_at = excluded.measured_at,
        created_at = excluded.created_at,
        assessment_json = excluded.assessment_json`,
      assessment.id,
      assessment.state,
      assessment.measuredAt ?? null,
      assessment.createdAt,
      JSON.stringify(assessment),
    );
    await pruneRealtimeData(database);
  },

  async getRecoveryAssessments(): Promise<RecoveryAssessment[]> {
    if (Platform.OS === 'web') {
      return [...webRecoveryAssessments].sort((a, b) =>
        b.createdAt.localeCompare(a.createdAt),
      );
    }
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<{ assessment_json: string }>(
      'SELECT assessment_json FROM recovery_assessments ORDER BY created_at DESC',
    );
    return rows.map(
      (row) => JSON.parse(row.assessment_json) as RecoveryAssessment,
    );
  },

  async savePressureFeature(feature: PressureFeatureSummary) {
    if (Platform.OS === 'web') {
      webPressureFeatures = [
        feature,
        ...webPressureFeatures.filter((item) => item.id !== feature.id),
      ].filter(
        (item) =>
          Date.parse(item.capturedAt) >=
          Date.now() - 30 * 24 * 60 * 60 * 1000,
      );
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO pressure_features (
        id, captured_at, feature_json
      ) VALUES (?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        captured_at = excluded.captured_at,
        feature_json = excluded.feature_json`,
      feature.id,
      feature.capturedAt,
      JSON.stringify(feature),
    );
    await pruneRealtimeData(database);
  },

  async getPressureFeatures(): Promise<PressureFeatureSummary[]> {
    if (Platform.OS === 'web') {
      return [...webPressureFeatures].sort((a, b) =>
        b.capturedAt.localeCompare(a.capturedAt),
      );
    }
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<{ feature_json: string }>(
      'SELECT feature_json FROM pressure_features ORDER BY captured_at DESC',
    );
    return rows.map(
      (row) => JSON.parse(row.feature_json) as PressureFeatureSummary,
    );
  },

  async saveRealtimePostureSegment(segment: RealtimePostureSegment) {
    if (Platform.OS === 'web') {
      webRealtimePostureSegments = [
        segment,
        ...webRealtimePostureSegments.filter(
          (item) => item.id !== segment.id,
        ),
      ].filter(
        (item) =>
          Date.parse(item.endAt) >=
          Date.now() - 90 * 24 * 60 * 60 * 1000,
      );
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO realtime_posture_segments (
        id, start_at, end_at, segment_json
      ) VALUES (?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        end_at = excluded.end_at,
        segment_json = excluded.segment_json`,
      segment.id,
      segment.startAt,
      segment.endAt,
      JSON.stringify(segment),
    );
    await pruneRealtimeData(database);
  },

  async getRealtimePostureSegments(): Promise<RealtimePostureSegment[]> {
    if (Platform.OS === 'web') {
      return [...webRealtimePostureSegments]
        .map(normalizeRealtimePostureSegment)
        .sort((a, b) => b.endAt.localeCompare(a.endAt));
    }
    const database = await openNativeDatabase();
    const rows = await database.getAllAsync<{ segment_json: string }>(
      'SELECT segment_json FROM realtime_posture_segments ORDER BY end_at DESC',
    );
    return rows.map((row) =>
      normalizeRealtimePostureSegment(
        JSON.parse(row.segment_json) as RealtimePostureSegment,
      ),
    );
  },

  async getSetting(key: string) {
    if (Platform.OS === 'web') return webSettings.get(key) ?? null;
    const database = await openNativeDatabase();
    const row = await database.getFirstAsync<{ value: string }>(
      'SELECT value FROM app_settings WHERE key = ?',
      key,
    );
    return row?.value ?? null;
  },

  async setSetting(key: string, value: string) {
    if (Platform.OS === 'web') {
      webSettings.set(key, value);
      return;
    }
    const database = await openNativeDatabase();
    await database.runAsync(
      `INSERT INTO app_settings (key, value) VALUES (?, ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
      key,
      value,
    );
  },
};
