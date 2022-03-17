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
from typing import Tuple

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import shapely.geometry

#===============================================================================

from mapmaker.geometry.beziers import bezier_connect, bezier_to_linestring
from mapmaker.geometry.beziers import coords_to_point, point_to_coords, width_along_line
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

    def layout(self):
    #================
        for path_id, route_graph in self.__route_graphs.items():
            nx.set_edge_attributes(route_graph, path_id, 'path-id')

        # We match up paths that have pre- and post-ganglionic types and
        # pair them together if they are of the same type and share a
        # terminal (i.e. degree one) node.
        pre_ganglionic_nodes = defaultdict(list)
        post_ganglionic_nodes = defaultdict(list)
        post_types = {}
        # Find the paths and nodes we are interested in
        for path_id, route_graph in self.__route_graphs.items():
            if route_graph.graph.get('path-type') in PRE_GANGLIONIC_TYPES:
                for node, degree in route_graph.degree():
                    if degree == 1:
                        pre_ganglionic_nodes[path_id].append((node, route_graph.graph.get('path-type')[:4]))
            elif route_graph.graph.get('path-type') in POST_GANGLIONIC_TYPES:
                for node, degree in route_graph.degree():
                    if degree == 1:
                        post_ganglionic_nodes[path_id].append(node)
                        post_types[path_id] = route_graph.graph.get('path-type')[:4]
        # Look for pairs and add them to the list of routes
        routes = []
        seen_paths = []
        for pre_path, pre_nodes in pre_ganglionic_nodes.items():
            matched = False
            for node, path_type in pre_nodes:
                for post_path, post_nodes in post_ganglionic_nodes.items():
                    if path_type == post_types[post_path] and node in post_nodes:
                        routes.append(nx.algorithms.compose(self.__route_graphs[pre_path], self.__route_graphs[post_path]))
                        seen_paths.append(pre_path)
                        seen_paths.append(post_path)
                        matched = True
                        break
                if matched: break
        # Now add in the paths that haven't been paired
        for path_id, route_graph in self.__route_graphs.items():
            if path_id not in seen_paths:
                if len(route_graph):
                    routes.append(route_graph)

        # Identify shared sub-paths
        edges = set()
        node_edge_order = {}
        shared_paths = defaultdict(set)
        for route_number, route_graph in enumerate(routes):
            for node, node_data in route_graph.nodes(data=True):
                if node not in node_edge_order and node_data.get('degree', 0) > 2:
                    # sorted list of edges in counter-clockwise order
                    node_edge_order[node] =  tuple(x[0] for x in sorted(node_data.get('edge-node-angle').items(), key=lambda x: x[1]))
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    edge = (node_0, node_1)
                    shared_paths[edge].add(route_number)
                    edges.add(edge)

        # Don't invoke solver if there's only a single shared path...
        if len(routes) > 1:
            layout = TransitMap(edges, shared_paths, node_edge_order)
            layout.solve()
            edge_order = layout.results()
        else:
            edge_order = { edge: list(route) for edge, route in shared_paths.items() }

        for route_number, route_graph in enumerate(routes):
            for _, node_dict in route_graph.nodes(data=True):
                node_dict['offsets'] = {}
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
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
        return { route_number: RoutedPath(route_graph, route_number)
            for route_number, route_graph in enumerate(routes) }

#===============================================================================

