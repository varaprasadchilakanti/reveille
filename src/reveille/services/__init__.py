# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Application service layer for Reveille.

Orchestrates the report generation pipeline by coordinating the
domain layer and adapter layer. Has no direct knowledge of
GitPython, Jinja2, Plotly, or Typer.
"""
