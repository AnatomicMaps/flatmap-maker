#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

from datetime import datetime, timezone
from typing import BinaryIO, TYPE_CHECKING

#===============================================================================

import lxml.etree as etree
import svgelements

#===============================================================================

from mapmaker import __version__
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.geometry import Transform
from mapmaker.properties.markup import parse_markup
from mapmaker.utils import FilePath

from .. import EXCLUDED_FEATURE_TYPES, EXCLUDE_SHAPE_TYPES, EXCLUDE_TILE_LAYERS
from .utils import length_as_pixels, svg_element_from_feature, svg_markup, SVG_TAG

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap
    from mapmaker.properties import PropertiesStore

#===============================================================================

class SVGCleaner(object):
    def __init__(self, svg_file: FilePath, properties_store: 'PropertiesStore', all_layers: bool=True):
        self.__svg = etree.parse(svg_file.get_fp())
        self.__svg_root = self.__svg.getroot()

        # Add a viewBox if it's missing
        if 'viewBox' not in self.__svg_root.attrib:
            (width, height) = (length_as_pixels(self.__svg_root.attrib['width']),
                               length_as_pixels(self.__svg_root.attrib['height']))
            self.__svg_root.attrib['viewBox'] = f'0 0 {width} {height}'

        # Remove any width and height attributes
        self.__svg_root.attrib.pop('width', None)
        self.__svg_root.attrib.pop('height', None)

        self.__properties_store = properties_store
        self.__all_layers = all_layers

    def add_connectivity_group(self, flatmap: 'FlatMap', transform: Transform):
    #==========================================================================
        # add tile-layer features that don't have an 'svg-element'
        # need to add a <g> element
        if self.__all_layers:
            connectivity_group = etree.Element(SVG_TAG('g'))
            inverse_transform = svgelements.Matrix(transform.inverse().svg_matrix)
            self.__svg_root.append(connectivity_group)
            for layer in flatmap.layers:
                if layer.exported:
                    for feature in layer.features:
                        if (feature.properties.get('tile-layer') == PATHWAYS_TILE_LAYER
                        and 'Line' in feature.properties['geometry']):
                            element = svg_element_from_feature(feature, inverse_transform)
                            connectivity_group.append(element)

    def clean(self):
    #===============
        self.__filter(self.__svg_root)

    def save(self, file_object: BinaryIO):
    #=====================================
        header = ' Generator: mapmaker {} at {} '.format(__version__, datetime.now(timezone.utc).isoformat(timespec='seconds'))
        comments = self.__svg.xpath('/comment()')
        if len(comments):
            comments[0].text = header
        else:
            self.__svg_root.addprevious(etree.Comment(header))
        self.__svg.write(file_object, encoding='utf-8', pretty_print=True, xml_declaration=True)

    def __filter(self, element, parent=None):
    #========================================
        if parent is not None and self.__exclude(element):
            parent.remove(element)
            return
        for child in element:
            self.__filter(child, element)

    def __exclude(self, element):
    #============================
        markup = svg_markup(element)
        if markup.startswith('.'):
            properties = parse_markup(markup)
            properties = self.__properties_store.update_properties(properties)
            for key, value in properties.items():
                if not self.__all_layers and key == 'tile-layer' and value in EXCLUDE_TILE_LAYERS:
                    return True
                elif key in EXCLUDE_SHAPE_TYPES:
                    return True
                elif key == 'type' and value in EXCLUDED_FEATURE_TYPES:
                    return True
                elif key == 'exclude' and value:
                    return True
        return False

#===============================================================================
