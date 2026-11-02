# SPDX-FileCopyrightText: 2026 Vara Prasad Chilakanti
# SPDX-License-Identifier: Apache-2.0

"""Reveille: offline reports of a Git repository's history.

The `reveille` logger gets a NullHandler so a host keeps its own logging
policy; the CLI adds a stderr handler under `--verbose`.
"""

import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.10.0"
__author__ = "Vara Prasad Chilakanti"
__email__ = "varaprasadchilakanti@gmail.com"
__licence__ = "Apache-2.0"
