"""Editor helpers, run in the bounded child (processors/__main__.py, operation `helper`) as a file is made.

A helper answers a question about a customer's file before a send: it makes no
file of its own, is no feature (nothing in /catalog, nothing billed) and says
only pages, codes and numbers.

  editor.blackout   which pages with a black-out box keep their words, and why
                    each other one becomes a picture (blackout.check)
"""
from __future__ import annotations
from pathlib import Path


def run(name,input_paths,parameters,output_dir,pdfcraft=False):
    """`pdfcraft` is the server's switch, as for a send."""
    from .engine import ProcessorError,_regular_file,inspect_file,normalize_parameters
    if name!='editor.blackout':raise ProcessorError('invalid_operation')
    if not isinstance(input_paths,list) or len(input_paths)!=1:raise ProcessorError('invalid_inputs')
    path=_regular_file(input_paths[0])
    metadata=inspect_file(path,office_preflight=False)
    if metadata['kind']!='pdf':raise ProcessorError('unsupported_type')
    if metadata.get('password_required'):raise ProcessorError('password_required')
    commands=(parameters or {}).get('commands') if isinstance(parameters,dict) else None
    if not isinstance(commands,list) or not commands or any(not isinstance(c,dict) or c.get('type')!='redact' for c in commands):raise ProcessorError('invalid_parameters')
    commands=normalize_parameters('editor.visual',{'commands':commands,'accept_rasterization':True,'combined':True},[metadata])['commands']
    out=Path(output_dir)
    if out.is_symlink():raise ProcessorError('unsafe_path')
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    if any(out.iterdir()):raise ProcessorError('output_directory_not_empty')
    from .blackout import check
    outcome=check(path,commands,out/'blackout',pdfcraft)
    return {'pages':{str(page):reason for page,reason in sorted(outcome.items())}}
