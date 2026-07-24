import * as Haptics from 'expo-haptics';
import { useCallback, useRef } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';

import HealthStickerDom from '@/components/health-sticker-dom';
import { SurfaceCard } from '@/components/surface-card';
import { Palette, Radius, Spacing } from '@/constants/theme';
import {
  formatChineseMonthDay,
  todayISODate,
} from '@/domain/date-utils';
import { HealthStickerPresentation } from '@/domain/types';

const HEALTH_PINK = '#FF2D55';

interface HealthStickerCardProps {
  presentation: HealthStickerPresentation;
  reduceMotion: boolean;
}

export function HealthStickerCard({
  presentation,
  reduceMotion,
}: HealthStickerCardProps) {
  const lastRevealedId = useRef<string | null>(null);
  const title =
    presentation.date === todayISODate()
      ? '今日健康贴纸'
      : `${formatChineseMonthDay(presentation.date)}健康贴纸`;
  const subtitle = reduceMotion
    ? '已展开达成依据与保持建议'
    : '拖动贴纸边缘，查看达成依据';

  const onReveal = useCallback(
    async (id: string) => {
      if (id !== presentation.id || lastRevealedId.current === id) return;
      lastRevealedId.current = id;

      if (Platform.OS === 'ios') {
        await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Soft);
      }
    },
    [presentation.id],
  );

  return (
    <SurfaceCard
      accessibilityLabel={`${title}，${presentation.title}`}
      testID="health-sticker-card">
      <View style={styles.metaRow}>
        <View style={styles.metaItem}>
          <View style={styles.healthDot} />
          <Text style={styles.healthLabel}>健康亮点</Text>
        </View>
        <View style={styles.metaItem}>
          <View style={styles.sourceDot} />
          <Text style={styles.sourceLabel}>智能坐垫记录</Text>
        </View>
      </View>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
      <View style={styles.stage}>
        <HealthStickerDom
          key={`${presentation.id}:${reduceMotion}`}
          presentation={presentation}
          reduceMotion={reduceMotion}
          onReveal={onReveal}
          dom={{
            scrollEnabled: false,
            style: styles.dom,
          }}
        />
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.md,
  },
  metaItem: {
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  healthDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: HEALTH_PINK,
  },
  sourceDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: Palette.teal,
  },
  healthLabel: {
    color: HEALTH_PINK,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.1,
  },
  sourceLabel: {
    flexShrink: 1,
    color: Palette.textMuted,
    fontSize: 11,
    fontWeight: '600',
    textAlign: 'right',
  },
  title: {
    marginTop: Spacing.md,
    color: Palette.text,
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: -0.55,
  },
  subtitle: {
    marginTop: 5,
    color: Palette.textMuted,
    fontSize: 12,
    fontWeight: '500',
    lineHeight: 17,
  },
  stage: {
    height: 248,
    marginTop: Spacing.xl,
    borderRadius: Radius.md,
    overflow: 'hidden',
    backgroundColor: Palette.background,
  },
  dom: {
    height: 248,
    backgroundColor: 'transparent',
  },
});
