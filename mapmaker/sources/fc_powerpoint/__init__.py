#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#===============================================================================

import rtree                        # type: ignore
import shapely.geometry             # type: ignore

#===============================================================================

from mapmaker.settings import settings
from mapmaker.utils import log, FilePath, TreeList

from .. import RasterSource
from ..powerpoint import PowerpointSource, PowerpointSlide
from ..powerpoint.powerpoint import SHAPE_TYPE

#===============================================================================

CONNECTOR_CLASSES = {
    '#FF0000': 'symp',     # Source is in Brain/spinal cord
    '#0070C0': 'sensory',  # Target is in Brain/spinal cord
    '#4472C4': 'sensory',
    '#548235': 'para',     # Source is in Brain/spinal cord
}

#===============================================================================

@dataclass
class Connector:
    id: str
    source: int
    target: int
    geometry: shapely.geometry.base.BaseGeometry
    arrows: int
    properties: Dict[str, str] = field(default_factory=dict)

#===============================================================================

@dataclass
class FCFeature:
    id: int
    geometry: shapely.geometry.base.BaseGeometry
    properties: Dict[str, str] = field(default_factory=dict)
    children: List[int] = field(default_factory=list, init=False)
    parents: List[int] = field(default_factory=list, init=False)

    def __str__(self):
        return f'FCFeature(id={self.id}, children={self.children}, parents={self.parents}, properties={self.properties})'

    @property
    def colour(self):
        return self.properties.get('colour')

    @property
    def feature_class(self):
        return self.properties.get('class')

    @feature_class.setter
    def feature_class(self, cls):
        self.properties['class'] = cls

    @property
    def label(self):
        return self.properties.get('label', '').replace('\t', '|').strip()

    @property
    def models(self):
        return self.properties.get('models')

    @models.setter
    def models(self, model):
        self.properties['models'] = model

#===============================================================================

class FCPowerpoint(PowerpointSource):
    def __init__(self, flatmap, id, source_href, source_kind, source_range=None, shape_filter=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind, source_range=source_range, SlideClass=FCSlide)
        self.__shape_filter = shape_filter
        self.__shapes = []

    def filter_shape(self, shape):
        if self.__shape_filter is not None:
            if self.kind == 'fc_base':
                self.__shapes.append(shape)
            elif self.kind == 'fc_layer':
                self.__shape_filter.filter(shape)

    def process(self):
        super().process()
        if self.__shape_filter is not None and self.kind == 'fc_base':
            self.__shape_filter.add_shapes(self.__shapes)

    def get_raster_source(self):
    #===========================
        ## This is where we can create the SVG (as BytesIO())
        svg_file = Path(source_href).with_suffix('.svg')
        return RasterSource('svg', svg_file)

#===============================================================================

class FCSlide(PowerpointSlide):
    def __init__(self, source, slide, slide_number):
        super().__init__(source, slide, slide_number)
        self.__features = {
            0: FCFeature(0, self.outer_geometry)
        }
        self.__connectors = []
        self.__systems = set()
        self.__organs = set()

    def _extract_shapes(self):
    #=========================
        shapes = super()._extract_shapes()
        self.__extract_components(shapes)
        self.__label_connectors(shapes)
        for shape in shapes.flatten():
            # Add the shape to the filter if we are processing a base map,
            # or exclude it from the layer because it is similar to those
            # in the base map
            self.source.filter_shape(shape)
            if shape.id in self.__systems:
                shape.properties.pop('label', None)  # We don't want System tooltips...
        return shapes

    def __extract_components(self, shapes):
    #======================================
        # Use a spatial index to find shape containment hierarchy
        idx = rtree.index.Index()
        idx.insert(0, self.bounds, obj=self.outer_geometry)
        for shape in shapes.flatten():
            id = shape.id
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and shape.geometry.geom_type == 'Polygon':
                idx.insert(id, geometry.bounds, obj=geometry)
                self.__features[id] = FCFeature(id, geometry, shape.properties)
            elif shape.type == SHAPE_TYPE.CONNECTOR:
                start_id = shape.properties.get('connection-start')
                end_id = shape.properties.get('connection-end')
                start_arrow = shape.properties.get('head-end', 'none') != 'none'
                end_arrow = shape.properties.get('tail-end', 'none') != 'none'
                if start_arrow and not end_arrow:
                    start_id, end_id = end_id, start_id
                    if start_id is not None:
                        shape.properties['connection-start'] = start_id
                    if end_id is not None:
                        shape.properties['connection-end'] = end_id
                    arrows = 1
                elif start_arrow and end_arrow:
                    arrows = 2     ## Do we create two connections???
                elif not start_arrow and not end_arrow:
                    arrows = 0
                else:
                    arrows = 1
                line_style = shape.properties.pop('line-style', '').lower()
                if 'dot' in line_style or 'dash' in line_style:
                    shape.properties['type'] = 'line-dash'   # pre-ganglionic
                else:
                    shape.properties['type'] = 'line'        # post-ganglionic

                self.__connectors.append(Connector(id, start_id, end_id, geometry, arrows, shape.properties))

