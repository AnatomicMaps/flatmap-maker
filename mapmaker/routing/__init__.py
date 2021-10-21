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

from collections import defaultdict
import itertools

#===============================================================================

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
    def __init__(self, network, external_properties):
        self.__id = network.get('id')
        self.__centreline_graph = nx.Graph()
        self.__contained_centrelines = defaultdict(list)  # Centreline ids of a container
        self.__containers = {}                            # Containers of a centreline
        self.__feature_map = None                         # Assigned after `maker` has processed sources
        for centreline in network.get('centrelines', []):
            id = centreline.get('id')
            if id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif id in self.__containers:
                log.error(f'Centreline {id} in network {self.__id} has a duplicated id')
            else:
                nodes = centreline.get('connects', [])
                if len(nodes) < 2:
                    log.warn(f'Centreline {id} in network {self.__id} has too few nodes')
                else:
                    edge_properties = {'id': id}
                    if len(nodes) > 2:
                        edge_properties['intermediates'] = nodes[1:-1]
                    self.__containers[id] = set(centreline.get('contained-in', []))
                    for container_id in self.__containers[id]:
                        self.__contained_centrelines[container_id].append(id)
                        if external_properties.get_property(container_id, 'type') == 'nerve':
                            edge_properties['nerve'] = container_id
                    self.__centreline_graph.add_edge(nodes[0], nodes[-1], **edge_properties)

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
        for edge in self.__centreline_graph.edges(data='id'):  # Returns triples: (node, node, id)
            for node_id in edge[0:2]:
                self.__set_node_properties(self.__centreline_graph.nodes[node_id], node_id)
            feature = self.__find_feature(edge[2])
            if feature is not None:
                bezier_path = feature.get_property('bezier-path')
                if bezier_path is None:
                    log.warn('Centreline {} has no Bezier path'.format(feature.id))
                else:
                    bezier_start = bezier_path.pointAtTime(0)
                    start_point = shapely.geometry.Point(bezier_start.x, bezier_start.y)
                    end_node_0 = self.__centreline_graph.nodes[edge[0]].get('geometry')
                    end_node_1 = self.__centreline_graph.nodes[edge[1]].get('geometry')
                    if end_node_0 is not None and end_node_1 is not None:
                        self.__centreline_graph.edges[edge[0:2]]['geometry'] = bezier_path
                        if start_point.distance(end_node_0) < start_point.distance(end_node_1):
                            self.__centreline_graph.edges[edge[0:2]]['start-node'] = edge[0]
                        else:
                            self.__centreline_graph.edges[edge[0:2]]['start-node'] = edge[1]
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
        route_graph = nx.Graph(get_connected_subgraph(self.__centreline_graph, end_nodes))

        # Add edges to terminal nodes that aren't part of the centreline network
        for end_node, terminal_nodes in terminals.items():
            for terminal_id in terminal_nodes:
                route_graph.add_edge(end_node, terminal_id)
                node = route_graph.nodes[terminal_id]
                self.__set_node_properties(node, terminal_id)
                route_graph.edges[end_node, terminal_id]['type'] = 'terminal'

        return route_graph

    def layout(self, route_graphs: nx.Graph) -> dict:
    #================================================
        laid_out_paths = {}
        for path_id, route_graph in route_graphs.items():
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

            ### Need to have all paths in each centreline to solve for offsets...
            # Route the connection's path through the centreline scaffold
            laid_out_paths[path_id] = RoutedPath(path_id, route_graph)
        return laid_out_paths

    def contains(self, id):
    #=======================
        return id in self.__centreline_graph

    def route_graph_from_connectivity(self, connectivity, feature_map) -> nx.Graph:
    #==============================================================================
        route_nodes = []
        node_terminals = {}

        # Construct a graph of SciCrunch's connected pairs
        G = nx.DiGraph()
        for connection in connectivity:
            G.add_edge(tuple(connection[0]), tuple(connection[1]), directed=True)

        # Walk edges from each start node, finding network nodes and centrelines
        for head_node in [ n for n in G if G.in_degree(n) == 0]:
            node_finder = NodeFinder(G, self.__centreline_graph, self.__containers,
                                        self.__contained_centrelines, feature_map)
            for edge in nx.edge_dfs(G, head_node):
                node_finder.lookup(edge[0])
                # Process the last node of the traversal
                if G.out_degree(edge[1]) == 0:
                    node_finder.lookup(edge[1])

            route_nodes.extend(node_finder.nodes)
            node_terminals.update(node_finder.terminals)

        route_graph = nx.Graph(get_connected_subgraph(self.__centreline_graph, route_nodes))

        # Add edges to terminal nodes that aren't part of the centreline network
        for end_node, terminal_nodes in node_terminals.items():
            for terminal_id in terminal_nodes:
                route_graph.add_edge(end_node, terminal_id)
                node = route_graph.nodes[terminal_id]
                self.__set_node_properties(node, terminal_id)
                route_graph.edges[end_node, terminal_id]['type'] = 'terminal'

        return route_graph

