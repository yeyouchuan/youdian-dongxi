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

import { healthSampleRepository } from '@/data/health-sample-repository';
import { HealthKitSample, HealthKitSyncState } from '@/domain/types';
import {
  classifyHealthSyncError,
  CORE_HEALTH_TYPES,
  HEALTH_TYPES,
  HealthTypeIdentifier,
  summarizeHealthSyncError,
} from '@/services/apple-health-adapter';
import { healthDataService } from '@/services/health-data-service';

type HealthConnectionStatus =
  | 'loading'
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'syncing'
  | 'unavailable'
  | 'error';

interface SensitiveSettings {
  menstrual: boolean;
  stateOfMind: boolean;
  showSensitiveOnReport: boolean;
}

interface HealthContextValue {
  status: HealthConnectionStatus;
  available: boolean;
  samples: HealthKitSample[];
  syncStates: HealthKitSyncState[];
  sensitive: SensitiveSettings;
  lastError?: string;
  connect: () => Promise<void>;
  sync: () => Promise<void>;
  disconnect: () => Promise<void>;
  clearCache: () => Promise<void>;
  setSensitive: (
    key: keyof Pick<SensitiveSettings, 'menstrual' | 'stateOfMind'>,
    enabled: boolean,
  ) => Promise<void>;
  setShowSensitiveOnReport: (enabled: boolean) => Promise<void>;
}

const HealthContext = createContext<HealthContextValue | null>(null);

function asBoolean(value: string | null) {
  return value === 'true';
}

