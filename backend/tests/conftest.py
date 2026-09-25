"""pytest 公共夹具。"""

from __future__ import annotations

import pytest

from tests._harness import isolate_data_dir


@pytest.fixture()
def temp_data_dir():
    return isolate_data_dir()
