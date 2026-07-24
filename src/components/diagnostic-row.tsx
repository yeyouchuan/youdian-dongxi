import { StyleSheet, Text, View } from 'react-native';

import { Palette, Spacing } from '@/constants/theme';

interface DiagnosticRowProps {
  label: string;
  value: string;
  tone?: string;
}

export function DiagnosticRow({
  label,
  value,
  tone = Palette.text,
}: DiagnosticRowProps) {
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <Text selectable style={[styles.value, { color: tone }]}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Palette.border,
  },
  label: {
    color: Palette.textMuted,
    fontSize: 11,
    flex: 1,
  },
  value: {
    fontSize: 12,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
    textAlign: 'right',
    maxWidth: '68%',
  },
});
