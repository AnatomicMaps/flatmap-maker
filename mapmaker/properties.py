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

#===============================================================================

from pathways import Pathways

#===============================================================================

class Properties(object):
    def __init__(self, properties_file):
        self.__properties_by_class = {}
        self.__properties_by_id = {}
        self.__pathways = None
        if properties_file:
            with open(properties_file) as fp:
                properties_dict = json.loads(fp.read())
                self.__set_properties(properties_dict['features'])
                self.__pathways = Pathways(properties_dict['pathways'])

    def __set_properties(self, features_list):
        for feature in features_list:
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

    @property
    def pathways(self):
        return self.__pathways

    def properties_from_class(self, cls):
        return self.__properties_by_class.get(cls, {})

    def properties_from_id(self, id):
        return self.__properties_by_id.get(id, {})

#===============================================================================
