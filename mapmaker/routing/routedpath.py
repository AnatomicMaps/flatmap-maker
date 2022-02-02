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
from typing import Tuple

#===============================================================================

from beziers.path import BezierPath
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
    def __init__(self, route_graph: nx.Graph):
        self.__graph = route_graph
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

    def geometry(self) -> [GeometricShape]:
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """
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
            else:
                path_line = self.__line_from_edge(edge)
            if path_line is not None:
                geometry.append(GeometricShape(path_line, properties))
                edge_dict['path-ends'] = {
                    node_0: path_line.coords[0],
                    node_1: path_line.coords[-1],
                }

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

        return { route_number: RoutedPath(route_graph)
            for route_number, route_graph in enumerate(routes) }


#===============================================================================
