import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => void>(),
  windows: [] as {
    show: () => void;
    focus: () => void;
    isMinimized: () => boolean;
    restore: () => void;
  }[],
  lock: true,
  appQuit: vi.fn(),
  key: vi.fn(async () => "synthetic-key"),
  createSupervisor: vi.fn(),
  shutdown: vi.fn<() => Promise<void>>(async () => undefined),
  prepareUpdate: vi.fn<() => Promise<void>>(async () => undefined),
  start: vi.fn(async () => undefined),
  notificationStop: vi.fn(),
  errorBox: vi.fn(),
  installGate: undefined as (() => Promise<void>) | undefined,
}));

vi.mock("electron", () => ({
  app: {
    isPackaged: false,
    requestSingleInstanceLock: () => mocks.lock,
    quit: mocks.appQuit,
    whenReady: async () => undefined,
    isReady: () => true,
    getPath: () => "C:/synthetic/workspace",
    getVersion: () => "0.54.0-alpha.1",
    setAppUserModelId: vi.fn(),
    on: (event: string, handler: (...args: unknown[]) => void) =>
      mocks.handlers.set(event, handler),
  },
  BrowserWindow: class {
    constructor() {
      mocks.windows.push(this);
    }
    static getAllWindows() {
      return mocks.windows;
    }
    show = vi.fn();
    focus = vi.fn();
    restore = vi.fn();
    isMinimized = () => false;
    once = vi.fn();
    loadFile = vi.fn(async () => undefined);
    loadURL = vi.fn(async () => undefined);
    webContents = { on: vi.fn(), setWindowOpenHandler: vi.fn(), send: vi.fn() };
  },
  dialog: { showErrorBox: mocks.errorBox },
  Notification: class {
    static isSupported() {
      return false;
    }
  },
  shell: { openExternal: vi.fn() },
}));
vi.mock("./backend-supervisor.js", () => ({
  BackendSupervisor: class {
    constructor() {
      mocks.createSupervisor();
    }
    shutdown = mocks.shutdown;
    prepareUpdate = mocks.prepareUpdate;
    start = mocks.start;
    onStatus = vi.fn();
    status = {
      state: "degraded",
      message: "Synthetic restore is still writing; keep the app open.",
    };
    client = {};
  },
}));
vi.mock("./secret-store.js", () => ({ loadOrCreateMasterKey: mocks.key }));
vi.mock("./notification-manager.js", () => ({
  DesktopNotificationManager: class {
    initialize = async () => undefined;
    stop = mocks.notificationStop;
    onStatus = vi.fn();
    refresh = async () => undefined;
  },
}));
vi.mock("./notification-state-store.js", () => ({
  FileNotificationStateStore: class {},
}));
vi.mock("./workbench-ipc.js", () => ({ registerWorkbenchIpc: vi.fn() }));
vi.mock("./update-manager.js", () => ({
  UpdateManager: class {
    constructor(
      _packaged: boolean,
      _version: string,
      beforeInstall: () => Promise<void>,
    ) {
      mocks.installGate = beforeInstall;
    }
    check = async () => undefined;
    onStatus = vi.fn();
  },
}));

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
}

describe("desktop terminal lifecycle callers", () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.handlers.clear();
    mocks.windows.length = 0;
    mocks.lock = true;
    mocks.installGate = undefined;
    vi.clearAllMocks();
    mocks.key.mockImplementation(async () => "synthetic-key");
    mocks.shutdown.mockImplementation(async () => undefined);
    mocks.prepareUpdate.mockImplementation(async () => undefined);
    vi.stubGlobal("__dirname", "C:/synthetic/out/main");
    vi.stubEnv("JAP_MASTER_KEY", "");
    // Empty is an explicit override, so remove it for key-initialization tests.
    delete process.env.JAP_MASTER_KEY;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("acquires single-instance ownership before any key or backend initialization", async () => {
    mocks.lock = false;
    await import("./index.js");
    await settle();
    expect(mocks.appQuit).toHaveBeenCalledOnce();
    expect(mocks.key).not.toHaveBeenCalled();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
  });

  it("awaits shutdown proof with reentrant before-quit protection", async () => {
    let confirm!: () => void;
    mocks.shutdown.mockImplementation(
      () =>
        new Promise((resolve) => {
          confirm = resolve;
        }),
    );
    await import("./index.js");
    await settle();
    expect(mocks.createSupervisor).toHaveBeenCalledOnce();
    const quit = mocks.handlers.get("before-quit")!;
    const first = { preventDefault: vi.fn() };
    const second = { preventDefault: vi.fn() };
    quit(first);
    quit(second);
    expect(first.preventDefault).toHaveBeenCalledOnce();
    expect(second.preventDefault).toHaveBeenCalledOnce();
    expect(mocks.shutdown).toHaveBeenCalledOnce();
    expect(mocks.appQuit).not.toHaveBeenCalled();
    confirm();
    await settle();
    expect(mocks.appQuit).toHaveBeenCalledOnce();
    const authorized = { preventDefault: vi.fn() };
    quit(authorized);
    expect(authorized.preventDefault).not.toHaveBeenCalled();
  });

  it("keeps a visible window and explains recovery when shutdown is refused", async () => {
    mocks.shutdown.mockRejectedValue(new Error("private process command"));
    await import("./index.js");
    await settle();
    mocks.windows.length = 0;
    mocks.handlers.get("before-quit")!({ preventDefault: vi.fn() });
    await settle();
    expect(mocks.appQuit).not.toHaveBeenCalled();
    expect(mocks.windows).toHaveLength(1);
    expect(mocks.windows[0]!.show).toHaveBeenCalled();
    expect(mocks.windows[0]!.focus).toHaveBeenCalled();
    expect(mocks.errorBox).toHaveBeenCalledExactlyOnceWith(
      "Job Apply Pro must remain open",
      "Synthetic restore is still writing; keep the app open.",
    );
    expect(JSON.stringify(mocks.errorBox.mock.calls)).not.toContain("private");
  });

  it("cannot start a backend after quit while key initialization was in flight", async () => {
    let keyReady!: (value: string) => void;
    mocks.key.mockImplementation(
      () =>
        new Promise((resolve) => {
          keyReady = resolve;
        }),
    );
    await import("./index.js");
    await settle();
    expect(mocks.key).toHaveBeenCalledOnce();
    mocks.handlers.get("before-quit")!({ preventDefault: vi.fn() });
    await settle();
    keyReady("synthetic-key");
    await settle();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
    expect(mocks.start).not.toHaveBeenCalled();
  });

  it("update uses its restore-aware preparation without preauthorizing future quit", async () => {
    await import("./index.js");
    await settle();
    await mocks.installGate!();
    expect(mocks.prepareUpdate).toHaveBeenCalledOnce();
    expect(mocks.shutdown).not.toHaveBeenCalled();
    const quit = { preventDefault: vi.fn() };
    mocks.handlers.get("before-quit")!(quit);
    expect(quit.preventDefault).toHaveBeenCalledOnce();
    expect(mocks.shutdown).toHaveBeenCalledOnce();
    await settle();
  });
});
