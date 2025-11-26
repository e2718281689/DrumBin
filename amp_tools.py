"""Launcher wrapper for amp_tools.main_app

This file keeps backward compatibility for users who run `python main_app.py`.
It delegates to `amp_tools.main_app.main()`.
"""

from amp_tools.main_app import main


if __name__ == "__main__":
    main()
