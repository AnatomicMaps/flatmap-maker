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

from beziers.path import BezierPath
import shapely.geometry

#===============================================================================

from mapmaker.geometry import bezier_sample
from mapmaker.settings import settings
from mapmaker.utils import log

import mapmaker.routing.order as ordering

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
    def circle(centre, radius=2000) -> shapely.geometry.Polygon:
        return shapely.geometry.Point(centre).buffer(radius)

    @staticmethod
    def line(start, end) -> shapely.geometry.LineString:
        return shapely.geometry.LineString([start, end])

#===============================================================================

class RoutedPath(object):
    def __init__(self, path_id, route_graph):
        self.__path_id = path_id
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

        # Fallback is centreline layout
        geometry = []
        for edge0, edge1, edge_data in self.__graph.edges.data():
            nerve = edge_data.get('nerve')
            properties = { 'nerve': nerve } if nerve is not None else None
            bezier = edge_data.get('geometry')
            if self.__path_layout != 'linear' and bezier is not None:
                geometry.append(GeometricShape(shapely.geometry.LineString(bezier_sample(bezier)), properties))
            else:
                edge = (edge0, edge1)
                line = self.__line_from_edge(edge)
                if line is not None:
                    geometry.append(GeometricShape(line, properties))
        return geometry

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }

#===============================================================================

class PathRouter(object):
    def __init__(self):
        self.__route_graphs = {}
        self.__routed_paths = {}

    @property
    def routed_paths(self):
        return self.__routed_paths

    def add_path(self, path_id, route_graph):
        self.__route_graphs[path_id] = route_graph

    def layout(self):
        ################  WIP <<<<<<<<<<<<
        ##ordering.layout(self.__route_graphs)

        ## This needs to derive path order in each connection...
        self.__routed_paths = {path_id: RoutedPath(path_id, route_graph)
            for path_id, route_graph in self.__route_graphs.items()}

#===============================================================================
