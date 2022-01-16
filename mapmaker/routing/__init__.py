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

from collections import Counter, defaultdict
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
        self.__contained_centrelines = defaultdict(list)  #! Feature id --> centrelines contained in feature
        self.__contained_count = {}
        self.__feature_map = None  #! Assigned after ``maker`` has processed sources
        for centreline in network.get('centrelines', []):
            id = centreline.get('id')
            if id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif id in self.__centreline_ids:
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
                    containing_features = set(centreline.get('containedIn', []))
                    self.__contained_count[id] = len(containing_features)
                    for container_id in containing_features:
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

        def find_feature_ids(connectivity_node):
            return set([f.id if f.id is not None else f.get_property('class')
                        for f in feature_map.find_features_by_anatomical_id(*connectivity_node)])

        def __centreline_end_nodes(centreline_id):
            for edge in self.__centreline_graph.edges(data='id'):
                if centreline_id == edge[2]:
                    return edge[:2]

        # Connectivity graph must be undirected
        if isinstance(connectivity, nx.DiGraph):
            connectivity = connectivity.to_undirected()

        route_graph = nx.Graph()
        # Split into connected sub-graphs
        for components in nx.connected_components(connectivity):
            G = connectivity.subgraph(components)
            for node in G.nodes:
                feature_id = None
                found_feature_ids = find_feature_ids(node)
                if len(found_feature_ids) > 1:
                    connected_features = found_feature_ids.intersection(self.__centreline_graph)
                    if len(connected_features) > 1:
                        log.error(f'Node {node} has too many features: {found_feature_ids}')
                    elif len(connected_features):
                        feature_id = connected_features.pop()
                elif len(found_feature_ids):
                    feature_id = found_feature_ids.pop()
                G.nodes[node]['feature_id'] = feature_id
                G.nodes[node]['feature_nodes'] = None

            # All nodes in the (sub-)graph now have a possible feature
            route_feature_ids = set()
            centreline_feature_count = Counter()
            container_features = []
            terminal_nodes = []
            for node in G.nodes:
                feature_id = G.nodes[node]['feature_id']
                if feature_id is not None:
                    if feature_id in self.__centreline_graph:           # Feature is a node
                        route_feature_ids.add(feature_id)
                        G.nodes[node]['feature_nodes'] = [feature_id]
                    elif feature_id in self.__contained_centrelines:    # Path is inside the feature
                        container_features.append((node, feature_id))
                        # Count how many ``containers`` the centreline is in
                        for centreline_id in self.__contained_centrelines[feature_id]:
                            centreline_feature_count[centreline_id] += 1
                    elif G.degree(node) == 1:                           # Terminal node on path
                        terminal_nodes.append(node)

            # Scale the count to get a score indicating how many features
            # contain the centreline
            centreline_score = { id: count/self.__contained_count[id]
                                for id, count in centreline_feature_count.items() }
            # Then find and use the "most-used" centreline for each feature
            # that contains centrelines
            for node, feature_id in container_features:
                max_centreline = None
                max_score = 0
                for centreline_id in self.__contained_centrelines[feature_id]:
                    score = centreline_score[centreline_id]
                    if score > max_score:
                        max_score = score
                        max_centreline = centreline_id
                for edge in self.__centreline_graph.edges(data='id'):
                    if max_centreline == edge[2]:
                        route_feature_ids.update(edge[:2])
                        G.nodes[node]['feature_nodes'] = list(edge[:2])
                        break

            node_terminals = defaultdict(set)
            for node in terminal_nodes:
                feature_id = G.nodes[node]['feature_id']
                feature = feature_map.get_feature(feature_id)
                if feature is None:
                    log.warn(f'Cannot find path terminal feature: {feature_id}')
                    continue
                feature_centre = feature.geometry.centroid
                for edge in nx.edge_dfs(G, node):
                    adjacent_node_features = G.nodes[edge[1]]['feature_nodes']
                    if adjacent_node_features is not None:
                        if len(adjacent_node_features) == 1:
                            adjacent_feature = adjacent_node_features[0]
                        else:
                            # find closest adjacent feature to node
                            node0_centre = self.__centreline_graph.nodes[adjacent_node_features[0]]['geometry'].centroid
                            node1_centre = self.__centreline_graph.nodes[adjacent_node_features[1]]['geometry'].centroid
                            d0 = feature_centre.distance(node0_centre)
                            d1 = feature_centre.distance(node1_centre)
                            adjacent_feature = adjacent_node_features[0] if d0 <= d1 else adjacent_node_features[1]
                        node_terminals[adjacent_feature].add(feature_id)
                        break

            # The centreline paths that connect features on the route
            route_paths = nx.Graph(get_connected_subgraph(self.__centreline_graph, route_feature_ids))

            # Add edges to terminal nodes that aren't part of the centreline network
            for end_node, terminal_nodes in node_terminals.items():
                for terminal_id in terminal_nodes:
                    route_paths.add_edge(end_node, terminal_id, type='terminal')
                    node = route_paths.nodes[terminal_id]
                    self.__set_node_properties(node, terminal_id)

            # Add paths and nodes from connected connectivity sub-graph to result
            route_graph.add_nodes_from(route_paths.nodes(data=True))
            route_graph.add_edges_from(route_paths.edges(data=True))

        return route_graph

#===============================================================================