class GeometricShape(object):
    def __init__(self, geometry: shapely.geometry, properties: dict = None):
        self.__geometry = geometry
        self.__properties = properties if properties is not None else {}

    @property
    def geometry(self) -> shapely.geometry:
        return self.__geometry

    @property
    def properties(self) -> dict:
        return self.__properties

    @classmethod
    def circle(cls, centre: Tuple[float], radius: float = 2000, properties: dict = None):
        return cls(shapely.geometry.Point(centre).buffer(radius), properties)

    @classmethod
    def line(cls, start: Tuple[float], end: Tuple[float], properties: dict = None):
        return cls(shapely.geometry.LineString([start, end]), properties)

    @classmethod
    def arrow(cls, back: BezierPoint, heading: float, length: float, properties: dict = None):
        tip = back + BezierPoint.fromAngle(heading)*length
        offset = BezierPoint.fromAngle(heading + math.pi/2)*length/3
        arrow = shapely.geometry.Polygon([point_to_coords(tip), point_to_coords(back+offset), point_to_coords(back-offset)])
        return cls(arrow, properties)

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
    bz_pts = tuple(point_to_coords(p) for p in bezier.points)
    for pt in (bz_pts[0], bz_pts[3]):
        geometry.append(GeometricShape.circle(pt, radius=500,
            properties={'type': 'bezier', 'kind': 'bezier-end'}))
    for pt in bz_pts[1:3]:
        geometry.append(GeometricShape.circle(pt, radius=400,
            properties={'type': 'bezier', 'kind': 'bezier-control', 'label': label}))
    geometry.append(GeometricShape.line(*bz_pts[0:2], properties={'type': 'bezier'}))
    geometry.append(GeometricShape.line(*bz_pts[2:4], properties={'type': 'bezier'}))
    return geometry

