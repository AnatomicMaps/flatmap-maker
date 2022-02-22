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
from .layout import TransitMap

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

    @classmethod
    def circle(cls, centre: Tuple[float], radius: float = 2000, properties: dict = None):
        return cls(shapely.geometry.Point(centre).buffer(radius), properties)

    @classmethod
    def line(cls, start: Tuple[float], end: Tuple[float], properties: dict = None):
        return cls(shapely.geometry.LineString([start, end]), properties)

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
            log.warning('Edge {} nodes have no geometry'.format(edge))
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
                geometry.append(GeometricShape.circle(pt,
                    properties={'type': 'bezier', 'kind': 'bezier-end'}))
            for pt in bz_pts[1:3]:
                geometry.append(GeometricShape.circle(pt,
                    properties={'type': 'bezier', 'kind': 'bezier-control', 'label': path_id}))
            geometry.append(GeometricShape.line(*bz_pts[0:2], properties={'type': 'bezier'}))
            geometry.append(GeometricShape.line(*bz_pts[2:4], properties={'type': 'bezier'}))
        return geometry

    def geometry(self) -> [GeometricShape]:
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """
        def join_geometry(node, edge_0, edge_1):
            e0 = edge_0['path-ends'][node]
            e1 = edge_1['path-ends'][node]
            d = e0.distanceFrom(e1)/3
            if (e0-e1).angle < (e1-e0).angle:
                d = -d
            s0 = edge_0['tangents'][node]
            s1 = edge_1['tangents'][node]
            bz = CubicBezier(e0, e0 + s0*d, e1 - s1*d, e1)
            geometry = []
            if edge_0.get('path-id') == edge_1.get('path-id'):
                geometry.append(
                    GeometricShape(bezier_to_linestring(bz), {
                        'nerve': edge_0.get('nerve'),
                        'path-id': edge_0.get('path-id')
                        }))
            else:
                mid_point = bz.pointAtTime(0.5)
                geometry.append(GeometricShape.circle(
                    (mid_point.x, mid_point.y),
                    radius = 0.8*PATH_SEPARATION,
                    properties={'type': 'junction', 'path-id': edges[0].get('path-id')}))
                for n, bz in enumerate(bz.splitAtTime(0.5)):
                    geometry.append(
                        GeometricShape(bezier_to_linestring(bz), {
                            'nerve': edges[n].get('nerve'),
                            'path-id': edges[n].get('path-id')
                        }))
            return geometry

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
            if node_dict.get('degree', 0) >= 2:
                edges = []
                for node_0, node_1, edge_dict in self.__graph.edges(node, data=True):
                    if edge_dict.get('type') != 'terminal':
                        edges.append(edge_dict)
                if len(edges) == 2:
                    geometry.extend(join_geometry(node, edges[0], edges[1]))
                elif len(edges) == 3:  ## Generalise
                    # Check angles between edges to find two most obtuse...
                    centre = node_dict['centre']
                    min_angle = math.pi
                    min_pair = None
                    pairs = []
                    for e0, e1 in itertools.combinations(enumerate(edges), 2):
                        pairs.append((e0[0], e1[0]))
                        a = abs((e0[1]['path-ends'][node] - centre).angle
                              - (e1[1]['path-ends'][node] - centre).angle)
                        if a > math.pi:
                            a = abs(a - 2*math.pi)
                        if a < min_angle:
                            min_angle = a
                            min_pair = pairs[-1]
                    for pair in pairs:
                        if pair != min_pair:
                            geometry.extend(join_geometry(node, edges[pair[0]], edges[pair[1]]))

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
                    edges_by_id[edge_dict['id']] = (node_0, node_1)

        #for edges from nodes with degree > 2
        #order by:
        #math.atan2(delta_y, delta_x)
        ##pprint([(n, [((e0, e1), d.get('id'), d.get('path-id')) for e0, e1, d in g.edges(data=True) if d.get('type') != 'terminal'])
        ##            for n, g in enumerate(routes)])

        layout = TransitMap(edges_by_id, shared_paths)
        layout.solve()
        edge_order = layout.results()

        for route_number, route_graph in enumerate(routes):
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    edge = (node_0, node_1)
                    edge_id = edge_dict.get('id')
                    ordering = edge_order.get(edge_id, [])
                    if route_number in ordering:
                        edge_dict['offset'] = ordering.index(route_number) - len(ordering)//2 + ((len(ordering)+1)%2)/2

        return { route_number: RoutedPath(route_graph, route_number)
            for route_number, route_graph in enumerate(routes) }


#===============================================================================