# ********               if start is None or end is None:
#                    ## Still add as connector but use colour/width to highlight
#                    log.warning('{} ends are missing: {} --> {}'
#                                .format(shape.properties['shape-name'], start, end))
#                elif arrows == 0:
#                    log.warning('{} has no direction'
# *********                                .format(shape.properties['shape-name']))

        # We use two passes to find the feature's spatial hierarchy
        non_system_features = {}
        for id, feature in self.__features.items():
            if id > 0:     # self.__features[0] == entire slide
                # List of spatial index items that intersect the feature
                items = idx.intersection(feature.geometry.bounds, objects=True)

                # Sort list by area, smallest item first
                overlaps = [i[0] for i in sorted([(item.id, item.object.area) for item in items], key = lambda x: x[1])]

                # Immediate parent is the object immediately larger than the feature
                parent_index = overlaps.index(id) + 1

                # Exclude larger features we partially intersect
                while parent_index < len(overlaps):
                    parent_geometry = self.__features[overlaps[parent_index]].geometry
                    if parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area:
        ## smaller and >= 80% common area ==> containment
                        break
                    parent_index += 1
                if (overlaps[parent_index] == 0
                and feature.label != ''
                and feature.label[-1].isupper()):
                    self.__systems.add(id)
                    self.__set_relationships(id, 0)
                else:
                    non_system_features[id] = overlaps

        # Now find parents of the non-system features
        for id, overlaps in non_system_features.items():
            feature = self.__features[id]
            parent_index = overlaps.index(id) + 1
            while parent_index < len(overlaps):
                parent_geometry = self.__features[overlaps[parent_index]].geometry
                assert parent_geometry.area >= feature.geometry.area
                if parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area:
                #if parent_geometry.contains(feature.geometry):
    ## smaller and >= 80% common area ==> containment
                    break
                parent_index += 1
            parent_id = overlaps[parent_index]
            if parent_id in self.__systems:
                if feature.label != '':
                    self.__organs.add(id)
                self.__set_relationships(id, parent_id)
                for system_id in self.__systems:
                    if (system_id != parent_id
                    and self.__features[system_id].geometry.contains(feature.geometry)):
                        self.__set_relationships(id, system_id)
            else:
                if parent_id == 0 and feature.label != '':
                    self.__organs.add(id)
                self.__set_relationships(id, parent_id)

    def __set_relationships(self, child, parent):
    #============================================
        self.__features[child].parents.append(parent)
        self.__features[parent].children.append(child)

    def __ftu_label(self, id):
    #=========================
        while (label := self.__features[id].label) == '':
            if id == 0 or id in self.__organs:
                break
            id = self.__features[id].parents[0]
        return label

    def __system_label(self, id):
    #============================
        while id != 0 and id not in self.__systems:
            id = self.__features[id].parents[0]
        return self.__features[id].label if id != 0 else ''

    def __connector_class(self, id):
    #===============================
        return CONNECTOR_CLASSES.get(self.__features[id].colour, 'unknown')

    def __connector_end_label(self, id, end):
    #========================================
        if id is not None:
            if (label := self.__ftu_label(id)) != '':
                if (system := self.__system_label(id)) != '':
                    cls = self.__connector_class(id)
                    if (cls != 'sensory') ^ system.startswith('BRAIN'):
                        end = 'Target'
                    else:
                        end = 'Source'
            return f'{end}: {label}'
        return ''

    def __label_connectors(self, shapes):
    #====================================
        for shape in shapes.flatten():
            if shape.type == SHAPE_TYPE.CONNECTOR and 'label' not in shape.properties:
                label_1 = self.__connector_end_label(shape.properties.pop('connection-start', None), 'Source')
                label_2 = self.__connector_end_label(shape.properties.pop('connection-end', None), 'Target')
                route_labels = []
                if label_1.startswith('Source'):
                    route_labels.append(label_1)
                elif label_2.startswith('Source'):
                    route_labels.append(label_2)
                if label_1.startswith('Target'):
                    route_labels.append(label_1)
                elif label_2.startswith('Target'):
                    route_labels.append(label_2)
                if len(route_labels):
                    shape.properties['label'] = '<br/>'.join(route_labels)

#===============================================================================
