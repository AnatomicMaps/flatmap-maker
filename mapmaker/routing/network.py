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

import beziers.path
import shapely.geometry

#===============================================================================

from mapmaker.geometry import bezier_sample
from mapmaker.settings import settings
from mapmaker.utils import log

#===============================================================================

class RouteSegment(object):
    def __init__(self, path_id, node_set, nodes_geometry, edge_geometry, path_type):
        print('Route segment {}: nodes: {}\n    geometry: {}\n    edges: {}'
            .format(path_id, node_set, nodes_geometry, edge_geometry))
        self.__id = path_id
        self.__node_set = node_set
        self.__nodes_geometry = nodes_geometry
        self.__edge_geometry = edge_geometry
        self.__path_type = path_type

    @property
    def id(self):
        return self.__id

    @property
    def node_set(self):
        return self.__node_set

    def geometry(self) -> shapely.geometry:
        """
        Returns:
            A ``LineString`` or ``MultiLineString`` object connecting the segment's nodes.
        """
        path_layout = settings.get('pathLayout', 'automatic')
        if path_layout == 'linear':
            return shapely.geometry.MultiLineString(
                [ shapely.geometry.LineString([ node.centroid for node in nodes ])
                    for nodes in self.__nodes_geometry ])
        elif path_layout == 'automatic':
            # Automatic routing magic goes in here...
            pass
        # Fallback is centreline layout
        path = beziers.path.BezierPath.fromSegments(self.__edge_geometry)
        return shapely.geometry.LineString(bezier_sample(path))

    def properties(self) -> dict:
        """
        Returns:
            Properties of the line string object connecting the segment's nodes.
        """
        return {
            'kind': self.__path_type,
            'type': 'line-dash' if self.__path_type.endswith('-post') else 'line',
            # this is were we could set flags to specify the line-end style.
            # --->   <---    |---   ---|    o---   ---o    etc...
            # See https://github.com/alantgeo/dataset-to-tileset/blob/master/index.js
            # and https://github.com/mapbox/mapbox-gl-js/issues/4096#issuecomment-303367657
        }

#===============================================================================
