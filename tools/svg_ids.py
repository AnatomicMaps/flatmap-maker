#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020, 2021  David Brooks
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

from lxml import etree

#===============================================================================

from mapmaker.sources.svg.utils import adobe_decode_markup

#===============================================================================

def print_ids(element, indent=0):
#================================
    id = adobe_decode_markup(element)
    if id != '': print('{}{}'.format(indent*' ', id))  # id.startswith('.') ??
    for child in element:
        print_ids(child, indent+4)


if __name__ == '__main__':
#=========================
    import sys

    if len(sys.argv) < 2:
        sys.exit('Usage: {} SVG_FILE'.format(sys.argv[0]))

    svg = etree.parse(sys.argv[1])

    print_ids(svg.getroot())

#===============================================================================
