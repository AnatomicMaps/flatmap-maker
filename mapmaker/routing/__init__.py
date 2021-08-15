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
Networks are defined in terms of their topological connections and geometric
structures and can be thought of as conduit networks through which individual
wires are routed.
"""

#===============================================================================

import itertools

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.utils import log

from .network import RouteSegment

#===============================================================================

"""
Find the subgraph G' induced on G, that
1) contain all nodes in a set of nodes V', and
2) is a connected component.

See: https://stackoverflow.com/questions/58076592/python-networkx-connect-subgraph-with-a-loose-node
"""

def get_connected_subgraph(graph, v_prime):
#==========================================
    """Given a graph G=(V,E), and a vertex set V', find the V'', that
    1) is a superset of V', and
    2) when used to induce a subgraph on G forms a connected component.

    Arguments:
    ----------
    graph : networkx.Graph object
        The full graph.
    v_prime : list
        The chosen vertex set.

    Returns:
    --------
    G_prime : networkx.Graph object
        The subgraph of G fullfilling criteria 1) and 2).

    """
    vpp = set()
    for source, target in itertools.combinations(v_prime, 2):
        paths = nx.all_shortest_paths(graph, source, target)
        for path in paths:
            vpp = vpp.union(path)
    return graph.subgraph(vpp)

#===============================================================================

class Network(object):
    def __init__(self, network):
        self.__id = network.get('id')
        self.__graph = nx.Graph()
        for centreline in network.get('centrelines', []):
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
        # The set of network nodes that have only one edge
        self.__terminal_nodes = { n for n, d in self.__graph.degree() if d == 1 }
        # Used to lookup features but only known when `maker` has processed sources
        self.__feature_map = None

    @property
    def id(self):
        return self.__id

    def __find_feature(self, id):
    #============================
        features = self.__feature_map.features(id)
        if len(features) == 1:
            return features[0]
        elif len(features) == 0:
            log.warn('Unknown network feature: {}'.format(id))
        else:
            log.warn('Multiple network features for: {}'.format(id))
        return None

    def __set_node_properties(self, node_id, graph):
    #===============================================
        feature = self.__find_feature(node_id)
        if feature is not None:
            node = graph.nodes[node_id]
            if 'geometry' not in node:
                for key, value in feature.properties.items():
                    node[key] = value
                node['geometry'] = feature.geometry

    def create_geometry(self, feature_map):
    #======================================
        self.__feature_map = feature_map
        for edge in self.__graph.edges.data('id'):  # Returns triples: (node, node, id)
            for node_id in edge[0:2]:
                self.__set_node_properties(node_id, self.__graph)

            feature = self.__find_feature(edge[2])
            if feature is not None:
                bezier_path = feature.get_property('bezier-path')
                if bezier_path is None:
                    log.warn('Centreline {} has no Bezier path'.format(feature.id))
                else:
                    bezier_start = bezier_path.pointAtTime(0)
                    start_point = shapely.geometry.Point(bezier_start.x, bezier_start.y)
                    end_node_0 = self.__graph.nodes[edge[0]].get('geometry')
                    end_node_1 = self.__graph.nodes[edge[1]].get('geometry')
                    if end_node_0 is not None and end_node_1 is not None:
                        if start_point.distance(end_node_0) > start_point.distance(end_node_1):
                            bezier_path = bezier_path.reverse()
                        self.__graph.edges[edge[0:2]]['geometry'] = bezier_path

    def layout(self, connections: list) -> dict:
    #===========================================
        route_segments = {}
        for connects in connections:
            end_nodes = []
            terminals = {}
            for node in connects:
                if isinstance(node, dict):
                    # Check that dict has 'node' and 'terminals'...
                    end_node = node['node']
                    end_nodes.append(end_node)
                    terminals[end_node] = node['terminals']
                else:
                    end_nodes.append(node)
            route_graph = nx.Graph(get_connected_subgraph(self.__graph, end_nodes))
            for end_node, terminal_nodes in terminals.items():
                for terminal in terminal_nodes:
                    route_graph.add_edge(end_node, terminal)
                    self.__set_node_properties(terminal, route_graph)

            '''  WIP...
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
                                                         [e for e in [self.__edges.get(edge)
                                                            for edge in pathway['paths']] if e is not None],
                                                         pathway['type'])
            '''
        return { } #connection['id']: [ route_segments.get(pathway)
                   #                     for pathway in connection['pathways']]
            #for connection in connections}

    def has_node(self, id):
    #=======================
        return id in self.__graph

#===============================================================================
