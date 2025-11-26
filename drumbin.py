#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Launcher wrapper for `drumbin.app`.

Keeps backward compatibility for `python app.py` by delegating to
`drumbin.app.main()`.
"""

from drumbin.app import main

if __name__ == "__main__":
    main()
