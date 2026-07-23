import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { Platform, StyleSheet } from 'react-native';

import { Palette } from '@/constants/theme';

function IOSNativeTabLayout() {
  return (
    <NativeTabs
      blurEffect="systemDefault"
      minimizeBehavior="automatic"
      tintColor={Palette.red}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'doc.text', selected: 'doc.text.fill' }}
        />
        <NativeTabs.Trigger.Label>日报</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="health">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'heart', selected: 'heart.fill' }}
        />
        <NativeTabs.Trigger.Label>健康</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="settings">
        <NativeTabs.Trigger.Icon
          sf={{ default: 'gearshape', selected: 'gearshape.fill' }}
        />
        <NativeTabs.Trigger.Label>设置</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}

function FallbackTabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: Palette.background },
        tabBarActiveTintColor: Palette.red,
        tabBarInactiveTintColor: Palette.textMuted,
        tabBarShowLabel: true,
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '700',
          paddingBottom: Platform.OS === 'android' ? 3 : 0,
        },
        tabBarIconStyle: { marginTop: 2 },
        tabBarItemStyle: {
          borderRadius: 24,
          marginVertical: 6,
          marginHorizontal: 4,
          overflow: 'hidden',
        },
        tabBarActiveBackgroundColor: Palette.surfaceMuted,
        tabBarStyle: {
          position: 'absolute',
          left: 22,
          right: 22,
          bottom: 12,
          height: 68,
          paddingHorizontal: 6,
          borderRadius: 34,
          backgroundColor: 'rgba(248,248,250,0.78)',
          borderTopWidth: 0,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: 'rgba(255,255,255,0.72)',
          ...(Platform.OS === 'web'
            ? { boxShadow: '0 8px 28px rgba(44, 44, 52, 0.16)' }
            : {
                shadowColor: '#000000',
                shadowOpacity: 0.14,
                shadowRadius: 20,
                shadowOffset: { width: 0, height: 8 },
                elevation: 8,
              }),
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: '日报',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="document-text-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="health"
        options={{
          title: '健康',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="heart-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: '设置',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="settings-outline" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}

export default function TabLayout() {
  return Platform.OS === 'ios' ? <IOSNativeTabLayout /> : <FallbackTabLayout />;
}
