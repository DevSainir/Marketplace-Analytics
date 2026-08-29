"""Organisations: the top-level tenancy, its members and its subscription.

A customer company owns workspaces and users. Everything about access —
which tenant a request belongs to, what its caller may do, and whether that
tenant has paid — is decided here, and consumed elsewhere through
``contract.py``.
"""
