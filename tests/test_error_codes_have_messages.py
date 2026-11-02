"""error_data falls back silently to a general message, so a code with no entry is only noticed by the customer who gets it."""
import ast
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parent.parent
RAISERS={'DomainError','ProcessorError'}


def literals(node):
    """The strings an expression can be: `'a'`, or `'a' if x else 'b'`. A variable is checked where it was raised."""
    if isinstance(node,ast.Constant) and isinstance(node.value,str):return {node.value}
    if isinstance(node,ast.IfExp):return literals(node.body)|literals(node.orelse)
    return set()


def raised_codes():
    codes={}
    for folder in ('apps','processors'):
        for path in sorted((ROOT/folder).rglob('*.py')):
            if 'tests' in path.parts or 'migrations' in path.parts:continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node,ast.Call) and getattr(node.func,'id',getattr(node.func,'attr','')) in RAISERS and node.args:
                    for code in literals(node.args[0]):codes.setdefault(code,f'{path.relative_to(ROOT)}:{node.lineno}')
    return codes


def test_the_scan_sees_the_codes_it_is_there_for():
    codes=raised_codes()
    assert len(codes)>100
    assert {'rate_limited','invalid_editor_command','signed_pdf_unsupported','version_conflict'}<=codes.keys()


@pytest.mark.parametrize('locale',['en','uz','ru'])
def test_every_code_raised_has_a_message(locale):
    messages=json.loads((ROOT/'i18n'/f'{locale}.json').read_text(encoding='utf-8'))
    missing={code:where for code,where in raised_codes().items() if not messages.get(code)}
    assert not missing,f'No {locale} message for: {missing}'
