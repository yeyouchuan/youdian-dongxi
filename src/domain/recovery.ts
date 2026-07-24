import {
  CushionRealtimeCapabilities,
  CushionRealtimeEvent,
  HrvBaseline,
  PhysiologyWindowSummary,
  PressureFeatureSummary,
  RecoveryAssessment,
  VitalBaseline,
} from '@/domain/realtime-types';
import { isValidPhysiologyWindow } from '@/domain/realtime';
import { HealthKitSample } from '@/domain/types';
import { HEALTH_TYPES } from '@/services/apple-health-adapter';

const DAY_MS = 24 * 60 * 60 * 1000;
const HRV_FRESHNESS_MS = 15 * 60 * 1000;
const BASELINE_WINDOW_MS = 30 * DAY_MS;
const VITAL_BASELINE_WINDOW_MS = 14 * DAY_MS;

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function rounded(value: number, digits = 3) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function isHrvSample(sample: HealthKitSample) {
  return (
    sample.typeIdentifier === HEALTH_TYPES.hrv &&
    typeof sample.value === 'number' &&
    Number.isFinite(sample.value) &&
    sample.value >= 5 &&
    sample.value <= 300
  );
}

function removeLogMadOutliers(values: { date: string; value: number }[]) {
  if (values.length < 3) return values;
  const logValues = values.map(({ value }) => Math.log(value));
  const center = median(logValues);
  const deviations = logValues.map((value) => Math.abs(value - center));
  const mad = median(deviations);
  if (mad === 0) return values;
  const robustLimit = 3.5 * 1.4826 * mad;
  return values.filter(
    ({ value }) => Math.abs(Math.log(value) - center) <= robustLimit,
  );
}

export function buildHrvBaseline(
  samples: HealthKitSample[],
  target: HealthKitSample,
): HrvBaseline | null {
  if (!isHrvSample(target)) return null;
  const targetTime = Date.parse(target.startDate);
  const earliestTime = targetTime - BASELINE_WINDOW_MS;
  const eligible = samples.filter(
    (sample) =>
      sample.uuid !== target.uuid &&
      isHrvSample(sample) &&
      sample.sourceBundleId === target.sourceBundleId &&
      Date.parse(sample.startDate) >= earliestTime &&
      Date.parse(sample.startDate) < targetTime,
  );
  const distinctDays = new Set(
    eligible.map((sample) => sample.startDate.slice(0, 10)),
  );
  if (eligible.length < 10 || distinctDays.size < 7) return null;

  const byDay = new Map<string, number[]>();
  for (const sample of eligible) {
    const date = sample.startDate.slice(0, 10);
    byDay.set(date, [...(byDay.get(date) ?? []), sample.value as number]);
  }
  const dailyMedians = [...byDay.entries()].map(([date, values]) => ({
    date,
    value: median(values),
  }));
  const filtered = removeLogMadOutliers(dailyMedians);
  if (filtered.length < 7) return null;

  return {
    sourceBundleId: target.sourceBundleId,
    startDate: eligible
      .map((sample) => sample.startDate)
      .sort((a, b) => Date.parse(a) - Date.parse(b))[0],
    endDate: target.startDate,
    valueMs: rounded(median(filtered.map(({ value }) => value)), 1),
    sampleCount: eligible.length,
    dayCount: filtered.length,
  };
}

export function buildVitalBaseline(
  windows: PhysiologyWindowSummary[],
  targetTime = new Date(),
): VitalBaseline {
  const targetMs = targetTime.getTime();
  const earliestMs = targetMs - VITAL_BASELINE_WINDOW_MS;
  const eligible = windows.filter((window) => {
    const endMs = Date.parse(window.endAt);
    return (
      endMs >= earliestMs &&
      endMs < targetMs &&
      isValidPhysiologyWindow(window)
    );
  });
  const sessions = new Set(eligible.map((window) => window.sessionId));
  if (sessions.size < 5) {
    return {
      heartRateMedian: null,
      respiratoryRateMedian: null,
      sessionCount: sessions.size,
    };
  }
  const heartRates = eligible
    .map((window) => window.heartRateMedian)
    .filter((value): value is number => value !== null);
  const respiratoryRates = eligible
    .map((window) => window.respiratoryRateMedian)
    .filter((value): value is number => value !== null);
  return {
    heartRateMedian:
      heartRates.length > 0 ? rounded(median(heartRates), 1) : null,
    respiratoryRateMedian:
      respiratoryRates.length > 0
        ? rounded(median(respiratoryRates), 1)
        : null,
    sessionCount: sessions.size,
  };
}

function insufficient(
  reasons: string[],
  now: Date,
  details: Partial<RecoveryAssessment> = {},
): RecoveryAssessment {
  return {
    id: `recovery:${now.toISOString()}`,
    state: 'insufficient',
    confidence: 'low',
    label: '信号不足',
    reasons,
    createdAt: now.toISOString(),
    ...details,
  };
}

