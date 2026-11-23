"""Candidate ranking rules on synthetic JMdict-shaped entries (no dictionary download).

Each case mirrors a failure observed with the real JMdict before ranking existed.
"""

from yomiscan.dictionary import DictionaryEntry, DictionaryReading, DictionarySense
from yomiscan.lexical_ranking import choose_matches, pos_rank, priority, rank_entries
from yomiscan.nlp import JapaneseToken


def entry(entry_id, spellings, readings, *senses, priority=None):
    return DictionaryEntry(entry_id, tuple(spellings), tuple(DictionaryReading(r) for r in readings),
                           tuple(DictionarySense((gloss,), tuple(pos)) for gloss, pos in senses),
                           priority or {})


def token(surface, pos, lemma=None, lemma_reading=None):
    return JapaneseToken(surface=surface, lemma=lemma or surface, reading=surface, part_of_speech=pos,
                         conjugation_type=None, conjugation_form=None, orthographic_base=surface,
                         lemma_reading=lemma_reading or surface)


FEATHER = entry(1, ["羽"], ["は"], ("feather", ["noun (common) (futsuumeishi)"]), priority={"羽": ("ichi1",)})
TOOTH = entry(2, ["歯"], ["は"], ("tooth", ["noun (common) (futsuumeishi)"]), priority={"歯": ("ichi1",)})
TOPIC = entry(3, [], ["は"], ("indicates sentence topic", ["particle"]))


def ids(entries):
    return [item.entry_id for item in entries]


def test_particle_drops_content_word_homophones():
    assert ids(rank_entries(token("は", "助詞 / 係助詞"), "は", [FEATHER, TOOTH, TOPIC])) == [3]


def test_particle_keeps_everything_when_no_particle_entry_exists():
    assert ids(rank_entries(token("は", "助詞 / 係助詞"), "は", [FEATHER, TOOTH])) == [1, 2]


def test_kanji_lemma_selects_the_written_entry():
    koto = [entry(10, ["琴"], ["こと"], ("koto", ["noun (common) (futsuumeishi)"])),
            entry(11, ["事"], ["こと"], ("thing", ["noun (common) (futsuumeishi)"]))]
    assert ids(rank_entries(token("こと", "名詞 / 普通名詞 / 一般", lemma="事"), "こと", koto)) == [11, 10]


def test_shared_lemma_kanji_beats_unrelated_spelling():
    ikeru = [entry(20, ["生ける"], ["いける"], ("to arrange (flowers)", ["Ichidan verb"]), priority={"生ける": ("news2",)}),
             entry(21, ["行ける"], ["いける"], ("to be good (at)", ["Ichidan verb"]))]
    potential = token("いけ", "動詞 / 非自立可能", lemma="行く", lemma_reading="いける")
    assert ids(rank_entries(potential, "いける", ikeru)) == [21, 20]


def test_first_sense_agreement_beats_later_sense_agreement():
    adjective = entry(30, ["無い"], ["ない"], ("nonexistent", ["adjective (keiyoushi)"]),
                      ("not", ["auxiliary adjective"]), priority={"ない": ("ichi1",)})
    auxiliary = entry(31, [], ["ない"], ("not", ["auxiliary adjective", "suffix"]))
    assert pos_rank(adjective, "助動詞") == 1 and pos_rank(auxiliary, "助動詞") == 0
    assert ids(rank_entries(token("ない", "助動詞"), "ない", [adjective, auxiliary])) == [31, 30]


def test_headword_beats_alternate_reading():
    tte = entry(40, [], ["って", "て"], ("you said", ["particle"]))
    te = entry(41, [], ["て", "で"], ("and", ["particle", "conjunction"]))
    assert ids(rank_entries(token("て", "助詞 / 接続助詞"), "て", [tte, te])) == [41, 40]


def test_common_word_and_frequency_band_break_ties():
    rare = entry(50, ["年"], ["とし"], ("year (rare)", ["noun (common) (futsuumeishi)"]))
    common = entry(51, ["年"], ["とし"], ("year", ["noun (common) (futsuumeishi)"]),
                   priority={"年": ("ichi1", "nf02")})
    assert priority(common, "年") == (True, 2)
    assert priority(rare, "年") == (False, 99)
    assert ids(rank_entries(token("年", "名詞 / 普通名詞 / 一般", lemma="年", lemma_reading="とし"), "年", [rare, common])) == [51, 50]


def test_function_word_prefers_the_form_with_a_primary_particle_entry():
    yes = entry(60, [], ["ん"], ("yes", ["interjection (kandoushi)"]), ("explanatory", ["particle"]))
    no_particle = entry(61, [], ["の"], ("indicates possessive", ["particle"]))
    table = {"ん": (yes,), "の": (no_particle,)}
    calls = []
    def lookup(form):
        calls.append(form)
        return table.get(form, ())
    contracted = token("ん", "助詞 / 準体助詞", lemma="の", lemma_reading="ん")
    assert choose_matches(contracted, ["ん", "の"], lookup) == ("の", (no_particle,))
    assert calls == ["ん", "の"]


def test_content_words_stop_at_the_first_matching_form():
    calls = []
    def lookup(form):
        calls.append(form)
        return (FEATHER,)
    assert choose_matches(token("羽", "名詞 / 普通名詞 / 一般"), ["羽", "は"], lookup) == ("羽", (FEATHER,))
    assert calls == ["羽"]


def test_no_match_returns_no_entries():
    assert choose_matches(token("ゴゴゴ", "名詞 / 普通名詞 / 一般"), ["ゴゴゴ"], lambda form: ()) == (None, ())
