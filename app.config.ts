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

  return {
    ...config,
    slug: config.slug ?? "youdian-dongxi",
    name: isDevelopment ? DEVELOPMENT_NAME : PRODUCTION_NAME,
    scheme: isDevelopment ? DEVELOPMENT_SCHEME : PRODUCTION_SCHEME,
    plugins: [
      ...(config.plugins ?? []),
      [
        "expo-dev-client",
        {
          addGeneratedScheme: isDevelopment,
        },
      ],
    ],
    ios: {
      ...config.ios,
      bundleIdentifier: isDevelopment
        ? DEVELOPMENT_BUNDLE_IDENTIFIER
        : PRODUCTION_BUNDLE_IDENTIFIER,
      infoPlist: {
        ...config.ios?.infoPlist,
        ...(isDevelopment
          ? {
              NSAppTransportSecurity: {
                NSAllowsArbitraryLoads: true,
              },
            }
          : {}),
      },
    },
  };
};
