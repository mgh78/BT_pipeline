"""Start the pipeline interface.

    cd pipeline
    python main.py

Everything a run produces is written to ``data/runs/<run id>/``.
"""

import os
import sys

# Allow `python main.py` from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import main  # noqa: E402

if __name__ == '__main__':
    main()
