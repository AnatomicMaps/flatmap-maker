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

from mapmaker.knowledgebase.sckan import PATH_TYPE
from mapmaker.knowledgebase.celldl import CD_CLASS, FC_CLASS, FC_KIND
from mapmaker.shapes import SHAPE_TYPE

from .colours import ColourMatcher, ColourMatcherDict

#===============================================================================

# If a connection end is closer than this gap to a connector
# of the same nerve class then it is connected
MAX_CONNECTION_GAP = 4000               # metres, approx. sqrt(MAX_AREA)/2

#===============================================================================

HYPERLINK_IDENTIFIERS = {
    FC_KIND.HYPERLINK_WIKIPEDIA: 'wikipedia',
    FC_KIND.HYPERLINK_PUBMED: 'pubmed',
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
    '#ED70F8': 'purple',        # e.g. pharyngeal nerve, vagus nerve communicating gradient
    '#C3B8FA': 'purple',
    '#FFD966': 'dark-biege',    # e.g. chorda tympani nerve
    '#B5C4E3': 'pale-blue',     # e.g. paravertebral ganglion
    '#B4C4E2': 'pale-blue',                               #
    '#B8C6E4': 'pale-blue',
    '#E5F0DB': 'pale-green',    # e.g. pterygopalatine ganglia
    '#C7EFC6': 'pale-green',
    '#FDF3D0': 'biege',         # e.g. pharyngeal nerve plexus, cardiac ganglia
    '#FFF3CC': 'biege',         # e.g. carotid plexus
})

#===============================================================================

VASCULAR_KINDS = ColourMatcherDict({
    # small ellipse, line
    '#EA3323': 'arterial',                  # red
    '#FF0000': 'arterial',                  # red
    '#FF3300': 'arterial',                  # red
    '#0070C0': 'venous',                    # blue
    '#156082': 'venous',                    # blue
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
    return shape.cd_class == CD_CLASS.ANNOTATION

def make_annotation(shape, fc_class: str):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.ANNOTATION
    shape.fc_class = fc_class
    return shape

#===============================================================================

def is_component(shape):
    return shape.cd_class in [CD_CLASS.CONDUIT, CD_CLASS.COMPONENT]

def make_component(shape):
    make_fc_shape(shape)
    if shape.shape_type == SHAPE_TYPE.CONTAINER:
        shape.cd_class = CD_CLASS.LAYER
        shape.fc_class = FC_CLASS.LAYER
    else:
        shape.cd_class = CD_CLASS.COMPONENT
    return shape

#===============================================================================

def is_connection(shape):
    return shape.cd_class == CD_CLASS.CONNECTION

def make_connection(shape):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.CONNECTION
    shape.path_type = PATH_TYPE.UNKNOWN
    shape.connector_ids = []
    shape.local_connector_ids = []
    shape.intermediate_connectors = []
    shape.intermediate_components = []
    return shape

#===============================================================================

def is_connector(shape):
    return shape.cd_class == CD_CLASS.CONNECTOR

def make_connector(shape):
    make_fc_shape(shape)
    shape.cd_class = CD_CLASS.CONNECTOR
    shape.path_type = PATH_TYPE.UNKNOWN
    return shape

#===============================================================================

def is_system_name(name):
    return len(name) > 6 and name == name.upper()

def system_ids(component) -> set[str]:
    if component.fc_class == FC_CLASS.SYSTEM:
        return set([component.global_shape.id])
    names = set()
    for parent in component.parents:
        names.update(system_ids(parent))
    return names

def ensure_parent_system(component, parent_system):
    if parent_system in component.parents:
        return
    if len(component.parents) == 0:
        component.add_parent(parent_system)
        return
    parent_systems = []
    for parent in component.parents:
        if parent.fc_class in [FC_CLASS.FTU, FC_CLASS.ORGAN]:
            return      # We don't climb out of FTUs or organs
        elif parent.fc_class == FC_CLASS.SYSTEM:
            parent_systems.append(parent)
    if len(parent_systems):
        component.add_parent(parent_system)
        return
    for parent in component.parents:
        ensure_parent_system(parent, parent_system)

#===============================================================================
