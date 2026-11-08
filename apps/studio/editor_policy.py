from apps.core.errors import DomainError
from .domain import allowed,pack,unpack
COMMAND_FEATURES={'add_text':'editor.add_text','highlight':'editor.highlight','note':'editor.annotate','draw':'editor.annotate','fill_form':'editor.fill_forms','signature':'editor.signature_image','insert_image':'editor.insert_images','replace_text':'editor.existing_text','replace_image':'editor.replace_images','remove_image':'editor.replace_images','redact':'editor.redact','edit_text':'editor.existing_text','whiteout':'editor.add_text','rotate_page':'editor.visual','delete_page':'editor.visual','reorder':'editor.visual'}
def stored_commands(document):
    """A draft's marks: the one way to read them.

    Encrypted on every write since 0010, with the version they were written at, and `commands`
    written beside them until 0012 for the image before this one. That image
    writes only `commands` and moves the version on, mid-deploy or after a
    rollback, so an encrypted copy of another version is older than `commands`,
    even when the customer has just emptied them.
    """
    if document.encrypted_commands is None:return document.commands
    packed=unpack(document.encrypted_commands)
    return packed['commands'] if packed['version']==document.version else document.commands
def store_commands(document,commands):
    """Sets a draft's marks and moves its version on: the one way to write them. The caller saves the fields in COMMAND_COLUMNS."""
    document.version+=1;document.commands=commands;document.encrypted_commands=pack({'version':document.version,'commands':commands})
COMMAND_COLUMNS=['version','commands','encrypted_commands']
def validate_commands_access(account,commands):
    if not isinstance(commands,list):raise DomainError('invalid_parameters')
    for command in commands:
        if not isinstance(command,dict):raise DomainError('invalid_parameters')
        fid=COMMAND_FEATURES.get(command.get('type',command.get('action')))
        if not fid:raise DomainError('invalid_parameters')
        if not allowed(account,fid):raise DomainError('feature_not_in_plan',403)
def require_text_edit(commands):
    """Changing a document's own words waits for its switch (/ops/editor, text_edit): refused at a quote and when the job runs, naming the change.

    Never at a save, so a draft's autosave outlives the switch being turned off.
    The index also rides on the error, where execute_job reads a failed command's.
    """
    found=[index for index,command in enumerate(commands if isinstance(commands,list) else []) if isinstance(command,dict) and command.get('type')=='edit_text']
    if not found:return
    from operations.integrations import editor_flags
    if editor_flags()['text_edit']:return
    error=DomainError('editor_text_edit_unavailable',409,{'index':found[0]});error.index=found[0]
    raise error
