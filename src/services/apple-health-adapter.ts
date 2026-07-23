import { Platform } from 'react-native';

import {
  HealthKitSample,
  HealthKitSyncState,
  HealthSyncBatch,
} from '@/domain/types';
import { AppleHealthAdapter } from '@/services/health-data-adapters';

export const HEALTH_TYPES = {
  restingHeartRate: 'HKQuantityTypeIdentifierRestingHeartRate',
  hrv: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
  respiratoryRate: 'HKQuantityTypeIdentifierRespiratoryRate',
  bodyMass: 'HKQuantityTypeIdentifierBodyMass',
  menstrualFlow: 'HKCategoryTypeIdentifierMenstrualFlow',
  stateOfMind: 'HKStateOfMindTypeIdentifier',
} as const;

export type HealthTypeIdentifier = (typeof HEALTH_TYPES)[keyof typeof HEALTH_TYPES];

export const CORE_HEALTH_TYPES: HealthTypeIdentifier[] = [
  HEALTH_TYPES.restingHeartRate,
  HEALTH_TYPES.hrv,
  HEALTH_TYPES.respiratoryRate,
  HEALTH_TYPES.bodyMass,
];

const QUANTITY_UNITS: Partial<Record<HealthTypeIdentifier, string>> = {
  [HEALTH_TYPES.restingHeartRate]: 'count/min',
  [HEALTH_TYPES.hrv]: 'ms',
  [HEALTH_TYPES.respiratoryRate]: 'count/min',
  [HEALTH_TYPES.bodyMass]: 'kg',
};

interface RawHealthSample {
  uuid: string;
  startDate: Date;
  endDate: Date;
  quantity?: number;
  unit?: string;
  value?: number;
  labels?: readonly number[];
  associations?: readonly number[];
  valence?: number;
  valenceClassification?: number;
  kind?: number;
  metadata?: Record<string, unknown>;
  sourceRevision: {
    source: { name: string; bundleIdentifier: string };
    version?: string;
  };
  device?: { name?: string };
}

interface RawSyncResponse {
  samples: readonly RawHealthSample[];
  deletedSamples: readonly { uuid: string }[];
  newAnchor: string;
}

interface HealthQueryOptions {
  limit: number;
  anchor?: string;
  filter?: {
    date: {
      startDate: Date;
      endDate: Date;
    };
  };
}

export interface HealthQueryPlan {
  options: HealthQueryOptions;
  earliestAuthorizedDate: string;
  usesAnchor: boolean;
}

export function buildHealthQueryPlan(
  previous?: HealthKitSyncState,
  now = new Date(),
): HealthQueryPlan {
  if (previous?.anchor && previous.status !== 'error') {
    return {
      options: {
        limit: 0,
        anchor: previous.anchor,
      },
      earliestAuthorizedDate:
        previous.earliestAuthorizedDate ?? now.toISOString(),
      usesAnchor: true,
    };
  }

  const initialStart = new Date(now);
  initialStart.setDate(initialStart.getDate() - 90);
  return {
    options: {
      limit: 0,
      filter: {
        date: {
          startDate: initialStart,
          endDate: now,
        },
      },
    },
    earliestAuthorizedDate: initialStart.toISOString(),
    usesAnchor: false,
  };
}

export type HealthSyncErrorCode =
  | 'AUTHORIZATION_REQUIRED'
  | 'ANCHOR_INVALID'
  | 'HEALTH_DATA_UNAVAILABLE'
  | 'UNIT_INCOMPATIBLE'
  | 'LOCAL_STORE_FAILED'
  | 'NATIVE_QUERY_FAILED';

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return typeof error === 'string' ? error : '';
}

export function classifyHealthSyncError(
  error: unknown,
): HealthSyncErrorCode {
  const message = errorMessage(error).toLowerCase();
  if (
    message.includes('authorization') ||
    message.includes('permission') ||
    message.includes('not authorized')
  ) {
    return 'AUTHORIZATION_REQUIRED';
  }
  if (message.includes('anchor')) return 'ANCHOR_INVALID';
  if (
    message.includes('health data is unavailable') ||
    message.includes('not available')
  ) {
    return 'HEALTH_DATA_UNAVAILABLE';
  }
  if (message.includes('unit') || message.includes('incompatible')) {
    return 'UNIT_INCOMPATIBLE';
  }
  if (
    message.includes('sqlite') ||
    message.includes('sqlcipher') ||
    message.includes('database') ||
    message.includes('constraint')
  ) {
    return 'LOCAL_STORE_FAILED';
  }
  return 'NATIVE_QUERY_FAILED';
}

