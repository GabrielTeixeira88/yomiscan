// Browser port of the backend's lexical analysis (Stage 5a increment 2):
// analysis.py (lookup candidates, _analyze_lexical), lexical_ranking.py, lexical_units.py,
// grammar_patterns.py and inflection.py. The rule data is the backend's own JSON, bundled
// from backend/yomiscan/resources/lexical, so both engines share one source of truth.
// Pure and DOM-free; parity with Python is checked token by token (scripts/compare_browser_lexical.py).
import unitsJson from '../../../backend/yomiscan/resources/lexical/units.json';
import grammarJson from '../../../backend/yomiscan/resources/lexical/grammar.json';
import inflectionsJson from '../../../backend/yomiscan/resources/lexical/inflections.json';

export interface JapaneseToken {surface: string; lemma: string | null; reading: string | null; part_of_speech: string | null;
  conjugation_type: string | null; conjugation_form: string | null; orthographic_base: string | null; lemma_reading: string | null}
export interface DictionaryReading {text: string; spellings: string[]; no_kanji: boolean}
export interface DictionarySense {glosses: string[]; parts_of_speech: string[]; spellings: string[]; readings: string[]; notes: string[]; labels: string[]}
export interface DictionaryEntry {entry_id: number; spellings: string[]; readings: DictionaryReading[]; senses: DictionarySense[];
  form_priority: Record<string, string[]>}
export type Lookup = (form: string) => readonly DictionaryEntry[];
export interface AnalyzedToken {token: JapaneseToken; lookup_form: string | null; entry_ids: number[]; inflection: string[]}
export interface LexicalUnit {start: number; end: number; surface: string; lookup_form: string; entry_ids: number[]}
export interface GrammarMatch {pattern: string; start: number; end: number}
export interface LexicalResult {original_text: string; tokens: AnalyzedToken[]; dictionary_entries: Map<number, DictionaryEntry>;
  units: LexicalUnit[]; grammar: GrammarMatch[]}

// ---- shared helpers (japanese.py) ----------------------------------------------------------

/** japanese.hiragana: NFKC, then katakana ァ–ヶ to hiragana. */
export function hiragana(text: string): string {
  return text.normalize('NFKC').replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60));
}
/** Every character is punctuation, a symbol or a separator (Python unicodedata P/S/Z). */
export const symbolic = (text: string) => /^[\p{P}\p{S}\p{Z}]*$/u.test(text);
const primaryPos = (token: JapaneseToken) => token.part_of_speech ? token.part_of_speech.split(' / ')[0] : null;
const unique = <T>(values: T[]) => [...new Set(values)];
/** Python tuple comparison over numbers (booleans as 0/1). */
function compare(a: readonly number[], b: readonly number[]): number {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}
const flag = (value: boolean) => value ? 1 : 0;

// ---- lexical_ranking.py --------------------------------------------------------------------

const COMMON_PRIORITY_TAGS = new Set(['news1', 'ichi1', 'spec1', 'spec2', 'gai1']);
const KANJI = /[㐀-鿿豈-﫿]/gu;
const verb = (label: string) => {const l = label.toLowerCase(); return l.includes('verb') && !['adverb', 'aux', 'noun'].some(p => l.includes(p));};
const POS_FAMILIES: Record<string, (label: string) => boolean> = {
  '名詞': l => l.includes('noun') || ['numeric', 'counter', 'pronoun'].includes(l),
  '代名詞': l => l === 'pronoun',
  '動詞': verb,
  '形容詞': l => l.startsWith('adjective (keiyoushi)') || l === "'ku' adjective (archaic)",
  '形状詞': l => l.startsWith('adjectival nouns') || ["'taru' adjective", 'archaic/formal form of na-adjective'].includes(l),
  '副詞': l => l.startsWith('adverb'),
  '連体詞': l => l.startsWith('pre-noun adjectival'),
  '接続詞': l => l === 'conjunction',
  '感動詞': l => l.startsWith('interjection'),
  '助詞': l => l === 'particle',
  '助動詞': l => ['auxiliary verb', 'auxiliary', 'auxiliary adjective', 'copula'].includes(l),
  '接頭辞': l => l.includes('prefix'),
  '接尾辞': l => l.includes('suffix') || l === 'counter',
};
export const FUNCTION_WORD_POS = new Set(['助詞', '助動詞']);

