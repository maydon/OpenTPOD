from .base import TFODDetector
from django.conf import settings

from logzero import logger
import os
from mako import template
import tempfile
import shutil
import pathlib

SELFMODELPATH = os.path.join(settings.TRAINMODEL_ROOT, 'modelpath')

class DetectorSelfModel(TFODDetector):
    TRAINING_PARAMETERS = {'batch_size': 2, 'num_steps': 20000}

    def __init__(self, config):
        super().__init__(config)
        # logger.info('init self detector')

    @property
    def pretrained_model_url(self):
        # logger.info('url ing')
        self.SELFMODEL = ""
        if os.path.exists(SELFMODELPATH):
            premodel = open(SELFMODELPATH, 'r')
            self.SELFMODEL = premodel.read()
            premodel.close()
        return self.SELFMODEL

    @property
    def pipeline_config_template(self):
        # logger.info('config ing')
        self.TEMPLATE = ""
        CONFIGPATH = os.path.join(self.SELFMODEL, 'pipeline.config')
        if os.path.exists(CONFIGPATH):
            f = open(CONFIGPATH, 'r')
            self.TEMPLATE = f.read()
            # logger.info('update TEMPLATE')
            f.close()
        return self.TEMPLATE

class DetectorGoogleAutoML(TFODDetector):
    TRAINING_PARAMETERS = {'project id': ""}

    def __init__(self, config):
        super().__init__(config)

    @property
    def pretrained_model_url(self):
        return None

    @property
    def pipeline_config_template(self):
        return None

    def cache_pretrained_model(self):
        # logger.info('get override')
        return

    def export(self, output_file_path, filepath):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy2(os.path.join(filepath, 'info.csv'), temp_dir)
            shutil.copytree(os.path.join(filepath, 'data'), os.path.join(temp_dir, 'data'))
            file_stem = str(pathlib.Path(output_file_path).parent
                            / pathlib.Path(output_file_path).stem)
            logger.debug(file_stem)
            shutil.make_archive(
                file_stem,
                'zip',
                temp_dir)

class DetectorPytorchClassfication(TFODDetector):
    TRAINING_PARAMETERS = {'num_epochs': 25}

    def __init__(self, config):
        super().__init__(config)

    @property
    def pretrained_model_url(self):
        return None

    @property
    def pipeline_config_template(self):
        return None

    def cache_pretrained_model(self):
        # logger.info('get override')
        return

    def export(self, output_file_path, filepath):
        logger.info('get override in export')
        with tempfile.TemporaryDirectory() as temp_dir:
            shutil.copy2(os.path.join(filepath, 'result.pth'), temp_dir)
            shutil.copy2(os.path.join(filepath, 'info.txt'), temp_dir)
            shutil.copytree(os.path.join(filepath, 'data'), os.path.join(temp_dir, 'data'))
            file_stem = str(pathlib.Path(output_file_path).parent
                            / pathlib.Path(output_file_path).stem)
            logger.debug(file_stem)
            shutil.make_archive(
                file_stem,
                'zip',
                temp_dir)
        