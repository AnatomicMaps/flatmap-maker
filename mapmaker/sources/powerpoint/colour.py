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

import colorsys
from zipfile import ZipFile
from typing import Optional

#===============================================================================

import numpy as np

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL_TYPE, MSO_THEME_COLOR, MSO_LINE_DASH_STYLE

#===============================================================================

from .presets import DRAWINGML, ThemeDefinition

#===============================================================================

# (colour, opacity)
ColourPair = tuple[Optional[str], float]

#===============================================================================

class ColourTheme(object):
    def __init__(self, pptx_source):
        with ZipFile(pptx_source, 'r') as presentation:
            for info in presentation.infolist():
                if info.filename.startswith('ppt/theme/'):
                    self.__theme_definition = ThemeDefinition.new(presentation.read(info))
                    break

    def colour_scheme(self):
    #=======================
        return self.__theme_definition.themeElements.clrScheme

#===============================================================================

class ColourMap(object):
    def __init__(self, ppt_theme, slide):
        self.__colour_defs = {}
        for colour_def in ppt_theme.colour_scheme():
            defn = colour_def[0]
            if defn.tag == DRAWINGML('sysClr'):
                self.__colour_defs[colour_def.tag] = RGBColor.from_string(defn.attrib['lastClr'])
            elif defn.tag == DRAWINGML('srgbClr'):
                self.__colour_defs[colour_def.tag] = RGBColor.from_string(defn.val)
        # The slide's layout master can have colour aliases
        colour_map = slide.slide_layout.slide_master.element.clrMap.attrib
        for key, value in colour_map.items():
            if key != value:
                self.__colour_defs[DRAWINGML(key)] = self.__colour_defs[DRAWINGML(value)]

    def lookup(self, colour_format):
    #===============================
        if colour_format.type == MSO_COLOR_TYPE.RGB:
            rgb = colour_format.rgb
        elif colour_format.type == MSO_COLOR_TYPE.SCHEME:
            key = MSO_THEME_COLOR.to_xml(colour_format.theme_color)
            rgb = self.__colour_defs[DRAWINGML(key)]
        elif colour_format.type == MSO_COLOR_TYPE.PRESET:
            return colour_format._color._xClr.attrib['val']
        else:
            raise ValueError('Unsupported colour format: {}'.format(colour_format.type))
        lumMod = colour_format.lumMod
        lumOff = colour_format.lumOff
        satMod = colour_format.satMod
        if lumMod != 1.0 or lumOff != 0.0 or satMod != 1.0:
            hls = list(colorsys.rgb_to_hls(*(np.array(rgb)/255.0)))
            hls[1] *= lumMod
            hls[1] += lumOff
            if hls[1] > 1.0:
                hls[1] = 1.0
            hls[2] *= satMod
            if hls[2] > 1.0:
                hls[2] = 1.0
            colour = np.uint8(255*np.array(colorsys.hls_to_rgb(*hls)) + 0.5)
            rgb = RGBColor(*colour.tolist())
        tint = colour_format.tint
        if tint > 0.0:
            colour = np.array(rgb)
            tinted = np.uint8((colour + tint*(255 - colour)))
            rgb = RGBColor(*colour.tolist())
        shade = colour_format.shade
        if shade != 1.0:
            shaded = np.uint8(shade*np.array(rgb))
            rgb = RGBColor(*shaded.tolist())
        return f'#{str(rgb)}'

    def scheme_colour(self, name):
    #=============================
        key = DRAWINGML(name)
        if key in self.__colour_defs:
            return f'#{str(self.__colour_defs[key])}'

#===============================================================================
