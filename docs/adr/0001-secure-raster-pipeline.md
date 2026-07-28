# ADR 0001: Use a raster-only redaction and output pipeline

- Status: accepted
- Date: 2026-07-28

## Context

PDF redaction annotations, drawn rectangles, content-stream edits, and source-PDF
rewrites can leave recoverable text, objects, attachments, prior revisions or
pixels. Preserving searchability conflicts with the MVP's irreversible-output
goal.

## Decision

Rasterize every input page at configurable high DPI, paint target pixels on
application-owned rasters, and construct a brand-new image-only PDF. The builder
accepts rasters and never a source PDF object. Independently verify the output
before it is released.

DOCX is converted to PDF only as an intermediate and then enters the identical
raster pipeline. Image inputs are decoded to canonical rasters and also produce a
PDF output.

## Consequences

- Source PDF interactive structures and text are discarded by construction.
- Output is not searchable or accessible as text and can be larger.
- Render DPI must balance OCR accuracy, output size and resource exhaustion.
- Visual fidelity depends on the rasterizer and font availability.
- Structural and re-OCR verification remain necessary defense in depth.
