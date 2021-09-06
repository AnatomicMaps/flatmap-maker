# ===============================================================================
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
# ===============================================================================

"""
File doc...
"""

# ===============================================================================

import beziers.path
import shapely.geometry

# ===============================================================================

from mapmaker.geometry import bezier_sample
from mapmaker.settings import settings
from mapmaker.utils import log
from mapmaker.routing.routes import Sheath
from mapmaker.routing.neurons import Connectivity

# ===============================================================================

class RoutedPath(object):
    def __init__(self, path_id, route_graph):
        self.__path_id = path_id
        self.__graph = route_graph

        self.__source_nodes = {node
                               for node, data in route_graph.nodes(data=True)
                               if 'type' in data and data['type'] == 'source'}
        self.__target_nodes = {node
                               for node, data in route_graph.nodes(data=True)
                               if 'type' in data and data['type'] == 'target'}
        self.__node_set = {node
                           for node, data in route_graph.nodes(data=True)
                           if not data.get('exclude', False)}

        self.__sheaths = Sheath(route_graph, path_id)
        self.__sheaths.build(self.__source_nodes, self.__target_nodes)

    @property
    def node_set(self):
        return self.__node_set

    @property
    def source_set(self):
        return self.__source_nodes

    @property
    def target_set(self):
        return self.__target_nodes

    def __line_from_edge(self, edge):
        node_0 = self.__graph.nodes[edge[0]]
        node_1 = self.__graph.nodes[edge[1]]
        if 'geometry' not in node_0 or 'geometry' not in node_1:
            log.warn('Edge {} nodes have no geometry'.format(edge))
        else:
            return shapely.geometry.LineString([
                node_0['geometry'].centroid, node_1['geometry'].centroid])

    def geometry(self) -> shapely.geometry:
        """
        Returns:
            A ``LineString`` or ``MultiLineString`` object connecting the paths's nodes.
        """
        path_layout = settings.get('pathLayout', 'automatic')
        if path_layout == 'automatic':
            log("Automated pathway layout. Path ID: ", self.__path_id)
            lines = []
            evaluate_settings = self.__sheaths.get_sheath(self.__source_nodes, self.__target_nodes)
            for sheath, index, derivative in zip(evaluate_settings['sheath_paths'],
                                                 evaluate_settings['sheath_ids'],
                                                 evaluate_settings['derivatives']):
                sheath.generate()
                connectivity = Connectivity(index, sheath, derivative)
                auto_beziers = connectivity.get_neuron_line_beziers()
                path = beziers.path.BezierPath.fromSegments(auto_beziers)
                lines.append(shapely.geometry.LineString(bezier_sample(path)))
            return shapely.geometry.MultiLineString(lines)
        # Fallback is centreline layout
        lines = []
        for edge in self.__graph.edges(data='geometry'):
            if path_layout != 'linear' and edge[2] is not None:
                lines.append(shapely.geometry.LineString(bezier_sample(edge[2])))
            else:
                line = self.__line_from_edge(edge)
                if line is not None:
                    lines.append(line)
        return shapely.geometry.MultiLineString(lines)

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }
