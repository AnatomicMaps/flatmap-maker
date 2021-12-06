#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2021  David Brooks
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
1. Add unique identifiers to shapes that have ``class()`` and no ``id()`` in their markup.
2. Remove ``class()`` attribute from shapes.
3. Create JSON that maps ``id`` to ``class`` for each shape.
4. Add anatomical class to JSON by looking up ``xlsx` anatomical mapping.
5. Update manifest (and ``mapmaker``) to use anatomical map in JSON (add new JSON to ``properties``??).
"""

#===============================================================================

from dataclasses import dataclass
import json

#===============================================================================

from lxml import etree

#===============================================================================

from mapmaker.sources.markup import parse_markup, properties_to_markup
from mapmaker.sources.svg.utils import adobe_decode, adobe_encode

#===============================================================================

class ClassMapper:
    def __init__(self, id_list):
        self.__ids = list(id_list)

    def id(self, class_id):
        i = 1
        while True:
            id = f'{class_id}-{i}'
            if id not in self.__ids:
                self.__ids.append(id)
                return id
            i += 1

#===============================================================================

@dataclass
class Element:
    element: etree.Element
    properties: dict

#===============================================================================

def main(svg_file):
    svg = etree.parse(svg_file)
    elements = []
    existing_ids = []
    for element in svg.findall('//*[@id]'):
        markup = adobe_decode(element.attrib['id'])
        if markup.startswith('.'):
            properties = parse_markup(markup)
            if 'error' in properties:
                print(f'Error: {properties["error"]} in markup: {markup}')
            if 'warning' in properties:
                print(f'Warning: {properties["warning"]} in markup: {markup}')
            if 'id' in properties:
                existing_ids.append(properties['id'])
            if 'class' in properties or 'id' in properties or 'path' in properties:
                elements.append(Element(element, properties))

    class_mapper = ClassMapper(existing_ids)
    id_to_class_map = {}

    for element in elements:
        properties = element.properties
        if 'path' in properties:
            path_id = properties.pop('path')
            properties['path'] = True
            if 'id' not in properties:
                properties['id'] = path_id
        if 'class' in properties:
            class_id = properties.pop('class')
            if 'id' not in properties:
                properties['id'] = class_mapper.id(class_id)
            id_to_class_map[properties['id']] = class_id
        element.element.attrib['id'] = adobe_encode(properties_to_markup(properties))

    svg.write('new-rat.svg')  ## UTF-8, XML header...
    with open('rat_mapping.json', 'w') as fd:
        fd.write(json.dumps(id_to_class_map))  ## set indent option


    # .path(XX) and no id()   -->  .path id(XX)
    # .path(XX) and id(YY)    -->  .path id(YY)


    # .class(XX) and no id()  -->  .id(XX_N) and { XX_N: XX }
    # .class(XX) and id(YY)   -->  .id(YY) and { YY: XX }

#===============================================================================

if __name__ == '__main__':
    main('../PMR/rat/whole-rat.svg')

#===============================================================================
