const { withEntitlementsPlist } = require("expo/config-plugins");

/**
 * expo-notifications enables the APNs entitlement by default, even when the
 * app only schedules local notifications. This app does not register for
 * remote push notifications, so keep the native notification module while
 * removing the unused APNs capability from the signed target.
 */
module.exports = function withLocalNotificationsOnly(config) {
  return withEntitlementsPlist(config, (entitlementsConfig) => {
    delete entitlementsConfig.modResults["aps-environment"];
    return entitlementsConfig;
  });
};
