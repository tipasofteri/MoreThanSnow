import os
import sys

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import and run the main function
from src.app import main

if __name__ == '__main__':
    main()
    print()
