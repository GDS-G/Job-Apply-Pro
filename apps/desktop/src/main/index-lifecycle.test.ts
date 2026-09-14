import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  RestoreAdmissionError,
  RESTORE_ADMISSION_MESSAGE,
  MissingMasterKeyError,
  MISSING_MASTER_KEY_MESSAGE,
} from "./restore-admission.js";

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => void>(),
  windows: [] as {
    show: () => void;
    focus: () => void;
    isMinimized: () => boolean;
    restore: () => void;
  }[],
  lock: true,
  packaged: false,
  appQuit: vi.fn(),
  key: vi.fn(async () => "synthetic-key"),
  createSupervisor: vi.fn(),
  shutdown: vi.fn<() => Promise<void>>(async () => undefined),
  prepareUpdate: vi.fn<() => Promise<void>>(async () => undefined),
  start: vi.fn(async () => undefined),
  notificationStop: vi.fn(),
  errorBox: vi.fn(),
  admission: vi.fn<() => void>(),
  recovery: vi.fn(async () => "cancelled" as const),
  installGate: undefined as (() => Promise<void>) | undefined,
}));

vi.mock("electron", () => ({
  app: {
    get isPackaged() {
      return mocks.packaged;
    },
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
    constructor(options: unknown) {
      mocks.createSupervisor(options);
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
vi.mock("./restore-recovery-controller.js", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("./restore-recovery-controller.js")>();
  return { ...actual, runInstalledRestoreRecovery: mocks.recovery };
});
vi.mock("./restore-admission.js", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("./restore-admission.js")>();
  return { ...actual, assertRestoreAdmission: mocks.admission };
});
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
    mocks.packaged = false;
    mocks.installGate = undefined;
    vi.clearAllMocks();
    mocks.key.mockImplementation(async () => "synthetic-key");
    mocks.shutdown.mockImplementation(async () => undefined);
    mocks.prepareUpdate.mockImplementation(async () => undefined);
    mocks.admission.mockImplementation(() => undefined);
    mocks.recovery.mockImplementation(async () => "cancelled");
    vi.stubGlobal("__dirname", "C:/synthetic/out/main");
    vi.stubEnv("JAP_MASTER_KEY", "");
    // Empty is an explicit override, so remove it for key-initialization tests.
    delete process.env.JAP_MASTER_KEY;
  });
  afterEach(() => {
    Reflect.deleteProperty(process, "resourcesPath");
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
    expect(mocks.admission).not.toHaveBeenCalled();
  });

  it("shows static lost-key preservation guidance and quits before opening backend services", async () => {
    mocks.key.mockRejectedValue(new MissingMasterKeyError());
    await import("./index.js");
    await settle();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
    expect(mocks.start).not.toHaveBeenCalled();
    expect(mocks.errorBox).toHaveBeenCalledExactlyOnceWith(
      "Job Apply Pro — encryption key recovery required",
      MISSING_MASTER_KEY_MESSAGE,
    );
    expect(mocks.appQuit).toHaveBeenCalledOnce();
    expect(mocks.windows).toHaveLength(0);
  });

  it.each([false, true])(
    "shows recovery guidance before key or backend initialization (key override=%s)",
    async (override) => {
      if (override) vi.stubEnv("JAP_MASTER_KEY", "synthetic override");
      mocks.admission.mockImplementation(() => {
        throw new RestoreAdmissionError();
      });
      await import("./index.js");
      await settle();
      expect(mocks.key).not.toHaveBeenCalled();
      expect(mocks.createSupervisor).not.toHaveBeenCalled();
      expect(mocks.start).not.toHaveBeenCalled();
      expect(mocks.windows).toHaveLength(0);
      expect(mocks.errorBox).toHaveBeenCalledExactlyOnceWith(
        "Job Apply Pro — restore recovery required",
        RESTORE_ADMISSION_MESSAGE,
      );
      expect(mocks.appQuit).toHaveBeenCalledOnce();
      expect(mocks.installGate).toBeUndefined();
    },
  );

  it("enters packaged recovery-only startup without constructing normal services", async () => {
    mocks.packaged = true;
    Object.defineProperty(process, "resourcesPath", {
      configurable: true,
      value: "C:/synthetic/resources",
    });
    vi.stubEnv("JAP_PROJECT_ROOT", "D:/untrusted-project-override");
    vi.stubEnv(
      "JAP_DATABASE_URL",
      "sqlite:///D:/untrusted-database-override.db",
    );
    mocks.admission.mockImplementation(() => {
      throw new RestoreAdmissionError();
    });

    await import("./index.js");
    await settle();

    expect(mocks.recovery).toHaveBeenCalledExactlyOnceWith({
      dataRoot: "C:/synthetic/workspace",
      databaseUrl: "sqlite:///C:/synthetic/workspace/job-apply-pro.db",
      projectRoot: "C:/synthetic/resources",
      resourcesPath: "C:/synthetic/resources",
      masterKeyPath: "C:\\synthetic\\workspace\\secrets\\master-key.bin",
    });
    expect(mocks.key).not.toHaveBeenCalled();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
    expect(mocks.start).not.toHaveBeenCalled();
    expect(mocks.notificationStop).not.toHaveBeenCalled();
    expect(mocks.installGate).toBeUndefined();
    expect(mocks.windows).toHaveLength(0);
    expect(mocks.appQuit).toHaveBeenCalledOnce();
  });

  it("ignores project and database environment overrides during normal packaged startup", async () => {
    mocks.packaged = true;
    Object.defineProperty(process, "resourcesPath", {
      configurable: true,
      value: "C:/synthetic/resources",
    });
    vi.stubEnv("JAP_PROJECT_ROOT", "D:/untrusted-project-override");
    vi.stubEnv(
      "JAP_DATABASE_URL",
      "sqlite:///D:/untrusted-database-override.db",
    );

    await import("./index.js");
    await settle();

    expect(mocks.createSupervisor).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        projectRoot: "C:/synthetic/resources",
        dataRoot: "C:/synthetic/workspace",
        databaseUrl: "sqlite:///C:/synthetic/workspace/job-apply-pro.db",
        backendExecutable:
          "C:\\synthetic\\resources\\backend\\job-apply-pro-backend.exe",
        browserEngine: "msedge",
      }),
    );
    expect(mocks.recovery).not.toHaveBeenCalled();
    expect(mocks.start).toHaveBeenCalledOnce();
    expect(mocks.installGate).toBeTypeOf("function");
  });

  it("enters recovery-only startup if a guard appears while loading an existing key", async () => {
    mocks.packaged = true;
    Object.defineProperty(process, "resourcesPath", {
      configurable: true,
      value: "C:/synthetic/resources",
    });
    mocks.admission
      .mockImplementationOnce(() => undefined)
      .mockImplementation(() => {
        throw new RestoreAdmissionError();
      });

    await import("./index.js");
    await settle();

    expect(mocks.key).toHaveBeenCalledOnce();
    expect(mocks.recovery).toHaveBeenCalledOnce();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
    expect(mocks.start).not.toHaveBeenCalled();
    expect(mocks.installGate).toBeUndefined();
    expect(mocks.appQuit).toHaveBeenCalledOnce();
  });

  it("rechecks admission after asynchronous key loading before constructing services", async () => {
    mocks.admission
      .mockImplementationOnce(() => undefined)
      .mockImplementation(() => {
        throw new RestoreAdmissionError();
      });
    await import("./index.js");
    await settle();
    expect(mocks.key).toHaveBeenCalledOnce();
    expect(mocks.createSupervisor).not.toHaveBeenCalled();
    expect(mocks.errorBox).toHaveBeenCalledExactlyOnceWith(
      "Job Apply Pro — restore recovery required",
      RESTORE_ADMISSION_MESSAGE,
    );
    expect(mocks.appQuit).toHaveBeenCalledOnce();
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

  it("rejected update preparation does not stop notifications for a continuing restore", async () => {
    mocks.prepareUpdate.mockRejectedValue(
      new Error("Synthetic restore is in progress."),
    );
    await import("./index.js");
    await settle();
    await expect(mocks.installGate!()).rejects.toThrow(
      "restore is in progress",
    );
    expect(mocks.prepareUpdate).toHaveBeenCalledOnce();
    expect(mocks.notificationStop).not.toHaveBeenCalled();
    expect(mocks.shutdown).not.toHaveBeenCalled();
    expect(mocks.appQuit).not.toHaveBeenCalled();
  });
});
