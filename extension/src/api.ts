export interface Meaning {
  entry_id: number; glosses: string[]; parts_of_speech: string[];
  spellings: string[]; readings: string[]; notes: string[]; labels: string[];
}
export interface Token {
  surface: string; reading: string | null; lemma: string | null; dictionary_form: string | null;
  part_of_speech: string | null; conjugation_type: string | null; conjugation_form: string | null;
  meanings: Meaning[];
}
export interface Analysis {
  original_text: string; translation: string | null;
  processing: {ocr_ms: number; translation_ms: number; analysis_ms: number; total_ms: number};
  tokens: Token[];
}

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const nullableString = (v: unknown) => v === null || typeof v === "string";
const strings = (v: unknown) => Array.isArray(v) && v.every(x => typeof x === "string");

export function parseAnalysis(value: unknown): Analysis {
  if (!record(value) || typeof value.original_text !== "string" || !nullableString(value.translation)
      || !record(value.processing) || !Array.isArray(value.tokens)) throw new Error("Invalid analysis response from local server.");
  if (!["ocr_ms", "translation_ms", "analysis_ms", "total_ms"].every(key =>
    typeof value.processing === "object" && value.processing !== null
    && typeof (value.processing as Record<string, unknown>)[key] === "number"
    && Number.isFinite((value.processing as Record<string, unknown>)[key])
    && Number((value.processing as Record<string, unknown>)[key]) >= 0)) {
    throw new Error("Invalid processing times from local server.");
  }
  for (const token of value.tokens) {
    if (!record(token) || typeof token.surface !== "string"
      || !["reading", "lemma", "dictionary_form", "part_of_speech", "conjugation_type", "conjugation_form"].every(k => nullableString(token[k]))
      || !Array.isArray(token.meanings)) throw new Error("Invalid token data from local server.");
    for (const meaning of token.meanings) {
      if (!record(meaning) || !Number.isInteger(meaning.entry_id)
        || !["glosses", "parts_of_speech", "spellings", "readings", "notes", "labels"].every(k => strings(meaning[k]))) {
        throw new Error("Invalid dictionary data from local server.");
      }
    }
  }
  return value as unknown as Analysis;
}

export function httpError(status: number): string {
  if (status === 400 || status === 413 || status === 422) return "The crop could not be read or is too large. Select a smaller clear text region.";
  if (status === 403) return "Local server rejected this extension. Check YOMISCAN_EXTENSION_ORIGINS in the backend setup.";
  if (status === 429) return "YomiScan is still processing another crop. Please try again shortly.";
  if (status === 503) return "YomiScan models or dictionary are unavailable. Check the backend terminal and restart after setup.";
  return "Local analysis failed. Try a smaller clear crop and check the backend terminal.";
}

export async function analyzeCrop(blob: Blob, signal: AbortSignal): Promise<Analysis> {
  const form = new FormData();
  form.append("file", blob, "selection.png");
  let response: Response;
  try {
    response = await fetch("http://127.0.0.1:8765/api/v1/analyze-image", {
      method: "POST", headers: {"X-YomiScan-Client": "study-extension-v1"}, body: form,
      signal, credentials: "omit", redirect: "error", cache: "no-store",
    });
  } catch (error) {
    if (signal.aborted) throw new Error("Analysis was cancelled or timed out. Try a smaller crop; the backend may still be finishing.");
    throw new Error("Cannot reach YomiScan. Start the local server at 127.0.0.1:8765 and try again.", {cause: error});
  }
  if (!response.ok) throw new Error(httpError(response.status));
  let value: unknown;
  try { value = await response.json(); }
  catch { throw new Error("The local server returned invalid JSON."); }
  return parseAnalysis(value);
}
