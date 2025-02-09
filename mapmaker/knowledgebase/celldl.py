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

import base64
from datetime import datetime, UTC
from typing import Optional
import zlib

#===============================================================================

import rdflib                                                   # type: ignore

#===============================================================================

from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.utils.svg import svg_id

#===============================================================================

CELLDL_SCHEMA_VERSION = '2.0'

#===============================================================================

class CD_CLASS:
    UNKNOWN    = 'celldl:Unknown'
    LAYER      = 'celldl:Layer'

    COMPONENT  = 'celldl:Component'     # What has CONNECTORs

    CONNECTOR  = 'celldl:Connector'     # What a CONNECTION connects to
    CONNECTION = 'celldl:Connection'    # The path between CONNECTORS
    CONDUIT    = 'celldl:Conduit'       # A container for CONNECTIONs

    MEMBRANE   = 'celldl:Membrane'      # A boundary around a collection of COMPONENTS

    ANNOTATION = 'celldl:Annotation'    # Additional information about something

#===============================================================================

class FC_CLASS:
    UNKNOWN     = 'fc:Unknown'
    LAYER       = 'fc:Layer'

    # Component classes
    SYSTEM      = 'fc:System'
    ORGAN       = 'fc:Organ'
    FTU         = 'fc:Ftu'

    # Connector, Connection, and Conduit classes
    NEURAL      = 'fc:Neural'
    VASCULAR    = 'fc:Vascular'

    # Annotation classes
    DESCRIPTION = 'fc:Description'
    HYPERLINK   = 'fc:Hyperlink'

#===============================================================================

class FC_KIND:
    UNKNOWN              = 'fc-kind:Unknown'

    # WIP: System kinds (is this independent to FC_KIND?)
    NERVOUS_SYSTEM       = 'fc-kind:NervousSystem'
    CARDIOVASCULAR_SYSTEM = 'fc-kind:CardiovascularSystem'

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

    # Hyperlink kinds
    HYPERLINK_WIKIPEDIA  = 'fc-kind:HyperlinkWikipedia'
    HYPERLINK_PUBMED     = 'fc-kind:HyperlinkPubMed'
    HYPERLINK_PROVENANCE = 'fc-kind:HyperlinkProvenance'

#===============================================================================

DCT_NS = rdflib.Namespace('http://purl.org/dc/terms/')
RDF_NS = rdflib.Namespace('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS_NS = rdflib.Namespace('http://www.w3.org/2000/01/rdf-schema#')

#===============================================================================

BG_NS = rdflib.Namespace('http://celldl.org/ontologies/bond-graph#')
CELLDL_NS = rdflib.Namespace('http://celldl.org/ontologies/celldl#')
FC_NS = rdflib.Namespace('http://celldl.org/ontologies/functional-connectivity#')

STANDARD_NAMESPACES = {
    'celldl': CELLDL_NS,
    'dct': DCT_NS
}

KNOWN_NAMESPACES = {
    'bg': BG_NS,
    'fc': FC_NS,
}

#===============================================================================

CELLDL_TYPE_FROM_CLASS = {
    CD_CLASS.CONDUIT: CELLDL_NS.Conduit,
    CD_CLASS.CONNECTION: CELLDL_NS.Connection,
    CD_CLASS.CONNECTOR: CELLDL_NS.Connector,
    CD_CLASS.COMPONENT: CELLDL_NS.Component,
}

#===============================================================================

GZIP_BASE64_DATA_URI = 'data:application/gzip;base64,'

#===============================================================================

CELLDL_CLASS_FROM_SHAPE_TYPE = {
    SHAPE_TYPE.COMPONENT: CD_CLASS.COMPONENT,
    SHAPE_TYPE.CONNECTION: CD_CLASS.CONNECTION,
    SHAPE_TYPE.CONTAINER: CD_CLASS.COMPONENT
}

#===============================================================================

DIAGRAM_NS = rdflib.Namespace('#')

def make_uri(shape_id: str) -> rdflib.URIRef:
    return DIAGRAM_NS[svg_id(shape_id)]

#===============================================================================

class CellDLGraph:
    def __init__(self, diagram_type: Optional[rdflib.URIRef]=None):
        self.__graph = rdflib.Graph()
        self.__diagram = make_uri('')
        self.__graph.bind('', str(DIAGRAM_NS))
        for (prefix, ns) in STANDARD_NAMESPACES.items():
            self.__graph.bind(prefix, str(ns))
        self.__graph.add((self.__diagram, RDF_NS.type, CELLDL_NS.Document))
        self.__graph.add((self.__diagram, CELLDL_NS.schema, rdflib.Literal(CELLDL_SCHEMA_VERSION)))
        if diagram_type is not None:
            for (prefix, ns) in KNOWN_NAMESPACES.items():
                if str(diagram_type).startswith(str(ns)):
                    self.__graph.bind(prefix, str(ns))
            self.__graph.add((self.__diagram, RDF_NS.type, diagram_type))
        self.__graph.add((self.__diagram, DCT_NS.created, rdflib.Literal(datetime.now(UTC).isoformat())))

    def add_shape(self, shape: Shape) -> Optional[str]:
    #==================================================
        if (shape.exclude
         or shape.shape_type not in CELLDL_CLASS_FROM_SHAPE_TYPE
         or shape.id is None):
            return
        this = make_uri(shape.id)
        celldl_class = CELLDL_CLASS_FROM_SHAPE_TYPE[shape.shape_type]
        self.__graph.add((this, RDF_NS.type, CELLDL_TYPE_FROM_CLASS[celldl_class]))
        if shape.label:
            self.__graph.add((this, RDFS_NS.label, rdflib.Literal(shape.label))) ## add port/node in XXX ??
        if (shape.name
            and (shape.label is None
              or shape.name.lower() != shape.label.lower())):
            self.__graph.add((this, RDFS_NS.comment, rdflib.Literal(shape.name)))
        if celldl_class == CD_CLASS.CONNECTION:
            if (source := shape.get_property('source')) is not None:
                self.__graph.add((this, CELLDL_NS.hasSource, make_uri(source)))
            if (target := shape.get_property('target')) is not None:
                self.__graph.add((this, CELLDL_NS.hasTarget, make_uri(target)))
        return celldl_class.replace(':', '-')

    def as_encoded_turtle(self):
    #===========================
        turtle = self.__graph.serialize(format='turtle', encoding='utf-8')
        return f'{GZIP_BASE64_DATA_URI}{base64.b64encode(zlib.compress(turtle)).decode()}'

    def as_turtle(self) -> bytes:
    #============================
        return self.__graph.serialize(format='turtle', encoding='utf-8')

    def as_xml(self) -> bytes:
    #=========================
        return self.__graph.serialize(format='xml', encoding='utf-8')

    def set_property(self, property: rdflib.URIRef, value: rdflib.Literal|rdflib.URIRef):
    #====================================================================================
        self.__graph.add((self.__diagram, property, value))

#===============================================================================
