import '@/global.css';

import { DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { Palette } from '@/constants/theme';
import { HealthProvider } from '@/state/health-context';

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

export default function RootLayout() {
  return (
    <ThemeProvider value={appTheme}>
      <HealthProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: Palette.background } }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="trends" />
        </Stack>
      </HealthProvider>
    </ThemeProvider>
  );
}
