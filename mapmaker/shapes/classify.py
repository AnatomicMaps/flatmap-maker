#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2024  David Brooks
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
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Optional

#===============================================================================

import networkx as nx
from numpy import ndarray
from shapely.geometry.base import BaseGeometry
import shapely.prepared
import shapely.strtree

#===============================================================================

from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.settings import settings
from mapmaker.shapes import Shape, SHAPE_TYPE
from mapmaker.utils import log

from .constants import COMPONENT_BORDER_WIDTH, CONNECTION_STROKE_WIDTH, MAX_LINE_WIDTH
from .constants import SHAPE_ERROR_COLOUR, SHAPE_ERROR_BORDER

from .line_finder import Line, LineFinder, XYPair
from .text_finder import TextFinder
from .types import VASCULAR_KINDS

#===============================================================================

"""

Mutually exclusive shape categories:

    parent: Shape
    children: list[Shape]
    overlapping: list[Shape]
    adjacent: list[Shape]

Shape types from size (area and aspect ratio) and geometry:

*   Component
*   Container
*   Boundary
*   Connection
*   Text

"""

#===============================================================================

@dataclass
class ConnectionEnd:
    shape: Shape
    index: int

#===============================================================================

class LineString:
    def __init__(self, geometry: BaseGeometry):
        self.__coords = list(geometry.coords)

    @property
    def coords(self):
        return self.__coords

    @property
    def line_string(self):
        return shapely.LineString(self.__coords)

    def end_line(self, end: int) -> Line:
        if end == 0:
            return Line.from_coords((self.__coords[0], self.__coords[1]))
        else:
            return Line.from_coords((self.__coords[-2], self.__coords[-1]))

#===============================================================================

