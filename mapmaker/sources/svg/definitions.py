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

class DefinitionStore(object):
    def __init__(self):
        self.__definitions = {}

    def add_definition(self, element):
    #=================================
        id = element.attrib.get('id')
        if id is not None:
            self.__definitions[id] = element

    def add_definitions(self, defs_element):
    #=======================================
        for element in defs_element:
            self.add_definition(element)

    def lookup(self, id):
    #====================
        if id is not None and id.startswith('#'):
            definition = self.__definitions.get(id[1:])
            if definition is not None:
                return copy.copy(definition)

    def use(self, element):
    #======================
        id = element.attrib.get('xlink:href')
        if id is not None and id.startswith('#'):
            definition = self.__definitions.get(id[1:])
            if definition is not None:
                del element.attrib['xlink:href']
                result = copy.copy(definition)
                result.attrib.update(element.attrib)
                return result
        return None

#===============================================================================
