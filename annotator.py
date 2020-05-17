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

from collections import OrderedDict

#===============================================================================

import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE

from tqdm import tqdm

#===============================================================================

from mapmaker.labels import AnatomicalMap
from mapmaker.parser import Parser
from mapmaker.properties import ExternalProperties

#===============================================================================

class Slide(object):
    def __init__(self, slide, mapping, properties):
        self._mapping = mapping
        self._properties = properties
        self._slide_id = slide.slide_id
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            self._notes = notes_slide.notes_text_frame.text.rstrip()
        else:
            self._notes = ''
        self._properties_by_id = OrderedDict()
        self._external_ids = []
        self._current_group = ['SLIDE']
        self.process_shape_list_(slide.shapes, True)

    def process_shape_list_(self, shapes, outermost):
        if outermost:
            print('Processing shape list...')
            progress_bar = tqdm(total=len(shapes),
                unit='shp', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                self._current_group.append(shape.name)
                self.process_shape_list_(shape.shapes, False)
                self._current_group.pop()
            else:
                unique_id = '{}#{}'.format(self._slide_id, shape.shape_id)
                self._properties_by_id[unique_id] = self.get_properties(shape)
            if outermost:
                progress_bar.update(1)
        if outermost:
            progress_bar.close()

    def get_properties(self, shape):
        if shape.name.startswith('.'):
            properties = Parser.shape_properties(shape.name)
            properties['name'] = shape.name
            try:
                group = self._current_group[-1]
            except IndexError:
                group = "UNKNOWN"
            properties['group'] = group
            if 'error' in properties:
                properties['error'] = ('Shape in group {} has annotation syntax error: {}'
                                       .format(group, shape.name))
            else:
                for (key, value) in properties.items():
                    if key in ['id', 'path']:
                        if value in self._external_ids:
                            properties['error'] = ('Shape in group {} has a duplicate id: {}'
                                                   .format(group, shape.name))
                        else:
                            self._external_ids.append(value)
                    if key == 'warning':
                        properties['warning'] = 'Warning in group {}: {}'.format(group, value)
                if 'class' in properties:
                    cls = properties['class']
                    if self._mapping is not None:
                        properties.update(self._mapping.properties(cls))
                    else:
                        properties['label'] = cls
                    properties.update(self._properties.properties_from_class(cls))
                if 'external-id' in properties:
                    properties.update(self._properties.properties_from_id(properties['external-id']))
            return properties
        elif shape.name.startswith('#'):
            return {'name': shape.name}
        return None

    def list(self):
        print('SLIDE: {!s:8} {}'.format(self._slide_id, self._notes))
        for id, properties in self._properties_by_id.items():
            if properties:
                print('SHAPE: {:8} {}'.format(id, properties))

#===============================================================================

class Presentation(object):
    def __init__(self, powerpoint, mapping, properties):
        self._pptx = pptx.Presentation(powerpoint)
        self._slides_by_id = OrderedDict()
        self._seen = []
        for slide in self._pptx.slides:
            self._slides_by_id[slide.slide_id] = Slide(slide, mapping, properties)

    def list(self):
        for slide in self._slides_by_id.values():
            slide.list()

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Modify annotations in Powerpoint slides.')

#    parser.add_argument('-l', '--list', action='store_true',
#                        help='list shape annotations')

    parser.add_argument('--anatomical-map',
                        help='Excel spreadsheet file for mapping shape classes to anatomical entities')
    parser.add_argument('--properties',
                        help='JSON file specifying additional properties of shapes')

    # Options `--replace`
    # specify slide
    #         shape by id/class

    #parser.add_argument('-r', '--replace', nargs=2, action='append',
    #                    help='find and replace text using ')

    parser.add_argument('powerpoint', help='Powerpoint file')

    args = parser.parse_args()


    label_database = 'labels.sqlite'

    if args.anatomical_map:
        anatomical_map = AnatomicalMap(args.anatomical_map, label_database)
    else:
        anatomical_map = None
    external_properties = ExternalProperties(args.properties)


    presentation = Presentation(args.powerpoint, anatomical_map, external_properties)

    presentation.list()
