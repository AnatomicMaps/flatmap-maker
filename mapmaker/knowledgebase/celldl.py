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
import zlib

#===============================================================================

import rdflib                                                   # type: ignore

#===============================================================================

from mapmaker.utils.svg import svg_id

#===============================================================================

CELLDL_SCHEMA_VERSION = '1.0'

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

RDF = rdflib.Namespace('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS = rdflib.Namespace('http://www.w3.org/2000/01/rdf-schema#')

CELLDL = rdflib.Namespace('http://celldl.org/ontologies/celldl#')
FC = rdflib.Namespace('http://celldl.org/ontologies/functional-connectivity#')

FLATMAP = rdflib.Namespace('#')

#===============================================================================

CELLDL_CLASS_TO_RDF = {
    CD_CLASS.CONDUIT: CELLDL.Conduit,
    CD_CLASS.CONNECTION: CELLDL.Connection,
    CD_CLASS.CONNECTOR: CELLDL.Connector,
    CD_CLASS.COMPONENT: CELLDL.Component,
}

#===============================================================================

GZIP_BASE64_DATA_URI = 'data:application/gzip;base64,'

#===============================================================================

class CellDLGraph:
    def __init__(self):
        self.__graph = rdflib.Graph()
        self.__graph.bind('celldl', str(CELLDL))
        self.__graph.bind('fc', str(FC))
        this = FLATMAP['']
        self.__graph.add((this, RDF.type, CELLDL.Document))
        self.__graph.add((this, CELLDL.schema, rdflib.Literal(CELLDL_SCHEMA_VERSION)))
        self.__graph.add((this, RDF.type, FC.Diagram))

    def add_metadata(self, shape):
    #=============================
        if shape.exclude or shape.cd_class not in CELLDL_CLASS_TO_RDF:
            return
        this = FLATMAP[svg_id(shape.id)]
        self.__graph.add((this, RDF.type, CELLDL_CLASS_TO_RDF[shape.cd_class]))
        self.__graph.add((this, RDF.type, FC[shape.fc_class.split(':')[-1]]))
        if shape.label:
            self.__graph.add((this, RDFS.label, rdflib.Literal(shape.label))) ## add port/node in XXX ??
        if (shape.name
            and (shape.label is None
              or shape.name.lower() != shape.label.lower())):
            self.__graph.add((this, RDFS.comment, rdflib.Literal(shape.name)))
        ## models (layers...)
        if shape.cd_class == CD_CLASS.CONNECTION:
            if shape.fc_class == FC_CLASS.NEURAL:
                self.__graph.add((this, FC.connectionType, rdflib.Literal(shape.path_type.name)))
            for id in shape.connector_ids:
                self.__graph.add((this, CELLDL.hasConnector, FLATMAP[svg_id(id)]))
            for id in shape.intermediate_connectors:
                self.__graph.add((this, CELLDL.hasIntermediate, FLATMAP[svg_id(id)]))
            for id in shape.intermediate_components:
                self.__graph.add((this, CELLDL.hasIntermediate, FLATMAP[svg_id(id)]))

    def as_encoded_turtle(self):
    #===========================
        turtle = self.__graph.serialize(format='turtle', encoding='utf-8')
        return f'{GZIP_BASE64_DATA_URI}{base64.b64encode(zlib.compress(turtle)).decode()}'

    def as_xml(self):
    #================
        return self.__graph.serialize(format='xml', encoding='utf-8')

#===============================================================================
