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

#===============================================================================

class RoutedPath(object):
    def __init__(self, path_id, route_graph):
        print('Route path:', path_id, route_graph.edges)
        self.__path_id = path_id
        self.__graph = route_graph
        self.__node_set = { node
            for node, data in route_graph.nodes(data=True)
                if not data.get('exclude', False) }

    @property
    def node_set(self):
        return self.__node_set

    def geometry(self) -> shapely.geometry:
        """
        Returns:
            A ``LineString`` or ``MultiLineString`` object connecting the segment's nodes.
        """
        path_layout = settings.get('pathLayout', 'automatic')
        if True or path_layout == 'linear':
            return shapely.geometry.MultiLineString([
                        shapely.geometry.LineString([
                            self.__graph.nodes[edge[0]]['geometry'].centroid,
                            self.__graph.nodes[edge[1]]['geometry'].centroid
                        ])
                        for edge in self.__graph.edges
                    ])
        elif path_layout == 'automatic':
            # Automatic routing magic goes in here...
            pass
        # Fallback is centreline layout
        path = beziers.path.BezierPath.fromSegments(self.__edge_geometry)
        return shapely.geometry.LineString(bezier_sample(path))

#===============================================================================
