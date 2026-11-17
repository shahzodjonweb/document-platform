"""How a change request to a category paper is read (architecture 3.7).

A paper is drawn by its template from a fixed list of parts, so a change can
rewrite what the parts say but not what the paper is. The request is read by
today's reader (apps/studio/edits.py), whose patterns are proven on real
requests, and then narrowed as a CV's change is (domain._prepare_draft):

- a new look is refused: the template is the look, and nothing is chosen again;
- no part is added, removed, merged or moved, so pages added or taken away, a
  plan, an introduction or a title page asked for, and characters named are
  not read: "Kirish qo‘shing" on a paper that has one is answered by the
  document as it is, and on one that has none by its own parts;
- pictures are not read: no template places a photograph;
- a new total is read only for an entry whose length is a count (a 10-page
  mustaqil ish made 15), and sets its pages, not its parts; a fixed paper (an
  ariza) or one whose length follows its questions (a test) keeps its own;
- questions are read only for an entry that has them, and a test's are its
  body, so they may be added or cut to a number but never taken away;
- more, fuller information and another file format are kept as read: the
  domain answers a request for the file alone (format_only_change).

Nothing here is ever structural, so the prompt revises the parts in place and
never reshapes the paper (prompting.structural).
"""
from .. import edits as editing


def read(request, entry, *, fmt=None, sections=None, questions=0, **context):
    """The narrowed Edit for this request to a paper of `entry`, or None for today's reader (anything not a paper)."""
    if entry is None or entry.service != 'pdf':
        return None
    found = editing.read(request, fmt=fmt or 'pdf', sections=sections, questions=questions)
    edit = editing.Edit(format=found.format, format_only=found.format_only, expand=found.expand)
    if entry.length['mode'] == 'count':
        edit.total = found.total
    if entry.raw['questions']['max']:
        # A test's questions are what it is: removed, it would be a page of instructions sized for the default
        # count. A removal is therefore not read for an entry whose length follows them.
        removing = found.questions == 'remove' and entry.length['mode'] == 'derived'
        if not removing:
            edit.questions, edit.question_count = found.questions, found.question_count
            edit.more_questions = found.more_questions
    return edit
