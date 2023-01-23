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

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

#===============================================================================

import shapely.geometry
import shapely.strtree

#===============================================================================

from mapmaker.settings import settings
from mapmaker.utils import log, TreeList

from ..powerpoint import PowerpointSource, PowerpointLayer, Slide, SHAPE_TYPE
from ..shapefilter import ShapeFilter, ShapeFilters

#===============================================================================

CONNECTOR_CLASSES = {
    '#FF0000': 'symp',     # Source is in Brain/spinal cord
    '#0070C0': 'sensory',  # Target is in Brain/spinal cord
from .json_annotator import JsonAnnotator
from .xlsx_annotator import XlsxAnnotator
from .annotation import Annotator

def create_annotator(annotation_file: str) -> Annotator:
#=======================================================
    if annotation_file.endswith('.json'):
        return JsonAnnotator(annotation_file)
    elif annotation_file.endswith('.xlsx'):
        return XlsxAnnotator(annotation_file)
    else:
        raise TypeError('Unsupported annotation file format: {annotation_file}')

#===============================================================================

    '#4472C4': 'sensory',
    '#548235': 'para',     # Source is in Brain/spinal cord
}

#===============================================================================

@dataclass
class Connector:
    id: str
    source: Optional[int]
    target: Optional[int]
    geometry: shapely.geometry.base.BaseGeometry
    arrows: int
    properties: dict[str, str] = field(default_factory=dict)

#===============================================================================

@dataclass
class FCFeature:
    id: int
    geometry: shapely.geometry.base.BaseGeometry
    properties: dict[str, str] = field(default_factory=dict)
    children: list[int] = field(default_factory=list, init=False)
    parents: list[int] = field(default_factory=list, init=False)

    def __post_init__(self):
        label = self.properties.pop('label', '').replace('\t', '|').strip()
        self.properties['name'] = label
        self.properties['label'] = f'{self.id}: {label}' if settings.get('authoring', False) else label

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
        return self.properties.get('label', self.name)

    @property
    def models(self):
        return self.properties.get('models')

    @property
    def name(self):
        return self.properties.get('name', '')

    @models.setter
    def models(self, model):
        self.properties['models'] = model

#===============================================================================

class SVGShapeFilter(ShapeFilter):
    def add_shape(self, shape):
        super().add_shape(shape)

    def filter(self, shape):
        super().filter(shape)

class MapShapeFilter(ShapeFilter):
    def add_shape(self, shape):
        super().add_shape(shape)

class FCShapeFilters(ShapeFilters):
    def __init__(self):
        super().__init__(map_filter=MapShapeFilter, svg_filter=SVGShapeFilter)

#===============================================================================

    def __init__(self, flatmap, id, source_href, source_kind, source_range=None, shape_filters=None, annotator=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind, source_range=source_range, SlideClass=FCSlide)
class FCPowerpointSource(PowerpointSource):
        super().__init__(flatmap, id, source_href, source_kind=source_kind,
                         source_range=source_range, SlideLayerClass=FCSlideLayer,
                         shape_filters=shape_filters)
        self.__annotator = annotator



#===============================================================================

class FCSlideLayer(PowerpointLayer):   ## Shouldn't this be `FCSlide`, extending `Slide`??
    def __init__(self, source: FCPowerpointSource, slide: Slide, slide_number: int):
        super().__init__(source, slide, slide_number)
        self.__fc_features: dict[int, FCFeature] = {
            0: FCFeature(0, self.outer_geometry)
        }
        self.__connectors: list[Connector] = []
        self.__systems: set[int] = set()
        self.__organs: set[int] = set()

    @property
    def connectors(self) -> list[Connector]:
        return self.__connectors

    @property
    def fc_features(self) -> dict[int, FCFeature]:
        return self.__fc_features

    @property
    def organs(self) -> set[int]:
        return self.__organs

    @property
    def systems(self) -> set[int]:
        return self.__systems

    def process(self):
    #=================
        super().process()
        self.source.annotate(self)

    def _extract_shapes(self) -> TreeList:
    #=====================================
        shapes = super()._extract_shapes()
        self.__extract_components(shapes)
        self.__label_connectors(shapes)
        for shape in shapes.flatten():
            # Add the shape to the filter if we are processing a base map,
            # or exclude it from the layer because it is similar to those
            # in the base map
            self.source.filter_map_shape(shape)
            if shape.id in self.__systems:
                shape.properties.pop('label', None)  # We don't want System tooltips...
        return shapes

    def __extract_components(self, shapes: TreeList):
    #================================================
        geometries = [self.outer_geometry]
        shape_ids = {id(self.outer_geometry): 0}     # id(geometry) --> shape.id
        for shape in shapes.flatten():
            shape_id = shape.id
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and shape.geometry.geom_type == 'Polygon':
                geometries.append(geometry)
                shape_ids[id(geometry)] = shape_id
                self.__fc_features[shape_id] = FCFeature(shape_id, geometry, shape.properties.copy())
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

                self.__connectors.append(Connector(shape_id, start_id, end_id, geometry, arrows, shape.properties))

