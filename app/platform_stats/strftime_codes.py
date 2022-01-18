"""This module provides platform compatible format codes for strftime.

   By default, Python does not check the format codes sent to strftime:
   these are sent directly to the platform's implementation. This leads
   developers to use platform specific format codes for strftime that
   can't easily run on other platforms that are popular and normally
   easy to support for by the Python language.

   Hence we have this module that makes the translation between platform
   specific format codes. To refer to the different platform specific
   codes and what is deemed safe (i.e. ANSI C/ POSIX compatible):

   For windows, see:
   https://docs.microsoft.com/en-us/cpp/c-runtime-library/reference/strftime-wcsftime-strftime-l-wcsftime-l?redirectedfrom=MSDN&view=msvc-160

   For *nix compatible (non-POSIX compatible), see:
   https://man7.org/linux/man-pages/man3/strftime.3.html

   'somewhat POSIX'/ ANSI C compatible, see
   https://en.cppreference.com/w/c/chrono/strftime
"""

import platform


NO_PAD_POSIX_CHAR = "-"
NO_PAD_WINDOWS_CHAR = "#"

NO_PAD_CODES: list = ["d", "D", "e", "F", "H", "I", "j", "m", "M", "r", "R", "S", "T", "U", "V", "W", "y", "Y"]


def _get_system() -> str:
    return platform.system().lower()


def _get_no_pad_char() -> str:
    return NO_PAD_WINDOWS_CHAR if _is_windows() else NO_PAD_POSIX_CHAR


def _is_windows() -> bool:
    return _get_system() == "windows"


def no_pad_code(code: str) -> str:
    """Gets the non padded format for the given code (i.e. leading zero is removed)"""
    if code not in NO_PAD_CODES:
        raise ValueError(f"The {code} character is not supported for no padding: {NO_PAD_CODES}")
    no_pad = _get_no_pad_char()
    return f"%{no_pad}{code}"


def no_pad_day() -> str:
    """Gets the format code for non padded day (i.e. leading zero is removed)"""
    return no_pad_code("d")


def no_pad_hour12() -> str:
    """Gets the format code for non padded hour (i.e. 12h format & leading zero is removed)"""
    return no_pad_code("I")


def no_pad_hour24() -> str:
    """Gets the format code for non padded hour (i.e. 24h format & leading zero is removed)"""
    return no_pad_code("H")


def no_pad_month() -> str:
    """Gets the format code for non padded month (i.e. leading zero is removed)"""
    return no_pad_code("m")
