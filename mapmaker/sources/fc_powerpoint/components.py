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

from .colours import ColourMatcher, ColourMatcherDict

#===============================================================================

# Shapes smaller than this are assumed to be connectors or hyperlinks
MAX_CONNECTOR_AREA = 120000000              # metres**2

# If a connection end is closer than this gap to a connector
# of the same nerve class then it is connected
MAX_CONNECTION_GAP =     4000               # metres, approx. sqrt(MAX_AREA)/2

#===============================================================================

class CD_CLASS(enum.IntFlag):
    UNKNOWN    = 0
    LAYER      = enum.auto()
    COMPONENT  = enum.auto()   # What has CONNECTORs
    CONNECTOR  = enum.auto()   # What a CONNECTION connects to
    CONNECTION = enum.auto()   # The path between CONNECTORS
    ANNOTATION = enum.auto()   # Additional information about something

#===============================================================================

class FC_KIND(enum.IntFlag):
    UNKNOWN              = 0
    BRAIN                = enum.auto()
    DIAPHRAM             = enum.auto()

    ARTERIAL             = enum.auto()
    VENOUS               = enum.auto()
    VEIN                 = enum.auto()
    ARTERY               = enum.auto()
    VASCULAR_REGION      = enum.auto()

    GANGLION             = enum.auto()
    NEURON               = enum.auto()
    NERVE                = enum.auto()
    PLEXUS               = enum.auto()

    CONNECTOR_JOINER     = enum.auto()  # double headed arrow
    CONNECTOR_FREE_END   = enum.auto()  # unattached connection end
    CONNECTOR_NODE       = enum.auto()  # ganglionic node??
    CONNECTOR_PORT       = enum.auto()  # a neural connection end in FTU
    CONNECTOR_THROUGH    = enum.auto()  # cross in plexus and/or glanglion

    HYPERLINK_WIKIPEDIA  = enum.auto()
    HYPERLINK_PUBMED     = enum.auto()
    HYPERLINK_PROVENANCE = enum.auto()

class FC_CLASS(enum.IntFlag):
    UNKNOWN    = 0
    LAYER      = enum.auto()
    SYSTEM     = enum.auto()
    ORGAN      = enum.auto()
    FTU        = enum.auto()

    DESCRIPTION = enum.auto()
    HYPERLINK  = enum.auto()

    # Connector and Connection classes
    NEURAL     = enum.auto()
    VASCULAR   = enum.auto()

#===============================================================================

HYPERLINK_LABELS = {
    FC_KIND.HYPERLINK_WIKIPEDIA:  'Wikipedia',
    FC_KIND.HYPERLINK_PUBMED:     'PubMed',
    FC_KIND.HYPERLINK_PROVENANCE: 'Provenance',
}

HYPERLINK_KINDS = ColourMatcherDict({
    # small star
    '#B4C7E7': FC_KIND.HYPERLINK_WIKIPEDIA,
    '#FFE699': FC_KIND.HYPERLINK_PUBMED,
    '#C5E0B4': FC_KIND.HYPERLINK_PROVENANCE,
})

#===============================================================================

ORGAN_KINDS = ColourMatcherDict({
    # large rect, line (dashed)
    '#000000': FC_KIND.DIAPHRAM,
})

ORGAN_COLOUR = ColourMatcher('#D0CECE')

#===============================================================================

NEURON_KINDS = ColourMatcherDict({
    # small rect, small ellipse, line
    '#FF0000': "sympathetic",               # red
    '#EA3323': "sympathetic",               # red
    '#548235': "parasympathetic",           # green
    '#5E813F': "parasympathetic",           # green
    '#0070C0': "sensory",                   # blue
    '#2F6EBA': "sensory",                   # blue
    '#4472C4': "sensory",                   # blue
    '#DE8344': "intracardiac",              # orange
    '#68349A': "motor",                     # purple
})

# Communicating branches are gradients...
NERVE_FEATURE_KINDS = ColourMatcherDict({  # colour ==> nerve kind
    # large rect
    '#ADFCFE': 'cyan',          # e.g. upper branch of laryngeal nerve
    '#93FFFF': 'cyan',          # e.g. upper branch of internal laryngeal nerve
    '#9FCE63': 'green',         # e.g. maxillary nerve
    '#E5F0DB': 'pale-green',    # e.g. pterygopalatine ganglia
    '#ED70F8': 'purple',        # e.g. pharyngeal nerve
    '#ED70F8': 'purple',        # e.g. vagus nerve communicating gradient
    '#FDF3D0': 'biege',         # e.g. pharyngeal nerve plexus, cardiac ganglia
    '#FFF3CC': 'biege',         # e.g. carotid plexus
    '#FFD966': 'dark-biege',    # e.g. chorda tympani nerve
})

