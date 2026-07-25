# Firmware and embedded modules

Reserved for ESP32, sensor, and other embedded modules that belong to this
robot-arm system.

Each future module must document its board, pinout, power domain, build/flash
command, message schema, watchdog behavior, and safe failure state. Embedded
telemetry must never bypass the host-side A1Z motion and shutdown gates.
