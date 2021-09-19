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

from collections import defaultdict

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

import networkx as nx
import numpy as np
import shapely.geometry

#===============================================================================

from mapmaker.utils import log
from mapmaker.routing.utils.pair_iteration import pairwise
from mapmaker.routing.utils.maths import magnitude
from mapmaker.routing.utils.maths import mult
from mapmaker.routing.utils.maths import normalize
from mapmaker.routing.utils.maths import set_magnitude
from mapmaker.routing.utils.maths import sub
from mapmaker.routing.utils.maths import add
from mapmaker.routing.utils.interpolation import smooth_cubic_hermite_derivatives_line
from mapmaker.routing.utils.interpolation import sample_cubic_hermite_curves
from mapmaker.routing.scaffold_2d import Scaffold2dPath

#===============================================================================

NUMBER_OF_BEZIER_PARTS = 10  # We divide each Bezier segment of a centreline
                             # into 10 sub-segments

#===============================================================================

SHEATH_WIDTH = 5000     ## needs to be some fraction of map size...

#===============================================================================

# See https://pomax.github.io/bezierinfo/#catmullconv

Bezier_to_Hermite = np.array([[ 1,  0,  0,  0],
                              [-3,  3,  0,  0],
                              [ 0,  0, -3,  3],
                              [ 0,  0,  0,  1]])

#===============================================================================

def point_from_bezier(index, bezier):
    point = bezier.points[index]
    return np.array((point.x, point.y))

