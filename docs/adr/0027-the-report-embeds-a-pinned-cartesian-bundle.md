# 0027 — The report embeds a pinned plotly.js cartesian bundle, with its licences

**Status:** Proposed (2026-10-18). Supersedes the bundle source in 0006; the rest of 0006 stands.

## Context

Every HTML report embedded the full plotly.js bundle that the installed plotly Python package
carries: 4.8 MB with plotly 7.1.0 (plotly.js 4.1.1), 98% of the report. It had three costs.

- **Licences.** The bundle keeps a banner, "Licensed under the MIT license", but not the MIT
  permission notice, and it carries code under MIT, BSD-3-Clause and other licences whose texts
  are absent. MIT says "the above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software"; BSD-3-Clause says "Redistributions in binary
  form must reproduce the above copyright notice, this list of conditions and the following
  disclaimer". A report is a copy, and anyone who shares one redistributes it. Measured on
  2026-10-18: the report contained no licence text.
- **Size and drift.** The bundle is whatever plotly version the user has installed
  (`plotly = ">=5.20,<8.0"`); 7.0.0 to 7.1.0 added 522,418 bytes to every report.
- **Surface.** The full bundle holds map engines and 55 remote URLs for trace types the report
  never draws.

The report draws four trace types: bar, pie and scatter from Python, and the commit heatmap from
the page's own script. The plotly.js basic bundle (1.19 MB) was tried first and has no heatmap;
plotly.js drew the heatmap as a scatter, without an error, and the comparison in headless
Chromium caught it. The cartesian bundle (1.50 MB) registers all four.

## Decision

**Reveille ships `plotly.js-cartesian-dist-min` at a pinned version in `src/reveille/vendor/`, and
every HTML report embeds that bundle and the licence of every package it carries.**

- `scripts/vendor_plotly.py <version>` is the only way the files change. It downloads from the npm
  registry, checks each tarball against its published `sha512` integrity, traces which packages the
  bundle carries, and writes the bundle byte for byte, a pin record (`plotly-cartesian.json`) and
  `THIRD-PARTY-NOTICES.txt`. The trace starts from every `require` reachable from
  `lib/index-cartesian.js` in the plotly.js source, then follows each package's declared
  dependencies and every bare `require` in its code, resolved through plotly.js's lockfile at the
  same tag: esbuild bundles the npm package for a Node built-in such as `buffer` or `assert` when
  one is installed. A package reached only for a stylesheet (maplibre-gl) contributes that file
  alone. For 4.1.1 the trace lists 84 package versions under MIT, ISC, BSD-3-Clause, Zlib and
  BlueOak-1.0.0. The unminified `plotly.js-cartesian-dist` 4.1.1 names 71 packages in esbuild's
  module comments, all of them in the trace; the other 13 versions, `sax` (the only BlueOak-1.0.0
  one) among them, are listed but not bundled.
- The report carries the notices in a collapsed "Third-party licences" section after the footer.
- plotly Python stays a dependency: it builds the figure specifications. Its own bundle is no
  longer read.
- Tests: the bundle's hash matches the pin record; every trace type the report draws, from Python
  or from the page script, is registered in the bundle; every package in the pin record has a
  notice, and every package the bundle's licence block names is in the pin record; a rendered
  report carries the notices.

## Consequences

- The report is 1.7 MB instead of 4.9 MB (1,688,634 bytes for a one-commit repository, measured
  2026-10-18; 118,473 bytes of it the notices), and does not change with the installed plotly version.
- 24 of 24 charts render with the same SVG as with the full bundle in headless Chromium, light and
  dark, apart from Plotly's random element ids.
- A plotly.js security fix reaches reports only when the maintainer reruns the script; it no
  longer arrives with a plotly upgrade. The pin record names the version, so this is visible.
- The wheel and sdist now carry third-party JavaScript under those licences, with its notices.
  The package's licence metadata still says Apache-2.0, which covers Reveille's own code; the
  vendored files carry their own.
- The trace is from source at package level, so a package esbuild left out may still be listed
  (a superset errs towards more notices, not fewer). One bundled from outside that graph would be
  missed; the bundle's own "Bundled license information" block names seven packages, the
  polyfills `assert` and `safe-buffer` among them, and a test fails unless the trace lists each.
- Drawing a fifth trace type outside the cartesian set means choosing another bundle, and the
  trace-type test says so.
