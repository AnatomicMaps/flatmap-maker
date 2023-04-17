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

from mapmaker.properties.pathways import PATH_TYPE
from mapmaker.sources.shape import Shape, SHAPE_TYPE

from .colours import ColourMatcher, ColourMatcherDict

#===============================================================================

# If a connection end is closer than this gap to a connector
# of the same nerve class then it is connected
MAX_CONNECTION_GAP =     4000               # metres, approx. sqrt(MAX_AREA)/2

#===============================================================================

class CD_CLASS:
    UNKNOWN    = 'celldl:Unknown'
    LAYER      = 'celldl:Layer'

    COMPONENT  = 'celldl:Component'     # What has CONNECTORs

    CONNECTOR  = 'celldl:Connector'     # What a CONNECTION connects to
    CONNECTION = 'celldl:Connection'    # The path between CONNECTORS
    CONDUIT    = 'celldl:Conduit'       # A container for CONNECTIONs

    ANNOTATION = 'celldl:Annotation'    # Additional information about something

#===============================================================================

class FC_CLASS:
    UNKNOWN     = 'fc-class:Unknown'
    LAYER       = 'fc-class:Layer'

    # Component classes
    SYSTEM      = 'fc-class:System'
    ORGAN       = 'fc-class:Organ'
    FTU         = 'fc-class:Ftu'

    # Connector, Connection, and Conduit classes
    NEURAL      = 'fc-class:Neural'
    VASCULAR    = 'fc-class:Vascular'

    # Annotation classes
    DESCRIPTION = 'fc-class:Description'
    HYPERLINK   = 'fc-class:Hyperlink'

#===============================================================================

class FC_KIND:
    UNKNOWN              = 'fc-kind:Unknown'

    # WIP: System kinds (is this independent to FC_KIND?)
    NERVOUS_SYSTEM       = 'fc-kind:NervousSystem'

    # WIP: Organ kinds (is this independent to FC_KIND?)
    DIAPHRAM             = 'fc-kind:Diaphram'

    # Vascular kinds
    ARTERIAL             = 'fc-kind:Arterial'
    VENOUS               = 'fc-kind:Venous'
    VEIN                 = 'fc-kind:Vein'
    ARTERY               = 'fc-kind:Artery'
    VASCULAR_REGION      = 'fc-kind:VascularRegion'

    # Neural kinds
    GANGLION             = 'fc-kind:Ganglion'
    NEURON               = 'fc-kind:Neuron'
    NERVE                = 'fc-kind:Nerve'
    PLEXUS               = 'fc-kind:Plexus'

    # Connector kinds
    CONNECTOR_JOINER     = 'fc-kind:ConnectorJoiner'    # double headed arrow
    CONNECTOR_FREE_END   = 'fc-kind:ConnectorFreeEnd'   # unattached connection end
    CONNECTOR_NODE       = 'fc-kind:ConnectorNode'      # ganglionic node??
    CONNECTOR_PORT       = 'fc-kind:ConnectorPort'      # a neural connection end in FTU
    CONNECTOR_THROUGH    = 'fc-kind:ConnectorThrough'   # cross in plexus and/or glanglion

    # Hyperlink kinds
    HYPERLINK_WIKIPEDIA  = 'fc-kind:HyperlinkWikipedia'
    HYPERLINK_PUBMED     = 'fc-kind:HyperlinkPubMed'
    HYPERLINK_PROVENANCE = 'fc-kind:HyperlinkProvenance'

#===============================================================================

HYPERLINK_IDENTIFIERS = {
    FC_KIND.HYPERLINK_WIKIPEDIA:'wikipedia',
    FC_KIND.HYPERLINK_PUBMED:'pubmed',
    FC_KIND.HYPERLINK_PROVENANCE: 'provenance',
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

NEURON_PATH_TYPES = ColourMatcherDict({
    # small rect, small ellipse, line
    '#FF0000': PATH_TYPE.SYMPATHETIC,       # red
    '#EA3323': PATH_TYPE.SYMPATHETIC,       # red
    '#548235': PATH_TYPE.PARASYMPATHETIC,   # green
    '#5E813F': PATH_TYPE.PARASYMPATHETIC,   # green
    '#0070C0': PATH_TYPE.SENSORY,           # blue
    '#2F6EBA': PATH_TYPE.SENSORY,           # blue
    '#4472C4': PATH_TYPE.SENSORY,           # blue
    '#DE8344': PATH_TYPE.INTRINSIC,         # orange
    '#68349A': PATH_TYPE.MOTOR,             # purple
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

def make_fc_shape(shape):
    shape.cd_class = CD_CLASS.UNKNOWN
    shape.fc_class = FC_CLASS.UNKNOWN
    shape.fc_kind = FC_KIND.UNKNOWN
    shape.description = ''
    shape.set_property('name', shape.name.replace('\t', '|').strip())
    shape.hyperlinks = []
    return shape

#===============================================================================

def is_annotation(shape):
    return shape.get_property('cd-class') == CD_CLASS.ANNOTATION

def make_annotation(shape, fc_class: str):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.ANNOTATION
    shape.fc_class = fc_class
    return shape

#===============================================================================

def is_component(shape):
    return shape.get_property('cd-class') == CD_CLASS.COMPONENT

def make_component(shape):
    make_fc_shape(shape)
    if shape.type == SHAPE_TYPE.LAYER:
        shape.cd_class = CD_CLASS.LAYER
        shape.fc_class = FC_CLASS.LAYER
    else:
        shape.cd_class = CD_CLASS.COMPONENT
    return shape

#===============================================================================

def is_connection(shape):
    return shape.get_property('cd-class') == CD_CLASS.CONNECTION

def make_connection(shape):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.CONNECTION
    shape.path_type = PATH_TYPE.UNKNOWN
    shape.connector_ids = []
    shape.intermediate_connectors = []
    shape.intermediate_components = []
    return shape

#===============================================================================

def is_connector(shape):
    return shape.get_property('cd-class') == CD_CLASS.CONNECTOR

def make_connector(shape):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.CONNECTOR
    shape.path_type = PATH_TYPE.UNKNOWN
    return shape

#===============================================================================