export function posRank(entry: DictionaryEntry, pos: string | null): number {
  const family = Object.hasOwn(POS_FAMILIES, pos ?? '') ? POS_FAMILIES[pos!] : undefined;
  if (!family || !entry.senses.length) return 2;
  if (entry.senses[0].parts_of_speech.some(family)) return 0;
  return entry.senses.slice(1).some(s => s.parts_of_speech.some(family)) ? 1 : 2;
}
const posAgrees = (entry: DictionaryEntry, pos: string | null) => posRank(entry, pos) < 2;

function lemmaRank(entry: DictionaryEntry, token: JapaneseToken): number {
  const lemma = token.lemma ? token.lemma.split('-')[0] : null;
  const kanji = new Set((lemma ?? '').match(KANJI) ?? []);
  if (!kanji.size) return 2;
  if (lemma !== null && entry.spellings.includes(lemma)) return 0;
  return entry.spellings.some(s => [...s].some(c => kanji.has(c))) ? 1 : 2;
}

export function headwordAgrees(entry: DictionaryEntry, matched: string | null): boolean {
  if (!matched) return false;
  const first = [...entry.spellings.slice(0, 1), ...entry.readings.slice(0, 1).map(r => r.text)];
  return first.map(hiragana).includes(hiragana(matched));
}
const readingAgrees = (entry: DictionaryEntry, token: JapaneseToken) =>
  !!token.lemma_reading && entry.readings.some(r => hiragana(r.text) === token.lemma_reading);

export function priority(entry: DictionaryEntry, matched: string | null): [boolean, number] {
  const target = matched ? hiragana(matched) : null;
  const tags = Object.entries(entry.form_priority).filter(([form]) => target === null || hiragana(form) === target).flatMap(([, v]) => v);
  const bands = tags.map(t => /^nf(\d\d)$/.exec(t)).filter((m): m is RegExpExecArray => m !== null).map(m => Number(m[1]));
  return [tags.some(t => COMMON_PRIORITY_TAGS.has(t)), bands.length ? Math.min(...bands) : 99];
}

export function rankEntries(token: JapaneseToken, matched: string | null, entries: readonly DictionaryEntry[]): DictionaryEntry[] {
  const pos = primaryPos(token);
  let candidates = [...entries];
  if (pos !== null && FUNCTION_WORD_POS.has(pos) && candidates.some(e => posAgrees(e, pos))) candidates = candidates.filter(e => posAgrees(e, pos));
  const key = (entry: DictionaryEntry, index: number) => {
    const [common, band] = priority(entry, matched);
    return [lemmaRank(entry, token), posRank(entry, pos), flag(!headwordAgrees(entry, matched)),
      flag(!readingAgrees(entry, token)), flag(!common), band, index];
  };
  return candidates.map((entry, index) => ({entry, key: key(entry, index)})).sort((a, b) => compare(a.key, b.key)).map(x => x.entry);
}

export function chooseMatches(token: JapaneseToken, forms: readonly string[], lookup: Lookup): [string | null, DictionaryEntry[]] {
  const pos = primaryPos(token);
  let best: [number, string, readonly DictionaryEntry[]] | null = null;
  for (const form of forms) {
    const matches = lookup(form);
    if (!matches.length) continue;
    const rank = pos !== null && FUNCTION_WORD_POS.has(pos) ? Math.min(...matches.map(e => posRank(e, pos))) : 0;
    if (best === null || rank < best[0]) best = [rank, form, matches];
    if (best[0] === 0) break;
  }
  return best === null ? [null, []] : [best[1], rankEntries(token, best[1], best[2])];
}

/** analysis.lookup_candidates */
export function lookupCandidates(token: JapaneseToken): string[] {
  if (symbolic(token.surface)) return [];
  return unique([token.orthographic_base, token.lemma, token.surface, token.lemma_reading].filter((v): v is string => !!v));
}

// ---- lexical_units.py ----------------------------------------------------------------------

