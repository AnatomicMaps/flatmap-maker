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

from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import partial
import itertools
import math
import sys
from typing import TYPE_CHECKING


#===============================================================================

if sys.version_info >= (3, 10):
    # Python 3.10
    from itertools import pairwise
else:
    # Python < 3.10
    from itertools import tee

    def pairwise(iterable):
        "s -> (s0,s1), (s1,s2), (s2, s3), ..."
        a, b = tee(iterable)
        next(b, None)
        return zip(a, b)

#===============================================================================

from beziers.line import Line as BezierLine
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.flatmap.feature import Feature, full_node_name
from mapmaker.geometry.beziers import bezier_to_linestring, closest_time_distance
from mapmaker.geometry.beziers import coords_to_point, point_to_coords
from mapmaker.geometry.beziers import set_bezier_path_end_to_point, split_bezier_path_at_point
from mapmaker.settings import settings
from mapmaker.utils import log
import mapmaker.utils.graph as graph_utils

from .options import MIN_EDGE_JOIN_RADIUS
from .routedpath import PathRouter

if TYPE_CHECKING:
    from mapmaker.properties import ExternalProperties
    from mapmaker.properties.pathways import Path

#===============================================================================

"""
Find the subgraph G' induced on G, that
1) contain all nodes in a set of nodes V', and
2) is a connected component.

See: https://stackoverflow.com/questions/58076592/python-networkx-connect-subgraph-with-a-loose-node
"""

def get_connected_subgraph(path_id, graph, v_prime):
#===================================================
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
        if nx.has_path(graph, source, target):
            paths = nx.all_shortest_paths(graph, source, target)
            for path in paths:
                vpp.update(path)
        else:
            log.warning(f'{path_id}: No network connection between {source} and {target}')
    return graph.subgraph(vpp)

def expand_centreline_graph(graph: nx.Graph) -> nx.Graph:
#========================================================
    G = nx.Graph()
    for node_0, node_1, edge_dict in graph.edges(data=True):
        G.add_node(node_0, graph_object='node', **graph.nodes[node_0])
        G.add_node(node_1, graph_object='node', **graph.nodes[node_1])
        if (segment_id := edge_dict.get('segment')) is not None:
            edge_node = segment_id
        else:
            edge_node = (node_0, node_1)
        G.add_node(edge_node, graph_object='edge', node_ends=(node_0, node_1), **edge_dict)
        G.add_edge(node_0, edge_node, graph_object='node')
        G.add_edge(edge_node, node_1, graph_object='node')
    return G

def collapse_centreline_graph(graph: nx.Graph) -> nx.Graph:
#==========================================================
    G = nx.Graph()
    seen_edges = set()
    for node, node_dict in graph.nodes(data=True):
        new_dict = node_dict.copy()
        graph_object = new_dict.pop('graph_object', None)
        if graph_object == 'edge':
            end_nodes = new_dict.pop('node_ends')
            if end_nodes in seen_edges:
                log.warning(f'Edge `{node}` ignored as it is already in the route graph')
            else:
                G.add_edge(*end_nodes, **new_dict)
                seen_edges.add(end_nodes)
        elif graph_object == 'node':
            G.add_node(node, **new_dict)
        else:
            log.warning(f'Expanded graph node `{node}` ignored as it has no `graph type`')
    return G

#===============================================================================

@dataclass
class NetworkNode:
    full_id: str
    intermediate: bool = False
    map_feature: Feature = None
    feature_id: str = field(init=False)
    properties: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.feature_id = self.full_id.rsplit('/', 1)[-1]

    def __eq__(self, other):
        return self.feature_id == other.feature_id

    def __hash__(self, other):
        return hash(self.feature_id)

    @property
    def centre(self):
        return self.properties.get('centre')

    @centre.setter
    def centre(self, value):
        self.properties['centre'] = value

    @property
    def radii(self):
        return self.properties.get('radii')

    def set_properties_from_feature(self, feature: Feature):
    #=======================================================
        if feature is not None:
            self.map_feature = feature
            self.properties.update(feature.properties)
            self.properties['geometry'] = feature.geometry
            if feature.geometry is not None:
                centre = feature.geometry.centroid
                self.properties['centre'] = BezierPoint(centre.x, centre.y)
                radius = max(math.sqrt(feature.geometry.area/math.pi), MIN_EDGE_JOIN_RADIUS)
                self.properties['radii'] = (0.999*radius, 1.001*radius)
            else:
                log.warning(f'Centreline node {feature.id} has no geometry')

