# SPDX-FileCopyrightText: 2026 Varaprasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Infrastructure adapter layer for Reveille.

Contains the two external boundaries: the Git reader (GitPython)
and the HTML renderer (Jinja2 + Plotly). Both are replaceable
without touching domain or service logic.
"""
