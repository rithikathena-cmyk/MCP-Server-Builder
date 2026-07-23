import os
import sys

# Ensure the project root is importable so `import backend...` works when pytest
# is invoked from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
