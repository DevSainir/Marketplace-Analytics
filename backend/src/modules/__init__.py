"""Isolated business domains (bounded contexts) of the modular monolith.

Each module owns its models, schemas, repositories, services, DI wiring, and
routers. Cross-module communication is permitted **only** through a module's
public ``contract`` — direct imports of another module's internals are
forbidden by the architecture rules.
"""