def split_bezier(bezier, divisions):
#===================================
    if divisions == 1:
        return [bezier]
    elif divisions % 2 == 1:
        parts = bezier.splitAtTime(1.0/divisions)
        return [parts[0]] + split_bezier(parts[1], divisions - 1)
    else:
        parts = bezier.splitAtTime(0.5)
        return split_bezier(parts[0], divisions//2) + split_bezier(parts[1], divisions//2)

def trim_bezier_to_region_edge(bezier, region, start=True):   ## region = Circle(node_centre, RADIUS)
#=========================================================
    mid_point = bezier.pointAtTime(0.5)
    assert not region.contains(shapely.geometry.Point([mid_point.x, mid_point.y]))

    end_point = bezier.pointAtTime(0.0 if start else 1.0)
    if not region.contains(shapely.geometry.Point([end_point.x, end_point.y])):
        pass
        # Either curve passes through region (double intercept):
            # bezier.distance_to(node_centre) <= RADIUS
        # Or just isn't long enough:
            # Extend bezier until end is in region by setting end point
            # to region's centroid (node_centre)

        # BezierPath.distanceToPath(other, samples=10)
            # Finds the distance to the other curve at its closest point,
            # along with the t values for the closest point at each segment
            # and the relevant segments.
            #
            # Returns: distance, t1, t2, seg1, seg2.

    EPSILON = 0.01
    if start:
        t_start = 0.0
        t_end = 0.5
        while (t_end - t_start) > EPSILON:
            t_mid = (t_start + t_end)/2
            mid_point = bezier.pointAtTime(t_mid)
            if region.contains(shapely.geometry.Point([mid_point.x, mid_point.y])):
                t_start = t_mid
            else:
                t_end = t_mid
    else:
        t_start = 0.5
        t_end = 1.0
        while (t_end - t_start) > EPSILON:
            t_mid = (t_start + t_end)/2
            mid_point = bezier.pointAtTime(t_mid)
            if region.contains(shapely.geometry.Point([mid_point.x, mid_point.y])):
                t_end = t_mid
            else:
                t_start = t_mid
    parts = bezier.splitAtTime(t_mid)
    return parts[1 if start else 0]

def line_intersection(line_points_1, line_points_2):
#===================================================
    line_1 = shapely.geometry.LineString([[line_points_1[0].x, line_points_1[0].y],
                                          [line_points_1[1].x, line_points_1[1].y]])
    line_2 = shapely.geometry.LineString([[line_points_2[0].x, line_points_2[0].y],
                                          [line_points_2[1].x, line_points_2[1].y]])
    while not line_1.intersects(line_2):
        line_1 = shapely.affinity.scale(line_1, 10, 10)
        line_2 = shapely.affinity.scale(line_2, 10, 10)
    intersection = line_1.intersection(line_2)
    return intersection.coords[0]

def join_beziers_in_region(last_bezier, join_region, next_bezier):
#=================================================================
    last_bezier = trim_bezier_to_region_edge(last_bezier.asSegments()[-1], join_region, start=False)
    next_bezier = trim_bezier_to_region_edge(next_bezier.asSegments()[0], join_region, start=True)

    # now want intersection of derivative lines
    intersection = line_intersection(last_bezier.points[2:4], next_bezier.points[0:2])
    intersection = BezierPoint(*intersection)
    #join_bezier = CubicBezier(last_bezier.points[3], intersection, intersection, next_bezier.points[0])

    ## What if intersection is outside of join_region? Or even not near the region's centre??
    region_centre = BezierPoint(*join_region.centroid.coords[0])
    join_bezier = CubicBezier(last_bezier.points[3], region_centre, region_centre, next_bezier.points[0])

    ## Adjust derivatives at end/start of last/next bezier to have same magnitudes
    ## as join_bezier's start/end derivative (slope will already match so simply set as
    ## last_bezier.points[2] = (last_bezier.points[3] - (intersection - last_bezier.points[3]))
    ## etc...

    return (last_bezier, join_bezier, next_bezier)

#===============================================================================
#===============================================================================

class ControlPoint(object):
    def __init__(self, position: np.array, derivative: np.array):
        self.__position = position
        self.__derivative = derivative

    def __str__(self):
        return(f'CP: ({self.__position}, {self.__derivative})')

    @property
    def position(self):
        return self.__position

    @property
    def derivative(self):
        return self.__derivative

    def set_position(self, position: np.array) -> None:
        self.__position = position

    def smooth_slope(self, derivative: np.array) -> None:
        self.__derivative = 0.5*(self.__derivative + derivative)

#===============================================================================

class ControlPointList(list):
    def __init__(self, beziers=None, subdivision_parts=NUMBER_OF_BEZIER_PARTS):
        super().__init__()
        self.__subdivision_parts = subdivision_parts
        if beziers is not None:
            for bezier in beziers:
                self.append(bezier)

    def append(self, bezier):
        for bezier in split_bezier(bezier, self.__subdivision_parts):
            hermite = Bezier_to_Hermite@[[p.x, p.y] for p in bezier.points]
            if len(self) == 0:
                super().append(ControlPoint(hermite[0], hermite[1]))
            else:
                self[-1].smooth_slope(hermite[1])
            super().append(ControlPoint(hermite[3], hermite[2]))

#===============================================================================

class PathSegment(object):
    def __init__(self, start_region, connecting_path, end_region, subdivision_parts=NUMBER_OF_BEZIER_PARTS):
        self.__start_region = start_region
        self.__end_region = end_region
        if connecting_path is not None:
            bezier_segments = connecting_path.asSegments()
        else:
            ## NEED to handle line between start/end
            bezier_segments = []

        self.__control_points = ControlPointList(bezier_segments, subdivision_parts)
        if start_region is not None:
            self.__start_point = np.array(start_region.centroid.coords[0])
        elif connecting_path is not None:
            self.__start_point = point_from_bezier(0, bezier_segments[0])
        else:
            self.__start_point = None
        self.__end_region = end_region
        if end_region is not None:
            self.__end_point = np.array(end_region.centroid.coords[0])
        elif connecting_path is not None:
            self.__end_point = point_from_bezier(3, bezier_segments[-1])
        else:
            self.__end_point = None

    @property
    def start_point(self):
        return self.__start_point

    @property
    def end_point(self):
        return self.__end_point

    @property
    def control_points(self):
        return self.__control_points

#===============================================================================

class Sheath(object):
    def __init__(self, path_network: nx.Graph, path_id: str):
        self.__path_network = path_network
        self.__id = path_id
        self.__edges = None
        self.__node_geometry = None
        self.__control_points = defaultdict(list)
        self.__graphs = {}
        self.__continuous_paths = {}
        self.__scaffold_settings = {}
        self.__continuous_region_scaffolds = {}
        self.__path_beziers = defaultdict(list)

    @property
    def path_beziers(self):
        return self.__path_beziers

    def settings(self) -> dict:
    #==========================
        path_ids = list(self.__continuous_paths)
        scaffolds = [self.__continuous_region_scaffolds[i] for i in path_ids]
        coordinates = [[c.position.tolist() for c in self.__control_points[i]] for i in path_ids]
        derivatives = [[c.derivative.tolist() for c in self.__control_points[i]] for i in path_ids]
        settings = {'scaffolds': scaffolds,
                    'path_ids': path_ids,
                    'derivatives': derivatives,
                    'coordinates': coordinates}
        return settings

    def build(self, sources, targets) -> None:
    #=========================================
        log('Generating pathway scaffold layout...')
        # self.__check_for_middle_nodes()
        # self.__build_graphs()  # build a graph network for nerve sets
        self.__find_continuous_paths(sources, targets)  # find all possible paths from sources to targets
        self.__extract_components()  # get all the coordinates and derivatives
        self.__generate_2d_descriptions()

    def __find_continuous_paths(self, sources, targets) -> None:
    #===========================================================
        """
        Builds a dictionary of every possible paths from a source to target for every nerve set.
        Assumptions is that sources and targets have only 1 input/output (i.e, nodes with degree of 1). Any node with
        more than 1 degree are ignored and treated as branching/connecting node.
        """
        path_id = 1
        for source in sources:
            for target in targets:
                nodes = nx.shortest_path(self.__path_network, source=source, target=target)
                if len(nodes) >= 2 and nodes not in self.__continuous_paths.values():
                    self.__continuous_paths[f'p_{path_id}'] = nodes
                    path_id += 1

    def __extract_components(self) -> None:
    #======================================
        """
        Extracts and stores centreline components (i.e, coordinates & derivatives)
        in a dictionary for every nerve set. Each nerve set is a dict with keys
        corresponding to the keys in self.__continuous_paths.
        """
        node_geometry = self.__path_network.nodes(data='geometry')
        for path_id, path_nodes in self.__continuous_paths.items():
            # First derive the segments that connect the path's nodes
            centrelines = []
            node_regions = []
            for node_1, node_2 in pairwise(path_nodes):
                centreline = self.__get_centreline(node_1, node_2)
                if len(centrelines) > 0:
                    ##join_region = node_geometry[node_1]
                    # Join previous and current centreline in circle centred at region's centroid
                    join_region = node_geometry[node_1].centroid.buffer(2*SHEATH_WIDTH)
                    joined_beziers = join_beziers_in_region(centrelines[-1], join_region, centreline)

                    # Adjust previous centreline
                    segments = centrelines[-1].asSegments()
                    segments[-1] = joined_beziers[0]
                    centrelines[-1] = BezierPath.fromSegments(segments)

                    # Add centreline of join
                    centrelines.append(BezierPath.fromSegments(joined_beziers[1:2]))
                    node_regions.append((None, None))

                    # Adjust current centreline
                    segments = centreline.asSegments()
                    segments[0] = joined_beziers[2]
                    centreline = BezierPath.fromSegments(segments)

                centrelines.append(centreline)
                node_regions.append((node_geometry[node_1], node_geometry[node_2]))

            # Get the path segment for each centreline
            path_segments = []
            for n, centreline in enumerate(centrelines):
                regions = node_regions[n]
                path_segment = PathSegment(regions[0], centreline, regions[1],
                    subdivision_parts=(1 if regions[0] is None else NUMBER_OF_BEZIER_PARTS))
                path_segments.append(path_segment)

            # And use them to set the control points for the path's centreline sheath
            for path_segment in path_segments:
                control_points = path_segment.control_points
                if len(self.__control_points[path_id]) == 0:
                    self.__control_points[path_id].append(control_points[0])
                self.__control_points[path_id].extend(control_points[1:])

            # The sheath starts and ends at the respective node centroids
            self.__control_points[path_id][0].set_position(path_segments[0].start_point)
            self.__control_points[path_id][-1].set_position(path_segments[-1].end_point)

    def __get_centreline(self, n1: str, n2: str) -> BezierPath:
    #=========================================================
        if (n1, n2) in self.__path_network.edges:
            edge = self.__path_network.edges[n1, n2]
            bezier_path = edge.get('geometry')
            if bezier_path is not None:
                if n1 == edge.get('start-node'):
                    return bezier_path
                else:
                    segments = [bz.reversed() for bz in bezier_path.asSegments()]
                    segments.reverse()
                    return BezierPath.fromSegments(segments)
        return None

    def __generate_2d_descriptions(self) -> None:
    #============================================
        for path_id in self.__continuous_paths.keys():

            '''  Why?? Curves look nicer without this...
            self.__node_coordinates[path_id], node_derivatives, _, _, _ = sample_cubic_hermite_curves(self.__node_coordinates[path_id],
                                                                                                      self.__node_derivatives[path_id],
                                                                                                      number_of_nodes*7)  ## Why 7 ??????????
            self.__node_derivatives[path_id] = smooth_cubic_hermite_derivatives_line(self.__node_coordinates[path_id],
                                                                                     node_derivatives,
                                                                                     fix_all_directions=False,
                                                                                     fix_start_derivative=False,
                                                                                     fix_end_derivative=False,
                                                                                     fix_start_direction=False,
                                                                                     fix_end_direction=False)
            number_of_nodes = len(self.__node_coordinates[path_id])
            '''

            d1 = []
            d2 = []
            node_coords = []
            for control_point in self.__control_points[path_id]:
                x, y = control_point.position.tolist()
                dx, dy = control_point.derivative.tolist()
                if dx == 0 or dy == 0:
                    normal_width = [SHEATH_WIDTH, SHEATH_WIDTH]
                else:
                # TODO: find a way to properly adjust the normals so that the 2D nodes are created appropriately.
                # normal_left = mult(normalize([dy, -dx]),
                #                    self.__estimate_width(nerve, path_id, node_index) * 0.5)
                # normal_right = mult(normalize([-dy, dx]),
                #                     self.__estimate_width(nerve, path_id, node_index) * 0.5)
                    normal_width = mult(normalize([dy, -dx]), SHEATH_WIDTH)
                new_node1 = [x + normal_width[0], y + normal_width[1]]
                node_coords.append(new_node1)
                d1.append(set_magnitude(normal_width, magnitude(normal_width) * 1.))
                d2.append([dx, dy])
                new_node2 = [x - normal_width[0], y - normal_width[1]]
                node_coords.append(new_node2)
                d1.append(set_magnitude([-normal_width[0], -normal_width[1]], magnitude(normal_width) * 1.))
                d2.append([dx, dy])

            scaffold_settings = {
                'id': path_id,
                'node coordinates': node_coords,
                'node derivatives 1': d1,
                'node derivatives 2': d2,
                'number of elements': len(self.__control_points[path_id]) - 1
            }
            scaffold = Scaffold2dPath(scaffold_settings)
            self.__continuous_region_scaffolds[path_id] = scaffold

    # See TODO above...
    # def __estimate_width(self, nerve: str, path_id: str, node_id: int) -> float:
    #    shape = self.__continuous_paths[nerve][path_id][node_id]
    #    shape_object = self.__node_geometry[shape]
    #    scale_x = get_geo_coordinates(shape_object.centroid.x, None)[0] / shape_object.centroid.x
    #    scale_y = get_geo_coordinates(None, shape_object.centroid.y)[1] / shape_object.centroid.y
    #    shape_rough_width = shape_object.length * ((scale_x + scale_y) / 2)
    #    return shape_rough_width

#===============================================================================
