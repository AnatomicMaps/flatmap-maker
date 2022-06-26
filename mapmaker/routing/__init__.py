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
import math
from functools import partial


#===============================================================================

try:
    # Python 3.10
    from itertools import pairwise
except ImportError:
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

from mapmaker.flatmap.feature import full_node_name
from mapmaker.geometry.beziers import bezier_to_linestring, closest_time
from mapmaker.geometry.beziers import coords_to_point, point_to_coords
from mapmaker.settings import settings
from mapmaker.utils import log
import mapmaker.utils.graph as graph_utils

from .options import MIN_EDGE_JOIN_RADIUS
from .routedpath import IntermediateNode, PathRouter

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

#===============================================================================

class Network(object):
    def __init__(self, network: dict, external_properties):
        self.__id = network.get('id')
        self.__centreline_graph = nx.MultiGraph()   # Can have multiple paths between two nodes
        self.__centreline_ids = []
        self.__contained_centrelines = defaultdict(list)    #! Feature id --> centrelines contained in feature
        self.__contained_by_id = {}                         #! Centreline id --> set of features that centreline is contained in
        self.__edges_by_id = {}                             #! Centreline id --> edge
        self.__models_to_id = {}                            #! Ontological term --> centreline id
        self.__feature_ids = set()
        self.__feature_map = None  #! Assigned after ``maker`` has processed sources
        for centreline in network.get('centrelines', []):
            id = centreline.get('id')
            if id is None:
                log.error(f'Centreline in network {self.__id} does not have an id')
            elif id in self.__centreline_ids:
                log.error(f'Centreline {id} in network {self.__id} has a duplicated id')
            else:
                self.__feature_ids.add(id)
                if (models := centreline.get('models')) is not None:
                    if models in self.__models_to_id:
                        log.warning(f'Centrelines `{id}` and `{self.__models_to_id[models]}` both model {models}')
                    else:
                        self.__models_to_id[models] = id
                        if external_properties.get_property(id, 'models') is None:
                            external_properties.set_property(id, 'models', models)
                nodes = centreline.get('connects', [])
                if len(nodes) < 2:
                    log.warning(f'Centreline {id} in network {self.__id} has too few nodes')
                else:
                    self.__feature_ids.update(nodes)
                    self.__centreline_ids.append(id)
                    edge_properties = {'id': id}
                    if len(nodes) > 2:
                        edge_properties['intermediates'] = nodes[1:-1]
                    containing_features = set(centreline.get('contained-in', []))
                    self.__feature_ids.update(containing_features)
                    containing_features.update(nodes[1:-1])
                    if len(containing_features):
                        self.__contained_by_id[id] = containing_features
                    for container_id in containing_features:
                        self.__contained_centrelines[container_id].append(id)
                        if external_properties.get_property(container_id, 'type') == 'nerve':
                            edge_properties['nerve'] = container_id
                    key = self.__centreline_graph.add_edge(nodes[0], nodes[-1], **edge_properties)
                    self.__edges_by_id[id] = (nodes[0], nodes[-1], key)

    @property
    def id(self):
        return self.__id

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

    def __find_feature(self, id):
    #============================
        features = self.__feature_map.features(id)
        if len(features) == 1:
            return features[0]
        elif len(features) == 0:
            log.error('Cannot find network feature: {}'.format(id))
        else:
            log.warning('Multiple network features for: {}'.format(id))
        return None

    def __set_node_properties_from_feature(self, node_dict, feature_id):
    #===================================================================
        feature = self.__find_feature(feature_id)
        if feature is not None:
            if 'geometry' not in node_dict:
                for key, value in feature.properties.items():
                    node_dict[key] = value
                node_dict['geometry'] = feature.geometry
            geometry = node_dict.get('geometry')
            if geometry is not None:
                centre = geometry.centroid
                node_dict['centre'] = BezierPoint(centre.x, centre.y)
                radius = max(math.sqrt(geometry.area/math.pi), MIN_EDGE_JOIN_RADIUS)
                node_dict['radii'] = (0.999*radius, 1.001*radius)
            else:
                log.warning(f'Centreline node {node_dict.get("id")} has no geometry')

    def __node_centre(self, node):
    #=============================
        return self.__centreline_graph.nodes[node].get('centre')

    def __node_radii(self, node):
    #============================
        return self.__centreline_graph.nodes[node].get('radii')

    def create_geometry(self):
    #=========================
        def truncate_segments_start(segs, node):
            # This assumes node centre is close to segs[0].start
            node_centre = self.__node_centre(node)
            radii = self.__node_radii(node)
            if segs[0].start.distanceFrom(node_centre) > radii[0]:
                return segs
            n = 0
            while n < len(segs) and segs[n].end.distanceFrom(node_centre) < radii[0]:
                n += 1
            if n >= len(segs):
                return segs
            bz = segs[n]
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
            segs[n] = split[1]
            return segs[n:]

        def truncate_segments_end(segs, node):
            # This assumes node centre is close to segs[-1].end
            node_centre = self.__node_centre(node)
            radii = self.__node_radii(node)
            if segs[-1].end.distanceFrom(node_centre) > radii[0]:
                return segs
            n = len(segs) - 1
            while n >= 0 and segs[n].start.distanceFrom(node_centre) < radii[0]:
                n -= 1
            if n < 0:
                return segs
            bz = segs[n]
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
            segs[n] = split[0]
            return segs[:n+1]

        def time_scale(scale, T, x):
            return (scale(x) - T)/(1.0 - T)

        for node_id, degree in self.__centreline_graph.degree():
            node_dict = self.__centreline_graph.nodes[node_id]
            node_dict['degree'] = degree
            # Direction of a path at the node boundary, going towards the centre (radians)
            node_dict['edge-direction'] = {}
            # Angle of the radial line from the node's centre to a path's intersection with the boundary (radians)
            node_dict['edge-node-angle'] = {}
            # Set additional node attributes from its feature's geometry
            self.__set_node_properties_from_feature(node_dict, node_id)

        for node_0, node_1, edge_dict in self.__centreline_graph.edges(data=True):
            edge_id = edge_dict.get('id')
            feature = self.__find_feature(edge_id)
            if feature is not None:
                node_0_centre = self.__centreline_graph.nodes[node_0].get('centre')
                node_1_centre = self.__centreline_graph.nodes[node_1].get('centre')
                segments = feature.property('bezier-segments')

                if node_0_centre is None or node_1_centre is None:
                    log.warning(f'Centreline {feature.id} nodes are missing ({node_0} and/or {node_1})')
                    if len(segments) == 0:
                        log.warning(f'Centreline {feature.id} has no Bezier path')
                    segments = []
                elif len(segments) == 0:
                    log.warning(f'Centreline {feature.id} has no Bezier path')
                    segments = [ BezierLine(node_0_centre, node_1_centre) ]
                    start_node = node_0
                    end_node = node_1
                else:
                    start = segments[0].pointAtTime(0.0)
                    if start.distanceFrom(node_0_centre) <= start.distanceFrom(node_1_centre):
                        start_node = node_0
                        end_node = node_1
                    else:
                        start_node = node_1
                        end_node = node_0
                if segments:
                    if self.__centreline_graph.degree(node_0) >= 2:
                        if start_node == node_0:
                            # This assumes node_0 centre is close to segments[0].start
                            segments = truncate_segments_start(segments, node_0)
                        else:
                            # This assumes node_1 centre is close to segments[-1].end
                            segments = truncate_segments_end(segments, node_0)
                    if self.__centreline_graph.degree(node_1) >= 2:
                        if start_node == node_0:
                            # This assumes node_0 centre is close to segments[-1].end
                            segments = truncate_segments_end(segments, node_1)
                        else:
                            # This assumes node_1 centre is close to segments[0].start
                            segments = truncate_segments_start(segments, node_1)

                    # Save centreline geometry at its ends for use in drawing paths
                    edge_dict['start-node'] = start_node
                    # Direction is towards node
                    self.__centreline_graph.nodes[start_node]['edge-direction'][edge_id] = segments[0].startAngle + math.pi
                    self.__centreline_graph.nodes[start_node]['edge-node-angle'][end_node] = (
                                            (segments[0].pointAtTime(0.0) - self.__node_centre(start_node)).angle)

                    edge_dict['end-node'] = end_node
                    self.__centreline_graph.nodes[end_node]['edge-direction'][edge_id] = segments[-1].endAngle
                    self.__centreline_graph.nodes[end_node]['edge-node-angle'][start_node] = (
                                            (segments[0].pointAtTime(0.0) - self.__node_centre(end_node)).angle)

                    # Get the geometry of any intermediate nodes along an edge
                    intermediates = {}
                    for intermediate in edge_dict.get('intermediates', []):
                        feature = self.__find_feature(intermediate)
                        if feature is not None:
                            intermediates[intermediate] = feature.geometry

                    # Find where the centreline's segments cross intermediate nodes
                    intersection_times = {}
                    for seg_num, bz in enumerate(segments):
                        line = bezier_to_linestring(bz)
                        time_points = []
                        for node_id, geometry in intermediates.items():
                            if geometry.intersects(line):
                                intersection = geometry.boundary.intersection(line)
                                if isinstance(intersection, shapely.geometry.Point):
                                    time_points.append(((closest_time(bz, coords_to_point((intersection.x, intersection.y))), ),
                                                        node_id))
                                else:
                                    intersecting_points = intersection.geoms
                                    if len(intersecting_points) > 2:
                                        log.warning(f"Intermediate node {node_id} has multiple intersections with centreline {edge_id}")
                                    else:
                                        time_points.append((sorted((closest_time(bz, coords_to_point((pt.x, pt.y)))
                                                                                    for pt in intersecting_points)), node_id))
                        if len(time_points) > 0:
                            intersection_times[seg_num] = sorted(time_points)
                    if len(intermediates) > 0 and len(intersection_times) == 0:
                        log.warning(f"Intermediate node {node_id} doesn't intersect centreline {edge_id}")

                    path_components = []
                    last_intersection = None
                    for seg_num in range(len(segments)):
                        prev_intersection = None
                        bz = segments[seg_num]
                        scale = partial(time_scale, lambda x: x, 0.0)
                        node_intersections = intersection_times.get(seg_num, [])
                        intersection_num = 0
                        while intersection_num < len(node_intersections):
                            times, node_id = node_intersections[intersection_num]
                            if len(times) == 0:
                                continue
                            geometry = intermediates[node_id]
                            time_0 = scale(times[0])
                            if len(times) == 1:
                                if last_intersection is not None:
                                    assert node_id == last_intersection[1]
                                    # check times[0] < 0.5  ??
                                    parts = bz.splitAtTime(time_0)
                                    path_components.append(IntermediateNode(node_id, geometry, last_intersection[0].startAngle, parts[0].endAngle))
                                    bz = parts[1]
                                    scale = partial(time_scale, scale, time_0)
                                    last_intersection = None
                                elif (intersection_num + 1) == len(node_intersections):
                                    # check times[0] > 0.5 ??
                                    parts = bz.splitAtTime(time_0)
                                    path_components.append(parts[0])
                                    last_intersection = (parts[1], node_id)
                                else:
                                    log.error(f'Node {node_id} only intersects once with centreline {edge_id}')
                            else:
                                if prev_intersection is not None and prev_intersection[0] >= times[0]:
                                    log.error(f'Intermediate nodes {prev_intersection[1]} and {node_id} overlap on centreline {edge_id}')
                                else:
                                    parts = bz.splitAtTime(time_0)
                                    path_components.append(parts[0])
                                    bz = parts[1]
                                    scale = partial(time_scale, scale, time_0)
                                    time_1 = scale(times[1])
                                    parts = bz.splitAtTime(time_1)
                                    path_components.append(IntermediateNode(node_id, geometry, parts[0].startAngle, parts[0].endAngle))
                                    bz = parts[1]
                                    scale = partial(time_scale, scale, time_1)
                                prev_intersection = (times[1], node_id)
                            intersection_num += 1
                        if last_intersection is None:
                            path_components.append(bz)
                    if last_intersection is not None:
                        log.error(f'Last intermediate node {last_intersection[1]} on centreline {edge_id} only intersects once')
                    edge_dict['path-components'] = path_components

    def __route_graph_from_connections(self, path) -> nx.Graph:
    #==========================================================
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
                node = route_graph.nodes[terminal_id]
                self.__set_node_properties_from_feature(node, terminal_id)
                route_graph.edges[end_node, terminal_id]['type'] = 'terminal'
        return route_graph

    def route_graph_from_path(self, path):
    #=====================================
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

    def __route_graph_from_connectivity(self, path) -> nx.Graph:
    #===========================================================
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
            # First check if we can directly identify the centreline
            if (centreline := self.__models_to_id.get(connectivity_node[0])) is not None:
                return {
                    'node': connectivity_node,
                    'feature-id': centreline,
                    'centreline': centreline
                }
            features = self.__feature_map.find_path_features_by_anatomical_id(*connectivity_node)
            if len(features) == 0:
                return {'warning': f'Cannot find feature: {full_node_name(*connectivity_node)}'}
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
                                                result['warning'] = f'Node {feature_id} is close to both {closest_node} and {closest}'
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
            centreline_nodes = set()
            for centreline in centreline_set:
                centreline_nodes.update(self.__edges_by_id[centreline][0:2])

            node_terminals = defaultdict(set)   # node --> terminals
            seen_terminals = set()
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
                        self.__set_node_properties_from_feature(node_dict, terminal_id)

            # Add paths and nodes from connected connectivity sub-graph to result
            route_graph.add_nodes_from(route_paths.nodes(data=True))
            edge_key_count = defaultdict(int)
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
