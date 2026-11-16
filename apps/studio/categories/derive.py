"""Computed table cells and totals of a category paper, from the customer's own numbers: R5a builds it.

The model leaves a computed cell empty and code fills it from verified numbers
of the same row or column, so a total is never the model's arithmetic. Until
that exists, `apply` changes nothing and the cells stay empty.
"""


def apply(entry, content, trusted):
    """`content` with the computed cells of `entry`'s tables filled; for now `content` as it is."""
    return content
