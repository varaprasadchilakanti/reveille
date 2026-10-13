# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""`python -m reveille`, for when another tool owns the `reveille` command on PATH."""

from __future__ import annotations

if __name__ == "__main__":
    from reveille.cli import app

    app(prog_name="reveille")
