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
from typing import TYPE_CHECKING, Optional


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

def expand_centreline_graph(graph: nx.MultiGraph) -> nx.Graph:
#=============================================================
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
    map_feature: Optional[Feature] = None
    feature_id: str = field(init=False)
    ftu_id: str = field(init=False)
    properties: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.feature_id = self.full_id.rsplit('/', 1)[-1]
        self.ftu_id = self.full_id.rsplit('/', 2)[-2] if '/' in self.full_id else None

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

        self.__centreline_nodes: dict[str, list[NetworkNode]] = defaultdict(list)  #! Centreline id --> [Network nodes]
        self.__nodes_by_ftu: dict[str, list[NetworkNode]] = defaultdict(list)      #! FTU id id --> {Network nodes}
        self.__containers_by_centreline = {}                #! Centreline id --> set of features that centreline is contained in
        self.__models_to_id: dict[str, str] = {}            #! Ontological term --> centreline id
        self.__feature_ids: set[str] = set()
        self.__full_ids: set[str] = set()                   #! A ``full id`` is a slash-separated list of feature ids
        self.__feature_map = None  #! Assigned after ``maker`` has processed sources
        self.__missing_identifiers: set[str] = set()

        # The following are assigned once we have feature geometry
        self.__centreline_graph: nx.MultiGraph = None                               #! Edges are centreline segments between intermediate nodes.
        self.__containers_by_segment: dict[str, set[str]] = defaultdict(set)        #! Segment id --> set of features that segment is contained in
        self.__expanded_centreline_graph: nx.Graph = None                           #! Expanded version of centreline graph
        self.__segment_edge_by_segment: dict[str, tuple] = {}                       #! Segment id --> segment edge
        self.__segment_ids_by_centreline: dict[str, list[str]] = defaultdict(list)  #! Centreline id --> segment ids of the centreline

        # Track how nodes are associated with centrelines
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
                self.__add_feature(centreline_id)
                if (models := centreline.get('models')) is not None:
                    if models in self.__models_to_id:
                        log.warning(f'Centrelines `{centreline_id}` and `{self.__models_to_id[models]}` both model {models}')
                    else:
                        self.__models_to_id[models] = centreline_id
                        # If we have ``external_properties`` without ``models`` annotation for the centreline then set it
                        if external_properties is not None:
                            if external_properties.get_property(centreline_id, 'models') is None:
                                external_properties.set_property(centreline_id, 'models', models)
                            if (nerve_id := external_properties.nerve_ids_by_model.get(models)) is not None:
                                external_properties.set_property(centreline_id, 'nerve', nerve_id)
                connected_nodes = centreline.get('connects', [])
                if len(connected_nodes) < 2:
                    log.error(f'Centreline {centreline_id} in network {self.__id} has too few nodes')
                else:
                    self.__add_feature(connected_nodes[0])
                    self.__add_feature(connected_nodes[-1])

                    for node_id in connected_nodes:
                        network_node = NetworkNode(node_id)
                        self.__centreline_nodes[centreline_id].append(network_node)
                        if (ftu_id := network_node.ftu_id) is not None:
                            if network_node not in self.__nodes_by_ftu[ftu_id]:
                                self.__nodes_by_ftu[ftu_id].append(network_node)

                    self.__containers_by_centreline[centreline_id] = set(centreline.get('contained-in', []))
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
                if node.ftu_id is None and node.feature_id in self.__nodes_by_ftu:
                    if node not in self.__nodes_by_ftu[node.feature_id]:
                        self.__nodes_by_ftu[node.feature_id].append(node)

    @property
    def id(self):
        return self.__id

    def __add_feature(self, full_id):
    #=================================
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
        if feature_id not in self.__missing_identifiers:
            if (feature := self.__feature_map.get_feature(feature_id)) is not None:
                return feature
            log.error('Cannot find network feature: {}'.format(feature_id))
            self.__missing_identifiers.add(feature_id)
        return None

    def __set_properties_from_feature(self, feature_id):
    #===================================================
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
        def set_default_node_properties(network_node):
            feature_id = network_node.feature_id
            if feature_id not in self.__centreline_graph:
                self.__centreline_graph.add_node(feature_id, network_node=network_node, **network_node.properties)
                # Direction of a path at the node boundary, going towards the centre (radians)
                self.__centreline_graph.nodes[feature_id]['edge-direction'] = {}
                # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
                self.__centreline_graph.nodes[feature_id]['edge-node-angle'] = {}

        def split_path_and_update_centreline_graph(network_node_0, network_node_1, key, bz_path, path_reversed):
            # Split Bezier path at ``node_1``, assigning the front portion to the
            # ``(node_0, node_1)`` edge and return the remainder.

            if not path_reversed:
                (start_node, end_node) = (network_node_0, network_node_1)
            else:
                (start_node, end_node) = (network_node_1, network_node_0)
            (start_node_id, end_node_id) = (start_node.feature_id, end_node.feature_id)
            edge_dict = self.__centreline_graph.edges[start_node_id, end_node_id, key]

            (cl_path, bz_path) = split_bezier_path_at_point(bz_path, end_node.centre)

            # Set the end of the segment's centreline to the center of the end node for actual ``.node`` features
            if end_node.properties.get('node', False):
                set_bezier_path_end_to_point(cl_path, end_node.centre)

            segments = cl_path.asSegments()
            edge_dict['bezier-path'] = cl_path
            edge_dict['bezier-segments'] = segments
            edge_dict['geometry'] = bezier_to_linestring(cl_path) ##, num_points=50)
            edge_dict['reversed'] = path_reversed
            edge_dict['length'] = cl_path.length  # Use in finding shortest route

            segment_id = edge_dict['segment']

            edge_dict['start-node'] = start_node_id
            # Direction of a path at the node boundary, going towards the centre (radians)
            self.__centreline_graph.nodes[start_node_id]['edge-direction'][segment_id] = segments[0].startAngle + math.pi
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[start_node_id]['edge-node-angle'][end_node_id] = (
                                    (segments[0].pointAtTime(0.0) - start_node.centre).angle)

            edge_dict['end-node'] = end_node_id
            # Direction of a path at the node boundary, going towards the centre (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-direction'][segment_id] = segments[-1].endAngle
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-node-angle'][start_node_id] = (
                                    # why segments[0].pointAtTime(0.0) ??
                                    (segments[-1].pointAtTime(1.0) - end_node.centre).angle)

            return bz_path

        # Initialise
        self.__centreline_graph = nx.MultiGraph()           #! Can have multiple paths between nodes which will be contained in different features
        self.__containers_by_segment = defaultdict(set)     #! Segment id --> set of features that segment is contained in
        self.__segment_edge_by_segment = {}
        self.__segment_ids_by_centreline = defaultdict(list)

        segment_edge_ids_by_centreline = defaultdict(list)

        for centreline_id, network_nodes in self.__centreline_nodes.items():
            if (self.__map_feature(network_nodes[0].feature_id) is None
             or self.__map_feature(network_nodes[-1].feature_id) is None):
                log.error(f'Centreline {centreline_id} ignored: end nodes are not on map')
                continue
            if (centreline_feature := self.__map_feature(centreline_id)) is None:
                log.warning(f'Centreline {centreline_id} ignored: not on map')
                continue

            # Set network node properties
            for network_node in network_nodes:
                network_node.set_properties_from_feature(self.__map_feature(network_node.feature_id))

            bz_path = BezierPath.fromSegments(centreline_feature.property('bezier-segments'))

            node_0_centre = network_nodes[0].centre
            path_reversed = (node_0_centre.distanceFrom(bz_path.pointAtTime(0.0)) >
                             node_0_centre.distanceFrom(bz_path.pointAtTime(1.0)))

            # Construct the segmented centreline graph
            seg_no = 0
            start_index = 0
            while start_index < len(network_nodes) - 1:
                seg_no += 1
                start_node = network_nodes[start_index]
                # Set the start of the centreline to the center of next start node for actual ``.node`` features
                if start_node.properties.get('node', False):
                    set_bezier_path_end_to_point(bz_path, start_node.centre)

                end_index = start_index + 1
                # Loop must terminate as network_nodes[-1] is a map feature from above
                end_node = network_nodes[end_index]
                while end_node.map_feature is None or end_node.intermediate:
                    end_node.intermediate = True  # Nodes without a feature become intermediate nodes
                    end_index += 1
                    end_node = network_nodes[end_index]
                if start_index > 0 or end_index < (len(network_nodes) - 1):
                    segment_id = f'{centreline_id}/{seg_no}'
                else:
                    segment_id = centreline_id

                # Initialise the graph's node data before creating an edge between them
                set_default_node_properties(start_node)
                set_default_node_properties(end_node)

                # Add an edge to the segmented centreline graph
                edge_feature_ids = (start_node.feature_id, end_node.feature_id)
                key = self.__centreline_graph.add_edge(*edge_feature_ids, id=edge_feature_ids,
                                                       centreline=centreline_id, segment=segment_id,
                                                       network_nodes=network_nodes[start_index:end_index+1])
                edge_id = (*edge_feature_ids, key)

                # Split Bezier path at segment boundary and return the remainder.
                # NB. this also sets the end of the segment's centerline to the centre if the end node
                bz_path = split_path_and_update_centreline_graph(start_node, end_node, key, bz_path, path_reversed)

                segment_edge_ids_by_centreline[centreline_id].append(edge_id)
                self.__segment_edge_by_segment[segment_id] = edge_id
                self.__segment_ids_by_centreline[centreline_id].append(segment_id)
                start_index = end_index

        # Set the ``degree`` property now that we have the complete graph
        for feature_id, node_dict in self.__centreline_graph.nodes(data=True):
            node_dict['degree'] = self.__centreline_graph.degree(feature_id)

        for node_0, node_1, edge_dict in self.__centreline_graph.edges(data=True):
            bz_path = edge_dict['bezier-path']
            path_reversed = edge_dict['reversed']
            segment_id = edge_dict['segment']

            # Set intermediate node centres to their closest point on the centreline's path
            last_t = 0.0 if not path_reversed else 1.0
            for network_node in edge_dict['network_nodes'][1:-1]:
                t = closest_time_distance(bz_path, network_node.centre)[0]
                if (not path_reversed and t <= last_t
                 or     path_reversed and t >= last_t):
                    log.error(f'Centreline {segment_id} nodes are out of sequence...')
                else:
                    network_node.centre = bz_path.pointAtTime(t)
                last_t = t

        # Map container features to their centreline segments
        for centreline_id, feature_ids in self.__containers_by_centreline.items():
            if len(segment_edge_ids := segment_edge_ids_by_centreline[centreline_id]) == 1:
                segment_id = self.__centreline_graph.edges[segment_edge_ids[0]]['segment']
                # assert centreline_id == segment_id
                self.__containers_by_segment[segment_id] = feature_ids
            else:
                for feature_id in feature_ids:
                    # Find segment for the container node
                    feature = self.__map_feature(feature_id)
                    if feature is not None:
                        node_geometry = feature.geometry
                        longest_match = 0
                        longest_segment_edge = None
                        for segment_edge_id in segment_edge_ids:
                            segment_line_geometry = self.__centreline_graph.edges[segment_edge_id]['geometry']
                            intersection = node_geometry.intersection(segment_line_geometry.buffer(20))
                            if not intersection.is_empty:
                                if intersection.length > longest_match:
                                    longest_segment_edge = segment_edge_id

                        if longest_segment_edge is not None:
                            segment_id = self.__centreline_graph.edges[longest_segment_edge]['segment']
                            self.__containers_by_segment[segment_id].add(feature_id)

        self.__expanded_centreline_graph = expand_centreline_graph(self.__centreline_graph)

    def route_graph_from_path(self, path: Path):
    #===========================================
        return self.__route_graph_from_connectivity(path)

    def layout(self, route_graphs: nx.Graph) -> dict:
    #================================================
        path_router = PathRouter()
        for path_id, route_graph in route_graphs.items():
            path_router.add_path(path_id, route_graph)
        # Layout the paths and return the resulting routes
        return path_router.layout()

    def __node_dict_for_feature(self, connectivity_node):
    #====================================================
        result = {
            'node': connectivity_node
        }
        # Check if we can directly identify the centreline
        if (centreline_id := self.__models_to_id.get(connectivity_node[0])) is not None:
            if len(segment_ids := self.__segment_ids_by_centreline[centreline_id]) > 1:
                log.warning(f'Connectivity node {full_node_name(*connectivity_node)} has found segmented centreline: {centreline_id}')
            else:
                segment_id = segment_ids[0]
                result['segment-id'] = segment_id
                if segment_id in self.__expanded_centreline_graph:
                    result['cl-node'] = segment_id
                else:
                    log.error(f'Centreline segment {segment_id} missing from expanded graph...')
                if ((feature := self.__map_feature(centreline_id)) is not None
                and (nerve_id := feature.properties.get('nerve')) is not None):
                    result['nerve'] = nerve_id
        else:
            feature_id = None
            features = self.__feature_map.find_path_features_by_anatomical_id(*connectivity_node)
            feature_ids = set(f.id for f in features if f.id is not None)
            if len(feature_ids) > 1:
                # We've found multiple features on the flatmap, so restrict them to the set of centreline nodes
                # to see if we can find a unique feature
                connected_features = feature_ids.intersection(self.__centreline_graph)
                if len(connected_features) > 1:
                    log.error(f'Node {full_node_name(*connectivity_node)} has too many connected features: {feature_ids}')
                elif len(connected_features):  # len(connected_features) == 1
                    feature_id = connected_features.pop()
                else:                          # len(connected_features) == 0
                    # Multiple terminal nodes -- simply choose one
                    log.warning(f'Node {full_node_name(*connectivity_node)} has multiple terminal features: {feature_ids}')
                    feature_id = feature_ids.pop()
            elif len(feature_ids) == 1:
                feature_id = feature_ids.pop()
            if feature_id is not None:
                result['feature-id'] = feature_id
                if feature_id in self.__expanded_centreline_graph:
                    result['cl-node'] = feature_id
                if len(nodes := self.__nodes_by_ftu.get(feature_id, [])) > 0:
                    result['ftu-connections'] = [node.feature_id for node in nodes]
                    result['ftu'] = connectivity_node[0]
                elif len(connectivity_node[1]):
                    result['ftu'] = connectivity_node[1][-1]  # Unused at present but useful for FC integration
            elif connectivity_node not in self.__missing_identifiers:
                log.warning(f'Cannot find feature for connectivity node {connectivity_node} ({full_node_name(*connectivity_node)})')
                self.__missing_identifiers.add(connectivity_node)

        return result

    def __segment_from_containers(self, start_dict, features, end_dict):
    #===================================================================
        def nodes_from_dict(node_dict):
            nodes = set()
            if (segment_id := node_dict.get('segment-id')) is not None:
                nodes.update(self.__segment_edge_by_segment[segment_id][0:2])
            elif (feature_id := node_dict.get('feature-id')) is not None:
                nodes.add(feature_id)
            return nodes

        end_nodes = nodes_from_dict(start_dict)
        end_nodes.update(nodes_from_dict(end_dict))
        max_score = 0
        best_segment_id = None
        for segment_id, containing_features in self.__containers_by_segment.items():
            if len(end_nodes):
                edge_nodes = self.__segment_edge_by_segment[segment_id][0:2]
                node_score = len(end_nodes.intersection(edge_nodes))/len(end_nodes)
            else:
                node_score = 0
            if common := len(containing_features.intersection(features)):
                # Jaccard index
                jaccard_index = common/(len(features) + len(containing_features) - common)
                score = node_score + jaccard_index
                if score > max_score:
                    max_score = score
                    best_segment_id = segment_id
        return best_segment_id

    def __join_segment_to_node(self, segment_id, node_dict):
    #=======================================================
        # A centreline and feature node. Either the feature
        # node is one of the centreline's nodes or there
        # should be a centreline connecting them
        segment_nodes = self.__segment_edge_by_segment[segment_id][0:2]
        result = {}
        segments = set()
        feature_id = node_dict['feature-id']
        if feature_id not in segment_nodes:
            for n0 in segment_nodes:
                if (n0, feature_id) in self.__centreline_graph.edges:
                    for key in self.__centreline_graph[n0][feature_id]:
                        segments.add(self.__centreline_graph.edges[n0, feature_id, key]['segment'])
                    node_dict['segment-node'] = True
                    break
            if len(segments) > 1:
                result['warning'] = f'Node {feature_id} has several centreline segments connecting it {segment_id}: {segments}'
            elif len(segments) == 0:
                if (not node_dict.get('terminal', False)
                and node_dict.get('node', False)):
                    result['warning'] = f'Centreline segment {segment_id} has no path to node {feature_id}'
        result['segments'] = segments
        return result

    def __join_segments(self, segment_0, segment_1):
    #===============================================
        # The centreline segments should either have a node in common
        # or there should be a segment connecting them
        nodes_0 = self.__segment_edge_by_segment[segment_0][0:2]
        nodes_1 = self.__segment_edge_by_segment[segment_1][0:2]
        if nodes_0[0] in nodes_1 or nodes_0[1] in nodes_1:
            return {'segments': set()}
        result = {}
        segments = set()
        for n0 in nodes_0:
            for n1 in nodes_1:
                if (n0, n1) in self.__centreline_graph.edges:
                    for key in self.__centreline_graph[n0][n1]:
                        segments.add(self.__centreline_graph.edges[n0, n1, key]['segment'])
        if len(segments) > 1:
            result['warning'] = f'Centerline segments {segment_0} and {segment_1} have several segments connecting them: {segments}'
        elif len(segments) == 0:
            result['warning'] = f'No path between centreline segments {segment_0} and {segment_1}'
        result['segments'] = segments
        return result

    def __join_feature_nodes(self, node_dict_0, node_dict_1):
    #========================================================
        # Two feature nodes. There should be a centreline
        # connecting them.
        result = {}
        segments = set()
        node_0 = node_dict_0.get('feature-id')
        node_1 = node_dict_1.get('feature-id')
        if node_0 is None or node_1 is None:
            return {'segments': segments}
        if (node_0, node_1) in self.__centreline_graph.edges:
            for key in self.__centreline_graph[node_0][node_1]:
                segments.add(self.__centreline_graph.edges[node_0, node_1, key]['segment'])
            node_dict_0['segment-node'] = True
            node_dict_1['segment-node'] = True
        if len(segments) > 1:
            result['warning'] = f'Nodes {node_0} and {node_1} have several centreline segments connecting them: {segments}'
        elif len(segments) == 0:
            if (not node_dict_0.get('terminal', False)
            and not node_dict_1.get('terminal', False)
            and ((ftu := node_dict_0.get('ftu')) != node_dict_1.get('ftu') or ftu is None)
            and (node_dict_0.get('node', False) or node_dict_1.get('node', False))):
                result['warning'] = f'No centreline segment between nodes {node_0} and {node_1}'
        result['segments'] = segments
        return result

    def __segments_from_node_dicts(self, dict_0, dict_1):
    #====================================================
        segments = set()
        result = {}
        if segment_0 := dict_0.get('segment-id'):
            segments.add(segment_0)
            if segment_1 := dict_1.get('segment-id'):
                result = self.__join_segments(segment_0, segment_1)
                segments.add(segment_1)
            elif dict_1.get('feature-id'):
                result = self.__join_segment_to_node(segment_0, dict_1)
        elif dict_0.get('feature-id'):
            if segment_1 := dict_1.get('segment-id'):
                segments.add(segment_1)
                result = self.__join_segment_to_node(segment_1, dict_0)
            elif dict_1.get('feature-id'):
                result = self.__join_feature_nodes(dict_0, dict_1)
        if 'segments' in result:
            result['segments'].update(segments)
        else:
            result['segments'] = segments
        return result

    def __closest_node_to(self, feature_node, segment_id):
    #=====================================================
        # Find segment's node that is closest to ``feature_node``.
        feature = self.__feature_map.get_feature(feature_node)
        feature_centre = feature.geometry.centroid
        closest_node = None
        closest_distance = -1
        for node in self.__segment_edge_by_segment[segment_id][0:2]:
            node_centre = self.__centreline_graph.nodes[node]['geometry'].centroid
            distance = feature_centre.distance(node_centre)
            if closest_node is None or distance < closest_distance:
                closest_distance = distance
                closest_node = node
        return closest_node

    def __terminal_graph(self, G: nx.MultiDiGraph, start_node, seen_terminals) -> nx.graph:
    #======================================================================================
        # Returns a graph of terminal features that are connected to the
        # ``start_node``'s feature, with those features connected to the
        # centreline network having an ``upstream`` attribute, giving
        # the end feature of the centreline segment.

        terminal_network = nx.Graph()
        start_dict = G.nodes[start_node]
        if not start_dict.get('terminal', False):
            return terminal_network

        ftu_layer = start_dict.get('ftu')
        last_feature = start_dict.get('feature-id')

        def walk_paths_from_node(start_node, start_dict):
            nonlocal last_feature

            if start_node in seen_terminals:
                return
            if (start_feature := start_dict.get('feature-id')) is not None:
                if len(ftu_connections := start_dict.get('ftu-connections', [])) == 0:
                    # Not a connection to the c/l network so node is local to the FTU
                    terminal_network.add_node(start_feature)
                    seen_terminals.add(start_node)

                for next_node, key_dicts in G[start_node].items():
                    next_dict = G.nodes[next_node]
                    if len(ftu_connections):
                        # We have a connection to c/l network
                        if ftu_layer == next_dict.get('ftu'):
                            # Don't link to other terminals (besides how we've got to the connector)
                            continue
                    else:
                       last_feature = start_feature
                    for nk, (key, edge_dict) in enumerate(key_dicts.items()):
                        node_dicts = edge_dict.get('edge-features', []) + [next_dict]
                        # Walk along an edge path
                        for node_dict in node_dicts:
                            feature_id = node_dict.get('feature-id')
                            if (segment_id := node_dict.get('segment-id')) is not None:
                                # We've reached a node that represents a centreline segment so
                                # see which end of it is geometrically closest to the terminal
                                upstream_node = self.__closest_node_to(last_feature, segment_id)
                                node_dict['upstream-node'] = upstream_node
                            elif feature_id is not None:
                                if (upstream_node := node_dict.get('upstream-node')) is not None:
                                    pass
                                elif node_dict.get('segment-node', False):
                                    upstream_node = feature_id
                                elif len(node_dict.get('ftu-connections', [])) == 0:
                                    terminal_network.add_edge(last_feature, feature_id)
                                    last_feature = feature_id
                            else:
                                upstream_node = None
                            if upstream_node is not None and upstream_node != last_feature:
                                if 'upstream' in terminal_network.nodes[last_feature]:
                                    terminal_network.nodes[last_feature]['upstream'].add(upstream_node)
                                else:
                                    terminal_network.nodes[last_feature]['upstream'] = {upstream_node}
                                break

                    if not next_dict.get('segment-node', False):
                        walk_paths_from_node(next_node, next_dict)

        walk_paths_from_node(start_node, start_dict)
        return terminal_network

    def __route_graph_from_connectivity(self, path: Path, debug=False) -> tuple[nx.Graph, nx.Graph]:
    #===============================================================================================
        connectivity_graph = path.connectivity
        if path.trace:
            log.info(f'{path.id}: Edges {connectivity_graph.edges}')

        # Find feature corresponding to each connectivity node and identify
        # terminal nodes that are not part of the centreline network

        path_nerve_ids = set()
        for node, node_dict in connectivity_graph.nodes(data=True):
            node_dict.update(self.__node_dict_for_feature(node))
            node_dict['terminal'] = (node_dict.get('cl-node') is None
                                 and connectivity_graph.degree(node) == 1)
            if (nerve_id := node_dict.pop('nerve', None)) is not None:
                path_nerve_ids.add(nerve_id)

        for node, node_dict in connectivity_graph.nodes(data=True):
            if len(ftu_connections := node_dict.get('ftu-connections', [])):
                for cl_node in ftu_connections:
                    count = 0
                    for connected_node in nx.dfs_preorder_nodes(connectivity_graph, source=node, depth_limit=3):
                        if (connected_cl_node := connectivity_graph.nodes[connected_node].get('cl-node')) is not None:
                            if connected_cl_node != cl_node and nx.has_path(self.__expanded_centreline_graph, cl_node, connected_cl_node):
                                count += 1


        # Simplify connectivity by collapsing consecutive degree 2 nodes
        # into a single edge, returning a nx.MultiDiGraph. Each node has
        # a ``degree`` attribute with the node's degree in the source graph

        G = graph_utils.smooth_edges(connectivity_graph, edge_nodes_attribute='edge-nodes')

        path_edges = {}
        # And find feature for each node on edge's smoothed path
        for (node_0, node_1, key, edge_dict) in G.edges(keys=True, data=True):
            # ``edge-features`` is a list parallel with ``edge-nodes``
            edge_dict['edge-features'] = list(edge_dict['edge-nodes'].values())

            # We add the reverse edges after iterating over all edges
            path_edges[(node_0, node_1, key)] = edge_dict['edge-features']
            if len(edge_dict['edge-features']):
                node_dicts = [G.nodes[node_0]]
                node_dicts.extend(edge_dict['edge-features'])
                node_dicts.append(G.nodes[node_1])

                # Split smoothed edge into parts delimited by path features that map to a centreline segment
                part_boundaries = [0]
                part_boundaries.extend([n+1 for (n, path_feature) in enumerate(node_dicts[1:-1])
                                                    if path_feature.get('segment-id') is not None])
                part_boundaries.append(len(node_dicts) - 1)
                # First traversal of edge to see if feature nodes and segments can be joined
                for start, end in pairwise(part_boundaries):
                    if (end - start) > 1:
                        for dict_0, dict_1 in pairwise(node_dicts[start:end+1]):
                            # Can have segment/feature and feature/feature
                            # but not segment/segment
                            joined_features = None
                            if (segment_id := dict_0.get('segment-id')) and dict_1.get('feature-id'):
                                feature_dict = dict_1
                                joined_features = self.__join_segment_to_node(segment_id, dict_1)
                            elif (segment_id := dict_1.get('segment-id')) and dict_0.get('feature-id'):
                                feature_dict = dict_0
                                joined_features = self.__join_segment_to_node(segment_id, dict_0)
                            elif dict_0.get('feature-id') and dict_1.get('feature-id'):
                                feature_dict = dict_0
                                joined_features = self.__join_feature_nodes(dict_0, dict_1)
                            if joined_features is not None and len(segments := joined_features['segments']):
                                feature_dict['segment-id'] = segments.pop()

                # Resplit edge into parts as first traversal may have added segments
                part_boundaries = [0]
                part_boundaries.extend([n+1 for (n, path_feature) in enumerate(node_dicts[1:-1])
                                                    if path_feature.get('segment-id') is not None])
                part_boundaries.append(len(node_dicts) - 1)
                # Second traversal to find segments from containing features
                for start, end in pairwise(part_boundaries):
                    if (end - start) > 1:
                        segment_id = self.__segment_from_containers(node_dicts[start],
                                                                    [feature_dict.get('feature-id')
                                                                        for feature_dict in node_dicts[start+1:end]
                                                                            if feature_dict.get('feature-id') is not None],
                                                                    node_dicts[end])
                        for feature_dict in node_dicts[start+1:end]:
                            if feature_dict.get('feature-id') is not None:
                                feature_dict['segment-id'] = segment_id

        # Add reverse edges to the graph so we can traverse nodes in either direction
        for edge, path_features in path_edges.items():
            key = G.add_edge(edge[1], edge[0])
            G.edges[(edge[1], edge[0], key)].update({
                'edge-features': list(reversed(path_features)),
                'back-link': True
            })

        # Helper function used below
        def valid_feature_in_node_dicts(dicts, start_index):
            while (start_index < len(dicts)
               and dicts[start_index].get('cl-node') is None
               and dicts[start_index].get('feature-id') is None):
                start_index += 1
            return start_index

        # Helper function used below
        def log_errors(path_id, G):
            for node in G:
                if (warning := G.nodes[node].get('warning')) is not None:
                    log.warning(f'{path_id}: {warning}')
            for (_, _, edge_dict) in G.edges(data=True):
                for feature in edge_dict['edge-features']:
                    if (warning := feature.get('warning')) is not None:
                        log.warning(f'{path_id}: {warning}')

        seen_edges = set()
        segment_set = set()
        # Construct and extract centreline segments from the features we've found, preserving
        # local connectedness
        for start_node, start_dict in G.nodes(data=True):
            if (segment_id := start_dict.get('segment-id')) is not None:
                segment_set.add(segment_id)
            for end_node, edge_data in G[start_node].items():
                if edge_data[0].get('back-link'):
                    continue
                direct_link = self.__join_feature_nodes(start_dict, G.nodes[end_node])
                if len(direct_link['segments']):
                    segment_set.update(direct_link['segments'])
                    continue
                for key in edge_data:
                    edge = (start_node, end_node, key)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        node_dicts = [start_dict]
                        node_dicts.extend(G.edges[edge].get('edge-features', []))
                        node_dicts.append(G.nodes[end_node])
                        index = valid_feature_in_node_dicts(node_dicts, 0)
                        while index < (len(node_dicts) - 1):
                            next_index = valid_feature_in_node_dicts(node_dicts, index+1)
                            if next_index < len(node_dicts):
                                join_result = self.__segments_from_node_dicts(node_dicts[index], node_dicts[next_index])
                                segment_set.update(join_result['segments'])
                                if (warning := join_result.get('warning')) is not None:
                                    log.warning(f'{path.id}: {warning}')
                                    for i in range(index, next_index):
                                        if (warning := node_dicts[i].get('warning')) is not None:
                                            log.info(f'{path.id}: {warning}')
                            index = next_index

        if len(segment_set) == 0:
            log.warning(f'{path.id}: No centreline segments found...')
            log_errors(path.id, G)
        elif path.trace:
            log.info(f'{path.id}: Centreline segments {sorted(segment_set)}')

        joining_segments: set[str] = set()
        for seg_0, seg_1 in itertools.combinations(segment_set, 2):
            joins = self.__join_segments(seg_0, seg_1)['segments']
            if len(joins) and joins.isdisjoint(segment_set) and joins.isdisjoint(joining_segments):
                joining_segments.update(joins)
        segment_set.update(joining_segments)

        segment_nodes: set[str] = set()
        for segment_id in segment_set:
            segment_nodes.update(self.__segment_edge_by_segment[segment_id][0:2])

        terminal_graphs: dict[tuple, nx.Graph] = {}
        seen_terminals: set[tuple] = set()
        # Find nearest segment node to each terminal node
        for terminal_node, node_dict in G.nodes(data=True):
            if (node_dict.get('terminal', False)                      # A terminal node
            and terminal_node not in seen_terminals                   # not already processed
            and node_dict.get('feature-id') not in segment_nodes):    # and not at the end of a centreline
                terminal_graphs[terminal_node] = self.__terminal_graph(G, terminal_node, seen_terminals)

        # Construct the route graph from the centreline segments that make it up
        route_graph = nx.MultiGraph()
        for segment_id in segment_set:
            node_0, node_1, key = self.__segment_edge_by_segment[segment_id]
            route_graph.add_node(node_0, **self.__centreline_graph.nodes[node_0])
            route_graph.add_node(node_1, **self.__centreline_graph.nodes[node_1])
            route_graph.add_edge(node_0, node_1, **self.__centreline_graph.edges[node_0, node_1, key])

        # Add edges to terminal nodes that aren't part of the centreline network
        for terminal_graph in terminal_graphs.values():
            for terminal_id, upstream_nodes in terminal_graph.nodes(data='upstream'):
                # Each local node is a ``terminal`` node in the route graph
                route_graph.add_node(terminal_id, type='terminal')
                node_dict = route_graph.nodes[terminal_id]
                node_dict.update(self.__set_properties_from_feature(terminal_id))
                # Add links to upstream nodes in the c/l network
                if upstream_nodes is not None:
                    for upstream_node in upstream_nodes:
                        if upstream_node not in route_graph:
                            # This is the case when the upstream node's centreline hasn't been found
                            route_graph.add_node(upstream_node, **self.__centreline_graph.nodes[upstream_node])
                        route_graph.add_edge(upstream_node, terminal_id, type='upstream')
                        route_graph.nodes[upstream_node]['type'] = 'upstream'
                        route_graph.nodes[upstream_node]['direction'] = list(route_graph.nodes[upstream_node]['edge-direction'].items())[0][1]
            # Now add edges between local nodes in FTU
            for n0, n1 in terminal_graph.edges:
                if not route_graph.has_edge(n0, n1):
                    route_graph.add_edge(n0, n1, type='terminal')

        route_graph.graph['path-id'] = path.id
        route_graph.graph['path-type'] = path.path_type
        route_graph.graph['source'] = path.source
        route_graph.graph['nerve-features'] = [feature for nerve_id in path_nerve_ids
                                                if (feature := self.__map_feature(nerve_id)) is not None]
        if debug:
            return (route_graph, G, connectivity_graph, terminal_graphs)    # type: ignore
        else:
            return route_graph

#===============================================================================
