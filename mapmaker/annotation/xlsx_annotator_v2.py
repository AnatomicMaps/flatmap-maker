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
from typing import Optional

#===============================================================================

import openpyxl

#===============================================================================

from mapmaker.utils import log

from . import Annotation, Annotator

#===============================================================================

def fix_term(term):
    return ''.join(term.strip().split()) if term is not None else ''

#===============================================================================

TermKey = str | tuple[str, str]

class XlsxAnnotatorV2(Annotator):

    def __init__(self, annotation_file: str):
        self.__terms_by_keys: dict[TermKey, str] = {}
        self.__duplicate_keys: set[tuple[TermKey, str]] = set()
        super().__init__(annotation_file)   # Calls ``load()``
        self.__build_index()

    def __add_term(self, term, *names):
    #=================================
        if term and names and names[0]:
            self.__add_key(term, names[0])
            if len(names) > 1 and names[1]:
                self.__add_key(term, names[:2])

    def __add_key(self, term, key):
    #==============================
        if (term_1 := self.__terms_by_keys.get(key)) is not None:
            if term != term_1 and (key, term) not in self.__duplicate_keys:
                self.__duplicate_keys.add((key, term))
                log.error(f'Key `{key}` maps to both {term} and {term_1} and will be ignored')
        else:
             self.__terms_by_keys[key] = term

    def __build_index(self):
    #=======================
        for key, _ in self.__duplicate_keys:
            self.__terms_by_keys.pop(key)
        pairs = {}
        for key, term in self.__terms_by_keys.items():
            if isinstance(key, tuple):
                pairs[tuple(reversed(key))] = term
        self.__terms_by_keys.update(pairs)

    def find_term_by_names(self, *names) -> Optional[str]:
    #=====================================================
        if names and names[0]:
            if ((term := self.__terms_by_keys.get(names[0])) is None
            and len(names) > 1 and names[1]):
                return self.__terms_by_keys.get(names[:2])
            return term

    def load(self):
    #==============
        if self.annotation_file.exists():
            workbook = openpyxl.load_workbook(self.annotation_file, read_only=True, data_only=True)
            try:
                worksheet = workbook['OrganSystems']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ System Name'
                                 or row[1].value != 'Model')):
                        raise KeyError('Wrong Organ System header row')
                    elif n != 0:
                        term = fix_term(term=row[1].value)
                        self.add_system_annotation(Annotation(identifier='',
                                                              name=row[0].value,
                                                              term=term
                                                              ))
                        self.__add_term(term, row[0].value)

                worksheet = workbook['OrganNerves']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Nerve System Name'
                                 or row[1].value != 'Model')):
                        raise KeyError('Wrong Organ Nerve header row')
                    elif n != 0:
                        term = fix_term(term=row[1].value)
                        self.add_nerve_annotation(Annotation(identifier='',
                                                              name=row[0].value,
                                                              term=term))
                        self.__add_term(term, row[0].value)

                worksheet = workbook['Organs']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ Name'
                                 or row[1].value != 'System'
                                 or row[2].value != 'Model')):
                        raise KeyError('Wrong Organ header row')
                    elif n != 0:
                        term = fix_term(term=row[2].value)
                        self.add_organ_with_systems_annotation(Annotation(identifier='',
                                                                          name=row[0].value,
                                                                          term=term),
                                                                set(sys.strip() for sys in row[1].value.split(',')))
                        self.__add_term(term, row[0].value)

                worksheet = workbook['FTUs']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ'
                                 or row[1].value != 'FTU Name'
                                 or row[2].value != 'Model')):
                        raise KeyError('Wrong FTU header row')
                    elif n != 0:
                        term = fix_term(term=row[2].value)
                        self.add_ftu_with_organ_annotation(Annotation(identifier='',  ## but we want value. not formula...
                                                                    name=row[1].value,
                                                                    term=term),
                                                           row[0].value)
                        self.__add_term(term, row[1].value, row[0].value)

            except KeyError:
                print(f'{self.annotation_file} is in wrong format, ignored')
            workbook.close()

    def save(self):
    #==============
        pass

#===============================================================================

