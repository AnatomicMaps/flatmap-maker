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

from collections import defaultdict
from typing import Optional

#===============================================================================

from mapmaker.knowledgebase.sckan import PATH_TYPE
from mapmaker.sources.shape import Shape
from mapmaker.sources.fc_powerpoint.components import is_connector
from mapmaker.sources.fc_powerpoint.components import FC_CLASS
from mapmaker.utils import log

from .json_annotations import JsonAnnotations

#===============================================================================

TermKey = str | tuple[str, str]

class Annotator:
    def __init__(self, annotation_file: str):
        self.__annotations = JsonAnnotations(annotation_file)
        self.__terms_by_keys: dict[TermKey, str] = {}
        self.__duplicate_keys: set[tuple[TermKey, str]] = set()
        for system in self.__annotations.systems:
            self.__add_term(system.term, system.name)
        for nerve in self.__annotations.nerves:
            self.__add_term(nerve.term, nerve.name, *nerve.parent_list)
        for vessels in self.__annotations.vessels:
            self.__add_term(vessels.term, vessels.name)
        for organ in self.__annotations.organs:
            self.__add_term(organ.term, organ.name, *organ.parent_list)
        for ftu in self.__annotations.ftus:
            self.__add_term(ftu.term, ftu.name, *ftu.parent_list)
        self.__create_index()

    def lookup_shape(self, shape: Shape) -> Optional[str]:
    #=====================================================
        self.__check_shape_known(shape)
        return self.__find_shape_by_names(shape)

    def save(self):
    #==============
        self.__annotations.save()

    def __add_term(self, term, *names):
    #=================================
        if term and names and names[0]:
            if len(names) > 1 and names[1]:
                self.__add_key(term, names[:2])
            else:
                self.__add_key(term, names[0])

    def __add_key(self, term, key):
    #==============================
        if (term_1 := self.__terms_by_keys.get(key)) is not None:
            if term != term_1 and (key, term) not in self.__duplicate_keys:
                self.__duplicate_keys.add((key, term))
                log.error(f'Key `{key}` maps to both {term} and {term_1} and will be ignored')
        else:
             self.__terms_by_keys[key] = term

    def __create_index(self):
    #========================
        for key, _ in self.__duplicate_keys:
            self.__terms_by_keys.pop(key, None)
        pairs = {}
        terms_by_name = defaultdict(set)
        for key, term in self.__terms_by_keys.items():
            if isinstance(key, tuple):
                pairs[tuple(reversed(key))] = term
                terms_by_name[key[0]].add(term)
                terms_by_name[key[1]].add(term)
            else:
                terms_by_name[key].add(term)
        self.__terms_by_keys.update(pairs)
        for name, terms in terms_by_name.items():
            if len(terms) == 1:
                if name not in self.__terms_by_keys:
                    self.__terms_by_keys[name] = terms.pop()
            elif name in self.__terms_by_keys:
                del self.__terms_by_keys[name]

    def __find_shape_by_names(self, shape) -> Optional[str]:
    #=======================================================
        term = None
        if shape.name and shape.parent and shape.parent.name:
            if (term := self.__terms_by_keys.get((shape.name, shape.parent.name))) is None:
                term = self.__terms_by_keys.get(shape.name)
        elif shape.name:
            term = self.__terms_by_keys.get(shape.name)
        return term

    def __check_shape_known(self, shape: Shape):
    #===========================================
        if shape.fc_class == FC_CLASS.SYSTEM:
            self.__annotations.add_system(shape.name)
        elif shape.fc_class == FC_CLASS.ORGAN:
            systems = set(parent.name for parent in shape.parents if parent.fc_class == FC_CLASS.SYSTEM)
            self.__annotations.add_organ(shape.name, systems)
        elif shape.fc_class == FC_CLASS.NEURAL:
            parent = shape.parent.name if shape.parent is not None else ''
            self.__annotations.add_nerve(shape.name, parent)
        elif shape.fc_class == FC_CLASS.VASCULAR:
            self.__annotations.add_vessel(shape.name)
        elif shape.fc_class == FC_CLASS.FTU:
            connected = False
            for child in shape.children:
                if is_connector(child) and child.fc_class == FC_CLASS.NEURAL and child.path_type != PATH_TYPE.MOTOR:
                    connected = True
                    break
            organ = shape.parent.name if shape.parent is not None else ''
            self.__annotations.add_ftu(shape.name, organ, connected)
        elif shape.fc_class != FC_CLASS.LAYER:
            shape.log_warning(f'FC class unknown: {shape}')

#===============================================================================