interface UnitRules {max_tokens: number; variants: [string, string][]; clause_initial_only_pos: string[]; function_edge_entry_pos: string[];
  function_edge_common_pos: string[]; verb_span_excluded_pos: string[]; never_initial_surfaces: Set<string>; clause_initial_preferred_pos: string[]}
const INFLECTING_POS = new Set(['動詞', '形容詞']);

export function loadUnitRules(data: unknown = unitsJson): UnitRules {
  const d = data as Record<string, unknown>;
  if (d.schema_version !== 1) throw new Error('Unsupported unit rules schema');
  const max = d.max_tokens;
  if (!Number.isInteger(max) || Number(max) < 2 || Number(max) > 12) throw new Error('max_tokens must be an integer from 2 to 12');
  const variants = (d.variants as {colloquial: string; standard: string}[]).map(v => [v.colloquial, v.standard] as [string, string]);
  if (variants.some(([a, b]) => !a || !b || a === b)) throw new Error('Unit variants need distinct nonempty forms');
  const list = (key: string) => (d[key] as string[] | undefined) ?? [];
  return {max_tokens: Number(max), variants, clause_initial_only_pos: list('clause_initial_only_pos'), function_edge_entry_pos: list('function_edge_entry_pos'),
    function_edge_common_pos: list('function_edge_common_pos'), verb_span_excluded_pos: list('verb_span_excluded_pos'),
    never_initial_surfaces: new Set(list('never_initial_surfaces')), clause_initial_preferred_pos: list('clause_initial_preferred_pos')};
}

export function candidateForms(span: readonly JapaneseToken[], rules: UnitRules): string[] {
  const surface = span.map(t => t.surface).join(''), last = span[span.length - 1];
  const base = last.orthographic_base || last.lemma;
  const forms = [surface];
  if (base && base !== last.surface) forms.push(span.slice(0, -1).map(t => t.surface).join('') + base);
  for (const form of [...forms]) for (const [colloquial, standard] of rules.variants)
    if (form.includes(colloquial)) forms.push(form.replaceAll(colloquial, standard));
  return unique(forms);
}
const clauseInitial = (tokens: readonly JapaneseToken[], start: number) => start === 0 || symbolic(tokens[start - 1].surface);
const firstPosIn = (entry: DictionaryEntry, labels: readonly string[]) =>
  (entry.senses[0]?.parts_of_speech ?? []).some(pos => labels.some(label => pos.toLowerCase().startsWith(label)));

function rankUnitEntries(form: string, entries: readonly DictionaryEntry[]): DictionaryEntry[] {
  return entries.map((entry, index) => {const [common, band] = priority(entry, form);
    return {entry, key: [flag(!headwordAgrees(entry, form)), flag(!common), band, index]};}).sort((a, b) => compare(a.key, b.key)).map(x => x.entry);
}

export function findUnits(tokens: readonly JapaneseToken[], lookup: Lookup, rules: UnitRules = loadUnitRules()): [LexicalUnit, DictionaryEntry[]][] {
  const found: [LexicalUnit, DictionaryEntry[]][] = [];
  for (let start = 0; start < tokens.length; start++) {
    if (symbolic(tokens[start].surface) || rules.never_initial_surfaces.has(tokens[start].surface)) continue;
    for (let end = Math.min(tokens.length, start + rules.max_tokens); end > start + 1; end--) {
      const span = tokens.slice(start, end);
      if (span.some(t => symbolic(t.surface))) continue;
      let match: [string, readonly DictionaryEntry[]] | null = null;
      for (const form of candidateForms(span, rules)) {const entries = lookup(form); if (entries.length) {match = [form, entries]; break;}}
      if (!match) continue;
      const [form, entries] = match;
      let ranked = rankUnitEntries(form, entries);
      const first = primaryPos(span[0]), lastPos = primaryPos(span[span.length - 1]);
      if ((first !== null && FUNCTION_WORD_POS.has(first)) || (lastPos !== null && FUNCTION_WORD_POS.has(lastPos))) {
        ranked = ranked.filter(e => firstPosIn(e, rules.function_edge_entry_pos) || (priority(e, form)[0] && firstPosIn(e, rules.function_edge_common_pos)));
        if (!ranked.length) continue;
      }
      if (span.some(t => INFLECTING_POS.has(primaryPos(t) ?? ''))) {
        ranked = ranked.filter(e => !firstPosIn(e, rules.verb_span_excluded_pos));
        if (!ranked.length) continue;
      }
      if (!clauseInitial(tokens, start))  // stable: conjunction readings after particle/expression readings
        ranked = ranked.map((entry, index) => ({entry, key: [flag(firstPosIn(entry, rules.clause_initial_preferred_pos)), index]}))
          .sort((a, b) => compare(a.key, b.key)).map(x => x.entry);
      if (!clauseInitial(tokens, start) && firstPosIn(ranked[0], rules.clause_initial_only_pos)) continue;
      found.push([{start, end, surface: span.map(t => t.surface).join(''), lookup_form: form, entry_ids: ranked.map(e => e.entry_id)}, ranked]);
      break;  // the longest span starting here
    }
  }
  const chosen: [LexicalUnit, DictionaryEntry[]][] = [], taken = new Set<number>();
  for (const item of [...found].sort((a, b) => compare([-(a[0].end - a[0].start), a[0].start], [-(b[0].end - b[0].start), b[0].start]))) {
    const span = Array.from({length: item[0].end - item[0].start}, (_, i) => item[0].start + i);
    if (!span.some(i => taken.has(i))) {chosen.push(item); span.forEach(i => taken.add(i));}
  }
  return chosen.sort((a, b) => a[0].start - b[0].start);
}

