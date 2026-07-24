import { Platform } from 'react-native';

let handlerConfigured = false;

async function notificationsModule() {
  if (Platform.OS === 'web') return null;
  return import('expo-notifications');
}

async function configureHandler() {
  if (handlerConfigured) return;
  const Notifications = await notificationsModule();
  if (!Notifications) return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: false,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
  handlerConfigured = true;
}

export async function requestRecoveryNotificationPermission() {
  const Notifications = await notificationsModule();
  if (!Notifications) return false;
  await configureHandler();
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  const requested = await Notifications.requestPermissionsAsync({
    ios: {
      allowAlert: true,
      allowBadge: false,
      allowSound: false,
    },
  });
  return requested.granted;
}

export async function scheduleRecoveryNotification() {
  const Notifications = await notificationsModule();
  if (!Notifications) return null;
  await configureHandler();
  return Notifications.scheduleNotificationAsync({
    content: {
      title: '该休息一下了',
      body: '检测到连续生理趋势变化，建议短暂休息并留意自身感受。',
      data: { url: '/health' },
      sound: false,
    },
    trigger: null,
  });
}

export async function subscribeToRecoveryNotificationResponses(
  listener: (url: string) => void,
) {
  const Notifications = await notificationsModule();
  if (!Notifications) return () => undefined;
  const subscription = Notifications.addNotificationResponseReceivedListener(
    (response) => {
      const url = response.notification.request.content.data?.url;
      if (typeof url === 'string') listener(url);
    },
  );
  return () => subscription.remove();
}

export async function getInitialRecoveryNotificationUrl() {
  const Notifications = await notificationsModule();
  if (!Notifications) return null;
  const response = await Notifications.getLastNotificationResponseAsync();
  const url = response?.notification.request.content.data?.url;
  if (typeof url !== 'string') return null;
  await Notifications.clearLastNotificationResponseAsync();
  return url;
}
