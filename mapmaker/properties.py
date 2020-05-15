#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import json
import pyparsing

#===============================================================================

from parser import Parser

#===============================================================================

class ExternalProperties(object):
    def __init__(self, properties_file):
        self.__properties_by_class = {}
        self.__properties_by_id = {}
        self.__paths_by_id = {}
        self.__routes_by_id = {}

        if properties_file:
            with open(properties_file) as fp:
                properties_dict = json.loads(fp.read())

            for feature in properties_dict['features']:
                if 'class' in feature:
                    cls = feature['class']
                    properties = feature.get('properties', {})
                    if cls in self.__properties_by_class:
                        self.__properties_by_class[cls].update(properties)
                    else:
                        self.__properties_by_class[cls] = properties
                if 'id' in feature:
                    id = feature['id']
                    properties = feature.get('properties', {})
                    if id in self.__properties_by_id:
                        self.__properties_by_id[id].update(properties)
                    else:
                        self.__properties_by_id[id] = properties

            for path in properties_dict['paths']:
                path_id = path['id']
                self.__paths_by_id[path_id] = list(Parser.path_lines(path['path']))
                if 'route' in path:
                    routing = list(Parser.route_nodes(path['route']))
                    if len(routing) < 2:
                        raise ValueError('Route definition is too short for path {}'.format(path_id))
                    through_nodes = []
                    for node in routing[1:-2]:
                        through_nodes += ExternalProperties.__make_list(node)
                    self.__routes_by_id[path_id] = {
                        'start-nodes': ExternalProperties.__make_list(routing[0]),
                        'through-nodes': through_nodes,
                        'end-nodes': ExternalProperties.__make_list(routing[-1]),
                    }

    @staticmethod
    def __make_list(lst):
        return list(lst) if isinstance(lst, pyparsing.ParseResults) else [ lst ]

    def properties_from_class(self, cls):
        return self.__properties_by_class.get(cls, {})

    def properties_from_id(self, id):
        return self.__properties_by_id.get(id, {})

    def path_lines(self, path_id):
        return self.__paths_by_id.get(path_id, [])

    def route_nodes(self, path_id):
        return self.__routes_by_id.get(path_id, {
            'start-nodes': [],
            'through-nodes': [],
            'end-nodes': [],
        })

#===============================================================================
