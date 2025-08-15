#===============================================================================
#
#  Flatmap maker and annotation tools
#
#  Copyright (c) 2019 - 2025  David Brooks
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

import rdflib

#===============================================================================

DCT = rdflib.Namespace('http://purl.org/dc/terms/')
CDT = rdflib.Namespace('https://w3id.org/cdt/')
RDF = rdflib.Namespace('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS = rdflib.Namespace('http://www.w3.org/2000/01/rdf-schema#')

#===============================================================================

BG = rdflib.Namespace('http://celldl.org/ontologies/bondgraph#')
BGF = rdflib.Namespace('http://celldl.org/ontologies/bondgraph-framework#')
MODEL = rdflib.Namespace('#')

#===============================================================================

NAMESPACES = {
    'bg': BG,
    'bgf': BGF,
    'cdt': CDT,
    'dct': DCT,
    'rdfs': RDFS,
    '': MODEL
}

#===============================================================================
