"""Small hand-authored XML fixture; no downloaded dictionary required for tests."""

import pytest

from yomiscan.dictionary.importer import import_jmdict


@pytest.fixture
def jmdict_source(tmp_path):
    source = tmp_path / "fixture.xml"
    source.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [<!ENTITY noun "noun"><!ENTITY verb "verb">]>
<JMdict>
<entry><ent_seq>1</ent_seq><k_ele><keb>猫</keb></k_ele>
<r_ele><reb>ねこ</reb></r_ele>
<sense><pos>&noun;</pos><gloss>cat</gloss><gloss xml:lang="fre">chat</gloss></sense>
<sense><gloss>test inherited sense</gloss></sense></entry>
<entry><ent_seq>2</ent_seq><k_ele><keb>食べる</keb></k_ele>
<r_ele><reb>たべる</reb></r_ele><sense><pos>&verb;</pos><gloss>to eat</gloss></sense></entry>
<entry><ent_seq>3</ent_seq><k_ele><keb>高い</keb></k_ele>
<r_ele><reb>たかい</reb></r_ele><sense><gloss>high</gloss></sense></entry>
<entry><ent_seq>4</ent_seq><k_ele><keb>大丈夫</keb></k_ele>
<r_ele><reb>だいじょうぶ</reb></r_ele><sense><gloss>okay</gloss></sense></entry>
<entry><ent_seq>5</ent_seq><r_ele><reb>でも</reb></r_ele>
<sense><gloss>however</gloss></sense></entry>
<entry><ent_seq>6</ent_seq><k_ele><keb>試験</keb></k_ele>
<r_ele><reb>しけん</reb><re_restr>試験</re_restr></r_ele>
<r_ele><reb>テスト</reb><re_nokanji/></r_ele>
<sense><stagk>試験</stagk><stagr>しけん</stagr><pos>&noun;</pos>
<misc>test label</misc><s_inf>test note</s_inf><gloss>examination</gloss></sense></entry>
</JMdict>''', encoding="utf-8")
    return source


@pytest.fixture
def dictionary_path(jmdict_source, tmp_path):
    path = tmp_path / "dictionary.sqlite3"
    import_jmdict(jmdict_source, path)
    return path
