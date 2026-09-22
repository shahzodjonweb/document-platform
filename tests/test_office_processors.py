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
