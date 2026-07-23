#!/usr/bin/env node

const { spawn } = require("node:child_process");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const expoCli = path.join(projectRoot, "node_modules", "expo", "bin", "cli");
const forwardedArgs = process.argv.slice(2);
const child = spawn(
  process.execPath,
  [
    expoCli,
    "start",
    "--dev-client",
    "--scheme",
    "youdiandongxi-dev",
    ...forwardedArgs,
  ],
  {
    cwd: projectRoot,
    env: {
      ...process.env,
      APP_VARIANT: "development",
    },
    stdio: "inherit",
  },
);

child.on("error", (error) => {
  console.error(`无法启动 Expo Development Client: ${error.message}`);
  process.exitCode = 1;
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exitCode = code ?? 1;
});
