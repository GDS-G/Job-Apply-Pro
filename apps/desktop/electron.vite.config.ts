import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { sourcemap: true },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    // Electron sandboxed preload scripts must use CommonJS. The desktop
    // package is ESM, so make the format and extension explicit instead of
    // allowing electron-vite to emit an unloadable `.mjs` preload.
    build: {
      sourcemap: true,
      rollupOptions: {
        external: ["electron"],
        output: {
          entryFileNames: "index.cjs",
          format: "cjs",
        },
      },
    },
  },
  renderer: {
    resolve: {
      alias: {
        "@renderer": resolve("src/renderer/src"),
      },
    },
    plugins: [react()],
    build: { sourcemap: true },
  },
});
