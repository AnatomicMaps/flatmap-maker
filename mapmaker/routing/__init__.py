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

from pprint import pprint

#===============================================================================

from beziers.line import Line as BezierLine
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.geometry.beziers import bezier_to_linestring, closest_time
from mapmaker.geometry.beziers import coords_to_point, point_to_coords
from mapmaker.settings import settings
from mapmaker.utils import log

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
        self.__centreline_graph = nx.Graph()
        self.__centreline_ids = []
        self.__contained_centrelines = defaultdict(list)  #! Feature id --> centrelines contained in feature
        self.__contained_count = {}
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
                    self.__contained_count[id] = len(containing_features)
                    for container_id in containing_features:
                        self.__contained_centrelines[container_id].append(id)
                        if external_properties.get_property(container_id, 'type') == 'nerve':
                            edge_properties['nerve'] = container_id
                    self.__centreline_graph.add_edge(nodes[0], nodes[-1], **edge_properties)

    @property
    def id(self):
        return self.__id

    def set_feature_map(self, feature_map):
    #======================================
        self.__feature_map = feature_map

    def has_feature(self, feature):
    #==============================
    ##
    ## Is the ``feature`` included in this network?
    ##
        return (feature.id in self.__feature_ids
             or feature.property('tile-layer') == 'pathways')

    def __find_feature(self, id):
    #============================
        features = self.__feature_map.features(id)
        if len(features) == 1:
            return features[0]
        elif len(features) == 0:
            log.warning('Unknown network feature: {}'.format(id))
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
        route_graph.graph['path-type'] = path.path_type
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
        # Connectivity comes from SciCrunch

        def find_feature_ids(connectivity_node):
            return set([f.id if f.id is not None else f.property('class')
                        for f in self.__feature_map.find_path_features_by_anatomical_id(path.id, *connectivity_node)])

        def __centreline_end_nodes(centreline_id):
            for _, _, edge_id in self.__centreline_graph.edges(data='id'):
                if edge_id == centreline_id:
                    return edge_id

        # Connectivity graph must be undirected
        connectivity = path.connectivity
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
                        log.error(f'{path.id}: Node {node} has too many connected features: {found_feature_ids}')
                    elif len(connected_features):
                        feature_id = connected_features.pop()
                    else:
                        # Possible terminal nodes
                        log.warning(f'{path.id}: Node {node} has multiple terminal features: {found_feature_ids}')
                        feature_id = found_feature_ids.pop()
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
                for node_0, node_1, edge_id in self.__centreline_graph.edges(data='id'):
                    if edge_id == max_centreline:
                        edge = (node_0, node_1)
                        route_feature_ids.update(edge)
                        G.nodes[node]['feature_nodes'] = edge
                        break

            node_terminals = defaultdict(set)
            for node in terminal_nodes:
                feature_id = G.nodes[node]['feature_id']
                feature = feature_map.get_feature(feature_id)
                if feature is None:
                    log.warning(f'{path.id}: Cannot find path terminal feature with ID: {feature_id}')
                    continue
                feature_centre = feature.geometry.centroid
                for edge in nx.edge_dfs(G, node):
                    adjacent_node_features = G.nodes[edge[1]]['feature_nodes']
                    if adjacent_node_features is not None:
                        if len(adjacent_node_features) == 1:
                            adjacent_feature = adjacent_node_features[0]
                        else:
                            # find closest adjacent feature to node
                            try:
                                node0_centre = self.__centreline_graph.nodes[adjacent_node_features[0]]['geometry'].centroid
                                node1_centre = self.__centreline_graph.nodes[adjacent_node_features[1]]['geometry'].centroid
                                d0 = feature_centre.distance(node0_centre)
                                d1 = feature_centre.distance(node1_centre)
                                adjacent_feature = adjacent_node_features[0] if d0 <= d1 else adjacent_node_features[1]
                            except KeyError:
                                log.warning(f'{path.id}: Missing geometry for {adjacent_node_features[0]} and/or {adjacent_node_features[1]}')
                                break
                        node_terminals[adjacent_feature].add(feature_id)
                        break

            # The centreline paths that connect features on the route
            route_paths = nx.Graph(get_connected_subgraph(path.id, self.__centreline_graph, route_feature_ids))

            # Add edges to terminal nodes that aren't part of the centreline network
            ##pprint(route_feature_ids)
            ##pprint(node_terminals)
            ##pprint(route_paths.nodes)

            for end_node, terminal_nodes in node_terminals.items():
                #assert route_paths.nodes[end_node]['degree'] == 1  ## May not be true...
                # This will be used when drawing path to terminal node
                if end_node in route_paths:
                    route_paths.nodes[end_node]['direction'] = list(route_paths.nodes[end_node]['edge-direction'].items())[0][1]
                    for terminal_id in terminal_nodes:
                        route_paths.add_edge(end_node, terminal_id, type='terminal')
                        node = route_paths.nodes[terminal_id]
                        self.__set_node_properties_from_feature(node, terminal_id)

            # Add paths and nodes from connected connectivity sub-graph to result
            route_graph.add_nodes_from(route_paths.nodes(data=True))
            route_graph.add_edges_from(route_paths.edges(data=True))

        return route_graph

#===============================================================================
