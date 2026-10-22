export type ManifestTicket = {
  ticket_id: string;
  credential_hash: string;
  status: "active" | "revoked";
  attendee_name: string;
};

export type CachedSession = {
  eventId: string;
  deviceToken: string;
  snapshotId: string;
  generatedAt: string;
  eventTitle: string;
  startsAt: string;
  tickets: ManifestTicket[];
};

export type ScanStatus = "pending" | "accepted" | "duplicate" | "conflict";

export type LocalScan = {
  scanEventId: string;
  eventId: string;
  snapshotId: string;
  credential: string;
  credentialHash: string;
  scannedAt: string;
  status: ScanStatus;
  attendeeName?: string;
  localValidation: "recognized" | "revoked" | "not_in_snapshot";
  reason?: string;
  conflictId?: string;
};

export type SyncPayload = {
  batch_id: string;
  snapshot_id: string;
  scans: Array<{ scan_event_id: string; credential: string; scanned_at: string }>;
};

export type PendingBatch = {
  batchId: string;
  eventId: string;
  snapshotId: string;
  scanIds: string[];
  payload: SyncPayload;
  createdAt: string;
};

const DB_NAME = "evenspace-offline-scanner";
const DB_VERSION = 1;

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("sessions")) db.createObjectStore("sessions", { keyPath: "eventId" });
      if (!db.objectStoreNames.contains("scans")) {
        const scans = db.createObjectStore("scans", { keyPath: "scanEventId" });
        scans.createIndex("eventId", "eventId", { unique: false });
      }
      if (!db.objectStoreNames.contains("batches")) {
        const batches = db.createObjectStore("batches", { keyPath: "batchId" });
        batches.createIndex("eventId", "eventId", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Could not open local scan storage"));
  });
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Local storage request failed"));
  });
}

async function readOne<T>(storeName: string, key: IDBValidKey): Promise<T | undefined> {
  const db = await openDatabase();
  try {
    return await requestResult<T | undefined>(db.transaction(storeName, "readonly").objectStore(storeName).get(key));
  } finally {
    db.close();
  }
}

async function readIndex<T>(storeName: string, indexName: string, key: IDBValidKey): Promise<T[]> {
  const db = await openDatabase();
  try {
    return await requestResult<T[]>(db.transaction(storeName, "readonly").objectStore(storeName).index(indexName).getAll(key));
  } finally {
    db.close();
  }
}

async function putOne<T>(storeName: string, value: T): Promise<void> {
  const db = await openDatabase();
  try {
    await requestResult(db.transaction(storeName, "readwrite").objectStore(storeName).put(value));
  } finally {
    db.close();
  }
}

async function removeOne(storeName: string, key: IDBValidKey): Promise<void> {
  const db = await openDatabase();
  try {
    await requestResult(db.transaction(storeName, "readwrite").objectStore(storeName).delete(key));
  } finally {
    db.close();
  }
}

export const getSession = (eventId: string) => readOne<CachedSession>("sessions", eventId);
export async function getSessions(): Promise<CachedSession[]> {
  const db = await openDatabase();
  try {
    return await requestResult<CachedSession[]>(db.transaction("sessions", "readonly").objectStore("sessions").getAll());
  } finally {
    db.close();
  }
}
export const saveSession = (session: CachedSession) => putOne("sessions", session);
export const getScans = (eventId: string) => readIndex<LocalScan>("scans", "eventId", eventId);
export const saveScan = (scan: LocalScan) => putOne("scans", scan);
export const getBatches = (eventId: string) => readIndex<PendingBatch>("batches", "eventId", eventId);
export const saveBatch = (batch: PendingBatch) => putOne("batches", batch);
export const deleteBatch = (batchId: string) => removeOne("batches", batchId);

export async function forgetSession(eventId: string): Promise<void> {
  const [scans, batches] = await Promise.all([getScans(eventId), getBatches(eventId)]);
  if (scans.some((scan) => scan.status === "pending") || batches.length > 0) {
    throw new Error("Sync or resolve every queued scan before removing this event from the device.");
  }
  const db = await openDatabase();
  try {
    const tx = db.transaction(["sessions", "scans"], "readwrite");
    tx.objectStore("sessions").delete(eventId);
    for (const scan of scans) tx.objectStore("scans").delete(scan.scanEventId);
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error("Could not remove event data"));
      tx.onabort = () => reject(tx.error ?? new Error("Could not remove event data"));
    });
  } finally {
    db.close();
  }
}
