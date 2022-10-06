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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

#===============================================================================

import openpyxl
import xlsxwriter

#===============================================================================

from mapmaker.utils import log, relative_path

#===============================================================================

@dataclass
class Annotation:
    identifier: str = field(default_factory=str)
    term: str = field(default_factory=str)
    sources: set[str] = field(default_factory=set)

#===============================================================================


#===============================================================================

class AnnotationSet:
    def __init__(self, spreadsheet: str):
        if not relative_path(spreadsheet):
            if spreadsheet.startswith('file:'):
                spreadsheet = spreadsheet[5:]
            else:
                log.warning(f'Remote FC annotation at {spreadsheet} will not be updated')
        self.__spreadsheet = Path(spreadsheet)
        self.__system_labels: dict[str, Annotation] = {}
        self.__organ_system_labels: dict[str, tuple[Annotation, set[str]]] = {}
        self.__organ_ftu_labels: dict[tuple[str, str], Annotation] = {}
        self.__connectivity: list = []  ## networkx.Graph()   ???
        self.__load()

    def add_ftu(self, organ_label: str, ftu_label: str, source: str):
    #================================================================
        key = (organ_label, ftu_label)
        if key not in self.__organ_ftu_labels:
            self.__organ_ftu_labels[key] = Annotation()
        self.__organ_ftu_labels[key].sources.add(source)

    def add_organ(self, label: str, source: str, system_labels: Iterable[str]):
    #==========================================================================
        if label in self.__organ_system_labels:
            self.__organ_system_labels[label][1].update(system_labels)
        else:
            self.__organ_system_labels[label] = (Annotation(), set(system_labels))
        self.__organ_system_labels[label][0].sources.add(source)

    def add_system(self, label: str, source: str):
    #=============================================
        if label != '':
            if label not in self.__system_labels:
                self.__system_labels[label] = Annotation()
            self.__system_labels[label].sources.add(source)

    def __load(self):
    #================
        if self.__spreadsheet.exists():
            workbook = openpyxl.load_workbook(self.__spreadsheet, read_only=True)
            try:
                worksheet = workbook['OrganSystems']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ System Name'
                                 or row[1].value != 'Identifier'
                                 or row[2].value != 'Term')):
                        raise KeyError('Wrong Organ System header row')
                    elif n != 0:
                        key = row[0].value
                        if key not in self.__system_labels:
                            self.__system_labels[key] = Annotation(row[1].value, row[2].value)

                worksheet = workbook['Organs']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Organ Name'
                                 or row[1].value != 'Identifier'
                                 or row[2].value != 'Term'
                                 or row[3].value != 'Systems...')):
                        raise KeyError('Wrong Organ header row')
                    elif n != 0:
                        key = row[0].value
                        if key not in self.__organ_system_labels:
                            self.__organ_system_labels[key] = (Annotation(row[1].value, row[2].value),
                                                               set(row[3+i].value for i in range(3) if row[3+i].value is not None))

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
                        if key not in self.__organ_ftu_labels:
                            self.__organ_ftu_labels[key] = Annotation(row[2].value, row[3].value)

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
        for row, key in enumerate(sorted(self.__system_labels.keys())):
            annotation = self.__system_labels[key]
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
        for row, label in enumerate(sorted(self.__organ_system_labels.keys())):
            (annotation, system_labels) = self.__organ_system_labels[label]
            worksheet.write_string(row + 1, 0, label)
            worksheet.write_string(row + 1, 1, annotation.identifier)
            worksheet.write_string(row + 1, 2, annotation.term)
            for n, system_label in enumerate(sorted(system_labels)):
                worksheet.write_string(row + 1, n + 3, system_label)
            worksheet.write_string(row + 1, 6, ', '.join(sorted(annotation.sources)))
        last_organ_row = len(self.__organ_system_labels) + 1
        organ_lookup = f'Organs!$A$2:$A${last_organ_row}, Organs!$B$2:$B${last_organ_row}'
        worksheet.set_selection('B2')

        # FTUs are labeled features that have a (single) organ as a parent
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
        for key in sorted(self.__organ_ftu_labels.keys()):
            (organ_label, ftu_label) = key
            annotation = self.__organ_ftu_labels[key]
            worksheet.write_string(row, 0, organ_label)
            worksheet.write_string(row, 1, ftu_label)
            worksheet.write_string(row, 2, annotation.identifier)
            worksheet.write_string(row, 3, annotation.term)
            organ_id = f'_xlfn.XLOOKUP(A{row+1}, {organ_lookup})'
            worksheet.write_formula(row, 4, f'=IF(OR(C{row+1}="", {organ_id}=""), "", _xlfn.TEXTJOIN("/", TRUE, {organ_id}, C{row+1}))')
            worksheet.write_string(row, 5, ', '.join(sorted(annotation.sources)))
            row += 1
        worksheet.set_selection('C2')

        # Add connectivity as worksheet...

        workbook.close()

#===============================================================================

