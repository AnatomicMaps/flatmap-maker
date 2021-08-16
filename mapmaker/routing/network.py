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

class RouteSegment(object):
    def __init__(self, path_id, node_set, nodes_geometry, edge_geometry, path_type, roads, nerve):
        self.__id = path_id
        self.__node_set = node_set
        self.__nodes_geometry = nodes_geometry
        self.__edge_geometry = edge_geometry
        self.__path_type = path_type
        self.__sheaths = roads
        self.__nerve = nerve

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
                [shapely.geometry.LineString([node.centroid for node in nodes])
                 for nodes in self.__nodes_geometry])
        elif path_layout == 'automatic':
            log("Automated pathway layout...")
            sheath_scaffold, evaluate_settings = self.__sheaths.get_sheath(self.__nerve, self.__node_set)
            sheath_scaffold.generate()
            connectivity = Connectivity(self.__id, sheath_scaffold, evaluate_settings)
            auto_beziers = connectivity.get_neuron_line_beziers()
            path = beziers.path.BezierPath.fromSegments(auto_beziers)
            return shapely.geometry.LineString(bezier_sample(path))
        # Fallback is centreline layout
        path = beziers.path.BezierPath.fromSegments(self.__edge_geometry)
        return shapely.geometry.LineString(bezier_sample(path))

    def properties(self):
        return {
            'kind': self.__path_type,
            'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
        }

# ===============================================================================


class NetworkRouter(object):
    def __init__(self, networks, edges, nodes):
        self.__networks = networks
        self.__edges = edges
        self.__nodes = nodes
        self.__sheath_scaffolds = []

        self.__sheaths = Sheath(networks, edges, nodes)
        self.__sheaths.build()

    def layout(self, model, path_connections):
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
            if len(nodes_list[0]) > 2:
                nodes_list[0] = [nodes_list[0][0], nodes_list[0][1]]
            node_set = set(nodes_list[0])
            for nodes in nodes_list[1:]:
                if len(nodes) > 2:
                    nodes = nodes[nodes[0], nodes[1]]
                node_set.update(nodes)
            if pathway['start'] != nodes_list[0][0]:
                log.error("Start node doesn't match path start for '{}'".format(pathway['id']))
            if pathway['end'] != nodes_list[-1][-1]:
                log.error("End node doesn't match path end for '{}'".format(pathway['id']))
            path_layout = settings.get('pathLayout', 'automatic')
            if path_layout == 'automatic':
                route_segments[pathway['id']] = RouteSegment(pathway['id'], node_set,
                                                             [[self.__nodes.get(node) for node in nodes]
                                                              for nodes in nodes_list],
                                                             [self.__edges.get(edge)
                                                              for edge in pathway['paths']],
                                                             pathway['type'], self.__sheaths, model)

            else:
                route_segments[pathway['id']] = RouteSegment(pathway['id'], node_set,
                                                             [[self.__nodes.get(node) for node in nodes]
                                                              for nodes in nodes_list],
                                                             [self.__edges.get(edge)
                                                              for edge in pathway['paths']],
                                                             pathway['type'], self.__sheaths, model)




        return {connection['id']: [route_segments.get(pathway)
                                   for pathway in connection['pathways']]
                for connection in path_connections['connections']}
        '''
        {
            "id": "connection_1",
            "pathways": [ "neuron_1", "neuron_6"]  # index into pathways
        }
        '''

# ===============================================================================
