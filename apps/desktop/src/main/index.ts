import { randomBytes } from "node:crypto";
import { join, resolve } from "node:path";

import { app, BrowserWindow, dialog, Notification, shell } from "electron";

import { BackendSupervisor } from "./backend-supervisor.js";
import { loadOrCreateMasterKey } from "./secret-store.js";
import { DesktopNotificationManager } from "./notification-manager.js";
import { FileNotificationStateStore } from "./notification-state-store.js";
import { registerWorkbenchIpc } from "./workbench-ipc.js";
import { UpdateManager } from "./update-manager.js";

const isDevelopment = !app.isPackaged;
let backendSupervisor: BackendSupervisor | null = null;
let updateManager: UpdateManager | null = null;
let notificationManager: DesktopNotificationManager | null = null;

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
      dataRoot: userDataPath,
      baseUrl: process.env.JAP_API_BASE_URL ?? "http://127.0.0.1:8765/api/v1",
      apiToken,
      masterKey,
      databaseUrl: process.env.JAP_DATABASE_URL ?? `sqlite:///${databasePath}`,
      ...(app.isPackaged
        ? {
            backendExecutable: join(
              process.resourcesPath,
              "backend",
              "job-apply-pro-backend.exe",
            ),
            browserEngine: "msedge" as const,
          }
        : { browserEngine: "chromium" as const }),
      ...(process.env.JAP_PYTHON_PATH
        ? { pythonPath: process.env.JAP_PYTHON_PATH }
        : {}),
    });
    updateManager = new UpdateManager(app.isPackaged, app.getVersion());
    notificationManager = new DesktopNotificationManager(
      async () => {
        if (!backendSupervisor || !updateManager) {
          throw new Error("Desktop services are not initialized.");
        }
        const [
          workflows,
          challenges,
          communications,
          followUps,
          calendarEvents,
          backups,
        ] = await Promise.all([
          backendSupervisor.client.listWorkflows(),
          backendSupervisor.client.listChallengeSessions(),
          backendSupervisor.client.listCommunicationRecords(),
          backendSupervisor.client.listFollowUps(),
          backendSupervisor.client.listSyncedCalendarEvents(),
          backendSupervisor.client.listBackups(),
        ]);
        return {
          workflows,
          challenges,
          communications,
          followUps,
          calendarEvents,
          backups,
          updateStatus: updateManager.status,
        };
      },
      new FileNotificationStateStore(
        join(userDataPath, "notification-state.json"),
      ),
      {
        isSupported: () => Notification.isSupported(),
        show: (item, onActivate) => {
          const notification = new Notification({
            title: item.title,
            body: item.body,
            silent: true,
            timeoutType: "default",
          });
          notification.once("click", onActivate);
          notification.show();
        },
      },
      (item) => {
        const window = BrowserWindow.getAllWindows()[0] ?? createMainWindow();
        if (window.isMinimized()) window.restore();
        window.show();
        window.focus();
        const deliver = () =>
          window.webContents.send("notifications:activated", item.destination);
        if (window.webContents.isLoading()) {
          window.webContents.once("did-finish-load", deliver);
        } else {
          deliver();
        }
      },
    );
    await notificationManager.initialize();
    registerWorkbenchIpc(backendSupervisor, updateManager, notificationManager);
    backendSupervisor.onStatus((status) => {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send("workbench:status", status);
      }
      if (status.state === "ready") void notificationManager?.refresh();
    });
    updateManager.onStatus((status) => {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send("updates:status", status);
      }
      void notificationManager?.refresh();
    });
    notificationManager.onStatus((status) => {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send("notifications:status", status);
      }
    });
    createMainWindow();
    void backendSupervisor.start().catch(() => {
      backendSupervisor?.markDegraded(
        "Local backend startup failed. Saved data remains on disk; restart the app to retry.",
      );
    });
    void updateManager.check();

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

app.on("before-quit", () => {
  notificationManager?.stop();
  backendSupervisor?.stop();
});
