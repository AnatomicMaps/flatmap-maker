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
from typing import TYPE_CHECKING, Any, Optional


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

from mapmaker.flatmap.feature import AnatomicalNode, Feature, FeatureMap
from mapmaker.flatmap.feature import anatomical_node_name, full_node_name
from mapmaker.geometry.beziers import bezier_to_linestring, closest_time_distance
from mapmaker.geometry.beziers import coords_to_point
from mapmaker.geometry.beziers import split_bezier_path_at_point
from mapmaker.utils import log
import mapmaker.utils.graph as graph_utils

from .options import MIN_EDGE_JOIN_RADIUS
from .routedpath import IntermediateNode, PathRouter, RoutedPath

#===============================================================================

if TYPE_CHECKING:
    from mapmaker.properties import ExternalProperties
    from mapmaker.properties.pathways import Path

#===============================================================================

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
    ftu_id: Optional[str] = field(init=False)
    properties: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.feature_id = self.full_id.rsplit('/', 1)[-1]
        self.ftu_id = self.full_id.rsplit('/', 2)[-2] if '/' in self.full_id else None

    def __eq__(self, other):
        return self.feature_id == other.feature_id

    def __hash__(self, other):
        return hash(self.feature_id)

    @property
    def centre(self) -> BezierPoint:
        return self.properties.get('centre')

    @centre.setter
    def centre(self, value: BezierPoint):
        self.properties['centre'] = value

    @property
    def geometry(self):
        return self.properties.get('geometry')

    @property
    def radii(self) -> Optional[tuple[float, float]]:
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
    def __init__(self, network: dict, external_properties: Optional[ExternalProperties]=None):
        self.__id = network.get('id')
        self.__type = network.get('type')

        self.__centreline_nodes: dict[str, list[NetworkNode]] = defaultdict(list)  #! Centreline id --> [Network nodes]
        self.__nodes_by_ftu: dict[str, list[NetworkNode]] = defaultdict(list)      #! FTU id id --> {Network nodes}
        self.__containers_by_centreline = {}                #! Centreline id --> set of features that centreline is contained in
        self.__models_to_id: dict[str, set[str]] = defaultdict(set)                #! Ontological term --> centrelines
        self.__feature_ids: set[str] = set()
        self.__full_ids: set[str] = set()                   #! A ``full id`` is a slash-separated list of feature ids
        self.__feature_map: Optional[FeatureMap] = None  #! Assigned after ``maker`` has processed sources
        self.__missing_identifiers: set[AnatomicalNode] = set()

        # The following are assigned once we have feature geometry
        self.__centreline_graph: nx.MultiGraph = None                               #! Edges are centreline segments between intermediate nodes.
        self.__containers_by_segment: dict[str, set[str]] = defaultdict(set)        #! Segment id --> set of features that segment is contained in
        self.__expanded_centreline_graph: nx.Graph = None                           #! Expanded version of centreline graph
        self.__segment_edge_by_segment: dict[str, tuple[str, str, str]] = {}        #! Segment id --> segment edge
        self.__segment_ids_by_centreline: dict[str, list[str]] = defaultdict(list)  #! Centreline id --> segment ids of the centreline

        # Track how nodes are associated with centrelines
        end_nodes_to_centrelines = defaultdict(list)
        intermediate_nodes_to_centrelines = defaultdict(list)

        # Check for nerve cuffs in ``contained-in`` lists
        if external_properties is not None:
            for centreline in network.get('centrelines', []):
                if (centreline_id := centreline.get('id')) is not None:
                    centreline_models = centreline.get('models')
                    if len(containers := set(centreline.get('contained-in', []))) > 0:
                        contained_in = []
                        for feature_id in containers:
                            if (models := external_properties.nerve_models_by_id.get(feature_id)) is None:
                                contained_in.append(feature_id)
                            elif centreline_models is None:
                                log.warning(f'Contained-in feature `{feature_id}` used as nerve model of its centreline (`{centreline_id}`)')
                                centreline['models'] = models
                            elif models == centreline_models:
                                log.warning(f'Contained-in feature `{feature_id}` also models nerve of its centreline (`{centreline_id}`)')
                            elif models != centreline_models:
                                log.error(f'Contained-in feature `{feature_id}` models a different nerve than its centreline (`{centreline_id}`)')
                        centreline['contained-in'] = contained_in

        # Collect centreline and end node identifiers, checking validity
        for centreline in network.get('centrelines', []):
            centreline_id = centreline.get('id')
            if centreline_id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif centreline_id in self.__centreline_nodes:
                log.error(f'Centreline {centreline_id} in network {self.__id} has a duplicate id')
            else:
                self.__add_feature(centreline_id)
                if (centreline_models := centreline.get('models')) is not None:
                    self.__models_to_id[centreline_models].add(centreline_id)
                    # If we have ``external_properties`` without ``centreline_models`` annotation for the centreline then set it
                    if external_properties is not None:
                        if (models := external_properties.get_property(centreline_id, 'models')) is None:
                            external_properties.set_property(centreline_id, 'models', centreline_models)
                        elif centreline_models != models:
                            log.error(f'Centreline {centreline_id} models both {centreline_models} and {models}')
                        if (nerve_id := external_properties.nerve_ids_by_model.get(centreline_models)) is not None:
                            # Assign nerve cuff id to centreline
                            external_properties.set_property(centreline_id, 'nerve', nerve_id)
                elif (models := external_properties.get_property(centreline_id, 'models')) is not None:
                    # No ``models`` are directly specified for the centreline so assign what we've found
                    centreline['models'] = models
                    self.__models_to_id[models].add(centreline_id)
                # Check connected nodes
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

        # Check containing features of a centreline are only for that centreline
        centrelines_by_containing_feature = defaultdict(set)
        for centreline_id, containing_features in self.__containers_by_centreline.items():
            for feature_id in containing_features:
                centrelines_by_containing_feature[feature_id].add(centreline_id)
        for feature_id, centreline_set in centrelines_by_containing_feature.items():
            if len(centreline_set) > 1:
                log.warning(f'Feature `{feature_id}` is container for multiple centrelines: {centreline_set}')

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

        def truncate_segments_at_start(segments, network_node):
            # This assumes node centre is close to segments[0].start
            node_centre = network_node.centre
            radii = network_node.radii
            if segments[0].start.distanceFrom(node_centre) > radii[0]:
                return segments
            n = 0
            while n < len(segments) and segments[n].end.distanceFrom(node_centre) < radii[0]:
                n += 1
            if n >= len(segments):
                return segments
            bz = segments[n]
            u = 0.0
            v = 1.0
            while True:
                t = (u + v)/2.0
                point = bz.pointAtTime(t)
                if point.distanceFrom(node_centre) > radii[1]:
                    v = t
                elif point.distanceFrom(node_centre) < radii[0]:
                    u = t
                else:
                    break
            # Drop 0 -- t at front of bezier
            split = bz.splitAtTime(t)
            segments[n] = split[1]
            return segments[n:]

        def truncate_segments_at_end(segments, network_node):
            # This assumes node centre is close to segments[-1].end
            node_centre = network_node.centre
            radii = network_node.radii
            if segments[-1].end.distanceFrom(node_centre) > radii[0]:
                return segments
            n = len(segments) - 1
            while n >= 0 and segments[n].start.distanceFrom(node_centre) < radii[0]:
                n -= 1
            if n < 0:
                return segments
            bz = segments[n]
            u = 0.0
            v = 1.0
            while True:
                t = (u + v)/2.0
                point = bz.pointAtTime(t)
                if point.distanceFrom(node_centre) > radii[1]:
                    u = t
                elif point.distanceFrom(node_centre) < radii[0]:
                    v = t
                else:
                    break
            # Drop t -- 1 at end of bezier
            split = bz.splitAtTime(t)
            segments[n] = split[0]
            return segments[:n+1]

        def set_segment_geometry(node_id_0, node_1, edge_dict):
            segments = edge_dict.pop('bezier-path').asSegments()
            segment_id = edge_dict['segment']
            network_nodes = edge_dict['network-nodes']

            start_node = edge_dict.pop('path-start-node')
            end_node = edge_dict.pop('path-end-node')
            (start_node_id, end_node_id) = (start_node.feature_id, end_node.feature_id)
            edge_dict['start-node'] = start_node_id
            edge_dict['end-node'] = end_node_id

            # Truncate the path at brannch nodes
            if self.__centreline_graph.degree(node_0) >= 2:
                if start_node_id == node_id_0:
                    # This assumes network_nodes[0] centre is close to segments[0].start
                    segments = truncate_segments_at_start(segments, network_nodes[0])
                else:
                    # This assumes network_nodes[-1] centre is close to segments[-1].end
                    segments = truncate_segments_at_end(segments, network_nodes[-1])
            if self.__centreline_graph.degree(node_1) >= 2:
                if start_node_id == node_id_0:
                    # This assumes network_nodes[0] centre is close to segments[-1].end
                    segments = truncate_segments_at_end(segments, network_nodes[0])
                else:
                    # This assumes network_nodes[-1] centre is close to segments[0].start
                    segments = truncate_segments_at_start(segments, network_nodes[-1])

            # We've now have the possibly truncated path of the centreline segment
            # so save it along with geometric information about its end points
            edge_dict['bezier-segments'] = segments
            bz_path = BezierPath.fromSegments(segments)
            edge_dict['geometry'] = bezier_to_linestring(bz_path)

            # Direction of a path at the node boundary, going towards the centre (radians)
            self.__centreline_graph.nodes[start_node_id]['edge-direction'][segment_id] = segments[0].startAngle + math.pi
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[start_node_id]['edge-node-angle'][end_node_id] = (
                                    (segments[0].pointAtTime(0.0) - start_node.centre).angle)

            # Direction of a path at the node boundary, going towards the centre (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-direction'][segment_id] = segments[-1].endAngle
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            self.__centreline_graph.nodes[end_node_id]['edge-node-angle'][start_node_id] = (
                                    # why segments[0].pointAtTime(0.0) ??
                                    (segments[-1].pointAtTime(1.0) - end_node.centre).angle)


        def time_scale(scale, T, x):
            return (scale(x) - T)/(1.0 - T)

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

            # Set centreline type to that of the network
            if self.__type is not None:
                centreline_feature.set_property('type', self.__type)

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
                                                       centreline=centreline_id, segment=segment_id)

                path_start_node = end_node if path_reversed else start_node
                path_end_node = start_node if path_reversed else end_node

                # Split the current Bezier path at the segment boundary and return the remainder
                (cl_path, bz_path) = split_bezier_path_at_point(bz_path, path_end_node.centre)

                # Save properties for later
                edge_id = (*edge_feature_ids, key)
                edge_dict = self.__centreline_graph.edges[edge_id]
                edge_dict['bezier-path'] = cl_path
                edge_dict['reversed'] = path_reversed
                edge_dict['path-start-node'] = path_start_node
                edge_dict['path-end-node'] = path_end_node
                edge_dict['network-nodes'] = network_nodes[start_index:end_index+1]

                segment_edge_ids_by_centreline[centreline_id].append(edge_id)
                self.__segment_edge_by_segment[segment_id] = edge_id
                self.__segment_ids_by_centreline[centreline_id].append(segment_id)
                start_index = end_index

        # Set the ``degree`` property now that we have the complete graph
        for feature_id, node_dict in self.__centreline_graph.nodes(data=True):
            node_dict['degree'] = self.__centreline_graph.degree(feature_id)

        for node_0, node_1, edge_dict in self.__centreline_graph.edges(data=True):
            set_segment_geometry(node_0, node_1, edge_dict)

        # Process intermediate nodes
        for node_0, node_1, edge_dict in self.__centreline_graph.edges(data=True):
            bz_segments = edge_dict.pop('bezier-segments')
            bz_path = BezierPath.fromSegments(bz_segments)
            edge_id = edge_dict['centreline']       # Used in error messages below
            path_reversed = edge_dict['reversed']
            segment_id = edge_dict['segment']
            # Set intermediate node centres to their closest point on the centreline's path
            last_t = 0.0 if not path_reversed else 1.0
            for network_node in edge_dict['network-nodes'][1:-1]:
                t = closest_time_distance(bz_path, network_node.centre)[0]
                if (not path_reversed and t <= last_t
                 or     path_reversed and t >= last_t):
                    log.error(f'Centreline {segment_id} nodes are out of sequence...')
                else:
                    network_node.centre = bz_path.pointAtTime(t)
                last_t = t

            # Find where the centreline's segments cross intermediate nodes
            intermediate_geometry = {}
            intersection_times = {}
            for seg_num, bz_segment in enumerate(bz_segments):
                line = bezier_to_linestring(bz_segment)
                time_points = []
                for network_node in edge_dict['network-nodes'][1:-1]:
                    if not network_node.properties.get('node', False):
                        node_id = network_node.feature_id
                        intermediate_geometry[node_id] = network_node.geometry
                        intersection_points = []
                        if network_node.geometry.intersects(line):
                            intersection = network_node.geometry.boundary.intersection(line)
                            if isinstance(intersection, shapely.geometry.Point):
                                intersection_points.append((closest_time_distance(bz_segment, coords_to_point((intersection.x, intersection.y)))[0], ))
                            else:
                                intersecting_points = intersection.geoms
                                if len(intersecting_points) > 2:
                                    log.warning(f"Intermediate node {node_id} has multiple intersections with centreline {segment_id}")
                                else:
                                    intersection_points.append(sorted((closest_time_distance(bz_segment, coords_to_point((pt.x, pt.y)))[0]
                                                                                for pt in intersecting_points)))
                        if len(intersection_points) == 0:
                            log.warning(f"Intermediate node `{node_id}` doesn't intersect centreline `{segment_id}`")
                        else:
                            time_points.extend(((pts, node_id) for pts in intersection_points))
                intersection_times[seg_num] = sorted(time_points)

            # Break the centreline segment into components, consisting of Bezier segments and intermediate
            # nodes. This is what is used for rendering paths along the centreline segment
            path_components = []
            last_intersection = None
            for seg_num, bz_segment in enumerate(bz_segments):
                prev_intersection = None
                scale = partial(time_scale, lambda x: x, 0.0)
                node_intersections = intersection_times[seg_num]
                intersection_num = 0
                while intersection_num < len(node_intersections):
                    times, node_id = node_intersections[intersection_num]
                    if len(times) == 0:
                        continue
                    node_geometry = intermediate_geometry[node_id]
                    time_0 = scale(times[0])
                    if len(times) == 1:
                        # path touches feature
                        if last_intersection is not None:
                            assert node_id == last_intersection[1]
                            # check times[0] < 0.5  ??
                            bz_parts = bz_segment.splitAtTime(time_0)
                            path_components.append(IntermediateNode(node_geometry, last_intersection[0].startAngle, bz_parts[0].endAngle))
                            bz_segment = bz_parts[1]
                            scale = partial(time_scale, scale, time_0)
                            last_intersection = None
                        elif (intersection_num + 1) == len(node_intersections):
                            # check times[0] > 0.5 ??
                            bz_parts = bz_segment.splitAtTime(time_0)
                            path_components.append(bz_parts[0])
                            last_intersection = (bz_parts[1], node_id)
                        else:
                            log.error(f'Node {node_id} only intersects once with centreline {edge_id}')
                    else:
                        # path crosses feature
                        if prev_intersection is not None and prev_intersection[0] >= times[0]:
                            log.error(f'Intermediate nodes {prev_intersection[1]} and {node_id} overlap on centreline {edge_id}')
                        else:
                            bz_parts = bz_segment.splitAtTime(time_0)
                            path_components.append(bz_parts[0])
                            bz_segment = bz_parts[1]
                            scale = partial(time_scale, scale, time_0)
                            time_1 = scale(times[1])
                            bz_parts = bz_segment.splitAtTime(time_1)
                            path_components.append(IntermediateNode(node_geometry, bz_parts[0].startAngle, bz_parts[0].endAngle))
                            bz_segment = bz_parts[1]
                            scale = partial(time_scale, scale, time_1)
                        prev_intersection = (times[1], node_id)
                    intersection_num += 1
                if last_intersection is None:
                    path_components.append(bz_segment)
            if last_intersection is not None:
                log.error(f'Last intermediate node {last_intersection[1]} on centreline {edge_id} only intersects once')
            edge_dict['path-components'] = path_components

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

    def route_graph_from_path(self, path: Path) -> tuple[nx.Graph, nx.Graph]:
    #========================================================================
        return self.__route_graph_from_connectivity(path)

    def layout(self, route_graphs: nx.Graph) -> dict[int, RoutedPath]:
    #=================================================================
        path_router = PathRouter()
        for path_id, route_graph in route_graphs.items():
            path_router.add_path(path_id, route_graph)
        # Layout the paths and return the resulting routes
        return path_router.layout()

    def __feature_properties_from_node(self, connectivity_node: AnatomicalNode) -> dict[str, Any]:
    #=============================================================================================
        properties: dict[str, Any] = {
            'node': connectivity_node,
            'name': anatomical_node_name(connectivity_node),
            'type': None,
            'contains': set()
        }
        # Can directly identify the centreline
        if (centreline_ids := self.__models_to_id.get(connectivity_node[0])) is not None:
            if len(connectivity_node[1]) > 0:
                log.error(f'Node {full_node_name(connectivity_node)} has centreline inside layers')
            nerve_ids = set()
            segment_ids = set()
            for centreline_id in centreline_ids:
                if ((feature := self.__map_feature(centreline_id)) is not None
                    and (nerve_id := feature.property('nerve')) is not None):
                        # Save the id of the centreline's nerve cuff
                        nerve_ids.add(nerve_id)
                segment_ids.update(self.__segment_ids_by_centreline[centreline_id])
            properties['subgraph'] = self.__centreline_graph.edge_subgraph([self.__segment_edge_by_segment[segment_id]
                                                                                for segment_id in segment_ids]).copy()
            properties['subgraph'].graph['centreline_ids'] = centreline_ids
            properties['nerve-ids'] = nerve_ids
            properties['type'] = 'segment'

        elif self.__feature_map is not None:
            matched = self.__feature_map.find_path_features_by_anatomical_node(connectivity_node)
            properties['name'] = anatomical_node_name(matched[0])
            feature_ids = set(f.id for f in matched[1] if f.id is not None)
            if len(feature_ids):
                properties['type'] = 'feature'
                properties['feature-ids'] = feature_ids
            elif connectivity_node not in self.__missing_identifiers:
                log.warning(f'Cannot find feature for connectivity node {connectivity_node} ({full_node_name(connectivity_node)})')
                self.__missing_identifiers.add(connectivity_node)
        return properties

    def __route_graph_from_connectivity(self, path: Path, debug=False) -> tuple[nx.Graph, nx.Graph]:
    #===============================================================================================
        connectivity_graph = path.connectivity

        if path.trace:
            log.info(f'{path.id}: Edges {connectivity_graph.edges}')

        # Find feature corresponding to each connectivity node and identify
        # terminal nodes that are not part of the centreline network

        for node, node_dict in connectivity_graph.nodes(data=True):
            node_dict.update(self.__feature_properties_from_node(node))

        seen_pairs = set()
        feature_nodes = set()
        segment_nodes = set()
        for node, node_dict in connectivity_graph.nodes(data=True):
            if node_dict['type'] == 'feature':
                feature_nodes.add(node)
                for neighbour in connectivity_graph.neighbors(node):
                    if (node, neighbour) in seen_pairs:
                        continue
                    seen_pairs.add((node, neighbour))
                    seen_pairs.add((neighbour, node))
                    neighbour_dict = connectivity_graph.nodes[neighbour]
                    if neighbour_dict['type'] == 'feature':
                        feature_nodes.add(neighbour)
                        if node_dict['name'] == neighbour_dict['name']:
                            log.error(f'Adjacent connectivity nodes are identical! {node_dict["name"]}')
                        elif neighbour_dict['name'].startswith(node_dict['name']):
                            # node contains neighbour
                            node_dict['contains'].add(neighbour)
                            neighbour_dict['contained-by'] = node
                        elif node_dict['name'].startswith(neighbour_dict['name']):
                            # neighbour contains node
                            neighbour_dict['contains'].add(node)
                            node_dict['contained-by'] = neighbour
            elif node_dict['type'] == 'segment':
                segment_nodes.add(node)

        for node in feature_nodes:
            if len(connectivity_graph.nodes[node]['contains']) == 0:
                while (container := connectivity_graph.nodes[node].get('contained-by')) is not None:
                    connectivity_graph.nodes[container]['exclude'] = True
                    node = container

        ### WIP: need to check for and add centrelines connecting nodes...

        path_feature_ids = set()
        route_graph = nx.MultiGraph()
        for node, node_dict in connectivity_graph.nodes(data=True):
            node_type = node_dict['type']

            if node_type == 'segment':
                path_feature_ids.update(node_dict['nerve-ids'])
                segment_graph = node_dict['subgraph']
                if segment_graph.number_of_edges() == 1:
                    for node_0, node_1, edge_dict in segment_graph.edges(data=True):
                        route_graph.add_node(node_0, **self.__centreline_graph.nodes[node_0])
                        route_graph.add_node(node_1, **self.__centreline_graph.nodes[node_1])
                        route_graph.add_edge(node_0, node_1, **edge_dict)
                else:
                    # Get set of neighbouring features
                    neighbouring_ids = set()
                    for neighbour in connectivity_graph.neighbors(node):
                        neighbour_dict = connectivity_graph.nodes[neighbour]
                        if neighbour_dict['type'] == 'feature':
                            neighbouring_ids.update(neighbour_dict['feature-ids'])
                        elif neighbour_dict['type'] == 'segment':
                            neighbouring_ids.update(neighbour_dict['subgraph'].nodes)
                    # And get actual segment edges used by our path
                    for node_0, node_1, edge_dict in graph_utils.get_connected_subgraph(segment_graph, neighbouring_ids).edges(data=True):
                        route_graph.add_node(node_0, **self.__centreline_graph.nodes[node_0])
                        route_graph.add_node(node_1, **self.__centreline_graph.nodes[node_1])
                        route_graph.add_edge(node_0, node_1, **edge_dict)


        terminal_nodes = set()
        for node, node_dict in connectivity_graph.nodes(data=True):
            if node_dict['type'] == 'feature' and not node_dict.get('exclude', False):
                included = False
                for feature_id in node_dict['feature-ids']:
                    if feature_id in route_graph:
                        included = True
                        break
                if not included:
                    terminal_nodes.add(node)
                    node_dict['terminal'] = True

        for feature_id in route_graph.nodes:
            feature = self.__map_feature(feature_id)
            if feature is not None and not feature.property('invisible', False):
                # Add the feature to set of features for the path
                path_feature_ids.add(feature.id)
                feature.set_property('exclude', False)

        ### WIP: need to add terminal nodes/graphs to the route graph

        route_graph.graph['path-id'] = path.id
        route_graph.graph['path-type'] = path.path_type
        route_graph.graph['source'] = path.source
        route_graph.graph['nerve-features'] = set(nerve_id for nerve_id in path_nerve_ids if self.__map_feature(nerve_id) is not None)
        route_graph.graph['traced'] = path.trace
        if debug:
            return (route_graph, G, connectivity_graph, terminal_graphs)    # type: ignore
        else:
            return route_graph

#===============================================================================
