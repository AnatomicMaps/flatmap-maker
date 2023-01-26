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

from dataclasses import dataclass, field
import enum
from typing import Optional

#===============================================================================

import shapely.geometry

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

CONNECTION_CLASSES = {
    '#FF0000': 'symp',      # Source is in Brain/spinal cord
    '#0070C0': 'sensory',   # Target is in Brain/spinal cord
    '#4472C4': 'sensory',
    '#548135': 'para',      # Source is in Brain/spinal cord
    '#548235': 'para',      # Source is in Brain/spinal cord
    '#FFC000': 'connector', # An inline connector
}

#===============================================================================

class FC_Class(enum.Enum):
    UNKNOWN = 0
    BRAIN = enum.auto()

class FC(enum.IntFlag):
    # Values can be or'd together...
    UNKNOWN   = 0
    SYSTEM    = 1
    ORGAN     = 2
    FTU       = 4
    NERVE     = 64
    CONNECTED = 256

#===============================================================================

@dataclass
class Connector:
    id: str
    source: Optional[str]
    target: Optional[str]
    geometry: shapely.geometry.base.BaseGeometry
    arrows: int
    properties: dict[str, str] = field(default_factory=dict)

#===============================================================================

@dataclass
class FCFeature:
    id: str
    kind: FC = field(default=FC.UNKNOWN, init=False)
    fc_class: FC_Class = field(default=FC_Class.UNKNOWN, init=False)
    geometry: shapely.geometry.base.BaseGeometry
    properties: dict[str, str] = field(default_factory=dict)
    children: list[str] = field(default_factory=list, init=False)
    parents: list[str] = field(default_factory=list, init=False)

    def __post_init__(self):
        label = self.properties.pop('label', '').replace('\t', '|').strip()
        self.properties['name'] = label
        label = self.properties.pop('hyperlink', label)
        self.properties['label'] = f'{self.id}: {label}' if settings.get('authoring', False) else label

    ## post init to assigh organ_class

    def __str__(self):
        return f'FCFeature({self.id}: {str(self.kind)}/{str(self.fc_class)}, parents={self.parents}, children={self.children} {self.name})'

    @property
    def colour(self):
        return self.properties.get('colour')

    @property
    def feature_class(self):
        return self.properties.get('class')

    ## Maybe have set_feature_class() (or add) so more explicit?
    ## Should class property be a list??
    @feature_class.setter
    def feature_class(self, cls):
        self.properties['class'] = cls

    @property
    def feature_id(self) -> Optional[str]:
        return self.properties.get('id')

    ## Maybe have set_feature_id() so more explicit
    @feature_id.setter
    def feature_id(self, id):
        self.properties['id'] = id

    @property
    def label(self):
        return self.properties.get('label', self.name)

    @property
    def models(self):
        return self.properties.get('models')

    @property
    def name(self):
        return self.properties.get('name', '')

    @models.setter
    def models(self, model):
        self.properties['models'] = model

#===============================================================================
