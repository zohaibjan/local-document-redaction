from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_delivery_files_exist() -> None:
    required = [
        "README.md",
        "AGENTS.md",
        "ORCHESTRATION_LOG.md",
        "FINAL_REPORT.md",
        "Dockerfile",
        "compose.yaml",
        ".github/workflows/ci.yml",
        "docs/architecture.md",
        "docs/threat-model.md",
        "docs/acceptance-criteria.md",
        "docs/adr/0001-secure-raster-pipeline.md",
        "examples/patterns/synthetic-case-id.json",
    ]
    assert [name for name in required if not (ROOT / name).is_file()] == []


def test_ci_is_lightweight_and_does_not_install_heavy_models() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "DOC_REDACT_OCR_BACKEND: fake" in workflow
    assert 'DOC_REDACT_VERIFY_WITH_OCR: "false"' in workflow
    assert "pip install -e '.[test]'" in workflow
    assert "pytest --cov=doc_redact" in workflow
    assert ".[ocr" not in workflow
    assert "gliner" not in workflow.casefold()


def test_container_is_non_root_bounded_and_has_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "compose.yaml").read_text()

    assert "libreoffice-writer" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert '"--limit-concurrency", "8"' in dockerfile
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "internal: true" in compose


def test_readme_states_supported_formats_locality_and_detection_limits() -> None:
    readme = (ROOT / "README.md").read_text().casefold()

    for extension in (".pdf", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        assert extension in readme
    assert "format-valid" in readme
    assert "cannot verify whether services australia actually issued" in readme
    assert "automated pii detection is not guaranteed" in readme
    assert "no document is sent to an external service" in readme
    assert "pp-ocrv5" in readme
    assert "libreoffice" in readme
    assert "image-only pdf" in readme


def test_pattern_example_is_synthetic_and_does_not_shadow_builtin() -> None:
    import json

    payload = json.loads(
        (ROOT / "examples/patterns/synthetic-case-id.json").read_text()
    )
    assert payload["identifier"] != "AU_CENTRELINK_CRN"
    assert "synthetic" in (payload["name"] + payload["output_label"]).casefold()
