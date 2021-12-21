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

from .routedpath import PathRouter

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
        self.__centreline_ids = []
        self.__containing_features = defaultdict(set)  #! Centreline id --> set of feature ids that contain centreline
        self.__contained_centrelines = defaultdict(list)  #! Feature id --> centrelines contained in feature
        self.__feature_map = None  #! Assigned after ``maker`` has processed sources
        for centreline in network.get('centrelines', []):
            id = centreline.get('id')
            if id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif id in self.__containing_features:
                log.error(f'Centreline {id} in network {self.__id} has a duplicated id')
            else:
                nodes = centreline.get('connects', [])
                if len(nodes) < 2:
                    log.warn(f'Centreline {id} in network {self.__id} has too few nodes')
                else:
                    self.__centreline_ids.append(id)
                    edge_properties = {'id': id}
                    if len(nodes) > 2:
                        edge_properties['intermediates'] = nodes[1:-1]
                    self.__containing_features[id] = set(centreline.get('containedIn', []))
                    for container_id in self.__containing_features[id]:
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
        path_router = PathRouter()
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
            path_router.add_path(path_id, route_graph)
        # Layout the paths and return the result
        path_router.layout()
        return path_router.routed_paths

    def contains(self, id):
    #=======================
        return (id in self.__centreline_ids
             or id in self.__centreline_graph)

    def route_graph_from_connectivity(self, connectivity, feature_map) -> nx.Graph:
    #==============================================================================
        route_feature_ids = set()
        node_terminals = {}

        # Construct a graph of SciCrunch's connected pairs
        G = nx.DiGraph()
        for connection in connectivity:
            G.add_edge(connection[0], connection[1], directed=True)

        # Walk edges from each start node, finding network nodes and centrelines
        seen_edges = []
        for head_node in [ n for n in G if G.in_degree(n) == 0]:
            node_finder = NodeFinder(G, self.__centreline_graph, self.__containing_features,
                                        self.__contained_centrelines, feature_map)
            for edge in nx.edge_dfs(G, head_node):
                if edge in seen_edges:
                    continue
                seen_edges.append(edge)
                node_finder.add_node(edge[0], False)
                # Process the last node of the traversal
                if G.out_degree(edge[1]) == 0:
                    node_finder.add_node(edge[1], True)
            route_feature_ids.update(node_finder.feature_ids)
            node_terminals.update(node_finder.terminals)

        route_graph = nx.Graph(get_connected_subgraph(self.__centreline_graph, route_feature_ids))

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
    def __init__(self, anatomical_graph, centreline_graph, containing_features,
                                         contained_centrelines, feature_map):
        self.__anatomical_graph = anatomical_graph
        self.__centreline_graph = centreline_graph
        self.__containing_features = containing_features  # Centreline id --> set of feature ids that contain centreline
        self.__contained_centrelines = contained_centrelines  # Feature id --> centrelines contained in feature
        self.__feature_map = feature_map
        self.__feature_ids = []
        self.__node_terminals = defaultdict(set)
        self.__matched_features = {}
        self.__start_terminals = set()

    @property
    def feature_ids(self):
        return self.__feature_ids

    @property
    def terminals(self):
        if len(self.__start_terminals) and len(self.__feature_ids) > 0:   ### WIP
            self.__node_terminals[self.__feature_ids[-1]].update(self.__start_terminals)
            self.__start_terminals = set()
        return self.__node_terminals

    def __find_feature_ids(self, connectivity_node):
    #===============================================
        return set([f.id if f.id is not None else f.get_property('class')
                    for f in self.__feature_map.find_features_by_anatomical_id(*connectivity_node)])

    def __centreline_end_nodes(self, id):
    #====================================
        for edge in self.__centreline_graph.edges(data='id'):
            if id == edge[2]:
                return edge[:2]

    def add_node(self, connectivity_node, last_node):
    #================================================
        found_ids = self.__find_feature_ids(connectivity_node)
        if len(found_ids) > 1:
            log.error(f'Node {connectivity_node} has too many features: {found_ids}')
        elif len(found_ids) == 1:
            found_id = list(found_ids)[0]
            if found_id in self.__centreline_graph:
                self.__matched_features = {}
                if len(self.__start_terminals):
                    self.__node_terminals[found_id] = self.__start_terminals
                    self.__start_terminals = set()
                self.__feature_ids.append(found_id)
            elif found_id in self.__contained_centrelines and len(self.__matched_features) == 0:
                self.__matched_features = { centreline_id: list(self.__containing_features[centreline_id])
                                                for centreline_id in self.__contained_centrelines[found_id] }
            elif self.__anatomical_graph.in_degree(connectivity_node) == 0:
                self.__start_terminals.add(found_id)     # Start of chain
            elif last_node:
                if len(self.__feature_ids):
                    self.__node_terminals[self.__feature_ids[-1]].add(found_id)
                #self.__terminal_nodes.add(node)     # End of chain

            end_feature_ids = []
            if len(self.__matched_features):
                for centreline_id, feature_ids in self.__matched_features.items():
                    if found_id in feature_ids:
                        feature_ids.remove(found_id)
                        if len(feature_ids) == 0:
                            end_feature_ids = self.__centreline_end_nodes(centreline_id)
                            self.__feature_ids.extend(end_feature_ids)
                            self.__matched_features = {}
                            if len(self.__start_terminals):
                                self.__node_terminals[self.__feature_ids[-1]].update(self.__start_terminals)
                                self.__start_terminals = set()
                            break

#===============================================================================
