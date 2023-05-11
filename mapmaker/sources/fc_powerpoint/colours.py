#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

from typing import Any, Optional

#===============================================================================

from colormath.color_objects import LabColor, sRGBColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000

# See https://github.com/gtaylor/python-colormath/issues/104
import numpy

def patch_asscalar(a):
    return a.item()

setattr(numpy, "asscalar", patch_asscalar)

#===============================================================================

# CIE Delta E 2000 color difference
CLOSE_COLOUR_DISTANCE = 6       # Perceptible on close inspection

#===============================================================================

class ColourMatcher:
    def __init__(self, rgb_colour: str):
        self.__colour = (convert_color(sRGBColor.new_from_rgb_hex(rgb_colour), LabColor)
            if rgb_colour is not None
            else None)
        self.__rgb_colour = rgb_colour

    @property
    def rgb_colour(self):
        return self.__rgb_colour

    def matches(self, colour: Optional[str]) -> bool:
        if colour is not None and self.__colour is not None:
            lab_colour = convert_color(sRGBColor.new_from_rgb_hex(colour), LabColor)
            return delta_e_cie2000(lab_colour, self.__colour) < CLOSE_COLOUR_DISTANCE
        return colour == self.__colour

#===============================================================================

class ColourMatcherDict:
    def __init__(self, lookup_table: dict[str, Any]):
        self.__lookup_table = {
            convert_color(sRGBColor.new_from_rgb_hex(key), LabColor): value
                for key, value in lookup_table.items()
        }

    def lookup(self, colour: Optional[str]) -> Optional[Any]:
        if colour is not None:
            lab_colour = convert_color(sRGBColor.new_from_rgb_hex(colour), LabColor)
            for key, value in self.__lookup_table.items():
                if delta_e_cie2000(lab_colour, key) < CLOSE_COLOUR_DISTANCE:
                    return value

#===============================================================================
