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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

#===============================================================================

import openpyxl
import xlsxwriter

#===============================================================================

from mapmaker.utils import log, relative_path

#===============================================================================

try:
    @dataclass(kw_only=True)  # Requires Python 3.10
    class Annotation:
        identifier: str = field(default_factory=str)
        name: str = field(default_factory=str)
        term: str = field(default_factory=str)
        sources: set[str] = field(default_factory=set)
except TypeError:
    class Annotation:
        def __init__(self, identifier: str='', name: str='', term: str='', sources: set[str]=set()):
            self.identifier = identifier
            self.name = name
            self.term = term
            self.sources = sources

#===============================================================================

class Annotator:
    def __init__(self, spreadsheet: str):
        if not relative_path(spreadsheet):
            if spreadsheet.startswith('file:'):
                spreadsheet = spreadsheet[5:]
            else:
                log.warning(f'Remote FC annotation at {spreadsheet} will not be updated')
        self.__spreadsheet = Path(spreadsheet)
        self.__systems_by_name: dict[str, Annotation] = {}                          #! System name -> Annotation
        self.__organ_systems_by_name: dict[str, tuple[Annotation, set[str]]] = {}   #! Organ name -> (Annotation, Systems)
        self.__ftus_by_names: dict[tuple[str, str], Annotation] = {}                #! (Organ, FTU name) -> Annotation
        self.__annotations_by_id: dict[str, Annotation] = {}
        self.__connectivity: list = []  ## networkx.Graph()   ???
        self.__load()

    def find_annotation(self, identifier: str) -> Optional[Annotation]:
    #==================================================================
        return self.__annotations_by_id.get(identifier)

    def find_ftu_by_names(self, organ_name: str, ftu_name: str) -> Optional[Annotation]:
    #======================================================================================
        return self.__ftus_by_names.get((organ_name, ftu_name))

    def add_ftu(self, organ_name: str, ftu_name: str, source: str) -> Annotation:
    #==============================================================================
        if (annotation := self.find_ftu_by_names(organ_name, ftu_name)) is None:
            annotation = Annotation(name=ftu_name)
            self.__ftus_by_names[(organ_name, ftu_name)] = annotation
        annotation.sources.add(source)
        return annotation

    def add_organ(self, name: str, source: str, system_names: Iterable[str]):
    #==========================================================================
        if name in self.__organ_systems_by_name:
            self.__organ_systems_by_name[name][1].update(system_names)
        else:
            self.__organ_systems_by_name[name] = (Annotation(), set(system_names))
        self.__organ_systems_by_name[name][0].sources.add(source)

    def add_system(self, name: str, source: str):
    #=============================================
        if name != '':
            if name not in self.__systems_by_name:
                self.__systems_by_name[name] = Annotation()
            self.__systems_by_name[name].sources.add(source)

    def __add_annotation(self, annotation: Annotation):
    #==================================================
        if annotation.identifier != '':
            if annotation.identifier in self.__annotations_by_id:
                log.error(f'Duplicate identifier in FC annotation: {annotation.identifier}')
            else:
                self.__annotations_by_id[annotation.identifier] = annotation

    def __load(self):
    #================
        if self.__spreadsheet.exists():
            workbook = openpyxl.load_workbook(self.__spreadsheet, read_only=True, data_only=True)
            try:
                worksheet = workbook['OrganSystems']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ System Name'
                                 or row[1].value != 'Identifier'
                                 or row[2].value != 'Term')):
                        raise KeyError('Wrong Organ System header row')
                    elif n != 0:
                        key = row[0].value
                        if key not in self.__systems_by_name:
                            self.__systems_by_name[key] = Annotation(identifier=row[1].value,
                                                                      name=row[0].value,
                                                                      term=row[2].value)
                            self.__add_annotation(self.__systems_by_name[key])
                worksheet = workbook['Organs']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ Name'
                                 or row[1].value != 'Identifier'
                                 or row[2].value != 'Term'
                                 or row[3].value != 'Systems...')):
                        raise KeyError('Wrong Organ header row')
                    elif n != 0:
                        key = row[0].value
                        if key not in self.__organ_systems_by_name:
                            self.__organ_systems_by_name[key] = (Annotation(identifier=row[1].value,
                                                                             name=row[0].value,
                                                                             term=row[2].value),
                                                                    set(row[3+i].value for i in range(3) if row[3+i].value is not None))
                            self.__add_annotation(self.__organ_systems_by_name[key][0])
                worksheet = workbook['FTUs']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ'
                                 or row[1].value != 'FTU Name'
                                 or row[2].value != 'Identifier'
                                 or row[3].value != 'Term'
                                 or row[4].value != 'Full Identifier')):
                        raise KeyError('Wrong FTU header row')
                    elif n != 0:
                        key = (row[0].value, row[1].value)
                        if key not in self.__ftus_by_names:
                            if (full_identifier := row[4].value) in [0, '', None]:
                                full_identifier = row[2].value
                            self.__ftus_by_names[key] = Annotation(identifier=full_identifier,  ## but we want value. not formula...
                                                                    name=row[1].value,
                                                                    term=row[3].value)

                            self.__add_annotation(self.__ftus_by_names[key])
            except KeyError:
                print(f'{self.__spreadsheet} is in wrong format, ignored')
            workbook.close()

    def save(self):
    #==============
        workbook = xlsxwriter.Workbook(self.__spreadsheet)
        workbook.set_size(1600, 1200)
        header_format = workbook.add_format({'bold': True,
                                             'align': 'left',
                                             'valign': 'top',
                                             'fg_color': '#80C080',
                                             'border': 1,
                                             })
        hidden = workbook.add_format({
            'hidden': True,
            'bg_color': '#E0E0E0',
            'left': 1,
            'border': 1,
            'border_color': '#C0C0C0',
            })
        locked = workbook.add_format({
            'locked': True,
            'border': 1,
            'bg_color': '#E0E0E0',
            'border_color': '#C0C0C0',
            })
        locked_name = workbook.add_format({
            'locked': True,
            'border': 1,
            'bg_color': '#EBF1DE',
            'border_color': '#C0C0C0',
            })
        unlocked = workbook.add_format({'locked': False})

        worksheet = workbook.add_worksheet('OrganSystems')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:A', 32, locked_name)
        worksheet.set_column('B:C', 24, unlocked)
        worksheet.set_column('D:D', 40, hidden)
        worksheet.write_string(0, 0, 'Organ System Name')
        worksheet.write_string(0, 1, 'Identifier')
        worksheet.write_string(0, 2, 'Term')
        worksheet.write_string(0, 3, 'Sources...')
        for row, key in enumerate(sorted(self.__systems_by_name.keys())):
            annotation = self.__systems_by_name[key]
            worksheet.write_string(row + 1, 0, key)
            worksheet.write_string(row + 1, 1, annotation.identifier)
            worksheet.write_string(row + 1, 2, annotation.term)
            worksheet.write_string(row + 1, 3, ', '.join(sorted(annotation.sources)))
        worksheet.set_selection('B2')

        worksheet = workbook.add_worksheet('Organs')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:A', 50, locked_name)
        worksheet.set_column('B:C', 24, unlocked)
        worksheet.set_column('D:F', 32, locked)
        worksheet.set_column('G:G', 40, locked)
        worksheet.write_string(0, 0, 'Organ Name')
        worksheet.write_string(0, 1, 'Identifier')
        worksheet.write_string(0, 2, 'Term')
        worksheet.write_string(0, 3, 'Systems...')
        worksheet.write_string(0, 6, 'Sources...')
        for row, name in enumerate(sorted(self.__organ_systems_by_name.keys())):
            (annotation, system_names) = self.__organ_systems_by_name[name]
            worksheet.write_string(row + 1, 0, name)
            worksheet.write_string(row + 1, 1, annotation.identifier)
            worksheet.write_string(row + 1, 2, annotation.term)
            for n, system_name in enumerate(sorted(system_names)):
                worksheet.write_string(row + 1, n + 3, system_name)
            worksheet.write_string(row + 1, 6, ', '.join(sorted(annotation.sources)))
        last_organ_row = len(self.__organ_systems_by_name) + 1
        organ_lookup = f'Organs!$A$2:$A${last_organ_row}, Organs!$B$2:$B${last_organ_row}'
        worksheet.set_selection('B2')

        # FTUs are nameed features that have a (single) organ as a parent
        worksheet = workbook.add_worksheet('FTUs')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:A', 40, locked)
        worksheet.set_column('B:B', 32, locked_name)
        worksheet.set_column('C:D', 24, unlocked)
        worksheet.set_column('E:E', 40, hidden)
        worksheet.set_column('F:F', 40, locked)
        worksheet.write_string(0, 0, 'Organ')
        worksheet.write_string(0, 1, 'FTU Name')
        worksheet.write_string(0, 2, 'Identifier')
        worksheet.write_string(0, 3, 'Term')
        worksheet.write_string(0, 4, 'Full Identifier')
        worksheet.write_string(0, 5, 'Sources...')
        row = 1
        for key in sorted(self.__ftus_by_names.keys()):
            (organ_name, ftu_name) = key
            annotation = self.__ftus_by_names[key]
            worksheet.write_string(row, 0, organ_name)
            worksheet.write_string(row, 1, ftu_name)
            worksheet.write_string(row, 2, annotation.identifier.split('/')[-1])
            worksheet.write_string(row, 3, annotation.term)
            organ_id = f'_xlfn.XLOOKUP(A{row+1}, {organ_lookup})'
            worksheet.write_formula(row, 4, f'=IF(OR(C{row+1}="", {organ_id}=""), "", _xlfn.TEXTJOIN("/", TRUE, {organ_id}, C{row+1}))')
            worksheet.write_string(row, 5, ', '.join(sorted(annotation.sources)))
            row += 1
        worksheet.set_selection('C2')

        # Add connectivity as worksheet...

        workbook.close()

#===============================================================================

