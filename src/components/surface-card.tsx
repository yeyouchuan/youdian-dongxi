import { PropsWithChildren } from 'react';
import { Platform, StyleSheet, View, ViewProps } from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';

interface SurfaceCardProps extends PropsWithChildren<ViewProps> {
  muted?: boolean;
}

export function SurfaceCard({
  children,
  style,
  muted = false,
  ...viewProps
}: SurfaceCardProps) {
  return (
    <View
      {...viewProps}
      style={[styles.card, muted && styles.muted, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: Radius.lg,
    backgroundColor: Palette.surface,
    padding: Spacing.xxl,
    ...(Platform.OS === 'web'
      ? { boxShadow: '0 3px 12px rgba(0, 0, 0, 0.055)' }
      : {
          shadowColor: '#000000',
          shadowOpacity: 0.055,
          shadowRadius: 12,
          shadowOffset: { width: 0, height: 3 },
          elevation: 2,
        }),
  },
  muted: {
    backgroundColor: Palette.surfaceRaised,
  },
});
