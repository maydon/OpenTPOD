"""Dataset functions.
"""
import os
import pathlib
import re
import tempfile
from datetime import datetime
from zipfile import ZipFile

import tensorflow as tf
import numpy as np
from object_detection.protos import string_int_label_map_pb2
from google.protobuf import text_format

from cvat.apps.dataset_manager.task import export_task as cvat_export_task
import collections
import json
from logzero import logger
import shutil
from xml.dom.minidom import parse

# from helper import getXml

tf.compat.v1.enable_eager_execution()


def _cvat_get_frame_path(base_dir, frame):
    """CVAT's image directory layout.

    Specified in cvat.engine.models.py Task class
    """
    d1 = str(int(frame) // 10000)
    d2 = str(int(frame) // 100)
    path = os.path.join(base_dir, d1, d2,
                        str(frame) + '.jpg')

    return path


def dump_cvat_task_annotations(db_task, db_user, scheme, host, format_name=None):
    """Use CVAT's utilities to dump annotations for a task."""
    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')

    if format_name is None:
        if db_task.mode == 'annotation':
            format_name = "CVAT for images 1.1"
        else:
            format_name = "CVAT for video 1.1"

    output_file_path = os.path.join(
        db_task.get_task_dirname(),
        '{}.{}.{}.zip'.format(db_task.id, db_user.username, timestamp)
    )

    cvat_export_task(
        task_id=db_task.id,
        dst_file=output_file_path,
        format_name=format_name,
        server_url=scheme + host,
        save_images=True,
    )
    return output_file_path


def fix_cvat_tfrecord(cvat_tf_record_zip, output_file_path):
    """Fix cvat tfrecord to comply with TF's object detection api.
    - change label id to invalid -1: so that TF is forced to use image/object/class/text
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        with ZipFile(cvat_tf_record_zip) as cur_zip:
            cur_zip.extractall(temp_dir)

        tfrecord_files = list(pathlib.Path(temp_dir).glob('*.tfrecord'))
        tfrecord_files = [str(tfrecord_file) for tfrecord_file in tfrecord_files]
        dataset = tf.data.TFRecordDataset(tfrecord_files)
        with tf.io.TFRecordWriter(str(output_file_path)) as writer:
            for item in iter(dataset):
                example = tf.train.Example()
                example.ParseFromString(item.numpy())

                # change class label to -1. force TF to use class/text
                for i in range(len(example.features.feature['image/object/class/label'].int64_list.value)):
                    example.features.feature['image/object/class/label'].int64_list.value[i] = -1

                writer.write(example.SerializeToString())


def get_label_map_from_cvat_tfrecord_zip(cvat_tf_record_zip):
    """Extract label map from cvat tfrecord zip file.
    CVAT's tfrecord file contains:
    - label_map.pbtxt
    - *.tfrecord
    """
    labels = []
    with tempfile.TemporaryDirectory() as temp_dir:
        with ZipFile(cvat_tf_record_zip) as cur_zip:
            with cur_zip.open('label_map.pbtxt', 'r') as f:
                content = f.read().decode('utf-8')
                cur_label_map = string_int_label_map_pb2.StringIntLabelMap()
                text_format.Merge(content, cur_label_map)
                for item in cur_label_map.item:
                    if item.name not in labels:
                        labels.append(item.name)
    return labels


def dump_metadata(metadata, output_file_path):
    with open(output_file_path, 'w') as f:
        json.dump(metadata, f)


def _dump_labelmap_file(labels, output_file_path):
    """Write out labels as tensorflow object detection API's lable_map.txt.
    https://github.com/tensorflow/models/blob/master/research/object_detection/data/kitti_label_map.pbtxt

    Label id 0 is reserved for 'background', therefore this file starts with id 1.
    """
    label_ids = collections.OrderedDict((label, idx + 1)
                                        for idx, label in enumerate(labels))
    with open(output_file_path, 'w', encoding='utf-8') as f:
        for label, idx in label_ids.items():
            f.write(u'item {\n')
            f.write(u'\tid: {}\n'.format(idx))
            f.write(u"\tname: '{}'\n".format(label))
            f.write(u'}\n\n')


def dump_detector_annotations(db_detector, db_tasks, db_user, scheme, host):
    """Dump annotation data for detector training.

    Output is placed into the detector's ondisk dir.
    """
    output_dir = db_detector.get_training_data_dir()
    output_labelmap_file_path = output_dir / 'label_map.pbtxt'

    # see cvat.apps.dataset_manager.formats
    # dump_format = 'COCO 1.0'
    dump_format = 'TFRecord 1.0'

    count = 0
    labels = []
    # call cvat dump tool on each video in the trainset
    for db_task in db_tasks:
        if (str(db_task).endswith('.tfrecord')):
            filePath = os.path.abspath(db_task.get_data_dirname() + "/../.upload/" + str(db_task))
            srcPath = str(output_dir) + "/default" + str(count) + ".tfrecord"
            shutil.copy2(filePath, srcPath)
            count += 1
        elif (str(db_task).endswith('.pbtxt')):
            filePath = os.path.abspath(db_task.get_data_dirname() + "/../.upload/" + str(db_task))
            logger.info(filePath)
            with open(filePath, 'r') as f:
                content = f.read()
                # labelsForHere = []
                cur_label_map = string_int_label_map_pb2.StringIntLabelMap()
                text_format.Merge(content, cur_label_map)
                for item in cur_label_map.item:
                    if item.name not in labels:
                        logger.info(item.name)
                        labels.append(item.name)
        else:
            task_annotations_file_path = dump_cvat_task_annotations(
                    db_task, db_user, scheme, host, format_name=dump_format)

            # force label_id's to -1
            fix_cvat_tfrecord(task_annotations_file_path, output_dir / (
                os.path.splitext(
                    os.path.basename(task_annotations_file_path))[0] + '.tfrecord')
            )
            task_labels = get_label_map_from_cvat_tfrecord_zip(
                task_annotations_file_path
            )
            for label in task_labels:
                if label not in labels:
                    labels.append(label)
            os.remove(task_annotations_file_path)

    _dump_labelmap_file(labels, output_labelmap_file_path)
    split_train_eval_tfrecord(output_dir)


def getXml(xmlfile, storage_path, tasknum):
    tree = parse(xmlfile)
    root = tree.documentElement
    # print(root.nodeName)
    filename = root.getElementsByTagName('filename')[0].childNodes[0].data
    # logger.info(filename.split('_')[1])
    # logger.info(int(filename.split('_')[1]))
    filename = int(filename.split('_')[1])
    filename = str(filename) + '.jpg'
    fileinstorage = os.path.join('gs://', storage_path, 'data', tasknum, filename)
    width = float(root.getElementsByTagName('width')[0].childNodes[0].data)
    height = float(root.getElementsByTagName('height')[0].childNodes[0].data)
    obj = root.getElementsByTagName('object')
    strpre = 'UNASSIGNED' + ',' + fileinstorage + ','
    result = ""
    for i in obj:
        name = i.getElementsByTagName("name")[0].childNodes[0].data
        xmin = float(i.getElementsByTagName("xmin")[0].childNodes[0].data) / width
        ymin = float(i.getElementsByTagName("ymin")[0].childNodes[0].data) / height
        xmax = float(i.getElementsByTagName("xmax")[0].childNodes[0].data) / width
        ymax = float(i.getElementsByTagName("ymax")[0].childNodes[0].data) / height
        strafter = strpre + name + ',' + str(xmin) + ',' + str(ymin) + ',,,' + str(xmax) + ',' + str(ymax) + ',,\n'
        result += strafter

    return result


def dump_detector_annotations4google_cloud(
        db_detector,
        db_tasks,
        db_user,
        scheme,
        host):
    """Dump annotation data for detector training.
    Output is placed into the detector's ondisk dir.
    """
    output_dir = db_detector.get_dir()
    datadir = os.path.join(output_dir, 'data')
    if not os.path.exists(datadir):
        os.mkdir(datadir)
    # another type is: TFRecord ZIP 1.0, see cvat.apps.annotation
    # dump_format = 'COCO JSON 1.0'
    dump_format = 'PASCAL VOC ZIP 1.0'

    # call cvat dump tool on each video in the trainset
    result = ""
    for db_task in db_tasks:
        task_annotations_file_path_pascal = dump_cvat_task_annotations(
            db_task, db_user, scheme, host, format_name=dump_format)

        # logger.info(task_annotations_file_path_pascal)
        data = db_task.get_data_dirname()
        currdir = os.path.abspath(os.path.join(db_task.get_data_dirname(), os.pardir))
        xmlpath = os.path.join(currdir, 'xml')
        # logger.info(xmlpath)
        tasknum = os.path.basename(currdir)
        # logger.info(tasknum)
        outputfolder = os.path.join(datadir, tasknum)

        if not os.path.exists(outputfolder):
            os.mkdir(outputfolder)

        if not os.path.exists(xmlpath):
            os.mkdir(xmlpath)
        with ZipFile(task_annotations_file_path_pascal) as cur_zip:
            cur_zip.extractall(xmlpath)
        os.remove(task_annotations_file_path_pascal)
        filedir = sorted(os.listdir(xmlpath))
        
        for fp in filedir:
            # logger.info(fp)
            result += getXml(os.path.join(xmlpath, fp), db_detector.name, tasknum)

        for root, dirs, files in os.walk(data):
            if len(files) != 0:
                for i in files:
                    if i.endswith('.jpg'):
                        src = os.path.join(root, i)
                        dest = os.path.join(outputfolder, i)
                        shutil.copy2(src, dest)
            # print(root)
            # print(dirs)
            # print(sorted(files))
            # print()
        # print(result)
    writecsv = open(os.path.join(output_dir, 'info.csv'), 'w+')
    writecsv.write(result)
    writecsv.close()



def split_train_eval_tfrecord(data_dir):
    """Split tfrecord in the data_dir into train and eval sets."""
    tfrecord_files = data_dir.glob('*.tfrecord')
    tfrecord_files = [str(tfrecord_file) for tfrecord_file in tfrecord_files]
    dataset = tf.data.TFRecordDataset(tfrecord_files)
    output_train_tfrecord_file_path = str(data_dir / 'train.tfrecord')
    output_eval_tfrecord_file_path = str(data_dir / 'eval.tfrecord')

    # get train/eval item ids
    total_num = 0
    eval_percentage = 0.1
    meta_data = {
        'train_num': 0,
        'eval_num': 0
    }
    for item in iter(dataset):
        total_num += 1
    eval_ids = np.random.choice(total_num,
                                int(eval_percentage * total_num), replace=False)

    with tf.io.TFRecordWriter(output_train_tfrecord_file_path) as train_writer:
        with tf.io.TFRecordWriter(output_eval_tfrecord_file_path) as eval_writer:
            for idx, item in enumerate(iter(dataset)):
                if idx in eval_ids:
                    eval_writer.write(item.numpy())
                    meta_data['eval_num'] += 1
                else:
                    train_writer.write(item.numpy())
                    meta_data['train_num'] += 1
    dump_metadata(
        meta_data,
        data_dir / 'meta'
    )


# def prepare_coco_dataset(annotation_file_path, cvat_image_dir, output_dir):
#     """Create a on-disk coco dataset with both images and annotations.
#     """
#     from pycocotools import coco as coco_loader

#     annotation_file_path = pathlib.Path(annotation_file_path).resolve()
#     output_dir = pathlib.Path(output_dir).resolve()
#     output_dir.mkdir(parents=True, exist_ok=True)

#     # annotation file
#     annotation_file_name = 'annotation.json'
#     os.symlink(annotation_file_path, output_dir / annotation_file_name)

#     # image files
#     output_data_dir = output_dir / 'images'
#     shutil.rmtree(output_data_dir, ignore_errors=True)
#     output_data_dir.mkdir()
#     coco_dataset = coco_loader.COCO(str(annotation_file_path))
#     coco_images = coco_dataset.loadImgs(coco_dataset.getImgIds())
#     cvat_frame_id_regex = re.compile(r'\d+')
#     for coco_image in coco_images:
#         coco_file_name = coco_image['file_name']
#         # cvat uses "frame_{:06d}".format(frame) as default file name
#         # see cvat.annotations.annotation
#         cvat_frame_id = int(cvat_frame_id_regex.findall(coco_file_name)[0])
#         input_image_file_path = _cvat_get_frame_path(cvat_image_dir,
#                                                      cvat_frame_id)
#         output_image_file_path = output_data_dir / coco_file_name
#         os.symlink(input_image_file_path, output_image_file_path)
