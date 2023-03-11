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

import json

#===============================================================================

import pandas

#===============================================================================

Records = list[dict[str, str]]
Workbook = dict[str, Records]

def record_sort(records: Records) -> Records:
#============================================
    return sorted(records, key=lambda r: ((v := list(r.values()))[0].lower(), v[1].lower()))

#===============================================================================

def read_excel(filename: str) -> Workbook:
#=========================================
    data = pandas.read_excel(filename, sheet_name=None, dtype=str, keep_default_na=False)
    return {
        name: record_sort(data[name].to_dict(orient='records'))
            for name in sorted(data.keys())
    }

def write_excel(filename: str, workbook: Workbook):
#==================================================
    with pandas.ExcelWriter(filename) as writer:        # type: ignore
        for name, records in workbook.items():
            dataframe = pandas.DataFrame.from_records(records)
            dataframe.to_excel(writer, sheet_name=name, index=False)

def read_json(filename: str) -> Workbook:
#========================================
    with open(filename) as fp:
        return json.load(fp)

def write_json(filename: str, workbook: Workbook):
#=================================================
    with open(filename, 'w') as fp:
        fp.write(json.dumps(workbook, indent=4))

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
        workbook = read_json(args.from_json)
        write_excel(args.output_file, workbook)
    else:
        workbook = read_excel(args.from_xlsx)
        write_json(args.output_file, workbook)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
