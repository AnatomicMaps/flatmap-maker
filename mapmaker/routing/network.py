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

import beziers.path
import shapely.geometry

#===============================================================================

from mapmaker.geometry import bezier_sample
from mapmaker.settings import settings
from mapmaker.utils import log

#===============================================================================

class RouteSegment(object):
    def __init__(self, nodes_list, edge_list, path_type):
        self.__nodes_list = nodes_list
        self.__edge_list = edge_list
        self.__path_type = path_type

    def geometry(self):
        path_layout = settings.get('pathLayout', 'automatic')
        if path_layout == 'linear':
            return shapely.geometry.MultiLineString(
                [ shapely.geometry.LineString([ node.centroid for node in nodes ])
                    for nodes in self.__nodes_geometry ])
        elif path_layout == 'automatic':
            # Automatic routing magic goes in here...
            pass
        # Fallback is centreline layout
        path = beziers.path.BezierPath.fromSegments(self.__edge_geometry)
        return shapely.geometry.LineString(bezier_sample(path))

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
        route_segments = {}
        for pathway in path_connections['pathways']:
            '''
            {
                "id": "neuron_1",
                "start": "brain_40",        # index into self.__nodes
                "end": "ganglion_1",        # index into self.__nodes
                "paths": [ "n_1", "n_5" ],  # index into self.__networks and self.__edges
                "type": "para-pre"
            }
            '''
            nodes_list = [network.get(edge) for edge in pathway['paths']]
            if pathway['start'] != nodes_list[0][0]:
                log.error("Start node doesn't match path start for '{}'".format(pathway['id']))
            if pathway['end'] != nodes_list[-1][-1]:
                log.error("End node doesn't match path end for '{}'".format(pathway['id']))
            route_segments[pathway['id']] = RouteSegment([[self.__nodes.get(node) for node in nodes]
                                                            for nodes in nodes_list],
                                                         [self.__edges.get(edge)
                                                            for edge in pathway['paths']],
                                                         pathway['type'])

        return { connection['id']: [ route_segments.get(pathway)
                                        for pathway in connection['pathways']]
            for connection in path_connections['connections']}
        '''
        {
            "id": "connection_1",
            "pathways": [ "neuron_1", "neuron_6"]  # index into pathways
        }
        '''

#===============================================================================
