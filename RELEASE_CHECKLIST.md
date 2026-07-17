# Pre-public-release checklist

Items that must be resolved before `vsl-core` ships to a public registry (PyPI or similar). Not exhaustive project TODOs — only things that block a real release.

- [x] **Replace the `LICENSE` copyright placeholder.** Resolved 2026-07-17 — now reads `Copyright (c) 2026 Super Semantics`.
- [ ] **Pick a PyPI distribution name.** `vsl-core` is already registered on PyPI by an unrelated third party (confirmed 2026-07-17 — a live `pip install vsl-core` pulls a completely unrelated empty stub package, not this code). Blocks any real `pip install <name>` release until a different name is chosen (e.g. a namespaced or otherwise distinct name) and `pyproject.toml`'s `name` field is updated to match. Until resolved, install instructions point at `pip install git+https://github.com/4vish/VSL-Core.git` instead (see README's Install section).
