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

from typing import Optional

#===============================================================================

from pptx.slide import Slide as PptxSlide
import networkx as nx

import shapely.geometry
import shapely.prepared
import shapely.strtree

#===============================================================================

from mapmaker.annotation import Annotator
from mapmaker.geometry import Transform
from mapmaker.settings import settings
from mapmaker.sources import MapBounds
from mapmaker.utils import log, TreeList

from ..shapefilter import ShapeFilter, ShapeFilters
from ..powerpoint import PowerpointSource, Slide, SHAPE_TYPE
from ..powerpoint.colour import ColourTheme

#===============================================================================

from .features import CONNECTION_CLASSES, Connector, FC, FC_Class, FCFeature
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

class FCPowerpointSource(PowerpointSource):
    def __init__(self, flatmap, id, source_href, source_kind, source_range=None,
                 shape_filters=None):
        super().__init__(flatmap, id, source_href, source_kind=source_kind,
                         shape_filters=shape_filters)
                         source_range=source_range, SlideClass=FCSlide,
                         SlideClass=FCSlide)



#===============================================================================

class FCSlide(Slide):
    def __init__(self, source_id: str, kind: str, index: int, pptx_slide: PptxSlide, theme: ColourTheme,
                 bounds: MapBounds, transform: Transform):
        super().__init__(source_id, kind, index, pptx_slide, theme, bounds, transform)
        self.__outer_geometry_prepared = shapely.prepared.prep(self.geometry)
        self.__fc_features: dict[int, FCFeature] = {
            0: FCFeature(0, self.geometry)
        }
        self.__connectors: dict[int, Connector] = {}
        self.__systems: set[int] = set()
        self.__organs: set[int] = set()
        self.__connection_graph = nx.Graph()
        self.__circuit_graph = nx.Graph()
        self.__unknown_colours = set()
        self.__seen_shape_kinds = set()
        self.__smallest_shape_area = 10000000000

    def process(self):
    #=================
        shapes = super().process()

        # Find circuits
        self.__extract_shapes(shapes)

        seen_nodes = set()
        self.__circuit_graph = nx.Graph()
        for (source, degree) in self.__connection_graph.degree():       # type: ignore
            if degree == 1 and source not in seen_nodes:
                self.__circuit_graph.add_node(source)
                seen_nodes.add(source)
                for target, _ in nx.shortest_path(self.__connection_graph, source=source).items():  # type: ignore
                    if target != source and self.__connection_graph.degree(target) == 1:
                        self.__circuit_graph.add_node(target)
                        self.__circuit_graph.add_edge(source, target)
                        seen_nodes.add(target)
            elif degree >= 3:
                log.warning(f'Node {source}/{degree} is a branch point...')
    def annotate(self, annotator: Annotator):
    #========================================
        # Called after shapes have been extracted

        ## This is where we could set shape attributes from existing annotation...

        for id in self.__systems:
            annotator.add_system(self.__fc_features[id].name, self.source_id)

        for id in self.__organs:
            annotator.add_organ(self.__fc_features[id].name, self.source_id,
                tuple(self.__fc_features[system_id].name for system_id in self.__fc_features[id].parents if system_id > 0)
                )

        for feature in self.__fc_features.values():
            self.__annotate_feature(feature, annotator)


    def __annotate_feature(self, feature: FCFeature,  annotator: Annotator):
    #=======================================================================
        if (feature.name != ''
        and (annotation := annotator.find_annotation(feature.name)) is None):
            organ_id = None
            for parent in feature.parents:
                if parent in self.__organs:
                    # Can have multiple parents
                    organ_id = parent
                    break
            if organ_id is not None:
                if len(feature.parents) > 1:
                    log.warning(f'FTU {feature} in multiple organs')
                else:
                    organ_name = self.__fc_features[organ_id].name
                    annotation = annotator.find_ftu_by_names(organ_name, feature.name)
                    if annotation is None:
                        annotation = annotator.add_ftu(self.__fc_features[organ_id].name, feature.name, self.source_id)
    def __extract_shapes(self, shapes: TreeList) -> TreeList:
    #========================================================

        self.__extract_components(shapes)
        self.__label_connectors(shapes)

        for shape in shapes.flatten(skip=1):
            # Add the shape to the filter if we are processing a base map,
            # or exclude it from the layer because it is similar to those
            # in the base map
            self.source.filter_map_shape(shape)
            if shape.id in self.__systems:
                shape.properties.pop('name', None)  # We don't want System tooltips...
            kind = shape.properties.get('shape-kind')
            if kind not in self.__seen_shape_kinds:
                self.__seen_shape_kinds.add(kind)
                if shape.geometry.area < self.__smallest_shape_area:
                    self.__smallest_shape_area = shape.geometry.area

            if shape.type == SHAPE_TYPE.CONNECTOR:
                shape.properties['shape-type'] = 'connector'
                shape.properties['shape-id'] = shape.id
                shape.properties['tile-layer'] = 'pathways'
                kind = shape.properties.pop('kind', 'unknown')
                ganglion = shape.properties.pop('ganglion')
                ## get dash style from pptx. cf. pptx2svg
                if kind in ['para', 'symp']:
                    path_type = f'{kind}-{ganglion}'
                else:
                    path_type = kind
                shape.properties['kind'] = path_type
                shape.properties['type'] = 'line-dash' if path_type.endswith('-post') else 'line'

        return shapes



    def __extract_components(self, shapes: TreeList):
    #================================================
        # First extract features
        geometries = [self.geometry]
        shape_ids = {id(self.geometry): 0}     # id(geometry) --> shape.id
        for shape in shapes.flatten(skip=1):
            shape_id = shape.id
            geometry = shape.geometry
            if shape.type == SHAPE_TYPE.FEATURE and geometry.geom_type == 'Polygon':
                # We are only interested in features actually on the slide
                if self.__outer_geometry_prepared.contains(geometry):
                    geometries.append(geometry)
                    shape_ids[id(geometry)] = shape_id
                    ## feature properties != shape.properties for FCFeatures
                    self.__fc_features[shape_id] = FCFeature(shape_id, geometry, shape.properties.copy())
                    if settings.get('authoring', False):    # For resulting map feature
                        shape.properties['label'] = self.__fc_features[shape_id].label

        # Use a spatial index to find shape containment hierarchy
        idx = shapely.strtree.STRtree(geometries)

        # We use two passes to find the feature's spatial ordering
        non_system_features = {}
        for shape_id, feature in self.__fc_features.items():
            if shape_id > 0:     # self.__fc_features[0] == entire slide
                # List of geometries that intersect the feature
                intersecting_geometries: list[int] = idx.query(feature.geometry)

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
                    if (parent_geometry is not None
                    and feature.geometry is not None
                    and parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area):
        ## smaller and >= 80% common area ==> containment
                        break
                    parent_index += 1

                if (overlaps[parent_index] == 0
                and feature.name != ''
                and feature.name[-1].isupper()):
                    self.__systems.add(shape_id)
                    feature.kind = FC.SYSTEM
                    if feature.name.startswith('BRAIN'):
                        feature.fc_class = FC_Class.BRAIN
                    self.__set_relationships(shape_id, 0)
                else:
                    non_system_features[shape_id] = overlaps

        # Now find parents of the non-system features
        for shape_id, overlaps in non_system_features.items():
            feature = self.__fc_features[shape_id]
            parent_index = overlaps.index(shape_id) + 1
            while parent_index < len(overlaps):
                parent_geometry = self.__fc_features[overlaps[parent_index]].geometry
                assert (parent_geometry is not None
                   and feature.geometry is not None
                   and parent_geometry.area >= feature.geometry.area)
                if parent_geometry.intersection(feature.geometry).area >= 0.8*feature.geometry.area:
                #if parent_geometry.contains(feature.geometry):
    ## smaller and >= 80% common area ==> containment
                    break
                parent_index += 1
            parent_id = overlaps[parent_index]
            if parent_id in self.__systems:
                if feature.name != '':
                    self.__organs.add(shape_id)
                    feature.kind = FC.ORGAN
                self.__set_relationships(shape_id, parent_id)
                for system_id in self.__systems:
                    geometry = self.__fc_features[system_id].geometry
                    if (system_id != parent_id
                    and geometry is not None
                    and geometry.contains(feature.geometry)):
                        self.__set_relationships(shape_id, system_id)
            else:
                if parent_id == 0 and feature.name != '':
                    self.__organs.add(shape_id)
                    feature.kind = FC.ORGAN
                self.__set_relationships(shape_id, parent_id)

        # Now extract connections between features
        for shape in shapes.flatten(skip=1):
            if shape.type == SHAPE_TYPE.CONNECTOR:
                shape.properties['messages'] = []
                shape_id = shape.id
                start_id = shape.properties.get('connection-start')
                end_id = shape.properties.get('connection-end')
                # Drop connections to features that aren't on the slide
                if start_id in self.__fc_features:
                    self.__fc_features[start_id].kind |= FC.CONNECTED
                    self.__connection_graph.add_node(start_id)    #### Include slide id with ppt id so connection_graph is over entire map...
                else:
                    shape.properties['messages'].append(f'Connector {shape_id} is not connected to a start node: {shape.kind}/{shape.name}')
                    shape.properties['connection-start'] = None
                    shape.properties['kind'] = 'error'
                    start_id = None
                if end_id in self.__fc_features:
                    self.__fc_features[end_id].kind |= FC.CONNECTED
                    self.__connection_graph.add_node(end_id)
                else:
                    shape.properties['messages'].append(f'Connector {shape_id} is not connected to an end node: {shape.kind}/{shape.name}')
                    shape.properties['connection-end'] = None
                    shape.properties['kind'] = 'error'
                    end_id = None
                if start_id is not None and end_id is not None:
                    self.__connection_graph.add_edge(start_id, end_id)
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
                    shape.properties['ganglion'] = 'pre'         # pre-ganglionic
                else:
                    shape.properties['ganglion'] = 'post'        # post-ganglionic

                self.__connectors[shape.id] = Connector(shape.id, start_id, end_id, shape.geometry, arrows, shape.properties)

    def __set_relationships(self, child: int, parent: int):
    #======================================================
        self.__fc_features[child].parents.append(parent)
        self.__fc_features[parent].children.append(child)

    def __ftu_label(self, shape_id: int) -> str:
    #===========================================
        while self.__fc_features[shape_id].name == '':
            if shape_id == 0 or shape_id in self.__organs:
                break
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id].label

    def __system_feature(self, shape_id: int) -> Optional[FCFeature]:
    #================================================================
        while shape_id != 0 and shape_id not in self.__systems:
            shape_id = self.__fc_features[shape_id].parents[0]
        return self.__fc_features[shape_id] if shape_id != 0 else None

    def __connector_node(self, shape_id: Optional[int]) -> Optional[tuple[str, str, FC_Class, list[str]]]:
    #================================================================================================
        if shape_id is not None:
            if (label := self.__ftu_label(shape_id)) != '':
                warnings: list[str] = []

                if (colour := self.__fc_features[shape_id].colour) in self.__unknown_colours:
                    cls = 'unknown'
                elif (cls := CONNECTION_CLASSES.get('colour', 'unknown')) == 'unknown':
                    self.__unknown_colours.add(colour)
                    # NB. Some of these are for junction colours...
                    warnings.append(f'Colour {colour} is not a known connector class (shape {shape_id})')

                system = self.__system_feature(shape_id)

                if system is None:
                    # NB. 'Breasts' are in three systems but none are assigned...
                    warnings.append(f'Cannot determine system for connector {shape_id} in FTU {label}')

                return (cls, label, system.fc_class if system is not None else FC_Class.UNKNOWN, warnings)

    def __label_connectors(self, shapes: TreeList):
    #==============================================
        for shape in shapes.flatten(skip=1):
            if shape.type == SHAPE_TYPE.CONNECTOR:
                node_0 = self.__connector_node(shape.properties.get('connection-start', None))
                node_1 = self.__connector_node(shape.properties.get('connection-end', None))
                messages = shape.properties['messages']
                kind = 'unknown'
                label = ''
                if node_0 is not None and node_1 is not None:
                    messages.extend(node_0[3])
                    messages.extend(node_1[3])
                    kind = node_0[0]
                    if node_0[0] != node_1[0]:
                        if 'connector' not in [node_0[0], node_1[0]]:
                            messages.append(f'Ends of connector have different kinds: {[node_0[0], node_1[0]]}')
                        elif node_0[0] == 'connector':
                            kind = node_1[0]
                    if not node_0[2] == FC_Class.BRAIN and not node_1[2] == FC_Class.BRAIN:
                        messages.append(f'Connection is not to/or from the brain')
                        label = f'({node_0[1]}, {node_1[1]})'
                    elif node_0[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'({node_1[1]}, {node_0[1]})'
                        else:
                            label = f'({node_0[1]}, {node_1[1]})'
                    elif kind == 'sensory':
                        label = f'({node_0[1]}, {node_1[1]})'
                    else:
                        label = f'({node_1[1]}, {node_0[1]})'
                elif node_0 is not None:
                    messages.extend(node_0[3])
                    kind = node_0[0]
                    if node_0[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'(..., {node_0[1]})'
                        else:
                            label = f'({node_0[1]}, ...)'
                elif node_1 is not None:
                    messages.extend(node_1[3])
                    kind = node_1[0]
                    if node_1[2] == FC_Class.BRAIN:
                        if kind == 'sensory':
                            label = f'({node_1[1]}, ...)'
                        else:
                            label = f'(..., {node_1[1]})'
                # If there are warning messages then set ``kind`` to highlight
                # the connector and report the messages
                if kind == 'unknown':
                    messages.append('Unknown connection kind')
                elif len(messages):
                    kind = 'error'
                if settings.get('authoring', False):
                    for warning in messages:
                        log.warning(warning)
                    messages.insert(0, f'{shape.id}: {label}')
                    shape.properties['label'] = '<br/>'.join(messages)
                else:
                    for warning in messages:
                        log.warning(f'{warning}: {node_0[:3] if node_0 is not None else node_0}/{node_1[:3] if node_1 is not None else node_1}')
                    shape.properties['label'] = label
                if 'kind' not in shape.properties:
                    shape.properties['kind'] = kind

#===============================================================================
