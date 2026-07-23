import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';
import { TrendRangeDays } from '@/domain/types';

const OPTIONS: TrendRangeDays[] = [7, 30];

export function TrendRangeControl({
  value,
  onChange,
}: {
  value: TrendRangeDays;
  onChange: (value: TrendRangeDays) => void;
}) {
  return (
    <View accessibilityRole="tablist" style={styles.wrap}>
      {OPTIONS.map((option) => {
        const selected = option === value;
        return (
          <Pressable
            key={option}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            onPress={() => onChange(option)}
            style={({ pressed }) => [
              styles.option,
              selected && styles.optionSelected,
              pressed && styles.pressed,
            ]}>
            <Text style={[styles.text, selected && styles.textSelected]}>
              {option}天
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    padding: 4,
    gap: 4,
    borderRadius: Radius.pill,
    backgroundColor: Palette.surfaceMuted,
  },
  option: {
    minHeight: 44,
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.pill,
    paddingHorizontal: Spacing.lg,
  },
  optionSelected: {
    backgroundColor: Palette.surface,
    ...(Platform.OS === 'web'
      ? { boxShadow: '0 2px 5px rgba(0, 0, 0, 0.08)' }
      : {
          shadowColor: '#000000',
          shadowOpacity: 0.08,
          shadowRadius: 5,
          shadowOffset: { width: 0, height: 2 },
        }),
  },
  text: {
    color: Palette.textMuted,
    fontSize: 14,
    fontWeight: '700',
  },
  textSelected: {
    color: Palette.text,
  },
  pressed: {
    opacity: 0.68,
  },
});
