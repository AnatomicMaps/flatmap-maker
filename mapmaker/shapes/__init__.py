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

from enum import Enum
from typing import Any, Optional

from shapely.geometry.base import BaseGeometry      # type: ignore

#===============================================================================

from mapmaker.utils import log, PropertyMixin

#===============================================================================

class SHAPE_TYPE(Enum):
    UNKNOWN    = 0
    CONNECTION = 1      #! A path between FEATUREs
    FEATURE    = 2
    GROUP      = 3
    LAYER      = 4

#===============================================================================

PropertiesInString = ['name', 'cd-class', 'fc-class', 'fc-kind']

class Shape(PropertyMixin):
    __attributes = ['id', 'geometry', 'parents', 'children']
    def __init__(self, id: str, geometry: BaseGeometry, properties=None):
        self.__initialising = True
        super().__init__(properties)
        self.id = id
        self.geometry = geometry
        self.children = []
        self.parents = []
        self.metadata: dict[str, str] = {}  # kw_only=True field for Python 3.10
        if self.has_property('id'):
            self.id = self.get_property('id')
        else:
            self.set_property('id', self.id)
        # We've now defined the new instance's attributes
        self.__initialising = False

    def __getattr__(self, key: str) -> Any:
        if key.startswith('_') or self.__initialising or key in self.__attributes:
            return object.__getattribute__(self, key)
        else:
            return self.get_property(key.replace('_', '-'))

    def __setattr__(self, key: str, value: Any=None):
        if key.startswith('_') or self.__initialising or key in self.__attributes:
            object.__setattr__(self, key, value)
        else:
            self.set_property(key.replace('_', '-'), value)

    def __str__(self):
        properties = {key: value for key, value in self.properties.items()
                                    if key in PropertiesInString}
        return f'Shape {self.id}: {properties}'

    @property
    def geojson_id(self) -> int:
        return self.get_property('geojson-id', 0)

    @property
    def global_shape(self) -> 'Shape':              # The shape that excluded this one via a filter
        return self.get_property('global-shape', self)

    @property
    def kind(self) -> Optional[str]:                # The geometric name of the shape or, for an image,
        return self.get_property('shape-kind')      # its content type: e.g. ``rect`` or ``image/png``

    @property
    def name(self) -> str:                          # Any text content associated with the shape: e.g. ``Bladder``
        return self.get_property('name', '')

    @property
    def opacity(self) -> float:
        return self.get_property('opacity', 1.0)

    @property
    def parent(self):
        return self.parents[0] if self.parents else None

    @property
    def shape_name(self) -> str:                    # The name of the shape in the source: e.g. ``Text Box 3086``
        return self.get_property('shape-name', '')

    @property
    def type(self) -> SHAPE_TYPE:
        return self.get_property('type', SHAPE_TYPE.UNKNOWN)

    def add_parent(self, parent):
        self.parents.append(parent)
        parent.children.append(self)

    def get_metadata(self, name: str, default: Optional[str]=None) -> Optional[str]:
        return self.metadata.get(name, default)

    def set_metadata(self, name: str, value: str):
        self.metadata[name] = value

    def log_error(self, msg: str):
        self.set_property('error', msg)
        log.error(msg)

    def log_warning(self, msg: str):
        self.set_property('warning', msg)
        log.warning(msg)

#===============================================================================