#===============================================================================

class Network(object):
    def __init__(self, network: dict, external_properties: ExternalProperties=None):
        self.__id = network.get('id')
        self.__centreline_graph = None                      #! Edges are centreline segments between intermediate nodes.
                                                            #! Assigned once we have feature geometry
        self.__expanded_centreline_graph = None             #! Expanded version of centreline graph
        self.__centreline_nodes: dict[str, list[NetworkNode]] = defaultdict(list)  #! Centreline id --> [Network nodes]


        self.__contained_centrelines = defaultdict(list)    #! Feature id --> centrelines contained in feature
        self.__containers_by_centreline = {}                #! Centreline id --> set of features that centreline is contained in
        self.__centrelines_by_container = defaultdict(set)  #! Containing feature id --> set of centrelines contained in feature

        self.__edges_by_segment_id = {}                     #! Edge id --> edge key
                                                            ## vs segmented centreline id???

        self.__models_to_id: dict[str, str] = {}            #! Ontological term --> centreline id

        self.__feature_ids: set[str] = set()
        self.__full_ids: set[str] = set()                   #! A ``full id`` is a slash-separated list of feature ids
        self.__feature_map = None  #! Assigned after ``maker`` has processed sources
        self.__missing_feature_ids = set()

        end_nodes_to_centrelines = defaultdict(list)
        intermediate_nodes_to_centrelines = defaultdict(list)

        # First pass to check validity and collect centreline and end node identifiers
        for centreline in network.get('centrelines', []):
            centreline_id = centreline.get('id')
            if centreline_id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif centreline_id in self.__centreline_nodes:
                log.error(f'Centreline {centreline_id} in network {self.__id} has a duplicate id')
            else:
                self.__add_full_id(centreline_id)
                if (models := centreline.get('models')) is not None:
                    if models in self.__models_to_id:
                        log.warning(f'Centrelines `{centreline_id}` and `{self.__models_to_id[models]}` both model {models}')
                    else:
                        self.__models_to_id[models] = centreline_id
                        # If we have ``external_properties`` without ``models`` annotation for the centreline then set it
                        if (external_properties is not None
                        and external_properties.get_property(centreline_id, 'models') is None):
                            external_properties.set_property(centreline_id, 'models', models)
                connected_nodes = centreline.get('connects', [])
                if len(connected_nodes) < 2:
                    log.warning(f'Centreline {centreline_id} in network {self.__id} has too few nodes')
                else:
                    self.__add_full_id(connected_nodes[0])
                    self.__add_full_id(connected_nodes[-1])
                    self.__centreline_nodes[centreline_id] = [NetworkNode(node_id) for node_id in connected_nodes]
                    end_nodes_to_centrelines[connected_nodes[0]].append(centreline_id)
                    end_nodes_to_centrelines[connected_nodes[-1]].append(centreline_id)
                    for node_id in connected_nodes[1:-1]:
                        intermediate_nodes_to_centrelines[node_id].append(centreline_id)

        # Check for multiple branches and crossings
        for node, centrelines in intermediate_nodes_to_centrelines.items():
            if len(centrelines) > 1:
                log.error(f'Node {node} is intermediate node for more than several centrelines: {centrelines}')
            if len(centrelines := end_nodes_to_centrelines.get(node, [])) > 1:
                log.error(f'Intermediate node {node} branches to several centrelines: {centrelines}')

        # Separate out branch nodes that make up the segmented centreline graph from intermediate nodes
        for centreline_id, nodes in self.__centreline_nodes.items():
            for node in nodes:
                node.intermediate = (node.full_id not in self.__full_ids)

    @property
    def id(self):
        return self.__id

    def __add_full_id(self, full_id):
    #================================
        self.__full_ids.add(full_id)
        for id in full_id.split('/'):
            self.__feature_ids.add(id)

    def set_feature_map(self, feature_map):
    #======================================
        self.__feature_map = feature_map
        # Check that the network's features are on the map
        for id in sorted(self.__feature_ids):
            if not feature_map.has_feature(id):
                log.warning(f'Network feature {id} cannot be found on the flatmap')

    def has_feature(self, feature):
    #==============================
        # Is the ``feature`` included in this network?
        return (feature.id in self.__feature_ids
             or feature.property('tile-layer') == 'pathways')

    def __map_feature(self, feature_id):
    #===================================
        if feature_id not in self.__missing_feature_ids:
            if (feature := self.__feature_map.get_feature(feature_id)) is not None:
                return feature
            log.error('Cannot find network feature: {}'.format(feature_id))
            self.__missing_feature_ids.add(feature_id)
        return None

    def __set_properties_from_feature(self, feature_id):
    #====================================================
        feature = self.__map_feature(feature_id)
        node_dict = {}
        if feature is not None:
            node_dict.update(feature.properties)
            node_dict['geometry'] = feature.geometry
            if feature.geometry is not None:
                centre = feature.geometry.centroid
                node_dict['centre'] = BezierPoint(centre.x, centre.y)
                radius = max(math.sqrt(feature.geometry.area/math.pi), MIN_EDGE_JOIN_RADIUS)
                node_dict['radii'] = (0.999*radius, 1.001*radius)
            else:
                log.warning(f'Centreline node {node_dict.get("id")} has no geometry')
        return node_dict

    def create_geometry(self):
    #=========================
        def set_default_node_properties(node):
            feature_id = node.feature_id
            if feature_id not in self.__centreline_graph:
                self.__centreline_graph.add_node(feature_id, **node.properties)
                # Direction of a path at the node boundary, going towards the centre (radians)
                self.__centreline_graph.nodes[feature_id]['edge-direction'] = {}
                # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
                self.__centreline_graph.nodes[feature_id]['edge-node-angle'] = {}

        def split_path_and_update_centreline_graph(node_0, node_1, bz_path, path_reversed):
            # Split Bezier path at ``node_1``, assigning the front portion to the
            # ``(node_0, node_1)`` edge and return the remainder.

            if not path_reversed:
                (start_node, end_node) = (node_0, node_1)
            else:
                (start_node, end_node) = (node_1, node_0)

            (start_node_id, end_node_id) = (start_node.feature_id, end_node.feature_id)
            edge_dict = self.__centreline_graph.edges[start_node_id, end_node_id]

            (cl_path, bz_path) = split_bezier_path_at_point(bz_path, end_node.centre)

            # Set the end of the segment's centreline to the center of the end node
            set_bezier_path_end_to_point(cl_path, end_node.centre)

            edge_dict['bezier-path'] = cl_path
            edge_dict['reversed'] = path_reversed
            edge_dict['length'] = cl_path.length  # Use in finding shortest route

            segments = cl_path.asSegments()
            edge_id = edge_dict['segment']

            edge_dict['start-node'] = start_node_id
            try:
                # Direction of a path at the node boundary, going towards the centre (radians)
                self.__centreline_graph.nodes[start_node_id]['edge-direction'][edge_id] = segments[0].startAngle + math.pi
            except KeyError:
                print(start_node_id, end_node_id)
                raise
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[start_node_id]['edge-node-angle'][end_node_id] = (
                                    (segments[0].pointAtTime(0.0) - start_node.centre).angle)

            edge_dict['end-node'] = end_node_id
            # Direction of a path at the node boundary, going towards the centre (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-direction'][edge_id] = segments[-1].endAngle
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-node-angle'][start_node_id] = (
                                    # why segments[0].pointAtTime(0.0) ??
                                    (segments[-1].pointAtTime(1.0) - end_node.centre).angle)

            return bz_path

        self.__centreline_graph = nx.Graph()
        for centreline_id, nodes in self.__centreline_nodes.items():
            if (self.__map_feature(nodes[0].feature_id) is None
             or self.__map_feature(nodes[-1].feature_id) is None):
                log.error(f'Centreline {centreline_id} ignored: end nodes are not on map')
                continue
            if (centreline_feature := self.__map_feature(centreline_id)) is None:
                log.warning(f'Centreline {centreline_id} ignored: not on map')
                continue

            # Set node properties
            for node in nodes:
                node.set_properties_from_feature(self.__map_feature(node.feature_id))

            bz_path = BezierPath.fromSegments(centreline_feature.property('bezier-segments'))
            node_0_centre = nodes[0].centre
            path_reversed = (node_0_centre.distanceFrom(bz_path.pointAtTime(0.0)) >
                             node_0_centre.distanceFrom(bz_path.pointAtTime(1.0)))
            seg_no = 0
            start_index = 0
            # Construct the segmented centreline graph
            while start_index < len(nodes) - 1:
                seg_no += 1
                start_node = nodes[start_index]
                # Set the start of the centreline to the center of next start node
                set_bezier_path_end_to_point(bz_path, start_node.centre)

                end_index = start_index + 1
                # Loop must terminate as nodes[-1] is a map feature from above
                end_node = nodes[end_index]
                while end_node.map_feature is None or end_node.intermediate:
                    end_node.intermediate = True  # Nodes without a feature become intermediate nodes
                    end_index += 1
                    end_node = nodes[end_index]
                if start_index > 0 or end_index < (len(nodes) - 1):
                    segment_id = f'{centreline_id}/{seg_no}'
                else:
                    segment_id = centreline_id

                # Initialise the graph's node data before creating an edge between them
                set_default_node_properties(start_node)
                set_default_node_properties(end_node)

                # Add an edge to the segmented centreline graph
                self.__centreline_graph.add_edge(start_node.feature_id, end_node.feature_id,
                                                 segment=segment_id,
                                                 nodes=nodes[start_index:end_index+1])

                # Split Bezier path at segment boundary and return the remainder.
                # NB. this also sets the end of the segment's centerline to the centre if the end node
                bz_path = split_path_and_update_centreline_graph(start_node, end_node, bz_path, path_reversed)

                start_index = end_index

        # Set the ``degree`` property now that we have the complete graph
        for feature_id, node_dict in self.__centreline_graph.nodes(data=True):
            node_dict['degree'] = self.__centreline_graph.degree(feature_id)

        # Ensure all intermediate node centres are on their centreline
        for node_0, node_1, edge_dict in self.__centreline_graph.edges(data=True):
            nodes = edge_dict['nodes']
            bz_path = edge_dict['bezier-path']
            path_reversed = edge_dict['reversed']
            segment_id = edge_dict['segment']
            last_t = 0.0 if not path_reversed else 1.0
            for node in nodes[1:-1]:
                # Set node centre to the closest point on the centreline's path
                t = closest_time_distance(bz_path, node.centre)[0]
                if (not path_reversed and t <= last_t
                 or     path_reversed and t >= last_t):
                    log.error(f'Centreline {segment_id} nodes are out of sequence...')
                else:
                    node.centre = bz_path.pointAtTime(t)
                last_t = t

            nodes = self.__centreline_nodes[centreline_id]
        self.__expanded_centreline_graph = expand_centreline_graph(self.__centreline_graph)

        self.__expanded_centreline_nodes = { centreline_id: node for node, node_dict
                                                in self.__expanded_centreline_graph.nodes(data=True)
                                                    if (centreline_id := node_dict.get('centreline')) is not None}

    def __route_graph_from_connections(self, path: Path) -> nx.Graph:
    #================================================================
        # This is when the paths are manually specified and don't come from SciCrunch
        end_nodes = []
        terminals = {}
        for node in path.connections:
            if isinstance(node, dict):
                # Check that dict has 'node', 'terminals' and 'type'...
                end_node = node['node']
                end_nodes.append(end_node)
                terminals[end_node] = node.get('terminals', [])
            else:
                end_nodes.append(node)

        # Our route as a subgraph of the centreline network
        route_graph = nx.Graph(get_connected_subgraph(path.id, self.__centreline_graph, end_nodes))

        # Add edges to terminal nodes that aren't part of the centreline network
        for end_node, terminal_nodes in terminals.items():
            for terminal_id in terminal_nodes:
                route_graph.add_edge(end_node, terminal_id)
                node_dict = route_graph.nodes[terminal_id]
                node_dict.update(self.__node_properties_from_feature(terminal_id))
                route_graph.edges[end_node, terminal_id]['type'] = 'terminal'
        return route_graph

    def route_graph_from_path(self, path: Path):
    #===========================================
        if path.connections is not None:
            route_graph = self.__route_graph_from_connections(path)
        else:
            route_graph = self.__route_graph_from_connectivity(path)
        route_graph.graph['path-id'] = path.id
        route_graph.graph['path-type'] = path.path_type
        route_graph.graph['source'] = path.source
        return route_graph

    def layout(self, route_graphs: nx.Graph) -> dict:
    #================================================
        path_router = PathRouter()
        for path_id, route_graph in route_graphs.items():
            path_router.add_path(path_id, route_graph)
        # Layout the paths and return the resulting routes
        return path_router.layout()

    def contains(self, id: str) -> bool:
    #===================================
        return (id in self.__centreline_ids
             or id in self.__centreline_graph)

    def __route_graph_from_connectivity(self, path: Path) -> nx.Graph:
    #=================================================================
        # Connectivity comes from SCKAN

        def nodes_from_dict(node_dict):
        #==============================
            nodes = set()
            if (centreline := node_dict.get('centreline')) is not None:
                nodes.update(self.__edges_by_id[centreline][0:2])
            elif (feature_id := node_dict.get('feature-id')) is not None:
                nodes.add(feature_id)
            return nodes

        def find_centreline_from_containers(start_dict, features, end_dict):
        #===================================================================
            end_nodes = nodes_from_dict(start_dict)
            end_nodes.update(nodes_from_dict(end_dict))
            max_score = 0
            centreline_id = None
            for id, containing_features in self.__contained_by_id.items():
                if len(end_nodes):
                    edge_nodes = self.__edges_by_id[id][0:2]
                    node_score = len(end_nodes.intersection(edge_nodes))/len(end_nodes)
                else:
                    node_score = 0
                if common := len(containing_features.intersection(features)):
                    # Jaccard index
                    jaccard_index = common/(len(features) + len(containing_features) - common)
                    score = node_score + jaccard_index
                    if score > max_score:
                        max_score = score
                        centreline_id = id
            return centreline_id

        def node_dict_for_feature(connectivity_node):
        #============================================
            # Check if we can directly identify the centreline
            if (centreline := self.__models_to_id.get(connectivity_node[0])) is not None:
                return {
                    'node': connectivity_node,
                    'feature-id': centreline,
                    'centreline': centreline
                }
            features = self.__feature_map.find_path_features_by_anatomical_id(*connectivity_node)
            if len(features) == 0:
                return {'warning': f'Cannot find connectivity node: {full_node_name(*connectivity_node)}'}
            result = {'node': connectivity_node}
            if len(connectivity_node[1]):
                result['organ'] = connectivity_node[1][-1]
            feature_ids = set(f.id if f.id is not None else f.property('class')    ## Class is deprecated as an identifier...
                                        for f in features)
            if len(feature_ids) > 1:
                # We've found multiple features on the flatmap, so restrict them to the set of centreline nodes
                # to see if we can find a unique feature
                connected_features = feature_ids.intersection(self.__centreline_graph)
                if len(connected_features) > 1:
                    result.update({'error': f'Node {full_node_name(*connectivity_node)} has too many connected features: {feature_ids}'})
                elif len(connected_features):  # len(connected_features) == 1
                    result.update({'feature-id': connected_features.pop()})
                else:                          # len(connected_features) == 0
                    # Multiple terminal nodes -- simply choose one
                    result.update({
                        'warning': f'Node {full_node_name(*connectivity_node)} has multiple terminal features: {feature_ids}',
                        'feature-id': feature_ids.pop()
                    })
            elif len(feature_ids):
                result.update({'feature-id': feature_ids.pop()})
            if len(result) == 0:
                log.error(f'{path.id}: Cannot find {full_node_name(*connectivity_node)}   <<<<<<<<<<<<<<<<<<<<<<')
            return result

        def closest_node_to(feature_node, centreline):
        #=============================================
            # Find closest centreline node to feature_node
            feature = self.__feature_map.get_feature(feature_node)
            feature_centre = feature.geometry.centroid
            closest_node = None
            closest_distance = -1
            for node in self.__edges_by_id[centreline][0:2]:
                node_centre = self.__centreline_graph.nodes[node]['geometry'].centroid
                distance = feature_centre.distance(node_centre)
                if closest_node is None or distance < closest_distance:
                    closest_distance = distance
                    closest_node = node
            return closest_node

        def join_centrelines(centreline_0, centreline_1):
        #================================================
            # The centrelines should either have a node in common
            # or there should be a centreline connecting them
            nodes_0 = self.__edges_by_id[centreline_0][0:2]
            nodes_1 = self.__edges_by_id[centreline_1][0:2]
            if nodes_0[0] in nodes_1 or nodes_0[1] in nodes_1:
                return {'centrelines': set()}
            result = {}
            centrelines = set()
            for n0 in nodes_0:
                for n1 in nodes_1:
                    if (n0, n1) in self.__centreline_graph.edges:
                        for key in self.__centreline_graph[n0][n1]:
                            centrelines.add(self.__centreline_graph.edges[n0, n1, key]['id'])
            if len(centrelines) > 1:
                result['warning'] = f'Centerlines {centreline_0} and {centreline_1} have everal centrelines connecting them: {centrelines}'
            elif len(centrelines) == 0:
                result['warning'] = f'No path between centrelines {centreline_0} and {centreline_1}'
            result['centrelines'] = centrelines
            return result

        def join_centreline_to_node(centreline, node_dict):
        #==================================================
            # A centreline and feature node. Either the feature
            # node is one of the centreline's nodes or there
            # should be a centreline connecting them
            centreline_nodes = self.__edges_by_id[centreline][0:2]
            result = {}
            centrelines = set()
            node = node_dict['feature-id']
            if node not in centreline_nodes:
                for n0 in centreline_nodes:
                    if (n0, node) in self.__centreline_graph.edges:
                        for key in self.__centreline_graph[n0][node]:
                            centrelines.add(self.__centreline_graph.edges[n0, node, key]['id'])
                        node_dict['centreline-node'] = True
                        break
                if len(centrelines) > 1:
                    result['warning'] = f'Node {node} has several centrelines connecting it {centreline}: {centrelines}'
                elif len(centrelines) == 0:
                    if (not node_dict.get('terminal', False)
                    and node_dict.get('node', False)):
                        result['warning'] = f'Centreline {centreline} has no path to node {node}'
            result['centrelines'] = centrelines
            return result

        def join_feature_nodes(node_dict_0, node_dict_1):
        #================================================
            # Two feature nodes. There should be a centreline
            # connecting them.
            result = {}
            centrelines = set()
            node_0 = node_dict_0['feature-id']
            node_1 = node_dict_1['feature-id']
            if (node_0, node_1) in self.__centreline_graph.edges:
                for key in self.__centreline_graph[node_0][node_1]:
                    centrelines.add(self.__centreline_graph.edges[node_0, node_1, key]['id'])
                node_dict_0['centreline-node'] = True
                node_dict_1['centreline-node'] = True
            if len(centrelines) > 1:
                result['warning'] = f'Nodes {node_0} and {node_1} have several centrelines connecting them: {centrelines}'
            elif len(centrelines) == 0:
                if (not node_dict_0.get('terminal', False)
                and not node_dict_1.get('terminal', False)
                and (node_dict_0.get('node', False) or node_dict_1.get('node', False))):
                    result['warning'] = f'No centreline path between nodes {node_0} and {node_1}'
            result['centrelines'] = centrelines
            return result

        def centrelines_from_node_dicts(dict_0, dict_1):
        #===============================================
            centrelines = set()
            result = {}
            if centreline_0 := dict_0.get('centreline'):
                centrelines.add(centreline_0)
                if centreline_1 := dict_1.get('centreline'):
                    result = join_centrelines(centreline_0, centreline_1)
                    centrelines.add(centreline_1)
                elif dict_1.get('feature-id'):
                    result = join_centreline_to_node(centreline_0, dict_1)
            elif dict_0.get('feature-id'):
                if centreline_1 := dict_1.get('centreline'):
                    centrelines.add(centreline_1)
                    result = join_centreline_to_node(centreline_1, dict_0)
                elif dict_1.get('feature-id'):
                    result = join_feature_nodes(dict_0, dict_1)
            result['centrelines'].update(centrelines)
            return result

        def get_closest_centreline_node(G, terminal_node, seen_terminals):
        #=================================================================
            organ_terminals = set()
            terminal_dict = G.nodes[terminal_node]
            if (organ_layer := terminal_dict.get('organ')) is not None:
                terminal_feature = terminal_dict.get('feature-id')
                organ_terminals.add(terminal_feature)
                seen_edges = set()
                connected_nodes = [terminal_node]
                while len(connected_nodes):
                    nodes = connected_nodes
                    connected_nodes = []
                    for start in nodes:
                        for end, edge_data in G[start].items():
                            for key in edge_data:
                                edge = (start, end, key)
                                if edge not in seen_edges:
                                    seen_edges.add(edge)
                                    node_dicts = G.edges[edge].get('path-features', []) + [G.nodes[end]]
                                    for node_dict in node_dicts:
                                        feature_id = node_dict.get('feature-id')
                                        if organ_layer == node_dict.get('organ'):
                                            if node_dict.get('terminal', False):
                                                organ_terminals.add(feature_id)
                                                terminal_feature = feature_id
                                                seen_terminals.add(end)    # A path feature node can't be a terminal
                                        if not node_dict.get('terminal', False) and node_dict.get('centreline-node', False):
                                            closest_node = feature_id
                                        elif (centreline := node_dict.get('centreline')) is not None:
                                            closest_node = closest_node_to(terminal_feature, centreline)
                                            if (closest := node_dict.get('closest-node')) is None:
                                                node_dict['closest-node'] = closest_node
                                            elif closest != closest_node:
                                                node_dict['warning'] = f'Node {feature_id} is close to both {closest_node} and {closest}'
                                        else:
                                            closest_node = node_dict.get('closest-node')
                                        if closest_node is not None:
                                            return (closest_node, organ_terminals)
                                    if organ_layer == node_dicts[-1].get('organ'):
                                        connected_nodes.append(end)
            return(None, organ_terminals)

        def valid_feature_in_node_dicts(dicts, start_index):
        #===================================================
            while start_index < len(dicts) and dicts[start_index].get('feature-id') is None:
                start_index += 1
            return start_index

        def log_errors(path_id, G):
        #==========================
            for node in G:
                if (warning := G.nodes[node].get('warning')) is not None:
                    log.warning(f'{path_id}: {warning}')
            for (_, _, edge_dict) in G.edges(data=True):
                for feature in edge_dict['path-features']:
                    if (warning := feature.get('warning')) is not None:
                        log.warning(f'{path_id}: {warning}')

        # Connectivity graph must be undirected
        connectivity = path.connectivity
        if isinstance(connectivity, nx.DiGraph):
            connectivity = connectivity.to_undirected()

        # The resulting route graph
        route_graph = nx.MultiGraph()

        # Process each connected sub-graph
        for components in nx.connected_components(connectivity):

            # Simplify connectivity by collapsing consecutive degree 2 nodes
            # into a single edge, returning a nx.MultiDiGraph. Each node has
            # a ``degree`` attribute with the node's degree in the source graph
            G = graph_utils.smooth_edges(connectivity.subgraph(components), path_attribute='path-nodes')

            # Find feature corresponding to each connectivity node and identify terminal nodes
            for node, node_dict in G.nodes(data=True):
                node_dict.update(node_dict_for_feature(node))
                if G.degree(node) == 1:
                    node_dict['terminal'] = True

            path_edges = {}
            # And find feature for each node on edge's smoothed path
            for (node_0, node_1, key, edge_dict) in G.edges(keys=True, data=True):
                # ``path-features`` is a list parallel with ``path-nodes``
                edge_dict['path-features'] = [node_dict_for_feature(node) for node in edge_dict['path-nodes']]
                path_edges[(node_0, node_1, key)] = edge_dict['path-features']  # we will add the reverse edges after iterating over all edges
                if len(edge_dict['path-features']):
                    node_dicts = [G.nodes[node_0]]
                    node_dicts.extend(edge_dict['path-features'])
                    node_dicts.append(G.nodes[node_1])

                    # split into segments delimited by path features that map to a centreline
                    segment_boundaries = [0]
                    segment_boundaries.extend([n+1 for (n, path_feature) in enumerate(node_dicts[1:-1])
                                                        if path_feature.get('centreline') is not None])
                    segment_boundaries.append(len(node_dicts) - 1)
                    for start, end in pairwise(segment_boundaries):
                        if (end - start) > 1:
                            for dict_0, dict_1 in pairwise(node_dicts[start:end]):
                                # Can have centreline/feature and feature/feature
                                # but not centreline/centreline
                                joined_features = None
                                if (centreline := dict_0.get('centreline')) and dict_1.get('feature-id'):
                                    feature_dict = dict_1
                                    joined_features = join_centreline_to_node(centreline, dict_1)
                                elif (centreline := dict_1.get('centreline')) and dict_0.get('feature-id'):
                                    feature_dict = dict_0
                                    joined_features = join_centreline_to_node(centreline, dict_0)
                                elif dict_0.get('feature-id') and dict_1.get('feature-id'):
                                    feature_dict = dict_0
                                    joined_features = join_feature_nodes(dict_0, dict_1)
                                if joined_features is not None and len(centrelines := joined_features['centrelines']):
                                    feature_dict['centreline'] = centrelines.pop()

                    segment_boundaries = [0]
                    segment_boundaries.extend([n+1 for (n, path_feature) in enumerate(node_dicts[1:-1])
                                                        if path_feature.get('centreline') is not None])
                    segment_boundaries.append(len(node_dicts) - 1)
                    for start, end in pairwise(segment_boundaries):
                        if (end - start) > 1:
                            centreline = find_centreline_from_containers(node_dicts[start],
                                                                         [feature_dict.get('feature-id')
                                                                            for feature_dict in node_dicts[start+1:end]
                                                                                if feature_dict.get('feature-id') is not None],
                                                                          node_dicts[end])
                            for feature_dict in node_dicts[start+1:end]:
                                if feature_dict.get('feature-id') is not None:
                                    feature_dict['centreline'] = centreline

            # Add reverse edges to the graph so we can traverse nodes in either direction
            for edge, path_features in path_edges.items():
                key = G.add_edge(edge[1], edge[0])
                G.edges[(edge[1], edge[0], key)]['path-features'] = list(reversed(path_features))

            seen_edges = set()
            centreline_set = set()
            # Construct and extract centrelines from the features we've found, preserving
            # local connectedness
            for start_node, start_dict in G.nodes(data=True):
                for end_node, edge_data in G[start_node].items():
                    for key in edge_data:
                        edge = (start_node, end_node, key)
                        if edge not in seen_edges:
                            seen_edges.add(edge)
                            node_dicts = [start_dict]
                            node_dicts.extend(G.edges[edge].get('path-features', []))
                            node_dicts.append(G.nodes[end_node])
                            index = valid_feature_in_node_dicts(node_dicts, 0)
                            while index < (len(node_dicts) - 1):
                                next_index = valid_feature_in_node_dicts(node_dicts, index+1)
                                if next_index < len(node_dicts):
                                    join_result = centrelines_from_node_dicts(node_dicts[index], node_dicts[next_index])
                                    centreline_set.update(join_result['centrelines'])
                                    if (warning := join_result.get('warning')) is not None:
                                        log.warning(f'{path.id}: {warning}')
                                        for i in range(index, next_index):
                                            if (warning := node_dicts[i].get('warning')) is not None:
                                                log.info(f'{path.id}: {warning}')
                                index = next_index

            if len(centreline_set) == 0:
                log.warning(f'{path.id}: No centrelines found...')
                log_errors(path.id, G)
            elif path.trace:
                log.info(f'{path.id}: Centrelines {sorted(centreline_set)}')

            centreline_nodes: set[str] = set()
            for centreline in centreline_set:
                centreline_nodes.update(self.__edges_by_id[centreline][0:2])

            node_terminals: dict[str, set[str]] = defaultdict(set)   # node --> terminals
            seen_terminals: set[str] = set()
            # Find nearest centreline node to each terminal node
            for terminal_node, node_dict in G.nodes(data=True):
                if (node_dict.get('terminal', False)
                and terminal_node not in seen_terminals
                and node_dict.get('feature-id') not in centreline_nodes):
                    (upstream_node, terminals) = get_closest_centreline_node(G, terminal_node, seen_terminals)
                    if upstream_node is not None:
                        node_terminals[upstream_node].update(terminals)

            # Construct the route graph from the centrelines that make it up
            route_paths = nx.MultiGraph()
            for centreline in centreline_set:
                node_0, node_1, key = self.__edges_by_id[centreline]
                route_paths.add_node(node_0, **self.__centreline_graph.nodes[node_0])
                route_paths.add_node(node_1, **self.__centreline_graph.nodes[node_1])
                route_paths.add_edge(node_0, node_1, **self.__centreline_graph.edges[node_0, node_1, key])

            # Add edges to terminal nodes that aren't part of the centreline network
            for end_node, terminal_nodes in node_terminals.items():
                #assert route_paths.nodes[end_node]['degree'] == 1  ## May not be true...
                # This will be used when drawing path to terminal node
                if end_node in route_paths:
                    route_paths.nodes[end_node]['direction'] = list(route_paths.nodes[end_node]['edge-direction'].items())[0][1]
                    for terminal_id in terminal_nodes:
                        route_paths.add_edge(end_node, terminal_id, type='terminal')
                        node_dict = route_paths.nodes[terminal_id]
                        node_dict.update(self.__node_properties_from_feature(terminal_id))

            # Add paths and nodes from connected connectivity sub-graph to result
            route_graph.add_nodes_from(route_paths.nodes(data=True))
            edge_key_count: dict[tuple[str, str], int] = defaultdict(int)
            for node_0, node_1, key in route_paths.edges(keys=True):
                edge_key_count[(node_0, node_1)] += 1
            for node_0, node_1, edge_dict in route_paths.edges(data=True):
                if edge_key_count[(node_0, node_1)] == 1 or edge_dict.get('id') in centreline_set:
                    route_graph.add_edge(node_0, node_1, **edge_dict)
                    edge_key_count[(node_0, node_1)] = 0

            for (node_0, node_1), count in edge_key_count.items():
                if count:
                    log.warning(f'{path.id}: Multiple edges between nodes {node_0} and {node_1}')

        return route_graph

#===============================================================================
