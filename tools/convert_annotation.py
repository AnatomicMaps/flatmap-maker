#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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
import json
from typing import Optional

#===============================================================================

import openpyxl
import openpyxl.utils.exceptions
import xlsxwriter

#===============================================================================

def fix_term(term):
    return ''.join(term.strip().split()) if term is not None else ''

#===============================================================================

@dataclass
class Feature:
    name: str
    models: Optional[str]
    label:  Optional[str]

    def __post_init__(self):
        if self.name is None:
            raise TypeError('Features must have a name')
        if self.models:
            self.models = fix_term(self.models)

    def as_dict(self):
        d = {'name': self.name}
        if self.models:
            d['models'] = self.models
        if self.label:
            d['label'] = self.label
        return d

    @classmethod
    def from_dict(cls, d):
        feature = cls.__new__(cls)
        feature.name = d['name']
        feature.models = fix_term(d.get('models', ''))
        feature.label = d.get('label', '')
        return feature

#===============================================================================

@dataclass
class FeatureWithParent(Feature):
    parents: str = field(default='')

    def __post_init__(self):
        super().__post_init__()
        if self.parents is None:
            self.parents = ''
        else:
            parents = sorted([p.strip() for p in self.parents.split(',')], key=str.lower)
            self.parents = ', '.join(parents)

    def as_dict(self) -> dict[str, str]:
        d = super().as_dict()
        if self.parents:
            d['parents'] = self.parents
        return d

    @classmethod
    def from_dict(cls, d):
        feature = cls.__new__(cls)
        feature.__init__(d['name'], d.get('models', ''), d.get('label', ''), d.get('parents', ''))
        return feature

#===============================================================================

class FeatureList(list[Feature]):

    def as_sorted_list(self) -> list[dict[str, str]]:
        return [f.as_dict() for f in sorted(self, key=lambda a: a.name.lower())]

    @classmethod
    def from_list(cls, l):
        feature_list = cls.__new__(cls)
        for d in l:
            feature_list.append(Feature.from_dict(d))
        return feature_list

#===============================================================================

class FeatureWithParentList(list[FeatureWithParent]):

    def as_sorted_list(self) -> list[dict[str, str]]:
        return [f.as_dict() for f in sorted(self, key=lambda a: (a.name.lower(), a.parents.lower()))]

    @classmethod
    def from_list(cls, l):
        feature_list = cls.__new__(cls)
        for d in l:
            feature_list.append(FeatureWithParent.from_dict(d))
        return feature_list

#===============================================================================

class Annotations:
    def __init__(self):
        self.__systems = FeatureList()
        self.__nerves = FeatureWithParentList()
        self.__vessels = FeatureList()
        self.__organs = FeatureWithParentList()
        self.__ftus = FeatureWithParentList()

    def add_system(self, system:str, models: str='', label: str=''):
        self.__systems.append(Feature(system, models, label))

    def add_nerve(self, nerve:str, organ_systems: str='', models: str='', label: str=''):
        self.__nerves.append(FeatureWithParent(nerve, models, label, organ_systems))

    def add_vessel(self, vessel:str, models: str='', label: str=''):
        self.__vessels.append(Feature(vessel, models, label))

    def add_organ(self, organ:str, systems: str='', models: str='', label: str=''):
        self.__organs.append(FeatureWithParent(organ, models, label, systems))

    def add_ftu(self, ftu:str, organ: str='', models: str='', label: str=''):
        self.__ftus.append(FeatureWithParent(ftu, models, label, organ))

    def as_dict(self):
        return {
            'systems': self.__systems.as_sorted_list(),
            'nerves': self.__nerves.as_sorted_list(),
            'vessels': self.__vessels.as_sorted_list(),
            'organs': self.__organs.as_sorted_list(),
            'ftus': self.__ftus.as_sorted_list()
        }

    @classmethod
    def from_dict(cls, d):
        annotations = cls.__new__(cls)
        annotations.__systems = FeatureList.from_list(d.get('systems', []))
        annotations.__nerves = FeatureWithParentList.from_list(d.get('nerves', []))
        annotations.__vessels = FeatureList.from_list(d.get('vessels', []))
        annotations.__organs = FeatureWithParentList.from_list(d.get('organs', []))
        annotations.__ftus = FeatureWithParentList.from_list(d.get('ftus', []))
        return annotations

#===============================================================================

