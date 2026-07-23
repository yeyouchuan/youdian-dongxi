import { useEffect, useState } from 'react';
import { Animated, Platform, StyleSheet, View } from 'react-native';

import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { useReduceMotion } from '@/hooks/use-reduce-motion';

function SkeletonLine({
  width,
  height = 12,
}: {
  width: `${number}%` | number;
  height?: number;
}) {
  return <View style={[styles.line, { width, height }]} />;
}

export function ReportSkeleton({
  label = '正在加载坐姿日报',
}: {
  label?: string;
}) {
  const reduceMotion = useReduceMotion();
  const [opacity] = useState(() => new Animated.Value(0.48));

  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(0.72);
      return;
    }
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.82,
          duration: 720,
          useNativeDriver: Platform.OS !== 'web',
        }),
        Animated.timing(opacity, {
          toValue: 0.48,
          duration: 720,
          useNativeDriver: Platform.OS !== 'web',
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity, reduceMotion]);

  return (
    <Animated.View
      accessibilityLabel={label}
      accessibilityRole="progressbar"
      style={[styles.wrap, { opacity }]}>
      <SurfaceCard style={styles.hero}>
        <SkeletonLine width="34%" height={16} />
        <View style={styles.gauge} />
        <SkeletonLine width="44%" height={18} />
        <SkeletonLine width="62%" />
        <View style={styles.metrics}>
          <SkeletonLine width="24%" height={42} />
          <SkeletonLine width="24%" height={42} />
          <SkeletonLine width="24%" height={42} />
        </View>
      </SurfaceCard>
      <SurfaceCard style={styles.detail}>
        <SkeletonLine width="30%" height={18} />
        <SkeletonLine width="92%" />
        <SkeletonLine width="78%" />
        <SkeletonLine width="86%" />
      </SurfaceCard>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 14,
  },
  hero: {
    alignItems: 'center',
    gap: Spacing.md,
  },
  line: {
    borderRadius: Radius.pill,
    backgroundColor: Palette.surfaceMuted,
  },
  gauge: {
    width: 190,
    height: 94,
    borderTopLeftRadius: 96,
    borderTopRightRadius: 96,
    backgroundColor: Palette.surfaceMuted,
    marginTop: Spacing.md,
  },
  metrics: {
    width: '100%',
    flexDirection: 'row',
    justifyContent: 'space-around',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
    paddingTop: Spacing.xl,
    marginTop: Spacing.sm,
  },
  detail: {
    gap: Spacing.lg,
  },
});
