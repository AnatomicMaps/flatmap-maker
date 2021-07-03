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

import shapely.geometry

#===============================================================================

from .network import NetworkRouter

#===============================================================================

class Network(object):
    def __init__(self, flatmap, network_list):
        self.__flatmap = flatmap
        self.__networks = {}
        self.__path_connections = {}
        self.__path_networks = {}
        self.__way_points = set()
        for network in network_list:
            paths = {}
            for path in network['paths']:
                paths[path['id']] = path['connects']
                self.__path_connections[path['id']] = path['connects']
                self.__path_networks[path['id']] = network['id']
                self.__way_points.update(path['connects'])
            self.__networks[network['id']] = paths
        self.__edges = {}
        self.__nodes = {}

    @staticmethod
    def __find_feature(id, id_map):
    #==============================
        if id not in id_map:
            log.warn('Unknown network feature: {}'.format(id))
        return id_map.get(id)

    def __add_node(self, node):
    #==========================
        if node is not None and node.id not in self.__nodes:
            self.__nodes[node.id] = node.geometry

    def create_geometry(self, id_map):
    #=================================
        for path_id, end_points in self.__path_connections.items():
            edge = self.__find_feature(path_id, id_map)
            if edge is not None:
                for point in end_points:
                    self.__add_node(self.__find_feature(point, id_map))
                beziers = edge.get_property('bezier-paths', [])
                assert(len(beziers) == 1)   ## TEMP, need to check earlier (svg.__get_geometry()) and give error?
                bezier_path = beziers[0]
                bezier_start = bezier_path.pointAtTime(0)
                start_point = shapely.geometry.Point(bezier_start.x, bezier_start.y)
                end_node_0 = self.__nodes.get(end_points[0])
                end_node_1 = self.__nodes.get(end_points[-1])
                if end_node_0 is not None and end_node_1 is not None:
                    if start_point.distance(end_node_0) > start_point.distance(end_node_1):
                        bezier_path = bezier_path.reverse()
                    self.__edges[path_id] = bezier_path

    def router(self):
    #=================
        return NetworkRouter(self.__networks, self.__edges, self.__nodes)

    def way_point(self, id):
    #=======================
        return id in self.__way_points

#===============================================================================
