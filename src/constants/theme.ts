import { Platform } from 'react-native';

export const Palette = {
  background: '#F2F2F7',
  surface: '#FFFFFF',
  surfaceRaised: '#F7F7FA',
  surfaceMuted: '#E9E9EE',
  text: '#000000',
  textSecondary: '#3C3C43',
  textMuted: '#8E8E93',
  border: '#E5E5EA',
  teal: '#00C7BE',
  emerald: '#34C759',
  sky: '#007AFF',
  amber: '#FF9F0A',
  red: '#FF375F',
  purple: '#AF52DE',
} as const;

export const Fonts = Platform.select({
  ios: {
    sans: 'system-ui',
    serif: 'ui-serif',
    rounded: 'ui-rounded',
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-display)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
});

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
} as const;

export const Radius = {
  sm: 12,
  md: 18,
  lg: 24,
  pill: 999,
} as const;

export const MaxContentWidth = 560;
