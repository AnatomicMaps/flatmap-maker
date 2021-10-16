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
from mapmaker.routing.routes import Sheath
from mapmaker.routing.neurons import Connectivity

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
    def __init__(self, path_id, route_graph, centreline_scaffold=None):
        self.__path_id = path_id
        self.__graph = route_graph
        self.__centreline_scaffold = centreline_scaffold
        self.__path_layout = settings.get('pathLayout', 'automatic')
        self.__node_set = {node for node, data in route_graph.nodes(data=True)
                                if not data.get('exclude', False)}
        self.__source_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'source'}
        self.__target_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'target'}
        if self.__path_layout == 'automatic':
            ## The sheath scaffold is a network property and should be set
            ## from the `centreline_scaffold` parameter
            self.__sheath = Sheath(route_graph, path_id)
            self.__sheath.build(self.__source_nodes, self.__target_nodes)
        else:
            self.__sheath = None

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
        display_bezier_points = True #False     ### To come from settings...
        if self.__path_layout == 'automatic':
            log("Automated pathway layout. Path ID: ", self.__path_id)
            evaluate_settings = self.__sheath.settings()
            # TODO: use evenly-distributed offsets for the final product.
            number_of_neurons = len(evaluate_settings['derivatives'])
            # locations = [0.01 + x*(0.99-0.01)/number_of_neurons for x in range(number_of_neurons)]
            location = 0.5
            geometry = []
            for scaffold, path_id, derivative in zip(evaluate_settings['scaffolds'],
                                                     evaluate_settings['path_ids'],
                                                     evaluate_settings['derivatives']):
                scaffold.generate()
                connectivity = Connectivity(path_id, scaffold, derivative, location)
                auto_beziers = connectivity.get_neuron_line_beziers()
                path = BezierPath.fromSegments(auto_beziers)
                geometry.append(GeometricShape(shapely.geometry.LineString(bezier_sample(path))))
            end_nodes = set(self.__source_nodes)
            end_nodes.update(self.__target_nodes)
            for node in end_nodes:
                for edge in self.__graph.edges(node, data=True):
                    if edge[2].get('type') == 'terminal':
                        line = self.__line_from_edge(edge)
                        if line is not None:
                            geometry.append(GeometricShape(line))
            if display_bezier_points:
                for beziers in self.__sheath.path_beziers.values():
                    for bezier in beziers:
                        bz_pts = tuple([p.x, p.y] for p in bezier.points)
                        for pt in [bz_pts[0], bz_pts[3]]:
                            geometry.append(GeometricShape(GeometricShape.circle(pt),
                                {'type': 'bezier', 'kind': 'bezier-end'}))
                        for pt in bz_pts[1:3]:
                            geometry.append(GeometricShape(GeometricShape.circle(pt),
                                {'type': 'bezier', 'kind': 'bezier-control'}))
                        geometry.append(GeometricShape(GeometricShape.line(*bz_pts[0:2]), {'type': 'bezier'}))
                        geometry.append(GeometricShape(GeometricShape.line(*bz_pts[2:4]), {'type': 'bezier'}))

            return geometry

        # Fallback is centreline layout
        geometry = []
        for edge in self.__graph.edges(data='geometry'):
            if self.__path_layout != 'linear' and edge[2] is not None:
                geometry.append(GeometricShape(shapely.geometry.LineString(bezier_sample(edge[2]))))
            else:
                line = self.__line_from_edge(edge)
                if line is not None:
                    geometry.append(GeometricShape(line))
        return geometry

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }

#===============================================================================
