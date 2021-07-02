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

class Route(object):
    def __init__(self, start_node, end_node, edge_node_list, path_type):
        self.__start_node = start_node
        self.__end_node = end_node
        self.__edge_node_list = edge_node_list
        self.__path_type = path_type

    def geometry(self):
        """ Override this method..."""
        return [ shapely.geometry.LineString([ node.centroid for node in nodes ])
                    for nodes in self.__edge_node_list ]

    def properties(self):
        return {
            'kind': self.__path_type,
            'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
        }

#===============================================================================

class NetworkRouter(object):
    def __init__(self, networks, edges, nodes):
        self.__networks = networks
        self.__edges = edges
        self.__nodes = nodes

    def layout(self, model, path_connections):
        """ Override this method..."""
        network = self.__networks.get(model, {})
        routes = { pathway['id']: Route(self.__nodes.get(pathway['start']),
                                             self.__nodes.get(pathway['end']),
                                             [ [ self.__nodes.get(node) for node in nodes ]
                                                    for nodes in [ network.get(edge)
                                                        for edge in pathway['paths']]],
                                            pathway['type']
                                            )
            for pathway in path_connections['pathways']}
        '''
        {
            "id": "neuron_1",
            "start": "brain_40",        # index into self.__nodes
            "end": "ganglion_1",        # index into self.__nodes
            "paths": [ "n_1", "n_5" ],  # index into self.__networks and self.__edges
            "type": "cns"
        }
        '''

        return { connection['id']: [ routes.get(pathway)
                                        for pathway in connection['pathways']]
            for connection in path_connections['connections']}
        '''
        {
            "id": "connection_1",
            "pathways": [ "neuron_1", "neuron_6"]  # index into pathways
        }
        '''

#===============================================================================
