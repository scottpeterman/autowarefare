"""
World → view → NDC projection helpers.

Stub for the next milestone (first-person camera + render). Will hold the
single, consistent projection path that Heminger's JS got wrong by stacking
two perspective divides with different constants (see transition doc:
"camera.js:50 — Inconsistent projection math").

Plan:
  - Use ``glMatrixMode(GL_PROJECTION) + gluPerspective`` for the actual
    GL projection matrix; this file's job is the small bit of numpy math
    we need outside GL — frustum culling tests, world-to-screen for
    HUD overlays, etc.
  - One field of view, one near plane, one far plane. No multipliers
    layered on top.
"""
