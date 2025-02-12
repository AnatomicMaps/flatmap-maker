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
File doc...
"""

#===============================================================================

from collections import defaultdict
import itertools
import math
from typing import Optional

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.geometry.beziers import bezier_connect, bezier_to_line_coords, bezier_to_linestring
from mapmaker.geometry.beziers import coords_to_point, point_to_coords, width_along_line
from mapmaker.geometry.shapes import GeometricShape
from mapmaker.settings import settings
from mapmaker.utils import log

from .layout import TransitMap
from .options import ARROW_LENGTH, PATH_SEPARATION, SMOOTHING_TOLERANCE

#===============================================================================

PRE_GANGLIONIC_TYPES = ['para-pre', 'symp-pre']
POST_GANGLIONIC_TYPES = ['para-post', 'symp-post']

#===============================================================================

class PathRouter(object):
    def __init__(self):
        self.__route_graphs = {}

    def add_path(self, path_id: str, route_graph: nx.Graph):
    #=======================================================
        self.__route_graphs[path_id] = route_graph

    def layout(self) -> dict[int, 'RoutedPath']:
    #===========================================
        for path_id, route_graph in self.__route_graphs.items():
            nx.set_edge_attributes(route_graph, path_id, 'path-id')
            nx.set_edge_attributes(route_graph, route_graph.graph['source'], 'source')

        # Within a connectivity model we pair together paths that have the same pre- and
        # post-ganglionic type, share a terminal node (i.e. degree one) and are connected
        # to the node by different edges

        routes = []    # The resulting set of routes, across all models

        routes_by_source = defaultdict(dict)
        for path_id, route_graph in self.__route_graphs.items():
            routes_by_source[route_graph.graph['source']][path_id] = route_graph

        for route_graphs in routes_by_source.values():
            pre_types = {}
            post_paths = defaultdict(set)
            # Find the paths and nodes we are interested in
            for path_id, route_graph in route_graphs.items():
                if route_graph.graph.get('path-type') in PRE_GANGLIONIC_TYPES:
                    pre_types[path_id] = route_graph.graph.get('path-type')[:4]
                elif route_graph.graph.get('path-type') in POST_GANGLIONIC_TYPES:
                    for node, degree in route_graph.degree():
                        post_paths[route_graph.graph.get('path-type')[:4]].add(path_id)
            # Look for pairs and add them to the list of routes
            seen_paths = []
            for pre_path, path_type in pre_types.items():
                pre_nodes = set(route_graphs[pre_path].nodes)
                for post_path in post_paths[path_type]:
                    if len(join_nodes := (pre_nodes & set(route_graphs[post_path].nodes))) == 1:
                        join_node = join_nodes.pop()
                        if (route_graphs[pre_path].degree(join_node) == 1
                        and route_graphs[post_path].degree(join_node) == 1):
                            joined_paths = nx.algorithms.compose(route_graphs[pre_path], route_graphs[post_path])
                            routes.append((f'{pre_path}/{post_path}', joined_paths))
                            seen_paths.append(pre_path)
                            seen_paths.append(post_path)
                            # Make sure nodes marked as upstream are still flagged in joined graph
                            if 'upstream' in [route_graphs[pre_path].nodes[join_node].get('type'),
                                              route_graphs[post_path].nodes[join_node].get('type')]:
                                joined_paths.nodes[join_node]['type'] = 'upstream'
                            break
            # Now add in the paths that haven't been paired
            for path_id, route_graph in route_graphs.items():
                if path_id not in seen_paths:
                    if len(route_graph):
                        routes.append((path_id, route_graph))

        # Identify shared sub-paths
        edges = set()
        node_edge_order = {}
        shared_paths = defaultdict(set)
        term_ups_edges = set()
        term_ups_shared_paths = defaultdict(set)

        for route_number, (_, route_graph) in enumerate(routes):
            for node, node_data in route_graph.nodes(data=True):
                if node not in node_edge_order and node_data.get('degree', 0) > 2:
                    # sorted list of edges in counter-clockwise order
                    node_edge_order[node] = tuple(x[0] for x in sorted(node_data.get('edge-node-angle').items(), key=lambda x: x[1]))
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                edge = (node_0, node_1)
                if edge_dict.get('type') not in ['terminal', 'upstream']:
                    shared_paths[edge].add(route_number)
                    edges.add(edge)
                else:
                    term_ups_shared_paths[edge].add(route_number)
                    term_ups_edges.add(edge)

        # Don't invoke solver if there's only a single shared path...
        if not settings.get('noPathLayout', False) and len(routes) > 1:
            log.info('Solving for path order...')
            layout = TransitMap(edges, shared_paths, node_edge_order)
            layout.solve()
            edge_order = layout.results()
        else:
            edge_order = { edge: list(route) for edge, route in shared_paths.items() }

        term_ups_edge_order = {edge: list(route) for edge, route in term_ups_shared_paths.items()}

        for route_number, (_, route_graph) in enumerate(routes):
            for _, node_dict in route_graph.nodes(data=True):
                node_dict['offsets'] = {}
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') not in ['terminal', 'upstream']:
                    if (node_0, node_1) in edge_order:
                        ordering = edge_order[(node_0, node_1)]
                    else:
                        ordering = edge_order.get((node_1, node_0), [])
                        (node_0, node_1) = tuple(reversed((node_0, node_1)))
                    if route_number in ordering:
                        edge_dict['max-paths'] = len(ordering)
                        route_index = ordering.index(route_number)
                        offset = len(ordering)//2 - ((len(ordering)+1)%2)/2
                        route_graph.nodes[node_0]['offsets'][node_1] = route_index - offset
                        route_graph.nodes[node_1]['offsets'][node_0] = len(ordering) - route_index - 1 - offset
                else:
                    if (node_0, node_1) in term_ups_edge_order:
                        ordering = term_ups_edge_order[(node_0, node_1)]
                    else:
                        ordering = term_ups_edge_order.get((node_1, node_0), [])
                        (node_0, node_1) = tuple(reversed((node_0, node_1)))
                    if route_number in ordering:
                        edge_dict['max-paths'] = len(ordering)
                        route_index = ordering.index(route_number)
                        offset = len(ordering)//2 - ((len(ordering)+1)%2)/2
                        route_graph.nodes[node_0]['offsets'][node_1] = route_index - offset
                        route_graph.nodes[node_1]['offsets'][node_0] = len(ordering) - route_index - 1 - offset

        return { route_number: RoutedPath(path_id, route_graph, route_number)
            for route_number, (path_id, route_graph) in enumerate(routes) }

#===============================================================================

def bezier_control_points(bezier, label=''):
#===========================================
    """
    Draw cubic Bezier control points and tangents.

    :param      bezier:  A CubicBezier
    :param      label:   A label for the middle control points

    :returns:   A list of GeometricShapes
    """
    geometry = []
    if isinstance(bezier, CubicBezier):
        bz_pts = tuple(point_to_coords(p) for p in bezier.points)
        for pt in (0, 3):
            geometry.append(GeometricShape.circle(bz_pts[pt], radius=600 if pt == 0 else 300,
                properties={'type': 'bezier', 'kind': 'bezier-end', 'label': f'{label}-{pt}'}))
        for pt in (1, 2):
            geometry.append(GeometricShape.circle(bz_pts[pt], radius=400,
                properties={'type': 'bezier', 'kind': 'bezier-control', 'label': f'{label}-{pt}'}))
        geometry.append(GeometricShape.line(*bz_pts[0:2], properties={'type': 'bezier'}))
        geometry.append(GeometricShape.line(*bz_pts[2:4], properties={'type': 'bezier'}))
    return geometry

def extend_geometry_by_join(geometry, node, node_dict, edge_dict_0, edge_dict_1):
#===============================================================================
    """
    Smoothly join two edges of a route at a node.
    """
    try:
        bz = smooth_join(edge_dict_0['path-end'][node],
                            node_dict['edge-direction'][edge_dict_0['segment']],
                            node_dict['edge-direction'][edge_dict_1['segment']] + math.pi,
                         edge_dict_1['path-end'][node])
    except KeyError:
        log.warning(f"{edge_dict_0['path-id']}: Missing edge direction for `{node}` with `{edge_dict_0['segment']}` and/or `{edge_dict_1['segment']}`")
        return geometry

    path_id_0 = edge_dict_0.get('path-id')
    if edge_dict_0.get('path-id') == edge_dict_1.get('path-id'):
        geometry[path_id_0].append(
            GeometricShape(bezier_to_linestring(bz), {
                'nerve': edge_dict_0.get('nerve'),
                'path-id': path_id_0,
                'source': edge_dict_0.get('source')
                }))
    else:
        # The edges are from different paths so show a junction.
        mid_point = bz.pointAtTime(0.5)
        geometry[path_id_0].append(GeometricShape.circle(
            point_to_coords(mid_point),
            radius = 1.2*PATH_SEPARATION,
            properties = {
                'type': 'junction',
                'path-id': path_id_0,
                'source': edge_dict_0.get('source')
            }))
        edge_dicts = [edge_dict_0, edge_dict_1]
        for n, bz in enumerate(bz.splitAtTime(0.5)):
            path_id_n = edge_dicts[n].get('path-id')
            geometry[path_id_n].append(
                GeometricShape(bezier_to_linestring(bz), {
                    'nerve': edge_dicts[n].get('nerve'),
                    'path-id': path_id_n,
                    'source': edge_dicts[n].get('source')
                }))
    return geometry

def smooth_join(e0, a0, a1, e1):
#===============================
    d = e0.distanceFrom(e1)/3
    s0 = BezierPoint.fromAngle(a0)
    s1 = BezierPoint.fromAngle(a1)
    return CubicBezier(e0, e0 + s0*d, e1 - s1*d, e1)

#===============================================================================

class IntermediateNode:
#======================
    def __init__(self, geometry, start_angle, end_angle):
        self.__start_angle = start_angle
        self.__mid_angle = (start_angle + end_angle)/2.0
        self.__end_angle = end_angle
        centre = geometry.centroid
        self.__mid_point = BezierPoint(centre.x, centre.y)
        mid_normal = BezierPoint.fromAngle(self.__mid_angle + math.pi/2)
        width = width_along_line(geometry, self.__mid_point, mid_normal)
        if width == 0:
           log.error(f'Cannot get width of node {id}')
        self.__width_normal = mid_normal*width/2.0

    def geometry(self, path_source, path_id, start_point, end_point, num_points=100, offset=0, show_controls=False):
        node_point = self.__mid_point + self.__width_normal*offset
        geometry = [GeometricShape.circle(
            point_to_coords(node_point),
            radius = 0.8*PATH_SEPARATION,
            properties = {
                'type': 'junction',
                'path-id': path_id,
                'source': path_source
            })]
        segs = [ bezier_connect(start_point, node_point, self.__start_angle, self.__mid_angle),
                 bezier_connect(node_point, end_point, self.__mid_angle, self.__end_angle) ]
        if show_controls:
            geometry.extend(bezier_control_points(segs[0], 'intermediate 0'))
            geometry.extend(bezier_control_points(segs[1], 'intermediate 1'))
        return (bezier_to_line_coords(BezierPath.fromSegments(segs), num_points=num_points, offset=offset), geometry)

#===============================================================================

class RoutedPath(object):
    def __init__(self, path_id: str, route_graph: nx.Graph, number: int):
        self.__path_id = path_id
        self.__graph = route_graph
        self.__trace = route_graph.graph.get('traced', False)
        self.__number = number

    @property
    def centrelines(self) -> Optional[list[str]]:
        return self.__graph.graph.get('centrelines')

    @property
    def centrelines_model(self) -> Optional[list[str]]:
        return self.__graph.graph.get('centrelines-model')

    @property
    def nerve_feature_ids(self) -> set[str]:
        return self.__graph.graph['nerve-features']

    @property
    def node_feature_ids(self) -> set[str]:
        return self.__graph.graph['node-features']

    @property
    def path_id(self):
        return self.__path_id

    def path_geometry(self) -> dict[str, list[GeometricShape]]:
    #==========================================================
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """
        reference_nodes = {}
        path_geometry = defaultdict(list)
        def connect_gap(node, node_points, iscentreline=False):
            # don't fill the gap from centreline to centreline
            if node in reference_nodes and iscentreline:
                if reference_nodes[node]['iscenterline']:
                    return

            if node in reference_nodes:
                distance_dict = {}
                for p_0 in node_points:
                    for p_1 in reference_nodes[node]['points']:
                        distance_dict[(p_0, p_1)] = p_0.distanceFrom(p_1)
                selected_p = min(distance_dict, key=distance_dict.get)
                if distance_dict[selected_p] > 0:
                    bz = bezier_connect(selected_p[0], selected_p[1], (selected_p[0] - selected_p[1]).angle)
                    path_geometry[path_id].append(GeometricShape(
                            bezier_to_linestring(bz), {
                                'path-id': path_id,
                                'source': path_source,
                                'label': self.__graph.graph.get('label')
                            }))
            else:
                reference_nodes[node] = {'points': node_points, 'iscenterline': iscentreline}
            if node in reference_nodes and not iscentreline and reference_nodes[node]['iscenterline']:
                reference_nodes[node] = {'points': node_points, 'iscenterline': iscentreline}

        for node_0, node_1, edge_dict in self.__graph.edges(data=True):
            path_id = edge_dict.get('path-id')
            path_source = edge_dict.get('source')
            properties = {
                'nerve': edge_dict.get('nerve'),
                'path-id': path_id,
                'source': path_source,
            }
            path_components = edge_dict.get('path-components')
            if path_components is None:
                continue
            offset = self.__graph.nodes[edge_dict['start-node']]['offsets'][edge_dict['end-node']]
            path_offset = PATH_SEPARATION*offset
            intermediate_start = None
            coords = []
            component_num = 0
            while component_num < len(path_components):
                component = path_components[component_num]
                if isinstance(component, IntermediateNode):
                    component_num += 1
                    if self.__trace:
                        path_geometry[path_id].extend(bezier_control_points(path_components[component_num],
                                                                            label=f'{path_id}-{component_num}'))
                    next_line_coords = bezier_to_line_coords(path_components[component_num], offset=path_offset)
                    intermediate_geometry = component.geometry(path_source, path_id,
                                                               intermediate_start, BezierPoint(*next_line_coords[0]),
                                                               offset=2*offset/edge_dict['max-paths'],
                                                               show_controls=self.__trace)
                    line_coords = intermediate_geometry[0]
                    path_geometry[path_id].extend(intermediate_geometry[1])
                    coords.extend(line_coords)
                    line_coords = next_line_coords
                    intermediate_start = BezierPoint(*line_coords[-1])
                else:
                    if self.__trace:
                        path_geometry[path_id].extend(bezier_control_points(component,
                                                                            label=f'{path_id}-{component_num}'))
                    line_coords = bezier_to_line_coords(component, offset=path_offset)
                    if len(line_coords) == 0:
                        log.warning(f'{path_id}: offset too big for parallel path...')
                        line_coords = bezier_to_line_coords(component, offset=0)
                    intermediate_start = BezierPoint(*line_coords[-1])
                coords.extend(line_coords)
                component_num += 1
            path_line = shapely.geometry.LineString(coords)
            if path_line is not None:
                # Draw path line
                path_line = path_line.simplify(SMOOTHING_TOLERANCE, preserve_topology=False)
                path_geometry[path_id].append(GeometricShape(path_line, properties))
                if edge_dict.get('type') not in ['terminal', 'upstream']:
                    start_point = BezierPoint(*path_line.coords[0])
                    end_point = BezierPoint(*path_line.coords[-1])
                    # Save where branch node edges will connect to offsetted path line
                    edge_dict['path-end'] = {
                        edge_dict['start-node']: start_point,
                        edge_dict['end-node']: end_point
                    }
                    # Save offsetted point where terminal edges start from
                    self.__graph.nodes[edge_dict['start-node']]['start-point'] = start_point
                    self.__graph.nodes[edge_dict['end-node']]['start-point'] = end_point
                    # Connect centerline to the available terminal edges
                    connect_gap(edge_dict['start-node'], [start_point], iscentreline=True)
                    connect_gap(edge_dict['end-node'], [end_point], iscentreline=True)

        # Draw paths to terminal nodes
        def draw_arrow(start_point, end_point, path_id, path_source):
            heading = (end_point - start_point).angle
            end_point -= BezierPoint.fromAngle(heading)*0.9*ARROW_LENGTH
            path_geometry[path_id].append(GeometricShape.arrow(end_point, heading, ARROW_LENGTH, properties={
                'type': 'arrow',
                'path-id': path_id,
                'source': path_source,
                'label': self.__graph.graph.get('label')
            }))

        def draw_line(node_0, node_1, tolerance=0.1, separation=2000):
            start_coords = self.__graph.nodes[node_0]['geometry'].centroid.coords[0]
            end_coords = self.__graph.nodes[node_1]['geometry'].centroid.coords[0]
            offset = self.__graph.nodes[node_0]['offsets'][node_1]
            path_offset = separation * offset
            start_point = coords_to_point(start_coords)
            end_point = coords_to_point(end_coords)
            if end_point.distanceFrom(start_point) == 0:
                return
            angle = (end_point - start_point).angle + tolerance * (end_point - start_point).angle
            heading = angle
            bz = bezier_connect(start_point, end_point, angle, heading)
            path_geometry[path_id].append(GeometricShape(
                        bezier_to_linestring(bz, offset=path_offset), {
                            'path-id': path_id,
                            'source': path_source,
                        }))
            bz_line_coord = bezier_to_line_coords(bz, offset=path_offset)
            if self.__graph.degree(node_0) == 1:
                draw_arrow(coords_to_point(bz_line_coord[-1]), coords_to_point(bz_line_coord[0]), path_id, path_source)
            if self.__graph.degree(node_1) == 1:
                draw_arrow(coords_to_point(bz_line_coord[0]), coords_to_point(bz_line_coord[-1]), path_id, path_source)
            connect_gap(node_0, [coords_to_point(bz_line_coord[0])])
            connect_gap(node_1, [coords_to_point(bz_line_coord[-1])])

        terminal_nodes = set()
        for node_0, node_1, edge_dict in self.__graph.edges(data=True):    ## This assumes node_1 is the terminal...
            path_id = edge_dict.get('path-id')
            path_source = edge_dict.get('source')
            if ((edge_type := edge_dict.get('type')) == 'terminal'
             or (edge_type == 'upstream'
              and 'upstream' not in [self.__graph.nodes[node_0].get('type'),
                                     self.__graph.nodes[node_1].get('type')])):
                # Draw lines...
                terminal_nodes.update([node_0, node_1])
                draw_line(node_0, node_1)
            elif edge_type == 'upstream':
                terminal_nodes.update([node_0, node_1])
                if self.__graph.nodes[node_0].get('type') == 'upstream':
                    terminal_node = node_1
                    upstream_node = node_0
                elif self.__graph.nodes[node_1].get('type') == 'upstream':
                    terminal_node = node_0
                    upstream_node = node_1
                else:
                    raise ValueError(f'>>>>>>>>>>>>> Missing upstream node... {self.__path_id} {node_0} {node_1}')
                # assert self.__graph.nodes[terminal_node]['type'] == 'terminal'

                if (start_point := self.__graph.nodes[upstream_node].get('start-point')) is not None:
                    angle = self.__graph.nodes[upstream_node]['direction']
                    end_coords = self.__graph.nodes[terminal_node]['geometry'].centroid.coords[0]
                    end_point = coords_to_point(end_coords)
                    heading = (end_point - start_point).angle
                    bz_end_point = end_point - BezierPoint.fromAngle(heading)*0.9*ARROW_LENGTH
                    bz = bezier_connect(start_point, bz_end_point, angle, heading)
                    path_geometry[path_id].append(GeometricShape(
                        bezier_to_linestring(bz), {
                            'path-id': path_id,
                            'source': path_source,
                        }))
                    bz_line_coord = bezier_to_line_coords(bz)
                    connect_gap(upstream_node, [coords_to_point(bz_line_coord[0])])
                    connect_gap(terminal_node, [coords_to_point(bz_line_coord[-1])])
                    if self.__trace:
                        path_geometry[path_id].extend(bezier_control_points(bz, label=f'{self.__path_id}-T'))
                    # Draw arrow iff degree(node_1) == 1
                    if self.__graph.degree(terminal_node) == 1:
                        draw_arrow(start_point, end_point, path_id, path_source)
                else:
                    # This is when the upstream node doesn't have an ongoing centreline
                    draw_line(upstream_node, terminal_node)

        # Connect edges at branch nodes
        for node, node_dict in self.__graph.nodes(data=True):
            if self.__graph.degree(node) >= 2:
                edge_dicts = []
                edge_nodes = []
                for _, node_1, edge_dict in self.__graph.edges(node, data=True):
                    if edge_dict.get('type') not in ['terminal', 'upstream']:
                        edge_dicts.append(edge_dict)
                        edge_nodes.append(node_1)
                if len(edge_nodes) == 1 and edge_nodes[0] not in terminal_nodes:
                    pass
                    """
                    # TEMP: This produces visual artifacts so suppress...

                    # Draw path from node boundary to offsetted centre
                    edge_dict = edge_dicts[0]
                    try:
                        offset = PATH_SEPARATION*self.__graph.nodes[node]['offsets'][edge_nodes[0]]
                        edge_angle = node_dict['edge-node-angle'][edge_nodes[0]]
                        bz = smooth_join(edge_dict['path-end'][node],
                                            node_dict['edge-direction'][edge_dict['id']],
                                            edge_angle,
                                         node_dict['centre'] + BezierPoint.fromAngle(edge_angle + math.pi/2)*offset)
                        geometry.append(GeometricShape(bezier_to_linestring(bz), {
                            'nerve': edge_dict.get('nerve'),
                            'path-id': edge_dict.get('path-id'),
                            'source': edge_dict.get('source')
                        }))
                    except KeyError:
                        log.warning(f"{edge_dict.get('path-id')}: Missing geometry for {node} and/or {edge_nodes[0]}")
                    """
                elif len(edge_nodes) == 2:
                    extend_geometry_by_join(path_geometry, node, node_dict, edge_dicts[0], edge_dicts[1])
                elif len(edge_nodes) == 3:  ## Generalise
                    # Check angles between edges to find two most obtuse...
                    centre = node_dict['centre']
                    min_angle = math.pi
                    min_pair = None
                    pairs = []
                    for e0, e1 in itertools.combinations(enumerate(edge_dicts), 2):
                        pairs.append((e0[0], e1[0]))
                        a = abs((e0[1]['path-end'][node] - centre).angle
                              - (e1[1]['path-end'][node] - centre).angle)
                        if a > math.pi:
                            a = abs(a - 2*math.pi)
                        if a < min_angle:
                            min_angle = a
                            min_pair = pairs[-1]
                    for pair in pairs:
                        if pair != min_pair:
                            extend_geometry_by_join(path_geometry, node, node_dict, edge_dicts[pair[0]], edge_dicts[pair[1]])
        return path_geometry

#===============================================================================
