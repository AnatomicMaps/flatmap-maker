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

import importlib.resources

#===============================================================================

from saxonche import PySaxonProcessor

#===============================================================================

def latex(openmathml: str) -> str:
    with PySaxonProcessor(license=False) as proc:
        # Load stylesheets
        omml_proc = proc.new_xslt30_processor()
        omml2mathml = omml_proc.compile_stylesheet(
            stylesheet_file=str(importlib.resources.files('resources').joinpath('xsl/omml2mathml.xsl')))
        mathml_proc = proc.new_xslt30_processor()
        mathml_proc.set_cwd(
            str(importlib.resources.files('resources').joinpath('xsl/mathml2latex/')))
        mathml2latex = mathml_proc.compile_stylesheet(stylesheet_file='mmltex.xsl')
        # Transform OpenMath to Latex via MathML
        mathml = omml2mathml.transform_to_string(xdm_node=proc.parse_xml(xml_text=openmathml))
        latex = mathml2latex.transform_to_string(xdm_node=proc.parse_xml(xml_text=mathml))
    return latex

#===============================================================================

if __name__ == '__main__':
    omml = '''
<m:oMathPara xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <m:oMathParaPr>
    <m:jc m:val="centerGroup"/>
  </m:oMathParaPr>
  <m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
    <m:sSub>
      <m:sSubPr>
        <m:ctrlPr>
          <a:rPr lang="en-NZ" sz="600" b="1" i="1" smtClean="0">
            <a:solidFill>
              <a:schemeClr val="bg1"/>
            </a:solidFill>
            <a:latin typeface="Cambria Math" panose="02040503050406030204" pitchFamily="18" charset="0"/>
          </a:rPr>
        </m:ctrlPr>
      </m:sSubPr>
      <m:e>
        <m:r>
          <a:rPr lang="en-NZ" sz="600" b="1" i="1" smtClean="0">
            <a:solidFill>
              <a:schemeClr val="bg1"/>
            </a:solidFill>
            <a:latin typeface="Cambria Math" panose="02040503050406030204" pitchFamily="18" charset="0"/>
          </a:rPr>
          <m:t>𝑷</m:t>
        </m:r>
      </m:e>
      <m:sub>
        <m:r>
          <a:rPr lang="en-NZ" sz="600" b="1" i="1" smtClean="0">
            <a:solidFill>
              <a:schemeClr val="bg1"/>
            </a:solidFill>
            <a:latin typeface="Cambria Math" panose="02040503050406030204" pitchFamily="18" charset="0"/>
          </a:rPr>
          <m:t>𝒊</m:t>
        </m:r>
      </m:sub>
    </m:sSub>
  </m:oMath>
</m:oMathPara>
'''
    print(latex(omml))      # Expect ${𝑷}_{𝒊}$

#===============================================================================
