import { Platform } from 'react-native';
import type { SQLiteDatabase } from 'expo-sqlite';

import {
  openDatabaseWithRecovery,
  withKeyedTransaction,
} from '@/data/database-recovery';
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
      webSyncStates.clear();
      return;
    }
    const database = await openNativeDatabase();
    await withKeyedTransaction(database, async (transaction) => {
      await transaction.execAsync('DELETE FROM health_samples; DELETE FROM health_sync_state;');
    });
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
