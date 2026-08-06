"""Reveille -- Git Repository Intelligence.

A CLI tool that generates self-contained HTML performance reports
from local Git repositories.

Reveille's modules emit diagnostics through the standard `logging`
module under the `reveille` logger. A NullHandler is attached here so
that importing Reveille as a library produces no output unless the host
application configures a handler itself — the convention for libraries,
which must not impose logging policy on the program embedding them. The
CLI attaches its own stderr handler when `--verbose` is passed.
"""

import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.7.0"
__author__ = "Varaprasad Chilakanti"
__email__ = "varaprasadchilakanti@gmail.com"
__licence__ = "MIT"
