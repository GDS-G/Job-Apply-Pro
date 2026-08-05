import { join } from "node:path";

import { app, BrowserWindow, shell } from "electron";

const isDevelopment = !app.isPackaged;

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
      preload: join(__dirname, "../preload/index.mjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  window.once("ready-to-show", () => window.show());

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

app.whenReady().then(() => {
  app.setAppUserModelId("com.jobapplypro.desktop");
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
