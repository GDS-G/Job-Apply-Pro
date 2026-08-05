import { randomBytes } from "node:crypto";
import { join, resolve } from "node:path";

import { app, BrowserWindow, dialog, shell } from "electron";

import { BackendSupervisor } from "./backend-supervisor.js";
import { loadOrCreateMasterKey } from "./secret-store.js";
import { registerWorkbenchIpc } from "./workbench-ipc.js";

const isDevelopment = !app.isPackaged;
let backendSupervisor: BackendSupervisor | null = null;

function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    backgroundColor: "#f5f7fb",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#10182d",
      symbolColor: "#dbe5ff",
      height: 42,
    },
    webPreferences: {
      preload: join(__dirname, "../preload/index.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  window.once("ready-to-show", () => window.show());

  window.webContents.on("preload-error", (_event, preloadPath, error) => {
    console.error(`Desktop preload failed at ${preloadPath}:`, error);
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) {
      void shell.openExternal(url);
    }
    return { action: "deny" };
  });

  window.webContents.on("will-navigate", (event, url) => {
    const rendererOrigin = process.env.ELECTRON_RENDERER_URL;
    if (!rendererOrigin || !url.startsWith(rendererOrigin)) {
      event.preventDefault();
    }
  });

  if (isDevelopment && process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }

  return window;
}

app
  .whenReady()
  .then(async () => {
    app.setAppUserModelId("com.jobapplypro.desktop");
    const projectRoot =
      process.env.JAP_PROJECT_ROOT ??
      (isDevelopment
        ? resolve(__dirname, "../../../..")
        : process.resourcesPath);
    const apiToken =
      process.env.JAP_API_TOKEN ?? randomBytes(32).toString("base64url");
    const userDataPath = app.getPath("userData");
    const masterKey =
      process.env.JAP_MASTER_KEY ??
      (await loadOrCreateMasterKey(
        join(userDataPath, "secrets", "master-key.bin"),
      ));
    const databasePath = join(userDataPath, "job-apply-pro.db").replaceAll(
      "\\",
      "/",
    );
    backendSupervisor = new BackendSupervisor({
      projectRoot,
      baseUrl: process.env.JAP_API_BASE_URL ?? "http://127.0.0.1:8765/api/v1",
      apiToken,
      masterKey,
      databaseUrl: process.env.JAP_DATABASE_URL ?? `sqlite:///${databasePath}`,
      ...(process.env.JAP_PYTHON_PATH
        ? { pythonPath: process.env.JAP_PYTHON_PATH }
        : {}),
    });
    registerWorkbenchIpc(backendSupervisor);
    backendSupervisor.onStatus((status) => {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send("workbench:status", status);
      }
    });
    createMainWindow();
    void backendSupervisor.start().catch(() => {
      backendSupervisor?.markDegraded(
        "Local backend startup failed. Saved data remains on disk; restart the app to retry.",
      );
    });

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  })
  .catch(() => {
    dialog.showErrorBox(
      "Job Apply Pro could not start",
      "The encrypted local workspace could not be initialized. No data was changed.",
    );
    app.quit();
  });

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => backendSupervisor?.stop());
