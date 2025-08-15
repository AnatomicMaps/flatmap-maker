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

from datetime import datetime, UTC

#===============================================================================

import lark
from lark import Lark, UnexpectedInput
import rdflib

#===============================================================================

from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.shapes.colours import ColourMatcherDict
from mapmaker.utils.svg import svg_id

from .namespaces import NAMESPACES
from .namespaces import BG, BGF, DCT, RDF, MODEL

#===============================================================================

BG_FRAMEWORK_VERSION = "1.0"

#===============================================================================

NODE_BORDER_TYPES = ColourMatcherDict({
    '#042433': 'bgf:OneNode',       # dark green
    '#00B050': 'bgf:OneResistance', # green
    '#FF0000': 'bgf:ZeroStorage',   # red
})

#===============================================================================

LATEX_GRAMMAR = """
    start: _name

    _name: TEXT super? sub?
         | TEXT sub? super?

    super: "^" _block
    sub: "_" _block
    _block: _brackets | TEXT

    _brackets: "{" [ _name+ | _chem ] "}"
    _chem: "\\ce{" _formula "}"
    _formula: [ SYMBOL _exponent? ]+
    SYMBOL: /[A-Za-z]+/
    _exponent: NUMBER? _sign?
    _sign: "+" | "-"

    NUMBER: /[0-9]+/
    TEXT:   /[A-Za-z0-9\\-\\+\\.]+/
"""

latex_parser = Lark(LATEX_GRAMMAR)

#===============================================================================

def get_text(tokens: list) -> str:
#=================================
    text = []
    for token in tokens:
        if isinstance(token, lark.Token):
            if token.type == 'TEXT':
                text.append(token.value.replace('+', '').replace('-', ''))
            elif token.type in ['NUMBER', 'SYMBOL']:
                text.append(token.value)
        elif isinstance(token, lark.Tree):
            text.append(get_text(token.children))
    return ''.join(text)

def latex_to_symbol(name: str) -> str:
#====================================
    try:
        children = latex_parser.parse(name).children
    except UnexpectedInput:
        raise ValueError(f'Cannot parse LaTeX name of shape: {name}')
    base = None
    sub_text = None
    super_text = None
    for n, child in enumerate(children):
        if n == 0:
            if isinstance(child, lark.Token) and child.type == 'TEXT':
                base = child.value
        elif isinstance(child, lark.Tree):
            if child.data == 'super':
                super_text = get_text(child.children)
            elif child.data == 'sub':
                sub_text = get_text(child.children)

    if base is None:
        return name
    else:
        text = [base]
        if sub_text is not None:
            text.append(sub_text)
        if super_text is not None:
            text.append(super_text)
        return '_'.join(text)

def name_to_symbol(name: str) -> str:
#====================================
    if name.startswith('$') and name.endswith('$'):
        return ', '.join([latex_to_symbol(latex) for latex in name[1:-1].split(',')])
    return name

#===============================================================================
#===============================================================================

class BondgraphModel:
    def __init__(self, id: str, shapes: TreeList[Shape]):
        self.__graph = rdflib.Graph()

        ## This could be embedded into a CellDL diagram, separate to its
        ## CellDL structure.

        self.__uri = MODEL[id]
        for (prefix, ns) in NAMESPACES.items():
            self.__graph.bind(prefix, str(ns))
        self.__graph.add((self.__uri, RDF_NS.type, BG_NS.BondGraph))
        self.__graph.add((self.__uri, BGF_NS.hasSchema, rdflib.Literal(BG_FRAMEWORK_VERSION)))
        self.__graph.add((self.__uri, DCT_NS.created, rdflib.Literal(datetime.now(UTC).isoformat())))
        self.__process_shape_list(shapes)

    def as_turtle(self) -> bytes:
    #============================
        ttl = self.__graph.serialize(format='turtle', encoding='unicode')
        return ttl

    def as_xml(self) -> bytes:
    #=========================
        return self.__graph.serialize(format='xml', encoding='unicode')

    def set_property(self, property: rdflib.URIRef, value: rdflib.Literal|rdflib.URIRef):
    #====================================================================================
        self.__graph.add((self.__uri, property, value))

    def __process_shape_list(self, shapes: list[Shape]):
    #===================================================
        nodes: dict[str, tuple[str, str]] = {}
        bonds: dict[str, tuple[str, str]] = {}

        for shape in shapes:
            if not shape.properties.get('exclude', False):
                uri = svg_id(shape.id)
                if shape.shape_type == SHAPE_TYPE.COMPONENT:
                    if shape.has_property('stroke'):
                        stroke = shape.get_property('stroke')
                        component_type = str(NODE_BORDER_TYPES.lookup(stroke, 'unknown'))
                    elif shape.name.startswith('$q^'):
                        component_type = 'bgf:StorageNode'
                    elif shape.name.startswith('$u^'):
                        component_type = 'bgf:ZeroNode'
                    elif shape.name.startswith('$v^'):
                        component_type = 'bgf:OneNode'
                    else:
                        component_type = 'unknown'
                    if component_type != 'unknown':
                        nodes[shape.id] = (component_type, name_to_symbol(shape.name))

                elif shape.shape_type == SHAPE_TYPE.CONNECTION:
                    bonds[shape.id] = (shape.source, shape.target)

                elif shape.shape_type == SHAPE_TYPE.ANNOTATION:
                    pass

        for shape_id, bond in bonds.items():
            if bond[0] not in nodes or bond[1] not in nodes:
                raise ValueError(f'Bad bondgraph connection ({shape_id}) -- source ({bond[0]}) and/or target ({bond[1]}) missing')

#===============================================================================
