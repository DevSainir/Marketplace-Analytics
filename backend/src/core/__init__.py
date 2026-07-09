"""Global infrastructure: configuration, database engine, security, and DI wiring.

Everything in this package is cross-cutting and may be imported by any module
inside ``src.modules``. It must never import from a business module in return
(dependencies flow strictly downward: modules -> core / integrations).
"""
