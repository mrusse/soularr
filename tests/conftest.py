import os
import sys

# Let the tests import soularr.py from the repository root, however pytest is started.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
