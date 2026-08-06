# 0006 — The report is a single offline file

**Status:** Accepted

## Context

Reveille's output is meant to be forwarded: attached to an email,
embedded in Confluence, opened from a download folder. The people
reading it are frequently not the people who generated it, and often not
on the network where it was generated.

Anything the page fetches at open time is a dependency on the *reader's*
environment and a disclosure to a third party. A CDN request tells that
CDN who opened an internal engineering report and when. A web font
breaks the layout on an air-gapped machine. A sidecar asset directory
does not survive being attached to an email.

## Decision

The report is one HTML file that makes **no network requests**. The
Plotly bundle (~3.5 MB) is inlined. Fonts are system stacks. There are
no external stylesheets, scripts, or images.

A test asserts that no `<link>`, `<script>`, or `<img>` in the template
references a remote host.

## Consequences

The file is large — several megabytes, most of it Plotly. This is the
central trade, and it is accepted: a few megabytes is cheap next to a
report that fails to open.

It also means charting is expensive to change. Plotly is not a
dependency that can be swapped casually, since the offline bundle is the
thing being embedded.

`plotly.offline.get_plotlyjs()` reads that bundle from disk on every
call, so it is cached at module import in `_PLOTLY_JS_BUNDLE`. Without
the cache the e2e suite took roughly forty minutes; with it, about two.

The guarantee has one honest boundary. The generated HTML contains
sixteen `https://` string literals, all of them inert map-attribution
text inside the Plotly bundle. They are never fetched by any report
Reveille produces, and no chart Reveille builds is a map. They are
present because the bundle is shipped whole. The test asserts what
matters — that nothing in *our* template loads a remote resource —
rather than that the string `https://` is absent, which would be a
weaker check dressed as a stronger one.
