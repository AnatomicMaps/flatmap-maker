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

from collections import defaultdict
from dataclasses import dataclass, field

import lxml.etree as etree

#===============================================================================

from mapmaker.rdf import NamedNode, Namespace, RdfGraph, RDFS

from .utils import SVG_TAG

#===============================================================================

BGF = Namespace('https://bg-rdf.org/ontologies/bondgraph-framework#')

#===============================================================================

@dataclass(kw_only=True)
class NameLabel:
    name: str = field(default_factory=str)
    label: str = field(default_factory=str)

#===============================================================================

QUERY_LABELS = """
    SELECT ?element_id ?p ?label WHERE {
        ?element_id rdfs:label ?label
    }
"""

QUERY_NAMES = """
    SELECT ?element_id ?symbol ?species ?location WHERE {
        ?element_id bgf:hasSymbol ?symbol .
        OPTIONAL { ?element_id bgf:hasSpecies ?species }
        OPTIONAL { ?element_id bgf:hasLocation ?location }
    }
"""

#===============================================================================

def get_metadata_names(source_href: str, layer_id: str, svg_element: etree.Element) -> defaultdict[str, NameLabel]:
    # Create a RDF graph and populate it with the SVG's CellDL metadata
    rdf_graph = RdfGraph({
        '': f'{source_href}#',
        'bgf': str(BGF),
        'rdfs': str(RDFS)
    })
    metadata_element = svg_element.find(f'.//{SVG_TAG('metadata')}[@id="celldl-rdf-metadata"]')
    if metadata_element is not None:
        if metadata_element.attrib.get('data-content-type') == 'text/turtle':
            rdf_graph.load(source_href, str(metadata_element.text))

    self_prefix = f'{source_href}#'
    def get_id(uri) -> str|None:
        if uri is not None and uri.value.startswith(self_prefix):
            return f'{layer_id}/{uri.value[len(self_prefix):]}'

    name_labels = defaultdict(NameLabel)
    for row in rdf_graph.query(QUERY_LABELS):
        if (element_id := get_id(row['element_id'])) is not None:
            if (label_literal := row['label']) is not None:
                name_labels[element_id].label = label_literal.value
    for row in rdf_graph.query(QUERY_NAMES):
        if (element_id := get_id(row['element_id'])) is not None:
            if (symbol_literal := row['symbol']) is not None:
                latex = [f'{{{symbol_literal.value}}}']
                if row['species'] is not None:
                    latex.append(f'^{{{row['species'].value}}}')
                if row['location'] is not None:
                    latex.append(f'_{{{row['location'].value}}}')
                name_labels[element_id].label = f'${''.join(latex)}$'

    return name_labels

#===============================================================================
#===============================================================================
