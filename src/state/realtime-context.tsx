import {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AppState } from 'react-native';

import { healthSampleRepository } from '@/data/health-sample-repository';
import {
  appendPostureEvent,
  buildPressureFeatures,
  buildPhysiologyWindow,
  getRadarFrameStatus,
  getRealtimeStreamStatus,
  appendPostureFeature,
  isValidPhysiologyWindow,
} from '@/domain/realtime';
import {
  assessRecovery,
  buildVitalBaseline,
  shouldNotifyElevatedLoad,
} from '@/domain/recovery';
import {
  CushionRealtimeCapabilities,
  CushionRealtimeConnectionError,
  CushionRealtimeConnectionState,
  CushionRealtimeEvent,
  CushionRealtimeStreamType,
  PhysiologyWindowSummary,
  PressureFeatureSummary,
  RadarDiagnosticsSnapshot,
  RadarFrameStatus,
  RealtimeImportResult,
  RealtimePostureSegment,
  RealtimeStreamStatus,
  RecoveryAssessment,
  VitalBaseline,
} from '@/domain/realtime-types';
import { healthDataService } from '@/services/health-data-service';
import {
  CUSHION_MQTT_SETTING_KEY,
  DEFAULT_CUSHION_MQTT_URL,
  normalizeCushionBrokerUrl,
} from '@/services/mqtt-cushion-transport';
import {
  requestRecoveryNotificationPermission,
  scheduleRecoveryNotification,
} from '@/services/recovery-notification-service';
import { useHealth } from '@/state/health-context';

const STREAM_TYPES: CushionRealtimeStreamType[] = [
  'heartRate',
  'respiratoryRate',
  'posture',
  'pressureFrame',
];
const EMPTY_IMPORT_RESULT: RealtimeImportResult = {
  accepted: 0,
  duplicates: 0,
  dropped: 0,
  errors: [],
};

