#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

from __future__ import annotations
import json

#===============================================================================

from . import Annotation, Annotator

#===============================================================================

class JsonAnnotator(Annotator):

    def load(self):
    #==============
        if self.annotation_file.exists():
            with open(self.annotation_file, 'r') as fp:
                annotations = json.loads(fp.read())
            try:
                for system in annotations['systems']:
                    self.add_system_annotation(Annotation(identifier=system.get('id', ''),
                                                          name=system['name'],
                                                          term=system.get('term', ''),
                                                          sources=set(system.get('sources', [])))
                                              )
                for organ in annotations['organs']:
                    self.add_organ_with_systems_annotation(Annotation(identifier=organ.get('id', ''),
                                                                      name=organ['name'],
                                                                      term=organ.get('term', ''),
                                                                      sources=set(organ.get('sources', []))),
                                                           set(organ.get('systems', [])))
                for ftu in annotations['ftus']:
                    full_id = ftu.get('full-id', ftu.get('id', ''))
                    self.add_ftu_with_organ_annotation(Annotation(identifier=full_id,
                                                                  name=ftu['name'],
                                                                  term=ftu.get('term', ''),
                                                                  sources=set(ftu.get('sources', []))),
                                                       ftu['organ'])
            except (AttributeError, KeyError):
                print(f'{self.annotation_file} is in wrong format, ignored')

    def save(self):
    #==============
        annotations = {
            'systems': [ self.get_system(name).as_dict()
                            for name in sorted(self.system_names)],
            'organs': [],
            'ftus': []
        }
        for n, name in enumerate(sorted(self.organ_names)):
            (annotation, systems) = self.get_organ_with_systems(name)
            organ_dict = annotation.as_dict()
            if systems: organ_dict.update({'systems': sorted(systems)})
            annotations['organs'].append(organ_dict)
        for key in sorted(self.ftu_names_with_organ):
            ftu_dict = self.get_ftu_with_organ(*key).as_dict()
            ftu_dict['organ'] = key[0]
            if 'id' in ftu_dict:
                id = ftu_dict['id'].split('/')[-1]
                ftu_dict['id'] = id
                if (organ_id := self.get_organ_with_systems(ftu_dict['organ'])[0].identifier):
                    ftu_dict['full-id'] = f'{organ_id}/{id}'
            annotations['ftus'].append(ftu_dict)

        # Add connectivity...

        with open(self.annotation_file, 'w') as fp:
            fp.write(json.dumps(annotations, indent=4))

#===============================================================================