function pressureReady(
  capabilities: CushionRealtimeCapabilities,
  features: PressureFeatureSummary[],
) {
  if (!capabilities.pressure) return { ready: true, reason: undefined };
  const recent = [...features].sort(
    (a, b) => Date.parse(b.capturedAt) - Date.parse(a.capturedAt),
  );
  const latest = recent[0];
  if (!capabilities.pressureCalibrated || latest?.calibrationState !== 'ready') {
    return { ready: false, reason: 'pressureCalibrationRequired' };
  }
  const latestTime = Date.parse(latest.capturedAt);
  const fiveMinuteFeatures = recent.filter(
    (feature) =>
      feature.deviceId === latest.deviceId &&
      feature.sessionId === latest.sessionId &&
      latestTime - Date.parse(feature.capturedAt) <= 5 * 60 * 1000,
  );
  const span =
    fiveMinuteFeatures.length > 1
      ? latestTime -
        Math.min(
          ...fiveMinuteFeatures.map((feature) =>
            Date.parse(feature.capturedAt),
          ),
        )
      : 0;
  const validRatio =
    fiveMinuteFeatures.filter(
      (feature) =>
        feature.calibrationState === 'ready' &&
        feature.inference.occupancy === 'occupied' &&
        feature.quality >= 0.7,
    ).length / Math.max(1, fiveMinuteFeatures.length);
  const centers = fiveMinuteFeatures.map(
    (feature) => feature.centerOfPressure,
  );
  const centerSpread =
    centers.length > 0
      ? Math.max(
          Math.max(...centers.map((center) => center.x)) -
            Math.min(...centers.map((center) => center.x)),
          Math.max(...centers.map((center) => center.y)) -
            Math.min(...centers.map((center) => center.y)),
        )
      : 1;
  if (span < 290_000 || validRatio < 0.8 || centerSpread > 0.16) {
    return { ready: false, reason: 'pressureSessionUnconfirmed' };
  }
  return { ready: true, reason: undefined };
}

export function assessRecovery({
  hrvSamples,
  physiologyWindow,
  vitalBaseline,
  capabilities,
  pressureFeatures = [],
  now = new Date(),
}: {
  hrvSamples: HealthKitSample[];
  physiologyWindow: PhysiologyWindowSummary | null;
  vitalBaseline: VitalBaseline;
  capabilities: CushionRealtimeCapabilities;
  pressureFeatures?: PressureFeatureSummary[];
  now?: Date;
}): RecoveryAssessment {
  const latestHrv = hrvSamples
    .filter(isHrvSample)
    .filter((sample) => Date.parse(sample.startDate) <= now.getTime())
    .sort(
      (a, b) => Date.parse(b.startDate) - Date.parse(a.startDate),
    )[0];
  if (!latestHrv) return insufficient(['hrvMissing'], now);
  if (now.getTime() - Date.parse(latestHrv.startDate) > HRV_FRESHNESS_MS) {
    return insufficient(['hrvStale'], now, {
      measuredAt: latestHrv.startDate,
      hrvSampleUuid: latestHrv.uuid,
    });
  }
  const baseline = buildHrvBaseline(hrvSamples, latestHrv);
  if (!baseline) {
    return insufficient(['hrvBaselineInsufficient'], now, {
      measuredAt: latestHrv.startDate,
      hrvSampleUuid: latestHrv.uuid,
      hrvSdnnMs: latestHrv.value as number,
    });
  }
  if (
    !physiologyWindow ||
    physiologyWindow.heartRateMedian === null ||
    physiologyWindow.respiratoryRateMedian === null ||
    physiologyWindow.heartRateCoverage < 0.8 ||
    physiologyWindow.respiratoryRateCoverage < 0.8
  ) {
    return insufficient(['realtimeWindowInsufficient'], now, {
      measuredAt: latestHrv.startDate,
      hrvSampleUuid: latestHrv.uuid,
      hrvSdnnMs: latestHrv.value as number,
      hrvBaselineMs: baseline.valueMs,
      physiologyWindowId: physiologyWindow?.id,
    });
  }
  if (
    !physiologyWindow.heartRateStable ||
    (physiologyWindow.heartRateQuality ?? 0) < 0.7 ||
    (physiologyWindow.respiratoryRateQuality ?? 0) < 0.7
  ) {
    return insufficient(['realtimeQualityLow'], now, {
      measuredAt: latestHrv.startDate,
      hrvSampleUuid: latestHrv.uuid,
      hrvSdnnMs: latestHrv.value as number,
      hrvBaselineMs: baseline.valueMs,
      physiologyWindowId: physiologyWindow.id,
    });
  }
  const pressure = pressureReady(capabilities, pressureFeatures);
  if (!pressure.ready) {
    return insufficient([pressure.reason as string], now, {
      measuredAt: latestHrv.startDate,
      hrvSampleUuid: latestHrv.uuid,
      hrvSdnnMs: latestHrv.value as number,
      hrvBaselineMs: baseline.valueMs,
      physiologyWindowId: physiologyWindow.id,
    });
  }

  const ratio = (latestHrv.value as number) / baseline.valueMs;
  const state =
    ratio >= 1.05
      ? 'recoveryGood'
      : ratio >= 0.85
        ? 'steady'
        : 'elevatedLoad';
  const labels = {
    recoveryGood: '恢复良好',
    steady: '状态平稳',
    elevatedLoad: '负荷升高',
  } as const;
  const reasons = ['hrvComparedWithPersonalBaseline'];
  let confidence: RecoveryAssessment['confidence'] = 'medium';
  if (
    vitalBaseline.heartRateMedian !== null &&
    physiologyWindow.heartRateMedian >
      vitalBaseline.heartRateMedian +
        Math.max(8, vitalBaseline.heartRateMedian * 0.12)
  ) {
    reasons.push('heartRateAboveSittingBaseline');
    if (state === 'elevatedLoad') confidence = 'high';
  }
  if (
    vitalBaseline.respiratoryRateMedian !== null &&
    physiologyWindow.respiratoryRateMedian >
      vitalBaseline.respiratoryRateMedian +
        Math.max(3, vitalBaseline.respiratoryRateMedian * 0.2)
  ) {
    reasons.push('respiratoryRateAboveSittingBaseline');
  }

  return {
    id: `recovery:${latestHrv.uuid}:${physiologyWindow.id}`,
    state,
    confidence,
    label: labels[state],
    measuredAt: latestHrv.startDate,
    hrvSampleUuid: latestHrv.uuid,
    hrvSdnnMs: latestHrv.value as number,
    hrvBaselineMs: baseline.valueMs,
    hrvRatio: rounded(ratio),
    physiologyWindowId: physiologyWindow.id,
    reasons,
    createdAt: now.toISOString(),
  };
}

