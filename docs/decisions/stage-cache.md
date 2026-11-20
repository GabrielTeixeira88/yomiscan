# Stage caching and bounded chapter results

Accepted for post-MVP Caching & Performance, 2026-11-20.

Implement the browser result LRU first. The existing serial chapter queue owns
results, byte accounting, eviction and export pins. Visible pages and active
refreshes retain their output. An evicted page is eligible for normal processing
when it becomes visible, provided it can fit. Eviction itself never schedules work.
Original report pixels belong to the same result and budget as its PNG/snapshot.
Blob URLs are detached from overlays before revocation. In-flight acquisition,
transport and a single report download have separate bounded transient lifetimes.

The backend keeps logical detection/grouping, crop OCR, lexical, translation-batch
and render entries behind a small byte-store interface. JSON and PNG bytes, never
pickle or live engines, are stored in a bounded RAM LRU. Explicit opt-in enables a
local SQLite database containing checksummed BLOBs. A transaction publishes the
metadata and payload together; there are no external artifact files to orphan.
SQLite and inference remain on the existing single owning worker.

Canonical decoded RGB pixels identify an image, separately from the existing
uploaded-byte diagnostic digest. Each stage key includes its effective inputs,
upstream identity and algorithm/configuration/artifact identity. Unknown effective
model identities bypass reusable entries. Translation remains a native ordered
batch. Renderer keys exclude dictionary data which the renderer does not consume.

Translation refresh bypasses translation and rendering, preserving valid extraction
and lexical entries. Failed refreshes must not replace successful browser output or
publish failed translation/render entries. Diagnostics distinguish current work
from restored work and never relabel historical processing time as current work.

Persistence retains pixels and text locally and is disabled by default. Controls
distinguish Clear Session from Clear Persistent Cache. No URL, browser title,
credential or browsing metadata belongs in persistent entries. Report inclusion
controls from the diagnostic privacy decision continue to apply. This decision
extends that historical decision's session-only storage description.
