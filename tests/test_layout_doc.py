"""``docs/layout.md`` shows what the codecs write, not what someone remembered.

Every tree in the chapter is a generated block (``scripts/layout_examples.py``):
the examples are built from molrec's models and written by molrec's codecs.
These tests regenerate them and fail on any drift, and check that every
relative link of the chapter lands on a page and a heading that exist.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"


@pytest.fixture(scope="module")
def generator():
    """``scripts/layout_examples.py``, imported from its path."""
    spec = importlib.util.spec_from_file_location(
        "layout_examples", REPO / "scripts" / "layout_examples.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated(generator) -> dict[str, str]:
    return generator.render_all()


def test_every_generated_block_is_what_the_codecs_write(generator, generated) -> None:
    written = generator.doc_blocks(generator.DOC.read_text())
    assert set(written) == set(generated), "run scripts/layout_examples.py --write"
    for name, body in generated.items():
        assert written[name] == body, (
            f"docs/layout.md block {name!r} has drifted: run scripts/layout_examples.py --write"
        )


def test_the_generator_is_deterministic(generator, generated) -> None:
    assert generator.render_all() == generated


def _slug(heading: str) -> str:
    """The anchor the docs build gives a heading (Python-Markdown's toc slug)."""
    text = re.sub(r"[`*]", "", heading).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def _anchors(page: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", page.read_text(), flags=re.DOTALL)
    return {_slug(match) for match in re.findall(r"^#{1,6}\s+(.+)$", text, flags=re.MULTILINE)}


def test_every_relative_link_of_the_chapter_resolves() -> None:
    page = DOCS / "layout.md"
    text = re.sub(r"```.*?```", "", page.read_text(), flags=re.DOTALL)
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+://", target):
            continue
        path, _, anchor = target.partition("#")
        resolved = (page.parent / path).resolve() if path else page
        if not resolved.is_file() or (anchor and anchor not in _anchors(resolved)):
            broken.append(target)
    assert not broken, f"broken links in docs/layout.md: {broken}"