interface RealtimeContextValue {
  connectionState: CushionRealtimeConnectionState;
  connectionError: CushionRealtimeConnectionError | null;
  brokerUrl: string;
  postureRevision: number;
  capabilities: CushionRealtimeCapabilities;
  latestByStream: Partial<
    Record<CushionRealtimeStreamType, CushionRealtimeEvent>
  >;
  streamStatuses: Record<CushionRealtimeStreamType, RealtimeStreamStatus>;
  radarDiagnostics: RadarDiagnosticsSnapshot;
  radarFrameStatus: RadarFrameStatus;
  physiologyWindow: PhysiologyWindowSummary | null;
  pressureFeature: PressureFeatureSummary | null;
  recovery: RecoveryAssessment;
  vitalBaseline: VitalBaseline;
  importResult: RealtimeImportResult;
  notificationsEnabled: boolean;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  saveBrokerUrl: (brokerUrl: string) => Promise<boolean>;
  ingest: (event: unknown) => RealtimeImportResult;
  ingestBatch: (events: unknown[]) => RealtimeImportResult;
  clearSessionData: () => void;
  setNotificationsEnabled: (enabled: boolean) => Promise<boolean>;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

function mergedImportResult(
  current: RealtimeImportResult,
  next: RealtimeImportResult,
): RealtimeImportResult {
  return {
    accepted: current.accepted + next.accepted,
    duplicates: current.duplicates + next.duplicates,
    dropped: current.dropped + next.dropped,
    errors: [...current.errors, ...next.errors].slice(-50),
  };
}

function localDateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function latestEvents(
  events: CushionRealtimeEvent[],
): Partial<Record<CushionRealtimeStreamType, CushionRealtimeEvent>> {
  const latest: Partial<
    Record<CushionRealtimeStreamType, CushionRealtimeEvent>
  > = {};
  for (const event of events) {
    const previous = latest[event.type];
    if (
      !previous ||
      Date.parse(event.capturedAt) > Date.parse(previous.capturedAt)
    ) {
      latest[event.type] = event;
    }
  }
  return latest;
}

export function RealtimeProvider({ children }: PropsWithChildren) {
  const { refreshHrv, samples } = useHealth();
  const postureSegmentsRef = useRef<RealtimePostureSegment[]>([]);
  const lastPersistedMinuteRef = useRef<string | undefined>(undefined);
  const lastPosturePersistedMinuteRef = useRef<string | undefined>(undefined);
  const lastPressureFeaturePersistedMinuteRef = useRef<string | undefined>(
    undefined,
  );
  const lastAssessmentPersistedRef = useRef<string | undefined>(undefined);
  const notificationInFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const sessionRequestedRef = useRef(false);
  const resumeSessionRef = useRef(false);
  const connectingRef = useRef(false);
  const connectionStateRef = useRef<CushionRealtimeConnectionState>(
    healthDataService.cushionRealtime.getConnectionState(),
  );
  const [events, setEvents] = useState<CushionRealtimeEvent[]>([]);
  const [pressureFeatures, setPressureFeatures] = useState<
    PressureFeatureSummary[]
  >([]);
  const [now, setNow] = useState(() => new Date());
  const [connectionState, setConnectionState] =
    useState<CushionRealtimeConnectionState>(
      healthDataService.cushionRealtime.getConnectionState(),
    );
  const [connectionError, setConnectionError] =
    useState<CushionRealtimeConnectionError | null>(
      healthDataService.cushionRealtime.getConnectionSnapshot().error ?? null,
    );
  const [brokerUrl, setBrokerUrl] = useState(DEFAULT_CUSHION_MQTT_URL);
  const brokerUrlRef = useRef(DEFAULT_CUSHION_MQTT_URL);
  const [postureRevision, setPostureRevision] = useState(0);
  const [capabilities, setCapabilities] =
    useState<CushionRealtimeCapabilities>(
      healthDataService.cushionRealtime.getCapabilities(),
    );
  const [storedWindows, setStoredWindows] = useState<
    PhysiologyWindowSummary[]
  >([]);
  const [importResult, setImportResult] =
    useState<RealtimeImportResult>(EMPTY_IMPORT_RESULT);
  const [radarDiagnostics, setRadarDiagnostics] =
    useState<RadarDiagnosticsSnapshot>(
      healthDataService.cushionRealtime.getRadarDiagnostics(),
    );
  const [notificationsEnabled, updateNotificationsEnabled] = useState(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const unsubscribeConnection =
      healthDataService.cushionRealtime.subscribeConnection((snapshot) => {
        connectionStateRef.current = snapshot.state;
        setConnectionState(snapshot.state);
        setConnectionError(snapshot.error ?? null);
      });
    const unsubscribeImportResults =
      healthDataService.cushionRealtime.subscribeImportResults((result) => {
        setImportResult((current) => mergedImportResult(current, result));
      });
    const unsubscribeRadarDiagnostics =
      healthDataService.cushionRealtime.subscribeRadarDiagnostics(
        setRadarDiagnostics,
      );
    return () => {
      unsubscribeConnection();
      unsubscribeImportResults();
      unsubscribeRadarDiagnostics();
    };
  }, []);

  const persistPostureProgress = useCallback(
    (
      previous: RealtimePostureSegment[],
      next: RealtimePostureSegment[],
    ) => {
      const previousSegment = previous.at(-1);
      const nextSegment = next.at(-1);
      if (!nextSegment) return;
      const transitioned = previousSegment?.id !== nextSegment.id;
      const minute = nextSegment.endAt.slice(0, 16);
      const segments = transitioned
        ? [previousSegment, nextSegment].filter(
            (segment): segment is RealtimePostureSegment => Boolean(segment),
          )
        : minute !== lastPosturePersistedMinuteRef.current
          ? [nextSegment]
          : [];
      if (segments.length === 0) return;
      lastPosturePersistedMinuteRef.current = minute;
      void Promise.all(
        segments.map((segment) =>
          healthSampleRepository.saveRealtimePostureSegment(segment),
        ),
      )
        .then(() => setPostureRevision((current) => current + 1))
        .catch(() =>
          console.warn('[realtime-store] POSTURE_SEGMENT_SAVE_FAILED'),
        );
    },
    [],
  );

