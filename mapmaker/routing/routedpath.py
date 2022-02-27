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
from mapmaker.geometry.beziers import coords_to_point, point_to_coords
from mapmaker.utils import log

from .layout import TransitMap
from .options import ARROW_LENGTH, PATH_SEPARATION, SMOOTHING_TOLERANCE

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
    """
    Draw cubic Bezier control points and tangents.

    :param      bezier:  A CubicBezier
    :param      label:   A label for the middle control points

    :returns:   A list of GeometricShapes
    """
    geometry = []
    bz_pts = tuple(point_to_coords(p) for p in bezier.points)
    for pt in (bz_pts[0], bz_pts[3]):
        geometry.append(GeometricShape.circle(pt, radius=1000,
            properties={'type': 'bezier', 'kind': 'bezier-end'}))
    for pt in bz_pts[1:3]:
        geometry.append(GeometricShape.circle(pt, radius=1000,
            properties={'type': 'bezier', 'kind': 'bezier-control', 'label': label}))
    geometry.append(GeometricShape.line(*bz_pts[0:2], properties={'type': 'bezier'}))
    geometry.append(GeometricShape.line(*bz_pts[2:4], properties={'type': 'bezier'}))
    return geometry

#===============================================================================

class IntermediateNode:
#======================
    def __init__(self, width, mid_point, start_angle, end_angle):
        """
        ``start_angle`` and ``end_angle`` are directions into the node.
        """
        self.__start_angle = start_angle
        self.__mid_angle = (start_angle + end_angle)/2   # Has the same sense as start_angle
        self.__mid_normal = BezierPoint.fromAngle(self.__mid_angle + math.pi/2)*width
        self.__mid_point = mid_point
        self.__end_angle = end_angle

    def geometry(self, start_point, end_point, num_points=100, offset=0):
        node_point = self.__mid_point + self.__mid_normal*offset
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
        """
        Returns:
            A list of geometric objects. This are LineStrings describing paths
            between nodes and possibly additional features (e.g. way markers)
            of the paths.
        """

        def join_geometry(node, edge_0, edge_1):
            """
            Smoothly join two edges of a route at a node.
            """
            e0 = edge_0['path-ends'][node]
            e1 = edge_1['path-ends'][node]
            d = e0.distanceFrom(e1)/3
            if (e0-e1).angle < (e1-e0).angle:
                d = -d
            s0 = edge_0['tangents'][node]
            s1 = edge_1['tangents'][node]
            bz = CubicBezier(e0, e0 + s0*d, e1 - s1*d, e1)
            geometry = []
            if edge_0.get('path-id') == edge_1.get('path-id'):
                geometry.append(
                    GeometricShape(bezier_to_linestring(bz), {
                        'nerve': edge_0.get('nerve'),
                        'path-id': edge_0.get('path-id')
                        }))
            else:
                # The edges are from different paths so show a junction.
                mid_point = bz.pointAtTime(0.5)
                geometry.append(GeometricShape.circle(
                    point_to_coords(mid_point),
                    radius = 0.8*PATH_SEPARATION,
                    properties={'type': 'junction', 'path-id': edges[0].get('path-id')}))
                for n, bz in enumerate(bz.splitAtTime(0.5)):
                    geometry.append(
                        GeometricShape(bezier_to_linestring(bz), {
                            'nerve': edges[n].get('nerve'),
                            'path-id': edges[n].get('path-id')
                        }))
            return geometry

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
            path_offset = PATH_SEPARATION*edge_dict['offset']
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
                                                               offset=edge_dict['offset']/edge_dict['max-paths'])
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
                path_line = path_line.simplify(SMOOTHING_TOLERANCE, preserve_topology=False)
                geometry.append(GeometricShape(path_line, properties))
                if edge_dict.get('type') != 'terminal':
                    # Save where branch node edges will connect
                    edge_dict['path-ends'] = {
                        edge_dict['start-node']: BezierPoint(*path_line.coords[0]),
                        edge_dict['end-node']: BezierPoint(*path_line.coords[-1])
                    }
                    # Save where terminal edges would start from
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
                angle = self.__graph.nodes[node_0]['angle'] + math.pi
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
                edges = []
                for node_0, node_1, edge_dict in self.__graph.edges(node, data=True):
                    if edge_dict.get('type') != 'terminal':
                        edges.append(edge_dict)
                if len(edges) == 2:
                    geometry.extend(join_geometry(node, edges[0], edges[1]))
                elif len(edges) == 3:  ## Generalise
                    # Check angles between edges to find two most obtuse...
                    centre = node_dict['centre']
                    min_angle = math.pi
                    min_pair = None
                    pairs = []
                    for e0, e1 in itertools.combinations(enumerate(edges), 2):
                        pairs.append((e0[0], e1[0]))
                        a = abs((e0[1]['path-ends'][node] - centre).angle
                              - (e1[1]['path-ends'][node] - centre).angle)
                        if a > math.pi:
                            a = abs(a - 2*math.pi)
                        if a < min_angle:
                            min_angle = a
                            min_pair = pairs[-1]
                    for pair in pairs:
                        if pair != min_pair:
                            geometry.extend(join_geometry(node, edges[pair[0]], edges[pair[1]]))

        return geometry

    # def properties(self):
    #     return {
    #         'kind': self.__path_type,
    #         'type': 'line-dash' if self.__path_type.endswith('-post') else 'line'
    #     }

