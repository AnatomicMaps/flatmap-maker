#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023 David Brooks
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

# These match those hard coded in the viewer
#

PATH_COLOURS = {
    'cns':          '#9B1FC1',
    'intracardiac': '#F19E38',
    'para-pre':     '#3F8F4A',
    'para-post':    '#3F8F4A',
    'sensory':      '#2A62F6',
    'motor':        '#98561D',
    'somatic':      '#98561D',
    'symp-pre':     '#EA3423',
    'symp-post':    '#EA3423',
    'other':        '#888',
    'arterial':     '#F00',
    'venous':       '#2F6EBA',
    'centreline':   '#CCC',
    'error':        '#FF0'
}

#===============================================================================

def get_path_colour(kind):
    return PATH_COLOURS.get(kind, PATH_COLOURS['other'])

#===============================================================================
