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

from mapmaker.sources.shape import Shape, SHAPE_TYPE

from .colours import convert_lookup_table, lookup_colour_table

#===============================================================================

# Shapes smaller than this are assumed to be connectors or hyperlinks
MAX_CONNECTOR_AREA = 50000000               # metres**2

# If a connection end is closer than this gap to a connector
# of the same nerve class then it is connected
MAX_CONNECTION_GAP =     4000               # metres, approx. sqrt(MAX_AREA)/2

#===============================================================================

class FC_CLASS(enum.Enum):
    UNKNOWN    = 0
    BRAIN      = enum.auto()
    HYPERLINK  = enum.auto()

    NERVE      = enum.auto()
    PLEXUS     = enum.auto()
    GANGLION   = enum.auto()
    NEURON     = enum.auto()

    ARTERIAL   = enum.auto()
    VENOUS     = enum.auto()

    JOIN       = enum.auto()
    FREE_END   = enum.auto()
    NODE       = enum.auto()
    PORT       = enum.auto()
    THROUGH    = enum.auto()

class FC_TYPE(enum.IntFlag):
    UNKNOWN    = 0
    LAYER      = enum.auto()
    SYSTEM     = enum.auto()
    ORGAN      = enum.auto()
    FTU        = enum.auto()
    HYPERLINK  = enum.auto()
    NERVE      = enum.auto()
    CONNECTOR  = enum.auto()   # What a CONNECTION connects to
    CONNECTION = enum.auto()   # The path between CONNECTORS

#===============================================================================

NEURON_PATH_CLASSES = [
    "sympathetic",
    "parasympathetic",
    "sensory",
]

CONNECTOR_PORT_CLASSES = [
    FC_CLASS.NODE,
    FC_CLASS.PORT,
]

CONNECTOR_SYMBOL_CLASSES = [
    FC_CLASS.JOIN,
    FC_CLASS.THROUGH,
]

#===============================================================================

# Communicating branches are gradients...
NERVE_FEATURE_CLASSES = {  # colour ==> nerve class
    '#ADFCFE': 'cyan',          # e.g. upper branch of laryngeal nerve
    '#93FFFF': 'cyan',          # e.g. upper branch of internal laryngeal nerve
    '#9FCE63': 'green',         # e.g. maxillary nerve
###    '#E5F0DB': 'pale-green',    # e.g. pterygopalatine ganglia  ### FTU colour
    '#ED70F8': 'purple',        # e.g. pharyngeal nerve
    '#ED70F8': 'purple',        # e.g. vagus nerve communicating gradient
    '#FDF3D0': 'biege',         # e.g. pharyngeal nerve plexus
    '#FFF3CC': 'biege',         # e.g. carotid plexus
    '#FFD966': 'dark-biege',    # e.g. chorda tympani nerve
    # Red
    '#FF0000': "sympathetic",
    '#EA3323': "sympathetic",
    # Green
    '#548235': "parasympathetic",
    '#5E813F': "parasympathetic",
    # Blue
    '#0070C0': "sensory",
    '#2F6EBA': "sensory",
    '#4472C4': "sensory",
    # Markers and joiners
    '#FFC000': FC_CLASS.JOIN,           # An inline connector arrow, `leftRightArrow`
    '#ED7D31': FC_CLASS.THROUGH,        # cross in plexus, `plus`
}
NERVE_FEATURE_LAB_COLOURS = convert_lookup_table(NERVE_FEATURE_CLASSES)

#===============================================================================

def nerve_class(shape: Shape) -> Optional[str]:
#==============================================
    if (not shape.properties.get('shape-kind', '').startswith('star')
        and (cls := lookup_colour_table(NERVE_FEATURE_LAB_COLOURS, shape.colour)) is not None):
        return cls

def nerve_type_and_class(shape: Shape) -> Optional[tuple[FC_TYPE, FC_CLASS, str]]:
#=================================================================================
    shape_kind = shape.properties.get('shape-kind', '')
    if (shape_kind.startswith('star')
    and shape.geometry.area < MAX_CONNECTOR_AREA):
        return (FC_TYPE.HYPERLINK, FC_CLASS.HYPERLINK, '')
    cls = nerve_class(shape)
    if shape.type == SHAPE_TYPE.CONNECTION:
        if cls in NEURON_PATH_CLASSES:
            line_style = shape.properties.get('line-style', '').lower()
            ganglionic = 'pre' if 'dot' in line_style or 'dash' in line_style else 'post'
            if cls in ['sympathetic', 'parasympathetic']:
                cls = f'{cls}-{ganglionic}'
            return (FC_TYPE.CONNECTION, FC_CLASS.NEURON, cls)
    elif cls is not None:
        if (shape.geometry.area < MAX_CONNECTOR_AREA):
            if cls in NEURON_PATH_CLASSES:
                if shape_kind == 'rect':
                    return (FC_TYPE.CONNECTOR, FC_CLASS.PORT, cls)
                else:  ##  elif shape_kind == 'ellipse':
                    return (FC_TYPE.CONNECTOR, FC_CLASS.NODE, cls)
            elif cls in CONNECTOR_SYMBOL_CLASSES:
                return (FC_TYPE.CONNECTOR, cls, '')
        else:
            return (FC_TYPE.NERVE, FC_CLASS.NERVE, cls)   ## Future: NERVE/PLEXUS/GANGLION class

#===============================================================================

@dataclass
class FCComponent:
    shape: Shape
    __fc_type: FC_TYPE = field(default=FC_TYPE.UNKNOWN, init=False)
    fc_class: FC_CLASS = field(default=FC_CLASS.UNKNOWN, init=False)
    nerve_class: str = field(default='N/A', init=False)
    children: list[str] = field(default_factory=list, init=False)
    parents: list[str] = field(default_factory=list, init=False)
    connectors: list[str] = field(default_factory=list, init=False)

    def __post_init__(self):
    #=======================
        label = self.properties.pop('label', '').replace('\t', '|').strip()
        if self.shape.type == SHAPE_TYPE.LAYER:
            self.fc_type = FC_TYPE.LAYER
        elif (self.shape.type in [SHAPE_TYPE.CONNECTION, SHAPE_TYPE.FEATURE]
        and (type_class := nerve_type_and_class(self.shape)) is not None):
            self.fc_type = type_class[0]
            self.fc_class = type_class[1]
            self.nerve_class = type_class[2]
        self.properties['name'] = label
        self.properties['label'] = label

    def __str__(self):
        shape_kind = self.shape.properties.get('shape-kind', '')
        return f'FC({self.id}: {shape_kind}/{str(self.fc_type)}/{str(self.fc_class)}/{self.nerve_class} `{self.name}`)'

    @property
    def colour(self):
        return self.properties.get('colour')

    @property
    def fc_type(self):
        return self.__fc_type

    @fc_type.setter
    def fc_type(self, type):
        self.__fc_type = type
        self.shape.properties['fc-type'] = type

    @property
    def feature_id(self) -> Optional[str]:
        return self.properties.get('id')

    @property
    def geometry(self):
        return self.shape.geometry

    @property
    def id(self):
        return self.shape.id

    @property
    def label(self):
        return self.properties.get('label', self.name)

    @property
    def models(self):
        return self.properties.get('models')

    @property
    def name(self):
        return self.properties.get('name', '')

    @property
    def properties(self):
        return self.shape.properties

    def set_geometry(self, geometry):
        self.shape.geometry = geometry

#===============================================================================
