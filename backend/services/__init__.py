"""
backend/services/ — Business logic and service layer for Golteris.

Service modules encapsulate domain logic that is shared between API routes,
the background worker, and agent orchestration. They operate on SQLAlchemy
sessions and models, and are the primary place where cross-cutting constraints
(C1-C7) are enforced in application code.
"""