# ********               if start is None or end is None:
#                    ## Still add as connector but use colour/width to highlight
#                    log.warning('{} ends are missing: {} --> {}'
#                                .format(shape.properties['shape-name'], start, end))
#                elif arrows == 0:
#                    log.warning('{} has no direction'
# *********                                .format(shape.properties['shape-name']))

        # Use a spatial index to find shape containment hierarchy
        idx = shapely.strtree.STRtree(geometries)

        # We use two passes to find the feature's spatial hierarchy
        non_system_features = {}
        for shape_id, feature in self.__fc_features.items():
            if shape_id > 0:     # self.__fc_features[0] == entire slide
                # List of geometries that intersect the feature
                intersecting_geometries = idx.query(feature.geometry)

                # Sort geometries by area, smallest item first
                overlaps = [shape_ids[i[0]]
                                for i in sorted([(id(geometries[index]), geometries[index].area)
                                                    for index in intersecting_geometries],
                                                key = lambda x: x[1])
                           ]

                # Immediate parent is the object immediately larger than the feature
                parent_index = overlaps.index(shape_id) + 1

                # Exclude larger features we partially intersect
                while parent_index < len(overlaps):
                    parent_geometry = self.__fc_features[overlaps[parent_index]].geometry
                    if parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area:
        ## smaller and >= 80% common area ==> containment
                        break
                    parent_index += 1
                if (overlaps[parent_index] == 0
                and feature.label != ''
                and feature.label[-1].isupper()):
                    self.__systems.add(shape_id)
                    self.__set_relationships(shape_id, 0)
                else:
                    non_system_features[shape_id] = overlaps

        # Now find parents of the non-system features
        for shape_id, overlaps in non_system_features.items():
            feature = self.__fc_features[shape_id]
            parent_index = overlaps.index(shape_id) + 1
            while parent_index < len(overlaps):
                parent_geometry = self.__fc_features[overlaps[parent_index]].geometry
                assert parent_geometry.area >= feature.geometry.area
                if parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area:
                #if parent_geometry.contains(feature.geometry):
    ## smaller and >= 80% common area ==> containment
                    break
                parent_index += 1
            parent_id = overlaps[parent_index]
            if parent_id in self.__systems:
                if feature.label != '':
                    self.__organs.add(shape_id)
                self.__set_relationships(shape_id, parent_id)
                for system_id in self.__systems:
                    if (system_id != parent_id
                    and self.__fc_features[system_id].geometry.contains(feature.geometry)):
                        self.__set_relationships(shape_id, system_id)
            else:
                if parent_id == 0 and feature.label != '':
                    self.__organs.add(shape_id)
                self.__set_relationships(shape_id, parent_id)

    def __set_relationships(self, child: int, parent: int):
    #======================================================
        self.__fc_features[child].parents.append(parent)
        self.__fc_features[parent].children.append(child)

    def __ftu_label(self, shape_id: int) -> str:
    #===========================================
        while (label := self.__fc_features[shape_id].label) == '':
            if shape_id == 0 or shape_id in self.__organs:
                break
            shape_id = self.__fc_features[shape_id].parents[0]
        return label

    def __system_label(self, shape_id: int) -> str:
    #==============================================
        while shape_id != 0 and shape_id not in self.__systems:
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id].label if shape_id != 0 else ''

    def __connector_class(self, shape_id: int) -> str:
    #=================================================
        return CONNECTOR_CLASSES.get(self.__fc_features[shape_id].colour, 'unknown')

    def __connector_end_label(self, shape_id: Optional[int]) -> str:
    #===============================================================
        if shape_id is not None:
            if (label := self.__ftu_label(shape_id)) != '':
                cls = self.__connector_class(shape_id)
                if cls == 'unknown':
                    # NB. Some of these are have junction colours...
                    log.warning(f'FTU {label} has unknown class for connector {shape_id}, colour: {self.__fc_features[shape_id].colour}')
                    return ''
                system_label = self.__system_label(shape_id)
                if system_label == '':
                    # NB. 'Breasts' are in three systems but none are assigned...
                    log.warning(f'Cannot determine system for connector {shape_id} in FTU {label}')
                    return ''
                if cls == 'sensory':
                    end = 'Target' if system_label.startswith('BRAIN') else 'Source'
                else:
                    end = 'Source' if system_label.startswith('BRAIN') else 'Target'
                return f'{end}: {label}'
        return ''

    def __label_connectors(self, shapes: TreeList):
    #==============================================
        for shape in shapes.flatten():
            if shape.type == SHAPE_TYPE.CONNECTOR and 'label' not in shape.properties:
                label_1 = self.__connector_end_label(shape.properties.pop('connection-start', None))
                label_2 = self.__connector_end_label(shape.properties.pop('connection-end', None))
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
