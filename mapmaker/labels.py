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

import csv
import os
import sqlite3

#===============================================================================

import requests

#===============================================================================

#ILX_ENDPOINT = 'http://uri.interlex.org/base/ilx_{}.json'
VOCAB_ENDPOINT = 'https://scigraph.olympiangods.org/scigraph/vocabulary/id/{}.json'

#===============================================================================

class LabelData(object):
    def __init__(self, database):
        new_db = not os.path.exists(database)
        self.__db = sqlite3.connect(database)
        self.__cursor = self.__db.cursor()
        if new_db:
            self.__cursor.execute('CREATE TABLE labels (entity text, label text)')
            self.__db.commit()

    def close(self):
        self.__db.close()

    def set_label(self, entity, label):
        self.__cursor.execute('REPLACE INTO labels(entity, label) VALUES (?, ?)', (entity, label))
        self.__db.commit()

    def get_label(self, entity):
        self.__cursor.execute('SELECT label FROM labels WHERE entity=?', (entity,))
        row = self.__cursor.fetchone()
        if row is not None:
            return row[0]
        label = entity
        if not entity.startswith('ILX:'):
            try:
                response = requests.get(VOCAB_ENDPOINT.format(entity))
                if response:
                    l = response.json().get('labels', [entity])[0]
                    label = l[0].upper() + l[1:]
                    self.set_label(entity, label)
            except:
                print("Couldn't access", VOCAB_ENDPOINT.format(entity))
        return label

#===============================================================================

class AnatomicalMap(object):
    """
    Map ``class`` identifiers in Powerpoint to anatomical entities.

    The mapping is specified in a CSV file:

        - Has a header row which **must** include columns ``Power point identifier``, ``Preferred ID``, and `UBERON``.
        - A shape's ``class`` is used as the key into the ``Power point identifier`` column to obtain a preferred anatomical identifier for the shape.
        - If no ``Preferred ID`` is defined then the UBERON identifier is used.
        - The shape's label is set from its anatomical identifier; if none was assigned then the label is set to the shape's class.
    """
    def __init__(self, mapping_file, label_database):
        self.__label_data = LabelData(label_database)
        self.__map = {}
        with open(mapping_file, newline='') as csvfile:
            header_checked = False
            rows = csv.DictReader(csvfile)
            for row in rows:
                if not header_checked:
                    if not ('Power point identifier' in row
                        and 'Preferred ID' in row
                        and 'UBERON' in row):
                        raise ValueError('Invalid anatomical mapping file')
                    header_checked = True
                pp_id = row['Power point identifier'].strip()
                preferred = row['Preferred ID']
                uberon = row['UBERON']
                if pp_id and (preferred or uberon):
                    self.__map[pp_id] = (preferred if preferred else uberon).strip()
        print(self.__map)

    def properties(self, cls):
        props = {}
        if cls in self.__map:
            props['models'] = self.__map[cls]
            props['label'] = self.__label_data.get_label(props['models'])
        else:
            props['label'] = cls
        print(cls, props)
        return props
