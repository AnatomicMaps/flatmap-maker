/******************************************************************************

Flatmap creation tools

Copyright (c) 2021  David Brooks

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

******************************************************************************/

/**
 *  Saves current Adobe Illustrator document as an SVG file, optimised for
 *  flatmaps.
 *
 *  Save this in Illustrator's ``Scripts`` directory to make it available
 *  under ``File/Scripts``.
 *
 *  * macOS: ``/Applications/Adobe Illustrator 2021/Presets.localized/en_US/scripts``
 *  * Windows: ``C:\Program Files\Adobe\Adobe Illustrator 2021\Presets\en_US\Scripts``
 */

//==============================================================================

// uncomment to suppress Illustrator warning dialogs
// app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;

try {
    if (app.documents.length > 0 ) {
//        $.level = 2;
//        debugger;
        var documentName = app.activeDocument.fullName;

// if name starts with 'Untitled-' then prompt for file name,
// initialising with a '.svg' extension, else just save without
// any prompting...


        //var flatmapFile = File(documentPath);
        //alert(documentPath, 'debugging...', true);

        var saveFile = documentName; //.saveDlg();
        if (saveFile != null) {
            var options = new ExportOptionsSVG();
            options.compressed = false;
            options.coordinatePrecision = 3;
            options.cssProperties = SVGCSSPropertyLocation.PRESENTATIONATTRIBUTES;
            options.documentEncoding = SVGDocumentEncoding.UTF8;
            options.DTD = SVGDTDVersion.SVG1_1;
            options.embedRasterImages = true;
            options.includeFileInfo = false;
            options.preserveEditability = false;
            app.activeDocument.exportFile(saveFile, ExportType.SVG, options);
        }
    }
    else{
        throw new Error('No document open...');
    }
}
catch(e) {
    alert(e.message, 'Script error...', true);
}

//==============================================================================
