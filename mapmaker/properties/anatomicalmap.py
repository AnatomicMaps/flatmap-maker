#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019-21  David Brooks
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

import openpyxl

#===============================================================================

from mapmaker.utils import FilePath, log

#===============================================================================

## Also see http://ontology.neuinfo.org/trees/sparc/view/FlatMap/
## and https://github.com/SciCrunch/NIF-Ontology

class AnatomicalMap(object):
    def __init__(self, anatomical_map):
        if anatomical_map is None:
            self.__map = {}
        else:
            path = FilePath(anatomical_map)
            if path.extension in ['xls', 'xlsx']:
                self.__map = self.__load_spreadsheet(path.get_BytesIO())
            else:
                self.__map = path.get_json()
        self.__missing_terms = []

    @property
    def mapping_dict(self):
        return self.__map

    def properties(self, cls):
    #=========================
        properties = {}
        if cls in self.__map:
            term = self.__map[cls]
            if isinstance(term, dict):
                properties.update(term)
                models = properties.pop('term', '').strip()
            else:
                models = term.strip()
            if models != '':
                properties['models'] = models
            elif cls not in self.__missing_terms:
                self.__missing_terms.append(cls)
                log.warning(f'Missing ontological term for {cls}')
        return properties

    def name(self, cls):
    #===================
        if cls in self.__map:
            properties = self.__map[cls]
            if isinstance(properties, dict):
                return properties.get('name')

    def __load_spreadsheet(self, bytes):
    #===================================
        """
        Map ``class`` identifiers in Powerpoint to anatomical entities.

        The mapping is specified in an XLSX file:

            - Has a header row which **must** include columns ``Power point identifier``, ``Preferred ID``, and `UBERON``.
            - A shape's ``class`` is used as the key into the ``Power point identifier`` column to obtain a preferred anatomical identifier for the shape.
            - If no ``Preferred ID`` is defined then the UBERON identifier is used.
            - The shape's label is set from its anatomical identifier; if none was assigned then the label is set to the shape's class.
        """
        mapping = {}
        for sheet in openpyxl.load_workbook(bytes):
            col_indices = {}
            for (n, row) in enumerate(sheet.rows):
                if n == 0:
                    for cell in row:
                        if cell.value in ['Power point identifier',
                                          'Preferred ID',
                                          'UBERON ID']:
                            col_indices[cell.value] = cell.column - 1
                    if len(col_indices) < 3:
                        log.warning("Sheet '{}' doean't have a valid header row -- data ignored".format(sheet.title))
                        break
                else:
                    pp_id = row[col_indices['Power point identifier']].value
                    preferred = row[col_indices['Preferred ID']].value
                    if preferred == '-': preferred = ''

                    uberon = row[col_indices['UBERON ID']].value
                    if uberon == '-': uberon = ''

                    if pp_id and (preferred or uberon):
                        mapping[pp_id.strip()] = (preferred if preferred else uberon).strip()
        return mapping

#===============================================================================
