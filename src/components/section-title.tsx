import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, Text, View } from 'react-native';

import { Palette, Spacing } from '@/constants/theme';

interface SectionTitleProps {
  eyebrow?: string;
  title: string;
  icon?: keyof typeof Ionicons.glyphMap;
  accent?: string;
}

export function SectionTitle({
  eyebrow,
  title,
  icon,
  accent = Palette.text,
}: SectionTitleProps) {
  return (
    <View style={styles.wrap}>
      {eyebrow ? <Text style={[styles.eyebrow, { color: accent }]}>{eyebrow}</Text> : null}
      <View style={styles.titleRow}>
        {icon ? <Ionicons name={icon} size={18} color={accent} /> : null}
        <Text style={styles.title}>{title}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: Spacing.xs,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  title: {
    color: Palette.text,
    fontSize: 20,
    fontWeight: '800',
    letterSpacing: -0.45,
  },
});