export function shouldNotifyElevatedLoad({
  assessment,
  heartRateEvents,
  vitalBaseline,
  capabilities,
  pressureFeatures = [],
  lastNotificationAt,
  notificationsToday,
  now = new Date(),
}: {
  assessment: RecoveryAssessment;
  heartRateEvents: CushionRealtimeEvent[];
  vitalBaseline: VitalBaseline;
  capabilities: CushionRealtimeCapabilities;
  pressureFeatures?: PressureFeatureSummary[];
  lastNotificationAt?: string;
  notificationsToday: number;
  now?: Date;
}) {
  const reasons: string[] = [];
  const hour = now.getHours();
  if (hour >= 22 || hour < 8) reasons.push('quietHours');
  if (notificationsToday >= 2) reasons.push('dailyLimit');
  if (
    lastNotificationAt &&
    now.getTime() - Date.parse(lastNotificationAt) < 4 * 60 * 60 * 1000
  ) {
    reasons.push('cooldown');
  }
  if (
    assessment.state !== 'elevatedLoad' ||
    assessment.hrvRatio === undefined ||
    assessment.hrvRatio >= 0.8
  ) {
    reasons.push('hrvThresholdNotMet');
  }
  if (vitalBaseline.heartRateMedian === null) {
    reasons.push('heartRateBaselineInsufficient');
  } else {
    const threshold =
      vitalBaseline.heartRateMedian +
      Math.max(8, vitalBaseline.heartRateMedian * 0.12);
    const threeMinutesAgo = now.getTime() - 3 * 60 * 1000;
    const recent = heartRateEvents
      .filter(
        (
          event,
        ): event is Extract<CushionRealtimeEvent, { type: 'heartRate' }> =>
          event.type === 'heartRate' &&
          Date.parse(event.capturedAt) >= threeMinutesAgo &&
          Date.parse(event.capturedAt) <= now.getTime(),
      )
      .sort((a, b) => a.capturedAt.localeCompare(b.capturedAt));
    const span =
      recent.length > 1
        ? Date.parse(recent.at(-1)!.capturedAt) -
          Date.parse(recent[0].capturedAt)
        : 0;
    const elevatedRatio =
      recent.length > 0
        ? recent.filter(
            (event) =>
              event.payload.bpm > threshold && (event.quality ?? 0) >= 0.7,
          ).length / recent.length
        : 0;
    if (span < 170_000 || elevatedRatio < 0.8) {
      reasons.push('heartRateNotSustained');
    }
  }
  const pressure = pressureReady(capabilities, pressureFeatures);
  if (!pressure.ready) reasons.push(pressure.reason as string);
  return { eligible: reasons.length === 0, reasons };
}
