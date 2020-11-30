#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

import re
import string

#===============================================================================

from .. import PIXELS_PER_INCH

#===============================================================================

CM_PER_INCH = 2.54
MM_PER_INCH = 10*CM_PER_INCH

POINTS_PER_INCH = 72
PICAS_PER_INCH = 6

#===============================================================================

__unit_scaling = {
    'px': 1,
    'in': PIXELS_PER_INCH,
    'cm': PIXELS_PER_INCH/CM_PER_INCH,
    'mm': PIXELS_PER_INCH/MM_PER_INCH,
    'pt': PIXELS_PER_INCH/POINTS_PER_INCH,
    'pc': PIXELS_PER_INCH/PICAS_PER_INCH,
    '%' : None,      # 1/100.0 of viewport dimension
    'em': None,      # em/pt depends on current font size
    'ex': None,      # ex/pt depends on current font size
    }

def length_as_pixels(length):
#============================
    if not isinstance(length, str):
        return length
    match = re.search(r'(.*)(em|ex|px|in|cm|mm|pt|pc|%)', length)
    if match is None:
        return float(length)
    else:
        scaling = __unit_scaling[match.group(2)]
        if scaling is None:
            raise ValueError('Unsupported units: {}'.format(length))
        return scaling*float(match.group(1))

#===============================================================================

# Helpers for encoding names for Adobe Illustrator

def __match_to_char(m):
#======================
    s = m[0]
    if s == '_':
        return ' '
    else:
        return chr(int(s[2:4], 16))

def adobe_decode(s):
#===================
    if s.startswith('_x2E_'):
        return re.sub('(_x.._)|(_)', __match_to_char, s)
    else:
        return s

def __match_to_hex(m):
#=====================
    c = m[0]
    return (c   if c in (string.ascii_letters + string.digits) else
            '_' if c in string.whitespace else
            '_x{:02X}_'.format(ord(c)))

def adobe_encode(s):
#===================
    return re.sub('.', __match_to_hex, s)

#===============================================================================
