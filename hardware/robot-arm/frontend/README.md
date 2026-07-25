# Frontend

Web applications belonging to the robot-arm demonstration live here.

- [`cushion-dashboard/`](cushion-dashboard/): SmartCushion report UI and
  showcase assets.

Frontend code cannot directly command the arm. Any future web-to-robot bridge
must go through an authenticated backend and the same joint, speed, workspace,
timeout, and operator-enable gates used by the local runners.
