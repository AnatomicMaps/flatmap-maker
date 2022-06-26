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

import json

#===============================================================================

import openpyxl

#===============================================================================

def terms_from_spreadsheet(spreadsheet):
#=======================================
    connectivity_terms = []
    wb = openpyxl.load_workbook(spreadsheet)
    sheet = wb.worksheets[0]
    for (n, row) in enumerate(sheet.rows):
        if n == 0:
            if [row[i].value for i in range(3)] != ['SCKAN', 'Term', 'Label']:
                log.warning("Sheet '{}' doesn't have a valid header row -- data ignored".format(sheet.title))
                break
        else:
            if row[4].value is not None:
                connectivity_terms.append({
                    'id': row[1].value,
                    'name': row[2].value,
                    'aliases': [ row[n].value for n in [4, 7] if row[n].value is not None]
                })
    return connectivity_terms

def save_terms_as_json(connectivity_terms, json_file):
#=====================================================
    with open(json_file, 'w') as fp:
        fp.write(json.dumps(connectivity_terms, indent=4))
        fp.write('\n')

#===============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate a JSON file with anatomical term equivalences from a spreadsheet")
    parser.add_argument('spreadsheet', metavar='SPREADSHEET', help='Spreadsheet with equivalent anatomical terms')
    parser.add_argument('connectivity_terms', metavar='JSON_OUTPUT', help='JSON file to create')
    args = parser.parse_args()

    terms = terms_from_spreadsheet(args.spreadsheet)
    save_terms_as_json(terms, args.connectivity_terms)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