def join_geometry(node, node_dict, edge_dict_0, edge_dict_1):
#============================================================
    """
    Smoothly join two edges of a route at a node.
    """
    bz = smooth_join(edge_dict_0['path-end'][node],
                        node_dict['edge-direction'][edge_dict_0['id']],
                        node_dict['edge-direction'][edge_dict_1['id']] + math.pi,
                     edge_dict_1['path-end'][node])
    geometry = []
    if edge_dict_0.get('path-id') == edge_dict_1.get('path-id'):
        geometry.append(
            GeometricShape(bezier_to_linestring(bz), {
                'nerve': edge_dict_0.get('nerve'),
                'path-id': edge_dict_0.get('path-id')
                }))
    else:
        # The edges are from different paths so show a junction.
        mid_point = bz.pointAtTime(0.5)
        geometry.append(GeometricShape.circle(
            point_to_coords(mid_point),
            radius = 0.8*PATH_SEPARATION,
            properties={'type': 'junction', 'path-id': edge_dict_0.get('path-id')}))
        edge_dicts = [edge_dict_0, edge_dict_1]
        for n, bz in enumerate(bz.splitAtTime(0.5)):
            geometry.append(
                GeometricShape(bezier_to_linestring(bz), {
                    'nerve': edge_dicts[n].get('nerve'),
                    'path-id': edge_dicts[n].get('path-id')
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
    def __init__(self, id, geometry, start_angle, end_angle):
        self.__id = id
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

    def geometry(self, start_point, end_point, num_points=100, offset=0):
        node_point = self.__mid_point + self.__width_normal*offset
        segs = [ bezier_connect(start_point, node_point, self.__start_angle, self.__mid_angle),
                 bezier_connect(node_point, end_point, self.__mid_angle, self.__end_angle) ]
        return (bezier_to_linestring(BezierPath.fromSegments(segs), num_points=num_points, offset=offset), node_point)

#===============================================================================

class RoutedPath(object):
    def __init__(self, route_graph: nx.Graph, number: int):
        self.__graph = route_graph
        self.__number = number
        self.__node_set = {node for node, data in route_graph.nodes(data=True)
                                if not data.get('exclude', False)}
        self.__source_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'source'}
        self.__target_nodes = {node for node, data in route_graph.nodes(data=True)
                                if data.get('type') == 'target'}

    @property
    def node_set(self):
        return self.__node_set

    def __line_from_edge(self, edge):
        node_0 = self.__graph.nodes[edge[0]]
        node_1 = self.__graph.nodes[edge[1]]
        if 'geometry' not in node_0 or 'geometry' not in node_1:
            log.warning('Edge {} nodes have no geometry'.format(edge))
        else:
            return shapely.geometry.LineString([
                node_0['geometry'].centroid, node_1['geometry'].centroid])

    def geometry(self) -> [GeometricShape]:
    #======================================
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """
        geometry = []
        for node_0, node_1, edge_dict in self.__graph.edges.data():
            edge = (node_0, node_1)
            path_id = edge_dict.get('path-id')
            properties = {
                'nerve': edge_dict.get('nerve'),
                'path-id': path_id
            }
            path_components = edge_dict.get('path-components')
            if path_components is None:
                continue
            offset = self.__graph.nodes[edge_dict['start-node']]['offsets'][edge_dict['end-node']]
            path_offset = PATH_SEPARATION*offset
            intermediate_nodes = []
            coords = []
            intermediate_start = None
            component_num = 0
            while component_num < len(path_components):
                component = path_components[component_num]
                if isinstance(component, IntermediateNode):
                    component_num += 1
                    next_line_coords = bezier_to_linestring(path_components[component_num], offset=path_offset).coords
                    intermediate_geometry = component.geometry(intermediate_start, BezierPoint(*next_line_coords[0]),
                                                               offset=2*offset/edge_dict['max-paths'])
                    line_coords = intermediate_geometry[0].coords
                    intermediate_nodes.append(intermediate_geometry[1])
                    coords.extend(line_coords if path_offset >= 0 else reversed(line_coords))
                    line_coords = next_line_coords
                    intermediate_start = BezierPoint(*line_coords[-1])
                else:
                    line_coords = bezier_to_linestring(component, offset=path_offset).coords
                    intermediate_start = BezierPoint(*line_coords[-1])
                coords.extend(line_coords if path_offset >= 0 else reversed(line_coords))
                component_num += 1
                path_line = shapely.geometry.LineString(coords)
            if path_line is not None:
                # Draw path line
                path_line = path_line.simplify(SMOOTHING_TOLERANCE, preserve_topology=False)
                geometry.append(GeometricShape(path_line, properties))
                if edge_dict.get('type') != 'terminal':
                    # Save where branch node edges will connect to offsetted path line
                    edge_dict['path-end'] = {
                        edge_dict['start-node']: BezierPoint(*path_line.coords[0]),
                        edge_dict['end-node']: BezierPoint(*path_line.coords[-1])
                    }
                    # Save offsetted point where terminal edges start from
                    self.__graph.nodes[edge_dict['start-node']]['start-point'] = BezierPoint(*path_line.coords[0])
                    self.__graph.nodes[edge_dict['end-node']]['start-point'] = BezierPoint(*path_line.coords[-1])
            # Draw intermediate nodes
            for node_point in intermediate_nodes:
                geometry.append(GeometricShape.circle(
                    point_to_coords(node_point),
                    radius = 0.8*PATH_SEPARATION,
                    properties={'type': 'junction', 'path-id': path_id}))

        # Draw paths to terminal nodes
        for node_0, node_1, edge_dict in self.__graph.edges.data():
            if edge_dict.get('type') == 'terminal':
                start_point = self.__graph.nodes[node_0]['start-point']
                angle = self.__graph.nodes[node_0]['direction']
                end_coords = self.__graph.nodes[node_1]['geometry'].centroid.coords[0]
                end_point = coords_to_point(end_coords)
                heading = (end_point - start_point).angle
                end_point -= BezierPoint.fromAngle(heading)*0.9*ARROW_LENGTH
                bz = bezier_connect(start_point, end_point, angle, heading)
                geometry.append(GeometricShape(
                    bezier_to_linestring(bz), {
                        'path-id': edge_dict.get('path-id')
                    }))
                geometry.append(GeometricShape.arrow(end_point, heading, ARROW_LENGTH, properties = {
                    'type': 'junction',
                    'path-id': edge_dict.get('path-id')
                }))

        # Connect edges at branch nodes
        for node, node_dict in self.__graph.nodes(data=True):
            if node_dict.get('degree', 0) >= 2:
                edge_dicts = []
                edge_nodes = []
                for _, node_1, edge_dict in self.__graph.edges(node, data=True):
                    if edge_dict.get('type') != 'terminal':
                        edge_dicts.append(edge_dict)
                        edge_nodes.append(node_1)
                if len(edge_nodes) == 1:
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
                            'path-id': edge_dict.get('path-id')
                        }))
                    except KeyError:
                        log.warning(f"{edge_dict.get('path-id')}: Missing geometry for {node} and/or {edge_nodes[0]}")
                elif len(edge_dicts) == 2:
                    geometry.extend(join_geometry(node, node_dict, edge_dicts[0], edge_dicts[1]))
                elif len(edge_dicts) == 3:  ## Generalise
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
                            geometry.extend(join_geometry(node, node_dict, edge_dicts[pair[0]], edge_dicts[pair[1]]))

        return geometry

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }

#===============================================================================