  const flushActivePostureSegment = useCallback(async () => {
    const segment = postureSegmentsRef.current.at(-1);
    if (!segment) return;
    await healthSampleRepository.saveRealtimePostureSegment(segment);
    if (mountedRef.current) {
      setPostureRevision((current) => current + 1);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      healthSampleRepository.getPhysiologyWindows(),
      healthSampleRepository.getSetting('recovery.notifications.enabled'),
      healthSampleRepository.getSetting(CUSHION_MQTT_SETTING_KEY),
    ]).then(([windows, enabled, storedBrokerUrl]) => {
      if (cancelled) return;
      setStoredWindows(windows);
      updateNotificationsEnabled(enabled === 'true');
      const normalized = normalizeCushionBrokerUrl(
        storedBrokerUrl ?? DEFAULT_CUSHION_MQTT_URL,
      );
      const nextBrokerUrl = normalized.url ?? DEFAULT_CUSHION_MQTT_URL;
      brokerUrlRef.current = nextBrokerUrl;
      setBrokerUrl(nextBrokerUrl);
    }).catch(() =>
      console.warn('[realtime-store] INITIAL_READ_FAILED'),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const unsubscribe = healthDataService.cushionRealtime.subscribe((event) => {
      const cutoff = Date.now() - 10 * 60 * 1000;
      setEvents((current) =>
        [...current, event].filter(
          (item) => Date.parse(item.capturedAt) >= cutoff,
        ),
      );
      if (event.type === 'pressureFrame') {
        const feature = buildPressureFeatures(
          event,
          healthDataService.cushionRealtime.getPressureCalibration(),
        );
        setPressureFeatures((current) =>
          [...current, feature].filter(
            (item) =>
              Date.parse(item.capturedAt) >=
              Date.now() - 10 * 60 * 1000,
          ),
        );
        const previousSegments = postureSegmentsRef.current;
        const nextSegments = appendPostureFeature(previousSegments, feature);
        postureSegmentsRef.current = nextSegments;
        persistPostureProgress(previousSegments, nextSegments);
        const minute = feature.capturedAt.slice(0, 16);
        if (minute !== lastPressureFeaturePersistedMinuteRef.current) {
          lastPressureFeaturePersistedMinuteRef.current = minute;
          void healthSampleRepository
            .savePressureFeature(feature)
            .catch(() =>
              console.warn('[realtime-store] PRESSURE_DERIVATIVE_SAVE_FAILED'),
            );
        }
      }
      if (event.type === 'posture') {
        const previousSegments = postureSegmentsRef.current;
        const nextSegments = appendPostureEvent(previousSegments, event);
        postureSegmentsRef.current = nextSegments;
        persistPostureProgress(previousSegments, nextSegments);
      }
      setCapabilities(healthDataService.cushionRealtime.getCapabilities());
    });
    return unsubscribe;
  }, [persistPostureProgress]);

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(interval);
  }, []);

  const latestByStream = useMemo(
    () => latestEvents(events),
    [events],
  );
  const streamStatuses = useMemo(
    () =>
      Object.fromEntries(
        STREAM_TYPES.map((type) => [
          type,
          getRealtimeStreamStatus(type, latestByStream[type], now),
        ]),
      ) as Record<CushionRealtimeStreamType, RealtimeStreamStatus>,
    [latestByStream, now],
  );
  const radarFrameStatus = useMemo(
    () => getRadarFrameStatus(radarDiagnostics, now),
    [now, radarDiagnostics],
  );
  const physiologyWindow = useMemo(
    () => buildPhysiologyWindow(events, now),
    [events, now],
  );
  const pressureFeature =
    [...pressureFeatures].sort((a, b) =>
      Date.parse(b.capturedAt) - Date.parse(a.capturedAt),
    )[0] ?? null;
  const vitalBaseline = useMemo(
    () => buildVitalBaseline(storedWindows, now),
    [now, storedWindows],
  );
  const recovery = useMemo(
    () =>
      assessRecovery({
        hrvSamples: samples,
        physiologyWindow,
        vitalBaseline,
        capabilities,
        pressureFeatures,
        now,
      }),
    [
      capabilities,
      now,
      pressureFeatures,
      samples,
      physiologyWindow,
      vitalBaseline,
    ],
  );

  useEffect(() => {
    if (
      connectionState !== 'connected' ||
      !isValidPhysiologyWindow(physiologyWindow)
    ) {
      return;
    }
    const minute = now.toISOString().slice(0, 16);
    if (minute === lastPersistedMinuteRef.current) return;
    lastPersistedMinuteRef.current = minute;
    void healthSampleRepository
      .savePhysiologyWindow(physiologyWindow)
      .then(() =>
        setStoredWindows((current) => [
          physiologyWindow,
          ...current.filter(
            (item) =>
              item.id !== physiologyWindow.id &&
              Date.parse(item.endAt) >=
                Date.now() - 30 * 24 * 60 * 60 * 1000,
          ),
        ]),
      )
      .catch(() =>
        console.warn('[realtime-store] PHYSIOLOGY_WINDOW_SAVE_FAILED'),
      );
  }, [connectionState, now, physiologyWindow]);

  useEffect(() => {
    if (recovery.state === 'insufficient') return;
    const persistenceKey = `${recovery.id}:${now.toISOString().slice(0, 16)}`;
    if (lastAssessmentPersistedRef.current === persistenceKey) return;
    lastAssessmentPersistedRef.current = persistenceKey;
    void healthSampleRepository
      .saveRecoveryAssessment(recovery)
      .catch(() =>
        console.warn('[realtime-store] RECOVERY_ASSESSMENT_SAVE_FAILED'),
      );
  }, [now, recovery]);

  useEffect(() => {
    if (connectionState !== 'connected') return;
    void refreshHrv();
    const refresh = () => {
      if (AppState.currentState === 'active') void refreshHrv();
    };
    const interval = setInterval(refresh, 5 * 60 * 1000);
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') refresh();
    });
    return () => {
      clearInterval(interval);
      subscription.remove();
    };
  }, [connectionState, refreshHrv]);

  useEffect(() => {
    if (
      !notificationsEnabled ||
      recovery.state !== 'elevatedLoad' ||
      notificationInFlightRef.current
    ) {
      return;
    }
    notificationInFlightRef.current = true;
    void (async () => {
      try {
        const today = localDateKey(now);
        const [lastNotificationAt, countValue, countDate] =
          await Promise.all([
            healthSampleRepository.getSetting(
              'recovery.notifications.lastSentAt',
            ),
            healthSampleRepository.getSetting(
              'recovery.notifications.dailyCount',
            ),
            healthSampleRepository.getSetting(
              'recovery.notifications.dailyDate',
            ),
          ]);
        if (!mountedRef.current) return;
        const notificationsToday =
          countDate === today ? Number(countValue ?? 0) : 0;
        const decision = shouldNotifyElevatedLoad({
          assessment: recovery,
          heartRateEvents: events,
          vitalBaseline,
          capabilities,
          pressureFeatures,
          lastNotificationAt: lastNotificationAt ?? undefined,
          notificationsToday,
          now,
        });
        if (!decision.eligible) return;
        const notificationId = await scheduleRecoveryNotification();
        if (!notificationId) return;
        await Promise.all([
          healthSampleRepository.setSetting(
            'recovery.notifications.lastSentAt',
            now.toISOString(),
          ),
          healthSampleRepository.setSetting(
            'recovery.notifications.dailyDate',
            today,
          ),
          healthSampleRepository.setSetting(
            'recovery.notifications.dailyCount',
            String(notificationsToday + 1),
          ),
        ]);
      } finally {
        notificationInFlightRef.current = false;
      }
    })();
  }, [
    capabilities,
    events,
    notificationsEnabled,
    now,
    pressureFeatures,
    recovery,
    vitalBaseline,
  ]);

  const connectSource = useCallback(async () => {
    if (
      connectingRef.current ||
      connectionStateRef.current === 'connected' ||
      connectionStateRef.current === 'reconnecting'
    ) {
      return;
    }
    connectingRef.current = true;
    try {
      await healthDataService.cushionRealtime.connect({
        brokerUrl: brokerUrlRef.current,
      });
      setCapabilities(healthDataService.cushionRealtime.getCapabilities());
      void refreshHrv();
    } finally {
      connectingRef.current = false;
    }
  }, [refreshHrv]);

  const connect = useCallback(async () => {
    sessionRequestedRef.current = true;
    resumeSessionRef.current = false;
    try {
      await connectSource();
    } catch {
      // The adapter publishes a structured connection error for the UI.
    }
  }, [connectSource]);

  const disconnect = useCallback(async () => {
    sessionRequestedRef.current = false;
    resumeSessionRef.current = false;
    await flushActivePostureSegment().catch(() =>
      console.warn('[realtime-store] POSTURE_SEGMENT_FLUSH_FAILED'),
    );
    await healthDataService.cushionRealtime.disconnect();
  }, [flushActivePostureSegment]);

  const saveBrokerUrl = useCallback(
    async (value: string) => {
      const normalized = normalizeCushionBrokerUrl(value);
      if (!normalized.url) return false;
      await healthSampleRepository.setSetting(
        CUSHION_MQTT_SETTING_KEY,
        normalized.url,
      );
      brokerUrlRef.current = normalized.url;
      setBrokerUrl(normalized.url);
      if (sessionRequestedRef.current) {
        await flushActivePostureSegment().catch(() =>
          console.warn('[realtime-store] POSTURE_SEGMENT_FLUSH_FAILED'),
        );
        await healthDataService.cushionRealtime.disconnect();
        connectingRef.current = false;
        try {
          await connectSource();
        } catch {
          // The saved address remains available for a later manual retry.
        }
      }
      return true;
    },
    [connectSource, flushActivePostureSegment],
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        if (resumeSessionRef.current && sessionRequestedRef.current) {
          resumeSessionRef.current = false;
          void connectSource().catch(() => undefined);
        }
        return;
      }
      if (
        sessionRequestedRef.current &&
        !resumeSessionRef.current &&
        connectionStateRef.current !== 'disconnected'
      ) {
        resumeSessionRef.current = true;
        void flushActivePostureSegment()
          .catch(() =>
            console.warn('[realtime-store] POSTURE_SEGMENT_FLUSH_FAILED'),
          )
          .finally(() =>
            healthDataService.cushionRealtime.disconnect().catch(() => undefined),
          );
      }
    });
    return () => {
      subscription.remove();
      if (sessionRequestedRef.current) {
        void flushActivePostureSegment().finally(() =>
          healthDataService.cushionRealtime.disconnect().catch(() => undefined),
        );
      }
    };
  }, [connectSource, flushActivePostureSegment]);

  const ingest = useCallback((event: unknown) => {
    return healthDataService.cushionRealtime.ingest(event);
  }, []);

  const ingestBatch = useCallback((events: unknown[]) => {
    return healthDataService.cushionRealtime.ingestBatch(events);
  }, []);

  const clearSessionData = useCallback(() => {
    setEvents([]);
    setPressureFeatures([]);
    setStoredWindows([]);
    postureSegmentsRef.current = [];
    lastPersistedMinuteRef.current = undefined;
    lastPosturePersistedMinuteRef.current = undefined;
    lastPressureFeaturePersistedMinuteRef.current = undefined;
    lastAssessmentPersistedRef.current = undefined;
    setImportResult(EMPTY_IMPORT_RESULT);
    setPostureRevision((current) => current + 1);
  }, []);

  const setNotificationsEnabled = useCallback(async (enabled: boolean) => {
    if (enabled) {
      const granted = await requestRecoveryNotificationPermission();
      if (!granted) return false;
    }
    await healthSampleRepository.setSetting(
      'recovery.notifications.enabled',
      String(enabled),
    );
    updateNotificationsEnabled(enabled);
    return true;
  }, []);

  const value = useMemo<RealtimeContextValue>(
    () => ({
      connectionState,
      connectionError,
      brokerUrl,
      postureRevision,
      capabilities,
      latestByStream,
      streamStatuses,
      radarDiagnostics,
      radarFrameStatus,
      physiologyWindow,
      pressureFeature,
      recovery,
      vitalBaseline,
      importResult,
      notificationsEnabled,
      connect,
      disconnect,
      saveBrokerUrl,
      ingest,
      ingestBatch,
      clearSessionData,
      setNotificationsEnabled,
    }),
    [
      capabilities,
      brokerUrl,
      clearSessionData,
      connect,
      connectionError,
      connectionState,
      disconnect,
      importResult,
      ingest,
      ingestBatch,
      latestByStream,
      notificationsEnabled,
      physiologyWindow,
      pressureFeature,
      postureRevision,
      radarDiagnostics,
      radarFrameStatus,
      recovery,
      saveBrokerUrl,
      setNotificationsEnabled,
      streamStatuses,
      vitalBaseline,
    ],
  );

  return (
    <RealtimeContext.Provider value={value}>
      {children}
    </RealtimeContext.Provider>
  );
}

export function useRealtime() {
  const value = useContext(RealtimeContext);
  if (!value) {
    throw new Error('useRealtime must be used inside RealtimeProvider');
  }
  return value;
}
