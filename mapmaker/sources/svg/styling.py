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

import cssselect2
import tinycss2

#===============================================================================

from mapmaker.utils import log

#===============================================================================

UNIMPLEMENTED_STYLES = ['filter']

#===============================================================================

class ElementStyleDict(dict):
    def __init__(self, element, style_dict={}):
        super().__init__(style_dict)   # Copies dict
        attributes = dict(element.attrib)
        if 'style' in attributes:
            style_attribute = attributes.pop('style')
            local_style = {}
            for declaration in tinycss2.parse_declaration_list(
                style_attribute,
                skip_comments=True, skip_whitespace=True):
                local_style[declaration.lower_name] = ' '.join(
                    [t.serialize() for t in declaration.value])
            super().update(local_style)
        super().update(attributes)

#===============================================================================

class StyleMatcher(cssselect2.Matcher):
    '''Parse CSS and add rules to the matcher.'''
    def __init__(self, style_element):
        super().__init__()
        rules = tinycss2.parse_stylesheet(style_element.text
                    if style_element is not None else '',
                    skip_comments=True, skip_whitespace=True)
        for rule in rules:
            selectors = cssselect2.compile_selector_list(rule.prelude)
            declarations = [obj for obj in tinycss2.parse_declaration_list(
                                               rule.content,
                                               skip_whitespace=True)
                            if obj.type == 'declaration']
            for selector in selectors:
                self.add_selector(selector, declarations)

    def __match(self, element):
    #==========================
        styling = {}
        matches = super().match(element)
        if matches:
            for match in matches:
                specificity, order, pseudo, declarations = match
                for declaration in declarations:
                    styling[declaration.lower_name] = declaration.value
        return styling

    def element_style(self, wrapped_element, parent_style=None):
    #===========================================================
        element_style = parent_style.copy() if parent_style is not None else {}
        for key, value in self.__match(wrapped_element).items():
            if key in UNIMPLEMENTED_STYLES:
                log.warning("'{}: {}' not implemented".format(key, value))
            else:
                element_style[key] = ' '.join([t.serialize() for t in value])
        return ElementStyleDict(wrapped_element.etree_element, element_style)

#===============================================================================

def wrap_element(element) -> cssselect2.ElementWrapper:
#======================================================
    return cssselect2.ElementWrapper.from_xml_root(element)

#===============================================================================
