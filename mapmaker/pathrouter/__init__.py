#===============================================================================
#
#  Flatmap viewer and annotation tools
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

import shapely.geometry

#===============================================================================

class Route(object):
    def __init__(self, id, kind, path):
        self.__id = id
        self.__kind = kind
        self.__path = path
        self.__geometry = None
        self.__layout()

    @property
    def geometry(self):
        return self.__geometry

    @property
    def id(self):
        return self.__id

    @property
    def kind(self):
        return self.__kind

    def __layout(self):
        if (isinstance(self.__path[0], tuple)
        and isinstance(self.__path[-1], tuple)):
            self.__geometry = shapely.geometry.LineString(self.__path)
            return
        elif (isinstance(self.__path[0], tuple)
          and not isinstance(self.__path[-1], tuple)):
            lines = [ shapely.geometry.LineString([self.__path[-2], pt]) for pt in self.__path[-1] ]
            if len(self.__path) > 2:
                lines.append(shapely.geometry.LineString(self.__path[:-1]))
        elif (not isinstance(self.__path[0], tuple)
          and isinstance(self.__path[-1], tuple)):
            lines = [ shapely.geometry.LineString(pt, [self.__path[1]]) for pt in self.__path[0] ]
            if len(self.__paths) > 2:
                lines.append(shapely.geometry.LineString(self.__path[1:]))
        elif len(self.__path) > 2:
            lines = [ shapely.geometry.LineString([self.__path[-2], pt]) for pt in self.__path[-1] ]
            lines.extend([ shapely.geometry.LineString(pt, [self.__path[1]]) for pt in self.__path[0] ])
            if len(self.__path) > 3:
                lines.append(shapely.geometry.LineString(self.__path[1:-1]))
        else:
            raise ValueError("Route '{}' is ill-defined".format(self.__id))
        self.__geometry = shapely.geometry.MultiLineString(lines)

#===============================================================================

class PathRouter(object):
    def __init__(self, nerve_tracks):
        self.__nerve_tracks = nerve_tracks
        self.__routes = defaultdict(list)     # model_id: [ route ]

    def add_route(self, model_id, route_id, kind, path):
        self.__routes[model_id].append(Route(route_id, kind, path))

    def get_routes(self, model_id):
        return self.__routes[model_id]

#===============================================================================
