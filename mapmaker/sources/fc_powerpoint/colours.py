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

#===============================================================================

# CIE Delta E 2000 color difference
CLOSE_COLOUR_DISTANCE = 5       # Perceptible on close inspection

#===============================================================================

def convert_lookup_table(table: dict[str, Any]) -> dict[str, Any]:
#=================================================================
    return {
        convert_color(sRGBColor.new_from_rgb_hex(key), LabColor): value
            for key, value in table.items()
    }

def lookup_colour_table(table: dict[str, str], colour: Optional[str]) -> Optional[Any]:
#======================================================================================
    if colour is not None:
        lab_colour = convert_color(sRGBColor.new_from_rgb_hex(colour), LabColor)
        for key, value in table.items():
            if delta_e_cie2000(lab_colour, key) < CLOSE_COLOUR_DISTANCE:
                return value

#===============================================================================
