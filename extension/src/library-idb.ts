// IndexedDB storage for saved words and sentences (library.ts). The service worker and the
// Saved page open the same database (one extension origin); IndexedDB transactions keep their
// writes consistent. Uninstalling the extension deletes it.
import type {LibraryStore, StoreName} from './library';

const NAME = 'yomiscan-library', VERSION = 1;
const KEYS: Record<StoreName, string> = {words: 'key', sentences: 'id'};

const done = <T>(request: IDBRequest<T>) => new Promise<T>((resolve, reject) => {
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(new Error(`Saved words storage failed: ${request.error?.message ?? 'unknown error'}`, {cause: request.error}));
});
const finished = (transaction: IDBTransaction) => new Promise<void>((resolve, reject) => {
  transaction.oncomplete = () => resolve();
  const fail = () => reject(new Error(`Saved words storage failed: ${transaction.error?.message ?? 'aborted'}`, {cause: transaction.error}));
  transaction.onerror = fail; transaction.onabort = fail;
});

export class IndexedDbStore implements LibraryStore {
  private database: Promise<IDBDatabase> | null = null;

  private open(): Promise<IDBDatabase> {
    this.database ??= new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(NAME, VERSION);
      request.onupgradeneeded = () => {
        for (const [store, keyPath] of Object.entries(KEYS))
          if (!request.result.objectStoreNames.contains(store)) request.result.createObjectStore(store, {keyPath});
      };
      request.onsuccess = () => {
        // Another context upgrading the database closes this connection; reopen on next use.
        request.result.onversionchange = () => {request.result.close(); this.database = null;};
        resolve(request.result);
      };
      request.onerror = () => {this.database = null; reject(new Error(`Could not open saved words storage: ${request.error?.message}`, {cause: request.error}));};
      request.onblocked = () => {this.database = null; reject(new Error('Saved words storage is busy in another YomiScan tab; close it and retry.'));};
    });
    return this.database;
  }

  private async run<T>(store: StoreName, mode: IDBTransactionMode, work: (objects: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
    const transaction = (await this.open()).transaction(store, mode);
    const request = work(transaction.objectStore(store));
    const [result] = await Promise.all([request ? done(request) : Promise.resolve(undefined), finished(transaction)]);
    return result;
  }

  get<S extends StoreName>(store: S, key: string) {return this.run(store, 'readonly', objects => objects.get(key)) as Promise<never>;}
  async all<S extends StoreName>(store: S) {return (await this.run(store, 'readonly', objects => objects.getAll())) as never;}
  async put<S extends StoreName>(store: S, values: unknown[]) {
    if (values.length) await this.run(store, 'readwrite', objects => {for (const value of values) objects.put(value);});
  }
  async delete(store: StoreName, key: string) {await this.run(store, 'readwrite', objects => objects.delete(key));}
  async clear(store: StoreName) {await this.run(store, 'readwrite', objects => objects.clear());}
  async count(store: StoreName) {return (await this.run(store, 'readonly', objects => objects.count())) ?? 0;}
  async has(store: StoreName, keys: string[]) {
    if (!keys.length) return [];
    const transaction = (await this.open()).transaction(store, 'readonly'), objects = transaction.objectStore(store);
    const complete = finished(transaction);  // attached before any await, so completion is never missed
    const found = await Promise.all(keys.map(key => done(objects.getKey(key)).then(hit => hit !== undefined)));
    await complete;
    return keys.filter((_, i) => found[i]);
  }
}