#===============================================================================

VASCULAR_KINDS = ColourMatcherDict({
    # small ellipse, line
    '#EA3323': 'arterial',                  # red
    '#2F6EBA': 'venous',                    # blue
})

VASCULAR_VESSEL_KINDS = ColourMatcherDict({
    # large rect
    '#F1908B': FC_KIND.ARTERY,              # pale red
    '#EA3323': FC_KIND.ARTERY,              # red
    '#92A8DC': FC_KIND.VEIN,                # pale blue
    '#2F6EBA': FC_KIND.VEIN,                # blue
})

VASCULAR_REGION_COLOUR = ColourMatcher('#FF99CC') # pink

#===============================================================================

@dataclass
class FCShape:
    shape: Shape
    __cd_class: CD_CLASS = field(default=CD_CLASS.UNKNOWN, init=False)
    __fc_class: FC_CLASS = field(default=FC_CLASS.UNKNOWN, init=False)
    __fc_kind: FC_KIND = field(default=FC_KIND.UNKNOWN, init=False)
    description: str = field(default='', init=False)
    children: list = field(default_factory=list, init=False)    # list[FCShape]
    parents: list = field(default_factory=list, init=False)     # list[FCShape]

    def __post_init__(self):
    #=======================
        label = self.properties.pop('label', self.name).replace('\t', '|').strip()
        self.properties['name'] = label
        self.properties['label'] = label
        self.__classify()

    def __classify(self):
    #====================
        if self.shape.type == SHAPE_TYPE.LAYER:
            self.cd_class = CD_CLASS.LAYER
            self.fc_class = FC_CLASS.LAYER

        elif self.shape.type == SHAPE_TYPE.CONNECTION:
            self.cd_class = CD_CLASS.CONNECTION

        elif self.shape.type == SHAPE_TYPE.FEATURE:
            if self.colour is None:
                if self.label != '':
                    self.cd_class = CD_CLASS.ANNOTATION
                    self.fc_class = FC_CLASS.DESCRIPTION
            elif (self.shape.geometry.area < MAX_CONNECTOR_AREA):
                if self.shape_kind.startswith('star'):
                    if (kind := HYPERLINK_KINDS.lookup(self.shape.colour)) is not None:
                        # set label to ??
                        self.cd_class = CD_CLASS.ANNOTATION
                        self.fc_class = FC_CLASS.HYPERLINK
                        self.fc_kind = kind
                        self.properties['label'] = HYPERLINK_LABELS[kind]
                else:
                    self.cd_class = CD_CLASS.CONNECTOR
            else:
                self.cd_class = CD_CLASS.COMPONENT

    def __str__(self):
        shape_kind = self.properties.get('shape-kind', '')
        return f'FC({self.id}: {shape_kind}/{str(self.cd_class)}/{str(self.fc_class)}/{str(self.fc_kind)}/{self.description} `{self.name}`)'

    @property
    def colour(self) -> Optional[str]:
        return self.properties.get('colour')

    @property
    def cd_class(self):
        return self.__cd_class

    @cd_class.setter
    def cd_class(self, cls):
        self.__cd_class = cls
        self.properties['cd-class'] = cls

    @property
    def fc_class(self):
        return self.__fc_class

    @fc_class.setter
    def fc_class(self, cls):
        self.__fc_class = cls
        self.properties['fc-class'] = cls

    @property
    def fc_kind(self):
        return self.__fc_kind

    @fc_kind.setter
    def fc_kind(self, kind):
        self.__fc_kind = kind
        self.properties['fc-kind'] = kind

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

    @property
    def shape_kind(self):
        return self.properties.get('shape-kind', '')

    def set_geometry(self, geometry):
        self.shape.geometry = geometry

#===============================================================================

class Connection(FCShape):
    def __init__(self, shape: Shape):
        super().__init__(shape)
        self.cd_class = CD_CLASS.CONNECTION
        self.connector_ids: list[str] = []
        self.intermediate_connectors: list[str] = []

#===============================================================================
