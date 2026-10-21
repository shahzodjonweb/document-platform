"""AI CV: the templates a CV can wear and the renderer that sets one on one or two A4 pages.

`templates` is the catalogue (fifty looks in six categories) and the model's
choice; `render.render_cv` turns a CV's content into the PDF; `check.problems`
reads a rendered CV back and lists anything a reader would notice; `sample`
holds the fictional CVs the picker's thumbnails and the tests are drawn from.
`sources` is where a CV's facts come from (one message, a LinkedIn PDF or
screenshots, an old CV), and `reads` the queue its files wait in until
`runreader` reads them, one at a time (`reader` is the child that does).
Nothing here is imported by the generation pipeline until the CV service is
switched on.
"""
