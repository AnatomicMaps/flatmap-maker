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
    def __init__(self, path_id, node_set, nodes_geometry, edge_geometry, path_type):
        self.__id = path_id
        self.__node_set = node_set
        self.__nodes_geometry = nodes_geometry
        self.__edge_geometry = edge_geometry
        self.__path_type = path_type

    @property
    def id(self):
        return self.__id

    @property
    def node_set(self):
        return self.__node_set

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
            'type': 'line-dash' if self.__path_type.endswith('-post') else 'line',
            # this is were we could set flags to specify the line-end style.
            # --->   <---    |---   ---|    o---   ---o    etc...
            # See https://github.com/alantgeo/dataset-to-tileset/blob/master/index.js
            # and https://github.com/mapbox/mapbox-gl-js/issues/4096#issuecomment-303367657
        }

#===============================================================================

class NetworkRouter(object):
    def __init__(self, networks: dict, edges: dict, nodes: dict):
        self.__networks = networks
        self.__edges = edges
        self.__nodes = nodes

    def layout(self, model: str, connections: dict, pathways: dict) -> dict:
        network = self.__networks.get(model, {})
        route_segments = {}
        for pathway in pathways:
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
            node_set = set(nodes_list[0])
            for nodes in nodes_list[1:]:
                node_set.update(nodes)
            if pathway['start'] != nodes_list[0][0]:
                log.error("Start node doesn't match path start for '{}'".format(pathway['id']))
            if pathway['end'] != nodes_list[-1][-1]:
                log.error("End node doesn't match path end for '{}'".format(pathway['id']))
            route_segments[pathway['id']] = RouteSegment(pathway['id'], node_set,
                                                         [[self.__nodes.get(node) for node in nodes]
                                                            for nodes in nodes_list],
                                                         [self.__edges.get(edge)
                                                            for edge in pathway['paths']],
                                                         pathway['type'])

        return { connection['id']: [ route_segments.get(pathway)
                                        for pathway in connection['pathways']]
            for connection in connections}
        '''
        {
            "id": "connection_1",
            "pathways": [ "neuron_1", "neuron_6"]  # index into pathways
        }
        '''

#===============================================================================