// ---- grammar_patterns.py -------------------------------------------------------------------

type Step = Partial<Record<'surface' | 'base' | 'pos' | 'form', string[]>>;
export interface GrammarPattern {id: string; name: string; forms: string[]; meaning: string; alternatives: Step[][]; after: Step | null}
const STEP_FIELDS = new Set(['surface', 'base', 'pos', 'form']);

export function loadGrammar(data: unknown = grammarJson): GrammarPattern[] {
  const d = data as {schema_version: number; patterns: Record<string, unknown>[]};
  if (d.schema_version !== 1) throw new Error('Unsupported grammar rules schema');
  const seen = new Set<string>();
  return d.patterns.map(item => {
    const id = String(item.id);
    if (seen.has(id)) throw new Error(`Duplicate grammar pattern ${id}`);
    seen.add(id);
    const alternatives = item.alternatives as Step[][];
    if (alternatives.some(steps => !steps.length || steps.some(step => !Object.keys(step).length || Object.keys(step).some(k => !STEP_FIELDS.has(k)))))
      throw new Error(`Pattern ${id} has an empty or unknown step field`);
    const after = (item.after ?? null) as Step | null;
    if (after !== null && (!Object.keys(after).length || Object.keys(after).some(k => !STEP_FIELDS.has(k)))) throw new Error(`Pattern ${id} has an invalid 'after'`);
    return {id, name: String(item.name), forms: item.forms as string[], meaning: String(item.meaning), alternatives, after};
  });
}
const GRAMMAR = loadGrammar();
export const grammarPattern = (id: string) => GRAMMAR.find(p => p.id === id);

function stepMatches(step: Step, token: JapaneseToken): boolean {
  const pos = primaryPos(token), bases = [token.orthographic_base, token.lemma].filter(Boolean);
  return (!step.surface || step.surface.includes(token.surface)) && (!step.base || bases.some(b => step.base!.includes(b!))) &&
    (!step.pos || (pos !== null && step.pos.includes(pos))) &&
    (!step.form || step.form.some(f => (token.conjugation_form ?? '').startsWith(f)));
}

export function findGrammar(tokens: readonly JapaneseToken[], patterns: readonly GrammarPattern[] = GRAMMAR): GrammarMatch[] {
  const best = new Map<number, GrammarMatch>();
  for (let start = 0; start < tokens.length; start++) for (const pattern of patterns) {
    if (pattern.after && (start === 0 || !stepMatches(pattern.after, tokens[start - 1]))) continue;
    for (const steps of pattern.alternatives) {
      const end = start + steps.length;
      if (end <= tokens.length && steps.every((step, i) => stepMatches(step, tokens[start + i]))) {
        const current = best.get(start);
        if (!current || end > current.end) best.set(start, {pattern: pattern.id, start, end});
      }
    }
  }
  const matches = [...best.keys()].sort((a, b) => a - b).map(k => best.get(k)!);
  return matches.filter(m => !matches.some(o => o !== m && o.start <= m.start && m.end <= o.end));
}

