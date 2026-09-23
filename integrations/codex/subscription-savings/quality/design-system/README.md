# Shared primitives

Opt-in CSS and a dependency-free `gameAsset(metadata, baseUrl, options)` DOM
component, usable from a React ref or a WordPress module. Import `primitives.css`
once; append the returned picture to an owned container. Pass the JSON generated
by `asset-prepare`. `priority: true` is for an above-the-fold hero only. No network
request is made for metadata; the caller supplies it. Variant URLs must be local.

Bind `--mc-text`, `--mc-font`, `--mc-border`, `--mc-action`, `--mc-action-text`,
`--mc-focus` and `--mc-surface` inside `.mc-ui` to the project's canonical tokens.
Use semantic button/link elements, labels and native disabled states. `.mc-card`,
`.mc-stack`, `.mc-icon` and `.mc-button` provide shared geometry and motion.
The project profiles reference the existing application components; adopting
these new primitives in production is a separate reviewed application change.

Asset presets process color/blur/alpha; the component adds responsive sources,
intrinsic dimensions, alt/decorative semantics, focal position and the preset's
overlay. Use `.mc-hero-copy` for the left text-safe area and a solid surface for
mobile copy when required by contrast. Focal detection is an edge heuristic;
inspect the crop and contrast before accepting a baseline.
