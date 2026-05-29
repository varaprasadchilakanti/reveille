# Security Policy

## Supported Versions

Only the current stable release receives security fixes.

| Version | Supported |
|---------|-----------|
| 0.6.x   | ✓         |
| < 0.6.0 | ✗         |

## Reporting a Vulnerability

Do not open a public GitHub issue for security vulnerabilities.

Use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/varaprasadchilakanti/reveille/security/advisories/new)

Include a description of the vulnerability and its potential impact,
steps to reproduce it, and the version of Reveille and Python in use.

You can expect an acknowledgement within 48 hours. Confirmed
vulnerabilities will receive a resolution timeline within 7 days.

## Scope

Reveille is a local analysis tool. It reads only the Git repository
it is explicitly pointed at, produces a single HTML output file, and
does not transmit data over a network. It does not accept inbound
connections and does not execute content from commit messages or file
contents. The primary attack surface is maliciously crafted Git
repository content that could affect the HTML output, or
vulnerabilities in the runtime dependency chain (GitPython, Jinja2,
Plotly, Typer).
