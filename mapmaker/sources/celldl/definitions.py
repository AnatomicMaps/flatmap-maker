#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2025 David Brooks
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

import lxml.etree as etree

#===============================================================================

from mapmaker.utils import SVG_NS

#===============================================================================

EM_SIZE = 16                    # Pixels, sets ``font-size`` in CellDLStylesheet
INTERFACE_PORT_RADIUS = 4       # pixels

#===============================================================================

ERROR_COLOUR = 'yellow'

#===============================================================================

DIAGRAM_LAYER = 'diagram-layer'

CELLDL_BACKGROUND_CLASS = 'celldl-background'
CELLDL_LAYER_CLASS = 'celldl-Layer'

CELLDL_DEFINITIONS_ID = "celldl-svg-definitions"
CELLDL_METADATA_ID = "celldl-rdf-metadata"
CELLDL_STYLESHEET_ID = 'celldl-svg-stylesheet'

#===============================================================================

CellDLStylesheet = '\n'.join([    # Copied from ``@renderer/styles/stylesheet.ts``
    f'svg{{font-size:{EM_SIZE}px}}',
    # Conduits
    '.celldl-Conduit{z-index:9999}',
    # Connections
    '.celldl-Connection{stroke-width:2;opacity:0.7;fill:none;stroke:currentcolor}',
    '.celldl-Connection.dashed{stroke-dasharray:5}',
    # Compartments
    '.celldl-Compartment>rect.compartment{fill:#CCC;opacity:0.6;stroke:#444;rx:10px;ry:10px}',
    # Interfaces
    f'.celldl-InterfacePort{{fill:red;r:{INTERFACE_PORT_RADIUS}px}}',
    f'.celldl-Unconnected{{fill:red;fill-opacity:0.1;stroke:red;r:{INTERFACE_PORT_RADIUS}px}}'
])

#===============================================================================

def arrow_marker_definition(markerId: str, markerType: str) -> str:
#==================================================================
    # see https://developer.mozilla.org/en-US/docs/Web/SVG/Element/marker
    return f"""<marker id="{markerId}" viewBox="0 0 10 10" class="{markerType}"
refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
    <path fill="currentcolor" stroke="currentcolor" d="M 0 0 L 10 5 L 0 10 z" />
</marker>"""

#===============================================================================
#===============================================================================

def bondgraph_arrow_definition(domain: str) -> str:
#==================================================
    return arrow_marker_definition(f'connection-end-arrow-{domain}', domain)

#===============================================================================

BondgraphSvgDefinitions: list[etree.Element] = etree.fromstring(
    '\n'.join([
        f'<defs xmlns="{SVG_NS}">',
        bondgraph_arrow_definition('bondgraph'),
        bondgraph_arrow_definition('mechanical'),
        bondgraph_arrow_definition('electrical'),
        bondgraph_arrow_definition('biochemical'),
        '</defs>'
    ])
).getchildren()

#===============================================================================

BondgraphStylesheet = '\n'.join([
    # Bondgraph specific
    'svg{--biochemical:#2F6EBA;--electrical:#DE8344;--mechanical:#4EAD5B}',
    '.bondgraph{color:pink}'
    '.biochemical{color:var(--biochemical)}',
    '.electrical{color:var(--electrical)}',
    '.mechanical{color:var(--mechanical)}',
    # use var(--colour), setting them in master stylesheet included in <defs> (along with MathJax styles)
    '.celldl-Connection.bondgraph{marker-end:url(#connection-end-arrow-bondgraph)}',
    '.celldl-Connection.bondgraph.biochemical{marker-end:url(#connection-end-arrow-biochemical)}',
    '.celldl-Connection.bondgraph.electrical{marker-end:url(#connection-end-arrow-electrical)}',
    '.celldl-Connection.bondgraph.mechanical{marker-end:url(#connection-end-arrow-mechanical)}',
])

#===============================================================================

