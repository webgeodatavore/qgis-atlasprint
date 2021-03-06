"""
***************************************************************************
    QGIS Server Plugin Filters: Add a new request to print a specific atlas
    feature
    ---------------------
    Date                 : October 2017
    Copyright            : (C) 2017 by Michaël Douchin - 3Liz
    Email                : mdouchin at 3liz dot com
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

import json
import os
import tempfile
from uuid import uuid4

from pathlib import Path
from configparser import ConfigParser

from qgis.server import QgsServerFilter
from qgis.gui import QgsMapCanvas, QgsLayerTreeMapCanvasBridge
from qgis.core import Qgis, QgsProject, QgsMessageLog, QgsExpression, QgsFeatureRequest
from qgis.core import QgsPrintLayout, QgsReadWriteContext, QgsLayoutItemMap, QgsLayoutExporter
from qgis.PyQt.QtCore import QByteArray
from qgis.PyQt.QtXml import QDomDocument


class AtlasPrintFilter(QgsServerFilter):

    metadata = {}

    def __init__(self, serverIface):
        QgsMessageLog.logMessage("atlasprintFilter.init", 'atlasprint', Qgis.Info)
        super(AtlasPrintFilter, self).__init__(serverIface)

        self.serverIface = serverIface
        self.handler = None
        self.project = None
        self.debug_mode = True
        self.composer_name = None
        self.predefined_scales = [
            500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000,
            2500000, 5000000, 10000000, 25000000, 50000000, 100000000, 250000000
        ]
        self.page_name_expression = None
        self.feature_filter = None

        self.metadata = {}
        self.get_plugin_metadata()

        # QgsMessageLog.logMessage("atlasprintFilter end init", 'atlasprint', Qgis.Info)

    def get_plugin_metadata(self):
        """
        Get plugin metadata
        """
        metadata_file = Path(__file__).resolve().parent.parent / 'metadata.txt'
        if metadata_file.is_file():
            config = ConfigParser()
            config.read(str(metadata_file))
            self.metadata['name'] = config.get('general', 'name')
            self.metadata['version'] = config.get('general', 'version')

    def setJsonResponse(self, status, body):
        """
        Set response with given parameters
        """
        self.handler.clear()
        self.handler.setResponseHeader('Content-type', 'text/json')
        self.handler.setResponseHeader('Status', status)
        self.handler.appendBody(json.dumps(body).encode('utf-8'))

    def responseComplete(self):
        """
        Send new response
        """
        self.handler = self.serverIface.requestHandler()
        params = self.handler.parameterMap()

        # Check if needed params are passed
        # If not, do not change QGIS Server response
        service = params.get('SERVICE')
        if not service:
            return

        if service.lower() != 'wms':
            return

        # Check if getprintatlas request. If not, just send the response
        if 'REQUEST' not in params or params['REQUEST'].lower() not in [
            'getreport', 'getprintatlas', 'getcapabilitiesatlas']:
            return

        # Get capabilities
        if params['REQUEST'].lower() == 'getcapabilitiesatlas':
            body = {
                'status': 'success',
                'metadata': self.metadata
            }
            self.setJsonResponse('200', body)
            return

        # Check if needed params are set
        required = ['TEMPLATE', 'EXP_FILTER']

        # For QGIS a report is the same as an atlas. so we use the same calls
        if params['REQUEST'].lower() == 'getreport':
            required = ['TEMPLATE']
            params['REQUEST'] = 'GetPrintAtlas'
            # a report has no filters so we can ignore the EXP_FILTER
            params['EXP_FILTER'] = '""'

        if not all(elem in params for elem in required):
            body = {
                'status': 'fail',
                'message': 'Missing parameters: {} required.'.format(
                    ', '.join(required))
            }
            self.setJsonResponse('400', body)
            return

        self.composer_name = params['TEMPLATE']
        self.feature_filter = params['EXP_FILTER']

        # check expression
        expression = QgsExpression(self.feature_filter)
        if expression.hasParserError():
            body = {
                'status': 'fail',
                'message': 'An error occurred while parsing the given expression: %s' % expression.parserErrorString()
                }
            QgsMessageLog.logMessage('ATLAS - ERROR EXPRESSION: {}'.format(expression.parserErrorString()), 'atlasprint', Qgis.Critical)
            self.setJsonResponse('400', body)
            return

        # noinspection PyBroadException
        try:
            pdf = self.print(
                composer_name=self.composer_name,
                predefined_scales=self.predefined_scales,
                feature_filter=self.feature_filter
            )
        except Exception as e:
            pdf = None
            QgsMessageLog.logMessage('ATLAS - PDF CREATION ERROR: {}'.format(e), 'atlasprint', Qgis.Critical)

        if not pdf:
            body = {
                'status': 'fail',
                'message': 'ATLAS - Error while generating the PDF'
            }
            QgsMessageLog.logMessage("ATLAS - No PDF generated in %s" % pdf, 'atlasprint', Qgis.Critical)
            self.setJsonResponse('500', body)
            return

        # Send PDF
        self.handler.clear()
        self.handler.setResponseHeader('Content-type', 'application/pdf')
        self.handler.setResponseHeader('Status', '200')

        # noinspection PyBroadException
        try:
            with open(pdf, 'rb') as f:
                loads = f.readlines()
                ba = QByteArray(b''.join(loads))
                self.handler.appendBody(ba)
        except Exception as e:
            QgsMessageLog.logMessage('ATLAS - PDF READING ERROR: {}'.format(e), 'atlasprint', Qgis.Critical)
            body = {
                'status': 'fail',
                'message': 'Error occured while reading PDF file',
            }
            self.setJsonResponse('500', body)
        finally:
            os.remove(pdf)

        return

    def print(self, composer_name, predefined_scales,
              feature_filter, page_name_expression=None):

        project_instance = QgsProject.instance()
        layout_manager = project_instance.layoutManager()
        composer = layout_manager.layoutByName(composer_name)

        if isinstance(composer, QgsPrintLayout):
            composer = self.prepare_atlas(
                composer, predefined_scales, feature_filter, page_name_expression)

        return self.export_pdf(composer_name, composer)

    @staticmethod
    def prepare_atlas(composer, predefined_scales, feature_filter,
                      page_name_expression=None):
        if not feature_filter:
            QgsMessageLog.logMessage("atlasprint: No feature_filter provided!",
                                     'atlasprint', Qgis.Critical)
            return None

        atlas = composer.atlas()
        atlas.setEnabled(True)
        atlas_map = composer.referenceMap()
        atlas_map.setAtlasDriven(True)
        atlas_map.setAtlasScalingMode(QgsLayoutItemMap.Predefined)
        composer.reportContext().setPredefinedScales(predefined_scales)
        if page_name_expression:
            atlas.setPageNameExpression(page_name_expression)

        # Filter feature here to avoid QGIS looping through every feature when
        # doing : composition.setAtlasMode(QgsComposition.ExportAtlas)
        coverage_layer = atlas.coverageLayer()

        # Filter by FID as QGIS cannot compile expressions with $id or other
        # $ vars which leads to bad performance for big dataset
        use_fid = None
        if '$id' in feature_filter:
            import re
            ids = list(map(int, re.findall(r'\d+', feature_filter)))
            if len(ids) > 0:
                use_fid = ids[0]
        if use_fid:
            qReq = QgsFeatureRequest().setFilterFid(use_fid)
        else:
            qReq = QgsFeatureRequest().setFilterExpression(feature_filter)

        # Change feature_filter in order to improve performance
        pks = coverage_layer.dataProvider().pkAttributeIndexes()
        if use_fid and len(pks) == 1:
            pk = coverage_layer.dataProvider().fields()[pks[0]].name()
            feature_filter = '"%s" IN (%s)' % (pk, use_fid)
            QgsMessageLog.logMessage("atlasprint: feature_filter changed into: %s" % feature_filter, 'atlasprint', Qgis.Info)
            qReq = QgsFeatureRequest().setFilterExpression(feature_filter)
        atlas.setFilterFeatures(True)
        atlas.setFilterExpression(feature_filter)
        return atlas

    @staticmethod
    def export_pdf(composer_name, composer):
        # setup settings
        settings = QgsLayoutExporter.PdfExportSettings()
        export_path = os.path.join(
                tempfile.gettempdir(),
                '%s_%s.pdf' % (composer_name, uuid4())
              )
        result, error = QgsLayoutExporter.exportToPdf(
            composer,
            export_path,
            settings)

        if (result != QgsLayoutExporter.Success
                or not os.path.isfile(export_path)):
            QgsMessageLog.logMessage("atlasprint: export not generated {} "
                                     "Error: {}".format(export_path, error),
                                     'atlasprint', Qgis.Critical)
            return None

        QgsMessageLog.logMessage("atlasprint: path generated %s" % export_path, 'atlasprint', Qgis.Success)
        return export_path
