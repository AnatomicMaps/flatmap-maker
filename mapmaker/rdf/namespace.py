#===============================================================================
#
#  CellDL and bondgraph tools
#
#  Copyright (c) 2020 - 2026 David Brooks
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

from typing import cast

#===============================================================================

from .rdfgraph import NamedNode, namedNode

#===============================================================================

"""
Generate NamedNodes.
"""
class Namespace:
    def __init__(self, ns: str):
        self.__ns = ns

    def __str__(self):
        return self.__ns

    def __getattr__(self, attr: str='') -> NamedNode:
        return cast(NamedNode, namedNode(f'{self.__ns}{attr}'))

#===============================================================================

RDF = Namespace('http://www.w3.org/1999/02/22-rdf-syntax-ns#')
RDFS = Namespace('http://www.w3.org/2000/01/rdf-schema#')
XSD = Namespace('http://www.w3.org/2001/XMLSchema#')

#===============================================================================
