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
from io import BytesIO, StringIO
from pathlib import Path

#===============================================================================

import shapely.geometry
import shapely.strtree

#===============================================================================

from mapmaker.settings import settings
from mapmaker.utils import log, FilePath, TreeList

from .. import RasterSource
from ..powerpoint import PowerpointSource, PowerpointSlide
from ..powerpoint.powerpoint import SHAPE_TYPE
from ..powerpoint.pptx2svg import Pptx2Svg

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
    properties: dict[str, str] = field(default_factory=dict)

#===============================================================================

@dataclass
class FCFeature:
    id: int
    geometry: shapely.geometry.base.BaseGeometry
    properties: dict[str, str] = field(default_factory=dict)
    children: list[int] = field(default_factory=list, init=False)
    parents: list[int] = field(default_factory=list, init=False)

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
    def __init__(self, flatmap, id, source_href, source_kind, source_range=None, shape_filters=None, annotation_set=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind, source_range=source_range, SlideClass=FCSlide)
        self.__annotation_set = annotation_set
        if shape_filters is not None:
            self.__map_shape_filter = shape_filters.map_filter
            self.__svg_shape_filter = shape_filters.svg_filter
        else:
            self.__map_shape_filter = None
            self.__svg_shape_filter = None

    def annotate(self, slide):
    #=========================
        if self.__annotation_set is None:
            return
        for id in slide.systems:
            self.__annotation_set.add_system(slide.fc_features[id].label, self.id)
        for id in slide.organs:
            self.__annotation_set.add_organ(slide.fc_features[id].label, self.id,
                tuple(slide.fc_features[system_id].label for system_id in slide.fc_features[id].parents if system_id != 0)
                )
        for feature in slide.fc_features.values():
            if feature.label != '':
                organ_id = None
                for parent in feature.parents:
                    if parent in slide.organs:
                        organ_id = parent
                        break
                if organ_id is not None:
                    if len(feature.parents) > 1:
                        log.warning(f'FTU {feature} in multiple organs')
                    else:
                        self.__annotation_set.add_ftu(slide.fc_features[organ_id].label, feature.label, self.id)

    def filter_map_shape(self, shape):
    #=================================
        # Called as each shape is extracted from a slide
        if self.__map_shape_filter is not None:
            if self.kind == 'base':
                self.__map_shape_filter.add_shape(shape)
            elif self.kind == 'layer':
                self.__map_shape_filter.filter(shape)

    def process(self):
    #=================
        super().process()
        if self.__map_shape_filter is not None and self.kind == 'base':
            self.__map_shape_filter.create_filter()

    def get_raster_source(self):
    #===========================
        return RasterSource('svg', self.__get_raster_data)

    def __get_raster_data(self):
    #===========================
        svg_extractor = Pptx2Svg(self.source_href,
            kind=self.kind, shape_filter=self.__svg_shape_filter)
        svg_extractor.slides_to_svg()
        for layer in svg_extractor.svg_layers:
            svg = StringIO()
            layer.save(svg)
            svg_bytes = BytesIO(svg.getvalue().encode('utf-8'))
            svg.close()
            svg_bytes.seek(0)
            return svg_bytes

#===============================================================================

class FCSlide(PowerpointSlide):
    def __init__(self, source, slide, slide_number):
        super().__init__(source, slide, slide_number)
        self.__fc_features = {
            0: FCFeature(0, self.outer_geometry)
        }
        self.__connectors = []
        self.__systems = set()
        self.__organs = set()

    @property
    def connectors(self):
        return self.__connectors

    @property
    def fc_features(self):
        return self.__fc_features

    @property
    def organs(self):
        return self.__organs

    @property
    def systems(self):
        return self.__systems

    def process(self):
    #=================
        super().process()
        self.source.annotate(self)

    def _extract_shapes(self):
    #=========================
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

    def __extract_components(self, shapes):
    #======================================
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
                                for i in sorted([(id(geometry), geometry.area)
                                                    for geometry in intersecting_geometries],
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

    def __set_relationships(self, child, parent):
    #============================================
        self.__fc_features[child].parents.append(parent)
        self.__fc_features[parent].children.append(child)

    def __ftu_label(self, shape_id):
    #===============================
        while (label := self.__fc_features[shape_id].label) == '':
            if shape_id == 0 or shape_id in self.__organs:
                break
            shape_id = self.__fc_features[shape_id].parents[0]
        return label

    def __system_label(self, shape_id):
    #==================================
        while shape_id != 0 and shape_id not in self.__systems:
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id].label if shape_id != 0 else ''

    def __connector_class(self, shape_id):
    #=====================================
        return CONNECTOR_CLASSES.get(self.__fc_features[shape_id].colour, 'unknown')

    def __connector_end_label(self, shape_id):
    #=========================================
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

    def __label_connectors(self, shapes):
    #====================================
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
