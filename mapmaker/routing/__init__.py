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

from mapmaker.settings import settings
from mapmaker.utils import log

from .routedpath import RoutedPath

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
            vpp.update(path)
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
                    self.__graph.add_edge(nodes[0], nodes[-1], id=edge_id, intermediates=nodes[1:-1])
        self.__edges_by_id = { id: edge
                                for edge, id in nx.get_edge_attributes(self.__graph, 'id').items() }
        # The set of network nodes that have only one edge
        self.__terminal_nodes = { n for n, d in self.__graph.degree() if d == 1 }
        # Used to lookup features but only known when `maker` has processed sources
        self.__feature_map = None
        self.__centreline_scaffold = None

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

    def __set_node_properties(self, node, id):
    #=========================================
        feature = self.__find_feature(id)
        if feature is not None:
            if 'geometry' not in node:
                for key, value in feature.properties.items():
                    node[key] = value
                node['geometry'] = feature.geometry

    def create_geometry(self, feature_map):
    #======================================
        self.__feature_map = feature_map
        for edge in self.__graph.edges(data='id'):  # Returns triples: (node, node, id)
            for node_id in edge[0:2]:
                self.__set_node_properties(self.__graph.nodes[node_id], node_id)
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
                        self.__graph.edges[edge[0:2]]['geometry'] = bezier_path
                        if start_point.distance(end_node_0) < start_point.distance(end_node_1):
                            self.__graph.edges[edge[0:2]]['start-node'] = edge[0]
                        else:
                            self.__graph.edges[edge[0:2]]['start-node'] = edge[1]
        if settings.get('pathLayout', 'automatic') == 'automatic':
            # Construct the centreline scaffold for the network
            ##self.__centreline_scaffold = Sheath(self.__id, self.__graph)
            pass

    def route_graph_from_connections(self, connections: dict) -> nx.Graph:
    #=====================================================================
        end_nodes = []
        terminals = {}
        for node in connections:
            if isinstance(node, dict):
                # Check that dict has 'node', 'terminals' and 'type'...
                end_node = node['node']
                end_nodes.append(end_node)
                terminals[end_node] = node.get('terminals', [])
            else:
                end_nodes.append(node)
        # Our route as a subgraph of the centreline network
        route_graph = nx.Graph(get_connected_subgraph(self.__graph, end_nodes))

        # Add edges to terminal nodes that aren't part of the centreline network
        for end_node, terminal_nodes in terminals.items():
            for terminal_id in terminal_nodes:
                route_graph.add_edge(end_node, terminal_id)
                node = route_graph.nodes[terminal_id]
                self.__set_node_properties(node, terminal_id)
                route_graph.edges[end_node, terminal_id]['type'] = 'terminal'

        # Save the geometry of any intermediate points on an edge
        for edge in route_graph.edges(data='intermediates'):
            if edge[2] is not None:
                way_point_geometry = []
                for way_point in edge[2]:
                    feature = self.__find_feature(way_point)
                    if feature is not None:
                        way_point_geometry.append(feature.geometry)
                del(route_graph.edges[edge[0:2]]['intermediates'])
                route_graph.edges[edge[0:2]]['way-points'] = way_point_geometry

        return route_graph

    def layout(self, route_graphs: nx.Graph) -> dict:
    #================================================
        # Route the connection's path through the centreline scaffold
        return { path_id: RoutedPath(path_id, route_graph, self.__centreline_scaffold)
                            for path_id, route_graph in route_graphs.items() }

    def contains(self, id):
    #=======================
        return id in self.__graph

    @staticmethod
    def __find_node_ids(feature_map, anatomical_id, anatomical_layer=None):
        return set([(f.id if f.id is not None else f.get_property('class'), f.get_property('type'))
                    for f in feature_map.find_features_by_anatomical_id(anatomical_id, anatomical_layer)])

    def route_graph_from_connectivity(self, connectivity, feature_map) -> nx.Graph:
    #==============================================================================
        nodes = set()
        nerves = set()
        G = nx.DiGraph()
        for connection in connectivity:
            # connection == graph edge
            print(connection)
            G.add_edge(tuple(connection[0]), tuple(connection[1]), directed=True)
            for anatomical_details in connection:
                for (node_id, node_type) in self.__find_node_ids(feature_map, *anatomical_details):
                    if node_id is not None:
                        if node_type is None:
                            if node_id in self.__graph:
                                nodes.add(node_id)
                            else:
                                ## Terminal, WIP
                                pass
                        elif node_type == 'nerve':   ## type == 'nerve' ##################
                            nerves.add(node_id)
        '''
        in_degrees = G.in_degree()
        heads = [n[0] for n in node_degrees if n[1] == 0]
        for head in heads:
            node = head
            while in_degrees[node] < 2:   ## out_degree??
                node = list(G.neighbors(node)[0]  ### in_ or out_ neighbours ??
        '''
        print('nerves', nerves)
        route_graph = nx.Graph(get_connected_subgraph(self.__graph, nodes))
        nerve_graph = nx.subgraph_view(self.__graph,
            filter_edge=lambda n1, n2: self.__graph[n1][n2].get('container')[0] in nerves)  ## WIP
        nerve_nodes = set()
        for edge in nerve_graph.edges:
            nerve_nodes.update(edge)
        route_graph.update(self.__graph.subgraph(nerve_nodes))
        print(route_graph.nodes)
        return route_graph

#===============================================================================
