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

import copy

#===============================================================================

from .utils import XLINK_HREF

#===============================================================================

class ObjectStore(object):
    def __init__(self):
        self.__objects = {}

    def __str__(self):
        return '\n'.join(['{}: {}'.format(k, v) for k, v in self.__objects.items()])

    @staticmethod
    def __id_from_url(url_id):
        if url_id is not None:
            url_id = url_id.strip()
            if url_id[:4] == 'url(' and url_id[-1] == ')':
                id = url_id[4:-1].strip()
                if len(id) and id[0] in ['"', "'"] and id[0] == id[-1]:
                    id = id[1:-1]
                if id.startswith('#'):
                    return id[1:]
        return None

    def add(self, id, obj):
    #======================
        if id is not None:
            self.__objects[id] = obj

    def get(self, id):
    #=================
        return self.__objects.get(id)

    def get_by_url(self, url_id):
    #============================
        return self.__objects.get(ObjectStore.__id_from_url(url_id))

#===============================================================================

class DefinitionStore(ObjectStore):

    def add_definition(self, element):
    #=================================
        super().add(element.attrib.get('id'), element)

    def add_definitions(self, defs_element):
    #=======================================
        for element in defs_element:
            self.add_definition(element)

    def get_by_url(self, url_id):
    #============================
        if (definition := super().get_by_url(url_id)) is not None:
            return copy.copy(definition)

    def use(self, element):
    #======================
        id = element.attrib.get('href', element.attrib.get(XLINK_HREF))
        if id is not None and id.startswith('#'):
            definition = self.get(id[1:])
            if definition is not None:
                if 'href' in element.attrib:
                    del element.attrib['href']
                else:
                    del element.attrib[XLINK_HREF]
                result = copy.copy(definition)
                result.attrib.update(element.attrib)
                return result
        return None

#===============================================================================
