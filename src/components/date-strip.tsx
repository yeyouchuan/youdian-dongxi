import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';
import {
  Animated,
  Easing,
  type LayoutChangeEvent,
  PanResponder,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

import {
  MaxContentWidth,
  Palette,
  Radius,
  Spacing,
} from '@/constants/theme';
import { useReduceMotion } from '@/hooks/use-reduce-motion';

const DATES_PER_WEEK = 7;
const SWIPE_ACTIVATION_DISTANCE = 8;
const SWIPE_COMMIT_DISTANCE = 44;
const SWIPE_COMMIT_VELOCITY = 0.45;
const ITEM_GAP = 3;
const SETTLE_DURATION = 220;
const SETTLE_EASING = Easing.bezier(0.25, 1, 0.5, 1);

export type DateSwipeDirection = 'previous' | 'next';

export function resolveDateSwipe({
  dx,
  dy,
  vx,
  canSwipeNext = true,
  canSwipePrevious = true,
}: {
  dx: number;
  dy: number;
  vx: number;
  canSwipeNext?: boolean;
  canSwipePrevious?: boolean;
}): DateSwipeDirection | null {
  const horizontalDistance = Math.abs(dx);
  const horizontalVelocity = Math.abs(vx);
  const isHorizontal = horizontalDistance > Math.abs(dy) * 1.2;
  const crossedThreshold =
    horizontalDistance >= SWIPE_COMMIT_DISTANCE ||
    horizontalVelocity >= SWIPE_COMMIT_VELOCITY;

  if (!isHorizontal || !crossedThreshold) return null;
  if (dx < 0 && canSwipeNext) return 'next';
  if (dx > 0 && canSwipePrevious) return 'previous';
  return null;
}

export interface DateItem {
  date: string;
  day: string;
  weekday: string;
  hasCushionData?: boolean;
}

interface DateStripProps {
  dates: DateItem[];
  selectedDate: string;
  onSelect: (date: string) => void;
}

export function DateStrip({
  dates,
  selectedDate,
  onSelect,
}: DateStripProps) {
  const reduceMotion = useReduceMotion();
  const { width: windowWidth } = useWindowDimensions();
  const initialWidth = Math.max(
    1,
    Math.min(windowWidth, MaxContentWidth) - Spacing.xl * 2,
  );
  const [containerWidth, setContainerWidth] = useState(initialWidth);
  const itemWidth = containerWidth / DATES_PER_WEEK;
  const selectedIndex = Math.max(
    0,
    dates.findIndex((item) => item.date === selectedDate),
  );
  const selectedSlot = selectedIndex % DATES_PER_WEEK;
  const currentPageIndex = Math.floor(selectedIndex / DATES_PER_WEEK);
  const pageCount = Math.ceil(dates.length / DATES_PER_WEEK);
  const baseOffset = -currentPageIndex * containerWidth;
  const [trackOffset] = useState(
    () =>
      new Animated.Value(
        -Math.floor(selectedIndex / DATES_PER_WEEK) * initialWidth,
      ),
  );
  const [indicatorOffset] = useState(
    () =>
      new Animated.Value(
        (selectedIndex % DATES_PER_WEEK) *
          (initialWidth / DATES_PER_WEEK),
      ),
  );
  const [transitioning, setTransitioning] = useState(false);

  useLayoutEffect(() => {
    trackOffset.setValue(baseOffset);
  }, [baseOffset, selectedDate, trackOffset]);

  useLayoutEffect(() => {
    Animated.timing(indicatorOffset, {
      toValue: selectedSlot * itemWidth,
      duration: reduceMotion ? 0 : 180,
      easing: SETTLE_EASING,
      useNativeDriver: true,
    }).start();
  }, [indicatorOffset, itemWidth, reduceMotion, selectedSlot]);

  const resetTrack = useCallback(() => {
    Animated.timing(trackOffset, {
      toValue: baseOffset,
      duration: reduceMotion ? 0 : 160,
      easing: SETTLE_EASING,
      useNativeDriver: true,
    }).start();
  }, [baseOffset, reduceMotion, trackOffset]);

  const settleWeek = useCallback(
    (direction: DateSwipeDirection | null) => {
      if (!direction || transitioning) {
        resetTrack();
        return;
      }

      const indexDelta =
        direction === 'next' ? DATES_PER_WEEK : -DATES_PER_WEEK;
      const targetDate = dates[selectedIndex + indexDelta]?.date;
      if (!targetDate) {
        resetTrack();
        return;
      }

      if (reduceMotion) {
        trackOffset.setValue(baseOffset);
        onSelect(targetDate);
        return;
      }

      setTransitioning(true);
      Animated.timing(trackOffset, {
        toValue:
          baseOffset +
          (direction === 'next' ? -containerWidth : containerWidth),
        duration: SETTLE_DURATION,
        easing: SETTLE_EASING,
        useNativeDriver: true,
      }).start(({ finished }) => {
        setTransitioning(false);
        if (!finished) {
          resetTrack();
          return;
        }
        onSelect(targetDate);
      });
    },
    [
      baseOffset,
      containerWidth,
      dates,
      onSelect,
      reduceMotion,
      resetTrack,
      selectedIndex,
      trackOffset,
      transitioning,
    ],
  );

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => false,
        onMoveShouldSetPanResponder: (_, gesture) => {
          const horizontalDistance = Math.abs(gesture.dx);
          return (
            !transitioning &&
            horizontalDistance >= SWIPE_ACTIVATION_DISTANCE &&
            horizontalDistance > Math.abs(gesture.dy) * 1.25
          );
        },
        onPanResponderGrant: () => {
          trackOffset.stopAnimation();
          trackOffset.setValue(baseOffset);
        },
        onPanResponderMove: (_, gesture) => {
          if (reduceMotion) return;
          const clampedDrag = Math.max(
            -containerWidth,
            Math.min(containerWidth, gesture.dx),
          );
          trackOffset.setValue(baseOffset + clampedDrag);
        },
        onPanResponderRelease: (_, gesture) => {
          settleWeek(
            resolveDateSwipe({
              dx: gesture.dx,
              dy: gesture.dy,
              vx: gesture.vx,
              canSwipeNext:
                selectedIndex + DATES_PER_WEEK < dates.length,
              canSwipePrevious:
                selectedIndex - DATES_PER_WEEK >= 0,
            }),
          );
        },
        onPanResponderTerminate: resetTrack,
        onPanResponderTerminationRequest: () => false,
      }),
    [
      baseOffset,
      containerWidth,
      dates.length,
      reduceMotion,
      resetTrack,
      selectedIndex,
      settleWeek,
      trackOffset,
      transitioning,
    ],
  );

  const handleLayout = (event: LayoutChangeEvent) => {
    const nextWidth = event.nativeEvent.layout.width;
    if (
      nextWidth > 0 &&
      Math.abs(nextWidth - containerWidth) > 0.5
    ) {
      setContainerWidth(nextWidth);
    }
  };

  return (
    <View
      testID="date-strip-swipe-area"
      onLayout={handleLayout}
      {...panResponder.panHandlers}
      style={styles.viewport}>
      <Animated.View
        testID="date-strip-track"
        style={[
          styles.track,
          {
            width: itemWidth * dates.length,
            transform: [{ translateX: trackOffset }],
          },
        ]}>
        {Array.from({ length: pageCount }, (_, pageIndex) => (
          <Animated.View
            key={`selection-${pageIndex}`}
            testID="date-selection-pill"
            pointerEvents="none"
            style={[
              styles.selectionPill,
              {
                left: pageIndex * containerWidth + ITEM_GAP / 2,
                width: Math.max(44, itemWidth - ITEM_GAP),
                transform: [{ translateX: indicatorOffset }],
              },
            ]}
          />
        ))}
        {dates.map((item, index) => {
          const selected = item.date === selectedDate;
          const selectedWeekday =
            index % DATES_PER_WEEK === selectedSlot;
          const visible =
            Math.floor(index / DATES_PER_WEEK) === currentPageIndex;
          return (
            <View
              key={item.date}
              style={[styles.slot, { width: itemWidth }]}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${item.date}，${item.hasCushionData ? '有坐垫数据' : '无坐垫数据'}`}
                accessibilityHint={
                  selected
                    ? '左右滑动可切换前后周'
                    : '双击选择这一天'
                }
                accessibilityState={{ selected }}
                accessibilityElementsHidden={!visible}
                importantForAccessibility={
                  visible ? 'auto' : 'no-hide-descendants'
                }
                onPress={() => {
                  if (visible && !transitioning) onSelect(item.date);
                }}
                style={({ pressed }) => [
                  styles.item,
                  { width: Math.max(44, itemWidth - ITEM_GAP) },
                  pressed && styles.itemPressed,
                ]}>
                <Text
                  style={[
                    styles.weekday,
                    selectedWeekday && styles.textSelected,
                  ]}>
                  {item.weekday}
                </Text>
                <Text
                  style={[
                    styles.day,
                    selectedWeekday && styles.textSelected,
                  ]}>
                  {item.day}
                </Text>
                <View
                  style={[
                    styles.dot,
                    item.hasCushionData
                      ? styles.dotActive
                      : styles.dotMuted,
                    selectedWeekday && styles.dotSelected,
                  ]}
                />
              </Pressable>
            </View>
          );
        })}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  viewport: {
    minHeight: 68,
    overflow: 'hidden',
  },
  track: {
    zIndex: 1,
    flexDirection: 'row',
    minHeight: 68,
  },
  slot: {
    zIndex: 1,
    minHeight: 68,
    alignItems: 'center',
  },
  selectionPill: {
    position: 'absolute',
    zIndex: 0,
    top: 0,
    minHeight: 68,
    borderRadius: Radius.pill,
    backgroundColor: Palette.red,
    ...(Platform.OS === 'web'
      ? { boxShadow: '0 3px 7px rgba(255, 55, 95, 0.22)' }
      : {
          shadowColor: Palette.red,
          shadowOpacity: 0.22,
          shadowRadius: 7,
          shadowOffset: { width: 0, height: 3 },
        }),
  },
  item: {
    minWidth: 44,
    minHeight: 68,
    borderRadius: Radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
  },
  itemPressed: {
    opacity: 0.72,
  },
  weekday: {
    color: Palette.textMuted,
    fontSize: 12,
    fontWeight: '600',
  },
  day: {
    color: Palette.textSecondary,
    fontSize: 16,
    fontWeight: '700',
  },
  textSelected: {
    color: '#FFFFFF',
  },
  dot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    marginTop: 2,
  },
  dotActive: {
    backgroundColor: Palette.red,
  },
  dotMuted: {
    backgroundColor: 'transparent',
  },
  dotSelected: {
    backgroundColor: '#FFFFFF',
  },
});