#===============================================================================

class NodeFinder(object):
    def __init__(self, anatomical_graph, centreline_graph, containers,
                                         contained_centrelines, feature_map):
        self.__anatomical_graph = anatomical_graph
        self.__centreline_graph = centreline_graph
        self.__containers = containers
        self.__contained_centrelines = contained_centrelines
        self.__feature_map = feature_map
        self.__nodes = []
        self.__node_terminals = {}
        self.__matched = None
        self.__terminal_nodes = set()

    @property
    def nodes(self):
        return self.__nodes

    @property
    def terminals(self):
        if len(self.__terminal_nodes):   ### WIP
            self.__node_terminals[self.__nodes[-1]] = self.__terminal_nodes
        return self.__node_terminals

    def __find_map_ids(self, anatomical_id, anatomical_layer=None):
    #========================================================
        return set([f.id if f.id is not None else f.get_property('class')
                    for f in self.__feature_map.find_features_by_anatomical_id(anatomical_id, anatomical_layer)])

    def __centreline_end_nodes(self, id):
    #====================================
        for edge in self.__centreline_graph.edges(data='id'):
            if id == edge[2]:
                return edge[:2]

    def lookup(self, anatomical_node):
    #=================================
        nodes = self.__find_map_ids(*anatomical_node)
        if len(nodes) > 1:
            log.error(f'Node {anatomical_node} has too many features, {nodes}')
        elif len(nodes) == 1:
            node = list(nodes)[0]
            if node in self.__nodes:
                return         # Already seen remaining edges
            elif node in self.__centreline_graph:
                matched = None
                if len(self.__terminal_nodes):
                    self.__node_terminals[node] = self.__terminal_nodes
                    self.__terminal_nodes = set()
                self.__nodes.append(node)
            elif self.__matched is None and node in self.__contained_centrelines:
                self.__matched = { id: list(self.__containers[id])
                                        for id in self.__contained_centrelines[node] }
            elif self.__anatomical_graph.in_degree(anatomical_node) == 0:
                self.__terminal_nodes.add(node)     # Start of chain
            elif self.__anatomical_graph.out_degree(anatomical_node) == 0:
                self.__terminal_nodes.add(node)     # End of chain

            end_nodes = None
            if self.__matched is not None:
                for id, containers in self.__matched.items():
                    if node in containers:
                        if len(self.__matched) == 1:
                            end_nodes = self.__centreline_end_nodes(id)
                            self.__matched = None
                            break
                        else:
                            containers.remove(node)
                            if len(containers) == 0:
                                end_nodes = self.__centreline_end_nodes(id)
                                self.__matched = None
                                break
            if end_nodes is not None:
                self.__nodes.extend(end_nodes)
                if len(self.__terminal_nodes):
                    # want end of centreline e[0] -> e[1] that is closest to terminals...
                    self.__node_terminals[end_nodes[1]] = self.__terminal_nodes
                    self.__terminal_nodes = set()

#===============================================================================
