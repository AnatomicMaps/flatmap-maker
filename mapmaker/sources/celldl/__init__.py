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

import copy
import itertools
from pathlib import Path
from typing import Optional

#===============================================================================

import lxml.etree as etree
import rdflib

#===============================================================================

from mapmaker.geometry import Transform
from mapmaker.knowledgebase.celldl import BG_NS, CellDLGraph, DCT_NS
from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.sources.svg.utils import length_as_pixels
from mapmaker.utils import TreeList, SVG_NS
from mapmaker.utils.svg import svg_id

from .definitions import CELLDL_DEFINITIONS_ID, CELLDL_LAYER_CLASS, CELLDL_METADATA_ID, CELLDL_STYLESHEET_ID, DIAGRAM_LAYER
from .definitions import BondgraphStylesheet, BondgraphSvgDefinitions, CellDLStylesheet

#===============================================================================

class EXPORT_TYPE:
    BONDGRAPH = 'bondgraph'

#===============================================================================

MAXIMIMUM_SMALLEST_SVG_DIMENSION = 1200

#===============================================================================

# If successive x-coordinates (y-coordinates) of a path are within this distance then the
# connecting line segment is considered to be horizontal (vertical)

PATH_EPSILON = 0.5     # pixels

#===============================================================================

etree.register_namespace('svg', str(SVG_NS))

#===============================================================================

class CellDLExporter:
    def __init__(self, svg_root: etree.Element, source_href: str, world_to_pixels: Transform,
                 export_type: Optional[str]=EXPORT_TYPE.BONDGRAPH):
        self.__celldl = CellDLGraph(BG_NS.Model if export_type == EXPORT_TYPE.BONDGRAPH else None)
        self.__celldl.set_property(DCT_NS.source, rdflib.URIRef(source_href))
        self.__svg_root = svg_root
        self.__world_to_pixels = world_to_pixels
        self.__export_type = export_type

        celldl_defs = svg_root.find(f'.//{SVG_NS.defs}[@id="{CELLDL_DEFINITIONS_ID}"]')
        if celldl_defs is None:
            celldl_defs = svg_root.find(f'.//{SVG_NS.defs}')
            if celldl_defs is not None:
                celldl_defs.attrib['id'] = CELLDL_DEFINITIONS_ID
            else:
                celldl_defs = etree.SubElement(svg_root, SVG_NS.defs, {
                    'id': CELLDL_DEFINITIONS_ID
                })
            if export_type == EXPORT_TYPE.BONDGRAPH:
                celldl_defs.extend(BondgraphSvgDefinitions)

        celldl_style = celldl_defs.find(f'.//{SVG_NS.style}[@id="{CELLDL_STYLESHEET_ID}"]')
        if celldl_style is None:
            celldl_style = etree.SubElement(celldl_defs, SVG_NS.style, {
                'id': CELLDL_STYLESHEET_ID
            })
            stylesheets = [CellDLStylesheet]
            if export_type == EXPORT_TYPE.BONDGRAPH:
                stylesheets.append(BondgraphStylesheet)
            celldl_style.text = '\n'.join(stylesheets)

        celldl_diagram = etree.Element(SVG_NS.g, {
            'id': DIAGRAM_LAYER,
            'class': CELLDL_LAYER_CLASS
        })
        viewbox = self.__check_viewbox()
        for child in svg_root:
            if child.tag != SVG_NS.defs:
                celldl_diagram.append(child)
        svg_root.append(celldl_diagram)         # Need to append after above copy/move
        self.__connection_group = etree.SubElement(celldl_diagram, SVG_NS.g)
        self.__annotation_group = etree.SubElement(celldl_diagram, SVG_NS.g)
        self.__metadata_element = etree.Element(SVG_NS.metadata, {
            'id': CELLDL_METADATA_ID,
            'data-content-type': 'text/turtle'
        })
        svg_root.insert(0, self.__metadata_element)

    def process(self, shapes: TreeList[Shape]):
    #==========================================
        self.__process_shape_list(shapes) ##, self.__diagram)

    def save(self, path: Path):
    #==========================
        self.__metadata_element.text = etree.CDATA(self.__celldl.as_turtle())
        svg_tree = etree.ElementTree(self.__svg_root)
        svg_tree.write(path,
            encoding='utf-8', #inclusive_ns_prefixes=['svg'],
            pretty_print=True, xml_declaration=True)

    def __check_viewbox(self) -> tuple[float, float, float, float]:
    #==============================================================
        width = self.__svg_root.attrib.pop('width', None)
        height = self.__svg_root.attrib.pop('height', None)
        if 'viewBox' not in self.__svg_root.attrib:
            self.__svg_root.attrib['viewBox'] = f'0 0 {length_as_pixels(width):.1f} {length_as_pixels(height):.1f}'
        return tuple(float(i) for i in self.__svg_root.attrib['viewBox'].split())   # type: ignore

    def __process_shape_list(self, shapes: TreeList[Shape]): #, group: etree.Element):
    #=======================================================
        for shape in shapes[0:]:
            if isinstance(shape, TreeList):
                self.__process_shape_list(shape)
            elif not shape.properties.get('exclude', False):
                if (svg_element := shape.get_property('svg-element')) is not None:
                    element_id = svg_id(shape.id)
                    if (svg_class := self.__celldl.add_shape(shape)) is not None:
                        if shape.shape_type == SHAPE_TYPE.CONNECTION:
                            geometry = self.__world_to_pixels.transform_geometry(shape.geometry)
                            coords = [f'{coord[0]} {coord[1]}' for coord in geometry.coords]
                            attributes = {
                                'id': element_id,
                                'd': f'M{coords[0]}L{"L".join(coords[1:])}'
                            }
                            classes = [svg_class]
                            connection_style = 'rectilinear'
                            for (c1, c2) in itertools.pairwise(geometry.coords):
                                if (abs(c1[0] - c2[0]) > PATH_EPSILON
                                and abs(c1[1] - c2[1]) > PATH_EPSILON):
                                    connection_style = 'linear'
                                    break
                            classes.append(connection_style)
                            if shape.properties.get('directional', False):
                                classes.append('arrow')
                            if self.__export_type == EXPORT_TYPE.BONDGRAPH:
                                classes.append('bondgraph')
                            if (colour := shape.properties.get('colour')) is not None:
                                attributes['style'] = f'stroke: {colour}'
                            attributes['class'] = ' '.join(classes)
                            svg_element.getparent().remove(svg_element)
                            svg_element = etree.SubElement(self.__connection_group, SVG_NS.path, attributes)
                        elif (text_shapes := shape.get_property('text-shapes')) is not None:
                            shape_element = copy.deepcopy(svg_element)
                            svg_element.tag = SVG_NS.g
                            svg_element.attrib.clear()
                            svg_element.attrib['id'] = element_id
                            svg_element.attrib['class'] = svg_class
                            svg_element.append(shape_element)
                            svg_element.extend([element for text_shape in text_shapes
                                                    if (element := text_shape.get_property('svg-element')) is not None])
                            shape.set_property('svg-element', svg_element)
                            if shape.shape_type == SHAPE_TYPE.ANNOTATION:
                                self.__annotation_group.append(svg_element)
                        else:
                            svg_element.attrib['id'] = element_id
                            svg_element.attrib['class'] = ' '.join(svg_element.attrib.get('class', '').split() + [svg_class])

#===============================================================================
