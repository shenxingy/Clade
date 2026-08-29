# Presentation Surface Adapter

Load this reference for slides, pitch decks, projected reports, and other
surfaces consumed at presentation distance rather than through direct browsing.

## Presentation contract

- Give every slide one dominant thesis. Use supporting evidence and metadata as
  secondary and tertiary layers rather than equal cards.
- Design for the audience's distance, room, display, and speaking context. A
  slide is not a document page and should not require silent close reading while
  someone is presenting.
- Keep audience-facing body copy at least 18pt where possible. Treat roughly
  13pt as metadata-only and keep the main slide near 70 words or fewer.
- Use heavy dark, saturated, photographic, or textured surfaces as focal beats,
  not as decoration behind every sentence.
- Keep charts honest and legible: label the claim, unit, time range, source, and
  meaningful comparison; do not use visual effects to inflate differences.
- Preserve the project's brand assets and typography, but let legibility at
  distance override ornamental treatments.

## Visual checkpoint

- Build from one content model when possible, then render to slide images or PDF
  before judging. Source coordinates are not evidence of the final pixels.
- Review a contact sheet for narrative rhythm and individual slides at fit-to-
  screen or presentation distance.
- Use one recommended direction. Produce an alternative only for a real story,
  density, or tone tradeoff.

## Verification

- Run `design-lint deck <file.pptx>` for source metrics and
  `design-lint render <slide-images>` after rendering.
- Check the rendered result for clipped text, font substitution, low contrast,
  chart labels, image resolution, safe margins, and unsupported effects.
- Verify the decisive point can be identified in about two seconds without
  reading body copy.
- Rehearse important sequences in the actual presentation mode and target
  aspect ratio. Mark projector/room testing as unrun when it did not occur.
