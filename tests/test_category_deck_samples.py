"""The sample content of the ten deck categories, read and finished as the deck sample tool does.

The samples (apps/studio/categories/samples/<entry>/<case>.json) are what the
sample tool draws beside each deck's mock-up before a native reader and the
owner look at it. They are read by the tool's own `load` and `draft`, so a
file the tool cannot read fails here rather than drawing every slide as a
blank form. Each sample is finished at several lengths in three languages as
a job finishes a model's answer: it must come out with exactly its slide
count and with nothing taken out, since a sample that the finish has to blank
shows the owner a deck no customer should get. Every person, organisation and
figure in them is invented.
"""
from apps.studio import pages, title_lines
from apps.studio.categories import catalogue, finish, sample, skeleton
from apps.studio.categories.catalogue import LOCALES

DECKS = ('slides.mavzu', 'slides.himoya', 'slides.dars', 'slides.tadbir.tarbiyaviy_soat', 'slides.tadbir.bayram',
         'slides.tadbir.ota_onalar', 'slides.tadbir.pedkengash', 'slides.pitch', 'slides.hisobot', 'slides.kompaniya')
KEYS = {'entry', 'case', 'about', 'prompt', 'title', 'slots'}
SECTION_KEYS = {'heading', 'body', 'notes', 'items', 'columns', 'layout'}


def lengths(entry):
    """The lengths a sample is finished at: the least, the default, 10 and the most the entry takes."""
    bounds = entry.length
    return sorted({bounds['min'], bounds['default'], 10, bounds['max']} & set(range(bounds['min'], bounds['max'] + 1)))


def finished(entry, given, locale, length):
    """(sections, codes) of a deck drawn from `given` and finished, as the sample tool draws it."""
    data, content = sample.draft(entry, given, locale, length)
    content = title_lines.apply(data, content)
    codes = []
    content, _ = finish.apply(data, content, file_names=[], codes=codes)
    return content['sections'], codes


def test_every_deck_entry_has_both_cases_and_nothing_else_has_samples():
    root = sample.HERE / 'samples'
    assert sorted(path.name for path in root.iterdir() if path.is_dir()) == sorted(DECKS)
    for entry_id in DECKS:
        assert catalogue.get(entry_id).service == 'slides'
        for case in sample.CASES:
            assert sample.sample_path(entry_id, case) == root / entry_id / f'{case}.json'


def every_sample():
    """(entry, case, sample) of every deck entry's two cases, read by the sample tool's own `load`."""
    for entry_id in DECKS:
        for case in sample.CASES:
            yield catalogue.get(entry_id), case, sample.load(entry_id, case)


def test_a_sample_is_in_the_sample_tools_format():
    for entry, case, given in every_sample():
        assert set(given) <= KEYS and given['entry'] == entry.id and given['case'] == case
        assert set(given['prompt']) == set(LOCALES) and all(given['prompt'][locale].strip() for locale in LOCALES)
        assert given['slots'], 'a sample with no slots is drawn as blank forms'
        for part_id, instances in given['slots'].items():
            assert entry.part(part_id) is not None, f'{entry.id} has no part {part_id}'
            for instance in instances:
                assert set(instance) == set(LOCALES)
                assert all(set(instance[locale]) <= SECTION_KEYS for locale in LOCALES)


def test_a_sample_is_finished_to_its_count_with_nothing_taken_out():
    for entry, case, given in every_sample():
        for locale in LOCALES:
            for length in lengths(entry):
                sections, codes = finished(entry, given, locale, length)
                assert len(sections) == length, (entry.id, case, locale, length)
                assert codes == [], (entry.id, case, locale, length, codes)


def test_every_slot_a_figures_sample_reaches_at_its_own_length_has_content():
    # The figures case is one of the entry's own examples; at the count its message asks for (or its cue's
    # default), no slot of it may fall back to the tool's blank form, or the owner reviews a form where the
    # content should be.
    for entry_id in DECKS:
        entry = catalogue.get(entry_id)
        given = sample.load(entry_id, 'figures')
        for locale in LOCALES:
            data, _ = sample.draft(entry, given, locale, entry.length['default'])
            cues = skeleton.cues_of(data)
            length = skeleton.length(entry, asked=pages.requested_pages(data['prompt']), cues=cues)
            missing = [use.part['id'] for use in skeleton.parts(entry, length, cues)
                       if use.part['id'] not in given['slots']]
            assert missing == [], (entry_id, locale, missing)


def test_a_constitution_day_deck_is_six_slides_and_keeps_its_cover():
    # Konstitutsiya kuni is not a fact day: every sentence about a constitution is a legal one, which the facts
    # guard removes unless the customer wrote it, so the entry neither lists its facts nor quotes it 10 slides.
    entry = catalogue.get('slides.tadbir.bayram')
    given = {'prompt': {'uz': 'Konstitutsiya kuni tadbiriga slaydlar kerak: 21-maktab, 7-B sinf.',
                        'ru': 'Нужны слайды ко Дню Конституции: школа № 21, 7 «Б» класс.',
                        'en': 'I need slides for a Constitution Day event: School No. 21, class 7-B.'},
             'slots': {'cover': [{'uz': {'layout': 'cover', 'heading': 'Konstitutsiya kuni',
                                         'body': '21-maktab, 7-B sinf'},
                                  'ru': {'layout': 'cover', 'heading': 'День Конституции',
                                         'body': 'Школа № 21, 7 «Б» класс'},
                                  'en': {'layout': 'cover', 'heading': 'Constitution Day',
                                         'body': 'School No. 21, class 7-B'}}]}}
    for locale in LOCALES:
        data, _ = sample.draft(entry, given, locale, entry.length['default'])
        assert skeleton.length(entry, cues=skeleton.cues_of(data)) == 6
        sections, codes = finished(entry, given, locale, 6)
        assert codes == [], (locale, codes)
        cover = given['slots']['cover'][0][locale]
        assert sections[0]['heading'] == cover['heading'] and cover['body'] in sections[0]['body']
