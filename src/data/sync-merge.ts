import {
  HealthKitSample,
  HealthKitSyncState,
  HealthSyncBatch,
} from '@/domain/types';

export function mergeHealthSyncBatch(
  currentSamples: HealthKitSample[],
  batch: HealthSyncBatch,
): HealthKitSample[] {
  const deleted = new Set(batch.deletedUuids);
  const merged = new Map(
    currentSamples
      .filter((sample) => !deleted.has(sample.uuid))
      .map((sample) => [sample.uuid, sample]),
  );
  for (const sample of batch.samples) {
    merged.set(sample.uuid, sample);
  }
  return [...merged.values()].sort((a, b) => b.startDate.localeCompare(a.startDate));
}

export interface CommittedSyncSnapshot {
  samples: HealthKitSample[];
  state: HealthKitSyncState;
}

export function buildCommittedSyncSnapshot(
  currentSamples: HealthKitSample[],
  batch: HealthSyncBatch,
  completedAt = new Date().toISOString(),
): CommittedSyncSnapshot {
  if (!batch.newAnchor) throw new Error('A successful sync batch requires an anchor');
  if (batch.samples.some((sample) => sample.typeIdentifier !== batch.typeIdentifier)) {
    throw new Error('A sync batch may only contain one HealthKit data type');
  }

  return {
    samples: mergeHealthSyncBatch(currentSamples, batch),
    state: {
      typeIdentifier: batch.typeIdentifier,
      anchor: batch.newAnchor,
      lastSyncAt: completedAt,
      earliestAuthorizedDate: batch.earliestAuthorizedDate,
      status: 'success',
    },
  };
}
