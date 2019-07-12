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

from pyparsing import alphanums, printables, Combine, delimitedList, Group, Keyword
from pyparsing import Optional, ParseException, Suppress, Word, ZeroOrMore

#===============================================================================

class Parser(object):
    IDENTIFIER = Word(alphanums, alphanums+':/_-.')

    TEXT = Word(printables + ' ', excludeChars='()')
    DESCRIPTION = Group(Keyword('description') + Suppress('(') + TEXT + Suppress(')'))

    TAXONOMY_ID = Combine(Keyword('NCBITaxon') + ':' + IDENTIFIER)
    DESCRIBES = Group(Keyword('describes') + Suppress('(') + TAXONOMY_ID + Suppress(')'))

    BACKGROUND_DIRECTIVE = Group(Keyword('background-for') + Suppress('(') + IDENTIFIER + Suppress(')'))
    SELECT_DIRECTIVE = Group(Keyword('not-selectable') | Keyword('selected'))

    DIRECTIVES = DESCRIPTION | DESCRIBES | SELECT_DIRECTIVE | BACKGROUND_DIRECTIVE
    DIRECTIVE = '.layer-id' + Suppress('(') + IDENTIFIER + Suppress(')') + ZeroOrMore(DIRECTIVES)

    FEATURE_ID = Combine('#' + IDENTIFIER)

    ONTOLOGY_SUFFIX = Keyword('FMA') | Keyword('ILX') | Keyword('UBERON')
    ONTOLOGY_ID = Combine(ONTOLOGY_SUFFIX + ':' + IDENTIFIER)

    MODELS_SPEC = Group(Keyword('models') + Suppress('(') + Group(delimitedList(ONTOLOGY_ID)) + Suppress(')'))

    NEURAL_NODE = Keyword('N1') | Keyword('N2') | Keyword('N3') | Keyword('N4') | Keyword('N5')
    NODE_SPEC = Group(Keyword('node') + Suppress('(') + NEURAL_NODE + Suppress(')'))

    ## Need to check at least two IDs...
    ## and that they are nodes...
    EDGE_SPEC = Group(Keyword('edge') + Suppress('(') + Group(delimitedList(FEATURE_ID)) + Suppress(')'))

    FEATURE_CLASS = NODE_SPEC | EDGE_SPEC

    ROUTING = Keyword('source') | Keyword('target') | Keyword('via')
    ROUTING_SPEC = Group(ROUTING + Suppress('(') + FEATURE_ID + Suppress(')'))

    PROPERTY_SPEC = ZeroOrMore(MODELS_SPEC | ROUTING_SPEC)

    ANNOTATION = FEATURE_ID + Optional(FEATURE_CLASS | PROPERTY_SPEC)

    @staticmethod
    def directive(s):
        result = {}
        try:
            parsed = Parser.DIRECTIVE.parseString(s, parseAll=True)
            result['id'] = parsed[1]
            result['selectable'] = True
            for directive in parsed[2:]:
                if directive[0] in ['describes', 'description', 'background-for']:
                    result[directive[0]] = directive[1]
                elif directive[0] == 'not-selectable':
                    result['selectable'] = False
                elif directive[0] == 'selected':
                    result['selected'] = True
        except ParseException:
            result['error'] = 'Syntax error in directive'
        return result

    @staticmethod
    def annotation(s):
        try:
            return Parser.ANNOTATION.parseString(s, parseAll=True)
        except ParseException:
            return tuple()

#===============================================================================
