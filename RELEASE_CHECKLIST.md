# Pre-public-release checklist

Items that must be resolved before `vsl-core` ships to a public registry (PyPI or similar). Not exhaustive project TODOs — only things that block a real release.

- [x] **Replace the `LICENSE` copyright placeholder.** Resolved 2026-07-17 — now reads `Copyright (c) 2026 Super Semantics`.
- [x] **Pick a PyPI distribution name.** `vsl-core` is already registered on PyPI by an unrelated third party (confirmed 2026-07-17 — a live `pip install vsl-core` pulls a completely unrelated empty stub package, not this code). Resolved 2026-07-18 — distribution name is now `super-semantics-vsl` (confirmed available on PyPI at decision time), set in `pyproject.toml`. The importable module name is unchanged (`import vsl_core`).
- [ ] **Actually publish `super-semantics-vsl` to PyPI.** Name is reserved in `pyproject.toml` but nothing has been built/uploaded yet — `pip install super-semantics-vsl` will 404 until this is done (`python -m build` + `twine upload dist/*`, requires a PyPI account + API token). Until then, install instructions point at `pip install git+https://github.com/4vish/VSL-Core.git` (see README's Install section).
