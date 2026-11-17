import { objectKeyFromUrl } from "../ports/storage.ts";
import { StorageError } from "./storage-error.ts";

/** Classifies a stored URL: the key of this bucket's object, or a StorageError. */
export function storedObjectKey(value: string, keyFromBucketUrl: (value: string) => string): string {
  const key = objectKeyFromUrl(value, (url) => {
    try { return keyFromBucketUrl(url.href); }
    catch (error) { if (error instanceof StorageError) return undefined; throw error; }
  });
  if (!key) throw new StorageError("URL does not belong to this bucket.");
  return key;
}
