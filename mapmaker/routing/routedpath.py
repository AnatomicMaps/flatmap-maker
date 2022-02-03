#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
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

"""
File doc...
"""

#===============================================================================

from collections import defaultdict
import itertools
import math
from typing import Tuple

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint
import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.geometry import bezier_to_linestring
from mapmaker.settings import settings
from mapmaker.utils import log

from .options import PATH_SEPARATION, SMOOTHING_TOLERANCE

#===============================================================================

class GeometricShape(object):
    def __init__(self, geometry: shapely.geometry, properties: dict = None):
        self.__geometry = geometry
        self.__properties = properties if properties is not None else {}

    @property
    def geometry(self) -> shapely.geometry:
        return self.__geometry

    @property
    def properties(self) -> dict:
        return self.__properties

    @staticmethod
    def circle(centre: Tuple[float], radius: float = 2000) -> shapely.geometry.Polygon:
        return shapely.geometry.Point(centre).buffer(radius)

    @staticmethod
    def line(start: Tuple[float], end: Tuple[float]) -> shapely.geometry.LineString:
        return shapely.geometry.LineString([start, end])

#===============================================================================

class RoutedPath(object):
    def __init__(self, route_graph: nx.Graph, number: int):
        self.__graph = route_graph
        self.__number = number
        self.__path_layout = settings.get('pathLayout', 'automatic')
        self.__node_set = {node for node, data in route_graph.nodes(data=True)
                                if not data.get('exclude', False)}
        self.__source_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'source'}
        self.__target_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'target'}

    @property
    def node_set(self):
        return self.__node_set

    def __line_from_edge(self, edge):
        node_0 = self.__graph.nodes[edge[0]]
        node_1 = self.__graph.nodes[edge[1]]
        if 'geometry' not in node_0 or 'geometry' not in node_1:
            log.warn('Edge {} nodes have no geometry'.format(edge))
        else:
            return shapely.geometry.LineString([
                node_0['geometry'].centroid, node_1['geometry'].centroid])

    def __bezier_geometry(self, path_id, bezier_path):
        geometry = []
        for _, node_geometry in self.__graph.nodes(data='geometry'):
            pass ## geometry.append(GeometricShape(node_geometry, {'type': 'junction'}))
        for bezier in bezier_path.asSegments():
            bz_pts = tuple((p.x, p.y) for p in bezier.points)
            for pt in (bz_pts[0], bz_pts[3]):
                geometry.append(GeometricShape(GeometricShape.circle(pt),
                    {'type': 'bezier', 'kind': 'bezier-end'}))
            for pt in bz_pts[1:3]:
                geometry.append(GeometricShape(GeometricShape.circle(pt),
                    {'type': 'bezier', 'kind': 'bezier-control', 'label': path_id}))
            geometry.append(GeometricShape(GeometricShape.line(*bz_pts[0:2]), {'type': 'bezier'}))
            geometry.append(GeometricShape(GeometricShape.line(*bz_pts[2:4]), {'type': 'bezier'}))
        return geometry

    def geometry(self) -> [GeometricShape]:
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """
        def join_paths(e0, s0, e1, s1):
            d = e0.distanceFrom(e1)/3
            if (e0-e1).angle < (e1-e0).angle:
                d = -d
            bz = CubicBezier(e0, e0 + s0*d, e1 - s1*d, e1)
            return bezier_to_linestring(bz)
        geometry = []
        for node_0, node_1, edge_dict in self.__graph.edges.data():
            edge = (node_0, node_1)
            properties = {
                'nerve': edge_dict.get('nerve'),
                'path-id': edge_dict.get('path-id')
            }
            bezier = edge_dict.get('geometry')
            if self.__path_layout != 'linear' and bezier is not None:
                path_line = (bezier_to_linestring(bezier, offset=PATH_SEPARATION*edge_dict['offset'])
                             .simplify(SMOOTHING_TOLERANCE, preserve_topology=False))
                display_bezier_points = False  ### From settings... <<<<<<<<<<<<<<<<<<<<<<<
                if display_bezier_points:
                    geometry.extend(self.__bezier_geometry(edge_dict.get('path-id'), bezier))
            else:
                path_line = self.__line_from_edge(edge)
            if path_line is not None:
                geometry.append(GeometricShape(path_line, properties))
                if edge_dict.get('type') != 'terminal':
                    edge_dict['path-ends'] = {
                        edge_dict['start-node']: BezierPoint(*path_line.coords[0]),
                        edge_dict['end-node']: BezierPoint(*path_line.coords[-1])
                    }

        for node, node_dict in self.__graph.nodes(data=True):
            if node_dict.get('degree', 0) > 2:
                ends = []
                slopes = []
                for node_0, node_1, edge_dict in self.__graph.edges(node, data=True):
                    if edge_dict.get('type') != 'terminal':
                        ends.append(edge_dict['path-ends'][node])
                        slopes.append(edge_dict['tangents'][node])
                if len(ends) == 2:
                    join_line = join_paths(ends[0], slopes[0], ends[1], slopes[1])
                    geometry.append(GeometricShape(join_line, properties))
                elif len(ends) == 3:  ## Generalise
                    # Check angles between ends to find two most obtuse...
                    centre = node_dict['centre']
                    min_angle = math.pi
                    pairs = []
                    for e0, e1 in itertools.combinations(enumerate(ends), 2):
                        pairs.append((e0[0], e1[0]))
                        a = abs((e0[1]-centre).angle-(e1[1]-centre).angle)
                        if a > math.pi:
                            a = abs(a - 2*math.pi)
                        if a < min_angle:
                            a = min_angle
                            min_pair = pairs[-1]
                    for pair in pairs:
                        if pair != min_pair:
                            join_line = join_paths(ends[pair[0]], slopes[pair[0]], ends[pair[1]], slopes[pair[1]])
                            geometry.append(GeometricShape(join_line, properties))

        return geometry

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }

#===============================================================================

class PathRouter(object):
    def __init__(self, projections: dict):
        self.__projections = projections
        self.__route_graphs = {}

    def add_path(self, path_id: str, route_graph: nx.Graph):
        self.__route_graphs[path_id] = route_graph

    def layout(self):
        for path_id, route_graph in self.__route_graphs.items():
            nx.set_edge_attributes(route_graph, path_id, 'path-id')
        routes = []
        seen_paths = []
        for path_id, route_graph in self.__route_graphs.items():
            if path_id not in seen_paths:
                projects_to = self.__projections.get(path_id)
                if projects_to is not None and projects_to in self.__route_graphs:
                    routes.append(nx.algorithms.compose(route_graph, self.__route_graphs[projects_to]))
                    seen_paths.append(path_id)
                    seen_paths.append(projects_to)
        for path_id, route_graph in self.__route_graphs.items():
            if path_id not in seen_paths:
                if len(route_graph):
                    routes.append(route_graph)

        # Identify shared sub-paths
        edges_by_id = {}
        shared_paths = defaultdict(set)
        for route_number, route_graph in enumerate(routes):
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    shared_paths[edge_dict['id']].add(route_number)
        ## Need to derive path order in each connection from shared_paths...

        ## edge_order = ordering(shared_paths)
        edge_order = { # When traversing "down" with first entry the "left-most"
            'L1_dorsal_root': [4],              # 0
            'L1_spinal_n': [4, 0, 2],           # -g, 0, g
            'L1_ventral_root_ramus': [0, 2],    # -g/2, g/2
            'L2_dorsal_root': [4],
            'L2_spinal_n': [4, 0, 2],
            'L2_ventral_root_ramus': [0, 2],
            'bladder_n': [4, 0, 2, 1, 3],       # -2g, -g, 0, g, 2g
            'hypogastric_n': [4, 0, 2],
            'lumbar_splanchnic_n': [4, 0, 2],
            'pelvic_splanchnic_n': [1, 3]
        }

        for route_number, route_graph in enumerate(routes):
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    edge = (node_0, node_1)
                    edge_id = edge_dict.get('id')
                    ordering = edge_order.get(edge_id, [])
                    if route_number in ordering:
                        edge_dict['offset'] = ordering.index(route_number) - len(ordering)//2 + ((len(ordering)+1)%2)/2
        ################  WIP <<<<<<<<<<<<
        ##ordering.layout(self.__route_graphs)

        return { route_number: RoutedPath(route_graph, route_number)
            for route_number, route_graph in enumerate(routes) }


#===============================================================================
