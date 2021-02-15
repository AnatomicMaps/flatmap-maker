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

class Route(object):
    def __init__(self, id, path):
        self.__id = id
        self.__geometry = None

    @property
    def geometry(self):
        return self.__geometry

    @property
    def id(self):
        return self.__id

#===============================================================================

class PathRouter(object):
    def __init__(self, nerve_tracks):
        print("Tracks:")
        for track in nerve_tracks:
            print('  ', track)
        self.__nerve_tracks = nerve_tracks
        self.__routes = defaultdict(list)     # model_id: [ route ]

    def add_route(self, model_id, route_id, path):
        print('Route:')
        print('  ', model_id, route_id, path)
        self.__routes[model_id].append(Route(route_id, path))

    def get_routes(self, model_id):
        return self.__routes[model_id]

#===============================================================================
