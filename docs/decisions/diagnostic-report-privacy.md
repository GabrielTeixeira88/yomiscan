# Page reports: explicit local export with bounded session snapshots

Accepted 2026-11-20 for post-MVP Reliability & Quality of Life.

A failed page needs its acquisition, detection, OCR, translation and renderer evidence
from the same job. The existing CLI diagnostics are rich; rerunning inference during
export can produce a different result and wastes processing.

The extension requests an optional render transport bundle containing the existing PNG
and a bounded JSON snapshot. The original PNG endpoint remains compatible. The backend
writes nothing to disk and retains no report cache. Snapshots reuse the result produced
by that render call; they do not load another engine or rerun OCR.

Export is an explicit page-level action. The default ZIP contains metadata, region
lineage/status and timings. Separate unchecked options include raw OCR/translation text,
original pixels and translated pixels. Pixel attachments are decoded/re-encoded to PNG,
discarding ancillary image metadata. Text is sensitive even after URL/path/credential
redaction, so inclusion is consent to retain it locally, not permission to redistribute it.

Export uses an allowlist of metadata fields and code-owned reason labels. Raw exceptions,
source URLs, headers, cookies, credentials and local paths are excluded. Model revisions
are declared metadata, not a verification of arbitrary sideloaded weight bytes. Unknown
OCR confidence remains null; incomplete/rejected model responses are not reconstructed.

Input byte SHA-256, dimensions and the owning page/job record bind snapshots to results.
An export checks source/session identity again after asynchronous work and is cancelled
on replacement or navigation. A failed refresh retains the previous successful snapshot;
it is identified by its original job ID rather than relabelled as the new attempt.

Limits: 2 MiB backend snapshot, 32 MiB rendered PNG, 48 MiB exported ZIP. Oversized
snapshots explicitly report unavailable diagnostics while preserving image processing.
Session accounting includes snapshots. Only three recent original images, totalling
at most 24 MiB, are retained in memory. Clear/navigation releases retained data and
object URLs. Downloads remain on disk because the user explicitly requested them;
the application does not silently delete a user's saved file.

The stored-ZIP implementation accepts bounded fixed safe paths, verifies CRC/directory
consistency and supports no compression, executable content or path extraction.
There is no automatic upload, GitHub attachment, persistent stage cache or new permission.

Yomu informed the architecture. This is an independent Python/TypeScript implementation;
no AGPL-covered source was imported.
