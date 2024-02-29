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
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import partial
import itertools
import math
import sys
from typing import TYPE_CHECKING, Any, Optional
from mapmaker.knowledgebase.sckan import PATH_TYPE

from mapmaker.settings import settings
from mapmaker.knowledgebase.celldl import FC_CLASS, FC_KIND


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

from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.flatmap.feature import Feature
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.geometry.beziers import bezier_to_linestring, closest_time_distance
from mapmaker.geometry.beziers import coords_to_point
from mapmaker.geometry.beziers import split_bezier_path_at_point
from mapmaker.knowledgebase import AnatomicalNode
from mapmaker.utils import log
import mapmaker.utils.graph as graph_utils

from .options import MIN_EDGE_JOIN_RADIUS
from .routedpath import IntermediateNode, PathRouter, RoutedPath

#===============================================================================

if TYPE_CHECKING:
#   from mapmaker.flatmap import FlatMap
#   from mapmaker.properties import PropertiesStore
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
    def centre(self) -> Optional[BezierPoint]:
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

    def set_properties_from_feature(self, feature: Optional[Feature]):
    #=================================================================
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
    def __init__(self, flatmap: 'FlatMap', network: dict, properties_store: Optional['PropertiesStore']=None):
        self.__flatmap = flatmap
        self.__id = network.get('id')
        self.__type = network.get('type')

        self.__centreline_nodes: dict[str, list[NetworkNode]] = defaultdict(list)  #! Centreline id --> [Network nodes]
        self.__nodes_by_ftu: dict[str, list[NetworkNode]] = defaultdict(list)      #! FTU id id --> {Network nodes}
        self.__containers_by_centreline = {}                                       #! Centreline id --> set of features that centreline is contained in
        self.__models_to_id: dict[str, set[str]] = defaultdict(set)                #! Ontological term --> centrelines
        self.__feature_ids: set[str] = set()
        self.__full_ids: set[str] = set()                                          #! A ``full id`` is a slash-separated list of feature ids
        self.__missing_identifiers: set[AnatomicalNode] = set()
        self.__end_feature_ids = set()
        self.__container_feature_ids = set()

        # The following are assigned once we have feature geometry
        self.__centreline_graph: nx.MultiGraph = None                               #! Edges are centreline segments between intermediate nodes.
        self.__containers_by_segment: dict[str, set[str]] = defaultdict(set)        #! Segment id --> set of features that segment is contained in
        self.__centrelines_by_containing_feature = defaultdict(set)                 #! Feature id --> set of centrelines that are contained in feature
        self.__expanded_centreline_graph: nx.Graph = None                           #! Expanded version of centreline graph
        self.__segment_edge_by_segment: dict[str, tuple[str, str, str]] = {}        #! Segment id --> segment edge
        self.__segment_ids_by_centreline: dict[str, list[str]] = defaultdict(list)  #! Centreline id --> segment ids of the centreline

        # Track how nodes are associated with centrelines
        end_nodes_to_centrelines = defaultdict(list)
        intermediate_nodes_to_centrelines = defaultdict(list)

        # Check for nerve cuffs in ``contained-in`` lists
        if properties_store is not None:
            for centreline in network.get('centrelines', []):
                if (centreline_id := centreline.get('id')) is not None:
                    centreline_models = centreline.get('models')
                    if len(containers := set(centreline.get('contained-in', []))) > 0:
                        contained_in = []
                        for feature_id in containers:
                            if properties_store.properties(feature_id).get('models') is None:
                                # Container features are of no use if they don't model anything...
                                log.error(f'Contained-in feature `{feature_id}` of `{centreline_id}` does not have an anatomical term')
                            elif (models := properties_store.nerve_models_by_id.get(feature_id)) is None:
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
        centrelines_by_end_feature = defaultdict(set)
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
                    # If we have ``properties_store`` without ``centreline_models`` annotation for the centreline then set it
                    if properties_store is not None:
                        if (models := properties_store.get_property(centreline_id, 'models')) is None:
                            properties_store.set_property(centreline_id, 'models', centreline_models)
                        elif centreline_models != models:
                            log.error(f'Centreline {centreline_id} models both {centreline_models} and {models}')
                        if (nerve_id := properties_store.nerve_ids_by_model.get(centreline_models)) is not None:
                            # Assign nerve cuff id to centreline
                            properties_store.set_property(centreline_id, 'nerve', nerve_id)
                elif (properties_store is not None
                  and (models := properties_store.get_property(centreline_id, 'models')) is not None):
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
                    centrelines_by_end_feature[connected_nodes[0]].add(centreline_id)
                    centrelines_by_end_feature[connected_nodes[-1]].add(centreline_id)
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

        # Create feature_id |--> centreline_id mapping and check containing features are not
        # also end features
        for centreline_id, containing_features in self.__containers_by_centreline.items():
            for feature_id in containing_features:
                if (centrelines := centrelines_by_end_feature.get(feature_id)) is None:
                    self.__centrelines_by_containing_feature[feature_id].add(centreline_id)
                else:
                    log.warning(f"Container feature {feature_id} of {centreline_id} is also an end node for: {centrelines}")

    @property
    def id(self):
        return self.__id

    def __add_feature(self, full_id):
    #=================================
        self.__full_ids.add(full_id)
        for id in full_id.split('/'):
            self.__feature_ids.add(id)

    def check_features_on_map(self):
    #===============================
        # Check that the network's features are on the map
        for id in sorted(self.__feature_ids):
            if not self.__flatmap.has_feature(id):
                log.warning(f'Network feature {id} cannot be found on the flatmap')

    def has_feature(self, feature):
    #==============================
        # Is the ``feature`` included in this network?
        return (feature.id in self.__feature_ids
             or feature.get_property('tile-layer') == PATHWAYS_TILE_LAYER)

    def __map_feature(self, feature_id):
    #===================================
        if feature_id not in self.__missing_identifiers:
            if (feature := self.__flatmap.get_feature(feature_id)) is not None:
                return feature
            log.error('Cannot find network feature: {}'.format(feature_id))
            self.__missing_identifiers.add(feature_id)
        return None

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

        def set_segment_geometry(node_id_0, node_1_id, edge_dict):
            segments = edge_dict.pop('bezier-path').asSegments()
            segment_id = edge_dict['segment']
            network_nodes = edge_dict['network-nodes']

            start_node = edge_dict.pop('path-start-node')
            end_node = edge_dict.pop('path-end-node')
            (start_node_id, end_node_id) = (start_node.feature_id, end_node.feature_id)
            edge_dict['start-node'] = start_node_id
            edge_dict['end-node'] = end_node_id

            # Truncate the path at branch nodes
            if self.__centreline_graph.degree(node_id_0) >= 2:
                if start_node_id == node_id_0:
                    # This assumes network_nodes[0] centre is close to segments[0].start
                    segments = truncate_segments_at_start(segments, network_nodes[0])
                else:
                    # This assumes network_nodes[-1] centre is close to segments[-1].end
                    segments = truncate_segments_at_end(segments, network_nodes[-1])
            if self.__centreline_graph.degree(node_1_id) >= 2:
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

            bz_path = BezierPath.fromSegments(centreline_feature.get_property('bezier-segments'))

            # A node's centre may not be where a centreline into the node finishes
            # so check both ends of the Bezier path to decide the curve's direction
            node_0_centre = network_nodes[0].centre
            node_1_centre = network_nodes[-1].centre
            min_distance = None
            coords = (0, 0)
            for n, centre in enumerate([node_0_centre, node_1_centre]):
                for m, t in enumerate([0.0, 1.0]):
                    distance = centre.distanceFrom(bz_path.pointAtTime(t))
                    if min_distance is None or distance < min_distance:
                        min_distance = distance
                        coords = (n, m)
            path_reversed = (coords[0] != coords[1])

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

    def route_graph_from_path(self, path: 'Path') -> tuple[nx.Graph, nx.Graph]:
    #==========================================================================
        return self.__route_graph_from_connectivity(path)

    def layout(self, route_graphs: nx.Graph) -> dict[int, RoutedPath]:
    #=================================================================
        path_router = PathRouter()
        for path_id, route_graph in route_graphs.items():
            path_router.add_path(path_id, route_graph)
        # Layout the paths and return the resulting routes
        return path_router.layout()

    def __segment_properties_from_ids(self, centreline_ids: Iterable[str]) -> dict[str, Any]:
    #========================================================================================
        properties = {}
        nerve_ids = set()
        segment_ids = set()
        for centreline_id in centreline_ids:
            if ((feature := self.__map_feature(centreline_id)) is not None
                and (nerve_id := feature.get_property('nerve')) is not None):
                    # Save the id of the centreline's nerve cuff
                    nerve_ids.add(nerve_id)
            segment_ids.update(self.__segment_ids_by_centreline[centreline_id])
        properties['subgraph'] = self.__centreline_graph.edge_subgraph([self.__segment_edge_by_segment[segment_id]
                                                                            for segment_id in segment_ids]).copy()
        properties['subgraph'].graph['segment-ids'] = segment_ids
        properties['nerve-ids'] = nerve_ids
        properties['type'] = 'segment'
        return properties

    def __feature_properties_from_node(self, connectivity_node: AnatomicalNode) -> dict[str, Any]:
    #=============================================================================================
        # # Allow to use the identified alias
        if (matched:=self.__flatmap.features_for_anatomical_node(connectivity_node)) is not None:
            if connectivity_node.name != matched[0].name:
                connectivity_node = matched[0]

        # Find the features and centrelines that corresponds to a connectivity node
        properties: dict[str, Any] = {
            'node': connectivity_node,
            'name': connectivity_node.name,
            'type': None,
            'contains': set(),
            'used': set()
        }
        # Can we directly identify the centreline from nodes anatomical base term?
        if (centreline_ids := self.__models_to_id.get(connectivity_node[0])) is not None:
            if len(connectivity_node[1]) > 0:
                log.error(f'Node {connectivity_node.full_name} has centreline inside layers')
            properties.update(self.__segment_properties_from_ids(centreline_ids))

        elif matched is not None:
            properties['name'] = matched[0].name
            features = set(f for f in matched[1] if f.id is not None)
            if len(features):
                properties['type'] = 'feature'
                properties['features'] = features
            elif connectivity_node not in self.__missing_identifiers:
                properties['warning'] = f'Cannot find feature for connectivity node {connectivity_node} ({connectivity_node.full_name})'
                self.__missing_identifiers.add(connectivity_node)
        return properties

    def __closest_feature_id_to_point(self, point, node_feature_ids) -> Optional[str]:
    #=================================================================================
        # Find feature id of feature that is closest to ``point``.
        closest_feature_id: Optional[str] = None
        closest_distance = -1
        for node_id in node_feature_ids:
            node_centre = self.__centreline_graph.nodes[node_id]['geometry'].centroid
            distance = point.distance(node_centre)
            if closest_feature_id is None or distance < closest_distance:
                closest_distance = distance
                closest_feature_id = node_id
        return closest_feature_id

    def __closest_segment_node_to_point(self, point, segment_id) -> tuple[Optional[str], float]:
    #===========================================================================================
        # Find segment's node that is closest to ``point``.
        closest_node = None
        closest_distance = -1
        for node_id in self.__segment_edge_by_segment[segment_id][0:2]:
            node_centre = self.__centreline_graph.nodes[node_id]['geometry'].centroid
            distance = point.distance(node_centre)
            if closest_node is None or distance < closest_distance:
                closest_distance = distance
                closest_node = node_id
        return (closest_node, closest_distance)

    def __route_graph_from_connectivity(self, path: 'Path', debug=False) -> tuple[nx.Graph, nx.Graph]:
    #=================================================================================================
        connectivity_graph = path.connectivity

        # Map connectivity nodes to map features and centrelines, storing the result
        # in the connectivity graph
        for node, node_dict in connectivity_graph.nodes(data=True):
            node_dict.update(self.__feature_properties_from_node(node))
            if (warning := node_dict.pop('warning', None)) is not None:
                log.warning(f'{path.id}: {warning}')

        def bypass_missing_node(ms_node):
            if len(neighbours:=list(connectivity_graph.neighbors(ms_node))) > 1:
                predecessors, successors = [], []
                for neighbour in neighbours:
                    if neighbour == connectivity_graph.edges[(ms_node, neighbour)]['predecessor']:
                        predecessors += [neighbour]
                    elif neighbour == connectivity_graph.edges[(ms_node, neighbour)]['successor']:
                        successors += [neighbour]
                if len(predecessors) > 0 and len(successors) > 0:
                    ms_nodes = list(connectivity_graph[ms_node].values())[0].get('missing_nodes', [])
                    for e in [edge for edge in itertools.product(predecessors,successors) if (edge[0]!=edge[1])]:
                        ms_nodes = list(set([ms_node] + connectivity_graph.edges[(e[0], ms_node)].get('missing_nodes', []) + \
                                            connectivity_graph.edges[(ms_node, e[1])].get('missing_nodes', [])))
                        connectivity_graph.add_edges_from(
                            [e],
                            completeness = False,
                            missing_nodes = ms_nodes,
                            predecessor = e[0],
                            successor = e[1],
                        )
            connectivity_graph.remove_nodes_from([ms_node])

        # In a case of FC map, we need to remove missing nodes
        if settings.get('NPO', False) and self.__flatmap.manifest.kind == 'functional':
            missing_nodes = [c for c in connectivity_graph.nodes if c in self.__missing_identifiers]
            for ms_node in missing_nodes:
                bypass_missing_node(ms_node)

        if path.trace:
            for node, node_dict in connectivity_graph.nodes(data=True):
                node_data = {}
                if node_dict['type'] == 'feature':
                    node_data['features'] = {f.id for f in node_dict['features']}
                elif node_dict['type'] == 'segment':
                    node_data['segments'] = node_dict['subgraph'].graph['segment-ids']
                log.info(f'{path.id}: Connectivity node {node}: {node_data}')
            log.info(f'{path.id}: Connectivity edges {connectivity_graph.edges}')

        # Go through all the nodes that map to a feature and flag those which enclose
        # an immediate neighbour so that we don't draw a path to the containing node
        # but instead will pass through it.
        feature_nodes = set()
        seen_pairs = set()
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
                            log.error(f'{path.id}: Adjacent connectivity nodes are identical! {node_dict["name"]}')
                        elif neighbour_dict['name'].startswith(node_dict['name']):
                            # node contains neighbour
                            node_dict['contains'].add(neighbour)
                            neighbour_dict['contained-by'] = node
                        elif node_dict['name'].startswith(neighbour_dict['name']):
                            # neighbour contains node
                            neighbour_dict['contains'].add(node)
                            node_dict['contained-by'] = neighbour
        for node in feature_nodes:
            if len(connectivity_graph.nodes[node]['contains']) == 0:
                while (container := connectivity_graph.nodes[node].get('contained-by')) is not None:
                    connectivity_graph.nodes[container]['exclude'] = True
                    node = container

        # Create the route graphe for the connectivity path
        route_graph = nx.MultiGraph()

        # Nerves and nodes used by the path
        path_nerve_ids = set()
        path_node_ids = set()

        # Helper functions
        def add_route__with_edge_dict(node_0, node_1, edge_dict):
            route_graph.add_node(node_0, **self.__centreline_graph.nodes[node_0])
            route_graph.add_node(node_1, **self.__centreline_graph.nodes[node_1])
            route_graph.add_edge(node_0, node_1, **edge_dict)
            path_node_ids.update(node.feature_id for node in edge_dict['network-nodes'])
        def add_route_edges_from_graph(G, used_nodes):
            node_feature_ids = set()
            for node_0, node_1, edge_dict in G.edges(data=True):
                add_route__with_edge_dict(node_0, node_1, edge_dict)
                node_feature_ids.update({node_0, node_1})
            for node in used_nodes:
                node_dict = connectivity_graph.nodes[node]
                node_dict['used'] = node_feature_ids

        # Add directly identified centreline segments to the route, noting path nodes and
        # nerve cuff identifiers
        no_sub_segment_nodes = []
        for node, node_dict in connectivity_graph.nodes(data=True):
            node_type = node_dict['type']
            if node_type == 'segment':
                path_nerve_ids.update(node_dict['nerve-ids'])
                segment_graph = node_dict['subgraph']
                if segment_graph.number_of_edges() > 1:
                    # Get set of neighbouring features
                    neighbouring_ids = set()
                    for neighbour in connectivity_graph.neighbors(node):
                        neighbour_dict = connectivity_graph.nodes[neighbour]
                        if neighbour_dict['type'] == 'feature':
                            neighbouring_ids.update(f.id for f in neighbour_dict['features'])
                        elif neighbour_dict['type'] == 'segment':
                            neighbouring_ids.update(neighbour_dict['subgraph'].nodes)
                    segment_graph = graph_utils.get_connected_subgraph(segment_graph, neighbouring_ids)
                if segment_graph.number_of_edges():
                    # Add segment edges used by our path to the route
                    add_route_edges_from_graph(segment_graph, {node})
                else:
                    log.warning(f'{path.id}: Cannot find any sub-segments of centreline for `{node_dict["name"]}`')
                    node_dict['type'] = 'no-segment'
                    no_sub_segment_nodes += [node] # store node with undecided sub-segments

        # draw direct line, skip the centerline if sub-segments cannot be find
        for no_sub_segment_node in no_sub_segment_nodes:
            bypass_missing_node(no_sub_segment_node)

        # Find centrelines where adjacent connectivity nodes are centreline end nodes
        seen_pairs = set()
        for node, node_dict in connectivity_graph.nodes(data=True):
            if node_dict['type'] == 'feature':
                for neighbour in connectivity_graph.neighbors(node):
                    if (node, neighbour) in seen_pairs:
                        continue
                    seen_pairs.add((node, neighbour))
                    seen_pairs.add((neighbour, node))
                    neighbour_dict = connectivity_graph.nodes[neighbour]
                    if neighbour_dict['type'] == 'feature':
                        for node_feature in node_dict['features']:
                            for neighbouring_feature in neighbour_dict['features']:
                                if (edge_dicts := self.__centreline_graph.get_edge_data(node_feature.id, neighbouring_feature.id)) is not None:
                                    if len(edge_dicts) > 1:
                                        log.warning(f'{path.id}: Multiple centrelines between {node_feature.id} and {neighbouring_feature.id}')
                                    edge_dict = edge_dicts[list(edge_dicts)[0]]
                                    add_route__with_edge_dict(node_feature.id, neighbouring_feature.id, edge_dict)
                                    node_dict['used'] = {node_feature.id}
                                    neighbour_dict['used'] = {neighbouring_feature.id}

        # Find centrelines that are contained in sequences of so far unused nodes of the
        # connectivity graph
        def get_centreline_from_containing_features(start_dict, end_dict, feature_ids: set[str], used_nodes: set):
            start_feature_ids = [f.id for f in start_dict.get('features', [])]
            end_feature_ids = [f.id for f in end_dict.get('features', [])]
            if path.trace:
                log.info(f'{path.id}: Search between {start_feature_ids} and {end_feature_ids}: containers {feature_ids}')
            candidate_contained_centrelines = set()
            for feature_id in feature_ids:
                candidate_contained_centrelines.update(self.__centrelines_by_containing_feature.get(feature_id, set()))
            if path.trace:
                log.info(f'{path.id}: Candidates: {candidate_contained_centrelines}')
            matched_centreline = None
            max_score = 0
            for centreline_id in candidate_contained_centrelines:
                centreline_containers = self.__containers_by_centreline[centreline_id]
                score = len(centreline_containers & feature_ids)/len(centreline_containers | feature_ids)
                centreline_nodes = self.__centreline_nodes[centreline_id]
                if (centreline_nodes[0].feature_id in start_feature_ids
                 or centreline_nodes[0].feature_id in end_feature_ids):
                    score += 1
                if (centreline_nodes[-1].feature_id in start_feature_ids
                 or centreline_nodes[-1].feature_id in end_feature_ids):
                    score += 1
                if path.trace:
                    log.info(f'{path.id}: Score: {score}: {centreline_id}')
                if score > max_score:
                    matched_centreline = centreline_id
                    max_score = score
            if matched_centreline is not None:
                if path.trace:
                    log.info(f'{path.id}: Selected: {max_score}: {matched_centreline}')
                properties = (self.__segment_properties_from_ids([matched_centreline]))
                path_nerve_ids.update(properties['nerve-ids'])
                add_route_edges_from_graph(properties['subgraph'], used_nodes)

        for ends, path_nodes in graph_utils.connected_paths(connectivity_graph).items():
            feature_ids = set()
            used_nodes = set()
            start_dict = connectivity_graph.nodes[ends[0]]
            for node in path_nodes:
                node_dict = connectivity_graph.nodes[node]
                if len(node_dict['used']):
                    if len(feature_ids):
                        get_centreline_from_containing_features(start_dict, node_dict, feature_ids, used_nodes)
                        feature_ids = set()
                        used_nodes = set()
                        start_dict = node_dict
                elif node_dict['type'] == 'feature':
                    feature_ids.update(f.id for f in node_dict['features'])
                    used_nodes.add(node)
            if len(feature_ids):
                get_centreline_from_containing_features(start_dict, connectivity_graph.nodes[ends[1]], feature_ids, used_nodes)

        # Now see if unconnected centreline end nodes in the route graph are in fact connected
        # by a centreline
        new_edge_dicts = {}
        for node_0, node_1 in itertools.combinations(route_graph.nodes, 2):
            if (not route_graph.has_edge(node_0, node_1)
            and (edge_dicts := self.__centreline_graph.get_edge_data(node_0, node_1)) is not None):
                if len(edge_dicts) > 1:
                    log.warning(f'{path.id}: Multiple centrelines between {node_0} and {node_1}')
                new_edge_dicts[(node_0, node_1)] = edge_dicts[list(edge_dicts)[0]]
        for edge, edge_dict in new_edge_dicts.items():
            route_graph.add_edge(*edge, **edge_dict)
            path_node_ids.update(node.feature_id for node in edge_dict['network-nodes'])

        def get_ftu_node(feature):
            # looking for FTU if possible
            if feature.properties.get('fc-class') != FC_CLASS.FTU:
                for child in feature.properties.get('children', []):
                    child_feature = self.__flatmap.get_feature_by_geojson_id(child)
                    if child_feature.properties.get('fc-class') == FC_CLASS.FTU and child_feature.models == feature.models:
                        feature = child_feature
                        break
            # looking for correct connector or port
            for child in feature.properties.get('children', []):
                child_feature = self.__flatmap.get_feature_by_geojson_id(child)
                if (child_feature.properties.get('fc-kind') in [FC_KIND.CONNECTOR_NODE, FC_KIND.CONNECTOR_PORT, FC_KIND.GANGLION] and \
                    path.path_type is not None and \
                    child_feature.properties.get('path-type') != PATH_TYPE.UNKNOWN) and \
                    (path.path_type == child_feature.properties.get('path-type') or \
                    PATH_TYPE.PRE_GANGLIONIC|child_feature.properties.get('path-type') == path.path_type or \
                    PATH_TYPE.POST_GANGLIONIC|child_feature.properties.get('path-type') == path.path_type):
                        return child_feature
            return feature

        def get_node_feature(node_dict) -> Feature:
            if len(node_dict['features']) > 1:
                log.error(f'{path.id}: Terminal node {node_dict["name"]} has multiple features {sorted(set(f.id for f in node_dict["features"]))}')
            selected_feature = list(f for f in node_dict['features'])[0]
            if settings.get('NPO', False):
                return get_ftu_node(selected_feature)
            return selected_feature

        terminal_graphs: dict[tuple, nx.Graph] = {}
        visited = set()
        for node, node_dict in connectivity_graph.nodes(data=True):
            if node not in visited and connectivity_graph.degree(node) == 1:
                if node_dict['type'] == 'feature':
                    # First check node isn't already the end of a centreline
                    if len(node_dict['used']) == 0:
                        for feature in node_dict['features']:
                            if feature.id in route_graph:
                                node_dict['used'] = {feature.id}
                                break

                    if len(node_dict['used']) == 0:
                        terminal_graph = nx.Graph()

                        def add_paths_to_neighbours(node, node_dict):
                            visited.add(node)
                            # Find the actual nodes we want to connect to, skipping
                            # over that we are directly contained in
                            neighbours = set(connectivity_graph[node])
                            for neighbour in (neighbours - visited):
                                neighbour_dict = connectivity_graph.nodes[neighbour]
                                if (neighbour_dict['type'] == 'feature'
                                  and len(neighbour_dict.get('used', set())) == 0
                                  and node in (children := neighbour_dict.get('contains', set()))):
                                    # Replace the neighbour by it's neighbours which aren't children
                                    downstream = set(connectivity_graph[neighbour]) - children
                                    neighbours.remove(neighbour)
                                    neighbours.update(downstream)
                            # Connect to each neighbour of interest, noting those that will
                            # then need connecting
                            neighbours_neighbours = []
                            node_feature = get_node_feature(node_dict)
                            for neighbour in (neighbours - visited):
                                neighbour_dict = connectivity_graph.nodes[neighbour]
                                degree = connectivity_graph.degree(neighbour)
                                node_feature_centre = node_feature.geometry.centroid
                                if neighbour_dict['type'] == 'feature':
                                    terminal_graph.add_node(node_feature.id, feature=node_feature)
                                    if len(used_ids := neighbour_dict.get('used', set())):
                                        closest_feature_id = self.__closest_feature_id_to_point(node_feature_centre, used_ids)
                                        terminal_graph.add_edge(node_feature.id, closest_feature_id,
                                            upstream=True)
                                        segments = set()
                                        for connected_edges in route_graph[closest_feature_id].values():
                                            for edge_dict in connected_edges.values():
                                                if (segment_id := edge_dict.get('segment')) is not None:
                                                    segments.add(segment_id)
                                        terminal_graph.nodes[closest_feature_id]['upstream'] = True
                                        terminal_graph.nodes[closest_feature_id]['segments'] = segments
                                    else:
                                        if (debug_properties:=connectivity_graph.get_edge_data(node, neighbour_dict.get('node'))) is None:
                                            debug_properties = {}
                                        neighbour_feature = get_node_feature(neighbour_dict)
                                        terminal_graph.add_node(neighbour_feature.id, feature=neighbour_feature)
                                        terminal_graph.add_edge(node_feature.id, neighbour_feature.id, **debug_properties)
                                elif neighbour_dict['type'] == 'segment':
                                    closest_feature_id = None
                                    closest_distance = None
                                    last_segment = None
                                    for segment_id in neighbour_dict['subgraph'].graph['segment-ids']:
                                        (segment_end, distance) = self.__closest_segment_node_to_point(node_feature_centre, segment_id)
                                        if (segment_end is not None
                                          and segment_end in route_graph
                                          and (closest_distance is None or distance < closest_distance)):
                                            closest_feature_id = segment_end
                                            closest_distance = distance
                                            last_segment = segment_id
                                    if closest_feature_id is not None:
                                        terminal_graph.add_edge(node_feature.id, closest_feature_id, upstream=True)
                                        terminal_graph.nodes[node_feature.id]['feature'] = node_feature
                                        terminal_graph.nodes[closest_feature_id]['upstream'] = True
                                        terminal_graph.nodes[closest_feature_id]['segments'] = set([last_segment])
                                        neighbour_dict['used'] = {closest_feature_id}
                                # Only have our neighbour visit their neighbours if the neighbour is unconnected
                                if degree > 1 and len(neighbour_dict['used']) == 0 and neighbour_dict['type'] == 'feature':
                                    neighbours_neighbours.append((neighbour, neighbour_dict))
                            # Connect our neighbour's neighbours
                            for neighbour in neighbours_neighbours:
                                add_paths_to_neighbours(*neighbour)

                        add_paths_to_neighbours(node, node_dict)
                        terminal_graphs[node] = terminal_graph

        if path.trace:
            log.info(f'{path.id}: Terminal connections:')
            for terminal_graph in terminal_graphs.values():
                for n_0, nd in terminal_graph.nodes(data=True):
                    log.info(f'{path.id}: Node {n_0}: {nd}')
                for n_0, n_1, ed in terminal_graph.edges(data=True):
                    log.info(f'{path.id}: Edge {n_0} -> {n_1}: {ed}')

        def set_properties_from_feature_id(feature_id: str):
            node_dict = {}
            if (feature := self.__map_feature(feature_id)) is not None:
                node_dict.update(feature.properties)
                node_dict['geometry'] = feature.geometry
                if feature.geometry is not None:
                    centre = feature.geometry.centroid
                    node_dict['centre'] = BezierPoint(centre.x, centre.y)
                    radius = max(math.sqrt(feature.geometry.area/math.pi), MIN_EDGE_JOIN_RADIUS)
                    node_dict['radii'] = (0.999*radius, 1.001*radius)
                else:
                    log.warning(f'{path.id}: Feature {feature.id} has no geometry')
            return node_dict

        # Now add edges from the terminal graphs to the path's route graph
        for terminal_graph in terminal_graphs.values():
            for node_0, node_1, upstream in terminal_graph.edges(data='upstream'):
                debug_properties = terminal_graph.get_edge_data(node_0, node_1)
                if not upstream:
                    upstream_node = None
                    route_graph.add_node(node_0, type='terminal')
                    route_graph.add_node(node_1, type='terminal')
                    route_graph.add_edge(node_0, node_1, type='terminal', **debug_properties)
                else:
                    upstream_node = node_0 if terminal_graph.nodes[node_0].get('upstream') else node_1
                    route_graph.nodes[upstream_node]['type'] = 'upstream'
                    segment_ids = terminal_graph.nodes[upstream_node].get('segments', set())
                    if len(segment_ids):
                        # We want the path direction we were going when we reached the upstream node
                        direction = 0.0
                        for segment_id in segment_ids:
                            direction += route_graph.nodes[upstream_node]['edge-direction'][segment_id]
                        route_graph.nodes[upstream_node]['direction'] = direction/len(segment_ids)
                    else:
                        route_graph.nodes[upstream_node]['direction'] = list(route_graph.nodes[upstream_node]['edge-direction'].items())[0][1]
                    route_graph.add_edge(node_0, node_1, type='upstream', **debug_properties)
                if node_0 != upstream_node:
                    route_graph.nodes[node_0].update(set_properties_from_feature_id(node_0))
                if node_1 != upstream_node:
                    route_graph.nodes[node_1].update(set_properties_from_feature_id(node_1))

        # Make sure the set of path nodes includes those from the routed path
        path_node_ids.update(route_graph.nodes)

        # Identify features on the path with a nerve cuff used by the path
        # and make hidden nodes that are actually used in the route visible
        nerve_id = list(path_nerve_ids)[0] if len(path_nerve_ids) else None
        if nerve_id is not None and (nerve_feature := self.__map_feature(nerve_id)) is not None:
            nerve_id = nerve_feature.geojson_id
        for feature_id in path_node_ids:
            feature = self.__map_feature(feature_id)
            if feature is not None:  # Redundant test...
                if nerve_id is not None:
                    feature.set_property('nerveId', nerve_id)   # Used in map viewer
                if 'auto-hide' in feature.get_property('class', ''):
                    # Show the hidden feature on the map
                    feature.pop_property('exclude')

        route_graph.graph['path-id'] = path.id
        route_graph.graph['path-type'] = path.path_type
        route_graph.graph['source'] = path.source
        route_graph.graph['traced'] = path.trace
        route_graph.graph['nerve-features'] = set(feature_id for feature_id in path_nerve_ids if self.__map_feature(feature_id) is not None)
        route_graph.graph['node-features'] = set(feature_id for feature_id in path_node_ids if self.__map_feature(feature_id) is not None)

        if path.trace:
            log.info(f'{path.id}: Route graph: {route_graph.graph}')
            for n_0, n_1, ed in route_graph.edges(data=True):
                log.info(f'{path.id}: Edge {n_0} -> {n_1}: {ed.get("centreline")}')

        if debug:
            return (route_graph, G, connectivity_graph, terminal_graphs)    # type: ignore
        else:
            return route_graph

#===============================================================================
