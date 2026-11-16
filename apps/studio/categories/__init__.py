"""Categories of AI PDF and AI Slides: `options.category` on the two existing services.

`categories.of(data)`, `categories.live(fid)` and the rest are the catalogue's
(catalogue.py), read here on first use rather than at import, so
`python -m apps.studio.categories.catalogue --check` runs the module once and
not twice. A draft without a category never touches any of this.
"""
NAMES = frozenset((
    'get', 'of', 'bounds', 'for_feature', 'live', 'menu', 'on', 'examples', 'version', 'template', 'check',
    'CHOSEN_EVENT', 'PAPER_BOUNDS', 'Bounds', 'Entry', 'Node', 'CatalogueError'))


def __getattr__(name):
    if name in NAMES:
        from . import catalogue
        return getattr(catalogue, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
