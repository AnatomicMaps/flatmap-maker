#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

from enum import Enum
from typing import Any

#===============================================================================

# Updated by flatmap maker to contain settings and options for map generation

settings: dict[str, Any] = {}

#===============================================================================

class MAP_KIND(Enum):
    UNKNOWN    = 0
    ANATOMICAL = 1
    FUNCTIONAL = 2

#===============================================================================
