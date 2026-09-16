"""«Сводка» — the account-level read of one settlement window.

Owns no tables. Every figure is composed through the ``finreports`` and
``monitoring`` contracts, which is the point: the numbers a seller reads here
must be the same ones «По артикулам» shows, and the only way to guarantee that
is to derive them from the same reconciled cut rather than from a second query.
"""
