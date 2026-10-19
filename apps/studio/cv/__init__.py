"""AI CV: the templates a CV can wear and the renderer that sets one on one or two A4 pages.

`templates` is the catalogue (fifty looks in six categories) and the model's
choice; `render.render_cv` turns a CV's content into the PDF; `check.problems`
reads a rendered CV back and lists anything a reader would notice; `sample`
holds the fictional CVs the picker's thumbnails and the tests are drawn from.
Nothing here is imported by the generation pipeline until the CV service is
switched on.
"""
