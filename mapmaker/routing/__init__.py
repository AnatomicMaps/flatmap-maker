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
import typing
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

from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry
import structlog

#===============================================================================

from mapmaker.flatmap.feature import Feature
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.geometry.beziers import bezier_to_linestring, closest_time_distance
from mapmaker.geometry.beziers import coords_to_point
from mapmaker.geometry.beziers import split_bezier_path_at_point
from mapmaker.knowledgebase import AnatomicalNode
from mapmaker.knowledgebase.celldl import FC_CLASS, FC_KIND
from mapmaker.knowledgebase.sckan import PATH_TYPE
from mapmaker.settings import settings
from mapmaker.utils import log
import mapmaker.utils.graph as graph_utils

#===============================================================================

from .options import MIN_EDGE_JOIN_RADIUS
from .routedpath import IntermediateNode, PathRouter, RoutedPath

#===============================================================================

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap
    from mapmaker.properties import PropertiesStore
    from mapmaker.properties.pathways import Path


#=============================================================

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
        G.add_node(edge_node, graph_object='edge', edge=(node_0, node_1), **edge_dict)
        G.add_edge(node_0, edge_node, graph_object='node')
        G.add_edge(edge_node, node_1, graph_object='node')
    return G

def collapse_centreline_graph(graph: nx.Graph) -> nx.Graph:
#==========================================================
    G = nx.Graph()
    seen_edges = set()
    for node_or_edge, node_dict in graph.nodes(data=True):
        new_dict = node_dict.copy()
        graph_object = new_dict.pop('graph_object', None)
        if graph_object == 'edge':
            edge_nodes = new_dict.pop('edge')
            if edge_nodes in seen_edges:
                log.warning('Edge ignored as it is already in the route graph', type='conn', node=node_or_edge)
            else:
                G.add_edge(*edge_nodes, **new_dict)
                seen_edges.add(edge_nodes)
        elif graph_object == 'node':
            G.add_node(node_or_edge, **new_dict)
        else:
            log.warning('Expanded graph node ignored as it has no `graph type', type='conn', node=node_or_edge)
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

    def __hash__(self):
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

    def set_properties_from_feature(self, feature: Feature):
    #=======================================================
        self.map_feature = feature
        self.properties.update(feature.properties)
        self.properties['geometry'] = feature.geometry
        if feature.geometry is not None:
            centre = feature.geometry.centroid
            self.properties['centre'] = BezierPoint(centre.x, centre.y)
            radius = max(math.sqrt(feature.geometry.area/math.pi), MIN_EDGE_JOIN_RADIUS)
            self.properties['radii'] = (0.999*radius, 1.001*radius)
        else:
            log.warning('Centreline node has no geometry', type='conn', node=feature.id)

#===============================================================================

