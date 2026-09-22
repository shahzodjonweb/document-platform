"""Actual multilingual OOXML conversion through the configured local engine."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import zipfile
import pytest
from pypdf import PdfReader
from processors import ProcessorError, capabilities, inspect_file
from processors.engine import office_runtime
from processors.sandbox import execute_sandbox, inspect_file_sandbox

FIXTURES = Path(__file__).resolve().parent.parent / 'processors' / 'fixtures'
AVAILABLE = office_runtime()['available']
REQUIRES_OFFICE = pytest.mark.skipif(not AVAILABLE, reason='No working configured LibreOffice runtime; Office capability remains unavailable')
PHRASES = ('Document pages remain readable', 'Hujjat sahifalari aniq ko‘rinadi', 'Страницы документа остаются читаемыми')


@REQUIRES_OFFICE
@pytest.mark.parametrize('kind', ['docx', 'pptx'])
def test_office_preflight_counts_real_converted_pages(kind):
    metadata = inspect_file_sandbox(FIXTURES / f'office-multilingual.{kind}')
    assert metadata['page_count'] == 3
    assert metadata['kind'] == kind
    assert metadata['preflight_kind'] == 'libreoffice_pdf'
    assert metadata['office_engine'].startswith('LibreOffice')


@REQUIRES_OFFICE
@pytest.mark.parametrize(('kind', 'feature'), [('docx', 'convert.word_to_pdf'), ('pptx', 'convert.pptx_to_pdf')])
def test_office_conversion_preserves_all_three_languages(kind, feature, tmp_path):
    result = execute_sandbox(feature, [FIXTURES / f'office-multilingual.{kind}'], {}, tmp_path / kind)
    artifact = result['artifacts'][0]
    reader = PdfReader(artifact['path'])
    assert artifact['mime_type'] == 'application/pdf'
    assert artifact['page_count'] == result['actual_page_units'] == len(reader.pages) == 3
    for page, expected in zip(reader.pages, PHRASES):
        assert expected in page.extract_text()
    assert 'libreoffice' in result['metadata']['engine_versions']
    assert len(list((tmp_path / kind).iterdir())) == 1, 'Private Office source/profile must be removed after the attempt'


@REQUIRES_OFFICE
def test_concurrent_office_jobs_use_independent_profiles(tmp_path):
    def convert(kind, feature):
        return execute_sandbox(feature, [FIXTURES / f'office-multilingual.{kind}'], {}, tmp_path / kind)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(convert, 'docx', 'convert.word_to_pdf'), executor.submit(convert, 'pptx', 'convert.pptx_to_pdf')]
        outputs = [future.result()['artifacts'][0]['path'] for future in futures]
    assert len(set(outputs)) == 2
    assert all(len(PdfReader(path).pages) == 3 for path in outputs)


def test_unavailable_configured_office_fails_closed(monkeypatch):
    monkeypatch.setenv('PDFMASTER_SOFFICE_BIN', '/nonexistent/pdfmaster/soffice')
    office_runtime.cache_clear()
    try:
        assert capabilities()['convert.word_to_pdf']['available'] is False
        assert capabilities()['convert.pptx_to_pdf']['available'] is False
    finally:
        office_runtime.cache_clear()


def test_external_office_relationship_rejected_before_conversion(tmp_path):
    target = tmp_path / 'external.docx'
    relationship = 'word/_rels/document.xml.rels'
    with zipfile.ZipFile(FIXTURES / 'office-multilingual.docx') as original, zipfile.ZipFile(target, 'w') as modified:
        for entry in original.infolist():
            if entry.filename != relationship:
                modified.writestr(entry, original.read(entry))
        modified.writestr(relationship, '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.invalid/private" TargetMode="External" /></Relationships>')
    with pytest.raises(ProcessorError) as error:
        inspect_file(target)
    assert error.value.code == 'external_content_unsupported'


def legacy_viewer_pdf(path, *, action=None, extra_action=False, indirect=False, invalid_page=False):
    """Serialize the initial-view destination written by older LibreOffice."""
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject,DictionaryObject,NameObject,NullObject,NumberObject,TextStringObject
    from tests.test_processors import pdf
    source=pdf(path.with_name('source.pdf'),('English. Document pages remain readable.',))
    writer=PdfWriter(clone_from=source)
    reference=writer.pages[0].indirect_reference
    if invalid_page:reference=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/NotAPage')}))
    destination=ArrayObject([reference,NameObject('/XYZ'),NullObject(),NullObject(),NumberObject(0)])
    if action is not None:
        destination=DictionaryObject({NameObject('/S'):NameObject(action),NameObject('/D'):destination,NameObject('/JS'):TextStringObject('app.alert("blocked")')})
    if indirect:destination=writer._add_object(destination)
    writer.root_object[NameObject('/OpenAction')]=destination
    if extra_action:writer.root_object[NameObject('/AA')]=DictionaryObject({NameObject('/WC'):DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject('app.alert("blocked")')})})
    writer.write(path)
    return path


@pytest.mark.parametrize('indirect',[False,True])
def test_only_converter_output_normalizes_legacy_initial_page_hint(tmp_path,indirect):
    from processors.engine import _normalize_office_viewer_hint
    path=legacy_viewer_pdf(tmp_path/'converted.pdf',indirect=indirect)
    # The same uploaded PDF remains outside the accepted active-content policy.
    with pytest.raises(ProcessorError) as error:inspect_file(path)
    assert error.value.code=='active_content_unsupported'
    _normalize_office_viewer_hint(path)
    reader=PdfReader(path)
    assert '/OpenAction' not in reader.root_object
    assert 'Document pages remain readable.' in reader.pages[0].extract_text()
    assert inspect_file(path)['page_count']==1


@pytest.mark.parametrize('action',['/JavaScript','/Launch','/GoToR','/GoTo','/URI'])
def test_converter_viewer_normalization_never_accepts_action_dictionaries(tmp_path,action):
    from processors.engine import _normalize_office_viewer_hint
    path=legacy_viewer_pdf(tmp_path/'converted.pdf',action=action)
    original=path.read_bytes()
    with pytest.raises(ProcessorError) as error:_normalize_office_viewer_hint(path)
    assert error.value.code=='active_content_unsupported' and path.read_bytes()==original


@pytest.mark.parametrize('malicious',['other_active_content','nonpage_destination','nested_dictionary','chained_destination'])
def test_converter_viewer_hint_cannot_mask_active_or_malformed_content(tmp_path,malicious):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,TextStringObject
    from processors.engine import _normalize_office_viewer_hint
    path=legacy_viewer_pdf(tmp_path/'converted.pdf',extra_action=malicious=='other_active_content',invalid_page=malicious=='nonpage_destination')
    if malicious in ('nested_dictionary','chained_destination'):
        writer=PdfWriter(clone_from=path)
        action=DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject('blocked')})
        if malicious=='nested_dictionary':writer.root_object['/OpenAction'][2]=action
        else:writer.root_object['/OpenAction'].append(action)
        writer.write(path)
    with pytest.raises(ProcessorError) as error:_normalize_office_viewer_hint(path)
    assert error.value.code=='active_content_unsupported'


@REQUIRES_OFFICE
def test_real_office_output_legacy_hint_normalized_before_artifact_validation(tmp_path,monkeypatch):
    """Exercise the real converter entry point even on newer LibreOffice builds."""
    import processors.engine as engine
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject,NameObject,NullObject,NumberObject
    original=engine._normalize_office_viewer_hint
    normalized=[]
    def legacy_output(path):
        writer=PdfWriter(clone_from=path)
        writer.root_object[NameObject('/OpenAction')]=ArrayObject([writer.pages[0].indirect_reference,NameObject('/XYZ'),NullObject(),NullObject(),NumberObject(0)])
        writer.write(path)
        original(path);normalized.append(True)
    monkeypatch.setattr(engine,'_normalize_office_viewer_hint',legacy_output)
    metadata=inspect_file(FIXTURES/'office-multilingual.docx')
    assert metadata['page_count']==3 and normalized==[True]