// ---- inflection.py -------------------------------------------------------------------------

type Rule = Partial<Record<'surface' | 'base' | 'form' | 'pos', string[]>> & {label: string};
interface InflectionRules {own_forms: Rule[]; followers: Rule[]; follower_pos: Set<string>; follower_particles: Set<string>; heads: Set<string>}
const RULE_FIELDS = new Set(['surface', 'base', 'form', 'pos', 'label']);

export function loadInflections(data: unknown = inflectionsJson): InflectionRules {
  const d = data as Record<string, unknown>;
  if (d.schema_version !== 1) throw new Error('Unsupported inflection rules schema');
  const rules = (items: Rule[]) => {
    for (const item of items) if (!('label' in item) || Object.keys(item).some(k => !RULE_FIELDS.has(k)) || Object.keys(item).length < 2)
      throw new Error('Inflection rules need a label and at least one match field');
    return items;
  };
  return {own_forms: rules(d.own_forms as Rule[]), followers: rules(d.followers as Rule[]), follower_pos: new Set(d.follower_pos as string[]),
    follower_particles: new Set(d.follower_particles as string[]), heads: new Set(d.heads as string[])};
}
const INFLECTIONS = loadInflections();

function ruleLabel(rules: readonly Rule[], token: JapaneseToken): string | null {
  const bases = [token.orthographic_base, token.lemma].filter(Boolean), pos = primaryPos(token);
  for (const rule of rules)
    if ((!rule.surface || rule.surface.includes(token.surface)) && (!rule.base || bases.some(b => rule.base!.includes(b!))) &&
      (!rule.pos || (pos !== null && rule.pos.includes(pos))) && (!rule.form || rule.form.some(f => (token.conjugation_form ?? '').startsWith(f))))
      return rule.label;
  return null;
}

export function inflectionLabels(tokens: readonly JapaneseToken[], rules: InflectionRules = INFLECTIONS): string[][] {
  const result: string[][] = tokens.map(() => []), consumed = new Set<number>();
  tokens.forEach((token, index) => {
    if (!rules.heads.has(primaryPos(token) ?? '\0') || consumed.has(index)) return;
    const own = ruleLabel(rules.own_forms, token), labels = own ? [own] : [];
    for (let offset = index + 1; offset < tokens.length; offset++) {
      const follower = tokens[offset];
      const explicit = rules.followers.some(rule => 'pos' in rule && ruleLabel([rule], follower) !== null);
      if (!rules.follower_pos.has(primaryPos(follower) ?? '\0') && !rules.follower_particles.has(follower.surface) && !explicit) break;
      const label = ruleLabel(rules.followers, follower);
      if (label === null) break;  // an unknown auxiliary (copula だ, etc.) ends the word
      labels.push(label);consumed.add(offset);
      if (rules.follower_particles.has(follower.surface)) break;  // て/で/ば close the inflected word
    }
    result[index] = unique(labels);
  });
  return result;
}

// ---- analysis.py: TextAnalyzer._analyze_lexical --------------------------------------------

export function analyzeLexical(text: string, tokens: readonly JapaneseToken[], dictionaryLookup: Lookup): LexicalResult {
  const cache = new Map<string, readonly DictionaryEntry[]>(), entries = new Map<number, DictionaryEntry>();
  const lookup: Lookup = form => {if (!cache.has(form)) cache.set(form, dictionaryLookup(form)); return cache.get(form)!;};
  const labels = inflectionLabels(tokens);
  const analyzed = tokens.map((token, i): AnalyzedToken => {
    const [form, matches] = chooseMatches(token, lookupCandidates(token), lookup);
    matches.forEach(e => entries.set(e.entry_id, e));
    return {token, lookup_form: form, entry_ids: matches.map(e => e.entry_id), inflection: labels[i]};
  });
  const units = findUnits(tokens, lookup).map(([unit, matches]) => {matches.forEach(e => entries.set(e.entry_id, e)); return unit;});
  return {original_text: text, tokens: analyzed, dictionary_entries: entries, units, grammar: findGrammar(tokens)};
}
