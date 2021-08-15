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

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.utils import log

from .network import NetworkRouter

#===============================================================================

class Network(object):
    def __init__(self, flatmap, network):
        self.__flatmap = flatmap
        self.__id = network.get('id')
        self.__graph = nx.Graph()
        for centreline in network.get('centreline', []):
            edge_id = centreline.get('id')
            if edge_id is None:
                log.warn('Network {} has edge without an ID'.format(self.__id))
            else:
                nodes = centreline.get('connects', [])
                if len(nodes) < 2:
                    log.warn('Edge {} in network {} has too few nodes'.format(edge_id, self.__id))
                else:
                    self.__graph.add_edge(nodes[0], nodes[-1], id=edge_id, way_points=nodes[1:-1])
        self.__edges_by_id = { id: edge
                                for edge, id in nx.get_edge_attributes(self.__graph, 'id').items() }

    @staticmethod
    def __find_feature(id, id_map):
    #==============================
        if id not in id_map:
            log.warn('Unknown network feature: {}'.format(id))
        return id_map.get(id)

    def __set_node_properties(self, feature):
    #========================================
        if feature is not None and 'geometry' not in self.__graph.nodes[node]:
            node = self.__graph.nodes[feature.id]
            for key, value in feature.properties.items():
                node[key] = value
            node['geometry'] = node.geometry

    def create_geometry(self, id_map):
    #=================================
        for edge in self.__graph.edges.data('id'):
            for node in edge[0:2]:
                self.__set_node_properties(self.__find_feature(node, id_map))
            feature = self.__find_feature(edge[2], id_map)
            if feature is not None:
                beziers = feature.get_property('bezier-paths', [])
                assert(len(beziers) == 1)   ## TEMP, need to check earlier (svg.__get_geometry()) and give error?
                bezier_path = beziers[0]
                bezier_start = bezier_path.pointAtTime(0)
                start_point = shapely.geometry.Point(bezier_start.x, bezier_start.y)
                end_node_0 = self.__graph.nodes[edge[0]].get('geometry')
                end_node_1 = self.__graph.nodes[edge[1]].get('geometry')
                if end_node_0 is not None and end_node_1 is not None:
                    if start_point.distance(end_node_0) > start_point.distance(end_node_1):
                        bezier_path = bezier_path.reverse()
                    self.__graph.edges[edge[0:2]]['geometry'] = bezier_path

    def router(self):
    #=================
        return NetworkRouter(self.__graph)

    def has_node(self, id):
    #=======================
        return id in self.__graph

#===============================================================================