export function summarizeHealthSyncError(error: unknown) {
  const message = errorMessage(error).replace(/\s+/g, ' ').trim();
  return message ? message.slice(0, 180) : 'No native error message';
}

function normalizeSample(
  sample: RawHealthSample,
  typeIdentifier: HealthTypeIdentifier,
): HealthKitSample {
  let value: number | string | undefined = sample.quantity ?? sample.value;
  if (typeIdentifier === HEALTH_TYPES.stateOfMind) {
    value = JSON.stringify({
      valence: sample.valence,
      valenceClassification: sample.valenceClassification,
      kind: sample.kind,
      labels: sample.labels ?? [],
      associations: sample.associations ?? [],
    });
  }
  return {
    uuid: sample.uuid,
    typeIdentifier,
    startDate: sample.startDate.toISOString(),
    endDate: sample.endDate.toISOString(),
    value,
    unit: sample.unit ?? QUANTITY_UNITS[typeIdentifier],
    sourceName: sample.sourceRevision.source.name,
    sourceBundleId: sample.sourceRevision.source.bundleIdentifier,
    sourceVersion: sample.sourceRevision.version,
    deviceName: sample.device?.name,
    metadata: sample.metadata,
    importedAt: new Date().toISOString(),
  };
}

async function loadHealthKit() {
  return import('@kingstinct/react-native-healthkit');
}

async function queryHealthType(
  HealthKit: Awaited<ReturnType<typeof loadHealthKit>>,
  typeIdentifier: HealthTypeIdentifier,
  options: HealthQueryOptions,
) {
  if (typeIdentifier === HEALTH_TYPES.menstrualFlow) {
    return (await HealthKit.queryCategorySamplesWithAnchor(
      HEALTH_TYPES.menstrualFlow,
      options,
    )) as unknown as RawSyncResponse;
  }
  if (typeIdentifier === HEALTH_TYPES.stateOfMind) {
    return (await HealthKit.queryStateOfMindSamplesWithAnchor(
      options,
    )) as unknown as RawSyncResponse;
  }

  const unit = QUANTITY_UNITS[typeIdentifier];
  return (await HealthKit.queryQuantitySamplesWithAnchor(
    typeIdentifier as
      | typeof HEALTH_TYPES.restingHeartRate
      | typeof HEALTH_TYPES.hrv
      | typeof HEALTH_TYPES.respiratoryRate
      | typeof HEALTH_TYPES.bodyMass,
    { ...options, unit },
  )) as unknown as RawSyncResponse;
}

export const appleHealthAdapter: AppleHealthAdapter = {
  async isAvailable() {
    if (Platform.OS !== 'ios') return false;
    const HealthKit = await loadHealthKit();
    return HealthKit.isHealthDataAvailable();
  },

  async requestCoreReadAccess() {
    if (Platform.OS !== 'ios') return false;
    const HealthKit = await loadHealthKit();
    return HealthKit.requestAuthorization({ toRead: CORE_HEALTH_TYPES });
  },

  async requestSensitiveReadAccess(type) {
    if (Platform.OS !== 'ios') return false;
    const HealthKit = await loadHealthKit();
    const identifier =
      type === 'menstrual' ? HEALTH_TYPES.menstrualFlow : HEALTH_TYPES.stateOfMind;
    return HealthKit.requestAuthorization({ toRead: [identifier] });
  },

  async syncType(typeIdentifier, previous) {
    if (Platform.OS !== 'ios') {
      return {
        typeIdentifier,
        samples: [],
        deletedUuids: [],
        newAnchor: previous?.anchor ?? '',
      };
    }

    const HealthKit = await loadHealthKit();
    const healthTypeIdentifier = typeIdentifier as HealthTypeIdentifier;
    const now = new Date();
    let plan = buildHealthQueryPlan(previous, now);
    let result: RawSyncResponse;
    try {
      result = await queryHealthType(
        HealthKit,
        healthTypeIdentifier,
        plan.options,
      );
    } catch (error) {
      if (!plan.usesAnchor) throw error;

      // Development builds can retain anchors created by an older native
      // module. Rebuild that type from the bounded history window once.
      plan = buildHealthQueryPlan(
        { typeIdentifier, status: 'error' },
        now,
      );
      result = await queryHealthType(
        HealthKit,
        healthTypeIdentifier,
        plan.options,
      );
    }

    return {
      typeIdentifier,
      samples: result.samples.map((sample) =>
        normalizeSample(sample, healthTypeIdentifier),
      ),
      deletedUuids: result.deletedSamples.map((sample) => sample.uuid),
      newAnchor: result.newAnchor,
      earliestAuthorizedDate: plan.earliestAuthorizedDate,
    } satisfies HealthSyncBatch;
  },
};
