# 06 — Open Questions, Assumptions and Unverified Areas

These are decisions and uncertainties that could materially change the proposal in 04
and 05. **Blocking** questions should be answered in Milestone 0.

---

## 1. Decisions only the owner can make

| # | Question | Why it matters | If unanswered I assume… | Blocking? |
|---|---|---|---|---|
| Q1 | **Who is the user?** Only the owner, a small group of friends, or the public? What Japanese level? | It sets the bar for setup UX, packaging, signing, support and documentation. It also sets the grammar content level (N5 basics vs N2 nuance). | A small group of N4–N2 learners on desktop Chrome. Public release is a later option. | **Yes** |
| Q2 | **Is automatic English typesetting (current Translate Chapter) a must-keep main feature?** | My proposal demotes it to an optional "Glance" mode. If it is the owner's primary use, the roadmap should keep it in the MVP path, and the learning work becomes a parallel track. | It is valued, but secondary to learning. | **Yes** |
| Q3 | **Which reading sources are in scope?** Specific web readers, official stores (often canvas-rendered or DRM'd), aggregator sites, or local files (CBZ/folders)? | Discovery and acquisition work only on `<img>`-based readers. Official readers usually need the screenshot fallback. Aggregator sites carry legal and reputational risk for a *public* tool. Local files would favour building the local reader earlier. | Image-based web readers plus region-select for everything else. A local reader is optional. | **Yes** |
| Q4 | **Platforms:** Windows only? Linux? macOS? Chrome only, or Edge/Firefox? | Native messaging registration, installers, GPU runtimes and the side-panel API (Chrome/Edge only) all differ by platform. | Windows + Chrome first, Linux second. No macOS or Firefox in the MVP. | No |
| Q5 | **Hardware baseline.** Can we assume a discrete GPU? | It decides whether Hy-MT2 (Standard profile) or OPUS (Light) is the default, and how aggressive background prefetching can be on CPU. | Both profiles are supported, and GPU is auto-detected. The owner's RTX 4070 SUPER is *not* assumed for other users. | No |
| Q6 | **Do you (and target users) use Anki/AnkiConnect and Yomitan?** | If yes, AnkiConnect export and Yomitan compatibility of the text layer are high priority, and the 8765 port conflict is urgent. If not, a built-in deck/CSV is enough. | Yes, which is common among this audience. | No |
| Q8 | **Gloss and translation language:** English only, or Portuguese too? | The repository has PT/ES experiments. JMdict non-English glosses are uneven. A PT learner experience needs different dictionary sources, and I can't judge their quality yet. | English only for the MVP. PT is a future option, evaluated separately. | No |
| Q10 | **Distribution:** unsigned developer builds, or a signed installer plus Chrome Web Store listing? | Windows SmartScreen warnings without code signing (a recurring cost). Web Store review of an extension that talks to a native host. Redistribution of model licences (JMdict CC BY-SA attribution; NLLB is non-commercial and must not ship). | Unsigned builds for a small group. No bundled models; downloads go through the model manager. | No |
| Q11 | **What translation quality is acceptable to show by default?** | My proposal collapses the translation by default because it is often wrong. Some users will want it visible. | Collapsed by default, with a user setting to always show it. | No |
| Q12 | **Is an LLM "explain this sentence" acceptable at all, given hallucination risk to learners?** | It changes whether Milestone 6 item 3 is pursued, and how it is labelled. | Opt-in only, labelled experimental, never the default explanation source. | No |
| Q13 | **Privacy default for the text-only result cache.** | I propose **on by default** (OCR text + analysis keyed by image hash, no pixels, no URLs). The current project is stricter (all persistence off). | Acceptable, with a visible toggle and a clear button. | No |
| Q15 | **Development process preferences.** Is AI-agent-driven development continuing? Is the current documentation density wanted? | My roadmap assumes short docs, deletion of failed experiments, and human-reviewable code density. That conflicts with the current "record everything, delete nothing" pattern. | Shorter docs and stricter pruning are welcome. | No |

## 2. Licensing and content questions

| # | Question | Implication |
|---|---|---|
| Q7 | **JLPT level data and frequency lists.** No official JLPT vocabulary lists have existed since 2010. Community lists differ in licence (some CC-BY, some unclear). The same applies to word-frequency lists. | Known-word seeding and "N3 grammar" labels depend on a licensable source. Fallback: JMdict priority tags only, and project-authored JLPT labels on our own grammar patterns. |
| Q7b | **Deinflection rules and grammar data from existing GPL-3 projects** (Yomitan, mokuro). | YomiScan is MIT. Copying GPL rule tables would force a licence change. Plan: author our own rule table from grammar knowledge, and treat GPL projects as *behavioural references only*. Interoperating with Yomitan as a separate extension has no licence effect. |
| Q7c | **KANJIDIC2** is CC BY-SA 4.0 (EDRDG), like JMdict. | The same attribution handling as JMdict applies. The derived DB is not MIT. Already understood by the project. |
| Q7d | **Detector weight provenance.** The INT8 ONNX detector shares a repository revision with the PyTorch checkpoint, but its equivalence is unverified (Repo-reported). | Confirm licence and provenance of the exact ONNX artifact before making it the default. |
| Q7e | **manga-ocr ONNX export.** It would be a project-generated derivative of Apache-2.0 weights. | Distributing our own export is fine with notice. Check whether to host it, or have users export it locally at setup (which needs Torch once). |

## 3. Technical unknowns to resolve early

| # | Unknown | How to resolve | What changes if it fails |
|---|---|---|---|
| Q9 | **Can Yomitan (and similar popups) scan a text layer that YomiScan injects?** The current overlays use *closed* Shadow DOM, which external extensions cannot see. | Prototype a light-DOM or open-shadow-root text layer on 3 sites in week 1 of Milestone 3. | Yomitan compatibility becomes a nice-to-have. YomiScan's own side panel and tooltip carry the experience. |
| Q16 | Does manga-ocr's ONNX export reproduce PyTorch output exactly? | Milestone 1 gate. | Keep Torch OCR as an extra, and the install stays larger. |
| Q17 | How often does furigana leak into OCR output on real pages? | Count it on the Milestone 0 corpus. | If frequent, add a geometric ruby filter before OCR in the MVP. |
| Q18 | How often are long narration blocks truncated by manga-ocr? | Compare OCR length against the reference length on long blocks in the corpus. | If frequent, split blocks into columns or lines before OCR. |
| Q19 | GPU runtime on Windows for non-NVIDIA users (DirectML vs WinML vs Vulkan llama.cpp). | Benchmark in Milestone 1. | Non-NVIDIA users get the CPU (Light) profile. |
| Q20 | Real CPU time per page with ONNX on a mid-range laptop (not the i7-14700K development PC). | Measure on one lower-end machine in Milestone 1. | Background prefetch depth and default profile per machine. |
| Q21 | Does `chrome.sidePanel` plus a native-messaging port keep the MV3 service worker alive reliably for the session? | Prototype in Milestone 1. | Use the offscreen document (already used today) as the long-lived connection owner. |

## 4. Assumptions I made, and their implications

| Assumption | Basis | Implication if wrong |
|---|---|---|
| Learning, not translation, is the primary goal | Project description, README, `AGENTS.md` ("Language learning rather than translation alone") | If translation is primary, keep Translate Chapter as the main mode (Q2) and invest in translation models over the lexical engine. |
| The owner is currently the main user | Setup complexity; personal paths in the README; the corpus comes from the owner's own reading | Public-release work (signing, support, docs) moves earlier. |
| The development pace and style are AI-agent driven | Five post-MVP stages merged in about 24 h; doc density; additive history | The roadmap's effort estimates may be pessimistic for coding and accurate for evaluation and content work. |
| The 3-page, single-series corpus does not represent manga in general | Repository's own caveats | Every model decision (including the ones I endorse, such as keeping manga-ocr) must be re-checked on the Milestone 0 corpus. |
| AnkiConnect uses port 8765 by default | Its standard configuration | If it doesn't conflict in practice, the native-messaging port negotiation is still worth having for auth and auto-start. |
| Users read on desktop Chrome | Extension-only project | A mobile reading use case would need a different product (e.g., the sibling "Yomu" Android project). |

## 5. What this assessment could not verify

- **Live browser behaviour on real reader sites.** I did not drive Chrome. I relied on
  the repository's headless fixture (Repo-reported: 37 checks) and the unmerged audit
  branch's probes for AU-01 to AU-03.
- **GPU performance** of any component. The installed Torch build is CPU-only.
- **Optional engines** (Hy-MT2, Qwen, Fugu, NLLB, ONNX OCR/detector). I relied on the
  Stage 2/4 reports and did not re-run them.
- **General OCR or translation accuracy.** I only ran two real pages and a handful of
  sentences. My observations show *types* of failure, not rates.
- **Install from scratch.** The default models and JMdict were already present, so I
  did not repeat first-time setup on a clean machine.
- **Proposed technologies.** ONNX export parity, Yomitan scanning of injected text,
  side-panel lifecycle and installer feasibility are untested. They are listed above
  as unknowns with a resolution plan.
