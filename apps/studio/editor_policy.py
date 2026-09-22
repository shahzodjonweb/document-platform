from apps.core.errors import DomainError
from .domain import allowed
COMMAND_FEATURES={'add_text':'editor.add_text','highlight':'editor.highlight','note':'editor.annotate','draw':'editor.annotate','fill_form':'editor.fill_forms','signature':'editor.signature_image','insert_image':'editor.insert_images','replace_text':'editor.existing_text','replace_image':'editor.replace_images','remove_image':'editor.replace_images','redact':'editor.redact'}
def validate_commands_access(account,commands):
    if not isinstance(commands,list):raise DomainError('invalid_parameters')
    for command in commands:
        if not isinstance(command,dict):raise DomainError('invalid_parameters')
        fid=COMMAND_FEATURES.get(command.get('type',command.get('action')))
        if not fid:raise DomainError('invalid_parameters')
        if not allowed(account,fid):raise DomainError('feature_not_in_plan',403)