class JsonAnnotator:

    @staticmethod
    def load(filename: str) -> Annotations:
        with open(filename) as fp:
            return Annotations.from_dict(json.load(fp))

    @staticmethod
    def save(filename: str, annotations: Annotations):
        with open(filename, 'w') as fp:
            fp.write(json.dumps(annotations.as_dict(), indent=4))

#===============================================================================

class XlsxAnnotator:

    @staticmethod
    def load(filename: str) -> Annotations:
        annotations = Annotations()
        try:
            workbook = openpyxl.load_workbook(filename, read_only=True, data_only=True)
            worksheet = workbook['Systems']
            for n, row in enumerate(worksheet.rows):
                if (n == 0 and (row[0].value != 'System Name'
                             or row[1].value != 'Models')):
                    raise KeyError('Wrong System header row')
                elif n != 0 and row[0].value:
                    term = fix_term(term=row[1].value)
                    annotations.add_system(row[0].value, term, row[2].value)
            worksheet = workbook['Neural']
            for n, row in enumerate(worksheet.rows):
                if (n == 0 and (row[0].value != 'Nerve Name'
                             or row[1].value != 'Organ/System'
                             or row[2].value != 'Models')):
                    raise KeyError('Wrong Nerve header row')
                elif n != 0 and row[0].value:
                    term = fix_term(term=row[2].value)
                    annotations.add_nerve(row[0].value, row[1].value, term, row[3].value)
            try:
                worksheet = workbook['Vascular']
                for n, row in enumerate(worksheet.rows):
                    if (n == 0 and (row[0].value != 'Vessel Name'
                                 or row[1].value != 'Models')):
                        raise KeyError('Wrong Vessel header row')
                    elif n != 0 and row[0].value:
                        term = fix_term(term=row[1].value)
                        annotations.add_vessel(row[0].value, term, row[2].value)
            except KeyError:
                pass
            worksheet = workbook['Organs']
            for n, row in enumerate(worksheet.rows):
                if (n == 0 and (row[0].value != 'Organ Name'
                             or row[1].value != 'Systems'
                             or row[2].value != 'Models')):
                    raise KeyError('Wrong Organ header row')
                elif n != 0 and row[0].value:
                    term = fix_term(term=row[2].value)
                    annotations.add_organ(row[0].value, row[1].value, term, row[3].value)
            worksheet = workbook['FTUs']
            for n, row in enumerate(worksheet.rows):
                if (n == 0 and (row[0].value != 'FTU Name'
                             or row[1].value != 'Organ'
                             or row[2].value != 'Model')):
                    raise KeyError('Wrong FTU header row')
                elif n != 0 and row[0].value:
                    term = fix_term(term=row[2].value)
                    annotations.add_ftu(row[0].value, row[1].value, term, row[3].value)
            workbook.close()

        except (openpyxl.utils.exceptions.InvalidFileException, KeyError):
            raise TypeError(f'{filename} is in wrong format, ignored')

        return annotations

    @staticmethod
    def save(filename: str, annotations: Annotations):
        workbook = xlsxwriter.Workbook(filename)
        workbook.set_size(1600, 1200)
        header_format = workbook.add_format({'bold': True,
                                             'align': 'left',
                                             'valign': 'top',
                                             'fg_color': '#80C080',
                                             'border': 1,
                                             })
        connected_format = workbook.add_format({'bg_color': '#FFFF00'})
        locked_name = workbook.add_format({
            'locked': True,
            'border': 1,
            'bg_color': '#EBF1DE',
            'border_color': '#C0C0C0',
            })
        unlocked = workbook.add_format({'locked': False})

        d = annotations.as_dict()

        worksheet = workbook.add_worksheet('Systems')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:A', 40, locked_name)
        worksheet.set_column('B:B', 16, unlocked)
        worksheet.set_column('C:C', 40, unlocked)
        worksheet.write_string(0, 0, 'System Name')
        worksheet.write_string(0, 1, 'Models')
        worksheet.write_string(0, 2, 'Label')
        for row, system in enumerate(d['systems']):
            worksheet.write_string(row + 1, 0, system.get('name', ''))
            worksheet.write_string(row + 1, 1, system.get('models', ''))
            worksheet.write_string(row + 1, 2, system.get('label', ''))
        worksheet.set_selection('B2')

        worksheet = workbook.add_worksheet('Neural')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:B', 40, locked_name)
        worksheet.set_column('C:C', 16, unlocked)
        worksheet.set_column('D:D', 40, unlocked)
        worksheet.write_string(0, 0, 'Nerve Name')
        worksheet.write_string(0, 1, 'Organ/System')
        worksheet.write_string(0, 2, 'Models')
        worksheet.write_string(0, 3, 'Label')
        for row, nerve in enumerate(d['nerves']):
            worksheet.write_string(row + 1, 0, nerve.get('name', ''))
            worksheet.write_string(row + 1, 1, nerve.get('parents', ''))
            worksheet.write_string(row + 1, 2, nerve.get('models', ''))
            worksheet.write_string(row + 1, 3, nerve.get('label', ''))
        worksheet.set_selection('B3')

        worksheet = workbook.add_worksheet('Vascular')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:A', 40, locked_name)
        worksheet.set_column('B:B', 16, unlocked)
        worksheet.set_column('C:C', 40, unlocked)
        worksheet.write_string(0, 0, 'Vessel Name')
        worksheet.write_string(0, 1, 'Models')
        worksheet.write_string(0, 2, 'Label')
        for row, vessel in enumerate(d['vessels']):
            worksheet.write_string(row + 1, 0, vessel.get('name', ''))
            worksheet.write_string(row + 1, 1, vessel.get('models', ''))
            worksheet.write_string(row + 1, 2, vessel.get('label', ''))
        worksheet.set_selection('B2')

        worksheet = workbook.add_worksheet('Organs')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:B', 40, locked_name)
        worksheet.set_column('C:C', 16, unlocked)
        worksheet.set_column('D:D', 40, unlocked)
        worksheet.write_string(0, 0, 'Organ Name')
        worksheet.write_string(0, 1, 'Systems')
        worksheet.write_string(0, 2, 'Models')
        worksheet.write_string(0, 3, 'Label')
        for row, organ in enumerate(d['organs']):
            worksheet.write_string(row + 1, 0, organ.get('name', ''))
            worksheet.write_string(row + 1, 1, organ.get('parents', ''))
            worksheet.write_string(row + 1, 2, organ.get('models', ''))
            worksheet.write_string(row + 1, 3, organ.get('label', ''))
        worksheet.set_selection('C3')

        # FTUs are nameed features that have a (single) organ as a parent
        worksheet = workbook.add_worksheet('FTUs')
        worksheet.protect()
        worksheet.freeze_panes(1, 0)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_row(0, 20, header_format)
        worksheet.set_column('A:B', 40, locked_name)
        worksheet.set_column('C:C', 16, unlocked)
        worksheet.set_column('D:D', 40, unlocked)
        worksheet.set_column('E:E',  4, locked_name)
        worksheet.write_string(0, 0, 'FTU Name')
        worksheet.write_string(0, 1, 'Organ')
        worksheet.write_string(0, 2, 'Model')
        worksheet.write_string(0, 3, 'Label')
        for row, ftu in enumerate(d['ftus']):
            worksheet.write_string(row + 1, 0, ftu.get('name', ''))
            worksheet.write_string(row + 1, 1, ftu.get('parents', ''))
            worksheet.write_string(row + 1, 2, ftu.get('models', ''))
            worksheet.write_string(row + 1, 3, ftu.get('label', ''))
        worksheet.set_selection('C3')

        workbook.close()

#===============================================================================

def main():
    import argparse

    args_error = 'One of either `--from-json JSON` or `--from-xlsx XLSX` must be specified'
    parser = argparse.ArgumentParser(description='Convert FC annotation between JSON and MS Excel formats', epilog=args_error)
    parser.add_argument('--from-json', metavar='JSON', help='Name of JSON file to read')
    parser.add_argument('--from-xlsx', metavar='XLSX', help='Name of Excel file to read')
    parser.add_argument('output_file', metavar='OUTPUT_FILE', help='Name of JSOMN or XLSX file to create')
    args = parser.parse_args()

    if args.from_json is not None and args.from_xlsx is not None:
        exit('Cannot convert from both JSON and XLSX at the same time...')
    elif args.from_json is None and args.from_xlsx is None:
        parser.print_usage()
        exit(args_error)

    if args.from_json is not None:
        XlsxAnnotator.save(args.output_file, JsonAnnotator.load(args.from_json))
    else:
        JsonAnnotator.save(args.output_file, XlsxAnnotator.load(args.from_xlsx))

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================

