"""Entry point for `flet run` and `flet build`.

Flet packaging looks for main.py by default. This file just hands off to the
real GUI in ringLight3.py so we can keep a descriptive module name and still
satisfy the Flet convention.

The `if __name__ == "__main__":` block at the bottom is Python's way of saying
"only run this when the file is launched directly, not when it is imported."
"""

import flet as ft

from ringLight3 import main


if __name__ == "__main__":
    ft.run(main)
