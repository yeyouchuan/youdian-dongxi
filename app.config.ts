import type { ConfigContext, ExpoConfig } from "expo/config";

const DEVELOPMENT_VARIANT = "development";
const PRODUCTION_NAME = "有垫东西";
const DEVELOPMENT_NAME = `${PRODUCTION_NAME} Dev`;
const PRODUCTION_BUNDLE_IDENTIFIER = "com.yeyou.youdiandongxi";
const DEVELOPMENT_BUNDLE_IDENTIFIER = `${PRODUCTION_BUNDLE_IDENTIFIER}.dev`;
const PRODUCTION_SCHEME = "youdiandongxi";
const DEVELOPMENT_SCHEME = `${PRODUCTION_SCHEME}-dev`;

export default ({ config }: ConfigContext): ExpoConfig => {
  const isDevelopment = process.env.APP_VARIANT === DEVELOPMENT_VARIANT;
  const configuredTransportSecurity =
    (config.ios?.infoPlist?.NSAppTransportSecurity as
      | Record<string, unknown>
      | undefined) ?? {};
  const developmentPlugins: NonNullable<ExpoConfig["plugins"]> =
    isDevelopment
      ? [
          [
            "expo-dev-client",
            {
              addGeneratedScheme: true,
            },
          ],
        ]
      : [];

  return {
    ...config,
    slug: config.slug ?? "youdian-dongxi",
    name: isDevelopment ? DEVELOPMENT_NAME : PRODUCTION_NAME,
    scheme: isDevelopment ? DEVELOPMENT_SCHEME : PRODUCTION_SCHEME,
    plugins: [
      ...(config.plugins ?? []),
      ...developmentPlugins,
    ],
    ios: {
      ...config.ios,
      bundleIdentifier: isDevelopment
        ? DEVELOPMENT_BUNDLE_IDENTIFIER
        : PRODUCTION_BUNDLE_IDENTIFIER,
      infoPlist: {
        ...config.ios?.infoPlist,
        NSLocalNetworkUsageDescription:
          "有垫东西需要连接同一 Wi-Fi 下的智能坐垫数据广播站，以接收姿态、心率和呼吸数据。",
        NSAppTransportSecurity: {
          ...configuredTransportSecurity,
          NSAllowsLocalNetworking: true,
          ...(isDevelopment ? { NSAllowsArbitraryLoads: true } : {}),
        },
      },
    },
  };
};
