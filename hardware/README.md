# Hardware

The maintained Galaxea A1Z, G0.5 and SmartCushion work lives under
[`robot-arm/`](robot-arm/).

## Start here

- [`robot-arm/README.md`](robot-arm/README.md): repository map, hardware safety,
  installation and verified runtime status.
- [`robot-arm/a1z-g05-client/README.md`](robot-arm/a1z-g05-client/README.md):
  operational DGX → Mark → A1Z runbook.
- [`robot-arm/docs/g05-a1z-technical-summary.md`](robot-arm/docs/g05-a1z-technical-summary.md):
  G0.5 → A1Z observation, mapping, camera, execution and safety design.
- [`robot-arm/docs/mqtt-cushion-reminder-service-plan.md`](robot-arm/docs/mqtt-cushion-reminder-service-plan.md):
  MQTT firmware contract, continuous-sitting rule, robot intent contract and
  production service phases.
- [`robot-arm/cushion-reminder-service/README.md`](robot-arm/cushion-reminder-service/README.md):
  runnable MQTT simulator and `localhost:3000` scenario trigger console.
- [`robot-arm/docs/openai-action-evaluator-workflow.md`](robot-arm/docs/openai-action-evaluator-workflow.md):
  planned post-action vision evaluation and bounded correction loop.

## Main areas

```text
robot-arm/
├── a1z-g05-client/            # G0.5 client, safe daemon, configs and tests
├── cushion-reminder-service/  # MQTT simulator and local scenario trigger API
├── GALAXEA-A1Z/               # pinned/nested A1Z SDK checkout
├── docs/                      # runbooks, technical decisions and service plans
├── scripts/ + tests/          # guarded macOS hardware runners and regression tests
├── simulation/                # MuJoCo/FK/IK/dynamics tools
├── frontend/cushion-dashboard # SmartCushion report UI
├── recordings/                # teach-and-play trajectories
└── firmware/                  # embedded-device placeholder
```

The arm has no brake lock. Read
[`robot-arm/README.md#mandatory-a1z-safety`](robot-arm/README.md#mandatory-a1z-safety)
before running any command that enables or disables motors.
