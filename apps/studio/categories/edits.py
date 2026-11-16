"""How a change request to a category paper is read (architecture 3.7): today's reader until E1 builds it.

A paper's change is the CV's narrowing (a new look is refused, a new total
sets the length, nothing is reshaped). Until that exists, `read` answers None
and the domain reads the request as it reads any document's.
"""


def read(request, entry, *, fmt=None, sections=None, **context):
    """The Edit for this request to a paper of `entry`, or None for today's reader."""
    return None
