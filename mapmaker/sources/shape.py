#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2023  David Brooks
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

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shapely.geometry.base import BaseGeometry

#===============================================================================

class SHAPE_TYPE(Enum):
    FEATURE = 1
    CONNECTOR = 2

#===============================================================================

@dataclass
class Shape:
    type: SHAPE_TYPE
    id: int
    geometry: Optional[BaseGeometry]
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.metadata: dict[str, str] = {}  # kw_only=True field for Python 3.10

    @property
    def opacity(self) -> float:
        return self.properties.get('opacity', 1.0)

    @property
    def colour(self) -> Optional[str]:
        return self.properties.get('colour')

    @property
    def kind(self) -> Optional[str]:
        return self.properties.get('shape-kind')

    @property
    def label(self) -> str:
        return self.properties.get('label', '')

    @property
    def name(self) -> Optional[str]:
        return self.properties.get('shape-name')

    def set_metadata(self, name: str, value: str):
        self.metadata[name] = value

    def get_metadata(self, name: str, default: Optional[str]=None) -> Optional[str]:
        return self.metadata.get(name, default)

#===============================================================================
