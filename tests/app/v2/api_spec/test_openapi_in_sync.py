import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_openapi  # noqa: E402  (import after sys.path edit)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_generated_openapi_matches_committed_file(lang):
    committed = (ROOT / "openapi" / f"v2-notifications-api-{lang}.yaml").read_text(encoding="utf-8")

    assert (
        generate_openapi.render(lang) == committed
    ), f"openapi/v2-notifications-api-{lang}.yaml is out of date. Run 'make generate-openapi' and commit the changes."