export function HealthProvider({ children }: PropsWithChildren) {
  const hasStartedSync = useRef(false);
  const [status, setStatus] = useState<HealthConnectionStatus>('loading');
  const [available, setAvailable] = useState(false);
  const [samples, setSamples] = useState<HealthKitSample[]>([]);
  const [syncStates, setSyncStates] = useState<HealthKitSyncState[]>([]);
  const [lastError, setLastError] = useState<string>();
  const [sensitive, updateSensitive] = useState<SensitiveSettings>({
    menstrual: false,
    stateOfMind: false,
    showSensitiveOnReport: false,
  });

  const reload = useCallback(async () => {
    const [nextSamples, nextSyncStates] = await Promise.all([
      healthSampleRepository.getSamples(),
      healthSampleRepository.getSyncStates(),
    ]);
    setSamples(nextSamples);
    setSyncStates(nextSyncStates);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await healthSampleRepository.initialize();
        const [isAvailable, connected, menstrual, stateOfMind, showSensitive] =
          await Promise.all([
            healthDataService.appleHealth.isAvailable(),
            healthSampleRepository.getSetting('health.connected'),
            healthSampleRepository.getSetting('health.sensitive.menstrual'),
            healthSampleRepository.getSetting('health.sensitive.stateOfMind'),
            healthSampleRepository.getSetting('health.showSensitiveOnReport'),
          ]);
        await reload();
        if (cancelled) return;
        setAvailable(isAvailable);
        updateSensitive({
          menstrual: asBoolean(menstrual),
          stateOfMind: asBoolean(stateOfMind),
          showSensitiveOnReport: asBoolean(showSensitive),
        });
        setStatus(!isAvailable ? 'unavailable' : asBoolean(connected) ? 'connected' : 'disconnected');
      } catch {
        if (!cancelled) {
          setLastError('本地健康数据初始化失败');
          setStatus('error');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const sync = useCallback(async () => {
    if (!available) return;
    hasStartedSync.current = true;
    setStatus('syncing');
    setLastError(undefined);
    const typeIdentifiers: HealthTypeIdentifier[] = [...CORE_HEALTH_TYPES];
    if (sensitive.menstrual) typeIdentifiers.push(HEALTH_TYPES.menstrualFlow);
    if (sensitive.stateOfMind) typeIdentifiers.push(HEALTH_TYPES.stateOfMind);
    const previousByType = new Map(syncStates.map((state) => [state.typeIdentifier, state]));

    try {
      const coreAuthorizationCompleted =
        await healthDataService.appleHealth.requestCoreReadAccess();
      if (!coreAuthorizationCompleted) {
        throw new Error('HealthKit authorization was not completed');
      }
      if (sensitive.menstrual) {
        const completed =
          await healthDataService.appleHealth.requestSensitiveReadAccess(
            'menstrual',
          );
        if (!completed) {
          throw new Error('Menstrual flow authorization was not completed');
        }
      }
      if (sensitive.stateOfMind) {
        const completed =
          await healthDataService.appleHealth.requestSensitiveReadAccess(
            'stateOfMind',
          );
        if (!completed) {
          throw new Error('State of mind authorization was not completed');
        }
      }

      let failures = 0;
      for (const typeIdentifier of typeIdentifiers) {
        try {
          const batch = await healthDataService.appleHealth.syncType(
            typeIdentifier,
            previousByType.get(typeIdentifier),
          );
          await healthSampleRepository.applySyncBatch(batch);
        } catch (error) {
          failures += 1;
          const errorCode = classifyHealthSyncError(error);
          console.warn(
            `[health-sync] ${typeIdentifier} ${errorCode}: ${summarizeHealthSyncError(error)}`,
          );
          await healthSampleRepository.recordSyncError(
            typeIdentifier,
            errorCode,
          );
        }
      }
      await reload();
      if (failures > 0) {
        setLastError(
          `${failures} 个项目没有完成。重试会重新确认权限，并重建失败项目的同步锚点。`,
        );
        setStatus('error');
      } else {
        setStatus('connected');
      }
    } catch (error) {
      const errorCode = classifyHealthSyncError(error);
      console.warn(
        `[health-sync] authorization ${errorCode}: ${summarizeHealthSyncError(error)}`,
      );
      setLastError(
        errorCode === 'AUTHORIZATION_REQUIRED'
          ? 'Apple Health 授权没有完成。请确认“健康”中的数据访问权限后再试。'
          : `同步准备失败（${errorCode}）。本地已有数据不会被删除。`,
      );
      setStatus('error');
    }
  }, [available, reload, sensitive.menstrual, sensitive.stateOfMind, syncStates]);

  useEffect(() => {
    if (status !== 'connected' || hasStartedSync.current) return;
    void sync();
  }, [status, sync]);

  const connect = useCallback(async () => {
    if (!available) return;
    setStatus('connecting');
    setLastError(undefined);
    try {
      const completed = await healthDataService.appleHealth.requestCoreReadAccess();
      if (!completed) throw new Error('Authorization was not completed');
      await healthSampleRepository.setSetting('health.connected', 'true');
      setStatus('connected');
      await sync();
    } catch {
      setLastError('未能完成 Apple Health 连接');
      setStatus('error');
    }
  }, [available, sync]);

  const setSensitive = useCallback(
    async (
      key: keyof Pick<SensitiveSettings, 'menstrual' | 'stateOfMind'>,
      enabled: boolean,
    ) => {
      if (enabled) {
        const completed = await healthDataService.appleHealth.requestSensitiveReadAccess(key);
        if (!completed) return;
      }
      await healthSampleRepository.setSetting(`health.sensitive.${key}`, String(enabled));
      updateSensitive((current) => ({ ...current, [key]: enabled }));
    },
    [],
  );

  const setShowSensitiveOnReport = useCallback(async (enabled: boolean) => {
    await healthSampleRepository.setSetting(
      'health.showSensitiveOnReport',
      String(enabled),
    );
    updateSensitive((current) => ({ ...current, showSensitiveOnReport: enabled }));
  }, []);

  const disconnect = useCallback(async () => {
    await healthSampleRepository.setSetting('health.connected', 'false');
    setStatus(available ? 'disconnected' : 'unavailable');
  }, [available]);

  const clearCache = useCallback(async () => {
    await healthSampleRepository.clearHealthCache();
    await reload();
  }, [reload]);

  const value = useMemo<HealthContextValue>(
    () => ({
      status,
      available,
      samples,
      syncStates,
      sensitive,
      lastError,
      connect,
      sync,
      disconnect,
      clearCache,
      setSensitive,
      setShowSensitiveOnReport,
    }),
    [
      available,
      clearCache,
      connect,
      disconnect,
      lastError,
      samples,
      sensitive,
      setSensitive,
      setShowSensitiveOnReport,
      status,
      sync,
      syncStates,
    ],
  );

  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth() {
  const value = useContext(HealthContext);
  if (!value) throw new Error('useHealth must be used inside HealthProvider');
  return value;
}