class Network(object):
    def __init__(self, flatmap: 'FlatMap', network: dict, properties_store: Optional['PropertiesStore']=None):
        self.__flatmap = flatmap
        self.__id = network.get('id')
        self.__type = network.get('type', 'nerve')
        self.__log = typing.cast(structlog.BoundLogger, log.bind(type='network', network=self.__id))

        self.__centreline_models: dict[str, str] = {}                              #! Centreline id --> models
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
        self.__centreline_graph = nx.MultiGraph()                                   #! Can have multiple paths between nodes which will be contained in different features
        self.__containers_by_segment: dict[str, set[str]] = defaultdict(set)        #! Segment id --> set of features that segment is contained in
        self.__centrelines_by_containing_feature = defaultdict(set)                 #! Feature id --> set of centrelines that are contained in feature
        self.__expanded_centreline_graph: Optional[nx.Graph] = None                 #! Expanded version of centreline graph
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
                                self.__log.error('Contained-in feature of centreline does not have an anatomical term',
                                    feature=feature_id, centreline=centreline_id)
                            elif (models := properties_store.nerve_models_by_id.get(feature_id)) is None:
                                contained_in.append(feature_id)
                            elif centreline_models is None:
                                self.__log.warning('Contained-in feature used as nerve model of its centreline',
                                    feature=feature_id, centreline=centreline_id)
                                centreline['models'] = models
                            elif models == centreline_models:
                                self.__log.warning('Contained-in feature also models nerve of its centreline',
                                    feature=feature_id, centreline=centreline_id)
                            elif models != centreline_models:
                                self.__log.error('Contained-in feature models a different nerve than its centreline',
                                    feature=feature_id, centreline=centreline_id)
                        centreline['contained-in'] = contained_in

        # Collect centreline and end node identifiers, checking validity
        centrelines_by_end_feature = defaultdict(set)
        for centreline in network.get('centrelines', []):
            centreline_id = centreline.get('id')
            if centreline_id is None:
                self.__log.error('Centreline in network does not have an id')
            elif centreline_id in self.__centreline_nodes:
                self.__log.error('Centreline in network has a duplicate id', centreline=centreline_id)
            else:
                self.__add_feature(centreline_id)
                if (centreline_models := centreline.get('models')) is not None:
                    self.__models_to_id[centreline_models].add(centreline_id)
                    # If we have ``properties_store`` without ``centreline_models`` annotation for the centreline then set it
                    if properties_store is not None:
                        properties_store.set_property(centreline_id, 'centreline', True)
                        if (models := properties_store.get_property(centreline_id, 'models')) is None:
                            properties_store.set_property(centreline_id, 'models', centreline_models)
                        elif centreline_models != models:
                            self.__log.error('Centreline models both two entities', entities=[centreline_models, models],
                                 centreline=centreline_id)
                        if (nerve_id := properties_store.nerve_ids_by_model.get(centreline_models)) is not None:
                            # Assign nerve cuff id to centreline
                            properties_store.set_property(centreline_id, 'nerve', nerve_id)
                elif properties_store is not None:
                    properties_store.set_property(centreline_id, 'centreline', True)
                    if (centreline_models := properties_store.get_property(centreline_id, 'models')) is not None:
                        # No ``models`` are directly specified for the centreline so assign what we've found
                        centreline['models'] = centreline_models
                    elif (centreline_label := centreline.get('label')) is not None:
                        properties_store.set_property(centreline_id, 'label', centreline_label)
                if centreline_models is not None:
                    self.__models_to_id[centreline_models].add(centreline_id)
                    self.__centreline_models[centreline_id] = centreline_models

                # Check connected nodes
                connected_nodes = centreline.get('connects', [])
                if len(connected_nodes) < 2:
                    self.__log.error('Centreline in network has too few nodes', centreline=centreline_id)
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
                        if properties_store is not None:
                            if (properties_store.get_property(node_id, 'models') is None
                            and properties_store.get_property(node_id, 'label') is None):
                                properties_store.set_property(node_id, 'node', True)
                    self.__containers_by_centreline[centreline_id] = set(centreline.get('contained-in', []))
                    end_nodes_to_centrelines[connected_nodes[0]].append(centreline_id)
                    end_nodes_to_centrelines[connected_nodes[-1]].append(centreline_id)
                    for node_id in connected_nodes[1:-1]:
                        intermediate_nodes_to_centrelines[node_id].append(centreline_id)

        # Check for multiple branches and crossings
        for node, centrelines in intermediate_nodes_to_centrelines.items():
            if len(centrelines) > 1:
                self.__log.error('Node is intermediate node for more than several centrelines',
                                 node=node, centrelines=centrelines)
            if len(centrelines := end_nodes_to_centrelines.get(node, [])) > 1:
                self.__log.error('Intermediate node branches to several centrelines',
                                 node=node, centrelines=centrelines)

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
                    self.__log.warning('Container feature of centrelineis also an end node for other centrelines',
                                 feature=feature_id, centreline=centreline_id, centrelines=centrelines)

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
                self.__log.warning('Network feature cannot be found on the flatmap', feature=id)

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
            self.__log.error('Cannot find network feature', feature=feature_id)
            self.__missing_identifiers.add(feature_id)
        return None

    def create_geometry(self):
    #=========================
        def add_centreline_graph_node(network_node):
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
            if self.__centreline_graph.degree(node_id_0) >= 2:      # type: ignore
                if start_node_id == node_id_0:
                    # This assumes network_nodes[0] centre is close to segments[0].start
                    segments = truncate_segments_at_start(segments, network_nodes[0])
                else:
                    # This assumes network_nodes[-1] centre is close to segments[-1].end
                    segments = truncate_segments_at_end(segments, network_nodes[-1])
            if self.__centreline_graph.degree(node_1_id) >= 2:      # type: ignore
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
        self.__containers_by_segment = defaultdict(set)     #! Segment id --> set of features that segment is contained in
        self.__segment_edge_by_segment = {}
        self.__segment_ids_by_centreline = defaultdict(list)

        segment_edge_ids_by_centreline = defaultdict(list)

        for centreline_id, network_nodes in self.__centreline_nodes.items():
            if (centreline_feature := self.__map_feature(centreline_id)) is None:
                self.__log.warning('Centreline ignored, not on map', centreline=centreline_id)
                continue
            if (self.__map_feature(network_nodes[0].feature_id) is None
             or self.__map_feature(network_nodes[-1].feature_id) is None):
                self.__log.error('Centreline ignored, end nodes are not on map', centreline=centreline_id)
                centreline_feature.set_property('exclude', not settings.get('authoring', False))
                continue

            # Set centreline type to that of the network
            if self.__type is not None:
                centreline_feature.set_property('type', self.__type)

            # Set network node properties
            valid_nodes = []
            for network_node in network_nodes:
                feature = self.__map_feature(network_node.feature_id)
                if feature is not None:
                    valid_nodes.append(network_node)
                    network_node.set_properties_from_feature(feature)
            network_nodes = valid_nodes
            self.__centreline_nodes[centreline_id] = valid_nodes

            bz_path = BezierPath.fromSegments(centreline_feature.get_property('bezier-segments'))

            # A node's centre may not be where a centreline into the node finishes
            # so check both ends of the Bezier path to decide the curve's direction
            node_0_centre = network_nodes[0].centre
            node_1_centre = network_nodes[-1].centre
            min_distance = None
            coords = (0, 0)
            for n, centre in enumerate([node_0_centre, node_1_centre]):
                for m, t in enumerate([0.0, 1.0]):
                    distance = centre.distanceFrom(bz_path.pointAtTime(t))      # type: ignore
                    if min_distance is None or distance < min_distance:
                        min_distance = distance
                        coords = (n, m)
            path_reversed = (coords[0] != coords[1])
            if path_reversed:
                centreline_feature.geometry = centreline_feature.geometry.reverse()

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
                add_centreline_graph_node(start_node)
                add_centreline_graph_node(end_node)

                # Add an edge to the segmented centreline graph
                edge_feature_ids = (start_node.feature_id, end_node.feature_id)
                key = self.__centreline_graph.add_edge(*edge_feature_ids, id=edge_feature_ids,
                                                       centreline=centreline_id, segment=segment_id)

                path_start_node = end_node if path_reversed else start_node
                path_end_node = start_node if path_reversed else end_node

                # Split the current Bezier path at the segment boundary and return the remainder
                (cl_path, bz_path) = split_bezier_path_at_point(bz_path, path_end_node.centre)  # type: ignore

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
                    self.__log.error('Centreline nodes are out of sequence...', centreline=segment_id)
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
                                    self.__log.warning('Intermediate node has multiple intersections with centreline',
                                                       node=node_id, centreline=segment_id)
                                else:
                                    intersection_points.append(sorted((closest_time_distance(bz_segment, coords_to_point((pt.x, pt.y)))[0]
                                                                                for pt in intersecting_points)))
                        if len(intersection_points) == 0:
                            self.__log.warning("Intermediate node doesn't intersect centreline",
                                               node=node_id, centreline=segment_id)
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
                            self.__log.error('Node only intersects once with centreline', node=node_id, centreline=edge_id)
                    else:
                        # path crosses feature
                        if prev_intersection is not None and prev_intersection[0] >= times[0]:
                            self.__log.error('Intermediate nodes overlap on centreline', nodes=[prev_intersection[1], node_id], centreline=edge_id)
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
                self.__log.error('Last intermediate node on centreline only intersects once', node=last_intersection[1], centreline=edge_id)
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

    def route_graph_from_path(self, path: 'Path') -> Optional[nx.Graph]:
    #===================================================================
        return self.__route_graph_from_connectivity(path)

    def layout(self, route_graphs: dict[str, nx.Graph]) -> dict[int, RoutedPath]:
    #============================================================================
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
        if (matched:=self.__flatmap.features_for_anatomical_node(connectivity_node, warn=True)) is not None:
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
                self.__log.error('Node has centreline inside layers', name=connectivity_node.full_name)
            properties.update(self.__segment_properties_from_ids(centreline_ids))

        elif matched is not None:
            properties['name'] = matched[0].name
            features = set(f for f in matched[1] if f.id is not None and not f.get_property('unrouted', False))
            if len(features):
                properties['type'] = 'feature'
                properties['features'] = features
            elif connectivity_node not in self.__missing_identifiers:
                properties['warning'] = {
                    'msg': 'Cannot find feature for connectivity node',
                    'node': connectivity_node,
                    'name': connectivity_node.full_name
                    }
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

    def __route_graph_from_connectivity(self, path: 'Path', debug=False) -> Optional[nx.Graph]:
    #==========================================================================================
        connectivity_graph = path.connectivity

        # Map connectivity nodes to map features and centrelines, storing the result
        # in the connectivity graph
        for node, node_dict in connectivity_graph.nodes(data=True):
            node_dict.update(self.__feature_properties_from_node(node))
            if (warning := node_dict.pop('warning', None)) is not None:
                if (msg := warning.pop('msg', None)) is not None:
                    self.__log.warning(msg, **warning)

        def bypass_missing_node(ms_node):
            if len(neighbours:=list(connectivity_graph.neighbors(ms_node))) > 1:
                predecessors, successors = [], []
                for neighbour in neighbours:
                    if neighbour == connectivity_graph.edges[(ms_node, neighbour)]['predecessor']:
                        predecessors += [neighbour]
                    elif neighbour == connectivity_graph.edges[(ms_node, neighbour)]['successor']:
                        successors += [neighbour]
                if len(predecessors) == 0 or len(successors) == 0:
                    predecessors =neighbours
                    successors = neighbours
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

        # Removing missing nodes (in FC and AC)
        if settings.get('NPO', False):
            missing_nodes = [c for c in connectivity_graph.nodes if c in self.__missing_identifiers]
            for ms_node in missing_nodes:
                bypass_missing_node(ms_node)

        # Merging duplicate nodes due to aliasing
        if settings.get('NPO', False):
            group_nodes = {}
            for node, node_dict in connectivity_graph.nodes(data=True):
                if (att_node:=node_dict['node']) not in group_nodes:
                    group_nodes[att_node] = []
                group_nodes[att_node] += [node]
            for g_node, ref_nodes in group_nodes.items():
                if len(ref_nodes) > 1:
                    if g_node in ref_nodes:
                        ref_nodes.remove(g_node)
                    else:
                        g_node = ref_nodes[0]
                        ref_nodes = ref_nodes[1:]
                    for ref_node in ref_nodes:
                        nx.contracted_nodes(connectivity_graph, g_node, ref_node, self_loops=False, copy=False)
                        for neighbor in connectivity_graph.neighbors(g_node):
                            for key in ('predecessor', 'successor'):
                                if connectivity_graph[g_node][neighbor].get(key) == ref_node:
                                    connectivity_graph[g_node][neighbor][key] = g_node

        if path.trace:
            for node, node_dict in connectivity_graph.nodes(data=True):
                node_data = {}
                if node_dict['type'] == 'feature':
                    node_data['features'] = {f.id for f in node_dict['features']}
                elif node_dict['type'] == 'segment':
                    node_data['segments'] = node_dict['subgraph'].graph['segment-ids']
                log.info('Connectivity for node', type='trace', path=path.id, node=node, data=node_data)
            log.info('Connectivity edges', type='trace', path=path.id, edges=connectivity_graph.edges)

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
                            self.__log.error('Adjacent connectivity nodes are identical!', path=path.id, nodes=node_dict["name"])
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

        # Create the route graph for the connectivity path
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
        node_with_segments = {}
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
                    node_with_segments[node] = segment_graph
                else:
                    self.__log.warning('Cannot find any sub-segments of centreline', path=path.id, entity=node_dict['name'])
                    node_dict['type'] = 'no-segment'
                    no_sub_segment_nodes += [node] # store node with undecided sub-segments

        # Handles unidentified segments related to centerline type nodes
        # Looks for the closest feature to the connected node, then determines the segments
        new_direct_edges = set()
        tmp_edge_dicts = {}
        for node in no_sub_segment_nodes:
            segment_graph = connectivity_graph.nodes[node]['subgraph']
            if segment_graph.number_of_edges() > 1:
                neighbouring_ids = set()
                updated_neighbouring_ids = set()
                closest_feature_dict = {}  # .geometry.centroid.distance sometime is inconsistent
                for neighbour in connectivity_graph.neighbors(node):
                    neighbour_dict = connectivity_graph.nodes[neighbour]
                    if len(neighbour_dict.get('contains', set())) > 0:
                        neighbour_dict = connectivity_graph.nodes[next(iter(neighbour_dict['contains']))]
                    edge_dict = connectivity_graph.edges[(node, neighbour)]
                    if neighbour_dict['type'] == 'feature':
                        # if the node is a no-segment and neighbour is a terminal, connect to all neighbour features
                        # else connect to one closest no_segment point and neighbour feature.
                        features = (
                            neighbour_dict['features']
                            if len(neighbour_dict['features']) <= 2
                            else sorted(neighbour_dict['features'], key=lambda f: f.id)[:1]
                        )
                        for feature in features:
                            neighbouring_ids.update([feature.id])
                            closest_feature_id = None
                            for n, s in itertools.product([feature.id], segment_graph.nodes):
                                if (edge_dicts := self.__centreline_graph.get_edge_data(n, s)) is not None:
                                    closest_feature_dict[n] = s
                                    tmp_edge_dicts[(n, s)] = edge_dicts[0]
                                    break
                            if feature.id not in closest_feature_dict:
                                closest_feature_id = self.__closest_feature_id_to_point(feature.geometry.centroid, segment_graph.nodes)
                                closest_feature_dict[feature.id] = closest_feature_id
                                tmp_edge_dicts[(feature.id, closest_feature_id)] = edge_dict
                    elif neighbour_dict['type'] in ['segment', 'no-segment']: # should check this limitation
                        candidates= {}
                        for n, s in itertools.product(neighbour_dict['subgraph'].nodes, segment_graph.nodes):
                            if (nf:=self.__map_feature(n)) is not None and (sf:=self.__map_feature(s)) is not None:
                                candidates[(n,s)] = nf.geometry.centroid.distance(sf.geometry.centroid)
                            tmp_edge_dicts[(n,s)] = edge_dict
                        if len(candidates) > 0:
                            selected_c = min(candidates, key=candidates.get)    # type: ignore
                            neighbouring_ids.update([selected_c[0]])
                            closest_feature_dict[selected_c[0]] = selected_c[1]
                for n_id in neighbouring_ids:
                    if n_id in segment_graph:
                        updated_neighbouring_ids.update([n_id])
                    else:
                        if self.__map_feature(n_id) is not None:
                            if (closest_feature_id:=closest_feature_dict.get(n_id)) is not None:
                                updated_neighbouring_ids.update([closest_feature_id])
                                new_direct_edges.update([(n_id, closest_feature_id)])
                segment_graph = graph_utils.get_connected_subgraph(segment_graph, updated_neighbouring_ids)
            if segment_graph.number_of_edges():
                # Add segment edges used by our path to the route
                add_route_edges_from_graph(segment_graph, {node})

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
                                        self.__log.warning('Multiple centrelines between features',
                                                           path=path.id, features=[node_feature.id, neighbouring_feature.id])
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
                log.info('Search between features with containers',
                         type='trace', path=path.id, start_features=start_feature_ids, end_features=end_feature_ids,
                         containers=feature_ids)
            candidate_contained_centrelines = set()
            for feature_id in feature_ids:
                candidate_contained_centrelines.update(self.__centrelines_by_containing_feature.get(feature_id, set()))
            if path.trace:
                log.info('Candidates', type='trace', path=path.id, candidates=candidate_contained_centrelines)
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
                    log.info('Score for centreline', type='trace', path=path.id, score=score, centreline=centreline_id)
                if score > max_score:
                    matched_centreline = centreline_id
                    max_score = score
            if matched_centreline is not None:
                if path.trace:
                    log.info('Selected centreline', type='trace', path=path.id, score=max_score, centreline=matched_centreline)
                properties = (self.__segment_properties_from_ids([matched_centreline]))
                path_nerve_ids.update(properties['nerve-ids'])
                add_route_edges_from_graph(properties['subgraph'], used_nodes)

                # Need to connect two consecutive centrelines, even though they don't share any common features.
                for se_dict in [start_dict, end_dict]:
                    if se_dict.get('type') == 'segment' and \
                        len(se_dict.get('used', {})) > 0 and \
                        len(se_dict.get('used', {}) & set(properties['subgraph'].nodes)) == 0:
                            candidates= {(n, s):self.__flatmap.get_feature(n).geometry.centroid.distance(self.__flatmap.get_feature(s).geometry.centroid)
                                         for n, s in itertools.product(se_dict.get('used', set()), properties['subgraph'].nodes)}
                            if len(candidates) > 0:
                                if len(selected:=min(candidates, key=candidates.get)) == 2:
                                    for n, s in itertools.product([se_dict['node']], used_nodes):
                                        if (n, s) in connectivity_graph.edges:
                                            edge_dict = connectivity_graph.edges[(n, s)]
                                            tmp_edge_dicts[selected] = edge_dict
                                            new_direct_edges.update([selected])
                                            break

        for ends, list_path_nodes in graph_utils.connected_paths(connectivity_graph).items():
            for path_nodes in list_path_nodes:
                feature_ids = set()
                used_nodes = set()
                start_dict = connectivity_graph.nodes[ends[0]]
                prev_node = None
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

                    # two centerline nodes that do not have a sharing feature must be connected.
                    if prev_node is not None:
                        if len(pn_used:=connectivity_graph.nodes[prev_node]['used']) and len(n_used:=node_dict['used']):
                            if len(pn_used - n_used) == len(pn_used):
                                edge_dict = connectivity_graph.edges[(prev_node, node)]
                                candidates= {}
                                for n, s in itertools.product(pn_used, n_used):
                                    if (nf:=self.__map_feature(n)) is not None and (sf:=self.__map_feature(s)) is not None:
                                        candidates[(n,s)] = nf.geometry.centroid.distance(sf.geometry.centroid)
                                    tmp_edge_dicts[(n,s)] = edge_dict
                                if len(candidates) > 0:
                                    new_direct_edges.update([min(candidates, key=candidates.get)])  # type: ignore
                        elif ((p_dict:=connectivity_graph.nodes[prev_node])['type'] == 'feature' and 
                              (n_dict:=connectivity_graph.nodes[node])['type'] == 'feature'):
                            if ((pf:=list(p_dict.get('features'))[0].id) in route_graph.nodes and
                                (nf:=list(n_dict.get('features'))[0].id) in route_graph.nodes):
                                edge_dict = connectivity_graph.edges[(prev_node, node)]
                                tmp_edge_dicts[(pf, nf)] = edge_dict
                                new_direct_edges.update([(pf, nf)])
                    prev_node = node

                if len(feature_ids):
                    get_centreline_from_containing_features(start_dict, connectivity_graph.nodes[ends[1]], feature_ids, used_nodes)

        # Now see if unconnected centreline end nodes in the route graph are in fact connected
        # by a centreline
        new_edge_dicts = {}
        for node_0, node_1 in itertools.combinations(route_graph.nodes, 2):
            if (not route_graph.has_edge(node_0, node_1)
            and (edge_dicts := self.__centreline_graph.get_edge_data(node_0, node_1)) is not None):
                if len(edge_dicts) > 1:
                    self.__log.warning('Multiple centrelines between nodes', path=path.id, nodes=[node_0, node_1])
                new_edge_dicts[(node_0, node_1)] = edge_dicts[list(edge_dicts)[0]]
        for edge, edge_dict in new_edge_dicts.items():
            route_graph.add_edge(*edge, **edge_dict)
            path_node_ids.update(node.feature_id for node in edge_dict['network-nodes'])

        def get_ftu_node(feature: Feature):
            # looking for FTU if possible
            if feature.properties.get('fc-class') != FC_CLASS.FTU:
                for child in feature.properties.get('children', []):
                    child_feature = self.__flatmap.get_feature_by_geojson_id(child)
                    if (child_feature is not None
                    and child_feature.properties.get('fc-class') == FC_CLASS.FTU
                    and child_feature.models == feature.models):
                        feature = child_feature
                        break
            # looking for correct connector or port
            for child in feature.properties.get('children', []):
                child_feature = self.__flatmap.get_feature_by_geojson_id(child)
                if (child_feature is not None
                and child_feature.properties.get('fc-kind') in [FC_KIND.CONNECTOR_NODE, FC_KIND.CONNECTOR_PORT, FC_KIND.GANGLION]
                and path.path_type is not None
                and (child_path_type := child_feature.properties.get('path-type')) != PATH_TYPE.UNKNOWN
                and child_path_type is not None
                and (child_path_type == path.path_type
                  or PATH_TYPE.PRE_GANGLIONIC|child_path_type == path.path_type
                  or PATH_TYPE.POST_GANGLIONIC|child_path_type == path.path_type)):
                    return child_feature
            return feature

        # select the closest feature of a node with multiple features to it's neighbors
        def get_node_feature(node_dict, neighbour_features, used_features) -> Feature:
            (features:=list(f for f in node_dict['features'])).sort(key=lambda f: f.id)
            selected_feature = features[0]
            # in a case of a terminal node having multiple features, select the closest one to it's neighbour_features
            if len(features) > 1:
                self.__log.error('Terminal node has multiple features', path=path.id, entity=node_dict['name'],
                                 features=sorted(set(f.id for f in node_dict["features"])))
                if selected_feature.properties.get('fc-class') is None:
                    feature_distances = {}
                    if len(neighbour_features) > 0:
                        for f in features:
                            distances = []
                            for nf in neighbour_features:
                                distances += [nf.geometry.centroid.distance(f.geometry.centroid)]
                            feature_distances[f] = sum(distances)/len(distances)
                        selected_feature = min(feature_distances, key=feature_distances.get)    # type: ignore
                else:
                    prev_features = [feature for features in used_features.values() for feature in features]
                    if len(prev_features) > 0 and len(features) > 1:
                        min_distance = prev_features[-1].geometry.centroid.distance(features[0].geometry.centroid)
                        for f in (features:=[f for f in features[1:]]):
                            if (distance:=prev_features[-1].geometry.centroid.distance(f.geometry.centroid)) < min_distance:
                                min_distance = distance
                                selected_feature = f
                    return get_ftu_node(selected_feature)
            return selected_feature

        # handling connectivity with no centreline and no terminal
        pseudo_terminals = []
        if route_graph.size() == 0 and len([node for node, degree in connectivity_graph.degree() if degree == 1]) == 0:
            pseudo_terminals += list(connectivity_graph.nodes)[0:1]
        # handling centrelines connected to subgraph with no terminal
        centrelines = list(node_with_segments.keys()) + no_sub_segment_nodes
        (temp_connectivity_graph := nx.Graph(connectivity_graph)).remove_nodes_from(centrelines)
        subgraphs = [temp_connectivity_graph.subgraph(component) for component in nx.connected_components(temp_connectivity_graph)]
        for subgraph in subgraphs:
            if len([node for node in subgraph.nodes if connectivity_graph.degree[node] == 1]) == 0:
                pseudo_terminals += list(subgraph.nodes)[0:1]

        # sorting nodes with priority -> terminal, number of features (2 than 1, than any size), distance to neighbours
        one_feature_terminals = {
            n: min([
                features[0].geometry.centroid.distance(nf.geometry.centroid)
                for nf in nfs
            ])
            for n, n_dict in connectivity_graph.nodes(data=True)
            if connectivity_graph.degree(n) == 1
                and len(features := list(n_dict.get("features", []))) == 1
                and len(nfs:= [
                    nf for neighbour in connectivity_graph.neighbors(n)
                        for nf in (
                            connectivity_graph.nodes[neighbour].get("features", set()) |
                            {self.__flatmap.get_feature(f_id) for f_id in connectivity_graph.nodes[neighbour].get("used", set())}
                        )
                    ]) > 0
        }
        one_feature_terminals = dict(sorted(one_feature_terminals.items(), key=lambda item: item[1]))
        two_feature_terminals = [
            n for n, n_dict in connectivity_graph.nodes(data=True)
            if len(n_dict.get("features", [])) == 2 and connectivity_graph.degree(n) == 1
        ]
        sorted_nodes = (
            two_feature_terminals +
            list(one_feature_terminals.keys()) +
            [n for n in connectivity_graph if n not in two_feature_terminals and n not in one_feature_terminals]
        )

        terminal_graphs: dict[tuple, nx.Graph] = {}
        visited = set()
        used_features = {}
        for node in sorted_nodes:
            node_dict = connectivity_graph.nodes[node]
            if node not in visited and (connectivity_graph.degree(node) == 1 or node in pseudo_terminals):
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
                                elif (neighbour_dict['type'] == 'feature'
                                    and len(neighbour_dict.get('used', set())) == 0
                                    and len(children:=neighbour_dict.get('contains', set())) > 0):
                                    # Replace the neighbour by it's children if the node is a downstream
                                    neighbours.update(set(children) - set(visited))
                                    neighbours.remove(neighbour)
                            # Connect to each neighbour of interest, noting those that will
                            # then need connecting
                            neighbours_neighbours = []
                            for neighbour in (neighbours - visited):
                                neighbour_dict = connectivity_graph.nodes[neighbour]
                                degree = connectivity_graph.degree(neighbour)
                                neighbour_features = neighbour_dict.get('features', set()) | {self.__flatmap.get_feature(f_id) for f_id in neighbour_dict.get('used', set())}
                                node_features = (
                                    [get_node_feature(node_dict, neighbour_features, used_features)]
                                    if len(node_dict['features']) != 2
                                    else used_features.get(node, set())
                                    if connectivity_graph.degree(node) > 1 and len(used_features.get(node, set())) in [1, 2]
                                    else set(node_dict['features'])
                                    if connectivity_graph.degree(node) == 1
                                    else [get_node_feature(node_dict, neighbour_features, used_features)]
                                )
                                for node_feature in node_features:
                                    used_features.setdefault(node, set()).add(node_feature)
                                    node_feature_centre = node_feature.geometry.centroid
                                    debug_properties = connectivity_graph.get_edge_data(node, neighbour) or {}
                                    if neighbour_dict['type'] == 'feature':
                                        terminal_graph.add_node(node_feature.id, feature=node_feature)
                                        if len(used_ids := neighbour_dict.get('used', set())):
                                            closest_feature_id = self.__closest_feature_id_to_point(node_feature_centre, used_ids)
                                            terminal_graph.add_edge(node_feature.id, closest_feature_id,
                                                upstream=True, **debug_properties)
                                            segments = set()
                                            for connected_edges in route_graph[closest_feature_id].values():
                                                for edge_dict in connected_edges.values():
                                                    if (segment_id := edge_dict.get('segment')) is not None:
                                                        segments.add(segment_id)
                                            terminal_graph.nodes[closest_feature_id]['upstream'] = True
                                            terminal_graph.nodes[closest_feature_id]['segments'] = segments
                                        else:
                                            neighbour_terminal_laterals = [
                                                k for k in connectivity_graph[neighbour]
                                                if connectivity_graph.degree(k) == 1 and len(connectivity_graph.nodes[k].get('features', [])) == 2
                                            ]
                                            neighbour_features = (
                                                neighbour_dict.get('features', [])
                                                if len(neighbour_dict.get('features', [])) <= 2 and degree == 1 and len(node_features) == 1
                                                else [get_node_feature(neighbour_dict, [node_feature], used_features)]
                                                if len(neighbour_terminal_laterals) > 0 and len(used_features.get(neighbour, set())) == 0
                                                else [get_node_feature(neighbour_dict, [node_feature], used_features)]
                                            )
                                            for neighbour_feature in neighbour_features:
                                                used_features.setdefault(neighbour, set()).add(neighbour_feature)
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
                                            terminal_graph.add_edge(node_feature.id, closest_feature_id, upstream=True, **debug_properties)
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
            log.info('Terminal connections', type='trace', path=path.id)
            for terminal_graph in terminal_graphs.values():
                for n_0, nd in terminal_graph.nodes(data=True):
                    log.info('Node', type='trace', path=path.id, node=n_0, data=nd)
                for n_0, n_1, ed in terminal_graph.edges(data=True):
                    log.info('Edge', type='trace', path=path.id, edge=[n_0, n_1], data=ed)

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
                    self.__log.warning('Feature has no geometry', path=path.id, feature=feature.id)
            return node_dict

        tmp_route_graph = nx.Graph(route_graph)
        # Now add edges from the terminal graphs to the path's route graph
        for terminal_graph in terminal_graphs.values():
            for node_0, node_1, upstream in terminal_graph.edges(data='upstream'):
                if node_0 in route_graph.nodes and node_1 in route_graph.nodes:
                    # no need to add an edge that is already contained in centreline
                    if node_0 in tmp_route_graph.nodes and node_1 in tmp_route_graph.nodes:
                        if node_0 == node_1 or len(list(nx.all_simple_paths(tmp_route_graph, node_0, node_1))) > 0:
                            continue
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
        route_graph.graph['label'] = path.label
        route_graph.graph['path-type'] = path.path_type
        route_graph.graph['source'] = path.source
        route_graph.graph['traced'] = path.trace
        route_graph.graph['nerve-features'] = set(feature_id for feature_id in path_nerve_ids if self.__map_feature(feature_id) is not None)
        route_graph.graph['node-features'] = set(feature_id for feature_id in path_node_ids if self.__map_feature(feature_id) is not None)
        if 'alert' in connectivity_graph.graph:
            route_graph.graph['alert'] = connectivity_graph.graph['alert']
        if 'biological-sex' in connectivity_graph.graph:
            route_graph.graph['biological-sex'] = connectivity_graph.graph['biological-sex']

        if path.trace:
            log.info('Route graph', type='trace', path=path.id, graph=route_graph.graph)
            for n_0, n_1, ed in route_graph.edges(data=True):
                log.info('Edge', type='trace', path=path.id, edge=[n_0, n_1], centreline=ed.get("centreline"))

        # Adds direct edges to graph routes for nodes connected to unidentified segments
        def set_direction(upstream_node):
            if 'direction' in route_graph.nodes[upstream_node]:
                return
            segment_ids = route_graph.nodes[upstream_node].get('segments', set())
            if len(segment_ids:=route_graph.nodes[upstream_node].get('segments', set())) > 0:
                # We want the path direction we were going when we reached the upstream node
                direction = 0.0
                for segment_id in segment_ids:
                    direction += route_graph.nodes[upstream_node]['edge-direction'][segment_id]
                route_graph.nodes[upstream_node]['direction'] = direction/len(segment_ids)
            elif 'edge-direction' in route_graph.nodes[upstream_node]:
                route_graph.nodes[upstream_node]['direction'] = list(route_graph.nodes[upstream_node]['edge-direction'].items())[0][1]
            else:
                route_graph.nodes[upstream_node]['direction'] = 0.0

        tmp_route_graph = nx.Graph(route_graph)
        tmp_route_graph.add_edges_from(new_direct_edges)
        for node_0, node_1 in new_direct_edges:
            if (node_0, node_1) in route_graph.edges:
                continue
            if node_0 not in route_graph:
                route_graph.add_node(node_0, type='terminal')
            if node_1 not in route_graph:
                route_graph.add_node(node_1, type='terminal')
            if (node_0, node_1) in tmp_edge_dicts:
                node_0_prop = set_properties_from_feature_id(node_0)
                node_1_prop = set_properties_from_feature_id(node_1)
                if 'centreline' in tmp_edge_dicts[(node_0, node_1)]:
                    route_graph.add_edge(node_0, node_1 , **tmp_edge_dicts[(node_0, node_1)])
                    route_graph.nodes[node_0].update({'network_node':tmp_edge_dicts[(node_0, node_1)]['network-nodes'][0]})
                elif 'network_node' not in route_graph.nodes[node_0] and 'network_node' not in route_graph.nodes[node_1]:
                    route_graph.add_edge(node_0, node_1, type='terminal', **tmp_edge_dicts[(node_0, node_1)])
                else:
                    route_graph.add_edge(node_0, node_1, type='upstream', upstream=True , **tmp_edge_dicts[(node_0, node_1)])
                    upstream_node = node_0
                    route_graph.nodes[upstream_node]['type'] = 'upstream'
                    set_direction(upstream_node)
                route_graph.nodes[node_0].update(node_0_prop)
                route_graph.nodes[node_1].update(node_1_prop)

        # connects the remaining centerlines that have edges to terminal nodes but are not yet connected
        for node, segment_graph in node_with_segments.items():
            if len(neighbours:=list(connectivity_graph.neighbors(node))) > 0:
                if len(end_nodes:=[n for n in segment_graph.nodes if route_graph.degree(n) < 2]) > 1:
                    for neighbour in neighbours:
                        if 'features' in connectivity_graph.nodes[neighbour]:
                            n_features = list(connectivity_graph.nodes[neighbour]['features'])
                            if connectivity_graph.nodes[neighbour]['type'] == 'feature' and len(n_features) > 0:
                                if n_features[0].id not in route_graph.nodes:
                                    route_graph.add_node(n_features[0].id, type='terminal')
                                closest_feature_id = self.__closest_feature_id_to_point(n_features[0].geometry.centroid, end_nodes)
                                if (closest_feature_id, n_features[0].id) in route_graph.edges: continue
                                route_graph.add_edge(closest_feature_id, n_features[0].id, type='terminal',
                                                    **connectivity_graph.edges[(node, neighbour)])
                                route_graph.nodes[closest_feature_id]['type'] = 'terminal'
                                route_graph.nodes[n_features[0].id].update(set_properties_from_feature_id(n_features[0].id))

        # checking looping paths, remove if connectivity_graph doesn't require it
        # this could be caused by unnecesary centrelines
        for edge in new_edge_dicts:
            if len(simple_paths:=sorted(list(nx.all_simple_paths(tmp_route_graph, source=edge[0], target=edge[1])), key=len, reverse=True)) > 1:
                matching_nodes = {
                    n:sp for sp in simple_paths
                    for n, data in connectivity_graph.nodes(data=True)
                    if set(data.get('features', data.get('used', []))) & set(sp)
                }
                if len(mn_keys:=list(matching_nodes.keys())) == 2:
                    simple_node_paths = list(nx.all_simple_edge_paths(connectivity_graph, source=mn_keys[0], target=mn_keys[1]))
                    while len(simple_paths) > len(simple_node_paths):
                        route_graph.remove_edges_from([simple_paths.pop()])

        centreline_ids = set()
        for node_0, node_1, edge_dict in nx.Graph(route_graph).edges(data=True):
            # remove self loops due to generalisation
            if node_0 == node_1 and route_graph.has_edge(node_0, node_1):
                route_graph.remove_edge(node_0, node_1)
            elif (centreline_id := edge_dict.get('centreline')) is not None:
                centreline_ids.add(centreline_id)

        # The centrelines used by the path
        route_graph.graph['centrelines'] = list(centreline_ids)
        route_graph.graph['centrelines-model'] = [self.__centreline_models[id] for id in centreline_ids if id in self.__centreline_models]

        # Apply a filter to prevent incomplete paths from being rendered due to missing nodes in the flatmap.
        if len(connectivity_graph.nodes) > 0:
            min_degree = min(dict(path.connectivity.degree()).values())
            min_degree_nodes = set([node for node, degree in path.connectivity.degree() if degree == min_degree])
            if len(min_degree_nodes & set(self.__missing_identifiers)):
                self.__log.warning('Path is not rendered due to partial rendering', path=path.id)
                route_graph.remove_nodes_from(list(route_graph.nodes))
                connectivity_graph.remove_nodes_from(list(connectivity_graph.nodes))

        # Assign connectivity_node as a route_graph property, which will be used along with ResolvedPathways.
        route_graph.graph['connectivity'] = connectivity_graph

        if debug:
            return (route_graph, G, connectivity_graph, terminal_graphs)    # type: ignore
        else:
            return route_graph

#===============================================================================