class ShapeClassifier:
    def __init__(self, shapes: list[Shape], map_area: float, metres_per_pixel: float):
        self.__shapes = list(shapes)
        self.__shapes_by_type: DefaultDict[SHAPE_TYPE, list[Shape]] = defaultdict(list[Shape])
        self.__geometry_to_shape: dict[int, Shape] = {}
        self.__line_finder = LineFinder(metres_per_pixel)
        self.__text_finder = TextFinder(metres_per_pixel)
        self.__connection_ends: list[shapely.Polygon] = []
        self.__connection_ends_to_shape: dict[int, ConnectionEnd] = {}
        self.__max_line_width = metres_per_pixel*MAX_LINE_WIDTH
        connection_joiners: list[Shape] = []
        component_geometries = []
        for n, shape in enumerate(shapes):
            if shape.get_property('background', False):
                shape.set_property('exclude', True)
                continue
            geometry = shape.geometry
            area = geometry.area
            self.__bounds = geometry.bounds
            width = abs(self.__bounds[2] - self.__bounds[0])
            height = abs(self.__bounds[3] - self.__bounds[1])
            bbox_coverage = (width*height)/map_area
            if width > 0 and height > 0:
                aspect = min(width, height)/max(width, height)
                coverage = area/(width*height)
            else:
                aspect = 0
                coverage = 1
            shape.properties.update({
                'area': area,
                'aspect': aspect,
                'coverage': coverage,
                'bbox-coverage': bbox_coverage,
            })
            if shape.shape_type == SHAPE_TYPE.UNKNOWN:
                if bbox_coverage > 0.001 and geometry.geom_type == 'MultiPolygon':
                    shape.properties['shape-type'] = SHAPE_TYPE.BOUNDARY
                elif ((n < len(shapes) - 1) and shapes[n+1].shape_type == SHAPE_TYPE.TEXT
                  and coverage < 0.5 and bbox_coverage < 0.001):
                    shape.properties['exclude'] = True
                elif 'LineString' in geometry.geom_type or coverage < 0.4 and 'Multi' not in geometry.geom_type:
                    if not self.__add_connection(shape):
                        log.warning('Cannot extract line from polygon', shape=shape.id)
                elif bbox_coverage > 0.001 and coverage > 0.9:
                    shape.properties['shape-type'] = SHAPE_TYPE.CONTAINER if bbox_coverage > 0.2 else SHAPE_TYPE.COMPONENT
                elif bbox_coverage < 0.0003 and 0.7 < coverage <= 0.8:
                    shape.properties['shape-type'] = SHAPE_TYPE.ANNOTATION
                elif bbox_coverage < 0.001 and coverage > 0.75:
                    shape.properties['shape-type'] = SHAPE_TYPE.COMPONENT
                elif 'Multi' not in geometry.boundary.geom_type and len(shape.geometry.boundary.coords) == 4:      # A triangle
                    connection_joiners.append(shape)
                elif not self.__add_connection(shape):
                    log.warning('Unclassifiable shape', shape=shape.id)
                    if settings.get('authoring', False):
                        shape.properties['exclude'] = True
                    else:
                        shape.properties['colour'] = SHAPE_ERROR_COLOUR
            if not shape.properties.get('exclude', False):
                self.__shapes_by_type[shape.shape_type].append(shape)
                if shape.shape_type in [SHAPE_TYPE.ANNOTATION,
                                        SHAPE_TYPE.COMPONENT,
                                        SHAPE_TYPE.TEXT]:
                    self.__geometry_to_shape[id(shape.geometry)] = shape
                    component_geometries.append(shape.geometry)
                    shape.properties['stroke-width'] = COMPONENT_BORDER_WIDTH

        # An index for component geometries
        self.__component_index = shapely.strtree.STRtree(component_geometries)
        self.__component_geometries: list[BaseGeometry] = self.__component_index.geometries     # type: ignore

        # If possible, join connections that share a triangular joiner
        self.__join_connections(connection_joiners)

        # Set parent/child relationship for components
        self.__set_parent_relationships()

        # Assign text labels to components and source and target of connections
        for shape in self.__shapes:
            if shape.shape_type in [SHAPE_TYPE.ANNOTATION, SHAPE_TYPE.COMPONENT]:
                if (name_and_shapes := self.__text_finder.get_text(shape)) is not None:
                    shape.properties['name'] = name_and_shapes[0]
                    shape.properties['text-shapes'] = name_and_shapes[1]
                # Although we do want their text, we don't want annotations to be active features
                if shape.shape_type == SHAPE_TYPE.ANNOTATION:
                    shape.properties['exclude'] = True
            elif shape.shape_type == SHAPE_TYPE.CONNECTION:
                line_ends: shapely.geometry.base.GeometrySequence[shapely.MultiPoint] = shape.geometry.boundary.geoms  # type: ignore
                self.__connect_line_end(shape, line_ends[0], 'source')
                self.__connect_line_end(shape, line_ends[1], 'target')

    @property
    def shapes(self) -> list[Shape]:
    #===============================
        return [s for s in self.__shapes if not s.exclude]

    def __add_connection(self, shape: Shape) -> bool:
    #================================================
        if shape.geometry.geom_type == 'MultiPolygon':
            return False
        elif 'Polygon' in shape.geometry.geom_type:
            if (line := self.__line_finder.get_line(shape)) is None:
                if settings.get('authoring', False):
                    shape.properties['exclude'] = True
                else:
                    shape.properties['colour'] = SHAPE_ERROR_COLOUR
                return False
            shape.geometry = line
            colour = shape.properties.get('fill')
        else:
            colour = shape.properties.get('stroke')
        if colour is not None:
            shape.properties['colour'] = colour
        if (kind := VASCULAR_KINDS.lookup(colour)) is not None:
            shape.properties['kind'] = kind
        else:
            print(shape.id, 'COLOUR ?', colour)
        shape.properties['shape-type'] = SHAPE_TYPE.CONNECTION
        shape.properties['tile-layer'] = PATHWAYS_TILE_LAYER
        shape.properties['stroke-width'] = CONNECTION_STROKE_WIDTH
        shape.properties['type'] = 'line-dash' if shape.get_property('dashed', False) else 'line'
        assert shape.geometry.geom_type == 'LineString', f'Connection not a LineString: {shape.id}'
        line_ends: shapely.geometry.base.GeometrySequence[shapely.MultiPoint] = shape.geometry.boundary.geoms  # type: ignore
        self.__append_connection_ends(line_ends[0], shape, 0)
        self.__append_connection_ends(line_ends[1], shape, -1)
        return True

    def __append_connection_ends(self, end: shapely.Point, shape: Shape, index: int):
    #================================================================================
        end_circle = end.buffer(self.__max_line_width)
        self.__connection_ends.append(end_circle)
        self.__connection_ends_to_shape[id(end_circle)] = ConnectionEnd(shape, index)

    def __connect_line_end(self, shape: Shape, end: shapely.Point, property: str):
    #=============================================================================
        for child in [self.__geometry_to_shape[id(self.__component_geometries[c])]
                        for c in self.__component_index.query(end.buffer(self.__max_line_width), predicate='intersects')
                            if self.__component_geometries[c].area > 0]:
            if not child.exclude:
                shape.set_property(property, child.id)
                return

    def __extend_joined_connections(self, ends: ndarray) -> tuple[Shape, Shape]:
    #===========================================================================
        # Extend connection line ends so that they touch...
        c0 = self.__connection_ends_to_shape[id(self.__connection_ends[ends[0]])]
        c1 = self.__connection_ends_to_shape[id(self.__connection_ends[ends[1]])]
        l0 = LineString(c0.shape.geometry)
        l0_end = l0.end_line(c0.index)
        l1 = LineString(c1.shape.geometry)
        l1_end = l1.end_line(c1.index)
        pt = l0_end.intersection(l1_end, extend=True)
        if pt is not None:
            l0.coords[c0.index] = pt.coords
            c0.shape.geometry = l0.line_string
            l1.coords[c1.index] = pt.coords
            c1.shape.geometry = l1.line_string
        return (c0.shape, c1.shape)

    def __join_connections(self, connection_joiners):
    #================================================
        connection_index = shapely.strtree.STRtree(self.__connection_ends)
        joined_connection_graph = nx.Graph()
        for joiner in connection_joiners:
            ends = connection_index.query_nearest(joiner.geometry)
            if len(ends) == 1:
                continue
            elif len(ends) == 2:
                joiner.properties['exclude'] = True
                (connection_0, connection_1) = self.__extend_joined_connections(ends)
                joined_connection_graph.add_edge(connection_0, connection_1)
            else:
                joiner.properties['colour'] = SHAPE_ERROR_COLOUR
                joiner.properties['stroke'] = SHAPE_ERROR_BORDER
                joiner.properties['stroke-width'] = COMPONENT_BORDER_WIDTH
                joiner.geometry = joiner.geometry.buffer(self.__max_line_width)
        for joined_connection in nx.connected_components(joined_connection_graph):
            connections = list(joined_connection)
            connected_line = shapely.line_merge(shapely.unary_union([conn.geometry for conn in connections]))
            assert connected_line.geom_type == 'LineString', f'Cannot join connections: {[conn.id for conn in connections]}'

            # Need to check all segments have the same colour...

            connections[0].geometry = connected_line
            for connection in connections[1:]:
                if connection.properties.get('directional', False):
                    connections[0].properties['directional'] = True
                connection.properties['exclude'] = True

    def __set_parent_relationships(self):
    #====================================
        parent_child = []
        for geometry in self.__component_geometries:
            if geometry.area > 0:
                parent = self.__geometry_to_shape[id(geometry)]
                bbox_intersecting_shapes = [self.__geometry_to_shape[id(self.__component_geometries[c])]
                    for c in self.__component_index.query(geometry)
                        if self.__component_geometries[c].area > 0]
                for shape in bbox_intersecting_shapes:
                    if parent.shape_type != SHAPE_TYPE.TEXT and parent.id != shape.id:
                        # A text shape is always a child even when not properly contained
                        if (shapely.contains_properly(parent.geometry, shape.geometry)
                          or (shape.shape_type == SHAPE_TYPE.TEXT
                          and parent.geometry.intersection(shape.geometry).area/shape.geometry.area > MIN_TEXT_INSIDE)):
                            parent_child.append((parent, shape))
        last_child_id = None
        for (parent, child) in sorted(parent_child, key=lambda s: (s[1].id, s[0].geometry.area)):
            # Sorted by child id with smallest parent first when there are multiple parents
            if child.id != last_child_id:
                child.add_parent(parent)
                last_child_id = child.id

#===============================================================================
