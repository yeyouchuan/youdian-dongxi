import { PropsWithChildren, ReactNode } from 'react';
import {
  RefreshControl,
  Platform,
  ScrollView,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { MaxContentWidth, Palette, Spacing } from '@/constants/theme';

const DEFAULT_BOTTOM_PADDING = Platform.OS === 'ios' ? 36 : 118;

interface AppScreenProps extends PropsWithChildren {
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
  footer?: ReactNode;
  bottomPadding?: number;
}

export function AppScreen({
  children,
  refreshing = false,
  onRefresh,
  contentStyle,
  footer,
  bottomPadding = DEFAULT_BOTTOM_PADDING,
}: AppScreenProps) {
  return (
    <SafeAreaView collapsable={false} style={styles.safeArea} edges={['top']}>
      <ScrollView
        style={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={Palette.teal}
            />
          ) : undefined
        }
        contentContainerStyle={[
          styles.scrollContent,
          { paddingBottom: bottomPadding },
        ]}>
        <View style={[styles.content, contentStyle]}>{children}</View>
        {footer}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Palette.background,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    alignItems: 'center',
  },
  content: {
    width: '100%',
    maxWidth: MaxContentWidth,
    paddingHorizontal: Spacing.xl,
    gap: 14,
  },
});
