import '@/global.css';

import { useEffect } from 'react';
import {
  DefaultTheme,
  Href,
  Stack,
  ThemeProvider,
  useRouter,
} from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { Palette } from '@/constants/theme';
import {
  getInitialRecoveryNotificationUrl,
  subscribeToRecoveryNotificationResponses,
} from '@/services/recovery-notification-service';
import { HealthProvider } from '@/state/health-context';
import { RealtimeProvider } from '@/state/realtime-context';

const appTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: Palette.red,
    background: Palette.background,
    card: Palette.surface,
    text: Palette.text,
    border: Palette.border,
    notification: Palette.amber,
  },
};

function NotificationNavigation() {
  const router = useRouter();

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;
    let cancelled = false;
    const open = (url: string) => router.push(url as Href);
    void subscribeToRecoveryNotificationResponses(open).then((next) => {
      if (cancelled) next();
      else unsubscribe = next;
    });
    void getInitialRecoveryNotificationUrl().then((url) => {
      if (!cancelled && url) open(url);
    });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [router]);

  return null;
}

export default function RootLayout() {
  return (
    <ThemeProvider value={appTheme}>
      <HealthProvider>
        <RealtimeProvider>
          <NotificationNavigation />
          <StatusBar style="dark" />
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: Palette.background } }}>
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="trends" />
            <Stack.Screen name="cushion-diagnostics" />
            {__DEV__ ? <Stack.Screen name="cushion-test" /> : null}
          </Stack>
        </RealtimeProvider>
      </HealthProvider>
    </ThemeProvider>
  );
}
