"""Fixtures for the in-process Flet UI integration suite.

Each test composes the real application with test doubles and mounts it on a
recording page. Nothing here needs Flutter or a display.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest_asyncio

from integration_tests.harness import Harness, build_harness

StartApp = Callable[..., Awaitable[Harness]]


@pytest_asyncio.fixture
async def start_test_app(tmp_path: Path) -> AsyncIterator[StartApp]:
    """Yield a factory that mounts one composed application per call."""

    running: list[Harness] = []

    async def _start(
        *,
        with_initial_profile: bool = False,
        release_on_run: bool = False,
        ndi_available: bool = False,
    ) -> Harness:
        harness = build_harness(
            tmp_path,
            with_initial_profile=with_initial_profile,
            release_on_run=release_on_run,
            ndi_available=ndi_available,
        )
        await harness.mount()
        running.append(harness)
        return harness

    try:
        yield _start
    finally:
        for harness in running:
            await harness.shutdown()
