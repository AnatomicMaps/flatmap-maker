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

    # .path(XX) and no id()   -->  .path id(XX)
    # .path(XX) and id(YY)    -->  .path id(YY)


    # .class(XX) and no id()  -->  .id(XX_N) and { XX_N: XX }
    # .class(XX) and id(YY)   -->  .id(YY) and { YY: XX }

"""

#===============================================================================

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import os

#===============================================================================

from lxml import etree

#===============================================================================

from mapmaker.properties.anatomicalmap import AnatomicalMap
from mapmaker.properties.pathways import Pathways, parse_nerves, parse_path_lines, parse_route_nodes
from mapmaker.sources.markup import parse_markup, properties_to_markup
from mapmaker.sources.svg.utils import adobe_decode, adobe_encode
from mapmaker.utils import FilePath, relative_path

#===============================================================================

class DeclassifyError(Exception):
    pass

#===============================================================================

class ClassMapper:
    def __init__(self):
        self.__ids = []

    @property
    def ids(self):
        return self.__ids

    def add_id(self, id):
        self.__ids.append(id)

    def map_id(self, class_id):
        i = 1
        while True:
            id = f'{class_id}-{i}'
            if id not in self.__ids:
                self.__ids.append(id)
                return id
            i += 1

#===============================================================================

class IdMapper:
    def __init__(self, elements_by_id, elements_by_class, mapped_ids):
        self.__elements_by_id = elements_by_id
        self.__elements_by_class = elements_by_class
        self.__mapped_ids = mapped_ids

    def map_id(self, id_or_class):
        if id_or_class in self.__elements_by_id:
            return self.__mapped_ids.get(id_or_class, id_or_class)
        elif id_or_class in self.__elements_by_class:
            class_elements = self.__elements_by_class[id_or_class]
            if len(class_elements) > 1:
                raise DeclassifyError(f'Class `{id_or_class}` has multiple elements.')
            return class_elements[0].properties['id']
        else:
            print(f'Unknown ID or class: {id_or_class}')   ### ????? <<<<<<<<<<<<<<
            return id_or_class

#===============================================================================

@dataclass
class Element:
    element: etree.Element
    properties: dict

#===============================================================================

class Declassifier:
    def __init__(self, manifest_path, output_dir):
        self.__manifest_file = FilePath(manifest_path)
        self.__manifest = self.__manifest_file.get_json()
        self.__anatomical_map = AnatomicalMap(
                                    self.__manifest_file.join_url(self.__manifest.get('anatomicalMap')))
        self.__feature_properties = defaultdict(dict)
        self.__class_properties = defaultdict(dict)
        self.__networks = []
        if 'properties' in self.__manifest:
            if not relative_path(self.__manifest['properties']):
                raise DeclassifyError('Path of `properties` must be relative.')
            properties = FilePath(self.__manifest_file.join_url(self.__manifest['properties'])).get_json()
            for property in properties.get('features', []):
                if 'id' in property:
                    self.__feature_properties[property['id']] = property.get('properties', {})
                    if 'class' in properties:
                        print(f"Property's file has both `id` and `class` -- `class` ignored: {property['id']}, {property['class']}")
                elif 'class' in property:
                    self.__class_properties[property['class']] = property.get('properties', {})
                else:
                    print(f"Property's file has unknown entry -- ignored: {property}")
            self.__networks = properties.get('networks', [])
        self.__svg_sources = []
        for source in self.__manifest.get('sources', []):
            if source.get('kind') in ['base', 'details']:
                if not relative_path(source['href']):
                    raise DeclassifyError('Paths to SVG files must be relative.')
                self.__svg_sources.append(source['href'])
        self.__connectivity = {}
        for connectivity_file in self.__manifest.get('connectivity', []):
            if not relative_path(connectivity_file):
                raise DeclassifyError('Connectivity paths must be relative.')
            connectivity = FilePath(self.__manifest_file.join_url(connectivity_file)).get_json()
            for path_dict in connectivity.get('paths', []):
                if 'path' in path_dict:
                    path_dict['path'] = list(parse_path_lines(path_dict['path']))
                if 'route' in path_dict:
                    routing = parse_route_nodes(path_dict['route'])
                    route = []
                    route.append(Pathways.make_list(routing[0]))
                    route += list(routing[1:-1])
                    route.append(Pathways.make_list(routing[-1]))
                    path_dict['route'] = route
                if 'nerves' in path_dict:
                    path_dict['nerves'] = list(parse_nerves(path_dict['nerves']))
            self.__connectivity[connectivity_file] = connectivity
        self.__output_dir = Path(output_dir)
        self.__class_mapper = ClassMapper()
        self.__elements_by_class = defaultdict(list)
        self.__elements_by_id = {}
        self.__id_to_class_map = {}
        self.__id_mapper = None
        self.__mapped_ids = {}

    def __write_json(self, filename, data):
    #======================================
        with open(self.__output_dir.joinpath(filename), 'w') as fp:
            fp.write(json.dumps(data, indent=4))

    def __process_svg(self, svg_file):
    #=================================
        svg = etree.parse(FilePath(self.__manifest_file.join_url(svg_file)).get_fp())
        elements = []
        for xml_element in svg.findall('//*[@id]'):
            # Don't rewrite IDs of gradient elements
            if xml_element.tag in ['radialGradient', 'linearGradient']:
                continue
            markup = adobe_decode(xml_element.attrib['id'])
            if markup.startswith('.'):
                properties = parse_markup(markup)
                element = Element(xml_element, properties)
                if 'error' in properties:
                    print(f'Error: {properties["error"]} in markup: {markup}')
                if 'warning' in properties:
                    print(f'Warning: {properties["warning"]} in markup: {markup}')
                #if 'path' in properties:
                #    print(f'Deprecated `path` markup ignored: {str(properties)}')
                if 'class' in properties or 'id' in properties:
                    elements.append(element)
                    if 'class' in properties:
                        self.__elements_by_class[properties['class']].append(element)
                    if 'id' in properties:
                        id = properties['id']
                        self.__class_mapper.add_id(id)
                        if id in self.__elements_by_id:
                            raise DeclassifyError(f'Duplicate ID: {id}')
                        self.__elements_by_id[id] = element
        for element in elements:
            properties = element.properties
            #if 'path' in properties:
                #path_id = properties.pop('path')
                #properties['path'] = True
                #if 'id' not in properties:
                #    properties['id'] = path_id
            if 'class' in properties:
                class_id = properties.pop('class')
                if 'id' not in properties:
                    properties['id'] = self.__class_mapper.map_id(class_id)
                self.__id_to_class_map[properties['id']] = class_id
            elif 'id' in properties:
                id = properties['id']
                anatomical_id = self.__anatomical_map.properties(id).get('models')
                if anatomical_id is not None:
                    class_id = id
                    properties['id'] = self.__class_mapper.map_id(id)
                    self.__mapped_ids[id] = properties['id']
                    self.__id_to_class_map[properties['id']] = class_id
        # Encode IDs in Adobe format
        for element in elements:
            element.element.attrib['id'] = adobe_encode(properties_to_markup(element.properties))
        # Save the updated SVG
        svg.write(str(self.__output_dir.joinpath(svg_file)), xml_declaration=True, encoding='utf-8')

    def process_svg_files(self):
    #===========================
        for svg_file in self.__svg_sources:
            self.__process_svg(svg_file)

    def __remap_connectivity(self):
    #==============================
        # All lines/routes/nerves that use the class need to now use the new id
        # forall lines/routes/nerves identifiers:
        #    if id not in id_list and id in class_list
        for connectivity in self.__connectivity.values():
            for path_dict in connectivity.get('paths', []):
                if 'path' in path_dict:
                    path_dict['path'] = [ self.__id_mapper.map_id(id) for id in path_dict['path'] ]
                if 'route' in path_dict:
                    route = []
                    route.append([ self.__id_mapper.map_id(id) for id in path_dict['route'][0] ])
                    route += [ self.__id_mapper.map_id(node) for node in path_dict['route'][1:-1] ]
                    route.append([ self.__id_mapper.map_id(id) for id in path_dict['route'][-1] ])
                    path_dict['route'] = route
                if 'nerves' in path_dict:
                    path_dict['nerves'] = [ self.__id_mapper.map_id(id) for id in path_dict['nerves'] ]

    def __remap_properties(self):
    #===========================
        for id, cls in self.__id_to_class_map.items():
            if id in self.__feature_properties:
                properties = self.__feature_properties[id]
                # Class list is space separated
                properties['class'] = ' '.join(properties.get('class', '').split() + [cls])
        for network in self.__networks:
            for centreline in network.get('centrelines', []):
                centreline['connects'] = [ self.__id_mapper.map_id(id) for id in centreline.get('connects', []) ]
                centreline['contained-in'] = [ self.__id_mapper.map_id(id) for id in centreline.get('contained-in', []) ]

    def remap_ids(self):
    #===================
        self.__id_mapper = IdMapper(self.__elements_by_id, self.__elements_by_class, self.__mapped_ids)
        self.__remap_connectivity()
        self.__remap_properties()

    def __save_connectivity(self, connectivity_file, connectivity):
    #==============================================================
        def nodes_as_string(nodes):
            if len(nodes) == 1:
                return nodes[0]
            else:
                return '(' + ', '.join(nodes) + ')'
        for path_dict in connectivity.get('paths', []):
            if 'path' in path_dict:
                path_dict['path'] = ', '.join(path_dict['path'])
            if 'route' in path_dict:
                route = []
                route.append(nodes_as_string(path_dict['route'][0]))
                route += path_dict['route'][1:-1]
                route.append(nodes_as_string(path_dict['route'][-1]))
                path_dict['route'] = ', '.join(route)
            if 'nerves' in path_dict:
                path_dict['nerves'] = ', '.join(path_dict['nerves'])
        self.__write_json(connectivity_file, connectivity)

    def save(self):
    #==============
        self.__manifest.pop('anatomicalMap')
        self.__manifest['anatomical-map'] = 'anatomical_map.json'
        self.__write_json(self.__manifest['anatomical-map'], self.__anatomical_map.mapping_dict)

        for connectivity_file, connectivity in self.__connectivity.items():
            self.__save_connectivity(connectivity_file, connectivity)

        for id, cls in self.__id_to_class_map.items():
            if (id not in self.__feature_properties
             or 'class' not in self.__feature_properties[id]):
                self.__feature_properties[id]['class'] = cls
        properties = {}
        if len(self.__class_properties):
            properties['classes'] = dict(sorted(self.__class_properties.items()))
        if len(self.__feature_properties):
            properties['features'] = dict(sorted(self.__feature_properties.items()))
        if len(self.__networks):
            properties['networks'] = self.__networks

        if 'properties' not in self.__manifest:
            self.__manifest['properties'] = 'properties.json'
        self.__write_json(self.__manifest['properties'], properties)

        self.__write_json(self.__manifest_file.filename, self.__manifest)

#===============================================================================

def declassify(manifest_path, output_dir):

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    declassifier = Declassifier(manifest_path, output_dir)
    declassifier.process_svg_files()
    declassifier.remap_ids()
    declassifier.save()

#===============================================================================

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Remove `class` markup from flatmap's SVG sources")
    parser.add_argument('manifest', metavar='MANIFEST', help='Path of flatmap manifest')
    parser.add_argument('output_dir', metavar='OUTPUT_DIR', help='Directory to save converted flatmap in')

    try:
        args = parser.parse_args()
        declassify(args.manifest, args.output_dir)
    except DeclassifyError as error:
        sys.stderr.write(f'{error}\n')
        sys.exit(1)
    sys.exit(0)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
