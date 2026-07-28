# UI/UX review

Status: accepted for the secure MVP, 2026-07-28.

## Acceptance evidence

The implemented experience was inspected against the running FastAPI app, not a
standalone mock. Orchestrator browser smoke evidence covered:

- Desktop layout: hero/scope warning, upload workspace, assurance panel and custom
  pattern controls render as a cohesive local-only product with no external assets.
- 320 px layout: content reflows to one column without horizontal overflow; primary
  actions remain full-width and touch-sized.
- Keyboard/accessibility basics: a skip link, semantic headings and landmarks,
  programmatic file/form labels, visible focus, live progress/error regions and a
  focused result state are present. Motion is reduced when the OS requests it.
- File states: supported-format and effective size/page guidance appears beside the
  drop zone; invalid selection and processing failure produce fixed, actionable
  messages without document contents, paths or stack traces.
- Verified result: the download and output-only preview have no URL while idle or
  on failure. They receive an in-memory blob URL only after a PDF response includes
  `X-Redaction-Verified: true`. The summary shows neutral target and page counts,
  never matched values.
- Pattern flow: the protected `AU_CENTRELINK_CRN` recognizer is visible and has no
  mutation controls. Add/edit/enable/disable/delete use labeled controls and bounded
  client validation; disabling and deleting require confirmation.

Automated coverage verifies the home route, no premature download URL, supported
format/warning copy, responsive CSS, live status semantics, user pattern fields,
protected-pattern API behavior, fixed safe errors, verified-only response headers,
and fail-closed verification behavior.

## Security and privacy decisions

- No input preview is created. After verification, the browser may preview only the
  newly generated image-only output PDF.
- Output bytes stay in an in-memory browser object URL, which is revoked on reset or
  navigation. No persistent result route or enumerable job identifier exists.
- CSP permits only same-origin scripts/styles/connections and a `blob:` frame for
  the verified preview. There are no CDNs, web fonts, analytics or remote calls.
- Unsafe browser methods reject `Sec-Fetch-Site: cross-site` and reject an `Origin`
  whose authority differs from `Host`. This protects the local UI against cross-site
  form/API mutations. Non-browser API clients without browser metadata remain
  supported; they are outside the browser CSRF threat model.

## Residual UX limits

- Progress is exact only during upload; OCR/redaction/verification stages are
  announced but the backend does not expose granular percentages.
- Native confirmation dialogs are intentionally used for destructive pattern
  actions. They are accessible and dependable, but not visually branded.
- The output is image-only by design, so its original searchable text and document
  accessibility structure cannot be preserved.