#===============================================================================

class PathRouter(object):
    def __init__(self, projections: dict):
        self.__projections = projections
        self.__route_graphs = {}

    def add_path(self, path_id: str, route_graph: nx.Graph):
        self.__route_graphs[path_id] = route_graph

    def layout(self):
        for path_id, route_graph in self.__route_graphs.items():
            nx.set_edge_attributes(route_graph, path_id, 'path-id')
        routes = []
        seen_paths = []
        for path_id, route_graph in self.__route_graphs.items():
            if path_id not in seen_paths:
                projects_to = self.__projections.get(path_id)
                if projects_to is not None and projects_to in self.__route_graphs:
                    routes.append(nx.algorithms.compose(route_graph, self.__route_graphs[projects_to]))
                    seen_paths.append(path_id)
                    seen_paths.append(projects_to)
        for path_id, route_graph in self.__route_graphs.items():
            if path_id not in seen_paths:
                if len(route_graph):
                    routes.append(route_graph)

        # Identify shared sub-paths
        edges_by_id = {}
        shared_paths = defaultdict(set)
        for route_number, route_graph in enumerate(routes):
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    shared_paths[edge_dict['id']].add(route_number)
                    edges_by_id[edge_dict['id']] = (node_0, node_1)

        #for edges from nodes with degree > 2
        #order by:
        #math.atan2(delta_y, delta_x)
        ##pprint([(n, [((e0, e1), d.get('id'), d.get('path-id')) for e0, e1, d in g.edges(data=True) if d.get('type') != 'terminal'])
        ##            for n, g in enumerate(routes)])

        layout = TransitMap(edges_by_id, shared_paths)
        layout.solve()
        edge_order = layout.results()

        for route_number, route_graph in enumerate(routes):
            for node_0, node_1, edge_dict in route_graph.edges(data=True):
                if edge_dict.get('type') != 'terminal':
                    edge = (node_0, node_1)
                    edge_id = edge_dict.get('id')
                    ordering = edge_order.get(edge_id, [])
                    if route_number in ordering:
                        edge_dict['offset'] = ordering.index(route_number) - len(ordering)//2 + ((len(ordering)+1)%2)/2
                        edge_dict['max-paths'] = len(ordering)

        return { route_number: RoutedPath(route_graph, route_number)
            for route_number, route_graph in enumerate(routes) }


#===============================================================================
